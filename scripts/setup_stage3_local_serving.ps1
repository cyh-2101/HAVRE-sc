[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ManifestRoot = Join-Path $ProjectRoot "mlsys\serving\manifests"
$RuntimeRoot = Join-Path $ProjectRoot ".runtime\stage3"
$DownloadRoot = Join-Path $RuntimeRoot "downloads"
$EngineRoot = Join-Path $RuntimeRoot "engine\llama-cpp-b10405"
$ModelRoot = Join-Path $RuntimeRoot "models"
$StatePath = Join-Path $RuntimeRoot "runtime-state.json"
$EngineManifestPath = Join-Path $ManifestRoot "llama-cpp-b10405-win-cuda-12.4-x64.json"
$ModelManifestPath = Join-Path $ManifestRoot "qwen3-8b-q4-k-m.json"

function Read-JsonManifest {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw "Pinned manifest is missing: $LiteralPath"
    }
    return Get-Content -Raw -LiteralPath $LiteralPath | ConvertFrom-Json
}

function Get-UnqualifiedSha256 {
    param([Parameter(Mandatory = $true)][string]$QualifiedHash)

    if ($QualifiedHash -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "Manifest contains an invalid SHA-256 value: $QualifiedHash"
    }
    return $QualifiedHash.Substring(7)
}

function Assert-PinnedFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][long]$ExpectedSizeBytes,
        [Parameter(Mandatory = $true)][string]$ExpectedQualifiedSha256
    )

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw "Pinned artifact is missing: $LiteralPath"
    }
    $file = Get-Item -LiteralPath $LiteralPath
    if ($file.Length -ne $ExpectedSizeBytes) {
        throw "Pinned artifact size mismatch for $LiteralPath"
    }
    $expected = Get-UnqualifiedSha256 $ExpectedQualifiedSha256
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $LiteralPath).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "Pinned artifact SHA-256 mismatch for $LiteralPath"
    }
}

function Get-PinnedArtifact {
    param(
        [Parameter(Mandatory = $true)]$Artifact,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )

    $destination = Join-Path $DestinationRoot ([string]$Artifact.filename)
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        Assert-PinnedFile `
            -LiteralPath $destination `
            -ExpectedSizeBytes ([long]$Artifact.size_bytes) `
            -ExpectedQualifiedSha256 ([string]$Artifact.sha256)
        return $destination
    }

    $partial = "$destination.$([guid]::NewGuid().ToString('N')).partial"
    Write-Host "Downloading pinned artifact $($Artifact.filename)"
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri ([string]$Artifact.url) `
        -OutFile $partial
    Assert-PinnedFile `
        -LiteralPath $partial `
        -ExpectedSizeBytes ([long]$Artifact.size_bytes) `
        -ExpectedQualifiedSha256 ([string]$Artifact.sha256)
    Move-Item -LiteralPath $partial -Destination $destination
    return $destination
}

foreach ($directory in @($RuntimeRoot, $DownloadRoot, $EngineRoot, $ModelRoot)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

$engineManifest = Read-JsonManifest $EngineManifestPath
$modelManifest = Read-JsonManifest $ModelManifestPath
if (
    [string]$modelManifest.serving_profile.serving_engine_manifest_id -ne
    [string]$engineManifest.manifest_id
) {
    throw "Model and serving-engine manifests are not compatible"
}

$verifiedArchives = @()
foreach ($artifact in $engineManifest.artifacts) {
    $archivePath = Get-PinnedArtifact `
        -Artifact $artifact `
        -DestinationRoot $DownloadRoot
    $verifiedArchives += [pscustomobject]@{
        role = [string]$artifact.role
        relative_path = "downloads\$([string]$artifact.filename)"
        size_bytes = [long]$artifact.size_bytes
        sha256 = [string]$artifact.sha256
    }
}

# Every archive has passed its manifest size and SHA-256 checks before extraction.
foreach ($archive in $verifiedArchives) {
    $archivePath = Join-Path $RuntimeRoot ([string]$archive.relative_path)
    Assert-PinnedFile `
        -LiteralPath $archivePath `
        -ExpectedSizeBytes ([long]$archive.size_bytes) `
        -ExpectedQualifiedSha256 ([string]$archive.sha256)
    Expand-Archive -LiteralPath $archivePath -DestinationPath $EngineRoot -Force
}

$serverCandidates = @(
    Get-ChildItem `
        -LiteralPath $EngineRoot `
        -Recurse `
        -File `
        -Filter ([string]$engineManifest.expected_executable_name)
)
if ($serverCandidates.Count -ne 1) {
    throw "Expected exactly one $($engineManifest.expected_executable_name); found $($serverCandidates.Count)"
}
$serverPath = [IO.Path]::GetFullPath($serverCandidates[0].FullName)
$serverHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $serverPath).Hash.ToLowerInvariant()

$modelPath = Get-PinnedArtifact `
    -Artifact $modelManifest.artifact `
    -DestinationRoot $ModelRoot
Assert-PinnedFile `
    -LiteralPath $modelPath `
    -ExpectedSizeBytes ([long]$modelManifest.artifact.size_bytes) `
    -ExpectedQualifiedSha256 ([string]$modelManifest.artifact.sha256)

$runtimePrefix = $RuntimeRoot.TrimEnd('\') + '\'
if (-not $serverPath.StartsWith($runtimePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Discovered executable escaped the Stage 3 runtime root"
}
$resolvedModelPath = [IO.Path]::GetFullPath($modelPath)
if (-not $resolvedModelPath.StartsWith($runtimePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Downloaded model escaped the Stage 3 runtime root"
}

$state = [ordered]@{
    schema_version = 1
    engine_manifest_id = [string]$engineManifest.manifest_id
    engine_manifest_sha256 = "sha256:$((Get-FileHash -Algorithm SHA256 -LiteralPath $EngineManifestPath).Hash.ToLowerInvariant())"
    model_manifest_id = [string]$modelManifest.manifest_id
    model_manifest_sha256 = "sha256:$((Get-FileHash -Algorithm SHA256 -LiteralPath $ModelManifestPath).Hash.ToLowerInvariant())"
    server_executable_relative_path = $serverPath.Substring($runtimePrefix.Length)
    server_executable_sha256 = "sha256:$serverHash"
    model_relative_path = $resolvedModelPath.Substring($runtimePrefix.Length)
    verified_archives = $verifiedArchives
    prepared_at = [DateTimeOffset]::UtcNow.ToString("o")
}
$state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StatePath -Encoding utf8

Write-Host "Stage 3 local serving runtime is pinned and verified at $RuntimeRoot"
Write-Host "Discovered server executable: $serverPath"
Write-Host "Pinned model: $modelPath"
