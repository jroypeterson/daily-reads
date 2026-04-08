param(
    [string]$TaskName = "DailyReadsDropboxTasteSync",
    [string]$Time = "06:00"
)

$ErrorActionPreference = "Stop"

$RepoPath = "C:\Users\jroyp\Dropbox\Claude Folder\daily-reads"
$Python = "C:\Users\jroyp\AppData\Local\Programs\Python\Python314\python.exe"
$Script = @"
import subprocess, sys
# Sync with remote first so local taste ingestion stacks on top of the latest
# GitHub Actions workflow output instead of forking history. Without this the
# local 'taste ingestion' commits and the remote 'Daily reads' commits diverge
# every day because they touch the same learned_preferences files.
subprocess.run(['git', 'fetch', 'origin'], check=False)
r = subprocess.run(['git', 'pull', '--rebase', '--autostash', '-X', 'ours', 'origin', 'main'])
if r.returncode != 0:
    print('git pull --rebase failed; aborting taste ingestion to avoid divergence')
    subprocess.run(['git', 'rebase', '--abort'], check=False)
    sys.exit(r.returncode)
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
