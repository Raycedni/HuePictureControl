# Phase 19: WLED Strip Paint UI - Pattern Map

**Mapped:** 2026-05-14
**Files analyzed:** 25 (new + modified, per RESEARCH.md `## File Map`)
**Analogs found:** 24 / 25 (RegionOrientationPopover is greenfield — Base UI Popover documented but never used in repo)

> **Planning-time override honored:** This map reflects the **per-region** orientation narrowing (CONTEXT D-16/D-19/D-21/D-22 + RESEARCH override note). Files explicitly excluded: HueStreamer (no changes needed); coordinator nested-dict gradient restructure (NOT needed); `_load_wled_device_rows` does NOT thread per-channel orientation. The coordinator change reduces to: one extra SELECT to resolve the region-scoped orientation in `_build_region_plan`, then one call to `sub_sample_gradient(...)` per region with that resolved orientation.

> **Out of scope (skipped by directive):** HA control endpoints (Phase 18), WledStreamer protocol changes (Phase 17 frozen), WledDevicesPanel.tsx (Phase 17 frozen), wled_streamer.py orientation reads (the gradient is already orientation-resolved at coordinator level).

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Backend/database.py` (orientation + next_channel_n ALTER) | schema migration | one-shot startup | `Backend/database.py:48-61` (existing `regions.light_id` ADD COLUMN migration) | **exact** (same file, same pattern) |
| `Backend/services/wled_channels.py` (NEW) | backend service | CRUD + atomic transaction | `Backend/routers/wled.py:286-329` (3-statement cascade-delete txn) + `Backend/services/streaming_coordinator.py::_load_wled_device_rows` (aiosqlite SELECT pattern) | role-match |
| `Backend/services/color_math.py::sub_sample_gradient` extension | backend pure-function service | transform (frame → ndarray) | itself, lines 201-255 (the existing function) | **exact** (extending in place) |
| `Backend/services/streaming_coordinator.py::_build_region_plan` (minor) | backend service | request-response (per-frame plan build) | `Backend/services/streaming_coordinator.py:346-388` (existing region_plan SQL) | **exact** (same function) |
| `Backend/routers/wled.py` channel-CRUD additions (5 new endpoints) | FastAPI router | CRUD + request-response | `Backend/routers/wled.py:193-283` (POST device) + `:286-329` (DELETE device cascade) + `:332-370` (PUT enabled) | **exact** (same file, same conventions) |
| `Backend/tests/test_wled_channels.py` (NEW) | backend test | unit (transactional SQL) | `Backend/tests/test_wled_router.py::_make_db()` lines 40-79 (in-memory aiosqlite fixture) | **exact** |
| `Backend/tests/test_wled_router.py` (extend) | backend test | integration | same file's existing test patterns | **exact** (in place) |
| `Backend/tests/test_color_math.py` (extend) | backend test | unit | existing tests for `sub_sample_gradient` | **exact** |
| `Backend/tests/test_database.py` (extend) | backend test | unit | existing init_db idempotency tests | **exact** |
| `Backend/tests/test_phase19_e2e.py` (NEW) | backend test | E2E | `Backend/tests/test_phase17_e2e.py` (full-stack smoke) | role-match |
| `Frontend/src/api/wled.ts` extension (7 new functions) | frontend HTTP client | request-response | `Frontend/src/api/wled.ts:49-79` (existing CRUD functions) | **exact** (same file) |
| `Frontend/src/utils/wled-palette.ts` (NEW) | frontend pure helper | transform (index → HSL string) | `Frontend/src/utils/geometry.ts` (existing pure helper module — closest structural analog; no color helper exists) | role-match |
| `Frontend/src/utils/wled-palette.test.ts` (NEW) | frontend test | unit | `Frontend/src/utils/geometry.test.ts` (pure-function vitest) | **exact** |
| `Frontend/src/components/Settings/wled-paint-reducer.ts` (NEW) | frontend pure helper | state-machine transform | `Frontend/src/utils/geometry.ts` (closest pure-function shape) + Konva drawing state in `EditorCanvas.tsx:60-185` (rect state machine being extracted) | role-match |
| `Frontend/src/components/Settings/wled-paint-reducer.test.ts` (NEW) | frontend test | unit | `Frontend/src/utils/geometry.test.ts` | **exact** |
| `Frontend/src/components/Settings/WledStripPainter.tsx` (NEW) | Konva canvas surface | event-driven (pointer) | `Frontend/src/components/EditorCanvas.tsx:1-185` (Stage/Layer setup + rect state machine + width-from-props pattern) | **exact** (same primitives, same pattern) |
| `Frontend/src/components/Settings/WledStripPainter.test.tsx` (NEW) | frontend test | unit (Konva pure-state) | (none — no existing Konva component tests; pure-state coverage of selection + ResizeObserver only per VALIDATION.md) | no-analog |
| `Frontend/src/components/Settings/WledChannelSidebar.tsx` (NEW) | frontend React component | request-response (auto-save inputs) | `Frontend/src/components/Settings/WledDevicesPanel.tsx` (existing sibling settings component) + the rename input pattern with `onBlur` save | role-match |
| `Frontend/src/components/Settings/SettingsPanel.tsx` (modify) | frontend React component | mounting | itself, lines 38-43 (existing dashed placeholder) | **exact** (in place replacement) |
| `Frontend/src/components/Settings/SettingsPage.tsx` (modify) | frontend React component | mounting | mirror of SettingsPanel.tsx | **exact** |
| `Frontend/src/components/Editor/RegionOrientationPopover.tsx` (NEW) | frontend React component | event-driven (anchor + virtual rect) | **NO project Popover usage exists.** Base UI primitives only used in shadcn-imported ui/* primitives (button/badge/scroll-area/separator). Greenfield Popover integration. | **no-analog** (greenfield — see Base UI section) |
| `Frontend/src/components/Editor/OrientationSegmentedControl.tsx` (NEW) | frontend React component | request-response (PATCH on click) | `Frontend/src/components/ui/button.tsx` (button group composition) + LightPanel sync button at lines 337-353 (auto-action on click pattern) | role-match |
| `Frontend/src/components/LightPanel.tsx` (modify — add WLED section) | frontend React component | drag-source | `Frontend/src/components/LightPanel.tsx:320-440` (existing Lights section + draggable channel rows) | **exact** (same file, near-copy) |
| `Frontend/src/components/EditorCanvas.tsx::handleDrop` (modify — add WLED branch) | frontend React component | event-driven (drag-drop) | `Frontend/src/components/EditorCanvas.tsx:190-233` (existing handleDrop) | **exact** (in place) |
| `Frontend/src/components/EditorCanvas.test.tsx` (NEW) | frontend test | unit (drop handler) | (no existing EditorCanvas test — but LightPanel.test.tsx is the nearest structural sibling for DOM + dataTransfer assertions) | role-match |
| `Frontend/src/store/useRegionStore.ts` (modify — add `wledAssignments` field) | Zustand store | local state | itself, lines 19-50 (existing store) | **exact** |
| `Frontend/playwright.config.ts` (NEW) | config | test runner | no existing playwright config; @playwright/test ^1.59.1 already in package.json | **no-analog** |
| `Frontend/e2e/wled-paint.spec.ts` (NEW) | E2E test | event-driven (pointer) | no existing playwright spec | **no-analog** |

---

## Pattern Assignments

### `Backend/database.py` — orientation + next_channel_n migration block

**Analog:** `Backend/database.py` itself, lines 48-61 (the existing `regions.light_id` ALTER pattern).

**Idempotent ADD COLUMN pattern to COPY VERBATIM** (lines 48-61):
```python
# Migration: add light_id column to existing databases that predate this column
try:
    await db.execute("ALTER TABLE regions ADD COLUMN light_id TEXT")
    await db.commit()
