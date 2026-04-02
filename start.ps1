# HuePictureControl — Start Backend + Frontend (detached)
# Usage: .\start.ps1
# Stop:  Get-Job HPC-* | Stop-Job -PassThru | Remove-Job

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

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
$backendJob = Start-Job -Name "HPC-Backend" -ScriptBlock {
    param($dir, $activate)
    Set-Location $dir
    & $activate
    $env:CAPTURE_DEVICE = "0"
    uvicorn main:app --host 0.0.0.0 --port 8000
} -ArgumentList $backendDir, $venvActivate

# --- Frontend ---
$frontendDir = Join-Path $root "Frontend"

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "Installing frontend dependencies..."
    Push-Location $frontendDir
    npm install
    Pop-Location
}

Write-Host "Starting frontend dev server on :5173 ..."
$frontendJob = Start-Job -Name "HPC-Frontend" -ScriptBlock {
    param($dir)
    Set-Location $dir
    npm run dev
} -ArgumentList $frontendDir

Write-Host ""
Write-Host "Both services started as background jobs:"
Write-Host "  Backend:  http://localhost:8000  (job: $($backendJob.Name))"
Write-Host "  Frontend: http://localhost:5173  (job: $($frontendJob.Name))"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Receive-Job HPC-Backend   # view backend logs"
Write-Host "  Receive-Job HPC-Frontend  # view frontend logs"
Write-Host "  Get-Job HPC-*             # check status"
Write-Host "  Get-Job HPC-* | Stop-Job -PassThru | Remove-Job  # stop all"
