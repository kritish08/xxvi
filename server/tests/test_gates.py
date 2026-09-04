import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from xxvi.auth.passwords import hash_password
from xxvi.core.models import Difficulty
from xxvi.gates.service import GateId, GateOutcome, GateService
from xxvi.persistence.models import Account, Base
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings

# Each gate gets its own code. A fixture that reuses one code for all three
# gates (as an earlier version of this file did) can't tell "the right code
# for this gate" apart from "any code, wired to the wrong gate" -- and a
# checkpoint mis-wired to ACTIVATION_CODE's hash is exactly the scenario
# that would let the code the player is told out loud at the start of the
# night open a checkpoint and release a real gift card without the actual
# checkpoint code ever being entered.
ACTIVATION_CODE = "ACTIVATE-0001"
CHECKPOINT_1_CODE = "CHECK-ONE-0002"
CHECKPOINT_2_CODE = "CHECK-TWO-0003"


@pytest.fixture
def settings():
    return Settings(
        activation_code_hash=hash_password(ACTIVATION_CODE),
        checkpoint_1_hash=hash_password(CHECKPOINT_1_CODE),
        checkpoint_2_hash=hash_password(CHECKPOINT_2_CODE),
    )


@pytest.fixture
async def service(sessionmaker, settings):
    return GateService(RunRepository(sessionmaker), settings)


@pytest.fixture
async def run(sessionmaker, account):
    return await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)


@pytest.fixture
async def run2(sessionmaker, account2):
    return await RunRepository(sessionmaker).create(account2.id, Difficulty.KIDDIE)


async def test_correct_code_passes(service, run):
    assert await service.submit(run.id, GateId.CHECKPOINT_1, CHECKPOINT_1_CODE) is GateOutcome.OK


async def test_wrong_code_is_rejected(service, run):
    assert await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.WRONG


async def test_a_gates_own_correct_code_does_not_open_another_gate(service, run):
    # The scenario the reviewer flagged as landing on the money path: if
    # CHECKPOINT_1 were ever mis-wired to check against ACTIVATION's hash,
    # the code announced out loud at the very start of the event would
    # silently open a checkpoint. Each gate must reject every other gate's
    # correct code.
    assert (
        await service.submit(run.id, GateId.CHECKPOINT_1, ACTIVATION_CODE) is GateOutcome.WRONG
    )
    assert (
        await service.submit(run.id, GateId.CHECKPOINT_1, CHECKPOINT_2_CODE) is GateOutcome.WRONG
    )
    assert await service.submit(run.id, GateId.ACTIVATION, CHECKPOINT_1_CODE) is GateOutcome.WRONG
    assert await service.submit(run.id, GateId.ACTIVATION, CHECKPOINT_2_CODE) is GateOutcome.WRONG
    assert (
        await service.submit(run.id, GateId.CHECKPOINT_2, ACTIVATION_CODE) is GateOutcome.WRONG
    )
    assert (
        await service.submit(run.id, GateId.CHECKPOINT_2, CHECKPOINT_1_CODE) is GateOutcome.WRONG
    )


async def test_comparison_normalises_case_and_surrounding_whitespace(service, run):
    assert (
        await service.submit(run.id, GateId.CHECKPOINT_1, f"  {CHECKPOINT_1_CODE.lower()}  ")
        is GateOutcome.OK
    )


async def test_checkpoint_locks_after_three_wrong_attempts(service, run):
    for _ in range(3):
        assert await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.WRONG
    assert await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.LOCKED
    # Locked means locked, even for the right answer.
    assert (
        await service.submit(run.id, GateId.CHECKPOINT_1, CHECKPOINT_1_CODE) is GateOutcome.LOCKED
    )


async def test_activation_gate_never_hard_locks(service, run):
    for _ in range(25):
        assert await service.submit(run.id, GateId.ACTIVATION, "NOPE") is GateOutcome.WRONG
    assert await service.submit(run.id, GateId.ACTIVATION, ACTIVATION_CODE) is GateOutcome.OK


async def test_operator_can_clear_a_lockout(service, run):
    for _ in range(3):
        await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE")
    assert (
        await service.submit(run.id, GateId.CHECKPOINT_1, CHECKPOINT_1_CODE) is GateOutcome.LOCKED
    )

    await service.clear_lock(run.id, GateId.CHECKPOINT_1)
    assert await service.submit(run.id, GateId.CHECKPOINT_1, CHECKPOINT_1_CODE) is GateOutcome.OK