except Exception:
    # Column already exists — safe to ignore OperationalError
    pass
# Migration: add entertainment_config_id to regions for zone-camera join (Phase 9, D-08)
try:
    await db.execute("ALTER TABLE regions ADD COLUMN entertainment_config_id TEXT")
    await db.commit()
except Exception:
    # Column already exists — safe to ignore
    pass
```

**Existing WLED schema for context** (lines 98-126 — where the new ALTER blocks go *after*):
```python
await db.execute("""
    CREATE TABLE IF NOT EXISTS wled_devices (
        id TEXT PRIMARY KEY,
        ip TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        led_count INTEGER NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
""")
# ... (wled_channels CREATE) ...
await db.execute("""
    CREATE TABLE IF NOT EXISTS wled_light_assignments (
        region_id TEXT NOT NULL,
        wled_channel_id TEXT NOT NULL,
        entertainment_config_id TEXT NOT NULL,
        PRIMARY KEY (region_id, wled_channel_id, entertainment_config_id),
        FOREIGN KEY (wled_channel_id) REFERENCES wled_channels(id) ON DELETE CASCADE
    )
""")
await db.commit()
return db
```

**Delta:** Insert two new idempotent `try/except` blocks immediately after line 126 (after the `wled_light_assignments` CREATE):

1. `ALTER TABLE wled_light_assignments ADD COLUMN orientation TEXT NOT NULL DEFAULT 'auto'` (D-16)
2. `ALTER TABLE wled_devices ADD COLUMN next_channel_n INTEGER NOT NULL DEFAULT 1` (Channel-N invariant)

Both wrapped in the **exact** `try / await db.execute / await db.commit / except Exception: pass` shape from lines 49-54.

---

### `Backend/services/wled_channels.py` (NEW)

**Analog (transaction shape):** `Backend/routers/wled.py:286-329` — the existing 3-statement cascade-delete transaction.

**Analog (aiosqlite helper SELECT):** `Backend/services/streaming_coordinator.py:242-324` — the existing `_load_wled_device_rows` JOIN+iterate pattern.

**Cascade-delete txn pattern to MIRROR** (`routers/wled.py:298-329`):
```python
db = request.app.state.db

# Pre-delete existence check — 404 if missing.
async with db.execute(
    "SELECT id FROM wled_devices WHERE id = ?", (device_id,)
) as cur:
    existing = await cur.fetchone()
if existing is None:
    raise HTTPException(
        status_code=404,
        detail=f"WLED device '{device_id}' not found",
    )

# 1) Delete assignments via subquery on this device's channels.
await db.execute(
    "DELETE FROM wled_light_assignments WHERE wled_channel_id IN "
    "(SELECT id FROM wled_channels WHERE device_id = ?)",
    (device_id,),
)

# 2) Delete channels
await db.execute(
    "DELETE FROM wled_channels WHERE device_id = ?", (device_id,)
)

# 3) Delete device
await db.execute(
    "DELETE FROM wled_devices WHERE id = ?", (device_id,)
)
await db.commit()
```

**Channel SELECT pattern to MIRROR** (`streaming_coordinator.py:283-294`):
```python
async with await self._db.execute(
    """
    SELECT wc.id AS channel_id, wc.start_led, wc.end_led, wla.region_id
    FROM wled_channels wc
    LEFT JOIN wled_light_assignments wla
        ON wla.wled_channel_id = wc.id
        AND wla.entertainment_config_id = ?
    WHERE wc.device_id = ?
    """,
    (config_id, dev_id),
) as cur:
    ch_rows = await cur.fetchall()
```

**Delta:** New module exposing pure aiosqlite-coroutine helpers. RESEARCH.md `## Overlap Auto-Split Algorithm` provides the exact pseudocode for `create_channel_with_split` (lines 138-249). Additional helpers needed: `_next_channel_name(db, device_id)` (RESEARCH.md lines 334-348), `resize_boundary(db, left_id, right_id, boundary)` (atomic two-row UPDATE), `delete_channel_with_cascade(db, channel_id)` (mirror cascade-delete shape above, but channel-scoped: assignments first, then the channel row). Wrap the multi-step paths in `try / ... / await db.commit() / except: await db.rollback(); raise`.

---

### `Backend/services/color_math.py::sub_sample_gradient` extension

**Analog:** itself — extending in place, lines 201-255.

