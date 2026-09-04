import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from xxvi.api.deps import require_live, require_player
from xxvi.api.run_service import ApplyOutcome, ConcurrentUpdate, RunService, SegmentBrief
from xxvi.auth.sessions import SessionData
from xxvi.content.loader import get_config
from xxvi.core.models import Difficulty, Event, Phase, RunState, act_of
from xxvi.games.tokens import TokenInvalid, TokenService
from xxvi.games.verify import GameResult
from xxvi.gates.service import GateOutcome, GateService
from xxvi.persistence.models import Run
from xxvi.persistence.repositories import RunRepository
from xxvi.realtime.hub import OPERATOR_CHANNEL, hub, player_channel
from xxvi.realtime.messages import CodeReleasedMsg, RunStateMsg, TrophyPopMsg
from xxvi.settings import Settings, get_settings
from xxvi.vault.service import VaultService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/run", dependencies=[Depends(require_live)])

# Which phase each preamble event is only valid from. Enforced explicitly on
# every route below (not via a blanket exception handler) so that removing
# any one of these checks is independently observable: without it, an
# out-of-order request reaches `advance()` and raises `InvalidTransition`,
# which is not caught here and surfaces as a 500 instead of a 409.
_PREAMBLE_PHASE: dict[Event, Phase] = {
    Event.ACTIVATED: Phase.ACTIVATION,
    Event.PROFILE_CHOSEN: Phase.PROFILE,
    Event.DIFFICULTY_CHOSEN: Phase.DIFFICULTY,
    Event.INSTALLED: Phase.INSTALL,
    Event.HOWTO_ACKED: Phase.HOWTO,
}


class QuestionView(BaseModel):
    prompt: str
    blank: str
    # `accept` (the answer key) is deliberately absent -- it never reaches
    # the client. See xxvi/content/schema.py::Question.


class RunView(BaseModel):
    phase: str
    segment: int
    difficulty: str | None
    cleared_segments: list[int]
    released_rewards: list[int]
    lives: int | None
    # Attempts remaining on the question currently in play, derived here
    # rather than sent raw so the client never has to know the configured
    # allowance or do the subtraction itself. `None` whenever no question is
    # in play -- there is nothing to have attempts at.
    question_attempts_left: int | None
    trophies: list[str]
    question: QuestionView | None


class AnsweredView(BaseModel):
    """One question he has already got right.

    Only ever built for a CLEARED segment. The answer key never reaches the
    client for anything still ahead of him — same rule QuestionView follows
    by omitting `accept` — so this can reveal nothing he has not already
    earned.
    """
    segment: int
    prompt: str
    answer: str


class ProfileView(BaseModel):
    recipient: str
    difficulty: str | None
    phase: str
    segment: int
    total_segments: int
    cleared: int
    lives: int | None
    started_at: str
    answered: list[AnsweredView]
    trophies: list[str]


class ActivateRequest(BaseModel):
    code: str


class DifficultyRequest(BaseModel):
    difficulty: Difficulty


class GameResultBody(BaseModel):
    mechanic: str
    passed_client_side: bool
    # ge=0: without this, a negative duration_ms/input_count/score can flip
    # the sign of comparisons in verify_result's floor/ceiling checks in
    # ways those checks never anticipated (e.g. "duration_ms >=
    # input_count * MIN_MS_PER_INPUT" is trivially true for two negative
    # numbers of the right magnitude). None of these fields is ever
    # meaningfully negative for a real game session.
    duration_ms: int = Field(ge=0)
    input_count: int = Field(ge=0)
    score: int = Field(ge=0)
    sequence: list[int] = Field(default_factory=list)


class GameSubmission(BaseModel):
    token: str
    result: GameResultBody


class AnswerRequest(BaseModel):
    # Free text, not multiple choice: normalised server-side against the
    # question's `accept` list, which never leaves the server.
    answer: str


class CheckpointRequest(BaseModel):
    code: str


