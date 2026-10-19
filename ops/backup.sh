#!/usr/bin/env sh
# Back up the PostgreSQL database from the docker-compose deployment.
#   ./ops/backup.sh            -> ./backups/dhm-YYYYmmdd-HHMMSS.dump  (keeps 14 days)
set -eu
OUT_DIR="${OUT_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p "$OUT_DIR"
FILE="$OUT_DIR/dhm-$(date +%Y%m%d-%H%M%S).dump"
docker compose exec -T db pg_dump -U dhm --format=custom --no-owner dhm > "$FILE"
docker compose exec -T db pg_restore --list < "$FILE" > /dev/null
find "$OUT_DIR" -name 'dhm-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "Backup written and verified: $FILE"
