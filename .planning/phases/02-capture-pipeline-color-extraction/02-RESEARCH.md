# Phase 2: Capture Pipeline and Color Extraction - Research

**Researched:** 2026-03-23
**Domain:** OpenCV UVC capture, numpy polygon masking, CIE xy color conversion, FastAPI async integration
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CAPT-01 | Backend captures frames from a USB UVC device (HDMI capture card) at 640x480 MJPEG | `cv2.VideoCapture` with V4L2 backend; `CAP_PROP_FOURCC` set to MJPG; `CAP_PROP_FRAME_WIDTH/HEIGHT` set to 640/480 |
| CAPT-02 | Capture device path is configurable (e.g. `/dev/video0`) | `cv2.VideoCapture("/dev/video0")` accepts string paths on Linux; `os.getenv("CAPTURE_DEVICE")` + `PUT /api/capture/device` endpoint to reconfigure at runtime |
| CAPT-05 | A snapshot of the current camera frame is available via REST endpoint | `cv2.imencode(".jpg", frame)` + `fastapi.responses.Response(content=bytes, media_type="image/jpeg")` |
</phase_requirements>

---

## Summary

Phase 2 builds the frame capture pipeline and color extraction math that all downstream phases depend on. The technical domain spans three distinct areas: OpenCV UVC device capture in a Docker container, numpy polygon mask infrastructure for region color sampling, and RGB-to-CIE-xy color math with Gamut C clamping.

The primary challenge is keeping `cap.read()` from blocking the asyncio event loop. OpenCV's `VideoCapture.read()` is a synchronous blocking call — on a physical USB HDMI capture card at 640x480 MJPEG it will block for 10-40ms per frame. The standard solution is `asyncio.to_thread(cap.read)` (Python 3.9+), which delegates the call to a thread pool without occupying the event loop. This lets FastAPI remain responsive for REST calls during capture.

The color math (RGB to CIE xy) is a well-defined algorithm published by Philips in their SDK. The `rgbxy` library on PyPI implements it correctly for Gamut A/B/C, but it is lightly maintained (latest version 0.5, last release 2020). For a project with a Python 3.12 pin and active maintenance concerns, the algorithm is short enough to inline (roughly 20 lines). The phase description explicitly lists "inline or via rgbxy" — both are viable; inlining avoids a dependency on an unmaintained package.

**Primary recommendation:** Use `opencv-python-headless>=4.10` (headless variant required in Docker — no GUI backends). Open `VideoCapture` with the device path string and `cv2.CAP_V4L2` backend. Wrap `cap.read()` with `asyncio.to_thread`. Inline the RGB-to-CIE-xy Gamut C math rather than taking a dependency on the unmaintained `rgbxy` package.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| opencv-python-headless | >=4.10,<5 (latest: 4.13.0.92) | UVC frame capture, JPEG encoding, polygon mask creation | Headless variant avoids X11/GUI dependencies not available in Docker slim images; `cv2.VideoCapture`, `cv2.imencode`, `cv2.fillPoly`, `cv2.mean` all in core |
| numpy | >=1.26,<3 (bundled with opencv) | Polygon mask arrays, frame data manipulation | Required by opencv; zero-copy array slicing; `np.zeros` for mask creation |
| Python stdlib (math, os) | 3.12 (pinned) | CIE xy math (inline), environment variable config | No additional dependency for the 20-line color math |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rgbxy | 0.5 | RGB to CIE xy with Gamut A/B/C | Use if inlining the math is not preferred; caution — project last released 2020, no active maintenance |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `asyncio.to_thread(cap.read)` | Dedicated capture thread with `asyncio.Queue` | Thread+Queue adds more code complexity; `to_thread` is simpler and sufficient for single-consumer snapshot endpoint |
| Inline CIE xy math | `rgbxy` library | `rgbxy` is unmaintained (last release 2020); algorithm is 20 lines — inlining is lower risk |
| `opencv-python-headless` | `opencv-python` | `opencv-python` pulls in GTK/Qt GUI backends that require X11 libraries not in Docker slim images |

**Installation:**
```bash
pip install "opencv-python-headless>=4.10,<5"
```
`numpy` is pulled in automatically as a dependency. No additional packages required for the inline color math.

