#!/usr/bin/env bash
# P10 — the smallest production-appropriate backup mechanism this repository
# can actually own: a `pg_dump` taken through the already-running Postgres
# container's own bundled tools (no new dependency to install, no invented
# infrastructure -- see this phase's own production-readiness doc for why
# that distinction matters). Custom format (-Fc): compressed, and restorable
# selectively via pg_restore, not just as one monolithic SQL replay.
#
# What this does NOT cover, and does not pretend to: point-in-time recovery
# (WAL archiving), off-host/offsite storage, retention policy, or a restore
# schedule/rehearsal cadence -- those are operational decisions for whoever
# actually runs this in production, out of scope for a repository-owned
# script. See restore_postgres.sh's own round-trip test
# (backend/tests/test_backup_restore.py, `docker`-marked) for what IS
# proven: a dump taken this way restores byte-for-byte-equivalent rows.
#
# Usage:
#   scripts/backup_postgres.sh [db-name]
#   POSTGRES_CONTAINER=my-postgres-1 scripts/backup_postgres.sh ados
set -euo pipefail

CONTAINER="${POSTGRES_CONTAINER:-ados-postgres-1}"
DB="${1:-ados}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${BACKUP_DIR:-$REPO_ROOT/backups}"
mkdir -p "$OUT_DIR"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "no such container: $CONTAINER (set POSTGRES_CONTAINER to override)" >&2
  exit 1
fi

# $RANDOM (a bash builtin, not GNU date's %N -- unavailable on BSD/macOS
# date) guards against two backups landing in the same wall-clock second
# and one silently overwriting the other's file.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
OUT_FILE="$OUT_DIR/${DB}-${STAMP}.dump"

echo "backing up database '$DB' from container '$CONTAINER' -> $OUT_FILE"
docker exec "$CONTAINER" pg_dump -U ados -Fc -d "$DB" > "$OUT_FILE"
echo "done: $(du -h "$OUT_FILE" | cut -f1)  $OUT_FILE"
