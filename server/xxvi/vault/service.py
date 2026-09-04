import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from xxvi.persistence.models import CodeRelease
from xxvi.settings import Settings

logger = logging.getLogger(__name__)


class AlreadyReleased(Exception):
    """This reward has already been emitted for this run."""


class NotApproved(Exception):
    """No operator approval accompanied the request."""


class UnknownReward(Exception):
    """No code is configured for that reward id."""


def _is_unique_violation(exc: IntegrityError) -> bool:
    """Distinguish "duplicate (run_id, reward_id)" from any other IntegrityError.

    `CodeRelease.run_id` is itself a foreign key to `runs.id`, so an invalid
    run id raises an `IntegrityError` too -- as would any other constraint
    violation the schema grows later. A bare `except IntegrityError` would
    misread all of those as "already released" and swallow them as a quiet
    success-shaped no-op, which is catastrophic here (no code gets emitted
    and nobody is told why). Only the specific unique-constraint violation
    on `(run_id, reward_id)` may be treated as a duplicate; everything else
    must propagate as a real error.

    Two checks, for two different reasons -- read this before "simplifying"
    either one away:

    - `type(orig).__name__ == "UniqueViolationError"`: this is here for
      asyncpg, which raises a `UniqueViolationError` distinct from
      `ForeignKeyViolationError` in its own exception hierarchy. In
      practice this branch does NOT fire against this project's stack:
      SQLAlchemy's asyncpg dialect re-wraps the driver-level error before
      it reaches `exc.orig`, so as currently observed this is dead code in
      production. It is kept in case that wrapping behaviour ever changes
      upstream, but nothing here currently depends on it firing.
    - The message-substring match (`"unique constraint" in message`) is
      NOT a fallback -- it is what actually distinguishes the two cases on
      both backends this project uses today (Postgres via asyncpg in
      production, SQLite via aiosqlite in tests), because both wrap the
      real error down to a message-only `IntegrityError` by the time it's
      inspectable here. Deleting it as "redundant" with the branch above
      would silently turn every IntegrityError back into a false
      "already released" -- i.e. it would reintroduce the exact bug this
      function exists to fix.

    Residual risk NOT closed by this function: a primary-key unique
    violation -- e.g. from an `id` sequence desync after a database
    dump/restore -- would also contain "unique constraint" in its message
    and would be misread as AlreadyReleased, the same way a bare
    `except IntegrityError` would misread an FK violation. This is a much
    narrower window (a specific kind of database corruption vs. any
    IntegrityError) but it is not eliminated here.
    """
    orig = exc.orig
    if orig is not None and type(orig).__name__ == "UniqueViolationError":
        return True
    message = str(orig if orig is not None else exc).lower()
    return "unique constraint" in message


class VaultService:
    """Custody of the gift card codes.

    Invariants enforced here and nowhere else:
      1. A code is emitted only with explicit operator approval.
      2. A code is emitted at most once per (run, reward) -- guaranteed by a
         database UNIQUE constraint, not by application logic.
      3. A code value is never logged, never persisted, and never included
         in an exception message.
      4. A dry run never touches the `code_releases` ledger -- it is not
         subject to invariant 2 and leaves the real (run, reward) pair
         completely unclaimed, so any number of rehearsals can never block
         (or be mistaken for) the one real release.
    """

    def __init__(self, sessionmaker: async_sessionmaker, settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    def _code_for(self, reward_id: int) -> str:
        if self._settings.dry_run:
            # A rehearsal must never emit -- or even read -- the real value.
            return f"DRY-RUN-REWARD-{reward_id}"
        code = self._settings.reward_code(reward_id)
        if not code:
            raise UnknownReward(f"no code configured for reward {reward_id}")
        return code

    def code_for(self, reward_id: int) -> str:
        """Public accessor for the configured code, for the one caller with
        real justification to read it outside `release()`'s persistence
        path: `cli.py`'s `cmd_release`, recovering a code that was emitted
        once already (an `AlreadyReleased` run) but never reached him --
        e.g. the release happened, the process died, and he never saw the
        code print. `Run.released_rewards` (state-machine bookkeeping) and
        `cli state` (which reads the real `code_releases` ledger) can both
        tell the operator THAT a code went out; neither can tell him WHAT
        it was. This is deliberately a thin, explicit escape hatch from
        invariant 3's "never included in an exception message" -- the
        code still never touches a log line or an exception, only an
        operator-invoked print statement."""
        return self._code_for(reward_id)

    async def release(self, run_id: int, reward_id: int, *, approved_by_operator: bool) -> str:
        if not approved_by_operator:
            logger.warning(
                "release refused: no operator approval (run=%s reward=%s)", run_id, reward_id
            )
            raise NotApproved(f"reward {reward_id} requires operator approval")

        code = self._code_for(reward_id)

        if self._settings.dry_run:
            # A rehearsal must leave no trace that could block (or falsely
            # satisfy) the real release later -- see
            # `Settings.assert_production_ready`, which now refuses to run
            # at all under dry_run, so this branch is reachable only via
            # direct `VaultService` use (as the operator-surface review's
            # dry-run reproduction did) rather than through the CLI's
            # production-ready release path. Committing a `CodeRelease` row
            # here would let a forgotten rehearsal permanently consume
            # `(run_id, reward_id)` and make the real release 409 forever --
            # exactly the bug this guards against. No row, no trace: the
            # `UNIQUE(run_id, reward_id)` constraint that makes a real
            # release single-use is never touched by a dry run.
            logger.info("dry-run release, not persisted (run=%s reward=%s)", run_id, reward_id)
            return code

        # Claim the release first. If the constraint rejects it as a
        # duplicate, nothing is emitted. Any other IntegrityError (e.g. an
        # invalid run_id) is a real error and must propagate, not be
        # swallowed as a false "already released".
        async with self._sessionmaker() as session:
            session.add(CodeRelease(run_id=run_id, reward_id=reward_id))
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if not _is_unique_violation(exc):
                    raise
                logger.info("release rejected as duplicate (run=%s reward=%s)", run_id, reward_id)
                raise AlreadyReleased(f"reward {reward_id} already released") from None

        logger.info("released reward %s for run %s", reward_id, run_id)
        return code

    async def released_reward_ids(self, run_id: int) -> frozenset[int]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(CodeRelease.reward_id).where(CodeRelease.run_id == run_id)
            )
            return frozenset(result.scalars())
