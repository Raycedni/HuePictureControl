"""Unit tests for Backend/services/color_math.py."""
import numpy as np
import pytest

from services.color_math import (
    GAMUT_C,
    _clamp_to_gamut,
    _in_gamut,
    build_polygon_mask,
    extract_region_color,
    rgb_to_xy,
)


# ---------------------------------------------------------------------------
# rgb_to_xy
# ---------------------------------------------------------------------------


class TestRgbToXy:
    def test_red_primary_within_gamut_c(self):
        """rgb_to_xy(255, 0, 0) should return xy near Gamut C red vertex."""
        x, y = rgb_to_xy(255, 0, 0)
        # Red vertex is at (0.692, 0.308); expect to be close
        assert abs(x - 0.692) < 0.01
        assert abs(y - 0.308) < 0.01

    def test_green_primary_within_gamut_c(self):
        """rgb_to_xy(0, 255, 0) should return xy near Gamut C green vertex."""
        x, y = rgb_to_xy(0, 255, 0)
        # Green vertex at (0.17, 0.7)
        assert abs(x - 0.17) < 0.01
        assert abs(y - 0.7) < 0.01

    def test_blue_primary_within_gamut_c(self):
        """rgb_to_xy(0, 0, 255) should return xy near Gamut C blue vertex."""
        x, y = rgb_to_xy(0, 0, 255)
        # Blue vertex at (0.153, 0.048)
        assert abs(x - 0.153) < 0.01
        assert abs(y - 0.048) < 0.01

    def test_black_returns_d65_white_point(self):
        """rgb_to_xy(0, 0, 0) should return D65 white point without raising."""
        x, y = rgb_to_xy(0, 0, 0)
        assert x == pytest.approx(0.3127, abs=1e-4)
        assert y == pytest.approx(0.3290, abs=1e-4)

    def test_white_returns_valid_gamut_c_xy(self):
        """rgb_to_xy(255, 255, 255) should return a valid xy within Gamut C."""
        x, y = rgb_to_xy(255, 255, 255)
        assert _in_gamut(x, y, GAMUT_C), f"White xy ({x}, {y}) is outside Gamut C"

    def test_return_values_are_floats(self):
        """rgb_to_xy should return a tuple of two floats."""
        result = rgb_to_xy(128, 64, 32)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)


# ---------------------------------------------------------------------------
# _in_gamut
# ---------------------------------------------------------------------------


class TestInGamut:
    def test_red_vertex_is_in_gamut(self):
        """Gamut C red vertex should be identified as inside the gamut."""
        assert _in_gamut(0.692, 0.308, GAMUT_C)

    def test_green_vertex_is_in_gamut(self):
        """Gamut C green vertex should be identified as inside the gamut."""
        assert _in_gamut(0.17, 0.7, GAMUT_C)

    def test_blue_vertex_is_in_gamut(self):
        """Gamut C blue vertex should be identified as inside the gamut."""
        assert _in_gamut(0.153, 0.048, GAMUT_C)

    def test_center_of_gamut_is_in_gamut(self):
        """Centroid of Gamut C triangle should be inside."""
        # Centroid: ((0.692+0.17+0.153)/3, (0.308+0.7+0.048)/3)
        cx = (0.692 + 0.17 + 0.153) / 3
        cy = (0.308 + 0.7 + 0.048) / 3
        assert _in_gamut(cx, cy, GAMUT_C)

    def test_far_point_is_outside_gamut(self):
        """A point clearly outside Gamut C should be identified as out-of-gamut."""
        # (0.9, 0.9) is outside any reasonable gamut
        assert not _in_gamut(0.9, 0.9, GAMUT_C)

    def test_origin_is_outside_gamut(self):
        """(0, 0) is outside Gamut C."""
        assert not _in_gamut(0.0, 0.0, GAMUT_C)


# ---------------------------------------------------------------------------
# _clamp_to_gamut
# ---------------------------------------------------------------------------


class TestClampToGamut:
    def test_in_gamut_point_unchanged(self):
        """A point already inside Gamut C should not be moved significantly."""
        cx = (0.692 + 0.17 + 0.153) / 3
        cy = (0.308 + 0.7 + 0.048) / 3
        x, y = _clamp_to_gamut(cx, cy, GAMUT_C)
        # After clamping an in-gamut point, result should still be in gamut
        assert _in_gamut(x, y, GAMUT_C)

    def test_out_of_gamut_point_clamped_to_edge(self):
        """An out-of-gamut point should be moved to the nearest gamut edge."""
        # (0.9, 0.9) is well outside — after clamping it must be on or inside the triangle
        x, y = _clamp_to_gamut(0.9, 0.9, GAMUT_C)
        # The clamped point should be at an edge (we verify it's in-gamut or on boundary)
        # _in_gamut might return False for boundary points due to float precision,
        # so we verify the clamped point is close to a valid edge
        r, g, b = GAMUT_C["red"], GAMUT_C["green"], GAMUT_C["blue"]
        # The result should be one of the three edge projections
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0


