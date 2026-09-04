import time
from datetime import UTC, datetime, timedelta

import pytest
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from xxvi.content.schema import GameSlot
from xxvi.core.models import Difficulty
from xxvi.games.seeds import simon_sequence
from xxvi.games.tokens import (
    _SALT,
    TokenInvalid,
    TokenService,
    decode_segment_token,
    issue_segment_token,
)
from xxvi.games.verify import GameResult, verify_result
from xxvi.persistence.models import Base
from xxvi.persistence.repositories import RunRepository


# SQLite ignores FK constraints unless a connection turns them on
# explicitly (see tests/test_vault.py, which needs the identical fixture for
# the identical reason: proving a real FK violation on ConsumedToken.run_id
# is NOT mistaken for a duplicate-nonce unique violation). The shared
# `sessionmaker` fixture in conftest.py doesn't enable this, so it can't
# exercise that path.
@pytest.fixture
async def fk_enforcing_sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def test_simon_sequence_is_deterministic_for_a_seed():
    assert simon_sequence("seed-a", 6) == simon_sequence("seed-a", 6)


def test_simon_sequence_differs_between_seeds():
    assert simon_sequence("seed-a", 8) != simon_sequence("seed-b", 8)


def test_simon_sequence_is_a_prefix_of_a_longer_one():
    assert simon_sequence("seed-a", 4) == simon_sequence("seed-a", 8)[:4]


def test_simon_values_are_face_buttons():
    assert set(simon_sequence("seed-a", 40)) <= {0, 1, 2, 3}


def test_simon_passes_only_with_the_exact_server_sequence():
    slot = GameSlot(segment=1, mechanic="simon", params={"length": 5})
    correct = simon_sequence("s", 5)

    ok = GameResult(mechanic="simon", passed_client_side=True, duration_ms=6000,
                    input_count=5, score=5, sequence=correct)
    assert verify_result(slot, "s", ok) is True

    wrong = GameResult(mechanic="simon", passed_client_side=True, duration_ms=6000,
                       input_count=5, score=5, sequence=list(reversed(correct)))
    assert verify_result(slot, "s", wrong) is False


def test_simon_ignores_a_lying_client_verdict():
    slot = GameSlot(segment=1, mechanic="simon", params={"length": 5})
    lying = GameResult(mechanic="simon", passed_client_side=True, duration_ms=6000,
                       input_count=5, score=5, sequence=[0, 0, 0, 0, 0])
    assert verify_result(slot, "s", lying) is False


def test_update_game_requires_the_configured_tap_count():
    slot = GameSlot(segment=2, mechanic="update", params={"taps_required": 20})
    enough = GameResult(mechanic="update", passed_client_side=True, duration_ms=9000,
                        input_count=20, score=20, sequence=[])
    short = GameResult(mechanic="update", passed_client_side=True, duration_ms=9000,
                       input_count=11, score=11, sequence=[])
    assert verify_result(slot, "s", enough) is True
    assert verify_result(slot, "s", short) is False


def test_implausibly_fast_runs_are_rejected():
    slot = GameSlot(segment=2, mechanic="update", params={"taps_required": 20})
    too_fast = GameResult(mechanic="update", passed_client_side=True, duration_ms=50,
                          input_count=20, score=20, sequence=[])
    assert verify_result(slot, "s", too_fast) is False


def test_update_input_count_ceiling_rejects_an_implausible_tap_count():
    # The per-input floor alone doesn't stop a claim like "five million taps
    # against a twenty-tap slot" as long as duration_ms is padded to match --
    # a mechanic-specific ceiling derived from the slot's own params is a
    # second, independent bound that catches it regardless of duration.
    slot = GameSlot(segment=2, mechanic="update", params={"taps_required": 20})
    absurd = GameResult(mechanic="update", passed_client_side=True,
                        duration_ms=5_000_000 * 60, input_count=5_000_000, score=5_000_000,
                        sequence=[])
    assert verify_result(slot, "s", absurd) is False


def test_a_claimed_duration_longer_than_real_elapsed_time_is_rejected():
    # A client can compute a correct seeded Simon sequence in under a
    # millisecond -- the server hands it the seed up front -- then simply
    # report a duration_ms that clears the internal per-input floor exactly.
    # The internal consistency check alone (duration_ms vs input_count)
    # can't catch this; it needs to be cross-checked against how much real
    # wall-clock time actually passed since the token was issued.
    slot = GameSlot(segment=1, mechanic="simon", params={"length": 5})
    correct = simon_sequence("s", 5)
    issued_at = datetime(2026, 1, 1, tzinfo=UTC)
    submitted_at = issued_at + timedelta(milliseconds=400)  # solved near-instantly

    honest = GameResult(mechanic="simon", passed_client_side=True, duration_ms=300,
                        input_count=5, score=5, sequence=correct)
    assert verify_result(slot, "s", honest, issued_at=issued_at, now=submitted_at) is True

    faked = GameResult(mechanic="simon", passed_client_side=True, duration_ms=6000,
                       input_count=5, score=5, sequence=correct)
    assert verify_result(slot, "s", faked, issued_at=issued_at, now=submitted_at) is False


