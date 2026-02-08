"""Add file_status column to documents table

Feature #254: Track file existence status for orphaned record detection

This migration:
1. Adds a 'file_status' column to the documents table (VARCHAR 20, default 'ok')
2. Creates an index on file_status for efficient filtering

Revision ID: 013
Revises: 012
Create Date: 2026-01-31 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '013'
down_revision: Union[str, None] = '012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add file_status column with default 'ok'."""

    # Step 1: Add file_status column if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'file_status'
            ) THEN
                ALTER TABLE documents ADD COLUMN file_status VARCHAR(20) NOT NULL DEFAULT 'ok';
                RAISE NOTICE '[Feature #254] Added file_status column to documents table';
            ELSE
                RAISE NOTICE '[Feature #254] file_status column already exists';
            END IF;
        END $$;
    """)

    # Step 2: Create index on file_status for efficient filtering
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_documents_file_status'
            ) THEN
                CREATE INDEX idx_documents_file_status ON documents(file_status);
                RAISE NOTICE '[Feature #254] Created index on file_status';
            END IF;
        END $$;
    """)

    op.execute("SELECT '[Feature #254] Migration 013 completed: file_status column added'")


def downgrade() -> None:
    """Remove file_status column."""

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_documents_file_status'
            ) THEN
                DROP INDEX idx_documents_file_status;
            END IF;
        END $$;
    """)

    op.execute("""
        ALTER TABLE documents DROP COLUMN IF EXISTS file_status;
    """)
