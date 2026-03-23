# Philips Hue API Research: CLIP v2 + Entertainment API

**Project:** HuePictureControl
**Researched:** 2026-03-23
**Overall confidence:** MEDIUM-HIGH (developer portal behind login wall; findings from official third-party integrations, library source, and verified community documentation)

---

## 1. CLIP API v2 Overview

### What Changed from v1

The CLIP v2 API (also called "New Hue API") is a complete redesign. It runs exclusively over **HTTPS** on the local bridge and exposes a unified resource graph instead of numbered light IDs. Key differences:

- "Username" renamed to **application key** (treated as a secret, passed in header)
- All resources addressed by **UUID** (e.g. `3a2b1c4d-...`)
- Event delivery via **Server-Sent Events (SSE)** instead of polling
- Gradient light segments exposed as first-class resources (v1 was blind to them)
- Entertainment API v2 required for per-segment gradient control

Base URL for all CLIP v2 requests:
```
https://<bridge-ip>/clip/v2/resource/
```

All requests require the header:
```
hue-application-key: <application_key>
```

---

## 2. Authentication Flow

### Step 1: Discover the Bridge

Three supported discovery methods (in order of preference):

**mDNS (preferred, no internet required):**
```python
from zeroconf import ServiceBrowser, Zeroconf

# Look for service type "_hue._tcp.local."
# Bridge advertises its IP and bridge ID
```

**N-UPnP fallback (requires internet):**
```
GET https://discovery.meethue.com/
# Returns: [{"id": "001788fffe123456", "internalipaddress": "192.168.1.100"}]
```

**Manual:** Read from DHCP table on router.

Note: SSDP/UPnP discovery is deprecated.

### Step 2: Create Application Key (one-time)

Press the physical link button on the bridge, then within 30 seconds:

```python
import requests

bridge_ip = "192.168.1.100"

payload = {
    "devicetype": "HuePictureControl#raspberry",  # app#instance
    "generateclientkey": True  # MUST be true for Entertainment API
}

# Bridge uses a self-signed or Signify-CA cert — disable SSL verification for this step
response = requests.post(
    f"https://{bridge_ip}/api",
    json=payload,
    verify=False  # See Section 3 for proper cert handling
)

data = response.json()[0]["success"]
application_key = data["username"]   # Used as hue-application-key header
client_key = data["clientkey"]        # PSK for DTLS Entertainment streaming
                                      # CRITICAL: cannot be retrieved again
```

Example response:
```json
[{"success": {
    "username": "Qn74cB7YlKursSzMYyPL4pr5oLWxayBqhKyjFD10",
    "clientkey": "8B249DD79EF93F004595E2AC2DFEC942"
}}]
```

**Store both values securely. The clientkey cannot be re-fetched.**

### Step 3: Verify Connection

```python
headers = {"hue-application-key": application_key}

response = requests.get(
    f"https://{bridge_ip}/clip/v2/resource/device",
    headers=headers,
    verify=False
)
```

---

## 3. SSL Certificate Handling

Hue bridges use a certificate signed by **Signify's private CA**. Newer bridges have a cert with CN matching their bridge ID (lowercase MAC-derived). Older bridges use self-signed certs.

**Development approach (acceptable for local-only tools):**
```python
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

session = requests.Session()
session.verify = False
session.headers.update({"hue-application-key": application_key})
```

**Production approach** (if Signify CA cert is available from developer portal):
```python
import ssl

# Download hue_ca.pem from developers.meethue.com
# Validate CN == bridge_id.lower()
ssl_context = ssl.create_default_context(cafile="hue_ca.pem")
ssl_context.check_hostname = False  # CN is bridge ID, not IP
```

For this project (local Raspberry Pi tool), `verify=False` is acceptable.

---

## 4. Device and Light Discovery

### Enumerate All Resources

```python
# All resource types
GET /clip/v2/resource                     # Everything
GET /clip/v2/resource/device              # Physical devices
GET /clip/v2/resource/light               # Light services
GET /clip/v2/resource/entertainment       # Entertainment-capable lights
GET /clip/v2/resource/entertainment_configuration  # Entertainment zones
GET /clip/v2/resource/room                # Rooms
GET /clip/v2/resource/zone                # Zones
```

