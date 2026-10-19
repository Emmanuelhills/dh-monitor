<#
.SYNOPSIS
  Prepare a hosted PostgreSQL database (e.g. Neon on Vercel) for Domain & Hosting Monitor.

.DESCRIPTION
  1. Applies all migrations to the target database.
  2. With -CopyLocalData: copies your local data (domains, hosting plans, registrars, users,
     settings, history) into it. The target must be empty (freshly migrated).

.EXAMPLE
  .\ops\deploy-db.ps1 -TargetUrl "postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require" -CopyLocalData
#>
param(
  [Parameter(Mandatory = $true)][string]$TargetUrl,
  [switch]$CopyLocalData,
  [string]$EnvFile = "$PSScriptRoot\..\backend\.env",
  [string]$PgBin = "C:\Program Files\PostgreSQL\17\bin"
)
# Native tools log to stderr; failures are detected through exit codes below.
$ErrorActionPreference = "Continue"
$backend = Resolve-Path "$PSScriptRoot\..\backend"

function To-LibpqUrl([string]$url) { $url -replace '^postgresql\+psycopg://', 'postgresql://' -replace '^postgres://', 'postgresql://' }
$target = To-LibpqUrl $TargetUrl

Write-Output "1/2 Applying migrations to the target database..."
Push-Location $backend
try {
  $env:DHM_DATABASE_URL = $target
  & .\.venv\Scripts\alembic.exe upgrade head
  if ($LASTEXITCODE -ne 0) { throw "Migration failed." }
} finally {
  Remove-Item Env:\DHM_DATABASE_URL -ErrorAction SilentlyContinue
  Pop-Location
}

if (-not $CopyLocalData) { Write-Output "Done (schema only)."; exit 0 }

Write-Output "2/2 Copying local data..."
$line = Get-Content $EnvFile | Where-Object { $_ -match '^DHM_DATABASE_URL=' } | Select-Object -First 1
if (-not $line) { throw "DHM_DATABASE_URL not found in $EnvFile" }
$source = To-LibpqUrl ($line -replace '^DHM_DATABASE_URL=', '')

$count = & "$PgBin\psql.exe" $target -tAc "select (select count(*) from domains) + (select count(*) from hosting_accounts) + (select count(*) from users)"
if ([int]$count -gt 0) { throw "The target database already contains data; refusing to copy over it." }

$dump = Join-Path $env:TEMP "dhm-data-$(Get-Date -Format yyyyMMddHHmmss).sql"
# Data only, in dependency order. Sessions and broker tables are not copied.
& "$PgBin\pg_dump.exe" --data-only --no-owner --no-privileges `
  --exclude-table=alembic_version --exclude-table=user_sessions --exclude-table='kombu_*' `
  --exclude-table=message_id_sequence --exclude-table=queue_id_sequence `
  --file=$dump $source
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed." }
try {
  & "$PgBin\psql.exe" $target -v ON_ERROR_STOP=1 --single-transaction --quiet -f $dump | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Copy failed; nothing was changed in the target (single transaction)." }
} finally {
  Remove-Item $dump -ErrorAction SilentlyContinue
}
$summary = & "$PgBin\psql.exe" $target -tAc "select format('%s domains, %s hosting plans, %s registrars, %s users', (select count(*) from domains), (select count(*) from hosting_accounts), (select count(*) from registrars), (select count(*) from users))"
Write-Output "Copied: $summary"
Write-Output "Use the SAME DHM_ENCRYPTION_KEY on Vercel as in backend\.env so stored secrets stay readable."
