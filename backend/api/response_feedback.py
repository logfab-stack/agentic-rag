"""
Response Feedback API endpoints (Feature #350).

Provides endpoints to submit and retrieve user feedback (thumbs up/down)
on AI responses. Stores the full context: query, response, retrieved chunks,
and metadata to enable RAG quality analysis.
"""

import logging
from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, func, case, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.response_feedback import ResponseFeedback
from models.db_models import DBMessage, DBConversation
from core.database import get_db
from core.store import settings_store

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Pydantic models ---

class ResponseFeedbackCreate(BaseModel):
    """Request model for submitting response feedback."""
    message_id: str = Field(..., min_length=1, description="ID of the assistant message being rated")
    conversation_id: str = Field(..., min_length=1, description="Conversation ID")
    rating: int = Field(..., ge=-1, le=1, description="+1 for thumbs up, -1 for thumbs down")


class ResponseFeedbackResponse(BaseModel):
    """Response model for response feedback."""
    id: int
    message_id: str
    conversation_id: str
    query: str
    response: str
    rating: int
    retrieved_chunks: Optional[list] = None
    embedding_model: Optional[str] = None
    tool_used: Optional[str] = None
    response_source: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class ResponseFeedbackStats(BaseModel):
    """Aggregated response feedback statistics."""
    total_feedback: int
    positive_count: int
    negative_count: int
    positive_percentage: float
    negative_percentage: float
    by_source: dict  # {"rag": {"total": N, "positive": N}, "direct": {...}, "hybrid": {...}}
    by_tool: dict    # {"vector_search": {"total": N, "positive": N}, ...}
    recent_negative: List[ResponseFeedbackResponse]  # Last 5 negative ratings for review


# --- Helper ---

def _to_response(fb: ResponseFeedback) -> ResponseFeedbackResponse:
    return ResponseFeedbackResponse(
        id=fb.id,
        message_id=fb.message_id,
        conversation_id=fb.conversation_id,
        query=fb.query,
        response=fb.response[:500] if fb.response else "",
        rating=fb.rating,
        retrieved_chunks=fb.retrieved_chunks,
        embedding_model=fb.embedding_model,
        tool_used=fb.tool_used,
        response_source=fb.response_source,
        created_at=fb.created_at.isoformat() if fb.created_at else "",
    )


# --- Endpoints ---

