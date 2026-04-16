"""Tests for Backend/services/pipeline_manager.py.

All subprocess calls are mocked — tests run on Windows and Linux CI
where v4l2loopback-ctl, ffmpeg, scrcpy are not available.
"""
import asyncio
import subprocess

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

        with patch.object(pm, "_wait_for_producer", side_effect=fake_wait):
            session_id = await pm.start_android_scrcpy("192.168.1.50")

        session = pm.get_session(session_id)
        assert session is not None
        assert session.source_type == "android_scrcpy"
        assert session.device_path == "/dev/video11"


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
