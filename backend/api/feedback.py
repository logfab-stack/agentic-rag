"""
Chunk Feedback API endpoints for the Agentic RAG System.

Provides endpoints to submit, retrieve, and manage user feedback (thumbs up/down)
on retrieved chunks for a given query. This enables learning from user feedback
to improve retrieval quality.
"""

import os
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete, text, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
import httpx
from openai import OpenAI

from models.chunk_feedback import ChunkFeedback
from models.embedding import DocumentEmbedding
from models.db_models import DBDocument
from core.database import get_db
from core.store import settings_store

logger = logging.getLogger(__name__)

router = APIRouter()

# Ollama settings
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


# Pydantic models for request/response
class FeedbackCreate(BaseModel):
    """Request model for creating chunk feedback."""
    chunk_id: str = Field(..., min_length=1, description="ID of the chunk receiving feedback")
    query_text: str = Field(..., min_length=1, description="The query that was performed")
    feedback: int = Field(..., ge=-1, le=1, description="+1 for thumbs up, -1 for thumbs down")


class FeedbackResponse(BaseModel):
    """Response model for chunk feedback."""
    id: int
    chunk_id: str
    query_text: str
    feedback: int
    created_at: str

    class Config:
        from_attributes = True


class ChunkFeedbackStats(BaseModel):
    """Aggregated feedback stats for a chunk."""
    chunk_id: str
    total_feedback: int
    positive_count: int
    negative_count: int
    net_score: int
    feedbacks: List[FeedbackResponse]


async def generate_query_embedding(text: str) -> Optional[List[float]]:
    """
    Generate embedding for query text using the configured embedding model.

    Args:
        text: The query text to embed

    Returns:
        Embedding vector as list of floats, or None if generation fails
    """
    embedding_model = settings_store.get('embedding_model', 'text-embedding-3-small')

    try:
        if embedding_model.startswith("ollama:"):
            # Ollama embedding
            ollama_model_name = embedding_model.replace("ollama:", "")
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/embeddings",
                    json={"model": ollama_model_name, "prompt": text}
                )
                if response.status_code == 200:
                    data = response.json()
                    embedding = data.get("embedding", [])
                    if embedding:
                        logger.info(f"Generated Ollama embedding ({len(embedding)} dims) for query")
                        return embedding
                else:
                    logger.warning(f"Ollama embedding request failed: {response.status_code}")
        else:
            # OpenAI embedding
            api_key = settings_store.get('openai_api_key')
            if not api_key or len(api_key) < 10:
                logger.warning("OpenAI API key not configured, cannot generate embedding")
                return None

            client = OpenAI(api_key=api_key)
            response = client.embeddings.create(
                model=embedding_model,
                input=[text]
            )

            if response.data and len(response.data) > 0:
                embedding = response.data[0].embedding
                logger.info(f"Generated OpenAI embedding ({len(embedding)} dims) for query")
                return embedding

    except Exception as e:
        logger.error(f"Error generating embedding for query: {e}")

    return None


def chunk_feedback_to_response(feedback: ChunkFeedback) -> FeedbackResponse:
    """Convert SQLAlchemy ChunkFeedback to Pydantic FeedbackResponse."""
    return FeedbackResponse(
        id=feedback.id,
        chunk_id=feedback.chunk_id,
        query_text=feedback.query_text,
        feedback=feedback.feedback,
        created_at=feedback.created_at.isoformat() if feedback.created_at else ""
    )


