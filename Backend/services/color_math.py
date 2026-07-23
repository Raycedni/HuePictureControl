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


# ---------------------------------------------------------------------------
# Vibrancy-weighted sampling + saturation boost (quick-task 260704-iss)
# ---------------------------------------------------------------------------
# Fixes "white pollution": small bright-white UI elements (subtitles, HUD
# lines) inside a region desaturate the plain cv2.mean color sent to the
# LEDs. `color_vibrancy` re-weights the region mean toward saturated pixels
# while rescaling to preserve the region's unweighted luma (brightness).
# `saturation_boost` is an independent post-hoc HSV-S boost applied to the
# final per-region/per-LED RGB, leaving HSV V (brightness) untouched.


def _saturation_weights(roi_bgr: np.ndarray, alpha: float) -> np.ndarray:
    """Per-pixel sampling weight from HSV-style saturation S = (max-min)/max.

    Computed ONCE per region ROI (perf constraint: reused across all slabs
    in sub_sample_gradient's n>1 path). Returns an (H, W) float32 array;
    w = (1-alpha) + alpha*(S*S) so alpha=0 -> uniform weights (== unweighted
    mean) and alpha=1 -> pure S^2 weighting (near-white pixels contribute
    almost nothing).
    """
    roi_f = roi_bgr.astype(np.float32)
    mx = roi_f.max(axis=2)
    mn = roi_f.min(axis=2)
    s = np.where(mx > 0, (mx - mn) / mx, 0.0).astype(np.float32)
    return ((1.0 - alpha) + alpha * (s * s)).astype(np.float32)


def _weighted_region_mean(
    roi_bgr: np.ndarray, mask: np.ndarray, weights: np.ndarray
) -> tuple[int, int, int]:
    """Saturation-weighted region mean with brightness (luma) preservation.

    Rescales the weighted-mean color so its Rec.709 luma matches the
    region's plain unweighted-mean luma — this is what suppresses white
    pixels' chromaticity contribution WITHOUT dimming the result. Falls
    back to the unweighted mean when the mask is empty or every pixel's
    weight collapses to ~0 (e.g. an all-white/all-gray region at alpha=1.0,
    where every S=0).
    """
    mask_bool = mask > 0
    masked_px = roi_bgr[mask_bool].astype(np.float32)  # (N, 3) BGR
    if masked_px.shape[0] == 0:
        return (0, 0, 0)

    unweighted_bgr = masked_px.mean(axis=0)

    w = weights[mask_bool].astype(np.float32)
    w_sum = float(w.sum())
    if w_sum < 1e-6:
        weighted_bgr = unweighted_bgr
    else:
        weighted_bgr = (masked_px * w[:, np.newaxis]).sum(axis=0) / w_sum

    def _luma(bgr: np.ndarray) -> float:
        # bgr = [B, G, R]; Rec.709 luma on RGB order.
        return 0.2126 * bgr[2] + 0.7152 * bgr[1] + 0.0722 * bgr[0]

    luma_unweighted = _luma(unweighted_bgr)
    luma_weighted = _luma(weighted_bgr)

    if luma_weighted > 1e-6:
        scale = luma_unweighted / luma_weighted
        max_channel = float(weighted_bgr.max())
        if max_channel > 1e-6:
            # Cap the scale so no channel overflows 255 — uniform per-channel
            # scaling preserves hue while guaranteeing no clipping artifact.
            scale = min(scale, 255.0 / max_channel)
        weighted_bgr = weighted_bgr * scale

    weighted_bgr = np.clip(weighted_bgr, 0.0, 255.0)
    b, g, r_val = int(round(weighted_bgr[0])), int(round(weighted_bgr[1])), int(round(weighted_bgr[2]))
    return r_val, g, b


