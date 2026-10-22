param(
    [string]$DatabaseUrl = $env:PG_DATABASE_URL,
    [string]$BackupDir = "./backups",
    [int]$RetentionDays = 14,
    [string]$PgDump = "pg_dump"
)

$ErrorActionPreference = "Stop"
if (-not $DatabaseUrl) { throw "set PG_DATABASE_URL (libpq URL, not +psycopg)" }
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$file = Join-Path $BackupDir "roommate-$stamp.dump"

& $PgDump --dbname="$DatabaseUrl" --format=custom --compress=9 --no-owner --no-privileges --file="$file"
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed: $LASTEXITCODE" }

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLower()
"$hash  $(Split-Path -Leaf $file)" | Set-Content -LiteralPath "$file.sha256" -Encoding ascii

$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem -LiteralPath $BackupDir -Filter "roommate-*.dump*" -File |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    Remove-Item -Force

Write-Output "backup=$file"
Write-Output "sha256=$hash"
