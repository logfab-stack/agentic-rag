"""
SQLAlchemy model for document embeddings with pgvector support.

IMPORTANT - Vector Index Dimension Limits (Feature #209):
- pgvector HNSW and IVFFLAT indexes support max 2000 dimensions for 'vector' type
- pgvector halfvec type extends this to 4000 dimensions
- Embeddings >4000 dimensions (e.g., qwen3-embedding:8b with 4096) cannot use indexes
- Sequential scan fallback is used for high-dimension embeddings
- Performance is still acceptable: ~28ms for 3140 embeddings at 4096 dimensions
"""

from sqlalchemy import Column, String, Integer, Text, JSON, Index, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from models.db_models import Base


# Embedding status enum values (Feature #249)
EMBEDDING_STATUS_ACTIVE = 'active'
EMBEDDING_STATUS_PENDING_DELETE = 'pending_delete'
EMBEDDING_STATUS_ARCHIVED = 'archived'


class EmbeddingsBackup(Base):
    """
    Feature #250: Backup table for embeddings before re-embed operations.

    This table stores a copy of document embeddings BEFORE a re-embed operation
    starts. This provides a physical backup that can be restored if the re-embed
    operation fails catastrophically (e.g., server crash).

    The backup is:
    - Created before re-embed starts (INSERT INTO embeddings_backup SELECT * FROM document_embeddings WHERE document_id = X)
    - Restored on failure (INSERT INTO document_embeddings SELECT * FROM embeddings_backup WHERE document_id = X)
    - Deleted on success (DELETE FROM embeddings_backup WHERE document_id = X)
    - Also supports manual restoration via API endpoint

    Cleanup: Backups older than 7 days are automatically cleaned up.

    Feature #263: NOT NULL constraint on embedding column
    - embedding column has NOT NULL constraint to ensure backup is complete
    """
    __tablename__ = "embeddings_backup"

    # Primary key for backup table
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Original ID from document_embeddings (for reference)
    original_id = Column(Integer, nullable=False)

    # Same columns as DocumentEmbedding
    document_id = Column(String(255), nullable=False, index=True)
    chunk_id = Column(String(255), nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(None), nullable=False)
    chunk_metadata = Column('metadata', JSONB, nullable=True, default={})
    status = Column(String(20), nullable=False, default=EMBEDDING_STATUS_ACTIVE)
    pending_delete_at = Column(DateTime(timezone=True), nullable=True)

    # Backup metadata
    backup_created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    backup_reason = Column(String(100), nullable=True, default='reembed')

    __table_args__ = (
        Index('ix_embeddings_backup_backup_created_at', 'backup_created_at'),
    )

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "original_id": self.original_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "text": self.text,
            "embedding": self.embedding if isinstance(self.embedding, list) else list(self.embedding),
            "metadata": self.chunk_metadata or {},
            "status": self.status,
            "backup_created_at": self.backup_created_at.isoformat() if self.backup_created_at else None,
            "backup_reason": self.backup_reason
        }


class DocumentEmbedding(Base):
    """
    Table for storing document text chunks with their vector embeddings.
    Uses pgvector extension for efficient similarity search.

    Note on indexing (Feature #209):
    - Vector indexes (HNSW/IVFFLAT) are only created if dimensions ≤4000
    - For dimensions >4000, sequential scan is used (still performant)
    - Index creation is handled by alembic migration 005

    Feature #249: Soft delete strategy
    - status column tracks embedding lifecycle: active, pending_delete, archived
    - During re-embed, old embeddings are marked pending_delete instead of being deleted
    - Only permanently deleted after new embeddings are verified
    - Cleanup job removes stale pending_delete rows after 24h

    Feature #256: Foreign key constraint
    - document_id references documents.id with ON DELETE CASCADE
    - Ensures referential integrity and automatic cleanup of embeddings when documents are deleted
    - Prevents orphaned embedding records

    Feature #263: NOT NULL constraints for critical columns
    - embedding column has NOT NULL constraint - vector must exist for record to be useful
    - created_at column has NOT NULL constraint with server default
    - These constraints prevent incomplete records from being created
    """
    __tablename__ = "document_embeddings"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Document reference - FK constraint added by migration 014 with ON DELETE CASCADE
    # Note: ForeignKey declaration here for documentation; actual constraint is in database
    document_id = Column(String(255), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String(255), nullable=False, unique=True)

    # Chunk content
    text = Column(Text, nullable=False)

    # Vector embedding - supports variable dimensions
    # Common dimensions: 1536 (OpenAI text-embedding-3-small),
    # 4096 (qwen3-embedding:8b, nomic-embed-text-v1.5-4096)
    # Using Vector(None) to support any embedding model
    embedding = Column(Vector(None), nullable=False)

    # Metadata (chunk_index, total_chunks, embedding_source, etc.)
    # Using 'chunk_metadata' instead of 'metadata' because 'metadata' is reserved by SQLAlchemy
    chunk_metadata = Column('metadata', JSONB, nullable=True, default={})

    # Feature #249: Soft delete status for embeddings
    # Values: 'active' (default), 'pending_delete', 'archived'
    status = Column(String(20), nullable=False, default=EMBEDDING_STATUS_ACTIVE, index=True)

    # Feature #249: Timestamp for when status changed to pending_delete
    # Used by cleanup job to delete stale pending_delete rows after 24h
    pending_delete_at = Column(DateTime(timezone=True), nullable=True)

    # Feature #263: Created timestamp with NOT NULL constraint
    # Ensures we always know when an embedding was created
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Indexes for performance
    # Note: Vector index (HNSW) is created conditionally by alembic migration 005
    # based on embedding dimensions. If dimensions exceed pgvector limits,
    # no vector index is created and sequential scan is used.
    __table_args__ = (
        # Vector index is created by migration if dimensions permit:
        # - ≤2000 dims: HNSW on 'vector' type
        # - 2001-4000 dims: HNSW on 'halfvec' cast
        # - >4000 dims: No index (sequential scan)
    )

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "text": self.text,
            "embedding": self.embedding if isinstance(self.embedding, list) else list(self.embedding),
            "metadata": self.chunk_metadata or {},
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
