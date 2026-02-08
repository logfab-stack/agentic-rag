#!/usr/bin/env python3
"""
Feature #264: Apply trigger to update documents.updated_at on embedding changes

This script creates a PostgreSQL trigger that automatically updates the
documents.updated_at timestamp when embeddings are added or deleted.
"""

import psycopg2
import os

# Database connection
DATABASE_URL = os.getenv(
    "DATABASE_SYNC_URL",
    "postgresql://postgres:postgres@localhost:5432/agentic_rag"
)

def apply_trigger():
    """Create the trigger function and trigger."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    # Step 1: Create the trigger function
    print("[Feature #264] Creating trigger function...")
    cur.execute("""
        CREATE OR REPLACE FUNCTION update_document_updated_at_on_embedding_change()
        RETURNS TRIGGER AS $$
        DECLARE
            target_document_id VARCHAR(36);
        BEGIN
            IF TG_OP = 'INSERT' THEN
                target_document_id := NEW.document_id;
            ELSIF TG_OP = 'DELETE' THEN
                target_document_id := OLD.document_id;
            ELSE
                target_document_id := NEW.document_id;
            END IF;

            UPDATE documents
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = target_document_id;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            ELSE
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)
    print("[Feature #264] Trigger function created!")

    # Step 2: Check if trigger exists and create if not
    cur.execute("""
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_embedding_update_document_updated_at'
    """)
    trigger_exists = cur.fetchone() is not None

    if not trigger_exists:
        print("[Feature #264] Creating trigger...")
        cur.execute("""
            CREATE TRIGGER trg_embedding_update_document_updated_at
            AFTER INSERT OR DELETE ON document_embeddings
            FOR EACH ROW
            EXECUTE FUNCTION update_document_updated_at_on_embedding_change();
        """)
        print("[Feature #264] Trigger created!")
    else:
        print("[Feature #264] Trigger already exists, skipping creation.")

    # Verify trigger exists
    cur.execute("""
        SELECT trigger_name
        FROM information_schema.triggers
        WHERE event_object_table = 'document_embeddings'
        AND trigger_name = 'trg_embedding_update_document_updated_at'
    """)
    result = cur.fetchall()
    print(f"[Feature #264] Verification - Trigger exists: {len(result) > 0}")

    conn.close()
    print("[Feature #264] Migration complete!")


if __name__ == "__main__":
    apply_trigger()
