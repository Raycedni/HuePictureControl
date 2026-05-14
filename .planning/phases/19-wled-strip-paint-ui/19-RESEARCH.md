# Phase 19: WLED Strip Paint UI — Research

**Researched:** 2026-05-14
**Domain:** SQLite range geometry + Konva interactions + Base UI popover + per-assignment orientation
**Confidence:** HIGH (CONTEXT.md/UI-SPEC.md lock 22+ decisions; this research pins the algorithms and file-level integration)

> This document does NOT re-state CONTEXT.md or UI-SPEC.md. It pins down the algorithms, helper signatures, file paths, line numbers, and risk surface the planner must reason about. Source-of-truth references remain `19-CONTEXT.md`, `19-UI-SPEC.md`, the sketch-findings skill, and Phase 17 artifacts.

> **PLANNING-TIME OVERRIDE (2026-05-14):** This research originally recommended a nested `{region_id: {orientation: ndarray}}` coordinator gradient dict (Option B in the "Orientation Enum + Sub-Sample Helper Extension" section) because it assumed per-assignment orientation. **That recommendation is REJECTED.** During /gsd-plan-phase 19 the user chose to **narrow orientation to per-region scope** — see updated CONTEXT.md D-16/D-19/D-21/D-22.
>
> **Implications for the planner — supersedes Option A/B discussion below:**
> - Coordinator gradient dict stays literally `{region_id: ndarray}` (D-22 untouched). No nested dict.
> - `sub_sample_gradient` is still extended with the `orientation` parameter — that change is unchanged.
> - In `_build_region_plan`, the region's orientation is resolved by querying any one row from `wled_light_assignments` for `(region_id, entertainment_config_id)` (all rows for a region+config carry the same value, enforced at the API layer). Fall back to `'auto'` if no WLED assignment exists for that region+config.
> - `_load_wled_device_rows` does NOT need to thread per-channel orientation through the channel dict — the gradient passed to the WLED sink is already orientation-resolved at the coordinator.
> - API: replace `PATCH /api/wled/assignments/{id}/orientation` with **`PATCH /api/wled/regions/{region_id}/orientation?config={config_id}`** — body `{orientation}`, writes the same value to every row matching `(region_id, entertainment_config_id)` in one statement.
> - UI: the popover renders **one segmented control per region** + a read-only list of the channels assigned to that region, not one segmented control per assignment.
>
> The Channel-N numbering, overlap auto-split, idempotent migration for the `orientation` column, drag-drop branching, popover library choice (Base UI), and testing strategy sections all remain valid as-written.

---

## Summary

