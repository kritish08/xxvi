import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from xxvi.api.deps import require_operator
from xxvi.api.run_routes import build_service as build_run_service, publish_run
from xxvi.api.run_service import ConcurrentUpdate
from xxvi.core.models import Event, Phase
from xxvi.gates.service import GateId, GateService
from xxvi.persistence.models import Run
from xxvi.persistence.repositories import RunRepository
from xxvi.realtime.hub import hub, player_channel
from xxvi.realtime.messages import CodeReleasedMsg, RunStateMsg, ToastMsg
from xxvi.settings import Settings, get_settings
from xxvi.vault.service import AlreadyReleased, NotApproved, VaultService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/operator", dependencies=[Depends(require_operator)])


class ApproveRequest(BaseModel):
    run_id: int
    reward_id: int


class ToastRequest(BaseModel):
    run_id: int
    text: str


class UnlockGateRequest(BaseModel):
    run_id: int
    gate: GateId


class BypassCheckpointRequest(BaseModel):
    run_id: int


class SkipGameRequest(BaseModel):
    run_id: int


class SkipGameResponse(BaseModel):
    phase: str
    segment: int


class ResetRunRequest(BaseModel):
    run_id: int
    # A typed confirmation, not a boolean. Every other operator action is
    # recoverable; this one deletes the record that a gift card was handed
    # over, so it should not be reachable by a stray `{"run_id": 1}` from a
    # curl someone still had in their shell history.
    confirm: str


class ResetRunResponse(BaseModel):
    run_id: int
    deleted: dict[str, int]


class BypassCheckpointResponse(BaseModel):
    phase: str
    segment: int
    released: CodeReleasedMsg | None


class RunSummary(BaseModel):
    id: int
    difficulty: str | None
    phase: str
    segment: int
    cleared_segments: list[int]
    released_rewards: list[int]
    # Devil-mode lives remaining -- run-state bookkeeping (Run.lives itself),
    # not a ledger, because there is no separate ledger for it: unlike a
    # trophy or a released code, "lives remaining" has no independent
    # append-only record anywhere else to be inconsistent WITH. It is
    # `None` in Kiddie mode and before Devil is chosen, mirroring
    # `RunView.lives` (run_routes.py) and `Run.lives` (persistence/models.py)
    # exactly.
    lives: int | None
    # The earned count, sourced from the `trophies_earned` ledger via
    # `RunRepository.earned_trophies` -- the same table `RunView.trophies`
    # (run_routes.py's `_view`) reads, and the same reasoning `released`
    # above already follows for `code_releases`: this project's standing
    # rule is that a ledger is authoritative and run-state bookkeeping is
    # not. (`Run` carries no `trophies` column at all -- there is no
    # bookkeeping copy to have preferred over the ledger here.)
    trophies: list[str]


class OperatorState(BaseModel):
    live_forced: bool
    runs: list[RunSummary]