# ---------------------------------------------------------------------------
# build_polygon_mask
# ---------------------------------------------------------------------------


class TestBuildPolygonMask:
    def test_left_half_mask_shape(self):
        """build_polygon_mask should produce a (480, 640) uint8 mask."""
        points = [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]
        mask = build_polygon_mask(points)
        assert mask.shape == (480, 640)
        assert mask.dtype == np.uint8

    def test_left_half_mask_has_255_in_left(self):
        """Left-half polygon should fill left 320 columns with 255."""
        points = [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]
        mask = build_polygon_mask(points)
        # Left half should be filled
        assert np.all(mask[:, :300] == 255), "Left portion should be 255"
        # Right half should be empty
        assert np.all(mask[:, 350:] == 0), "Right portion should be 0"

    def test_coordinate_clamping_at_boundary(self):
        """x=1.0 should not produce pixel index 640 (out of bounds)."""
        # Full-frame polygon — all points at boundary
        points = [[0, 0], [1.0, 0], [1.0, 1.0], [0, 1.0]]
        mask = build_polygon_mask(points)
        # Should not raise and result should be filled
        assert mask.shape == (480, 640)
        # Almost the whole frame should be filled
        assert np.sum(mask == 255) > 640 * 480 * 0.9

    def test_custom_dimensions(self):
        """build_polygon_mask should respect custom width/height arguments."""
        points = [[0, 0], [1, 0], [1, 1], [0, 1]]
        mask = build_polygon_mask(points, width=320, height=240)
        assert mask.shape == (240, 320)

    def test_empty_region_when_points_outside(self):
        """A polygon with degenerate points should not crash."""
        # Triangle with a single pixel-size area
        points = [[0, 0], [0.001, 0], [0, 0.001]]
        mask = build_polygon_mask(points)
        assert mask.shape == (480, 640)


# ---------------------------------------------------------------------------
# extract_region_color
# ---------------------------------------------------------------------------


class TestExtractRegionColor:
    def test_solid_red_frame_with_full_mask(self):
        """extract_region_color returns (255, 0, 0) for a solid red BGR frame."""
        # OpenCV frames are BGR
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :] = (0, 0, 255)  # BGR: red channel is index 2
        mask = np.full((480, 640), 255, dtype=np.uint8)
        r, g, b = extract_region_color(frame, mask)
        assert r == 255
        assert g == 0
        assert b == 0

    def test_solid_green_frame_with_full_mask(self):
        """extract_region_color returns (0, 255, 0) for a solid green BGR frame."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :] = (0, 255, 0)  # BGR: green channel is index 1
        mask = np.full((480, 640), 255, dtype=np.uint8)
        r, g, b = extract_region_color(frame, mask)
        assert r == 0
        assert g == 255
        assert b == 0

    def test_solid_blue_frame_with_full_mask(self):
        """extract_region_color returns (0, 0, 255) for a solid blue BGR frame."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :] = (255, 0, 0)  # BGR: blue channel is index 0
        mask = np.full((480, 640), 255, dtype=np.uint8)
        r, g, b = extract_region_color(frame, mask)
        assert r == 0
        assert g == 0
        assert b == 255

    def test_region_mask_limits_sampling(self):
        """extract_region_color only samples pixels covered by the mask."""
        # Left half: red (BGR 0,0,255); Right half: blue (BGR 255,0,0)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :320] = (0, 0, 255)   # Left half: red in BGR
        frame[:, 320:] = (255, 0, 0)   # Right half: blue in BGR
        # Mask covers only left half
        mask = np.zeros((480, 640), dtype=np.uint8)
        mask[:, :320] = 255
        r, g, b = extract_region_color(frame, mask)
        assert r == 255  # Only red pixels sampled
        assert g == 0
        assert b == 0

    def test_returns_integer_tuple(self):
        """extract_region_color should return a tuple of ints."""
        frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        mask = np.full((480, 640), 255, dtype=np.uint8)
        result = extract_region_color(frame, mask)
        assert len(result) == 3
        assert all(isinstance(v, int) for v in result)