async def test_clear_lock_resets_the_attempt_counter_not_just_the_lock_flag(service, run):
    # A clear that only flips `locked` back to False but leaves `attempts`
    # at 3 would re-lock on the very next wrong guess -- the operator's
    # override has to buy a genuinely fresh set of attempts, not one.
    for _ in range(3):
        await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE")
    assert await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.LOCKED

    await service.clear_lock(run.id, GateId.CHECKPOINT_1)
    assert await service.attempts_remaining(run.id, GateId.CHECKPOINT_1) == 3
    assert await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.WRONG
    assert await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.WRONG
    assert await service.submit(run.id, GateId.CHECKPOINT_1, CHECKPOINT_1_CODE) is GateOutcome.OK


async def test_clear_lock_only_clears_the_named_gate(service, run):
    # A clear that drops the gate_id filter (or otherwise touches every
    # gate for the run) would reset CHECKPOINT_2's progress as a side
    # effect of unlocking CHECKPOINT_1. It must not.
    for _ in range(3):
        await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE")
    assert (
        await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.LOCKED
    )
    for _ in range(2):
        await service.submit(run.id, GateId.CHECKPOINT_2, "NOPE")
    assert await service.attempts_remaining(run.id, GateId.CHECKPOINT_2) == 1

    await service.clear_lock(run.id, GateId.CHECKPOINT_1)

    assert await service.attempts_remaining(run.id, GateId.CHECKPOINT_2) == 1


async def test_gates_are_tracked_independently(service, run):
    for _ in range(3):
        await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE")
    assert await service.submit(run.id, GateId.CHECKPOINT_2, CHECKPOINT_2_CODE) is GateOutcome.OK


async def test_gate_attempts_are_scoped_to_the_run(service, run, run2):
    # A `gate_row`/`set_gate` that drops its `run_id` filter (matches on
    # `gate_id` alone) would let one player's wrong guesses lock -- or
    # unlock -- a completely different run's checkpoint.
    for _ in range(3):
        await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE")
    assert (
        await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.LOCKED
    )

    assert await service.attempts_remaining(run2.id, GateId.CHECKPOINT_1) == 3
    assert (
        await service.submit(run2.id, GateId.CHECKPOINT_1, CHECKPOINT_1_CODE) is GateOutcome.OK
    )


async def test_attempts_remaining_is_none_for_the_unlockable_front_door(service, run):
    assert await service.attempts_remaining(run.id, GateId.ACTIVATION) is None
    assert await service.attempts_remaining(run.id, GateId.CHECKPOINT_1) == 3