@router.post("/approve", response_model=CodeReleasedMsg)
async def approve_release(
    body: ApproveRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> CodeReleasedMsg:
    vault = VaultService(request.app.state.sessionmaker, settings)
    try:
        # Explicit operator action, behind require_operator on this whole
        # router -- this call site IS the approval.
        code = await vault.release(body.run_id, body.reward_id, approved_by_operator=True)
    except AlreadyReleased:
        raise HTTPException(status.HTTP_409_CONFLICT, "already released") from None
    except NotApproved:  # pragma: no cover - unreachable, approved_by_operator is always True here
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not approved") from None

    message = CodeReleasedMsg(reward_id=body.reward_id, label=f"Reward {body.reward_id}", code=code)
    # A real gift-card code. Only ever sent on the PLAYER's channel -- never
    # OPERATOR_CHANNEL, which every connected operator socket shares. See
    # xxvi/realtime/messages.py and xxvi/realtime/hub.py.
    await hub.broadcast(player_channel(body.run_id), message)
    return message


@router.post("/toast")
async def send_toast(body: ToastRequest) -> dict[str, int]:
    delivered = await hub.broadcast(player_channel(body.run_id), ToastMsg(text=body.text))
    return {"delivered": delivered}


@router.post("/unlock-gate")
async def unlock_gate(
    body: UnlockGateRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    repo = RunRepository(request.app.state.sessionmaker)
    await GateService(repo, settings).clear_lock(body.run_id, body.gate)
    return {"ok": True}


@router.post("/pass-checkpoint", response_model=BypassCheckpointResponse)
async def bypass_checkpoint(
    body: BypassCheckpointRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> BypassCheckpointResponse:
    """Pass a checkpoint WITHOUT the passphrase, and release its reward.

    THE ONE ROUTE THAT DEFEATS THE GATE ON PURPOSE. Everything else in this
    system exists to make sure a gift-card code cannot be obtained without
    the out-of-band phrase only the operator holds; this hands it over on a
    click. That is the point: on the night, the failure that actually costs
    something is not "someone cheated the gate", it is "the gate broke, or
    he cannot type the phrase, and the present does not arrive". The gate
    protects a code the operator is going to read aloud anyway, over a call,
    to the one person it is for.

    It is safe to reach for because it is not privileged beyond what the
    operator can already do: this router is behind `require_operator`, and
    an operator can already emit any code directly via `/approve`. This
    route adds no new power -- it makes the run's STATE agree with what the
    operator was always able to do to the vault, which `/approve` alone does
    not (that is precisely how the run observed live ended up holding a
    released reward while still sitting on the checkpoint screen).

    Runs the same `RunService.pass_checkpoint` the real code path runs, so
    the rescue cannot drift from the thing it is rescuing. The only
    difference it makes is a `bypassed_by_operator` marker on the audit log.
    """
    service = build_run_service(request, settings)
    run = await service.repo.get_by_id(body.run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {body.run_id}")

    state = RunRepository.to_state(run)
    if state.phase is not Phase.CHECKPOINT:
        # Not an error worth hiding: tell the operator exactly where the run
        # actually is, because the reason he pressed this was that he
        # believed it was somewhere else.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run {body.run_id} is not at a checkpoint (phase={state.phase.value}, "
            f"segment={state.segment})",
        )

    logger.warning(
        "OPERATOR BYPASS: passing checkpoint for run=%s at segment=%s without a passphrase",
        run.id, state.segment,
    )
    try:
        outcome = await service.pass_checkpoint(run, state, approved=True, bypassed=True)
    except ConcurrentUpdate as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None

    # The player is watching a screen that must now change under him, and
    # the code has to actually reach it -- the whole failure this fixes was
    # a release that never made it to his screen.
    await publish_run(service, run, outcome)

    return BypassCheckpointResponse(
        phase=outcome.state.phase.value,
        segment=outcome.state.segment,
        released=outcome.released,
    )


@router.post("/skip-game", response_model=SkipGameResponse)
async def skip_game(
    body: SkipGameRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SkipGameResponse:
    """Clear the current game without playing it, and go to its question.

    The rescue for a game that will not cooperate -- a mechanic misbehaving,
    a keyboard that is not registering, or simply a segment he cannot get
    past while everyone waits. It counts as a pass, so the game trophy is
    awarded exactly as if he had played it: from the run's point of view the
    segment's skill half is done, and the question still has to be answered
    on his own.

    Much narrower than the checkpoint bypass: no gift card is released and
    no gate is defeated, so it is a single click with no typed confirmation.
    """
    service = build_run_service(request, settings)
    run = await service.repo.get_by_id(body.run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {body.run_id}")

    state = RunRepository.to_state(run)
    if state.phase is not Phase.GAME:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run {body.run_id} is not at a game (phase={state.phase.value}, "
            f"segment={state.segment})",
        )

    logger.warning(
        "OPERATOR SKIP: clearing the game at segment %s for run %s without play",
        state.segment, run.id,
    )
    try:
        outcome = await service.apply(
            run, state, Event.GAME_PASSED, event_payload={"skipped_by_operator": True}
        )
    except ConcurrentUpdate as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None

    await publish_run(service, run, outcome)
    return SkipGameResponse(phase=outcome.state.phase.value, segment=outcome.state.segment)


@router.post("/reset-run", response_model=ResetRunResponse)
async def reset_run(
    body: ResetRunRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ResetRunResponse:
    """Put a run back to its very first screen. FOR TESTING.

    Deletes every trophy, gate attempt, consumed token, event AND released
    code for the run, then resets the row. It exists because testing the
    night end to end otherwise means hand-editing the database, which is how
    this project twice hit a foreign-key violation by deleting in the wrong
    order.

    WHAT MAKES THIS DIFFERENT FROM EVERY OTHER OPERATOR ACTION:
    `code_releases` is the only thing enforcing that a gift card is released
    at most once (`VaultService.release` leans on its
    UNIQUE(run_id, reward_id)). Clearing it makes an already-given code
    releasable again -- exactly what a test rerun needs, and exactly what
    must never happen by accident on the night. Hence the typed
    confirmation, and hence a response reporting what was destroyed rather
    than a bare {"ok": true}.
    """
    if body.confirm != "RESET":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'reset requires confirm="RESET"')

    repo = RunRepository(request.app.state.sessionmaker)
    logger.warning(
        "OPERATOR RESET: wiping run=%s, including any released-code records", body.run_id
    )
    deleted = await repo.reset_run(body.run_id)
    if deleted is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {body.run_id}")

    # His screen is mid-run and has just become wrong. Push the fresh state
    # so it drops back to the start rather than sitting on a segment that no
    # longer exists.
    await hub.broadcast(
        player_channel(body.run_id),
        RunStateMsg(
            phase="activation",
            segment=0,
            difficulty=None,
            cleared_segments=[],
            released_rewards=[],
        ),
    )
    return ResetRunResponse(run_id=body.run_id, deleted=deleted)


@router.post("/force-golive")
async def force_golive(request: Request) -> dict[str, bool]:
    request.app.state.force_unlocked = True
    return {"live": True}


@router.get("/state", response_model=OperatorState)
async def operator_state(request: Request, settings: Settings = Depends(get_settings)) -> OperatorState:
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        rows = (await session.execute(select(Run))).scalars().all()

    vault = VaultService(sessionmaker, settings)
    repo = RunRepository(sessionmaker)
    summaries = []
    for r in rows:
        # code_releases, not the state machine's own released_rewards
        # bookkeeping -- see RunService.released_reward_ids's docstring.
        # The operator dashboard must never show a reward as "released"
        # before a code has actually been emitted for it, or it invites
        # approving (or believing already-approved) a release that hasn't
        # happened.
        released = sorted(await vault.released_reward_ids(r.id))
        # trophies_earned, not run-state bookkeeping -- same ledger
        # RunView.trophies (run_routes.py) reads, same reasoning as
        # `released` immediately above. See RunSummary's own comment.
        trophies = sorted(await repo.earned_trophies(r.id))
        summaries.append(RunSummary(
            id=r.id, difficulty=r.difficulty, phase=r.phase, segment=r.segment,
            cleared_segments=r.cleared_segments or [],
            released_rewards=released,
            lives=r.lives,
            trophies=trophies,
        ))

    return OperatorState(
        live_forced=bool(getattr(request.app.state, "force_unlocked", False)),
        runs=summaries,
    )
