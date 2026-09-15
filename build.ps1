$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$BuildRoot = Join-Path $env:TEMP "NexTermBuild"
$SourceRoot = Join-Path $BuildRoot "src"
$BuildVenv = Join-Path $BuildRoot ".venv"
if ((Test-Path $BuildRoot) -and ((Resolve-Path $BuildRoot).Path.StartsWith((Resolve-Path $env:TEMP).Path))) {
  Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $SourceRoot | Out-Null
Copy-Item -LiteralPath app -Destination $SourceRoot -Recurse
Copy-Item -LiteralPath assets -Destination $SourceRoot -Recurse -ErrorAction SilentlyContinue
Copy-Item -LiteralPath packaging -Destination $SourceRoot -Recurse
Copy-Item -LiteralPath main.py, requirements.txt -Destination $SourceRoot

py -m venv $BuildVenv
& "$BuildVenv\Scripts\python.exe" -m pip install --upgrade pip
& "$BuildVenv\Scripts\python.exe" -m pip install -r "$SourceRoot\requirements.txt" pyinstaller

Push-Location $SourceRoot
& "$BuildVenv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name NexTerm `
  --version-file packaging\version_info.txt `
  --collect-all qfluentwidgets `
  --exclude-module tkinter `
  --exclude-module unittest `
  --distpath "$PSScriptRoot\dist" `
  --workpath "$PSScriptRoot\build" `
  main.py
Pop-Location

if (-not (Test-Path "dist\NexTerm\NexTerm.exe")) {
  throw "Build failed: dist\NexTerm\NexTerm.exe was not created"
}
New-Item -ItemType Directory -Force -Path artifacts | Out-Null
Compress-Archive -Path dist\NexTerm\* -DestinationPath artifacts\NexTerm-Windows.zip -Force
Write-Host "Build complete: dist\NexTerm\NexTerm.exe" -ForegroundColor Green
Write-Host "Release archive: artifacts\NexTerm-Windows.zip" -ForegroundColor Green
