<#
.SYNOPSIS
  Start the full development stack on Windows in separate windows:
  API (8000), Celery worker, Celery beat scheduler, Next.js frontend (3000).
#>
$root = Split-Path $PSScriptRoot -Parent
$be = Join-Path $root "backend"
$fe = Join-Path $root "frontend"
Start-Process powershell -WorkingDirectory $be -ArgumentList "-NoExit", "-Command", ".\.venv\Scripts\python -m alembic upgrade head; .\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -WorkingDirectory $be -ArgumentList "-NoExit", "-Command", ".\.venv\Scripts\celery -A app.celery_app worker --loglevel=INFO --pool=solo"
Start-Process powershell -WorkingDirectory $be -ArgumentList "-NoExit", "-Command", ".\.venv\Scripts\celery -A app.celery_app beat --loglevel=INFO --schedule `"$env:TEMP\dhm-celerybeat-schedule`""
Start-Process powershell -WorkingDirectory $fe -ArgumentList "-NoExit", "-Command", "npm run dev"
Write-Output "Starting... open http://localhost:3000"
