"""Behaviour that SQLite fakes and Postgres does for real.

Each test here targets a spot where SQLite's emulation of a feature
diverges from Postgres's real implementation of the same feature -- not a
retest of business logic the fast suite already covers. In particular,
`DateTime(timezone=True)` is honest on Postgres (a real `timestamptz`) and
fictional on SQLite (there is no such storage type; SQLAlchemy's SQLite
dialect stores a naive string and hands back a naive `datetime`), so the
same assertion made against the SQLite fixture would not exercise anything
real.
"""

import pytest
from sqlalchemy import select

from xxvi.core.models import Difficulty, Phase, RunState
from xxvi.persistence.models import Run, RunEvent
from xxvi.persistence.repositories import RunRepository

pytestmark = pytest.mark.pg


@pytest.fixture
def repo(sessionmaker):
    return RunRepository(sessionmaker)


@pytest.fixture
async def run(repo, account):
    return await repo.create(account.id, Difficulty.KIDDIE)


async def test_json_columns_round_trip_lists_and_dicts_through_a_fresh_read(
    sessionmaker, repo, run
):
    state = RunState(
        phase=Phase.GAME,
        difficulty=Difficulty.KIDDIE,
        segment=3,
        cleared_segments=frozenset({1, 2, 3}),
        released_rewards=frozenset({2}),
        lives=None,
    )
    await repo.save_state(run.id, run.version, state)
    payload = {"nested": {"a": [1, 2, 3]}, "flag": True, "count": 0, "n": None}
    await repo.append_event(run.id, "sample_event", payload)

    # A brand new session over a brand new (NullPool) connection -- not the
    # same Python object still holding the value it was given -- so this
    # only passes if Postgres actually stored and returned real JSON.
    async with sessionmaker() as session:
        fetched_run = (
            await session.execute(select(Run).where(Run.id == run.id))
        ).scalar_one()
        fetched_event = (
            await session.execute(select(RunEvent).where(RunEvent.run_id == run.id))
        ).scalar_one()

    assert sorted(fetched_run.cleared_segments) == [1, 2, 3]
    assert fetched_run.released_rewards == [2]
    assert fetched_event.payload == payload


async def test_timestamptz_defaults_are_timezone_aware_on_read(sessionmaker, run):
    async with sessionmaker() as session:
        fetched = (
            await session.execute(select(Run).where(Run.id == run.id))
        ).scalar_one()

    assert fetched.started_at.tzinfo is not None, (
        "server_default=func.now() on a DateTime(timezone=True) column must "
        "round-trip as an aware datetime on Postgres; SQLite's DateTime "
        "columns are naive strings regardless of the timezone=True flag "
        "and cannot exercise this."
    )
    assert fetched.started_at.utcoffset() is not None


async def test_update_returning_falls_back_correctly_on_zero_matched_rows(repo, run):
    # `record_gate_failure` decides "already locked before this call" by
    # whether its own UPDATE ... RETURNING (WHERE ... locked=False)
    # matched zero rows -- asyncpg's real RETURNING-with-no-rows path,
    # not a simulated one. Lock the gate out-of-band first so the WHERE
    # clause is guaranteed to match nothing.
    await repo.set_gate(run.id, "checkpoint_1", attempts=3, locked=True)

    attempts, locked, applied = await repo.record_gate_failure(
        run.id, "checkpoint_1", max_attempts=3
    )

    assert applied is False
    assert attempts == 3
    assert locked is True
