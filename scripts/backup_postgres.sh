#!/bin/sh
# 逻辑备份（custom format），带 SHA-256 和保留期清理。
# 用法：
#   PG_DATABASE_URL='postgresql://user:pass@host:5432/db' BACKUP_DIR=/backups ./scripts/backup_postgres.sh
set -eu

: "${PG_DATABASE_URL:?set PG_DATABASE_URL (libpq URL, not +psycopg)}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
umask 077
mkdir -p "$BACKUP_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
file="$BACKUP_DIR/roommate-$stamp.dump"

pg_dump \
  --dbname="$PG_DATABASE_URL" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-privileges \
  --file="$file"

( cd "$BACKUP_DIR" && sha256sum "$(basename "$file")" > "$(basename "$file").sha256" )

# 只删除本脚本生成且超过保留期的 dump / checksum。
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'roommate-*.dump' -mtime "+$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'roommate-*.dump.sha256' -mtime "+$RETENTION_DAYS" -delete

echo "backup=$file"
echo "sha256=$(cat "$file.sha256")"
