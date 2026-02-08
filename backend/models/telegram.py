"""
SQLAlchemy models for Telegram Bot integration.

Feature #307: Telegram database models

These models store Telegram user information and message history
for admin monitoring and analytics, similar to WhatsApp models.
"""

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Index, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone
import uuid

from .db_models import Base


def utc_now():
    """Return current UTC time."""
    return datetime.now(timezone.utc)


def generate_uuid():
    """Generate a new UUID string."""
    return str(uuid.uuid4())


class DBTelegramUser(Base):
    """
    Telegram user model - stores information about users who have interacted via Telegram Bot.

    Tracks chat_id (unique Telegram user identifier), usernames, activity timestamps.
    Links to a conversation for maintaining context across messages.
    Links to a default collection for document uploads via bot.
    """
    __tablename__ = "telegram_users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # Telegram chat_id is a 64-bit integer, unique per user
    chat_id = Column(BigInteger, nullable=False, unique=True, index=True)
    username = Column(String(255), nullable=True, index=True)  # Telegram @username (optional)
    first_name = Column(String(255), nullable=True)  # User's first name
    last_name = Column(String(255), nullable=True)  # User's last name
    # FK to conversation for maintaining chat context
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    # Default collection for document uploads via Telegram
    default_collection_id = Column(String(36), ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    last_message_at = Column(DateTime(timezone=True), nullable=True, default=utc_now, server_default=func.now())

    # Relationships
    messages = relationship("DBTelegramMessage", back_populates="user", cascade="all, delete-orphan", order_by="DBTelegramMessage.created_at")

    # Indexes for common queries
    __table_args__ = (
        Index('idx_telegram_users_chat_id', 'chat_id'),
        Index('idx_telegram_users_username', 'username'),
        Index('idx_telegram_users_conversation', 'conversation_id'),
        Index('idx_telegram_users_default_collection', 'default_collection_id'),
        Index('idx_telegram_users_last_message', 'last_message_at'),
    )


class DBTelegramMessage(Base):
    """
    Telegram message model - stores individual messages for monitoring and history.

    Stores both incoming messages from users and outgoing responses from the bot.
    """
    __tablename__ = "telegram_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # Foreign key to telegram_users table
    user_id = Column(String(36), ForeignKey("telegram_users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Telegram's unique message_id within the chat
    telegram_message_id = Column(BigInteger, nullable=True, index=True)
    # Chat ID for quick lookups (denormalized for efficiency)
    chat_id = Column(BigInteger, nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # 'inbound' or 'outbound'
    content = Column(Text, nullable=True)  # Message text content
    # Media handling
    media_type = Column(String(50), nullable=True)  # 'photo', 'document', 'voice', 'video', 'audio', 'sticker', etc.
    media_file_id = Column(String(255), nullable=True)  # Telegram's file_id for media
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())

    # Relationships
    user = relationship("DBTelegramUser", back_populates="messages")

    # Indexes for efficient queries
    __table_args__ = (
        Index('idx_telegram_messages_user', 'user_id'),
        Index('idx_telegram_messages_chat', 'chat_id'),
        Index('idx_telegram_messages_telegram_msg_id', 'telegram_message_id'),
        Index('idx_telegram_messages_created', 'created_at'),
        Index('idx_telegram_messages_direction', 'direction'),
    )
