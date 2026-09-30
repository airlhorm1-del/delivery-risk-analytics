# Removes the daily 07:00 task created by register_daily_task.ps1. Nothing else is changed.
Unregister-ScheduledTask -TaskName "DeliveryRisk daily simulation" -Confirm:$false
Write-Output "Removed the scheduled task 'DeliveryRisk daily simulation'."
