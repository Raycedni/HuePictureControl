"""Wireless session and capabilities REST endpoints.

Exports:
    router -- APIRouter for /api/wireless prefix
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from models.wireless import (
    CapabilitiesResponse,
    NicCapability,
    ScrcpyStartRequest,
    SessionsResponse,
    ToolInfo,
    WirelessSessionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wireless", tags=["wireless"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _check_tool(cmd: list[str]) -> tuple[bool, str]:
    """Return (available, version_string). Returns (False, '') on any error."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        output = (stdout + stderr).decode("utf-8", errors="replace")
        version_line = output.split("\n")[0][:100] if output.strip() else ""
        return True, version_line
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return False, ""


async def _check_nic_p2p() -> NicCapability:
    """Check if NIC supports WiFi Direct P2P mode by parsing iw list output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "iw", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        text = stdout.decode("utf-8", errors="replace")
        p2p_supported = "P2P-GO" in text and "P2P-client" in text
        return NicCapability(p2p_supported=p2p_supported)
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return NicCapability(p2p_supported=False)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities() -> CapabilitiesResponse:
    """Report installed tool versions and NIC P2P capability."""
    ffmpeg_ok, ffmpeg_ver = await _check_tool(["ffmpeg", "-version"])
    scrcpy_ok, scrcpy_ver = await _check_tool(["scrcpy", "--version"])
    adb_ok, adb_ver = await _check_tool(["adb", "version"])
    iw_ok, iw_ver = await _check_tool(["iw", "--version"])

    nic = await _check_nic_p2p()

    miracast_ready = ffmpeg_ok and nic.p2p_supported
    scrcpy_ready = scrcpy_ok and adb_ok

    return CapabilitiesResponse(
        ffmpeg=ToolInfo(available=ffmpeg_ok, version=ffmpeg_ver),
        scrcpy=ToolInfo(available=scrcpy_ok, version=scrcpy_ver),
        adb=ToolInfo(available=adb_ok, version=adb_ver),
        iw=ToolInfo(available=iw_ok, version=iw_ver),
        nic=nic,
        ready=miracast_ready or scrcpy_ready,
        miracast_ready=miracast_ready,
        scrcpy_ready=scrcpy_ready,
    )


@router.get("/sessions", response_model=SessionsResponse)
async def list_sessions(request: Request) -> SessionsResponse:
    """List all active wireless sessions with status."""
    pipeline_manager = request.app.state.pipeline_manager
    raw_sessions = pipeline_manager.get_sessions()
    sessions = [WirelessSessionResponse(**s) for s in raw_sessions]
    return SessionsResponse(sessions=sessions)


@router.post("/scrcpy", status_code=200)
async def start_scrcpy(
    body: ScrcpyStartRequest, request: Request
) -> WirelessSessionResponse:
    """Start an Android scrcpy session. Blocks until producer-ready (~15s max).

    Per D-05: synchronous -- returns 200 with session info on success,
    or 422 with error_code on failure.
    Per D-06: accepts {"device_ip": "..."} in body.
    """
    pipeline_manager = request.app.state.pipeline_manager
    try:
        session_id = await pipeline_manager.start_android_scrcpy(body.device_ip, body.device_port)
    except RuntimeError as exc:
        # Retrieve the session to get structured error_code (D-04)
        session = pipeline_manager.get_session_by_ip(body.device_ip)
        error_code = session.error_code if session else "unknown"
        raise HTTPException(status_code=422, detail={
            "error_code": error_code,
            "message": str(exc),
        })
    session = pipeline_manager.get_session(session_id)
    return WirelessSessionResponse(
        session_id=session.session_id,
        source_type=session.source_type,
        device_path=session.device_path,
        status=session.status,
        error_message=session.error_message,
        error_code=session.error_code,
        started_at=session.started_at,
    )


@router.delete("/scrcpy/{session_id}", status_code=204)
async def stop_scrcpy(session_id: str, request: Request) -> None:
    """Stop a scrcpy session: kill scrcpy, disconnect ADB, destroy device.

    Per D-07: kills scrcpy, runs adb disconnect, destroys v4l2 device.
    Returns 404 if session_id not found.
    """
    pipeline_manager = request.app.state.pipeline_manager
    if pipeline_manager.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await pipeline_manager.stop_session(session_id)
