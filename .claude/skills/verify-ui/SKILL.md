---
name: verify-ui
description: Visually verify the frontend UI by screenshotting all tabs using Playwright MCP
disable-model-invocation: true
argument-hint: [tab-name]
---

# Visual UI Verification

Use the Playwright MCP browser tools to visually verify the HuePictureControl frontend.
Argument: `$ARGUMENTS` (default: all tabs).

## Steps

1. Navigate to `http://localhost:8091`
2. Take a screenshot of the current tab (Setup)
3. Click the **Preview** tab, wait for content to load, take a screenshot
4. Click the **Editor** tab, wait for content to load, take a screenshot
5. If a specific tab is requested, only screenshot that tab

## What to Check
For each tab, verify:
- **Setup tab**: Pairing flow renders, bridge IP input visible, status bar present
- **Preview tab**: Canvas area renders (may show "no preview" if capture card absent — that's OK)
- **Editor tab**: Konva canvas area renders, drawing toolbar visible, light panel visible

## How to Navigate Tabs
Use `mcp__playwright__browser_snapshot` to get element refs, then `mcp__playwright__browser_click` on the tab buttons.

## Output
For each tab, report what you see and flag anything that looks broken (missing elements, error messages, blank sections that shouldn't be blank). Include screenshots in your response.

If the frontend isn't running on :8091, try :5173 (dev server). Suggest `docker compose up -d` or `cd Frontend && npm run dev`.
