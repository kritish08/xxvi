# server/tests/test_core_machine.py
import dataclasses

import pytest

from xxvi.core.machine import InvalidTransition, advance
from xxvi.core.models import Difficulty, Event, Phase, RunState, Shape, initial_state

SHAPE = Shape(acts=2, segments_per_act=4)

# The configured devil-mode life pool used throughout this file's DEVIL
# fixtures. Deliberately exercised against a *different* value too (see
# test_devil_life_pool_size_is_read_from_devil_lives_not_hardcoded) so a
# hardcoded "3" in the machine can't hide behind this constant happening to
# equal the content-layer default.
DEVIL_LIVES = 3


def at_segment(n: int, phase: Phase, difficulty: Difficulty, cleared=frozenset(), released=frozenset(),
               lives=None):
    return RunState(phase=phase, difficulty=difficulty, segment=n,
                    cleared_segments=cleared, released_rewards=released, lives=lives)


def test_preamble_walks_activation_to_first_game():
    state = initial_state()
    for event in (Event.ACTIVATED, Event.PROFILE_CHOSEN):
        state = advance(state, event, SHAPE)
    assert state.phase is Phase.DIFFICULTY

    state = advance(state, Event.DIFFICULTY_CHOSEN, SHAPE, difficulty=Difficulty.DEVIL,
                     devil_lives=DEVIL_LIVES)
    assert state.difficulty is Difficulty.DEVIL
    assert state.lives == DEVIL_LIVES, "choosing DEVIL grants the full configured life pool"

    state = advance(state, Event.INSTALLED, SHAPE)
    state = advance(state, Event.HOWTO_ACKED, SHAPE)
    assert state.phase is Phase.GAME
    assert state.segment == 1


def test_game_pass_moves_to_question_same_segment():
    state = at_segment(3, Phase.GAME, Difficulty.KIDDIE)
    result = advance(state, Event.GAME_PASSED, SHAPE)
    assert result.phase is Phase.QUESTION
    assert result.segment == 3


def test_question_pass_clears_segment_and_advances():
    state = at_segment(2, Phase.QUESTION, Difficulty.KIDDIE, cleared=frozenset({1}))
    result = advance(state, Event.QUESTION_PASSED, SHAPE)
    assert result.cleared_segments == frozenset({1, 2})
    assert result.segment == 3
    assert result.phase is Phase.GAME


def test_last_segment_of_act_leads_to_checkpoint():
    state = at_segment(4, Phase.QUESTION, Difficulty.KIDDIE, cleared=frozenset({1, 2, 3}))
    result = advance(state, Event.QUESTION_PASSED, SHAPE)
    assert result.phase is Phase.CHECKPOINT
    assert result.segment == 4


def test_checkpoint_releases_reward_and_opens_next_act():
    state = at_segment(4, Phase.CHECKPOINT, Difficulty.KIDDIE, cleared=frozenset({1, 2, 3, 4}))
    result = advance(state, Event.CHECKPOINT_PASSED, SHAPE)
    assert result.released_rewards == frozenset({1})
    assert result.segment == 5
    assert result.phase is Phase.GAME


def test_final_checkpoint_completes_the_run():
    state = at_segment(8, Phase.CHECKPOINT, Difficulty.DEVIL,
                       cleared=frozenset(range(1, 9)), released=frozenset({1}))
    result = advance(state, Event.CHECKPOINT_PASSED, SHAPE)
    assert result.phase is Phase.COMPLETE
    assert result.released_rewards == frozenset({1, 2})


# --- Checkpoints must never touch lives -- not to refill, not by any amount.
# One life pool for the entire run, "not refilled at checkpoints" per the
# brief. Parametrized over lives=1 and lives=2 (not just a "full" pool)
# specifically because an off-by-one refill (e.g. bumping a depleted pool
# back up by one instead of leaving it alone) is the likeliest regression
# shape, and would be invisible if the pool already happened to be full.
@pytest.mark.parametrize("lives_before", [1, 2])
def test_checkpoint_pass_does_not_refill_devil_lives_mid_run(lives_before):
    state = at_segment(4, Phase.CHECKPOINT, Difficulty.DEVIL,
                        cleared=frozenset({1, 2, 3, 4}), lives=lives_before)
    result = advance(state, Event.CHECKPOINT_PASSED, SHAPE)
    assert result.lives == lives_before
    assert result.phase is Phase.GAME
    assert result.segment == 5


