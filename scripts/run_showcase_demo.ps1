[CmdletBinding()]
param(
    [ValidatePattern('^havre_showcase_[a-z0-9_]+$')]
    [string]$DatabaseName = 'havre_showcase_demo',
    [string]$ExternalDatabaseUrl,
    [switch]$ServeWeb
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$ClusterRoot = Join-Path $ProjectRoot 'var\postgres'
$RuntimeRoot = Join-Path $ProjectRoot '.runtime\showcase'
$PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$UsingExternalDatabase = -not [string]::IsNullOrWhiteSpace($ExternalDatabaseUrl)
$DatabaseUrl = if ($UsingExternalDatabase) {
    $ExternalDatabaseUrl
} else {
    "postgresql://postgres@127.0.0.1:55432/$DatabaseName"
}
$OutputPath = Join-Path $ProjectRoot 'var\showcase\latest.json'
$PostgresStartedHere = $false

foreach ($path in @($PythonPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required verified HAVRE path is missing: $path"
    }
}

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
$PgCtl = $null
$PgIsReady = $null
$Psql = $null
$CreateDb = $null

if (-not $UsingExternalDatabase) {
    Import-Module (Join-Path $PSScriptRoot 'HavreLocalRuntime.psm1') -Force
    if (-not (Test-Path -LiteralPath $ClusterRoot)) {
        throw "Required verified HAVRE path is missing: $ClusterRoot"
    }
    $PgCtl = (Get-Command pg_ctl -ErrorAction Stop).Source
    $PgIsReady = (Get-Command pg_isready -ErrorAction Stop).Source
    $Psql = (Get-Command psql -ErrorAction Stop).Source
    $CreateDb = (Get-Command createdb -ErrorAction Stop).Source
}

function Assert-ShowcasePostgres {
    $identityRows = & $Psql -X -h 127.0.0.1 -p 55432 -U postgres -d postgres `
        -v ON_ERROR_STOP=1 -At -F '|' -c `
        "SELECT current_setting('data_directory'), current_setting('server_version_num'), COALESCE((SELECT default_version FROM pg_available_extensions WHERE name = 'vector'), '')"
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not verify the active PostgreSQL instance identity'
    }
    $identityLines = @($identityRows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
    if ($identityLines.Count -ne 1) {
        throw 'Active PostgreSQL identity query returned an unexpected result'
    }
    $identity = ([string]$identityLines[0]).Split('|')
    if ($identity.Count -ne 3) {
        throw 'Active PostgreSQL identity response is malformed'
    }
    Assert-HavrePostgresIdentity `
        -ExpectedDataDirectory $ClusterRoot `
        -ReportedDataDirectory $identity[0] `
        -ServerVersionNum $identity[1] `
        -PgvectorAvailableVersion $identity[2]
}

try {
    if (-not $UsingExternalDatabase) {
        & $PgIsReady -h 127.0.0.1 -p 55432 *> $null
        if ($LASTEXITCODE -ne 0) {
            $PostgresLog = Join-Path $RuntimeRoot 'postgres.log'
            & $PgCtl -D $ClusterRoot -l $PostgresLog -o '-h 127.0.0.1 -p 55432' start
            if ($LASTEXITCODE -ne 0) {
                throw 'PostgreSQL failed to start from the verified HAVRE cluster'
            }
            $PostgresStartedHere = $true
        }

        Assert-ShowcasePostgres
        $databaseExists = & $Psql -X -h 127.0.0.1 -p 55432 -U postgres -d postgres `
            -v ON_ERROR_STOP=1 -At -c "SELECT 1 FROM pg_database WHERE datname = '$DatabaseName'"
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not inspect the local PostgreSQL cluster'
        }
        if ($databaseExists -ne '1') {
            & $CreateDb -h 127.0.0.1 -p 55432 -U postgres $DatabaseName
            if ($LASTEXITCODE -ne 0) {
                throw 'Could not create the dedicated showcase database'
            }
        }
    }

    $env:HAVRE_PROVIDER_ID = 'deterministic-local'
    Remove-Item Env:HAVRE_RUNTIME_ADAPTER_VERSION -ErrorAction SilentlyContinue
    Remove-Item Env:HAVRE_RUNTIME_ADAPTER_HASH -ErrorAction SilentlyContinue
    $DemoOutput = & $PythonPath -m scripts.showcase_demo `
        --database-url $DatabaseUrl `
        --output $OutputPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Synthetic showcase flow failed'
    }
    if (-not $ServeWeb) {
        $DemoOutput | Write-Output
    }
    if ($ServeWeb) {
        $Demo = Get-Content -Raw -Encoding UTF8 -LiteralPath $OutputPath | ConvertFrom-Json
        $OwnerToken = [Convert]::ToHexString(
            [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
        ).ToLowerInvariant()
        $BootstrapToken = [Convert]::ToHexString(
            [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
        ).ToLowerInvariant()
        $env:HAVRE_DATABASE_URL = $DatabaseUrl
        $env:HAVRE_OWNER_ID = [string]$Demo.demo_id
        $env:HAVRE_OWNER_API_TOKEN = $OwnerToken
        $env:HAVRE_DESKTOP_BOOTSTRAP_TOKEN = $BootstrapToken
        $ShowcaseUrl = "http://127.0.0.1:8765/chat#desktop-bootstrap=$BootstrapToken"
        Write-Host ''
        Write-Host 'Synthetic Web showcase is starting on loopback.'
        Write-Host "Open: $ShowcaseUrl"
        Write-Host 'Press Ctrl+C here when the screenshot/demo is complete.'
        & $PythonPath -m services.api.cli serve --host 127.0.0.1 --port 8765
        if ($LASTEXITCODE -ne 0) {
            throw 'Synthetic showcase Web server stopped unexpectedly'
        }
    }
}
finally {
    if ($PostgresStartedHere) {
        & $PgCtl -D $ClusterRoot stop | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'The showcase run could not restore PostgreSQL to its prior stopped state'
        }
    }
}

Write-Host ''
Write-Host 'Showcase complete: deterministic provider, synthetic data only.'
Write-Host "Evidence: $OutputPath"
