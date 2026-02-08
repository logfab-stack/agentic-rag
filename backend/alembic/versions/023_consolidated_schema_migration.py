"""Consolidated schema migration for features #256-261 and #273

This migration consolidates all schema changes from the following features into
a single, properly-ordered migration that can be applied to a fresh database:

Feature Dependencies (ordered by database dependencies):
1. #257 - Add file_path column (no dependencies)
2. #258 - Add status column (no dependencies)
3. #259 - Add embedding_model column (no dependencies)
4. #260 - Add chunk_count column (no dependencies)
5. #256 - Add FK constraint document_embeddings -> documents (requires documents table)
6. #261 - Add CHECK constraint for status values (requires status column from #258)

This migration is IDEMPOTENT - it will skip changes that already exist, making it
safe to run on databases that have already applied the individual migrations.

For fresh databases, this provides a clean upgrade path without needing to run
22 individual migrations.

IMPORTANT - DOWNGRADE WARNING:
==============================
The downgrade() function removes ALL schema changes including columns, indexes,
constraints, and triggers. This is DESTRUCTIVE and will result in DATA LOSS.

Only use downgrade in development/testing environments, NEVER in production.

If you need to rollback in production:
1. Take a backup first
2. Consider whether the schema changes can remain in place
3. Application code may depend on these columns

Revision ID: 023
Revises: 022
Create Date: 2026-01-31
Feature: #273 - Create consolidated schema migration

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
import os
from pathlib import Path


# revision identifiers, used by Alembic.
revision: str = '023'
down_revision: Union[str, None] = '022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Upload directory path for backfill operations
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"


def upgrade() -> None:
    """Apply all consolidated schema changes in dependency order.

    Order of operations:
    1. Add columns (no dependencies between them)
    2. Create indexes for columns
    3. Backfill data for columns
    4. Add foreign key constraints (requires columns to exist)
    5. Add check constraints (requires columns to exist)
    6. Create triggers for automatic updates
    """

    conn = op.get_bind()

    # =========================================================================
    # PHASE 1: ADD COLUMNS (Features #257, #258, #259, #260)
    # These can be added in any order as they don't depend on each other
    # =========================================================================

    print("[Phase 1] Adding columns to documents table...")

    # Feature #257: Add file_path column
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'file_path'
            ) THEN
                ALTER TABLE documents ADD COLUMN file_path VARCHAR(1000);
                RAISE NOTICE '[#257] Added file_path column';
            ELSE
                RAISE NOTICE '[#257] file_path column already exists';
            END IF;
        END $$;
    """)

    # Feature #258: Add status column
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'status'
            ) THEN
                ALTER TABLE documents ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'ready';
                RAISE NOTICE '[#258] Added status column';
            ELSE
                RAISE NOTICE '[#258] status column already exists';
            END IF;
        END $$;
    """)

    # Feature #259: Add embedding_model column
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'embedding_model'
            ) THEN
                ALTER TABLE documents ADD COLUMN embedding_model VARCHAR(100) DEFAULT NULL;
                RAISE NOTICE '[#259] Added embedding_model column';
            ELSE
                RAISE NOTICE '[#259] embedding_model column already exists';
            END IF;
        END $$;
    """)

    # Feature #260: Add chunk_count column
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'chunk_count'
            ) THEN
                ALTER TABLE documents ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 0;
                RAISE NOTICE '[#260] Added chunk_count column';
            ELSE
                RAISE NOTICE '[#260] chunk_count column already exists';
            END IF;
        END $$;
    """)

    # =========================================================================
    # PHASE 2: CREATE INDEXES
    # =========================================================================

    print("[Phase 2] Creating indexes...")

    # Index for file_path (#257)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_documents_file_path ON documents(file_path);
    """)

    # Index for status (#258)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
    """)

    # Index for embedding_model (#259)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_embedding_model ON documents(embedding_model);
    """)

    # Index for chunk_count (#260)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_chunk_count ON documents(chunk_count);
    """)

    # =========================================================================
    # PHASE 3: BACKFILL DATA
    # =========================================================================

    print("[Phase 3] Backfilling data...")

    # Backfill file_path from url column (#257)
    op.execute("""
        UPDATE documents
        SET file_path = url
        WHERE url IS NOT NULL AND file_path IS NULL;
    """)

    # Backfill status from embedding_status and file_status (#258)
    # Only update documents that still have default status
    op.execute("""
        UPDATE documents
        SET status = CASE
            WHEN file_status = 'file_missing' THEN 'file_missing'
            WHEN embedding_status = 'embedding_failed' THEN 'embedding_failed'
            WHEN embedding_status = 'processing' THEN 'processing'
            ELSE 'ready'
        END
        WHERE status = 'ready'
        AND (
            file_status IS NOT NULL AND file_status != 'ok'
            OR embedding_status IS NOT NULL AND embedding_status != 'ready'
        );
    """)

    # Backfill chunk_count from document_embeddings table (#260)
    op.execute("""
        DO $$
        BEGIN
            -- Check if document_embeddings has a status column
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings' AND column_name = 'status'
            ) THEN
                -- Table has status column, only count active embeddings
                UPDATE documents d
                SET chunk_count = COALESCE(
                    (SELECT COUNT(*)
                     FROM document_embeddings e
                     WHERE e.document_id = d.id
                     AND e.status = 'active'),
                    0
                )
                WHERE d.chunk_count = 0;
            ELSE
                -- Table doesn't have status column, count all
                UPDATE documents d
                SET chunk_count = COALESCE(
                    (SELECT COUNT(*) FROM document_embeddings e WHERE e.document_id = d.id),
                    0
                )
                WHERE d.chunk_count = 0;
            END IF;
            RAISE NOTICE '[#260] Backfilled chunk_count for documents';
        END $$;
    """)

    # =========================================================================
    # PHASE 4: FOREIGN KEY CONSTRAINTS (#256)
    # =========================================================================

    print("[Phase 4] Adding foreign key constraints...")

    # Clean up orphaned embeddings first
    op.execute("""
        DO $$
        DECLARE
            orphan_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO orphan_count
            FROM document_embeddings de
            LEFT JOIN documents d ON de.document_id = d.id
            WHERE d.id IS NULL;

            IF orphan_count > 0 THEN
                RAISE NOTICE '[#256] Found % orphaned embeddings, cleaning up...', orphan_count;
                DELETE FROM document_embeddings
                WHERE document_id NOT IN (SELECT id FROM documents);
                RAISE NOTICE '[#256] Cleaned up % orphaned embeddings', orphan_count;
            END IF;
        END $$;
    """)

    # Add FK constraint
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
                RAISE NOTICE '[#256] Added FK constraint fk_embeddings_document';
            ELSE
                RAISE NOTICE '[#256] FK constraint already exists';
            END IF;
        END $$;
    """)

    # =========================================================================
    # PHASE 5: CHECK CONSTRAINTS (#261)
    # =========================================================================

    print("[Phase 5] Adding CHECK constraints...")

    # First, fix any invalid status values
    op.execute("""
        UPDATE documents
        SET status = 'ready'
        WHERE status NOT IN ('uploading', 'processing', 'ready', 'embedding_failed', 'file_missing');
    """)

    # Add CHECK constraint
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
                RAISE NOTICE '[#261] Added CHECK constraint chk_document_status';
            ELSE
                RAISE NOTICE '[#261] CHECK constraint already exists';
            END IF;
        END $$;
    """)

    # =========================================================================
    # PHASE 6: TRIGGERS (#260 - chunk_count auto-update)
    # =========================================================================

    print("[Phase 6] Creating triggers...")

    # Create trigger function for chunk_count updates
    op.execute("""
        CREATE OR REPLACE FUNCTION update_document_chunk_count()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE documents
                SET chunk_count = chunk_count + 1
                WHERE id = NEW.document_id;
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE documents
                SET chunk_count = GREATEST(chunk_count - 1, 0)
                WHERE id = OLD.document_id;
                RETURN OLD;
            ELSIF TG_OP = 'UPDATE' THEN
                IF TG_ARGV[0] = 'has_status' THEN
                    IF OLD.status = 'active' AND NEW.status = 'pending_delete' THEN
                        UPDATE documents
                        SET chunk_count = GREATEST(chunk_count - 1, 0)
                        WHERE id = NEW.document_id;
                    ELSIF OLD.status = 'pending_delete' AND NEW.status = 'active' THEN
                        UPDATE documents
                        SET chunk_count = chunk_count + 1
                        WHERE id = NEW.document_id;
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create triggers on document_embeddings
    op.execute("""
        DO $$
        BEGIN
            DROP TRIGGER IF EXISTS trg_update_chunk_count_insert ON document_embeddings;
            DROP TRIGGER IF EXISTS trg_update_chunk_count_delete ON document_embeddings;
            DROP TRIGGER IF EXISTS trg_update_chunk_count_update ON document_embeddings;

            CREATE TRIGGER trg_update_chunk_count_insert
            AFTER INSERT ON document_embeddings
            FOR EACH ROW
            EXECUTE FUNCTION update_document_chunk_count();

            CREATE TRIGGER trg_update_chunk_count_delete
            AFTER DELETE ON document_embeddings
            FOR EACH ROW
            EXECUTE FUNCTION update_document_chunk_count();

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings' AND column_name = 'status'
            ) THEN
                CREATE TRIGGER trg_update_chunk_count_update
                AFTER UPDATE OF status ON document_embeddings
                FOR EACH ROW
                EXECUTE FUNCTION update_document_chunk_count('has_status');
            END IF;

            RAISE NOTICE '[#260] Created chunk_count triggers';
        END $$;
    """)

    print("[Consolidated Migration] Complete - all schema changes applied")