@pytest.mark.parametrize("lives_before", [1, 2])
def test_final_checkpoint_pass_does_not_refill_devil_lives(lives_before):
    state = at_segment(8, Phase.CHECKPOINT, Difficulty.DEVIL,
                        cleared=frozenset(range(1, 9)), released=frozenset({1}),
                        lives=lives_before)
    result = advance(state, Event.CHECKPOINT_PASSED, SHAPE)
    assert result.lives == lives_before
    assert result.phase is Phase.COMPLETE


@pytest.mark.parametrize("failure", [Event.GAME_FAILED, Event.QUESTION_FAILED])
@pytest.mark.parametrize("segment", range(1, 9))
def test_kiddie_failure_restarts_only_the_current_segment(segment, failure):
    cleared = frozenset(range(1, segment))
    released = frozenset({1}) if segment > 4 else frozenset()
    phase = Phase.GAME if failure is Event.GAME_FAILED else Phase.QUESTION
    state = at_segment(segment, phase, Difficulty.KIDDIE, cleared=cleared, released=released)

    result = advance(state, failure, SHAPE)

    assert result.segment == segment
    assert result.phase is Phase.GAME, "restart means the whole segment, game first"
    assert result.cleared_segments == cleared
    assert result.released_rewards == released


# --- Devil mode now costs a life per failure and only wipes on the failure
# that exhausts the last one. One pool for the whole run: not per segment,
# not refilled at checkpoints. This used to be a single 16-case sweep
# asserting an immediate wipe; it is now two 16-case sweeps -- one per
# distinct outcome -- so coverage of every (segment, failure-kind)
# combination is preserved for *both* the decrement path and the exhaustion
# path, rather than narrowed.
@pytest.mark.parametrize("failure", [Event.GAME_FAILED, Event.QUESTION_FAILED])
@pytest.mark.parametrize("segment", range(1, 9))
def test_devil_failure_with_lives_remaining_decrements_and_replays_segment(segment, failure):
    cleared = frozenset(range(1, segment))
    released = frozenset({1}) if segment > 4 else frozenset()
    phase = Phase.GAME if failure is Event.GAME_FAILED else Phase.QUESTION
    state = at_segment(segment, phase, Difficulty.DEVIL, cleared=cleared, released=released,
                        lives=DEVIL_LIVES)

    result = advance(state, failure, SHAPE, devil_lives=DEVIL_LIVES)

    assert result.lives == DEVIL_LIVES - 1
    assert result.segment == segment, "one life pool for the run -- replay in place, not a wipe"
    assert result.phase is Phase.GAME, "restart means the whole segment, game first"
    assert result.cleared_segments == cleared, "cleared_segments untouched while lives remain"
    assert result.released_rewards == released, "earned codes are never revoked"


@pytest.mark.parametrize("failure", [Event.GAME_FAILED, Event.QUESTION_FAILED])
@pytest.mark.parametrize("segment", range(1, 9))
def test_devil_failure_exhausting_the_last_life_wipes_and_restores_lives_to_full(segment, failure):
    cleared = frozenset(range(1, segment))
    released = frozenset({1}) if segment > 4 else frozenset()
    phase = Phase.GAME if failure is Event.GAME_FAILED else Phase.QUESTION
    state = at_segment(segment, phase, Difficulty.DEVIL, cleared=cleared, released=released,
                        lives=1)

    result = advance(state, failure, SHAPE, devil_lives=DEVIL_LIVES)

    assert result.segment == 1
    assert result.phase is Phase.GAME
    assert result.cleared_segments == frozenset()
    assert result.released_rewards == released, "earned codes are never revoked"
    assert result.lives == DEVIL_LIVES, "without the restore, the second run is unwinnable"


