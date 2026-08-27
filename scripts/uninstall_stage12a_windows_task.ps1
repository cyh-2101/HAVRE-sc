param(
    [string]$TaskName = 'HAVRE Stage12A Windows Context',
    [string]$QueuePath = (Join-Path $HOME '.havre\context-queue.dpapi'),
    [string]$ProtectedSecretPath = (Join-Path $HOME '.havre\context-device-secret.dpapi'),
    [Parameter(Mandatory = $true)]
    [switch]$ConfirmLocalErasure
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmLocalErasure) {
    throw 'Uninstall requires -ConfirmLocalErasure so queued context and the device secret are erased.'
}
$cleanupTaskName = "$TaskName Retention Cleanup"
foreach ($name in @($TaskName, $cleanupTaskName)) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
}

foreach ($candidate in @(
    [System.IO.Path]::GetFullPath($QueuePath),
    [System.IO.Path]::GetFullPath($QueuePath + '.lock'),
    [System.IO.Path]::GetFullPath($ProtectedSecretPath)
)) {
    if (Test-Path -LiteralPath $candidate) {
        if ((Get-Item -LiteralPath $candidate).PSIsContainer) {
            throw "Refusing to erase a directory: $candidate"
        }
        Remove-Item -LiteralPath $candidate -Force
    }
}
