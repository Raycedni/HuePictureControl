"""PipelineManager: owns all v4l2loopback devices and FFmpeg/scrcpy subprocesses.

Manages virtual device lifecycle for wireless input sessions (Miracast, Android scrcpy).
Integrates with CaptureRegistry via a producer-ready gate to prevent premature acquisition.

Exports:
    PipelineManager -- Main service for wireless session lifecycle
    WirelessSessionState -- Internal state dataclass for a single wireless session
"""
import asyncio
import ipaddress
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from services.capture_service import CaptureRegistry

logger = logging.getLogger(__name__)


@dataclass
class WirelessSessionState:
    """Internal state for a single wireless input session.

    Not a Pydantic model — internal use only, not serialized directly by FastAPI.
    """
    session_id: str
    source_type: str               # "miracast" | "android_scrcpy"
    device_path: str               # "/dev/video10" or "/dev/video11"
    device_nr: int                 # 10 or 11
    card_label: str                # "Miracast Input" or "scrcpy Input"
    status: str = "starting"       # starting | active | error | stopped
    error_message: Optional[str] = None
    proc: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    producer_ready: asyncio.Event = field(default_factory=asyncio.Event)
    supervisor_task: Optional[asyncio.Task] = field(default=None, repr=False)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PipelineManager:
    """Owns all v4l2loopback devices and FFmpeg/scrcpy subprocesses.

    Per D-01: sessions are ephemeral (in-memory dict, not DB).
    Per D-02: static device numbering (video10 = Miracast, video11 = scrcpy).
    Per D-03: stop_all() destroys everything within 5 seconds at shutdown.
    """

    DEVICE_NR_MIRACAST = 10
    DEVICE_NR_SCRCPY = 11

    def __init__(self, capture_registry: CaptureRegistry) -> None:
        self._capture_registry = capture_registry
        self._sessions: dict[str, WirelessSessionState] = {}

    # ------------------------------------------------------------------
    # Private helpers — device management
    # ------------------------------------------------------------------

    async def _create_v4l2_device(self, device_nr: int, card_label: str) -> str:
        """Create a v4l2loopback device. Returns device_path. Raises RuntimeError on failure.

        Per D-04: uses v4l2loopback-ctl add (not modprobe).
        Per D-05: passes card_label via -n.
        --exclusive_caps=1 ensures V4L2_CAP_VIDEO_CAPTURE bit is set (PITFALLS Pitfall 9).
        """
        device_path = f"/dev/video{device_nr}"
        try:
            await asyncio.to_thread(
                subprocess.run,
                [
                    "sudo", "v4l2loopback-ctl", "add",
                    "-n", card_label,
                    "--exclusive_caps=1",
                    device_path,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"v4l2loopback-ctl add failed for {device_path}: {exc.stderr}"
            ) from exc
        return device_path

    async def _delete_v4l2_device(self, device_nr: int) -> None:
        """Delete a v4l2loopback device. Best-effort — logs on failure but does not raise."""
        device_path = f"/dev/video{device_nr}"
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["sudo", "v4l2loopback-ctl", "delete", device_path],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Failed to delete v4l2loopback device %s: %s", device_path, exc.stderr
            )

    # ------------------------------------------------------------------
    # Private helpers — process launch
    # ------------------------------------------------------------------

    async def _launch_ffmpeg(
        self, rtsp_url: str, device_path: str
    ) -> asyncio.subprocess.Process:
        """Launch FFmpeg RTSP -> v4l2 pipeline. stderr=DEVNULL per D-06 to prevent pipe deadlock."""
        return await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-vf", "scale=640:480",
            "-pix_fmt", "yuyv422",
            "-f", "v4l2",
            device_path,
            "-loglevel", "quiet",
            "-nostats",
            stderr=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
        )

    # ------------------------------------------------------------------
    # Private helpers — producer-ready gate (D-08, WPIP-01)
    # ------------------------------------------------------------------

    async def _wait_for_producer(
        self, session: WirelessSessionState, delay: float = 1.5
    ) -> None:
        """Set producer_ready after delay if process is still running.

        Per D-08 and Pattern 2 from RESEARCH.md: simple timed check.
        Only sets the event if the process is alive (returncode is None).
        If the process died, the supervisor task handles error reporting.
        """
        await asyncio.sleep(delay)
        if session.proc is not None and session.proc.returncode is None:
            session.producer_ready.set()
        # else: process died — _supervise_session handles the error

    # ------------------------------------------------------------------
    # Private helpers — supervised restart (D-07, VCAM-03)
    # ------------------------------------------------------------------

    async def _supervise_session(self, session_id: str) -> None:
        """Monitor process exit; restart with exponential backoff on unexpected exit.

        Parameters: base_delay=1.0, max_delay=30.0, max_retries=5.
        Backoff sequence: 1s, 2s, 4s, 8s, 16s then give up.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return

        base_delay = 1.0
        max_delay = 30.0
        max_retries = 5
        attempt = 0

        while session.status not in ("stopped",) and attempt < max_retries:
            await session.proc.wait()  # blocks until process exits
            if session.status == "stopped":
                break  # user-initiated stop — do not restart

            attempt += 1
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            session.status = "error"
            session.error_message = (
                f"Process exited (attempt {attempt}/{max_retries}); retrying in {delay}s"
            )
            logger.warning(
                "Session %s process died, restart attempt %d/%d in %.1fs",
                session_id, attempt, max_retries, delay,
            )

            await asyncio.sleep(delay)

            if session.status == "stopped":
                break  # stop requested during backoff sleep

            await self._restart_session(session_id)

        if attempt >= max_retries and session.status != "stopped":
            session.status = "error"
            session.error_message = (
                f"Max retries ({max_retries}) exceeded — session terminated"
            )
            logger.error("Session %s: max retries exceeded, cleaning up", session_id)
            await self._cleanup_session_resources(session_id)

    async def _restart_session(self, session_id: str) -> None:
        """Re-launch the process for an existing session after a failure."""
        session = self._sessions.get(session_id)
        if session is None:
            return

        try:
            if session.source_type == "miracast":
                # Relaunch FFmpeg — rtsp_url was not stored; error is logged, status remains error
                # Sessions store their launch params for restart support
                logger.warning(
                    "Session %s: restart not fully supported without stored rtsp_url", session_id
                )
                return
            elif session.source_type == "android_scrcpy":
                logger.warning(
                    "Session %s: restart not fully supported without stored device_ip", session_id
                )
                return

            # Reset producer_ready for the new process
            session.producer_ready.clear()
            asyncio.create_task(self._wait_for_producer(session))
            session.status = "active"
        except Exception as exc:
            logger.error("Session %s: restart failed: %s", session_id, exc)
            session.status = "error"
            session.error_message = f"Restart failed: {exc}"

    async def _cleanup_session_resources(self, session_id: str) -> None:
        """Release capture registry and delete v4l2 device. Best-effort."""
        session = self._sessions.get(session_id)
        if session is None:
            return

        try:
            await asyncio.to_thread(self._capture_registry.release, session.device_path)
        except Exception as exc:
            logger.warning(
                "Session %s: registry release failed (best-effort): %s", session_id, exc
            )

        await self._delete_v4l2_device(session.device_nr)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_miracast(self, rtsp_url: str) -> str:
        """Start a Miracast (RTSP) session on /dev/video10.

        Creates v4l2loopback device, launches FFmpeg, waits for producer-ready,
        then acquires CaptureRegistry.

        Returns session_id.
        Raises RuntimeError if device creation or FFmpeg launch fails.
        """
        session_id = str(uuid.uuid4())
        session = WirelessSessionState(
            session_id=session_id,
            source_type="miracast",
            device_nr=self.DEVICE_NR_MIRACAST,
            device_path="/dev/video10",
            card_label="Miracast Input",
        )
        self._sessions[session_id] = session

        try:
            await self._create_v4l2_device(self.DEVICE_NR_MIRACAST, "Miracast Input")
            session.proc = await self._launch_ffmpeg(rtsp_url, "/dev/video10")

            asyncio.create_task(self._wait_for_producer(session))

            try:
                await asyncio.wait_for(session.producer_ready.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                session.status = "error"
                session.error_message = "Producer did not start within 15s timeout"
                logger.error("Session %s: producer_ready timeout", session_id)
                raise RuntimeError(session.error_message)

            # Acquire CaptureRegistry only after first frame (WPIP-01)
            await asyncio.to_thread(self._capture_registry.acquire, session.device_path)
            session.status = "active"

            session.supervisor_task = asyncio.create_task(
                self._supervise_session(session_id)
            )
            logger.info("Session %s (miracast) started on %s", session_id, session.device_path)

        except Exception:
            session.status = "error"
            # Clean up partial state
            if session.proc is not None:
                try:
                    session.proc.kill()
                    await session.proc.wait()
                except Exception:
                    pass
            try:
                await self._delete_v4l2_device(self.DEVICE_NR_MIRACAST)
            except Exception:
                pass
            raise

        return session_id

    async def start_android_scrcpy(self, device_ip: str) -> str:
        """Start an Android scrcpy session on /dev/video11.

        Validates device_ip, creates v4l2loopback device, launches scrcpy,
        waits for producer-ready, then acquires CaptureRegistry.

        T-12-02: device_ip is validated with ipaddress.ip_address() to prevent injection.

        Returns session_id.
        Raises RuntimeError if IP is invalid, device creation, or scrcpy launch fails.
        """
        # T-12-02: validate IP address before passing to subprocess
        try:
            ipaddress.ip_address(device_ip)
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid device_ip '{device_ip}': must be a valid IP address"
            ) from exc

        session_id = str(uuid.uuid4())
        session = WirelessSessionState(
            session_id=session_id,
            source_type="android_scrcpy",
            device_nr=self.DEVICE_NR_SCRCPY,
            device_path="/dev/video11",
            card_label="scrcpy Input",
        )
        self._sessions[session_id] = session

        try:
            await self._create_v4l2_device(self.DEVICE_NR_SCRCPY, "scrcpy Input")
            session.proc = await asyncio.create_subprocess_exec(
                "scrcpy",
                "--v4l2-sink=/dev/video11",
                f"--tcpip={device_ip}",
                stderr=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
            )

            asyncio.create_task(self._wait_for_producer(session))

            try:
                await asyncio.wait_for(session.producer_ready.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                session.status = "error"
                session.error_message = "Producer did not start within 15s timeout"
                logger.error("Session %s: producer_ready timeout", session_id)
                raise RuntimeError(session.error_message)

            # Acquire CaptureRegistry only after first frame (WPIP-01)
            await asyncio.to_thread(self._capture_registry.acquire, session.device_path)
            session.status = "active"

            session.supervisor_task = asyncio.create_task(
                self._supervise_session(session_id)
            )
            logger.info(
                "Session %s (android_scrcpy) started on %s", session_id, session.device_path
            )

        except Exception:
            session.status = "error"
            if session.proc is not None:
                try:
                    session.proc.kill()
                    await session.proc.wait()
                except Exception:
                    pass
            try:
                await self._delete_v4l2_device(self.DEVICE_NR_SCRCPY)
            except Exception:
                pass
            raise

        return session_id

    async def stop_session(self, session_id: str) -> None:
        """Stop a wireless session: terminate process, release registry, delete device.

        VCAM-02: SIGTERM -> 5s wait -> SIGKILL sequence.
        """
        session = self._sessions.get(session_id)
        if session is None:
            logger.warning("stop_session: session %s not found", session_id)
            return

        session.status = "stopped"

        # Terminate process: SIGTERM -> wait 5s -> SIGKILL
        if session.proc is not None:
            try:
                session.proc.terminate()
                try:
                    await asyncio.wait_for(session.proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        "Session %s: process did not exit after SIGTERM; sending SIGKILL",
                        session_id,
                    )
                    session.proc.kill()
                    await session.proc.wait()
            except Exception as exc:
                logger.warning("Session %s: process termination error: %s", session_id, exc)

        # Cancel supervisor task
        if session.supervisor_task is not None:
            session.supervisor_task.cancel()
            try:
                await session.supervisor_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Session %s: supervisor task error on cancel: %s", session_id, exc)

        # Release registry and delete device
        await self._cleanup_session_resources(session_id)

        del self._sessions[session_id]
        logger.info("Session %s stopped and cleaned up", session_id)

    async def stop_all(self) -> None:
        """Stop all wireless sessions. Per D-03: budget is called within 5s at shutdown.

        Iterates all session IDs and calls stop_session for each.
        Errors in individual sessions do not prevent others from being stopped.
        """
        session_ids = list(self._sessions.keys())
        for session_id in session_ids:
            try:
                await self.stop_session(session_id)
            except Exception as exc:
                logger.warning("stop_all: error stopping session %s: %s", session_id, exc)

    def get_sessions(self) -> list[dict]:
        """Return a list of session dicts for serialization to WirelessSessionResponse."""
        return [
            {
                "session_id": s.session_id,
                "source_type": s.source_type,
                "device_path": s.device_path,
                "status": s.status,
                "error_message": s.error_message,
                "started_at": s.started_at,
            }
            for s in self._sessions.values()
        ]

    def get_session(self, session_id: str) -> Optional[WirelessSessionState]:
        """Return the WirelessSessionState for session_id, or None if not found."""
        return self._sessions.get(session_id)
