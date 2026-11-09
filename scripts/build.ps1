# Builds dist\Perch.exe (widget + its own installer) and dist\perch-agent.exe.
#   powershell -ExecutionPolicy Bypass -File scripts\build.ps1
param([string]$Python = "python")
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Run { & $args[0] @($args | Select-Object -Skip 1); if ($LASTEXITCODE) { throw "failed: $args" } }

if (-not (Test-Path .venv)) { Run $Python -m venv .venv }
$py = Join-Path $root '.venv\Scripts\python.exe'
Run $py -m pip install -q -e ".[build,dev]"
Run $py -m ruff check .
Run $py -m ruff format --check .
Run $py -m unittest discover -s tests
Run $py scripts\make_assets.py

Run $py -m PyInstaller --noconfirm --clean --log-level WARN --onefile --windowed `
    --name Perch --icon build\perch.ico --version-file build\version_perch.txt `
    --paths . --hidden-import pystray._win32 perch\__main__.py
Run $py -m PyInstaller --noconfirm --log-level WARN --onefile --console `
    --name perch-agent --icon build\perch.ico --version-file build\version_agent.txt `
    agent\perch_agent.py

Get-ChildItem dist\*.exe | ForEach-Object { "{0,-16} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB) }
