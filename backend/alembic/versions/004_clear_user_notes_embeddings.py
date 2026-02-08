"""Clear user_notes embeddings to fix dimension mismatch

Revision ID: 004
Revises: 003
Create Date: 2026-01-29 22:30:00.000000

The user_notes table has embeddings with 1024 dimensions, but the system
now uses qwen3-embedding:8b which produces 4096 dimensions. This causes
SQL errors when querying user notes with cosine similarity.

The column type is already vector (no dimension constraint), but existing
data is incompatible. This migration clears existing embeddings so they
can be re-generated with the correct dimensions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Clear all user_notes embeddings to fix dimension mismatch.

    The existing embeddings (1024 dimensions) are incompatible with
    the current embedding model (4096 dimensions). Setting them to
    NULL allows the system to re-embed notes with the correct dimensions
    when needed.

    Note: User notes content is preserved - only the embeddings are cleared.
    Notes will be re-embedded automatically when vector search is performed.
    """
    # Clear existing embeddings (they have incompatible dimensions)
    op.execute("""
        UPDATE user_notes
        SET embedding = NULL
        WHERE embedding IS NOT NULL
    """)


def downgrade() -> None:
    """No downgrade possible - embeddings must be regenerated manually.

    The old embeddings cannot be restored. To regenerate embeddings,
    use the Admin Maintenance page's "Re-embed Documents" feature.
    """
    pass
