$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$cmdLauncher = Join-Path $repoRoot "jarvis.cmd"
$batLauncher = Join-Path $repoRoot "jarvis.bat"
$pythonScripts = Join-Path $env:LocalAppData "Programs\Python\Python313\Scripts"
$cmdDestination = Join-Path $pythonScripts "jarvis.cmd"
$batDestination = Join-Path $pythonScripts "jarvis.bat"

if (-not (Test-Path $cmdLauncher)) {
    throw "Launcher not found: $cmdLauncher"
}

if (-not (Test-Path $batLauncher)) {
    throw "Launcher not found: $batLauncher"
}

if (-not (Test-Path $pythonScripts)) {
    New-Item -ItemType Directory -Path $pythonScripts -Force | Out-Null
}

Copy-Item -Path $cmdLauncher -Destination $cmdDestination -Force
Copy-Item -Path $batLauncher -Destination $batDestination -Force

Write-Host "Installed Jarvis launcher:"
Write-Host $cmdDestination
Write-Host $batDestination
Write-Host ""
Write-Host "Open a new terminal and run:"
Write-Host "jarvis"
