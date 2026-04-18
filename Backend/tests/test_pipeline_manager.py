"""Tests for Backend/services/pipeline_manager.py.

All subprocess calls are mocked — tests run on Windows and Linux CI
where v4l2loopback-ctl, ffmpeg, scrcpy are not available.
"""
import asyncio
import subprocess
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.pipeline_manager import PipelineManager, WirelessSessionState
from services.capture_service import CaptureRegistry


@pytest.fixture
def mock_registry():
    """Mock CaptureRegistry with acquire/release as synchronous mocks."""
    registry = MagicMock(spec=CaptureRegistry)
    registry.acquire = MagicMock(return_value=MagicMock())
    registry.release = MagicMock()
    return registry


@pytest.fixture
def pm(mock_registry):
    """PipelineManager instance with mocked CaptureRegistry."""
    return PipelineManager(capture_registry=mock_registry)


def _make_mock_process(returncode=None):
    """Create a mock asyncio.subprocess.Process."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=returncode or 0)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# TestDeviceCreation (VCAM-01)
# ---------------------------------------------------------------------------


class TestDeviceCreation:
    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_create_v4l2_device_correct_args(self, mock_to_thread, pm):
        mock_to_thread.return_value = MagicMock()
        result = await pm._create_v4l2_device(10, "Miracast Input")

        assert result == "/dev/video10"
        mock_to_thread.assert_called_once()
        call_args = mock_to_thread.call_args
        assert call_args[0][0] is subprocess.run
        cmd_list = call_args[0][1]
        assert "sudo" in cmd_list
        assert "v4l2loopback-ctl" in cmd_list
        assert "add" in cmd_list
        assert "-n" in cmd_list
        assert "Miracast Input" in cmd_list
        assert "--exclusive_caps=1" in cmd_list
        assert "/dev/video10" in cmd_list

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_create_v4l2_device_failure_raises(self, mock_to_thread, pm):
        mock_to_thread.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr="permission denied"
        )
        with pytest.raises(RuntimeError, match="v4l2loopback-ctl add failed"):
            await pm._create_v4l2_device(10, "Test")


# ---------------------------------------------------------------------------
# TestDeviceDeletion (VCAM-02)
# ---------------------------------------------------------------------------


class TestDeviceDeletion:
    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_delete_v4l2_device_calls_ctl_delete(self, mock_to_thread, pm):
        await pm._delete_v4l2_device(10)
        mock_to_thread.assert_called_once()
        call_args = mock_to_thread.call_args
        cmd_list = call_args[0][1]
        assert "delete" in cmd_list
        assert "/dev/video10" in cmd_list

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_delete_v4l2_device_failure_does_not_raise(self, mock_to_thread, pm):
        mock_to_thread.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr="not found"
        )
        # Should not raise — best-effort deletion
        await pm._delete_v4l2_device(10)


# ---------------------------------------------------------------------------
# TestProducerReadyGate (WPIP-01, WPIP-03)
# ---------------------------------------------------------------------------


class TestProducerReadyGate:
    @pytest.mark.asyncio
    async def test_producer_ready_sets_event_when_alive(self, pm):
        session = WirelessSessionState(
            session_id="test",
            source_type="miracast",
            device_path="/dev/video10",
            device_nr=10,
            card_label="Test",
        )
        session.proc = _make_mock_process(returncode=None)
        await pm._wait_for_producer(session, delay=0.01)
        assert session.producer_ready.is_set()

    @pytest.mark.asyncio
    async def test_producer_ready_not_set_when_dead(self, pm):
        session = WirelessSessionState(
            session_id="test",
            source_type="miracast",
            device_path="/dev/video10",
            device_nr=10,
            card_label="Test",
        )
        session.proc = _make_mock_process(returncode=1)
        await pm._wait_for_producer(session, delay=0.01)
        assert not session.producer_ready.is_set()


# ---------------------------------------------------------------------------
# TestSessionStart (WPIP-02)
# ---------------------------------------------------------------------------


class TestSessionStart:
    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_start_miracast_creates_device_and_launches(
        self, mock_to_thread, mock_exec, pm
    ):
        mock_proc = _make_mock_process(returncode=None)
        mock_exec.return_value = mock_proc
        # Make to_thread pass through for acquire, return None for subprocess.run
        mock_to_thread.return_value = MagicMock()

        # Patch _wait_for_producer to immediately set the event
        async def fake_wait(session, delay=1.5):
            session.producer_ready.set()

        with patch.object(pm, "_wait_for_producer", side_effect=fake_wait):
            session_id = await pm.start_miracast("rtsp://192.168.1.100:554")

        assert session_id
        session = pm.get_session(session_id)
        assert session is not None
        assert session.status == "active"
        assert session.source_type == "miracast"
        assert session.device_path == "/dev/video10"

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_start_android_scrcpy_validates_ip(self, mock_to_thread, mock_exec, pm):
        with pytest.raises(RuntimeError, match="Invalid device_ip"):
            await pm.start_android_scrcpy("not-an-ip")

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_start_android_scrcpy_creates_session(
        self, mock_to_thread, mock_exec, pm
    ):
        mock_proc = _make_mock_process(returncode=None)
        mock_exec.return_value = mock_proc
        mock_to_thread.return_value = MagicMock()

        async def fake_wait(session, delay=1.5):
            session.producer_ready.set()

        async def fake_adb_connect(device_ip, device_port=5555):
            return True, None

        with patch.object(pm, "_wait_for_producer", side_effect=fake_wait), \
             patch.object(pm, "_run_adb_connect", side_effect=fake_adb_connect):
            session_id = await pm.start_android_scrcpy("192.168.1.50")

        session = pm.get_session(session_id)
        assert session is not None
        assert session.source_type == "android_scrcpy"
        assert session.device_path == "/dev/video11"
        assert session.device_ip == "192.168.1.50"
        assert session.device_port == 5555


# ---------------------------------------------------------------------------
# TestSessionStop (VCAM-02)
# ---------------------------------------------------------------------------


class TestSessionStop:
    @pytest.mark.asyncio
    async def test_stop_session_terminates_process(self, pm):
        proc = _make_mock_process(returncode=None)
        proc.wait = AsyncMock(return_value=0)
        session = WirelessSessionState(
            session_id="s1",
            source_type="miracast",
            device_path="/dev/video10",
            device_nr=10,
            card_label="Test",
        )
        session.proc = proc
        pm._sessions["s1"] = session

        with patch.object(pm, "_cleanup_session_resources", new_callable=AsyncMock):
            await pm.stop_session("s1")

        proc.terminate.assert_called_once()
        assert "s1" not in pm._sessions

    @pytest.mark.asyncio
    async def test_stop_session_kills_on_timeout(self, pm):
        proc = _make_mock_process(returncode=None)
        proc.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), 0])
        session = WirelessSessionState(
            session_id="s1",
            source_type="miracast",
            device_path="/dev/video10",
            device_nr=10,
            card_label="Test",
        )
        session.proc = proc
        pm._sessions["s1"] = session

        with patch.object(pm, "_cleanup_session_resources", new_callable=AsyncMock):
            await pm.stop_session("s1")

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_stop_session_releases_registry(self, mock_to_thread, pm, mock_registry):
        proc = _make_mock_process(returncode=None)
        proc.wait = AsyncMock(return_value=0)
        session = WirelessSessionState(
            session_id="s1",
            source_type="miracast",
            device_path="/dev/video10",
            device_nr=10,
            card_label="Test",
        )
        session.proc = proc
        pm._sessions["s1"] = session

        await pm.stop_session("s1")

        # to_thread should have been called for registry.release
        release_calls = [
            c for c in mock_to_thread.call_args_list
            if len(c[0]) >= 2 and c[0][0] is mock_registry.release
        ]
        assert len(release_calls) >= 1


# ---------------------------------------------------------------------------
# TestStopAll (VCAM-03 shutdown)
# ---------------------------------------------------------------------------


class TestStopAll:
    @pytest.mark.asyncio
    async def test_stop_all_stops_all_sessions(self, pm):
        pm._sessions["s1"] = WirelessSessionState(
            session_id="s1", source_type="miracast",
            device_path="/dev/video10", device_nr=10, card_label="Test",
        )
        pm._sessions["s2"] = WirelessSessionState(
            session_id="s2", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="Test",
        )

        with patch.object(pm, "stop_session", new_callable=AsyncMock) as mock_stop:
            await pm.stop_all()
            assert mock_stop.call_count == 2

    @pytest.mark.asyncio
    async def test_stop_all_continues_on_failure(self, pm):
        pm._sessions["s1"] = WirelessSessionState(
            session_id="s1", source_type="miracast",
            device_path="/dev/video10", device_nr=10, card_label="Test",
        )
        pm._sessions["s2"] = WirelessSessionState(
            session_id="s2", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="Test",
        )

        call_count = 0

        async def fail_then_succeed(session_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first fails")

        with patch.object(pm, "stop_session", side_effect=fail_then_succeed):
            await pm.stop_all()
            assert call_count == 2


# ---------------------------------------------------------------------------
# TestGetSessions (WAPI-04)
# ---------------------------------------------------------------------------


class TestGetSessions:
    def test_get_sessions_empty(self, pm):
        assert pm.get_sessions() == []

    def test_get_sessions_returns_data(self, pm):
        pm._sessions["s1"] = WirelessSessionState(
            session_id="s1",
            source_type="miracast",
            device_path="/dev/video10",
            device_nr=10,
            card_label="Test",
            status="active",
        )
        sessions = pm.get_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "s1"
        assert sessions[0]["source_type"] == "miracast"
        assert sessions[0]["status"] == "active"

    def test_get_session_returns_none_for_unknown(self, pm):
        assert pm.get_session("nonexistent") is None

    def test_get_session_returns_state(self, pm):
        state = WirelessSessionState(
            session_id="s1", source_type="miracast",
            device_path="/dev/video10", device_nr=10, card_label="Test",
        )
        pm._sessions["s1"] = state
        assert pm.get_session("s1") is state


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_device_number_constants(self):
        assert PipelineManager.DEVICE_NR_MIRACAST == 10
        assert PipelineManager.DEVICE_NR_SCRCPY == 11


# ---------------------------------------------------------------------------
# TestAdbConnect (SCPY-01, D-02)
# ---------------------------------------------------------------------------


class TestAdbConnect:
    """Tests for PipelineManager._run_adb_connect() (SCPY-01, D-02)."""

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_adb_connect_success(self, mock_to_thread, pm):
        """Successful ADB connect returns (True, None)."""
        connect_result = MagicMock()
        connect_result.stdout = "connected to 192.168.1.50:5555"
        connect_result.stderr = ""
        mock_to_thread.side_effect = [MagicMock(), connect_result]

        success, error_code = await pm._run_adb_connect("192.168.1.50")
        assert success is True
        assert error_code is None
        assert mock_to_thread.call_count == 2

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_adb_connect_already_connected(self, mock_to_thread, pm):
        """'already connected to' output is treated as success."""
        connect_result = MagicMock()
        connect_result.stdout = "already connected to 192.168.1.50:5555"
        connect_result.stderr = ""
        mock_to_thread.side_effect = [MagicMock(), connect_result]

        success, error_code = await pm._run_adb_connect("192.168.1.50")
        assert success is True
        assert error_code is None

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_adb_connect_unauthorized(self, mock_to_thread, pm):
        """'unauthorized' in output returns (False, 'adb_unauthorized')."""
        connect_result = MagicMock()
        connect_result.stdout = ""
        connect_result.stderr = "adb: device unauthorized.\nThis adb server's $ADB_VENDOR_KEYS is not set"
        mock_to_thread.side_effect = [MagicMock(), connect_result]

        success, error_code = await pm._run_adb_connect("192.168.1.50")
        assert success is False
        assert error_code == "adb_unauthorized"

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_adb_connect_refused(self, mock_to_thread, pm):
        """'refused' in output returns (False, 'adb_refused')."""
        connect_result = MagicMock()
        connect_result.stdout = ""
        connect_result.stderr = "cannot connect to 192.168.1.50:5555: Connection refused"
        mock_to_thread.side_effect = [MagicMock(), connect_result]

        success, error_code = await pm._run_adb_connect("192.168.1.50")
        assert success is False
        assert error_code == "adb_refused"

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_adb_connect_timeout(self, mock_to_thread, pm):
        """subprocess.TimeoutExpired returns (False, 'adb_refused')."""
        mock_to_thread.side_effect = [MagicMock(), subprocess.TimeoutExpired("adb", 10)]

        success, error_code = await pm._run_adb_connect("192.168.1.50")
        assert success is False
        assert error_code == "adb_refused"

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_adb_connect_calls_disconnect_first(self, mock_to_thread, pm):
        """Per D-02: disconnect is called before connect to clear stale state."""
        connect_result = MagicMock()
        connect_result.stdout = "connected to 192.168.1.50:5555"
        connect_result.stderr = ""
        mock_to_thread.side_effect = [MagicMock(), connect_result]

        await pm._run_adb_connect("192.168.1.50")

        calls = mock_to_thread.call_args_list
        assert len(calls) == 2
        disconnect_cmd = calls[0][0][1]
        connect_cmd = calls[1][0][1]
        assert "disconnect" in disconnect_cmd
        assert "connect" in connect_cmd


# ---------------------------------------------------------------------------
# TestScrcpyStartAdb (SCPY-01)
# ---------------------------------------------------------------------------


class TestScrcpyStartAdb:
    """Tests for start_android_scrcpy() ADB integration (SCPY-01)."""

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_start_stores_device_ip(self, mock_to_thread, mock_exec, pm):
        """Per D-03: device_ip is stored on WirelessSessionState for restart."""
        mock_proc = _make_mock_process(returncode=None)
        mock_exec.return_value = mock_proc
        mock_to_thread.return_value = MagicMock()

        with patch.object(pm, "_run_adb_connect", new_callable=AsyncMock, return_value=(True, None)):
            async def fake_wait(session, delay=1.5):
                session.producer_ready.set()
            with patch.object(pm, "_wait_for_producer", side_effect=fake_wait):
                session_id = await pm.start_android_scrcpy("192.168.1.50")

        session = pm.get_session(session_id)
        assert session.device_ip == "192.168.1.50"

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_start_calls_adb_connect(self, mock_to_thread, mock_exec, pm):
        """start_android_scrcpy calls _run_adb_connect before launching scrcpy."""
        mock_proc = _make_mock_process(returncode=None)
        mock_exec.return_value = mock_proc
        mock_to_thread.return_value = MagicMock()

        with patch.object(pm, "_run_adb_connect", new_callable=AsyncMock, return_value=(True, None)) as mock_adb:
            async def fake_wait(session, delay=1.5):
                session.producer_ready.set()
            with patch.object(pm, "_wait_for_producer", side_effect=fake_wait):
                await pm.start_android_scrcpy("192.168.1.50")

            mock_adb.assert_called_once_with("192.168.1.50", 5555)

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_start_adb_failure_raises(self, mock_to_thread, mock_exec, pm):
        """ADB connect failure raises RuntimeError with error_code on session."""
        mock_to_thread.return_value = MagicMock()

        with patch.object(pm, "_run_adb_connect", new_callable=AsyncMock, return_value=(False, "adb_refused")):
            with pytest.raises(RuntimeError, match="ADB connect failed"):
                await pm.start_android_scrcpy("192.168.1.50")

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_start_includes_no_video_playback_flag(self, mock_to_thread, mock_exec, pm):
        """scrcpy is launched with --no-video-playback for headless operation."""
        mock_proc = _make_mock_process(returncode=None)
        mock_exec.return_value = mock_proc
        mock_to_thread.return_value = MagicMock()

        with patch.object(pm, "_run_adb_connect", new_callable=AsyncMock, return_value=(True, None)):
            async def fake_wait(session, delay=1.5):
                session.producer_ready.set()
            with patch.object(pm, "_wait_for_producer", side_effect=fake_wait):
                await pm.start_android_scrcpy("192.168.1.50")

        call_args = mock_exec.call_args[0]
        assert "--no-video-playback" in call_args


# ---------------------------------------------------------------------------
# TestStaleFrameMonitor (SCPY-04, D-01)
# ---------------------------------------------------------------------------


class TestStaleFrameMonitor:
    """Tests for PipelineManager._stale_frame_monitor() (SCPY-04, D-01)."""

    @pytest.mark.asyncio
    async def test_monitor_stops_when_session_stopped(self, pm):
        """Monitor exits when session.status == 'stopped'."""
        session = WirelessSessionState(
            session_id="s1", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="scrcpy Input",
            status="stopped",
        )
        pm._sessions["s1"] = session

        await pm._stale_frame_monitor("s1")

    @pytest.mark.asyncio
    async def test_monitor_stops_when_session_removed(self, pm):
        """Monitor exits when session is no longer in _sessions dict."""
        with patch("services.pipeline_manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await pm._stale_frame_monitor("nonexistent")
            mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    async def test_monitor_skips_when_status_error(self, pm, mock_registry):
        """Monitor continues (skips restart) when session.status == 'error'."""
        session = WirelessSessionState(
            session_id="s1", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="scrcpy Input",
            status="error",
        )
        pm._sessions["s1"] = session

        call_count = 0

        async def counting_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                session.status = "stopped"

        with patch("services.pipeline_manager.asyncio.sleep", side_effect=counting_sleep):
            await pm._stale_frame_monitor("s1")

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_monitor_triggers_restart_on_stale_frame(self, pm, mock_registry):
        """Monitor calls _restart_session when frame is stale >3s (D-01)."""
        session = WirelessSessionState(
            session_id="s1", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="scrcpy Input",
            status="active", device_ip="192.168.1.50",
        )
        pm._sessions["s1"] = session

        mock_backend = MagicMock()
        mock_backend.last_frame_time = time.monotonic() - 5.0
        mock_registry.get = MagicMock(return_value=mock_backend)

        restart_called = False

        async def mock_restart(sid):
            nonlocal restart_called
            restart_called = True
            session.status = "stopped"

        with patch("services.pipeline_manager.asyncio.sleep", new_callable=AsyncMock):
            with patch.object(pm, "_restart_session", side_effect=mock_restart):
                await pm._stale_frame_monitor("s1")

        assert restart_called
        assert session.error_code == "wifi_timeout"


# ---------------------------------------------------------------------------
# TestRestartSessionScrcpy (SCPY-04, D-02)
# ---------------------------------------------------------------------------


class TestRestartSessionScrcpy:
    """Tests for _restart_session() android_scrcpy branch (SCPY-04, D-02)."""

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_restart_calls_adb_cycle(self, mock_exec, pm):
        """Restart runs full ADB disconnect+connect cycle per D-02."""
        proc = _make_mock_process(returncode=1)
        session = WirelessSessionState(
            session_id="s1", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="scrcpy Input",
            device_ip="192.168.1.50", status="error",
        )
        session.proc = proc
        pm._sessions["s1"] = session

        new_proc = _make_mock_process(returncode=None)
        mock_exec.return_value = new_proc

        with patch.object(pm, "_run_adb_connect", new_callable=AsyncMock, return_value=(True, None)) as mock_adb:
            await pm._restart_session("s1")
            mock_adb.assert_called_once_with("192.168.1.50", 5555)

        assert session.status == "active"

    @pytest.mark.asyncio
    async def test_restart_sets_error_on_adb_failure(self, pm):
        """If ADB reconnect fails, session stays in error with error_code."""
        session = WirelessSessionState(
            session_id="s1", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="scrcpy Input",
            device_ip="192.168.1.50", status="error",
        )
        pm._sessions["s1"] = session

        with patch.object(pm, "_run_adb_connect", new_callable=AsyncMock, return_value=(False, "adb_refused")):
            await pm._restart_session("s1")

        assert session.status == "error"
        assert session.error_code == "adb_refused"

    @pytest.mark.asyncio
    async def test_restart_without_device_ip_returns_early(self, pm):
        """If device_ip is None, restart logs error and returns without crashing."""
        session = WirelessSessionState(
            session_id="s1", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="scrcpy Input",
            device_ip=None, status="error",
        )
        pm._sessions["s1"] = session

        await pm._restart_session("s1")
        assert session.status == "error"


# ---------------------------------------------------------------------------
# TestStopSessionAdbDisconnect (SCPY-03)
# ---------------------------------------------------------------------------


class TestStopSessionAdbDisconnect:
    """Tests for stop_session() ADB disconnect extension (SCPY-03)."""

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_stop_scrcpy_disconnects_adb(self, mock_to_thread, pm):
        """stop_session() calls 'adb disconnect' for android_scrcpy sessions."""
        proc = _make_mock_process(returncode=None)
        proc.wait = AsyncMock(return_value=0)
        session = WirelessSessionState(
            session_id="s1", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="scrcpy Input",
            device_ip="192.168.1.50",
        )
        session.proc = proc
        pm._sessions["s1"] = session

        await pm.stop_session("s1")

        adb_calls = [
            c for c in mock_to_thread.call_args_list
            if len(c[0]) >= 2 and isinstance(c[0][1], list) and "adb" in c[0][1]
        ]
        assert len(adb_calls) >= 1
        adb_cmd = adb_calls[0][0][1]
        assert "disconnect" in adb_cmd
        assert "192.168.1.50:5555" in adb_cmd

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_stop_miracast_no_adb_disconnect(self, mock_to_thread, pm):
        """stop_session() does NOT call adb disconnect for miracast sessions."""
        proc = _make_mock_process(returncode=None)
        proc.wait = AsyncMock(return_value=0)
        session = WirelessSessionState(
            session_id="s1", source_type="miracast",
            device_path="/dev/video10", device_nr=10, card_label="Miracast Input",
        )
        session.proc = proc
        pm._sessions["s1"] = session

        await pm.stop_session("s1")

        adb_calls = [
            c for c in mock_to_thread.call_args_list
            if len(c[0]) >= 2 and isinstance(c[0][1], list) and "adb" in c[0][1]
        ]
        assert len(adb_calls) == 0

    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_stop_cancels_stale_monitor_task(self, mock_to_thread, pm):
        """stop_session() cancels stale_monitor_task if present."""
        proc = _make_mock_process(returncode=None)
        proc.wait = AsyncMock(return_value=0)
        session = WirelessSessionState(
            session_id="s1", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="scrcpy Input",
            device_ip="192.168.1.50",
        )
        session.proc = proc

        async def cancelled_coro():
            raise asyncio.CancelledError()

        real_task = asyncio.ensure_future(cancelled_coro())
        real_task.cancel()
        try:
            await real_task
        except (asyncio.CancelledError, Exception):
            pass

        cancel_mock = MagicMock()

        class FakeTask:
            def __init__(self):
                self.cancel = cancel_mock

            def __await__(self):
                async def _raise():
                    raise asyncio.CancelledError()
                return _raise().__await__()

        session.stale_monitor_task = FakeTask()
        pm._sessions["s1"] = session

        await pm.stop_session("s1")

        cancel_mock.assert_called_once()


# ---------------------------------------------------------------------------
# TestGetSessionByIp
# ---------------------------------------------------------------------------


class TestGetSessionByIp:
    """Tests for PipelineManager.get_session_by_ip()."""

    def test_returns_matching_session(self, pm):
        session = WirelessSessionState(
            session_id="s1", source_type="android_scrcpy",
            device_path="/dev/video11", device_nr=11, card_label="scrcpy Input",
            device_ip="192.168.1.50",
        )
        pm._sessions["s1"] = session
        assert pm.get_session_by_ip("192.168.1.50") is session

    def test_returns_none_for_unknown_ip(self, pm):
        assert pm.get_session_by_ip("10.0.0.1") is None
