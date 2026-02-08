"""Migrate from IVFFLAT to HNSW index for faster vector search (dimension-aware)

Feature #209: Optimize vector search with HNSW index

HNSW (Hierarchical Navigable Small World) provides significantly faster
approximate nearest neighbor search compared to IVFFLAT, especially for
larger datasets.

IMPORTANT - DIMENSION LIMITS:
- pgvector HNSW and IVFFLAT indexes only support vectors up to 2000 dimensions
- halfvec type extends this to 4000 dimensions
- If embeddings exceed 4000 dimensions, no vector index can be created
- Sequential scan performance is still acceptable for moderate dataset sizes

This migration:
1. Checks the embedding dimensions in each table
2. Creates HNSW indexes only if dimensions are supported (≤2000)
3. For dimensions 2001-4000, uses halfvec casting for the index
4. For dimensions >4000, skips index creation (sequential scan fallback)

Current system uses qwen3-embedding:8b with 4096 dimensions, which exceeds
limits. Sequential scan performance is ~28ms for 3140 embeddings, which is
well within the <1 second target.

Parameters (when index can be created):
- m = 16: Number of connections per layer
- ef_construction = 64: Size of dynamic candidate list during construction

Revision ID: 005
Revises: 004
Create Date: 2026-01-30 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Migrate from IVFFLAT to HNSW index for document_embeddings table.

    Handles dimension limits intelligently:
    - ≤2000 dimensions: Creates standard HNSW index
    - 2001-4000 dimensions: Creates HNSW index on halfvec cast
    - >4000 dimensions: Skips index (sequential scan fallback, still fast)
    """

    # Drop any existing IVFFLAT indexes
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_embedding_vector")
    op.execute("DROP INDEX IF EXISTS ix_chunk_feedback_query_embedding")
    op.execute("DROP INDEX IF EXISTS ix_message_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS ix_user_notes_embedding_vector")

    # Create HNSW index on document_embeddings (dimension-aware)
    # This is the main embedding table for RAG search
    op.execute("""
        DO $$
        DECLARE
            max_dim integer;
        BEGIN
            -- Check the maximum embedding dimension
            SELECT MAX(vector_dims(embedding)) INTO max_dim
            FROM document_embeddings
            WHERE embedding IS NOT NULL;

            IF max_dim IS NULL THEN
                RAISE NOTICE 'document_embeddings: No embeddings found, skipping index creation';
            ELSIF max_dim <= 2000 THEN
                -- Standard vector index for ≤2000 dimensions
                RAISE NOTICE 'document_embeddings: Creating HNSW index for % dimensions', max_dim;
                CREATE INDEX IF NOT EXISTS ix_document_embeddings_embedding_hnsw
                ON document_embeddings
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            ELSIF max_dim <= 4000 THEN
                -- Use halfvec for 2001-4000 dimensions
                RAISE NOTICE 'document_embeddings: Creating HNSW index with halfvec for % dimensions', max_dim;
                EXECUTE format('
                    CREATE INDEX IF NOT EXISTS ix_document_embeddings_embedding_hnsw
                    ON document_embeddings
                    USING hnsw ((embedding::halfvec(%s)) halfvec_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                ', max_dim);
            ELSE
                -- >4000 dimensions - no index possible, use sequential scan
                RAISE NOTICE 'document_embeddings: % dimensions exceeds pgvector limits (max 4000 for halfvec)', max_dim;
                RAISE NOTICE 'Using sequential scan fallback - performance is acceptable for moderate dataset sizes';
            END IF;
        END $$;
    """)

    # Create HNSW index on chunk_feedback (if table exists and has supported dimensions)
    op.execute("""
        DO $$
        DECLARE
            max_dim integer;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'chunk_feedback') THEN
                RETURN;
            END IF;

            SELECT MAX(vector_dims(query_embedding)) INTO max_dim
            FROM chunk_feedback
            WHERE query_embedding IS NOT NULL;

            IF max_dim IS NULL THEN
                RAISE NOTICE 'chunk_feedback: No embeddings found, skipping index';
            ELSIF max_dim <= 2000 THEN
                CREATE INDEX IF NOT EXISTS ix_chunk_feedback_query_embedding_hnsw
                ON chunk_feedback
                USING hnsw (query_embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            ELSIF max_dim <= 4000 THEN
                EXECUTE format('
                    CREATE INDEX IF NOT EXISTS ix_chunk_feedback_query_embedding_hnsw
                    ON chunk_feedback
                    USING hnsw ((query_embedding::halfvec(%s)) halfvec_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                ', max_dim);
            ELSE
                RAISE NOTICE 'chunk_feedback: % dimensions exceeds limits, using sequential scan', max_dim;
            END IF;
        END $$;
    """)

    # Create HNSW index on message_embeddings (if table exists)
    op.execute("""
        DO $$
        DECLARE
            max_dim integer;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'message_embeddings') THEN
                RETURN;
            END IF;

            SELECT MAX(vector_dims(embedding)) INTO max_dim
            FROM message_embeddings
            WHERE embedding IS NOT NULL;

            IF max_dim IS NULL THEN
                RAISE NOTICE 'message_embeddings: No embeddings found, skipping index';
            ELSIF max_dim <= 2000 THEN
                CREATE INDEX IF NOT EXISTS ix_message_embeddings_embedding_hnsw
                ON message_embeddings
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            ELSIF max_dim <= 4000 THEN
                EXECUTE format('
                    CREATE INDEX IF NOT EXISTS ix_message_embeddings_embedding_hnsw
                    ON message_embeddings
                    USING hnsw ((embedding::halfvec(%s)) halfvec_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                ', max_dim);
            ELSE
                RAISE NOTICE 'message_embeddings: % dimensions exceeds limits, using sequential scan', max_dim;
            END IF;
        END $$;
    """)

    # Create HNSW index on user_notes (if table exists and has embeddings)
    op.execute("""
        DO $$
        DECLARE
            max_dim integer;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'user_notes') THEN
                RETURN;
            END IF;

            SELECT MAX(vector_dims(embedding)) INTO max_dim
            FROM user_notes
            WHERE embedding IS NOT NULL;

            IF max_dim IS NULL THEN
                RAISE NOTICE 'user_notes: No embeddings found, skipping index';
            ELSIF max_dim <= 2000 THEN
                CREATE INDEX IF NOT EXISTS ix_user_notes_embedding_hnsw
                ON user_notes
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            ELSIF max_dim <= 4000 THEN
                EXECUTE format('
                    CREATE INDEX IF NOT EXISTS ix_user_notes_embedding_hnsw
                    ON user_notes
                    USING hnsw ((embedding::halfvec(%s)) halfvec_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                ', max_dim);
            ELSE
                RAISE NOTICE 'user_notes: % dimensions exceeds limits, using sequential scan', max_dim;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Drop HNSW indexes. Note: Does not recreate IVFFLAT due to dimension limits."""

    # Drop HNSW indexes (both regular and halfvec variants share the same name)
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_chunk_feedback_query_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_message_embeddings_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_user_notes_embedding_hnsw")

    # Note: We don't recreate IVFFLAT indexes because they have the same
    # dimension limits as HNSW. If dimensions were >4000 (like qwen3-embedding:8b
    # with 4096 dimensions), IVFFLAT also cannot be created.
