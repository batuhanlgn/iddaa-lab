# iddaa-lab baslatici: arka uc (FastAPI, 127.0.0.1:8765) + arayuz (Next.js, 127.0.0.1:3000)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Web = Join-Path $Root "web"
$Py = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $Py)) {
    Write-Host "Python sanal ortami kuruluyor..." -ForegroundColor Cyan
    python -m venv (Join-Path $Backend ".venv")
    & $Py -m pip install -q -r (Join-Path $Backend "requirements.txt")
}
if (-not (Test-Path (Join-Path $Web "node_modules"))) {
    Write-Host "Arayuz bagimliliklari kuruluyor..." -ForegroundColor Cyan
    Push-Location $Web; npm install; Pop-Location
}

# Ilk kurulum: veritabani bossa tam veri indirme + backtest + tahmin (yaklasik 1 saat)
Push-Location $Backend
$flag = (& $Py -m app.needs_bootstrap | Out-String).Trim()
Pop-Location
$NeedBootstrap = ($flag -eq "1")
if ($NeedBootstrap) {
    Write-Host "Ilk kurulum verisi indiriliyor (arka planda; arayuz 'Veri' sayfasinda ilerlemeyi gosterir)..." -ForegroundColor Yellow
    Start-Process -FilePath $Py -ArgumentList "-m","app.jobs","bootstrap" -WorkingDirectory $Backend -WindowStyle Minimized
}

Write-Host "Arka uc baslatiliyor: http://127.0.0.1:8765" -ForegroundColor Green
Start-Process -FilePath $Py -ArgumentList "-m","uvicorn","app.api:app","--host","127.0.0.1","--port","8765" -WorkingDirectory $Backend -WindowStyle Minimized

Push-Location $Web
$NeedBuild = -not (Test-Path ".next\BUILD_ID")
if (-not $NeedBuild) {
    $built = (Get-Item ".next\BUILD_ID").LastWriteTime
    $newer = Get-ChildItem -Recurse -File -Path "app","components","lib" | Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1
    if ($newer) { $NeedBuild = $true }
}
if ($NeedBuild) {
    Write-Host "Arayuz derleniyor..." -ForegroundColor Cyan
    npm run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Arayuz derlemesi basarisiz" }
}
Write-Host "Arayuz baslatiliyor: http://127.0.0.1:3000" -ForegroundColor Green
Start-Process -FilePath "npm.cmd" -ArgumentList "run","start","--","-H","127.0.0.1","-p","3000" -WorkingDirectory $Web -WindowStyle Minimized
Pop-Location

Start-Sleep -Seconds 4
Start-Process "http://127.0.0.1:3000"
Write-Host "Hazir. Kapatmak icin: .\stop.ps1" -ForegroundColor Green
