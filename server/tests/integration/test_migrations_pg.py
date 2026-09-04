"""Alembic migrations against a real Postgres database.

The fast suite never runs a migration at all -- every SQLite fixture builds
its schema straight from `Base.metadata.create_all()`, which proves the ORM
models are internally consistent but proves nothing about the actual
`alembic/versions/*.py` scripts deploy day runs. This file is the only
place in the project that invokes `alembic upgrade head` for real, against
a real Postgres database, from a genuinely empty schema.

Each migration is run as a subprocess (the installed `alembic` console
script, in `server/`, with `DATABASE_URL` overridden in that subprocess's
environment only) rather than in-process via `alembic.command`. That is
deliberate: `alembic/env.py` resolves its target database from
`get_settings().database_url`, and `xxvi.settings.get_settings` is
`@lru_cache`d at module scope -- calling it in-process risks either
poisoning that cache for the rest of the pytest session or, worse, racing
which URL wins if something else in the process already called it first.
Every invocation here is a brand new Python process with `DATABASE_URL` set
explicitly for that process alone, so there is no cache to poison and no
way for this file to accidentally point anything at the URL `.env` actually
contains (this project's real, non-test database).

Only two tests here do a full drop-schema/upgrade-head cycle (not one per
assertion) -- each cycle is a real round trip to Neon for a `DROP SCHEMA`,
three migrations, and a compute wake-up, measured around 25-30s. Bundling
every from-empty assertion (tables, unique constraints, the code_releases
column allowlist) into one cycle instead of three keeps this file
runnable; splitting it further would not add coverage, only wall-clock.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.pg

PG_TEST_URL = os.environ.get("PG_TEST_URL")
SERVER_DIR = Path(__file__).resolve().parents[2]  # .../server
ALEMBIC_BIN = str(Path(sys.executable).parent / "alembic")

EXPECTED_TABLES = {
    "accounts",
    "runs",
    "run_events",
    "trophies_earned",
    "gate_attempts",
    "code_releases",
    "consumed_tokens",
    "alembic_version",
}

EXPECTED_UNIQUE_CONSTRAINT_COLUMN_SETS = {
    "accounts": frozenset({"username"}),
    "runs": frozenset({"account_id"}),
    "trophies_earned": frozenset({"run_id", "trophy_id"}),
    "gate_attempts": frozenset({"run_id", "gate_id"}),
    "code_releases": frozenset({"run_id", "reward_id"}),
    "consumed_tokens": frozenset({"run_id", "nonce"}),
}

# `CodeRelease` exists to record THAT a reward was released, never its
# value (see the class docstring in xxvi/persistence/models.py). This is
# the complete, exhaustive set of columns it is ever allowed to have --
# nothing here may be capable of holding a code value.
CODE_RELEASES_ALLOWED_COLUMNS = {"id", "run_id", "reward_id", "released_at"}


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": PG_TEST_URL}
    return subprocess.run(
        [ALEMBIC_BIN, *args],
        cwd=SERVER_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


async def _with_inspector(fn):
    """Run `fn(sync_inspector)` against one short-lived connection. Callers
    pass a plain sync function so the whole introspection for a test can
    share a single connection/round-trip instead of opening a fresh one
    (NullPool -- see conftest.py) per question asked of the database.
    """
    engine = create_async_engine(PG_TEST_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(lambda sc: fn(inspect(sc)))
    finally:
        await engine.dispose()


async def _reset_schema_to_nothing() -> None:
    """A real empty database -- including `alembic_version` -- not just
    "no app tables". `alembic upgrade head` from this exact state is what
    deploy day runs against a brand new branch.
    """

    def _reset(sync_conn):
        sync_conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        sync_conn.exec_driver_sql("CREATE SCHEMA public")

    engine = create_async_engine(PG_TEST_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_reset)
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _migrated_schema():
    """Setup: reset to a genuinely empty database, then `upgrade head` --
    this is the "from empty reaches head" proof itself.

    Teardown: unconditionally `upgrade head` again (idempotent once
    already there). The round-trip test below tears the schema all the way
    down as part of its own body; every other file in this suite assumes
    the schema already exists and doesn't manage it itself, so this file
    must never hand back control with the schema in anything other than
    the head state -- including when an assertion in the test body fails.
    """
    if not PG_TEST_URL:
        pytest.skip("PG_TEST_URL not set")
    await _reset_schema_to_nothing()
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr}"
    try:
        yield
    finally:
        result = _run_alembic("upgrade", "head")
        assert result.returncode == 0, f"alembic upgrade head (teardown) failed:\n{result.stderr}"


async def test_upgrade_head_from_empty_creates_the_expected_schema():
    def _introspect(insp):
        tables = set(insp.get_table_names())
        unique_sets = {
            table: {frozenset(c["column_names"]) for c in insp.get_unique_constraints(table)}
            for table in EXPECTED_UNIQUE_CONSTRAINT_COLUMN_SETS
        }
        code_release_columns = {c["name"] for c in insp.get_columns("code_releases")}
        return tables, unique_sets, code_release_columns

    tables, unique_sets, code_release_columns = await _with_inspector(_introspect)

    assert EXPECTED_TABLES <= tables, f"missing tables: {EXPECTED_TABLES - tables}"

    for table, expected in EXPECTED_UNIQUE_CONSTRAINT_COLUMN_SETS.items():
        assert expected in unique_sets[table], (
            f"{table}: expected a UNIQUE constraint on {sorted(expected)}, "
            f"found {[sorted(s) for s in unique_sets[table]]}"
        )

    assert code_release_columns == CODE_RELEASES_ALLOWED_COLUMNS, (
        f"code_releases grew an unexpected column: "
        f"{code_release_columns - CODE_RELEASES_ALLOWED_COLUMNS}"
    )


async def test_downgrade_then_upgrade_round_trips():
    down = _run_alembic("downgrade", "base")
    assert down.returncode == 0, f"alembic downgrade base failed:\n{down.stderr}"

    tables_after_downgrade = await _with_inspector(lambda insp: set(insp.get_table_names()))
    assert "runs" not in tables_after_downgrade
    assert "code_releases" not in tables_after_downgrade
    assert "consumed_tokens" not in tables_after_downgrade

    up = _run_alembic("upgrade", "head")
    assert up.returncode == 0, f"alembic upgrade head failed:\n{up.stderr}"

    tables_after_upgrade = await _with_inspector(lambda insp: set(insp.get_table_names()))
    assert EXPECTED_TABLES <= tables_after_upgrade