def test_devil_wipe_in_act_two_keeps_reward_one():
    state = at_segment(7, Phase.GAME, Difficulty.DEVIL,
                       cleared=frozenset({1, 2, 3, 4, 5, 6}), released=frozenset({1}),
                       lives=1)
    result = advance(state, Event.GAME_FAILED, SHAPE, devil_lives=DEVIL_LIVES)
    assert result.released_rewards == frozenset({1})
    assert result.segment == 1
    assert result.lives == DEVIL_LIVES


def test_events_out_of_phase_are_rejected():
    state = at_segment(1, Phase.GAME, Difficulty.KIDDIE)
    with pytest.raises(InvalidTransition):
        advance(state, Event.CHECKPOINT_PASSED, SHAPE)


def test_advance_never_mutates_the_input_state():
    state = at_segment(2, Phase.QUESTION, Difficulty.DEVIL, cleared=frozenset({1}), lives=DEVIL_LIVES)
    advance(state, Event.QUESTION_FAILED, SHAPE, devil_lives=DEVIL_LIVES)
    assert state.segment == 2
    assert state.cleared_segments == frozenset({1})


# --- C1: every (phase, event) pair that is NOT a legal transition must raise. ---
#
# The legal set is built explicitly from what advance() actually accepts today
# (including the fact that GAME_FAILED and QUESTION_FAILED are both accepted in
# both the GAME and QUESTION phases — the phase check in advance() only cares
# that the phase is one of {GAME, QUESTION}, not which specific failure event
# named itself after which phase). Everything not in this set is illegal and
# must raise InvalidTransition; the test derives the illegal pairs from this
# set rather than hand-listing 78 cases.
_LEGAL_TRANSITIONS: set[tuple[Phase, Event]] = {
    (Phase.ACTIVATION, Event.ACTIVATED),
    (Phase.PROFILE, Event.PROFILE_CHOSEN),
    (Phase.DIFFICULTY, Event.DIFFICULTY_CHOSEN),
    (Phase.INSTALL, Event.INSTALLED),
    (Phase.HOWTO, Event.HOWTO_ACKED),
    (Phase.GAME, Event.GAME_PASSED),
    (Phase.GAME, Event.GAME_FAILED),
    (Phase.GAME, Event.QUESTION_FAILED),
    (Phase.QUESTION, Event.QUESTION_PASSED),
    (Phase.QUESTION, Event.QUESTION_FAILED),
    (Phase.QUESTION, Event.QUESTION_MISSED),
    (Phase.QUESTION, Event.GAME_FAILED),
    (Phase.CHECKPOINT, Event.CHECKPOINT_PASSED),
}

_ALL_PHASE_EVENT_PAIRS = [(phase, event) for phase in Phase for event in Event]
_ILLEGAL_PHASE_EVENT_PAIRS = [
    pair for pair in _ALL_PHASE_EVENT_PAIRS if pair not in _LEGAL_TRANSITIONS
]

assert len(_ALL_PHASE_EVENT_PAIRS) == len(Phase) * len(Event)
assert len(_LEGAL_TRANSITIONS) == 13
assert len(_ILLEGAL_PHASE_EVENT_PAIRS) == len(_ALL_PHASE_EVENT_PAIRS) - 13


@pytest.mark.parametrize(
    "phase,event",
    _ILLEGAL_PHASE_EVENT_PAIRS,
    ids=[f"{phase.value}-{event.value}" for phase, event in _ILLEGAL_PHASE_EVENT_PAIRS],
)
def test_every_illegal_phase_event_pair_raises(phase, event):
    state = RunState(phase=phase, difficulty=Difficulty.KIDDIE, segment=1)
    with pytest.raises(InvalidTransition):
        advance(state, event, SHAPE, difficulty=Difficulty.KIDDIE)


