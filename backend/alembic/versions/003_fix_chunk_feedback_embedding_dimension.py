"""Fix chunk_feedback query_embedding to support any dimension

Revision ID: 003
Revises: 002a
Create Date: 2026-01-29 22:10:00.000000

The chunk_feedback table was created with vector(1024) dimensions,
but the system now uses qwen3-embedding:8b which produces 4096 dimensions.
This migration changes the column to support any dimension by removing
the dimension constraint.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change query_embedding from vector(1024) to vector (any dimension).

    This is done by:
    1. Dropping the existing ivfflat index (requires fixed dimensions)
    2. Altering the column type to vector without dimension constraint
    3. Recreating the index without dimension specification

    Note: Existing embeddings in the table may become incompatible if they
    were created with a different embedding model. Consider clearing old
    feedback data if dimension mismatch errors occur.
    """
    # Drop the existing index that requires fixed dimensions
    op.execute('DROP INDEX IF EXISTS ix_chunk_feedback_query_embedding')

    # Alter the column to vector without dimension constraint
    # This allows any dimension embedding to be stored
    op.execute("""
        ALTER TABLE chunk_feedback
        ALTER COLUMN query_embedding TYPE vector
        USING query_embedding::vector
    """)

    # Note: We cannot create an ivfflat index without knowing the dimension
    # at index creation time. For chunk_feedback which is a relatively small
    # table, we'll skip the vector index. The table has a regular index on
    # chunk_id which is the primary query pattern.
    #
    # If vector similarity search on query_embedding is needed frequently,
    # consider creating the index after embeddings are added:
    # CREATE INDEX ix_chunk_feedback_query_embedding ON chunk_feedback
    # USING ivfflat (query_embedding vector_cosine_ops) WITH (lists = 100);


def downgrade() -> None:
    """Revert to vector(1024) dimension constraint."""
    # Drop any existing index
    op.execute('DROP INDEX IF EXISTS ix_chunk_feedback_query_embedding')

    # Alter back to fixed dimension (may fail if data has different dimensions)
    op.execute("""
        ALTER TABLE chunk_feedback
        ALTER COLUMN query_embedding TYPE vector(1024)
        USING query_embedding::vector(1024)
    """)

    # Recreate the ivfflat index with fixed dimensions
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_chunk_feedback_query_embedding
        ON chunk_feedback
        USING ivfflat (query_embedding vector_cosine_ops)
        WITH (lists = 100)
    """)
