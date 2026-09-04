"""add consumed_tokens for race-safe single-use segment tokens

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-08 12:00:00.000000

Single-use enforcement for segment tokens previously lived as a
check-then-act pair against `run_events` (`has_event` then `append_event`,
two separate transactions, no constraint) which does not serialize
concurrent consumers: two requests racing the same token both pass the
`has_event` check before either commits its `append_event`. This table
makes the claim itself the lock via a real UNIQUE constraint, matching the
existing `trophies_earned` / `code_releases` pattern.

`run_events` is left untouched -- it stays a pure append-only audit log,
with no constraints, as it always has been.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: str | Sequence[str] | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('consumed_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('nonce', sa.String(length=32), nullable=False),
    sa.Column('segment', sa.Integer(), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'nonce')
    )
    op.create_index(op.f('ix_consumed_tokens_run_id'), 'consumed_tokens', ['run_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_consumed_tokens_run_id'), table_name='consumed_tokens')
    op.drop_table('consumed_tokens')
