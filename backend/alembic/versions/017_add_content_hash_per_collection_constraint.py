"""Add unique constraint on content_hash per collection

Revision ID: 017
Revises: 016
Create Date: 2026-01-31

Feature #262: Change content_hash uniqueness from global to per-collection.
This allows the same document to be uploaded to different collections while
still preventing duplicates within the same collection.

The old global constraint: ix_documents_content_hash (content_hash) UNIQUE
The new constraint: ix_documents_content_hash_collection (content_hash, collection_id) UNIQUE

Note: NULL collection_id values are handled specially in PostgreSQL unique constraints.
Multiple rows with (same_hash, NULL) would normally all be allowed (since NULL != NULL).
We create a partial unique index for the NULL case to enforce uniqueness for
uncategorized documents as well.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '017'
down_revision: Union[str, None] = '016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change content_hash unique constraint from global to per-collection."""

    # Step 1: Drop the existing global unique index on content_hash (if it exists)
    op.execute('''
        DROP INDEX IF EXISTS ix_documents_content_hash
    ''')

    # Step 2: Create new composite unique index on (content_hash, collection_id)
    # This allows the same document in different collections
    op.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS ix_documents_content_hash_collection
        ON documents (content_hash, collection_id)
    ''')

    # Step 3: Create a partial unique index for NULL collection_id (uncategorized documents)
    # Without this, multiple documents with the same content_hash and NULL collection_id
    # would be allowed (since NULL != NULL in SQL comparisons)
    op.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS ix_documents_content_hash_null_collection
        ON documents (content_hash)
        WHERE collection_id IS NULL
    ''')


def downgrade() -> None:
    """Restore global content_hash unique constraint."""

    # Step 1: Drop the partial index for NULL collection_id
    op.execute('DROP INDEX IF EXISTS ix_documents_content_hash_null_collection')

    # Step 2: Drop the composite unique index
    op.execute('DROP INDEX IF EXISTS ix_documents_content_hash_collection')

    # Step 3: Restore the original global unique index
    # WARNING: This will fail if there are duplicate content_hashes across collections!
    op.execute('''
        CREATE UNIQUE INDEX ix_documents_content_hash
        ON documents (content_hash)
    ''')
