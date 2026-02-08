"""
Conversation models for the Agentic RAG System.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid


def utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class ConversationBase(BaseModel):
    """Base conversation model with common fields."""
    title: Optional[str] = Field(None, max_length=255, description="Conversation title (auto-generated or user-defined)")


class ConversationCreate(ConversationBase):
    """Model for creating a new conversation."""
    pass


class ConversationUpdate(BaseModel):
    """Model for updating an existing conversation."""
    title: Optional[str] = Field(None, min_length=1, max_length=255, description="New conversation title")
    is_archived: Optional[bool] = Field(None, description="Whether the conversation is archived")


class MessageBase(BaseModel):
    """Base message model."""
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class MessageCreate(MessageBase):
    """Model for creating a new message."""
    conversation_id: str = Field(..., description="ID of the conversation")
    tool_used: Optional[str] = Field(None, description="Which tool was invoked")
    tool_details: Optional[dict] = Field(None, description="SQL query, chunks found, etc.")
    response_source: Optional[str] = Field(None, description="Source of response: 'rag' (document-based), 'direct' (general knowledge), or 'hybrid'")


class MessageInDB(MessageBase):
    """Full message model as stored in database."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique message ID")
    conversation_id: str
    tool_used: Optional[str] = None
    tool_details: Optional[dict] = None
    response_source: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

    class Config:
        from_attributes = True


class Message(MessageInDB):
    """Message model for API responses."""
    pass


class ConversationInDB(ConversationBase):
    """Full conversation model as stored in database."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique conversation ID")
    is_archived: bool = Field(default=False, description="Whether the conversation is archived")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Config:
        from_attributes = True


class Conversation(ConversationInDB):
    """Conversation model for API responses."""
    pass


class ConversationWithMessages(Conversation):
    """Conversation with all messages included."""
    messages: List[Message] = Field(default_factory=list)
