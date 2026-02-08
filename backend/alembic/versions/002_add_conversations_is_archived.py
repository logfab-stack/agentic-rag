"""Add is_archived column and created_at index to conversations

Revision ID: 002a
Revises: 002
Create Date: 2026-01-28 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002a'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_archived column and created_at index to conversations table."""
    # Add is_archived column to conversations table
    op.add_column(
        'conversations',
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add index on created_at for sorting
    op.create_index('idx_conversations_created', 'conversations', ['created_at'])


def downgrade() -> None:
    """Remove is_archived column and created_at index from conversations table."""
    # Drop index on created_at
    op.drop_index('idx_conversations_created', table_name='conversations')

    # Drop is_archived column
    op.drop_column('conversations', 'is_archived')
