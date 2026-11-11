param([switch]$Offline)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath 'frontend/node_modules/.package-lock.json')) {
    $npmArgs = @('--prefix', 'frontend', 'ci', '--no-audit', '--no-fund')
    if ($Offline) { $npmArgs += '--offline' }
    & npm @npmArgs
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
}
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
if (-not (Test-Path -LiteralPath 'resources/engine/mihomo.exe')) {
    throw 'Missing engine. Run: python scripts/fetch_engine.py'
}
New-Item -ItemType Directory -Force -Path product | Out-Null
python -m PyInstaller --noconfirm --clean --onedir --console --name node-quality-service --distpath resources/backend-dist --workpath build/python --specpath build --paths backend --collect-all certifi backend/main.py
if ($LASTEXITCODE -ne 0) { throw 'Python backend build failed' }
$built = Join-Path $PSScriptRoot 'resources/backend-dist/node-quality-service'
$target = Join-Path $PSScriptRoot 'resources/backend'
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $built '*') -Destination $target -Recurse -Force
& (Join-Path $PSScriptRoot 'scripts/build-clash-helper.ps1')
$cargoArgs = @('--locked')
if ($Offline) { $cargoArgs += '--offline' }
cargo tauri build -- @cargoArgs
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
Get-ChildItem src-tauri/target/release/bundle/nsis/*.exe | Copy-Item -Destination product -Force
