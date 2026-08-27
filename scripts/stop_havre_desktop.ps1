[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$StatePath = Join-Path $ProjectRoot ".runtime\desktop\state.json"
$SecretRoot = Join-Path $ProjectRoot ".runtime\desktop\secrets"
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "HAVRE desktop state is missing; refusing to stop an unverified process"
}
$state = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
if ([int]$state.schema_version -ne 1 -or -not [bool]$state.candidate_only) {
    throw "HAVRE desktop state is invalid"
}
$process = Get-Process -Id ([int]$state.api_pid) -ErrorAction SilentlyContinue
if ($null -ne $process) {
    $expected = [IO.Path]::GetFullPath([string]$state.api_executable)
    if (-not $process.Path.Equals($expected,[StringComparison]::OrdinalIgnoreCase)) {
        throw "Desktop API PID no longer names the recorded executable"
    }
    Stop-Process -Id $process.Id -ErrorAction Stop
    $process.WaitForExit(30000) | Out-Null
}
Remove-Item -LiteralPath $StatePath -Force
& (Join-Path $PSScriptRoot "stop_havre_candidate_local.ps1")
foreach ($name in @("database-url.secret","owner-api-token.secret","desktop-bootstrap-token.secret")) {
    $path = Join-Path $SecretRoot $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
    }
}
Write-Host "HAVRE desktop stopped cleanly."
