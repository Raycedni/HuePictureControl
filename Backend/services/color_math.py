"""Color math utilities for Hue Entertainment API color conversion and region sampling.

Exports:
    GAMUT_C       -- Gamut C triangle vertices (all newer Hue lights)
    rgb_to_xy     -- Convert sRGB to CIE xy with Gamut C clamping
    RegionMask    -- Pre-computed mask with bounding box for fast ROI extraction
    build_polygon_mask -- Build a RegionMask from normalized polygon coordinates
    extract_region_color -- Extract mean RGB from a frame within a RegionMask
    sub_sample_gradient  -- Sample N RGBs along the region's bounding-box longest axis
"""
import math
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Gamut C definition
# All Gen 3+ Hue lights: A19/BR30/Go, LightStrips Plus, Festavia, Flux
# Source: Philips Hue SDK ApplicationDesignNotes
# ---------------------------------------------------------------------------
GAMUT_C: dict[str, tuple[float, float]] = {
    "red":   (0.692, 0.308),
    "green": (0.17,  0.7),
    "blue":  (0.153, 0.048),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cross_product(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return p1[0] * p2[1] - p1[1] * p2[0]


def _closest_point_on_segment(
    a: tuple[float, float],
    b: tuple[float, float],
    p: tuple[float, float],
) -> tuple[float, float]:
    """Return the closest point on segment [a, b] to point p."""
    ab = (b[0] - a[0], b[1] - a[1])
    ap = (p[0] - a[0], p[1] - a[1])
    t = (ap[0] * ab[0] + ap[1] * ab[1]) / (ab[0] ** 2 + ab[1] ** 2 + 1e-10)
    t = max(0.0, min(1.0, t))
    return (a[0] + t * ab[0], a[1] + t * ab[1])


def _in_gamut(x: float, y: float, gamut: dict[str, tuple[float, float]]) -> bool:
    """Return True if (x, y) is inside the gamut triangle (barycentric test)."""
    r, g, b = gamut["red"], gamut["green"], gamut["blue"]
    v0 = (g[0] - r[0], g[1] - r[1])
    v1 = (b[0] - r[0], b[1] - r[1])
    v2 = (x - r[0], y - r[1])
    dot00 = v0[0] * v0[0] + v0[1] * v0[1]
    dot01 = v0[0] * v1[0] + v0[1] * v1[1]
    dot02 = v0[0] * v2[0] + v0[1] * v2[1]
    dot11 = v1[0] * v1[0] + v1[1] * v1[1]
    dot12 = v1[0] * v2[0] + v1[1] * v2[1]
    inv = 1.0 / (dot00 * dot11 - dot01 * dot01 + 1e-10)
    u = (dot11 * dot02 - dot01 * dot12) * inv
    v = (dot00 * dot12 - dot01 * dot02) * inv
    return (u >= 0) and (v >= 0) and (u + v <= 1)


def _clamp_to_gamut(
    x: float, y: float, gamut: dict[str, tuple[float, float]]
) -> tuple[float, float]:
    """Move (x, y) to the nearest point on the gamut triangle boundary."""
    r, g, b = gamut["red"], gamut["green"], gamut["blue"]
    candidates = [
        _closest_point_on_segment(r, g, (x, y)),
        _closest_point_on_segment(g, b, (x, y)),
        _closest_point_on_segment(b, r, (x, y)),
    ]
    best = min(candidates, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
    return best


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rgb_to_xy(r: int, g: int, b: int) -> tuple[float, float]:
    """Convert sRGB (0-255) to CIE xy with Gamut C clamping.

    Returns the D65 white point (0.3127, 0.3290) for black input to avoid
    divide-by-zero at XYZ = (0, 0, 0).

    Args:
        r, g, b: sRGB channel values in range 0-255

    Returns:
        (x, y) CIE xy chromaticity coordinates, clamped to Gamut C
    """
    # Step 1: normalize to [0..1]
    r_f, g_f, b_f = r / 255.0, g / 255.0, b / 255.0

    # Step 2: gamma expansion (sRGB to linear)
    def _gamma(v: float) -> float:
        return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92

    r_lin, g_lin, b_lin = _gamma(r_f), _gamma(g_f), _gamma(b_f)

    # Step 3: Wide RGB D65 matrix to XYZ
    X = r_lin * 0.649926 + g_lin * 0.103455 + b_lin * 0.197109
    Y = r_lin * 0.234327 + g_lin * 0.743075 + b_lin * 0.022598
    Z = r_lin * 0.0       + g_lin * 0.053077 + b_lin * 1.035763

    # Step 4: XYZ to xy chromaticity; guard against black input (XYZ = 0)
    denom = X + Y + Z
    if denom < 1e-10:
        return (0.3127, 0.3290)  # D65 white point fallback
    cx, cy = X / denom, Y / denom

    # Step 5: clamp to Gamut C triangle
    if not _in_gamut(cx, cy, GAMUT_C):
        cx, cy = _clamp_to_gamut(cx, cy, GAMUT_C)

    return round(cx, 4), round(cy, 4)


# ---------------------------------------------------------------------------
# Vectorized rgb_to_xy + bri (quick-task 260516-iqp)
# ---------------------------------------------------------------------------
# Wide-RGB D65 matrix (same numbers as scalar rgb_to_xy) — kept module-level
# so rgb_to_xy_batch's matmul reads from a pre-built array on each call.
_WIDE_RGB_D65 = np.array(
    [
        [0.649926, 0.103455, 0.197109],
        [0.234327, 0.743075, 0.022598],
        [0.0,      0.053077, 1.035763],
    ],
    dtype=np.float32,
)

# Gamut C vertices in the order [R, G, B] so vectorized barycentric tests
# can broadcast across N input pixels.
_GAMUT_C_VERTS = np.array(
    [GAMUT_C["red"], GAMUT_C["green"], GAMUT_C["blue"]],
    dtype=np.float32,
)

# Rec. 709 luma coefficients used by HueStreamer for the per-channel bri.
# float64 so the 0.01 dark-scene floor is represented exactly — float32's
# round-off would emit 0.009999... and break HueStreamer's `bri >= 0.01`
# contract (see test_render_brightness_clamped_for_black).
_REC709_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
_BRI_FLOOR = np.float64(0.01)

# D65 white-point fallback for black input (matches scalar rgb_to_xy).
_D65_XY = np.array([0.3127, 0.3290], dtype=np.float32)


def _gamma_expand(values: np.ndarray) -> np.ndarray:
    """sRGB → linear vectorized. Matches the scalar piecewise definition."""
    threshold = 0.04045
    high = ((values + 0.055) / 1.055) ** 2.4
    low = values / 12.92
    return np.where(values > threshold, high, low).astype(np.float32, copy=False)


def _clamp_to_gamut_batch(points: np.ndarray) -> np.ndarray:
    """Project each (cx, cy) outside Gamut C to its nearest triangle edge.

    Mirrors the scalar _closest_point_on_segment / _clamp_to_gamut combo
    but vectorized over N points. Returns an (N, 2) array.
    """
    r, g, b = _GAMUT_C_VERTS[0], _GAMUT_C_VERTS[1], _GAMUT_C_VERTS[2]
    edges = [(r, g), (g, b), (b, r)]
    candidates = np.empty((len(edges), points.shape[0], 2), dtype=np.float32)
    for i, (a, c) in enumerate(edges):
        ac = c - a
        ap = points - a
        denom = float(ac[0] ** 2 + ac[1] ** 2) + 1e-10
        t = (ap[:, 0] * ac[0] + ap[:, 1] * ac[1]) / denom
        t = np.clip(t, 0.0, 1.0)
        candidates[i, :, 0] = a[0] + t * ac[0]
        candidates[i, :, 1] = a[1] + t * ac[1]
    # Pick the closest of the three projections per point.
    deltas = candidates - points[np.newaxis, :, :]
    sq_dist = (deltas ** 2).sum(axis=2)         # (3, N)
    best_idx = np.argmin(sq_dist, axis=0)        # (N,)
    n = points.shape[0]
    return candidates[best_idx, np.arange(n), :]


def rgb_to_xy_batch(
    rgb: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized sRGB→xy + Rec. 709 bri for an (N, 3) RGB array.

    Quick-task 260516-iqp: replaces the per-channel scalar ``rgb_to_xy`` +
    Python luma compute that HueStreamer ran in a Python for-loop per
    frame. Single numpy pipeline:

        normalize → gamma expand → matmul XYZ → xy chromaticity →
        Gamut C in-gamut test + per-row segment-projection clamp →
        round to 4 decimals (same precision the scalar path emitted).

    Args:
        rgb: shape (N, 3), dtype convertible to float32. Values in [0, 255]
            (uint8 frame means or float means produced by gradient.mean).

    Returns:
        xy:  shape (N, 2), float32, rounded to 4 decimals.
        bri: shape (N,),   float32, Rec. 709 luma / 255 with the same
             0.01 dark-scene floor HueStreamer applied scalar-wise.
    """
    arr = np.asarray(rgb, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[np.newaxis, :]
    if arr.shape[-1] != 3:
        raise ValueError(f"rgb_to_xy_batch expects (..., 3) array; got {arr.shape}")

    normalized = arr / np.float32(255.0)
    linear = _gamma_expand(normalized)
    # XYZ = linear @ M.T (per-row matrix multiply with our row vectors).
    xyz = linear @ _WIDE_RGB_D65.T  # (N, 3)
    denom = xyz.sum(axis=1)
    # Black-input mask: matches scalar guard `denom < 1e-10`.
    black = denom < 1e-10
    safe_denom = np.where(black, np.float32(1.0), denom)
    xy = xyz[:, :2] / safe_denom[:, np.newaxis]

    # In-gamut barycentric test (same triangle vertices as scalar path).
    r, g, b = _GAMUT_C_VERTS[0], _GAMUT_C_VERTS[1], _GAMUT_C_VERTS[2]
    v0 = g - r
    v1 = b - r
    v2 = xy - r
    dot00 = float(v0 @ v0)
    dot01 = float(v0 @ v1)
    dot11 = float(v1 @ v1)
    dot02 = v2 @ v0
    dot12 = v2 @ v1
    inv = 1.0 / (dot00 * dot11 - dot01 * dot01 + 1e-10)
    u = (dot11 * dot02 - dot01 * dot12) * inv
    v = (dot00 * dot12 - dot01 * dot02) * inv
    inside = (u >= 0) & (v >= 0) & ((u + v) <= 1)
    outside = ~inside
    if outside.any():
        xy[outside] = _clamp_to_gamut_batch(xy[outside])

    # Black input overrides clamp result with D65 white point.
    if black.any():
        xy[black] = _D65_XY

    # Match scalar 4-decimal rounding so test parity holds.
    xy = np.round(xy, 4)

    # Rec. 709 luma / 255, with the dark-scene floor applied per row.
    # float64 throughout so the 0.01 floor is exact (float32 round-off
    # would round it to ~0.0099999998 and break the >= 0.01 contract).
    bri = (arr.astype(np.float64) @ _REC709_LUMA) / 255.0
    bri = np.maximum(bri, _BRI_FLOOR)

    return xy.astype(np.float32, copy=False), bri


@dataclass
class RegionMask:
    """Pre-computed mask with bounding box for fast ROI-cropped color extraction."""
    mask: np.ndarray          # Full-frame mask (height x width), uint8
    roi_mask: np.ndarray      # Cropped mask (roi_h x roi_w), uint8
    x1: int
    y1: int
    x2: int
    y2: int


def build_polygon_mask(
    normalized_points: list[list[float]],
    width: int = 640,
    height: int = 480,
) -> RegionMask:
    """Build a binary uint8 mask with pre-computed bounding box for ROI extraction.

    Coordinates are clamped with ``min(1.0, max(0.0, v)) * (dim - 1)`` before
    int conversion to prevent out-of-bounds indices at the frame boundary.

    Args:
        normalized_points: List of [x, y] pairs in range [0..1]
        width: Frame width in pixels (default 320)
        height: Frame height in pixels (default 240)

    Returns:
        RegionMask with full mask, cropped ROI mask, and bounding box coordinates
    """
    mask = np.zeros((height, width), dtype=np.uint8)
    pts = np.array(
        [
            [
                int(min(1.0, max(0.0, x)) * (width - 1)),
                int(min(1.0, max(0.0, y)) * (height - 1)),
            ]
            for x, y in normalized_points
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [pts], color=255)

    # Pre-compute bounding box for ROI crop
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return RegionMask(mask=mask, roi_mask=mask, x1=0, y1=0, x2=width, y2=height)

    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    roi_mask = mask[y1:y2, x1:x2]

    return RegionMask(mask=mask, roi_mask=roi_mask, x1=x1, y1=y1, x2=x2, y2=y2)


def extract_region_color(
    frame: np.ndarray, region: RegionMask
) -> tuple[int, int, int]:
    """Extract mean BGR color from a frame within a polygon mask region.

    Uses bounding-box crop to avoid scanning the entire frame.

    Args:
        frame: BGR uint8 numpy array from capture
        region: RegionMask from build_polygon_mask()

    Returns:
        (r, g, b) tuple of mean color in [0..255] range
    """
    # Crop frame and mask to bounding box — scans only the ROI pixels
    roi_frame = frame[region.y1:region.y2, region.x1:region.x2]
    mean_bgr = cv2.mean(roi_frame, mask=region.roi_mask)
    b, g, r_val = int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])
    return r_val, g, b


# Phase 19 D-17: per-region orientation enum for sub-sample axis + direction.
# 'auto' preserves the Phase 17 bbox-longest-axis behavior (D-22 contract).
Orientation = Literal[
    "auto",
    "horizontal-LTR",
    "horizontal-RTL",
    "vertical-TTB",
    "vertical-BTT",
]


def sub_sample_gradient(
    frame: np.ndarray,
    region: RegionMask,
    n: int,
    orientation: Orientation = "auto",
) -> np.ndarray:
    """Return an (n, 3) array of RGB means sampled along the region's longest bbox axis.

    Per Phase 17 D-10: each LED i in a range of width N samples position i/(N-1)
    along the longer of (x2-x1, y2-y1). The slab around each sample center is
    3 columns/rows wide to absorb single-pixel noise.

    When n == 1, returns a (1, 3) array equal to extract_region_color (so HueStreamer
    can call .mean(axis=0) on the same gradient array WledStreamer slices).
    When n > longest_axis_length, n is clamped to longest_axis_length (per
    17-RESEARCH.md Pitfall 8 — tiny regions can't produce more distinct samples
    than they have pixels in their long dimension).

    Args:
        frame: BGR uint8 numpy array (H x W x 3).
        region: RegionMask with pre-computed bounding box.
        n: Number of equidistant samples to produce.
        orientation: One of 'auto', 'horizontal-LTR', 'horizontal-RTL',
            'vertical-TTB', 'vertical-BTT'. 'auto' (default) keeps the Phase 17
            bbox-longest-axis behavior so Hue callers and untouched WLED
            assignments stay bit-for-bit identical (D-22 contract). The four
            explicit modes force both axis and indexing direction; 'RTL' and
            'BTT' reverse the output array (D-17).

    Returns:
        uint8 ndarray of shape (n_effective, 3) in RGB order, where
        n_effective = max(1, min(n, longest_axis_length)).
    """
    if n <= 1:
        r, g, b = extract_region_color(frame, region)
        return np.array([[r, g, b]], dtype=np.uint8)

    width = region.x2 - region.x1
    height = region.y2 - region.y1
    longest = max(width, height, 1)
    n_effective = max(1, min(n, longest))

    # Phase 19 D-20: orientation overrides longest-axis fallback.
    if orientation == "auto":
        axis_x = width >= height
        reverse = False
    elif orientation == "horizontal-LTR":
        axis_x = True
        reverse = False
    elif orientation == "horizontal-RTL":
        axis_x = True
        reverse = True
    elif orientation == "vertical-TTB":
        axis_x = False
        reverse = False
    elif orientation == "vertical-BTT":
        axis_x = False
        reverse = True
    else:
        raise ValueError(f"Unknown orientation: {orientation!r}")

    # Quick-task 260516-iqp: replace the N×cv2.mean Python loop with a
    # single per-region reduction along the long axis. Strategy:
    #   1. Zero out unmasked pixels in the ROI once.
    #   2. Reduce to per-axis (column or row) sums + per-axis pixel counts.
    #   3. Use a prefix-sum trick to compute every 3-wide slab sum/count in
    #      one vectorized lookup — bit-exact match to the old loop's
    #      cv2.mean(slab, mask=slab_mask) → int() conversion.
    roi_frame = frame[region.y1:region.y2, region.x1:region.x2]
    roi_mask_bool = region.roi_mask > 0

    # Masked frame: unmasked pixels contribute zero to the sums.
    masked = np.where(
        roi_mask_bool[:, :, np.newaxis],
        roi_frame,
        np.zeros_like(roi_frame),
    ).astype(np.int64, copy=False)

    if axis_x:
        axis_len = width
        # Per-column (BGR) sums + per-column masked-pixel counts.
        axis_sums = masked.sum(axis=0)                          # (W, 3)
        axis_counts = roi_mask_bool.sum(axis=0).astype(np.int64)  # (W,)
        centers = np.round(
            np.linspace(0.0, axis_len - 1, n_effective)
        ).astype(np.int64)
    else:
        axis_len = height
        axis_sums = masked.sum(axis=1)                          # (H, 3)
        axis_counts = roi_mask_bool.sum(axis=1).astype(np.int64)  # (H,)
        centers = np.round(
            np.linspace(0.0, axis_len - 1, n_effective)
        ).astype(np.int64)

    # Prefix sums so each slab's sum is a single subtraction.
    cum_sums = np.concatenate(
        [np.zeros((1, 3), dtype=np.int64), axis_sums.cumsum(axis=0)],
        axis=0,
    )
    cum_counts = np.concatenate(
        [np.zeros(1, dtype=np.int64), axis_counts.cumsum()],
    )

    slab_lo = np.maximum(centers - 1, 0)
    slab_hi = np.minimum(centers + 2, axis_len)

    slab_sums = cum_sums[slab_hi] - cum_sums[slab_lo]            # (N, 3)
    slab_counts = cum_counts[slab_hi] - cum_counts[slab_lo]      # (N,)

    # Divide where slab has any masked pixels; zero otherwise (matches
    # cv2.mean's all-masked-out behavior which returns 0 for each channel).
    safe = slab_counts > 0
    slab_means_bgr = np.zeros((n_effective, 3), dtype=np.float64)
    if safe.any():
        slab_means_bgr[safe] = slab_sums[safe] / slab_counts[safe, None]

    # BGR → RGB via channel reversal; truncate to uint8 (same as
    # the old `int(mean_bgr[...])` cast, which rounded toward zero).
    means = np.empty((n_effective, 3), dtype=np.uint8)
    means[:, 0] = slab_means_bgr[:, 2].astype(np.uint8, copy=False)
    means[:, 1] = slab_means_bgr[:, 1].astype(np.uint8, copy=False)
    means[:, 2] = slab_means_bgr[:, 0].astype(np.uint8, copy=False)

    if reverse:
        means = means[::-1]
    return means