### Light Resource Structure

```json
{
  "id": "3a2b1c4d-0000-0000-0000-000000000001",
  "type": "light",
  "metadata": {"name": "TV Gradient Strip"},
  "on": {"on": true},
  "dimming": {"brightness": 80.0, "min_dim_level": 0.0},
  "color_temperature": {"mirek": 312, "mirek_valid": true},
  "color": {
    "xy": {"x": 0.4573, "y": 0.4100},
    "gamut": {
      "red":   {"x": 0.692, "y": 0.308},
      "green": {"x": 0.170, "y": 0.700},
      "blue":  {"x": 0.153, "y": 0.048}
    },
    "gamut_type": "C"
  },
  "gradient": {
    "points": [
      {"color": {"xy": {"x": 0.6, "y": 0.3}}},
      {"color": {"xy": {"x": 0.2, "y": 0.7}}},
      {"color": {"xy": {"x": 0.15, "y": 0.05}}}
    ],
    "mode": "interpolated_palette",
    "points_capable": 5,
    "mode_values": [
      "interpolated_palette",
      "interpolated_palette_mirrored",
      "random_pixelated"
    ],
    "pixel_count": 7
  }
}
```

Key gradient fields:
- `points`: Up to 5 color gradient points (interpolated between)
- `pixel_count`: Actual independently addressable segments (7 for Play Gradient Lightstrip)
- `mode`: `interpolated_palette` (smooth gradient), `interpolated_palette_mirrored` (mirror), `random_pixelated` (scattered — for Festavia/string lights)

---

## 5. SSE Event Stream

CLIP v2 pushes state changes via SSE — no polling needed.

```python
import sseclient
import requests

def listen_for_events(bridge_ip, application_key):
    headers = {
        "hue-application-key": application_key,
        "Accept": "text/event-stream"
    }
    response = requests.get(
        f"https://{bridge_ip}/eventstream/clip/v2",
        headers=headers,
        stream=True,
        verify=False
    )
    client = sseclient.SSEClient(response)
    for event in client.events():
        # event.data is JSON array of resource update objects
        pass
```

SSE rate limit: **1 event container per second**. If a property changes twice within 1 second, only the final state is delivered. Multiple resources changed within 1 second are batched into one container.

HTTP/2 is supported and allows multiplexing SSE and regular requests on a single connection.

---

## 6. Controlling Lights via REST

**Rate limit: 20 requests per second** (REST endpoint)

### Set color (XY):
```python
import requests

def set_light_xy(bridge_ip, app_key, light_id, x, y, brightness=None):
    payload = {"color": {"xy": {"x": x, "y": y}}}
    if brightness is not None:
        payload["dimming"] = {"brightness": brightness}  # 0.0-100.0

    requests.put(
        f"https://{bridge_ip}/clip/v2/resource/light/{light_id}",
        headers={"hue-application-key": app_key},
        json=payload,
        verify=False
    )
```

### Set gradient points:
```python
payload = {
    "gradient": {
        "points": [
            {"color": {"xy": {"x": 0.675, "y": 0.322}}},  # red
            {"color": {"xy": {"x": 0.17,  "y": 0.70 }}},  # green
            {"color": {"xy": {"x": 0.153, "y": 0.048}}}   # blue
        ],
        "mode": "interpolated_palette"
    }
}
```

**REST gradient update latency: ~50-100ms round trip.** Not suitable for <100ms real-time sync across many lights. Use Entertainment API for low-latency streaming.

---

## 7. Entertainment API (Streaming Mode)

This is the path for real-time ambient sync. It bypasses Zigbee's normal command queue and enables 50-60 Hz updates.

### Architecture

```
App → DTLS/UDP :2100 → Hue Bridge → Zigbee → Lights
          ↑
    ~10ms latency
    (vs ~50ms REST)
```

