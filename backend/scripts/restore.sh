#!/usr/bin/env bash
# Khôi phục từ một bản sao lưu:  scripts/restore.sh ~/har-backups/har-20261114-030000.sql.gz
set -euo pipefail
[ $# -eq 1 ] || { echo "Dùng: $0 <file.sql.gz>"; exit 1; }
cd "$(dirname "$0")/.."
set -a; source .env; set +a
read -r -p "Ghi đè DB '$POSTGRES_DB' bằng $1? Gõ 'yes': " ok
[ "$ok" = "yes" ] || exit 1
gunzip -c "$1" | docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 >/dev/null
echo "Đã khôi phục."