# --- Concurrent first-touch at a gate. ---
#
# This needs its own file-backed `NullPool` sessionmaker, not the shared
# `conftest.py` one (`sqlite+aiosqlite:///:memory:`, backed by `StaticPool`
# -- every session shares one underlying connection, which makes any
# conclusion drawn from it about concurrent access unsound; see
# tests/test_vault.py for the fuller writeup and an empirical proof). A
# double-clicked submit button is two concurrent requests hitting a gate
# that has never been touched before -- exactly the case `gate_row`'s
# get-or-create has to survive without one of them crashing on the
# `UNIQUE(run_id, gate_id)` constraint.
@pytest.fixture
async def file_sessionmaker(tmp_path):
    db_path = tmp_path / "gates-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_concurrent_first_touch_at_a_gate_does_not_crash(file_sessionmaker, settings):
    async with file_sessionmaker() as session:
        acct = Account(username="race", password_hash="x", role="player")
        session.add(acct)
        await session.commit()
        acct_id = acct.id

    run = await RunRepository(file_sessionmaker).create(acct_id, Difficulty.KIDDIE)
    service = GateService(RunRepository(file_sessionmaker), settings)

    # ACTIVATION never hard-locks and is the literal front door -- a crash
    # here, not a lockout, is the failure this test exists to catch.
    results = await asyncio.gather(
        *(service.submit(run.id, GateId.ACTIVATION, ACTIVATION_CODE) for _ in range(8)),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert errors == []
    assert all(r is GateOutcome.OK for r in results)


async def test_concurrent_wrong_guesses_lock_at_exactly_max_attempts(file_sessionmaker, settings):
    # The lost-update race: a read-modify-write counter undercounts
    # concurrent wrong guesses (measured: 13 concurrent guesses left
    # attempts=2, locked=False). This proves the fix holds under real
    # concurrent connections, not just the shared in-memory fixture.
    async with file_sessionmaker() as session:
        acct = Account(username="race2", password_hash="x", role="player")
        session.add(acct)
        await session.commit()
        acct_id = acct.id

    run = await RunRepository(file_sessionmaker).create(acct_id, Difficulty.KIDDIE)
    service = GateService(RunRepository(file_sessionmaker), settings)

    results = await asyncio.gather(
        *(service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") for _ in range(13)),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert errors == []
    assert results.count(GateOutcome.WRONG) == 3
    assert results.count(GateOutcome.LOCKED) == 10

    row = await RunRepository(file_sessionmaker).gate_row(run.id, GateId.CHECKPOINT_1.value)
    assert row.attempts == 3
    assert row.locked is True


async def test_concurrent_set_gate_on_a_never_touched_gate_does_not_crash(file_sessionmaker):
    # IMPORTANT: `set_gate` is a sixth check-then-act site (SELECT -> if
    # None: INSERT -> UPDATE) with no IntegrityError handling. Measured
    # before the fix: 8 concurrent calls against a gate with no
    # pre-existing row produced 7 IntegrityError-driven 500s. This is
    # reached by POST /api/operator/unlock-gate -> GateService.clear_lock,
    # the operator's rescue path when a player is locked out -- so it used
    # to fail exactly when it was needed. Mirrors
    # test_concurrent_first_touch_at_a_gate_does_not_crash for `gate_row`
    # above, against the same file-backed NullPool fixture: the shared
    # in-memory fixture gives every pooled connection its own database, so
    # a concurrency test against it would be meaningless (see that
    # fixture's docstring).
    async with file_sessionmaker() as session:
        acct = Account(username="race3", password_hash="x", role="player")
        session.add(acct)
        await session.commit()
        acct_id = acct.id

    run = await RunRepository(file_sessionmaker).create(acct_id, Difficulty.KIDDIE)
    repo = RunRepository(file_sessionmaker)

    results = await asyncio.gather(
        *(
            repo.set_gate(run.id, GateId.CHECKPOINT_1.value, attempts=0, locked=False)
            for _ in range(8)
        ),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert errors == [], f"expected no errors, got: {errors}"

    row = await repo.gate_row(run.id, GateId.CHECKPOINT_1.value)
    assert row.attempts == 0
    assert row.locked is False


async def test_concurrent_unlock_gate_via_clear_lock_does_not_crash(file_sessionmaker, settings):
    # Same race, exercised through the actual operator rescue path
    # (GateService.clear_lock -> set_gate) rather than the repository
    # method directly, against a gate that was locked and never touched by
    # a get-or-create read first.
    async with file_sessionmaker() as session:
        acct = Account(username="race4", password_hash="x", role="player")
        session.add(acct)
        await session.commit()
        acct_id = acct.id

    run = await RunRepository(file_sessionmaker).create(acct_id, Difficulty.KIDDIE)
    service = GateService(RunRepository(file_sessionmaker), settings)

    results = await asyncio.gather(
        *(service.clear_lock(run.id, GateId.CHECKPOINT_1) for _ in range(8)),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert errors == [], f"expected no errors, got: {errors}"


def test_checkpoint_gate_ids_match_the_strings_already_in_the_database():
    # gate_attempts.gate_id is a plain String(32) holding these literals for
    # every run ever recorded. Changing the shape of act 1 and 2's ids would
    # orphan existing lockout rows, so the generalisation must reproduce them
    # exactly, not merely produce something consistent.
    from xxvi.gates.service import checkpoint_gate

    assert checkpoint_gate(1) == "checkpoint_1"
    assert checkpoint_gate(2) == "checkpoint_2"


def test_checkpoint_gate_extends_past_the_two_acts_xxvi_shipped_with():
    from xxvi.gates.service import checkpoint_gate

    assert checkpoint_gate(3) == "checkpoint_3"
    assert checkpoint_gate(7) == "checkpoint_7"


def test_a_third_act_does_not_reuse_the_second_acts_checkpoint_hash():
    # The bug this closes: `CHECKPOINT_1 if act == 1 else CHECKPOINT_2` sent
    # every act above 2 to act 2's gate, so act 3 would have opened to act 2's
    # code -- releasing act 3's reward to someone who never cleared act 3.
    from xxvi.settings import Settings

    settings = Settings(checkpoint_1_hash="h1", checkpoint_2_hash="h2")
    assert settings.checkpoint_hash(3) == ""
    assert settings.checkpoint_hash(3) != settings.checkpoint_hash(2)
