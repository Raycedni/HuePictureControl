import { test, expect, type Page } from '@playwright/test'

const BACKEND = 'http://localhost:8000'

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

async function clearChannels(page: Page, deviceId: string) {
  const resp = await page.request.get(
    `${BACKEND}/api/wled/devices/${encodeURIComponent(deviceId)}/channels`,
  )
  expect(resp.ok()).toBeTruthy()
  const body = await resp.json()
  for (const ch of body.channels) {
    await page.request.delete(
      `${BACKEND}/api/wled/devices/${encodeURIComponent(deviceId)}/channels/${encodeURIComponent(ch.id)}`,
    )
  }
}

// ---------------------------------------------------------------------------
// Specs
// ---------------------------------------------------------------------------

test.describe('WLED paint canvas', () => {
  test('paint creates channel', async ({ page }) => {
    const { id: deviceId, ledCount } = await ensureWledDevice(page)
    await clearChannels(page, deviceId)

    // Open the Settings page so the strip painter mounts.
    await page.goto('/')
    // Click whatever opens Settings (Settings button in nav, or modal trigger).
    // The exact selector depends on the app shell - both `data-testid="settings-page"`
    // and the SettingsPanel modal expose the same `paint-canvas-placeholder`-replacement.
    const stripCanvas = page.getByTestId('wled-strip-painter')
    await expect(stripCanvas).toBeVisible({ timeout: 10_000 })

    // Find the first Stage canvas inside the strip painter and paint LEDs ~50-100.
    const firstStage = page.locator(`[data-testid="wled-strip-${deviceId}"] canvas`).first()
    const box = await firstStage.boundingBox()
    expect(box).not.toBeNull()
    const startX = box!.x + box!.width * (50 / ledCount)
    const endX = box!.x + box!.width * (100 / ledCount)
    const midY = box!.y + 20 // mid-strip (40px tall)

    await page.mouse.move(startX, midY)
    await page.mouse.down()
    await page.mouse.move(endX, midY, { steps: 10 })
    await page.mouse.up()

    // Allow the POST to round-trip.
    await page.waitForTimeout(500)

    // Assert via the API that a channel landed at roughly the painted range.
    const resp = await page.request.get(
      `${BACKEND}/api/wled/devices/${encodeURIComponent(deviceId)}/channels`,
    )
    expect(resp.ok()).toBeTruthy()
    const body = await resp.json()
    const channels = body.channels as Array<{ start_led: number; end_led: number }>
    // The paint gesture covers approximately LED 50..100. Allow ±5 LED tolerance
    // for pixel-to-LED rounding at the click points.
    const match = channels.find(
      (c) => Math.abs(c.start_led - 50) <= 5 && Math.abs(c.end_led - 100) <= 5,
    )
    expect(match, `no channel near (50, 100) in ${JSON.stringify(channels)}`).toBeTruthy()
  })

  test('boundary handle resize', async ({ page }) => {
    const { id: deviceId, ledCount } = await ensureWledDevice(page)
    await clearChannels(page, deviceId)
    // Seed two adjacent channels via the API so the boundary handle is rendered.
    await page.request.post(
      `${BACKEND}/api/wled/devices/${encodeURIComponent(deviceId)}/channels`,
      { data: { start_led: 0, end_led: 99 } },
    )
    await page.request.post(
      `${BACKEND}/api/wled/devices/${encodeURIComponent(deviceId)}/channels`,
      { data: { start_led: 100, end_led: 199 } },
    )

    await page.goto('/')
    const stripCanvas = page.getByTestId('wled-strip-painter')
    await expect(stripCanvas).toBeVisible({ timeout: 10_000 })

    const firstStage = page.locator(`[data-testid="wled-strip-${deviceId}"] canvas`).first()
    const box = await firstStage.boundingBox()
    expect(box).not.toBeNull()
    const boundaryX = box!.x + box!.width * (100 / ledCount)
    const targetX = box!.x + box!.width * (80 / ledCount)
    const midY = box!.y + 20

    await page.mouse.move(boundaryX, midY)
    await page.mouse.down()
    await page.mouse.move(targetX, midY, { steps: 10 })
    await page.mouse.up()

    await page.waitForTimeout(500)

    const resp = await page.request.get(
      `${BACKEND}/api/wled/devices/${encodeURIComponent(deviceId)}/channels`,
    )
    const body = await resp.json()
    const channels = body.channels.sort(
      (a: { start_led: number }, b: { start_led: number }) => a.start_led - b.start_led,
    )
    // After drag, the boundary should be near LED 80. Allow ±5.
    expect(Math.abs(channels[0].end_led - 79)).toBeLessThanOrEqual(5)
    expect(Math.abs(channels[1].start_led - 80)).toBeLessThanOrEqual(5)
  })

  test('fit-to-width per device', async ({ page }) => {
    const { id: deviceId } = await ensureWledDevice(page)
    await page.goto('/')
    const stripCanvas = page.getByTestId('wled-strip-painter')
    await expect(stripCanvas).toBeVisible({ timeout: 10_000 })
    const firstStage = page.locator(`[data-testid="wled-strip-${deviceId}"] canvas`).first()
    const box = await firstStage.boundingBox()
    expect(box).not.toBeNull()
    const containerBox = await stripCanvas.boundingBox()
    expect(containerBox).not.toBeNull()
    // Strip canvas width is within 20px of the container (allowing for padding).
    expect(Math.abs(box!.width - containerBox!.width)).toBeLessThanOrEqual(20)
  })
})