@router.post("/", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    feedback_data: FeedbackCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Submit feedback for a chunk.

    Creates or updates feedback for a chunk+query combination.
    If feedback for the same chunk_id + query_text already exists, the feedback value is updated.

    Args:
        feedback_data: The feedback to submit (chunk_id, query_text, feedback)

    Returns:
        The created or updated feedback record
    """
    # Validate feedback value
    if feedback_data.feedback not in (-1, 1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feedback must be +1 (thumbs up) or -1 (thumbs down)"
        )

    # Generate embedding for the query
    query_embedding = await generate_query_embedding(feedback_data.query_text)

    if query_embedding is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not generate embedding for query. Check embedding model configuration."
        )

    # Check if feedback already exists for this chunk+query combination
    existing_result = await db.execute(
        select(ChunkFeedback).where(
            ChunkFeedback.chunk_id == feedback_data.chunk_id,
            ChunkFeedback.query_text == feedback_data.query_text
        )
    )
    existing_feedback = existing_result.scalar_one_or_none()

    if existing_feedback:
        # Update existing feedback (upsert behavior)
        existing_feedback.feedback = feedback_data.feedback
        existing_feedback.query_embedding = query_embedding
        await db.commit()
        await db.refresh(existing_feedback)
        logger.info(f"Updated feedback for chunk {feedback_data.chunk_id}: {feedback_data.feedback}")
        return chunk_feedback_to_response(existing_feedback)
    else:
        # Create new feedback
        db_feedback = ChunkFeedback(
            chunk_id=feedback_data.chunk_id,
            query_text=feedback_data.query_text,
            query_embedding=query_embedding,
            feedback=feedback_data.feedback
        )

        db.add(db_feedback)
        await db.commit()
        await db.refresh(db_feedback)

        logger.info(f"Created feedback for chunk {feedback_data.chunk_id}: {feedback_data.feedback}")

        return chunk_feedback_to_response(db_feedback)


@router.get("/chunk/{chunk_id}", response_model=ChunkFeedbackStats)
async def get_chunk_feedback(
    chunk_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get all feedback for a specific chunk with aggregated stats.

    Returns all individual feedback records for the chunk along with
    aggregated statistics including total count, positive/negative counts,
    and net score.

    Args:
        chunk_id: The ID of the chunk to get feedback for

    Returns:
        ChunkFeedbackStats with all feedback and aggregated scores
    """
    # Get all feedback for this chunk
    result = await db.execute(
        select(ChunkFeedback)
        .where(ChunkFeedback.chunk_id == chunk_id)
        .order_by(ChunkFeedback.created_at.desc())
    )
    feedbacks = result.scalars().all()

    # Calculate aggregated stats
    positive_count = sum(1 for f in feedbacks if f.feedback > 0)
    negative_count = sum(1 for f in feedbacks if f.feedback < 0)
    net_score = positive_count - negative_count

    return ChunkFeedbackStats(
        chunk_id=chunk_id,
        total_feedback=len(feedbacks),
        positive_count=positive_count,
        negative_count=negative_count,
        net_score=net_score,
        feedbacks=[chunk_feedback_to_response(f) for f in feedbacks]
    )


@router.delete("/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback(
    feedback_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a specific feedback record.

    Args:
        feedback_id: The ID of the feedback to delete

    Returns:
        204 No Content on success
    """
    result = await db.execute(
        select(ChunkFeedback).where(ChunkFeedback.id == feedback_id)
    )
    feedback = result.scalar_one_or_none()

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feedback with ID '{feedback_id}' not found"
        )

    await db.execute(
        delete(ChunkFeedback).where(ChunkFeedback.id == feedback_id)
    )
    await db.commit()

    logger.info(f"Deleted feedback {feedback_id}")
    return None


@router.get("/", response_model=List[FeedbackResponse])
async def list_all_feedback(
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """
    List all feedback records (for debugging/admin purposes).

    Args:
        limit: Maximum number of records to return (default 100)
        offset: Number of records to skip (default 0)

    Returns:
        List of feedback records
    """
    result = await db.execute(
        select(ChunkFeedback)
        .order_by(ChunkFeedback.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    feedbacks = result.scalars().all()

    return [chunk_feedback_to_response(f) for f in feedbacks]


# Analytics response models
class TopChunkInfo(BaseModel):
    """Information about a top-performing or bottom-performing chunk."""
    chunk_id: str
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    text_preview: Optional[str] = None
    net_score: int
    positive_count: int
    negative_count: int


class FeedbackTrendItem(BaseModel):
    """Feedback trend for a specific date."""
    date: str
    positive: int
    negative: int
    total: int


class FeedbackAnalyticsResponse(BaseModel):
    """Complete feedback analytics response."""
    total_feedback: int
    positive_count: int
    negative_count: int
    positive_percentage: float
    negative_percentage: float
    top_upvoted_chunks: List[TopChunkInfo]
    top_downvoted_chunks: List[TopChunkInfo]
    feedback_trend: List[FeedbackTrendItem]


@router.get("/analytics", response_model=FeedbackAnalyticsResponse)
async def get_feedback_analytics(
    trend_days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive feedback analytics.

    Returns:
    - Total feedback count and percentages
    - Top 5 most upvoted chunks with document info
    - Top 5 most downvoted chunks with document info
    - Feedback trend over time (default 30 days)

    Args:
        trend_days: Number of days for trend data (default 30)
    """
    # 1. Get total counts
    total_result = await db.execute(
        select(
            func.count(ChunkFeedback.id).label('total'),
            func.sum(case((ChunkFeedback.feedback > 0, 1), else_=0)).label('positive'),
            func.sum(case((ChunkFeedback.feedback < 0, 1), else_=0)).label('negative')
        )
    )
    totals = total_result.first()

    total_feedback = totals.total or 0
    positive_count = int(totals.positive or 0)
    negative_count = int(totals.negative or 0)

    positive_percentage = (positive_count / total_feedback * 100) if total_feedback > 0 else 0
    negative_percentage = (negative_count / total_feedback * 100) if total_feedback > 0 else 0

    # 2. Get top 5 most upvoted chunks (highest net score)
    chunk_scores_query = select(
        ChunkFeedback.chunk_id,
        func.sum(ChunkFeedback.feedback).label('net_score'),
        func.sum(case((ChunkFeedback.feedback > 0, 1), else_=0)).label('positive'),
        func.sum(case((ChunkFeedback.feedback < 0, 1), else_=0)).label('negative')
    ).group_by(ChunkFeedback.chunk_id)

    # Top upvoted (positive net score, sorted descending)
    top_upvoted_result = await db.execute(
        chunk_scores_query
        .having(func.sum(ChunkFeedback.feedback) > 0)
        .order_by(func.sum(ChunkFeedback.feedback).desc())
        .limit(5)
    )
    top_upvoted_rows = top_upvoted_result.all()

    # Top downvoted (negative net score, sorted ascending)
    top_downvoted_result = await db.execute(
        chunk_scores_query
        .having(func.sum(ChunkFeedback.feedback) < 0)
        .order_by(func.sum(ChunkFeedback.feedback).asc())
        .limit(5)
    )
    top_downvoted_rows = top_downvoted_result.all()

    # 3. Enrich chunk data with document info
    async def enrich_chunk_info(rows) -> List[TopChunkInfo]:
        enriched = []
        for row in rows:
            chunk_id = row.chunk_id
            net_score = int(row.net_score or 0)
            positive = int(row.positive or 0)
            negative = int(row.negative or 0)

            # Try to get document info from embedding table
            doc_id = None
            doc_name = None
            text_preview = None

            try:
                embedding_result = await db.execute(
                    select(DocumentEmbedding)
                    .where(DocumentEmbedding.chunk_id == chunk_id)
                    .limit(1)
                )
                embedding = embedding_result.scalar_one_or_none()

                if embedding:
                    doc_id = embedding.document_id
                    text_preview = embedding.text[:200] + "..." if len(embedding.text) > 200 else embedding.text

                    # Get document name
                    doc_result = await db.execute(
                        select(DBDocument.title)
                        .where(DBDocument.id == doc_id)
                    )
                    doc_title = doc_result.scalar_one_or_none()
                    doc_name = doc_title
            except Exception as e:
                logger.warning(f"Could not enrich chunk {chunk_id}: {e}")

            enriched.append(TopChunkInfo(
                chunk_id=chunk_id,
                document_id=doc_id,
                document_name=doc_name,
                text_preview=text_preview,
                net_score=net_score,
                positive_count=positive,
                negative_count=negative
            ))
        return enriched

    top_upvoted_chunks = await enrich_chunk_info(top_upvoted_rows)
    top_downvoted_chunks = await enrich_chunk_info(top_downvoted_rows)

    # 4. Get feedback trend over time
    start_date = datetime.utcnow() - timedelta(days=trend_days)

    trend_result = await db.execute(
        select(
            func.date(ChunkFeedback.created_at).label('date'),
            func.sum(case((ChunkFeedback.feedback > 0, 1), else_=0)).label('positive'),
            func.sum(case((ChunkFeedback.feedback < 0, 1), else_=0)).label('negative'),
            func.count(ChunkFeedback.id).label('total')
        )
        .where(ChunkFeedback.created_at >= start_date)
        .group_by(func.date(ChunkFeedback.created_at))
        .order_by(func.date(ChunkFeedback.created_at).asc())
    )
    trend_rows = trend_result.all()

    feedback_trend = [
        FeedbackTrendItem(
            date=str(row.date),
            positive=int(row.positive or 0),
            negative=int(row.negative or 0),
            total=int(row.total or 0)
        )
        for row in trend_rows
    ]

    return FeedbackAnalyticsResponse(
        total_feedback=total_feedback,
        positive_count=positive_count,
        negative_count=negative_count,
        positive_percentage=round(positive_percentage, 1),
        negative_percentage=round(negative_percentage, 1),
        top_upvoted_chunks=top_upvoted_chunks,
        top_downvoted_chunks=top_downvoted_chunks,
        feedback_trend=feedback_trend
    )