# --- I3: the missing-difficulty guard on DIFFICULTY_CHOSEN, tested explicitly. ---
# (DIFFICULTY, DIFFICULTY_CHOSEN) is a *legal* pair, so C1's illegal-pair sweep
# above does not exercise this failure mode: it is a legal transition missing a
# required kwarg, not an illegal phase/event pair.
def test_difficulty_chosen_without_a_difficulty_kwarg_raises():
    state = RunState(phase=Phase.DIFFICULTY)
    with pytest.raises(InvalidTransition):
        advance(state, Event.DIFFICULTY_CHOSEN, SHAPE)


# --- C2: the act boundary must be exercised at every segment, including inside
# Act II (segments 5, 6, 7), not just at the true boundaries (4, 8). This is
# what catches `segment % segments_per_act == 0` being weakened to
# `segment >= segments_per_act`, which would send segment 5 straight to
# CHECKPOINT and release the Act II reward one segment into Act II.
@pytest.mark.parametrize("segment", range(1, 9))
def test_question_passed_reaches_checkpoint_only_at_true_act_boundaries(segment):
    cleared_before = frozenset(range(1, segment))
    state = at_segment(segment, Phase.QUESTION, Difficulty.KIDDIE, cleared=cleared_before)
    result = advance(state, Event.QUESTION_PASSED, SHAPE)

    assert result.cleared_segments == cleared_before | {segment}

    if segment in (4, 8):
        assert result.phase is Phase.CHECKPOINT, f"segment {segment} is a true act boundary"
        assert result.segment == segment
    else:
        assert result.phase is Phase.GAME, f"segment {segment} must NOT trigger a checkpoint"
        assert result.segment == segment + 1


# --- I1: immutability of the input state, across every legal transition
# (not just one), including both difficulties for the failure paths so both
# the KIDDIE restart-in-place path and the DEVIL wipe-to-segment-1 path are
# each checked for accidental in-place mutation.
_IMMUTABILITY_CASES = [
    ("activation", RunState(phase=Phase.ACTIVATION), Event.ACTIVATED, {}),
    ("profile", RunState(phase=Phase.PROFILE), Event.PROFILE_CHOSEN, {}),
    (
        "difficulty_chosen",
        RunState(phase=Phase.DIFFICULTY),
        Event.DIFFICULTY_CHOSEN,
        {"difficulty": Difficulty.KIDDIE},
    ),
    (
        "difficulty_chosen_devil",
        RunState(phase=Phase.DIFFICULTY),
        Event.DIFFICULTY_CHOSEN,
        {"difficulty": Difficulty.DEVIL, "devil_lives": DEVIL_LIVES},
    ),
    (
        "install",
        RunState(phase=Phase.INSTALL, difficulty=Difficulty.KIDDIE),
        Event.INSTALLED,
        {},
    ),
    (
        "howto",
        RunState(phase=Phase.HOWTO, difficulty=Difficulty.KIDDIE),
        Event.HOWTO_ACKED,
        {},
    ),
    (
        "game_passed",
        at_segment(3, Phase.GAME, Difficulty.KIDDIE, cleared=frozenset({1, 2})),
        Event.GAME_PASSED,
        {},
    ),
    (
        "game_failed_kiddie",
        at_segment(3, Phase.GAME, Difficulty.KIDDIE, cleared=frozenset({1, 2})),
        Event.GAME_FAILED,
        {},
    ),
    (
        "game_failed_devil",
        at_segment(3, Phase.GAME, Difficulty.DEVIL, cleared=frozenset({1, 2}), lives=DEVIL_LIVES),
        Event.GAME_FAILED,
        {"devil_lives": DEVIL_LIVES},
    ),
    (
        "question_passed",
        at_segment(2, Phase.QUESTION, Difficulty.KIDDIE, cleared=frozenset({1})),
        Event.QUESTION_PASSED,
        {},
    ),
    (
        "question_passed_at_act_boundary",
        at_segment(4, Phase.QUESTION, Difficulty.KIDDIE, cleared=frozenset({1, 2, 3})),
        Event.QUESTION_PASSED,
        {},
    ),
    (
        "question_failed_kiddie",
        at_segment(2, Phase.QUESTION, Difficulty.KIDDIE, cleared=frozenset({1})),
        Event.QUESTION_FAILED,
        {},
    ),
    (
        "question_failed_devil",
        at_segment(2, Phase.QUESTION, Difficulty.DEVIL, cleared=frozenset({1}), lives=DEVIL_LIVES),
        Event.QUESTION_FAILED,
        {"devil_lives": DEVIL_LIVES},
    ),
    (
        "checkpoint_mid_run",
        at_segment(4, Phase.CHECKPOINT, Difficulty.KIDDIE, cleared=frozenset({1, 2, 3, 4})),
        Event.CHECKPOINT_PASSED,
        {},
    ),
    (
        "checkpoint_final",
        at_segment(
            8,
            Phase.CHECKPOINT,
            Difficulty.DEVIL,
            cleared=frozenset(range(1, 9)),
            released=frozenset({1}),
        ),
        Event.CHECKPOINT_PASSED,
        {},
    ),
]


