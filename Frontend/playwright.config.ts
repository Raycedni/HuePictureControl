import { defineConfig, devices } from '@playwright/test'

/**
 * Phase 19 Playwright runner config.
 *
 * Spec covers the Konva pointer interactions (paint gesture, boundary drag)
 * that Vitest cannot exercise reliably. See 19-RESEARCH.md §Testing Strategy.
 *
 * Pre-req: backend + frontend dev servers running.
 *   Backend:  uvicorn main:app --reload --port 8000
 *   Frontend: npm run dev   (binds 5173, Vite default)
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    actionTimeout: 5_000,
    navigationTimeout: 10_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
