# Phase 5: Gradient Device Support and Polish - Research

**Researched:** 2026-03-31
**Domain:** Philips Hue CLIP v2 gradient device detection, Entertainment API channel-to-segment mapping, capture card reconnect, React/Tailwind UI patterns
**Confidence:** MEDIUM-HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 20-channel limit: soft warning only — do NOT hard-prevent assignment beyond 20 channels
- Always-visible channel counter: "X / 20 channels" displayed in the light panel header at all times
- Yellow/red warning banner above the canvas when total assigned channels exceed 20
- Banner message is a simple count: "22/20 channels assigned — bridge will ignore excess channels." No identification of which specific channels to remove
- Counter updates live as assignments change (no save-then-check)
- Capture card reconnect: add auto-retry with exponential backoff on disconnect (overrides Phase 3 "stop entirely" behavior)

### Claude's Discretion
- Gradient device detection approach (CLIP v2 `gradient.pixel_count` vs `points_capable` vs channel enumeration)
- Entertainment config channel-to-light backward mapping implementation
- Per-segment channel ID resolution strategy
- Festavia/Flux segment count handling (empirical hardware validation required)
- Capture card reconnect backoff timing and retry limits
- How segment rows integrate with existing drag-to-assign flow

### Deferred Ideas (OUT OF SCOPE)
- Per-light color preview widgets showing current output color (v2 AUI-04)
- Configurable color saturation boost / brightness scaling per light (v2 COLR-02)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BRDG-04 | Gradient-capable devices (Festavia, Flux, Play Gradient) identified with per-segment channel count | Channel members in entertainment config carry SegmentReference with service RID + index; detect via `gradient.points_capable` on light resource |
| GRAD-01 | Festavia string light segments individually assignable to regions | Per-segment LightPanel rows + entertainment config channel enumeration; hardware count validation required |
| GRAD-02 | Flux lightstrip segments individually assignable to regions | Treat as Play Gradient (7 channels) by analogy; hardware confirmation needed |
| GRAD-03 | Play Gradient Lightstrip per-segment control | Confirmed 7 channels from entertainment config; channel-granular streaming already works |
| GRAD-04 | 20-channel Entertainment API limit enforced with warning | Live counter in LightPanel header + conditional warning banner above canvas |
</phase_requirements>

---

## Summary

The core technical challenge of this phase is bridging the gap between how lights are discovered (via `/resource/light`) and how they appear in an entertainment configuration (as N individual channels, one per gradient segment). The channel members structure in the CLIP v2 entertainment configuration resource provides the backward mapping: each `EntertainmentChannel.members` array contains `SegmentReference` objects with a `service` RID pointing to a light service and an `index` identifying the segment. This means detection and mapping are both derivable from the entertainment config — no separate gradient resource API call is required.

The Play Gradient Lightstrip is confirmed at 7 channels in entertainment mode; the Ambiance Gradient Lightstrip shows 3 channels; Festavia's actual count (~5-7) is underdocumented and requires hardware validation. The Flux Lightstrip (released Sept 2025) has no confirmed developer documentation on channel count yet. The existing streaming infrastructure is already channel-granular, so adding more channels per gradient device requires no changes to `_load_channel_map` or `_frame_loop`.

Capture card reconnect is a straightforward extension of the existing `_reconnect_loop` pattern already in `StreamingService`. The bridge reconnect loops with exponential backoff from 1s to 30s; the same parameters are appropriate for the capture device. The only structural difference is that capture reconnect must call `capture.release()` and then `capture.open()` before resuming the frame loop, rather than just re-activating the entertainment config.

**Primary recommendation:** Extend `fetch_entertainment_config_channels` to also return `service_rid` and `segment_index` from each channel's `members[0]`; extend `list_lights` to include `gradient.points_capable` (non-null = gradient device) and `segment_count` from the entertainment config channel enumeration; render N draggable rows per gradient light in LightPanel; compute total channel count reactively in a Zustand selector for the live counter and conditional banner.

---

## Standard Stack

### Core (no new dependencies needed)
| Component | Version | Purpose | Status |
|-----------|---------|---------|--------|
| httpx.AsyncClient | existing | CLIP v2 REST calls for channel enumeration | In use |
| aiosqlite | existing | Persist `segment_count`, `is_gradient` in lights table if caching | In use |
| React + Zustand | existing | Live channel counter computed from regions store | In use |
| Tailwind v4 + cn() | existing | Conditional warning banner styling | In use |

