param(
    [string]$TaskName = "DailyReadsDropboxTasteSync",
    [string]$Time = "06:00"
)

$ErrorActionPreference = "Stop"

$RepoPath = "$env:USERPROFILE\Dropbox\Claude Folder\daily-reads"
$Python = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
$Action = New-ScheduledTaskAction -Execute $Python -Argument "taste_sync.py" -WorkingDirectory $RepoPath
$DailyTrigger = New-ScheduledTaskTrigger -Daily -At $Time
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$Settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -RestartCount 2 `
  -RestartInterval (New-TimeSpan -Minutes 10) `
  -StartWhenAvailable `
  -WakeToRun `
  -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal `
  -UserId $CurrentUser `
  -LogonType Interactive `
  -RunLevel Limited

try {
  Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger @($DailyTrigger, $LogonTrigger) `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Daily Dropbox taste exemplar sync for Daily Reads" `
    -Force | Out-Null

  Write-Host "Registered task '$TaskName' for user $CurrentUser with daily run at $Time, catch-up after missed runs, and a logon fallback"
}
catch {
  Write-Error "Failed to register scheduled task '$TaskName' for user $CurrentUser. $_"
  exit 1
}
