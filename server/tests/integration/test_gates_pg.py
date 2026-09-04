"""Gate behaviour under real Postgres MVCC.

The fast suite (tests/test_gates.py) covers every branch of `GateService`
against a file-backed, `NullPool` SQLite database, including two
concurrency regressions already fixed there. This file exists only for
proving those same fixes hold against a real MVCC engine:

  - `gate_row`'s get-or-create was a Critical: 8 concurrent correct submits
    at a never-before-touched gate crashed 7 of them on the
    `UNIQUE(run_id, gate_id)` constraint before the try/except-and-reselect
    fix landed. ACTIVATION is the literal front door of the event; a crash
    there is exactly as fatal as a lockout.
  - `record_gate_failure`'s naive read-modify-write undercounted concurrent
    wrong guesses (measured: 13 concurrent guesses left attempts=2,
    locked=False) before the atomic `UPDATE ... RETURNING` fix landed.
"""

import asyncio

import pytest

from xxvi.auth.passwords import hash_password
from xxvi.core.models import Difficulty
from xxvi.gates.service import GateId, GateOutcome, GateService
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings

pytestmark = pytest.mark.pg

ACTIVATION_CODE = "ACTIVATE-0001"
CHECKPOINT_1_CODE = "CHECK-ONE-0002"


@pytest.fixture
def settings():
    return Settings(
        activation_code_hash=hash_password(ACTIVATION_CODE),
        checkpoint_1_hash=hash_password(CHECKPOINT_1_CODE),
    )


@pytest.fixture
def repo(sessionmaker):
    return RunRepository(sessionmaker)


@pytest.fixture
def service(repo, settings):
    return GateService(repo, settings)


@pytest.fixture
async def run(repo, account):
    return await repo.create(account.id, Difficulty.KIDDIE)


async def test_concurrent_first_touch_at_a_never_before_seen_gate_does_not_crash(
    service, run
):
    # This gate has never been touched, so every one of these 8 concurrent
    # calls races `gate_row`'s get-or-create against real, independent
    # Postgres connections. None may crash; all must resolve to the same
    # correct outcome.
    results = await asyncio.gather(
        *(service.submit(run.id, GateId.ACTIVATION, ACTIVATION_CODE) for _ in range(8)),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, BaseException)]
    assert errors == [], f"unexpected exceptions: {errors!r}"
    assert all(r is GateOutcome.OK for r in results)


async def test_13_concurrent_wrong_guesses_lock_at_exactly_attempts_3_not_fewer(
    service, run, repo
):
    results = await asyncio.gather(
        *(service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") for _ in range(13)),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, BaseException)]
    assert errors == [], f"unexpected exceptions: {errors!r}"
    assert results.count(GateOutcome.WRONG) == 3
    assert results.count(GateOutcome.LOCKED) == 10

    row = await repo.gate_row(run.id, GateId.CHECKPOINT_1.value)
    assert row.attempts == 3, "a lost-update race would undercount this"
    assert row.locked is True


async def test_30_concurrent_wrong_attempts_at_activation_never_hard_locks(
    service, run
):
    # ACTIVATION has `max_attempts=None` -- rate-limited but never
    # hard-locked. 30 concurrent wrong guesses must all come back WRONG,
    # and the correct code must still pass immediately afterward.
    results = await asyncio.gather(
        *(service.submit(run.id, GateId.ACTIVATION, "NOPE") for _ in range(30)),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, BaseException)]
    assert errors == [], f"unexpected exceptions: {errors!r}"
    assert results.count(GateOutcome.WRONG) == 30
    assert results.count(GateOutcome.LOCKED) == 0

    assert await service.submit(run.id, GateId.ACTIVATION, ACTIVATION_CODE) is GateOutcome.OK
