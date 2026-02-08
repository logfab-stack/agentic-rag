"""Add CHECK constraint for document status values

Feature #261: Add CHECK constraint for document status values

This migration adds a PostgreSQL CHECK constraint to ensure the status column
only contains valid values. This prevents invalid states from being inserted
at the database level, providing an additional layer of data integrity.

Valid status values:
- 'uploading': File is being uploaded to server
- 'processing': Document is being processed (parsing, embedding generation)
- 'ready': Document is fully processed and ready for use
- 'embedding_failed': Embedding generation failed, document may not be searchable
- 'file_missing': File has been deleted or is missing from disk

Revision ID: 022
Revises: 021
Create Date: 2026-01-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '022'
down_revision: Union[str, None] = '021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add CHECK constraint for document status values."""

    # First, verify there are no invalid status values in the table
    # If any exist, set them to 'ready' to allow constraint creation
    op.execute("""
        UPDATE documents
        SET status = 'ready'
        WHERE status NOT IN ('uploading', 'processing', 'ready', 'embedding_failed', 'file_missing');
    """)

    # Add CHECK constraint if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_document_status'
                AND conrelid = 'documents'::regclass
            ) THEN
                ALTER TABLE documents
                ADD CONSTRAINT chk_document_status
                CHECK (status IN ('uploading', 'processing', 'ready', 'embedding_failed', 'file_missing'));
                RAISE NOTICE '[Feature #261] Added CHECK constraint chk_document_status to documents table';
            ELSE
                RAISE NOTICE '[Feature #261] CHECK constraint chk_document_status already exists';
            END IF;
        END $$;
    """)

    op.execute("SELECT '[Feature #261] Migration 022 completed: document status CHECK constraint added'")


def downgrade() -> None:
    """Remove CHECK constraint for document status values."""

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_document_status'
                AND conrelid = 'documents'::regclass
            ) THEN
                ALTER TABLE documents DROP CONSTRAINT chk_document_status;
                RAISE NOTICE '[Feature #261] Dropped CHECK constraint chk_document_status';
            END IF;
        END $$;
    """)
