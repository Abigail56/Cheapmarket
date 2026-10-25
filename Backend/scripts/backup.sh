#!/bin/sh
# Dumps the database to $BACKUP_DIR/<db>_<UTC timestamp>.dump (pg_dump custom format,
# compressed) and deletes dumps older than $BACKUP_KEEP_DAYS.
#
# Uses the standard Postgres env vars: PGHOST, PGPORT, POSTGRES_USER, POSTGRES_PASSWORD,
# POSTGRES_DB. The docker-compose `backup` service runs this once a day.
# Restore with scripts/restore.sh.
set -eu

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
export PGPASSWORD="$POSTGRES_PASSWORD"
mkdir -p "$BACKUP_DIR"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
file="$BACKUP_DIR/${POSTGRES_DB}_${stamp}.dump"

# write to a temp name first so a half-finished dump is never mistaken for a good one
pg_dump --host="${PGHOST:-localhost}" --port="${PGPORT:-5432}" --username="$POSTGRES_USER" \
        --format=custom --no-owner --file="$file.partial" "$POSTGRES_DB"
mv "$file.partial" "$file"
echo "$(date -u +%FT%TZ) backup ok: $file ($(du -h "$file" | cut -f1))"

find "$BACKUP_DIR" -name "${POSTGRES_DB}_*.dump" -type f -mtime +"$KEEP_DAYS" -print -delete \
  | sed 's/^/deleted old backup: /'