---

## Architecture Patterns

### Recommended Project Structure Extension

The existing `Backend/` structure gains a new service and router:

```
Backend/
├── main.py                     # Add: import routers.capture
├── routers/
│   ├── capture.py              # GET /api/capture/snapshot
│   │                           # PUT /api/capture/device (runtime device reconfiguration)
├── services/
│   ├── capture_service.py      # LatestFrameCapture class (asyncio-compatible)
│   └── color_math.py           # rgb_to_xy(r, g, b) with Gamut C clamping
│                               # extract_region_color(frame, mask) -> (r, g, b)
```

### Pattern 1: LatestFrameCapture — asyncio-Compatible Capture Class

**What:** A class that holds a `cv2.VideoCapture` object and a cached `_latest_frame`. Exposes an async `get_frame()` method that calls `cap.read()` via `asyncio.to_thread`. The class does not run a background loop — it is pull-based (frame captured on demand). This is correct for Phase 2 scope; Phase 3 will add a push-based loop.

**When to use:** All snapshot and color extraction calls in Phase 2.

```python
# Source: OpenCV docs + Python asyncio.to_thread docs (Python 3.9+)
import asyncio
import cv2
import numpy as np
import os
from typing import Optional

class LatestFrameCapture:
    def __init__(self, device_path: str = "/dev/video0"):
        self._device_path = device_path
        self._cap: Optional[cv2.VideoCapture] = None

    def open(self, device_path: Optional[str] = None) -> None:
        """Open or reopen the capture device. Closes any existing device first."""
        if self._cap is not None:
            self._cap.release()
        path = device_path or self._device_path
        self._device_path = path
        self._cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open capture device: {path}")
        # Request MJPEG at 640x480 — camera may silently refuse; verify with cap.get()
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    def release(self) -> None:
        """Release the capture device."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _read_frame(self):
        """Synchronous blocking read — call only via asyncio.to_thread."""
        if self._cap is None or not self._cap.isOpened():
            raise RuntimeError("Capture device is not open")
        ret, frame = self._cap.read()
        if not ret:
            raise RuntimeError("cap.read() returned False — device may be disconnected")
        return frame

    async def get_frame(self) -> np.ndarray:
        """Non-blocking async frame read; delegates blocking cap.read() to thread pool."""
        return await asyncio.to_thread(self._read_frame)
```

### Pattern 2: Pre-Computed Polygon Mask

**What:** Convert normalized [0..1] polygon coordinates to pixel coordinates at 640x480, then use `cv2.fillPoly` to create a binary uint8 mask once. Store the mask alongside the region. Recompute only when the polygon changes or the resolution changes.

**When to use:** At application startup and when region definitions are updated.

```python
# Source: OpenCV fillPoly docs + numpy docs
import cv2
import numpy as np

FRAME_WIDTH = 640
FRAME_HEIGHT = 480

def build_polygon_mask(
    normalized_points: list[list[float]],
    width: int = FRAME_WIDTH,
    height: int = FRAME_HEIGHT,
) -> np.ndarray:
    """
    Build a binary uint8 mask for a polygon region.

    Args:
        normalized_points: List of [x, y] pairs in range [0..1]
        width: Frame width in pixels
        height: Frame height in pixels

    Returns:
        uint8 mask array of shape (height, width) with 255 inside polygon, 0 outside
    """
    mask = np.zeros((height, width), dtype=np.uint8)
    pts = np.array(
        [[int(x * width), int(y * height)] for x, y in normalized_points],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [pts], color=255)
    return mask
```

### Pattern 3: Region Mean Color Extraction

**What:** Use `cv2.mean(frame, mask=mask)` to compute the mean BGR color within a polygon region. This is O(pixels) and fast — at 640x480 with a typical region covering 20% of the frame, this is ~61,000 pixel accesses, well under 1ms.

**When to use:** Every time a frame is captured and color values are needed.

