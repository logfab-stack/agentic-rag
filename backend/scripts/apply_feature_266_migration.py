#!/usr/bin/env python3
"""
Apply Feature #266 migration: Add details JSONB column and retention policy function.

This script applies the database changes for Feature #266:
1. Adds 'details' JSONB column to audit_embeddings_delete table
2. Creates cleanup_audit_retention() function for 30-day retention policy
3. Creates GIN index on details column for efficient JSONB queries
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from sqlalchemy import text


def apply_migration():
    """Apply Feature #266 migration changes."""
    with SessionLocal() as session:
        # Step 1: Check if details column exists
        result = session.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_embeddings_delete'
                AND column_name = 'details'
            )
        """))
        exists = result.scalar()

        if not exists:
            print('[Feature #266] Adding details JSONB column...')
            session.execute(text('ALTER TABLE audit_embeddings_delete ADD COLUMN details JSONB'))
            session.commit()
            print('[Feature #266] Added details column')
        else:
            print('[Feature #266] details column already exists')

        # Step 2: Create or replace retention policy function
        print('[Feature #266] Creating retention policy function...')
        session.execute(text("""
            CREATE OR REPLACE FUNCTION cleanup_audit_retention(
                p_retention_days INTEGER DEFAULT 30
            )
            RETURNS TABLE(
                deleted_count INTEGER,
                oldest_remaining TIMESTAMP WITH TIME ZONE,
                retention_days INTEGER
            ) AS $func$
            DECLARE
                v_cutoff TIMESTAMP WITH TIME ZONE;
                v_deleted INTEGER := 0;
                v_oldest TIMESTAMP WITH TIME ZONE;
            BEGIN
                v_cutoff := NOW() - (p_retention_days || ' days')::INTERVAL;

                DELETE FROM audit_embeddings_delete
                WHERE deleted_at < v_cutoff;

                GET DIAGNOSTICS v_deleted = ROW_COUNT;

                SELECT MIN(deleted_at) INTO v_oldest
                FROM audit_embeddings_delete;

                RETURN QUERY SELECT v_deleted, v_oldest, p_retention_days;
            END;
            $func$ LANGUAGE plpgsql
        """))
        session.commit()
        print('[Feature #266] Created retention policy function')

        # Step 3: Create GIN index if it doesn't exist
        result = session.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_audit_embeddings_delete_details'
            )
        """))
        idx_exists = result.scalar()

        if not idx_exists:
            print('[Feature #266] Creating GIN index on details column...')
            session.execute(text(
                'CREATE INDEX ix_audit_embeddings_delete_details '
                'ON audit_embeddings_delete USING GIN (details)'
            ))
            session.commit()
            print('[Feature #266] Created GIN index')
        else:
            print('[Feature #266] GIN index already exists')

        print('[Feature #266] Migration complete!')


if __name__ == '__main__':
    apply_migration()