The bridge converts UDP messages to Zigbee at **25 Hz** (its Zigbee limit). Sending at 50-60 Hz provides redundancy against UDP packet loss — the bridge just drops duplicate frames.

### 7.1 Prerequisites: Entertainment Configuration

An "entertainment configuration" (zone) must exist before streaming. Create and manage these in the **Philips Hue app** (not via API for creation in practice, though the API supports it).

**List existing configurations:**
```python
response = requests.get(
    f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration",
    headers={"hue-application-key": app_key},
    verify=False
)
configs = response.json()["data"]
# Each config has: id, metadata.name, status, channels[], light_services[]
```

**Entertainment configuration structure:**
```json
{
  "id": "d476df48-83ad-4430-a104-53c30b46b4d0",
  "type": "entertainment_configuration",
  "metadata": {"name": "TV Sync Zone"},
  "configuration_type": "screen",
  "status": "inactive",
  "stream_proxy": {"mode": "auto", "node": {"rid": "...", "rtype": "bridge"}},
  "channels": [
    {
      "channel_id": 0,
      "position": {"x": -0.5, "y": 0.0, "z": -1.0},
      "members": [
        {
          "service": {"rid": "<light-service-id>", "rtype": "entertainment"},
          "index": 0
        }
      ]
    },
    {
      "channel_id": 1,
      "position": {"x": 0.0, "y": 0.0, "z": -1.0},
      "members": [{"service": {"rid": "<light-service-id>", "rtype": "entertainment"}, "index": 1}]
    }
  ],
  "light_services": [
    {"rid": "<entertainment-service-id>", "rtype": "entertainment"}
  ]
}
```

Each gradient segment of a light gets its own **channel_id** with a spatial position. A 7-segment Play Gradient Lightstrip will appear as 7 separate channels.

### 7.2 Activate Streaming Mode

**Must call before DTLS connection:**
```python
entertainment_config_id = "d476df48-83ad-4430-a104-53c30b46b4d0"

requests.put(
    f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration/{entertainment_config_id}",
    headers={"hue-application-key": app_key},
    json={"action": "start"},
    verify=False
)
# status becomes "active"
```

**Deactivate after streaming:**
```python
requests.put(
    f"...",
    json={"action": "stop"},
    ...
)
```

If the streaming connection drops without explicit stop, the bridge auto-deactivates after ~10 seconds of inactivity.

### 7.3 DTLS Handshake

The bridge accepts DTLS 1.2 **only** with exactly one cipher suite:
```
TLS_PSK_WITH_AES_128_GCM_SHA256
```

- **Port:** 2100/UDP
- **Auth:** Pre-Shared Key (PSK)
  - PSK identity = `application_key` (the "username" string)
  - PSK value = `client_key` decoded from hex bytes

Python DTLS options:
- **`dtls` package** (`pip install dtls`): Wraps OpenSSL, supports PSK
- **`mbedtls` Python bindings**: Alternative but less commonly used
- **`hue-entertainment-pykit`**: Pre-built wrapper that handles DTLS internally

Low-level DTLS with the `dtls` package:
```python
from dtls import do_patch
do_patch()  # Patches socket module to support DTLS

import socket
import ssl

psk_identity = application_key.encode("utf-8")
psk_key = bytes.fromhex(client_key)  # clientkey is hex string

# Standard PSK DTLS setup — exact API varies by library version
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Wrap with DTLS PSK context (library-specific)
```

**Practical recommendation:** Use `hue-entertainment-pykit` or study its source for the DTLS bootstrap, then extract the raw UDP socket access for direct frame building. The DTLS negotiation is the hardest part.

### 7.4 Binary Message Format

Every UDP packet sent to port 2100 after the DTLS handshake uses this structure:

