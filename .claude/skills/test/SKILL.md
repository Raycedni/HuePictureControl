---
name: test
description: Run all backend and frontend tests in parallel and report results
disable-model-invocation: true
argument-hint: [backend|frontend|all]
---

# Run Project Tests

Run the test suites for HuePictureControl. Argument: `$ARGUMENTS` (default: all).

## Rules
- Run backend and frontend tests **in parallel** using separate Bash tool calls in a single message.
- Report pass/fail counts and any failures with file:line references.
- If a specific suite is requested (`backend` or `frontend`), only run that one.

## Commands

### Backend (167+ tests)
```bash
source /tmp/hpc-venv/bin/activate && cd /mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/Backend && python -m pytest --tb=short -q
```
If the venv doesn't exist, create it first:
```bash
python3 -m venv /tmp/hpc-venv && source /tmp/hpc-venv/bin/activate && pip install -r /mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/Backend/requirements.txt
```

### Frontend (30+ tests)
```bash
cd /mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/Frontend && npx vitest run
```

## Output Format
Summarize results as:
```
Backend:  X passed, Y failed
Frontend: X passed, Y failed
```
If all pass, say "All tests green." If any fail, list the failing test names.
