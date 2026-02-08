"""Add Telegram integration tables

Feature #307: Telegram database models

This migration creates the telegram_users and telegram_messages tables
for Telegram Bot integration, similar to WhatsApp integration tables.

Tables created:
- telegram_users: Stores Telegram user information (chat_id, username, etc.)
- telegram_messages: Stores message history for monitoring and analytics

Revision ID: 026
Revises: 025
Create Date: 2026-02-02
Feature: #307 - Telegram database models

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic
revision: str = '026'
down_revision: Union[str, None] = '025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create telegram_users and telegram_messages tables (idempotent)."""

    # Use DO block for idempotent table creation
    op.execute("""
        DO $$
        BEGIN
            -- Create telegram_users table if it doesn't exist
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'telegram_users') THEN
                CREATE TABLE telegram_users (
                    id VARCHAR(36) PRIMARY KEY,
                    chat_id BIGINT NOT NULL UNIQUE,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE SET NULL,
                    default_collection_id VARCHAR(36) REFERENCES collections(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    last_message_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                RAISE NOTICE '[Feature #307] Created telegram_users table';
            ELSE
                RAISE NOTICE '[Feature #307] telegram_users table already exists, skipping';
            END IF;

            -- Create telegram_messages table if it doesn't exist
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'telegram_messages') THEN
                CREATE TABLE telegram_messages (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL REFERENCES telegram_users(id) ON DELETE CASCADE,
                    telegram_message_id BIGINT,
                    chat_id BIGINT NOT NULL,
                    direction VARCHAR(10) NOT NULL,
                    content TEXT,
                    media_type VARCHAR(50),
                    media_file_id VARCHAR(255),
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                );
                RAISE NOTICE '[Feature #307] Created telegram_messages table';
            ELSE
                RAISE NOTICE '[Feature #307] telegram_messages table already exists, skipping';
            END IF;
        END
        $$;
    """)

    # Create indexes idempotently (Postgres handles IF NOT EXISTS for indexes)
    op.execute("CREATE INDEX IF NOT EXISTS idx_telegram_users_chat_id ON telegram_users(chat_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_telegram_users_username ON telegram_users(username);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_telegram_users_conversation ON telegram_users(conversation_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_telegram_users_default_collection ON telegram_users(default_collection_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_telegram_users_last_message ON telegram_users(last_message_at);")

    op.execute("CREATE INDEX IF NOT EXISTS idx_telegram_messages_user ON telegram_messages(user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_telegram_messages_chat ON telegram_messages(chat_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_telegram_messages_telegram_msg_id ON telegram_messages(telegram_message_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_telegram_messages_created ON telegram_messages(created_at);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_telegram_messages_direction ON telegram_messages(direction);")

    print("[Feature #307] Telegram tables setup complete (idempotent)")


def downgrade() -> None:
    """Drop telegram_users and telegram_messages tables."""

    # Drop indexes first
    op.drop_index('idx_telegram_messages_direction', table_name='telegram_messages')
    op.drop_index('idx_telegram_messages_created', table_name='telegram_messages')
    op.drop_index('idx_telegram_messages_telegram_msg_id', table_name='telegram_messages')
    op.drop_index('idx_telegram_messages_chat', table_name='telegram_messages')
    op.drop_index('idx_telegram_messages_user', table_name='telegram_messages')

    op.drop_index('idx_telegram_users_last_message', table_name='telegram_users')
    op.drop_index('idx_telegram_users_default_collection', table_name='telegram_users')
    op.drop_index('idx_telegram_users_conversation', table_name='telegram_users')
    op.drop_index('idx_telegram_users_username', table_name='telegram_users')
    op.drop_index('idx_telegram_users_chat_id', table_name='telegram_users')

    # Drop tables (messages first due to FK)
    op.drop_table('telegram_messages')
    op.drop_table('telegram_users')

    print("[Feature #307] Dropped telegram_users and telegram_messages tables")