```
Offset  Size  Value         Description
------  ----  -----         -----------
0       9     "HueStream"   ASCII protocol identifier (no null terminator)
9       1     0x02          API major version
10      1     0x00          API minor version
11      1     0x01+         Sequence number (increment each packet, wraps)
12      2     0x00 0x00     Reserved
14      1     0x00 / 0x01   Color space: 0x00=RGB, 0x01=XY+Brightness
15      1     0x00          Reserved
-- Header is 16 bytes --

16      36    "<uuid>"      Entertainment configuration ID (ASCII, no null)
-- Config ID is 36 bytes --

52+     7*N   channel data  Up to 20 channels per packet

Per channel (7 bytes each):
  Offset  Size  Value
  0       1     channel_id  (matches channel_id from configuration)
  1       2     val1        (R 16-bit big-endian, or X 16-bit big-endian)
  3       2     val2        (G 16-bit big-endian, or Y 16-bit big-endian)
  5       2     val3        (B 16-bit big-endian, or Brightness 16-bit big-endian)

Color value range: 0x0000 (off) to 0xFFFF (full)
```

Python struct pack example:
```python
import struct

def build_huestream_packet(
    config_id: str,
    channels: list[tuple[int, int, int, int]],  # (channel_id, r, g, b) — 0-65535
    seq: int = 0,
    color_space: int = 0x00  # 0=RGB
) -> bytes:
    header = (
        b"HueStream"          # 9 bytes
        + bytes([0x02, 0x00]) # version 2.0
        + bytes([seq & 0xFF]) # sequence
        + bytes([0x00, 0x00]) # reserved
        + bytes([color_space])# color mode
        + bytes([0x00])        # reserved
    )
    config_bytes = config_id.encode("ascii")  # 36 bytes

    channel_data = b""
    for channel_id, v1, v2, v3 in channels:
        channel_data += struct.pack(">BHHH", channel_id, v1, v2, v3)

    return header + config_bytes + channel_data


# Example: set channel 0 to red, channel 1 to blue (RGB mode)
packet = build_huestream_packet(
    config_id="d476df48-83ad-4430-a104-53c30b46b4d0",
    channels=[
        (0, 0xFFFF, 0x0000, 0x0000),  # channel 0: full red
        (1, 0x0000, 0x0000, 0xFFFF),  # channel 1: full blue
    ],
    seq=1
)
# Send packet via DTLS-wrapped UDP socket
```

**Key constraints:**
- Max **20 channels per packet**
- Recommended rate: **50-60 Hz**
- Bridge internal Zigbee rate: **25 Hz** (so 50+ Hz gives 2x redundancy)
- Keep-alive: resend last packet if silent for >9.5 seconds (bridge auto-stops at ~10s)
- All values **big-endian**

---

## 8. Gradient-Capable Device Details

### 8.1 Play Gradient Lightstrip (TV/Monitor)

| Property | Value |
|----------|-------|
| Segments via Entertainment API | **7** independent channels |
| Layout | 3 top, 2 left, 2 right (for TV mounting) |
| REST gradient points | Up to 5 (interpolated across 7 segments) |
| V1 Entertainment | NOT supported (segments invisible) |
| V2 Entertainment | Full 7-channel independent control |

The 7 channels map to physical positions along the strip. In an entertainment configuration each channel gets an `(x, y, z)` coordinate in the -1..1 virtual space.

### 8.2 Festavia String Lights (LCX012 — 250 LEDs)

| Property | Value |
|----------|-------|
| Physical LEDs | 250 mini LEDs over 20m |
| API gradient mode | `random_pixelated` ("scattered") |
| Entertainment channels | Grouped (not 250 individual channels) |
| Gradient modes | `interpolated_palette`, `interpolated_palette_mirrored`, `random_pixelated` |
| Effects | `candle`, `fire`, `sparkle` |

**Important:** The 250 LEDs are **not** individually addressable via the API. The Festavia exposes a small number of entertainment channels (likely 5-7, same as other gradient products) and uses internal algorithms to distribute colors across the LEDs. The `random_pixelated` mode scatters assigned palette colors randomly across the string.

Confidence: MEDIUM — official docs unavailable; derived from Home Assistant integration source and aiohue model.

### 8.3 Flux Lightstrip (RGBWWIC)

