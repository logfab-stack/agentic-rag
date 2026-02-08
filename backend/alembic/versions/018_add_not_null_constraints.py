"""Add NOT NULL constraints for critical columns

Feature #263: Add NOT NULL constraints for critical columns

This migration adds NOT NULL constraints to critical columns that should never
contain NULL values:

1. document_embeddings.embedding - Vector embeddings must exist for the record to be useful
2. document_embeddings.created_at - Timestamp should always be recorded
3. embeddings_backup.embedding - Backup embeddings must also contain the vector

Prerequisites:
- No NULL values should exist in these columns (verified in upgrade function)

Revision ID: 018
Revises: 017
Create Date: 2026-01-31 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '018'
down_revision: Union[str, None] = '017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add NOT NULL constraints to critical columns."""

    # Step 1: Check and clean up any NULL embeddings in document_embeddings
    # These records are invalid and should be removed
    op.execute("""
        DO $$
        DECLARE
            null_count INTEGER;
        BEGIN
            -- Count NULL embeddings
            SELECT COUNT(*) INTO null_count
            FROM document_embeddings
            WHERE embedding IS NULL;

            IF null_count > 0 THEN
                RAISE NOTICE '[Feature #263] Found % records with NULL embedding, removing...', null_count;

                -- Delete records with NULL embeddings (they are useless)
                DELETE FROM document_embeddings WHERE embedding IS NULL;

                RAISE NOTICE '[Feature #263] Removed % invalid records with NULL embedding', null_count;
            ELSE
                RAISE NOTICE '[Feature #263] No NULL embeddings found in document_embeddings';
            END IF;
        END $$;
    """)

    # Step 2: Set default for created_at where NULL (use current timestamp)
    op.execute("""
        UPDATE document_embeddings
        SET created_at = CURRENT_TIMESTAMP
        WHERE created_at IS NULL;
    """)

    # Step 3: Add NOT NULL constraint to document_embeddings.embedding
    op.execute("""
        DO $$
        BEGIN
            -- Check if constraint already exists by checking column nullability
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings'
                AND column_name = 'embedding'
                AND is_nullable = 'YES'
            ) THEN
                ALTER TABLE document_embeddings
                ALTER COLUMN embedding SET NOT NULL;

                RAISE NOTICE '[Feature #263] Added NOT NULL constraint to document_embeddings.embedding';
            ELSE
                RAISE NOTICE '[Feature #263] document_embeddings.embedding already has NOT NULL constraint';
            END IF;
        END $$;
    """)

    # Step 4: Add NOT NULL constraint to document_embeddings.created_at
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings'
                AND column_name = 'created_at'
                AND is_nullable = 'YES'
            ) THEN
                -- Ensure server default exists
                ALTER TABLE document_embeddings
                ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;

                ALTER TABLE document_embeddings
                ALTER COLUMN created_at SET NOT NULL;

                RAISE NOTICE '[Feature #263] Added NOT NULL constraint to document_embeddings.created_at';
            ELSE
                RAISE NOTICE '[Feature #263] document_embeddings.created_at already has NOT NULL constraint';
            END IF;
        END $$;
    """)

    # Step 5: Clean up NULL embeddings in embeddings_backup (same logic)
    op.execute("""
        DO $$
        DECLARE
            null_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO null_count
            FROM embeddings_backup
            WHERE embedding IS NULL;

            IF null_count > 0 THEN
                RAISE NOTICE '[Feature #263] Found % records with NULL embedding in backup, removing...', null_count;
                DELETE FROM embeddings_backup WHERE embedding IS NULL;
                RAISE NOTICE '[Feature #263] Removed % invalid backup records', null_count;
            ELSE
                RAISE NOTICE '[Feature #263] No NULL embeddings found in embeddings_backup';
            END IF;
        END $$;
    """)

    # Step 6: Add NOT NULL constraint to embeddings_backup.embedding
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'embeddings_backup'
                AND column_name = 'embedding'
                AND is_nullable = 'YES'
            ) THEN
                ALTER TABLE embeddings_backup
                ALTER COLUMN embedding SET NOT NULL;

                RAISE NOTICE '[Feature #263] Added NOT NULL constraint to embeddings_backup.embedding';
            ELSE
                RAISE NOTICE '[Feature #263] embeddings_backup.embedding already has NOT NULL constraint';
            END IF;
        END $$;
    """)

    op.execute("SELECT '[Feature #263] Migration 018 completed: NOT NULL constraints added to critical columns'")


def downgrade() -> None:
    """Remove NOT NULL constraints from critical columns."""

    # Remove NOT NULL from document_embeddings.embedding
    op.execute("""
        ALTER TABLE document_embeddings
        ALTER COLUMN embedding DROP NOT NULL;
    """)

    # Remove NOT NULL from document_embeddings.created_at
    op.execute("""
        ALTER TABLE document_embeddings
        ALTER COLUMN created_at DROP NOT NULL;
    """)

    # Remove NOT NULL from embeddings_backup.embedding
    op.execute("""
        ALTER TABLE embeddings_backup
        ALTER COLUMN embedding DROP NOT NULL;
    """)

    op.execute("SELECT '[Feature #263] Migration 018 downgrade: NOT NULL constraints removed'")