@pytest.mark.parametrize(
    "label,state,event,kwargs",
    _IMMUTABILITY_CASES,
    ids=[case[0] for case in _IMMUTABILITY_CASES],
)
def test_advance_never_mutates_input_across_every_transition(label, state, event, kwargs):
    before = dataclasses.asdict(state)
    advance(state, event, SHAPE, **kwargs)
    after = dataclasses.asdict(state)
    assert before == after


# --- I2: shape-agnosticism. Everything above uses Shape(2, 4); run a full
# happy path under a different shape to catch anything hardcoded to 8/4/2.
def test_full_happy_path_under_a_different_shape():
    shape = Shape(acts=3, segments_per_act=3)
    state = initial_state()
    for event in (Event.ACTIVATED, Event.PROFILE_CHOSEN):
        state = advance(state, event, shape)
    state = advance(state, Event.DIFFICULTY_CHOSEN, shape, difficulty=Difficulty.KIDDIE)
    state = advance(state, Event.INSTALLED, shape)
    state = advance(state, Event.HOWTO_ACKED, shape)
    assert state.phase is Phase.GAME
    assert state.segment == 1

    checkpoints_seen = 0
    for segment in range(1, shape.total + 1):
        state = advance(state, Event.GAME_PASSED, shape)
        assert state.phase is Phase.QUESTION
        state = advance(state, Event.QUESTION_PASSED, shape)
        if segment % shape.segments_per_act == 0:
            assert state.phase is Phase.CHECKPOINT
            state = advance(state, Event.CHECKPOINT_PASSED, shape)
            checkpoints_seen += 1
        else:
            assert state.phase is Phase.GAME

    assert checkpoints_seen == shape.acts == 3
    assert state.phase is Phase.COMPLETE
    assert state.released_rewards == frozenset({1, 2, 3})
    assert state.cleared_segments == frozenset(range(1, shape.total + 1))


# --- I4: Shape.total has to actually multiply, not e.g. add. ---
def test_shape_total_multiplies_acts_by_segments_per_act():
    assert Shape(acts=2, segments_per_act=4).total == 8
    assert Shape(acts=3, segments_per_act=5).total == 15
    assert Shape(acts=1, segments_per_act=1).total == 1


# --- M1: fail closed. An unset/unknown difficulty reaching a failure event
# must never be treated as DEVIL by default — it must be rejected outright.
# This path is unreachable via advance()'s own preamble today (DIFFICULTY_CHOSEN
# always sets a real Difficulty before GAME/QUESTION become reachable), but a
# RunState rehydrated from persisted storage with a missing/corrupt difficulty
# must not silently route a player down the harsher DEVIL wipe.
def test_apply_failure_with_missing_difficulty_raises_instead_of_defaulting_to_devil():
    state = RunState(
        phase=Phase.GAME,
        difficulty=None,
        segment=3,
        cleared_segments=frozenset({1, 2}),
    )
    with pytest.raises(InvalidTransition):
        advance(state, Event.GAME_FAILED, SHAPE)


