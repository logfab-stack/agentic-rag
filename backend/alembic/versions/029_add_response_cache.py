"""Add response_cache table for semantic response caching

Feature #352: Semantic Response Cache

Stores AI responses keyed by query embedding similarity, allowing
near-instant responses for semantically similar repeated questions.
Uses pgvector for cosine similarity matching on cached query embeddings.

Revision ID: 029
Revises: 028
Create Date: 2026-02-07
Feature: #352 - Semantic Response Cache

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '029'
down_revision: Union[str, None] = '028'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'response_cache',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('query_text', sa.Text(), nullable=False),
        # query_embedding is added via raw SQL below (pgvector column, dimension varies by model)
        sa.Column('response_text', sa.Text(), nullable=False),
        sa.Column('tool_used', sa.String(100), nullable=True),
        sa.Column('tool_details', sa.JSON(), nullable=True),
        sa.Column('response_source', sa.String(20), nullable=True),
        sa.Column('embedding_model', sa.String(100), nullable=True),
        sa.Column('document_ids', sa.JSON(), nullable=True),
        sa.Column('hit_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_hit_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # Add pgvector column with raw SQL (no fixed dimension - we use raw SQL for queries)
    op.execute("ALTER TABLE response_cache ADD COLUMN query_embedding vector")

    op.create_index('idx_response_cache_created', 'response_cache', ['created_at'])
    op.create_index('idx_response_cache_expires', 'response_cache', ['expires_at'])
    op.create_index('idx_response_cache_embedding_model', 'response_cache', ['embedding_model'])


def downgrade() -> None:
    op.drop_index('idx_response_cache_embedding_model', table_name='response_cache')
    op.drop_index('idx_response_cache_expires', table_name='response_cache')
    op.drop_index('idx_response_cache_created', table_name='response_cache')
    op.drop_table('response_cache')
