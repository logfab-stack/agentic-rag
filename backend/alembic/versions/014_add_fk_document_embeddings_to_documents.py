"""Add FK constraint from document_embeddings.document_id to documents.id

Feature #256: Add FK constraint document_embeddings → documents

This migration adds a foreign key constraint from document_embeddings.document_id
to documents.id with ON DELETE CASCADE. This ensures:

1. Referential integrity - embeddings can only reference valid documents
2. Automatic cleanup - when a document is deleted, its embeddings are cascade deleted
3. Prevention of orphaned records - can't insert embeddings for non-existent documents

Prerequisites:
- No orphaned embeddings (document_id not in documents) must exist
- The migration will first clean up any orphaned embeddings before adding the FK

Revision ID: 014a
Revises: 014
Create Date: 2026-01-31 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '014a'
down_revision: Union[str, None] = '014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add foreign key constraint from document_embeddings to documents."""

    # Step 1: Clean up any orphaned embeddings (embeddings whose document_id doesn't exist in documents)
    # This is a safety measure - orphaned embeddings should not exist, but if they do, we need to remove them
    # before adding the FK constraint
    op.execute("""
        DO $$
        DECLARE
            orphan_count INTEGER;
        BEGIN
            -- Count orphaned embeddings
            SELECT COUNT(*) INTO orphan_count
            FROM document_embeddings de
            LEFT JOIN documents d ON de.document_id = d.id
            WHERE d.id IS NULL;

            IF orphan_count > 0 THEN
                -- Log the count for audit purposes (also logs to audit_embeddings_delete via trigger)
                RAISE NOTICE '[Feature #256] Found % orphaned embeddings, cleaning up...', orphan_count;

                -- Delete orphaned embeddings
                DELETE FROM document_embeddings
                WHERE document_id NOT IN (SELECT id FROM documents);

                RAISE NOTICE '[Feature #256] Cleaned up % orphaned embeddings', orphan_count;
            ELSE
                RAISE NOTICE '[Feature #256] No orphaned embeddings found, proceeding with FK constraint';
            END IF;
        END $$;
    """)

    # Step 2: Add the foreign key constraint if it doesn't already exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_embeddings_document'
                AND conrelid = 'document_embeddings'::regclass
            ) THEN
                ALTER TABLE document_embeddings
                ADD CONSTRAINT fk_embeddings_document
                FOREIGN KEY (document_id)
                REFERENCES documents(id)
                ON DELETE CASCADE;

                RAISE NOTICE '[Feature #256] Added FK constraint fk_embeddings_document with ON DELETE CASCADE';
            ELSE
                RAISE NOTICE '[Feature #256] FK constraint fk_embeddings_document already exists';
            END IF;
        END $$;
    """)

    op.execute("SELECT '[Feature #256] Migration 014 completed: FK constraint document_embeddings → documents added'")


def downgrade() -> None:
    """Remove foreign key constraint from document_embeddings to documents."""

    op.execute("""
        ALTER TABLE document_embeddings
        DROP CONSTRAINT IF EXISTS fk_embeddings_document
    """)

    op.execute("SELECT '[Feature #256] Migration 014 downgrade: FK constraint removed'")