**Existing signature to EXTEND** (lines 201-255):
```python
def sub_sample_gradient(
    frame: np.ndarray, region: RegionMask, n: int
) -> np.ndarray:
    """Return an (n, 3) array of RGB means sampled along the region's longest bbox axis.
    ...
    """
    if n <= 1:
        r, g, b = extract_region_color(frame, region)
        return np.array([[r, g, b]], dtype=np.uint8)

    width = region.x2 - region.x1
    height = region.y2 - region.y1
    longest = max(width, height, 1)
    n_effective = max(1, min(n, longest))

    axis_x = width >= height
    roi_frame = frame[region.y1:region.y2, region.x1:region.x2]

    means = np.empty((n_effective, 3), dtype=np.uint8)
    for i in range(n_effective):
        t = i / (n_effective - 1) if n_effective > 1 else 0.0
        if axis_x:
            col_center = int(round(t * (width - 1)))
            slab_x1 = max(col_center - 1, 0)
            slab_x2 = min(col_center + 2, width)
            slab_frame = roi_frame[:, slab_x1:slab_x2]
            slab_mask = region.roi_mask[:, slab_x1:slab_x2]
        else:
            row_center = int(round(t * (height - 1)))
            slab_y1 = max(row_center - 1, 0)
            slab_y2 = min(row_center + 2, height)
            slab_frame = roi_frame[slab_y1:slab_y2, :]
            slab_mask = region.roi_mask[slab_y1:slab_y2, :]
        mean_bgr = cv2.mean(slab_frame, mask=slab_mask)
        # cv2.mean returns BGR; convert to RGB for output
        means[i] = [int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0])]
    return means
```

**Delta:**
- Add `from typing import Literal` at top of module if not present.
- Add `Orientation = Literal["auto", "horizontal-LTR", "horizontal-RTL", "vertical-TTB", "vertical-BTT"]`.
- Extend the signature with `orientation: Orientation = "auto"` (defaults preserve Phase 17 behavior — D-22).
- **Keep the existing `axis_x = width >= height` line** as the fallback when `orientation == "auto"`. Replace it with an if-ladder per RESEARCH.md `## Orientation Enum + Sub-Sample Helper Extension` (lines 400-419) that derives `(axis_x, reverse)` from the enum.
- After the existing slab-sampling loop, apply `if reverse: means = means[::-1]` before the return.
- Slab-sampling loop body itself (lines 237-254) is **unchanged**.

---

### `Backend/services/streaming_coordinator.py::_build_region_plan` (minor)

**Analog:** itself, lines 330-388.

**Existing query to EXTEND** (lines 346-355):
```python
sql = """
    SELECT DISTINCT r.id AS region_id, r.polygon,
           COALESCE(MAX(wc.end_led - wc.start_led + 1), 1) AS n_region
    FROM regions r
    LEFT JOIN light_assignments la ON la.region_id = r.id AND la.entertainment_config_id = :cfg
    LEFT JOIN wled_light_assignments wla ON wla.region_id = r.id AND wla.entertainment_config_id = :cfg
    LEFT JOIN wled_channels wc ON wc.id = wla.wled_channel_id
    WHERE la.region_id IS NOT NULL OR wla.region_id IS NOT NULL
    GROUP BY r.id, r.polygon
"""
```

**Delta (per-region narrowing — supersedes RESEARCH.md GROUP_CONCAT):** Add `MAX(wla.orientation) AS orientation` (or equivalently `MIN(...)` — all rows for a region+config share the same orientation by the per-region invariant enforced at the API layer) so the plan dict can carry a single resolved orientation per region. Resulting tuple per region: `(RegionMask, N_region, orientation_str)` where `orientation_str` defaults to `'auto'` when no WLED assignment exists for that region+config. Pass this `orientation_str` into `sub_sample_gradient` at the existing call site in `_frame_loop` (RESEARCH.md cites line 508). The outer `region_gradients: dict[str, np.ndarray]` contract is **unchanged** (D-22 preserved literally) — only one call per region, one resolved orientation.

---

### `Backend/routers/wled.py` — channel-CRUD additions

**Analog:** existing endpoints in the same file. Three reference blocks:

**Pydantic model declaration pattern** (`routers/wled.py:55-86`):
```python
class WledDeviceIn(BaseModel):
    ip: str = Field(..., pattern=r"^(\d{1,3}\.){3}\d{1,3}$")


class WledDeviceOut(BaseModel):
    id: str
    ip: str
    name: str
    led_count: int
    enabled: bool
    created_at: str
    connected: bool
    last_error: str | None = None
    last_success_at: str | None = None


class WledDevicesResponse(BaseModel):
    devices: list[WledDeviceOut]


class WledEnabledRequest(BaseModel):
    enabled: bool
```

**POST endpoint + HTTPException pattern** (`routers/wled.py:193-283`):
```python
@router.post("/devices", response_model=WledDeviceOut, status_code=201)
async def add_device(body: WledDeviceIn, request: Request) -> WledDeviceOut:
    """Register a new WLED device by IP.
    ...
    """
    db = request.app.state.db

    # Pre-INSERT duplicate check (UNIQUE(ip) on the table is the ultimate
    # safety net, but this gives a clean 409 without firing httpx).
    async with db.execute(
        "SELECT id FROM wled_devices WHERE ip = ?", (body.ip,)
    ) as cur:
        existing = await cur.fetchone()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"WLED device with ip '{body.ip}' already registered",
        )
    # ...
    device_id = str(uuid.uuid4())
    channel_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    # ...
    await db.execute(
        "INSERT INTO wled_devices (id, ip, name, led_count, enabled, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (device_id, body.ip, name, led_count, now_iso),
    )
    await db.execute(
        "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) "
        "VALUES (?, ?, 'Strip', 0, ?, '#ffffff')",
        (channel_id, device_id, led_count - 1),
    )
    await db.commit()
```

**DELETE-with-cascade pattern** (`routers/wled.py:286-329`): full block reproduced under `Backend/services/wled_channels.py` above.

**PUT existence-check pattern** (`routers/wled.py:332-370`):
```python
@router.put("/devices/{device_id}/enabled")
async def set_enabled(
    device_id: str, body: WledEnabledRequest, request: Request
):
    db = request.app.state.db
    async with db.execute(
        "SELECT id FROM wled_devices WHERE id = ?", (device_id,)
    ) as cur:
        existing = await cur.fetchone()
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"WLED device '{device_id}' not found",
        )
    # ...
```

