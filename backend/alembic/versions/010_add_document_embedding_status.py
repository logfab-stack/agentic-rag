"""Add embedding_status column to documents table

Feature #251: Post re-embed verification check

This migration adds an embedding_status column to the documents table to track
the embedding state of each document:

1. 'ready' - Document has embeddings and is searchable (default)
2. 'processing' - Document is being processed/re-embedded
3. 'embedding_failed' - Embedding generation failed, document needs attention

This enables:
- Visual indicator in UI for documents with failed embeddings
- Filtering documents by embedding status
- Recovery workflow for failed documents

Revision ID: 010
Revises: 009
Create Date: 2026-01-31 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add embedding_status column to documents table."""

    # Add embedding_status column if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'embedding_status'
            ) THEN
                ALTER TABLE documents
                ADD COLUMN embedding_status VARCHAR(20) NOT NULL DEFAULT 'ready';
                RAISE NOTICE '[Feature #251] Added embedding_status column to documents table';
            ELSE
                RAISE NOTICE '[Feature #251] embedding_status column already exists';
            END IF;
        END $$;
    """)

    # Create index for efficient filtering by embedding status
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_documents_embedding_status'
            ) THEN
                CREATE INDEX idx_documents_embedding_status
                ON documents(embedding_status);
                RAISE NOTICE '[Feature #251] Created index idx_documents_embedding_status';
            ELSE
                RAISE NOTICE '[Feature #251] Index idx_documents_embedding_status already exists';
            END IF;
        END $$;
    """)

    op.execute("SELECT '[Feature #251] Migration 010 completed: embedding_status column added to documents'")


def downgrade() -> None:
    """Remove embedding_status column from documents table."""

    # Drop index first
    op.execute("DROP INDEX IF EXISTS idx_documents_embedding_status")

    # Drop column
    op.execute("""
        ALTER TABLE documents
        DROP COLUMN IF EXISTS embedding_status
    """)
