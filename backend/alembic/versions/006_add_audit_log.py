"""Add audit_log table for tracking sensitive operations

Revision ID: 006
Revises: 005
Create Date: 2026-01-30 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create audit_log table for tracking sensitive operations."""

    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('action', sa.String(length=100), nullable=False),  # e.g., "database_reset", "database_reset_cancelled"
        sa.Column('status', sa.String(length=50), nullable=False),  # "initiated", "completed", "cancelled", "failed"
        sa.Column('details', sa.Text(), nullable=True),  # JSON details of what was affected
        sa.Column('ip_address', sa.String(length=45), nullable=True),  # Client IP if available
        sa.Column('user_agent', sa.String(length=500), nullable=True),  # Browser user agent
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create index on action for filtering
    op.create_index('ix_audit_log_action', 'audit_log', ['action'])

    # Create index on created_at for time-based queries
    op.create_index('ix_audit_log_created_at', 'audit_log', ['created_at'])


def downgrade() -> None:
    """Drop audit_log table."""
    op.drop_index('ix_audit_log_created_at', table_name='audit_log')
    op.drop_index('ix_audit_log_action', table_name='audit_log')
    op.drop_table('audit_log')