```python
# Source: OpenCV docs — cv2.mean()
import cv2
import numpy as np

def extract_region_color(
    frame: np.ndarray, mask: np.ndarray
) -> tuple[int, int, int]:
    """
    Extract mean BGR color from a frame within a polygon mask region.

    Args:
        frame: BGR uint8 numpy array from cv2.VideoCapture
        mask: uint8 mask from build_polygon_mask()

    Returns:
        (r, g, b) tuple of mean color in [0..255] range
    """
    # cv2.mean returns (B, G, R, alpha) for BGR images
    mean_bgr = cv2.mean(frame, mask=mask)
    b, g, r = int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])
    return r, g, b
```

### Pattern 4: RGB to CIE xy with Gamut C Clamping (Inline)

**What:** Standard Philips Hue color conversion algorithm. Newer Hue lights (all Gen 3+, LightStrips Plus, Festavia, Flux) use Gamut C. The algorithm: normalize RGB to [0..1], apply gamma expansion, multiply by Wide RGB D65 matrix to get XYZ, normalize to xy chromaticity, then clamp to Gamut C triangle.

**When to use:** After `extract_region_color`, before sending to the Hue bridge.

```python
# Source: Philips Hue SDK ApplicationDesignNotes/RGB to xy Color conversion.md
# https://github.com/johnciech/PhilipsHueSDK/blob/master/ApplicationDesignNotes/RGB%20to%20xy%20Color%20conversion.md
import math

# Gamut C triangle — all newer Hue lights (Gen 3 A19, BR30, Go, LightStrips Plus, Festavia, Flux)
GAMUT_C = {
    "red":   (0.692, 0.308),
    "green": (0.17,  0.7),
    "blue":  (0.153, 0.048),
}

def _cross_product(p1: tuple, p2: tuple) -> float:
    return p1[0] * p2[1] - p1[1] * p2[0]

def _closest_point_on_segment(
    a: tuple, b: tuple, p: tuple
) -> tuple[float, float]:
    """Return the closest point on segment [a, b] to point p."""
    ab = (b[0] - a[0], b[1] - a[1])
    ap = (p[0] - a[0], p[1] - a[1])
    t = (ap[0] * ab[0] + ap[1] * ab[1]) / (ab[0] ** 2 + ab[1] ** 2 + 1e-10)
    t = max(0.0, min(1.0, t))
    return (a[0] + t * ab[0], a[1] + t * ab[1])

def _in_gamut(x: float, y: float, gamut: dict) -> bool:
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

def _clamp_to_gamut(x: float, y: float, gamut: dict) -> tuple[float, float]:
    r, g, b = gamut["red"], gamut["green"], gamut["blue"]
    candidates = [
        _closest_point_on_segment(r, g, (x, y)),
        _closest_point_on_segment(g, b, (x, y)),
        _closest_point_on_segment(b, r, (x, y)),
    ]
    # Pick the candidate closest to the original (x, y)
    best = min(candidates, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
    return best

def rgb_to_xy(r: int, g: int, b: int) -> tuple[float, float]:
    """
    Convert sRGB (0-255) to CIE xy with Gamut C clamping.

    Args:
        r, g, b: sRGB channel values in range 0-255

    Returns:
        (x, y) CIE xy chromaticity coordinates, clamped to Gamut C
    """
    # Step 1: normalize
    r_f, g_f, b_f = r / 255.0, g / 255.0, b / 255.0

    # Step 2: gamma expansion (sRGB to linear)
    def gamma(v: float) -> float:
        return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92

    r_lin, g_lin, b_lin = gamma(r_f), gamma(g_f), gamma(b_f)

    # Step 3: Wide RGB D65 matrix to XYZ
    X = r_lin * 0.649926 + g_lin * 0.103455 + b_lin * 0.197109
    Y = r_lin * 0.234327 + g_lin * 0.743075 + b_lin * 0.022598
    Z = r_lin * 0.0       + g_lin * 0.053077 + b_lin * 1.035763

    # Step 4: XYZ to xy chromaticity
    denom = X + Y + Z
    if denom < 1e-10:
        return (0.3127, 0.3290)  # D65 white point fallback for black input
    cx, cy = X / denom, Y / denom

    # Step 5: clamp to Gamut C
    if not _in_gamut(cx, cy, GAMUT_C):
        cx, cy = _clamp_to_gamut(cx, cy, GAMUT_C)

    return round(cx, 4), round(cy, 4)
```