**Delta:** Append the new endpoints after the existing scan route (~line 388). Endpoints per D-21 / RESEARCH.md `## File Map`:
- `GET /api/wled/devices/{device_id}/channels`
- `POST /api/wled/devices/{device_id}/channels` (body: `{start_led, end_led, name?}` — calls `create_channel_with_split` from the new service module)
- `PUT /api/wled/devices/{device_id}/channels/{channel_id}` (rename + resize fields, all optional)
- `PUT /api/wled/devices/{device_id}/channels/boundary` (body: `{left_channel_id, right_channel_id, boundary}` — atomic two-row UPDATE; recommended by RESEARCH.md `## Boundary Drag-Handle Resize`)
- `DELETE /api/wled/devices/{device_id}/channels/{channel_id}` (cascade to assignments — mirror the device-delete shape)
- `PUT /api/wled/assignments` (upsert via `INSERT ... ON CONFLICT(region_id, wled_channel_id, entertainment_config_id) DO UPDATE SET orientation=excluded.orientation`)
- `PATCH /api/wled/regions/{region_id}/orientation?config={config_id}` — **per-region scope (planning-time narrowing)**; body `{orientation}`; one statement: `UPDATE wled_light_assignments SET orientation = ? WHERE region_id = ? AND entertainment_config_id = ?`. Returns count of rows updated.
- `DELETE /api/wled/assignments` (body or query params identifying the triple)

All endpoints use `request.app.state.db`, the same 404/409/422 status conventions, and accept/return Pydantic models declared at the top of the file (between lines 86 and 174).

---

### `Frontend/src/api/wled.ts` extension

**Analog:** itself, lines 49-79. The full existing `addWledDevice` shape is the direct template.

**Full existing function to MIRROR** (`Frontend/src/api/wled.ts:49-57`):
```typescript
export async function addWledDevice(ip: string): Promise<WledDevice> {
  const res = await fetch('/api/wled/devices', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ip }),
  })
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}
```

**WledApiError pattern** (`Frontend/src/api/wled.ts:34-41`):
```typescript
/** Typed API error exposing HTTP status for UI branching. */
export class WledApiError extends Error {
  public status: number
  constructor(status: number, message?: string) {
    super(message ?? `HTTP ${status}`)
    this.name = 'WledApiError'
    this.status = status
  }
}
```

**Delta:** Add the 7 functions listed in RESEARCH.md `## File Map` row for `Frontend/src/api/wled.ts`, each following the `fetch / if (!res.ok) throw new WledApiError(res.status) / return res.json()` shape verbatim. Also add `WledChannel`, `WledAssignment`, and a `WledOrientation` union-literal type at the top of the file alongside the existing interfaces (lines 8-31).

---

### `Frontend/src/utils/wled-palette.ts` (NEW)

**Analog:** `Frontend/src/utils/geometry.ts` — closest structural analog as a pure-function utility module. No existing color helper exists in the project.

**Existing pure-function module shape to MIRROR** (`geometry.ts:1-21`):
```typescript
/**
 * Normalize pixel coordinates to [0..1] range.
 */
export function normalize(
  points: [number, number][],
  width: number,
  height: number,
): [number, number][] {
  return points.map(([x, y]) => [x / width, y / height])
}

/**
 * Denormalize [0..1] coordinates to pixel coordinates.
 */
export function denormalize(
  points: [number, number][],
  width: number,
  height: number,
): [number, number][] {
  return points.map(([x, y]) => [x * width, y * height])
}
```

**Delta:** Single exported pure function `channelColor(index: number): string` returning `\`hsl(${(index * 137.508) % 360}, 60%, 60%)\`` (golden-angle, per UI-SPEC §Color and `.claude/skills/sketch-findings-huepicturecontrol/references/zone-palette.md`). No caching, no DB dependency. JSDoc comment block mirroring the `geometry.ts` style. Co-located test file (`wled-palette.test.ts`) mirrors `geometry.test.ts` structure.

---

### `Frontend/src/components/Settings/WledStripPainter.tsx` (NEW)

**Analog:** `Frontend/src/components/EditorCanvas.tsx` lines 1-185 — the established react-konva Stage/Layer pattern, rect-drawing state machine, and width-from-props sync pattern.

**Stage/Layer setup + width-from-props pattern** (`EditorCanvas.tsx:1-19`, `:241-244`):
```typescript
import { useEffect, useRef, useState } from 'react'
import { Stage, Layer, Image as KonvaImage, Line, Circle } from 'react-konva'
import type Konva from 'konva'
// ...

export interface EditorCanvasProps {
  width: number
  height: number
  // ...
}

export function EditorCanvas({ width, height, ... }: EditorCanvasProps) {
  // ...
  const stageRef = useRef<Konva.Stage>(null)
  // ...
  return (
    <div onDragOver={...} onDrop={handleDrop} ...>
      <Stage
        ref={stageRef}
        width={width}
        height={height}
        // ...
```

**Rect-drawing state machine (mousedown/move/up) to MIRROR** (`EditorCanvas.tsx:145-185`):
```typescript
function handleMouseDown(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
  if (drawingMode !== 'rectangle') return
  const pos = getPointerPos()
  if (!pos) return
  setRectStart(pos)
  setRectPreview(null)
  e.cancelBubble = true
}

function handleMouseMove(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
  if (drawingMode !== 'rectangle' || !rectStart) return
  const pos = getPointerPos()
  if (!pos) return
  const [sx, sy] = rectStart
  const [ex, ey] = pos
  setRectPreview([
    [sx, sy],
    [ex, sy],
    [ex, ey],
    [sx, ey],
  ])
  e.cancelBubble = true
}

async function handleMouseUp(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
  if (drawingMode !== 'rectangle' || !rectStart) return
  const pos = getPointerPos()
  if (!pos) return
  // ...
  setRectStart(null)
  setRectPreview(null)
  await commitPolygon(pts)
  e.cancelBubble = true
}
```

**Pointer-clamp helper to MIRROR** (`EditorCanvas.tsx:113-120`):
```typescript
function getPointerPos(): [number, number] | null {
  const stage = stageRef.current
  if (!stage) return null
  const pos = stage.getPointerPosition()
  if (!pos) return null
  // Clamp to canvas bounds
  return [Math.min(Math.max(pos.x, 0), width), Math.min(Math.max(pos.y, 0), height)]
}
```