### No New Dependencies
Phase 5 requires no new packages. All detection, mapping, and UI patterns extend existing code.

---

## Architecture Patterns

### Pattern 1: Channel-to-Light Backward Mapping via Entertainment Config

**What:** Each `EntertainmentChannel` in the CLIP v2 response already carries a `members` array. Each member has a `service.rid` (the light service UUID) and an `index` (segment 0-N). This is the backward mapping from channel_id to parent light + segment index.

**When to use:** During `fetch_entertainment_config_channels` — extend to capture member info.

**Raw CLIP v2 response structure (verified via aiohue model):**
```json
{
  "channels": [
    {
      "channel_id": 0,
      "position": {"x": -0.8, "y": 0.0, "z": -0.5},
      "members": [
        {
          "service": {"rid": "<light-service-uuid>", "rtype": "entertainment"},
          "index": 0
        }
      ]
    },
    {
      "channel_id": 1,
      "position": {"x": -0.4, "y": 0.0, "z": -0.5},
      "members": [
        {
          "service": {"rid": "<light-service-uuid>", "rtype": "entertainment"},
          "index": 1
        }
      ]
    }
  ]
}
```

For a 7-segment Play Gradient Lightstrip in a config, the same `service.rid` appears across 7 consecutive channel entries with `index` 0-6. Channels for a non-gradient light have a single member with `index` 0.

**Extended fetch function signature:**
```python
# Source: aiohue/v2/models/entertainment_configuration.py (verified)
async def fetch_entertainment_config_channels(
    bridge_ip: str, username: str, config_id: str
) -> list[dict]:
    # Returns: [{channel_id, position, service_rid, segment_index}, ...]
    # service_rid maps back to the light service RID (same as light.id in /resource/light)
    # segment_index is 0 for single-channel lights, 0..N-1 for gradient lights
```

### Pattern 2: Gradient Detection via Light Resource

**What:** The `/resource/light` response includes a `gradient` object for gradient-capable devices. The `points_capable` field is the count of distinct color points the device can accept. When `gradient` is present and `points_capable >= 1`, the light is gradient-capable.

**Verified fields (source: aiohue/v2/models/feature.py):**
```python
class GradientFeature:
    points_capable: int        # number of addressable color points
    pixel_count: int | None    # total pixels (optional, hardware-specific)
    mode: GradientMode         # INTERPOLATED_PALETTE default
    mode_values: list[GradientMode]
    points: list[GradientPoint]  # from GradientFeatureBase
```

**Detection strategy:** Rather than relying solely on `gradient.points_capable` from the light resource, use the entertainment configuration's channel enumeration as ground truth for segment count. A light service RID that appears in N channels with indices 0..N-1 has N segments. This is more reliable than `pixel_count` (which is optional and hardware-dependent) and directly matches what the streaming API consumes.

**Recommended detection approach:**
1. Call `fetch_entertainment_config_channels` (extended) to get channel-to-service mapping
2. Group channels by `service_rid` → count gives actual segment count for that light
3. Light appears N times = N-segment gradient device; appears once = single-channel light
4. Use `gradient.points_capable != null` from light resource as a secondary flag for the `is_gradient` field

### Pattern 3: Segment Rows in LightPanel

**What:** A 7-segment gradient light renders as 7 draggable rows in LightPanel, one per segment. Each row carries `channel_id` instead of `light_id` in dataTransfer.

**Segment display format:**
```
Play Gradient Strip       [gradient]
  Segment 1 (ch 0)
  Segment 2 (ch 1)
  ...
  Segment 7 (ch 6)
```

**Drag payload (extend HTML5 dataTransfer):**
```typescript
// For a gradient segment row drag:
e.dataTransfer.setData('channelId', String(channel.channel_id))
e.dataTransfer.setData('channelName', `${light.name} – Seg ${channel.segment_index + 1}`)
e.dataTransfer.setData('lightId', light.id)  // parent light ID for display
```

**Canvas drop handler** already uses `channel_id` via `light_assignments` table — the drop just resolves the channel_id from dataTransfer instead of looking up light_id → channel_id through the config.

### Pattern 4: Live Channel Counter (Zustand Derived State)

**What:** Total assigned channels = count of regions with a non-null `channel_id` in `light_assignments`, plus count of regions assigned to non-gradient lights (each counts as 1). Computed reactively.

