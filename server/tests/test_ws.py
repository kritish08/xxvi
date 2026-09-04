"""WebSocket auth and channel-isolation tests for xxvi/api/ws_routes.py.

Uses starlette.testclient.TestClient rather than httpx.AsyncClient: httpx's
ASGITransport doesn't speak the WebSocket protocol. Two quirks worth noting
for anyone extending this file:

  - TestClient's `websocket_connect` targets a fixed "testserver" host
    regardless of `base_url`, and (in this starlette version) does not
    reliably forward cookies set by an earlier `.post()` through its
    persistent jar into the upgrade request. Both tests below extract the
    session cookie's value from `client.cookies` after logging in and pass
    it explicitly via `websocket_connect(..., cookies={...})`.
  - TestClient is sync, but bridges to the app's async code via its own
    portal; it works fine against the async `sessionmaker` fixture used
    throughout this suite.
"""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from xxvi.auth.passwords import hash_password
from xxvi.auth.sessions import SESSION_COOKIE
from xxvi.content.loader import get_config
from xxvi.core.models import Difficulty
from xxvi.main import create_app, seed_accounts
from xxvi.persistence.models import Account, Base, RunEvent, TrophyEarned
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings, get_settings


# starlette.testclient.TestClient runs the ASGI app's WebSocket handling in
# a background thread with its own event loop (via an anyio portal). The
# shared in-memory `sessionmaker` fixture from conftest.py is backed by
# SQLAlchemy's StaticPool over a single shared aiosqlite connection, which
# is not safe to touch from a different thread/loop than the one that
# opened it -- see tests/test_games_concurrency.py's fixture docstring for
# the identical reasoning (that one needs it for genuine concurrency, this
# one needs it for genuine cross-thread access). A file-backed database
# with NullPool gives every `sessionmaker()` call its own real connection.
@pytest.fixture
async def sessionmaker(tmp_path):
    db_path = tmp_path / "ws-test.db"
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
        go_live_iso="2020-01-01T00:00:00+05:30",
    )


@pytest.fixture
async def app(sessionmaker, settings):
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.state.sessionmaker = sessionmaker
    await seed_accounts(sessionmaker, settings)
    return application


def _receive_json_with_timeout(ws, timeout: float = 2.0):
    """`WebSocketTestSession.receive_json()` blocks on a queue with no
    timeout of its own. If a channel-isolation bug ever delivers a message
    to the WRONG socket (this file's whole point), the RIGHT socket's
    blocking receive would hang forever waiting for a message that's never
    coming -- turning a real regression into a stuck test run instead of a
    clean failure.

    Run the receive on a DAEMON thread and wait on a `queue.Queue` with a
    timeout, rather than `concurrent.futures.ThreadPoolExecutor` (whose
    `__exit__`/`shutdown` blocks waiting for the worker to finish even
    after `future.result(timeout=...)` has already raised -- which hangs
    exactly as badly as not having a timeout at all when the receive never
    returns). A daemon thread that's still blocked when we give up on it
    is abandoned, not joined, so it can never block the test suite.
    """
    import queue
    import threading

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
        raise TimeoutError(
            f"no message received within {timeout}s -- likely delivered to the wrong channel"
        ) from None
    if kind == "error":
        raise value
    return value


def _assert_nothing_arrives(ws, timeout: float = 0.5) -> None:
    """The directional counterpart to `_receive_json_with_timeout`: proves a
    socket receives NOTHING, rather than proving it receives the right
    thing. `_receive_json_with_timeout` alone can only check one direction
    of a leak -- it reads a specific socket after a specific broadcast and
    asserts the payload it got, but never proves that OTHER sockets got
    nothing from that same broadcast. A superset-subscription leak (a
    socket silently joined to channels beyond its own) can survive a suite
    that only ever reads the "expected" recipient after each broadcast, as
    long as no test ever also confirms an unexpected recipient's queue
    stayed empty. Success here IS the timeout: a message arriving within
    `timeout` is the failure.
    """
    with pytest.raises(TimeoutError):
        _receive_json_with_timeout(ws, timeout=timeout)


