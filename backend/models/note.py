"""
Pydantic models for User Notes API.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class NoteBase(BaseModel):
    """Base note model with common fields."""
    content: str = Field(..., min_length=1, max_length=10000, description="Note content text")


class NoteCreate(NoteBase):
    """Model for creating a new note."""
    document_id: Optional[str] = Field(None, description="Optional link to a document")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for organization")
    boost_factor: Optional[float] = Field(default=1.5, ge=0.1, le=10.0, description="Ranking boost factor")


class NoteUpdate(BaseModel):
    """Model for updating an existing note."""
    content: Optional[str] = Field(None, min_length=1, max_length=10000, description="Updated content (re-generates embedding)")
    tags: Optional[List[str]] = Field(None, description="Updated tags")
    boost_factor: Optional[float] = Field(None, ge=0.1, le=10.0, description="Updated boost factor")
    document_id: Optional[str] = Field(None, description="Link/unlink to a document")


class Note(NoteBase):
    """Note model for API responses."""
    id: str = Field(..., description="Unique note ID")
    document_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    boost_factor: float = 1.5
    has_embedding: bool = Field(False, description="Whether the note has an embedding vector")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NoteWithDocument(Note):
    """Note with associated document information."""
    document_title: Optional[str] = None


class NoteListResponse(BaseModel):
    """Paginated response for listing notes."""
    notes: List[Note]
    total: int
    page: int
    per_page: int
    total_pages: int
