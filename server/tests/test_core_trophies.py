from xxvi.core.models import Difficulty, Event, Phase, RunState, Shape
from xxvi.core.trophies import (
    PLATINUM_ID,
    platinum_earned,
    required_for_platinum,
    trophy_for,
    wipe_trophies,
)

SHAPE = Shape(acts=2, segments_per_act=4)


def state(segment: int, phase: Phase) -> RunState:
    return RunState(phase=phase, difficulty=Difficulty.KIDDIE, segment=segment)


def test_passing_a_game_awards_that_segments_game_trophy():
    assert trophy_for(state(3, Phase.GAME), Event.GAME_PASSED, SHAPE) == "game-3"


def test_passing_a_question_awards_that_segments_question_trophy():
    assert trophy_for(state(6, Phase.QUESTION), Event.QUESTION_PASSED, SHAPE) == "question-6"


def test_passing_a_checkpoint_awards_the_act_trophy():
    assert trophy_for(state(8, Phase.CHECKPOINT), Event.CHECKPOINT_PASSED, SHAPE) == "act-2"


def test_failures_award_nothing():
    assert trophy_for(state(3, Phase.GAME), Event.GAME_FAILED, SHAPE) is None


def test_question_failures_award_nothing():
    assert trophy_for(state(6, Phase.QUESTION), Event.QUESTION_FAILED, SHAPE) is None


def test_platinum_requires_all_eighteen_others():
    required = required_for_platinum(SHAPE)
    assert len(required) == 18
    assert PLATINUM_ID not in required
    assert not platinum_earned(required - {"question-8"}, SHAPE)
    assert platinum_earned(required, SHAPE)


def test_hidden_trophies_do_not_gate_the_platinum():
    earned = required_for_platinum(SHAPE) | {"hidden-rage-quit"}
    assert platinum_earned(earned, SHAPE)


def test_a_wipe_clears_segment_trophies_but_keeps_hidden_ones():
    earned = frozenset({"game-1", "question-1", "act-1", "hidden-rage-quit"})
    assert wipe_trophies(earned) == frozenset({"hidden-rage-quit"})


def test_a_wipe_only_keeps_ids_that_start_with_the_hidden_prefix():
    # "my-hidden-thing" contains "hidden-" as a substring but does not start
    # with it, and must not survive the wipe. "un-hidden-1" is the same
    # shape of trap. Only a true prefix match should be kept.
    earned = frozenset({"my-hidden-thing", "un-hidden-1", "hidden-rage-quit"})
    assert wipe_trophies(earned) == frozenset({"hidden-rage-quit"})


def test_platinum_prerequisites_are_derived_from_shape_not_hardcoded():
    other_shape = Shape(acts=3, segments_per_act=3)
    required = required_for_platinum(other_shape)
    assert len(required) == 21
    assert PLATINUM_ID not in required
    assert {f"act-{a}" for a in (1, 2, 3)} <= required
    assert {f"game-{n}" for n in range(1, 10)} <= required
    assert {f"question-{n}" for n in range(1, 10)} <= required

    # Missing one prerequisite under this shape must gate the platinum.
    assert not platinum_earned(required - {"act-3"}, other_shape)
    assert platinum_earned(required, other_shape)

    # A trophy set that is exactly the SHAPE=(2,4) requirements (18 ids) is
    # neither complete nor a superset of what Shape(3, 3) demands (21 ids):
    # it must not satisfy platinum_earned under the other shape. This is
    # only distinguishing if platinum_earned actually consults its `shape`
    # argument rather than a hardcoded default.
    assert not platinum_earned(required_for_platinum(SHAPE), other_shape)
