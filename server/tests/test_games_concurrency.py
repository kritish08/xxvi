import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from xxvi.core.models import Difficulty
from xxvi.games.tokens import TokenInvalid, TokenService, issue_segment_token
from xxvi.persistence.models import Base
from xxvi.persistence.repositories import RunRepository


# See tests/test_vault.py for the full reasoning; this fixture is the same
# shape and exists for the identical reason. The shared in-memory
# `sessionmaker` fixture in conftest.py is backed by SQLAlchemy's
# StaticPool, where every session in a test secretly shares one underlying
# connection -- concurrent calls against it are silently serialized through
# that single connection/transaction context rather than racing as
# independent DB clients would. A prior reviewer proved this makes a
# concurrency test against that fixture actively misleading: it can report
# the correct-looking "exactly one winner" outcome while leaving no row
# behind at all, which is worse than not testing concurrency, because it
# looks like coverage. `consume()`'s single-use guarantee is exactly the
# kind of conclusion that must not be reached that way, so this file gets
# its own fixture: a file-backed SQLite database with NullPool, so every
# `sessionmaker()` call opens a genuinely separate connection -- the same
# shape independent request handlers get against Postgres in production.
# This overrides the module-scoped `sessionmaker` fixture name from
# conftest.py for every test in this file (pytest resolves fixtures per
# module, closest definition wins), so the `account` fixture below -- which
# is unaware of any of this and just depends on "the sessionmaker fixture"
# by name -- transparently gets the file-backed engine instead of the
# in-memory one.
@pytest.fixture
async def sessionmaker(tmp_path):
    db_path = tmp_path / "games-concurrency-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_concurrent_consume_of_the_same_token_has_exactly_one_winner(sessionmaker, account):
    # The regression this reproduces: TokenService.consume() used to be a
    # check-then-act pair (has_event, then append_event) across two separate
    # transactions with no constraint backing them. Two connections racing
    # the same token both pass has_event before either commits, so both
    # succeed. Fired 200 trials against fresh state, both succeeded 200/200.
    # The fix replaces that with an atomic insert into a UNIQUE(run_id,
    # nonce) table -- the insert itself is the lock, so this must now
    # produce exactly one winner regardless of how many callers race it.
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    service = TokenService(repo)
    token, _ = issue_segment_token(run_id=run.id, segment=1, ttl_seconds=600)

    results = await asyncio.gather(
        *(service.consume(token, run_id=run.id) for _ in range(8)),
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, BaseException)]
    conflicts = [r for r in results if isinstance(r, TokenInvalid)]
    unexpected = [r for r in results if isinstance(r, BaseException) and not isinstance(r, TokenInvalid)]

    assert unexpected == [], f"unexpected exceptions: {unexpected!r}"
    assert len(successes) == 1
    assert len(conflicts) == 7


async def test_concurrent_consume_of_different_tokens_all_succeed(sessionmaker, account):
    # Sanity check on the same fixture/mechanism in the other direction --
    # the unique constraint must key on (run_id, nonce), not on run_id
    # alone. Distinct tokens (distinct nonces) for the same run racing
    # concurrently must all be independently consumable.
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    service = TokenService(repo)
    tokens = [issue_segment_token(run_id=run.id, segment=i, ttl_seconds=600)[0] for i in range(1, 6)]

    results = await asyncio.gather(
        *(service.consume(token, run_id=run.id) for token in tokens),
        return_exceptions=True,
    )
    failures = [r for r in results if isinstance(r, BaseException)]
    assert failures == [], f"unexpected failures: {failures!r}"
    assert len(results) == 5
