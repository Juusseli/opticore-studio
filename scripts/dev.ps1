# Start the OptiCore engine (port 8000, or the next free port) and the web UI (port 5173).
# Usage:  .\scripts\dev.ps1          (developers)
#         .\scripts\dev.ps1 -Open    (also opens the browser when the UI is ready;
#                                     used by "Start OptiCore.bat")
param([switch]$Open)
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
  Write-Host 'First start: creating the engine environment (this takes a few minutes)...'
  python -m venv (Join-Path $root 'backend\.venv')
  & $py -m pip install -e (Join-Path $root 'backend[dev]')
}
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
  Write-Host 'First start: installing the user interface packages...'
  Push-Location (Join-Path $root 'frontend'); npm install; Pop-Location
}
# The engine takes port 8000, or the first free port from 8010 when another program holds 8000 (the UI's
# dev server is pointed at it through OPTICORE_ENGINE_URL).
function Test-PortFree([int]$port) {
  $l = $null
  try { $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port); $l.Start(); return $true }
  catch { return $false }
  finally { if ($l) { $l.Stop() } }
}
$enginePort = 8000
if (-not (Test-PortFree $enginePort)) {
  $enginePort = 8010  # 8001 is kept for a test instance
  while (-not (Test-PortFree $enginePort)) {
    $enginePort++
    if ($enginePort -gt 8100) { Write-Host 'No free port for the engine (8000, 8010-8100).' -ForegroundColor Red; exit 1 }
  }
}
if ($enginePort -ne 8000) { Write-Host "Port 8000 is used by another program; the engine runs on port $enginePort." -ForegroundColor Yellow }
$env:OPTICORE_ENGINE_URL = "http://127.0.0.1:$enginePort"
$engine = Start-Process -FilePath $py -ArgumentList '-m','uvicorn','--app-dir',(Join-Path $root 'backend'),'opticore.api.main:app','--host','127.0.0.1','--port',"$enginePort" -PassThru -NoNewWindow
# report an engine that stops at once (instead of a user interface that only says 'offline')
Start-Sleep -Seconds 3
if ($engine.HasExited) { Write-Host "The engine stopped at start (exit code $($engine.ExitCode)); see the messages above." -ForegroundColor Red }
if ($Open) {
  # open the browser as soon as the user interface answers (at most 90 s)
  Start-Job -ScriptBlock {
    for ($i = 0; $i -lt 180; $i++) {
      try {
        Invoke-WebRequest -Uri 'http://localhost:5173' -UseBasicParsing -TimeoutSec 2 | Out-Null
        Start-Process 'http://localhost:5173'
        return
      } catch { Start-Sleep -Milliseconds 500 }
    }
  } | Out-Null
  Write-Host ''
  Write-Host 'OptiCore Studio is starting; the browser opens at http://localhost:5173'
  Write-Host 'Close this window (or press Ctrl+C) to stop the program.'
  Write-Host ''
}
try {
  Push-Location (Join-Path $root 'frontend')
  npm run dev
} finally {
  Pop-Location
  if ($engine -and -not $engine.HasExited) { Stop-Process -Id $engine.Id }
}
