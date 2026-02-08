"""Add embeddings_backup table for re-embed operations

Feature #250: Backup embeddings before re-embed operation

This migration creates an embeddings_backup table that stores copies of embeddings
before re-embedding. This provides an additional layer of safety beyond the soft
delete mechanism (Feature #249):

1. embeddings_backup table with same schema as document_embeddings + timestamp
2. Backup is created before re-embed operation starts
3. If re-embed fails, embeddings can be restored from backup
4. Backup is deleted only after successful re-embed completion
5. API endpoint allows manual restore from backup if needed

Revision ID: 009
Revises: 008
Create Date: 2026-01-31 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create embeddings_backup table."""

    # Create embeddings_backup table
    op.execute("""
        CREATE TABLE IF NOT EXISTS embeddings_backup (
            id SERIAL PRIMARY KEY,
            original_id INTEGER NOT NULL,
            document_id VARCHAR(255) NOT NULL,
            chunk_id VARCHAR(255) NOT NULL,
            text TEXT NOT NULL,
            embedding vector,
            metadata JSONB DEFAULT '{}',
            status VARCHAR(20) DEFAULT 'active',
            pending_delete_at TIMESTAMP WITH TIME ZONE NULL,
            backup_created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            backup_reason VARCHAR(100) DEFAULT 'reembed'
        );
    """)

    # Create indexes for efficient lookup
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_embeddings_backup_document_id'
            ) THEN
                CREATE INDEX ix_embeddings_backup_document_id
                ON embeddings_backup(document_id);
                RAISE NOTICE 'Created index ix_embeddings_backup_document_id';
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_embeddings_backup_backup_created_at'
            ) THEN
                CREATE INDEX ix_embeddings_backup_backup_created_at
                ON embeddings_backup(backup_created_at);
                RAISE NOTICE 'Created index ix_embeddings_backup_backup_created_at';
            END IF;
        END $$;
    """)

    op.execute("SELECT 'Migration 009 completed: embeddings_backup table created'")


def downgrade() -> None:
    """Drop embeddings_backup table."""

    # Drop indexes first
    op.execute("DROP INDEX IF EXISTS ix_embeddings_backup_backup_created_at")
    op.execute("DROP INDEX IF EXISTS ix_embeddings_backup_document_id")

    # Drop table
    op.execute("DROP TABLE IF EXISTS embeddings_backup")