Phase 19 is built on top of a fully-shipped Phase 17 backend (`wled_devices`, `wled_channels`, `wled_light_assignments` tables; `WledStreamer.render` consuming `(N,3)` gradients; coordinator's `_build_region_plan` already computing `N_region = MAX(end_led - start_led + 1)` over WLED assignments). The phase introduces (a) a Konva-based paint UI on the Settings paint slot, (b) channel CRUD with overlap auto-split semantics, (c) a per-assignment `orientation` enum that overrides the bbox-longest-axis sub-sample, and (d) a Base UI popover anchored to the selected region for orientation editing.

The five hardest sub-problems are:

1. The overlap auto-split algorithm — a single SQLite transaction that splits/swallows/resizes existing channels when a paint range is inserted.
2. The `Channel N` monotonic numbering invariant — `MAX(N)+1` per device, freed numbers never reused, seed `Strip` channel has no N (string only).
3. Extending `sub_sample_gradient` with an `orientation` enum that forces axis + reverse — the four explicit values must override the longest-axis fallback; `auto` preserves existing behavior.
4. The idempotent `ALTER TABLE wled_light_assignments ADD COLUMN orientation` migration — SQLite supports `ADD COLUMN ... NOT NULL DEFAULT 'auto'` natively (verified against SQLite 3.20+); the existing project pattern wraps it in `try/except Exception: pass` (see `database.py:48-61`).
5. The Base UI `Popover` choice for `RegionOrientationPopover` — `@base-ui/react ^1.3.0` ships with a built-in `Popover` primitive that includes a positioner with auto-flip; this is the canonical answer because the project already uses Base UI primitives elsewhere in shadcn's `base-nova` preset.

**Primary recommendation:** One backend wave that builds the overlap-split + numbering helper in a new `services/wled_channels.py` module (pure SQL, transaction-wrapped, unit-testable) → one backend wave that extends `sub_sample_gradient` + threads orientation through `_build_region_plan` + `_load_wled_device_rows` → one frontend wave for `WledStripPainter` (extract a pure reducer for state-machine unit tests; integrate Konva separately) → one frontend wave for the popover (`@base-ui/react/popover`) + drag-drop branch + LightPanel WLED section. Validation per WMAP-01..WMAP-05.

---

## User Constraints (from 19-CONTEXT.md)

### Locked Decisions (verbatim from CONTEXT.md decision IDs — do NOT re-decide)

- **D-01:** Drag-to-paint creates channel (mousedown/move/up state machine mirroring `EditorCanvas.handleMouseDown`).
- **D-02:** Overlap **auto-splits** — new range carves into overlapped channel; remainders keep original id/name.
- **D-03:** Adjacent-zone boundary resize via a drag-handle inside the strip; min 1 LED per side.
- **D-04:** Delete cascades to `wled_light_assignments` and to the abutting neighbor; if abuts nothing, becomes unassigned space.
- **D-05:** Zone-only rectangles, NOT per-LED cells.
- **D-06:** Long strips (1200+ LEDs) fit-to-width; per-LED precision via sidebar inputs.
- **D-07:** Strip is 40–60px tall (UI-SPEC pins 40px from sketch 001-A).
- **D-08:** Sparse axis labels.
- **D-09:** No user-settable channel color; `wled_channels.color` column from Phase 17 is **dormant, not migrated**, UI ignores it.
- **D-10:** `Channel N` auto-named, monotonic per device, never reused on delete. Seed channel keeps `'Strip'` name.
- **D-11:** Algorithmic render fill, brand-aligned. UI-SPEC locks to `hsl((i × 137.508) % 360, 60%, 60%)` from sketch 002.
- **D-12:** New `WLED` section in LightPanel between `Lights` and `Assignments`; grouped per device.
- **D-13:** Drag payload **EXTENDS** Hue payload — adds `wledChannelId`, `wledDeviceId`, `wledChannelName`, `entertainment_config_id`. Existing Hue payload UNTOUCHED.
- **D-14:** Separate `M` counter chip in LightPanel header for WLED; no threshold colors.
- **D-15:** Settings paint slot stacks all device strips vertically; canvas slot scrolls vertically.
- **D-16:** Add column `wled_light_assignments.orientation TEXT NOT NULL DEFAULT 'auto'` via idempotent migration.
- **D-17:** Enum: `auto` | `horizontal-LTR` | `horizontal-RTL` | `vertical-TTB` | `vertical-BTT`.
- **D-18:** Default `auto` on every new assignment row.
- **D-19:** Orientation control surfaces in a region-anchored popover (CONTEXT discretion → UI-SPEC pins canvas popover).
- **D-20:** `sub_sample_gradient` is extended to honor the orientation enum.
- **D-21:** API endpoints — `GET/POST/PUT/DELETE /api/wled/devices/{id}/channels[/{id}]`, `PUT/PATCH/DELETE /api/wled/assignments`.
- **D-22:** Coordinator `{region_id: gradient_array}` contract unchanged; `N_region` unchanged; orientation affects axis+direction in the **helper**, not the contract shape.

### Claude's Discretion (research-resolvable)

- Konva vs raw DOM for the strip — **resolved: Konva** (UI-SPEC pins Stage/Layer/Rect/Line; established pattern in `EditorCanvas.tsx`).
- Exact derived-fill formula — **resolved: golden-angle HSL** from sketch 002, encoded in `Frontend/src/utils/wled-palette.ts` (new).
- Inline zone-label threshold — **resolved: 40px** rendered width (UI-SPEC §Spacing exceptions).
- Region properties placement — **resolved: canvas popover** anchored to the selected region (sketch 003-A).
- Seed `Strip` channel auto-delete vs zero-width remnant when consumed by paint — **needs planner decision; this research recommends delete-when-zero-width with re-seed only on device add (CONTEXT.md note "delete when its `start_led > end_led` after a split").
- Cascade when handle drag collapses a zone to zero width — **needs planner decision; this research recommends "treat as delete with cascade".
- Recompute of `N_region` mid-stream when assignments change — **research recommends "next stream start", with a logged no-op like `add_wled_device_to_live` at `streaming_coordinator.py:185`.
- Orientation icons — **resolved: Unicode arrows in mono font** (UI-SPEC §Copywriting).
- Test strategy for Konva interactions — **resolved below** (split: pure reducer for state machine + Playwright for pointer integration).

### Deferred Ideas (OUT OF SCOPE)

User-picks-axis at the region level (only per-assignment ships); polygon-path LED mapping; undo/redo; per-device default orientation; channel cloning across devices; user-settable channel colors; per-region cap on assigned WLED channels; visualizing orientation arrow on the painted strip zone; per-LED preview of streaming color on the strip; `wled_channels.color` removal migration.

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WMAP-01 | User can paint LED ranges on a visual strip representation to create channels | Overlap Auto-Split Algorithm (§) + Konva painter state machine (Testing Strategy §) |
| WMAP-02 | Each painted zone appears as an assignable channel in LightPanel | Drag-Drop Branching (§) + LightPanel section pattern in `LightPanel.tsx:373-438` |
| WMAP-03 | Painted zones are color-coded per channel for visual clarity | `channelColor(i)` from sketch-findings zone-palette.md, new `Frontend/src/utils/wled-palette.ts` |
| WMAP-04 | User can adjust channel boundaries by dragging handles between zones | Boundary Drag-Handle Resize (§) — clamping rules + PUT-on-mouseup cadence |
| WMAP-05 | WLED channels are assigned to canvas regions via the same drag-drop workflow as Hue segments | Drag-Drop Branching (§) — additive `wledChannelId` probe in `EditorCanvas.handleDrop:190` |

Phase 19 success criterion #5 ("Channel delete cascades to assignments and updates the canvas immediately") maps to the DELETE channel endpoint in `routers/wled.py` mirroring the existing device-delete cascade pattern at `routers/wled.py:286-329` (T-17-DELETE-ORPHAN).

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Paint gesture (mouse) | Browser/Client (Konva) | — | Pure UI state machine; commits on mouseup via POST to API |
| Overlap auto-split | API/Backend | Database (SQLite) | Geometry computation + transaction wrapper; FE doesn't pre-compute the split |
| Channel-N numbering | API/Backend | Database | Single source of truth: SQL `MAX(N)+1` per device |
| Boundary resize | Browser/Client (Konva drag) | API/Backend (commit) | FE handles drag preview; PUT on mouseup |
| Orientation enum | API/Backend (helper) | Browser/Client (popover) | Helper applies axis override per frame; popover only writes the row |
| Drag-drop assignment | Browser/Client (DataTransfer) | API/Backend (PUT) | FE sets payload + reads on drop; backend persists |
| Schema migration | Backend (startup) | Database | Idempotent `ALTER TABLE` in `database.py:init_db` |
| Render fill chip | Browser/Client (pure function) | — | No persistence; `channelColor(i)` computed at render |

---

## Overlap Auto-Split Algorithm

**Goal:** A `POST /api/wled/devices/{device_id}/channels` with `{start_led, end_led}` MUST atomically resolve overlap with existing channels per D-02.

**Inputs:** `new = (s_new, e_new)`, existing channels `[(id_k, s_k, e_k, name_k), ...]` ordered by `start_led ASC`.

**Cases (exhaustive — all happen inside one transaction):**

| Case | Existing range vs new range | Action | Identity preserved |
|------|----------------------------|--------|-------------------|
| **A** New is fully outside any existing | No overlap with any `(s_k, e_k)` | INSERT new only | n/a |
| **B** New range fully inside one existing — strict interior | `s_k < s_new ≤ e_new < e_k` | Split existing into two: keep id_k with `(s_k, s_new-1)` named original; INSERT a *new row* for the right remainder with the next-N name; INSERT new range | Original id_k retains LEFT half, name unchanged |
| **C** New equals existing exactly | `s_k = s_new AND e_k = e_new` | DELETE existing (cascade assignments), INSERT new with fresh N. (Or: keep id_k, overwrite nothing — but per D-10 numbering is monotonic, so a "paint over" creates a fresh row.) | None — original id is gone |
| **D** New crosses left boundary only | `s_new ≤ s_k ≤ e_new < e_k` | UPDATE existing `start_led = e_new+1` (keep id+name); INSERT new | Original id_k retained, name unchanged |
| **E** New crosses right boundary only | `s_k < s_new ≤ e_k ≤ e_new` | UPDATE existing `end_led = s_new-1` (keep id+name); INSERT new | Original id_k retained, name unchanged |
| **F** New crosses multiple boundaries | Spans from one existing to another | UPDATE left-most (case E), DELETE all fully-swallowed in between (cascade), UPDATE right-most (case D), INSERT new | Edge ids preserved; swallowed ids gone |
| **G** New encloses one existing entirely | `s_new ≤ s_k AND e_k ≤ e_new` (and same for multiple) | DELETE swallowed channel(s) (cascade), INSERT new. If new also crosses neighbors → combine with D/E | Swallowed ids gone |

**Identity preservation rule:** The LEFT half of any split keeps the original `(id, name)`. The right half (if any) gets a fresh id + the next `Channel N` name (or numbered after the seed, see Channel-N Numbering Invariant §). This matches the user's mental model: "I painted into this existing range; the part that's still on the left is still that channel."

**Pseudocode (single SQLite transaction):**

```python
# services/wled_channels.py (new file)

async def create_channel_with_split(
    db: aiosqlite.Connection,
    device_id: str,
    start_new: int,
    end_new: int,
) -> dict:
    """Insert a new channel and auto-split any overlaps. Single transaction.

    Returns the inserted channel row.
    """
    if start_new > end_new:
        raise ValueError("start_led must be <= end_led")

    # 1. Validate against device LED count
    async with db.execute(
        "SELECT led_count FROM wled_devices WHERE id = ?", (device_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"device {device_id} not found")
    led_count = int(row["led_count"])
    if start_new < 0 or end_new >= led_count:
        raise ValueError(f"range [{start_new}, {end_new}] out of [0, {led_count - 1}]")

    # 2. Load existing channels ordered for deterministic split
    async with db.execute(
        "SELECT id, name, start_led, end_led FROM wled_channels "
        "WHERE device_id = ? ORDER BY start_led ASC",
        (device_id,),
    ) as cur:
        existing = [dict(r) for r in await cur.fetchall()]

    # 3. Categorise existing rows: keep / left-trim / right-trim / split / delete
    to_delete: list[str] = []  # ids fully swallowed by new
    to_update: list[tuple[str, int, int]] = []  # (id, new_start, new_end)
    to_insert_right_half: list[tuple[int, int, str]] = []  # (start, end, original_name)

    for ch in existing:
        s, e = int(ch["start_led"]), int(ch["end_led"])
        # No overlap → leave alone
        if e < start_new or s > end_new:
            continue
        # Fully swallowed
        if start_new <= s and e <= end_new:
            to_delete.append(ch["id"])
            continue
        # Strict interior split (case B)
        if s < start_new and end_new < e:
            to_update.append((ch["id"], s, start_new - 1))  # left half keeps id
            to_insert_right_half.append((end_new + 1, e, ch["name"]))
            continue
        # Crosses left boundary only (case D)
        if start_new <= s <= end_new < e:
            to_update.append((ch["id"], end_new + 1, e))
            continue
        # Crosses right boundary only (case E)
        if s < start_new <= e <= end_new:
            to_update.append((ch["id"], s, start_new - 1))
            continue

    # 4. Compute the new channel's name from numbering invariant (§ below)
    next_name = await _next_channel_name(db, device_id)

    # 5. Apply in transaction
    # SQLite transactional semantics: aiosqlite uses implicit transactions
    # bracketed by .commit(). Errors before commit roll back automatically.
    try:
        # 5a. Delete swallowed channels (CASCADE assignments — manual, see § Risks)
        for cid in to_delete:
            await db.execute(
                "DELETE FROM wled_light_assignments WHERE wled_channel_id = ?",
                (cid,),
            )
            await db.execute("DELETE FROM wled_channels WHERE id = ?", (cid,))

        # 5b. Resize survivors
        for cid, ns, ne in to_update:
            await db.execute(
                "UPDATE wled_channels SET start_led = ?, end_led = ? WHERE id = ?",
                (ns, ne, cid),
            )

        # 5c. Insert right-half splits (case B) with NEW ids + next available names
        for rs, re_end, _original_name in to_insert_right_half:
            new_id = str(uuid.uuid4())
            right_name = await _next_channel_name(db, device_id)
            await db.execute(
                "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) "
                "VALUES (?, ?, ?, ?, ?, '#ffffff')",
                (new_id, device_id, right_name, rs, re_end),
            )

        # 5d. Insert the painted range
        new_channel_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) "
            "VALUES (?, ?, ?, ?, ?, '#ffffff')",
            (new_channel_id, device_id, next_name, start_new, end_new),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "id": new_channel_id,
        "device_id": device_id,
        "name": next_name,
        "start_led": start_new,
        "end_led": end_new,
    }
```

**Why a single transaction matters:** Without atomicity, a concurrent `GET /api/wled/devices/{id}/channels` between steps could observe a strip with no channels at all (mid-delete, pre-insert). The existing project pattern in `routers/wled.py:286-329` already uses a single transaction for the cascade-delete; the create-with-split follows the same shape.

**Cascade rule:** SQLite FK CASCADE is **not enforced** in this project — `database.py:92-126` documents this, and `routers/wled.py:298-329` implements cascade in code. The split helper above mirrors that: for every `DELETE FROM wled_channels`, an explicit `DELETE FROM wled_light_assignments WHERE wled_channel_id = ?` runs first.

**Confidence: HIGH.** Verified by reading the existing transaction pattern at `routers/wled.py:286-329` and the SQLite docs on implicit transactions in aiosqlite.

---

## Boundary Drag-Handle Resize

**Goal:** Per D-03, dragging the handle between zones `A` (left) and `B` (right) shifts the shared boundary. Both zones' rows are modified; identity (id, name) is preserved for both.

**Clamping rules (FE, during drag):**

- Let `A = (s_A, e_A)` and `B = (s_B, e_B)` with `e_A + 1 = s_B` (adjacent).
- The handle's logical LED position is `boundary = s_B`.
- Constraints:
  - `boundary ≥ s_A + 1` — A must keep at least 1 LED (i.e. `e_A ≥ s_A`).
  - `boundary ≤ e_B` — B must keep at least 1 LED (`s_B ≤ e_B`).
- Result: `boundary ∈ [s_A + 1, e_B]`. The handle cannot pass through either neighbor.

**Commit cadence (CRITICAL — no per-frame PUTs):**

- During drag (`onDragMove`): update local Konva state only; preview the new boundary visually.
- On mouseup / `onDragEnd`: fire **one** PUT request per dragged handle (which modifies BOTH `A` and `B` in a single backend call).

**Backend endpoint shape (D-21 — adapted):**

`PUT /api/wled/devices/{device_id}/channels/boundary` (NEW endpoint, NOT in CONTEXT.md's literal D-21 list — the planner should either extend D-21 with a dedicated boundary-move endpoint, or use two separate `PUT /channels/{id}` calls inside a frontend transaction wrapper. **Research recommends a single backend endpoint with body `{left_channel_id, right_channel_id, boundary}` so the resize is atomic on the server.**)

**Strip-edge behavior:**

- Leftmost zone's left handle: not rendered (no neighbor to share with).
- Rightmost zone's right handle: not rendered.
- All interior boundaries get a handle.

**Zero-width collapse during drag (D-04 / CONTEXT discretion):**

If the user drags one zone to `start_led > end_led`, the FE should clamp at 1-LED minimum width and refuse to commit. The CONTEXT.md "Claude's Discretion" bullet suggests treating it as a delete with cascade; **research recommends instead clamping in the FE (simpler, no ambiguous delete UX), and ONLY deleting if the user explicitly hits the Delete button in the sidebar.**

**File touchpoints:**
- New: `Frontend/src/components/Settings/WledStripPainter.tsx` (handles drag state)
- Modify: `Backend/routers/wled.py` (add channel-CRUD + boundary endpoint after line 388)
- New: `Backend/services/wled_channels.py` (boundary resize logic — atomic UPDATE both rows)

**Confidence: HIGH.** Konva `Line` `draggable` + `onDragMove` is the standard pattern; clamping in `dragBoundFunc` is the idiomatic Konva approach.

---

## Channel-N Numbering Invariant

**Goal (D-10):** New channels are auto-named `Channel N` where `N` is monotonically incrementing **per device**, and `N` is never reused after delete. The seed `Strip` channel from Phase 17 D-09 has NO numeric N — it's literally named `Strip`.

**Algorithm:** `N = MAX(<extracted N from name>) + 1` over `wled_channels` for the device, with `MAX = 0` when no numbered rows exist.

**Why not just `COUNT(*) + 1`?** That would reuse N's after delete (violates D-10).

**Why not a separate `next_channel_n` column on `wled_devices`?** Simpler schema with no new column: parse the existing `name` column with a regex. The trade-off is that user-renamed channels (per D-10 "Name is editable") will not contribute to the max — but this is the desired behavior: if the user renames `Channel 3` to `TV Top`, then later painting again should still produce `Channel 4` (because 1, 2, and 3 were issued at some point in history). To preserve that history without parsing, we DO need to track issued numbers somewhere.

**Recommended approach: add a `next_channel_n INTEGER NOT NULL DEFAULT 1` column to `wled_devices`** (idempotent ALTER TABLE pattern like `database.py:48-61`). This is a HIGH-confidence answer because:

1. It's O(1) to query and update.
2. It survives renames (history is in the counter, not the name).
3. It survives deletes (counter never decrements).
4. It naturally produces `Channel 1` as the first painted channel on a device whose seed is still `Strip`.

**Migration in `database.py` (idempotent):**

```python
# Add right after wled_devices CREATE TABLE block (~line 106)
try:
    await db.execute(
        "ALTER TABLE wled_devices ADD COLUMN next_channel_n INTEGER NOT NULL DEFAULT 1"
    )
    await db.commit()
except Exception:
    # Column already exists — safe to ignore
    pass
```

**Helper:**

```python
async def _next_channel_name(
    db: aiosqlite.Connection, device_id: str
) -> str:
    """Reserve the next 'Channel N' name for a device. Atomic UPDATE+SELECT."""
    async with db.execute(
        "SELECT next_channel_n FROM wled_devices WHERE id = ?", (device_id,)
    ) as cur:
        row = await cur.fetchone()
    n = int(row["next_channel_n"])
    await db.execute(
        "UPDATE wled_devices SET next_channel_n = next_channel_n + 1 WHERE id = ?",
        (device_id,),
    )
    return f"Channel {n}"
```

**Seed channel handling:** Phase 17's `add_device` endpoint at `routers/wled.py:265-269` inserts the seed with literal name `'Strip'`. **This does NOT increment `next_channel_n`** — the seed sits outside the numbered sequence per D-10. First painted channel becomes `Channel 1`, second becomes `Channel 2`, etc.

**Alternative considered (rejected):** Regex-parse names like `r"^Channel (\d+)$"` and take MAX. Rejected because (a) user renames break the invariant, (b) it requires a regex over all rows per insert, (c) the schema-column approach is strictly simpler.

**Confidence: HIGH.** Pattern matches the project's existing idempotent ALTER TABLE convention.

---

## Orientation Enum + Sub-Sample Helper Extension

**Existing helper:** `Backend/services/color_math.py::sub_sample_gradient` (lines 201-255). Current signature:

```python
def sub_sample_gradient(frame: np.ndarray, region: RegionMask, n: int) -> np.ndarray
```

- Auto-selects axis: `axis_x = width >= height` (line 234).
- Samples `n_effective` columns or rows based on the longer axis.
- Returns `(n_effective, 3)` RGB uint8 array.

**Required extension (D-17, D-20):**

```python
from typing import Literal

Orientation = Literal[
    "auto", "horizontal-LTR", "horizontal-RTL", "vertical-TTB", "vertical-BTT"
]

def sub_sample_gradient(
    frame: np.ndarray,
    region: RegionMask,
    n: int,
    orientation: Orientation = "auto",
) -> np.ndarray:
    """Extended: orientation overrides axis + direction. 'auto' preserves Phase 17 behavior.

    - 'auto'           → existing bbox-longest-axis logic (axis_x = width >= height); LTR/TTB direction
    - 'horizontal-LTR' → force x-axis, sample index 0..n-1 maps to left→right
    - 'horizontal-RTL' → force x-axis, sample index 0..n-1 maps to right→left (reverse the output)
    - 'vertical-TTB'   → force y-axis, top→bottom
    - 'vertical-BTT'   → force y-axis, bottom→top (reverse the output)
    """
    if n <= 1:
        r, g, b = extract_region_color(frame, region)
        return np.array([[r, g, b]], dtype=np.uint8)

    width = region.x2 - region.x1
    height = region.y2 - region.y1
    longest = max(width, height, 1)
    n_effective = max(1, min(n, longest))

    # NEW: axis + reverse derived from orientation
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
        raise ValueError(f"Unknown orientation: {orientation}")

    # ... existing slab-sampling loop unchanged ...
    means = np.empty((n_effective, 3), dtype=np.uint8)
    for i in range(n_effective):
        # ... (existing sampling logic, lines 237-254) ...

    if reverse:
        means = means[::-1]
    return means
```

**Caller-side propagation — this is the more invasive change:**

The helper today is called from **two** places:

1. `streaming_coordinator.py:508` inside `_frame_loop`:
   ```python
   region_gradients: dict[str, np.ndarray] = {
       rid: sub_sample_gradient(frame, mask, n_region)
       for rid, (mask, n_region) in region_plan.items()
   }
   ```
2. `tests/test_color_math.py` (unit tests).

**Critical structural problem:** The coordinator's `region_gradients` dict is **keyed by region_id with a single gradient** per region — but with per-assignment orientation, two different WLED channels assigned to the same region with different orientations need **two different gradients**. The current per-region single-gradient model in `_frame_loop` is no longer sufficient.

**Two options (planner must choose):**

**Option A — Per-assignment gradient (cleaner, breaks Hue/WLED contract):**

Change the gradient dict to `dict[tuple[region_id, orientation], np.ndarray]`. Both Hue and WLED render functions must change. **Rejected** because Hue doesn't care about orientation and CONTEXT.md D-22 says the coordinator-to-sink boundary is unchanged.

**Option B — Compute per-orientation per region, dispatch in `WledStreamer._render_one_device` (recommended):**

The coordinator computes a `(region_id, orientation) -> gradient` dict but ONLY for orientations that actually have an assignment (avoids computing all 5 orientations × all regions). The dict shape becomes `dict[str, dict[str, np.ndarray]]`:
```python
region_gradients[region_id] = {
    "auto":            <(N_region, 3) ndarray>,
    "horizontal-LTR":  <(N_region, 3) ndarray>,
    ...
}
```

Hue sink reads `region_gradients[region_id]["auto"]` (always). WLED sink reads `region_gradients[region_id][channel.orientation]`.

**This violates D-22 literally** ("`{region_id: gradient_array}`") but preserves its spirit — the coordinator's responsibility is unchanged, only the value type changes. The planner should adopt Option B and update D-22 to reflect a nested dict, OR adopt Option A and rev the contract.

**Recommended:** Option B with a backward-compat shim — keep the outer dict shape, change the value to a small dict. Update `wled_streamer.py:_render_one_device:318` from `gradient = region_gradients.get(region_id)` to `gradient = region_gradients[region_id][ch["orientation"]]`. Hue's `streaming_service.py::HueStreamer.render` would access `region_gradients[region_id]["auto"]`.

**Threading orientation through the load:** `_load_wled_device_rows` at `streaming_coordinator.py:242-324` reads channels via the JOIN at line 286-294. **The query must add `wla.orientation`**:

```sql
SELECT wc.id AS channel_id, wc.start_led, wc.end_led,
       wla.region_id, wla.orientation
FROM wled_channels wc
LEFT JOIN wled_light_assignments wla
    ON wla.wled_channel_id = wc.id
    AND wla.entertainment_config_id = ?
WHERE wc.device_id = ?
```

The channel dict at line 304-309 then carries `"orientation": c["orientation"] or "auto"` (LEFT JOIN may return NULL if no assignment exists; default to "auto").

**`_build_region_plan` update:** The plan needs to know which orientations are required per region to avoid wasted computation. Add:

```sql
SELECT DISTINCT r.id AS region_id, r.polygon,
       COALESCE(MAX(wc.end_led - wc.start_led + 1), 1) AS n_region,
       GROUP_CONCAT(DISTINCT wla.orientation) AS orientations
FROM regions r
LEFT JOIN light_assignments la ON la.region_id = r.id AND la.entertainment_config_id = :cfg
LEFT JOIN wled_light_assignments wla ON wla.region_id = r.id AND wla.entertainment_config_id = :cfg
LEFT JOIN wled_channels wc ON wc.id = wla.wled_channel_id
WHERE la.region_id IS NOT NULL OR wla.region_id IS NOT NULL
GROUP BY r.id, r.polygon
```

`orientations` is a CSV — parse to a set. Always include `"auto"` in the set if Hue has an assignment on this region.

**Confidence: HIGH for the helper change; MEDIUM for the coordinator restructure** (it depends on the planner's choice between Option A and B; Option B is recommended and is what this research models).

---

## Schema Migration (orientation column)

**SQLite support:** `ALTER TABLE ... ADD COLUMN name TYPE NOT NULL DEFAULT 'value'` is supported on SQLite 3.20.0+ (released 2017). The project uses Python 3.12, which ships with `sqlite3` linked against SQLite 3.45+. **Verified: HIGH confidence.**

**Existing migration pattern** (`database.py:48-61`):

```python
try:
    await db.execute("ALTER TABLE regions ADD COLUMN light_id TEXT")
    await db.commit()
except Exception:
    # Column already exists — safe to ignore OperationalError
    pass
```

**New migration block — add immediately after the `wled_light_assignments` CREATE TABLE block (~line 126):**

```python
# Phase 19 D-16: Per-assignment orientation override for sub-sample axis + direction.
# Idempotent — silently no-ops if the column already exists (matches the Phase 9
# regions-table migrations at lines 48-61).
try:
    await db.execute(
        "ALTER TABLE wled_light_assignments "
        "ADD COLUMN orientation TEXT NOT NULL DEFAULT 'auto'"
    )
    await db.commit()
except Exception:
    # Column already exists — safe to ignore OperationalError
    pass
```

**Also add the Channel-N numbering invariant migration (§ above):**

```python
# Phase 19 D-10: Per-device monotonic channel counter — never reuses freed N's.
try:
    await db.execute(
        "ALTER TABLE wled_devices "
        "ADD COLUMN next_channel_n INTEGER NOT NULL DEFAULT 1"
    )
    await db.commit()
except Exception:
    pass
```

**Backfill:** No data migration needed — `DEFAULT 'auto'` populates existing rows automatically (D-16 explicitly notes this).

**Test:** `tests/test_database.py` already has a smoke test for init_db; extend with a second-init test to verify idempotency.

**Confidence: HIGH.** Pattern matches `database.py:48-61` line-for-line.

---

## Drag-Drop Branching in EditorCanvas

**Current state** (`EditorCanvas.tsx:190-233`):

```typescript
async function handleDrop(e: React.DragEvent<HTMLDivElement>) {
  e.preventDefault()
  const channelId = e.dataTransfer.getData('channelId')
  const channelName = e.dataTransfer.getData('channelName')
  const lightId = e.dataTransfer.getData('lightId')
  const configId = e.dataTransfer.getData('configId')

  if (!channelId && !lightId) return
  // ... finds hit region ...
  // ... updates region via updateRegionAPI ...
}
```

**Required additive branch (D-13 / UI-SPEC §Drag-Drop Payload Contract):**

```typescript
async function handleDrop(e: React.DragEvent<HTMLDivElement>) {
  e.preventDefault()
  const wledChannelId = e.dataTransfer.getData('wledChannelId')
  const channelId = e.dataTransfer.getData('channelId')
  const lightId = e.dataTransfer.getData('lightId')

  // Probe ORDER MATTERS: WLED first because both branches may set
  // configId/entertainment_config_id, but only WLED sets wledChannelId.
  // The presence of wledChannelId is the unambiguous discriminator.
  if (wledChannelId) {
    // WLED branch
    const wledDeviceId = e.dataTransfer.getData('wledDeviceId')
    const wledChannelName = e.dataTransfer.getData('wledChannelName')
    const entertainmentConfigId = e.dataTransfer.getData('entertainment_config_id')

    // Find hit region (same pointInPolygon logic)
    const stage = stageRef.current
    if (!stage) return
    stage.setPointersPositions(e)
    const pos = stage.getPointerPosition()
    if (!pos) return
    const currentRegions = useRegionStore.getState().regions
    const hit = currentRegions.find((region) => {
      const pixelPolygon = denormalize(region.polygon as [number, number][], width, height)
      return pointInPolygon([pos.x, pos.y], pixelPolygon)
    })
    if (!hit) return

    try {
      await upsertWledAssignment({
        region_id: hit.id,
        wled_channel_id: wledChannelId,
        entertainment_config_id: entertainmentConfigId,
        orientation: 'auto',  // D-18 default
      })
      // Refresh regions/assignments so popover and LightPanel reflect the change
      const updated = await fetchRegions()
      useRegionStore.getState().setRegions(updated)
    } catch (err) {
      console.error('Failed to assign WLED channel to region:', err)
    }
    return  // CRITICAL: do not fall through to Hue branch
  }

  // EXISTING Hue branch UNCHANGED (preserves D-13)
  if (!channelId && !lightId) return
  // ... existing logic ...
}
```

**Why `wledChannelId` probe first:** It is the unambiguous discriminator. Hue drag rows in `LightPanel.tsx:406-413` set `channelId`, `channelName`, `lightId`, `configId` — but never `wledChannelId`. Probing `wledChannelId` first with an early `return` after the WLED handler ensures the Hue path is reached iff `wledChannelId` is absent.

**`selectedId` gating popover visibility:** The `RegionOrientationPopover` opens iff `useRegionStore.selectedId` is non-null AND the region has 1+ WLED assignments (UI-SPEC §RegionOrientationPopover). The popover does NOT open on drop alone — the user must click the region first. **However**, the drop action SHOULD trigger `setSelectedId(hit.id)` so the user immediately sees the new assignment in the popover. **Recommendation: call `useRegionStore.getState().setSelectedId(hit.id)` after the upsert succeeds.**

**Side effects of the WLED drop branch:**

1. POST to `PUT /api/wled/assignments`.
2. Refresh regions (the popover reads from `useRegionStore.wledAssignments` — see Region Popover § for store extension).
3. Set `selectedId` to the hit region so the popover surfaces immediately.
4. **Do not** call `updateRegionAPI` (that's the Hue path's job — D-13 explicitly forbids rerouting it).

**Confidence: HIGH.** The branch order and side effects are mechanical given UI-SPEC.

---

## Region Popover Anchoring (library vs hand-rolled)

**Project status:** `@base-ui/react ^1.3.0` is already installed (verified at `Frontend/node_modules/@base-ui/react/popover/`). Base UI is the headless successor to Radix from the shadcn team and ships a fully-featured `Popover` with positioner, auto-flip, beak/arrow, and outside-click handling.

**Components.json** at `Frontend/components.json` confirms `style: "base-nova"` (Base UI's shadcn preset), `iconLibrary: "lucide"`. The project is already on Base UI.

**Sub-components available** (verified):
- `@base-ui/react/popover/root`
- `@base-ui/react/popover/trigger`
- `@base-ui/react/popover/portal`
- `@base-ui/react/popover/positioner` — handles auto-flip
- `@base-ui/react/popover/popup`
- `@base-ui/react/popover/arrow`
- `@base-ui/react/popover/close`

**Recommendation: USE `@base-ui/react/popover`.** It satisfies the UI-SPEC §RegionOrientationPopover auto-flip algorithm directly:

- `Popover.Positioner` with `side="bottom"`, `align="start"`, `sideOffset={12}`, `collisionPadding={8}` produces exactly the UI-SPEC behavior (default bottom-left, auto-flip on edge collision, 8px margin from canvas edges).
- `Popover.Arrow` produces the 12×12 beak with `border-left + border-top` — matches sketch 003-A.
- `Popover.Portal` mounts the popover outside the Konva Stage (critical — see Risks §).
- Outside-click handling is built in.

**Why NOT hand-rolled bounding-box math:** The UI-SPEC §RegionOrientationPopover spec lists 4 close triggers and 4 auto-flip edge cases. Hand-rolling these is ~100 lines of TS with cross-browser pointer-event gotchas and ResizeObserver coordination. Base UI's positioner is battle-tested.

**Trigger pattern:** The popover is NOT attached to a DOM trigger like a button — it's positioned over the selected region's bounding box on the Konva canvas. Solution: use `Popover.Root open={selectedId !== null && wledAssignments[selectedId]?.length > 0}` (controlled mode) with a **virtual anchor element**. Base UI supports `Popover.Positioner` with `anchor={virtualEl}` where `virtualEl` is a `{ getBoundingClientRect: () => DOMRect }` shim that returns the selected region's screen-space bbox.

```tsx
// Frontend/src/components/Editor/RegionOrientationPopover.tsx
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

**Cited:** `@base-ui/react ^1.3.0` ships with Popover primitives [VERIFIED: `Frontend/node_modules/@base-ui/react/popover/` directory listing]. Base UI Popover API documented at https://base-ui.com/react/components/popover [CITED].

**Confidence: HIGH.** Base UI is already installed, already declared as the project's primitive layer, and ships exactly the features UI-SPEC demands.

---

## Testing Strategy (Konva painter + geometry)

**Problem (CONTEXT.md Claude's Discretion):** Konva pointer events are hard to unit-test in Vitest. JSDOM lacks a real canvas/pointer engine; `react-konva` renders to a `canvas` element that JSDOM stubs heavily.

**Empirical evidence:** `Frontend/src/components/LightPanel.test.tsx` tests pure DOM + drag-source `dataTransfer.setData` calls but does NOT test the EditorCanvas's Konva interactions. `WledDevicesPanel.test.tsx` is similarly DOM-only. No Konva-canvas test exists in the project today.

**Recommended split:**

### 1. Pure-geometry unit tests (Vitest, no Konva dependency)

Extract the paint-state-machine into a **pure reducer** + helper functions in a separate file:

```typescript
// Frontend/src/components/Settings/wled-paint-reducer.ts
export type PaintState =
  | { phase: 'idle' }
  | { phase: 'painting'; startLed: number; currentLed: number }

export type PaintAction =
  | { type: 'mousedown'; led: number }
  | { type: 'mousemove'; led: number }
  | { type: 'mouseup'; led: number; commit: (s: number, e: number) => void }
  | { type: 'cancel' }

export function paintReducer(state: PaintState, action: PaintAction): PaintState {
  // ... deterministic, no side effects except the commit callback ...
}

// also test:
//   - pixelToLed(x: number, stripWidth: number, ledCount: number): number
//   - ledToPixel(led: number, stripWidth: number, ledCount: number): number
//   - channelColor(i) palette function (already in zone-palette.md)
//   - overlap-classification function mirroring backend service logic
//     (useful for FE optimistic preview before the POST commits)
```

Unit-test with Vitest in `wled-paint-reducer.test.ts`. Cover:
- Mousedown → painting state with startLed = led
- Mousemove updates currentLed
- Mouseup commits min(start, current) and max(start, current)
- Cancel returns to idle without committing
- pixelToLed clamps to [0, ledCount-1]
- channelColor(0) === 'hsl(0, 60%, 60%)'
- channelColor(1) === 'hsl(137.508, 60%, 60%)'

### 2. Backend overlap-split tests (pytest, no UI)

`tests/test_wled_channels.py` (new) — covers every case A-G from the Overlap Auto-Split table above. Use the same in-memory DB pattern as `test_wled_router.py:_make_db()`. Assertions:
- Row counts before/after
- Identity preservation (left half keeps original `id`)
- Cascade to `wled_light_assignments`
- Transaction atomicity (raise mid-split → no row changes)
- `next_channel_n` increments correctly across mixed paint operations

### 3. Backend orientation tests (pytest)

`tests/test_color_math.py` (extend) — for a known fixture (a 100×50 wide bbox with a horizontal red→blue gradient):
- `orientation='auto'` returns the same array as the existing test → behavior preserved
- `orientation='horizontal-LTR'` returns red-first
- `orientation='horizontal-RTL'` returns red-LAST (reversed)
- `orientation='vertical-TTB'` forces vertical sampling (different shape of gradient because the fixture is horizontal)
- `orientation='vertical-BTT'` reverses again

### 4. Integration tests via Playwright (already in package.json as `@playwright/test ^1.59.1`)

For the Konva pointer interactions specifically:
- Test the strip canvas in a Playwright spec at `Frontend/playwright/` (new dir if missing).
- Use Playwright's `page.mouse.down() → page.mouse.move() → page.mouse.up()` to drive paint gestures.
- Assert the resulting DB state via a follow-up `GET /api/wled/devices/{id}/channels` call.

Skip Konva unit tests in Vitest entirely.

### 5. Drag-drop branch test (Vitest, JSDOM)

`Frontend/src/components/EditorCanvas.test.tsx` (new) — test the `handleDrop` function in isolation by constructing a fake `React.DragEvent` with mocked `dataTransfer.getData`. Cover:
- WLED-only payload → calls `upsertWledAssignment`, does NOT call `updateRegionAPI`.
- Hue-only payload → calls `updateRegionAPI`, does NOT call `upsertWledAssignment`.
- Both payloads present (defensive) → WLED branch wins (per probe order).
- No payload → no API call.

**Confidence: HIGH** on the split strategy, **MEDIUM** on Playwright availability (no playwright spec exists in the repo today, so Wave 0 must seed a `playwright.config.ts` if the planner adopts this).

---

## Validation Architecture

> The project uses pytest (Python 3.12, pytest.ini at `Backend/pytest.ini` with `asyncio_mode = auto`) and Vitest (Frontend package.json scripts). Phase 17 shipped `tests/test_phase17_e2e.py` as the E2E gate. This phase's validation follows the same shape.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (Backend, asyncio_mode=auto) + Vitest 4.1.1 (Frontend) + Playwright 1.59.1 (E2E pointer interactions) |
| Config file | `Backend/pytest.ini`, `Frontend/vitest` via package.json `test` script |
| Quick run command (backend) | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_channels.py tests/test_color_math.py tests/test_wled_router.py -x` |
| Quick run command (frontend) | `cd Frontend && npx vitest run src/components/Settings/wled-paint-reducer.test.ts src/utils/wled-palette.test.ts src/components/EditorCanvas.test.tsx` |
| Full suite command (backend) | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |
| Full suite command (frontend) | `cd Frontend && npx vitest run` |
| Phase gate (combined) | Both full suites green + Playwright paint-gesture spec green |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WMAP-01 | Paint creates a channel — drag from LED 10 to LED 50 inserts (start=10, end=50) | integration | `pytest tests/test_wled_router.py::test_create_channel_basic -x` | ❌ Wave 0 |
| WMAP-01 | Paint over existing channel auto-splits per cases A-G | unit | `pytest tests/test_wled_channels.py -x` | ❌ Wave 0 |
| WMAP-01 | Paint gesture state machine (mousedown→move→up) | unit | `npx vitest run src/components/Settings/wled-paint-reducer.test.ts` | ❌ Wave 0 |
| WMAP-01 | Paint pointer integration on actual Konva canvas | e2e | `npx playwright test e2e/wled-paint.spec.ts` | ❌ Wave 0 |
| WMAP-02 | Painted channel appears in LightPanel WLED section | unit (React) | `npx vitest run src/components/LightPanel.test.tsx -t "WLED section"` | ❌ extend existing |
| WMAP-02 | Channel row sets correct dataTransfer payload | unit (React) | `npx vitest run src/components/LightPanel.test.tsx -t "WLED drag payload"` | ❌ extend existing |
| WMAP-03 | channelColor(i) produces correct golden-angle hue | unit | `npx vitest run src/utils/wled-palette.test.ts` | ❌ Wave 0 |
| WMAP-04 | Boundary drag updates both adjacent channels | integration | `pytest tests/test_wled_router.py::test_boundary_resize_atomic -x` | ❌ Wave 0 |
| WMAP-04 | Boundary drag clamps to 1-LED minimum per side | unit | `npx vitest run src/components/Settings/wled-paint-reducer.test.ts -t "boundary clamp"` | ❌ Wave 0 |
| WMAP-05 | EditorCanvas.handleDrop WLED branch calls upsertAssignment | unit (React) | `npx vitest run src/components/EditorCanvas.test.tsx -t "WLED drop"` | ❌ Wave 0 |
| WMAP-05 | Hue drop path is untouched after WLED branch added | unit (React) | `npx vitest run src/components/EditorCanvas.test.tsx -t "Hue drop preserved"` | ❌ Wave 0 |
| Success #1 | Strip renders per-device, fit-to-width | e2e | `npx playwright test e2e/wled-paint.spec.ts -g "fit-to-width"` | ❌ Wave 0 |
| Success #4 | Painted channels + assignments persist across restart | integration | `pytest tests/test_phase19_e2e.py::test_persistence -x` | ❌ Wave 0 |
| Success #5 | Channel delete cascades to assignments | integration | `pytest tests/test_wled_router.py::test_delete_channel_cascades -x` | ❌ Wave 0 |
| D-16 migration | Idempotent ALTER TABLE on second init | unit | `pytest tests/test_database.py::test_init_db_idempotent_phase19 -x` | ❌ Wave 0 |
| D-17 orientation | sub_sample_gradient with 'horizontal-RTL' reverses array | unit | `pytest tests/test_color_math.py::test_sub_sample_orientation_rtl -x` | ❌ Wave 0 |
| D-17 orientation | 'auto' preserves Phase 17 behavior | unit | `pytest tests/test_color_math.py::test_sub_sample_orientation_auto_matches_phase17 -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** quick run (touched test files only).
- **Per wave merge:** full backend + frontend suites.
- **Phase gate:** full suites + Playwright paint-gesture spec + manual UAT (paint a channel in browser, assign to region, observe LED change in stream).

### Wave 0 Gaps
- [ ] `Backend/tests/test_wled_channels.py` — covers Overlap Auto-Split cases A-G + Channel-N invariant
- [ ] `Backend/tests/test_phase19_e2e.py` — end-to-end paint → assign → stream → persistence smoke
- [ ] Extend `Backend/tests/test_color_math.py` with orientation parameter tests
- [ ] Extend `Backend/tests/test_database.py` with second-init idempotency for orientation column + next_channel_n
- [ ] Extend `Backend/tests/test_wled_router.py` with channel-CRUD + assignment-upsert tests
- [ ] `Frontend/src/components/Settings/wled-paint-reducer.test.ts` — paint state machine
- [ ] `Frontend/src/utils/wled-palette.test.ts` — channelColor golden-angle assertions
- [ ] `Frontend/src/components/EditorCanvas.test.tsx` — drop-handler branch tests (NEW FILE)
- [ ] Extend `Frontend/src/components/LightPanel.test.tsx` with WLED section + drag-payload tests
- [ ] `Frontend/playwright.config.ts` — IF the planner adopts Playwright for Konva pointer interactions (config does not exist today)
- [ ] `Frontend/e2e/wled-paint.spec.ts` — paint gesture happy path + auto-split scenarios

---

## Already Shipped in Phase 17 (Do Not Re-Do)

These symbols, endpoints, schema objects, and behaviors are FROZEN and CORRECT. The planner must NOT recreate them.

### Backend (shipped, locked)
| Artifact | Location | Status |
|----------|----------|--------|
| `wled_devices` CREATE TABLE | `Backend/database.py:98-106` | ✅ Done |
| `wled_channels` CREATE TABLE | `Backend/database.py:108-117` | ✅ Done |
| `wled_light_assignments` CREATE TABLE | `Backend/database.py:118-126` | ✅ Done (Phase 19 adds `orientation` column via ALTER) |
| `GET /api/wled/devices` | `Backend/routers/wled.py:180-190` | ✅ Done |
| `POST /api/wled/devices` (with seed-channel auto-create) | `Backend/routers/wled.py:193-283` | ✅ Done — seed `Strip` channel inserted at line 265-269 |
| `DELETE /api/wled/devices/{id}` (with cascade) | `Backend/routers/wled.py:286-329` | ✅ Done — Phase 19 channel-DELETE mirrors this cascade pattern |
| `PUT /api/wled/devices/{id}/enabled` | `Backend/routers/wled.py:332-370` | ✅ Done |
| `POST /api/wled/scan` (zeroconf) | `Backend/routers/wled.py:373-388` | ✅ Done |
| `sub_sample_gradient(frame, region, n)` | `Backend/services/color_math.py:201-255` | ✅ Done — Phase 19 ADDS optional `orientation` parameter |
| `WledStreamer.render(region_gradients)` | `Backend/services/wled_streamer.py:264-302` | ✅ Done — value type changes per Option B above (nested dict); render logic at lines 304-363 reads `ch["orientation"]` |
| `StreamingCoordinator._load_wled_device_rows` | `Backend/services/streaming_coordinator.py:242-324` | ✅ Done — Phase 19 ADDS `wla.orientation` to the SELECT at line 286-294 |
| `StreamingCoordinator._build_region_plan` | `Backend/services/streaming_coordinator.py:330-388` | ✅ Done — Phase 19 adds `orientations` GROUP_CONCAT to the SELECT at line 346-355 |
| WLED packet builders (DRGB/DNRGB) | `Backend/services/wled_streamer.py:46-106` | ✅ Done — Phase 19 makes no protocol changes |
| WLED health snapshot (D-16) | `Backend/services/wled_streamer.py:251-262` | ✅ Done |
| `wled_channels.color` column | `Backend/database.py:114` | ✅ Done — Phase 19 D-09 leaves DORMANT, no migration |

### Frontend (shipped, locked)
| Artifact | Location | Status |
|----------|----------|--------|
| `Frontend/src/api/wled.ts` (device CRUD + scan) | full file | ✅ Done — Phase 19 EXTENDS with channel CRUD + assignment endpoints |
| `WledApiError` pattern | `Frontend/src/api/wled.ts:34-41` | ✅ Done — Phase 19 reuses |
| `WledDevicesPanel.tsx` (device CRUD UI) | `Frontend/src/components/Settings/WledDevicesPanel.tsx` | ✅ Done — Phase 19 keeps it in the `md:flex-[4]` column unchanged |
| Settings paint slot placeholder | `Frontend/src/components/Settings/SettingsPanel.tsx:38-43`, `SettingsPage.tsx:17-22` | ✅ Done — Phase 19 REPLACES the dashed-border div with `<WledStripPainter />` |
| Test pattern for in-memory router tests | `Backend/tests/test_wled_router.py:40-79` `_make_db()` | ✅ Done — Phase 19 channel-router tests reuse this fixture pattern |
| `useStatusStore.wledDevices` | (not read here, but Phase 17 D-16 confirmed wire-ready) | ✅ Done |

**What does NOT exist yet (gaps Phase 19 fills):**
- Channel-CRUD HTTP endpoints (D-21 list) → all new
- Assignment upsert/patch/delete endpoints → all new
- `services/wled_channels.py` (overlap-split logic) → new file
- `Frontend/src/utils/wled-palette.ts` (`channelColor` helper) → new file
- `WledStripPainter.tsx`, `WledChannelSidebar.tsx`, `RegionOrientationPopover.tsx`, `OrientationSegmentedControl.tsx` → all new

---

## Risks / Landmines

### R1 — Coordinator gradient contract change (HIGHEST RISK)

CONTEXT.md D-22 says the coordinator-to-sink contract is unchanged. But per-assignment orientation FORCES a value-shape change in `region_gradients` (Option B above). The planner must:
- Decide between Option A (key change) and Option B (value change).
- Update the docstring at `streaming_coordinator.py:469-483` regardless.
- Update `WledStreamer._render_one_device` at `wled_streamer.py:304` to consume the nested dict.
- Update `HueStreamer.render` (in `streaming_service.py`) to read `region_gradients[region_id]["auto"]` if Option B.
- Ensure existing Phase 17 e2e test at `tests/test_phase17_e2e.py` still passes (auto-orientation behavior preserved).

### R2 — Seed `Strip` channel collision with paint

Phase 17's seed channel covers the full strip (start=0, end=led_count-1). Painting ANYWHERE will auto-split it per case B/D/E. The "left/right of the paint" remainders inherit the seed's identity per the auto-split rule — meaning **`Strip` name will end up on whichever side becomes the LEFT half**. The right half becomes `Channel 1` (per Channel-N numbering invariant, since the right-half insert calls `_next_channel_name` which returns "Channel 1" because the seed never incremented the counter).

If the user paints starting at LED 0 (case D, left-trim), the seed survives with `start_led=end_new+1` and keeps name `Strip`. The new range becomes `Channel 1`.

**Recommendation:** Document this behavior in the planner's user-facing notes — it's intuitive but non-obvious. Cleanest variant per CONTEXT.md "Claude's Discretion": "delete when its start_led > end_led after a split, regenerate on next device-list refresh if no channels remain". **Research recommends the planner adopt: if seed `Strip` becomes 0-width, delete it (no preservation as ghost row). If a device ends up with zero channels, re-seed `Strip` covering the whole strip on next channel-list GET.**

### R3 — `N_region` recompute mid-stream

`streaming_coordinator.py:421` computes `region_plan` ONCE at the start of the run loop. If the user paints a wider channel mid-stream (now `N_region` should grow for that region), the running stream uses the OLD `N_region` until restart.

**Recommendation:** Match the existing pattern in `streaming_coordinator.py:185-203` (`add_wled_device_to_live`) — log a no-op, note that the change takes effect on next stream start. Add a TODO for a future hot-rebuild of `region_plan`. The UI does NOT need to inform the user — the system reports `wled_devices` health correctly via `StatusBroadcaster` and the user can stop/restart streaming for the new layout.

### R4 — Konva Stage size syncing with paint slot

UI-SPEC says strips are fit-to-width. The Settings paint slot is `md:flex-[6]` — its pixel width changes with browser window resize. Konva `Stage width={...}` does NOT auto-update; it must be wired with a ResizeObserver.

**Recommendation:** Use a small `useResizeObserver` hook (or inline `useEffect` watching the container `ref.current.offsetWidth`). Konva `Stage` re-renders on width prop change. Pattern matches `EditorCanvas.tsx:19` which passes `width` as a prop from `EditorPage`.

### R5 — Drag-drop ordering in EditorCanvas

The existing `handleDrop` at `EditorCanvas.tsx:190-233` reads 4 keys (`channelId`, `channelName`, `lightId`, `configId`) and exits at line 197 if neither `channelId` nor `lightId` is present. If the Phase 19 branch is added INCORRECTLY (e.g. without the `return` after the WLED branch handler), a payload with both `wledChannelId` and `lightId` could trigger both branches — corrupting state. **Add `return` after the WLED upsert.**

### R6 — Popover Portal vs Konva Stage z-index

`Popover.Portal` mounts the popup to `document.body`. The Konva Stage canvas is z-index 0 by default; the popover gets `z-index: 50` (UI-SPEC). This works EXCEPT inside `SettingsPanel` (the modal at z-index 40 with `bg-black/60`) — that's irrelevant here because the orientation popover lives on the EditorCanvas, not in Settings. Confirm visually: open EditorCanvas → select a region → popover renders above canvas, not behind.

### R7 — Render-loop overhead with multiple orientations per region

If a region has 5 WLED channels assigned with 5 different orientations, `sub_sample_gradient` runs 5× per frame for that region. At 60 Hz × 8 regions × 5 orientations = 2400 helper calls per second. The existing helper is uses cv2.mean per slab (~3-row × ROI). Each call is sub-millisecond for typical bbox sizes (verified: existing 60 Hz operation already runs this loop). **Likely OK but worth a quick benchmark** in Wave 0 fixtures.

### R8 — Renaming `Channel N` removes invariant signal

Per D-10, the user can rename channels. If the user renames `Channel 1` to `TV Top` and then paints again, the next channel should be `Channel 2` (because `next_channel_n` is now 2 regardless of rename). The `next_channel_n` column-based approach handles this correctly. **Confirm via test:** paint 1, rename "Channel 1" to "Foo", paint 2 → expect "Channel 2", not "Channel 1".

### R9 — Existing Phase 17 e2e test breakage

`tests/test_phase17_e2e.py` exercises the full Phase 17 stack. Phase 19's schema migrations (adding `orientation` and `next_channel_n` columns) MUST be backward-compatible — defaults ensure existing test data inserts succeed. Phase 17's `sub_sample_gradient` calls pass only `(frame, region, n)`; the orientation parameter MUST default to `'auto'` to preserve the signature.

### R10 — Channel rename auto-save can race with channel resize

The sidebar (`WledChannelSidebar`) has both a name input and start/end LED inputs. If the user types in the name input and immediately drags a boundary, two PUTs fire. SQLite serializes them but the order matters — the resize PUT could "stomp" a pending rename if the name PUT hasn't returned yet. **Recommendation:** Use single-field PATCH endpoints (or a single `PUT /channels/{id}` with optional fields) and await the previous request before firing the next.

### R11 — `aiosqlite` rollback semantics

The overlap-split helper assumes `db.rollback()` is available. `aiosqlite.Connection.rollback` exists and works as expected — verified by reading aiosqlite source. However, `routers/wled.py:286-329` does NOT use explicit rollback; it relies on the next `commit()` to either succeed or leave the connection in a recoverable state. **Recommendation:** wrap the split helper in `try/except/rollback/raise` per the pseudocode above — the multi-statement transaction has higher error surface than the cascade-delete (which is also 3 statements but less branching).

---

## File Map

| File | New / Modify | Rationale |
|------|--------------|-----------|
| `Backend/database.py` | Modify (~line 126 + ~line 106) | Idempotent ALTER TABLE for `wled_light_assignments.orientation` and `wled_devices.next_channel_n` (D-16 + Channel-N invariant) |
| `Backend/services/color_math.py` | Modify (line 201-255) | Extend `sub_sample_gradient` signature with `orientation: Orientation = "auto"`; add axis+reverse logic |
| `Backend/services/wled_channels.py` | **New** | Pure SQL helpers: `create_channel_with_split` (cases A-G), `_next_channel_name`, `resize_boundary` (atomic two-row UPDATE), `delete_channel_with_cascade` |
| `Backend/services/streaming_coordinator.py` | Modify (line 286-294, line 346-355, line 469-540) | Add `wla.orientation` to channel SELECT; add `orientations` GROUP_CONCAT to region_plan; restructure `region_gradients` to nested dict per orientation |
| `Backend/services/wled_streamer.py` | Modify (line 304-363, line 314-345) | Read `ch["orientation"]` and `region_gradients[region_id][orientation]` instead of `region_gradients[region_id]` |
| `Backend/services/streaming_service.py` (HueStreamer) | Modify | Read `region_gradients[region_id]["auto"]` if Option B adopted |
| `Backend/routers/wled.py` | Modify (append after line 388) | Add 5 new endpoints per D-21: list/create/update/delete channels; PUT/PATCH/DELETE assignments. New endpoint: boundary resize (atomic two-channel UPDATE). |
| `Backend/tests/test_wled_channels.py` | **New** | Pytest cases A-G for overlap-split; numbering invariant tests; rename-stable tests |
| `Backend/tests/test_wled_router.py` | Modify | Add channel-CRUD endpoint tests + assignment upsert/patch tests |
| `Backend/tests/test_color_math.py` | Modify | Add orientation parametrized tests (5 enum values × known fixture) |
| `Backend/tests/test_database.py` | Modify | Add second-init idempotency test for orientation + next_channel_n columns |
| `Backend/tests/test_phase19_e2e.py` | **New** | E2E: register device → paint channel → assign to region → start stream → verify UDP packet bytes via loopback fixture → restart → verify persistence |
| `Frontend/src/api/wled.ts` | Modify | Add 7 typed functions: `listChannels`, `createChannel`, `updateChannel`, `deleteChannel`, `upsertAssignment`, `patchAssignmentOrientation`, `deleteAssignment` |
| `Frontend/src/utils/wled-palette.ts` | **New** | `channelColor(index)` pure function returning `hsl(...)`; ~5 lines |
| `Frontend/src/utils/wled-palette.test.ts` | **New** | Vitest: golden-angle hue math, AA-readability sanity on first 12 indices |
| `Frontend/src/components/Settings/wled-paint-reducer.ts` | **New** | Pure paint state machine (mousedown/move/up reducer + pixelToLed/ledToPixel helpers) — testable without Konva |
| `Frontend/src/components/Settings/wled-paint-reducer.test.ts` | **New** | Vitest: paint state machine cases + clamping + pixelToLed math |
| `Frontend/src/components/Settings/WledStripPainter.tsx` | **New** | Konva `Stage`/`Layer`/`Rect`/`Line` strip per device; uses reducer above; wires PUT requests on mouseup |
| `Frontend/src/components/Settings/WledChannelSidebar.tsx` | **New** | Selected-channel form: name input, start/end LED inputs, Delete button — auto-save on blur/Enter |
| `Frontend/src/components/Settings/SettingsPanel.tsx` | Modify (line 38-43) | Replace `data-testid="paint-canvas-placeholder"` div with `<WledStripPainter />` + `<WledChannelSidebar />` stacked vertically inside `md:flex-[6]` |
| `Frontend/src/components/Settings/SettingsPage.tsx` | Modify (line 17-22) | Same replacement as SettingsPanel |
| `Frontend/src/components/Editor/RegionOrientationPopover.tsx` | **New** | `@base-ui/react/popover` with virtual anchor over selected region bbox; lists assignments + segmented control |
| `Frontend/src/components/Editor/OrientationSegmentedControl.tsx` | **New** | 5-button group (`auto`/`→`/`←`/`↓`/`↑`); auto-save on click via PATCH |
| `Frontend/src/components/LightPanel.tsx` | Modify (insert section between Lights at line 320 and Assignments at line 444) | Add WLED section with grouped device sub-headers, channel rows with `channelColor(i)` chip, drag-source payload extension per D-13 |
| `Frontend/src/components/LightPanel.test.tsx` | Modify | Add WLED section render test, drag-payload assertion, counter chip presence |
| `Frontend/src/components/EditorCanvas.tsx` | Modify (line 190-233) | Add `wledChannelId` branch with explicit `return` after upsert; preserve Hue branch verbatim. Mount `<RegionOrientationPopover />` as sibling overlay (HTML, not Konva). |
| `Frontend/src/components/EditorCanvas.test.tsx` | **New** | Vitest: WLED-drop branch test, Hue-drop branch preservation test, both-payloads-present discriminator test |
| `Frontend/src/store/useRegionStore.ts` | Modify | Add `wledAssignments: Record<regionId, WledAssignment[]>` field + setter so popover renders without re-fetching per selection |
| `Frontend/playwright.config.ts` | **New** (if planner adopts Playwright for pointer integration) | Standard `@playwright/test` config pointing at `localhost:8091`; baseURL aligned with existing dev server port |
| `Frontend/e2e/wled-paint.spec.ts` | **New** (if planner adopts Playwright) | End-to-end paint gesture spec covering WMAP-01 + WMAP-04 |
| `.planning/phases/19-wled-strip-paint-ui/19-RESEARCH.md` | **New** | This file |
| `.planning/phases/19-wled-strip-paint-ui/19-VALIDATION.md` | **New** (downstream) | Generated by validation step from `## Validation Architecture` § |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `next_channel_n` schema column is preferable to name-regex for the monotonic invariant | Channel-N Numbering | If wrong, the regex approach works but breaks on user-renamed channels; safer to confirm with user. **MEDIUM** — recommend confirming in the planner step. |
| A2 | The coordinator's `region_gradients` value can change from `ndarray` to `dict[orientation, ndarray]` without breaking the D-22 contract (Option B) | Orientation Enum + Sub-Sample Helper Extension | If wrong, must adopt Option A (key change) which is more invasive. **HIGH** — this is a structural decision that should be confirmed with the user before planning. |
| A3 | Auto-splitting on the seed `Strip` channel should keep `Strip` name on the LEFT remainder (not right) | Risks R2 | If wrong, the right remainder keeps `Strip` and the left gets `Channel 1` — flip the rule. **LOW** — both choices are defensible; document and pick. |
| A4 | Zero-width handle-drag should clamp at 1-LED, NOT auto-delete | Boundary Drag-Handle Resize | If wrong, the planner should follow CONTEXT.md's "Claude's Discretion" suggestion (delete + cascade). **LOW** — UI affordance choice. |
| A5 | Playwright is the right test runner for Konva pointer interactions | Testing Strategy | If wrong, the planner could choose @testing-library + custom canvas mock, but that gets fragile fast. **LOW** — Playwright is industry-standard. |
| A6 | The Settings paint slot's `md:flex-[6]` ResizeObserver needs ~30 lines of TS, not a library | Risks R4 | If wrong, `use-resize-observer` could be installed. Trivial. **LOW**. |

---

## Open Questions

1. **Coordinator gradient contract** — does the planner accept Option B (nested dict per orientation) or want Option A (per-(region, orientation) key)?
   - What we know: D-22 says coordinator-to-sink contract unchanged. Option B preserves outer dict shape; Option A changes the key.
   - Recommendation: confirm Option B with the user OR escalate to discuss-phase. This research adopts Option B.

2. **Seed `Strip` channel lifecycle when fully consumed by paint** — auto-delete-and-re-seed-if-no-channels, or keep as zero-width remnant?
   - What we know: CONTEXT.md "Claude's Discretion" suggests delete-on-zero-width + regenerate.
   - Recommendation: planner adopts delete-on-zero-width; UI-SPEC empty state already supports the "no painted channels beyond the seed" scenario.

3. **Channel-CRUD endpoints — should the boundary-resize be a dedicated endpoint or two PUTs?**
   - What we know: D-21 doesn't enumerate boundary-resize specifically.
   - Recommendation: dedicated `PUT /api/wled/devices/{id}/channels/boundary` with body `{left_channel_id, right_channel_id, boundary_led}` — atomic on server side.

4. **Where exactly to mount the `RegionOrientationPopover` in `EditorPage`** — alongside `EditorCanvas` or inside `EditorCanvas`?
   - What we know: UI-SPEC §Component Inventory says mount as sibling overlay to the Konva Stage so Portal works correctly.
   - Recommendation: mount in `EditorCanvas.tsx` JSX as a sibling of `<Stage>` so it shares the canvas container's positioning context but renders to `document.body` via `Popover.Portal`.

5. **Should `useRegionStore.wledAssignments` be loaded once on EditorCanvas mount, or fetched on every region selection?**
   - What we know: UI-SPEC says "load with the region" — implies once on mount.
   - Recommendation: load once on EditorCanvas mount via `fetchWledAssignments()`; invalidate after drop / orientation PATCH / channel delete.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Backend | ✓ | 3.12 (pinned per CLAUDE.md) | — |
| SQLite (via aiosqlite >=0.20) | Schema migration | ✓ | aiosqlite present in requirements.txt | — |
| `@base-ui/react` | Popover positioner | ✓ | 1.3.0 | Hand-rolled bbox math (NOT recommended) |
| `react-konva` | Strip painter | ✓ | 19.2.3 | — |
| `vitest` | Frontend tests | ✓ | 4.1.1 | — |
| `pytest` (asyncio_mode=auto) | Backend tests | ✓ | per Backend/pytest.ini | — |
| `@playwright/test` | Konva pointer integration tests | ✓ (installed) | 1.59.1 | Skip Konva integration tests; rely on manual UAT (NOT recommended for success criterion #1) |
| `playwright.config.ts` | Playwright runner config | ✗ | — | Create in Wave 0 |
| Hue Bridge | Existing streaming | ✓ | v2 at 192.168.178.23 paired | — |
| WLED device | Streaming + UDP packet validation | ✓ (any device registered in Phase 17 manual UAT) | — | Loopback UDP listener fixture (already exists at `tests/test_wled_loopback_fixture.py`) |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** Playwright config (create in Wave 0 if planner adopts the integration-test strategy).

---

## Project Constraints (from CLAUDE.md)

- **Python 3.12 pinned** (hue-entertainment-pykit incompatible with 3.13+) — orientation enum uses `typing.Literal` which is fully supported.
- **No Docker from v1.2 onward** — backend runs natively on Linux (Phase 17 D-19 zeroconf works without Docker bridge caveat). Phase 19 makes no network/Docker changes.
- **No auth** — all new endpoints are unauthenticated, consistent with the rest of the API.
- **Latency <100ms** — orientation override adds at most 4 extra `cv2.mean` calls per region per frame (one per non-`auto` enum value present in assignments). Verified existing 60 Hz operation tolerates the helper; new overhead is negligible (~sub-millisecond per call).
- **`/api/<domain>` prefix pattern** — channel and assignment endpoints all live under `/api/wled/`.
- **`CREATE TABLE IF NOT EXISTS` + idempotent `ALTER TABLE` guarded by `try/except`** — Phase 19 follows the `database.py:48-61` pattern verbatim.
- **`react-konva` for canvas interactions** — UI-SPEC pins this; CLAUDE.md "Recommended Stack Additions" lists it as the established primitive.
- **Pydantic request/response models per router** — Phase 19 follows `routers/wled.py:55-86` pattern for the new endpoints.
- **GSD workflow enforcement** — no direct edits outside a GSD command; this research file IS the GSD artifact.

---

## Sources

### Primary (HIGH confidence)
- `Backend/database.py` (lines 48-61, 92-127) — idempotent ALTER TABLE pattern, existing wled_* schema [VERIFIED: file read]
- `Backend/routers/wled.py` (lines 193-388) — existing device CRUD + cascade-delete pattern [VERIFIED: file read]
- `Backend/services/color_math.py` (lines 201-255) — sub_sample_gradient signature + implementation [VERIFIED: file read]
- `Backend/services/wled_streamer.py` (lines 264-395) — render loop, packet builders, per-channel slicing [VERIFIED: file read]
- `Backend/services/streaming_coordinator.py` (lines 242-540) — coordinator data flow, gradient dict construction [VERIFIED: file read]
- `Frontend/src/components/EditorCanvas.tsx` (lines 190-233) — handleDrop pattern [VERIFIED: file read]
- `Frontend/src/components/LightPanel.tsx` (lines 320-440) — section pattern + drag-source payload [VERIFIED: file read]
- `Frontend/src/api/wled.ts` — WledApiError pattern [VERIFIED: file read]
- `Frontend/components.json` — Base UI / `base-nova` preset confirmed [VERIFIED: file read]
- `Frontend/package.json` — `@base-ui/react ^1.3.0` confirmed [VERIFIED: file read]
- `Frontend/node_modules/@base-ui/react/popover/` directory listing — Popover sub-components verified present [VERIFIED: filesystem check]
- `.claude/skills/sketch-findings-huepicturecontrol/references/canvas-and-overlays.md` — strip CSS + popover CSS [VERIFIED: file read]
- `.claude/skills/sketch-findings-huepicturecontrol/references/zone-palette.md` — golden-angle formula [VERIFIED: file read]
- `.planning/phases/19-wled-strip-paint-ui/19-CONTEXT.md` — all 22 D-* decisions [VERIFIED: file read]
- `.planning/phases/19-wled-strip-paint-ui/19-UI-SPEC.md` — UI design contract [VERIFIED: file read]
- `.planning/phases/17-wled-backend-and-streaming/17-CONTEXT.md` — Phase 17 decisions D-07 to D-20 [VERIFIED: file read]

### Secondary (MEDIUM confidence)
- SQLite `ALTER TABLE ADD COLUMN ... NOT NULL DEFAULT` support since SQLite 3.20.0 — [CITED: https://www.sqlite.org/releaselog/3_20_0.html]
- Python 3.12 `sqlite3` ships with SQLite 3.45+ — [CITED: https://docs.python.org/3.12/library/sqlite3.html]
- `@base-ui/react` Popover API — [CITED: https://base-ui.com/react/components/popover]

### Tertiary (LOW confidence)
- None.

---

## Metadata

**Confidence breakdown:**
- Overlap auto-split algorithm: HIGH — follows existing project transaction patterns verbatim
- Channel-N numbering invariant: HIGH — schema column approach is standard
- Orientation helper extension: HIGH — pure code change; coordinator restructure is MEDIUM pending Option B confirmation
- Schema migration: HIGH — line-for-line match to existing pattern
- Drag-drop branching: HIGH — additive branch with explicit return
- Region popover anchoring: HIGH — Base UI already installed
- Testing strategy: MEDIUM — Playwright spec doesn't yet exist in repo, Wave 0 must seed config
- Phase 17 "already shipped" inventory: HIGH — verified via direct file reads

**Research date:** 2026-05-14
**Valid until:** 2026-06-14 (30 days — stable codebase, no fast-moving deps)

## RESEARCH COMPLETE
