import { test, expect, type Page } from '@playwright/test'

/**
 * Phase 19.1 WLED segment-driven model e2e.
 *
 * Replaces the legacy Phase 19 e2e suite per CONTEXT.md D-10/D-23. Segments
 * are now mirrored from the device's own `/json/state seg[]` rather than
 * user-managed, so the e2e surface is:
 *
 *   1. segments render from refresh response (POST /segments/refresh stubbed)
 *   2. fit-to-width per device (segment-driven payload)
 *   3. drag payload uses wledDeviceId + seg_index (D-13 composite key)
 *
 * V3' (refresh after a WLED-side range change) requires real hardware and is
 * covered by manual UAT instead of Playwright (see 19.1-VALIDATION.md).
 */

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'

// ---------------------------------------------------------------------------
// Test fixture: ensure a WLED device exists before the spec runs.
// ---------------------------------------------------------------------------

async function ensureWledDevice(page: Page): Promise<{ id: string; ledCount: number }> {
  const resp = await page.request.get(`${BACKEND}/api/wled/devices`)
  expect(resp.ok()).toBeTruthy()
  const body = await resp.json()
  if (body.devices && body.devices.length > 0) {
    const d = body.devices[0]
    return { id: d.id, ledCount: d.led_count }
  }
  // No device registered - skip the spec gracefully (CI environments may not
  // have a real WLED endpoint reachable; manual UAT covers the hardware path).
  test.skip(true, 'No WLED device registered; run manual UAT to verify hardware-side.')
  return { id: '', ledCount: 0 }
}

/**
 * Navigate the single-page app shell to the Settings tab. The app uses
 * state-driven page switching (see Frontend/src/App.tsx), not a router, so
 * we click the nav button rather than visit a URL.
 */
async function openSettingsTab(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Settings' }).click()
  await expect(page.getByTestId('wled-strip-painter')).toBeVisible({ timeout: 10_000 })
}

// ---------------------------------------------------------------------------
// Specs
// ---------------------------------------------------------------------------