| Property | Value |
|----------|-------|
| Technology | RGBWWIC (dedicated warm white + color LEDs) |
| Gradient segments | 7 (same as Play Gradient Lightstrip) |
| New "Segmented" mode | Up to 4 distinct color blocks (no gradient between) |
| Entertainment API | Supported with gradient segment channels |
| Limitation | Cannot mix true white tones with color in segmented mode |

Available since late 2025. Entertainment API channel count matches Play Gradient Lightstrip (7 channels). Confidence: MEDIUM — product released Sept 2025, limited developer documentation found.

### 8.4 Entertainment Channel Count Summary

| Device | Entertainment Channels | Notes |
|--------|----------------------|-------|
| Play Gradient Lightstrip 55" | 7 | Standard TV strip |
| Play Gradient Lightstrip 75" | 7 | Larger TV strip |
| Gradient Lightstrip (non-Play) | 3 | Ambiance variant |
| Festavia string lights | ~5-7 | Not 250; internally distributed |
| Flux Lightstrip | 7 | RGBWWIC variant |
| Standard color bulb | 1 | Single channel |
| Hue Play bar | 1 | Single channel |

**Hard limit:** An entertainment configuration supports a **maximum of 20 channels total** across all assigned lights. With two 7-segment strips + a few bulbs, you can approach this limit.

---

## 9. Entertainment Configuration Setup

### Create via Hue App (Recommended Path)

1. Open Hue app → Entertainment Areas
2. Create new area, name it (e.g. "TV Sync")
3. Add lights and position them in the virtual layout
4. Gradient lights automatically split into their segment channels
5. Note the configuration UUID from `GET /clip/v2/resource/entertainment_configuration`

### Create via API (Advanced)

```python
payload = {
    "metadata": {"name": "TV Sync"},
    "configuration_type": "screen",  # or "music", "threedeespace", "monitor", "other"
    "stream_proxy": {"mode": "auto"},
    "locations": {
        "service_locations": [
            {
                "service": {"rid": "<entertainment-service-id>", "rtype": "entertainment"},
                "positions": [
                    {"x": -0.5, "y": 0.0, "z": -1.0},  # left
                    {"x":  0.5, "y": 0.0, "z": -1.0}   # right
                ]
            }
        ]
    }
}

requests.post(
    f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration",
    headers={"hue-application-key": app_key},
    json=payload,
    verify=False
)
```

Positions use a normalized 3D coordinate system: `x` = left/right (-1 to 1), `y` = vertical (-1 to 1), `z` = depth (-1 to 1, -1 = behind viewer).

For a screen configuration, the virtual screen maps the XZ plane at y=0. The bridge uses these positions to know which screen region each channel represents.

---

## 10. Color Space

### Hue's Native Format: CIE xy + Brightness

The API accepts and returns colors as CIE 1931 xy chromaticity coordinates. Brightness is separate (0.0-100.0 scale for REST, 0x0000-0xFFFF for Entertainment streaming).

```json
"color": {"xy": {"x": 0.4573, "y": 0.4100}}
```

### Color Gamuts by Device Generation

| Gamut | Devices | Red | Green | Blue |
|-------|---------|-----|-------|------|
| A | Legacy LivingColors | (0.704, 0.296) | (0.2151, 0.7106) | (0.138, 0.08) |
| B | Original Hue bulbs | (0.675, 0.322) | (0.4091, 0.518) | (0.167, 0.04) |
| C | Current gen (2018+) | (0.692, 0.308) | (0.170, 0.700) | (0.153, 0.048) |

Modern lights (gradient strips, Festavia, Flux) use **Gamut C**. The `gamut_type` field in the light resource confirms which gamut applies.

### RGB to XY Conversion

