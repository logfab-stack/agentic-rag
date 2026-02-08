"""Fix FK constraint on message_embeddings insert order

Feature #283: The message_embeddings table has a foreign key to messages,
but embeddings are being inserted via BackgroundTasks before the message
transaction is fully committed. This causes FK constraint violations.

This migration makes the FK constraints on message_embeddings DEFERRABLE
INITIALLY DEFERRED, which means the constraint check is deferred until the
end of the transaction rather than being checked immediately on INSERT.

This is the proper database-level solution for the race condition, as an
alternative to the application-level retry mechanism in Feature #242.

With deferred constraints:
- The INSERT happens immediately
- The FK check is deferred to transaction commit time
- By commit time, the parent row (message) should exist

Note: PostgreSQL doesn't support ALTER CONSTRAINT to add DEFERRABLE.
We must DROP and re-CREATE the constraint.

Revision ID: 024
Revises: 023
Create Date: 2026-01-31
Feature: #283 - Fix FK constraint on message_embeddings insert order

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '024'
down_revision: Union[str, None] = '023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make FK constraints on message_embeddings DEFERRABLE INITIALLY DEFERRED."""
    conn = op.get_bind()

    # Check if message_embeddings table exists
    result = conn.execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'message_embeddings'
        )
    """))
    if not result.scalar():
        print("message_embeddings table does not exist, skipping migration")
        return

    # Check if the constraint already has DEFERRABLE
    result = conn.execute(text("""
        SELECT condeferrable, condeferred
        FROM pg_constraint
        WHERE conname = 'message_embeddings_message_id_fkey'
    """))
    row = result.fetchone()
    if row and row[0]:  # condeferrable is True
        print("FK constraint message_embeddings_message_id_fkey is already DEFERRABLE, skipping")
    else:
        # Drop and recreate the message_id FK constraint with DEFERRABLE
        print("Making message_embeddings_message_id_fkey DEFERRABLE INITIALLY DEFERRED")
        op.execute(text("""
            ALTER TABLE message_embeddings
            DROP CONSTRAINT IF EXISTS message_embeddings_message_id_fkey
        """))
        op.execute(text("""
            ALTER TABLE message_embeddings
            ADD CONSTRAINT message_embeddings_message_id_fkey
            FOREIGN KEY (message_id)
            REFERENCES messages(id)
            ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED
        """))

    # Also check conversation_id FK (good practice to be consistent)
    result = conn.execute(text("""
        SELECT condeferrable, condeferred
        FROM pg_constraint
        WHERE conname = 'message_embeddings_conversation_id_fkey'
    """))
    row = result.fetchone()
    if row and row[0]:  # condeferrable is True
        print("FK constraint message_embeddings_conversation_id_fkey is already DEFERRABLE, skipping")
    else:
        print("Making message_embeddings_conversation_id_fkey DEFERRABLE INITIALLY DEFERRED")
        op.execute(text("""
            ALTER TABLE message_embeddings
            DROP CONSTRAINT IF EXISTS message_embeddings_conversation_id_fkey
        """))
        op.execute(text("""
            ALTER TABLE message_embeddings
            ADD CONSTRAINT message_embeddings_conversation_id_fkey
            FOREIGN KEY (conversation_id)
            REFERENCES conversations(id)
            ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED
        """))

    print("Feature #283: FK constraints on message_embeddings are now DEFERRABLE INITIALLY DEFERRED")


def downgrade() -> None:
    """Revert FK constraints to NOT DEFERRABLE (immediate check)."""
    conn = op.get_bind()

    # Check if message_embeddings table exists
    result = conn.execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'message_embeddings'
        )
    """))
    if not result.scalar():
        print("message_embeddings table does not exist, skipping downgrade")
        return

    # Revert message_id FK constraint
    print("Reverting message_embeddings_message_id_fkey to NOT DEFERRABLE")
    op.execute(text("""
        ALTER TABLE message_embeddings
        DROP CONSTRAINT IF EXISTS message_embeddings_message_id_fkey
    """))
    op.execute(text("""
        ALTER TABLE message_embeddings
        ADD CONSTRAINT message_embeddings_message_id_fkey
        FOREIGN KEY (message_id)
        REFERENCES messages(id)
        ON DELETE CASCADE
    """))

    # Revert conversation_id FK constraint
    print("Reverting message_embeddings_conversation_id_fkey to NOT DEFERRABLE")
    op.execute(text("""
        ALTER TABLE message_embeddings
        DROP CONSTRAINT IF EXISTS message_embeddings_conversation_id_fkey
    """))
    op.execute(text("""
        ALTER TABLE message_embeddings
        ADD CONSTRAINT message_embeddings_conversation_id_fkey
        FOREIGN KEY (conversation_id)
        REFERENCES conversations(id)
        ON DELETE CASCADE
    """))

    print("Feature #283 downgrade: FK constraints reverted to NOT DEFERRABLE")
