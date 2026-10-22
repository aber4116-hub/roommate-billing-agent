#!/bin/sh
# 恢复 custom-format 备份。会 DROP/重建目标库对象；必须显式确认。
# 用法：
#   CONFIRM_RESTORE=YES PG_RESTORE_URL='postgresql://user:pass@host:5432/db' ./scripts/restore_postgres.sh backups/roommate-....dump
set -eu

: "${PG_RESTORE_URL:?set PG_RESTORE_URL (libpq URL, not +psycopg)}"
file="${1:-}"
if [ -z "$file" ] || [ ! -f "$file" ]; then
  echo "usage: CONFIRM_RESTORE=YES PG_RESTORE_URL=... $0 <backup.dump>" >&2
  exit 2
fi
if [ "${CONFIRM_RESTORE:-}" != "YES" ]; then
  echo "refusing: set CONFIRM_RESTORE=YES and verify PG_RESTORE_URL" >&2
  exit 3
fi

# checksum 存在时先校验，避免恢复损坏文件。
if [ -f "$file.sha256" ]; then
  ( cd "$(dirname "$file")" && sha256sum --check "$(basename "$file").sha256" )
fi

pg_restore \
  --dbname="$PG_RESTORE_URL" \
  --clean \
  --if-exists \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  "$file"

echo "restored=$file"