### Pattern 5: Snapshot REST Endpoint

**What:** `GET /api/capture/snapshot` captures one frame, JPEG-encodes it with `cv2.imencode`, returns raw bytes with `Content-Type: image/jpeg`. Uses `Response` not `StreamingResponse` since the full frame is in memory.

**When to use:** Phase 2 debugging and Phase 4 UI region-drawing canvas.

```python
# Source: FastAPI custom response docs + OpenCV imencode docs
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
import cv2

router = APIRouter(prefix="/api/capture", tags=["capture"])

@router.get("/snapshot")
async def snapshot(request: Request) -> Response:
    """Capture and return the current camera frame as JPEG."""
    capture_service = request.app.state.capture
    try:
        frame = await capture_service.get_frame()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode frame as JPEG")

    return Response(content=buf.tobytes(), media_type="image/jpeg")
```

### Pattern 6: Runtime Device Path Reconfiguration

**What:** A `PUT /api/capture/device` endpoint accepts a new device path (e.g. `/dev/video1`) and calls `capture_service.open(new_path)` to switch without restarting. This satisfies CAPT-02 without a container restart.

**When to use:** Whenever the user needs to select a different video device.

```python
# Source: FastAPI docs
from pydantic import BaseModel

class SetDeviceRequest(BaseModel):
    device_path: str   # e.g. "/dev/video1"

@router.put("/device")
async def set_device(body: SetDeviceRequest, request: Request) -> dict:
    """Switch capture device without restarting the container."""
    capture_service = request.app.state.capture
    try:
        capture_service.open(body.device_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"device_path": body.device_path, "status": "opened"}
```

### Pattern 7: Lifespan Integration

**What:** Instantiate `LatestFrameCapture` in the FastAPI lifespan, store on `app.state`, and release on shutdown. Read the initial device path from the `CAPTURE_DEVICE` environment variable (fallback `/dev/video0`).

```python
# Source: FastAPI lifespan docs (extends existing main.py pattern)
import os

CAPTURE_DEVICE = os.getenv("CAPTURE_DEVICE", "/dev/video0")

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await init_db(DATABASE_PATH)
    app.state.db = db

    from services.capture_service import LatestFrameCapture
    capture = LatestFrameCapture(CAPTURE_DEVICE)
    capture.open()         # Opens device on startup; may raise if device absent
    app.state.capture = capture

    yield

    capture.release()
    await close_db(db)
```

### Anti-Patterns to Avoid

- **Calling `cap.read()` directly in an `async def` endpoint:** Even a 15ms read blocks the entire asyncio event loop, causing all other requests to queue. Always use `asyncio.to_thread(capture._read_frame)`.
- **Using `opencv-python` (with GUI) in Docker:** This pulls in GTK and X11 libraries that are not in `python:3.12-slim`. The install will fail or produce import errors at runtime. Use `opencv-python-headless` exclusively.
- **Recomputing polygon masks on every frame:** `cv2.fillPoly` is O(polygon_area) and must create a new numpy array. Pre-compute masks once, cache them, recompute only when polygon coordinates change.
- **Opening VideoCapture with integer 0 instead of string "/dev/video0":** Integer indices are assigned by the kernel at boot and can change when other video devices are present. String paths (or `/dev/v4l/by-id/...`) are stable. CAPT-02 requires configurable path — string-based from the start.
- **Setting FOURCC before opening the device:** `CAP_PROP_FOURCC` must be set after `cap.open()` (or after the constructor opens it). The sequence is: open, then set properties.
- **Assuming MJPEG mode was applied:** `cap.set(CAP_PROP_FOURCC, ...)` does not raise on failure — some devices silently ignore it. Log the actual fourcc after setting: `actual = cap.get(cv2.CAP_PROP_FOURCC)`. The device may run YUYV instead; this still works but has higher CPU cost.
- **Crashing lifespan if device is absent at startup:** In a testable deployment, the capture card may not be plugged in. Consider making `capture.open()` non-fatal at startup (log a warning, leave `_cap = None`) and returning HTTP 503 from the snapshot endpoint instead of crashing the server.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JPEG encoding of numpy array | Custom binary JPEG writer | `cv2.imencode(".jpg", frame)` | Single line; JPEG compression is non-trivial |
| Polygon rasterization | Custom scanline fill | `cv2.fillPoly(mask, [pts], 255)` | Handles concave polygons, sub-pixel edges, correct winding |
| Mean of pixels within polygon | Custom pixel iterator | `cv2.mean(frame, mask=mask)` | SIMD-accelerated C++ loop; Python loop would be 100x slower |
| RGB to CIE xy with gamut clamping | K-means or averaging in HSV | Inline Gamut C algorithm (Pattern 4) | The triangle-clamp algorithm is the correct Hue API requirement; simpler approaches produce out-of-gamut colors that the bridge silently ignores or clips |
| Async blocking I/O wrapper for cap.read | Custom threading with Event/Queue | `asyncio.to_thread(cap.read)` | Python 3.9+ stdlib; correct cancellation semantics; no extra thread management |

