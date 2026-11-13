#!/usr/bin/env bash
# Sao lưu PostgreSQL hằng ngày, giữ 7 bản. Cài cron trên VPS:
#   0 3 * * * /home/har/har/backend/scripts/backup.sh >> /home/har/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
DIR="${BACKUP_DIR:-$HOME/har-backups}"
mkdir -p "$DIR"
FILE="$DIR/har-$(date +%Y%m%d-%H%M%S).sql.gz"
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists | gzip > "$FILE"
echo "$(date -Is) backup -> $FILE ($(du -h "$FILE" | cut -f1))"
ls -1t "$DIR"/har-*.sql.gz | tail -n +8 | xargs -r rm --
