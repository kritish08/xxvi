"""WebSocket message contracts.

This is the one contract OpenAPI does not cover: every other client/server
type is generated from the FastAPI schema, but WebSocket messages are not.
A hand-written TypeScript mirror will be maintained against these Pydantic
models in a later task, so every message type lives in exactly one place
(this file) and the shape stays rigorously simple to mirror.

The `type` field on each message is the discriminator that makes the
`ServerMessage` union safe to parse and to switch on on the client side.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class RunStateMsg(BaseModel):
    type: Literal["run_state"] = "run_state"
    phase: str
    segment: int
    difficulty: str | None
    cleared_segments: list[int]
    released_rewards: list[int]


class TrophyPopMsg(BaseModel):
    type: Literal["trophy_pop"] = "trophy_pop"
    trophy_id: str
    name: str
    grade: str


class CodeReleasedMsg(BaseModel):
    type: Literal["code_released"] = "code_released"
    reward_id: int
    label: str
    code: str  # only ever sent on the player channel, after operator approval


class ToastMsg(BaseModel):
    type: Literal["toast"] = "toast"
    text: str


class OperatorPresenceMsg(BaseModel):
    type: Literal["operator_presence"] = "operator_presence"
    online: bool


class GateResultMsg(BaseModel):
    type: Literal["gate_result"] = "gate_result"
    gate: str
    outcome: str
    attempts_remaining: int | None


ServerMessage = Annotated[
    RunStateMsg
    | TrophyPopMsg
    | CodeReleasedMsg
    | ToastMsg
    | OperatorPresenceMsg
    | GateResultMsg,
    Field(discriminator="type"),
]
