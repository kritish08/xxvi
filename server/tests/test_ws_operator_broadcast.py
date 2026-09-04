"""Task 29: run-state changes are now fanned out to the operator channel
too (xxvi/api/run_routes.py's `_publish`), not just the player's own
channel -- closing the gap where a connected operator socket existed
(ws_routes.py's `operator_socket`, which is what makes `hub.operator_online()`
true) but nothing was ever actually broadcast to it, leaving the
dashboard's 2s poll as its only real freshness signal.

Uses starlette.testclient.TestClient, exactly like tests/test_ws.py (whose
docstring explains why: httpx's ASGITransport doesn't speak the WebSocket
protocol). Fixtures and the `_receive_json_with_timeout` /
`_assert_nothing_arrives` helpers are deliberately re-declared here rather
than imported from test_ws.py -- pytest fixtures resolve by name from the
importing module's own namespace, and importing a same-named fixture
function from another test file does not reliably wire it into this
file's fixture graph the way defining it locally does.
"""

import queue
import threading

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from xxvi.auth.passwords import hash_password
from xxvi.auth.sessions import SESSION_COOKIE
from xxvi.content.loader import load_config
from xxvi.main import create_app, seed_accounts
from xxvi.persistence.models import Account, Base
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings, get_settings
from tests.paths import EXAMPLE_CONFIG

CODE = "ABCD-EFGH-IJKL"


@pytest.fixture
async def sessionmaker(tmp_path):
    # File-backed, not the shared in-memory StaticPool fixture used
    # elsewhere -- see test_ws.py's identical fixture docstring: the
    # WebSocket handshake runs on TestClient's own background thread/loop,
    # which an in-memory aiosqlite connection is not safe to share with.
    db_path = tmp_path / "ws-operator-broadcast-test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def settings():
    return Settings(
        player_username="him", player_password_hash=hash_password("pw"),
        operator_username="me", operator_password_hash=hash_password("pw"),
        activation_code_hash=hash_password(CODE),
        go_live_iso="2020-01-01T00:00:00+05:30",  # already live
    )


@pytest.fixture
async def app(sessionmaker, settings):
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.state.sessionmaker = sessionmaker
    application.state.config = load_config(EXAMPLE_CONFIG)
    await seed_accounts(sessionmaker, settings)
    return application


def _receive_json_with_timeout(ws, timeout: float = 2.0):
    """See test_ws.py's identical helper for the full rationale (a daemon
    thread + a bounded queue.get, so a channel-isolation regression that
    delivers nothing hangs the assertion instead of the whole suite)."""
    result_queue: queue.Queue = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            result_queue.put(("ok", ws.receive_json()))
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller below
            result_queue.put(("error", exc))

    threading.Thread(target=_worker, daemon=True).start()
    try:
        kind, value = result_queue.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError(f"no message received within {timeout}s") from None
    if kind == "error":
        raise value
    return value


def _assert_nothing_arrives(ws, timeout: float = 0.5) -> None:
    with pytest.raises(TimeoutError):
        _receive_json_with_timeout(ws, timeout=timeout)


def _cookie_for(client: TestClient, username: str, password: str) -> str:
    client.post("/api/auth/login", json={"username": username, "password": password})
    token = client.cookies.get(SESSION_COOKIE)
    assert token is not None
    return token


async def _make_run(sessionmaker, username: str) -> int:
    # ws_routes.py's player_socket looks the run up with
    # `RunRepository.get_by_account` directly (closing 4404 if it finds
    # none) rather than going through `RunService.load()`'s
    # get-or-create -- so unlike an HTTP-only test, the run has to exist
    # BEFORE the player socket connects.
    async with sessionmaker() as session:
        result = await session.execute(select(Account).where(Account.username == username))
        account = result.scalar_one()
    run = await RunRepository(sessionmaker).create(account.id, None)
    return run.id


async def test_operator_socket_hears_a_run_state_change_live(app, sessionmaker):
    await _make_run(sessionmaker, "him")

    client_him = TestClient(app, base_url="https://testserver")
    token_him = _cookie_for(client_him, "him", "pw")
    client_operator = TestClient(app, base_url="https://testserver")
    token_operator = _cookie_for(client_operator, "me", "pw")

    with client_him.websocket_connect(
        "/api/ws/player", cookies={SESSION_COOKIE: token_him}
    ) as ws_him, client_operator.websocket_connect(
        "/api/ws/operator", cookies={SESSION_COOKIE: token_operator}
    ) as ws_operator:
        _receive_json_with_timeout(ws_him)  # operator_presence, sent at connect time

        # A real player action -- POST /api/run/activate, which
        # `_publish`'s only caller list is built from (run_routes.py) --
        # sent while BOTH sockets are live, not a raw hub.broadcast() call.
        response = client_him.post(
            "/api/run/activate", json={"code": CODE}, cookies={SESSION_COOKIE: token_him}
        )
        assert response.status_code == 200
        assert response.json()["phase"] == "profile"

        player_message = _receive_json_with_timeout(ws_him)
        operator_message = _receive_json_with_timeout(ws_operator)

        assert player_message["type"] == "run_state"
        assert player_message["phase"] == "profile"
        # The operator dashboard hears the exact same state change, over
        # the same live connection, at the same time -- not just on its
        # own next 2s poll.
        assert operator_message == player_message


async def test_a_broadcast_failure_to_the_operator_channel_never_breaks_the_players_own_request(
    app, sessionmaker, monkeypatch
):
    # The explicit requirement this broadcast was built under: a dropped or
    # misbehaving operator socket must never turn into a 500 for the
    # player's own mutating request. `Hub.broadcast` already swallows a
    # per-socket send failure internally (never raises out of a bad
    # recipient -- see its own docstring), and `_publish` additionally
    # wraps its OPERATOR_CHANNEL calls in their own try/except as
    # defence-in-depth against that guarantee ever regressing. Prove the
    # outer layer really does catch it: monkeypatch `hub.broadcast` itself
    # to raise outright (a harder failure than anything a real socket could
    # produce) whenever the operator channel is the target, and confirm the
    # player's request still succeeds and the player still gets their own
    # broadcast.
    from xxvi.realtime.hub import OPERATOR_CHANNEL, hub

    real_broadcast = hub.broadcast

    async def flaky_broadcast(channel, message):
        if channel == OPERATOR_CHANNEL:
            raise RuntimeError("simulated operator-channel failure")
        return await real_broadcast(channel, message)

    monkeypatch.setattr(hub, "broadcast", flaky_broadcast)

    await _make_run(sessionmaker, "him")
    client_him = TestClient(app, base_url="https://testserver")
    token_him = _cookie_for(client_him, "him", "pw")

    with client_him.websocket_connect(
        "/api/ws/player", cookies={SESSION_COOKIE: token_him}
    ) as ws_him:
        _receive_json_with_timeout(ws_him)  # operator_presence

        response = client_him.post(
            "/api/run/activate", json={"code": CODE}, cookies={SESSION_COOKIE: token_him}
        )
        assert response.status_code == 200
        assert response.json()["phase"] == "profile"

        player_message = _receive_json_with_timeout(ws_him)
        assert player_message["type"] == "run_state"
        assert player_message["phase"] == "profile"