```python
def rgb_to_xy(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert sRGB (0-255) to CIE xy + brightness Y.

    Returns (x, y, brightness) where brightness is 0.0-1.0.
    Uses Wide RGB D65 color space (Gamut C matrix).
    """
    # Normalize 0-255 to 0.0-1.0
    r_n = r / 255.0
    g_n = g / 255.0
    b_n = b / 255.0

    # Inverse sRGB gamma (linearize)
    def to_linear(c: float) -> float:
        if c > 0.04045:
            return ((c + 0.055) / 1.055) ** 2.4
        else:
            return c / 12.92

    r_lin = to_linear(r_n)
    g_lin = to_linear(g_n)
    b_lin = to_linear(b_n)

    # Wide RGB D65 to XYZ (Gamut C matrix — use this for modern lights)
    X = r_lin * 0.664511 + g_lin * 0.154324 + b_lin * 0.162028
    Y = r_lin * 0.283881 + g_lin * 0.668433 + b_lin * 0.047685
    Z = r_lin * 0.000088 + g_lin * 0.072310 + b_lin * 0.986039

    denom = X + Y + Z
    if denom == 0:
        return (0.0, 0.0, 0.0)

    x = X / denom
    y = Y / denom
    brightness = Y  # Y component IS brightness in CIE
    return (x, y, brightness)


def clamp_to_gamut_c(x: float, y: float) -> tuple[float, float]:
    """Clamp xy point to Gamut C triangle if outside."""
    # Gamut C triangle vertices
    RED   = (0.692, 0.308)
    GREEN = (0.170, 0.700)
    BLUE  = (0.153, 0.048)

    def cross2d(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def point_in_triangle(p, a, b, c):
        d1 = cross2d(p, a, b)
        d2 = cross2d(p, b, c)
        d3 = cross2d(p, c, a)
        has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
        has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
        return not (has_neg and has_pos)

    p = (x, y)
    if point_in_triangle(p, RED, GREEN, BLUE):
        return (x, y)  # Already inside gamut

    # Find closest point on each edge and return nearest
    def closest_on_segment(p, a, b):
        ab = (b[0]-a[0], b[1]-a[1])
        ap = (p[0]-a[0], p[1]-a[1])
        t = max(0, min(1, (ap[0]*ab[0] + ap[1]*ab[1]) / (ab[0]**2 + ab[1]**2)))
        return (a[0] + t*ab[0], a[1] + t*ab[1])

    candidates = [
        closest_on_segment(p, RED, GREEN),
        closest_on_segment(p, GREEN, BLUE),
        closest_on_segment(p, BLUE, RED),
    ]

    def dist2(a, b):
        return (a[0]-b[0])**2 + (a[1]-b[1])**2

    return min(candidates, key=lambda c: dist2(c, p))
```

### For Entertainment Streaming (16-bit XY)

The Entertainment API color mode `0x01` uses 16-bit XY + brightness:
```
val1 = int(x * 0xFFFF)           # X as 16-bit
val2 = int(y * 0xFFFF)           # Y as 16-bit
val3 = int(brightness * 0xFFFF)  # Y/brightness as 16-bit
```

For RGB mode `0x00`:
```
val1 = r * 257   # Scale 0-255 to 0-65535
val2 = g * 257
val3 = b * 257
```

**Recommendation for this project:** Use **XY mode** (0x01) in the Entertainment stream. Capture HDMI frame → crop region → average to RGB → convert to XY once per region → encode as 16-bit XY. This avoids double-converting and preserves the gamut-clamping logic in one place.

---

## 11. Python Libraries for Hue

Since the project wants **direct API usage**, these are reference resources rather than dependencies:

| Library | Use | Notes |
|---------|-----|-------|
| `aiohue` (home-assistant-libs) | Reference for v2 data models | asyncio, active maintenance, used by Home Assistant |
| `hue-entertainment-pykit` | Reference for DTLS bootstrap code | Solves the hard DTLS PSK problem in Python |
| `hue-python-rgb-converter` (`rgbxy`) | Color conversion reference | Has gamut A/B/C, well-tested |
| `qhue` | Minimal v1 wrapper | Ignore — v1 only |
| `huesdk` | Discovery + basic control | Has mDNS discovery example |

Key insight from `aiohue` source: it models `EntertainmentChannel.members` as a list of `SegmentReference(service, index)` — where `index` is the segment number within that light's entertainment service. This is how a 7-segment strip maps to 7 channel entries.

---

