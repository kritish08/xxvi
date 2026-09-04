"""In-process fan-out hub for player and operator WebSocket channels.

Single instance, single process, by design — one player, one operator, one
running event. No Redis, no pub/sub, no cross-process mechanism: that is
explicitly out of scope for this module.

Never log a message payload here. `CodeReleasedMsg` carries a real
gift-card code, and it is only ever sent on a player channel — logging a
payload would write that code to the logs.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Protocol

from xxvi.realtime.messages import ServerMessage

logger = logging.getLogger(__name__)

OPERATOR_CHANNEL = "operator"

# A local WebSocket send should resolve near-instantly. A socket that hangs
# instead of raising is a different failure than a dead one, but it must be
# treated the same way: the trophy pop broadcasts to a channel, and a single
# stuck recipient must never block delivery to everyone else on it.
SEND_TIMEOUT_SECONDS = 2.0


def player_channel(run_id: int) -> str:
    return f"player:{run_id}"


class SocketLike(Protocol):
    async def send_json(self, payload: dict[str, Any]) -> None: ...


class Hub:
    """In-process fan-out. Single instance by design — one player, one operator."""

    def __init__(self, send_timeout: float = SEND_TIMEOUT_SECONDS) -> None:
        self._channels: dict[str, set[SocketLike]] = defaultdict(set)
        self._send_timeout = send_timeout

    async def connect(self, channel: str, socket: SocketLike) -> None:
        self._channels[channel].add(socket)

    async def disconnect(self, channel: str, socket: SocketLike) -> None:
        self._channels[channel].discard(socket)

    def channels(self) -> tuple[str, ...]:
        """Read-only snapshot of currently-known channel names. Lets callers
        (e.g. the operator socket, fanning `OperatorPresenceMsg` out to every
        connected player) enumerate channels without reaching into `_channels`
        directly."""
        return tuple(self._channels)

    def operator_online(self) -> bool:
        return bool(self._channels.get(OPERATOR_CHANNEL))

    async def broadcast(self, channel: str, message: ServerMessage) -> int:
        payload = message.model_dump()
        delivered = 0
        for socket in list(self._channels.get(channel, ())):
            try:
                await asyncio.wait_for(
                    socket.send_json(payload), timeout=self._send_timeout
                )
                delivered += 1
            except Exception:  # noqa: BLE001 — a dead or hung socket must
                # never break a trophy pop for anyone else on the channel,
                # so any failure from an unknown transport — including a
                # send that times out instead of raising — is deliberately
                # caught broadly here. `asyncio.wait_for` raises
                # `TimeoutError`, a plain `Exception` subclass, so it is
                # caught by this same branch; `CancelledError` is a
                # `BaseException` and still propagates. Drop the socket and
                # keep going. Never log `payload` — it may carry a
                # gift-card code.
                logger.info("dropping dead or hung socket on channel %s", channel)
                self._channels[channel].discard(socket)
        return delivered


hub = Hub()