def _weighted_region_mean_linear(
    roi_linear: np.ndarray, mask: np.ndarray, weights: np.ndarray
) -> np.ndarray:
    """Saturation-weighted LINEAR-light region mean with luma preservation.

    Quick-task 260704-wy5 (HDR v2): mirrors ``_weighted_region_mean``'s
    saturation-weighting + Rec.709 luma-preservation algorithm, but operates
    entirely in linear float space (BGR order) so a bright pixel dominates
    the mean the way it dominates perceptually. Unlike the byte-space
    version, this does NOT clip/round to uint8 and does NOT cap the
    luma-rescale at a 255/max_channel ceiling -- there is no uint8 range to
    protect in linear space; the downstream tone-map
    (``_finish_linear_bt2020_to_srgb``) handles range compression. Falls
    back to the unweighted linear mean when the mask is empty or every
    pixel's weight collapses to ~0.

    Returns:
        (3,) float32 array, BGR order, unclipped linear light.
    """
    mask_bool = mask > 0
    masked_px = roi_linear[mask_bool].astype(np.float32)  # (N, 3) BGR linear
    if masked_px.shape[0] == 0:
        return np.zeros(3, dtype=np.float32)

    unweighted_bgr = masked_px.mean(axis=0)

    w = weights[mask_bool].astype(np.float32)
    w_sum = float(w.sum())
    if w_sum < 1e-6:
        weighted_bgr = unweighted_bgr
    else:
        weighted_bgr = (masked_px * w[:, np.newaxis]).sum(axis=0) / w_sum

    def _luma(bgr: np.ndarray) -> float:
        # bgr = [B, G, R]; Rec.709 luma on RGB order.
        return 0.2126 * bgr[2] + 0.7152 * bgr[1] + 0.0722 * bgr[0]

    luma_unweighted = _luma(unweighted_bgr)
    luma_weighted = _luma(weighted_bgr)

    if luma_weighted > 1e-6:
        scale = luma_unweighted / luma_weighted
        weighted_bgr = weighted_bgr * scale

    return weighted_bgr.astype(np.float32)


def boost_saturation_rgb(rgb: np.ndarray, boost: float) -> np.ndarray:
    """Adjust HSV saturation of an RGB array while leaving HSV V untouched.

    Args:
        rgb: (N, 3) or (3,) array, RGB order, any numeric dtype.
        boost: 0.0 = identity (returns ``rgb`` unchanged, zero cost).
            Range [-1.0, 1.0].
            > 0.0 raises saturation; 1.0 fully saturates (S -> 1.0).
            < 0.0 lowers saturation; -1.0 fully desaturates (S -> 0.0,
            i.e. full grayscale).

    Returns:
        uint8 array of the same shape as ``rgb``. The max channel per pixel
        (== HSV V) is numerically unchanged because ``mx - (mx - mx)*ratio
        == mx``; only the non-max channels are pulled toward (positive
        boost) or away from (negative boost) the max channel.
    """
    if boost == 0.0:
        return rgb

    arr = np.asarray(rgb, dtype=np.float32)
    mx = arr.max(axis=-1, keepdims=True)
    mn = arr.min(axis=-1, keepdims=True)
    chroma = mx - mn
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(mx > 0, chroma / mx, 0.0)
        if boost > 0.0:
            s_new = s + boost * (1.0 - s)
        else:
            s_new = s * (1.0 + boost)
        ratio = np.where(s > 1e-6, s_new / s, 1.0)
    out = mx - (mx - arr) * ratio
    return np.clip(out, 0.0, 255.0).astype(np.uint8)


def correct_channels_rgb(
    rgb: np.ndarray, gain_r: float, gain_g: float, gain_b: float
) -> np.ndarray:
    """Static flat per-channel color correction (quick-task 260719-efy).

    Applies a direct multiplicative gain to each RGB channel of every pixel
    unconditionally: ``red = arr[..., 0] * gain_r``, ``green = arr[..., 1] *
    gain_g``, ``blue = arr[..., 2] * gain_b``. There is NO dominant/max-channel
    special-casing -- the gain hits every channel of every pixel the same way.
    This is a deliberate HARDWARE-tint compensation knob (residual color
    rendering in the physical Hue/WLED lights), NOT a color-correctness fix --
    the computed colors going in are already correct end-to-end.

    Args:
        rgb: (N, 3) or (3,) array, RGB order, any numeric dtype.
        gain_r: direct multiplier on the red channel. 1.0 = identity.
            Suggested UI range [0.5, 1.5].
        gain_g: direct multiplier on the green channel. 1.0 = identity.
        gain_b: direct multiplier on the blue channel. 1.0 = identity.

    Returns:
        uint8 array of the same shape as ``rgb``. Each channel is scaled by
        its gain and clipped to [0, 255], so a gain > 1.0 can saturate a
        channel at 255 and a gain < 1.0 scales it down. Conversion to uint8
        uses truncation (``.astype(np.uint8)``), matching the rest of this
        module.

        At gain_r == gain_g == gain_b == 1.0 this returns ``rgb`` unchanged
        (same object, zero cost) -- mirrors ``boost_saturation_rgb``'s
        ``boost == 0.0`` identity contract.
    """
    if gain_r == 1.0 and gain_g == 1.0 and gain_b == 1.0:
        return rgb

    arr = np.asarray(rgb, dtype=np.float32)
    gains = np.array([gain_r, gain_g, gain_b], dtype=np.float32)
    out = arr * gains
    return np.clip(out, 0.0, 255.0).astype(np.uint8)


