from collections.abc import Iterable

from xxvi.core.models import Event, RunState, Shape, act_of

PLATINUM_ID = "platinum"
HIDDEN_PREFIX = "hidden-"


def trophy_for(state: RunState, event: Event, shape: Shape) -> str | None:
    """The trophy awarded by `event` given the state it was applied to."""
    match event:
        case Event.GAME_PASSED:
            return f"game-{state.segment}"
        case Event.QUESTION_PASSED:
            return f"question-{state.segment}"
        case Event.CHECKPOINT_PASSED:
            return f"act-{act_of(state.segment, shape)}"
        case _:
            return None


def required_for_platinum(shape: Shape) -> frozenset[str]:
    segments = range(1, shape.total + 1)
    acts = range(1, shape.acts + 1)
    return frozenset(
        [f"game-{n}" for n in segments]
        + [f"question-{n}" for n in segments]
        + [f"act-{a}" for a in acts]
    )


def platinum_earned(earned: Iterable[str], shape: Shape) -> bool:
    return required_for_platinum(shape) <= set(earned)


def wipe_trophies(earned: Iterable[str]) -> frozenset[str]:
    """A Devil wipe clears segment trophies. Hidden ones, once popped, stay popped."""
    return frozenset(t for t in earned if t.startswith(HIDDEN_PREFIX))
