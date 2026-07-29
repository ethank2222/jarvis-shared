$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$installer = Join-Path $PSScriptRoot "install_jarvis_command.ps1"
$runner = Join-Path $repoRoot "run_jarvis.py"

Write-Host "Repairing Jarvis command launcher..."
& $installer

Write-Host ""
Write-Host "Running Jarvis health diagnostics..."
python $runner --health
