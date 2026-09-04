"""add per-question attempt counter to runs

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-09 12:00:00.000000

Until now a single wrong answer was `QUESTION_FAILED` immediately, in both
difficulties -- one typo cost the whole segment and sent the player back to
replay the game, and in DEVIL it also cost one of only three lives for the
entire run. A one-letter spelling variant was enough to trigger it. That is not
difficulty, it is punishment, and it was never what the run was meant to do.

`question_attempts` counts wrong answers spent on the question currently in
play, and is reset to 0 whenever a question begins or ends -- it is never a
running total across the run. `RunService.submit_answer` compares it against
`RunConfig.question_attempts` to decide whether a wrong answer emits the new
non-terminal `QUESTION_MISSED` (stay put, spend an attempt, touch nothing
else) or the terminal `QUESTION_FAILED` (the existing behaviour, unchanged).

NOT NULL with a `0` server_default, unlike the nullable `lives`: there is no
"meaningless yet" state for this counter. Zero attempts spent is correct at
every phase, including before a difficulty is chosen, so existing rows take
the default and are immediately correct.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: str | Sequence[str] | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'runs',
        sa.Column('question_attempts', sa.Integer(), server_default='0', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('runs', 'question_attempts')
