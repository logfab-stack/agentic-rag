"""Add response_feedback table for response-level feedback

Feature #350: Response Feedback System (Thumbs Up/Down)

Stores user ratings on AI responses along with full context:
query, response text, retrieved chunks, tool used, and model info.

Revision ID: 028
Revises: 027
Create Date: 2026-02-07
Feature: #350 - Response Feedback System

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '028'
down_revision: Union[str, None] = '027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'response_feedback',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('message_id', sa.String(36), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('response', sa.Text(), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('retrieved_chunks', sa.JSON(), nullable=True),
        sa.Column('embedding_model', sa.String(100), nullable=True),
        sa.Column('tool_used', sa.String(100), nullable=True),
        sa.Column('response_source', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id', name='uq_response_feedback_message'),
    )

    op.create_index('idx_response_feedback_message', 'response_feedback', ['message_id'])
    op.create_index('idx_response_feedback_conversation', 'response_feedback', ['conversation_id'])
    op.create_index('idx_response_feedback_rating', 'response_feedback', ['rating'])
    op.create_index('idx_response_feedback_created', 'response_feedback', ['created_at'])


def downgrade() -> None:
    op.drop_index('idx_response_feedback_created', table_name='response_feedback')
    op.drop_index('idx_response_feedback_rating', table_name='response_feedback')
    op.drop_index('idx_response_feedback_conversation', table_name='response_feedback')
    op.drop_index('idx_response_feedback_message', table_name='response_feedback')
    op.drop_table('response_feedback')
