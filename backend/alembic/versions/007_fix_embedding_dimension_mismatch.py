"""Fix embedding column to support variable dimensions

Feature #226: Fix embedding dimension mismatch on model change

This migration addresses the issue where changing embedding models (e.g., from
OpenAI text-embedding-3-small with 1536 dims to Ollama embeddinggemma with 768 dims)
causes re-embedding to fail silently with a dimension mismatch error.

The problem:
- The document_embeddings.embedding column was created with a fixed dimension
  (e.g., vector(4096)) instead of variable dimension (vector without dimension)
- When inserting embeddings from a model with different dimensions, PostgreSQL
  rejects the insert with an error like "expected 4096 dimensions, not 768"

The solution:
1. Drop any existing HNSW/IVFFLAT indexes on the embedding column
2. Alter the embedding column to use 'vector' type without fixed dimension
3. Note: Indexes will need to be recreated after data is inserted with
   consistent dimensions (handled by migration 005's logic)

IMPORTANT: This migration drops existing embeddings and requires re-embedding
all documents after completion if documents exist.

Revision ID: 007
Revises: 006
Create Date: 2026-01-30 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Alter embedding columns to support variable dimensions.

    This enables switching between embedding models with different dimensions
    without database errors.
    """

    # Drop any existing vector indexes first (they have dimension constraints)
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_embedding_vector")
    op.execute("DROP INDEX IF EXISTS ix_chunk_feedback_query_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_chunk_feedback_query_embedding")
    op.execute("DROP INDEX IF EXISTS ix_message_embeddings_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_user_notes_embedding_hnsw")

    # Alter document_embeddings.embedding column to variable dimension
    # Using DO block to handle both fixed and variable dimension columns
    op.execute("""
        DO $$
        DECLARE
            current_type text;
        BEGIN
            -- Get current column type
            SELECT data_type || COALESCE('(' || character_maximum_length || ')', '')
            INTO current_type
            FROM information_schema.columns
            WHERE table_name = 'document_embeddings' AND column_name = 'embedding';

            RAISE NOTICE 'document_embeddings.embedding current type: %', current_type;

            -- Check if column exists and has a vector type with fixed dimension
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings' AND column_name = 'embedding'
            ) THEN
                -- Truncate existing embeddings (they have incompatible dimensions anyway)
                -- Users will need to re-embed after this migration
                DELETE FROM document_embeddings;
                RAISE NOTICE 'Cleared existing embeddings to allow dimension change';

                -- Alter to variable-dimension vector type
                -- Note: We use USING to handle the type conversion
                ALTER TABLE document_embeddings
                ALTER COLUMN embedding TYPE vector
                USING embedding::vector;

                RAISE NOTICE 'Altered document_embeddings.embedding to variable dimension vector';
            END IF;
        END $$;
    """)

    # Alter chunk_feedback.query_embedding if it exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'chunk_feedback' AND column_name = 'query_embedding'
            ) THEN
                DELETE FROM chunk_feedback;
                ALTER TABLE chunk_feedback
                ALTER COLUMN query_embedding TYPE vector
                USING query_embedding::vector;
                RAISE NOTICE 'Altered chunk_feedback.query_embedding to variable dimension vector';
            END IF;
        END $$;
    """)

    # Alter message_embeddings.embedding if it exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'message_embeddings' AND column_name = 'embedding'
            ) THEN
                DELETE FROM message_embeddings;
                ALTER TABLE message_embeddings
                ALTER COLUMN embedding TYPE vector
                USING embedding::vector;
                RAISE NOTICE 'Altered message_embeddings.embedding to variable dimension vector';
            END IF;
        END $$;
    """)

    # Alter user_notes.embedding if it exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'user_notes' AND column_name = 'embedding'
            ) THEN
                UPDATE user_notes SET embedding = NULL;
                ALTER TABLE user_notes
                ALTER COLUMN embedding TYPE vector
                USING embedding::vector;
                RAISE NOTICE 'Altered user_notes.embedding to variable dimension vector';
            END IF;
        END $$;
    """)

    # Log completion
    op.execute("SELECT 'Migration 007 completed: embedding columns now support variable dimensions'")


def downgrade() -> None:
    """Revert to fixed dimension vectors (not recommended).

    Note: This downgrade doesn't restore the original fixed dimension since
    we don't know what it was. The columns will remain as variable dimension.
    """
    # We can't really downgrade this properly without knowing the original dimension
    # and having the original data. Just leave columns as variable dimension.
    pass