**Delta:**
- One `<Stage>` per registered WLED device, rendered in a vertical stack inside the `md:flex-[6]` slot (D-15).
- Use the new pure reducer from `wled-paint-reducer.ts` to drive the painting state machine — extract the state out of the component so it can be unit-tested without JSDOM Konva (per RESEARCH.md `## Testing Strategy`).
- Stage `width` syncs to the container element via `ResizeObserver` in a `useEffect` (RESEARCH.md Risk R4); the height is fixed at 40px per UI-SPEC §Spacing.
- Boundary handle is a Konva `Line` per UI-SPEC and CONTEXT D-03 — `draggable` with `dragBoundFunc` clamping to `[s_A + 1, e_B]` (RESEARCH.md `## Boundary Drag-Handle Resize`). PUT on `onDragEnd` only, never on `onDragMove`.
- Zones are `Rect` nodes with fill from `channelColor(channel.index)` (new helper); selected zone gets `stroke: var(--accent), strokeWidth: 1`.
- Stage handlers call `e.cancelBubble = true` same as the EditorCanvas pattern when the gesture is consumed.

---

### `Frontend/src/components/EditorCanvas.tsx::handleDrop` — additive WLED branch

**Analog:** itself, lines 190-233 (the existing handleDrop).

**Full existing handleDrop to BRANCH** (`EditorCanvas.tsx:190-233`):
```typescript
async function handleDrop(e: React.DragEvent<HTMLDivElement>) {
  e.preventDefault()
  const channelId = e.dataTransfer.getData('channelId')
  const channelName = e.dataTransfer.getData('channelName')
  const lightId = e.dataTransfer.getData('lightId')
  const configId = e.dataTransfer.getData('configId')

  if (!channelId && !lightId) return

  const stage = stageRef.current
  if (!stage) return

  // Update Konva pointer position from the DOM drag event
  stage.setPointersPositions(e)
  const pos = stage.getPointerPosition()
  if (!pos) return

  // Find which region contains the drop point (in pixel space)
  const currentRegions = useRegionStore.getState().regions
  const hit = currentRegions.find((region) => {
    const pixelPolygon = denormalize(region.polygon as [number, number][], width, height)
    return pointInPolygon([pos.x, pos.y], pixelPolygon)
  })

  if (!hit) return

  const assignLightId = lightId || null
  if (!assignLightId) return

  try {
    const update: Parameters<typeof updateRegionAPI>[1] = {
      light_id: assignLightId,
      name: channelName || hit.name,
    }
    if (channelId && configId) {
      update.channel_id = Number(channelId)
      update.entertainment_config_id = configId
    }
    await updateRegionAPI(hit.id, update)
    updateRegionInStore(hit.id, { light_id: assignLightId, name: update.name })
  } catch (err) {
    console.error('Failed to assign light to region:', err)
  }
}
```

**Delta:** Add the WLED probe **before** the existing branch with an early `return` (UI-SPEC §Drag-Drop Payload Contract; RESEARCH.md `## Drag-Drop Branching in EditorCanvas` and Risk R5):
```typescript
// PROBE ORDER: wledChannelId first because it is the unambiguous discriminator.
const wledChannelId = e.dataTransfer.getData('wledChannelId')
if (wledChannelId) {
  // ... compute hit region using the same Konva pointer + pointInPolygon flow ...
  await upsertWledAssignment({
    region_id: hit.id,
    wled_channel_id: wledChannelId,
    entertainment_config_id: e.dataTransfer.getData('entertainment_config_id'),
    orientation: 'auto', // D-18 default
  })
  useRegionStore.getState().setSelectedId(hit.id) // surface the popover
  const updated = await fetchRegions()
  useRegionStore.getState().setRegions(updated)
  return  // CRITICAL — prevents fall-through into the Hue branch
}

// Existing Hue branch UNCHANGED below this line.
```

Existing Hue branch (lines 192-233) **must not be edited**. The new WLED branch sits above it with the explicit `return` to preserve D-13.

---

### `Frontend/src/components/LightPanel.tsx` — WLED section addition

**Analog:** itself, lines 320-440 — the existing Lights section + draggable channel rows. The new WLED section is a near-copy with payload keys swapped and the per-row chip color computed via `channelColor(channel.index)` instead of being absent.

**Section header + counter chip pattern to MIRROR** (`LightPanel.tsx:320-356`):
```tsx
{/* Lights section */}
<div className="flex flex-col gap-2 min-h-0 flex-1">
  <div className="flex items-center justify-between">
    <h2 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Lights</h2>
    <div className="flex items-center gap-2">
      <span
        className={cn(
          'text-[11px] font-mono',
          assignedCount > 20
            ? 'text-red-400'
            : assignedCount === 20
              ? 'text-hue-amber'
              : 'text-muted-foreground',
        )}
      >
        {assignedCount}/20
      </span>
      {/* ... Sync button ... */}
    </div>
  </div>
  <p className="text-[11px] text-muted-foreground/60">Drag a channel onto a region to assign it.</p>
```

**Light header + draggable per-channel row pattern to MIRROR** (`LightPanel.tsx:378-435`):
```tsx
<div key={light.id} className="flex flex-col gap-0.5">
  {/* Light header */}
  <div className="flex items-center justify-between gap-1 rounded-lg px-2.5 py-1.5 bg-white/[0.03] border border-white/[0.06] select-none">
    <span className="text-xs font-semibold truncate text-foreground">{light.name}</span>
    <div className="flex items-center gap-1 shrink-0">
      {hasChannels ? (
        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-hue-orange/10 text-hue-amber/80">
          {lightChannels.length} ch
        </span>
      ) : (
        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/[0.04] text-muted-foreground/60">
          not in config
        </span>
      )}
    </div>
  </div>

  {/* Per-channel draggable rows */}
  {hasChannels && (
    <div className="ml-3 border-l-2 border-hue-orange/20 flex flex-col gap-0.5 pl-1">
      {lightChannels
        .sort((a, b) => a.segment_index - b.segment_index)
        .map((channel) => {
          const segAssignedTo = assignedMap[light.id]
          return (
            <div
              key={channel.channel_id}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData('channelId', String(channel.channel_id))
                e.dataTransfer.setData(
                  'channelName',
                  `${light.name} [${channel.segment_index + 1}/${channel.segment_count}]`,
                )
                e.dataTransfer.setData('lightId', channel.light_id)
                e.dataTransfer.setData('configId', selectedConfigId)
                e.dataTransfer.effectAllowed = 'copy'
              }}
              className="flex flex-col gap-0.5 rounded-lg px-2.5 py-1.5 border border-white/[0.06] cursor-grab active:opacity-60 hover:bg-white/[0.04] select-none transition-colors"
            >
              <div className="flex items-center justify-between gap-1">
                <span className="text-[11px] font-medium text-foreground/80">
                  Seg {channel.segment_index + 1}/{channel.segment_count}
                </span>
                <span className="text-[10px] text-muted-foreground font-mono">
                  ch {channel.channel_id}
                </span>
              </div>
              {segAssignedTo && (
                <span className="text-[10px] text-hue-amber/60">
                  Assigned: {segAssignedTo}
                </span>
              )}
            </div>
          )
        })}
    </div>
  )}
</div>
```

