param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^sha256:[0-9a-f]{64}$')]
    [string]$SourceSnapshot,
    [string]$TaskName = 'HAVRE Stage12A Windows Context',
    [string]$QueuePath = (Join-Path $HOME '.havre\context-queue.dpapi'),
    [ValidateRange(1, 60)]
    [int]$CleanupIntervalMinutes = 1,
    [switch]$EnableCollection
)

$ErrorActionPreference = 'Stop'
$resolvedPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$resolvedQueue = [System.IO.Path]::GetFullPath($QueuePath)
$cleanupTaskName = "$TaskName Retention Cleanup"

if ($EnableCollection) {
    throw 'Collection activation requires an owner-approved policy manifest and is intentionally unavailable in this checkpoint.'
}

$argument = "-m apps.windows_agent.cli capability-check --expected-source-snapshot $SourceSnapshot"
& $resolvedPython -m apps.windows_agent.cli capability-check `
    --expected-source-snapshot $SourceSnapshot | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Windows agent source snapshot preflight failed.'
}
$action = New-ScheduledTaskAction `
    -Execute $resolvedPython `
    -Argument $argument `
    -WorkingDirectory $resolvedRoot
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Settings $settings `
    -Description 'Disabled-by-default HAVRE Stage12A content-free capability check. No collection trigger is registered.' `
    -Force | Out-Null
Disable-ScheduledTask -TaskName $TaskName | Out-Null

# This enabled task performs no sensing and no network access. It exists only
# to make consented local ciphertext expiry physical even while collection is
# disabled, revoked, offline, or never run again.
$cleanupArgument = "-m apps.windows_agent.cli queue-cleanup --expected-source-snapshot $SourceSnapshot --queue-path `"$resolvedQueue`""
$cleanupAction = New-ScheduledTaskAction `
    -Execute $resolvedPython `
    -Argument $cleanupArgument `
    -WorkingDirectory $resolvedRoot
$cleanupTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $CleanupIntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask `
    -TaskName $cleanupTaskName `
    -Action $cleanupAction `
    -Trigger $cleanupTrigger `
    -Settings $settings `
    -Description 'No-sensing HAVRE local encrypted-queue retention cleanup.' `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName,$cleanupTaskName | Select-Object TaskName, State
