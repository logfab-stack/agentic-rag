#!/usr/bin/env python3
"""
Apply NOT NULL constraints for critical columns.

Feature #263: Add NOT NULL constraints for critical columns

This script adds NOT NULL constraints to:
1. document_embeddings.embedding - Vector embeddings must exist
2. document_embeddings.created_at - Timestamp should always be recorded
3. embeddings_backup.embedding - Backup embeddings must contain vectors

Run with: python -m scripts.apply_not_null_constraints
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


def apply_constraints():
    """Apply NOT NULL constraints to critical columns."""

    # Use sync engine for DDL operations
    sync_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    if "postgresql://" not in sync_url:
        sync_url = f"postgresql://postgres:postgres@localhost:5432/agentic_rag"

    engine = create_engine(sync_url, echo=True)

    with engine.connect() as conn:
        # Check current state
        print("\n=== Feature #263: Checking current column state ===\n")

        result = conn.execute(text("""
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'document_embeddings'
            AND column_name IN ('embedding', 'created_at')
        """))

        for row in result:
            print(f"  document_embeddings.{row[0]}: nullable={row[1]}")

        # Check for NULL values
        print("\n=== Checking for NULL values ===\n")

        result = conn.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE embedding IS NULL) as null_embeddings,
                COUNT(*) FILTER (WHERE created_at IS NULL) as null_created_at
            FROM document_embeddings
        """))
        row = result.fetchone()
        print(f"  NULL embeddings: {row[0]}")
        print(f"  NULL created_at: {row[1]}")

        if row[0] > 0:
            print(f"\n  WARNING: Found {row[0]} NULL embeddings - these will be deleted")
            conn.execute(text("DELETE FROM document_embeddings WHERE embedding IS NULL"))
            conn.commit()
            print("  Deleted NULL embedding records")

        if row[1] > 0:
            print(f"\n  WARNING: Found {row[1]} NULL created_at - setting to now()")
            conn.execute(text("UPDATE document_embeddings SET created_at = NOW() WHERE created_at IS NULL"))
            conn.commit()
            print("  Updated NULL created_at records")

        # Apply NOT NULL constraints
        print("\n=== Applying NOT NULL constraints ===\n")

        try:
            # Set timeout for DDL operations (in milliseconds)
            conn.execute(text("SET lock_timeout = '5000ms'"))

            # document_embeddings.embedding
            print("  Adding NOT NULL to document_embeddings.embedding...")
            conn.execute(text("ALTER TABLE document_embeddings ALTER COLUMN embedding SET NOT NULL"))
            conn.commit()
            print("  ✓ document_embeddings.embedding is now NOT NULL")

        except SQLAlchemyError as e:
            print(f"  ✗ Failed to alter embedding: {e}")
            conn.rollback()

        try:
            # document_embeddings.created_at
            print("  Adding NOT NULL to document_embeddings.created_at...")
            conn.execute(text("ALTER TABLE document_embeddings ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP"))
            conn.execute(text("ALTER TABLE document_embeddings ALTER COLUMN created_at SET NOT NULL"))
            conn.commit()
            print("  ✓ document_embeddings.created_at is now NOT NULL")

        except SQLAlchemyError as e:
            print(f"  ✗ Failed to alter created_at: {e}")
            conn.rollback()

        try:
            # embeddings_backup.embedding
            print("  Adding NOT NULL to embeddings_backup.embedding...")
            conn.execute(text("DELETE FROM embeddings_backup WHERE embedding IS NULL"))
            conn.execute(text("ALTER TABLE embeddings_backup ALTER COLUMN embedding SET NOT NULL"))
            conn.commit()
            print("  ✓ embeddings_backup.embedding is now NOT NULL")

        except SQLAlchemyError as e:
            print(f"  ✗ Failed to alter embeddings_backup.embedding: {e}")
            conn.rollback()

        # Verify final state
        print("\n=== Verifying final state ===\n")

        result = conn.execute(text("""
            SELECT table_name, column_name, is_nullable
            FROM information_schema.columns
            WHERE (table_name = 'document_embeddings' AND column_name IN ('embedding', 'created_at'))
               OR (table_name = 'embeddings_backup' AND column_name = 'embedding')
            ORDER BY table_name, column_name
        """))

        all_passed = True
        for row in result:
            status = "✓" if row[2] == "NO" else "✗"
            if row[2] == "YES":
                all_passed = False
            print(f"  {status} {row[0]}.{row[1]}: nullable={row[2]}")

        print("\n" + "=" * 50)
        if all_passed:
            print("Feature #263: All NOT NULL constraints applied successfully!")
        else:
            print("Feature #263: Some constraints could not be applied (lock timeout?)")
            print("Try stopping the backend server and running again.")
        print("=" * 50 + "\n")

        return all_passed


if __name__ == "__main__":
    success = apply_constraints()
    sys.exit(0 if success else 1)