**Delta:** Insert a new "WLED" section between the existing Lights section (which closes at line 441) and the Assignments section (begins at line 443) per RESEARCH.md File Map. Copy the section structure verbatim with the following substitutions:
- Header label `Lights` → `WLED`. Sub-instruction copy is the same line `Drag a channel onto a region to assign it.` (UI-SPEC §Copywriting).
- Counter chip: drop the threshold-color logic (D-14 says count only). Style: `'text-[11px] font-mono text-muted-foreground'` (no `cn` ladder).
- Per-device sub-block replaces per-light sub-block. Meta label is `{device.ip} · {device.led_count} LEDs · {channel_count} channels` (mono).
- `draggable` row payload swaps keys per D-13 / UI-SPEC §Drag-Drop Payload Contract:
  ```typescript
  e.dataTransfer.setData('wledChannelId', channel.id)
  e.dataTransfer.setData('wledDeviceId', device.id)
  e.dataTransfer.setData('wledChannelName', channel.name)
  e.dataTransfer.setData('entertainment_config_id', selectedConfigId)
  e.dataTransfer.effectAllowed = 'copy'
  ```
  **Existing Hue payload keys (`channelId / channelName / lightId / configId`) MUST NOT be set on WLED rows** — they are the discriminator.
- Add a circular chip `<span className="w-2.5 h-2.5 rounded-full" style={{ background: channelColor(channel.index) }} />` on the left of each row (UI-SPEC §LightPanel WLED section).

Section is **hidden entirely** when no WLED devices are registered (UI-SPEC §Empty State Matrix).

---

### `Frontend/src/components/Editor/RegionOrientationPopover.tsx` (NEW — greenfield Popover)

**Analog:** **No existing Popover usage in the project.** `Grep("@base-ui/react", Frontend/src)` returned zero matches; Base UI is only used inside the shadcn-imported primitive files (`button.tsx`, `badge.tsx`, `scroll-area.tsx`, `separator.tsx`) which don't import `popover` sub-module.

**Documented Base UI Popover composition** (per RESEARCH.md `## Region Popover Anchoring`; verified `Frontend/node_modules/@base-ui/react/popover/` directory listing):
- `Popover.Root` (open/onOpenChange controlled mode)
- `Popover.Portal` (mounts under document.body — escapes Konva Stage z-index per Risk R6)
- `Popover.Positioner` (handles auto-flip via `side` / `align` / `sideOffset` / `collisionPadding`)
- `Popover.Popup` (the surface itself)
- `Popover.Arrow` (12×12 beak)
- `Popover.Close` (× button)

**Reference composition from RESEARCH.md lines 669-712:**
```tsx
import { Popover } from '@base-ui/react'
import { useRegionStore } from '@/store/useRegionStore'

export function RegionOrientationPopover({ canvasWidth, canvasHeight }: Props) {
  const selectedId = useRegionStore((s) => s.selectedId)
  const regions = useRegionStore((s) => s.regions)
  const wledAssignments = useRegionStore((s) => s.wledAssignments)
  const setSelectedId = useRegionStore((s) => s.setSelectedId)

  const region = regions.find((r) => r.id === selectedId)
  const assignments = (selectedId && wledAssignments[selectedId]) || []

  // Virtual anchor: compute bbox from region polygon in screen coords
  const virtualAnchor = useMemo(() => {
    if (!region) return null
    return {
      getBoundingClientRect: () => computeRegionBboxInScreen(region, canvasWidth, canvasHeight)
    }
  }, [region, canvasWidth, canvasHeight])

  const open = selectedId !== null && assignments.length > 0

  return (
    <Popover.Root open={open} onOpenChange={(o) => !o && setSelectedId(null)}>
      <Popover.Portal>
        <Popover.Positioner
          anchor={virtualAnchor}
          side="bottom"
          align="start"
          sideOffset={12}
          collisionPadding={8}
        >
          <Popover.Popup className="popover-surface">
            <Popover.Arrow className="popover-beak" />
            {/* assignment rows + segmented control */}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  )
}
```

**Visual styling tokens from UI-SPEC § Color / § Spacing exceptions:**
```css
.popover-surface {
  background: rgba(20, 20, 35, 0.96);
  border: 1px solid var(--glass-border);
  border-radius: 8px;
  padding: 12px;
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(12px);
  z-index: 50;
  width: 280px;
}
.popover-beak { width: 12px; height: 12px; transform: rotate(45deg); }
```

**Delta (per-region narrowing):**
- Render **one** `OrientationSegmentedControl` for the whole region (NOT one per assignment).
- Below the segmented control, render a **read-only** list of assignments: `{channelColor(i) chip}` + `{channel.name} · LEDs {start}–{end}` (en-dash, mono font).
- The 5 buttons in the segmented control map to `auto / → / ← / ↓ / ↑` (Unicode arrows in mono font; UI-SPEC §Copywriting).
- Click handler PATCHes the region-scoped endpoint: `patchRegionOrientation(regionId, configId, orientation)` from the new api/wled.ts function — writes the same value to every row matching `(region_id, entertainment_config_id)`.
- Close triggers per UI-SPEC §RegionOrientationPopover: outside-click (built into Base UI), explicit `×` button (`<Popover.Close aria-label="Close orientation panel">×</Popover.Close>`), region deselect, selection change.
- Mount as a sibling of the Konva `<Stage>` inside `EditorCanvas.tsx` JSX (RESEARCH.md `## Open Questions` Q4) — Portal renders to `document.body` regardless.

---

### `Frontend/src/components/Editor/OrientationSegmentedControl.tsx` (NEW)

**Analog (button group composition):** `Frontend/src/components/ui/button.tsx` + LightPanel's inline Sync button at `LightPanel.tsx:337-353`.