**Key insight:** OpenCV's `cv2.mean()` with a mask is the correct tool for this use case. It is not a naive loop — it is hardware-accelerated and runs in <1ms for a 640x480 region. There is no reason to implement alternative averaging strategies in Phase 2.

---

## Common Pitfalls

### Pitfall 1: FOURCC/Format Not Actually Applied
**What goes wrong:** `cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))` returns `True` but the device is still delivering YUYV. No error is raised.
**Why it happens:** Not all UVC devices support MJPEG at all resolutions; the V4L2 driver silently falls back.
**How to avoid:** After setting properties, call `actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))` and log it as a 4-char code: `struct.pack("<I", actual_fourcc).decode("ascii", errors="replace")`. YUYV fallback still works — it just uses more CPU for decode.
**Warning signs:** High CPU usage; frames arriving at lower rate than expected.

### Pitfall 2: `asyncio.to_thread` Not Available (Python 3.8)
**What goes wrong:** `AttributeError: module 'asyncio' has no attribute 'to_thread'`
**Why it happens:** `asyncio.to_thread` was added in Python 3.9. The project pins Python 3.12, so this is not a risk — but the alternative `loop.run_in_executor(None, func)` is equivalent if encountered in testing.
**How to avoid:** Non-issue on this project (Python 3.12 pinned). Note: `asyncio.to_thread` is preferred over `loop.run_in_executor(None, func)` in modern code — both work identically.
**Warning signs:** ImportError or AttributeError on the `asyncio.to_thread` call.

### Pitfall 3: VideoCapture Silently Fails in Docker Without video Group
**What goes wrong:** `LatestFrameCapture.open()` raises `RuntimeError: Could not open capture device: /dev/video0` even though the device is passed through.
**Why it happens:** The `python:3.12-slim` container process does not have supplementary group `video` (GID 44). The device file exists but is inaccessible.
**How to avoid:** `group_add: [video]` in docker-compose.yaml (already documented in Phase 1 research, INFR-02). Verify with `docker exec <container> ls -la /dev/video0`.
**Warning signs:** `cap.isOpened()` returns False; no specific error logged.

### Pitfall 4: Normalized Coordinates Must Be Clamped Before Pixel Conversion
**What goes wrong:** `int(x * 640)` for x values near 1.0 produces pixel index 640, which is out of bounds for a 640-wide image (valid indices: 0-639). `cv2.fillPoly` may silently clip or cause unexpected mask shapes.
**Why it happens:** Floating point rounding; user drawing slightly outside canvas edges.
**How to avoid:** Clamp coordinates: `int(max(0.0, min(1.0, x)) * (width - 1))`. Apply the clamp in `build_polygon_mask()`.
**Warning signs:** Mask edges cut off; region color extraction returns incorrect values for edge regions.

### Pitfall 5: Black Frame (All Zeros) From cap.read During First Frames
**What goes wrong:** The first 1-3 frames after opening `VideoCapture` are black or have garbage data. The snapshot endpoint returns a black JPEG on startup.
**Why it happens:** UVC devices need a few frames to stabilize AGC/AEC (auto gain/exposure control). The driver buffer fills with empty frames initially.
**How to avoid:** On `open()`, discard the first 3 frames: `for _ in range(3): cap.read()`. This can be done synchronously in `open()` since it runs at startup, not in the hot path.
**Warning signs:** `GET /api/capture/snapshot` immediately after startup returns a black image.

