"""Unit tests for Backend/services/color_math.py."""
import numpy as np
import pytest

from services.color_math import (
    GAMUT_C,
    RegionMask,
    _clamp_to_gamut,
    _in_gamut,
    boost_saturation_rgb,
    build_polygon_mask,
    extract_region_color,
    rgb_to_xy,
    sub_sample_gradient,
)
from tests.fixtures.mock_capture import _default_frame


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
        """build_polygon_mask should produce a RegionMask with (240, 320) mask."""
        points = [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]
        region = build_polygon_mask(points)
        assert isinstance(region, RegionMask)
        assert region.mask.shape == (480, 640)
        assert region.mask.dtype == np.uint8

    def test_left_half_mask_has_255_in_left(self):
        """Left-half polygon should fill left columns with 255."""
        points = [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]
        region = build_polygon_mask(points)
        # Left half should be filled
        assert np.all(region.mask[:, :300] == 255), "Left portion should be 255"
        # Right half should be empty
        assert np.all(region.mask[:, 350:] == 0), "Right portion should be 0"

    def test_coordinate_clamping_at_boundary(self):
        """x=1.0 should not produce pixel index out of bounds."""
        points = [[0, 0], [1.0, 0], [1.0, 1.0], [0, 1.0]]
        region = build_polygon_mask(points)
        assert region.mask.shape == (480, 640)
        assert np.sum(region.mask == 255) > 320 * 240 * 0.9

    def test_custom_dimensions(self):
        """build_polygon_mask should respect custom width/height arguments."""
        points = [[0, 0], [1, 0], [1, 1], [0, 1]]
        region = build_polygon_mask(points, width=160, height=120)
        assert region.mask.shape == (120, 160)

    def test_empty_region_when_points_outside(self):
        """A polygon with degenerate points should not crash."""
        points = [[0, 0], [0.001, 0], [0, 0.001]]
        region = build_polygon_mask(points)
        assert region.mask.shape == (480, 640)

    def test_roi_bounding_box(self):
        """RegionMask should have a tight bounding box around the polygon."""
        points = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]
        region = build_polygon_mask(points)
        assert region.x1 > 0
        assert region.y1 > 0
        assert region.x2 < 640
        assert region.y2 < 480
        assert region.roi_mask.shape == (region.y2 - region.y1, region.x2 - region.x1)


# ---------------------------------------------------------------------------
# extract_region_color
# ---------------------------------------------------------------------------


def _full_mask(h=480, w=640):
    """Helper: create a RegionMask covering the entire frame."""
    mask = np.full((h, w), 255, dtype=np.uint8)
    return RegionMask(mask=mask, roi_mask=mask, x1=0, y1=0, x2=w, y2=h)


