from dataclasses import dataclass, field
from datetime import UTC, datetime

from xxvi.content.schema import GameSlot
from xxvi.games.seeds import simon_sequence

# Nobody presses a key faster than this. Anything quicker did not happen.
MIN_MS_PER_INPUT = 60

# Mechanics where `input_count` is NOT a count of discrete deliberate
# actions, and so cannot be rate-limited by MIN_MS_PER_INPUT.
#
# `drift` is steering. The pull reverses every 3.5s and the correct way to
# play is a rapid stream of arrow taps -- easily several hundred over a
# 20s segment, far faster than one per 60ms. The floor below was written
# for games where each input is an answer (a Simon face, a prompt hit),
# and applying it to steering meant THE BETTER SOMEONE PLAYED, THE MORE
# LIKELY THE SERVER REJECTED THEM: fill the meter early, submit, get told
# you failed. Three of those in a run also awards the drift-denier trophy,
# so the run cheerfully congratulated the player for a bug.
#
# Drift keeps every check that actually models it -- time in zone >=
# hold_ms, duration >= hold_ms, and the wall-clock cap on duration_ms
# below, which is what stops a claimed play time being inflated. Only the
# per-input rate floor is skipped, because it never described this game.
RATE_FLOOR_EXEMPT = frozenset({"drift"})

# Generous slack for real network/processing latency between the browser
# finishing the game and the request landing here. Anything a claimed
# duration exceeds real elapsed wall-clock time by more than this could not
# have happened -- the client cannot claim to have spent more time playing
# than has actually passed since the server issued the token.
MAX_CLOCK_SLACK_MS = 2000

# A tap-mash game where the player keeps going well past the requirement is
# plausible; a claim of unbounded taps is not (e.g. "five million taps
# against a twenty-tap slot"). This is a coarse plausibility ceiling, not a
# game-design spec -- tune alongside the real client if it's ever too tight.
UPDATE_MAX_MULTIPLIER = 10

# A trophy_run has exactly `prompts` discrete prompts, so a score above that
# is structurally impossible -- there is nothing left to hit. input_count
# gets a little more slack for missed/retried attempts within the window.
# Raised from 3 now that a trophy_run has lives: a lost window replays the
# same prompt, so an honest run can legitimately press far more times than
# there are prompts. This is a coarse "did a human do this" ceiling, not a
# game rule -- the real bar is `score == prompts`, which lives cannot inflate
# because a hit is only ever counted once per prompt.
TROPHY_INPUT_MAX_MULTIPLIER = 8

# A stack run ends the moment the target is reached, so the number of drops
# is bounded by the target: every drop either places a block or ends the
# game. A claim of many more drops than blocks placed is not a real run.
#
# NOTE ON WHAT CAN AND CANNOT BE CHECKED HERE: unlike `simon` (whose
# sequence is re-derived from the seed) the stack mechanic is not
# seed-driven -- the block's travel is continuous and the drop points are
# whatever the player made them, so there is nothing for the server to
# re-simulate. This is the same position `update` is in, and it gets the
# same treatment: sanity bands on score, input count and elapsed time
# rather than a re-derivation. The wall-clock cross-check in
# `RunService.submit_game` still applies, so a claimed duration cannot
# exceed the time the token has actually existed.
STACK_INPUT_MAX_MULTIPLIER = 2


@dataclass(frozen=True)
class GameResult:
    mechanic: str
    passed_client_side: bool
    duration_ms: int
    input_count: int
    score: int
    sequence: list[int] = field(default_factory=list)


