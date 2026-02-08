"""Add details JSONB column to audit_embeddings_delete and retention policy function

Feature #266: Create embeddings_audit table for tracking deletions

This migration:
1. Adds a 'details' JSONB column to audit_embeddings_delete for structured metadata
2. Creates a retention policy function to delete records older than N days
3. Creates an index on deleted_at for efficient retention cleanup

Revision ID: 020
Revises: 019
Create Date: 2026-01-31 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '020'
down_revision: Union[str, None] = '019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add details JSONB column and retention policy function."""

    # Add details JSONB column if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_embeddings_delete'
                AND column_name = 'details'
            ) THEN
                ALTER TABLE audit_embeddings_delete
                ADD COLUMN details JSONB;
                RAISE NOTICE '[Feature #266] Added details JSONB column to audit_embeddings_delete';
            ELSE
                RAISE NOTICE '[Feature #266] details column already exists';
            END IF;
        END $$;
    """)

    # Create index on details for JSONB queries (GIN index)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_audit_embeddings_delete_details'
            ) THEN
                CREATE INDEX ix_audit_embeddings_delete_details
                ON audit_embeddings_delete USING GIN (details);
                RAISE NOTICE '[Feature #266] Created GIN index on details column';
            END IF;
        END $$;
    """)

    # Create retention policy function
    # This function deletes audit records older than the specified number of days
    op.execute("""
        CREATE OR REPLACE FUNCTION cleanup_audit_retention(
            p_retention_days INTEGER DEFAULT 30
        )
        RETURNS TABLE(
            deleted_count INTEGER,
            oldest_remaining TIMESTAMP WITH TIME ZONE,
            retention_days INTEGER
        ) AS $$
        DECLARE
            v_cutoff TIMESTAMP WITH TIME ZONE;
            v_deleted INTEGER := 0;
            v_oldest TIMESTAMP WITH TIME ZONE;
        BEGIN
            -- Calculate cutoff date
            v_cutoff := NOW() - (p_retention_days || ' days')::INTERVAL;

            -- Delete old records
            DELETE FROM audit_embeddings_delete
            WHERE deleted_at < v_cutoff;

            GET DIAGNOSTICS v_deleted = ROW_COUNT;

            -- Get the oldest remaining record
            SELECT MIN(deleted_at) INTO v_oldest
            FROM audit_embeddings_delete;

            RETURN QUERY SELECT v_deleted, v_oldest, p_retention_days;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("SELECT '[Feature #266] Migration 020 completed: details column and retention policy added'")


def downgrade() -> None:
    """Remove details column and retention policy function."""

    # Drop the retention policy function
    op.execute("DROP FUNCTION IF EXISTS cleanup_audit_retention(INTEGER)")

    # Drop the details index
    op.execute("DROP INDEX IF EXISTS ix_audit_embeddings_delete_details")

    # Drop the details column
    op.execute("""
        ALTER TABLE audit_embeddings_delete
        DROP COLUMN IF EXISTS details
    """)