def downgrade() -> None:
    """Reverse all consolidated schema changes in reverse dependency order.

    WARNING: This is a DESTRUCTIVE operation that will:
    - Remove columns (file_path, status, embedding_model, chunk_count)
    - Remove constraints and indexes
    - Remove triggers

    DATA IN THESE COLUMNS WILL BE LOST!

    Only use in development/testing environments. For production, consider
    whether the schema changes need to be reversed at all.

    Order of operations (reverse of upgrade):
    1. Drop triggers
    2. Drop check constraints
    3. Drop foreign key constraints
    4. Drop indexes
    5. Drop columns
    """

    print("[Downgrade] WARNING: This will remove columns and DATA WILL BE LOST!")
    print("[Downgrade] Reversing consolidated schema changes...")

    # =========================================================================
    # PHASE 1: DROP TRIGGERS
    # =========================================================================

    op.execute("""
        DROP TRIGGER IF EXISTS trg_update_chunk_count_insert ON document_embeddings;
        DROP TRIGGER IF EXISTS trg_update_chunk_count_delete ON document_embeddings;
        DROP TRIGGER IF EXISTS trg_update_chunk_count_update ON document_embeddings;
    """)

    op.execute("""
        DROP FUNCTION IF EXISTS update_document_chunk_count();
    """)

    # =========================================================================
    # PHASE 2: DROP CHECK CONSTRAINTS (#261)
    # =========================================================================

    op.execute("""
        ALTER TABLE documents DROP CONSTRAINT IF EXISTS chk_document_status;
    """)

    # =========================================================================
    # PHASE 3: DROP FOREIGN KEY CONSTRAINTS (#256)
    # =========================================================================

    op.execute("""
        ALTER TABLE document_embeddings DROP CONSTRAINT IF EXISTS fk_embeddings_document;
    """)

    # =========================================================================
    # PHASE 4: DROP INDEXES
    # =========================================================================

    op.execute("DROP INDEX IF EXISTS ix_documents_file_path;")
    op.execute("DROP INDEX IF EXISTS idx_documents_status;")
    op.execute("DROP INDEX IF EXISTS idx_documents_embedding_model;")
    op.execute("DROP INDEX IF EXISTS idx_documents_chunk_count;")

    # =========================================================================
    # PHASE 5: DROP COLUMNS
    # =========================================================================

    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS file_path;")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS status;")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS embedding_model;")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS chunk_count;")

    print("[Downgrade] Complete - all schema changes reversed")
