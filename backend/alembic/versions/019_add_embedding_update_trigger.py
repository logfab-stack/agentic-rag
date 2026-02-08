"""Add trigger to update documents.updated_at on embedding changes

Feature #264: Add trigger to update documents.updated_at on embedding changes

When embeddings are added or deleted for a document, automatically update the
document's updated_at timestamp. This helps track when documents were last
modified (either by adding new embeddings or removing existing ones).

The trigger fires AFTER INSERT OR DELETE on document_embeddings table and updates
the parent document's updated_at to the current timestamp.

Revision ID: 019
Revises: 018
Create Date: 2026-01-31 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '019'
down_revision: Union[str, None] = '018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create trigger to update documents.updated_at on embedding changes."""

    # Step 1: Create the trigger function that updates documents.updated_at
    # This function will be called by the trigger when embeddings are added/deleted
    op.execute("""
        CREATE OR REPLACE FUNCTION update_document_updated_at_on_embedding_change()
        RETURNS TRIGGER AS $$
        DECLARE
            target_document_id VARCHAR(36);
        BEGIN
            -- Get the document_id from either NEW (INSERT) or OLD (DELETE) record
            IF TG_OP = 'INSERT' THEN
                target_document_id := NEW.document_id;
            ELSIF TG_OP = 'DELETE' THEN
                target_document_id := OLD.document_id;
            ELSE
                -- For UPDATE, use NEW (though we only listen for INSERT/DELETE)
                target_document_id := NEW.document_id;
            END IF;

            -- Update the document's updated_at timestamp
            -- Only update if the document exists (defensive check)
            UPDATE documents
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = target_document_id;

            -- Return appropriate record based on operation
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            ELSE
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Step 2: Create the trigger on document_embeddings table
    # The trigger fires AFTER INSERT OR DELETE to update the parent document's timestamp
    op.execute("""
        DO $$
        BEGIN
            -- Check if trigger already exists to make migration idempotent
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger
                WHERE tgname = 'trg_embedding_update_document_updated_at'
            ) THEN
                CREATE TRIGGER trg_embedding_update_document_updated_at
                AFTER INSERT OR DELETE ON document_embeddings
                FOR EACH ROW
                EXECUTE FUNCTION update_document_updated_at_on_embedding_change();

                RAISE NOTICE '[Feature #264] Created trigger trg_embedding_update_document_updated_at on document_embeddings';
            ELSE
                RAISE NOTICE '[Feature #264] Trigger trg_embedding_update_document_updated_at already exists';
            END IF;
        END $$;
    """)

    op.execute("SELECT '[Feature #264] Migration 019 completed: trigger for documents.updated_at on embedding changes'")


def downgrade() -> None:
    """Remove the trigger and function."""

    # Drop the trigger first
    op.execute("""
        DROP TRIGGER IF EXISTS trg_embedding_update_document_updated_at
        ON document_embeddings;
    """)

    # Drop the function
    op.execute("""
        DROP FUNCTION IF EXISTS update_document_updated_at_on_embedding_change();
    """)

    op.execute("SELECT '[Feature #264] Migration 019 downgrade: trigger and function removed'")