**Since the regions store tracks `light_id` (not `channel_id` directly), the counter needs the channel mapping.** The cleanest approach: maintain a separate `assignedChannelCount` in LightPanel state, updated when regions change. A region assigned to a single-channel light = 1 channel; a region assigned to a gradient segment = 1 channel (since each segment IS a channel).

**Counter logic:**
```typescript
// Each assigned region already maps to exactly 1 channel_id in light_assignments
// So total channels = regions.filter(r => r.light_id !== null).length
// This works because: single lights have 1 channel; gradient segments are modeled
// as separate draggable items each tied to 1 channel_id
const assignedCount = regions.filter(r => r.light_id !== null).length
```

**Warning threshold:** `assignedCount >= 20` → yellow banner; `assignedCount > 20` → red banner (or just yellow — user decision not fully specified, Claude's discretion: use yellow for >=20, red for >20).

### Pattern 5: Capture Card Reconnect Loop

**What:** When `cap.read()` returns `False` (device disconnected), instead of entering error state, retry `capture.open()` with exponential backoff. Continue the frame loop once reconnected. Push a distinct "reconnecting" status to the broadcaster during retry.

**Reuse existing `_reconnect_loop` pattern from `StreamingService`:**
```python
# Source: Backend/services/streaming_service.py lines 315-352
async def _capture_reconnect_loop(self) -> bool:
    """Reconnect capture device with exponential backoff.

    Delays: 1s, 2s, 4s, 8s, 16s, 30s (capped).
    Returns True if reconnected, False if run_event cleared.
    """
    delay = 1
    max_delay = 30
    self._state = "reconnecting"
    await self._broadcaster.push_state("reconnecting")

    while self._run_event.is_set():
        try:
            self._capture.release()
            self._capture.open()
            logger.info("Capture device reconnected")
            self._state = "streaming"
            await self._broadcaster.push_state("streaming")
            return True
        except RuntimeError as exc:
            logger.warning("Capture reconnect failed: %s, retrying in %ds", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    return False
```

**Where to call it:** In `_frame_loop`, catch `RuntimeError` from `get_frame()` and call `_capture_reconnect_loop()` instead of returning immediately. If reconnect returns False (stopped), exit frame loop normally.

### Anti-Patterns to Avoid
- **Don't read `pixel_count` as segment count**: `pixel_count` is optional and represents total LED pixels, not the number of independently addressable entertainment channels. Use channel enumeration instead.
- **Don't store segment_count on the light resource**: The entertainment config is the authoritative source; segment count can differ across configs for the same light. Resolve at config-load time.
- **Don't rebuild channel map on every frame**: `_load_channel_map` is called once at stream start. The channel map is constant for a given config.
- **Don't use `light_id` for gradient segment drags**: Gradient segments share a `light_id` (the parent light). Each segment needs its own `channel_id` as the draggable identifier.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Gradient detection | Custom product archetype string matching | Channel count from entertainment config members | Archetype strings are unreliable; channel membership is ground truth |
| Channel counter | Manual count loop in render | `regions.filter(r => r.light_id !== null).length` | Regions already map 1:1 to channels in the assignment model |
| Conditional CSS | Manual class string concatenation | `cn()` already in codebase (shadcn dependency) | Tailwind v4 class purging requires static detection |
| Backoff timer | Custom Promise-based timer | `asyncio.sleep(delay)` + doubling | Standard Python asyncio pattern, already used in bridge reconnect |

---

## Common Pitfalls

### Pitfall 1: Confusing light.id with entertainment service RID
**What goes wrong:** `channel.members[0].service.rid` is the entertainment service RID, which is NOT the same UUID as the light's `/resource/light` ID. The light resource and entertainment resource have different IDs for the same physical device.
**Why it happens:** CLIP v2 uses separate resource types (`light`, `entertainment`, `device`) that reference each other via services arrays.
**How to avoid:** When fetching lights via `/resource/light`, also fetch the entertainment service RID from the device's services array (or cross-reference via `/resource/entertainment`). Alternatively, build the light-to-entertainment-service mapping from the entertainment config's `light_services` list.
**Warning signs:** Channel assignments appear to work in the map but no channels are highlighted in the UI — means the RID lookup is returning null.

### Pitfall 2: Festavia actual channel count unknown
**What goes wrong:** Rendering a hardcoded 7-segment UI for Festavia when the actual config may expose fewer channels.
**Why it happens:** Festavia channel count (~5-7) is underdocumented in official sources. The Hueblog FAQ mentions "one entertainment zone with ten lights" but this refers to the Hue app zone limit, not the individual Entertainment API channel count.
**How to avoid:** Use the entertainment config channel enumeration as ground truth. Count how many channels reference the Festavia service RID — that IS the segment count. Never hardcode it.
**Warning signs:** Segment rows in LightPanel show 7 but only 5 channels emit non-zero color.

### Pitfall 3: Capture reconnect blocking the asyncio event loop
**What goes wrong:** `capture.open()` calls `cv2.VideoCapture(path, cv2.CAP_V4L2)` which can block for several seconds if the device is absent.
**Why it happens:** V4L2 open is a synchronous blocking call; the existing `open()` method is not wrapped in `asyncio.to_thread`.
**How to avoid:** Wrap `self._capture.open()` in `await asyncio.to_thread(self._capture.open)` inside `_capture_reconnect_loop`, matching the pattern used for `streaming.start_stream`.
**Warning signs:** WebSocket status messages stop updating during reconnect attempts — means the event loop is blocked.

### Pitfall 4: service.rid vs light_id mismatch in drag payload
**What goes wrong:** Dragging a gradient segment onto the canvas and the drop handler fails to find a channel_id match.
**Why it happens:** The drag payload uses a new `channelId` key but the existing drop handler in EditorCanvas looks for `lightId`. Both paths need to co-exist.
**How to avoid:** In the drop handler, check for `channelId` first; fall back to `lightId` for non-gradient lights. The `light_assignments` table already stores `channel_id` as the canonical key.

### Pitfall 5: Counter includes regions without active config
**What goes wrong:** The channel counter shows assignments from a different entertainment config than the one currently selected.
**Why it happens:** `light_assignments` stores `(region_id, channel_id, entertainment_config_id)`. If regions from config A are still in the store when config B is selected, the count is wrong.
**How to avoid:** Filter the counter by `selectedConfigId`. The region store's `regions` array maps to `light_assignments` rows — include `entertainment_config_id` in the region/assignment model returned by `GET /api/regions`.

---

## Code Examples

### Extend fetch_entertainment_config_channels to include member info

```python
# Source: Backend/services/hue_client.py (extend existing function)
async def fetch_entertainment_config_channels(
    bridge_ip: str, username: str, config_id: str
) -> list[dict]:
    url = f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration/{config_id}"
    headers = {"hue-application-key": username}
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    channels = []
    config_data = data.get("data", [{}])[0]
    for ch in config_data.get("channels", []):
        members = ch.get("members", [])
        first_member = members[0] if members else {}
        channels.append({
            "channel_id": ch["channel_id"],
            "position": ch.get("position", {"x": 0.0, "y": 0.0, "z": 0.0}),
            "service_rid": first_member.get("service", {}).get("rid"),
            "segment_index": first_member.get("index", 0),
        })
    return channels
```

### Detect gradient lights by grouping channels per service_rid

```python
from collections import defaultdict

def build_light_segment_map(channels: list[dict]) -> dict[str, int]:
    """Map service_rid -> segment count from channel list.

    Args:
        channels: List from fetch_entertainment_config_channels (extended)
    Returns:
        Dict mapping service_rid to number of segments
    """
    counts: dict[str, int] = defaultdict(int)
    for ch in channels:
        rid = ch.get("service_rid")
        if rid:
            counts[rid] += 1
    return dict(counts)

# Usage: lights with count > 1 are gradient; count == 1 is single-channel
```

### Extend list_lights to include gradient fields

```python
# Source: Backend/services/hue_client.py (extend list_lights)
# Add gradient feature fetch from /resource/light response
for item in light_data.get("data", []):
    light_id = item["id"]
    light_type = rid_to_archetype.get(light_id, "light")
    gradient = item.get("gradient")
    is_gradient = gradient is not None and gradient.get("points_capable", 0) > 0
    lights.append({
        "id": light_id,
        "name": item["metadata"]["name"],
        "type": light_type,
        "is_gradient": is_gradient,
        "points_capable": gradient.get("points_capable", 0) if gradient else 0,
    })
# Note: segment_count requires entertainment config context — resolve at config-load time
```

### LightPanel gradient segment rows (React/TypeScript)

```typescript
// Source: project pattern — extend LightPanel.tsx
// Gradient light renders as parent header + N segment rows

interface LightWithSegments extends Light {
  is_gradient: boolean
  segments?: Array<{ channel_id: number; segment_index: number }>
}

// For each gradient light, render collapsed/expandable segment list:
{light.is_gradient && light.segments?.map((seg) => (
  <div
    key={`${light.id}-seg-${seg.segment_index}`}
    draggable
    onDragStart={(e) => {
      e.dataTransfer.setData('channelId', String(seg.channel_id))
      e.dataTransfer.setData('channelName', `${light.name} – Seg ${seg.segment_index + 1}`)
      e.dataTransfer.effectAllowed = 'copy'
    }}
    className="flex items-center gap-1 rounded px-2 py-1 border-l-2 border-primary/30 ml-3 cursor-grab hover:bg-accent"
  >
    <span className="text-xs text-muted-foreground">Seg {seg.segment_index + 1}</span>
    <span className="text-[10px] text-muted-foreground">ch {seg.channel_id}</span>
  </div>
))}
```

### Channel counter and warning banner

```typescript
// Channel counter in LightPanel header (always visible):
const assignedCount = regions.filter(r => r.light_id !== null).length
const isOverLimit = assignedCount > 20
const isAtLimit = assignedCount >= 20

// Header display:
<span className={cn(
  "text-xs font-mono",
  isAtLimit && "text-yellow-500",
  isOverLimit && "text-red-500"
)}>
  {assignedCount} / 20 channels
</span>

// Warning banner in EditorPage (above canvas, below toolbar):
{isOverLimit && (
  <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-600 dark:text-yellow-400 text-xs px-3 py-2 text-center">
    {assignedCount}/20 channels assigned — bridge will ignore excess channels.
  </div>
)}
```

### Capture reconnect in _frame_loop

```python
# Source: StreamingService._frame_loop — modify RuntimeError handling
try:
    frame = await self._capture.get_frame()
except RuntimeError as exc:
    logger.warning("Capture device error: %s — attempting reconnect", exc)
    success = await self._capture_reconnect_loop()
    if not success:
        self._state = "error"
        await self._broadcaster.push_state("error", error=str(exc))
        return
    # Reconnected — continue frame loop on next iteration
    continue
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| V1 Entertainment API (whole-device only) | V2 Entertainment API (per-segment channel) | 2021 (Play Gradient release) | Gradient devices now expose N channels in entertainment config |
| Detect gradient via archetype string | Detect via entertainment config channel count | This phase | More reliable — config is ground truth for streaming behavior |
| Stop on capture disconnect | Exponential backoff reconnect | This phase | Eliminates manual intervention after cable wiggle |

**Deprecated/outdated:**
- V1 Entertainment API `type: 0x00` group addressing: cannot address gradient segments individually; V2 per-channel addressing (what this project already uses) is required
- `pixel_count` as segment count: it represents total LEDs, not Entertainment API channels; Play Gradient has 84 pixels but only 7 channels

---

## Segment Count Reference

| Device | Entertainment Channels | Confidence | Source |
|--------|----------------------|------------|--------|
| Play Gradient Lightstrip | 7 | HIGH | Multiple verified sources (HyperHDR, aiohue, community) |
| Ambiance Gradient Lightstrip | 3 | MEDIUM | Community sources (HyperHDR discussion, Hueblog) |
| Festavia string lights | ~5-7 (unconfirmed) | LOW | Inferred from community; no official documentation |
| Flux Lightstrip (2025) | Unknown (treat as 7) | LOW | No developer documentation found; released Sept 2025 |

**Critical:** Festavia and Flux segment counts MUST be validated with physical hardware before finalizing the segment display UI. The implementation should derive segment count from the entertainment config channel enumeration — never hardcode.

---

## Open Questions

1. **light.id vs entertainment service RID**
   - What we know: `channel.members[0].service.rid` is the entertainment service RID; `/resource/light` items have their own IDs
   - What's unclear: Are the entertainment service RIDs the same as light resource IDs, or do they require a cross-reference via `/resource/entertainment`?
   - Recommendation: During implementation, log both IDs for a known gradient device and verify whether they match. If they don't, fetch `/resource/entertainment` to build the mapping. The `light_services` array on `EntertainmentConfiguration` may provide this link.

2. **Festavia actual channel count**
   - What we know: Festavia is gradient-capable; entertainment zone limit is 10 lights; actual channel count per device is ~5-7 per community reports
   - What's unclear: The official per-device Entertainment API channel count
   - Recommendation: Validate with physical Festavia by inspecting `channels` array in entertainment config response. Log service_rid grouping to confirm count. Do not ship this phase without hardware confirmation (existing project blocker).

3. **Zustand region store and channel_id**
   - What we know: Region store currently tracks `light_id` per region; `light_assignments` table stores `channel_id`
   - What's unclear: Whether regions assigned to gradient segments need to store `channel_id` in the region store (not just the DB) for the counter to work correctly per config
   - Recommendation: Extend region model to include `channel_id: number | null` and `entertainment_config_id: string | null`. The counter filters by `selectedConfigId` to avoid cross-config pollution.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (Backend), vitest (Frontend) |
| Config file | Backend/pytest.ini, Frontend/vite.config.ts |
| Quick run command | `cd Backend && python -m pytest tests/ -x -q` |
| Full suite command | `cd Backend && python -m pytest tests/ && cd ../Frontend && npx vitest run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BRDG-04 | `fetch_entertainment_config_channels` returns `service_rid` and `segment_index` | unit | `pytest tests/test_hue_client.py -x -k channel` | ✅ (extend) |
| BRDG-04 | `build_light_segment_map` groups channels by service_rid correctly | unit | `pytest tests/test_hue_client.py -x -k segment_map` | ❌ Wave 0 |
| GRAD-01/02/03 | Gradient lights appear as N segment rows in LightPanel | manual | visual inspection with physical device | N/A |
| GRAD-04 | Channel counter updates live when assignment changes | unit | `npx vitest run src/store/useRegionStore.test.ts` | ✅ (extend) |
| GRAD-04 | Warning banner renders when `assignedCount > 20` | unit | `npx vitest run src/components/LightPanel.test.tsx` | ❌ Wave 0 |
| BRDG-04 | `list_lights` returns `is_gradient` and `points_capable` | unit | `pytest tests/test_hue_client.py -x -k gradient` | ✅ (extend) |
| Capture reconnect | `_capture_reconnect_loop` retries with backoff | unit | `pytest tests/test_streaming_service.py -x -k reconnect` | ✅ (extend) |
| Capture reconnect | Frame loop continues after reconnect success | unit | `pytest tests/test_streaming_service.py -x -k capture_reconnect` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd Backend && python -m pytest tests/ -x -q`
- **Per wave merge:** `cd Backend && python -m pytest tests/ && cd ../Frontend && npx vitest run`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `Backend/tests/test_hue_client.py` — add tests for extended channel fields (service_rid, segment_index) and `build_light_segment_map`
- [ ] `Frontend/src/components/LightPanel.test.tsx` — covers GRAD-04 warning banner and channel counter display
- [ ] `Backend/tests/test_streaming_service.py` — add test for `_capture_reconnect_loop` with mock capture.open() retry behavior

---

## Sources

### Primary (HIGH confidence)
- [aiohue/v2/models/entertainment_configuration.py](https://github.com/home-assistant-libs/aiohue/blob/main/aiohue/v2/models/entertainment_configuration.py) — `EntertainmentChannel`, `SegmentReference`, `members` structure verified
- [aiohue/v2/models/feature.py](https://github.com/home-assistant-libs/aiohue/blob/main/aiohue/v2/models/feature.py) — `GradientFeature` fields: `points_capable`, `pixel_count`, `mode`
- Project codebase — `StreamingService._reconnect_loop` pattern (lines 315-352), `LatestFrameCapture.open()` blocking behavior

### Secondary (MEDIUM confidence)
- HyperHDR Discussion #512 — Play Gradient Lightstrip confirmed 7 zones; Ambiance confirmed 3 zones
- Hueblog.com — Play Gradient has 7 segments in entertainment mode; Festavia zone limit context
- aiohue/v2/models/light.py — `gradient: GradientFeature | None` field presence confirms detection approach

### Tertiary (LOW confidence)
- Community reports — Festavia channel count ~5-7 (unverified, hardware validation required)
- Hueblog Flux Lightstrip hands-on (Sept 2025) — segment spacing info only; no Entertainment API channel count confirmed

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; extending existing patterns
- Architecture (channel mapping): HIGH — verified via aiohue model which implements the official spec
- Architecture (gradient detection): MEDIUM — `points_capable` field confirmed; cross-RID mapping needs runtime verification
- Pitfalls: MEDIUM — based on code analysis + community reports, not all validated with hardware
- Festavia/Flux segment counts: LOW — hardware validation required, this is a documented project risk

**Research date:** 2026-03-31
**Valid until:** 2026-06-30 (stable Hue API; Flux docs may improve as product matures)
