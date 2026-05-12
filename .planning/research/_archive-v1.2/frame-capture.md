# Frame Capture and Color Analysis Research

**Project:** HuePictureControl
**Domain:** Real-time ambient lighting via HDMI capture card + Philips Hue
**Researched:** 2026-03-23
**Overall confidence:** HIGH (stack decisions), MEDIUM (performance figures — benchmarks inferred from working projects, not microbenchmarks)

---

## 1. Capturing Frames from a USB UVC Device in Python

### Primary approach: OpenCV VideoCapture over V4L2

OpenCV's `cv2.VideoCapture` is the correct primary tool. On Linux, it uses the V4L2 kernel subsystem under the hood. USB capture cards that present themselves as UVC devices appear as `/dev/videoN` nodes and are read identically to webcams.

```python
import cv2

cap = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)

# Force MJPEG — critical for bandwidth and latency (see Section 2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))

# Set capture resolution (see Section 2 for rationale)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

# Attempt to minimize internal buffer — reduces stale-frame lag
# Note: V4L2 may silently ignore this; use threaded capture as fallback
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
```

**Explicitly specifying `cv2.CAP_V4L2`** is important: without it, OpenCV may fall back to GStreamer or FFMPEG backends which introduce additional latency layers.

### Why MJPEG matters

USB bandwidth is limited. At 1080p 30fps, raw YUYV 4:2:2 requires ~1.5 Gbps — far beyond USB 2.0 (480 Mbps). MJPEG compresses on the capture card before USB transfer, enabling 1080p or 720p at 30+ fps within USB bandwidth. Without requesting MJPEG, the driver typically caps at 640x480 in raw YUYV.

```python
# Verify the format was accepted
actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
codec = "".join([chr((actual_fourcc >> 8 * i) & 0xFF) for i in range(4)])
print(f"Codec: {codec}")  # Should print "MJPG"
```

### The buffer problem and threaded capture

OpenCV maintains an internal frame buffer. If processing takes longer than the capture interval, frames queue up and you end up reading stale data. For a real-time ambient system this is unacceptable.

**Solution: dedicated capture thread that always discards all but the latest frame.**

```python
import threading
import cv2
import time

class LatestFrameCapture:
    """
    Runs capture in a background thread. read() always returns the
    most recent frame, never a buffered-up stale one.
    """

    def __init__(self, device: str = "/dev/video0", width: int = 640, height: int = 480, fps: int = 30):
        self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._frame = None
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        while self._running:
            ret, frame = self.cap.read()
            if ret:
                with self._lock:
                    self._frame = frame

    def read(self):
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def stop(self):
        self._running = False
        self._thread.join()
        self.cap.release()
```

### Alternative: v4l2py (direct V4L2, bypasses OpenCV overhead)

The `v4l2py` library (PyPI: `v4l2py`) provides direct Python bindings to V4L2. It avoids OpenCV's internal JPEG decode for MJPEG — you receive raw bytes and can decode with `turbojpeg` (libjpeg-turbo), which is ~3-5x faster than OpenCV's JPEG decode. This is worth considering if profiling shows JPEG decode is a bottleneck.

```python
# pip install v4l2py PyTurboJPEG
from v4l2py import Device
from turbojpeg import TurboJPEG
import numpy as np

jpeg = TurboJPEG()

with Device.from_id(0) as cam:
    cam.set_format(640, 480, "MJPG")
    for frame in cam:
        img = jpeg.decode(bytes(frame))  # numpy array, BGR
        # process img...
```

**Confidence:** HIGH — OpenCV + V4L2 is the proven path used by HarmonizeProject and similar ambilight implementations.

---

## 2. Capture Resolution: The Sweet Spot

### Why 4K/1080p is wasteful for color analysis

Color analysis for ambient lighting does not need pixel-accurate detail. It needs the average/dominant color within broad spatial zones. A 640x480 frame has 307,200 pixels — more than enough to compute accurate zone averages. Capturing at 1080p (2,073,600 pixels) multiplies processing work ~6.7x with negligible improvement in color accuracy for large zones.

