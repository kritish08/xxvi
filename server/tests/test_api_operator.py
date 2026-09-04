import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from xxvi.auth.passwords import hash_password
from xxvi.core.models import Difficulty
from xxvi.main import create_app, seed_accounts
from xxvi.persistence.models import Account, Run
from xxvi.persistence.repositories import RunRepository
from xxvi.realtime.hub import OPERATOR_CHANNEL, hub, player_channel
from xxvi.settings import Settings, get_settings
from xxvi.vault.service import AlreadyReleased, VaultService


@pytest.fixture
def settings():
    return Settings(
        player_username="him", player_password_hash=hash_password("pw"),
        operator_username="me", operator_password_hash=hash_password("pw"),
        checkpoint_1_hash=hash_password("X"), reward_1_code="R1",
        go_live_iso="2030-01-01T00:00:00+05:30",  # not yet live
    )


@pytest.fixture
async def app(sessionmaker, settings):
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.state.sessionmaker = sessionmaker
    await seed_accounts(sessionmaker, settings)
    return application


@pytest.fixture
async def operator(app):
    # https, not http -- see test_api_auth.py: the login cookie is Secure
    # and httpx's jar drops it on the next request over plain http.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "me", "password": "pw"})
        yield c


@pytest.fixture
async def player_run(sessionmaker):
    async with sessionmaker() as session:
        result = await session.execute(select(Account).where(Account.username == "him"))
        account = result.scalar_one()
    return await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)


