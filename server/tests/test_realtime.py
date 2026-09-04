import asyncio
import logging

import pytest
from pydantic import TypeAdapter

from xxvi.realtime.hub import Hub
from xxvi.realtime.messages import (
    CodeReleasedMsg,
    GateResultMsg,
    OperatorPresenceMsg,
    RunStateMsg,
    ServerMessage,
    ToastMsg,
    TrophyPopMsg,
)


class FakeSocket:
    def __init__(self, fail: bool = False, hang: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail
        self.hang = hang
        self.call_count = 0

    async def send_json(self, payload: dict) -> None:
        self.call_count += 1
        if self.hang:
            await asyncio.sleep(3600)  # never resolves on its own
        if self.fail:
            raise RuntimeError("socket is gone")
        self.sent.append(payload)


async def test_broadcast_reaches_every_socket_on_a_channel():
    hub = Hub()
    a, b = FakeSocket(), FakeSocket()
    await hub.connect("player:1", a)
    await hub.connect("player:1", b)

    delivered = await hub.broadcast("player:1", ToastMsg(text="bro"))

    assert delivered == 2
    assert a.sent[0]["type"] == "toast"
    assert b.sent[0]["text"] == "bro"


async def test_channels_are_isolated():
    hub = Hub()
    player, operator = FakeSocket(), FakeSocket()
    await hub.connect("player:1", player)
    await hub.connect("operator", operator)

    await hub.broadcast("player:1", ToastMsg(text="only for him"))

    assert len(player.sent) == 1
    assert operator.sent == []


async def test_a_dead_socket_is_dropped_without_breaking_the_broadcast():
    hub = Hub()
    dead, alive = FakeSocket(fail=True), FakeSocket()
    await hub.connect("player:1", dead)
    await hub.connect("player:1", alive)

    delivered = await hub.broadcast("player:1", TrophyPopMsg(trophy_id="game-1", name="n", grade="bronze"))

    assert delivered == 1
    assert len(alive.sent) == 1
    assert await hub.broadcast("player:1", ToastMsg(text="again")) == 1


async def test_operator_presence_tracks_connections():
    hub = Hub()
    assert hub.operator_online() is False
    socket = FakeSocket()
    await hub.connect("operator", socket)
    assert hub.operator_online() is True
    await hub.disconnect("operator", socket)
    assert hub.operator_online() is False


async def test_broadcast_to_an_empty_channel_is_harmless():
    assert await Hub().broadcast("player:99", ToastMsg(text="nobody home")) == 0


async def test_dead_socket_is_not_retried_on_a_later_broadcast():
    # Distinct from test_a_dead_socket_is_dropped_without_breaking_the_broadcast:
    # that test only checks the *count* delivered stays correct across two
    # broadcasts, which is true whether or not the dead socket was actually
    # removed (it fails every time either way). This test checks the dead
    # socket's send_json is invoked exactly once, proving it was dropped
    # from the channel rather than retried forever.
    hub = Hub()
    dead, alive = FakeSocket(fail=True), FakeSocket()
    await hub.connect("player:1", dead)
    await hub.connect("player:1", alive)

    await hub.broadcast("player:1", ToastMsg(text="one"))
    await hub.broadcast("player:1", ToastMsg(text="two"))
    await hub.broadcast("player:1", ToastMsg(text="three"))

    assert dead.call_count == 1
    assert alive.call_count == 3


async def test_operator_online_is_false_when_only_players_are_connected():
    hub = Hub()
    await hub.connect("player:1", FakeSocket())
    await hub.connect("player:2", FakeSocket())

    assert hub.operator_online() is False


async def test_disconnect_removes_only_the_given_socket():
    hub = Hub()
    a, b = FakeSocket(), FakeSocket()
    await hub.connect("player:1", a)
    await hub.connect("player:1", b)

    await hub.disconnect("player:1", a)
    delivered = await hub.broadcast("player:1", ToastMsg(text="still here"))

    assert delivered == 1
    assert a.sent == []
    assert b.sent[0]["text"] == "still here"


@pytest.mark.parametrize(
    ("message", "expected_type"),
    [
        (RunStateMsg(phase="question", segment=1, difficulty=None, cleared_segments=[], released_rewards=[]), "run_state"),
        (TrophyPopMsg(trophy_id="t1", name="Trophy", grade="gold"), "trophy_pop"),
        (CodeReleasedMsg(reward_id=1, label="Reward", code="SECRET-1"), "code_released"),
        (ToastMsg(text="hi"), "toast"),
        (OperatorPresenceMsg(online=True), "operator_presence"),
        (GateResultMsg(gate="g", outcome="pass", attempts_remaining=None), "gate_result"),
    ],
)
def test_every_message_type_round_trips_through_the_discriminated_union(message, expected_type):
    # Guards the discriminator itself: if a message type's Literal "type"
    # value were ever changed, its own model would still build the dict
    # correctly, but re-parsing that dict through the ServerMessage union
    # (as a client mirroring these types would) must land back on the same
    # concrete class. This is the one contract OpenAPI does not check.
    adapter = TypeAdapter(ServerMessage)
    payload = message.model_dump()
    assert payload["type"] == expected_type

    reparsed = adapter.validate_python(payload)
    assert type(reparsed) is type(message)
    assert reparsed == message


async def test_broadcast_never_logs_the_message_payload(caplog):
    # CodeReleasedMsg carries a real gift-card code. Nothing in this module
    # may write a message payload to the logs, or a code would end up in
    # the log file. Force a dead-socket path (the only place the hub logs
    # anything) and assert the secret never appears in any log record.
    hub = Hub()
    dead = FakeSocket(fail=True)
    await hub.connect("player:1", dead)

    secret = "SUPER-SECRET-GIFT-CODE-42"
    with caplog.at_level(logging.DEBUG):
        await hub.broadcast(
            "player:1", CodeReleasedMsg(reward_id=1, label="Reward", code=secret)
        )

    assert secret not in caplog.text
    for record in caplog.records:
        assert secret not in str(record.args)
        assert secret not in record.getMessage()


async def test_a_hung_socket_does_not_block_delivery_to_the_rest_of_the_channel():
    # A socket that hangs instead of raising is a different failure than a
    # dead one: without a timeout on the individual send, the broadcast loop
    # would await it forever and nothing after it in iteration order would
    # ever be delivered. This is the trophy-pop path, so it matters that a
    # single stuck recipient can never cost everyone else their reward.
    hub = Hub(send_timeout=0.05)
    hung, alive = FakeSocket(hang=True), FakeSocket()
    await hub.connect("player:1", hung)
    await hub.connect("player:1", alive)

    delivered = await asyncio.wait_for(
        hub.broadcast("player:1", TrophyPopMsg(trophy_id="game-1", name="n", grade="platinum")),
        timeout=2.0,
    )

    assert delivered == 1
    assert alive.sent[0]["grade"] == "platinum"

    # The hung socket must be dropped, not retried, on the next broadcast.
    delivered_again = await asyncio.wait_for(
        hub.broadcast("player:1", ToastMsg(text="again")), timeout=2.0
    )
    assert delivered_again == 1
    assert hung.call_count == 1
    assert alive.call_count == 2
