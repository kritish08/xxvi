"""add optimistic-concurrency version column to runs

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-08 18:00:00.000000

`RunRepository.save_state` previously loaded a Run via `session.get`,
assigned attributes, and committed -- SQLAlchemy then emits an UPDATE
containing only the columns dirty relative to THAT session's own load.
Two concurrent saves from the same base row (e.g. an honest game result
racing a garbage one, or two concurrent Devil failures) emit disjoint
column sets that silently merge in the database into a RunState that is
the successor of neither event -- not last-writer-wins, a torn row.

`version` makes `save_state` a `WHERE version = <version the caller read>`
compare-and-swap: it always writes every mutable column in one UPDATE, and
that UPDATE only lands if no concurrent save has landed first. The loser
gets `rowcount == 0` back and the caller (RunService.apply) turns that into
a 409 rather than silently accepting a computation based on stale data.
Existing rows default to 0 via `server_default`.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: str | Sequence[str] | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('runs', sa.Column('version', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('runs', 'version')