async def test_a_player_cannot_reach_operator_routes(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        assert (await c.post("/api/operator/force-golive")).status_code == 403


async def test_an_anonymous_visitor_cannot_reach_operator_routes(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        assert (await c.post("/api/operator/force-golive")).status_code == 401


async def test_a_player_cannot_force_golive_even_indirectly(app):
    # force-golive is the whole gate for every player route. Confirm the
    # 403 above actually means nothing happened -- not just that the
    # response looked right.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        await c.post("/api/operator/force-golive")  # 403, ignored
        assert (await c.get("/api/session")).json()["live"] is False


async def test_force_golive_opens_the_gate(operator, app):
    assert (await operator.get("/api/session")).json()["live"] is False
    await operator.post("/api/operator/force-golive")
    assert (await operator.get("/api/session")).json()["live"] is True


async def test_approving_a_release_returns_the_code_once(operator, player_run):
    first = await operator.post(
        "/api/operator/approve", json={"run_id": player_run.id, "reward_id": 1}
    )
    assert first.status_code == 200
    assert first.json()["code"] == "R1"

    second = await operator.post(
        "/api/operator/approve", json={"run_id": player_run.id, "reward_id": 1}
    )
    assert second.status_code == 409


async def test_clearing_a_lockout_restores_attempts(operator, player_run, sessionmaker, settings):
    from xxvi.gates.service import GateId, GateOutcome, GateService

    service = GateService(RunRepository(sessionmaker), settings)
    for _ in range(3):
        await service.submit(player_run.id, GateId.CHECKPOINT_1, "wrong")
    assert await service.submit(player_run.id, GateId.CHECKPOINT_1, "X") is GateOutcome.LOCKED

    response = await operator.post(
        "/api/operator/unlock-gate", json={"run_id": player_run.id, "gate": "checkpoint_1"}
    )
    assert response.status_code == 200
    assert await service.submit(player_run.id, GateId.CHECKPOINT_1, "X") is GateOutcome.OK


async def test_operator_state_reports_the_run(operator, player_run):
    body = (await operator.get("/api/operator/state")).json()
    assert body["runs"][0]["id"] == player_run.id
    assert body["runs"][0]["difficulty"] == "kiddie"
    assert body["runs"][0]["released_rewards"] == []


async def test_operator_state_released_rewards_reflects_actual_emission(operator, player_run):
    # Sourced from code_releases (via VaultService), not the state machine's
    # own bookkeeping -- an operator glancing at this dashboard must not be
    # told a reward is "released" before a code was ever actually emitted.
    await operator.post("/api/operator/approve", json={"run_id": player_run.id, "reward_id": 1})
    body = (await operator.get("/api/operator/state")).json()
    assert body["runs"][0]["released_rewards"] == [1]


async def test_operator_state_lives_is_null_for_kiddie(operator, player_run):
    # player_run is created KIDDIE -- Kiddie has no life pool at all, and
    # Run.lives is NULL until Devil is chosen (persistence/models.py).
    # A dashboard that showed 0 here would read as "he's out of lives" when
    # there is in fact no such concept for this run.
    body = (await operator.get("/api/operator/state")).json()
    assert body["runs"][0]["lives"] is None


async def test_operator_state_reports_lives_from_run_state(operator, player_run, sessionmaker):
    # Sourced straight from Run.lives (the Devil-mode pool remaining) --
    # there is no separate ledger for this the way there is for trophies or
    # released rewards, so run-state bookkeeping IS the authoritative
    # source here.
    async with sessionmaker() as session:
        await session.execute(update(Run).where(Run.id == player_run.id).values(lives=2))
        await session.commit()

    body = (await operator.get("/api/operator/state")).json()
    assert body["runs"][0]["lives"] == 2


async def test_operator_state_trophies_reflects_the_ledger(operator, player_run, sessionmaker):
    # Sourced from trophies_earned (RunRepository.earned_trophies), the same
    # ledger RunView.trophies (run_routes.py) reads -- never a bookkeeping
    # count that could disagree with what was actually awarded. Run itself
    # carries no `trophies` column to fall back to by accident.
    repo = RunRepository(sessionmaker)
    assert await repo.award_trophy(player_run.id, "first-blood") is True
    assert await repo.award_trophy(player_run.id, "speedrunner") is True

    body = (await operator.get("/api/operator/state")).json()
    assert sorted(body["runs"][0]["trophies"]) == ["first-blood", "speedrunner"]


async def test_operator_state_trophies_is_empty_before_any_are_earned(operator, player_run):
    body = (await operator.get("/api/operator/state")).json()
    assert body["runs"][0]["trophies"] == []


class FakeSocket:
    """Records every payload sent to it. See tests/test_realtime.py for the
    Hub-level version this mirrors."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


async def test_a_released_code_reaches_the_player_channel_never_the_operator_channel(
    operator, player_run
):
    player_socket = FakeSocket()
    operator_socket = FakeSocket()
    await hub.connect(player_channel(player_run.id), player_socket)
    await hub.connect(OPERATOR_CHANNEL, operator_socket)
    try:
        response = await operator.post(
            "/api/operator/approve", json={"run_id": player_run.id, "reward_id": 1}
        )
        assert response.status_code == 200

        code_messages_to_player = [m for m in player_socket.sent if m.get("type") == "code_released"]
        code_messages_to_operator = [
            m for m in operator_socket.sent if m.get("type") == "code_released"
        ]
        assert len(code_messages_to_player) == 1
        assert code_messages_to_player[0]["code"] == "R1"
        assert code_messages_to_operator == [], "a gift-card code reached the operator channel"
    finally:
        await hub.disconnect(player_channel(player_run.id), player_socket)
        await hub.disconnect(OPERATOR_CHANNEL, operator_socket)


# ---------------------------------------------------------------------------
# The checkpoint bypass: the one route that defeats the gate on purpose.
# ---------------------------------------------------------------------------

async def _park_at_checkpoint(sessionmaker, run_id: int, segment: int = 4) -> None:
    """Put a run exactly where a player stuck at a checkpoint would be."""
    async with sessionmaker() as session:
        await session.execute(
            update(Run).where(Run.id == run_id).values(
                phase="checkpoint", segment=segment,
                cleared_segments=list(range(1, segment + 1)),
            )
        )
        await session.commit()


async def test_the_bypass_passes_the_checkpoint_and_hands_over_the_code(
    operator, player_run, sessionmaker, app
):
    app.state.config = None  # use the real example config's shape
    await _park_at_checkpoint(sessionmaker, player_run.id)

    body = (await operator.post(
        "/api/operator/pass-checkpoint", json={"run_id": player_run.id}
    )).json()

    # It does the whole job: the run moves on AND the card is handed over.
    # Half of that is what the operator already had via /approve, and it is
    # exactly the half that left a run holding a released reward while still
    # sitting on the checkpoint screen.
    assert body["phase"] == "game"
    assert body["segment"] == 5
    assert body["released"]["code"] == "R1"
    assert body["released"]["reward_id"] == 1


async def test_the_bypass_needs_no_passphrase_but_still_needs_an_operator(app, player_run, sessionmaker):
    """The gate is defeated for the OPERATOR, not for anyone who asks."""
    await _park_at_checkpoint(sessionmaker, player_run.id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        assert (await c.post(
            "/api/operator/pass-checkpoint", json={"run_id": player_run.id}
        )).status_code == 401
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        assert (await c.post(
            "/api/operator/pass-checkpoint", json={"run_id": player_run.id}
        )).status_code == 403

    # ...and nothing moved.
    async with sessionmaker() as session:
        run = (await session.execute(select(Run).where(Run.id == player_run.id))).scalar_one()
        assert run.phase == "checkpoint", "a refused bypass must not advance the run"


async def test_the_bypass_refuses_when_the_run_is_not_at_a_checkpoint(
    operator, player_run, sessionmaker
):
    """It cannot be used to skip the run -- only to unstick a real checkpoint.

    Without this, a mistimed click is a free segment skip, and the failure
    mode is silent: the operator would see a success and never know the run
    jumped somewhere it had not earned.
    """
    async with sessionmaker() as session:
        await session.execute(
            update(Run).where(Run.id == player_run.id).values(phase="game", segment=2)
        )
        await session.commit()

    response = await operator.post(
        "/api/operator/pass-checkpoint", json={"run_id": player_run.id}
    )
    assert response.status_code == 409
    # The message names where the run ACTUALLY is -- he pressed the button
    # because he believed it was somewhere else.
    assert "phase=game" in response.json()["detail"]
    assert "segment=2" in response.json()["detail"]


async def test_the_bypass_reports_an_unknown_run_rather_than_creating_one(operator):
    response = await operator.post("/api/operator/pass-checkpoint", json={"run_id": 9999})
    assert response.status_code == 404


async def test_the_bypass_reaches_the_players_screen(operator, player_run, sessionmaker, app):
    """The bypass has no HTTP response going to the player, so the socket is
    the ONLY way his screen ever learns anything. A bypass that advanced the
    run without telling him would leave him staring at a checkpoint prompt
    for a gate that had already opened."""
    app.state.config = None
    await _park_at_checkpoint(sessionmaker, player_run.id)

    seen: list = []

    class FakeSocket:
        async def send_json(self, payload: dict) -> None:
            seen.append(payload)

    socket = FakeSocket()
    await hub.connect(player_channel(player_run.id), socket)
    try:
        await operator.post("/api/operator/pass-checkpoint", json={"run_id": player_run.id})
    finally:
        await hub.disconnect(player_channel(player_run.id), socket)

    kinds = [m.get("kind") or m.get("type") for m in seen]
    assert any("state" in str(k) for k in kinds), f"no run-state message: {kinds}"
    assert any("R1" == m.get("code") for m in seen), (
        f"the code never reached the player's socket: {seen}"
    )


# ---------------------------------------------------------------------------
# Reset — the testing tool, and the most destructive button on the dashboard.
# ---------------------------------------------------------------------------

async def test_reset_puts_the_run_back_to_its_first_screen(operator, player_run, sessionmaker):
    await _park_at_checkpoint(sessionmaker, player_run.id)
    repo = RunRepository(sessionmaker)
    await repo.award_trophy(player_run.id, "game-1")

    body = (await operator.post(
        "/api/operator/reset-run", json={"run_id": player_run.id, "confirm": "RESET"}
    )).json()

    assert body["run_id"] == player_run.id
    assert body["deleted"]["trophies_earned"] == 1

    async with sessionmaker() as session:
        run = (await session.execute(select(Run).where(Run.id == player_run.id))).scalar_one()
        assert run.phase == "activation"
        assert run.segment == 0
        assert run.difficulty is None
        assert run.cleared_segments == []
        assert run.lives is None
    assert await repo.earned_trophies(player_run.id) == frozenset()


async def test_reset_clears_the_ledger_so_a_code_can_be_released_again(
    operator, player_run, sessionmaker, settings
):
    """The whole point, and the whole danger, in one test.

    `code_releases` is what makes a release at-most-once. A test rerun needs
    that cleared; the night must never have it cleared by accident.
    """
    vault = VaultService(sessionmaker, settings)
    first = await vault.release(player_run.id, 1, approved_by_operator=True)
    with pytest.raises(AlreadyReleased):
        await vault.release(player_run.id, 1, approved_by_operator=True)

    body = (await operator.post(
        "/api/operator/reset-run", json={"run_id": player_run.id, "confirm": "RESET"}
    )).json()
    assert body["deleted"]["code_releases"] == 1

    # Releasable again — which is exactly why this needs a typed confirmation.
    again = await vault.release(player_run.id, 1, approved_by_operator=True)
    assert again == first


async def test_reset_refuses_without_the_typed_confirmation(operator, player_run, sessionmaker):
    for payload in ({"run_id": player_run.id, "confirm": ""},
                    {"run_id": player_run.id, "confirm": "reset"},
                    {"run_id": player_run.id, "confirm": "yes"}):
        response = await operator.post("/api/operator/reset-run", json=payload)
        assert response.status_code == 400, payload

    async with sessionmaker() as session:
        run = (await session.execute(select(Run).where(Run.id == player_run.id))).scalar_one()
        assert run.phase != "activation" or run.segment == 0  # untouched either way


async def test_reset_needs_an_operator(app, player_run):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        payload = {"run_id": player_run.id, "confirm": "RESET"}
        assert (await c.post("/api/operator/reset-run", json=payload)).status_code == 401
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        assert (await c.post("/api/operator/reset-run", json=payload)).status_code == 403


async def test_reset_reports_an_unknown_run(operator):
    response = await operator.post(
        "/api/operator/reset-run", json={"run_id": 4242, "confirm": "RESET"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Skip game — the narrow rescue: clears the game, never the question.
# ---------------------------------------------------------------------------

async def _park_at_game(sessionmaker, run_id: int, segment: int = 3) -> None:
    async with sessionmaker() as session:
        await session.execute(
            update(Run).where(Run.id == run_id).values(
                phase="game", segment=segment,
                cleared_segments=list(range(1, segment)),
            )
        )
        await session.commit()


async def test_skip_clears_the_game_and_lands_on_its_question(
    operator, player_run, sessionmaker, app
):
    app.state.config = None
    await _park_at_game(sessionmaker, player_run.id, segment=3)

    body = (await operator.post(
        "/api/operator/skip-game", json={"run_id": player_run.id}
    )).json()

    assert body["phase"] == "question"
    assert body["segment"] == 3, "the question for THIS segment, not the next one"
    # Counts as a pass, so the skill trophy is awarded exactly as if played.
    assert "game-3" in await RunRepository(sessionmaker).earned_trophies(player_run.id)


async def test_skip_does_not_answer_the_question_for_him(
    operator, player_run, sessionmaker, app
):
    """The narrow part. Skipping the game must never clear the segment --
    the memory half is the whole point of the run and is not the operator's
    to hand over."""
    app.state.config = None
    await _park_at_game(sessionmaker, player_run.id, segment=3)
    await operator.post("/api/operator/skip-game", json={"run_id": player_run.id})

    async with sessionmaker() as session:
        run = (await session.execute(select(Run).where(Run.id == player_run.id))).scalar_one()
        assert run.phase == "question"
        assert 3 not in run.cleared_segments
    assert "question-3" not in await RunRepository(sessionmaker).earned_trophies(player_run.id)


async def test_skip_refuses_when_the_run_is_not_at_a_game(operator, player_run, sessionmaker):
    await _park_at_checkpoint(sessionmaker, player_run.id)
    response = await operator.post("/api/operator/skip-game", json={"run_id": player_run.id})
    assert response.status_code == 409
    assert "phase=checkpoint" in response.json()["detail"]


async def test_skip_needs_an_operator(app, player_run, sessionmaker):
    await _park_at_game(sessionmaker, player_run.id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        payload = {"run_id": player_run.id}
        assert (await c.post("/api/operator/skip-game", json=payload)).status_code == 401
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        assert (await c.post("/api/operator/skip-game", json=payload)).status_code == 403
