"""Add llm_model column to response_cache table

Bug fix: Response cache was serving stale responses across LLM model changes.
When switching from e.g. Gemma to GPT-4o, cached Gemma responses were returned
because the cache only filtered by embedding_model, not by LLM model.

Adds llm_model column so cache lookups discriminate by which LLM generated
the cached response. Existing entries are truncated (they lack llm_model).

Revision ID: 032
Revises: 031
Create Date: 2026-02-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '032'
down_revision: Union[str, None] = '031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Truncate existing cache entries - they lack llm_model info
    op.execute("TRUNCATE TABLE response_cache")

    # Add llm_model column
    op.execute(
        "ALTER TABLE response_cache ADD COLUMN llm_model VARCHAR(100)"
    )

    # Add index for faster lookups
    op.create_index(
        'idx_response_cache_llm_model',
        'response_cache',
        ['llm_model']
    )


def downgrade() -> None:
    op.drop_index('idx_response_cache_llm_model', table_name='response_cache')
    op.execute("ALTER TABLE response_cache DROP COLUMN llm_model")
