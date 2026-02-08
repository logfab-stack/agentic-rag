"""Add chunk_count column to documents table

Feature #260: Store the number of chunks/embeddings for each document.
This allows quick verification that embeddings exist without querying the embeddings table.

This migration:
1. Adds a 'chunk_count' column to the documents table (INTEGER, DEFAULT 0)
2. Creates an index on chunk_count for efficient filtering
3. Backfills existing documents with chunk counts from document_embeddings table

Revision ID: 014
Revises: 013
Create Date: 2026-01-31 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '014'
down_revision: Union[str, None] = '013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add chunk_count column with default 0 and backfill existing documents."""

    # Step 1: Add chunk_count column if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'chunk_count'
            ) THEN
                ALTER TABLE documents ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 0;
                RAISE NOTICE '[Feature #260] Added chunk_count column to documents table';
            ELSE
                RAISE NOTICE '[Feature #260] chunk_count column already exists';
            END IF;
        END $$;
    """)

    # Step 2: Create index on chunk_count for efficient filtering
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_documents_chunk_count'
            ) THEN
                CREATE INDEX idx_documents_chunk_count ON documents(chunk_count);
                RAISE NOTICE '[Feature #260] Created index on chunk_count';
            END IF;
        END $$;
    """)

    # Step 3: Backfill chunk_count from document_embeddings table
    # Only count 'active' embeddings (not pending_delete or archived)
    op.execute("""
        DO $$
        DECLARE
            updated_count INTEGER;
        BEGIN
            -- Update documents with actual embedding counts
            -- Filter by status='active' if the status column exists
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
                );
            ELSE
                -- Table doesn't have status column, count all
                UPDATE documents d
                SET chunk_count = COALESCE(
                    (SELECT COUNT(*) FROM document_embeddings e WHERE e.document_id = d.id),
                    0
                );
            END IF;

            GET DIAGNOSTICS updated_count = ROW_COUNT;
            RAISE NOTICE '[Feature #260] Backfilled chunk_count for % documents', updated_count;
        END $$;
    """)

    # Step 4: Create or replace trigger function to automatically update chunk_count
    op.execute("""
        CREATE OR REPLACE FUNCTION update_document_chunk_count()
        RETURNS TRIGGER AS $$
        BEGIN
            -- After INSERT: increment chunk_count for the document
            IF TG_OP = 'INSERT' THEN
                UPDATE documents
                SET chunk_count = chunk_count + 1
                WHERE id = NEW.document_id;
                RETURN NEW;

            -- After DELETE: decrement chunk_count for the document
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE documents
                SET chunk_count = GREATEST(chunk_count - 1, 0)
                WHERE id = OLD.document_id;
                RETURN OLD;

            -- After UPDATE: handle status changes (soft delete/restore)
            ELSIF TG_OP = 'UPDATE' THEN
                -- Check if status column exists and changed
                IF TG_ARGV[0] = 'has_status' THEN
                    -- Active -> pending_delete: decrement
                    IF OLD.status = 'active' AND NEW.status = 'pending_delete' THEN
                        UPDATE documents
                        SET chunk_count = GREATEST(chunk_count - 1, 0)
                        WHERE id = NEW.document_id;
                    -- Pending_delete -> active: increment (restore)
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

    # Step 5: Create triggers on document_embeddings table
    op.execute("""
        DO $$
        BEGIN
            -- Drop existing triggers if they exist
            DROP TRIGGER IF EXISTS trg_update_chunk_count_insert ON document_embeddings;
            DROP TRIGGER IF EXISTS trg_update_chunk_count_delete ON document_embeddings;
            DROP TRIGGER IF EXISTS trg_update_chunk_count_update ON document_embeddings;

            -- Create trigger for INSERT
            CREATE TRIGGER trg_update_chunk_count_insert
            AFTER INSERT ON document_embeddings
            FOR EACH ROW
            EXECUTE FUNCTION update_document_chunk_count();

            -- Create trigger for DELETE
            CREATE TRIGGER trg_update_chunk_count_delete
            AFTER DELETE ON document_embeddings
            FOR EACH ROW
            EXECUTE FUNCTION update_document_chunk_count();

            -- Create trigger for UPDATE (only if status column exists)
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_embeddings' AND column_name = 'status'
            ) THEN
                CREATE TRIGGER trg_update_chunk_count_update
                AFTER UPDATE OF status ON document_embeddings
                FOR EACH ROW
                EXECUTE FUNCTION update_document_chunk_count('has_status');
            END IF;

            RAISE NOTICE '[Feature #260] Created triggers for automatic chunk_count sync';
        END $$;
    """)

    op.execute("SELECT '[Feature #260] Migration 014 completed: chunk_count column added with auto-sync triggers'")


def downgrade() -> None:
    """Remove chunk_count column and triggers."""

    # Drop triggers
    op.execute("""
        DROP TRIGGER IF EXISTS trg_update_chunk_count_insert ON document_embeddings;
        DROP TRIGGER IF EXISTS trg_update_chunk_count_delete ON document_embeddings;
        DROP TRIGGER IF EXISTS trg_update_chunk_count_update ON document_embeddings;
    """)

    # Drop trigger function
    op.execute("""
        DROP FUNCTION IF EXISTS update_document_chunk_count();
    """)

    # Drop index
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_documents_chunk_count'
            ) THEN
                DROP INDEX idx_documents_chunk_count;
            END IF;
        END $$;
    """)

    # Drop column
    op.execute("""
        ALTER TABLE documents DROP COLUMN IF EXISTS chunk_count;
    """)
