#!/usr/bin/env python3
"""
Apply document audit logging migration (Feature #267)
Adds document_id and metadata columns to audit_log table

Run with: python -m scripts.apply_document_audit_migration
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/agentic_rag"
)


def apply_migration():
    """Apply the document audit logging migration."""

    # Use sync engine for DDL operations
    sync_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    if "postgresql://" not in sync_url:
        sync_url = "postgresql://postgres:postgres@localhost:5432/agentic_rag"

    engine = create_engine(sync_url)

    with engine.connect() as conn:
        print("\n=== Feature #267: Adding document audit columns to audit_log ===\n")

        # Add document_id column
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'audit_log' AND column_name = 'document_id'
                ) THEN
                    ALTER TABLE audit_log ADD COLUMN document_id VARCHAR(36);
                    RAISE NOTICE 'Added document_id column';
                END IF;
            END $$;
        """))
        print("  - document_id column: OK")

        # Add document_name column
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'audit_log' AND column_name = 'document_name'
                ) THEN
                    ALTER TABLE audit_log ADD COLUMN document_name VARCHAR(255);
                    RAISE NOTICE 'Added document_name column';
                END IF;
            END $$;
        """))
        print("  - document_name column: OK")

        # Add file_size column
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'audit_log' AND column_name = 'file_size'
                ) THEN
                    ALTER TABLE audit_log ADD COLUMN file_size INTEGER;
                    RAISE NOTICE 'Added file_size column';
                END IF;
            END $$;
        """))
        print("  - file_size column: OK")

        # Add chunk_count column
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'audit_log' AND column_name = 'chunk_count'
                ) THEN
                    ALTER TABLE audit_log ADD COLUMN chunk_count INTEGER;
                    RAISE NOTICE 'Added chunk_count column';
                END IF;
            END $$;
        """))
        print("  - chunk_count column: OK")

        # Add model_used column
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'audit_log' AND column_name = 'model_used'
                ) THEN
                    ALTER TABLE audit_log ADD COLUMN model_used VARCHAR(100);
                    RAISE NOTICE 'Added model_used column';
                END IF;
            END $$;
        """))
        print("  - model_used column: OK")

        # Add duration_ms column
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'audit_log' AND column_name = 'duration_ms'
                ) THEN
                    ALTER TABLE audit_log ADD COLUMN duration_ms INTEGER;
                    RAISE NOTICE 'Added duration_ms column';
                END IF;
            END $$;
        """))
        print("  - duration_ms column: OK")

        # Create index on document_id
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = 'ix_audit_log_document_id'
                ) THEN
                    CREATE INDEX ix_audit_log_document_id ON audit_log(document_id);
                    RAISE NOTICE 'Created index on document_id';
                END IF;
            END $$;
        """))
        print("  - ix_audit_log_document_id index: OK")

        # Create composite index
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = 'ix_audit_log_document_action'
                ) THEN
                    CREATE INDEX ix_audit_log_document_action ON audit_log(document_id, action, created_at DESC);
                    RAISE NOTICE 'Created composite index';
                END IF;
            END $$;
        """))
        print("  - ix_audit_log_document_action index: OK")

        conn.commit()

    print('\nMigration completed successfully!')

    # Verify new columns
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'audit_log'
            ORDER BY ordinal_position
        """))
        columns = result.fetchall()
        print('\nUpdated audit_log columns:')
        for col in columns:
            print(f'  {col[0]}: {col[1]}')


if __name__ == "__main__":
    apply_migration()
