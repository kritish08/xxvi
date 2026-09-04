"""Hidden trophies are award-at-most-once under real concurrency.

`check_hidden` decides "should this pop" from a count/existence read
(`count_events`/`has_event`) but the actual award always goes through
`RunRepository.award_trophy` -- an insert-first-catch-the-unique-violation
primitive, not a second SELECT. This file is the concurrency regression
test for that: several simultaneous callers all deciding "yes, award it"
at once must still produce exactly one TrophyEarned row and exactly one
caller walking away with the pop in its own return value.

Uses a file-backed SQLite database with NullPool, not the shared in-memory
`sessionmaker` fixture from conftest.py -- see
tests/test_run_service_concurrency.py's identical fixture and its
docstring (mirroring tests/test_games_concurrency.py) for why: the shared
fixture's StaticPool secretly serializes every "concurrent" call through
one underlying connection, which would make this test report the
correct-looking outcome while proving nothing about a real race.
"""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.paths import EXAMPLE_CONFIG
from xxvi.api.run_service import (
    DRIFT_DENIER_THRESHOLD,
    HIDDEN_DRIFT_DENIER,
    HIDDEN_RAGE_QUIT,
    RunService,
)
from xxvi.content.loader import load_config
from xxvi.core.models import Difficulty
from xxvi.games.tokens import TokenService
from xxvi.gates.service import GateService
from xxvi.persistence.models import Account, Base, TrophyEarned
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings
from xxvi.vault.service import VaultService


@pytest.fixture
async def sessionmaker(tmp_path):
    db_path = tmp_path / "hidden-trophies-concurrency-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def account(sessionmaker):
    async with sessionmaker() as session:
        row = Account(username="him", password_hash="x", role="player")
        session.add(row)
        await session.commit()
        return row


@pytest.fixture
async def run(sessionmaker, account):
    return await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)


def _service(sessionmaker) -> RunService:
    settings = Settings()
    repo = RunRepository(sessionmaker)
    return RunService(
        repo=repo,
        config=load_config(EXAMPLE_CONFIG),
        gates=GateService(repo, settings),
        vault=VaultService(sessionmaker, settings),
        tokens=TokenService(repo),
    )


async def test_concurrent_drift_denier_checks_award_exactly_once(sessionmaker, run):
    repo = RunRepository(sessionmaker)
    for _ in range(DRIFT_DENIER_THRESHOLD):
        await repo.append_event(run.id, "game_failed", {"mechanic": "drift"})
    state = RunRepository.to_state(run)

    async def one_check():
        service = _service(sessionmaker)
        return await service.check_hidden(run, state, reconnecting=False)

    results = await asyncio.gather(*(one_check() for _ in range(10)), return_exceptions=True)

    failures = [r for r in results if isinstance(r, BaseException)]
    assert failures == [], f"unexpected exceptions: {failures!r}"

    winners = [r for r in results if any(t.id == HIDDEN_DRIFT_DENIER for t in r)]
    assert len(winners) == 1, (
        "exactly one of the 10 concurrent callers must observe the award "
        f"in its own return value, got {len(winners)}"
    )

    earned = await repo.earned_trophies(run.id)
    assert sum(1 for t in earned if t == HIDDEN_DRIFT_DENIER) == 1

    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(TrophyEarned).where(
                    TrophyEarned.run_id == run.id,
                    TrophyEarned.trophy_id == HIDDEN_DRIFT_DENIER,
                )
            )
        ).scalars().all()
    assert len(rows) == 1, "the UNIQUE(run_id, trophy_id) constraint must admit exactly one row"


async def test_concurrent_rage_quit_reconnect_checks_award_exactly_once(sessionmaker, run):
    repo = RunRepository(sessionmaker)
    await repo.append_event(run.id, "player_disconnected", {})
    state = RunRepository.to_state(run)

    async def one_reconnect():
        service = _service(sessionmaker)
        return await service.check_hidden(run, state, reconnecting=True)

    results = await asyncio.gather(*(one_reconnect() for _ in range(10)), return_exceptions=True)

    failures = [r for r in results if isinstance(r, BaseException)]
    assert failures == [], f"unexpected exceptions: {failures!r}"

    winners = [r for r in results if any(t.id == HIDDEN_RAGE_QUIT for t in r)]
    assert len(winners) == 1

    earned = await repo.earned_trophies(run.id)
    assert sum(1 for t in earned if t == HIDDEN_RAGE_QUIT) == 1
