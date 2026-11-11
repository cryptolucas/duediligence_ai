# Levanta backend (FastAPI :8000) y frontend (Next.js :3000) en Windows.
# Uso:  powershell -ExecutionPolicy Bypass -File .\dev.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creando entorno virtual de Python e instalando dependencias..."
    $launcher = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
    if ($launcher -eq "py") { & py -3 -m venv (Join-Path $backend ".venv") } else { & python -m venv (Join-Path $backend ".venv") }
    & $python -m pip install -r (Join-Path $backend "requirements.txt")
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "Instalando dependencias del frontend..."
    Push-Location $frontend; npm install; Pop-Location
}

Write-Host "Backend  -> http://127.0.0.1:8000/docs"
$api = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $backend -PassThru -NoNewWindow

try {
    Write-Host "Frontend -> http://localhost:3000  (Ctrl+C para detener ambos)"
    Push-Location $frontend
    npm run dev
}
finally {
    Pop-Location
    if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
}