def _cookie_for(client: TestClient, username: str, password: str) -> str:
    client.post("/api/auth/login", json={"username": username, "password": password})
    token = client.cookies.get(SESSION_COOKIE)
    assert token is not None
    return token


async def _make_run(sessionmaker, username: str) -> int:
    async with sessionmaker() as session:
        result = await session.execute(select(Account).where(Account.username == username))
        account = result.scalar_one()
    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    return run.id


async def test_player_socket_rejects_an_anonymous_connection(app):
    client = TestClient(app, base_url="https://testserver")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ws/player"):
            pass
    assert exc.value.code == 4401


async def test_player_socket_rejects_an_operator_session(app):
    client = TestClient(app, base_url="https://testserver")
    token = _cookie_for(client, "me", "pw")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ws/player", cookies={SESSION_COOKIE: token}):
            pass
    assert exc.value.code == 4401


async def test_operator_socket_rejects_a_player_session(app):
    client = TestClient(app, base_url="https://testserver")
    token = _cookie_for(client, "him", "pw")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ws/operator", cookies={SESSION_COOKIE: token}):
            pass
    assert exc.value.code == 4401


async def test_player_socket_rejects_before_a_run_exists(app):
    # Distinct from the auth cases above: the session cookie is valid here
    # (the handshake IS accepted), so this closes as a normal post-accept
    # close rather than a handshake rejection -- the disconnect surfaces on
    # the next receive, not at connect time.
    client = TestClient(app, base_url="https://testserver")
    token = _cookie_for(client, "him", "pw")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ws/player", cookies={SESSION_COOKIE: token}) as ws:
            ws.receive_json()
    assert exc.value.code == 4404


async def test_a_valid_player_connects_and_hears_operator_presence(app, sessionmaker):
    await _make_run(sessionmaker, "him")
    client = TestClient(app, base_url="https://testserver")
    token = _cookie_for(client, "him", "pw")
    with client.websocket_connect("/api/ws/player", cookies={SESSION_COOKIE: token}) as ws:
        first = ws.receive_json()
        assert first["type"] == "operator_presence"
        assert first["online"] is False


async def test_a_valid_operator_connects(app):
    client = TestClient(app, base_url="https://testserver")
    token = _cookie_for(client, "me", "pw")
    # Just needs to not raise/close -- the operator socket has no initial
    # message of its own (it only fans OperatorPresenceMsg OUT to players).
    with client.websocket_connect("/api/ws/operator", cookies={SESSION_COOKIE: token}):
        pass


async def test_reconnecting_after_a_disconnect_pops_hidden_rage_quit(app, sessionmaker):
    # Task 24: HIDDEN_RAGE_QUIT ("he closed the tab and came back") is
    # evaluated in `player_socket` itself, not somewhere a unit test can
    # reach without a socket -- the `finally` block records
    # `player_disconnected` when the FIRST connection ends, and the
    # SECOND connection's `check_hidden(..., reconnecting=True)` call must
    # see it and broadcast the pop back onto the very socket that just
    # reconnected.
    run_id = await _make_run(sessionmaker, "him")
    client = TestClient(app, base_url="https://testserver")
    token = _cookie_for(client, "him", "pw")

    with client.websocket_connect("/api/ws/player", cookies={SESSION_COOKIE: token}) as ws:
        first = _receive_json_with_timeout(ws)
        assert first["type"] == "operator_presence"
        # First-ever connection: no prior disconnect on the log, so this
        # must NOT pop.
        _assert_nothing_arrives(ws)

    # Exiting the `with` block above only guarantees the CLIENT side has
    # sent a close frame -- the server-side task's own `finally` block
    # (which is what actually writes `player_disconnected`) runs on
    # TestClient's background portal thread and is not guaranteed to have
    # completed by the time `__exit__` returns. Poll briefly rather than
    # asserting immediately.
    kinds: list[str] = []
    for _ in range(20):
        async with sessionmaker() as session:
            result = await session.execute(select(RunEvent).where(RunEvent.run_id == run_id))
            kinds = [row.kind for row in result.scalars()]
        if "player_disconnected" in kinds:
            break
        await asyncio.sleep(0.05)
    assert "player_disconnected" in kinds, "closing the socket must record the disconnect"

    with client.websocket_connect("/api/ws/player", cookies={SESSION_COOKIE: token}) as ws2:
        presence = _receive_json_with_timeout(ws2)
        assert presence["type"] == "operator_presence"

        pop = _receive_json_with_timeout(ws2)
        assert pop["type"] == "trophy_pop"
        assert pop["trophy_id"] == "hidden-rage-quit"
        # The pop carries whatever RunConfig actually has for this trophy's
        # `name` -- config/run.example.yaml's is still the "???" content
        # placeholder (see task-24-brief.md's "Content still required"),
        # so this deliberately does NOT assert a specific/real name, only
        # that the message threads the config's own value through
        # unmasked (unlike /api/content's listing, which masks a hidden
        # trophy's name only until it's earned -- this run just earned it).
        configured = next(t for t in get_config().trophies if t.id == "hidden-rage-quit")
        assert pop["name"] == configured.name
        assert pop["grade"] == configured.grade

    async with sessionmaker() as session:
        result = await session.execute(
            select(TrophyEarned).where(
                TrophyEarned.run_id == run_id, TrophyEarned.trophy_id == "hidden-rage-quit"
            )
        )
        rows = result.scalars().all()
    assert len(rows) == 1, "the reconnect pop must correspond to exactly one earned row"


