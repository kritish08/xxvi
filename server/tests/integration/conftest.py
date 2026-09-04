"""Fixtures shared by the Postgres integration suite (tests/integration/).

See tests/integration/README.md for what this suite covers and why it is
separate from the fast SQLite suite.

Everything here targets `PG_TEST_URL` -- a real Postgres database, never the
in-memory SQLite the rest of the project uses. That is the entire point of
this suite: SQLite's `StaticPool` fixture (used everywhere else in
tests/conftest.py) secretly serializes every session in a test through one
shared connection, which makes any conclusion drawn from it about
*concurrent* access unsound. A prior reviewer proved this the hard way: an
8-way race against that fixture reported the correct-looking "1 success, 7
conflicts" and then the winning row was gone -- no row in the database at
all. A test written against a fixture that can do that is worse than no
test, because it looks like coverage.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from xxvi.persistence.models import Base

PG_TEST_URL = os.environ.get("PG_TEST_URL")

# FK-safe delete order: every one of these references `runs`, so `runs`
# itself must be deleted after all of them; `runs` references `accounts`,
# so `accounts` goes last of all.
_CLEANUP_TABLES_FK_SAFE_ORDER = (
    "run_events",
    "trophies_earned",
    "consumed_tokens",
    "code_releases",
    "gate_attempts",
    "runs",
    "accounts",
)


def pytest_collection_modifyitems(config, items):
    """Skip the entire `pg`-marked suite, cleanly, when `PG_TEST_URL` is
    unset -- so the default `pytest` run (no env var) never opens a socket.

    This runs at collection time, before any fixture executes. A test that
    gets skipped here never reaches the `sessionmaker` fixture below, so no
    engine is ever constructed and nothing touches the network. This is the
    only gate that matters for "the default run must not touch the
    network" -- the `pytest.skip()` inside the fixture (below) is a
    defensive second layer in case a test somehow reaches it without the
    `pg` marker, not the primary mechanism.
    """
    if PG_TEST_URL:
        return
    skip_pg = pytest.mark.skip(
        reason=(
            "PG_TEST_URL not set; Postgres integration suite skipped "
            "(see tests/integration/README.md to run it)"
        )
    )
    for item in items:
        if item.get_closest_marker("pg"):
            item.add_marker(skip_pg)


async def _clean_all_tables(engine) -> None:
    """Blanket-delete every row in every app table, FK-safe order. Not
    scoped to what a given test created -- deliberately, so a prior test
    that crashed mid-test (leaving orphan rows) can't poison the ones after
    it, and so the branch is provably empty, not just "empty of what this
    test thinks it added", when the suite finishes.
    """
    async with engine.begin() as conn:
        for table in _CLEANUP_TABLES_FK_SAFE_ORDER:
            await conn.execute(text(f'DELETE FROM "{table}"'))


@pytest.fixture
async def sessionmaker():
    """Overrides the shared SQLite fixture of the same name from
    tests/conftest.py for every test collected under tests/integration/
    (pytest resolves fixtures per module; the closest definition wins --
    see tests/test_vault.py for the fuller writeup of this exact
    mechanism). So `account`/`account2`, defined in the root conftest and
    unaware of any of this, transparently get this Postgres engine instead
    of the in-memory one.

    `NullPool` is the task's hard requirement, not a style choice: every
    `sessionmaker()` call below opens a genuinely separate physical
    connection to Postgres -- the same shape independent request handlers
    get in production. A pooled or shared connection cannot model a race.

    Schema is ensured (not assumed) at the top of every test via
    `create_all(checkfirst=True)` -- cheap when the tables already exist,
    and it means this fixture does not depend on test_migrations_pg.py
    having run first (that file manages its own schema state independently,
    including a deliberate downgrade-to-nothing/upgrade-to-head round trip;
    without this, tests here would break depending on file execution
    order).
    """
    if not PG_TEST_URL:
        pytest.skip("PG_TEST_URL not set")
    engine = create_async_engine(PG_TEST_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await _clean_all_tables(engine)
    await engine.dispose()