### Pitfall 6: CIE xy Returns NaN or (0,0) for Pure Black Input
**What goes wrong:** `rgb_to_xy(0, 0, 0)` calculates X=Y=Z=0, then divides by 0.
**Why it happens:** Black input maps to XYZ = (0, 0, 0); chromaticity is undefined for zero luminance.
**How to avoid:** Guard the denominator: if `X + Y + Z < 1e-10`, return the D65 white point `(0.3127, 0.3290)` or a neutral low-luminance xy. See the implementation in Pattern 4.
**Warning signs:** `nan` values sent to the bridge; Hue Entertainment API ignores or crashes on malformed xy values.

### Pitfall 7: opencv-python (with GUI) Installed Instead of opencv-python-headless
**What goes wrong:** `pip install opencv-python` in Docker pulls in `libgtk-3-dev`, `libglib2.0`, and Qt libraries that aren't in `python:3.12-slim`. The pip install either fails (missing system headers) or the import succeeds but crashes at runtime when cv2 tries to initialize a GUI backend.
**Why it happens:** `opencv-python` includes full GUI support; the headless variant strips all display code.
**How to avoid:** Always use `opencv-python-headless` in Docker. If both packages are present in the same environment, they conflict.
**Warning signs:** `ImportError: libGL.so.1` on `import cv2`; or `ModuleNotFoundError: No module named 'cv2'` after a failed install.

---

## Code Examples

Verified patterns from official sources:

### VideoCapture with MJPEG at 640x480 (V4L2 Backend)
```python
# Source: OpenCV VideoCapture docs + cv2.CAP_V4L2 backend flags
import cv2

cap = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

print(f"Opened: {cap.isOpened()}")
print(f"Width: {cap.get(cv2.CAP_PROP_FRAME_WIDTH)}")
print(f"Height: {cap.get(cv2.CAP_PROP_FRAME_HEIGHT)}")
```

### Polygon Mask + Color Extraction (End-to-End)
```python
# Source: OpenCV fillPoly + cv2.mean docs
import cv2
import numpy as np

frame = ...   # np.ndarray from cap.read()

# Polygon in normalized coords (e.g. left-third of frame)
normalized_points = [[0.0, 0.0], [0.33, 0.0], [0.33, 1.0], [0.0, 1.0]]
mask = np.zeros((480, 640), dtype=np.uint8)
pts = np.array([[int(x * 640), int(y * 480)] for x, y in normalized_points], dtype=np.int32)
cv2.fillPoly(mask, [pts], 255)

# Extract mean color from region
mean_bgr = cv2.mean(frame, mask=mask)
b, g, r = int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])
print(f"Region mean color: R={r} G={g} B={b}")
```

### JPEG Snapshot Response
```python
# Source: FastAPI Response docs + OpenCV imencode docs
import cv2
from fastapi.responses import Response

frame = ...   # np.ndarray from cap.read()
ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
jpeg_bytes = buf.tobytes()
return Response(content=jpeg_bytes, media_type="image/jpeg")
```

### asyncio.to_thread for Blocking cap.read
```python
# Source: Python 3.12 asyncio docs — asyncio.to_thread()
import asyncio
import cv2

cap = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)

def _blocking_read():
    ret, frame = cap.read()
    if not ret:
        raise RuntimeError("cap.read() failed")
    return frame

async def get_frame():
    return await asyncio.to_thread(_blocking_read)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `opencv-python` in Docker | `opencv-python-headless` | 2018 (headless variant added) | Eliminates X11/GTK dependency pull; smaller Docker images |
| `loop.run_in_executor(None, func)` | `asyncio.to_thread(func)` | Python 3.9 (2020) | Simpler syntax; same semantics; cleaner cancellation |
| Integer camera index `VideoCapture(0)` | String device path `VideoCapture("/dev/video0")` | Always supported on Linux | Stable under multiple device configurations; required for CAPT-02 |
| `rgbxy` library for Hue color conversion | Inline algorithm per Philips SDK notes | `rgbxy` last released 2020 | Removes unmaintained dependency; 20-line implementation is equivalent |

**Deprecated/outdated:**
- `cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')` (4-char form): still works but `cv2.VideoWriter_fourcc(*"MJPG")` is idiomatic Python
- `loop.run_in_executor()`: replaced by `asyncio.to_thread()` in Python 3.9+ — use the newer form