## 12. Rate Limits and Latency Analysis

| Interface | Rate | Latency | Notes |
|-----------|------|---------|-------|
| REST CLIP v2 (PUT) | 20 req/sec | ~50-100ms | Per-request; aggregate limit |
| SSE events | 1 container/sec | Push | Batched; not for control |
| Entertainment UDP | 50-60 Hz send | ~10ms | Bridge Zigbee output: 25 Hz |
| Zigbee (internal) | 25 Hz | ~10-40ms | Physical RF limit |

**For 16+ segments at <100ms:**

REST is **not viable** for real-time ambient sync. At 20 req/sec with 16 segments, you'd need 16 requests for a full update cycle = ~800ms minimum. Even batching via `grouped_light` only gets you one average color.

Entertainment API is the **only viable path**:
- All 20 channels in one UDP packet
- Send at 50 Hz = 20ms update interval
- Well under the 100ms target
- Bridge Zigbee limit (25 Hz) means visible updates every 40ms — acceptable

**Practical latency budget:**
```
HDMI capture (frame):    ~8ms  (120fps capture)
Region analysis:         ~2ms  (GPU or numpy)
XY conversion:           <1ms
UDP packet build+send:   <1ms
DTLS/UDP to bridge:      ~1ms  (local network)
Bridge → Zigbee:         ~40ms (25 Hz Zigbee cycle)
Light response:          ~5ms
------
Total visible latency:   ~57ms (well under 100ms)
```

---

## 13. Full Workflow for Ambient Sync

```python
# Pseudo-code workflow for the complete pipeline

# == SETUP (once at startup) ==
bridge_ip = "192.168.1.100"
app_key = "..."      # from config
client_key = "..."   # from config (hex string)
ent_config_id = "..."  # from config

# 1. Activate entertainment mode
activate_streaming(bridge_ip, app_key, ent_config_id)

# 2. Establish DTLS connection
dtls_sock = establish_dtls(
    host=bridge_ip,
    port=2100,
    psk_identity=app_key.encode(),
    psk_key=bytes.fromhex(client_key)
)

# == MAIN LOOP (50 Hz) ==
while running:
    frame = capture_hdmi_frame()          # ~8ms

    channels = []
    for ch_id, region in channel_regions.items():
        # region = (x1, y1, x2, y2) in frame coordinates
        r, g, b = average_region_color(frame, region)
        x, y, bri = rgb_to_xy(r, g, b)
        x, y = clamp_to_gamut_c(x, y)
        # Scale to 16-bit
        channels.append((ch_id,
                          int(x * 0xFFFF),
                          int(y * 0xFFFF),
                          int(bri * 0xFFFF)))

    packet = build_huestream_packet(
        config_id=ent_config_id,
        channels=channels,
        seq=next_seq(),
        color_space=0x01  # XY+Brightness
    )
    dtls_sock.send(packet)

    time.sleep(1/50)  # 20ms = 50 Hz
```

---

## 14. Known Pitfalls

### Pitfall 1: clientkey Is Lost If Not Saved
The Entertainment API PSK (`clientkey`) is returned **once** during user creation. It cannot be retrieved later. If lost, a new user must be created (button press required again).

**Prevention:** Store in `.env` file or secrets manager immediately after provisioning.

### Pitfall 2: Entertainment Mode Must Be Activated Before DTLS
If you attempt DTLS connection without first calling `PUT /entertainment_configuration/{id}` with `{"action": "start"}`, the bridge silently refuses the connection.

**Prevention:** Always activate, then connect. Add health check: re-activate if connection drops.

### Pitfall 3: V1 Entertainment API Ignores Gradient Segments
Using the v1 Entertainment API with gradient strips gives a single channel per strip, not 7. All 7 segments show the same color.

**Prevention:** Use v2 Entertainment API exclusively. Confirm config channels count > 1 for gradient strips.

### Pitfall 4: 20-Channel Hard Limit
An entertainment configuration cannot have more than 20 channels. Two 7-segment strips + Festavia (5-7 channels) = 19-21 channels, potentially hitting the limit.

