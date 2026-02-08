"""
Document models for the Agentic RAG System.
"""

from pydantic import BaseModel, Field, field_serializer
from typing import Optional, List
from datetime import datetime, timezone
import uuid


def utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class DocumentBase(BaseModel):
    """Base document model with common fields."""
    title: str = Field(..., min_length=1, max_length=255, description="Custom name for the document")
    comment: Optional[str] = Field(None, max_length=1000, description="User's notes/description")


class DocumentCreate(DocumentBase):
    """Model for creating a new document."""
    original_filename: str = Field(..., description="Original uploaded filename")
    mime_type: str = Field(..., description="MIME type of the file")
    file_size: int = Field(..., ge=0, description="File size in bytes")
    document_type: str = Field(default="unstructured", description="'structured' or 'unstructured'")
    collection_id: Optional[str] = Field(None, description="Optional collection ID")
    content_hash: Optional[str] = Field(None, description="SHA-256 hash of file content")
    url: Optional[str] = Field(None, description="File storage path (deprecated)")
    file_path: Optional[str] = Field(None, description="Actual path to uploaded file")
    schema_info: Optional[str] = Field(None, description="Schema info for structured data")
    # Feature #258: Initial status when creating a document (default: processing)
    status: str = Field(default="processing", description="Initial document status")


class DocumentUpdate(BaseModel):
    """Model for updating an existing document."""
    title: Optional[str] = Field(None, min_length=1, max_length=255, description="New custom name")
    comment: Optional[str] = Field(None, max_length=1000, description="New comment/notes")
    collection_id: Optional[str] = Field(None, description="Move to different collection")
    schema_info: Optional[str] = Field(None, description="Schema info for structured data")
    # Feature #255: Allow updating file_status for file integrity checks
    file_status: Optional[str] = Field(None, description="File status: 'ok' or 'file_missing'")
    # Feature #258: Allow updating unified document status
    status: Optional[str] = Field(None, description="Document status: 'uploading', 'processing', 'ready', 'embedding_failed', 'file_missing'")
    # Feature #259: Allow updating embedding_model
    embedding_model: Optional[str] = Field(None, description="Embedding model used: 'openai:text-embedding-3-small' or 'ollama:bge-m3:latest'")


class DocumentInDB(DocumentBase):
    """Full document model as stored in database."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique document ID")
    original_filename: str
    mime_type: str
    file_size: int
    document_type: str = "unstructured"
    collection_id: Optional[str] = None
    content_hash: Optional[str] = Field(None, description="SHA-256 hash of file content")
    schema_info: Optional[str] = Field(None, description="Schema info for structured data")
    url: Optional[str] = Field(None, description="File storage path (deprecated)")
    file_path: Optional[str] = Field(None, description="Actual path to uploaded file")
    # Feature #251: Track embedding status for documents
    embedding_status: str = Field(default="ready", description="Embedding status: 'ready', 'processing', 'embedding_failed'")
    # Feature #254: Track file existence status for orphaned record detection
    file_status: str = Field(default="ok", description="File status: 'ok' or 'file_missing'")
    # Feature #258: Unified document processing status
    status: str = Field(default="ready", description="Document status: 'uploading', 'processing', 'ready', 'embedding_failed', 'file_missing'")
    # Feature #260: Store chunk/embedding count for quick health checks
    chunk_count: int = Field(default=0, description="Number of chunks/embeddings for this document")
    # Feature #259: Track which embedding model was used for this document
    embedding_model: Optional[str] = Field(None, description="Embedding model used: 'openai:text-embedding-3-small' or 'ollama:bge-m3:latest'")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Config:
        from_attributes = True


class Document(DocumentBase):
    """Document model for API responses - excludes internal file paths for security."""
    id: str = Field(..., description="Unique document ID")
    original_filename: str
    mime_type: str
    file_size: int
    document_type: str = "unstructured"
    collection_id: Optional[str] = None
    content_hash: Optional[str] = Field(None, description="SHA-256 hash of file content")
    schema_info: Optional[str] = Field(None, description="Schema info for structured data")
    # Note: 'url' field is intentionally excluded to prevent exposing internal file paths
    # Feature #251: Track embedding status for documents
    embedding_status: str = Field(default="ready", description="Embedding status: 'ready', 'processing', 'embedding_failed'")
    # Feature #254: Track file existence status for orphaned record detection
    file_status: str = Field(default="ok", description="File status: 'ok' or 'file_missing'")
    # Feature #258: Unified document processing status
    status: str = Field(default="ready", description="Document status: 'uploading', 'processing', 'ready', 'embedding_failed', 'file_missing'")
    # Feature #260: Store chunk/embedding count for quick health checks
    chunk_count: int = Field(default=0, description="Number of chunks/embeddings for this document")
    # Feature #259: Track which embedding model was used for this document
    embedding_model: Optional[str] = Field(None, description="Embedding model used: 'openai:text-embedding-3-small' or 'ollama:bge-m3:latest'")
    created_at: datetime
    updated_at: datetime

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: datetime, _info):
        """Serialize datetime to ISO 8601 with UTC 'Z' suffix."""
        if dt is None:
            return None
        # Ensure UTC timezone indicator for proper frontend parsing
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    """Wrapper response for document upload that includes embedding status and warnings."""
    document: Document
    embedding_status: str = Field(
        default="success",
        description="Status of embedding generation: 'success', 'partial', 'failed', or 'skipped'"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="List of warning messages from the upload process"
    )
