"""Add status column to documents table for unified processing state tracking

Feature #258: Add unified status column to documents table

This migration adds a 'status' column to track the overall document processing state:
- 'uploading': File is being uploaded to server
- 'processing': Document is being processed (parsing, embedding generation)
- 'ready': Document is fully processed and ready for use
- 'embedding_failed': Embedding generation failed, document may not be searchable
- 'file_missing': File has been deleted or is missing from disk

This provides a single source of truth for document state, combining the concepts
from embedding_status and file_status into one unified status field.

Revision ID: 015
Revises: 014a
Create Date: 2026-01-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '015'
down_revision: Union[str, None] = '014a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add status column to documents table."""

    # Step 1: Add status column if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'status'
            ) THEN
                ALTER TABLE documents ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'ready';
                RAISE NOTICE '[Feature #258] Added status column to documents table';
            ELSE
                RAISE NOTICE '[Feature #258] status column already exists';
            END IF;
        END $$;
    """)

    # Step 2: Migrate existing data - set status based on embedding_status and file_status
    # Priority: file_missing > embedding_failed > processing > ready
    op.execute("""
        UPDATE documents
        SET status = CASE
            WHEN file_status = 'file_missing' THEN 'file_missing'
            WHEN embedding_status = 'embedding_failed' THEN 'embedding_failed'
            WHEN embedding_status = 'processing' THEN 'processing'
            ELSE 'ready'
        END
        WHERE status = 'ready';
    """)

    # Step 3: Create index for efficient filtering by status
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_documents_status'
            ) THEN
                CREATE INDEX idx_documents_status ON documents(status);
                RAISE NOTICE '[Feature #258] Created index idx_documents_status';
            ELSE
                RAISE NOTICE '[Feature #258] Index idx_documents_status already exists';
            END IF;
        END $$;
    """)

    op.execute("SELECT '[Feature #258] Migration 015 completed: status column added'")


def downgrade() -> None:
    """Remove status column from documents table."""

    # Drop index first
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_documents_status'
            ) THEN
                DROP INDEX idx_documents_status;
            END IF;
        END $$;
    """)

    # Drop column
    op.execute("""
        ALTER TABLE documents DROP COLUMN IF EXISTS status;
    """)
