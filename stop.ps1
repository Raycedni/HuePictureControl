# HuePictureControl — Stop Backend + Frontend
# Usage: .\stop.ps1

$pidFile = Join-Path $PSScriptRoot ".hpc-pids"
$stopped = 0

# Kill saved cmd.exe processes and their children
if (Test-Path $pidFile) {
    $pids = (Get-Content $pidFile) -split ","
    foreach ($procId in $pids) {
        # Kill child processes (uvicorn, node, etc.) first
        Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq [int]$procId } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        $stopped++
    }
    Remove-Item $pidFile -Force
}

# Also kill anything still listening on our ports
foreach ($port in @(8000, 5173)) {
    $lines = netstat -ano | Select-String "LISTENING" | Select-String ":$port "
    foreach ($line in $lines) {
        $fields = $line.ToString().Trim() -split '\s+'
        $listenPid = [int]$fields[-1]
        if ($listenPid -gt 0) {
            Stop-Process -Id $listenPid -Force -ErrorAction SilentlyContinue
            $stopped++
        }
    }
}

Write-Host "Stopped $stopped HPC process(es)."
