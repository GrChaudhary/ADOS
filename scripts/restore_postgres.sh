#!/usr/bin/env bash
# P10 — restores a dump produced by backup_postgres.sh, through the same
# running Postgres container's own `pg_restore`.
#
# The target database is a REQUIRED, explicit argument -- deliberately no
# default, and deliberately not inferred from the dump's own filename. A
# restore is a genuinely destructive operation (`--clean` drops existing
# objects in the target before recreating them); the cost of typing the
# target database's name is small next to the cost of a script guessing
# wrong and quietly overwriting the live database because that happened to
# be the default.
#
# Usage:
#   scripts/restore_postgres.sh <dump-file> <target-db>
#   POSTGRES_CONTAINER=my-postgres-1 scripts/restore_postgres.sh backups/ados-....dump ados_restore_test
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: restore_postgres.sh <dump-file> <target-db>" >&2
  echo "  target-db must be named explicitly -- this will not guess or default to the live database" >&2
  exit 2
fi

DUMP_FILE="$1"
TARGET_DB="$2"
CONTAINER="${POSTGRES_CONTAINER:-ados-postgres-1}"

if [[ ! -f "$DUMP_FILE" ]]; then
  echo "no such dump file: $DUMP_FILE" >&2
  exit 1
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "no such container: $CONTAINER (set POSTGRES_CONTAINER to override)" >&2
  exit 1
fi

echo "restoring $DUMP_FILE into database '$TARGET_DB' (container '$CONTAINER')"
echo "  --clean --if-exists: existing objects in '$TARGET_DB' will be dropped and recreated"
docker exec -i "$CONTAINER" pg_restore -U ados -d "$TARGET_DB" --clean --if-exists --no-owner < "$DUMP_FILE"
echo "restore complete"
