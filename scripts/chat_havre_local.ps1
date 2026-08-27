[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "HAVRE virtual environment is missing: $PythonPath"
}

$env:HAVRE_DATABASE_URL = "postgresql://postgres@127.0.0.1:55432/havre"
$env:HAVRE_PROVIDER_ID = "self-hosted-openai-compatible"
$env:HAVRE_SELF_HOSTED_BASE_URL = "http://127.0.0.1:8080"

Push-Location $ProjectRoot
try {
    & $PythonPath -m services.api.cli chat
    if ($LASTEXITCODE -ne 0) {
        throw "HAVRE local chat exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
