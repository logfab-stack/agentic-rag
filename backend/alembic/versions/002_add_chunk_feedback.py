"""Add chunk_feedback table for user feedback on retrieved chunks

Revision ID: 002
Revises: 001
Create Date: 2026-01-28 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create chunk_feedback table for storing user feedback on retrieved chunks."""

    # Create chunk_feedback table
    op.create_table(
        'chunk_feedback',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('chunk_id', sa.String(length=255), nullable=False),
        sa.Column('query_text', sa.Text(), nullable=False),
        sa.Column('query_embedding', sa.Text(), nullable=False),  # pgvector type will be applied
        sa.Column('feedback', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chunk_id', 'query_text', name='uq_chunk_feedback_chunk_query')
    )

    # Create index on chunk_id for efficient aggregation queries
    op.create_index('ix_chunk_feedback_chunk_id', 'chunk_feedback', ['chunk_id'])

    # Create vector index for similarity search on query_embedding
    # Uses ivfflat for approximate nearest neighbor search
    op.execute("""
        ALTER TABLE chunk_feedback
        ALTER COLUMN query_embedding TYPE vector(1024)
        USING query_embedding::vector(1024)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_chunk_feedback_query_embedding
        ON chunk_feedback
        USING ivfflat (query_embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    """Drop chunk_feedback table."""
    op.execute('DROP INDEX IF EXISTS ix_chunk_feedback_query_embedding')
    op.drop_index('ix_chunk_feedback_chunk_id', table_name='chunk_feedback')
    op.drop_table('chunk_feedback')