**Prevention:** Design configurations carefully. Consider separate zones for different device groups.

### Pitfall 5: DTLS Cipher Suite Rigidity
The bridge only accepts `TLS_PSK_WITH_AES_128_GCM_SHA256`. Python DTLS libraries vary in their PSK cipher suite support. Standard `ssl` module does not support DTLS. OpenSSL PSK requires custom compilation flags.

**Prevention:** Use `hue-entertainment-pykit` or `mbedtls` Python bindings for the DTLS layer. Test DTLS connectivity before building anything else.

### Pitfall 6: Self-Signed Certificate in Python
Python's `requests` library rejects the bridge's SSL certificate by default.

**Prevention:** Use `verify=False` for local-only tools, or provide the Signify CA cert from the developer portal.

### Pitfall 7: Colors Outside Gamut Produce Unpredictable Results
Sending XY coordinates outside the light's color gamut doesn't raise an error — the bridge or light silently maps to the nearest reproducible color. Video content with saturated colors (red > 0.692 for Gamut C) will be silently clamped.

**Prevention:** Always run `clamp_to_gamut_c()` (or equivalent) before encoding.

### Pitfall 8: Festavia Is Not 250 Individually Addressable LEDs
Despite having 250 physical LEDs, the Festavia string light API exposes a small number of gradient channels (not 250). The `random_pixelated` mode internally distributes colors across LEDs.

**Prevention:** Design ambient regions for the actual channel count (~5-7), not individual LEDs.

---

## 15. Sources

| Source | Confidence | Notes |
|--------|-----------|-------|
| [Philips Hue Developer Program](https://developers.meethue.com/new-hue-api/) | MEDIUM | Login-gated; general overview accessible |
| [IoTech Blog — Entertainment API](https://iotech.blog/posts/philips-hue-entertainment-api/) | HIGH | Detailed protocol walkthrough, verified against multiple sources |
| [IoTech Blog — HTTPS](https://iotech.blog/posts/philips-https/) | HIGH | Certificate handling details |
| [aiohue source — entertainment_configuration.py](https://github.com/home-assistant-libs/aiohue/blob/main/aiohue/v2/models/entertainment_configuration.py) | HIGH | Official Home Assistant library, production use |
| [hue-entertainment-pykit](https://github.com/hrdasdominik/hue-entertainment-pykit) | MEDIUM | Community Python library with DTLS handling |
| [HyperHDR Discussion #512](https://github.com/awawa-dev/HyperHDR/discussions/512) | HIGH | Real-world segment count verification, production ambient sync system |
| [Philips Hue SDK — RGB to xy](https://github.com/johnciech/PhilipsHueSDK/blob/master/ApplicationDesignNotes/RGB%20to%20xy%20Color%20conversion.md) | HIGH | Official SDK notes |
| [hue-python-rgb-converter](https://github.com/benknight/hue-python-rgb-converter/blob/master/rgbxy/__init__.py) | HIGH | Well-tested gamut implementations |
| [Podfeet Blog — Hue Programming Part 1](https://www.podfeet.com/blog/2024/08/philips-hue-programming-part-1-of-3/) | MEDIUM | 2024 hands-on API usage |
| [openHAB v2 Binding docs](https://www.openhab.org/addons/bindings/hue/doc/readme_v2.html) | HIGH | Production integration, rate limit info |
| [HueBlog — Segmented mode](https://hueblog.com/2026/01/03/segmented-new-mode-for-philips-hue-gradient-products/) | MEDIUM | 2026 segment feature for Flux/gradient products |
| [HueBlog — Flux Lightstrip](https://hueblog.com/2025/09/16/hue-flux-lightstrip-new-light-strip-now-available/) | MEDIUM | Flux product details (Sept 2025) |
| [Home Assistant Issue #82264](https://github.com/home-assistant/core/issues/82264) | HIGH | Festavia effects/modes, API structure |
| [openhue-api OpenAPI spec](https://github.com/openhue/openhue-api) | HIGH | Comprehensive resource type enumeration |
