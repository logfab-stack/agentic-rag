"""
SQLAlchemy database models for PostgreSQL persistence.
These models map to actual database tables.
"""

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, JSON, Index, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone
import uuid

Base = declarative_base()


def utc_now():
    """Return current UTC time."""
    return datetime.now(timezone.utc)


def generate_uuid():
    """Generate a new UUID string."""
    return str(uuid.uuid4())


# Document embedding status constants (Feature #251)
EMBEDDING_STATUS_READY = 'ready'  # Document has embeddings and is searchable
EMBEDDING_STATUS_PROCESSING = 'processing'  # Document is being processed/re-embedded
EMBEDDING_STATUS_FAILED = 'embedding_failed'  # Embedding generation failed

# Document file status constants (Feature #254)
FILE_STATUS_OK = 'ok'  # File exists on disk
FILE_STATUS_MISSING = 'file_missing'  # File is missing from disk (orphaned record)

# Unified document status constants (Feature #258)
# Tracks overall document processing state
# NOTE: These values are enforced by CHECK constraint chk_document_status (Feature #261)
DOCUMENT_STATUS_UPLOADING = 'uploading'  # File is being uploaded to server
DOCUMENT_STATUS_QUEUED = 'queued'  # Feature #330: Document queued for background processing
DOCUMENT_STATUS_PROCESSING = 'processing'  # Document is being processed (parsing, embedding)
DOCUMENT_STATUS_READY = 'ready'  # Document is fully processed and ready for use
DOCUMENT_STATUS_EMBEDDING_FAILED = 'embedding_failed'  # Embedding generation failed
DOCUMENT_STATUS_FILE_MISSING = 'file_missing'  # File has been deleted or is missing from disk
# Feature #297: Post re-embed verification check
DOCUMENT_STATUS_VERIFICATION_FAILED = 'verification_failed'  # Embedding count verification failed after re-embed

# Feature #261: Valid document status values (matches CHECK constraint in database)
VALID_DOCUMENT_STATUSES = (
    DOCUMENT_STATUS_UPLOADING,
    DOCUMENT_STATUS_QUEUED,  # Feature #330
    DOCUMENT_STATUS_PROCESSING,
    DOCUMENT_STATUS_READY,
    DOCUMENT_STATUS_EMBEDDING_FAILED,
    DOCUMENT_STATUS_FILE_MISSING,
    DOCUMENT_STATUS_VERIFICATION_FAILED,  # Feature #297
)


class DBDocument(Base):
    """Document model - stores document metadata."""
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(255), nullable=False, index=True)
    comment = Column(Text, nullable=True)
    original_filename = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    document_type = Column(String(20), nullable=False, default="unstructured")  # 'structured' or 'unstructured'
    collection_id = Column(String(36), ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True)
    content_hash = Column(String(64), nullable=True, unique=True, index=True)  # SHA-256 hash for duplicate detection
    schema_info = Column(Text, nullable=True)  # JSON string of CSV headers/schema
    url = Column(String(1000), nullable=True)  # File storage path (deprecated, use file_path)
    # Feature #253: Explicit file path storage for robustness
    file_path = Column(String(1000), nullable=True, index=True)  # Actual path to uploaded file
    # Feature #251: Track embedding status for documents
    embedding_status = Column(String(20), nullable=False, default=EMBEDDING_STATUS_READY, server_default='ready')
    # Feature #254: Track file existence status for orphaned record detection
    file_status = Column(String(20), nullable=False, default=FILE_STATUS_OK, server_default='ok')
    # Feature #258: Unified document processing status
    status = Column(String(20), nullable=False, default=DOCUMENT_STATUS_READY, server_default='ready')
    # Feature #260: Store chunk/embedding count for quick health checks
    chunk_count = Column(Integer, nullable=False, default=0, server_default='0')
    # Feature #259: Track which embedding model was used for this document
    # Format: 'openai:text-embedding-3-small' or 'ollama:bge-m3:latest'
    # NULL for structured documents (CSV, Excel, JSON) that don't have embeddings
    embedding_model = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now())

    # Relationships
    collection = relationship("DBCollection", back_populates="documents")
    rows = relationship("DBDocumentRow", back_populates="document", cascade="all, delete-orphan")

    # Indexes for common queries
    __table_args__ = (
        Index('idx_documents_collection', 'collection_id'),
        Index('idx_documents_type', 'document_type'),
        Index('idx_documents_created', 'created_at'),
        Index('idx_documents_embedding_status', 'embedding_status'),  # Feature #251
        Index('idx_documents_file_status', 'file_status'),  # Feature #254
        Index('idx_documents_status', 'status'),  # Feature #258: Unified status
        Index('idx_documents_chunk_count', 'chunk_count'),  # Feature #260
        Index('idx_documents_embedding_model', 'embedding_model'),  # Feature #259
    )


