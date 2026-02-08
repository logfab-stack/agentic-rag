"""Add embedding_model column to documents table

Feature #259: Track which embedding model was used for each document.

This column stores the embedding model identifier (e.g., 'openai:text-embedding-3-small'
or 'ollama:bge-m3:latest') used to generate embeddings for the document.

This is critical for:
1. Knowing when re-embedding is needed after model changes
2. Detecting documents embedded with mismatched models
3. Providing transparency about which model was used

Revision ID: 016
Revises: 015
Create Date: 2026-01-31
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add embedding_model column to documents table."""

    # Step 1: Add the embedding_model column (only if it doesn't exist)
    # VARCHAR(100) to accommodate model names like 'ollama:snowflake-arctic-embed2:latest'
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'embedding_model'
            ) THEN
                ALTER TABLE documents ADD COLUMN embedding_model VARCHAR(100) DEFAULT NULL;
            END IF;
        END $$;
    """)

    # Step 2: Create index for efficient querying by embedding model (only if it doesn't exist)
    # This helps with queries like "find all documents using model X"
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_embedding_model
        ON documents (embedding_model);
    """)

    # Step 3: Backfill existing documents by reading from their embeddings
    # This is done in Python code after migration, not in SQL, because:
    # - We need to query the document_embeddings table for metadata
    # - The metadata is stored as JSONB with embedding_source field

    # Note: Backfill will be handled by a separate function in the API
    # that queries document_embeddings metadata for each document.
    # Documents with no embeddings (structured data) will remain NULL.

    print("Migration complete. Run backfill script to populate embedding_model for existing documents.")


def downgrade() -> None:
    """Remove embedding_model column from documents table."""

    # Step 1: Drop index
    op.drop_index('idx_documents_embedding_model', table_name='documents')

    # Step 2: Drop column
    op.drop_column('documents', 'embedding_model')
