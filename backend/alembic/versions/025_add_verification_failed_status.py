"""Add 'verification_failed' status to document status CHECK constraint

Feature #297: Post re-embed verification check

This migration adds 'verification_failed' as a valid document status value.
This status is set when:
- Re-embedding completes but verification shows mismatch between
  expected chunk_count and actual embedding count
- After automatic retry fails

The verification_failed status is distinct from embedding_failed:
- embedding_failed: The embedding generation process itself failed
- verification_failed: Embeddings were generated but count verification failed

Revision ID: 025
Revises: 024
Create Date: 2026-01-31
Feature: #297 - Post re-embed verification check

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic
revision: str = '025'
down_revision: Union[str, None] = '024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'verification_failed' to the status CHECK constraint."""
    # Use DO block for idempotent operation
    op.execute("""
        DO $$
        BEGIN
            -- First drop the existing constraint if it exists
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'chk_document_status'
                AND table_name = 'documents'
            ) THEN
                ALTER TABLE documents DROP CONSTRAINT chk_document_status;
                RAISE NOTICE '[Feature #297] Dropped existing CHECK constraint chk_document_status';
            END IF;

            -- Now add the new constraint with verification_failed status
            ALTER TABLE documents
            ADD CONSTRAINT chk_document_status
            CHECK (status IN ('uploading', 'processing', 'ready', 'embedding_failed', 'file_missing', 'verification_failed'));
            RAISE NOTICE '[Feature #297] Added CHECK constraint chk_document_status with verification_failed status';
        END
        $$;
    """)


def downgrade() -> None:
    """Remove 'verification_failed' from the status CHECK constraint."""
    op.execute("""
        DO $$
        BEGIN
            -- First, update any documents with verification_failed status to embedding_failed
            UPDATE documents SET status = 'embedding_failed' WHERE status = 'verification_failed';
            RAISE NOTICE '[Feature #297] Updated verification_failed documents to embedding_failed';

            -- Drop the existing constraint
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'chk_document_status'
                AND table_name = 'documents'
            ) THEN
                ALTER TABLE documents DROP CONSTRAINT chk_document_status;
            END IF;

            -- Restore the original constraint without verification_failed
            ALTER TABLE documents
            ADD CONSTRAINT chk_document_status
            CHECK (status IN ('uploading', 'processing', 'ready', 'embedding_failed', 'file_missing'));
            RAISE NOTICE '[Feature #297] Restored CHECK constraint chk_document_status without verification_failed';
        END
        $$;
    """)
