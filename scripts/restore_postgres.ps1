param(
    [Parameter(Mandatory = $true)][string]$File,
    [string]$RestoreUrl = $env:PG_RESTORE_URL,
    [string]$PgRestore = "pg_restore",
    [switch]$ConfirmRestore
)

$ErrorActionPreference = "Stop"
if (-not $RestoreUrl) { throw "set PG_RESTORE_URL (libpq URL, not +psycopg)" }
if (-not $ConfirmRestore) { throw "refusing: pass -ConfirmRestore after verifying the target database" }
if (-not (Test-Path -LiteralPath $File)) { throw "backup not found: $File" }

$checksum = "$File.sha256"
if (Test-Path -LiteralPath $checksum) {
    $expected = ((Get-Content -LiteralPath $checksum -Raw).Trim() -split "\s+")[0].ToLower()
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $File).Hash.ToLower()
    if ($expected -ne $actual) { throw "checksum mismatch" }
}

& $PgRestore --dbname="$RestoreUrl" --clean --if-exists --exit-on-error --no-owner --no-privileges "$File"
if ($LASTEXITCODE -ne 0) { throw "pg_restore failed: $LASTEXITCODE" }
Write-Output "restored=$File"
