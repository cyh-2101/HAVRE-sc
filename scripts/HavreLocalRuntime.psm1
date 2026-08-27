Set-StrictMode -Version Latest

function Assert-HavreProcessIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)][int]$ExpectedPid,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [Parameter(Mandatory = $true)][DateTime]$ExpectedStartedAt
    )

    if ([int]$Process.Id -ne $ExpectedPid) {
        throw "Process PID does not match its ownership record"
    }
    $actualPath = [IO.Path]::GetFullPath([string]$Process.Path)
    $expectedPath = [IO.Path]::GetFullPath($ExpectedExecutable)
    if (-not $actualPath.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Process executable does not match its ownership record"
    }
    $actualStartedAt = $Process.StartTime.ToUniversalTime()
    if ([Math]::Abs(($actualStartedAt - $ExpectedStartedAt.ToUniversalTime()).TotalSeconds) -gt 0.001) {
        throw "Process start time does not match its ownership record"
    }
}

function Invoke-HavreOwnedRollback {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Ownership,
        [Parameter(Mandatory = $true)][scriptblock]$StopApi,
        [Parameter(Mandatory = $true)][scriptblock]$StopLlama,
        [Parameter(Mandatory = $true)][scriptblock]$StopPostgres
    )

    $errors = [Collections.Generic.List[string]]::new()
    foreach ($action in @(
        [pscustomobject]@{ Name = "api"; Owned = [bool]$Ownership.api_started_by_this_run; Stop = $StopApi },
        [pscustomobject]@{ Name = "llama"; Owned = [bool]$Ownership.llama_started_by_this_run; Stop = $StopLlama },
        [pscustomobject]@{ Name = "postgres"; Owned = [bool]$Ownership.postgres_started_by_this_run; Stop = $StopPostgres }
    )) {
        if (-not $action.Owned) { continue }
        try {
            & $action.Stop
        }
        catch {
            $errors.Add("$($action.Name): $($_.Exception.Message)")
        }
    }
    if ($errors.Count -gt 0) {
        throw "HAVRE rollback encountered errors after attempting every owned resource: $([string]::Join('; ', $errors))"
    }
}

function Assert-HavrePostgresIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedDataDirectory,
        [Parameter(Mandatory = $true)][string]$ReportedDataDirectory,
        [Parameter(Mandatory = $true)][string]$ServerVersionNum,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$PgvectorAvailableVersion
    )

    $expected = [IO.Path]::GetFullPath($ExpectedDataDirectory).TrimEnd(
        [IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar
    )
    $reported = [IO.Path]::GetFullPath($ReportedDataDirectory).TrimEnd(
        [IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar
    )
    if (-not $reported.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "PostgreSQL data_directory does not match the verified HAVRE cluster"
    }
    $version = 0
    if (-not [int]::TryParse($ServerVersionNum, [ref]$version) -or
        $version -lt 180000 -or $version -ge 190000) {
        throw "HAVRE local runtime requires PostgreSQL major version 18"
    }
    if ([string]::IsNullOrWhiteSpace($PgvectorAvailableVersion)) {
        throw "The verified PostgreSQL 18 instance does not provide pgvector"
    }
}

function Assert-HavreOwnedApiPidFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][bool]$StateOwnsApi,
        [Parameter(Mandatory = $true)][string]$PidPath
    )
    if ($StateOwnsApi -and -not (Test-Path -LiteralPath $PidPath -PathType Leaf)) {
        throw "HAVRE runtime state owns the API but its PID file is missing; refusing cleanup to avoid orphaning the API"
    }
}

Export-ModuleMember -Function Assert-HavreProcessIdentity,Invoke-HavreOwnedRollback,Assert-HavrePostgresIdentity,Assert-HavreOwnedApiPidFile
