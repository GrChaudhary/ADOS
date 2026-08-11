"""
P10 — proves scripts/backup_postgres.sh + scripts/restore_postgres.sh are a
real, working round trip, not aspirational scripts nobody has run.

P8 found: "No backup/restore tooling found for Postgres; compose uses a bare
named volume" and "Do not pretend a backup exists merely because Postgres is
durable" (docs/prime-agent-integration/18-production-readiness-review.md,
Operations table). This is the smallest thing this repository can actually
own and prove: a `pg_dump` taken through the real running Postgres
container, restored into an independent, disposable scratch database, and
independently re-queried — never assumed.

`docker`-marked because it shells out to the real `docker exec`/`pg_dump`/
`pg_restore` inside the actual compose-managed Postgres container by name —
container-name-dependent behaviour, same category as
test_orphan_sweep_docker.py's own real-Docker tests, deselected by default
alongside them.

    pytest -m docker backend/tests/test_backup_restore.py
"""
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER = "ados-postgres-1"
SOURCE_DB = "ados_test"
SCRATCH_DB = f"ados_restore_scratch_{uuid.uuid4().hex[:8]}"


def _docker_available() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(
        ["docker", "inspect", CONTAINER], capture_output=True
    ).returncode == 0


def _psql(db: str, sql: str) -> str:
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "ados", "-d", db, "-tA", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"psql failed: {result.stderr}"
    return result.stdout.strip()


@pytest.fixture(autouse=True)
def _require_docker():
    if not _docker_available():
        pytest.skip(f"docker or container '{CONTAINER}' not available")


@pytest.fixture
def scratch_database():
    """A disposable database, never the real dev/test database, so a
    `--clean` restore's destructive half never touches anything this test
    suite (or a developer) actually depends on."""
    _psql("ados", f'DROP DATABASE IF EXISTS "{SCRATCH_DB}"')
    _psql("ados", f'CREATE DATABASE "{SCRATCH_DB}"')
    yield SCRATCH_DB
    _psql("ados", f'DROP DATABASE IF EXISTS "{SCRATCH_DB}"')


def test_a_real_dump_restores_into_an_independent_database_with_matching_rows(
    scratch_database, tmp_path,
):
    marker = f"backup-restore-proof-{uuid.uuid4()}"
    _psql(
        SOURCE_DB,
        "INSERT INTO missions (mission_id, title, objective, domain, allowed_capabilities, "
        "status, created_by, created_at, updated_at) VALUES "
        f"(gen_random_uuid(), '{marker}', 'o', 'it', '[]'::json, 'running', 'test', now(), now())",
    )
    before_count = _psql(SOURCE_DB, f"SELECT count(*) FROM missions WHERE title = '{marker}'")
    assert before_count == "1"

    dump_dir = tmp_path / "backups"
    dump_dir.mkdir()
    backup = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "backup_postgres.sh"), SOURCE_DB],
        capture_output=True, text=True, timeout=60,
        env={"BACKUP_DIR": str(dump_dir), "POSTGRES_CONTAINER": CONTAINER, "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    assert backup.returncode == 0, f"backup script failed: {backup.stderr}\n{backup.stdout}"

    dumps = list(dump_dir.glob(f"{SOURCE_DB}-*.dump"))
    assert len(dumps) == 1, f"expected exactly one dump file, found {dumps}"
    dump_file = dumps[0]
    assert dump_file.stat().st_size > 0

    restore = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "restore_postgres.sh"), str(dump_file), scratch_database],
        capture_output=True, text=True, timeout=60,
        env={"POSTGRES_CONTAINER": CONTAINER, "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    assert restore.returncode == 0, f"restore script failed: {restore.stderr}\n{restore.stdout}"

    # Independently re-queried against the SCRATCH database — not the
    # source — proving the dump file itself, not merely the source
    # database, carries the real row.
    restored_count = _psql(scratch_database, f"SELECT count(*) FROM missions WHERE title = '{marker}'")
    assert restored_count == "1", "the marker row did not survive the dump/restore round trip"

    restored_status = _psql(scratch_database, f"SELECT status FROM missions WHERE title = '{marker}'")
    assert restored_status == "running"

    tables = _psql(
        scratch_database,
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'",
    )
    source_tables = _psql(
        SOURCE_DB,
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'",
    )
    assert tables == source_tables, "restored schema does not have the same table count as the source"

    _psql(SOURCE_DB, f"DELETE FROM missions WHERE title = '{marker}'")


def test_restore_replaces_prior_content_rather_than_merging_with_it(scratch_database, tmp_path):
    """`--clean --if-exists` must really replace what was there, not
    additively merge — the real scenario this protects against is
    restoring a fresh backup onto a recovery instance that already holds an
    older restore's rows. Proven by restoring two different dumps in
    sequence into the SAME scratch database and confirming only the second
    dump's marker row survives."""
    dump_dir = tmp_path / "backups"
    dump_dir.mkdir()
    env = {"BACKUP_DIR": str(dump_dir), "POSTGRES_CONTAINER": CONTAINER, "PATH": "/usr/bin:/bin:/usr/local/bin"}

    marker_a = f"restore-replace-a-{uuid.uuid4()}"
    _psql(
        SOURCE_DB,
        "INSERT INTO missions (mission_id, title, objective, domain, allowed_capabilities, "
        "status, created_by, created_at, updated_at) VALUES "
        f"(gen_random_uuid(), '{marker_a}', 'o', 'it', '[]'::json, 'running', 'test', now(), now())",
    )
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "backup_postgres.sh"), SOURCE_DB],
        capture_output=True, text=True, timeout=60, check=True, env=env,
    )
    dump_a = max(dump_dir.glob(f"{SOURCE_DB}-*.dump"), key=lambda p: p.stat().st_mtime)
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "restore_postgres.sh"), str(dump_a), scratch_database],
        capture_output=True, text=True, timeout=60, check=True,
        env={"POSTGRES_CONTAINER": CONTAINER, "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    assert _psql(scratch_database, f"SELECT count(*) FROM missions WHERE title = '{marker_a}'") == "1"

    _psql(SOURCE_DB, f"DELETE FROM missions WHERE title = '{marker_a}'")
    marker_b = f"restore-replace-b-{uuid.uuid4()}"
    _psql(
        SOURCE_DB,
        "INSERT INTO missions (mission_id, title, objective, domain, allowed_capabilities, "
        "status, created_by, created_at, updated_at) VALUES "
        f"(gen_random_uuid(), '{marker_b}', 'o', 'it', '[]'::json, 'running', 'test', now(), now())",
    )
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "backup_postgres.sh"), SOURCE_DB],
        capture_output=True, text=True, timeout=60, check=True, env=env,
    )
    dump_b = max(dump_dir.glob(f"{SOURCE_DB}-*.dump"), key=lambda p: p.stat().st_mtime)
    assert dump_b != dump_a
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "restore_postgres.sh"), str(dump_b), scratch_database],
        capture_output=True, text=True, timeout=60, check=True,
        env={"POSTGRES_CONTAINER": CONTAINER, "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )

    assert _psql(scratch_database, f"SELECT count(*) FROM missions WHERE title = '{marker_a}'") == "0", (
        "the first restore's row survived a second restore -- --clean is not actually replacing prior content"
    )
    assert _psql(scratch_database, f"SELECT count(*) FROM missions WHERE title = '{marker_b}'") == "1"

    _psql(SOURCE_DB, f"DELETE FROM missions WHERE title = '{marker_b}'")


def test_restore_refuses_without_an_explicit_target_database():
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "restore_postgres.sh"), "some-dump-file.dump"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert "target-db" in result.stderr
