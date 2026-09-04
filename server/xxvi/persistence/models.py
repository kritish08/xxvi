from datetime import datetime

from sqlalchemy import (
    JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16))  # "player" | "operator"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    phase: Mapped[str] = mapped_column(String(16))
    segment: Mapped[int] = mapped_column(Integer, default=0)
    cleared_segments: Mapped[list[int]] = mapped_column(JSON, default=list)
    released_rewards: Mapped[list[int]] = mapped_column(JSON, default=list)
    # Devil-mode lives remaining. NULL until DEVIL is chosen (meaningless
    # before that, and always meaningless for KIDDIE) -- mirrors `difficulty`
    # itself being nullable for the same reason.
    lives: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Wrong answers spent on the question currently in play. NOT NULL with a
    # 0 default: unlike `lives` there is no "meaningless yet" state for it --
    # zero attempts spent is the correct answer at every phase, including
    # before a difficulty is chosen.
    question_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # Optimistic-concurrency token for `RunRepository.save_state`. Bumped by
    # exactly 1 on every successful save. `save_state` is a
    # `WHERE version = <version the caller read>` compare-and-swap, not a
    # plain `session.get` + attribute-assignment + commit -- the latter lets
    # SQLAlchemy emit an UPDATE containing only the columns dirty relative to
    # that session's own load, so two concurrent saves from the same base row
    # can emit disjoint column sets that silently merge in the database into
    # a RunState that is the successor of neither event. See
    # `RunRepository.save_state`'s docstring.
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RunEvent(Base):
    """Append-only. Drives the dashboard, the end-screen stats, and debugging."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrophyEarned(Base):
    __tablename__ = "trophies_earned"
    __table_args__ = (UniqueConstraint("run_id", "trophy_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    trophy_id: Mapped[str] = mapped_column(String(64))
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GateAttempt(Base):
    __tablename__ = "gate_attempts"
    __table_args__ = (UniqueConstraint("run_id", "gate_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    gate_id: Mapped[str] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[bool] = mapped_column(default=False)


class CodeRelease(Base):
    """Records THAT a reward was released. Never its value."""

    __tablename__ = "code_releases"
    __table_args__ = (UniqueConstraint("run_id", "reward_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    reward_id: Mapped[int] = mapped_column(Integer)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConsumedToken(Base):
    """Single-use marker for segment tokens, enforced by a real UNIQUE
    constraint rather than a check-then-act read of `run_events`. A segment
    token's nonce is claimed here exactly once; a second claim collides with
    the constraint and is read back as "already consumed" -- the insert
    itself is the lock, so this is race-safe under concurrent requests
    hitting independent DB connections (unlike a SELECT-then-INSERT pair).
    `run_events` still gets an audit entry on successful consumption, but it
    is not what makes single-use true.
    """

    __tablename__ = "consumed_tokens"
    __table_args__ = (UniqueConstraint("run_id", "nonce"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    nonce: Mapped[str] = mapped_column(String(32))
    segment: Mapped[int] = mapped_column(Integer)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
