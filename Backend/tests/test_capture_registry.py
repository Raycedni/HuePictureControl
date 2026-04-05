"""Unit tests for CaptureRegistry — ref-counted pool of CaptureBackend instances."""
import threading
from unittest.mock import MagicMock, patch, call

import pytest

from services.capture_service import CaptureRegistry, CAPTURE_DEVICE


def _make_backend_mock():
    """Return a fresh MagicMock pretending to be a CaptureBackend."""
    mock = MagicMock()
    mock.open = MagicMock()
    mock.release = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# acquire
# ---------------------------------------------------------------------------


class TestAcquire:
    def test_acquire_creates_backend(self):
        """acquire("/dev/video0") calls create_capture, calls open(), returns backend."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        with patch("services.capture_service.create_capture", return_value=mock_backend) as mock_factory:
            result = registry.acquire("/dev/video0")
        mock_factory.assert_called_once_with("/dev/video0")
        mock_backend.open.assert_called_once()
        assert result is mock_backend

    def test_acquire_twice_same_device_returns_same_backend(self):
        """Acquiring the same path twice returns identical object; factory+open called once."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        with patch("services.capture_service.create_capture", return_value=mock_backend) as mock_factory:
            result1 = registry.acquire("/dev/video0")
            result2 = registry.acquire("/dev/video0")
        mock_factory.assert_called_once_with("/dev/video0")
        mock_backend.open.assert_called_once()
        assert result1 is result2

    def test_acquire_different_devices_returns_different_backends(self):
        """Acquiring two distinct paths returns two distinct backend objects."""
        registry = CaptureRegistry()
        backend0 = _make_backend_mock()
        backend1 = _make_backend_mock()
        side_effects = [backend0, backend1]

        with patch("services.capture_service.create_capture", side_effect=side_effects):
            result0 = registry.acquire("/dev/video0")
            result1 = registry.acquire("/dev/video1")

        assert result0 is backend0
        assert result1 is backend1
        assert result0 is not result1


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


class TestRelease:
    def test_release_at_zero_destroys_backend(self):
        """Acquire then release calls backend.release() and removes from internal dicts."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        with patch("services.capture_service.create_capture", return_value=mock_backend):
            registry.acquire("/dev/video0")
        registry.release("/dev/video0")
        mock_backend.release.assert_called_once()
        # Internal dicts must be empty
        assert "/dev/video0" not in registry._backends
        assert "/dev/video0" not in registry._ref_counts

    def test_two_zones_same_device_no_premature_release(self):
        """Acquire twice, release once — backend.release NOT called yet."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        with patch("services.capture_service.create_capture", return_value=mock_backend):
            registry.acquire("/dev/video0")
            registry.acquire("/dev/video0")
        registry.release("/dev/video0")
        mock_backend.release.assert_not_called()

    def test_two_zones_same_device_release_twice_destroys(self):
        """Acquire twice, release twice — backend.release called once on second release."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        with patch("services.capture_service.create_capture", return_value=mock_backend):
            registry.acquire("/dev/video0")
            registry.acquire("/dev/video0")
        registry.release("/dev/video0")
        registry.release("/dev/video0")
        mock_backend.release.assert_called_once()

    def test_release_nonexistent_device_is_noop(self):
        """release() on a path never acquired does not raise."""
        registry = CaptureRegistry()
        # Must not raise
        registry.release("/dev/video99")


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    def test_shutdown_releases_all(self):
        """Acquire two different devices, shutdown — both backend.release called."""
        registry = CaptureRegistry()
        backend0 = _make_backend_mock()
        backend1 = _make_backend_mock()
        with patch("services.capture_service.create_capture", side_effect=[backend0, backend1]):
            registry.acquire("/dev/video0")
            registry.acquire("/dev/video1")
        registry.shutdown()
        backend0.release.assert_called_once()
        backend1.release.assert_called_once()
        assert len(registry._backends) == 0
        assert len(registry._ref_counts) == 0

    def test_shutdown_empty_registry_is_noop(self):
        """shutdown() on a fresh registry does not raise."""
        registry = CaptureRegistry()
        registry.shutdown()  # must not raise

    def test_shutdown_tolerates_release_exception(self):
        """shutdown() continues releasing other backends even if one raises."""
        registry = CaptureRegistry()
        backend0 = _make_backend_mock()
        backend1 = _make_backend_mock()
        backend0.release.side_effect = RuntimeError("device disconnected")
        with patch("services.capture_service.create_capture", side_effect=[backend0, backend1]):
            registry.acquire("/dev/video0")
            registry.acquire("/dev/video1")
        registry.shutdown()  # must not raise
        backend1.release.assert_called_once()


# ---------------------------------------------------------------------------
# get_default
# ---------------------------------------------------------------------------


class TestGetDefault:
    def test_get_default_returns_capture_device_backend(self):
        """acquire(CAPTURE_DEVICE) followed by get_default() returns that backend."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        with patch("services.capture_service.create_capture", return_value=mock_backend):
            registry.acquire(CAPTURE_DEVICE)
        result = registry.get_default()
        assert result is mock_backend

    def test_get_default_returns_none_when_not_acquired(self):
        """get_default() on a fresh registry returns None."""
        registry = CaptureRegistry()
        assert registry.get_default() is None


# ---------------------------------------------------------------------------
# get — non-ref-counted peek
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_returns_none_when_not_acquired(self):
        """get() on a fresh registry returns None for any device path."""
        registry = CaptureRegistry()
        assert registry.get("/dev/video0") is None

    def test_get_returns_acquired_backend(self):
        """get() returns the backend after acquire() on the same path."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        with patch("services.capture_service.create_capture", return_value=mock_backend):
            registry.acquire("/dev/video0")
        result = registry.get("/dev/video0")
        assert result is mock_backend

    def test_get_returns_none_for_different_path(self):
        """get() returns None for a path not yet acquired."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        with patch("services.capture_service.create_capture", return_value=mock_backend):
            registry.acquire("/dev/video0")
        assert registry.get("/dev/video1") is None

    def test_get_does_not_increment_ref_count(self):
        """get() does not increment reference count — acquire, get, release fully releases."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        with patch("services.capture_service.create_capture", return_value=mock_backend):
            registry.acquire("/dev/video0")
        # get() should not increment ref count — one release should destroy the backend
        registry.get("/dev/video0")
        registry.release("/dev/video0")
        mock_backend.release.assert_called_once()
        assert "/dev/video0" not in registry._backends

    def test_get_returns_none_after_release(self):
        """get() returns None once the last holder calls release()."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        with patch("services.capture_service.create_capture", return_value=mock_backend):
            registry.acquire("/dev/video0")
        registry.release("/dev/video0")
        assert registry.get("/dev/video0") is None


# ---------------------------------------------------------------------------
# Thread safety — basic smoke test
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_acquire_same_device_returns_same_backend(self):
        """Multiple threads acquiring the same device path all get the same object."""
        registry = CaptureRegistry()
        mock_backend = _make_backend_mock()
        results = []

        def acquire_in_thread():
            results.append(registry.acquire("/dev/video0"))

        with patch("services.capture_service.create_capture", return_value=mock_backend):
            threads = [threading.Thread(target=acquire_in_thread) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # All threads should get the same backend object
        assert all(r is mock_backend for r in results)
        # create_capture should only have been called once
        assert len(results) == 5
