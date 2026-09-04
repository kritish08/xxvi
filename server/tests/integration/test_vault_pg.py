"""Vault behaviour under real Postgres MVCC.

The fast suite (tests/test_vault.py) already covers every branch of
`VaultService` against a file-backed, `NullPool` SQLite database, including
the exactly-one-winner race. This file exists only for what that cannot
prove: that the same guarantee holds under a real MVCC engine handling
genuinely concurrent connections, on the money path -- the one place in
this codebase where a wrong concurrency conclusion has a real dollar cost.
"""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from xxvi.core.models import Difficulty
from xxvi.persistence.models import CodeRelease
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings
from xxvi.vault.service import AlreadyReleased, VaultService

pytestmark = pytest.mark.pg

SECRET = "REAL-CODE-DO-NOT-LEAK"


@pytest.fixture
def settings():
    return Settings(reward_1_code=SECRET, reward_2_code="SECOND-CODE")


@pytest.fixture
async def run(sessionmaker, account):
    return await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)


@pytest.fixture
def vault(sessionmaker, settings):
    return VaultService(sessionmaker, settings)


async def test_16_way_concurrent_release_emits_exactly_one_code_and_one_row(
    sessionmaker, vault, run
):
    # 16, not 8: the SQLite-fixture version of this test (test_vault.py)
    # uses 8 and that number was chosen for that fixture's purposes. Real
    # Postgres handling 16 genuinely independent connections is exactly
    # the scenario a shared/pooled connection cannot model.
    results = await asyncio.gather(
        *(vault.release(run.id, 1, approved_by_operator=True) for _ in range(16)),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, str)]
    conflicts = [r for r in results if isinstance(r, AlreadyReleased)]
    unexpected = [
        r for r in results if isinstance(r, BaseException) and not isinstance(r, AlreadyReleased)
    ]

    assert unexpected == [], f"unexpected exceptions: {unexpected!r}"
    assert len(successes) == 1
    assert successes[0] == SECRET
    assert len(conflicts) == 15

    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(CodeRelease).where(CodeRelease.run_id == run.id, CodeRelease.reward_id == 1)
            )
        ).scalars().all()
    assert len(rows) == 1, (
        "exactly the false-confidence failure this suite exists to catch: "
        "the gather() result can look like 1 success / N conflicts while "
        "the winning row is not actually there."
    )


async def test_second_release_for_same_run_and_reward_is_refused(vault, run):
    await vault.release(run.id, 1, approved_by_operator=True)
    with pytest.raises(AlreadyReleased):
        await vault.release(run.id, 1, approved_by_operator=True)


async def test_nonexistent_run_id_surfaces_the_foreign_key_error(vault):
    # run_id 999999 does not exist. This must raise a real IntegrityError
    # (a foreign-key violation), not be misread as AlreadyReleased -- that
    # misread would mean silently skipping a gift card and telling nobody.
    # SQLite only enforces this distinction when a connection has explicitly
    # turned FKs on (PRAGMA foreign_keys=ON); Postgres enforces it by
    # default, unconditionally, which is exactly the asymmetry worth
    # proving against the real engine.
    with pytest.raises(IntegrityError):
        await vault.release(999999, 1, approved_by_operator=True)
