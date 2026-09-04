"""Scoring is derived, never stored.

A score is a pure function of (config, cleared_segments), so enabling or
retuning points never needs a migration and never touches the run row --
which is what keeps it clear of the optimistic-concurrency machinery on
`Run.version`.
"""

from tests.factories import make_config
from xxvi.content.scoring import score_for

QUESTIONS_WITH_POINTS = [
    {"prompt": "p1", "accept": ["a"], "roast": "r", "points": 100},
    {"prompt": "p2", "accept": ["a"], "roast": "r", "points": 50},
]
QUESTIONS_PARTIAL_POINTS = [
    {"prompt": "p1", "accept": ["a"], "roast": "r", "points": 100},
    {"prompt": "p2", "accept": ["a"], "roast": "r"},
]


def _scored(questions):
    return make_config(acts=1, segments_per_act=2, questions=questions)


def test_scoring_is_off_when_no_question_declares_points():
    # The whole feature must be invisible unless someone opts in. None is the
    # signal the UI keys off to render no score at all -- distinct from 0,
    # which means "scoring is on and you have not scored yet".
    config = make_config(acts=1, segments_per_act=2)
    assert score_for(config, cleared_segments=[1, 2]) is None


def test_a_cleared_segment_contributes_its_questions_points():
    assert score_for(_scored(QUESTIONS_WITH_POINTS), cleared_segments=[1, 2]) == 150


def test_an_uncleared_segment_contributes_nothing():
    assert score_for(_scored(QUESTIONS_WITH_POINTS), cleared_segments=[1]) == 100


def test_scoring_is_on_even_if_only_some_questions_declare_points():
    # A question with no `points` is worth 0, not a reason to disable scoring.
    assert score_for(_scored(QUESTIONS_PARTIAL_POINTS), cleared_segments=[1, 2]) == 100


def test_no_cleared_segments_scores_zero_not_none_when_points_are_configured():
    assert score_for(_scored(QUESTIONS_WITH_POINTS), cleared_segments=[]) == 0
