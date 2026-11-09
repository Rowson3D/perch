# Installs the Perch agent on a Windows GPU machine as a startup task + firewall rule.
# Put this script next to perch-agent.exe (or perch_agent.py + Python 3), then from an
# elevated (Administrator) PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\install_agent_windows.ps1 [-Port 9123]
param([int]$Port = 9123)
$ErrorActionPreference = 'Stop'

$dest = Join-Path $env:ProgramData 'Perch'
New-Item -ItemType Directory -Force $dest | Out-Null
Stop-ScheduledTask -TaskName 'PerchAgent' -ErrorAction SilentlyContinue

$exe = Join-Path $PSScriptRoot 'perch-agent.exe'
if (Test-Path $exe) {
    Copy-Item $exe $dest -Force
    $action = New-ScheduledTaskAction -Execute (Join-Path $dest 'perch-agent.exe') -Argument "--port $Port"
} else {
    Copy-Item (Join-Path $PSScriptRoot 'perch_agent.py') $dest -Force
    $pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    if (-not $pyw) { throw "Neither perch-agent.exe nor pythonw.exe found. Download perch-agent.exe from the GitHub release." }
    $action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$dest\perch_agent.py`" --port $Port"
}

$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
             -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'PerchAgent' -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Force | Out-Null

Get-NetFirewallRule -DisplayName 'Perch agent' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'Perch agent' -Direction Inbound -Protocol TCP -LocalPort $Port `
    -Action Allow -Profile Domain,Private | Out-Null

Start-ScheduledTask -TaskName 'PerchAgent'
Start-Sleep 2
Write-Host "Agent installed and running. Test: http://localhost:$Port/gpus"
Write-Host "To remove: Unregister-ScheduledTask PerchAgent; Remove-NetFirewallRule -DisplayName 'Perch agent'"