---

## Open Questions

1. **MJPEG mode acceptance on the specific capture card**
   - What we know: Most USB HDMI capture cards support MJPEG at 640x480; setting `CAP_PROP_FOURCC` should work
   - What's unclear: The specific card model is not documented; MJPEG may not be available at 640x480 (only at higher resolutions); the driver may deliver YUYV
   - Recommendation: Log the actual fourcc after opening. YUYV fallback still works — add a debug log warning if MJPEG was requested but not granted. Measure `cap.read()` blocking time with a stopwatch (`time.perf_counter()`) and log it at first frame.

2. **Lifespan behavior when capture device is absent**
   - What we know: `VideoCapture.open()` with a non-existent device path returns a non-opened capture object (no exception)
   - What's unclear: Whether a hard crash in lifespan is acceptable (the container will restart) or whether the snapshot endpoint should return 503
   - Recommendation: Make `capture.open()` non-fatal in lifespan (log an error, don't raise). The snapshot endpoint should check `_cap is None` and return HTTP 503. This makes the backend testable without hardware.

3. **`asyncio.to_thread` thread pool saturation under concurrent snapshot requests**
   - What we know: The default thread pool is `min(32, os.cpu_count() + 4)` threads
   - What's unclear: Whether concurrent snapshot calls queue or block on the same `cap.read()` (since VideoCapture is not thread-safe)
   - Recommendation: Add a `asyncio.Lock` around `get_frame()` to serialize concurrent reads. In Phase 2, the snapshot endpoint is unlikely to be called concurrently, but the lock prevents potential corruption.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.x + pytest-asyncio 0.24.x (already installed) |
| Config file | `Backend/pytest.ini` (already exists: `asyncio_mode = auto`) |
| Quick run command | `cd /mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/Backend && python -m pytest tests/ -x -q` |
| Full suite command | `cd /mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/Backend && python -m pytest tests/ -v` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAPT-01 | LatestFrameCapture.open() calls cv2.VideoCapture with MJPG at 640x480 | unit (mock cv2) | `pytest tests/test_capture_service.py::test_open_sets_mjpg_640_480 -x` | Wave 0 |
| CAPT-01 | get_frame() awaits asyncio.to_thread and returns numpy array | unit (mock cap.read) | `pytest tests/test_capture_service.py::test_get_frame_returns_array -x` | Wave 0 |
| CAPT-01 | get_frame() raises RuntimeError when cap is None | unit | `pytest tests/test_capture_service.py::test_get_frame_no_device -x` | Wave 0 |
| CAPT-02 | PUT /api/capture/device reopens capture with new path | unit (mock LatestFrameCapture) | `pytest tests/test_capture_router.py::test_set_device_reopens -x` | Wave 0 |
| CAPT-02 | CAPTURE_DEVICE env var sets initial device path | unit (mock env + cap) | `pytest tests/test_capture_service.py::test_env_device_path -x` | Wave 0 |
| CAPT-05 | GET /api/capture/snapshot returns 200 with image/jpeg content-type | unit (mock get_frame + cv2.imencode) | `pytest tests/test_capture_router.py::test_snapshot_returns_jpeg -x` | Wave 0 |
| CAPT-05 | GET /api/capture/snapshot returns 503 when device not open | unit | `pytest tests/test_capture_router.py::test_snapshot_no_device_503 -x` | Wave 0 |
| CAPT-05 | Snapshot on real hardware returns JPEG within 200ms | smoke (physical hardware) | manual — requires capture card | manual-only |
| color math | rgb_to_xy(255, 0, 0) returns point within Gamut C triangle | unit | `pytest tests/test_color_math.py::test_red_in_gamut -x` | Wave 0 |
| color math | rgb_to_xy(0, 0, 0) does not raise; returns valid xy | unit | `pytest tests/test_color_math.py::test_black_no_divide_by_zero -x` | Wave 0 |
| color math | Out-of-gamut xy is clamped to nearest triangle edge | unit | `pytest tests/test_color_math.py::test_out_of_gamut_clamped -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `cd /mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/Backend && python -m pytest tests/ -x -q`
- **Per wave merge:** `cd /mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/Backend && python -m pytest tests/ -v`
- **Phase gate:** All automated tests green + `GET /api/capture/snapshot` on physical hardware returns JPEG within 200ms

### Wave 0 Gaps

- [ ] `Backend/tests/test_capture_service.py` — covers CAPT-01, CAPT-02 (service layer tests with mocked cv2)
- [ ] `Backend/tests/test_capture_router.py` — covers CAPT-05 (router tests with mocked capture_service)
- [ ] `Backend/tests/test_color_math.py` — covers rgb_to_xy correctness, gamut clamping, black/white edge cases
- [ ] Framework install: `pip install opencv-python-headless>=4.10,<5` — add to `Backend/requirements.txt`

---

## Sources

### Primary (HIGH confidence)
- [OpenCV VideoCapture Class Reference](https://docs.opencv.org/3.4/d8/dfe/classcv_1_1VideoCapture.html) — open, set, get, read API
- [OpenCV VideoCapture Flags](https://docs.opencv.org/3.4/d4/d15/group__videoio__flags__base.html) — CAP_PROP_FOURCC, CAP_V4L2, CAP_PROP_FRAME_WIDTH/HEIGHT
- [Philips Hue SDK — RGB to xy Color conversion](https://github.com/johnciech/PhilipsHueSDK/blob/master/ApplicationDesignNotes/RGB%20to%20xy%20Color%20conversion.md) — canonical color math algorithm with Gamut triangle points
- [FastAPI Custom Response docs](https://fastapi.tiangolo.com/advanced/custom-response/) — Response with media_type="image/jpeg"
- [Python asyncio.to_thread docs](https://docs.python.org/3/library/asyncio-eventloop.html) — blocking I/O executor pattern
- [opencv-python-headless PyPI](https://pypi.org/project/opencv-python-headless/) — version 4.13.0.92, Python 3.12 supported
- [benknight/hue-python-rgb-converter](https://github.com/benknight/hue-python-rgb-converter/blob/master/rgbxy/__init__.py) — reference implementation with Gamut C (Red: 0.692,0.308; Green: 0.17,0.7; Blue: 0.153,0.048)

### Secondary (MEDIUM confidence)
- [OpenCV forum — MJPG UVC format selection](https://forum.opencv.org/t/help-with-video-capturing-for-mjpg/12814) — FOURCC set after open; verify with get()
- [SuperFastPython — asyncio.to_thread](https://superfastpython.com/asyncio-to_thread/) — thread pool details, Python 3.9+ semantics
- [PyImageSearch — Image Masking with OpenCV](https://pyimagesearch.com/2021/01/19/image-masking-with-opencv/) — fillPoly + cv2.mean pattern verified

### Tertiary (LOW confidence)
- `cap.read()` blocking duration on specific HDMI capture card at 640x480 MJPEG: empirically unknown; estimate 10-40ms from community reports — must be measured during Phase 2 integration
- Whether the specific capture card supports MJPEG at exactly 640x480: unknown until hardware test

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — opencv-python-headless version confirmed via PyPI; numpy bundled; algorithm sourced from official Philips SDK docs
- Architecture: HIGH — patterns derived from OpenCV docs, FastAPI docs, Python asyncio docs
- Color math: HIGH — algorithm taken verbatim from Philips HueSDK ApplicationDesignNotes; Gamut C coordinates cross-referenced between two sources (Philips SDK notes + rgbxy library)
- Pitfalls: MEDIUM-HIGH — Docker/group_add from Phase 1 confirmed; MJPEG acceptance is hardware-dependent (LOW on specific card)

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (opencv-python-headless stable; color math algorithm is permanent; asyncio API is stable)