### Recommended: capture at 640x480, optionally downscale further

| Capture resolution | Pixels | Relative processing load | Notes |
|---|---|---|---|
| 3840x2160 (4K) | 8.3M | ~27x baseline | Wasteful; USB bandwidth issue |
| 1920x1080 (1080p) | 2.1M | ~6.7x baseline | OK if card requires it for MJPEG |
| 1280x720 (720p) | 921K | ~3x baseline | Good balance if 480p unavailable |
| **640x480 (480p)** | **307K** | **1x baseline** | **Recommended default** |
| 320x240 | 76K | 0.25x baseline | Acceptable; slight color averaging artifacts |

**Recommendation:** Configure the capture device to 640x480 MJPEG 30fps. If the capture card does not support 480p (some only advertise 720p/1080p), capture at the lowest supported resolution and `cv2.resize()` down to 640x480 immediately after decode using `cv2.INTER_AREA` (best quality for downscaling).

```python
frame_small = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)
```

For zone analysis, you can go even smaller. A 320x240 intermediate used purely for color extraction would reduce numpy operations 4x vs 640x480 with minimal perceptual difference in final light color. Consider this if profiling shows the color analysis step is the bottleneck.

**Confidence:** HIGH — this matches the practice of existing ambilight projects (HarmonizeProject uses 640x480@50fps equivalent; Hyperion recommends similar).

---

## 3. Extracting Dominant Colors from Polygon Regions

### The masking pipeline

Each "zone" is defined as a polygon of pixel coordinates in the (potentially scaled) frame. The core pipeline per frame:

