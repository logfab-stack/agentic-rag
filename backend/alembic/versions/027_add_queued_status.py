"""Add 'queued' status to document status CHECK constraint

Feature #330: Background document processing with async queue

This migration adds 'queued' as a valid document status value.
This status is set when:
- Document file is saved but processing hasn't started yet
- Document is waiting in the background processing queue

The queued status allows:
- Immediate response to uploads without waiting for processing
- Non-blocking upload experience for large documents
- Queue status visibility for users

Revision ID: 027
Revises: 026
Create Date: 2026-02-03
Feature: #330 - Background document processing with async queue

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic
revision: str = '027'
down_revision: Union[str, None] = '026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'queued' to the status CHECK constraint."""
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
                RAISE NOTICE '[Feature #330] Dropped existing CHECK constraint chk_document_status';
            END IF;

            -- Now add the new constraint with queued status
            ALTER TABLE documents
            ADD CONSTRAINT chk_document_status
            CHECK (status IN ('uploading', 'queued', 'processing', 'ready', 'embedding_failed', 'file_missing', 'verification_failed'));
            RAISE NOTICE '[Feature #330] Added CHECK constraint chk_document_status with queued status';
        END
        $$;
    """)


def downgrade() -> None:
    """Remove 'queued' from the status CHECK constraint."""
    op.execute("""
        DO $$
        BEGIN
            -- First, update any documents with queued status to processing
            UPDATE documents SET status = 'processing' WHERE status = 'queued';
            RAISE NOTICE '[Feature #330] Updated queued documents to processing';

            -- Drop the existing constraint
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'chk_document_status'
                AND table_name = 'documents'
            ) THEN
                ALTER TABLE documents DROP CONSTRAINT chk_document_status;
            END IF;

            -- Restore the constraint without queued
            ALTER TABLE documents
            ADD CONSTRAINT chk_document_status
            CHECK (status IN ('uploading', 'processing', 'ready', 'embedding_failed', 'file_missing', 'verification_failed'));
            RAISE NOTICE '[Feature #330] Restored CHECK constraint chk_document_status without queued';
        END
        $$;
    """)
