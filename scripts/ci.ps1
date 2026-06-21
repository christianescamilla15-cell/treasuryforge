# Full local quality gate for Windows. Run from the project root:
#   powershell -ExecutionPolicy Bypass -File scripts\ci.ps1
$ErrorActionPreference = "Stop"
$bin = ".\.venv\Scripts"

function Step($name, $cmd) {
    Write-Host "==> $name"
    & $cmd
    if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $name"; exit 1 }
}

Step "ruff (lint)"        { & "$bin\ruff.exe" check treasuryforge tests scripts }
Step "mypy (types)"       { & "$bin\mypy.exe" }
Step "bandit (security)"  { & "$bin\bandit.exe" -r treasuryforge -q -ll }
Step "pip-audit (deps)"   { & "$bin\pip-audit.exe" -r requirements-live.txt -r requirements-dev.txt --progress-spinner off }
Step "pytest + coverage"  { & "$bin\python.exe" -m pytest --cov=treasuryforge --cov-report=xml --cov-report=term -q }
Write-Host "==> ALL GREEN"
