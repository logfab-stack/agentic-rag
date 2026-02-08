#!/usr/bin/env python3
"""
Feature #228: Reset embeddings by dropping indexes and truncating table.

This script executes the SQL operations required for Feature #228:
1. Drop HNSW index
2. Drop IVFFlat index
3. Drop general embedding index
4. Truncate document_embeddings table
"""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from core.database import DATABASE_SYNC_URL


def reset_embeddings():
    """Reset embeddings by dropping indexes and truncating table."""
    print("[Feature #228] Starting embeddings reset...")

    engine = create_engine(DATABASE_SYNC_URL, isolation_level="AUTOCOMMIT")

    operations = [
        ("DROP INDEX IF EXISTS idx_document_embeddings_embedding_hnsw", "Drop HNSW index"),
        ("DROP INDEX IF EXISTS idx_document_embeddings_embedding_ivfflat", "Drop IVFFlat index"),
        ("DROP INDEX IF EXISTS ix_document_embeddings_embedding", "Drop general embedding index"),
        ("TRUNCATE document_embeddings", "Truncate embeddings table"),
    ]

    results = []

    with engine.connect() as conn:
        for sql, description in operations:
            try:
                conn.execute(text(sql))
                print(f"  ✅ {description}")
                results.append((description, "success"))
            except Exception as e:
                print(f"  ❌ {description}: {e}")
                results.append((description, f"error: {e}"))

    engine.dispose()

    print("\n[Feature #228] Reset complete!")
    print(f"  Successful: {sum(1 for _, s in results if s == 'success')}/{len(results)}")

    return results


if __name__ == "__main__":
    reset_embeddings()
