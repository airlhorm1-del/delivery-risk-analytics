# Registers the daily 07:00 run in Windows Task Scheduler under your own Windows account.
# - Runs only while you are logged in (no password needed), without waking the laptop.
# - If the laptop was off or asleep at 07:00, it runs as soon as it can; the simulator fills in missed days.
# See or switch it off: Task Scheduler app > Task Scheduler Library > "DeliveryRisk daily simulation".
# Remove it completely: scripts\unregister_daily_task.ps1

$taskName = "DeliveryRisk daily simulation"
$script = Join-Path $PSScriptRoot "run_daily.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At "07:00"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "Delivery-risk project: today's API data, simulated live orders (SYNTHETIC), dbt build and tests, BigQuery refresh." | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