def test_without_issued_at_the_wall_clock_check_is_skipped():
    # Documents the opt-in shape: callers that don't have a token's issue
    # timestamp handy (e.g. existing tests above) still get the internal
    # consistency check but not the wall-clock cross-check.
    slot = GameSlot(segment=1, mechanic="simon", params={"length": 5})
    correct = simon_sequence("s", 5)
    result = GameResult(mechanic="simon", passed_client_side=True, duration_ms=999_999_999,
                        input_count=5, score=5, sequence=correct)
    assert verify_result(slot, "s", result) is True


def test_a_large_input_count_claimed_too_soon_after_issuance_is_rejected():
    # The wall-clock check's lower bound: when issued_at is available, the
    # internal duration_ms-vs-input_count floor is REPLACED by a check
    # against real elapsed_ms (server-measured), not the client's own
    # duration_ms claim (see verify_result's docstring for why appending
    # rather than replacing would have been a no-op -- and why this
    # specific test deliberately keeps duration_ms SMALL, so the existing
    # upper-bound check can't accidentally be what catches this instead).
    # A 35-tap `update` segment floors at 2100ms -- bigger than
    # MAX_CLOCK_SLACK_MS (2000ms) -- so claiming 35 taps almost immediately
    # after the token was issued must be rejected regardless of what
    # duration_ms says.
    slot = GameSlot(segment=6, mechanic="update", params={"taps_required": 35})
    issued_at = datetime(2026, 1, 1, tzinfo=UTC)
    submitted_at = issued_at + timedelta(milliseconds=50)  # near-instant

    # duration_ms is small enough that the UPPER bound alone (duration_ms
    # <= elapsed_ms + slack) would happily accept it -- only the lower
    # bound, which ties input_count's physical floor to real elapsed time
    # independent of duration_ms, can reject this.
    claimed = GameResult(mechanic="update", passed_client_side=True, duration_ms=100,
                          input_count=35, score=35, sequence=[])
    assert verify_result(slot, "s", claimed, issued_at=issued_at, now=submitted_at) is False

    # The identical claim, with enough real time actually having passed, is fine.
    later = issued_at + timedelta(milliseconds=2200)
    assert verify_result(slot, "s", claimed, issued_at=issued_at, now=later) is True


def test_drift_requires_surviving_the_configured_duration():
    slot = GameSlot(segment=3, mechanic="drift", params={"duration_ms": 20000, "drift_rate": 1.0})
    survived = GameResult(mechanic="drift", passed_client_side=True, duration_ms=20000,
                          input_count=140, score=20000, sequence=[])
    quit_early = GameResult(mechanic="drift", passed_client_side=True, duration_ms=9000,
                            input_count=60, score=9000, sequence=[])
    idle = GameResult(mechanic="drift", passed_client_side=True, duration_ms=20000,
                      input_count=0, score=20000, sequence=[])
    assert verify_result(slot, "s", survived) is True
    assert verify_result(slot, "s", quit_early) is False
    assert verify_result(slot, "s", idle) is False, "no inputs means nobody played"


def test_verify_result_rejects_a_result_for_the_wrong_mechanic():
    # A malicious or buggy client could submit a well-formed "update" result
    # against a "simon" slot. The mechanic must be pinned to the slot, not
    # accepted from whatever the client claims.
    slot = GameSlot(segment=2, mechanic="update", params={"taps_required": 20})
    mismatched = GameResult(mechanic="simon", passed_client_side=True, duration_ms=9000,
                            input_count=20, score=20, sequence=[])
    assert verify_result(slot, "s", mismatched) is False


def test_trophy_run_requires_hitting_every_prompt():
    slot = GameSlot(segment=4, mechanic="trophy_run", params={"prompts": 6, "window_ms": 1200})
    cleared = GameResult(mechanic="trophy_run", passed_client_side=True, duration_ms=6000,
                         input_count=6, score=6, sequence=[])
    dropped = GameResult(mechanic="trophy_run", passed_client_side=True, duration_ms=6000,
                         input_count=6, score=5, sequence=[])
    assert verify_result(slot, "s", cleared) is True
    assert verify_result(slot, "s", dropped) is False


def test_trophy_run_rejects_a_score_unsupported_by_input_count():
    # A claimed score that exceeds the number of inputs actually made is
    # incoherent -- the score bound alone isn't enough, input_count must
    # independently clear the prompt count too.
    slot = GameSlot(segment=4, mechanic="trophy_run", params={"prompts": 6, "window_ms": 1200})
    inflated = GameResult(mechanic="trophy_run", passed_client_side=True, duration_ms=6000,
                          input_count=3, score=6, sequence=[])
    assert verify_result(slot, "s", inflated) is False