@router.post("/", response_model=ResponseFeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_response_feedback(
    data: ResponseFeedbackCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit feedback (thumbs up/down) on an AI response.

    Looks up the assistant message and its preceding user message to capture
    the full query/response context. Upserts if feedback already exists for
    this message.
    """
    if data.rating not in (-1, 1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rating must be +1 (thumbs up) or -1 (thumbs down)",
        )

    # Fetch the assistant message
    msg_result = await db.execute(
        select(DBMessage).where(DBMessage.id == data.message_id)
    )
    assistant_msg = msg_result.scalar_one_or_none()

    if not assistant_msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Message '{data.message_id}' not found",
        )

    if assistant_msg.role != "assistant":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feedback can only be given on assistant messages",
        )

    # Find the preceding user message (the query)
    user_msg_result = await db.execute(
        select(DBMessage)
        .where(
            DBMessage.conversation_id == data.conversation_id,
            DBMessage.role == "user",
            DBMessage.created_at < assistant_msg.created_at,
        )
        .order_by(DBMessage.created_at.desc())
        .limit(1)
    )
    user_msg = user_msg_result.scalar_one_or_none()
    query_text = user_msg.content if user_msg else ""

    # Extract retrieved chunks from tool_details
    retrieved_chunks = None
    if assistant_msg.tool_details:
        tool_result = assistant_msg.tool_details.get("tool_result", {})
        if isinstance(tool_result, dict):
            results = tool_result.get("results", [])
            if results and isinstance(results, list):
                retrieved_chunks = [
                    {
                        "chunk_id": c.get("chunk_id"),
                        "text": (c.get("text", "") or "")[:200],
                        "score": c.get("score") or c.get("similarity"),
                        "document_title": c.get("document_title"),
                    }
                    for c in results[:10]  # Cap at 10 chunks
                ]

    # Get current embedding model
    embedding_model = settings_store.get("embedding_model", "text-embedding-3-small")

    # Check for existing feedback (upsert)
    existing_result = await db.execute(
        select(ResponseFeedback).where(ResponseFeedback.message_id == data.message_id)
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.rating = data.rating
        await db.commit()
        await db.refresh(existing)
        logger.info(f"[Feature #350] Updated response feedback for message {data.message_id}: {data.rating}")
        return _to_response(existing)

    # Create new feedback
    fb = ResponseFeedback(
        message_id=data.message_id,
        conversation_id=data.conversation_id,
        query=query_text,
        response=assistant_msg.content,
        rating=data.rating,
        retrieved_chunks=retrieved_chunks,
        embedding_model=embedding_model,
        tool_used=assistant_msg.tool_used,
        response_source=assistant_msg.response_source,
    )

    db.add(fb)
    await db.commit()
    await db.refresh(fb)

    logger.info(f"[Feature #350] Created response feedback for message {data.message_id}: {data.rating}")
    return _to_response(fb)


@router.get("/{message_id}", response_model=Optional[ResponseFeedbackResponse])
async def get_response_feedback(
    message_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get feedback for a specific message, or null if none exists."""
    result = await db.execute(
        select(ResponseFeedback).where(ResponseFeedback.message_id == message_id)
    )
    fb = result.scalar_one_or_none()

    if not fb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No feedback for message '{message_id}'",
        )

    return _to_response(fb)


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_response_feedback(
    message_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete feedback for a specific message."""
    result = await db.execute(
        select(ResponseFeedback).where(ResponseFeedback.message_id == message_id)
    )
    fb = result.scalar_one_or_none()

    if not fb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No feedback for message '{message_id}'",
        )

    await db.execute(
        delete(ResponseFeedback).where(ResponseFeedback.message_id == message_id)
    )
    await db.commit()
    logger.info(f"[Feature #350] Deleted response feedback for message {message_id}")
    return None


@router.get("/stats/summary", response_model=ResponseFeedbackStats)
async def get_response_feedback_stats(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregated response feedback statistics.

    Returns total counts, percentages, breakdowns by source/tool,
    and the 5 most recent negative ratings for review.
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Total counts
    totals_result = await db.execute(
        select(
            func.count(ResponseFeedback.id).label("total"),
            func.sum(case((ResponseFeedback.rating > 0, 1), else_=0)).label("positive"),
            func.sum(case((ResponseFeedback.rating < 0, 1), else_=0)).label("negative"),
        ).where(ResponseFeedback.created_at >= since)
    )
    totals = totals_result.first()

    total = totals.total or 0
    positive = int(totals.positive or 0)
    negative = int(totals.negative or 0)

    pos_pct = round((positive / total * 100), 1) if total > 0 else 0.0
    neg_pct = round((negative / total * 100), 1) if total > 0 else 0.0

    # Breakdown by response_source
    source_result = await db.execute(
        select(
            ResponseFeedback.response_source,
            func.count(ResponseFeedback.id).label("total"),
            func.sum(case((ResponseFeedback.rating > 0, 1), else_=0)).label("positive"),
            func.sum(case((ResponseFeedback.rating < 0, 1), else_=0)).label("negative"),
        )
        .where(ResponseFeedback.created_at >= since)
        .group_by(ResponseFeedback.response_source)
    )
    by_source = {}
    for row in source_result.all():
        key = row.response_source or "unknown"
        by_source[key] = {
            "total": row.total or 0,
            "positive": int(row.positive or 0),
            "negative": int(row.negative or 0),
        }

    # Breakdown by tool_used
    tool_result = await db.execute(
        select(
            ResponseFeedback.tool_used,
            func.count(ResponseFeedback.id).label("total"),
            func.sum(case((ResponseFeedback.rating > 0, 1), else_=0)).label("positive"),
            func.sum(case((ResponseFeedback.rating < 0, 1), else_=0)).label("negative"),
        )
        .where(ResponseFeedback.created_at >= since)
        .group_by(ResponseFeedback.tool_used)
    )
    by_tool = {}
    for row in tool_result.all():
        key = row.tool_used or "none"
        by_tool[key] = {
            "total": row.total or 0,
            "positive": int(row.positive or 0),
            "negative": int(row.negative or 0),
        }

    # Recent negative feedback for review
    neg_result = await db.execute(
        select(ResponseFeedback)
        .where(ResponseFeedback.rating < 0, ResponseFeedback.created_at >= since)
        .order_by(ResponseFeedback.created_at.desc())
        .limit(5)
    )
    recent_negative = [_to_response(fb) for fb in neg_result.scalars().all()]

    return ResponseFeedbackStats(
        total_feedback=total,
        positive_count=positive,
        negative_count=negative,
        positive_percentage=pos_pct,
        negative_percentage=neg_pct,
        by_source=by_source,
        by_tool=by_tool,
        recent_negative=recent_negative,
    )
