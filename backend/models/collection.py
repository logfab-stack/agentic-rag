"""
Collection models for the Agentic RAG System.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid


def utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class CollectionBase(BaseModel):
    """Base collection model with common fields."""
    name: str = Field(..., min_length=1, max_length=255, description="Collection name")
    description: Optional[str] = Field(None, max_length=1000, description="Collection description")


class CollectionCreate(CollectionBase):
    """Model for creating a new collection."""
    pass


class CollectionUpdate(BaseModel):
    """Model for updating an existing collection."""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="New name")
    description: Optional[str] = Field(None, max_length=1000, description="New description")


class CollectionInDB(CollectionBase):
    """Full collection model as stored in database."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique collection ID")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Config:
        from_attributes = True


class Collection(CollectionInDB):
    """Collection model for API responses."""
    pass


class CollectionWithDocuments(Collection):
    """Collection model with embedded documents list."""
    documents: List[dict] = Field(default_factory=list, description="Documents in this collection")