class DBCollection(Base):
    """Collection model - stores collections/folders for organizing documents."""
    __tablename__ = "collections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now())

    # Relationships
    documents = relationship("DBDocument", back_populates="collection", cascade="all")


class DBDocumentRow(Base):
    """Document row model - stores structured data rows (CSV/Excel)."""
    __tablename__ = "document_rows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    row_data = Column(JSON, nullable=False)  # JSONB in PostgreSQL
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())

    # Relationships
    document = relationship("DBDocument", back_populates="rows")

    # Index for efficient queries
    __table_args__ = (
        Index('idx_document_rows_dataset', 'dataset_id'),
    )


class DBConversation(Base):
    """Conversation model - stores chat conversations."""
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(255), nullable=True)
    is_archived = Column(Boolean, nullable=False, default=False, server_default='false')
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now())

    # Relationships
    messages = relationship("DBMessage", back_populates="conversation", cascade="all, delete-orphan", order_by="DBMessage.created_at")

    # Indexes for sorting
    __table_args__ = (
        Index('idx_conversations_created', 'created_at'),
        Index('idx_conversations_updated', 'updated_at'),
    )


class DBMessage(Base):
    """Message model - stores individual messages in conversations."""
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    tool_used = Column(String(100), nullable=True)  # Which tool was invoked
    tool_details = Column(JSON, nullable=True)  # SQL query, chunks found, etc.
    response_source = Column(String(20), nullable=True)  # 'rag', 'direct', or 'hybrid'
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())

    # Relationships
    conversation = relationship("DBConversation", back_populates="messages")

    # Index for efficient queries
    __table_args__ = (
        Index('idx_messages_conversation', 'conversation_id'),
        Index('idx_messages_created', 'created_at'),
    )


class DBSetting(Base):
    """Settings model - stores application settings and configuration."""
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now())


class DBAuditLog(Base):
    """Audit log model - stores records of sensitive operations and document lifecycle events.

    Feature #267: Extended for detailed document operation tracking.

    Actions for document operations:
    - document_uploaded: Document was uploaded to the system
    - embedding_started: Embedding generation started
    - embedding_completed: Embedding generation completed successfully
    - embedding_failed: Embedding generation failed
    - document_deleted: Document was deleted
    - document_re_embed_started: Re-embedding operation started
    - document_re_embed_completed: Re-embedding operation completed
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(100), nullable=False, index=True)  # e.g., "database_reset", "document_uploaded"
    status = Column(String(50), nullable=False)  # "initiated", "completed", "cancelled", "failed"
    details = Column(Text, nullable=True)  # JSON details of what was affected
    ip_address = Column(String(45), nullable=True)  # Client IP if available
    user_agent = Column(String(500), nullable=True)  # Browser user agent
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())

    # Feature #267: Document operation tracking columns
    document_id = Column(String(36), nullable=True, index=True)  # UUID of the document
    document_name = Column(String(255), nullable=True)  # Document title at time of operation
    file_size = Column(Integer, nullable=True)  # File size in bytes
    chunk_count = Column(Integer, nullable=True)  # Number of chunks/embeddings generated
    model_used = Column(String(100), nullable=True)  # Embedding model used (e.g., 'ollama:bge-m3:latest')
    duration_ms = Column(Integer, nullable=True)  # Operation duration in milliseconds

    # Indexes for common queries
    __table_args__ = (
        Index('idx_audit_log_action', 'action'),
        Index('idx_audit_log_created', 'created_at'),
        Index('ix_audit_log_document_action', 'document_id', 'action', 'created_at'),  # Feature #267
    )
