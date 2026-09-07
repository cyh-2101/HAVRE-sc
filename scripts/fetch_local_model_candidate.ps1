[CmdletBinding()]
param(
    [ValidateSet(
        "qwen3-14b-q4-k-m.json",
        "qwen3-6-35b-a3b-q4-k-m.json"
    )]
    [string]$ModelManifestName = "qwen3-14b-q4-k-m.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ManifestPath = Join-Path $ProjectRoot "mlsys\serving\manifests\$ModelManifestName"
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Pinned candidate manifest is missing"
}
$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
if (
    [string]$manifest.artifact_kind -ne "model" -or
    [string]$manifest.lifecycle_status -ne "candidate" -or
    -not [bool]$manifest.immutable -or
    [bool]$manifest.serving_profile.request_logging
) {
    throw "Candidate manifest violates the local evaluation boundary"
}
$expectedHash = [string]$manifest.artifact.sha256
if ($expectedHash -notmatch '^sha256:[0-9a-f]{64}$') {
    throw "Candidate manifest SHA-256 is invalid"
}
$CandidateRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime\model-candidates\$($manifest.manifest_id)"))
$AllowedRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime\model-candidates"))
if (-not $CandidateRoot.StartsWith($AllowedRoot.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase)) {
    throw "Candidate path escaped the local runtime root"
}
New-Item -ItemType Directory -Path $CandidateRoot -Force | Out-Null
$destination = Join-Path $CandidateRoot ([string]$manifest.artifact.filename)
function Assert-CandidateArtifact {
    param([string]$Path)
    if ((Get-Item -LiteralPath $Path).Length -ne [long]$manifest.artifact.size_bytes) {
        throw "Candidate artifact size mismatch"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($actual -ne $expectedHash.Substring(7)) {
        throw "Candidate artifact SHA-256 mismatch"
    }
}
if (Test-Path -LiteralPath $destination -PathType Leaf) {
    Assert-CandidateArtifact -Path $destination
    Write-Host "Pinned candidate is already verified at $destination"
    return
}
$partial = "$destination.partial"
$legacyPartials = @(
    Get-ChildItem -LiteralPath $CandidateRoot -Filter "$([string]$manifest.artifact.filename).*.partial" -File -ErrorAction SilentlyContinue
)
if (-not (Test-Path -LiteralPath $partial) -and $legacyPartials.Count -eq 1) {
    Move-Item -LiteralPath $legacyPartials[0].FullName -Destination $partial
}
elseif ($legacyPartials.Count -gt 0) {
    throw "Ambiguous legacy candidate partials require manual review"
}
$aria2 = Get-Command aria2c.exe -ErrorAction SilentlyContinue
if ($null -ne $aria2) {
    Write-Host "Downloading pinned candidate $($manifest.display_name) with resumable parallel streaming"
    & $aria2.Source `
        "--allow-overwrite=true" `
        "--auto-file-renaming=false" `
        "--continue=true" `
        "--disable-ipv6=true" `
        "--file-allocation=none" `
        "--max-connection-per-server=16" `
        "--min-split-size=10M" `
        "--split=16" `
        "--dir=$CandidateRoot" `
        "--out=$([IO.Path]::GetFileName($partial))" `
        ([string]$manifest.artifact.url)
    if ($LASTEXITCODE -ne 0) {
        throw "Candidate download failed with aria2 exit code $LASTEXITCODE; resumable partial retained"
    }
}
else {
    $curl = Get-Command curl.exe -ErrorAction Stop
    Write-Host "Downloading pinned candidate $($manifest.display_name) with resumable streaming"
    & $curl.Source `
        "--fail" `
        "--location" `
        "--retry" "3" `
        "--retry-all-errors" `
        "--continue-at" "-" `
        "--output" $partial `
        ([string]$manifest.artifact.url)
    if ($LASTEXITCODE -ne 0) {
        throw "Candidate download failed with curl exit code $LASTEXITCODE; resumable partial retained"
    }
}
try {
    Assert-CandidateArtifact -Path $partial
}
catch {
    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
    throw
}
Move-Item -LiteralPath $partial -Destination $destination
Remove-Item -LiteralPath "$partial.aria2" -Force -ErrorAction SilentlyContinue
Write-Host "Pinned candidate downloaded and verified at $destination"