class AnswerResponse(RunView):
    passed: bool
    # True when this answer was wrong but NOT fatal -- he stays on the same
    # question with attempts remaining. Derivable from the returned phase
    # (a terminal failure always lands on GAME, a miss never leaves
    # QUESTION), but sent explicitly so the client renders "try again" from
    # a flag rather than from a re-implementation of the state machine's
    # rule. Always False when `passed` is True.
    retry: bool = False
    # The question's authored roast (content/schema.py::Question.roast) --
    # was loaded and validated at content-load time but never actually
    # reached the player anywhere; this is "designed to appear here" (see
    # run_service.py's SPEEDRUN_SECONDS comment, which already assumed a
    # player "pauses to read even one roast" before this field existed).
    # Only populated on a wrong answer -- there is nothing to roast about a
    # correct one, and by the time the NEXT question (if any) is reached,
    # `question` above already carries its own fresh prompt/blank.
    roast: str | None = None


def build_service(request: Request, settings: Settings) -> RunService:
    sessionmaker = request.app.state.sessionmaker
    config = getattr(request.app.state, "config", None) or get_config()
    repo = RunRepository(sessionmaker)
    return RunService(
        repo=repo,
        config=config,
        gates=GateService(repo, settings),
        vault=VaultService(sessionmaker, settings),
        tokens=TokenService(repo),
    )


async def _view(service: RunService, run: Run, state: RunState) -> RunView:
    trophies = await service.repo.earned_trophies(run.id)
    released = await service.released_reward_ids(run.id)
    question = None
    attempts_left = None
    if state.phase is Phase.QUESTION:
        q = service.config.questions[state.segment - 1]
        question = QuestionView(prompt=q.prompt, blank=q.blank)
        # max(0, ...) is belt-and-braces: the state machine never lets
        # `question_attempts` reach the allowance while still in QUESTION
        # phase (the answer that would take it there emits the terminal
        # QUESTION_FAILED instead), but a run rehydrated from a row written
        # by an older build must not render a negative count.
        attempts_left = max(0, service.config.question_attempts - state.question_attempts)
    return RunView(
        phase=state.phase.value,
        segment=state.segment,
        difficulty=state.difficulty.value if state.difficulty else None,
        cleared_segments=sorted(state.cleared_segments),
        released_rewards=sorted(released),
        lives=state.lives,
        question_attempts_left=attempts_left,
        trophies=sorted(trophies),
        question=question,
    )


async def publish_run(service: RunService, run: Run, outcome: ApplyOutcome) -> None:
    """Fan a state change out to the player's socket and the operator's.

    Public (was `_publish`) because operator_routes' checkpoint bypass needs
    exactly this: the player is looking at a screen that must change under
    him, and the released code has to actually reach it. A second copy of
    this fan-out would be a second place for the code to go missing, which
    is the failure the bypass exists to prevent.
    """
    channel = player_channel(run.id)
    released = await service.released_reward_ids(run.id)
    state_msg = RunStateMsg(
        phase=outcome.state.phase.value,
        segment=outcome.state.segment,
        difficulty=outcome.state.difficulty.value if outcome.state.difficulty else None,
        cleared_segments=sorted(outcome.state.cleared_segments),
        released_rewards=sorted(released),
    )
    await hub.broadcast(channel, state_msg)
    trophy_msgs = [
        TrophyPopMsg(trophy_id=trophy.id, name=trophy.name, grade=trophy.grade)
        for trophy in outcome.trophies
    ]
    for msg in trophy_msgs:
        await hub.broadcast(channel, msg)

    if outcome.released:
        # A real gift-card code. Only ever sent on the player's own channel,
        # never the operator's -- see xxvi/realtime/messages.py. Lives here
        # rather than at the call site so that EVERY path which releases a
        # code delivers it the same way; the operator's checkpoint bypass has
        # no HTTP response going to the player, so this socket message is the
        # only way his screen ever sees it.
        await hub.broadcast(channel, outcome.released)

    # Same two messages, also fanned out to the operator dashboard (task
    # 29): before this, OPERATOR_CHANNEL had a live socket connection
    # (ws_routes.py's operator_socket, which is what lets a player see
    # "operator online") but nothing was ever actually broadcast to it, so
    # the dashboard's only real freshness signal was its own 2s poll — a
    # trophy pop or a segment/checkpoint advance could sit stale on his
    # screen for up to 2 seconds during a live 20-minute run watched over a
    # Discord call. `Hub.broadcast` already catches and drops a dead/hung
    # socket per-recipient rather than raising (see its own docstring), so
    # this cannot itself turn into an unhandled exception here -- but this
    # function's return value feeds directly into the player's own HTTP
    # response (every call site does `await publish_run(...)` then returns
    # `_view(...)`), so the broadcast to the operator's channel is wrapped
    # in its own `try/except` regardless: a hypothetical future change to
    # `Hub.broadcast` that stops swallowing exceptions must not be able to
    # turn "the operator's dashboard is slightly stale" into "the player's
    # own request 500s." Content only, never behaviour: this never posts
    # anything the operator channel doesn't already receive types for
    # (Operator.tsx already wires a `run_state`/`trophy_pop` handler that
    # just triggers `refresh()` -- see its header comment on why those
    # handlers were "real but dead code" before this).
    try:
        await hub.broadcast(OPERATOR_CHANNEL, state_msg)
        for msg in trophy_msgs:
            await hub.broadcast(OPERATOR_CHANNEL, msg)
    except Exception:  # noqa: BLE001 — see comment above: never the player's problem.
        logger.info("operator-channel broadcast failed; player path unaffected", exc_info=True)


