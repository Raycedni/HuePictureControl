# HuePictureControl — Start Backend + Frontend (detached)
# Usage: .\start.ps1
# Stop:  .\stop.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# --- Configuration ---
$captureDevice = "1"  # Camera index from Device Manager (0 = first, 1 = second, etc.)

# --- Backend ---
$backendDir = Join-Path $root "Backend"
$venvActivate = Join-Path $backendDir ".venv\Scripts\Activate.ps1"

if (-not (Test-Path $venvActivate)) {
    Write-Host "Creating backend venv..."
    Push-Location $backendDir
    python -m venv .venv
    & $venvActivate
    pip install -r requirements.txt
    Pop-Location
}

Write-Host "Starting backend on :8000 ..."
$backendProc = Start-Process cmd -ArgumentList "/k", "cd /d `"$backendDir`" && .venv\Scripts\activate.bat && set CAPTURE_DEVICE=$captureDevice && uvicorn main:app --host 0.0.0.0 --port 8000" -PassThru -WindowStyle Minimized

# --- Frontend ---
$frontendDir = Join-Path $root "Frontend"

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "Installing frontend dependencies..."
    Push-Location $frontendDir
    npm install
    Pop-Location
}

Write-Host "Starting frontend dev server on :5173 ..."
$viteJs = Join-Path $frontendDir "node_modules\vite\bin\vite.js"
$frontendProc = Start-Process cmd -ArgumentList "/k", "cd /d `"$frontendDir`" && node `"$viteJs`"" -PassThru

# Save PIDs for stop.ps1
$pidFile = Join-Path $root ".hpc-pids"
"$($backendProc.Id),$($frontendProc.Id)" | Set-Content $pidFile

Write-Host ""
Write-Host "Both services started in minimized windows:"
Write-Host "  Backend:  http://localhost:8000  (PID $($backendProc.Id))"
Write-Host "  Frontend: http://localhost:5173  (PID $($frontendProc.Id))"
Write-Host ""
Write-Host "Run .\stop.ps1 to stop both."
