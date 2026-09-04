"""Concurrency regressions for RunService/RunRepository found in review:

1. RunRepository.create() was a SELECT-then-INSERT with no conflict
   handling. Every mutating route and GET /api/run calls
   RunService.load() -> get_by_account() -> create() on a player's very
   first touch of the night, so 7 of 8 concurrent first requests came
   back as a raw 500 (the loser's INSERT hit runs.account_id's UNIQUE
   constraint uncaught).

2. RunRepository.save_state() loaded a Run via session.get, assigned
   attributes, and committed -- SQLAlchemy then emits an UPDATE
   containing only the columns dirty relative to THAT session's own
   load. Two concurrent saves from the same base row emit disjoint
   column sets that silently merge in the database into a RunState that
   is the successor of NEITHER event (a torn row, not last-writer-wins).
   Reproduced end to end: a pass and a Devil wipe applied concurrently
   from (GAME, seg 2, cleared {1}, lives 1) produced
   ('question', 1, [], 3) in 20/20 trials -- and because the losing
   failure branch's clear_segment_trophies() ran unconditionally
   *before* the old save_state, a losing wipe could delete already-earned
   segment trophies even though the run's own state never actually
   wiped, making the Platinum trophy permanently unreachable.

Uses a file-backed SQLite database with NullPool, not the shared
in-memory `sessionmaker` fixture from conftest.py -- see
tests/test_games_concurrency.py's fixture docstring for why: the shared
fixture's StaticPool secretly serializes every "concurrent" call through
one underlying connection, which would make these tests report the
correct-looking outcome while proving nothing.
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from xxvi.api.run_service import ApplyOutcome, ConcurrentUpdate, RunService
from xxvi.auth.passwords import hash_password
from xxvi.content.loader import load_config
from xxvi.core.models import Difficulty, Event, Phase, RunState
from xxvi.gates.service import GateService
from xxvi.games.tokens import TokenService
from xxvi.main import create_app, seed_accounts
from xxvi.persistence.models import Account, Base
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings, get_settings
from xxvi.vault.service import VaultService
from tests.paths import EXAMPLE_CONFIG


# See tests/test_games_concurrency.py for the full reasoning; identical shape.
@pytest.fixture
async def sessionmaker(tmp_path):
    db_path = tmp_path / "run-service-concurrency-test.db"
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


def _run_service(sessionmaker, repo=None) -> RunService:
    settings = Settings()
    repo = repo or RunRepository(sessionmaker)
    return RunService(
        repo=repo,
        config=load_config(EXAMPLE_CONFIG),
        gates=GateService(repo, settings),
        vault=VaultService(sessionmaker, settings),
        tokens=TokenService(repo),
    )


# --- CRITICAL 1: RunRepository.create() first-touch race ------------------

async def test_concurrent_create_for_the_same_account_never_500s(sessionmaker, account):
    repo = RunRepository(sessionmaker)

    results = await asyncio.gather(
        *(repo.create(account.id, None) for _ in range(8)),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert failures == [], f"unexpected exceptions: {failures!r}"

    run_ids = {r.id for r in results}
    assert len(run_ids) == 1, "every concurrent caller must agree on the one row that exists"

    async with sessionmaker() as session:
        from sqlalchemy import select
        from xxvi.persistence.models import Run
        rows = (await session.execute(select(Run).where(Run.account_id == account.id))).scalars().all()
    assert len(rows) == 1


async def test_concurrent_get_api_run_on_first_touch_all_succeed(sessionmaker):
    # HTTP-level reproduction of the measured incident: 8 concurrent first
    # requests -> [500, 200, 500, 500, 500, 500, 500, 500] before the fix.
    settings = Settings(
        player_username="him", player_password_hash=hash_password("pw"),
        go_live_iso="2020-01-01T00:00:00+05:30",
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    await seed_accounts(sessionmaker, settings)

    async def one_request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
            await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
            return await c.get("/api/run")

    responses = await asyncio.gather(*(one_request() for _ in range(8)))
    statuses = [r.status_code for r in responses]
    assert statuses == [200] * 8, statuses


# --- CRITICAL 2: divergent concurrent state saves --------------------------

DEVIL_LIVES = 3  # matches config/run.example.yaml's devil_lives


async def _seed_state(sessionmaker, account, state: RunState):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, state.difficulty)
    ok = await repo.save_state(run.id, run.version, state)
    assert ok
    async with sessionmaker() as session:
        from xxvi.persistence.models import Run as RunModel
        fresh = await session.get(RunModel, run.id)
        return fresh


async def test_concurrent_divergent_events_never_produce_a_torn_row(sessionmaker, account):
    # Exact reproduction from review: (GAME, seg 2, cleared {1}, lives 1),
    # racing a pass (GAME_PASSED) against a wipe-triggering failure
    # (GAME_FAILED with lives<=1). The buggy save_state produced
    # ('question', 1, [], 3) -- phase from the pass, everything else from
    # the wipe -- in 20/20 trials.
    start = RunState(
        phase=Phase.GAME, difficulty=Difficulty.DEVIL, segment=2,
        cleared_segments=frozenset({1}), released_rewards=frozenset(), lives=1,
    )
    run = await _seed_state(sessionmaker, account, start)
    repo = RunRepository(sessionmaker)

    async def try_pass():
        service = _run_service(sessionmaker, repo)
        return await service.apply(run, start, Event.GAME_PASSED)

    async def try_fail():
        service = _run_service(sessionmaker, repo)
        return await service.apply(run, start, Event.GAME_FAILED)

    results = await asyncio.gather(try_pass(), try_fail(), return_exceptions=True)

    successes = [r for r in results if isinstance(r, ApplyOutcome)]
    conflicts = [r for r in results if isinstance(r, ConcurrentUpdate)]
    other = [r for r in results if isinstance(r, BaseException) and not isinstance(r, ConcurrentUpdate)]

    assert other == [], f"unexpected exceptions: {other!r}"
    assert len(successes) == 1, "exactly one of the two concurrent events must win"
    assert len(conflicts) == 1, "the loser must be told to retry, not silently merged"

    async with sessionmaker() as session:
        from xxvi.persistence.models import Run as RunModel
        final = await session.get(RunModel, run.id)

    actual = (final.phase, final.segment, tuple(sorted(final.cleared_segments)), final.lives)
    legitimate_outcomes = {
        ("question", 2, (1,), 1),  # GAME_PASSED won: phase moves on, nothing else changes
        ("game", 1, (), DEVIL_LIVES),  # GAME_FAILED won: last life spent, full wipe+restore
    }
    torn_row = ("question", 1, (), 3)  # the exact corruption measured in review
    assert actual != torn_row
    assert actual in legitimate_outcomes, actual


async def test_two_concurrent_devil_failures_cost_two_lives_not_one(sessionmaker, account):
    # The milder instance of the same bug: two concurrent failures with
    # lives remaining both read lives=3, both wrote lives=2 -- a lost
    # update, not a torn row, but still wrong (should be 3 -> 2 -> 1 across
    # the two events, one of which must be retried after losing the race).
    start = RunState(
        phase=Phase.GAME, difficulty=Difficulty.DEVIL, segment=2,
        cleared_segments=frozenset({1}), released_rewards=frozenset(), lives=3,
    )
    run = await _seed_state(sessionmaker, account, start)
    repo = RunRepository(sessionmaker)

    async def try_fail():
        service = _run_service(sessionmaker, repo)
        return await service.apply(run, start, Event.GAME_FAILED)

    results = await asyncio.gather(try_fail(), try_fail(), return_exceptions=True)
    successes = [r for r in results if isinstance(r, ApplyOutcome)]
    conflicts = [r for r in results if isinstance(r, ConcurrentUpdate)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert successes[0].state.lives == 2, "the winner spends exactly one life"

    # The loser retries against fresh state, as a real client would after a 409.
    async with sessionmaker() as session:
        from xxvi.persistence.models import Run as RunModel
        mid_run = await session.get(RunModel, run.id)
    fresh_state = RunRepository.to_state(mid_run)
    service = _run_service(sessionmaker, repo)
    retried = await service.apply(mid_run, fresh_state, Event.GAME_FAILED)

    assert retried.state.lives == 1, "two failures, two lives spent -- not one"


async def test_concurrent_honest_and_garbage_game_submission_never_strands_trophies(
    sessionmaker, account
):
    # Player-triggerable end to end: /segment/start mints unlimited tokens.
    # Set up segment 2 with game-1/question-1 already earned and exactly one
    # Devil life left, so a failure here would wipe. Race an honest pass
    # against a garbage failure for the SAME segment. Whichever wins, the
    # persisted trophies must always match the persisted run state --
    # never "advanced past segment 1 AND lost segment 1's trophies", which
    # is the exact way review found the Platinum becomes unreachable.
    start = RunState(
        phase=Phase.GAME, difficulty=Difficulty.DEVIL, segment=2,
        cleared_segments=frozenset({1}), released_rewards=frozenset(), lives=1,
    )
    run = await _seed_state(sessionmaker, account, start)
    repo = RunRepository(sessionmaker)
    await repo.award_trophy(run.id, "game-1")
    await repo.award_trophy(run.id, "question-1")

    async def try_pass():
        service = _run_service(sessionmaker, repo)
        return await service.apply(run, start, Event.GAME_PASSED)

    async def try_fail():
        service = _run_service(sessionmaker, repo)
        return await service.apply(run, start, Event.GAME_FAILED)

    results = await asyncio.gather(try_pass(), try_fail(), return_exceptions=True)
    successes = [r for r in results if isinstance(r, ApplyOutcome)]
    assert len(successes) == 1, "the CAS must admit exactly one winner here too"

    async with sessionmaker() as session:
        from xxvi.persistence.models import Run as RunModel
        final = await session.get(RunModel, run.id)
    earned = await repo.earned_trophies(run.id)

    # Derive "did the run actually wipe" from the FULL persisted state, not
    # a single field in isolation -- a loose check here (e.g. segment alone)
    # can accidentally agree with a torn row that has the wipe's segment but
    # the pass's phase, which is exactly the shape of corruption this test
    # exists to catch. Must match one of the two legitimate outcomes tested
    # directly in test_concurrent_divergent_events_never_produce_a_torn_row.
    actual = (final.phase, final.segment, tuple(sorted(final.cleared_segments)), final.lives)
    wiped = ("game", 1, (), DEVIL_LIVES)
    passed = ("question", 2, (1,), 1)
    assert actual in {wiped, passed}, f"not a legitimate successor of either event: {actual}"

    if actual == wiped:
        assert "game-1" not in earned, "wipe happened -- segment-1 trophies must be gone too"
        assert "question-1" not in earned
    else:
        assert "game-1" in earned, "no wipe happened -- segment-1 trophies must survive intact"
        assert "question-1" in earned
