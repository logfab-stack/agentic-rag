"""
SQLAlchemy models for WhatsApp integration.

These models store WhatsApp user information and message history
for admin monitoring and analytics.
"""

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Index, Boolean
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


class DBWhatsAppUser(Base):
    """
    WhatsApp user model - stores information about users who have interacted via WhatsApp.

    Tracks phone numbers, activity timestamps, message counts, and block status.
    Links to a conversation for maintaining context across messages.
    """
    __tablename__ = "whatsapp_users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    phone_number = Column(String(20), nullable=False, unique=True, index=True)  # e.g., "+1234567890"
    display_name = Column(String(255), nullable=True)  # Optional name if provided
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)  # FK to conversation
    default_collection_id = Column(String(36), ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True)  # Default collection for document uploads
    is_blocked = Column(Boolean, nullable=False, default=False, server_default='false')
    message_count = Column(Integer, nullable=False, default=0, server_default='0')
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    last_active_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now())

    # Relationships
    messages = relationship("DBWhatsAppMessage", back_populates="user", cascade="all, delete-orphan", order_by="DBWhatsAppMessage.created_at")

    # Indexes for common queries
    __table_args__ = (
        Index('idx_whatsapp_users_last_active', 'last_active_at'),
        Index('idx_whatsapp_users_blocked', 'is_blocked'),
        Index('idx_whatsapp_users_conversation', 'conversation_id'),
        Index('idx_whatsapp_users_default_collection', 'default_collection_id'),
    )


class DBWhatsAppMessage(Base):
    """
    WhatsApp message model - stores individual messages for monitoring and history.

    Stores both incoming messages from users and outgoing responses from the system.
    """
    __tablename__ = "whatsapp_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("whatsapp_users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_sid = Column(String(100), nullable=True, unique=True, index=True)  # Twilio MessageSid
    direction = Column(String(10), nullable=False)  # 'inbound' or 'outbound'
    body = Column(Text, nullable=True)  # Message text content
    media_urls = Column(Text, nullable=True)  # JSON array of media URLs
    status = Column(String(20), nullable=True)  # 'received', 'sent', 'delivered', 'read', 'failed'
    error_message = Column(Text, nullable=True)  # Error details if sending failed
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())

    # Relationships
    user = relationship("DBWhatsAppUser", back_populates="messages")

    # Indexes for efficient queries
    __table_args__ = (
        Index('idx_whatsapp_messages_user', 'user_id'),
        Index('idx_whatsapp_messages_created', 'created_at'),
        Index('idx_whatsapp_messages_direction', 'direction'),
    )
