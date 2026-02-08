"""
Conversation API endpoints for the Agentic RAG System.

Feature #327: Standardized error handling with user-friendly messages.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from pydantic import BaseModel

from models.conversation import (
    Conversation, ConversationCreate, ConversationUpdate,
    ConversationWithMessages, Message, MessageCreate
)
from core.dependencies import get_conversation_store, get_message_store
from core.store_postgres import ConversationStorePostgres, MessageStorePostgres

# Feature #327: Standardized error handling
from core.errors import NotFoundError, handle_exception, ErrorCode

router = APIRouter()


class ConversationListResponse(BaseModel):
    """Paginated list of conversations."""
    conversations: List[Conversation]
    total: int
    page: int
    per_page: int
    total_pages: int


@router.post("/", response_model=Conversation, status_code=201)
async def create_conversation(
    conversation_data: ConversationCreate,
    conversation_store: ConversationStorePostgres = Depends(get_conversation_store)
):
    """Create a new conversation."""
    conversation = await conversation_store.create(conversation_data)
    return Conversation(
        id=conversation.id,
        title=conversation.title,
        is_archived=conversation.is_archived,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at
    )


@router.get("/", response_model=ConversationListResponse)
async def list_conversations(
    search: str = None,
    include_archived: bool = True,
    page: int = 1,
    per_page: int = 20,
    conversation_store: ConversationStorePostgres = Depends(get_conversation_store),
    message_store: MessageStorePostgres = Depends(get_message_store)
):
    """List all conversations, sorted by most recent first (updated_at desc).

    Args:
        search: Optional search query to filter conversations by title or message content
        include_archived: If True, include archived conversations (default: True)
        page: Page number (default: 1)
        per_page: Items per page (default: 20)
    """
    conversations_db = await conversation_store.get_all()
    conversations = [
        Conversation(
            id=conv.id,
            title=conv.title,
            is_archived=conv.is_archived,
            created_at=conv.created_at,
            updated_at=conv.updated_at
        )
        for conv in conversations_db
    ]

    # Filter by archived status if requested
    if not include_archived:
        conversations = [c for c in conversations if not c.is_archived]

    # If search query provided, filter conversations
    if search and search.strip():
        search_lower = search.lower().strip()
        filtered_conversations = []

        for conv in conversations:
            # Check if search matches conversation title
            if conv.title and search_lower in conv.title.lower():
                filtered_conversations.append(conv)
                continue

            # Check if search matches any message content in the conversation
            conversation_messages = await message_store.get_by_conversation(conv.id)
            for msg in conversation_messages:
                if search_lower in msg.content.lower():
                    filtered_conversations.append(conv)
                    break  # Found a match, no need to check more messages

        conversations = filtered_conversations

    # Already sorted by updated_at descending from database
    total = len(conversations)
    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 1

    # Apply pagination
    start = (page - 1) * per_page
    end = start + per_page
    paginated_conversations = conversations[start:end]

    return ConversationListResponse(
        conversations=paginated_conversations,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages
    )


@router.get("/{conversation_id}", response_model=ConversationWithMessages)
async def get_conversation(
    conversation_id: str,
    conversation_store: ConversationStorePostgres = Depends(get_conversation_store),
    message_store: MessageStorePostgres = Depends(get_message_store)
):
    """Get a conversation with all its messages."""
    conversation = await conversation_store.get(conversation_id)
    if not conversation:
        raise NotFoundError("Conversation", conversation_id)

    # Get all messages for this conversation (already sorted by created_at)
    messages_db = await message_store.get_by_conversation(conversation_id)
    conversation_messages = [
        Message(
            id=msg.id,
            conversation_id=msg.conversation_id,
            role=msg.role,
            content=msg.content,
            tool_used=msg.tool_used,
            tool_details=msg.tool_details,
            created_at=msg.created_at
        )
        for msg in messages_db
    ]

    return ConversationWithMessages(
        id=conversation.id,
        title=conversation.title,
        is_archived=conversation.is_archived,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=conversation_messages
    )


async def _do_update_conversation(
    conversation_id: str,
    update_data: ConversationUpdate,
    conversation_store: ConversationStorePostgres
) -> Conversation:
    """Internal function to update a conversation."""
    conversation = await conversation_store.update(conversation_id, update_data)
    if not conversation:
        raise NotFoundError("Conversation", conversation_id)

    return Conversation(
        id=conversation.id,
        title=conversation.title,
        is_archived=conversation.is_archived,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at
    )


@router.put("/{conversation_id}", response_model=Conversation)
async def update_conversation_put(
    conversation_id: str,
    update_data: ConversationUpdate,
    conversation_store: ConversationStorePostgres = Depends(get_conversation_store)
):
    """Update a conversation's title and/or is_archived status (PUT method)."""
    return await _do_update_conversation(conversation_id, update_data, conversation_store)


