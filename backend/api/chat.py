"""
Chat API endpoints for the Agentic RAG System.

This module handles real-time chat interactions with the AI agent.

Feature #229: Added support for broad/listing queries with high top_k retrieval.
Feature #324: Added rate limiting to prevent API abuse.
Feature #327: Standardized error handling with user-friendly messages.
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid
import logging

# Feature #324: Rate limiting
from core.rate_limit import limiter
from core.config import settings

# Feature #327: Standardized error handling
from core.errors import (
    NotFoundError, ValidationError, ServiceError, handle_exception,
    ErrorCode, raise_api_error, wrap_or_reraise, AppError
)


def utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)

from services.ai_service import get_ai_service
from services.security_service import get_security_service
from core.dependencies import get_conversation_store, get_message_store, get_document_store
from core.store_postgres import ConversationStorePostgres, MessageStorePostgres
from core.store import settings_store
from models.conversation import Message, Conversation, MessageCreate, ConversationCreate

router = APIRouter()
logger = logging.getLogger(__name__)

# Token estimation constants
DEFAULT_CONTEXT_WINDOW_SIZE = 20  # Default number of previous messages
MAX_CONTEXT_TOKENS = 8000  # Maximum tokens for conversation context
CHARS_PER_TOKEN = 4  # Rough estimate: 4 characters per token


def estimate_tokens(text: str) -> int:
    """Estimate token count for text (rough approximation)."""
    return len(text) // CHARS_PER_TOKEN


def truncate_messages_to_token_limit(
    messages: List[dict],
    max_tokens: int = MAX_CONTEXT_TOKENS
) -> List[dict]:
    """
    Truncate oldest messages if total tokens exceed the limit.

    Always keeps the most recent message (the current user query).
    Removes oldest messages first until within budget.

    Args:
        messages: List of message dicts with 'role' and 'content'
        max_tokens: Maximum allowed tokens for context

    Returns:
        List of messages within token budget (most recent preserved)
    """
    if not messages:
        return messages

    # Calculate total tokens
    total_tokens = sum(estimate_tokens(msg.get("content", "")) for msg in messages)

    if total_tokens <= max_tokens:
        return messages

    # Need to truncate - always keep the last message (current query)
    result = list(messages)

    while len(result) > 1 and total_tokens > max_tokens:
        # Remove the oldest message (first in list)
        removed_msg = result.pop(0)
        removed_tokens = estimate_tokens(removed_msg.get("content", ""))
        total_tokens -= removed_tokens
        logger.info(f"Truncated oldest message to fit context window. Removed ~{removed_tokens} tokens.")

    if len(result) < len(messages):
        logger.info(f"Context truncated from {len(messages)} to {len(result)} messages (~{total_tokens} tokens)")

    return result


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    message: str = Field(..., min_length=1, description="User message to send")
    conversation_id: Optional[str] = Field(None, description="Conversation ID to continue")
    model: Optional[str] = Field(None, description="Model to use for this request (e.g., 'gpt-4o' or 'ollama:llama3.2')")
    # Feature #205: Document/collection scoping
    document_ids: Optional[List[str]] = Field(None, description="List of document IDs to scope the search to (overrides collection_id)")
    collection_id: Optional[str] = Field(None, description="Collection ID to scope the search to (all documents in collection)")


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    id: str = Field(..., description="Message ID")
    conversation_id: str = Field(..., description="Conversation ID")
    role: str = Field(default="assistant", description="Message role")
    content: str = Field(..., description="Assistant response content")
    tool_used: Optional[str] = Field(None, description="Tool used for response")
    tool_details: Optional[dict] = Field(None, description="Details about tool execution")
    response_source: Optional[str] = Field(None, description="Source of response: 'rag' (document-based), 'direct' (general knowledge), or 'hybrid'")
    created_at: datetime = Field(..., description="Message timestamp")


def generate_id() -> str:
    """Generate a unique ID."""
    return str(uuid.uuid4())


@router.post("/", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_CHAT)  # Feature #324: Rate limit chat endpoint (default 60/minute)
async def send_chat_message(
    request: Request,  # Required for rate limiting
    chat_request: ChatRequest,
    background_tasks: BackgroundTasks,  # [Feature #242] For deferred embedding
    conversation_store: ConversationStorePostgres = Depends(get_conversation_store),
    message_store: MessageStorePostgres = Depends(get_message_store),
    document_store = Depends(get_document_store)  # Feature #205
):
    """
    Send a message and get an AI response.

    If no conversation_id is provided, creates a new conversation.
    The user message and assistant response are both saved to the conversation.

    Feature #319: Includes prompt injection protection with input sanitization,
    pattern detection, and rate limiting for suspicious queries.
    """
    now = utc_now()
    ai_service = get_ai_service()

    # Feature #319: Security analysis of user input
    security_service = get_security_service()
    # Use conversation_id as user identifier for rate limiting (or generate temp ID)
    user_id = chat_request.conversation_id or f"new_{now.timestamp()}"
    security_analysis = security_service.analyze_query(chat_request.message, user_id=user_id)

    # Check if user is blocked due to excessive suspicious queries
    if security_analysis.get("is_blocked"):
        block_msg = security_analysis.get("message", "Rate limited due to security concerns.")
        logger.warning(f"[Feature #319] Blocked request from {user_id}: {block_msg}")
        # Feature #327: Use standardized error code
        raise_api_error(
            ErrorCode.CHAT_BLOCKED,
            status_code=429,
            detail=block_msg,
            log_message=f"Security block for user {user_id}",
            retry_after=security_analysis.get("block_remaining", 300)
        )

    # Log suspicious queries (but don't block unless rate limited)
    if security_analysis.get("is_suspicious"):
        logger.warning(
            f"[Feature #319] Suspicious query detected from {user_id}: "
            f"risk_score={security_analysis.get('risk_score', 0):.2f}, "
            f"patterns={len(security_analysis.get('detections', []))}"
        )

    # Get or create conversation
    conversation_id = chat_request.conversation_id
    conversation = None
    if conversation_id:
        conversation = await conversation_store.get(conversation_id)

    if not conversation:
        # Create new conversation
        conversation_id = generate_id()
        conversation_data = ConversationCreate(
            title="New Conversation"
        )
        conversation = await conversation_store.create(conversation_data)
        conversation_id = conversation.id
        logger.info(f"Created new conversation: {conversation_id}")

    # Save user message
    user_message_data = MessageCreate(
        conversation_id=conversation_id,
        role="user",
        content=chat_request.message,
        tool_used=None,
        tool_details=None,
        response_source=None
    )
    user_message = await message_store.create(user_message_data)

    # [Feature #242] Generate embedding for user message AFTER the response is returned
    # Using BackgroundTasks ensures the message is committed before embedding is attempted
    # This fixes the FK constraint error caused by embedding insert before message commit
    def embed_message_task():
        try:
            ai_service.embed_user_message(
                message_id=user_message.id,
                conversation_id=conversation_id,
                content=chat_request.message
            )
        except Exception as e:
            logger.warning(f"[Feature #242] Background embedding task failed: {e}")

    background_tasks.add_task(embed_message_task)

    # Get conversation history for context
    conversation_messages = await message_store.get_by_conversation(conversation_id)

    # Get context window size from settings (default 20)
    context_window_size = int(settings_store.get('context_window_size', DEFAULT_CONTEXT_WINDOW_SIZE))

    # Limit to last N messages for context (configurable)
    if len(conversation_messages) > context_window_size:
        # Keep the most recent messages
        conversation_messages = conversation_messages[-context_window_size:]
        logger.info(f"Limited context to last {context_window_size} messages (setting: context_window_size)")

    # Prepare messages for AI
    ai_messages = [
        {"role": msg.role, "content": msg.content}
        for msg in conversation_messages
    ]

    # Apply token limit truncation (removes oldest if too large)
    ai_messages = truncate_messages_to_token_limit(ai_messages)

    # Feature #205: Resolve document_ids from collection_id if needed
    document_ids = chat_request.document_ids
    if not document_ids and chat_request.collection_id:
        # Get all document IDs in this collection using the injected document_store
        all_docs = await document_store.get_all()
        document_ids = [doc.id for doc in all_docs if doc.collection_id == chat_request.collection_id]
        logger.info(f"Resolved collection {chat_request.collection_id} to {len(document_ids)} document(s)")

    # Get AI response
    logger.info(f"Processing chat message for conversation {conversation_id} with model {chat_request.model}, document_ids={document_ids}")
    ai_response = await ai_service.chat(ai_messages, conversation_id, model=chat_request.model, document_ids=document_ids)

    # Save assistant message
    assistant_message_data = MessageCreate(
        conversation_id=conversation_id,
        role="assistant",
        content=ai_response["content"],
        tool_used=ai_response.get("tool_used"),
        tool_details=ai_response.get("tool_details"),
        response_source=ai_response.get("response_source")
    )
    assistant_message = await message_store.create(assistant_message_data)

    # Update conversation timestamp and title if this is the first message
    new_title = conversation.title
    if (conversation.title is None or conversation.title == "New Conversation") and len(conversation_messages) <= 1:
        # Set title to first few words of user message
        new_title = chat_request.message[:50] + ("..." if len(chat_request.message) > 50 else "")

    from models.conversation import ConversationUpdate
    await conversation_store.update(
        conversation_id,
        ConversationUpdate(title=new_title)
    )

    return ChatResponse(
        id=assistant_message.id,
        conversation_id=conversation_id,
        role="assistant",
        content=ai_response["content"],
        tool_used=ai_response.get("tool_used"),
        tool_details=ai_response.get("tool_details"),
        response_source=ai_response.get("response_source"),
        created_at=assistant_message.created_at
    )
