"""Verification rules that are about the SHAPE of a submitted run rather
than about any one mechanic's content."""

from datetime import UTC, datetime, timedelta

from xxvi.content.schema import GameSlot
from xxvi.games.verify import GameResult, verify_result

# ---------------------------------------------------------------------------
# The rate floor must not punish steering.
# ---------------------------------------------------------------------------

def test_a_well_played_drift_run_is_not_rejected_for_tapping_too_fast():
    """Observed live: fill the meter, submit, get told you failed.

    `drift`'s input_count is arrow taps. The pull reverses every 3.5s so the
    correct way to play is a rapid stream of them -- several hundred over a
    20s segment. MIN_MS_PER_INPUT (60ms) was written for mechanics where an
    input is an answer, and applying it here meant the better someone
    played, the more likely the server rejected the run.
    """
    slot = GameSlot(segment=3, mechanic="drift",
                    params={"duration_ms": 20000, "hold_ms": 11000})
    issued = datetime.now(UTC) - timedelta(milliseconds=12000)
    # 300 taps in 12s is ~40ms apart: entirely reachable, and well under the
    # 60ms floor that used to reject it.
    result = GameResult(mechanic="drift", passed_client_side=True,
                        duration_ms=11500, input_count=300, score=11200)

    assert verify_result(slot, "seed", result, issued_at=issued) is True


def test_the_rate_floor_still_applies_to_mechanics_it_describes():
    """Exempting drift must not quietly exempt everything else."""
    slot = GameSlot(segment=4, mechanic="trophy_run",
                    params={"prompts": 6, "window_ms": 1200})
    issued = datetime.now(UTC) - timedelta(milliseconds=200)
    result = GameResult(mechanic="trophy_run", passed_client_side=True,
                        duration_ms=200, input_count=300, score=6)

    assert verify_result(slot, "seed", result, issued_at=issued) is False


def test_drift_still_cannot_claim_more_play_time_than_the_token_has_existed():
    """The exemption is the rate floor only -- not the wall-clock cap."""
    slot = GameSlot(segment=3, mechanic="drift",
                    params={"duration_ms": 20000, "hold_ms": 11000})
    issued = datetime.now(UTC) - timedelta(milliseconds=500)
    result = GameResult(mechanic="drift", passed_client_side=True,
                        duration_ms=11500, input_count=10, score=11200)

    assert verify_result(slot, "seed", result, issued_at=issued) is False


def test_a_long_stack_run_is_not_rejected_for_taking_its_time():
    """A stack segment is bounded by a TARGET, not a clock.

    At 166 blocks a careful player can genuinely be playing for the better
    part of ten minutes. The old 600s token TTL rejected exactly that run,
    after all of it, and the rejection is indistinguishable on screen from
    missing — the worst possible way to lose a perfect run.
    """
    from xxvi.games.tokens import DEFAULT_SEGMENT_TTL_SECONDS

    slot = GameSlot(segment=6, mechanic="stack", params={"target": 166})
    played_for_ms = 9 * 60 * 1000  # nine minutes of flawless stacking
    issued = datetime.now(UTC) - timedelta(milliseconds=played_for_ms + 1500)
    result = GameResult(mechanic="stack", passed_client_side=True,
                        duration_ms=played_for_ms, input_count=166, score=166)

    assert DEFAULT_SEGMENT_TTL_SECONDS * 1000 > played_for_ms, (
        "the token must outlive the run it is issued for"
    )
    assert verify_result(slot, "seed", result, issued_at=issued) is True