# --- M2/M3: persistence rehydration must yield real enum members, never raw
# strings. A RunState assembled from a DB row with `difficulty="kiddie"` (a
# plain str, not `Difficulty.KIDDIE`) looks equal but is not identical, and
# `_apply_failure` compares with `is`. These two tests pin that directly at
# the machine level, independent of the persistence layer: any repository
# that skips `Difficulty(row.difficulty)` / `Phase(row.phase)` construction
# and passes the raw string through will make both of these start failing to
# raise (M2) or start raising where it shouldn't (M3).
def test_apply_failure_with_raw_string_difficulty_raises():
    # "kiddie" == Difficulty.KIDDIE by value, but is not the same object.
    state = RunState(phase=Phase.GAME, difficulty="kiddie", segment=3,
                      cleared_segments=frozenset({1, 2}))
    with pytest.raises(InvalidTransition):
        advance(state, Event.GAME_FAILED, SHAPE)


def test_advance_rejects_raw_string_phase_even_though_it_equals_the_enum():
    # "game" == Phase.GAME by value (StrEnum), but advance() routes on `is`,
    # so a raw string must be rejected rather than silently accepted.
    state = RunState(phase="game", difficulty=Difficulty.KIDDIE, segment=3)
    with pytest.raises(InvalidTransition):
        advance(state, Event.GAME_PASSED, SHAPE)


# --- Devil lives: everything below is new for task 6b. ---

def test_kiddie_failure_never_touches_lives():
    # Lives are irrelevant to KIDDIE. A stray non-None value (as if left
    # over in a rehydrated state from an earlier difficulty choice) must
    # pass straight through, not be read, decremented, or cleared.
    state = at_segment(3, Phase.GAME, Difficulty.KIDDIE, lives=2)
    result = advance(state, Event.GAME_FAILED, SHAPE, devil_lives=DEVIL_LIVES)
    assert result.lives == 2


def test_difficulty_chosen_to_kiddie_does_not_require_devil_lives_and_lives_stays_none():
    state = RunState(phase=Phase.DIFFICULTY)
    result = advance(state, Event.DIFFICULTY_CHOSEN, SHAPE, difficulty=Difficulty.KIDDIE)
    assert result.lives is None


def test_difficulty_chosen_to_devil_grants_the_configured_life_pool():
    state = RunState(phase=Phase.DIFFICULTY)
    result = advance(state, Event.DIFFICULTY_CHOSEN, SHAPE, difficulty=Difficulty.DEVIL,
                      devil_lives=7)
    assert result.lives == 7


def test_difficulty_chosen_to_devil_without_devil_lives_raises():
    state = RunState(phase=Phase.DIFFICULTY)
    with pytest.raises(InvalidTransition):
        advance(state, Event.DIFFICULTY_CHOSEN, SHAPE, difficulty=Difficulty.DEVIL)


def test_devil_failure_without_devil_lives_raises():
    # Fail closed, same idiom as the missing/unknown-difficulty guard: the
    # machine cannot compute a decrement or a restore-to-full without
    # knowing the configured pool size, so it must refuse rather than guess.
    state = at_segment(3, Phase.GAME, Difficulty.DEVIL, lives=2)
    with pytest.raises(InvalidTransition):
        advance(state, Event.GAME_FAILED, SHAPE)


def test_devil_failure_with_missing_lives_on_state_raises():
    # A DEVIL state that somehow never had lives granted (corrupt/incomplete
    # rehydration) must not be treated as though it had a life to spend.
    state = at_segment(3, Phase.GAME, Difficulty.DEVIL, lives=None)
    with pytest.raises(InvalidTransition):
        advance(state, Event.GAME_FAILED, SHAPE, devil_lives=DEVIL_LIVES)


