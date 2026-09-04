import asyncio
import logging

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from xxvi.core.models import Difficulty
from xxvi.persistence.models import Base
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings
from xxvi.vault.service import AlreadyReleased, NotApproved, UnknownReward, VaultService

SECRET = "REAL-CODE-DO-NOT-LEAK"


# NOTE ON THE FIXTURE BELOW:
#
# The shared `sessionmaker` fixture in tests/conftest.py points at
# `sqlite+aiosqlite:///:memory:`, which SQLAlchemy backs with a `StaticPool`
# -- every session in the test shares a single underlying connection. That
# is fine for tests that only care about sequential behaviour, but it makes
# any conclusion about *concurrent* access unsound: a prior reviewer proved
# that eight concurrent `award_trophy` calls against that fixture returned
# the correct "exactly one winner" result and then the winning row vanished,
# because all eight sessions were secretly serialised through one shared
# connection/transaction context rather than racing as independent DB
# clients would.
#
# The vault is the one place in this codebase where a wrong concurrency
# conclusion has a real dollar cost, so it gets its own fixture: a
# file-backed SQLite database with `NullPool`, so every `sessionmaker()`
# call opens a genuinely separate connection, the way independent request
# handlers would against Postgres. This overrides the module-scoped
# `sessionmaker` fixture name from conftest.py for every test in this file
# (pytest resolves fixtures per test module, closest definition wins), so
# the `account`/`run` fixtures below -- which are unaware of any of this and
# just depend on "the sessionmaker fixture" by name -- transparently get the
# file-backed engine instead of the in-memory one.
@pytest.fixture
async def sessionmaker(tmp_path):
    db_path = tmp_path / "vault-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)

    # SQLite ignores FK constraints unless a connection turns them on
    # explicitly. Enabling this lets a test below prove that an invalid
    # run_id (a real foreign-key violation) raises a real error instead of
    # being misread as "already released" -- see the `_is_unique_violation`
    # guard in xxvi/vault/service.py this is exercising.
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def settings():
    return Settings(reward_1_code=SECRET, reward_2_code="SECOND-CODE")


@pytest.fixture
async def run(sessionmaker, account):
    return await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)


@pytest.fixture
async def run2(sessionmaker, account2):
    return await RunRepository(sessionmaker).create(account2.id, Difficulty.KIDDIE)


@pytest.fixture
def vault(sessionmaker, settings):
    return VaultService(sessionmaker, settings)


async def test_approved_release_returns_the_code(vault, run):
    assert await vault.release(run.id, 1, approved_by_operator=True) == SECRET


async def test_release_without_operator_approval_is_refused(vault, run):
    with pytest.raises(NotApproved):
        await vault.release(run.id, 1, approved_by_operator=False)
    assert await vault.released_reward_ids(run.id) == frozenset()


async def test_a_reward_can_only_be_released_once(vault, run):
    await vault.release(run.id, 1, approved_by_operator=True)
    with pytest.raises(AlreadyReleased):
        await vault.release(run.id, 1, approved_by_operator=True)


async def test_a_foreign_key_violation_is_not_mistaken_for_a_duplicate_release(vault):
    # run_id 999999 does not exist, so the insert violates the FK constraint
    # on CodeRelease.run_id -- a genuine IntegrityError that is NOT a
    # duplicate release. A bare `except IntegrityError` would misread this
    # as AlreadyReleased (a cosmetic "already sent" no-op that silently
    # eats a real bug and a real reward). It must surface as a real error.
    with pytest.raises(IntegrityError):
        await vault.release(999999, 1, approved_by_operator=True)


async def test_concurrent_releases_yield_exactly_one_winner(vault, run):
    results = await asyncio.gather(
        *(vault.release(run.id, 1, approved_by_operator=True) for _ in range(8)),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, str)]
    conflicts = [r for r in results if isinstance(r, AlreadyReleased)]
    assert len(successes) == 1
    assert len(conflicts) == 7


async def test_the_code_never_appears_in_log_output(vault, run, caplog):
    with caplog.at_level(logging.DEBUG):
        await vault.release(run.id, 1, approved_by_operator=True)
        with pytest.raises(AlreadyReleased):
            await vault.release(run.id, 1, approved_by_operator=True)
        with pytest.raises(NotApproved):
            await vault.release(run.id, 2, approved_by_operator=False)
    assert SECRET not in caplog.text


async def test_the_code_never_appears_in_an_exception_message(vault, run, settings):
    # `caplog` only proves the code stays out of logs. `code` is still in
    # lexical scope at the `raise AlreadyReleased` -- nothing stops a future
    # edit from interpolating it into the message, and tasks 11-13 wire
    # these exceptions to HTTP handlers where an exception message plausibly
    # becomes a response body. Check the exception's own string form.
    await vault.release(run.id, 1, approved_by_operator=True)

    with pytest.raises(AlreadyReleased) as first_ei:
        await vault.release(run.id, 1, approved_by_operator=True)
    assert SECRET not in str(first_ei.value)

    with pytest.raises(NotApproved) as second_ei:
        await vault.release(run.id, 2, approved_by_operator=False)
    assert settings.reward_2_code not in str(second_ei.value)


async def test_unknown_reward_id_is_rejected(vault, run):
    with pytest.raises(UnknownReward):
        await vault.release(run.id, 999, approved_by_operator=True)


def test_code_for_is_the_recovery_path_for_an_already_released_code(vault):
    # cli.py's cmd_release uses this on the AlreadyReleased path to recover
    # a code that was emitted once already but never actually reached the
    # operator -- the one caller with real justification to read the
    # configured code outside release()'s persistence path.
    assert vault.code_for(1) == SECRET


def test_code_for_respects_dry_run_like_release_does(sessionmaker):
    # A rehearsal must never even READ the real value -- code_for shares
    # _code_for's dry-run branch, not a second copy of that rule.
    settings = Settings(reward_1_code=SECRET, dry_run=True)
    vault = VaultService(sessionmaker, settings)
    assert vault.code_for(1) != SECRET
    assert vault.code_for(1).startswith("DRY-RUN")


def test_code_for_rejects_an_unknown_reward_id(vault):
    with pytest.raises(UnknownReward):
        vault.code_for(999)


async def test_released_ids_are_reported(vault, run):
    await vault.release(run.id, 1, approved_by_operator=True)
    assert await vault.released_reward_ids(run.id) == frozenset({1})


async def test_released_reward_ids_are_scoped_to_the_run(vault, run, run2):
    # A `released_reward_ids` that drops its `run_id` filter would report
    # one player's released rewards as belonging to every run -- cross-run
    # leakage on the money path.
    await vault.release(run.id, 1, approved_by_operator=True)
    assert await vault.released_reward_ids(run.id) == frozenset({1})
    assert await vault.released_reward_ids(run2.id) == frozenset()


async def test_a_third_reward_resolves_its_own_code(monkeypatch, sessionmaker):
    monkeypatch.setenv("REWARD_3_CODE", "THIRD-CODE-XYZ")
    settings = Settings(reward_1_code="one", reward_2_code="two")
    vault = VaultService(sessionmaker, settings)
    assert vault.code_for(3) == "THIRD-CODE-XYZ"


async def test_an_unconfigured_reward_still_raises_rather_than_returning_empty(sessionmaker):
    # The failure mode this preserves: silently returning "" would print a
    # blank code at the one moment that matters and look like it worked.
    vault = VaultService(sessionmaker, Settings())
    with pytest.raises(UnknownReward):
        vault.code_for(4)