test.describe('Phase 19.1 WLED segments', () => {
  test('segments render from refresh response (stubbed)', async ({ page }) => {
    const device = await ensureWledDevice(page)

    // Stub the per-device list endpoint so the initial mount doesn't depend
    // on whatever the backend cached. Three segments — Sofa / unnamed / TV.
    await page.route(
      `**/api/wled/devices/${encodeURIComponent(device.id)}/segments`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            segments: [
              {
                seg_index: 0,
                start_led: 0,
                stop_led: 99,
                name: 'Sofa',
                refreshed_at: new Date().toISOString(),
              },
              {
                seg_index: 1,
                start_led: 100,
                stop_led: 199,
                name: null,
                refreshed_at: new Date().toISOString(),
              },
              {
                seg_index: 2,
                start_led: 200,
                stop_led: 299,
                name: 'TV',
                refreshed_at: new Date().toISOString(),
              },
            ],
          }),
        }),
    )

    // Stub the refresh POST so clicking the button never hits a real WLED.
    await page.route(
      `**/api/wled/devices/${encodeURIComponent(device.id)}/segments/refresh`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            segments: [
              {
                seg_index: 0,
                start_led: 0,
                stop_led: 99,
                name: 'Sofa',
                refreshed_at: new Date().toISOString(),
              },
              {
                seg_index: 1,
                start_led: 100,
                stop_led: 199,
                name: null,
                refreshed_at: new Date().toISOString(),
              },
              {
                seg_index: 2,
                start_led: 200,
                stop_led: 299,
                name: 'TV',
                refreshed_at: new Date().toISOString(),
              },
            ],
            dropped_assignments: 0,
          }),
        }),
    )

    await openSettingsTab(page)

    const refreshButton = page.getByTestId(`wled-refresh-button-${device.id}`)
    await expect(refreshButton).toBeVisible()
    await refreshButton.click()

    // Konva zones aren't directly testable; the ZoneTestSentinel hidden <span>
    // pattern from Plan 07 SUMMARY exposes per-segment data-testids alongside
    // the canvas. Each segment surfaces as `wled-seg-{deviceId}-{segIndex}`.
    await expect(page.getByTestId(`wled-seg-${device.id}-0`)).toBeAttached()
    await expect(page.getByTestId(`wled-seg-${device.id}-1`)).toBeAttached()
    await expect(page.getByTestId(`wled-seg-${device.id}-2`)).toBeAttached()
  })

  test('fit-to-width per device', async ({ page }) => {
    const device = await ensureWledDevice(page)

    // Seed a single segment that covers the full strip so the strip canvas
    // has the data it needs to compute a width.
    await page.route(
      `**/api/wled/devices/${encodeURIComponent(device.id)}/segments`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            segments: [
              {
                seg_index: 0,
                start_led: 0,
                stop_led: Math.max(0, device.ledCount - 1),
                name: 'Full',
                refreshed_at: new Date().toISOString(),
              },
            ],
          }),
        }),
    )

    await openSettingsTab(page)

    const stripContainer = page.getByTestId('wled-strip-painter')
    await expect(stripContainer).toBeVisible()

    const stripWrapper = page.locator(`[data-testid="wled-strip-${device.id}"]`).first()
    await expect(stripWrapper).toBeVisible()

    const wrapperBox = await stripWrapper.boundingBox()
    const containerBox = await stripContainer.boundingBox()
    expect(wrapperBox).not.toBeNull()
    expect(containerBox).not.toBeNull()

    // The per-device strip wrapper occupies roughly the painter's width — the
    // ResizeObserver fit-to-width contract preserved from Phase 19 D-15.
    expect(wrapperBox!.width).toBeGreaterThan(100)
    expect(Math.abs(wrapperBox!.width - containerBox!.width)).toBeLessThanOrEqual(40)

    // And the segment surfaces as a discoverable zone testid (sentinel
    // pattern from Plan 07).
    await expect(page.getByTestId(`wled-seg-${device.id}-0`)).toBeAttached()
  })

  test('drag payload uses wledDeviceId + seg_index per D-13', async ({ page }) => {
    const device = await ensureWledDevice(page)

    // Stub a single named segment so the LightPanel WLED row mounts. The
    // production code reads from listSegments under the hood when the chip
    // row hydrates, then uses the cached list to render the drag-source rows.
    await page.route(
      `**/api/wled/devices/${encodeURIComponent(device.id)}/segments`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            segments: [
              {
                seg_index: 0,
                start_led: 0,
                stop_led: 9,
                name: 'Sofa',
                refreshed_at: new Date().toISOString(),
              },
            ],
          }),
        }),
    )

    await page.goto('/')
    // LightPanel is the right rail of the Editor page.
    await page.getByRole('button', { name: 'Editor' }).click()

    // Wait for the LightPanel row to mount. The composite-key testid contract
    // from Plan 08 is `lightpanel-wled-seg-{deviceId}-{segIndex}`.
    const rowTestId = `lightpanel-wled-seg-${device.id}-0`
    const row = page.getByTestId(rowTestId)
    await expect(row).toBeVisible({ timeout: 10_000 })

    // Capture the dataTransfer payload by hooking dragstart in the page
    // context. Playwright's native drag-and-drop is overkill when we only
    // need to verify the setData() calls — manual dispatchEvent does that
    // with no native DnD lifecycle complexity.
    const captured = await page.evaluate((selector) => {
      return new Promise<Record<string, string>>((resolve) => {
        const data: Record<string, string> = {}
        const row = document.querySelector(selector) as HTMLElement | null
        if (!row) {
          resolve({})
          return
        }
        // Fabricate a DragEvent + fake DataTransfer that records every setData.
        const fakeTransfer = {
          setData: (key: string, value: string) => {
            data[key] = value
          },
          getData: (key: string) => data[key] ?? '',
          effectAllowed: 'none' as const,
          dropEffect: 'none' as const,
          types: [] as string[],
          files: [] as unknown as FileList,
          items: [] as unknown as DataTransferItemList,
          clearData: () => {
            for (const k of Object.keys(data)) delete data[k]
          },
          setDragImage: () => {},
        }
        const evt = new Event('dragstart', { bubbles: true, cancelable: true }) as DragEvent
        Object.defineProperty(evt, 'dataTransfer', {
          value: fakeTransfer,
          writable: false,
        })
        row.dispatchEvent(evt)
        // Resolve on next tick so React's onDragStart handler runs synchronously
        // inside dispatchEvent.
        setTimeout(() => resolve(data), 50)
      })
    }, `[data-testid="${rowTestId}"]`)

    // D-13 composite-key payload contract (Plan 08 SUMMARY § "Exact Drag Payload Shape"):
    //   wledDeviceId            -> device.id
    //   seg_index               -> "0" (string)
    //   wledSegName             -> "Sofa" (segmentName(seg) D-08)
    //   entertainment_config_id -> selected config id (best-effort: present unless no
    //                              entertainment config is currently selected in the store)
    expect(captured.wledDeviceId).toBe(device.id)
    expect(captured.seg_index).toBe('0')
    expect(captured.wledSegName).toBe('Sofa')
    // Phase 19 legacy keys must NOT appear (negative assertion mirrors Plan 08
    // LightPanel.test.tsx line ~453).
    expect(captured.wledChannelId).toBeUndefined()
    expect(captured.wled_channel_id).toBeUndefined()
  })
})
