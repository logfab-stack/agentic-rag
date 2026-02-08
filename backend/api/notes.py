"""
User Notes API endpoints for the Agentic RAG System.

Provides CRUD operations for user notes with automatic embedding generation.
Notes can be retrieved alongside document chunks during RAG queries.
"""

import os
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Query, Depends
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
from openai import OpenAI

from models.note import Note, NoteCreate, NoteUpdate, NoteListResponse
from models.user_note import UserNote
from core.database import get_db
from core.store import settings_store

logger = logging.getLogger(__name__)

router = APIRouter()

# Ollama settings
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


async def generate_note_embedding(text: str) -> Optional[List[float]]:
    """
    Generate embedding for note content using the configured embedding model.

    Args:
        text: The note content to embed

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
                        logger.info(f"Generated Ollama embedding ({len(embedding)} dims) for note")
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
                logger.info(f"Generated OpenAI embedding ({len(embedding)} dims) for note")
                return embedding

    except Exception as e:
        logger.error(f"Error generating embedding for note: {e}")

    return None


def user_note_to_response(note: UserNote) -> Note:
    """Convert SQLAlchemy UserNote to Pydantic Note response model."""
    return Note(
        id=note.id,
        content=note.content,
        document_id=note.document_id,
        tags=note.tags or [],
        boost_factor=note.boost_factor,
        has_embedding=note.embedding is not None,
        created_at=note.created_at,
        updated_at=note.updated_at
    )


@router.post("/", response_model=Note, status_code=status.HTTP_201_CREATED)
async def create_note(
    note: NoteCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new user note with automatic embedding generation.

    The note content will be embedded using the configured embedding model
    (OpenAI or Ollama) for use in RAG retrieval.
    """
    # Validate document_id if provided
    if note.document_id:
        from models.db_models import DBDocument
        result = await db.execute(
            select(DBDocument).where(DBDocument.id == note.document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Document with ID '{note.document_id}' not found"
            )

    # Generate embedding for the note content
    embedding = await generate_note_embedding(note.content)

    # Create the note
    db_note = UserNote(
        content=note.content,
        document_id=note.document_id,
        tags=note.tags or [],
        boost_factor=note.boost_factor if note.boost_factor is not None else 1.5,
        embedding=embedding
    )

    db.add(db_note)
    await db.commit()
    await db.refresh(db_note)

    logger.info(f"Created note {db_note.id} with embedding: {embedding is not None}")

    return user_note_to_response(db_note)


@router.get("/", response_model=NoteListResponse)
async def list_notes(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    document_id: Optional[str] = Query(None, description="Filter by document ID"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    db: AsyncSession = Depends(get_db)
):
    """
    List all notes with pagination and optional filtering.

    Can filter by document_id to get notes associated with a specific document,
    or by tag to get notes with a specific tag.
    """
    # Build query with filters
    query = select(UserNote)
    count_query = select(func.count(UserNote.id))

    if document_id:
        query = query.where(UserNote.document_id == document_id)
        count_query = count_query.where(UserNote.document_id == document_id)

    if tag:
        # PostgreSQL array contains operator
        query = query.where(UserNote.tags.contains([tag]))
        count_query = count_query.where(UserNote.tags.contains([tag]))

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Apply pagination and ordering
    offset = (page - 1) * per_page
    query = query.order_by(UserNote.created_at.desc()).offset(offset).limit(per_page)

    result = await db.execute(query)
    notes = result.scalars().all()

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return NoteListResponse(
        notes=[user_note_to_response(n) for n in notes],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages
    )


@router.get("/{note_id}", response_model=Note)
async def get_note(
    note_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a single note by ID."""
    result = await db.execute(
        select(UserNote).where(UserNote.id == note_id)
    )
    note = result.scalar_one_or_none()

    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note with ID '{note_id}' not found"
        )

    return user_note_to_response(note)


@router.put("/{note_id}", response_model=Note)
async def update_note(
    note_id: str,
    update: NoteUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update an existing note.

    If the content is updated, the embedding will be re-generated.
    """
    result = await db.execute(
        select(UserNote).where(UserNote.id == note_id)
    )
    note = result.scalar_one_or_none()

    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note with ID '{note_id}' not found"
        )

    # Validate document_id if being updated
    if update.document_id is not None and update.document_id != "":
        from models.db_models import DBDocument
        doc_result = await db.execute(
            select(DBDocument).where(DBDocument.id == update.document_id)
        )
        doc = doc_result.scalar_one_or_none()
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Document with ID '{update.document_id}' not found"
            )

    # Update fields
    content_changed = False

    if update.content is not None:
        note.content = update.content
        content_changed = True

    if update.tags is not None:
        note.tags = update.tags

    if update.boost_factor is not None:
        note.boost_factor = update.boost_factor

    if update.document_id is not None:
        # Allow setting to None (empty string means unlink)
        note.document_id = update.document_id if update.document_id != "" else None

    # Re-generate embedding if content changed
    if content_changed:
        embedding = await generate_note_embedding(note.content)
        note.embedding = embedding
        logger.info(f"Re-generated embedding for note {note_id}: {embedding is not None}")

    await db.commit()
    await db.refresh(note)

    return user_note_to_response(note)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a note by ID."""
    result = await db.execute(
        select(UserNote).where(UserNote.id == note_id)
    )
    note = result.scalar_one_or_none()

    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note with ID '{note_id}' not found"
        )

    await db.execute(
        delete(UserNote).where(UserNote.id == note_id)
    )
    await db.commit()

    logger.info(f"Deleted note {note_id}")
    return None


@router.get("/{note_id}/embedding", response_model=dict)
async def get_note_embedding(
    note_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get the embedding vector for a note.

    Returns the embedding dimensions and a preview of the first 10 values.
    The full vector is not returned to reduce response size.
    """
    result = await db.execute(
        select(UserNote).where(UserNote.id == note_id)
    )
    note = result.scalar_one_or_none()

    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note with ID '{note_id}' not found"
        )

    if note.embedding is None:
        return {
            "note_id": note_id,
            "has_embedding": False,
            "dimensions": 0,
            "preview": []
        }

    try:
        # Handle various embedding formats (list, numpy array, pgvector)
        if isinstance(note.embedding, list):
            embedding_list = note.embedding
        else:
            embedding_list = list(note.embedding)

        return {
            "note_id": note_id,
            "has_embedding": True,
            "dimensions": len(embedding_list),
            "preview": [float(x) for x in embedding_list[:10]]  # First 10 values for inspection
        }
    except Exception as e:
        logger.error(f"Error processing embedding for note {note_id}: {e}")
        return {
            "note_id": note_id,
            "has_embedding": True,
            "dimensions": -1,
            "preview": [],
            "error": str(e)
        }


@router.post("/{note_id}/regenerate-embedding", response_model=Note)
async def regenerate_note_embedding(
    note_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Regenerate the embedding for an existing note.

    Useful if the embedding model configuration has changed or if
    the original embedding generation failed.
    """
    result = await db.execute(
        select(UserNote).where(UserNote.id == note_id)
    )
    note = result.scalar_one_or_none()

    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note with ID '{note_id}' not found"
        )

    embedding = await generate_note_embedding(note.content)
    note.embedding = embedding

    await db.commit()
    await db.refresh(note)

    logger.info(f"Regenerated embedding for note {note_id}: {embedding is not None}")

    return user_note_to_response(note)
