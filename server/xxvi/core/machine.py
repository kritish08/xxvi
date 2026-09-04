from xxvi.core.models import Difficulty, Event, Phase, RunState, Shape, act_of


class InvalidTransition(Exception):
    """An event arrived that the current phase does not accept."""


_PREAMBLE: dict[Phase, tuple[Event, Phase]] = {
    Phase.ACTIVATION: (Event.ACTIVATED, Phase.PROFILE),
    Phase.PROFILE: (Event.PROFILE_CHOSEN, Phase.DIFFICULTY),
    Phase.DIFFICULTY: (Event.DIFFICULTY_CHOSEN, Phase.INSTALL),
    Phase.INSTALL: (Event.INSTALLED, Phase.HOWTO),
}

_FAILURES = {Event.GAME_FAILED, Event.QUESTION_FAILED}


def advance(
    state: RunState,
    event: Event,
    shape: Shape,
    *,
    difficulty: Difficulty | None = None,
    devil_lives: int | None = None,
) -> RunState:
    if state.phase in _PREAMBLE:
        expected, next_phase = _PREAMBLE[state.phase]
        if event is not expected:
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        if event is Event.DIFFICULTY_CHOSEN:
            if difficulty is None:
                raise InvalidTransition("DIFFICULTY_CHOSEN requires a difficulty")
            if difficulty is Difficulty.DEVIL:
                # Grant the full life pool the moment DEVIL is chosen. `core/`
                # never reads config, so the caller (which does have the
                # RunConfig) must supply the configured count here.
                if devil_lives is None:
                    raise InvalidTransition(
                        "DIFFICULTY_CHOSEN to DEVIL requires devil_lives"
                    )
                return state.with_(phase=next_phase, difficulty=difficulty, lives=devil_lives)
            return state.with_(phase=next_phase, difficulty=difficulty)
        return state.with_(phase=next_phase)

    if state.phase is Phase.HOWTO:
        if event is not Event.HOWTO_ACKED:
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        return state.with_(phase=Phase.GAME, segment=1)

    if event in _FAILURES:
        if state.phase not in (Phase.GAME, Phase.QUESTION):
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        return _apply_failure(state, devil_lives)

    if state.phase is Phase.GAME:
        if event is not Event.GAME_PASSED:
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        # A question is starting: he gets its full allowance regardless of
        # what the last question cost him.
        return state.with_(phase=Phase.QUESTION, question_attempts=0)

    if state.phase is Phase.QUESTION:
        # A wrong answer with attempts still in hand. Nothing else moves --
        # same phase, same segment, same lives, same trophies. The only
        # change is that one more attempt is spent.
        if event is Event.QUESTION_MISSED:
            return state.with_(question_attempts=state.question_attempts + 1)
        if event is not Event.QUESTION_PASSED:
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        return _clear_segment(state, shape)

    if state.phase is Phase.CHECKPOINT:
        if event is not Event.CHECKPOINT_PASSED:
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        return _pass_checkpoint(state, shape)

    raise InvalidTransition(f"{state.phase} is terminal and accepts nothing")


def _apply_failure(state: RunState, devil_lives: int | None) -> RunState:
    # Restart means the whole segment, game first — never the question alone.
    # Lives are irrelevant to KIDDIE and are never touched here.
    if state.difficulty is Difficulty.KIDDIE:
        return state.with_(phase=Phase.GAME, question_attempts=0)
    # Devil: one life pool for the entire run, never refilled at checkpoints,
    # never per-segment. A failure with lives remaining costs a life and
    # replays the current segment in place (cleared_segments untouched,
    # segment untouched). Only the failure that exhausts the last life wipes
    # to segment 1 with cleared_segments emptied -- and restores lives to
    # full, or the second attempt would be unwinnable. Released rewards are
    # never revoked, on either path.
    if state.difficulty is Difficulty.DEVIL:
        if devil_lives is None:
            raise InvalidTransition("DEVIL failure requires devil_lives")
        if state.lives is None:
            # Fail closed, same spirit as the difficulty guard below: a DEVIL
            # state that never had lives granted (e.g. corrupt/incomplete
            # rehydration) must not be treated as having any lives to spend.
            raise InvalidTransition("DEVIL state is missing lives")
        if state.lives <= 1:
            return state.with_(
                phase=Phase.GAME,
                segment=1,
                cleared_segments=frozenset(),
                lives=devil_lives,
                question_attempts=0,
            )
        return state.with_(phase=Phase.GAME, lives=state.lives - 1, question_attempts=0)
    # Fail closed: an unset/unknown difficulty must never fall through to the
    # harsher DEVIL wipe. This is unreachable via advance() today (DIFFICULTY_CHOSEN
    # always sets a real Difficulty before GAME/QUESTION are reachable), but a
    # RunState rehydrated from storage with a corrupt/missing difficulty must not
    # silently wipe a KIDDIE player's progress.
    raise InvalidTransition(f"cannot apply failure with difficulty={state.difficulty!r}")


def _clear_segment(state: RunState, shape: Shape) -> RunState:
    cleared = state.cleared_segments | {state.segment}
    at_act_boundary = state.segment % shape.segments_per_act == 0
    if at_act_boundary:
        return state.with_(
            phase=Phase.CHECKPOINT, cleared_segments=cleared, question_attempts=0
        )
    return state.with_(
        phase=Phase.GAME,
        segment=state.segment + 1,
        cleared_segments=cleared,
        question_attempts=0,
    )


def _pass_checkpoint(state: RunState, shape: Shape) -> RunState:
    act = act_of(state.segment, shape)
    released = state.released_rewards | {act}
    if act >= shape.acts:
        return state.with_(phase=Phase.COMPLETE, released_rewards=released)
    return state.with_(
        phase=Phase.GAME,
        segment=state.segment + 1,
        released_rewards=released,
    )
