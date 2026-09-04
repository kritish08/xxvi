from dataclasses import dataclass, replace
from enum import StrEnum


class Difficulty(StrEnum):
    KIDDIE = "kiddie"
    DEVIL = "devil"


class Phase(StrEnum):
    ACTIVATION = "activation"
    PROFILE = "profile"
    DIFFICULTY = "difficulty"
    INSTALL = "install"
    HOWTO = "howto"
    GAME = "game"
    QUESTION = "question"
    CHECKPOINT = "checkpoint"
    COMPLETE = "complete"


class Event(StrEnum):
    ACTIVATED = "activated"
    PROFILE_CHOSEN = "profile_chosen"
    DIFFICULTY_CHOSEN = "difficulty_chosen"
    INSTALLED = "installed"
    HOWTO_ACKED = "howto_acked"
    GAME_PASSED = "game_passed"
    GAME_FAILED = "game_failed"
    QUESTION_PASSED = "question_passed"
    # A wrong answer that is NOT yet a failure -- he has attempts left and
    # stays on the question. Distinct from QUESTION_FAILED precisely so the
    # expensive consequences (spending a DEVIL life, clearing this run's
    # trophies, replaying the game) hang off the terminal event alone and
    # cannot be reached by a typo. See `RunService.submit_answer`, which
    # decides which of the two an answer produces.
    QUESTION_MISSED = "question_missed"
    QUESTION_FAILED = "question_failed"
    CHECKPOINT_PASSED = "checkpoint_passed"


@dataclass(frozen=True)
class Shape:
    acts: int = 2
    segments_per_act: int = 4

    @property
    def total(self) -> int:
        return self.acts * self.segments_per_act


@dataclass(frozen=True)
class RunState:
    phase: Phase = Phase.ACTIVATION
    difficulty: Difficulty | None = None
    segment: int = 0
    cleared_segments: frozenset[int] = frozenset()
    released_rewards: frozenset[int] = frozenset()
    # Devil-mode lives remaining, one pool for the entire run (never refilled
    # at checkpoints, never per-segment). Meaningless for KIDDIE and for any
    # state before a difficulty is chosen, so it stays None until DEVIL is
    # selected -- see `machine.advance`'s DIFFICULTY_CHOSEN handling.
    lives: int | None = None
    # Wrong answers spent on the CURRENT question only. Reset to 0 whenever a
    # question begins or ends, so it is always "attempts used on the question
    # he is looking at right now" and never a running total. Applies in BOTH
    # difficulties -- unlike `lives`, which is DEVIL-only. Kiddie needs this
    # more, not less: there, a single typo used to mean replaying the whole
    # game.
    question_attempts: int = 0

    def with_(self, **changes: object) -> "RunState":
        return replace(self, **changes)  # type: ignore[arg-type]


def initial_state() -> RunState:
    return RunState()


def act_of(segment: int, shape: Shape) -> int:
    return (segment - 1) // shape.segments_per_act + 1
