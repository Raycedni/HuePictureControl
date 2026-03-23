"""Color math utilities for Hue Entertainment API color conversion and region sampling.

Exports:
    GAMUT_C       -- Gamut C triangle vertices (all newer Hue lights)
    rgb_to_xy     -- Convert sRGB to CIE xy with Gamut C clamping
    build_polygon_mask -- Build a binary uint8 mask from normalized polygon coordinates
    extract_region_color -- Extract mean RGB from a frame within a polygon mask
"""
import math

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


def build_polygon_mask(
    normalized_points: list[list[float]],
    width: int = 640,
    height: int = 480,
) -> np.ndarray:
    """Build a binary uint8 mask for a polygon region from normalized coordinates.

    Coordinates are clamped with ``min(1.0, max(0.0, v)) * (dim - 1)`` before
    int conversion to prevent out-of-bounds indices at the frame boundary
    (Pitfall 4 in research).

    Args:
        normalized_points: List of [x, y] pairs in range [0..1]
        width: Frame width in pixels (default 640)
        height: Frame height in pixels (default 480)

    Returns:
        uint8 mask of shape (height, width) with 255 inside polygon, 0 outside
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
    return mask


def extract_region_color(
    frame: np.ndarray, mask: np.ndarray
) -> tuple[int, int, int]:
    """Extract mean BGR color from a frame within a polygon mask region.

    Args:
        frame: BGR uint8 numpy array from cv2.VideoCapture
        mask: uint8 mask from build_polygon_mask()

    Returns:
        (r, g, b) tuple of mean color in [0..255] range
    """
    # cv2.mean returns (B, G, R, alpha) for BGR images
    mean_bgr = cv2.mean(frame, mask=mask)
    b, g, r_val = int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])
    return r_val, g, b
