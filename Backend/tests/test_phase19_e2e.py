"""Phase 19 end-to-end smoke: paint → assign → stream → restart → persistence.

Mirrors the Phase 17 pattern at tests/test_phase17_e2e.py. Stubs that depend on
unshipped service modules (wled_channels) skip via pytest.importorskip.
"""
import pytest


async def test_persistence():
    """Painted channels + assignments + orientation persist across DB connection reopen."""
    pytest.importorskip("services.wled_channels")
    # Real implementation arrives in Wave 4-7. Until then, the test exists so
    # VALIDATION.md row "Success #4" has a known target.
    pytest.skip("Wave 7 fills this in (paint → assign → restart → reload).")


async def test_paint_assign_stream_smoke():
    """Register WLED device → paint channel → assign to region → run one frame → verify packet."""
    pytest.importorskip("services.wled_channels")
    pytest.skip("Wave 7 fills this in (full vertical-slice e2e).")