1. Pre-compute all zone masks once at startup (they don't change between frames)
2. For each frame, iterate zones and extract masked pixel arrays
3. Compute the dominant color from each pixel array

**Critical insight: pre-compute masks.** Creating a `cv2.fillPoly` mask is the expensive part (~200–400 µs per polygon). Done once at startup and reused every frame, this cost disappears.

```python
import cv2
import numpy as np

def precompute_masks(zones: list[list[tuple[int,int]]], frame_shape: tuple) -> list[np.ndarray]:
    """
    zones: list of polygon vertex lists, e.g.
           [[(0,0),(100,0),(100,100),(0,100)], ...]
    frame_shape: (height, width) of the (possibly downscaled) frame
    Returns list of uint8 masks, one per zone.
    """
    h, w = frame_shape
    masks = []
    for vertices in zones:
        mask = np.zeros((h, w), dtype=np.uint8)
        pts = np.array(vertices, dtype=np.int32).reshape((-1, 1, 2))
        cv2.fillPoly(mask, [pts], 255)
        masks.append(mask)
    return masks
```

### Color extraction algorithms

There are three practical approaches, each with different speed/quality tradeoffs:

#### Option A: Mean color (fastest, ~50–200 µs per zone)

Returns the average RGB of all pixels in the zone. For ambient lighting this is usually exactly what you want — you do not need the most "interesting" color, you need the representative color.

```python
def extract_mean_color(frame_bgr: np.ndarray, mask: np.ndarray) -> tuple[int, int, int]:
    # cv2.mean returns (B, G, R, _) when given a mask
    b, g, r, _ = cv2.mean(frame_bgr, mask=mask)
    return int(r), int(g), int(b)
```

**Performance:** `cv2.mean()` with a mask is a single C-accelerated call. For a 640x480 frame with 16 zones, total extraction is approximately 1–3 ms. This is the recommended approach.

#### Option B: Weighted mean in a different color space (MEDIUM, ~1–3 ms per zone)

Mean in RGB can be skewed by large neutral/dark areas. Computing mean in HSV and weighting by saturation emphasises vivid pixels.

```python
def extract_vivid_mean(frame_bgr: np.ndarray, mask: np.ndarray) -> tuple[int, int, int]:
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    masked_pixels = frame_bgr[mask == 255]   # shape: (N, 3)
    masked_hsv    = hsv[mask == 255]

    saturations = masked_hsv[:, 1].astype(np.float32) + 1.0  # avoid zero weights
    weights = saturations / saturations.sum()

    r = int(np.dot(weights, masked_pixels[:, 2]))
    g = int(np.dot(weights, masked_pixels[:, 1]))
    b = int(np.dot(weights, masked_pixels[:, 0]))
    return r, g, b
```

This adds a `frame_bgr[mask == 255]` array extraction step which allocates memory per call — avoid in the hot path unless you can confirm better perceptual results justify the cost.

#### Option C: K-means dominant color (SLOWEST, ~5–30 ms per zone)

Returns the single most-represented cluster center. Overkill for ambient lighting — use only if zones contain high contrast (e.g., half sky, half ground) and you want the "winner" rather than the blend.

```python
from sklearn.cluster import MiniBatchKMeans

def extract_dominant_kmeans(frame_bgr: np.ndarray, mask: np.ndarray, k: int = 1) -> tuple[int, int, int]:
    pixels = frame_bgr[mask == 255].reshape(-1, 3).astype(np.float32)
    if len(pixels) < k:
        return 0, 0, 0
    kmeans = MiniBatchKMeans(n_clusters=k, n_init=3)
    kmeans.fit(pixels)
    # For k=1, center IS the dominant color
    b, g, r = kmeans.cluster_centers_[0].astype(int)
    return int(r), int(g), int(b)
```

**Do not use this in the hot path for 16 zones at 30fps.** MiniBatchKMeans on even 5,000 pixels takes ~5ms per call, putting 16 zones at ~80ms — blowing the entire budget.

### Recommendation

**Use mean color (Option A) as the default.** It is fast enough that 16+ zones consume <5ms total. If you want vivid-bias without the cost, apply a simple pre-processing step: histogram-equalize the saturation channel of the downscaled frame once, then run mean — this biases the mean toward vivid pixels without per-zone weight calculations.

### Full batch extraction loop

```python
def extract_all_zones(
    frame_bgr: np.ndarray,
    masks: list[np.ndarray]
) -> list[tuple[int, int, int]]:
    """
    Returns list of (R, G, B) tuples, one per zone.
    Assumes masks were pre-computed at the correct resolution.
    """
    results = []
    for mask in masks:
        b, g, r, _ = cv2.mean(frame_bgr, mask=mask)
        results.append((int(r), int(g), int(b)))
    return results
```

**Confidence:** HIGH — `cv2.mean` with mask is a standard, well-documented OpenCV operation. Performance figures are based on known characteristics of C-accelerated OpenCV calls on typical modern hardware.

---

## 4. Frame Rate: How Much Do You Need?

### The human perception argument

The Philips Hue Zigbee radio can only update lights at ~25Hz. The Entertainment API bridge accepts up to 60 updates/second but the lights themselves physically change at approximately 12.5–25Hz. This creates a ceiling: there is no perceptual benefit to analyzing frames faster than the lights can respond.

### Recommended target: 20–25 fps analysis rate

| Rate | Frame interval | Suitable? | Notes |
|---|---|---|---|
| 60 fps | 16.7 ms | Marginal | Leaves <34ms for everything else; only if CPU is fast |
| **25 fps** | **40 ms** | **Yes** | **Comfortable budget; matches light update ceiling** |
| 20 fps | 50 ms | Yes | More headroom; still smooth |
| 10 fps | 100 ms | Acceptable | Noticeable lag on fast cuts |
| 5 fps | 200 ms | Poor | Visible stutter |

**Recommendation:** Target 25fps (every other frame if capturing at 50fps). This gives a 40ms budget per cycle and comfortably accommodates the light hardware ceiling. The capture thread can run at full device rate (30fps) while the analysis loop processes every frame or every other frame depending on load.

```python
import time

ANALYSIS_INTERVAL = 1 / 25  # 40ms

last_analysis = 0
while True:
    frame = capture.read()
    now = time.monotonic()
    if now - last_analysis >= ANALYSIS_INTERVAL:
        colors = extract_all_zones(frame, masks)
        send_to_hue(colors)
        last_analysis = now
```

**Confidence:** MEDIUM — the 12.5–25Hz light ceiling is from Philips documentation and HarmonizeProject observations. The 25fps recommendation follows from that ceiling plus the 100ms total latency budget.

---

## 5. Color Space Conversion: Camera RGB to Hue CIE xy

### Why this matters

Philips Hue accepts colors as CIE 1931 xy chromaticity coordinates, not RGB. The conversion is non-trivial: it involves gamma linearization, a color space matrix transformation, and gamut clamping specific to the light model.

### The conversion pipeline

```python
import numpy as np

# Gamut triangles (red, green, blue primaries) per Hue light generation
GAMUT_C = {
    "red":   (0.6915, 0.3083),
    "green": (0.1700, 0.7000),
    "blue":  (0.1532, 0.0475),
}
GAMUT_B = {
    "red":   (0.6750, 0.3220),
    "green": (0.4090, 0.5180),
    "blue":  (0.1670, 0.0400),
}

def _gamma_correct(v: float) -> float:
    """sRGB gamma linearization."""
    if v > 0.04045:
        return ((v + 0.055) / 1.055) ** 2.4
    return v / 12.92

def rgb_to_xy(r: int, g: int, b: int, gamut: dict = GAMUT_C) -> tuple[float, float]:
    """
    Convert 8-bit RGB to Philips Hue CIE 1931 xy.

    Args:
        r, g, b: 0–255 integer values
        gamut: Gamut C for modern Hue bulbs (A19 Gen 3, GU10, etc.)
               Gamut B for older A19 bulbs
    Returns:
        (x, y) chromaticity coordinates, clamped to gamut
    """
    # 1. Normalize to 0–1
    r_n = r / 255.0
    g_n = g / 255.0
    b_n = b / 255.0

    # 2. Gamma correction (linearize sRGB)
    r_lin = _gamma_correct(r_n)
    g_lin = _gamma_correct(g_n)
    b_lin = _gamma_correct(b_n)

    # 3. Wide Gamut D65 matrix (from Philips official documentation)
    X = r_lin * 0.664511 + g_lin * 0.154324 + b_lin * 0.162028
    Y = r_lin * 0.283881 + g_lin * 0.668433 + b_lin * 0.047685
    Z = r_lin * 0.000088 + g_lin * 0.072310 + b_lin * 0.986039

    total = X + Y + Z
    if total == 0:
        return 0.0, 0.0

    x = X / total
    y = Y / total

    # 4. Gamut clamp
    x, y = _clamp_to_gamut(x, y, gamut)
    return x, y


def _cross_product_2d(p1, p2) -> float:
    return p1[0] * p2[1] - p1[1] * p2[0]

def _closest_point_on_segment(a, b, p) -> tuple[float, float]:
    """Project point p onto segment a-b, return closest point."""
    ab = (b[0] - a[0], b[1] - a[1])
    ap = (p[0] - a[0], p[1] - a[1])
    t = (ap[0] * ab[0] + ap[1] * ab[1]) / (ab[0]**2 + ab[1]**2 + 1e-9)
    t = max(0.0, min(1.0, t))
    return a[0] + t * ab[0], a[1] + t * ab[1]

def _point_in_triangle(p, a, b, c) -> bool:
    d1 = _cross_product_2d((p[0]-a[0], p[1]-a[1]), (b[0]-a[0], b[1]-a[1]))
    d2 = _cross_product_2d((p[0]-b[0], p[1]-b[1]), (c[0]-b[0], c[1]-b[1]))
    d3 = _cross_product_2d((p[0]-c[0], p[1]-c[1]), (a[0]-c[0], a[1]-c[1]))
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)

def _clamp_to_gamut(x: float, y: float, gamut: dict) -> tuple[float, float]:
    """If (x,y) is outside the gamut triangle, project to nearest edge."""
    r, g, b = gamut["red"], gamut["green"], gamut["blue"]
    if _point_in_triangle((x, y), r, g, b):
        return x, y
    # Find nearest point on each edge
    candidates = [
        _closest_point_on_segment(r, g, (x, y)),
        _closest_point_on_segment(g, b, (x, y)),
        _closest_point_on_segment(b, r, (x, y)),
    ]
    best = min(candidates, key=lambda p: (p[0]-x)**2 + (p[1]-y)**2)
    return best
```

### Brightness (bri) from Y channel

The Y component from the XYZ conversion (before normalization) encodes luminance. Use it for the Hue `bri` (brightness) parameter:

```python
def rgb_to_xy_bri(r: int, g: int, b: int, gamut=GAMUT_C) -> tuple[float, float, int]:
    r_lin = _gamma_correct(r / 255.0)
    g_lin = _gamma_correct(g / 255.0)
    b_lin = _gamma_correct(b / 255.0)

    X = r_lin * 0.664511 + g_lin * 0.154324 + b_lin * 0.162028
    Y = r_lin * 0.283881 + g_lin * 0.668433 + b_lin * 0.047685
    Z = r_lin * 0.000088 + g_lin * 0.072310 + b_lin * 0.986039

    total = X + Y + Z
    if total == 0:
        return 0.0, 0.0, 0

    x = X / total
    y = Y / total
    bri = int(Y * 254)      # Hue brightness 0–254
    bri = max(0, min(254, bri))

    x, y = _clamp_to_gamut(x, y, gamut)
    return x, y, bri
```

### Which gamut to use

| Gamut | Hue products |
|---|---|
| Gamut A | LivingColors Iris, Bloom, LightStrips (gen 1), Aura |
| Gamut B | Hue A19 (gen 1 and 2), BR30, Ambiance |
| **Gamut C** | **A19 (gen 3+), GU10, Play, Gradient, Go** |

Query the light's gamut via the REST API: `GET /api/{apikey}/lights/{id}` → `capabilities.control.colorgamuttype`. Default to Gamut C for any light purchased after ~2019.

### Existing library alternative

The `rgbxy` PyPI package (`pip install rgbxy`) implements this conversion and is battle-tested. Consider it if you want to avoid maintaining the conversion math yourself. It supports all three gamut profiles and performs gamut clamping.

```python
from rgbxy import Converter, GamutC
converter = Converter(GamutC)
x, y = converter.rgb_to_xy(128, 200, 50)
```

**Confidence:** HIGH — conversion algorithm sourced from official Philips Hue developer documentation and independently verified in the `hue-python-rgb-converter` implementation.

---

## 6. Docker USB Device Passthrough

### The `/dev/videoN` approach

The simplest and most correct approach is to pass the specific device node into the container rather than using `--privileged`.

**docker-compose.yaml:**
```yaml
services:
  backend:
    build: ./Backend
    devices:
      - "/dev/video0:/dev/video0"
    group_add:
      - video        # GID of the host video group; container user needs this
    environment:
      - VIDEO_DEVICE=/dev/video0
```

**Why `group_add: video`?** The `/dev/videoN` nodes are owned by root with group `video` (mode 660). If the container runs as a non-root user (recommended), it must be in the `video` group to open the device.

### Device number is not stable

USB devices are assigned `/dev/video0`, `/dev/video1`, etc. dynamically. If the capture card is the only video device, it will typically be `/dev/video0`, but this is not guaranteed (e.g., if the host has a webcam).

**Robust approach: udev symlink on the host.** On the host machine, create a udev rule that creates a stable symlink based on the device's USB vendor/product ID:

```bash
# Find the attributes (run while capture card is connected)
udevadm info --name=/dev/video0 --attribute-walk | grep -E 'idVendor|idProduct|serial'

# Create /etc/udev/rules.d/99-hdmi-capture.rules:
SUBSYSTEM=="video4linux", ATTRS{idVendor}=="1234", ATTRS{idProduct}=="5678", SYMLINK+="hdmi_capture"
```

Then in docker-compose, mount `/dev/hdmi_capture:/dev/video0` — the container always sees it as `/dev/video0` regardless of host assignment.

### Multiple video device nodes

Many USB capture cards register multiple `/dev/videoN` nodes (e.g., `/dev/video0` and `/dev/video1`) — one for video, one for metadata/controls. If you see two nodes, `/dev/video0` is typically the video stream. Verify with:

```bash
v4l2-ctl --device=/dev/video0 --all
```

If you need to pass both nodes:
```yaml
devices:
  - "/dev/video0:/dev/video0"
  - "/dev/video1:/dev/video1"
```

### Windows/WSL2 note

This project is developed on WSL2 (Windows). USB passthrough to WSL2 requires `usbipd-win`. The device is then accessible as `/dev/videoN` within WSL2 and the Docker container.

```powershell
# Windows PowerShell (as Administrator)
usbipd list
usbipd bind --busid 2-3       # replace with your capture card bus ID
usbipd attach --wsl --busid 2-3
```

After attach, the device appears in WSL2 as `/dev/video0` and can be mounted into Docker normally. This must be re-run after each unplug/replug.

**Confidence:** HIGH for Linux native. MEDIUM for WSL2 (requires usbipd-win and re-attachment on reconnect; documented behavior as of 2024).

---

## 7. End-to-End Latency Budget

### What the Hue system can deliver

The Hue Entertainment API (UDP/DTLS) is the low-latency path. The Hue Bridge relays commands to lights over Zigbee at approximately 25Hz. Real light response (physical color change) adds another ~40–80ms on top of the Zigbee update interval.

The REST API (`PUT /lights/{id}/state`) adds HTTP round-trip overhead and a rate limit of approximately 10 commands/second per light — completely unsuitable for real-time ambient use. **Always use the Entertainment API for this project.**

### Latency breakdown

| Stage | Typical | Notes |
|---|---|---|
| HDMI capture card encode (MJPEG) | ~5 ms | Internal to device |
| USB transfer + V4L2 | ~2–5 ms | USB 2.0 bulk transfer |
| OpenCV JPEG decode | ~3–8 ms | MJPEG → BGR numpy array |
| Downscale (if any) | ~0.5–1 ms | cv2.resize, INTER_AREA |
| Zone mask extraction (16 zones) | ~1–3 ms | Pre-computed masks, cv2.mean |
| RGB → xy conversion (16 zones) | ~0.1 ms | Pure numpy, negligible |
| Entertainment API DTLS packet | ~1–3 ms | UDP to bridge on local LAN |
| Zigbee command (bridge → light) | ~20–40 ms | Proprietary 25Hz radio |
| Light physical response | ~40–80 ms | Hardware transition time |
| **Total** | **~73–145 ms** | **Typically ~100ms** |

### The 50ms software budget

If we allocate 50ms to the software pipeline (capture → analyze → send), the breakdown becomes:

```
Budget: 50ms
- Frame capture (USB + decode): 10–15ms
- Analysis (16 zones):           2–5ms
- API send:                      1–3ms
- Headroom:                     ~27–37ms
```

This is **comfortable at 25fps** (40ms per frame cycle). The soft budget is met with significant margin.

### HarmonizeProject reference point

The HarmonizeProject (Python + OpenCV on Raspberry Pi 4) achieves:
- 80ms video-to-light streaming latency
- ~60 color updates per second sent to bridge

On modern x86 hardware inside Docker, we can expect to match or beat the RPi4 figures.

---

## 8. Recommended Python Libraries

| Library | PyPI package | Purpose | Notes |
|---|---|---|---|
| `opencv-python-headless` | `opencv-python-headless` | Frame capture, masking, color ops | Headless variant avoids GUI deps — required in Docker |
| `numpy` | `numpy` | Array math, mask operations | Comes with OpenCV |
| `rgbxy` | `rgbxy` | RGB → CIE xy gamut conversion | If not implementing from scratch |
| `hue-entertainment-pykit` | `hue-entertainment-pykit` | Entertainment API DTLS streaming | Python 3.12 max (see note below) |
| `v4l2py` | `v4l2py` | Direct V4L2 bindings (optional) | Use if OpenCV MJPEG path proves slow |
| `PyTurboJPEG` | `PyTurboJPEG` | Fast MJPEG decode (optional) | 3–5x faster than OpenCV for JPEG |

**Critical warning on `hue-entertainment-pykit`:** This library uses `python-mbedtls` for DTLS and does not support Python 3.13+. Pin the container to Python 3.12.

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libopencv-dev \
    v4l-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install \
    opencv-python-headless \
    numpy \
    rgbxy \
    hue-entertainment-pykit
```

---

## 9. Putting It Together: Recommended Pipeline

```
[HDMI source]
     |
     v
[USB Capture Card] --MJPEG--> /dev/video0
     |
     v
[LatestFrameCapture thread]    <- runs at 30fps, always holds latest
     |
     v
[Analysis loop @ 25fps]
  1. capture.read()             -> (480, 640, 3) BGR numpy array
  2. cv2.resize() if needed     -> target analysis resolution
  3. extract_all_zones()        -> [(R,G,B), ...] x 16
  4. rgb_to_xy_bri() per zone   -> [(x,y,bri), ...] x 16
  5. send to Entertainment API  -> UDP/DTLS packet
     |
     v
[Hue Bridge] --Zigbee--> [Lights]
```

### Key decisions summary

1. **Capture at 640x480 MJPEG 30fps** — sufficient for color analysis, fits USB bandwidth
2. **Use threaded capture** — guarantees freshness, decouples capture from analysis rate
3. **Pre-compute polygon masks at startup** — reduces per-frame cost to ~1–3ms for 16 zones
4. **Use `cv2.mean()` with mask** — simplest, fastest, sufficient for ambient color
5. **Convert RGB → xy with gamut clamping** — use rgbxy library or inline implementation
6. **Use Entertainment API, not REST** — 10x lower latency, no per-light rate limits
7. **Pin to Python 3.12** — required by hue-entertainment-pykit's DTLS dependency
8. **Pass /dev/video0 via `devices:` in docker-compose** — not `--privileged`

---

## Sources

- [OpenCV: Access UVC Cameras on Linux (Arducam)](https://docs.arducam.com/UVC-Camera/Appilcation-Note/OpenCV-Python-GStreamer-on-linux/)
- [OpenCV: V4L2 camera capture (Arducam blog)](https://blog.arducam.com/faq/opencv-v4l2-python-rpi/)
- [OpenCV: Buffer latency issue (forum)](https://forum.opencv.org/t/delay-in-videocapture-because-of-buffer/2755)
- [OpenCV: MJPEG format selection (forum)](https://answers.opencv.org/question/186940/change-videocapture-format-to-mjpeg/)
- [v4l2py on PyPI](https://pypi.org/project/v4l2py/)
- [Docker: Sharing webcam devices with containers (FunWithLinux)](https://www.funwithlinux.net/blog/sharing-devices-webcam-usb-drives-etc-with-docker/)
- [Docker: Access host devices (Baeldung)](https://www.baeldung.com/ops/docker-access-host-devices)
- [Docker Compose: devices configuration](https://oneuptime.com/blog/post/2026-02-08-how-to-use-docker-compose-devices-configuration/view)
- [Philips Hue: RGB to xy Color Conversion (official SDK notes)](https://github.com/johnciech/PhilipsHueSDK/blob/master/ApplicationDesignNotes/RGB%20to%20xy%20Color%20conversion.md)
- [hue-python-rgb-converter (rgbxy library)](https://github.com/benknight/hue-python-rgb-converter)
- [Philips Hue: Entertainment API technical overview (IoTech Blog)](https://iotech.blog/posts/philips-hue-entertainment-api/)
- [hue-entertainment-pykit (GitHub)](https://github.com/hrdasdominik/hue-entertainment-pykit)
- [HarmonizeProject: Python OpenCV ambilight reference implementation](https://github.com/MCPCapital/HarmonizeProject)
- [PyImageSearch: Image Masking with OpenCV](https://pyimagesearch.com/2021/01/19/image-masking-with-opencv/)
- [PyImageSearch: Color Quantization with K-Means](https://pyimagesearch.com/2014/07/07/color-quantization-opencv-using-k-means-clustering/)
- [Saturn Cloud: Dominant Color Extraction with OpenCV and NumPy](https://saturncloud.io/blog/extracting-the-most-dominant-color-from-an-rgb-image-using-opencv-numpy-and-python/)