**Sync button click handler shape to MIRROR** (`LightPanel.tsx:337-353`):
```tsx
<Button
  size="xs"
  onClick={() => {
    setError(null)
    getLights()
      .then(setLights)
      .catch(() => setError('Failed to sync lights'))
    if (selectedConfigId) {
      fetchConfigChannels(selectedConfigId)
        .then(setChannels)
        .catch((err) => console.error('Failed to reload channels:', err))
    }
  }}
  className="bg-white/[0.04] text-muted-foreground border-white/[0.08] hover:bg-white/[0.08] hover:text-foreground h-5 text-[10px] px-1.5"
>
  Sync
</Button>
```

**Delta:** 5-button group, each a `<button type="button">` (or `Button` from `ui/button`). Active button styling per UI-SPEC §Color "Accent reserved for #4": `background: var(--accent-bg); color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent-border)`. Click handler fires the PATCH immediately (auto-save on click, no Apply button) per UI-SPEC §Interaction Contract. Optimistic UI: update local state before awaiting the PATCH; revert on error with an inline `text-red-400 text-[10px]` line (UI-SPEC §Empty/Loading/Error Matrix).

---

### `Frontend/src/components/Settings/SettingsPanel.tsx` & `SettingsPage.tsx`

**Analog:** `SettingsPanel.tsx:38-43` — the existing dashed-border placeholder.

**Existing placeholder to REPLACE** (`SettingsPanel.tsx:35-43`):
```tsx
{/* D-20: Phase 19 paint canvas slot. Hidden on mobile so the
    device CRUD always fits; reappears at md+ alongside the
    device list. */}
<div
  className="hidden md:flex md:flex-[6] items-center justify-center border border-dashed border-white/[0.1] rounded text-xs text-muted-foreground min-h-[200px]"
  data-testid="paint-canvas-placeholder"
>
  WLED strip paint canvas (Phase 19)
</div>
```

**Delta:** Replace with `<WledStripPainter />` (top) + `<WledChannelSidebar />` (bottom) stacked vertically inside the `md:flex-[6]` slot. The `md:flex-[4]` column with `<WledDevicesPanel />` (lines 44-46) is **unchanged**. Mirror the same replacement in `SettingsPage.tsx:17-22` per CONTEXT canonical refs.

---

### `Frontend/src/store/useRegionStore.ts` extension

**Analog:** itself, full file (50 lines).

**Existing store shape to EXTEND**:
```typescript
interface RegionState {
  regions: Region[]
  selectedId: string | null
  drawingMode: 'select' | 'rectangle' | 'polygon'
  drawingPoints: [number, number][]
  setRegions: (r: Region[]) => void
  addRegion: (r: Region) => void
  updateRegion: (id: string, patch: Partial<Region>) => void
  deleteRegion: (id: string) => void
  setSelectedId: (id: string | null) => void
  setDrawingMode: (m: RegionState['drawingMode']) => void
  appendPoint: (pt: [number, number]) => void
  clearDrawing: () => void
}

export const useRegionStore = create<RegionState>((set) => ({
  regions: [],
  selectedId: null,
  // ...
  setRegions: (r) => set({ regions: r }),
  // ...
}))
```

**Delta:** Add `wledAssignments: Record<string, WledAssignment[]>` to the state interface + initial state, plus a `setWledAssignments` setter mirroring the `setRegions` shape. Imports a `WledAssignment` type from `@/api/wled` (added there).

---

### `Backend/tests/test_wled_channels.py` (NEW)

**Analog:** `Backend/tests/test_wled_router.py::_make_db()` lines 40-79.

**In-memory aiosqlite fixture to REUSE** (`test_wled_router.py:40-79`):
```python
async def _make_db():
    """In-memory aiosqlite with the Plan 17-02 wled_* tables."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wled_devices (
            id TEXT PRIMARY KEY,
            ip TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            led_count INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wled_channels (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            name TEXT NOT NULL,
            start_led INTEGER NOT NULL,
            end_led INTEGER NOT NULL,
            color TEXT NOT NULL DEFAULT '#ffffff'
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wled_light_assignments (
            region_id TEXT NOT NULL,
            wled_channel_id TEXT NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, wled_channel_id, entertainment_config_id)
        )
        """
    )
    await conn.commit()
    return conn
```

**Delta:** Either import `_make_db` from `test_wled_router` (best — DRY) or duplicate the function with the Phase 19 additions (orientation column + next_channel_n column). Test cases A-G from the Overlap Auto-Split table in RESEARCH.md §Overlap Auto-Split Algorithm. Each test:
- Calls `_make_db()`
- Seeds devices + initial channels
- Invokes the new service helper (`create_channel_with_split`, `resize_boundary`, etc.)
- Asserts row counts, identity preservation (left-half keeps original `id`), cascade behavior, and transaction atomicity (raise mid-step → no row changes).

`pytest.ini` already has `asyncio_mode = auto`, so async tests don't need decorators.

---

## Shared Patterns

### Auth / Trust Boundary

**Source:** project convention (CLAUDE.md "No auth — Web UI is unauthenticated").
**Apply to:** all new endpoints in `Backend/routers/wled.py`.

No auth middleware, no decorators. Endpoints rely on Pydantic body validation for shape checks (see `WledDeviceIn(BaseModel)` at `routers/wled.py:55-56`) and explicit `HTTPException(status_code=..., detail=...)` for business-rule failures (404/409/422/502). The IP validation regex on `WledDeviceIn.ip` is the ONLY pattern-validation in the file — channel/assignment endpoints validate ranges (`0 <= start_led <= end_led < led_count`) via explicit checks inside the handler, raising 422 with a clear `detail` string.

### Error Handling (Backend)

**Source:** `Backend/routers/wled.py:217-252` — the existing 409/502/422 mapping in `add_device`.
**Apply to:** all new channel-CRUD and assignment endpoints.

```python
raise HTTPException(
    status_code=409,
    detail=f"WLED device with ip '{body.ip}' already registered",
)
# ... or ...
raise HTTPException(
    status_code=422,
    detail=f"WLED device reported led_count={led_count}; refusing to register.",
)
# ... or ...
raise HTTPException(
    status_code=404,
    detail=f"WLED device '{device_id}' not found",
)
```

Channel-CRUD specifics:
- 404 when channel/device id not found.
- 422 when range invalid (`start_led > end_led`, out of `[0, led_count-1]`, etc.).
- 409 when API-level region-scope orientation invariant would be violated (the per-region PATCH endpoint enforces "all rows for this region+config have the same orientation" — but since it WRITES that invariant in one statement, the only failure mode is 404 region/config not found).

