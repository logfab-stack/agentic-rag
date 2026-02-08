"""Add audit_embeddings_delete table and trigger

Feature #252: Cascade delete audit logging

This migration:
1. Creates the audit_embeddings_delete table to log all DELETE operations
   on the document_embeddings table
2. Creates a PostgreSQL trigger that fires AFTER DELETE to log deletions
3. Creates indexes for efficient querying of the audit log

Revision ID: 011
Revises: 010
Create Date: 2026-01-31 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create audit_embeddings_delete table and trigger."""

    # Create the audit table if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'audit_embeddings_delete'
            ) THEN
                CREATE TABLE audit_embeddings_delete (
                    id SERIAL PRIMARY KEY,
                    document_id VARCHAR(255) NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 1,
                    deleted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    source VARCHAR(50) NOT NULL DEFAULT 'trigger',
                    user_action VARCHAR(255),
                    context TEXT,
                    api_endpoint VARCHAR(255)
                );
                RAISE NOTICE '[Feature #252] Created audit_embeddings_delete table';
            ELSE
                RAISE NOTICE '[Feature #252] audit_embeddings_delete table already exists';
            END IF;
        END $$;
    """)

    # Create indexes for efficient querying
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_audit_embeddings_delete_document_id'
            ) THEN
                CREATE INDEX ix_audit_embeddings_delete_document_id
                ON audit_embeddings_delete(document_id);
                RAISE NOTICE '[Feature #252] Created index on document_id';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_audit_embeddings_delete_deleted_at'
            ) THEN
                CREATE INDEX ix_audit_embeddings_delete_deleted_at
                ON audit_embeddings_delete(deleted_at);
                RAISE NOTICE '[Feature #252] Created index on deleted_at';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_audit_embeddings_delete_source'
            ) THEN
                CREATE INDEX ix_audit_embeddings_delete_source
                ON audit_embeddings_delete(source);
                RAISE NOTICE '[Feature #252] Created index on source';
            END IF;
        END $$;
    """)

    # Create the trigger function that logs deletions
    # The function aggregates deletes by document_id in each statement
    op.execute("""
        CREATE OR REPLACE FUNCTION log_embedding_deletion()
        RETURNS TRIGGER AS $$
        DECLARE
            v_context TEXT;
        BEGIN
            -- Try to get some caller info from pg_stat_activity
            BEGIN
                SELECT application_name INTO v_context
                FROM pg_stat_activity
                WHERE pid = pg_backend_pid();
            EXCEPTION WHEN OTHERS THEN
                v_context := 'unknown';
            END;

            -- Insert audit record for each deleted row
            -- The trigger fires once per row in FOR EACH ROW mode
            INSERT INTO audit_embeddings_delete (
                document_id,
                chunk_count,
                deleted_at,
                source,
                user_action,
                context
            ) VALUES (
                OLD.document_id,
                1,
                NOW(),
                'trigger',  -- Will be overwritten by application if called via API
                'PostgreSQL DELETE trigger',
                v_context
            );

            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create the trigger on document_embeddings table
    # Using AFTER DELETE so the row is actually deleted before we log it
    op.execute("""
        DROP TRIGGER IF EXISTS trg_audit_embedding_delete ON document_embeddings;
        CREATE TRIGGER trg_audit_embedding_delete
        AFTER DELETE ON document_embeddings
        FOR EACH ROW
        EXECUTE FUNCTION log_embedding_deletion();
    """)

    # Create a function to aggregate multiple single-row audit entries into summary entries
    # This is called periodically or on-demand to reduce audit log size
    op.execute("""
        CREATE OR REPLACE FUNCTION aggregate_audit_embedding_deletes(
            p_interval INTERVAL DEFAULT INTERVAL '5 minutes'
        )
        RETURNS TABLE(
            aggregated_count INT,
            documents_affected INT
        ) AS $$
        DECLARE
            v_cutoff TIMESTAMP WITH TIME ZONE;
            v_aggregated INT := 0;
            v_documents INT := 0;
        BEGIN
            v_cutoff := NOW() - p_interval;

            -- Aggregate entries older than cutoff by document_id and source
            WITH aggregated AS (
                DELETE FROM audit_embeddings_delete
                WHERE deleted_at < v_cutoff
                  AND source = 'trigger'
                  AND chunk_count = 1
                RETURNING document_id, deleted_at, source, user_action, context
            ),
            grouped AS (
                SELECT
                    document_id,
                    COUNT(*) as total_chunks,
                    MIN(deleted_at) as first_deleted,
                    source,
                    user_action,
                    context
                FROM aggregated
                GROUP BY document_id, source, user_action, context
            )
            INSERT INTO audit_embeddings_delete (
                document_id, chunk_count, deleted_at, source, user_action, context
            )
            SELECT
                document_id,
                total_chunks::INT,
                first_deleted,
                source,
                user_action || ' (aggregated)',
                context
            FROM grouped;

            GET DIAGNOSTICS v_aggregated = ROW_COUNT;

            -- Count distinct documents in the aggregated entries
            SELECT COUNT(DISTINCT document_id) INTO v_documents
            FROM audit_embeddings_delete
            WHERE user_action LIKE '%(aggregated)%';

            RETURN QUERY SELECT v_aggregated, v_documents;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("SELECT '[Feature #252] Migration 011 completed: audit_embeddings_delete table and trigger created'")


def downgrade() -> None:
    """Remove audit_embeddings_delete table and trigger."""

    # Drop the trigger first
    op.execute("DROP TRIGGER IF EXISTS trg_audit_embedding_delete ON document_embeddings")

    # Drop the functions
    op.execute("DROP FUNCTION IF EXISTS log_embedding_deletion()")
    op.execute("DROP FUNCTION IF EXISTS aggregate_audit_embedding_deletes(INTERVAL)")

    # Drop the table
    op.execute("DROP TABLE IF EXISTS audit_embeddings_delete")
