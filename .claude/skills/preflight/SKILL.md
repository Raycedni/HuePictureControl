---
name: preflight
description: Full pre-commit verification — runs tests, health checks, and visual UI verification before committing
disable-model-invocation: true
---

# Preflight Check

Run the complete verification suite before committing changes. This combines all checks into one command.

## Sequence

### Phase 1: Tests (parallel)
Run `/test all` — execute backend and frontend test suites in parallel.
- Backend: `source /tmp/hpc-venv/bin/activate && cd /mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/Backend && python -m pytest --tb=short -q`
- Frontend: `cd /mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/Frontend && npx vitest run`

### Phase 2: Stack Health (parallel, only if backend is running)
Check API endpoints:
- `curl -sf http://localhost:8000/api/health`
- `curl -sf http://localhost:8000/api/hue/status`
- `curl -sf http://localhost:8000/api/hue/lights`
If backend is not running, skip and note it.

### Phase 3: Visual Verification (only if frontend is running)
Use Playwright MCP to navigate to http://localhost:8091 and screenshot each tab.
If frontend is not running, skip and note it.

## Output Format
```
PREFLIGHT REPORT
================
Tests:     PASS / FAIL (X backend, Y frontend)
Health:    PASS / SKIP (details)
UI:        PASS / SKIP (details)
================
Result:    READY TO COMMIT / ISSUES FOUND
```

If any phase fails, list the specific failures and stop — do not suggest committing.
