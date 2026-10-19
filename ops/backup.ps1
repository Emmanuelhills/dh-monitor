<#
.SYNOPSIS
  Back up the Domain & Hosting Monitor PostgreSQL database (custom format, compressed).
.EXAMPLE
  .\ops\backup.ps1                       # uses backend\.env, writes to .\backups
  .\ops\backup.ps1 -KeepDays 30
  Schedule daily with Task Scheduler:  powershell -File C:\path\ops\backup.ps1
#>
param(
  [string]$EnvFile = "$PSScriptRoot\..\backend\.env",
  [string]$OutDir = "$PSScriptRoot\..\backups",
  [int]$KeepDays = 14,
  [string]$PgBin = "C:\Program Files\PostgreSQL\17\bin"
)
$ErrorActionPreference = "Stop"
$line = Get-Content $EnvFile | Where-Object { $_ -match '^DHM_DATABASE_URL=' } | Select-Object -First 1
if (-not $line) { throw "DHM_DATABASE_URL not found in $EnvFile" }
$url = $line -replace '^DHM_DATABASE_URL=', '' -replace '^postgresql\+psycopg://', 'postgresql://'
New-Item -ItemType Directory -Force $OutDir | Out-Null
$file = Join-Path $OutDir ("dhm-{0:yyyyMMdd-HHmmss}.dump" -f (Get-Date))
& "$PgBin\pg_dump.exe" --format=custom --no-owner --dbname=$url --file=$file
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed ($LASTEXITCODE)" }
# Verify the archive is readable before pruning old ones.
& "$PgBin\pg_restore.exe" --list $file | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Backup verification failed for $file" }
Get-ChildItem $OutDir -Filter "dhm-*.dump" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } | Remove-Item
Write-Output "Backup written and verified: $file"
