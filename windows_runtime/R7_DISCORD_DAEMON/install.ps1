#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Install OpenClaw R7 Discord Daemon as a Task Scheduler task on Windows.

.DESCRIPTION
    - Creates Task Scheduler task: trigger=AtLogon, restart every 1min on failure
    - Creates .bearer.R7.local: prompts for token, writes file, sets hidden+system ACLs
    - Adds Windows Defender exclusion for workspace path
    - Creates 7-minute kill task for R1 (fires AtLogon+7min, kills R1 pythonw.exe)

.NOTES
    Run as Administrator.
    Requires: Python 3.11+ on PATH, pywinauto installed.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------

$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkspaceDir  = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$DaemonScript  = Join-Path $ScriptDir "daemon.py"
$IngestClientDir = Join-Path (Split-Path -Parent $ScriptDir) "ingest_client"
$BearerFileR7  = Join-Path $IngestClientDir ".bearer.R7.local"
$CurrentUser   = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

# Find python executable
try {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
} catch {
    Write-Error "Python not found on PATH. Install Python 3.11+ and ensure it is on PATH."
    exit 1
}

Write-Host ""
Write-Host "=== OpenClaw R7 Daemon Installer ===" -ForegroundColor Cyan
Write-Host "Workspace : $WorkspaceDir"
Write-Host "Python    : $PythonExe"
Write-Host "Daemon    : $DaemonScript"
Write-Host "User      : $CurrentUser"
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Create .bearer.R7.local
# ---------------------------------------------------------------------------

Write-Host "--- Step 1: Bearer token for R7 ---" -ForegroundColor Yellow

if (Test-Path $BearerFileR7) {
    Write-Host "  .bearer.R7.local already exists at $BearerFileR7"
    $overwrite = Read-Host "  Overwrite? [y/N]"
    if ($overwrite -notmatch '^[Yy]$') {
        Write-Host "  Skipping bearer token setup."
        $SkipBearer = $true
    }
}

if (-not $SkipBearer) {
    $token = Read-Host "  Enter R7 bearer token (from VPS /root/.openclaw/.env INGEST_BEARER_R7)"

    if ([string]::IsNullOrWhiteSpace($token)) {
        Write-Error "Token cannot be empty."
        exit 1
    }

    # Write without trailing newline
    [System.IO.File]::WriteAllText($BearerFileR7, $token.Trim())

    # Set hidden + system attributes
    attrib +H +S $BearerFileR7

    # Lock ACLs: remove inherited, grant only current user Full Control
    try {
        $acl = Get-Acl $BearerFileR7
        $acl.SetAccessRuleProtection($true, $false)  # Disable inheritance, remove inherited

        # Remove all existing access rules
        $acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }

        # Grant current user Full Control
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $CurrentUser,
            "FullControl",
            "None",
            "None",
            "Allow"
        )
        $acl.AddAccessRule($rule)
        Set-Acl -Path $BearerFileR7 -AclObject $acl
        Write-Host "  Bearer file created and locked: $BearerFileR7" -ForegroundColor Green
    } catch {
        Write-Warning "  Could not set ACL on bearer file: $_"
        Write-Host "  File written but ACL hardening failed. Set manually if needed." -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------------------
# 2. Task Scheduler: R7 daemon
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "--- Step 2: Task Scheduler — R7 daemon ---" -ForegroundColor Yellow

$TaskNameR7 = "OpenClaw-R7-Daemon"

try {
    $existingTask = Get-ScheduledTask -TaskName $TaskNameR7 -ErrorAction SilentlyContinue
    if ($existingTask) {
        Write-Host "  Task '$TaskNameR7' already exists — unregistering to recreate."
        Unregister-ScheduledTask -TaskName $TaskNameR7 -Confirm:$false
    }

    # Action: run python daemon.py with INGEST_URL from environment
    $action = New-ScheduledTaskAction `
        -Execute $PythonExe `
        -Argument "`"$DaemonScript`"" `
        -WorkingDirectory $ScriptDir

    # Trigger: at logon of current user
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser

    # Settings: restart on failure every 1 min, up to 999 times; run whether on battery or not
    $settings = New-ScheduledTaskSettingsSet `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Days 0) `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable:$false

    # Principal: run as current user, only when logged in (interactive)
    $principal = New-ScheduledTaskPrincipal `
        -UserId $CurrentUser `
        -LogonType Interactive `
        -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $TaskNameR7 `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "OpenClaw R7 Discord UI message capture daemon" | Out-Null

    Write-Host "  Task '$TaskNameR7' registered successfully." -ForegroundColor Green
} catch {
    Write-Error "Failed to create Task Scheduler task for R7: $_"
    exit 1
}

# ---------------------------------------------------------------------------
# 3. Task Scheduler: R1 kill task (fires at logon + 7 minutes)
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "--- Step 3: Task Scheduler — R1 kill task (logon + 7min) ---" -ForegroundColor Yellow

$TaskNameR1Kill = "OpenClaw-R1-KillAfter7Min"

try {
    $existingKill = Get-ScheduledTask -TaskName $TaskNameR1Kill -ErrorAction SilentlyContinue
    if ($existingKill) {
        Write-Host "  Task '$TaskNameR1Kill' already exists — unregistering to recreate."
        Unregister-ScheduledTask -TaskName $TaskNameR1Kill -Confirm:$false
    }

    # Action: kill pythonw.exe processes whose command line contains "R1"
    $killScript = "Get-WmiObject Win32_Process | Where-Object { `$_.Name -like '*python*' -and `$_.CommandLine -like '*R1*' } | ForEach-Object { Stop-Process -Id `$_.ProcessId -Force -ErrorAction SilentlyContinue }"
    $killAction = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NonInteractive -WindowStyle Hidden -Command `"$killScript`""

    # Trigger: at logon, then delay 7 minutes
    $killTrigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
    $killTrigger.Delay = "PT7M"

    $killSettings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
        -StartWhenAvailable

    $killPrincipal = New-ScheduledTaskPrincipal `
        -UserId $CurrentUser `
        -LogonType Interactive `
        -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $TaskNameR1Kill `
        -Action $killAction `
        -Trigger $killTrigger `
        -Settings $killSettings `
        -Principal $killPrincipal `
        -Description "Kill OpenClaw R1 python processes 7 minutes after logon" | Out-Null

    Write-Host "  Task '$TaskNameR1Kill' registered successfully." -ForegroundColor Green
} catch {
    Write-Warning "Failed to create R1 kill task: $_"
    Write-Host "  Non-fatal — continuing." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 4. Windows Defender exclusion
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "--- Step 4: Windows Defender exclusion ---" -ForegroundColor Yellow

try {
    Add-MpPreference -ExclusionPath $WorkspaceDir
    Write-Host "  Defender exclusion added: $WorkspaceDir" -ForegroundColor Green
} catch {
    Write-Warning "  Could not add Defender exclusion: $_"
    Write-Host "  Non-fatal — add manually if AV interferes with pywinauto." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Copy config.example.json → config.json and set your ingest_url + channels"
Write-Host "  2. Ensure INGEST_URL is set as a system environment variable (or edit the task action)"
Write-Host "  3. Log off and back on, or start the task manually:"
Write-Host "     Start-ScheduledTask -TaskName '$TaskNameR7'"
Write-Host "  4. View logs: Get-Content `"`$env:APPDATA\openclaw\r7.log`" -Wait"
Write-Host ""
