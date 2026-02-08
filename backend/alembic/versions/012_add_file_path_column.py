"""Add file_path column to documents table

Feature #253: Store file path in documents table

This migration:
1. Adds a 'file_path' column to the documents table (VARCHAR 1000)
2. Backfills file_path from the existing 'url' column
3. For documents with url=NULL, attempts to locate the file by document ID

Revision ID: 012
Revises: 011
Create Date: 2026-01-31 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
import os
from pathlib import Path

# revision identifiers, used by Alembic.
revision: str = '012'
down_revision: Union[str, None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Upload directory path for backfill
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"


def upgrade() -> None:
    """Add file_path column and backfill from url/file discovery."""

    # Step 1: Add file_path column if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'file_path'
            ) THEN
                ALTER TABLE documents ADD COLUMN file_path VARCHAR(1000);
                RAISE NOTICE '[Feature #253] Added file_path column to documents table';
            ELSE
                RAISE NOTICE '[Feature #253] file_path column already exists';
            END IF;
        END $$;
    """)

    # Step 2: Copy url values to file_path where url is not null
    op.execute("""
        UPDATE documents
        SET file_path = url
        WHERE url IS NOT NULL AND file_path IS NULL;
    """)

    # Get connection for more complex operations
    conn = op.get_bind()

    # Step 3: For documents with url=NULL, try to locate the file
    result = conn.execute(text("""
        SELECT id, original_filename, mime_type
        FROM documents
        WHERE file_path IS NULL
    """))

    documents_to_update = list(result)
    updated_count = 0

    for doc_id, original_filename, mime_type in documents_to_update:
        # Try common file extensions based on mime type
        extension_map = {
            "application/pdf": "pdf",
            "text/plain": "txt",
            "text/csv": "csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
            "application/vnd.ms-excel": "xls",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
            "application/json": "json",
            "text/markdown": "md",
        }

        file_path = None

        # Method 1: Try {doc_id}.{extension}
        if mime_type in extension_map:
            ext = extension_map[mime_type]
            potential_path = UPLOAD_DIR / f"{doc_id}.{ext}"
            if potential_path.exists():
                file_path = str(potential_path)

        # Method 2: Search uploads directory for file starting with doc_id
        if not file_path:
            if UPLOAD_DIR.exists():
                for uploaded_file in UPLOAD_DIR.iterdir():
                    if uploaded_file.is_file() and uploaded_file.stem == doc_id:
                        file_path = str(uploaded_file)
                        break

        # Method 3: Check if original_filename is a UUID and search by that
        if not file_path and original_filename:
            # Original filename might be a UUID-based name like "abc123.pdf"
            potential_path = UPLOAD_DIR / original_filename
            if potential_path.exists():
                file_path = str(potential_path)

        # Update the document if we found a file
        if file_path:
            conn.execute(text("""
                UPDATE documents SET file_path = :file_path WHERE id = :doc_id
            """), {"file_path": file_path, "doc_id": doc_id})
            updated_count += 1

    print(f"[Feature #253] Backfilled file_path for {updated_count} documents")

    # Step 4: Create index on file_path for efficient lookups
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_documents_file_path'
            ) THEN
                CREATE INDEX ix_documents_file_path ON documents(file_path);
                RAISE NOTICE '[Feature #253] Created index on file_path';
            END IF;
        END $$;
    """)

    op.execute("SELECT '[Feature #253] Migration 012 completed: file_path column added and backfilled'")


def downgrade() -> None:
    """Remove file_path column."""

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_documents_file_path'
            ) THEN
                DROP INDEX ix_documents_file_path;
            END IF;
        END $$;
    """)

    op.execute("""
        ALTER TABLE documents DROP COLUMN IF EXISTS file_path;
    """)