def verify_result(
    slot: GameSlot,
    seed: str,
    result: GameResult,
    *,
    issued_at: datetime | None = None,
    now: datetime | None = None,
) -> bool:
    """Server-side verdict. `passed_client_side` is advisory and never trusted.

    `issued_at` should be the segment token's own signed issue timestamp
    (`SegmentClaim.issued_at`) whenever one is available -- it lets this
    catch a claimed `duration_ms` that exceeds how much real wall-clock time
    has actually passed since the token was handed out, which the internal
    `duration_ms` vs. `input_count` check alone cannot: a client can solve a
    seeded Simon sequence in under a millisecond (the seed is handed to it
    up front) and simply report a `duration_ms` that clears the per-input
    floor exactly. Without `issued_at` this check is skipped, so callers
    that have a token in hand should always pass it.

    The wall-clock check is two-sided and, when `issued_at` is available,
    REPLACES the internal `duration_ms >= input_count * MIN_MS_PER_INPUT`
    check rather than merely supplementing it -- appending a lower bound
    phrased in terms of `duration_ms` (as an earlier version of this
    function did) is a no-op: `duration_ms >= input_count * MIN_MS_PER_INPUT`
    (the internal check) together with `duration_ms <= elapsed_ms + slack`
    (the upper bound) already ALGEBRAICALLY IMPLY
    `input_count * MIN_MS_PER_INPUT <= elapsed_ms + slack`, so a third check
    stating exactly that can never fire once the first two have already
    passed -- it would be dead code, not a fix. Rephrasing the lower bound
    against server-measured `elapsed_ms` INSTEAD of client-claimed
    `duration_ms`, and dropping the client-claimed version entirely for
    this path, closes the actual gap: `duration_ms` is fully
    attacker-controlled and can be set independently of how much real time
    passed, but `elapsed_ms` cannot be shortened below the genuine gap
    between token issuance and this request landing.

    This narrows, but does not eliminate, the attack it targets:
    `MAX_CLOCK_SLACK_MS` (2000ms) still exceeds the natural per-input floor
    for most configured segments (e.g. a 4-length Simon sequence floors at
    240ms), so an instantly-solved low-floor segment submitted immediately
    still slips under this bound. It reliably catches the same attack
    against segments whose floor approaches or exceeds the slack (e.g. a
    35-tap `update` segment, floor 2100ms). Tightening `MAX_CLOCK_SLACK_MS`
    itself would close more of the gap but risks false-rejecting genuine
    players on slow connections; that tradeoff is left for a content/ops
    decision, not made silently here.
    """
    if result.mechanic != slot.mechanic:
        return False
    rate_floor_applies = slot.mechanic not in RATE_FLOOR_EXEMPT
    if issued_at is not None:
        current = now if now is not None else datetime.now(UTC)
        elapsed_ms = (current - issued_at).total_seconds() * 1000
        # This one always applies: a claimed play time longer than the token
        # has existed is impossible for every mechanic.
        if result.duration_ms > elapsed_ms + MAX_CLOCK_SLACK_MS:
            return False
        if rate_floor_applies and (
            elapsed_ms + MAX_CLOCK_SLACK_MS < result.input_count * MIN_MS_PER_INPUT
        ):
            return False
    elif rate_floor_applies and result.duration_ms < result.input_count * MIN_MS_PER_INPUT:
        return False

    match slot.mechanic:
        case "simon":
            length = int(slot.params.get("length", 4))
            return result.sequence == simon_sequence(seed, length)
        case "update":
            required = int(slot.params.get("taps_required", 20))
            return required <= result.input_count <= required * UPDATE_MAX_MULTIPLIER
        case "drift":
            # THE TARGET ZONE IS NOW THE GAME. It used to be decorative --
            # the client marked it "cosmetic only" and the only real rule
            # was "don't reach either edge of the track". With unaided
            # drift at 5 units/s across a 100-unit track and a 20s segment,
            # that meant doing NOTHING failed you at almost exactly the
            # moment you would have won, and a single keypress won. The
            # screen said "hold it steady" and holding it steady was not
            # the thing being measured.
            #
            # `score` carries milliseconds spent inside the zone. Passing
            # now requires having actually held it there. `hold_ms`
            # defaults to 60% of the segment, which leaves real room to
            # wander without making it a formality.
            duration = int(slot.params.get("duration_ms", 20000))
            required_hold = int(slot.params.get("hold_ms", duration * 0.6))
            # NOT `duration_ms >= duration`. Filling the meter ends the
            # segment early and that is the intended win, so demanding the
            # full wall-clock window would have rejected exactly the runs
            # that played it best. `duration` is a deadline now; the only
            # floor is that he cannot have held the zone for longer than he
            # played, and `RunService.submit_game` separately caps
            # `duration_ms` against real elapsed time since the token was
            # issued, so neither number can be inflated.
            return (
                result.input_count > 0
                and result.score >= required_hold
                and result.duration_ms >= required_hold
            )
        case "stack":
            target = int(slot.params.get("target", 8))
            return (
                result.score >= target
                # Every placed block is one drop, so drops can never be
                # fewer than blocks.
                and result.input_count >= result.score
                and result.input_count <= max(1, result.score) * STACK_INPUT_MAX_MULTIPLIER
            )
        case "trophy_run":
            prompts = int(slot.params.get("prompts", 6))
            return (
                result.score == prompts
                and prompts <= result.input_count <= prompts * TROPHY_INPUT_MAX_MULTIPLIER
            )
        case _:
            return False
