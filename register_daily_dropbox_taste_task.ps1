param(
    [string]$TaskName = "DailyReadsDropboxTasteSync",
    [string]$Time = "06:00"
)

$ErrorActionPreference = "Stop"

$RepoPath = "C:\Users\jroyp\Dropbox\Claude Folder\daily-reads"
$Python = "C:\Users\jroyp\AppData\Local\Programs\Python\Python314\python.exe"
$Script = @"
import subprocess, sys
for s in ['process_dropbox_exemplars.py', 'process_exemplar_content.py', 'preference_learning.py']:
    r = subprocess.run([sys.executable, s])
    if r.returncode != 0:
        sys.exit(r.returncode)
# Commit and push if taste_evidence.json or learned_preferences changed
r = subprocess.run(['git', 'diff', '--quiet', 'taste_evidence.json', 'learned_preferences.json', 'learned_preferences.md'])
if r.returncode != 0:
    subprocess.run(['git', 'add', 'taste_evidence.json', 'learned_preferences.json', 'learned_preferences.md'])
    subprocess.run(['git', 'commit', '-m', 'Local Dropbox taste ingestion'])
    subprocess.run(['git', 'push'])
"@
$Action = New-ScheduledTaskAction -Execute $Python -Argument "-c ""$Script""" -WorkingDirectory $RepoPath
$DailyTrigger = New-ScheduledTaskTrigger -Daily -At $Time
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$Settings = New-ScheduledTaskSettingsSet `
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
