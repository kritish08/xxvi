"""Task 24: hidden trophies actually being awarded.

`core/trophies.py`'s `HIDDEN_PREFIX` machinery -- masking names until
earned (`api/content_routes.py`), surviving a Devil wipe
(`RunRepository.clear_segment_trophies`), and never gating the Platinum
(`core/trophies.py::platinum_earned`) -- already exists and is already
covered by `tests/test_core_trophies.py` and
`tests/test_persistence.py::test_clearing_segment_trophies_keeps_hidden_ones`.
This file is only the other half: `RunService.check_hidden` actually
deciding, from real player behaviour, whether HIDDEN_RAGE_QUIT,
HIDDEN_DRIFT_DENIER or HIDDEN_SPEEDRUN should pop -- plus one end-to-end
test proving an award made through `check_hidden` really does survive a
real Devil wipe driven through `apply()`, not just a directly-seeded one.

Concurrency (idempotent-under-a-race) coverage lives in
tests/test_hidden_trophies_concurrency.py, against its own file-backed
NullPool database -- see that file's fixture docstring for why this one's
shared in-memory `sessionmaker` (from conftest.py) would report
confidently wrong results for that.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from tests.paths import EXAMPLE_CONFIG
from xxvi.api.run_service import (
    DRIFT_DENIER_THRESHOLD,
    HIDDEN_DRIFT_DENIER,
    HIDDEN_RAGE_QUIT,
    HIDDEN_SPEEDRUN,
    SPEEDRUN_SECONDS,
    RunService,
)
from xxvi.content.loader import load_config
from xxvi.core.models import Difficulty, Event, Phase, RunState
from xxvi.games.tokens import TokenService
from xxvi.games.verify import GameResult
from xxvi.gates.service import GateService
from xxvi.persistence.models import Run
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings
from xxvi.vault.service import VaultService


@pytest.fixture
async def run(sessionmaker, account):
    return await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)


@pytest.fixture
def service(sessionmaker):
    settings = Settings()
    repo = RunRepository(sessionmaker)
    return RunService(
        repo=repo,
        config=load_config(EXAMPLE_CONFIG),
        gates=GateService(repo, settings),
        vault=VaultService(sessionmaker, settings),
        tokens=TokenService(repo),
    )


def _ids(trophies) -> set[str]:
    return {t.id for t in trophies}


# --- HIDDEN_RAGE_QUIT -------------------------------------------------

async def test_rage_quit_pops_on_returning_after_a_disconnect(sessionmaker, run, service):
    repo = RunRepository(sessionmaker)
    await repo.append_event(run.id, "player_disconnected", {})

    awarded = await service.check_hidden(run, RunRepository.to_state(run), reconnecting=True)

    assert HIDDEN_RAGE_QUIT in _ids(awarded)


async def test_rage_quit_does_not_pop_on_a_first_ever_connect(sessionmaker, run, service):
    # No player_disconnected event on the log yet -- this is not "coming
    # back", it's the very first connection of the night.
    awarded = await service.check_hidden(run, RunRepository.to_state(run), reconnecting=True)

    assert HIDDEN_RAGE_QUIT not in _ids(awarded)


async def test_rage_quit_is_never_evaluated_outside_the_reconnect_path(sessionmaker, run, service):
    # A disconnect event sitting on the log must not award this from
    # `apply()`'s own `check_hidden(..., reconnecting=False)` call on every
    # ordinary player action -- only a fresh WebSocket connect counts as
    # "coming back".
    repo = RunRepository(sessionmaker)
    await repo.append_event(run.id, "player_disconnected", {})

    awarded = await service.check_hidden(run, RunRepository.to_state(run), reconnecting=False)

    assert HIDDEN_RAGE_QUIT not in _ids(awarded)


async def test_rage_quit_is_awarded_at_most_once_across_repeated_reconnects(
    sessionmaker, run, service
):
    repo = RunRepository(sessionmaker)
    await repo.append_event(run.id, "player_disconnected", {})
    state = RunRepository.to_state(run)

    first = await service.check_hidden(run, state, reconnecting=True)
    second = await service.check_hidden(run, state, reconnecting=True)

    assert HIDDEN_RAGE_QUIT in _ids(first)
    assert HIDDEN_RAGE_QUIT not in _ids(second), "already held -- must not re-fire the pop"
    assert await repo.earned_trophies(run.id) == frozenset({HIDDEN_RAGE_QUIT})


# --- HIDDEN_DRIFT_DENIER ------------------------------------------------

async def test_drift_denier_pops_after_three_drift_failures(sessionmaker, run, service):
    repo = RunRepository(sessionmaker)
    for _ in range(DRIFT_DENIER_THRESHOLD):
        await repo.append_event(run.id, "game_failed", {"mechanic": "drift"})

    awarded = await service.check_hidden(run, RunRepository.to_state(run), reconnecting=False)

    assert HIDDEN_DRIFT_DENIER in _ids(awarded)


async def test_drift_denier_does_not_pop_after_only_two_failures(sessionmaker, run, service):
    repo = RunRepository(sessionmaker)
    for _ in range(DRIFT_DENIER_THRESHOLD - 1):
        await repo.append_event(run.id, "game_failed", {"mechanic": "drift"})

    awarded = await service.check_hidden(run, RunRepository.to_state(run), reconnecting=False)

    assert HIDDEN_DRIFT_DENIER not in _ids(awarded)


async def test_drift_denier_ignores_failures_at_other_mechanics(sessionmaker, run, service):
    repo = RunRepository(sessionmaker)
    for mechanic in ("simon", "update", "trophy_run"):
        await repo.append_event(run.id, "game_failed", {"mechanic": mechanic})

    awarded = await service.check_hidden(run, RunRepository.to_state(run), reconnecting=False)

    assert HIDDEN_DRIFT_DENIER not in _ids(awarded)


async def test_drift_denier_survives_across_a_devil_wipe_because_run_events_is_never_wiped(
    sessionmaker, run, service
):
    # clear_segment_trophies (a Devil wipe) only ever deletes TrophyEarned
    # rows -- run_events is the append-only audit log and is untouched, so
    # two drift failures before a wipe plus one after must still total
    # three, not reset to one.
    repo = RunRepository(sessionmaker)
    for _ in range(2):
        await repo.append_event(run.id, "game_failed", {"mechanic": "drift"})
    await repo.clear_segment_trophies(run.id)
    await repo.append_event(run.id, "game_failed", {"mechanic": "drift"})

    awarded = await service.check_hidden(run, RunRepository.to_state(run), reconnecting=False)

    assert HIDDEN_DRIFT_DENIER in _ids(awarded)


async def test_submit_game_records_the_mechanic_on_failure_and_the_trophy_pops_inline(
    sessionmaker, account, service
):
    """End to end through the real player-facing path (`submit_game`, not
    the audit log seeded directly): three genuine drift failures must
    themselves record `{"mechanic": "drift"}` (apply()'s `event_payload`),
    and the third failure's own `ApplyOutcome.trophies` must carry the pop
    -- nobody has to reconnect or poll for it separately.
    """
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    # Segment 3 in config/run.example.yaml is the drift mechanic.
    seeded = RunState(
        phase=Phase.GAME, difficulty=Difficulty.KIDDIE, segment=3,
        cleared_segments=frozenset({1, 2}), released_rewards=frozenset(), lives=None,
    )
    assert await repo.save_state(run.id, run.version, seeded)

    garbage = GameResult(
        mechanic="drift", passed_client_side=False,
        duration_ms=0, input_count=0, score=0, sequence=[],
    )

    outcome = None
    for _ in range(DRIFT_DENIER_THRESHOLD):
        run = await repo.get_by_account(account.id)
        state = RunRepository.to_state(run)
        brief = await service.start_segment(run, state)
        outcome = await service.submit_game(run, state, brief.token, garbage)

    assert outcome is not None
    assert HIDDEN_DRIFT_DENIER in _ids(outcome.trophies)
    assert await repo.count_events(run.id, "game_failed", {"mechanic": "drift"}) == 3


# --- HIDDEN_SPEEDRUN -----------------------------------------------------

def _final_checkpoint_state(shape) -> RunState:
    total = shape.total
    return RunState(
        phase=Phase.CHECKPOINT, difficulty=Difficulty.KIDDIE, segment=total,
        cleared_segments=frozenset(range(1, total + 1)),
        released_rewards=frozenset({1}), lives=None,
    )


async def test_speedrun_pops_when_the_run_completes_well_inside_the_threshold(
    sessionmaker, account, service
):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    state = _final_checkpoint_state(service.shape)
    assert await repo.save_state(run.id, run.version, state)
    run = await repo.get_by_account(account.id)

    # `run.started_at` was set moments ago by `create()` -- comfortably
    # inside SPEEDRUN_SECONDS without any clock manipulation.
    outcome = await service.apply(run, state, Event.CHECKPOINT_PASSED)

    assert outcome.state.phase is Phase.COMPLETE
    assert HIDDEN_SPEEDRUN in _ids(outcome.trophies)


async def test_speedrun_does_not_pop_when_the_run_took_too_long(sessionmaker, account, service):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)

    too_long_ago = datetime.now(UTC) - timedelta(seconds=SPEEDRUN_SECONDS + 120)
    async with sessionmaker() as session:
        await session.execute(update(Run).where(Run.id == run.id).values(started_at=too_long_ago))
        await session.commit()

    state = _final_checkpoint_state(service.shape)
    run = await repo.get_by_account(account.id)
    assert await repo.save_state(run.id, run.version, state)
    run = await repo.get_by_account(account.id)

    outcome = await service.apply(run, state, Event.CHECKPOINT_PASSED)

    assert outcome.state.phase is Phase.COMPLETE
    assert HIDDEN_SPEEDRUN not in _ids(outcome.trophies)


async def test_speedrun_is_not_evaluated_before_the_run_actually_completes(
    sessionmaker, account, service
):
    # Passing an EARLIER checkpoint (act 1 of 2) must never award this,
    # regardless of how fast it was reached -- only Phase.COMPLETE counts.
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    state = RunState(
        phase=Phase.CHECKPOINT, difficulty=Difficulty.KIDDIE, segment=4,
        cleared_segments=frozenset({1, 2, 3, 4}), released_rewards=frozenset(), lives=None,
    )
    assert await repo.save_state(run.id, run.version, state)
    run = await repo.get_by_account(account.id)

    outcome = await service.apply(run, state, Event.CHECKPOINT_PASSED)

    assert outcome.state.phase is not Phase.COMPLETE
    assert HIDDEN_SPEEDRUN not in _ids(outcome.trophies)


# --- Cross-cutting invariants (Task 24's two "do not break" guarantees) --
#
# The invariants themselves (HIDDEN_PREFIX exclusion from
# required_for_platinum, and clear_segment_trophies preserving it) are
# core/trophies.py's own machinery and are already pinned by
# tests/test_core_trophies.py -- untouched by this task. This is only an
# end-to-end check that a trophy `check_hidden` actually awards survives a
# REAL Devil wipe driven through `apply()` (not a directly-seeded one),
# and that a hidden trophy never becomes part of what `apply()` treats as
# platinum-relevant.

async def test_hidden_trophy_survives_a_real_devil_wipe_driven_through_apply(
    sessionmaker, account, service
):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.DEVIL)
    # One life left: the next failure wipes segment trophies (see
    # apply()'s docstring on `state.lives <= 1`).
    start = RunState(
        phase=Phase.GAME, difficulty=Difficulty.DEVIL, segment=2,
        cleared_segments=frozenset({1}), released_rewards=frozenset(), lives=1,
    )
    assert await repo.save_state(run.id, run.version, start)
    run = await repo.get_by_account(account.id)
    await repo.award_trophy(run.id, "game-1")
    await repo.award_trophy(run.id, HIDDEN_RAGE_QUIT)

    outcome = await service.apply(run, start, Event.GAME_FAILED)

    assert outcome.state.segment == 1  # the wipe actually happened
    earned = await repo.earned_trophies(run.id)
    assert "game-1" not in earned, "the wipe must still clear non-hidden segment trophies"
    assert HIDDEN_RAGE_QUIT in earned, "but the hidden trophy must survive it"


async def test_hidden_trophies_never_appear_in_platinum_requirements(sessionmaker, run, service):
    # `apply()`'s platinum check is `platinum_earned(earned, shape)` against
    # `core.trophies.required_for_platinum` -- assert the actual RunConfig
    # this service was built from doesn't leak a hidden id into that set,
    # i.e. the config-level guarantee holds for the real content file, not
    # just a synthetic Shape().
    from xxvi.core.trophies import required_for_platinum

    required = required_for_platinum(service.shape)
    hidden_ids = {t.id for t in service.config.trophies if t.hidden}
    assert hidden_ids, "sanity: the example config must actually define hidden trophies"
    assert required.isdisjoint(hidden_ids)
