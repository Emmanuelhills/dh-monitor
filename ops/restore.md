# Restoring a backup

Restores replace the current data. Test restores regularly against a scratch database
(spec §10/§12: "backup and restoration procedures must be established").

## Local Windows install

```powershell
# 1. Stop the API, worker and scheduler.
# 2. Restore into a fresh database (here: dhm_restore) to verify, or into dhm to recover.
$pg = "C:\Program Files\PostgreSQL\17\bin"
& "$pg\createdb.exe" -U postgres -h localhost -O dhm dhm_restore
& "$pg\pg_restore.exe" -U postgres -h localhost --no-owner --role=dhm -d dhm_restore .\backups\dhm-YYYYMMDD-HHMMSS.dump
# 3. Point DHM_DATABASE_URL at the restored database (or restore into `dhm` after dropping it),
#    run `alembic upgrade head`, then start the services again.
```

## docker compose

```sh
docker compose stop api worker scheduler
docker compose exec -T db dropdb -U dhm --if-exists dhm_restore
docker compose exec -T db createdb -U dhm dhm_restore
docker compose exec -T db pg_restore -U dhm --no-owner -d dhm_restore < backups/dhm-YYYYMMDD-HHMMSS.dump
# verify, then swap databases or restore into `dhm` the same way
docker compose start api worker scheduler
```

The encryption key (`DHM_ENCRYPTION_KEY`) is **not** in the database backup. Keep it in your
secret manager; without it, stored SES / integration credentials cannot be decrypted (re-enter them).
