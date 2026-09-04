"""Orchestrates a single player's run: the state machine, gates, tokens and
the vault, glued together behind one seam the routes call through.

Every "has this already happened, then do it" decision on the money path is
delegated to a primitive that makes the check-then-act atomic at the
database layer. Some of these fast-path with an initial SELECT (`load()`,
`gate_row`) -- that alone is NOT what makes them safe. What makes each one
safe is that its actual write is a real compare-and-swap or an
insert-first-catch-the-constraint-violation, so a race that slips past the
fast-path SELECT is still caught at the write:

  - a run created at most once   -> RunRepository.create (get-or-create,
    per account                     UNIQUE(account_id), insert-first-catch-violation,
                                     mirrors gate_row exactly)
  - segment token single-use     -> TokenService.consume (RunRepository.consume_token,
                                     UNIQUE(run_id, nonce), insert-first-catch-violation)
  - trophy awarded at most once  -> RunRepository.award_trophy
                                     (UNIQUE(run_id, trophy_id), insert-first-catch-violation)
  - checkpoint gate attempts     -> GateService.submit -> RunRepository.record_gate_failure
                                     (single UPDATE ... RETURNING ... WHERE locked = False)
  - a reward code released at    -> VaultService.release
    most once per (run, reward)    (UNIQUE(run_id, reward_id), insert-first-catch-violation)
  - run state saved without      -> RunRepository.save_state
    torn/lost updates               (single UPDATE ... WHERE version = expected_version,
                                     compare-and-swap; apply() raises ConcurrentUpdate,
                                     routes turn that into 409, on a lost race)

An earlier version of this docstring claimed this module "never SELECTs a
row to decide 'has this happened' and then issues a separate INSERT/UPDATE
for it" -- false: `load()`'s `get_by_account` then `create()` is exactly
that shape, and until `create()` caught the UNIQUE(account_id) violation,
that specific site was a fourth instance of the exact defect the sentence
claimed didn't exist here (7 of 8 concurrent first requests returned 500).
`save_state` was a fifth, different-shaped instance: not a crash, a torn
row -- see its own docstring. Read the site-by-site list above, not a
blanket claim, when adding a new one.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from xxvi.content.schema import RunConfig, Trophy
from xxvi.core.machine import advance
from xxvi.core.models import Difficulty, Event, Phase, RunState, Shape, act_of
from xxvi.core.trophies import PLATINUM_ID, platinum_earned, trophy_for
from xxvi.games.tokens import TokenService, issue_segment_token
from xxvi.games.verify import GameResult, verify_result
from xxvi.gates.service import GateId, GateOutcome, GateService, checkpoint_gate
from xxvi.normalize import normalize_answer
from xxvi.persistence.models import Run
from xxvi.persistence.repositories import RunRepository
from xxvi.realtime.messages import CodeReleasedMsg
from xxvi.vault.service import AlreadyReleased, NotApproved, VaultService

logger = logging.getLogger(__name__)

# -- Hidden trophies -----------------------------------------------------
#
# Real PlayStation games have these: the name stays masked (see
# `api/content_routes.py`) until the moment it pops. The machinery that
# makes them survive a Devil wipe (`RunRepository.clear_segment_trophies`)
# and never gate the Platinum (`core/trophies.py::platinum_earned`, which
# only ever requires the 18 standard ids) already exists and is already
# tested -- nothing below touches either. This is only the "does the
# player's actual behaviour earn one" half.
HIDDEN_RAGE_QUIT = "hidden-rage-quit"
HIDDEN_DRIFT_DENIER = "hidden-drift-denier"
HIDDEN_SPEEDRUN = "hidden-speedrun"

# Three genuine failures at the drift mechanic (segments 3 and 7 in
# config/run.example.yaml, a sustained precise hold -- see
# xxvi/games/verify.py's "drift" case). One or two off days is not
# "denial"; three is a real, repeated pattern, achievable in a normal
# unlucky run without popping on the very first stumble.
DRIFT_DENIER_THRESHOLD = 3

# Ten minutes wall-clock, measured from `Run.started_at` (set the instant
# the run row is created) to the run reaching `Phase.COMPLETE`. The two
# drift segments alone have a combined mechanical floor of 45s
# (20000ms + 25000ms, config/run.example.yaml's `duration_ms`) on top of
# six more games, eight questions, two checkpoint code entries and five
# preamble screens -- a player who pauses to read even one roast or
# trophy pop comfortably exceeds this. Clearing it means skipping past
# nearly everything as fast as the UI allows: achievable by someone who
# already knows every answer, not by accident.
SPEEDRUN_SECONDS = 600


def _elapsed_seconds(started_at: datetime) -> float:
    """Wall-clock seconds since `started_at`, tolerant of
    `DateTime(timezone=True)`'s two faces: a real timezone-aware value on
    Postgres, a naive one on SQLite (SQLite has no such storage type --
    SQLAlchemy's SQLite dialect always hands back a naive `datetime`
    regardless of the column's `timezone=True` flag; see
    tests/integration/test_pg_quirks.py's module docstring). Comparing an
    aware `now` against a naive `started_at` raises `TypeError`, so `now`
    is stripped to match whenever `started_at` came back naive.
    """
    now = datetime.now(UTC)
    if started_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return (now - started_at).total_seconds()


class ConcurrentUpdate(Exception):
    """`apply()` computed a new state from a snapshot another request has
    since overwritten. Nothing was saved. The caller (a route) should
    surface this as 409 -- the client's data is stale and it should reload
    `GET /api/run` and retry, not treat this as any kind of server error.
    """


@dataclass(frozen=True)
class SegmentBrief:
    segment: int
    token: str
    seed: str
    mechanic: str
    params: dict


@dataclass
class ApplyOutcome:
    state: RunState
    trophies: list[Trophy] = field(default_factory=list)
    released: CodeReleasedMsg | None = None


class RunService:
    def __init__(
        self,
        repo: RunRepository,
        config: RunConfig,
        gates: GateService,
        vault: VaultService,
        tokens: TokenService,
    ) -> None:
        self._repo = repo
        self._config = config
        self._gates = gates
        self._vault = vault
        self._tokens = tokens
        self._shape = Shape(acts=config.acts, segments_per_act=config.segments_per_act)

    # -- Public surface for routes. Routes must never reach into the
    # underscore-prefixed attributes above -- these properties (and the
    # narrow methods below, for the gate/vault operations routes need) are
    # the whole contract. --

    @property
    def shape(self) -> Shape:
        return self._shape

    @property
    def repo(self) -> RunRepository:
        return self._repo

    @property
    def config(self) -> RunConfig:
        return self._config

    def _trophy(self, trophy_id: str) -> Trophy:
        return next(t for t in self._config.trophies if t.id == trophy_id)

    async def load(self, account_id: int) -> tuple[Run, RunState]:
        run = await self._repo.get_by_account(account_id)
        if run is None:
            run = await self._repo.create(account_id, None)
        return run, RunRepository.to_state(run)

    async def released_reward_ids(self, run_id: int) -> frozenset[int]:
        """The player- and operator-facing truth about which rewards have
        actually been emitted.

        Deliberately NOT `RunState.released_rewards` / `Run.released_rewards`:
        that field is the state machine's own bookkeeping of which *acts*
        have had their checkpoint cleared (`core/machine.py::_pass_checkpoint`,
        keyed by act number, updated the instant `Event.CHECKPOINT_PASSED` is
        applied -- before this service even attempts a vault release, and
        regardless of whether that release succeeds, is approved, or was
        already claimed). `code_releases` (via `VaultService`) is the only
        table a code was ever actually written to, keyed by reward id. If a
        checkpoint is cleared while the operator has not yet approved the
        release, `Run.released_rewards` would already say "released" while
        no code exists -- reading from the vault instead is what keeps the
        two from ever disagreeing in anything shown to a client.
        """
        return await self._vault.released_reward_ids(run_id)

    async def submit_activation(self, run_id: int, candidate: str) -> GateOutcome:
        return await self._gates.submit(run_id, GateId.ACTIVATION, candidate)

    async def checkpoint_attempts_remaining(self, run_id: int, act: int) -> int | None:
        gate = checkpoint_gate(act)
        return await self._gates.attempts_remaining(run_id, gate)

    async def apply(
        self,
        run: Run,
        state: RunState,
        event: Event,
        *,
        difficulty: Difficulty | None = None,
        event_payload: dict | None = None,
    ) -> ApplyOutcome:
        """Compute and persist the successor state for `event`.

        `save_state`'s compare-and-swap runs FIRST, before any other write
        -- not last, and this ordering is load-bearing, not stylistic. Every
        write below it (`clear_segment_trophies`, `award_trophy`,
        `append_event`) is a real side effect with no undo. If the CAS ran
        last and lost, those side effects would have already landed for a
        computation whose resulting state was then discarded -- which is
        exactly how a losing DEVIL-failure branch could delete `game-1` and
        `question-1` (via `clear_segment_trophies`) for a request that,
        having lost the race, never actually got to wipe the run to segment
        1 for real. Gating every side effect behind the CAS succeeding
        means a losing request does nothing at all: it raises
        `ConcurrentUpdate` before touching trophies, the event log, or
        anything else.

        `event_payload`, when given, is merged into the audit-log row
        alongside the segment this event applied from -- e.g.
        `submit_game`'s failure branch passes `{"mechanic": slot.mechanic}`
        so `check_hidden` has something to count drift-mechanic failures
        from without a second source of truth.
        """
        new_state = advance(
            state, event, self._shape, difficulty=difficulty, devil_lives=self._config.devil_lives
        )

        if not await self._repo.save_state(run.id, run.version, new_state):
            raise ConcurrentUpdate(
                f"run {run.id} was modified concurrently; computed state is stale"
            )

        payload = {"segment": state.segment, **(event_payload or {})}
        await self._repo.append_event(run.id, event.value, payload)

        outcome = ApplyOutcome(state=new_state)

        if event in (Event.GAME_FAILED, Event.QUESTION_FAILED) and state.difficulty is Difficulty.DEVIL:
            # `state.lives` is the pool BEFORE this failure -- the same value
            # `machine._apply_failure` used to decide whether this call wipes
            # (lives <= 1, and only then) or merely costs a life in place.
            # A failure that still had lives left must never reach this
            # branch: it replays the current segment with cleared_segments
            # untouched, and non-hidden trophies for segments already
            # cleared this run must survive it.
            if state.lives is not None and state.lives <= 1:
                await self._repo.clear_segment_trophies(run.id)

        awarded = trophy_for(state, event, self._shape)
        if awarded and await self._repo.award_trophy(run.id, awarded):
            outcome.trophies.append(self._trophy(awarded))

        earned = await self._repo.earned_trophies(run.id)
        if platinum_earned(earned, self._shape) and await self._repo.award_trophy(run.id, PLATINUM_ID):
            outcome.trophies.append(self._trophy(PLATINUM_ID))

        # Hidden trophies never gate the platinum and must never gate
        # (or crash) a player action either: a bug in this check must cost
        # at most a missed pop, never the request the player is actually
        # waiting on. `new_state`/`run.id` have already been durably saved
        # above, so there is nothing left here worth risking a 500 for --
        # same reasoning as the operator-channel broadcast in
        # `run_routes._publish`, which is wrapped for the identical reason.
        try:
            outcome.trophies.extend(await self.check_hidden(run, new_state))
        except Exception:  # see comment above: deliberately broad, never the player's problem.
            logger.warning("hidden-trophy check failed; player action unaffected", exc_info=True)

        return outcome

    async def check_hidden(
        self, run: Run, state: RunState, *, reconnecting: bool = False
    ) -> list[Trophy]:
        """Evaluate and award whichever hidden trophies the player's actual
        behaviour now qualifies for.

        Called from two places: the tail of `apply()` above (every event
        that reaches it, `reconnecting=False`) and `ws_routes.player_socket`
        on a fresh WebSocket connect (`reconnecting=True`). Every award
        below goes through `RunRepository.award_trophy` -- the same
        insert-first-catch-the-unique-violation primitive every other
        "at most once" write in this module uses (see the module docstring)
        -- so calling this repeatedly, from either site, at any point in a
        run, is always safe: a trophy already held is a no-op, never a
        duplicate award or a re-fired pop. Nothing here re-derives "does he
        already have it" itself; that question belongs to `award_trophy`
        alone.
        """
        awarded: list[Trophy] = []

        async def give(trophy_id: str) -> None:
            if await self._repo.award_trophy(run.id, trophy_id):
                awarded.append(self._trophy(trophy_id))

        # He closed the tab and came back. `ws_routes.player_socket`'s
        # `finally` block records a `player_disconnected` event every time
        # this run's channel loses its socket; this connect is a fresh one,
        # so a matching event already on the log means there was an earlier
        # connection that ended and this player returned to it.
        if reconnecting and await self._repo.has_event(run.id, "player_disconnected", {}):
            await give(HIDDEN_RAGE_QUIT)

        # He failed the Stick Drift mechanic three times. Counted straight
        # from `run_events` -- `submit_game`'s failure branch records
        # `{"mechanic": slot.mechanic}` on every `game_failed` event (see
        # `apply()`'s `event_payload`), so this is reading the append-only
        # audit log, never a second source of truth for something it
        # already answers. Unaffected by a Devil wipe: `clear_segment_trophies`
        # only ever deletes `TrophyEarned` rows, never `run_events`.
        drift_failures = await self._repo.count_events(
            run.id, "game_failed", {"mechanic": "drift"}
        )
        if drift_failures >= DRIFT_DENIER_THRESHOLD:
            await give(HIDDEN_DRIFT_DENIER)

        # He finished notably fast. Only meaningful once the run has
        # actually reached the end -- checked on every `apply()` call, so
        # this fires the instant the winning `CHECKPOINT_PASSED` lands,
        # not on some later poll.
        if state.phase is Phase.COMPLETE and _elapsed_seconds(run.started_at) <= SPEEDRUN_SECONDS:
            await give(HIDDEN_SPEEDRUN)

        return awarded

    async def start_segment(self, run: Run, state: RunState) -> SegmentBrief:
        slot = next(g for g in self._config.games if g.segment == state.segment)
        token, seed = issue_segment_token(run.id, state.segment)
        return SegmentBrief(
            segment=state.segment, token=token, seed=seed,
            mechanic=slot.mechanic, params=dict(slot.params),
        )

    async def submit_game(
        self, run: Run, state: RunState, token: str, result: GameResult
    ) -> ApplyOutcome:
        # `TokenService.consume` is the single-use check -- see this
        # module's docstring. It runs BEFORE any state mutation, so a
        # replayed token (the same request sent twice, or a failed attempt
        # retried with a stale token) never reaches `apply()` a second time.
        claim = await self._tokens.consume(token, run_id=run.id)
        slot = next(g for g in self._config.games if g.segment == claim.segment)
        passed = claim.segment == state.segment and verify_result(
            slot, claim.seed, result, issued_at=claim.issued_at
        )
        event = Event.GAME_PASSED if passed else Event.GAME_FAILED
        # Record which mechanic this failure was at -- `check_hidden` counts
        # `game_failed` events with `mechanic == "drift"` to award
        # HIDDEN_DRIFT_DENIER. Only attached on failure: a pass has no
        # bearing on that count and `game_passed` events don't need it.
        payload = {"mechanic": slot.mechanic} if event is Event.GAME_FAILED else None
        return await self.apply(run, state, event, event_payload=payload)

    async def submit_answer(self, run: Run, state: RunState, answer: str) -> tuple[bool, ApplyOutcome]:
        # Free text, not multiple choice: normalise both sides identically
        # and accept if the submission matches ANY listed `accept` entry.
        # `question.accept` never leaves this function -- the caller only
        # ever sees pass/fail via the returned `passed` bool and the
        # returned ApplyOutcome. `passed` is also returned explicitly (not
        # just inferrable from the resulting phase) so the route can attach
        # `question.roast` on a wrong answer -- authored content that used
        # to be loaded and validated but never actually shown anywhere
        # (see xxvi/content/schema.py::Question.roast).
        question = self._config.questions[state.segment - 1]
        submitted = normalize_answer(answer)
        passed = any(normalize_answer(candidate) == submitted for candidate in question.accept)

        if passed:
            event = Event.QUESTION_PASSED
        elif state.question_attempts + 1 < self._config.question_attempts:
            # He has attempts left, so this wrong answer is a MISS, not a
            # failure: he stays on the question, keeps his lives, keeps his
            # trophies, and does not replay the game. `question_attempts` is
            # the count BEFORE this answer, so `+ 1` is what this answer
            # makes it -- the last allowed attempt is the one where that
            # total reaches `config.question_attempts`, and that one is
            # terminal.
            event = Event.QUESTION_MISSED
        else:
            event = Event.QUESTION_FAILED

        outcome = await self.apply(run, state, event)
        return passed, outcome

    async def submit_checkpoint(
        self, run: Run, state: RunState, candidate: str, *, approved: bool
    ) -> tuple[GateOutcome, ApplyOutcome | None]:
        act = act_of(state.segment, self._shape)
        gate = checkpoint_gate(act)
        verdict = await self._gates.submit(run.id, gate, candidate)
        if verdict is not GateOutcome.OK:
            return verdict, None

        return verdict, await self.pass_checkpoint(run, state, approved=approved)

    async def pass_checkpoint(
        self, run: Run, state: RunState, *, approved: bool, bypassed: bool = False
    ) -> ApplyOutcome:
        """Everything a checkpoint does once the code has been ACCEPTED.

        Split out of `submit_checkpoint` so the operator's bypass
        (`operator_routes.bypass_checkpoint`) runs this exact path rather
        than a parallel copy of it. A rescue route that advances the run
        slightly differently from the real one is worse than no rescue
        route: it would be exercised for the first time at midnight, on the
        one run that matters, with no way to tell what it did differently.

        `bypassed` only marks the audit log. It changes nothing about what
        happens -- which is the point.
        """
        act = act_of(state.segment, self._shape)
        outcome = await self.apply(
            run,
            state,
            Event.CHECKPOINT_PASSED,
            event_payload={"bypassed_by_operator": True} if bypassed else None,
        )
        reward = next(r for r in self._config.rewards if r.after_act == act)
        try:
            # VaultService.release is the atomic "at most once" claim -- see
            # this module's docstring. Passing the checkpoint and releasing
            # its reward are deliberately two separate outcomes: the player
            # advances into the next act on a correct code regardless of
            # whether the operator has approved the release yet.
            code = await self._vault.release(run.id, reward.id, approved_by_operator=approved)
            outcome.released = CodeReleasedMsg(reward_id=reward.id, label=reward.label, code=code)
        except AlreadyReleased:
            # This run's code for this reward was ALREADY emitted -- most
            # likely the operator released it from the dashboard before the
            # player got the checkpoint code in. Returning None here left him
            # staring at nothing at the single moment the whole thing exists
            # for: observed live as `released: null` on a successful
            # checkpoint, with the operator dashboard cheerfully reporting
            # "the player already has the code" when he had never been shown
            # it. The WS `code_released` broadcast that fired at release time
            # is a one-shot with no redelivery, so if he was on another
            # screen, or not yet connected, it is simply gone.
            #
            # Re-showing it is NOT a second emission: the `code_releases`
            # ledger is untouched (that is what raised this), the unique
            # constraint still holds, and reaching this branch is itself
            # proof that a row exists for exactly this `(run_id, reward_id)`.
            # It is his code, already spent from the vault's point of view,
            # being put back on his screen where it belonged.
            outcome.released = CodeReleasedMsg(
                reward_id=reward.id, label=reward.label, code=self._vault.code_for(reward.id)
            )
        except NotApproved:
            # Checkpoint cleared, but no operator has approved yet. The
            # caller (route) surfaces `released: None`; the operator's
            # separate approval (Task 13) delivers the code later over the
            # player's WebSocket channel.
            outcome.released = None
        return outcome
