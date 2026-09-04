"""Player and operator WebSocket endpoints.

Both authenticate from the session cookie BEFORE accepting the handshake:
`_authenticate` calls `websocket.close(code=...)` and returns `None` without
ever calling `websocket.accept()` when the cookie is missing, unsigned, or
the wrong role -- rejecting the connection outright rather than accepting it
and erroring afterwards (which would look, to a client, like a connection
that opened and then mysteriously died).

IMPORTANT for whoever writes the browser client -- the 4401 close code in
`_authenticate` never actually reaches a real browser. Calling
`websocket.close(code=4401)` BEFORE `websocket.accept()` makes Starlette
respond to the WebSocket upgrade request with a plain HTTP 403, because the
handshake itself was never completed -- uvicorn denies the upgrade and no
close frame (carrying 4401 or any other code) is ever transmitted. Only
Starlette's OWN test client (`TestClient`/`WebSocketTestSession`)
synthesises a `WebSocketDisconnect(code=4401)` for this case in-process, so
the test suite observing `exc.value.code == 4401` is real but is not
representative of what a browser sees. A real client's WebSocket `onerror`/
`onclose` handler will see a failed handshake (effectively an HTTP 403
during the upgrade, not a `CloseEvent` with code 4401) for an auth failure,
and must not rely on inspecting a close code to detect it -- check for the
connection never having opened instead. This is deliberate, not a bug:
rejecting before accepting is strictly better than accepting the socket and
erroring afterwards (which looks, to a client, like a connection that
opened and then mysteriously died), so this is NOT something to
"fix" by restructuring auth to accept-then-close. 4404 (no run yet, in
`player_socket` below) is a POST-accept close and does deliver its close
code to a real client normally, since the handshake already completed by
the time it fires.

The player channel is never taken from anything the client sends. It is
derived entirely from the session's `account_id` -> that account's own
`Run` -> `player_channel(run.id)`. There is no code path here that lets an
authenticated player ask for a DIFFERENT run's channel -- the only
"channel selection" available to a player socket is implicit in who they
are signed in as.
"""

import logging

import anyio
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from xxvi.api.run_service import RunService
from xxvi.auth.sessions import SESSION_COOKIE, SessionData, read_session
from xxvi.content.loader import get_config
from xxvi.games.tokens import TokenService
from xxvi.gates.service import GateService
from xxvi.persistence.repositories import RunRepository
from xxvi.realtime.hub import OPERATOR_CHANNEL, hub, player_channel
from xxvi.realtime.messages import OperatorPresenceMsg, TrophyPopMsg
from xxvi.settings import Settings, get_settings
from xxvi.vault.service import VaultService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ws")


async def _authenticate(websocket: WebSocket, expected_role: str) -> SessionData | None:
    token = websocket.cookies.get(SESSION_COOKIE)
    session = read_session(token) if token else None
    if session is None or session.role != expected_role:
        await websocket.close(code=4401)
        return None
    await websocket.accept()
    return session


@router.websocket("/player")
async def player_socket(
    websocket: WebSocket, settings: Settings = Depends(get_settings)
) -> None:
    session = await _authenticate(websocket, "player")
    if session is None:
        return

    repo = RunRepository(websocket.app.state.sessionmaker)
    run = await repo.get_by_account(session.account_id)
    if run is None:
        await websocket.close(code=4404)
        return

    # Derived from the session, never from client input -- see module docstring.
    channel = player_channel(run.id)
    await hub.connect(channel, websocket)
    try:
        await websocket.send_json(OperatorPresenceMsg(online=hub.operator_online()).model_dump())

        # HIDDEN_RAGE_QUIT: "he closed the tab and came back." This connect
        # is only "coming back" if a PREVIOUS connection on this same run
        # ended -- recorded as a `player_disconnected` event in the
        # `finally` block below -- so `RunService.check_hidden` is
        # evaluated with `reconnecting=True` right here, on every fresh
        # connect, not just the first. A bug in this check must never cost
        # the player their connection: wrapped the same way
        # `run_routes._publish` wraps its operator-channel broadcast, so
        # any failure here is at most a missed pop, logged and swallowed,
        # never a broken socket.
        try:
            sessionmaker = websocket.app.state.sessionmaker
            config = getattr(websocket.app.state, "config", None) or get_config()
            service = RunService(
                repo=repo,
                config=config,
                gates=GateService(repo, settings),
                vault=VaultService(sessionmaker, settings),
                tokens=TokenService(repo),
            )
            state = RunRepository.to_state(run)
            for trophy in await service.check_hidden(run, state, reconnecting=True):
                await hub.broadcast(
                    channel,
                    TrophyPopMsg(trophy_id=trophy.id, name=trophy.name, grade=trophy.grade),
                )
        except Exception:  # see comment above: deliberately broad, never the socket's problem.
            logger.warning(
                "hidden-trophy check on reconnect failed; connection unaffected", exc_info=True
            )

        try:
            while True:
                await websocket.receive_text()  # client sends heartbeats only
        except WebSocketDisconnect:
            pass
    finally:
        # Deliberately wraps EVERYTHING from `hub.connect` above to here,
        # not just the receive loop: a disconnect -- or a cancellation,
        # e.g. the ASGI server cancelling in-flight connection tasks on a
        # graceful shutdown, which is exactly the shape of interruption a
        # live one-shot event could hit mid-run -- can land at any of the
        # awaits above (sending the initial presence message, or anywhere
        # inside the hidden-trophy check), not only inside the receive
        # loop, and this socket's hub slot must still be released and the
        # disconnect still recorded either way.
        #
        # `anyio.CancelScope(shield=True)`: once a cancellation has already
        # been delivered to this task, every checkpoint reached while still
        # inside the SAME cancelled scope re-raises immediately -- an
        # unshielded `await` in this finally block would itself be
        # cancelled before the write ever reaches the database, silently
        # losing the very disconnect record HIDDEN_RAGE_QUIT depends on.
        # Shielding is what lets this specific bit of cleanup actually run
        # to completion instead of merely being attempted.
        with anyio.CancelScope(shield=True):
            try:
                await repo.append_event(run.id, "player_disconnected", {})
            except Exception:  # deliberately broad -- never block releasing the hub slot below.
                logger.warning("failed to record player_disconnected event", exc_info=True)
            await hub.disconnect(channel, websocket)


@router.websocket("/operator")
async def operator_socket(websocket: WebSocket) -> None:
    session = await _authenticate(websocket, "operator")
    if session is None:
        return

    await hub.connect(OPERATOR_CHANNEL, websocket)
    # Tell every connected player that the operator has arrived. Only ever
    # OperatorPresenceMsg here -- never a message that could carry a
    # gift-card code (that's CodeReleasedMsg, sent exclusively from
    # operator_routes.approve_release directly to a single player_channel).
    for channel in hub.channels():
        if channel.startswith("player:"):
            await hub.broadcast(channel, OperatorPresenceMsg(online=True))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(OPERATOR_CHANNEL, websocket)
        for channel in hub.channels():
            if channel.startswith("player:"):
                await hub.broadcast(channel, OperatorPresenceMsg(online=hub.operator_online()))
