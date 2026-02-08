"""Add document_id and metadata columns to audit_log table

Feature #267: Add detailed audit logging for document operations

This migration extends the audit_log table to track document lifecycle events:
- document_uploaded, embedding_started, embedding_completed, embedding_failed, document_deleted
- Includes metadata: file_size, chunk_count, model_used, duration

Revision ID: 021
Revises: 020
Create Date: 2026-01-31 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '021'
down_revision: Union[str, None] = '020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add document_id and metadata columns to audit_log table for document operation tracking."""

    # Add document_id column (nullable since existing records don't have it)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_log' AND column_name = 'document_id'
            ) THEN
                ALTER TABLE audit_log ADD COLUMN document_id VARCHAR(36);
                RAISE NOTICE '[Feature #267] Added document_id column to audit_log';
            ELSE
                RAISE NOTICE '[Feature #267] document_id column already exists';
            END IF;
        END $$;
    """)

    # Add document_name column to store the document title at time of operation
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_log' AND column_name = 'document_name'
            ) THEN
                ALTER TABLE audit_log ADD COLUMN document_name VARCHAR(255);
                RAISE NOTICE '[Feature #267] Added document_name column to audit_log';
            ELSE
                RAISE NOTICE '[Feature #267] document_name column already exists';
            END IF;
        END $$;
    """)

    # Add file_size column (in bytes)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_log' AND column_name = 'file_size'
            ) THEN
                ALTER TABLE audit_log ADD COLUMN file_size INTEGER;
                RAISE NOTICE '[Feature #267] Added file_size column to audit_log';
            ELSE
                RAISE NOTICE '[Feature #267] file_size column already exists';
            END IF;
        END $$;
    """)

    # Add chunk_count column
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_log' AND column_name = 'chunk_count'
            ) THEN
                ALTER TABLE audit_log ADD COLUMN chunk_count INTEGER;
                RAISE NOTICE '[Feature #267] Added chunk_count column to audit_log';
            ELSE
                RAISE NOTICE '[Feature #267] chunk_count column already exists';
            END IF;
        END $$;
    """)

    # Add model_used column (for embedding model)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_log' AND column_name = 'model_used'
            ) THEN
                ALTER TABLE audit_log ADD COLUMN model_used VARCHAR(100);
                RAISE NOTICE '[Feature #267] Added model_used column to audit_log';
            ELSE
                RAISE NOTICE '[Feature #267] model_used column already exists';
            END IF;
        END $$;
    """)

    # Add duration_ms column (operation duration in milliseconds)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_log' AND column_name = 'duration_ms'
            ) THEN
                ALTER TABLE audit_log ADD COLUMN duration_ms INTEGER;
                RAISE NOTICE '[Feature #267] Added duration_ms column to audit_log';
            ELSE
                RAISE NOTICE '[Feature #267] duration_ms column already exists';
            END IF;
        END $$;
    """)

    # Create index on document_id for efficient document history queries
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_audit_log_document_id'
            ) THEN
                CREATE INDEX ix_audit_log_document_id ON audit_log(document_id);
                RAISE NOTICE '[Feature #267] Created index on document_id';
            ELSE
                RAISE NOTICE '[Feature #267] Index ix_audit_log_document_id already exists';
            END IF;
        END $$;
    """)

    # Create composite index for document history with action type
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_audit_log_document_action'
            ) THEN
                CREATE INDEX ix_audit_log_document_action ON audit_log(document_id, action, created_at DESC);
                RAISE NOTICE '[Feature #267] Created composite index for document action queries';
            ELSE
                RAISE NOTICE '[Feature #267] Index ix_audit_log_document_action already exists';
            END IF;
        END $$;
    """)

    op.execute("SELECT '[Feature #267] Migration 021 completed: audit_log extended for document operations'")


def downgrade() -> None:
    """Remove document-related columns from audit_log table."""

    # Drop indexes first
    op.execute("DROP INDEX IF EXISTS ix_audit_log_document_action")
    op.execute("DROP INDEX IF EXISTS ix_audit_log_document_id")

    # Drop columns
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS duration_ms")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS model_used")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS chunk_count")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS file_size")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS document_name")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS document_id")
