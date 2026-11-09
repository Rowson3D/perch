# Installs the GPU Watch agent on a Windows GPU machine as a startup task + firewall rule.
# Put this script next to gpu-agent.exe (or gpu_agent.py + Python 3), then from an
# elevated (Administrator) PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\install_agent_windows.ps1 [-Port 9123]
param([int]$Port = 9123)
$ErrorActionPreference = 'Stop'

$dest = Join-Path $env:ProgramData 'GpuWatch'
New-Item -ItemType Directory -Force $dest | Out-Null
Stop-ScheduledTask -TaskName 'GpuWatchAgent' -ErrorAction SilentlyContinue

$exe = Join-Path $PSScriptRoot 'gpu-agent.exe'
if (Test-Path $exe) {
    Copy-Item $exe $dest -Force
    $action = New-ScheduledTaskAction -Execute (Join-Path $dest 'gpu-agent.exe') -Argument "--port $Port"
} else {
    Copy-Item (Join-Path $PSScriptRoot 'gpu_agent.py') $dest -Force
    $pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    if (-not $pyw) { throw "Neither gpu-agent.exe nor pythonw.exe found. Download gpu-agent.exe from the GitHub release." }
    $action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$dest\gpu_agent.py`" --port $Port"
}

$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
             -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'GpuWatchAgent' -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Force | Out-Null

Get-NetFirewallRule -DisplayName 'GPU Watch agent' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'GPU Watch agent' -Direction Inbound -Protocol TCP -LocalPort $Port `
    -Action Allow -Profile Domain,Private | Out-Null

Start-ScheduledTask -TaskName 'GpuWatchAgent'
Start-Sleep 2
Write-Host "Agent installed and running. Test: http://localhost:$Port/gpus"
Write-Host "To remove: Unregister-ScheduledTask GpuWatchAgent; Remove-NetFirewallRule -DisplayName 'GPU Watch agent'"
