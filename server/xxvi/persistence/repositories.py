from sqlalchemy import delete, not_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from xxvi.core.models import Difficulty, Phase, RunState
from xxvi.core.trophies import HIDDEN_PREFIX
from xxvi.persistence.models import (
    CodeRelease,
    ConsumedToken,
    GateAttempt,
    Run,
    RunEvent,
    TrophyEarned,
)


def _is_unique_violation(exc: IntegrityError) -> bool:
    """Distinguish "duplicate (run_id, nonce)" from any other IntegrityError.

    `ConsumedToken.run_id` is itself a foreign key to `runs.id`, so an
    invalid run id raises an `IntegrityError` too. A bare `except
    IntegrityError` (as `award_trophy` above does) would misread that as
    "already consumed" and silently accept a token for a run that doesn't
    exist. Mirrors `_is_unique_violation` in `xxvi/vault/service.py`, which
    exists for the identical reason on `CodeRelease` -- see that docstring
    for the asyncpg/SQLite message-matching detail this relies on.
    """
    orig = exc.orig
    if orig is not None and type(orig).__name__ == "UniqueViolationError":
        return True
    message = str(orig if orig is not None else exc).lower()
    return "unique constraint" in message


class RunRepository:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def create(self, account_id: int, difficulty: Difficulty | None) -> Run:
        """Get-or-create the account's run.

        `runs.account_id` is UNIQUE, and `RunService.load()` calls this only
        after a `get_by_account` that found nothing -- exactly `gate_row`'s
        shape (a SELECT fast-path, falling through to an INSERT). A first
        touch is a race: a page loading `GET /api/run` while the WebSocket
        handshake also creates the run, a double-clicked "enter", a React
        double-mount under StrictMode, or a bare client retry can all send
        two concurrent creates for the same account before either commits.
        Without catching the UNIQUE violation here, the loser's INSERT
        raises and every route that starts with `RunService.load()` -- which
        is all of them, including `GET /api/run` -- surfaces a 500 on
        someone's very first interaction of the night. On conflict, roll
        back and re-select: the winner's row is what both callers wanted,
        mirroring `gate_row` exactly.
        """
        async with self._sessionmaker() as session:
            run = Run(
                account_id=account_id,
                difficulty=difficulty.value if difficulty else None,
                phase="activation",
                segment=0,
                cleared_segments=[],
                released_rewards=[],
            )
            session.add(run)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(select(Run).where(Run.account_id == account_id))
                return result.scalar_one()
            return run

    async def get_by_account(self, account_id: int) -> Run | None:
        async with self._sessionmaker() as session:
            result = await session.execute(select(Run).where(Run.account_id == account_id))
            return result.scalar_one_or_none()

    async def get_by_id(self, run_id: int) -> Run | None:
        """Look a run up by its own id, for the operator surface -- which
        works from `run_id` (what its dashboard lists) and never has the
        player's `account_id`. Deliberately does NOT create on miss, unlike
        `get_by_account`: an operator naming a run that does not exist is a
        mistake to report, not a run to bring into being."""
        async with self._sessionmaker() as session:
            result = await session.execute(select(Run).where(Run.id == run_id))
            return result.scalar_one_or_none()

    async def reset_run(self, run_id: int) -> dict[str, int] | None:
        """Wipe a run back to its very first screen. Returns what it deleted,
        or None if there is no such run.

        THIS DESTROYS THE RELEASED-CODES LEDGER. `code_releases` is the only
        thing making a gift-card release at-most-once (its
        UNIQUE(run_id, reward_id) is what `VaultService.release` relies on),
        so deleting those rows makes an already-given code releasable again.
        For testing that is exactly what is wanted; on the night it would
        mean the run has no record that a card was ever handed over. The
        operator route above this is gated accordingly, and the counts come
        back so the caller can say precisely what went.

        FK-safe order: children first, then the row itself. `runs` has no
        ON DELETE CASCADE, so deleting or truncating in the wrong order
        raises a foreign-key violation -- a mistake this project has now
        made twice by hand.
        """
        async with self._sessionmaker() as session:
            run = (
                await session.execute(select(Run).where(Run.id == run_id))
            ).scalar_one_or_none()
            if run is None:
                return None

            deleted: dict[str, int] = {}
            for model in (CodeRelease, TrophyEarned, GateAttempt, ConsumedToken, RunEvent):
                result = await session.execute(
                    delete(model).where(model.run_id == run_id)
                )
                deleted[model.__tablename__] = result.rowcount or 0

            fresh = RunState()
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    phase=fresh.phase.value,
                    difficulty=None,
                    segment=fresh.segment,
                    cleared_segments=[],
                    released_rewards=[],
                    lives=None,
                    question_attempts=0,
                    # Bumped, never reset to 0: any request already in flight
                    # against the old version must lose its compare-and-swap
                    # and 409 rather than land on top of the reset.
                    version=Run.version + 1,
                )
            )
            await session.commit()
            return deleted

    async def save_state(self, run_id: int, expected_version: int, state: RunState) -> bool:
        """Compare-and-swap save. Returns True if this call's write landed,
        False if a concurrent save already moved the row past
        `expected_version` -- meaning `state` was computed from data that is
        no longer current and must NOT be written (see the module-level
        note above and this table's migration for the incident this
        replaces).

        A single `UPDATE ... WHERE id = run_id AND version = expected_version`
        that sets every mutable column at once, exactly mirroring
        `record_gate_failure`'s `UPDATE ... RETURNING ... WHERE locked =
        False` compare-and-swap. `expected_version` must be the version the
        caller read `state` from (`Run.version` at the time `RunService.load`
        ran) -- passing anything else defeats the guarantee.
        """
        async with self._sessionmaker() as session:
            stmt = (
                update(Run)
                .where(Run.id == run_id, Run.version == expected_version)
                .values(
                    phase=state.phase.value,
                    difficulty=state.difficulty.value if state.difficulty else None,
                    segment=state.segment,
                    cleared_segments=sorted(state.cleared_segments),
                    released_rewards=sorted(state.released_rewards),
                    lives=state.lives,
                    question_attempts=state.question_attempts,
                    version=expected_version + 1,
                )
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount == 1

    async def append_event(self, run_id: int, kind: str, payload: dict) -> None:
        async with self._sessionmaker() as session:
            session.add(RunEvent(run_id=run_id, kind=kind, payload=payload))
            await session.commit()

    async def has_event(self, run_id: int, kind: str, payload_match: dict) -> bool:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.kind == kind)
            )
            return any(
                all(row.payload.get(k) == v for k, v in payload_match.items())
                for row in result.scalars()
            )

    async def count_events(self, run_id: int, kind: str, payload_match: dict) -> int:
        """How many `run_events` rows of `kind` match `payload_match` -- the
        counting counterpart to `has_event` above, same shape and same
        Python-side filtering (matching on a JSON payload's subset of keys
        isn't expressible as a portable SQLite/Postgres WHERE clause here).
        Read-only: this is audit-log counting, never itself a decision that
        needs to be atomic -- the caller (`RunService.check_hidden`) turns a
        count into an award through `award_trophy`'s insert-first-catch-the-
        violation primitive, not through anything read here.
        """
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.kind == kind)
            )
            return sum(
                1
                for row in result.scalars()
                if all(row.payload.get(k) == v for k, v in payload_match.items())
            )

    async def earned_trophies(self, run_id: int) -> frozenset[str]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(TrophyEarned.trophy_id).where(TrophyEarned.run_id == run_id)
            )
            return frozenset(result.scalars())

    async def award_trophy(self, run_id: int, trophy_id: str) -> bool:
        """Returns True if newly awarded, False if already held."""
        async with self._sessionmaker() as session:
            session.add(TrophyEarned(run_id=run_id, trophy_id=trophy_id))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
            return True

    async def consume_token(self, run_id: int, nonce: str, segment: int) -> bool:
        """Atomically claim a segment token's nonce. Returns True if this call
        newly claimed it, False if it was already consumed (by this call or a
        concurrent one). Race-safe: the claim IS the insert, not a read
        followed by an insert, so two concurrent callers racing the same
        (run_id, nonce) can never both win -- the database's UNIQUE
        constraint on `consumed_tokens` is the only thing that decides.
        """
        async with self._sessionmaker() as session:
            session.add(ConsumedToken(run_id=run_id, nonce=nonce, segment=segment))
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if not _is_unique_violation(exc):
                    raise
                return False
            return True

    async def clear_segment_trophies(self, run_id: int) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                delete(TrophyEarned).where(
                    TrophyEarned.run_id == run_id,
                    not_(TrophyEarned.trophy_id.startswith(HIDDEN_PREFIX)),
                )
            )
            await session.commit()

    async def gate_row(self, run_id: int, gate_id: str) -> GateAttempt:
        """Get-or-create the attempt row for a gate.

        This is a read that inserts, so a first touch at a gate is a race:
        two concurrent requests (e.g. a double-clicked submit button) can
        both see no row, both `INSERT`, and the loser hits the
        `UNIQUE(run_id, gate_id)` constraint. That must never surface as a
        crash -- least of all at `ACTIVATION`, the one gate that is
        guaranteed to never hard-lock, since a 500 at the front door is
        just as fatal to the event as a lockout would be. On conflict, roll
        back and re-select: the winner's row is what both callers wanted.
        """
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(GateAttempt).where(
                    GateAttempt.run_id == run_id, GateAttempt.gate_id == gate_id
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                return row

            row = GateAttempt(run_id=run_id, gate_id=gate_id, attempts=0, locked=False)
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(GateAttempt).where(
                        GateAttempt.run_id == run_id, GateAttempt.gate_id == gate_id
                    )
                )
                row = result.scalar_one()
            return row

    async def set_gate(self, run_id: int, gate_id: str, *, attempts: int, locked: bool) -> None:
        """Unconditionally set a gate attempt row's attempts/locked state,
        creating the row if this is the first touch.

        This is a sixth check-then-act site (SELECT -> if None: INSERT ->
        UPDATE), the same shape as `gate_row` twenty lines above -- and it
        is reached from `GateService.clear_lock`, the operator's rescue
        path when a player is hard-locked out. Measured before this fix: 8
        concurrent calls against a gate with no pre-existing row produced 7
        `IntegrityError`-driven 500s. A 500 on the unlock button is exactly
        as fatal to the event as the lockout it's supposed to fix, so this
        must never crash -- mirroring `gate_row`'s own docstring on why a
        500 at the front door is unacceptable.

        Unlike `gate_row`, a caller here has specific `attempts`/`locked`
        values it wants written -- re-selecting and returning "whichever
        row won the insert race" (as `gate_row` does) would silently drop
        this call's values on the floor for the loser. So on conflict, this
        falls through to an explicit `UPDATE`, applying this call's values
        to the row the winner created rather than assuming it already holds
        them.
        """
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(GateAttempt).where(
                    GateAttempt.run_id == run_id, GateAttempt.gate_id == gate_id
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                row.attempts = attempts
                row.locked = locked
                await session.commit()
                return

            session.add(
                GateAttempt(run_id=run_id, gate_id=gate_id, attempts=attempts, locked=locked)
            )
            try:
                await session.commit()
                return
            except IntegrityError:
                await session.rollback()

        # Lost the insert race to a concurrent first-touch on the same
        # (run_id, gate_id). The row exists now; apply this call's values.
        async with self._sessionmaker() as session:
            await session.execute(
                update(GateAttempt)
                .where(GateAttempt.run_id == run_id, GateAttempt.gate_id == gate_id)
                .values(attempts=attempts, locked=locked)
            )
            await session.commit()

    async def record_gate_failure(
        self, run_id: int, gate_id: str, *, max_attempts: int | None
    ) -> tuple[int, bool, bool]:
        """Atomically increment the attempt counter and apply the lockout policy.

        Returns `(attempts, locked, applied)`. `applied` is False when the
        gate was already locked *before* this call, in which case the guess
        was not counted (`attempts`/`locked` reflect the pre-existing state,
        unchanged) -- the caller should treat that as an outright LOCKED
        rejection, not another wrong attempt.

        Two races are closed here, both by doing the whole decision in one
        `UPDATE ... RETURNING` instead of a Python-level read-modify-write:

        1. A plain "SELECT attempts, add 1 in Python, UPDATE" loses updates
           under concurrent wrong guesses -- two sessions can both read
           `attempts=2` and both write back `attempts=3`, undercounting by
           one for every extra concurrent guess.
        2. Even an atomic increment alone leaves a narrower race at the
           lock *boundary*: if the "is it already locked" check is a
           separate read before this update, a burst of concurrent guesses
           can all pass that check before any of them commits `locked=True`,
           overshooting past `max_attempts` instead of locking at exactly
           that count. The `WHERE ... locked == False` below makes the
           check and the increment a single atomic operation -- once one
           writer's commit sets `locked=True`, every other writer's UPDATE
           matches zero rows and is reported back as `applied=False`
           instead of sneaking in an extra counted guess.

        Ensures the row exists first via `gate_row`, which is itself race-safe
        (see its docstring) for the same reason this needs to be.
        """
        await self.gate_row(run_id, gate_id)
        async with self._sessionmaker() as session:
            new_attempts = GateAttempt.attempts + 1
            locked_expr = new_attempts >= max_attempts if max_attempts is not None else False
            stmt = (
                update(GateAttempt)
                .where(
                    GateAttempt.run_id == run_id,
                    GateAttempt.gate_id == gate_id,
                    GateAttempt.locked.is_(False),
                )
                .values(attempts=new_attempts, locked=locked_expr)
                .returning(GateAttempt.attempts, GateAttempt.locked)
            )
            result = await session.execute(stmt)
            row = result.one_or_none()
            await session.commit()
            if row is None:
                # Already locked before this call landed; the guess is not
                # counted. Report the current (unchanged) state.
                existing = await self.gate_row(run_id, gate_id)
                return existing.attempts, existing.locked, False
            attempts, locked = row
            return attempts, bool(locked), True

    @staticmethod
    def to_state(run: Run) -> RunState:
        """Rehydrate a persisted `Run` row into a `RunState` usable by `advance()`.

        `advance()` compares `state.phase`/`state.difficulty` against the enum
        members with `is`, not `==`. A `RunState` built with the raw strings
        stored on the row (e.g. `phase="game"`) would be equal to but not
        identical with `Phase.GAME`, and `machine._apply_failure` would raise
        `InvalidTransition` on every failure event as a result. Always go
        through the enum constructors here — `Difficulty("kiddie") is
        Difficulty.KIDDIE` is `True`, so this is correct and cheap.
        """
        return RunState(
            phase=Phase(run.phase),
            difficulty=Difficulty(run.difficulty) if run.difficulty is not None else None,
            segment=run.segment,
            cleared_segments=frozenset(run.cleared_segments),
            released_rewards=frozenset(run.released_rewards),
            lives=run.lives,
            question_attempts=run.question_attempts,
        )