def test_devil_life_pool_size_is_read_from_devil_lives_not_hardcoded():
    # If the pool size were hardcoded to 3 anywhere in the machine, this
    # would fail: with devil_lives=5, a decrement must land on 4 (not 2) and
    # an exhaustion-wipe must restore to 5 (not 3).
    decremented = advance(
        at_segment(3, Phase.GAME, Difficulty.DEVIL, lives=5),
        Event.GAME_FAILED, SHAPE, devil_lives=5,
    )
    assert decremented.lives == 4

    wiped = advance(
        at_segment(3, Phase.GAME, Difficulty.DEVIL, lives=1),
        Event.GAME_FAILED, SHAPE, devil_lives=5,
    )
    assert wiped.lives == 5

    granted = advance(
        RunState(phase=Phase.DIFFICULTY), Event.DIFFICULTY_CHOSEN, SHAPE,
        difficulty=Difficulty.DEVIL, devil_lives=5,
    )
    assert granted.lives == 5


# --- Per-question attempt allowance ---
# `question_attempts` must mean "spent on the question in front of him right
# now". Every transition that starts or ends a question therefore zeroes it,
# and each of those resets is asserted here rather than through the API: the
# API can only reach them via paths where some *other* reset already ran, so
# an API-level test passes even when one of these lines is deleted.


def test_starting_a_question_always_restores_the_full_allowance():
    # The load-bearing one. Entering QUESTION must guarantee a clean counter
    # locally, rather than trusting every predecessor to have zeroed it --
    # including a state rehydrated from a row written by an older build.
    state = RunState(
        phase=Phase.GAME, difficulty=Difficulty.KIDDIE, segment=2, question_attempts=2
    )
    assert advance(state, Event.GAME_PASSED, SHAPE).question_attempts == 0


def test_a_miss_spends_exactly_one_attempt_and_moves_nothing_else():
    state = RunState(
        phase=Phase.QUESTION, difficulty=Difficulty.DEVIL, segment=3, lives=3,
        cleared_segments=frozenset({1, 2}), question_attempts=1,
    )
    after = advance(state, Event.QUESTION_MISSED, SHAPE, devil_lives=3)
    assert after.question_attempts == 2
    assert after == dataclasses.replace(state, question_attempts=2), (
        "a miss must touch nothing but the counter -- not the phase, not the "
        "lives, not the cleared segments"
    )


def test_clearing_a_segment_resets_the_allowance():
    state = RunState(
        phase=Phase.QUESTION, difficulty=Difficulty.KIDDIE, segment=1, question_attempts=2
    )
    assert advance(state, Event.QUESTION_PASSED, SHAPE).question_attempts == 0


def test_reaching_a_checkpoint_resets_the_allowance():
    state = RunState(
        phase=Phase.QUESTION, difficulty=Difficulty.KIDDIE, segment=4, question_attempts=2
    )
    after = advance(state, Event.QUESTION_PASSED, SHAPE)
    assert after.phase is Phase.CHECKPOINT
    assert after.question_attempts == 0


@pytest.mark.parametrize("difficulty", [Difficulty.KIDDIE, Difficulty.DEVIL])
def test_a_terminal_failure_resets_the_allowance(difficulty):
    state = RunState(
        phase=Phase.QUESTION, difficulty=difficulty, segment=2, question_attempts=2,
        lives=3 if difficulty is Difficulty.DEVIL else None,
    )
    after = advance(state, Event.QUESTION_FAILED, SHAPE, devil_lives=3)
    assert after.phase is Phase.GAME
    assert after.question_attempts == 0, "the replayed question starts fresh"


def test_the_devil_wipe_also_resets_the_allowance():
    state = RunState(
        phase=Phase.QUESTION, difficulty=Difficulty.DEVIL, segment=5, lives=1,
        cleared_segments=frozenset({1, 2, 3, 4}), question_attempts=2,
    )
    after = advance(state, Event.QUESTION_FAILED, SHAPE, devil_lives=3)
    assert after.segment == 1 and after.lives == 3
    assert after.question_attempts == 0
