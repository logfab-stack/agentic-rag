"""Add soft delete status column to document_embeddings

Feature #249: Soft delete strategy for embeddings during re-embed

This migration adds:
1. 'status' column (active, pending_delete, archived) with default 'active'
2. 'pending_delete_at' timestamp column for cleanup scheduling

Instead of immediately deleting old embeddings during re-embed:
- Old embeddings are marked as 'pending_delete' with a timestamp
- New embeddings are created
- After successful creation, pending_delete rows are removed
- If re-embed fails, old embeddings remain available (data loss prevention)
- Cleanup job removes stale pending_delete rows after 24h

Revision ID: 008
Revises: 007
Create Date: 2026-01-31 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add soft delete columns to document_embeddings table."""

    # Add 'status' column with default 'active'
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings' AND column_name = 'status'
            ) THEN
                ALTER TABLE document_embeddings
                ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active';

                RAISE NOTICE 'Added status column to document_embeddings';
            ELSE
                RAISE NOTICE 'status column already exists in document_embeddings';
            END IF;
        END $$;
    """)

    # Add 'pending_delete_at' timestamp column
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings' AND column_name = 'pending_delete_at'
            ) THEN
                ALTER TABLE document_embeddings
                ADD COLUMN pending_delete_at TIMESTAMP WITH TIME ZONE NULL;

                RAISE NOTICE 'Added pending_delete_at column to document_embeddings';
            ELSE
                RAISE NOTICE 'pending_delete_at column already exists in document_embeddings';
            END IF;
        END $$;
    """)

    # Create index on status for filtering active embeddings efficiently
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_document_embeddings_status'
            ) THEN
                CREATE INDEX ix_document_embeddings_status
                ON document_embeddings(status);

                RAISE NOTICE 'Created index ix_document_embeddings_status';
            ELSE
                RAISE NOTICE 'Index ix_document_embeddings_status already exists';
            END IF;
        END $$;
    """)

    # Create partial index for quick lookup of pending_delete rows due for cleanup
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_document_embeddings_pending_cleanup'
            ) THEN
                CREATE INDEX ix_document_embeddings_pending_cleanup
                ON document_embeddings(pending_delete_at)
                WHERE status = 'pending_delete' AND pending_delete_at IS NOT NULL;

                RAISE NOTICE 'Created partial index for pending_delete cleanup';
            ELSE
                RAISE NOTICE 'Partial index ix_document_embeddings_pending_cleanup already exists';
            END IF;
        END $$;
    """)

    op.execute("SELECT 'Migration 008 completed: soft delete columns added'")


def downgrade() -> None:
    """Remove soft delete columns from document_embeddings table."""

    # Drop indexes first
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_pending_cleanup")
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_status")

    # Remove columns
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings' AND column_name = 'pending_delete_at'
            ) THEN
                ALTER TABLE document_embeddings DROP COLUMN pending_delete_at;
                RAISE NOTICE 'Dropped pending_delete_at column';
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings' AND column_name = 'status'
            ) THEN
                ALTER TABLE document_embeddings DROP COLUMN status;
                RAISE NOTICE 'Dropped status column';
            END IF;
        END $$;
    """)
