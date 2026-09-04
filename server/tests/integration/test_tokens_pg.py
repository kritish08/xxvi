"""Segment token behaviour under real Postgres MVCC.

The fast suite (tests/test_games_concurrency.py) already proves single-use
against a file-backed, `NullPool` SQLite database. This file exists only to
re-run the same proof against a real MVCC engine, across enough independent
trials to be meaningful, plus the cross-run rejection check that has
nothing to do with concurrency but everything to do with the token not
leaking a nonce claim across accounts.
"""

import asyncio

import pytest

from xxvi.core.models import Difficulty
from xxvi.games.tokens import TokenInvalid, TokenService, issue_segment_token
from xxvi.persistence.repositories import RunRepository

pytestmark = pytest.mark.pg


@pytest.fixture
def repo(sessionmaker):
    return RunRepository(sessionmaker)


@pytest.fixture
async def run(repo, account):
    return await repo.create(account.id, Difficulty.KIDDIE)


@pytest.fixture
async def run2(repo, account2):
    return await repo.create(account2.id, Difficulty.KIDDIE)


async def test_8_way_concurrent_consumption_of_one_token_yields_exactly_one_winner(
    repo, run
):
    # Repeated across independent trials (fresh token, fresh 8-way race
    # each time) rather than trusting a single run -- a race that only
    # sometimes misbehaves is exactly the kind of thing one lucky trial
    # would hide.
    service = TokenService(repo)
    for trial in range(5):
        token, _ = issue_segment_token(run_id=run.id, segment=trial + 1, ttl_seconds=600)

        results = await asyncio.gather(
            *(service.consume(token, run_id=run.id) for _ in range(8)),
            return_exceptions=True,
        )
        successes = [r for r in results if not isinstance(r, BaseException)]
        conflicts = [r for r in results if isinstance(r, TokenInvalid)]
        unexpected = [
            r for r in results if isinstance(r, BaseException) and not isinstance(r, TokenInvalid)
        ]

        assert unexpected == [], f"trial {trial}: unexpected exceptions: {unexpected!r}"
        assert len(successes) == 1, f"trial {trial}: expected exactly one winner"
        assert len(conflicts) == 7, f"trial {trial}: expected exactly seven conflicts"


async def test_token_minted_for_one_run_is_rejected_by_another_run(repo, run, run2):
    service = TokenService(repo)
    token, _ = issue_segment_token(run_id=run.id, segment=1, ttl_seconds=600)

    with pytest.raises(TokenInvalid):
        await service.consume(token, run_id=run2.id)

    # The rightful run can still consume it -- the token itself was never
    # touched by the rejected cross-run attempt.
    claim = await service.consume(token, run_id=run.id)
    assert claim.run_id == run.id
