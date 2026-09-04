from dataclasses import dataclass
from enum import StrEnum

from xxvi.auth.passwords import verify_password
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings


class GateId(StrEnum):
    """The two gates that are always exactly one apiece, regardless of
    `acts`: the front door (ACTIVATION) and -- for callers that still need
    a concrete member, e.g. `operator_routes.UnlockGateRequest`'s Pydantic
    field and `run_service.submit_activation`'s `GateId.ACTIVATION` --
    kept intact rather than deleted.

    Checkpoint gates are NOT enumerated here any more: with `acts`
    configurable, the set of checkpoint gates follows `config.acts`, not a
    fixed count of two. `checkpoint_gate(act)` below computes those ids
    instead. CHECKPOINT_1 / CHECKPOINT_2 remain as members purely because
    existing callers (tests, `operator_routes`) already reference them and
    the strings they produce ("checkpoint_1", "checkpoint_2") are identical
    to what `checkpoint_gate(1)` / `checkpoint_gate(2)` produce -- a
    `GateId.CHECKPOINT_1` and the string `"checkpoint_1"` are the same value
    everywhere a gate id is compared, stored or looked up.
    """

    ACTIVATION = "activation"
    CHECKPOINT_1 = "checkpoint_1"
    CHECKPOINT_2 = "checkpoint_2"


def checkpoint_gate(act: int) -> str:
    """The gate id for an act's checkpoint.

    Returns the same literals the old `GateId.CHECKPOINT_1` / `CHECKPOINT_2`
    members produced -- "checkpoint_1", "checkpoint_2" -- because those
    strings are already persisted in `gate_attempts.gate_id` for every run
    recorded to date. This is a StrEnum being replaced by a function purely
    so the set of gates can follow `acts` in config instead of being fixed
    at two; it is deliberately NOT a change of format.
    """
    return f"checkpoint_{act}"


class GateOutcome(StrEnum):
    OK = "ok"
    WRONG = "wrong"
    LOCKED = "locked"


@dataclass(frozen=True)
class GatePolicy:
    max_attempts: int | None  # None means rate-limited but never hard-locked


def gate_policy(gate: str) -> GatePolicy:
    """The lockout policy for a gate id.

    The front door is never bricked. Checkpoints can afford to be cruel.
    `gate` is a plain string (not `GateId`) because the set of checkpoint
    gates now follows `config.acts` rather than being fixed at two -- see
    `checkpoint_gate`. Identical policy to the old `GATE_POLICY` dict: only
    `GateId.ACTIVATION` (`str(GateId.ACTIVATION) == "activation"`) is
    unlockable; every checkpoint gets `max_attempts=3`.
    """
    if gate == GateId.ACTIVATION:
        return GatePolicy(max_attempts=None)
    return GatePolicy(max_attempts=3)


class GateService:
    def __init__(self, repo: RunRepository, settings: Settings) -> None:
        self._repo = repo
        self._settings = settings

    def _expected_hash(self, gate: str) -> str:
        if gate == GateId.ACTIVATION:
            return self._settings.activation_code_hash
        # "checkpoint_N" -> N. `checkpoint_gate` is the only producer of
        # this shape; any gate id reaching here that isn't ACTIVATION is one
        # of its outputs.
        act = int(str(gate).removeprefix("checkpoint_"))
        return self._settings.checkpoint_hash(act)

    async def submit(self, run_id: int, gate: str, candidate: str) -> GateOutcome:
        row = await self._repo.gate_row(run_id, str(gate))
        policy = gate_policy(gate)

        if row.locked:
            return GateOutcome.LOCKED

        if verify_password(candidate.strip().upper(), self._expected_hash(gate)):
            await self._repo.set_gate(run_id, str(gate), attempts=0, locked=False)
            await self._repo.append_event(run_id, "gate_passed", {"gate": str(gate)})
            return GateOutcome.OK

        attempts, _locked, applied = await self._repo.record_gate_failure(
            run_id, str(gate), max_attempts=policy.max_attempts
        )
        if not applied:
            # The gate crossed into locked between our read above and this
            # write landing (a concurrent guess got there first). This
            # guess was never counted -- report it as locked, not wrong.
            return GateOutcome.LOCKED
        await self._repo.append_event(
            run_id, "gate_failed", {"gate": str(gate), "attempts": attempts}
        )
        return GateOutcome.WRONG

    async def clear_lock(self, run_id: int, gate: str) -> None:
        await self._repo.set_gate(run_id, str(gate), attempts=0, locked=False)
        await self._repo.append_event(run_id, "gate_unlocked", {"gate": str(gate)})

    async def attempts_remaining(self, run_id: int, gate: str) -> int | None:
        policy = gate_policy(gate)
        if policy.max_attempts is None:
            return None
        row = await self._repo.gate_row(run_id, str(gate))
        return max(0, policy.max_attempts - row.attempts)