@router.get("", response_model=RunView)
async def read_run(
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> RunView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    return await _view(service, run, state)


@router.get("/profile", response_model=ProfileView)
async def profile(
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> ProfileView:
    """The run so far: who it is for, how far in, what he has answered and won.

    `answered` is built ONLY from `cleared_segments`. A question he has not
    cleared contributes nothing, so there is no path here that hands him an
    answer he has not already produced himself.
    """
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    config = service.config

    answered = [
        AnsweredView(
            segment=n,
            prompt=config.questions[n - 1].prompt,
            # The canonical spelling, not whatever he typed — normalisation
            # accepts many forms and the profile should read cleanly.
            answer=config.questions[n - 1].accept[0],
        )
        for n in sorted(state.cleared_segments)
        if 1 <= n <= len(config.questions)
    ]

    return ProfileView(
        recipient=config.recipient,
        difficulty=state.difficulty.value if state.difficulty else None,
        phase=state.phase.value,
        segment=state.segment,
        total_segments=service.shape.total,
        cleared=len(state.cleared_segments),
        lives=state.lives,
        started_at=run.started_at.isoformat(),
        answered=answered,
        trophies=sorted(await service.repo.earned_trophies(run.id)),
    )


@router.post("/activate", response_model=RunView)
async def activate(
    body: ActivateRequest,
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> RunView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    if state.phase is not Phase.ACTIVATION:
        raise HTTPException(status.HTTP_409_CONFLICT, "already activated")
    verdict = await service.submit_activation(run.id, body.code)
    if verdict is not GateOutcome.OK:
        raise HTTPException(status.HTTP_403_FORBIDDEN, verdict.value)
    try:
        outcome = await service.apply(run, state, Event.ACTIVATED)
    except ConcurrentUpdate as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await publish_run(service, run, outcome)
    return await _view(service, run, outcome.state)


def _simple(event: Event, path: str) -> None:
    expected_phase = _PREAMBLE_PHASE[event]

    @router.post(path, response_model=RunView, name=f"run_{event.value}")
    async def handler(
        request: Request,
        session: SessionData = Depends(require_player),
        settings: Settings = Depends(get_settings),
    ) -> RunView:
        service = build_service(request, settings)
        run, state = await service.load(session.account_id)
        if state.phase is not expected_phase:
            raise HTTPException(status.HTTP_409_CONFLICT, f"not at {expected_phase.value}")
        try:
            outcome = await service.apply(run, state, event)
        except ConcurrentUpdate as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        await publish_run(service, run, outcome)
        return await _view(service, run, outcome.state)


_simple(Event.PROFILE_CHOSEN, "/profile")
_simple(Event.INSTALLED, "/installed")
_simple(Event.HOWTO_ACKED, "/howto")


@router.post("/difficulty", response_model=RunView)
async def choose_difficulty(
    body: DifficultyRequest,
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> RunView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    if state.phase is not Phase.DIFFICULTY:
        raise HTTPException(status.HTTP_409_CONFLICT, "not at difficulty selection")
    try:
        outcome = await service.apply(run, state, Event.DIFFICULTY_CHOSEN, difficulty=body.difficulty)
    except ConcurrentUpdate as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await publish_run(service, run, outcome)
    return await _view(service, run, outcome.state)


class SegmentBriefView(BaseModel):
    segment: int
    token: str
    seed: str
    mechanic: str
    params: dict[str, float | int]


@router.post("/segment/start", response_model=SegmentBriefView)
async def start_segment(
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> SegmentBriefView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    if state.phase is not Phase.GAME:
        raise HTTPException(status.HTTP_409_CONFLICT, "not at a game")
    brief: SegmentBrief = await service.start_segment(run, state)
    return SegmentBriefView(**brief.__dict__)


@router.post("/segment/game", response_model=RunView)
async def submit_game(
    body: GameSubmission,
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> RunView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    if state.phase is not Phase.GAME:
        raise HTTPException(status.HTTP_409_CONFLICT, "not at a game")
    try:
        outcome = await service.submit_game(
            run, state, body.token, GameResult(**body.result.model_dump())
        )
    except TokenInvalid as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except ConcurrentUpdate as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await publish_run(service, run, outcome)
    return await _view(service, run, outcome.state)


@router.post("/segment/answer", response_model=AnswerResponse)
async def submit_answer(
    body: AnswerRequest,
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> AnswerResponse:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    if state.phase is not Phase.QUESTION:
        raise HTTPException(status.HTTP_409_CONFLICT, "not at a question")
    # Captured from the PRE-transition state -- `state.segment` (and thus
    # which question this was) can change by the time `submit_answer`
    # returns (a wrong answer restarts the segment; a right one can even
    # cross an act boundary), so this must be read before calling it.
    roast = service.config.questions[state.segment - 1].roast
    try:
        passed, outcome = await service.submit_answer(run, state, body.answer)
    except ConcurrentUpdate as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await publish_run(service, run, outcome)
    view = await _view(service, run, outcome.state)
    # A miss leaves him in QUESTION; every terminal failure routes through
    # `machine._apply_failure`, which always lands on GAME.
    retry = not passed and outcome.state.phase is Phase.QUESTION
    return AnswerResponse(
        **view.model_dump(),
        passed=passed,
        retry=retry,
        # The roast is the punchline for LOSING the segment, so it lands only
        # on the terminal failure. Firing it on every near-miss would spend
        # all eight of them in the first minute and leave nothing for the
        # moment it was written for.
        roast=None if passed or retry else roast,
    )


class CheckpointResponse(BaseModel):
    outcome: str
    attempts_remaining: int | None
    released: CodeReleasedMsg | None
    run: RunView


@router.post("/checkpoint", response_model=CheckpointResponse)
async def submit_checkpoint(
    body: CheckpointRequest,
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> CheckpointResponse:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    if state.phase is not Phase.CHECKPOINT:
        raise HTTPException(status.HTTP_409_CONFLICT, "not at a checkpoint")

    # Operator approval stand-in for the HTTP layer: Task 13 wires the real
    # `/api/operator/approve` route, which sets `release_approved[run_id]`
    # before a checkpoint is even reached in the normal flow. Tests set
    # `auto_approve_releases` to skip that dependency entirely.
    approved = bool(getattr(request.app.state, "auto_approve_releases", False)) or bool(
        getattr(request.app.state, "release_approved", {}).get(run.id)
    )
    try:
        verdict, outcome = await service.submit_checkpoint(run, state, body.code, approved=approved)
    except ConcurrentUpdate as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None

    if outcome is None:
        act = act_of(state.segment, service.shape)
        return CheckpointResponse(
            outcome=verdict.value,
            attempts_remaining=await service.checkpoint_attempts_remaining(run.id, act),
            released=None,
            run=await _view(service, run, state),
        )

    # publish_run now carries the code too -- see its own comment.
    await publish_run(service, run, outcome)
    return CheckpointResponse(
        outcome=verdict.value,
        attempts_remaining=None,
        released=outcome.released,
        run=await _view(service, run, outcome.state),
    )
