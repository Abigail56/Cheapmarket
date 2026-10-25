#!/bin/sh
# Restores a dump made by scripts/backup.sh, REPLACING the current database contents.
#
#   docker compose run --rm --entrypoint sh backup /restore.sh /backups/<file>.dump
# or, with the Postgres client tools installed locally:
#   PGHOST=localhost POSTGRES_USER=... POSTGRES_PASSWORD=... POSTGRES_DB=... \
#     sh scripts/restore.sh backups/<file>.dump
#
# Set RESTORE_CONFIRM=yes to skip the prompt (e.g. in a scripted restore test).
set -eu

file="${1:?usage: restore.sh <backup.dump>}"
[ -f "$file" ] || { echo "No such file: $file" >&2; exit 1; }
export PGPASSWORD="$POSTGRES_PASSWORD"

if [ "${RESTORE_CONFIRM:-}" != "yes" ]; then
  printf 'This replaces ALL data in database "%s" on %s. Type the database name to continue: ' \
    "$POSTGRES_DB" "${PGHOST:-localhost}"
  read -r answer
  [ "$answer" = "$POSTGRES_DB" ] || { echo "Aborted."; exit 1; }
fi

# --single-transaction: if anything fails, the database is left exactly as it was
pg_restore --host="${PGHOST:-localhost}" --port="${PGPORT:-5432}" --username="$POSTGRES_USER" \
           --dbname="$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction "$file"
echo "Restored $file into $POSTGRES_DB"