def extract_region_color(
    frame: np.ndarray, region: RegionMask, vibrancy: float = 0.0, hdr: bool = False
) -> tuple[int, int, int]:
    """Extract mean BGR color from a frame within a polygon mask region.

    Uses bounding-box crop to avoid scanning the entire frame.

    Args:
        frame: BGR uint8 numpy array from capture
        region: RegionMask from build_polygon_mask()
        vibrancy: 0.0 (default) keeps the exact original cv2.mean fast path,
            byte-identical to pre-260704-iss behavior. > 0.0 uses a
            saturation-weighted mean that suppresses white pixels'
            chromaticity contribution while preserving region luma.
        hdr: False (default) keeps the byte-space mean above, unchanged.
            True (quick-task 260704-wy5, HDR v2) expands the ROI through
            the limited-range PQ->linear LUT BEFORE averaging, so a bright
            area dominates the region mean in linear light instead of
            collapsing to a warm-gray byte-space average. The linear mean
            is finished with roll-off -> BT.2020->BT.709 -> sRGB encode.

    Returns:
        (r, g, b) tuple of mean color in [0..255] range
    """
    # Crop frame and mask to bounding box — scans only the ROI pixels
    roi_frame = frame[region.y1:region.y2, region.x1:region.x2]

    if hdr:
        mask_bool = region.roi_mask > 0
        if not mask_bool.any():
            return (0, 0, 0)
        roi_linear = _LINEAR_LUT[roi_frame]  # (H, W, 3) BGR linear
        if vibrancy <= 0.0:
            lin_bgr = roi_linear[mask_bool].mean(axis=0)
        else:
            weights = _saturation_weights(roi_linear, vibrancy)
            lin_bgr = _weighted_region_mean_linear(roi_linear, region.roi_mask, weights)
        lin_rgb = lin_bgr[::-1]  # BGR -> RGB (matrix below is RGB-order)
        out = _finish_linear_bt2020_to_srgb(lin_rgb)
        return int(out[0]), int(out[1]), int(out[2])

    if vibrancy <= 0.0:
        mean_bgr = cv2.mean(roi_frame, mask=region.roi_mask)
        b, g, r_val = int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])
        return r_val, g, b

    weights = _saturation_weights(roi_frame, vibrancy)
    return _weighted_region_mean(roi_frame, region.roi_mask, weights)


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
    vibrancy: float = 0.0,
    hdr: bool = False,
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
        vibrancy: 0.0 (default) keeps the exact current cv2.mean slab loop,
            byte-identical to pre-260704-iss behavior. > 0.0 uses a
            saturation-weighted per-slab mean (quick-task 260704-iss); the
            weight array is computed ONCE over the full ROI and sliced per
            slab (perf constraint — see below).
        hdr: False (default) keeps the byte-space per-slab cv2.mean loop,
            unchanged. True (quick-task 260704-wy5, HDR v2) computes each
            slab's mean in LINEAR light (via the limited-range PQ->linear
            LUT, applied ONCE over the full ROI) and finishes the whole
            (n,3) buffer through the BT.2020->BT.709->sRGB tone-map in a
            single vectorized call after the per-slab loop.

    Returns:
        uint8 ndarray of shape (n_effective, 3) in RGB order, where
        n_effective = max(1, min(n, longest_axis_length)).
    """
    if n <= 1:
        r, g, b = extract_region_color(frame, region, vibrancy=vibrancy, hdr=hdr)
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

    # Quick-task 260516-iqp note: a prefix-sum vectorized path was
    # benchmarked here. It produced bit-identical output but was 16–40×
    # slower at typical N (6–100) because numpy's per-region setup
    # (np.where + sum + cumsum) is heavier than N cv2.mean calls over
    # 3-wide slabs. Crossover with the scalar loop is around N=490
    # (full DRGB strip). The cv2.mean loop is kept because it wins for
    # every realistic N (≤300 LEDs typical).
    roi_frame = frame[region.y1:region.y2, region.x1:region.x2]

    if hdr:
        # 260704-wy5 (HDR v2): expand the ROI to LINEAR light ONCE, average
        # each slab in linear space (bright pixels dominate the way they
        # dominate perceptually), then finish the whole buffer through the
        # BT.2020->BT.709->sRGB tone-map in a single vectorized call AFTER
        # the loop -- never per-slab (perf + numerical parity with the
        # single-call finish extract_region_color uses).
        roi_linear = _LINEAR_LUT[roi_frame]  # (roi_h, roi_w, 3) BGR linear
        roi_weights_lin = _saturation_weights(roi_linear, vibrancy) if vibrancy > 0.0 else None
        lin_means = np.empty((n_effective, 3), dtype=np.float32)
        for i in range(n_effective):
            t = i / (n_effective - 1) if n_effective > 1 else 0.0
            if axis_x:
                col_center = int(round(t * (width - 1)))
                slab_x1 = max(col_center - 1, 0)
                slab_x2 = min(col_center + 2, width)
                slab_lin = roi_linear[:, slab_x1:slab_x2]
                slab_mask = region.roi_mask[:, slab_x1:slab_x2]
                slab_weights = roi_weights_lin[:, slab_x1:slab_x2] if roi_weights_lin is not None else None
            else:
                row_center = int(round(t * (height - 1)))
                slab_y1 = max(row_center - 1, 0)
                slab_y2 = min(row_center + 2, height)
                slab_lin = roi_linear[slab_y1:slab_y2, :]
                slab_mask = region.roi_mask[slab_y1:slab_y2, :]
                slab_weights = roi_weights_lin[slab_y1:slab_y2, :] if roi_weights_lin is not None else None
            if slab_weights is None:
                slab_mask_bool = slab_mask > 0
                if slab_mask_bool.any():
                    lin_bgr = slab_lin[slab_mask_bool].mean(axis=0)
                else:
                    lin_bgr = np.zeros(3, dtype=np.float32)
            else:
                lin_bgr = _weighted_region_mean_linear(slab_lin, slab_mask, slab_weights)
            lin_means[i] = lin_bgr[::-1]  # BGR -> RGB
        out = _finish_linear_bt2020_to_srgb(lin_means)
        if reverse:
            out = out[::-1]
        return out

    # 260704-iss: compute the saturation-weight array ONCE over the full ROI
    # (perf constraint) when vibrancy > 0, then slice it per slab below
    # exactly like slab_frame/slab_mask are sliced from roi_frame/roi_mask.
    roi_weights = _saturation_weights(roi_frame, vibrancy) if vibrancy > 0.0 else None

    means = np.empty((n_effective, 3), dtype=np.uint8)
    for i in range(n_effective):
        t = i / (n_effective - 1) if n_effective > 1 else 0.0
        if axis_x:
            col_center = int(round(t * (width - 1)))
            slab_x1 = max(col_center - 1, 0)
            slab_x2 = min(col_center + 2, width)
            slab_frame = roi_frame[:, slab_x1:slab_x2]
            slab_mask = region.roi_mask[:, slab_x1:slab_x2]
            slab_weights = roi_weights[:, slab_x1:slab_x2] if roi_weights is not None else None
        else:
            row_center = int(round(t * (height - 1)))
            slab_y1 = max(row_center - 1, 0)
            slab_y2 = min(row_center + 2, height)
            slab_frame = roi_frame[slab_y1:slab_y2, :]
            slab_mask = region.roi_mask[slab_y1:slab_y2, :]
            slab_weights = roi_weights[slab_y1:slab_y2, :] if roi_weights is not None else None
        if slab_weights is None:
            mean_bgr = cv2.mean(slab_frame, mask=slab_mask)
            # cv2.mean returns BGR; convert to RGB for output
            means[i] = [int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0])]
        else:
            r, g, b = _weighted_region_mean(slab_frame, slab_mask, slab_weights)
            means[i] = [r, g, b]
    if reverse:
        means = means[::-1]
    return means


# ---------------------------------------------------------------------------
# HDR10 -> sRGB conversion (quick-task 260704-w88, v2 260704-wy5)
# ---------------------------------------------------------------------------
# Some capture cards pass HDR10 (BT.2020 primaries + PQ/ST-2084 transfer)
# through unconverted, in LIMITED range (blacks ~16, whites ~235-255 per
# CTA-861 / typical HDMI HDR signaling). The pipeline downstream
# (boost_saturation_rgb, rgb_to_xy_batch) assumes full-range sRGB, so HDR10
# source content reads washed-out, hue-rotated (e.g. orange -> green) under
# saturation boost, and -- pre-v2 -- murky warm-gray in high-dynamic-range
# scenes.
#
# v1 (260704-w88) converted the ALREADY-BYTE-AVERAGED (N,3) sampled gradient
# from HDR10 to sRGB, post-hoc, after extract_region_color/sub_sample_gradient
# had already averaged in PQ-encoded byte space. That let a bright highlight
# (e.g. a fire) barely outweigh a dull midtone (e.g. a sail) in the byte-space
# mean (~1.7x), collapsing the result to warm gray -- because PQ compresses
# highlights logarithmically, a byte-space average badly under-weights how
# much brighter a highlight actually is in linear light (~10x).
#
# v2 (260704-wy5) DECOMPOSES the pipeline into two composable halves so
# HDR-aware sampling can average in LINEAR light BEFORE the mean is taken,
# letting a bright area dominate the region mean the way it dominates
# perceptually:
#   - `_LINEAR_LUT`: a 256-entry table (limited-range expand -> PQ EOTF ->
#     linear, built ONCE at import) applied per-pixel via numpy fancy
#     indexing on a uint8 ROI.
#   - `_finish_linear_bt2020_to_srgb`: highlight roll-off (in BT.2020 gamut,
#     BEFORE the primaries matrix -- see rationale below) -> BT.2020->BT.709
#     matrix -> clip -> sRGB OETF encode -> uint8.
# `hdr10_to_srgb` is now the composition of both halves (LUT then finish),
# preserving its original (3,)/(N,3) uint8-in/uint8-out contract for any
# remaining direct callers. `extract_region_color`/`sub_sample_gradient`'s
# new `hdr=True` path calls the LUT once over the whole ROI and averages in
# linear light BEFORE calling the finishing half, which is the actual v2 fix.
#
# v3 (260723-udg) reworks ONLY the finishing curve (`_finish_linear_bt2020_to_srgb`);
# `_LINEAR_LUT` and the linear-averaging paths are untouched. The v2 finish used
# per-channel extended Reinhard, which destroyed channel ratios on bright colors:
# bright orange collapsed to near-white yellow (which `saturation_boost` then
# rotated toward green), diffuse white crushed to ~0.5 (users compensated by
# blowing out brightness), and the post-matrix per-channel negative clip rotated
# brown toward red. v3 replaces it with a hue-preserving pipeline: a scalar
# max-RGB tone map (uniform per-sample scale with a knee + exponential shoulder,
# so diffuse white lands ~0.91 and ratios/saturation survive) followed by
# hue-preserving gamut compression toward the achromatic axis (a luma-preserving
# lerp) instead of a per-channel clip -- preserving hue end-to-end. See
# `_tone_map_max_rgb` and `_compress_to_gamut_709`.

HDR_REF_WHITE_NITS = 203.0  # SDR reference white per ITU-R BT.2408
# Linear-light knee below which the tone map is identity; SDR-range HDR
# content (max channel <= this) passes through untouched (quick-task 260723-udg).
_TONE_KNEE = np.float32(0.75)

# ST 2084 (PQ) EOTF constants.
_PQ_M1 = 0.1593017578125
_PQ_M2 = 78.84375
_PQ_C1 = 0.8359375
_PQ_C2 = 18.8515625
_PQ_C3 = 18.6875

# BT.2020 -> BT.709 primaries matrix (RGB order), applied as rel @ M.T.
_BT2020_TO_BT709 = np.array(
    [
        [1.6605, -0.5876, -0.0728],
        [-0.1246, 1.1329, -0.0083],
        [-0.0182, -0.1006, 1.1187],
    ],
    dtype=np.float32,
)


def _build_linear_lut() -> np.ndarray:
    """Build the 256-entry limited-range-PQ-byte -> linear-light LUT.

    b in [0,255] -> limited-range expansion (16 -> 0.0, >=235 -> 1.0,
    clipped) -> PQ EOTF (ST 2084 inverse) -> nits-scaled relative light
    (same 10000/HDR_REF_WHITE_NITS scaling v1 used). Built ONCE at import;
    monotonic non-decreasing across the full byte range.
    """
    b = np.arange(256, dtype=np.float32)
    e = np.clip((b - 16.0) / 219.0, 0.0, 1.0)
    ep = e ** (1.0 / _PQ_M2)
    linear = (
        np.maximum(ep - _PQ_C1, 0.0) / (_PQ_C2 - _PQ_C3 * ep)
    ) ** (1.0 / _PQ_M1)
    rel = linear * np.float32(10000.0 / HDR_REF_WHITE_NITS)
    return rel.astype(np.float32)


# Module-level LUT: index with a uint8 array (any shape) to get linear light
# in the same units `hdr10_to_srgb`'s old step 3 produced. Per-byte (channel
# agnostic) -- `_LINEAR_LUT[bgr_roi]` yields linear values still in BGR order.
_LINEAR_LUT = _build_linear_lut()


def _tone_map_max_rgb(rel: np.ndarray) -> np.ndarray:
    """Hue-preserving max-RGB tone map (quick-task 260723-udg).

    Compresses only the per-sample MAX channel with a knee + C1-continuous
    exponential shoulder, then applies that same scale factor UNIFORMLY to
    all three channels. Because every channel is scaled by the identical
    factor ``f(m)/m``, both hue AND saturation are preserved exactly, and no
    channel can exceed 1.0 before the BT.2020->BT.709 primaries matrix.

    The shoulder is ``f(m) = 1 - (1 - k) * exp(-(m - k) / (1 - k))`` for
    ``m > k`` (identity for ``m <= k``), with ``k = _TONE_KNEE``. It is
    C1-continuous at the knee (``f(k) = k``, ``f'(k) = 1``) and asymptotes to
    1.0, so linear-light HDR white (~49.26) lands just under 1.0 instead of
    the ~0.5 midtone the old per-channel extended-Reinhard produced.

    Args:
        rel: (N, 3) or (3,) float32 array, RGB order, linear-light BT.2020.

    Returns:
        float32 array of the same shape, every channel <= 1.0.
    """
    arr = np.asarray(rel, dtype=np.float32)
    single = arr.ndim == 1
    if single:
        arr = arr[np.newaxis, :]

    k = _TONE_KNEE
    m = arr.max(axis=-1, keepdims=True)
    shoulder = np.float32(1.0) - (np.float32(1.0) - k) * np.exp(
        -(m - k) / (np.float32(1.0) - k)
    )
    fm = np.where(m > k, shoulder, m)
    with np.errstate(invalid="ignore", divide="ignore"):
        # Guard the achromatic-black sample: scale 1.0 keeps it black.
        scale = np.where(m > np.float32(1e-6), fm / m, np.float32(1.0))
    out = (arr * scale).astype(np.float32)
    if single:
        out = out[0]
    return out


def _compress_to_gamut_709(rel709: np.ndarray) -> np.ndarray:
    """Hue-preserving BT.709 gamut compression (quick-task 260723-udg).

    Replaces the old per-channel ``np.maximum(rel709, 0.0)`` clip -- which
    rotated hue (e.g. brown -> red) whenever the BT.2020->BT.709 matrix
    pushed a channel negative. Instead, out-of-[0,1] samples are lerped
    toward their own achromatic point (Rec.709 luma ``Y`` on all three
    channels) by the largest ``s in [0, 1]`` that lands every channel inside
    [0, 1]. Because the lerp is uniform per sample and the achromatic point
    has luma ``Y``, Rec.709 luma is preserved exactly and channel ordering is
    monotonically preserved. In-gamut samples pass through untouched.

    Args:
        rel709: (N, 3) or (3,) float32 array, RGB order, post-matrix values
            (roughly in [-0.3 .. 1.2]).

    Returns:
        float32 array of the same shape, every channel in [0, 1].
    """
    arr = np.asarray(rel709, dtype=np.float32)
    single = arr.ndim == 1
    if single:
        arr = arr[np.newaxis, :]

    y = (arr.astype(np.float64) @ _REC709_LUMA).astype(np.float32)[..., np.newaxis]
    out_of_gamut = np.any((arr < 0.0) | (arr > 1.0), axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        # Per-channel feasible s: Y/(Y-c) for c<0, (1-Y)/(c-Y) for c>1.
        s_low = np.where(arr < 0.0, y / (y - arr), np.float32(np.inf))
        s_high = np.where(
            arr > 1.0, (np.float32(1.0) - y) / (arr - y), np.float32(np.inf)
        )
        s = np.minimum(s_low, s_high).min(axis=-1, keepdims=True)
    s = np.clip(s, 0.0, 1.0)

    compressed = y + (arr - y) * s
    result = np.where(out_of_gamut, compressed, arr)
    # Degenerate achromatic luma (Y<=0 or Y>=1): plain clip for that sample.
    degenerate = (y <= 0.0) | (y >= np.float32(1.0))
    result = np.where(out_of_gamut & degenerate, np.clip(arr, 0.0, 1.0), result)
    result = np.clip(result, 0.0, 1.0).astype(np.float32)
    if single:
        result = result[0]
    return result


def _finish_linear_bt2020_to_srgb(rel: np.ndarray) -> np.ndarray:
    """Finish a linear-light BT.2020 (N,3)/(3,) array into sRGB uint8.

    v3 (quick-task 260723-udg): the old per-channel extended-Reinhard roll-off
    rotated hue and collapsed saturation on highlights (bright orange ->
    near-white yellow, which ``boost_saturation_rgb`` then rotated toward
    green; brown -> red via per-channel channel crush + the post-matrix
    negative clip). v3 instead (a) tone-maps the max-RGB scalar with a knee +
    exponential shoulder applied UNIFORMLY across channels (hue- and
    saturation-preserving, midtone crush eliminated -- diffuse white now lands
    ~0.91 instead of ~0.5), then (b) applies the BT.2020->BT.709 matrix, then
    (c) gamut-compresses toward the achromatic axis (hue-preserving lerp)
    instead of a per-channel negative clip, and finally (d) sRGB OETF encodes.

    Args:
        rel: (N, 3) or (3,) float32 array, RGB order, linear light relative
            to SDR reference white (i.e. already scaled so ~1.0 == diffuse
            white, matching `_LINEAR_LUT`'s output units).

    Returns:
        uint8 array of the same shape as ``rel``.
    """
    arr = np.asarray(rel, dtype=np.float32)
    single = arr.ndim == 1
    if single:
        arr = arr[np.newaxis, :]

    # Hue-preserving max-RGB tone map (uniform per-sample scale); every
    # channel <= 1.0 afterward.
    toned = _tone_map_max_rgb(arr)

    # BT.2020 -> BT.709 primaries matrix.
    rel709 = toned @ _BT2020_TO_BT709.T

    # Hue-preserving gamut compression toward the achromatic axis (replaces
    # the old per-channel negative clip).
    rel709 = _compress_to_gamut_709(rel709)

    # sRGB OETF encode (inverse of _gamma_expand).
    srgb = np.where(
        rel709 > 0.0031308,
        1.055 * (rel709 ** (1.0 / 2.4)) - 0.055,
        12.92 * rel709,
    )

    out = np.clip(srgb, 0.0, 1.0) * 255.0
    out = np.round(out).astype(np.uint8)
    if single:
        out = out[0]
    return out


def hdr10_to_srgb(rgb: np.ndarray) -> np.ndarray:
    """Convert an HDR10 (BT.2020 + PQ, limited-range) sample array to sRGB.

    Applies ONLY to the handful of sampled colors per region per frame
    (the (N,3) gradient arrays produced by ``sub_sample_gradient``) --
    never the full frame -- to stay within the streaming latency budget.

    v2 (260704-wy5): this is now the composition of the two halves used by
    the linear-averaging hdr paths -- ``_LINEAR_LUT`` (limited-range expand
    -> PQ EOTF -> linear) followed by ``_finish_linear_bt2020_to_srgb``
    (roll-off -> matrix -> sRGB encode). Kept as a single entry point for
    any caller converting an already-computed sample array (e.g. legacy
    callers); the actual HDR v2 fix -- averaging BEFORE conversion -- lives
    in ``extract_region_color``/``sub_sample_gradient``'s ``hdr=True`` path.

    Args:
        rgb: (N, 3) or (3,) array, RGB order, uint8 (or castable to it).

    Returns:
        uint8 array of the same shape as ``rgb``.
    """
    arr = np.asarray(rgb, dtype=np.uint8)
    rel = _LINEAR_LUT[arr]
    return _finish_linear_bt2020_to_srgb(rel)