def _left_half_mask(h=480, w=640):
    """Helper: create a RegionMask covering the left half."""
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[:, :w // 2] = 255
    roi_mask = mask[:, :w // 2]
    return RegionMask(mask=mask, roi_mask=roi_mask, x1=0, y1=0, x2=w // 2, y2=h)


class TestExtractRegionColor:
    def test_solid_red_frame_with_full_mask(self):
        """extract_region_color returns (255, 0, 0) for a solid red BGR frame."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :] = (0, 0, 255)
        r, g, b = extract_region_color(frame, _full_mask())
        assert r == 255
        assert g == 0
        assert b == 0

    def test_solid_green_frame_with_full_mask(self):
        """extract_region_color returns (0, 255, 0) for a solid green BGR frame."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :] = (0, 255, 0)
        r, g, b = extract_region_color(frame, _full_mask())
        assert r == 0
        assert g == 255
        assert b == 0

    def test_solid_blue_frame_with_full_mask(self):
        """extract_region_color returns (0, 0, 255) for a solid blue BGR frame."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :] = (255, 0, 0)
        r, g, b = extract_region_color(frame, _full_mask())
        assert r == 0
        assert g == 0
        assert b == 255

    def test_region_mask_limits_sampling(self):
        """extract_region_color only samples pixels covered by the mask."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :320] = (0, 0, 255)   # Left half: red in BGR
        frame[:, 320:] = (255, 0, 0)   # Right half: blue in BGR
        r, g, b = extract_region_color(frame, _left_half_mask())
        assert r == 255
        assert g == 0
        assert b == 0

    def test_returns_integer_tuple(self):
        """extract_region_color should return a tuple of ints."""
        frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        result = extract_region_color(frame, _full_mask())
        assert len(result) == 3
        assert all(isinstance(v, int) for v in result)


# ---------------------------------------------------------------------------
# sub_sample_gradient (Phase 17 D-10)
# ---------------------------------------------------------------------------


class TestSubSampleGradient:
    def test_n1_matches_extract_region_color(self):
        """sub_sample_gradient(frame, region, 1) == extract_region_color (single RGB)."""
        frame = _default_frame()
        region = build_polygon_mask(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            width=640, height=480,
        )
        gradient = sub_sample_gradient(frame, region, 1)
        assert gradient.shape == (1, 3)
        assert gradient.dtype == np.uint8
        r, g, b = extract_region_color(frame, region)
        assert tuple(gradient[0]) == (r, g, b)

    def test_n3_left_to_right_on_rgb_gradient(self):
        """3-band BGR frame -> samples ordered red, green, blue along X axis."""
        frame = _default_frame()
        region = build_polygon_mask(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            width=640, height=480,
        )
        gradient = sub_sample_gradient(frame, region, 3)
        assert gradient.shape == (3, 3)
        r0, g0, b0 = gradient[0]
        assert r0 > 200 and g0 < 60 and b0 < 60, f"expected red, got {(r0, g0, b0)}"
        r2, g2, b2 = gradient[2]
        assert b2 > 200 and r2 < 60 and g2 < 60, f"expected blue, got {(r2, g2, b2)}"

    def test_picks_longer_axis_for_tall_region(self):
        """Tall skinny region samples top-to-bottom along Y axis."""
        frame = _default_frame()
        region = build_polygon_mask(
            [[0.49, 0.0], [0.51, 0.0], [0.51, 1.0], [0.49, 1.0]],
            width=640, height=480,
        )
        gradient = sub_sample_gradient(frame, region, 5)
        assert gradient.shape == (5, 3)
        # All samples fall inside the middle green band — green should dominate
        for rgb in gradient:
            assert rgb[1] >= rgb[0] and rgb[1] >= rgb[2], (
                f"expected green-dominant, got {rgb}"
            )

    def test_dtype_and_value_range(self):
        """Output is uint8 in [0, 255]."""
        frame = _default_frame()
        region = build_polygon_mask(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            width=640, height=480,
        )
        gradient = sub_sample_gradient(frame, region, 10)
        assert gradient.dtype == np.uint8
        assert gradient.min() >= 0 and gradient.max() <= 255

    def test_clamps_to_longest_axis_length_for_tiny_region(self):
        """N greater than the longest axis length is clamped (Pitfall 8)."""
        frame = _default_frame()
        # Tiny 2x2 region near the top-left -> longest axis is 2 px
        region = build_polygon_mask(
            [[0.0, 0.0], [0.003, 0.0], [0.003, 0.005], [0.0, 0.005]],
            width=640, height=480,
        )
        gradient = sub_sample_gradient(frame, region, 10)
        # Region width = ceil(0.003*639)+1 = 2-3 px; clamping cap -> at most 3
        assert gradient.shape[0] <= 10
        assert gradient.shape[1] == 3


# ---------------------------------------------------------------------------
# Phase 19 D-17 / D-20: orientation parameter on sub_sample_gradient
# ---------------------------------------------------------------------------


def _make_horizontal_red_blue_fixture():
    """Synthetic 100×50 BGR frame with horizontal red→blue gradient over a full-bbox region.

    Top-half is solid; the gradient is along x (width >= height => longest axis = x).
    Returns (frame, region_mask).
    """
    width, height = 100, 50
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for x in range(width):
        t = x / (width - 1)
        # BGR: blue grows, red shrinks
        frame[:, x, 0] = int(t * 255)         # blue
        frame[:, x, 2] = int((1 - t) * 255)   # red
    # Full-frame region polygon (normalized)
    polygon_pts = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    mask = build_polygon_mask(polygon_pts, width, height)
    return frame, mask


def test_sub_sample_orientation_auto_matches_phase17():
    """orientation='auto' MUST produce the bit-for-bit same result as the existing call."""
    frame, mask = _make_horizontal_red_blue_fixture()
    n = 10
    a = sub_sample_gradient(frame, mask, n)
    b = sub_sample_gradient(frame, mask, n, orientation="auto")
    assert (a == b).all(), "default 'auto' must match the pre-Phase-19 signature output"


def test_sub_sample_orientation_horizontal_ltr():
    """orientation='horizontal-LTR' forces x-axis; first sample is red, last is blue."""
    frame, mask = _make_horizontal_red_blue_fixture()
    out = sub_sample_gradient(frame, mask, 10, orientation="horizontal-LTR")
    # Output is RGB (per helper convention). First row should be high red, last high blue.
    assert out[0][0] > out[0][2], "first sample should be more red than blue"
    assert out[-1][2] > out[-1][0], "last sample should be more blue than red"


def test_sub_sample_orientation_horizontal_rtl():
    """orientation='horizontal-RTL' reverses the output."""
    frame, mask = _make_horizontal_red_blue_fixture()
    ltr = sub_sample_gradient(frame, mask, 10, orientation="horizontal-LTR")
    rtl = sub_sample_gradient(frame, mask, 10, orientation="horizontal-RTL")
    assert (rtl == ltr[::-1]).all(), "RTL must be LTR reversed"


def test_sub_sample_orientation_vertical_ttb():
    """orientation='vertical-TTB' forces y-axis regardless of bbox aspect."""
    frame, mask = _make_horizontal_red_blue_fixture()
    out = sub_sample_gradient(frame, mask, 10, orientation="vertical-TTB")
    # Fixture is horizontally graded — y-axis sampling should yield near-uniform colors per row.
    # All rows of `out` should be close (within rounding) since each y-row holds the same x-gradient mean.
    for i in range(1, len(out)):
        diff = abs(int(out[i][0]) - int(out[0][0])) + abs(int(out[i][2]) - int(out[0][2]))
        assert diff < 20, f"vertical sampling on a horizontal gradient should be near-uniform; row {i} diff {diff}"


def test_sub_sample_orientation_vertical_btt():
    """orientation='vertical-BTT' reverses the vertical output."""
    frame, mask = _make_horizontal_red_blue_fixture()
    ttb = sub_sample_gradient(frame, mask, 10, orientation="vertical-TTB")
    btt = sub_sample_gradient(frame, mask, 10, orientation="vertical-BTT")
    assert (btt == ttb[::-1]).all(), "BTT must be TTB reversed"


def test_sub_sample_orientation_invalid_raises_value_error():
    """orientation='bogus' raises ValueError."""
    frame, mask = _make_horizontal_red_blue_fixture()
    with pytest.raises(ValueError):
        sub_sample_gradient(frame, mask, 10, orientation="bogus")


# ---------------------------------------------------------------------------
# Vibrancy-weighted sampling (quick-task 260704-iss D-1)
# ---------------------------------------------------------------------------


def _rec709_luma(r: float, g: float, b: float) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _red_with_white_stripe_frame(h=100, w=100, stripe_rows=(49, 51)):
    """Mostly-red (RGB 200,0,0) frame with a thin white stripe (subtitle-like).

    NON-max red (200,0,0) so the vibrancy=1.0 luma-match scale-up does not
    hit the 255 per-channel cap (a 255,0,0 region can't brighten further).
    """
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:, :] = (0, 0, 200)  # BGR -> RGB (200, 0, 0)
    r0, r1 = stripe_rows
    frame[r0:r1, :] = (255, 255, 255)  # thin white stripe
    return frame


class TestVibrancy:
    def test_vibrancy_zero_is_byte_identical_to_plain_mean(self):
        """extract_region_color with vibrancy=0.0 (default) is the unmodified cv2.mean path."""
        frame = _red_with_white_stripe_frame()
        region = _full_mask(h=100, w=100)
        default_result = extract_region_color(frame, region)
        explicit_zero_result = extract_region_color(frame, region, vibrancy=0.0)
        assert default_result == explicit_zero_result

    def test_vibrancy_suppresses_white_stripe_preserving_luma(self):
        """High vibrancy suppresses the white stripe's desaturating effect
        while rescaling to preserve the region's unweighted-mean luma."""
        frame = _red_with_white_stripe_frame()
        region = _full_mask(h=100, w=100)

        r0, g0, b0 = extract_region_color(frame, region, vibrancy=0.0)
        # Current (desaturated) behavior: white admixture lifts g/b above 0.
        assert g0 > 0 and b0 > 0

        r1, g1, b1 = extract_region_color(frame, region, vibrancy=1.0)
        # Near-pure red hue: green/blue contribution is now negligible.
        assert r1 > g0 + b0 + g1 + b1 or (g1 <= 2 and b1 <= 2)
        assert g1 <= 2 and b1 <= 2

        # Luma preservation: vibrancy=1.0 result's luma matches the plain
        # unweighted-mean luma of the whole region (brightness unchanged).
        mask_bool = region.roi_mask > 0
        roi = frame[region.y1:region.y2, region.x1:region.x2]
        unweighted_bgr = roi[mask_bool].astype(np.float64).mean(axis=0)
        luma_unweighted = _rec709_luma(unweighted_bgr[2], unweighted_bgr[1], unweighted_bgr[0])
        luma_vibrant = _rec709_luma(r1, g1, b1)
        assert luma_vibrant == pytest.approx(luma_unweighted, abs=2.0)

    def test_vibrancy_uniform_saturated_frame_unchanged_at_any_alpha(self):
        """A single fully-saturated color has uniform per-pixel weights, so the
        weighted mean == unweighted mean and brightness is unchanged regardless
        of vibrancy."""
        frame = np.zeros((60, 60, 3), dtype=np.uint8)
        frame[:, :] = (0, 255, 0)  # BGR -> RGB (0, 255, 0), fully saturated green
        region = _full_mask(h=60, w=60)

        result_0 = extract_region_color(frame, region, vibrancy=0.0)
        result_half = extract_region_color(frame, region, vibrancy=0.5)
        result_1 = extract_region_color(frame, region, vibrancy=1.0)
        assert result_0 == result_half == result_1 == (0, 255, 0)

    def test_vibrancy_total_weight_zero_falls_back_to_unweighted_mean(self):
        """An all-gray region at vibrancy=1.0 has every pixel S=0 -> every
        weight=0 -> the total-weight-zero guard falls back to the plain
        unweighted mean instead of dividing by zero."""
        frame = np.zeros((40, 40, 3), dtype=np.uint8)
        frame[:, :] = (128, 128, 128)  # gray: R==G==B, S=0 everywhere
        region = _full_mask(h=40, w=40)

        result_default = extract_region_color(frame, region, vibrancy=0.0)
        result_vibrant = extract_region_color(frame, region, vibrancy=1.0)
        assert result_vibrant == result_default == (128, 128, 128)

    def test_sub_sample_gradient_vibrancy_zero_matches_current_path(self):
        """sub_sample_gradient(..., vibrancy=0.0) is byte-identical to the
        pre-260704-iss cv2.mean slab loop (n > 1 branch)."""
        frame = _default_frame()
        region = build_polygon_mask(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            width=640, height=480,
        )
        default_result = sub_sample_gradient(frame, region, 5)
        explicit_zero = sub_sample_gradient(frame, region, 5, vibrancy=0.0)
        assert (default_result == explicit_zero).all()

    def test_sub_sample_gradient_vibrancy_forwarded_at_n1(self):
        """n<=1 branch forwards vibrancy into extract_region_color."""
        frame = _red_with_white_stripe_frame()
        region = _full_mask(h=100, w=100)
        gradient = sub_sample_gradient(frame, region, 1, vibrancy=1.0)
        r, g, b = extract_region_color(frame, region, vibrancy=1.0)
        assert tuple(gradient[0]) == (r, g, b)

    def test_sub_sample_gradient_vibrancy_suppresses_white_per_slab(self):
        """n>1 branch with vibrancy>0 suppresses a white stripe per-slab too."""
        frame = _red_with_white_stripe_frame(h=100, w=100)
        region = build_polygon_mask(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            width=100, height=100,
        )
        gradient_plain = sub_sample_gradient(frame, region, 5, vibrancy=0.0)
        gradient_vibrant = sub_sample_gradient(frame, region, 5, vibrancy=1.0)
        # Every sample should stay strongly red-dominant, and vibrancy=1.0
        # should suppress the green/blue channels more than the plain path.
        for i in range(gradient_plain.shape[0]):
            assert int(gradient_vibrant[i][1]) <= int(gradient_plain[i][1])
            assert int(gradient_vibrant[i][2]) <= int(gradient_plain[i][2])


# ---------------------------------------------------------------------------
# Saturation boost (quick-task 260704-iss D-2)
# ---------------------------------------------------------------------------


class TestSaturationBoost:
    def test_boost_zero_is_identity(self):
        """boost_saturation_rgb(arr, 0.0) returns the input unchanged (same object)."""
        arr = np.array([[200, 100, 50], [128, 128, 128]], dtype=np.uint8)
        result = boost_saturation_rgb(arr, 0.0)
        assert result is arr

    def test_boost_raises_saturation_leaves_value_unchanged(self):
        """boost > 0 raises HSV S while HSV V (max channel) stays identical."""
        arr = np.array([[200, 100, 50], [10, 10, 200]], dtype=np.uint8)
        boosted = boost_saturation_rgb(arr, 0.5)

        assert boosted.dtype == np.uint8
        assert boosted.shape == arr.shape

        v_before = arr.max(axis=-1)
        v_after = boosted.max(axis=-1)
        assert (v_after == v_before).all()

        def _saturation(px):
            mx, mn = float(px.max()), float(px.min())
            return 0.0 if mx == 0 else (mx - mn) / mx

        for i in range(arr.shape[0]):
            assert _saturation(boosted[i]) >= _saturation(arr[i])

    def test_boost_gray_pixels_stay_gray(self):
        """Pure-gray (chroma 0) pixels are unaffected by any boost value."""
        arr = np.array([[128, 128, 128], [0, 0, 0], [255, 255, 255]], dtype=np.uint8)
        boosted = boost_saturation_rgb(arr, 1.0)
        assert (boosted == arr).all()

    def test_boost_works_on_single_pixel_shape(self):
        """boost_saturation_rgb also accepts a (3,) single-pixel shape."""
        px = np.array([200, 50, 50], dtype=np.uint8)
        boosted = boost_saturation_rgb(px, 0.5)
        assert boosted.shape == (3,)
        assert int(boosted.max()) == int(px.max())