### Error Handling (Frontend)

**Source:** `Frontend/src/api/wled.ts:34-41` — `WledApiError` typed error.
**Apply to:** all new HTTP helpers in `Frontend/src/api/wled.ts`.

```typescript
export class WledApiError extends Error {
  public status: number
  constructor(status: number, message?: string) {
    super(message ?? `HTTP ${status}`)
    this.name = 'WledApiError'
    this.status = status
  }
}

// Usage pattern (from existing addWledDevice):
const res = await fetch('/api/wled/devices', { ... })
if (!res.ok) throw new WledApiError(res.status)
return res.json()
```

UI consumers catch `WledApiError` and branch on `.status` (e.g. 409 → conflict toast, 422 → inline validation error, 502 → "device unreachable").

Drop-handler failures in `EditorCanvas.tsx` use **console.error only** (existing convention at `EditorCanvas.tsx:231`):
```typescript
} catch (err) {
  console.error('Failed to assign light to region:', err)
}
```

### Transactional SQL (Backend)

**Source:** `Backend/routers/wled.py:286-329` — the 3-statement cascade-delete in `delete_device`.
**Apply to:** `Backend/services/wled_channels.py` (overlap-split + resize-boundary + delete-with-cascade).

Pattern:
1. Existence check via `async with db.execute("SELECT ...") as cur; await cur.fetchone()` — raise 404 early.
2. Statement 1, statement 2, statement 3 — no intermediate commits.
3. Single `await db.commit()` at the end.
4. Cascade FKs are **not enforced** by SQLite (per `database.py:92-97`); cascade in app code with explicit DELETE-of-assignments-first then DELETE-of-channels.
5. For the multi-branch overlap-split, wrap the body in `try / ... commit / except: await db.rollback(); raise` (RESEARCH.md Risk R11 — split has higher error surface than the simpler cascade-delete).

### Auto-save on Change (Frontend)

**Source:** Phase 10 D-05 / Phase 16 D-03 (cited in CONTEXT canonical refs); `LightPanel.tsx` change handlers (e.g. `handleZoneChange` at lines 154-166) write through to the API on every change without an explicit Save button.
**Apply to:** orientation segmented control (PATCH on click), channel rename input (PUT on blur/Enter), start/end LED inputs (PUT on blur), drag-and-drop assignment (PUT on drop).

No "Apply" or "Save" buttons in any Phase 19 surface. All field-level changes commit immediately.

### `data-testid` for tests

**Source:** Phase 17 D-20 reserved `data-testid="paint-canvas-placeholder"` on the SettingsPanel slot; `WledDevicesPanel.test.tsx` uses `wled-add-button` etc.
**Apply to:** all new paint-UI surfaces. RESEARCH.md and UI-SPEC reference Wave 0 tests that target specific test ids — planner picks the actual strings but the convention is `wled-strip-*`, `wled-channel-*`, `region-orientation-*`.

### Pydantic Request/Response Models per Router

**Source:** `Backend/routers/wled.py:55-86` — every endpoint has a typed `*In` body and `*Out` response model.
**Apply to:** every new endpoint added by Phase 19.

Channel-CRUD additions need: `WledChannelOut`, `WledChannelsResponse`, `WledChannelCreate` (body for POST), `WledChannelUpdate` (body for PUT — all fields optional for partial update), `WledChannelBoundaryUpdate`, `WledAssignmentUpsert`, `WledOrientationUpdate`. All `class ... (BaseModel)` declared at the top of the file alongside the existing five models.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `Frontend/src/components/Editor/RegionOrientationPopover.tsx` | Popover component | event-driven | No project Popover usage exists — Base UI is installed but only used via shadcn-imported primitives. Greenfield Base UI Popover integration. Follow RESEARCH.md §Region Popover Anchoring + base-ui.com/react/components/popover documentation. |
| `Frontend/src/components/Settings/WledStripPainter.test.tsx` | Konva component test | unit | No existing Konva component test exists in the project (`EditorCanvas.tsx` has no test file). Test the pure paint reducer + ResizeObserver only; defer pointer integration to Playwright per VALIDATION.md. |
| `Frontend/playwright.config.ts` | Playwright config | n/a | `@playwright/test ^1.59.1` is in package.json but no config file exists. Wave 0 seeds a minimal config: `baseURL: 'http://localhost:8091'`, `testDir: './e2e'`, single chromium project (matches dev-server port from CLAUDE.md). |
| `Frontend/e2e/wled-paint.spec.ts` | Playwright spec | event-driven | No existing playwright spec. New file using `page.mouse.down() / page.mouse.move() / page.mouse.up()` to drive Konva paint gestures, asserting DB state via follow-up `GET /api/wled/devices/{id}/channels` calls. |

---

## Metadata

**Analog search scope:**
- `Backend/database.py` (full)
- `Backend/routers/wled.py` (full — channel CRUD analogs)
- `Backend/services/color_math.py` lines 180-256 (sub_sample_gradient)
- `Backend/services/streaming_coordinator.py` lines 230-388 (load device rows + region plan)
- `Backend/tests/test_wled_router.py` lines 1-85 (in-memory fixture)
- `Frontend/src/components/EditorCanvas.tsx` lines 1-233 (Stage + state machine + handleDrop)
- `Frontend/src/components/LightPanel.tsx` lines 1-441 (section + draggable row pattern)
- `Frontend/src/api/wled.ts` (full — WledApiError + CRUD)
- `Frontend/src/store/useRegionStore.ts` (full)
- `Frontend/src/utils/*.ts` (color helper search — none exists)
- `Frontend/src/components/Settings/SettingsPanel.tsx` (placeholder slot)
- `Frontend/src/components/ui/*.tsx` (Popover search — confirmed none)
- `Frontend/src/` Grep for `@base-ui/react` and `Popover` (zero matches outside `ui/*.tsx`)

**Files scanned:** ~15 source files, 4 test files, 1 store, plus directory listings of `Frontend/src/utils/`, `Frontend/src/components/ui/`, and `Frontend/src/components/Settings/`.

**Pattern extraction date:** 2026-05-14

**Override compliance:** All analog references reflect the planning-time per-region narrowing. No analog references the deprecated nested-dict gradient restructure; no HueStreamer analogs cited; `_load_wled_device_rows` is referenced only as a SQL-shape analog for the new `wled_channels.py` service, not as a file that itself needs orientation threading.