@router.patch("/{conversation_id}", response_model=Conversation)
async def update_conversation(
    conversation_id: str,
    update_data: ConversationUpdate,
    conversation_store: ConversationStorePostgres = Depends(get_conversation_store)
):
    """Update a conversation's title and/or is_archived status (PATCH method)."""
    return await _do_update_conversation(conversation_id, update_data, conversation_store)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    conversation_store: ConversationStorePostgres = Depends(get_conversation_store)
):
    """Delete a conversation and all its messages."""
    deleted = await conversation_store.delete(conversation_id)
    if not deleted:
        raise NotFoundError("Conversation", conversation_id)

    return None


@router.post("/{conversation_id}/messages", response_model=Message, status_code=201)
async def add_message(
    conversation_id: str,
    message_data: MessageCreate,
    conversation_store: ConversationStorePostgres = Depends(get_conversation_store),
    message_store: MessageStorePostgres = Depends(get_message_store)
):
    """Add a message to a conversation."""
    # Check if conversation exists
    conversation = await conversation_store.get(conversation_id)
    if not conversation:
        raise NotFoundError("Conversation", conversation_id)

    # Create the message (this also updates conversation's updated_at)
    message_db = await message_store.create(message_data)

    return Message(
        id=message_db.id,
        conversation_id=message_db.conversation_id,
        role=message_db.role,
        content=message_db.content,
        tool_used=message_db.tool_used,
        tool_details=message_db.tool_details,
        created_at=message_db.created_at
    )


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: str,
    format: str = "markdown",
    conversation_store: ConversationStorePostgres = Depends(get_conversation_store),
    message_store: MessageStorePostgres = Depends(get_message_store)
):
    """Export a conversation as Markdown or JSON.

    Args:
        conversation_id: The ID of the conversation to export
        format: Export format - 'markdown' (default) or 'json'

    Returns:
        Markdown: Text content with title as H1, messages with role prefixes
        JSON: Full conversation object with all metadata
    """
    from fastapi.responses import PlainTextResponse, JSONResponse

    # Get conversation
    conversation = await conversation_store.get(conversation_id)
    if not conversation:
        raise NotFoundError("Conversation", conversation_id)

    # Get all messages for this conversation
    messages_db = await message_store.get_by_conversation(conversation_id)

    if format.lower() == "json":
        # Full JSON export with all metadata
        export_data = {
            "id": conversation.id,
            "title": conversation.title or "Untitled Conversation",
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "is_archived": getattr(conversation, 'is_archived', False),
            "messages": [
                {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content,
                    "tool_used": msg.tool_used,
                    "tool_details": msg.tool_details,
                    "response_source": getattr(msg, 'response_source', None),
                    "created_at": msg.created_at.isoformat()
                }
                for msg in messages_db
            ]
        }
        return JSONResponse(
            content=export_data,
            headers={
                "Content-Disposition": f'attachment; filename="conversation-{conversation_id[:8]}.json"'
            }
        )

    else:
        # Markdown export
        title = conversation.title or "Untitled Conversation"
        created = conversation.created_at.strftime("%Y-%m-%d %H:%M UTC")

        lines = [
            f"# {title}",
            "",
            f"*Exported: {created}*",
            "",
            "---",
            ""
        ]

        # Track sources for footnotes
        sources = []
        source_counter = 1

        for msg in messages_db:
            role_label = "**User:**" if msg.role == "user" else "**Assistant:**"
            lines.append(role_label)
            lines.append("")
            lines.append(msg.content)
            lines.append("")

            # Check for tool details with sources (RAG citations)
            if msg.tool_details:
                tool_details = msg.tool_details
                if isinstance(tool_details, dict) and 'chunks' in tool_details:
                    for chunk in tool_details['chunks']:
                        if isinstance(chunk, dict) and 'document_title' in chunk:
                            source = chunk.get('document_title', 'Unknown Document')
                            if source not in [s[1] for s in sources]:
                                sources.append((source_counter, source))
                                source_counter += 1

            lines.append("")

        # Add footnotes for sources if any
        if sources:
            lines.append("---")
            lines.append("")
            lines.append("## Sources")
            lines.append("")
            for num, source in sources:
                lines.append(f"[{num}]: {source}")
            lines.append("")

        markdown_content = "\n".join(lines)

        return PlainTextResponse(
            content=markdown_content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="conversation-{conversation_id[:8]}.md"'
            }
        )