def test_trophy_run_input_count_ceiling_rejects_an_implausible_attempt_count():
    # There are only `prompts` discrete prompts in the segment; a claimed
    # input_count wildly beyond that (even alongside a legitimate score) is
    # not plausible and must be rejected by its own ceiling.
    slot = GameSlot(segment=4, mechanic="trophy_run", params={"prompts": 6, "window_ms": 1200})
    absurd = GameResult(mechanic="trophy_run", passed_client_side=True,
                        duration_ms=6_000_000, input_count=100_000, score=6, sequence=[])
    assert verify_result(slot, "s", absurd) is False


def test_token_round_trips_and_carries_a_seed():
    token, seed = issue_segment_token(run_id=1, segment=3, ttl_seconds=600)
    claim = decode_segment_token(token, max_age=600)
    assert claim.run_id == 1
    assert claim.segment == 3
    assert claim.seed == seed


def test_tampered_token_is_rejected():
    # Flipping only the final character is unreliable: base64's trailing
    # character sometimes carries don't-care bits, so `token[:-1] + "x"`
    # occasionally decodes to the *same* signature bytes and the tamper
    # goes undetected. Replace the whole signature segment instead, which
    # deterministically corrupts it regardless of padding alignment.
    token, _ = issue_segment_token(run_id=1, segment=3, ttl_seconds=600)
    head, _, signature = token.rpartition(".")
    garbage = "A" * len(signature)
    if garbage == signature:
        garbage = "B" * len(signature)
    tampered = f"{head}.{garbage}"
    with pytest.raises(TokenInvalid):
        decode_segment_token(tampered, max_age=600)


def test_expired_token_is_rejected():
    token, _ = issue_segment_token(run_id=1, segment=3, ttl_seconds=600)
    with pytest.raises(TokenInvalid):
        decode_segment_token(token, max_age=-1)


def test_a_short_ttl_genuinely_shrinks_the_expiry_window():
    # ttl_seconds used to be accepted and silently dropped: real expiry was
    # governed entirely by whatever max_age the verifier happened to pass,
    # so tokens issued with ttl_seconds=1 and ttl_seconds=999999 were
    # byte-identical and both decoded fine under the same generous max_age.
    # A short ttl_seconds must now expire the token on its own, even when
    # the verifier's max_age is much larger.
    token, _ = issue_segment_token(run_id=1, segment=3, ttl_seconds=0)
    time.sleep(0.05)
    with pytest.raises(TokenInvalid, match="expired"):
        decode_segment_token(token, max_age=600)

    # A generous ttl_seconds under the same generous max_age still decodes.
    long_token, _ = issue_segment_token(run_id=1, segment=3, ttl_seconds=600)
    claim = decode_segment_token(long_token, max_age=600)
    assert claim.run_id == 1


def test_a_token_signed_under_a_different_secret_is_rejected():
    forged = URLSafeTimedSerializer("a-totally-different-secret", salt=_SALT).dumps(
        {"run_id": 1, "segment": 3, "seed": "x", "nonce": "y"}
    )
    with pytest.raises(TokenInvalid):
        decode_segment_token(forged, max_age=600)


def test_a_token_signed_under_a_different_salt_is_rejected():
    from xxvi.settings import get_settings

    forged = URLSafeTimedSerializer(get_settings().session_secret, salt="different-salt").dumps(
        {"run_id": 1, "segment": 3, "seed": "x", "nonce": "y"}
    )
    with pytest.raises(TokenInvalid):
        decode_segment_token(forged, max_age=600)


async def test_a_token_can_only_be_consumed_once(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    service = TokenService(repo)
    token, _ = issue_segment_token(run_id=run.id, segment=1, ttl_seconds=600)

    await service.consume(token, run_id=run.id)
    with pytest.raises(TokenInvalid, match="consumed"):
        await service.consume(token, run_id=run.id)


async def test_consume_token_does_not_mistake_a_foreign_key_violation_for_a_duplicate(
    fk_enforcing_sessionmaker,
):
    # run_id 999999 does not exist, so the insert violates the FK constraint
    # on ConsumedToken.run_id -- a genuine IntegrityError that is NOT a
    # duplicate nonce. A bare `except IntegrityError` would misread this as
    # "already consumed" and silently swallow a real bug (mirrors
    # test_a_foreign_key_violation_is_not_mistaken_for_a_duplicate_release
    # in tests/test_vault.py, which exercises the identical pattern on
    # CodeRelease).
    repo = RunRepository(fk_enforcing_sessionmaker)
    with pytest.raises(IntegrityError):
        await repo.consume_token(run_id=999999, nonce="whatever", segment=1)


async def test_a_token_issued_for_another_run_is_rejected(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    service = TokenService(repo)
    token, _ = issue_segment_token(run_id=run.id + 999, segment=1, ttl_seconds=600)

    with pytest.raises(TokenInvalid):
        await service.consume(token, run_id=run.id)