async def test_a_player_socket_only_ever_hears_its_own_runs_channel(app, sessionmaker):
    # Two players, two runs. There is no client-supplied "which channel"
    # parameter anywhere in the player socket handler -- it's derived
    # entirely from the session's account -> that account's own run. This
    # confirms that derivation actually holds end-to-end: broadcasting to
    # run B's channel must never reach a socket authenticated as player A.
    async with sessionmaker() as session:
        session.add(Account(username="her", password_hash=hash_password("pw2"), role="player"))
        await session.commit()

    run_him = await _make_run(sessionmaker, "him")
    run_her = await _make_run(sessionmaker, "her")
    assert run_him != run_her

    client_him = TestClient(app, base_url="https://testserver")
    token_him = _cookie_for(client_him, "him", "pw")
    client_her = TestClient(app, base_url="https://testserver")
    token_her = _cookie_for(client_her, "her", "pw2")

    from xxvi.realtime.hub import hub, player_channel
    from xxvi.realtime.messages import ToastMsg

    with client_him.websocket_connect(
        "/api/ws/player", cookies={SESSION_COOKIE: token_him}
    ) as ws_him, client_her.websocket_connect(
        "/api/ws/player", cookies={SESSION_COOKIE: token_her}
    ) as ws_her:
        _receive_json_with_timeout(ws_him)  # operator_presence on connect
        _receive_json_with_timeout(ws_her)

        await hub.broadcast(player_channel(run_her), ToastMsg(text="for her only"))

        her_message = _receive_json_with_timeout(ws_her)
        assert her_message == {"type": "toast", "text": "for her only"}

        # "him"'s socket must have received NOTHING from run_her's channel.
        # If it had (silently subscribed to the wrong channel), send him a
        # message on his OWN channel now and confirm THAT (and only that,
        # and nothing left over from run_her's broadcast) is what arrives --
        # bounded by the timeout above rather than blocking forever.
        await hub.broadcast(player_channel(run_him), ToastMsg(text="for him only"))
        his_message = _receive_json_with_timeout(ws_him)
        assert his_message == {"type": "toast", "text": "for him only"}

        # The other direction, closing the blind spot: "her" socket must
        # have received NOTHING from the broadcast to run_him's channel
        # either. Without this, a socket that over-subscribes at connect
        # time to every player channel that already exists (a superset
        # leak, using the same `for channel in hub.channels(): ...` idiom
        # `operator_socket` uses to fan presence out) can pass every
        # assertion above: her own message still arrives correctly, and
        # HIS socket -- connected before her channel existed -- never sees
        # HER broadcast. Only re-reading HER socket after the SECOND
        # broadcast proves she didn't also silently pick up HIS channel.
        _assert_nothing_arrives(ws_her)
