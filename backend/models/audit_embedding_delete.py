"""
SQLAlchemy model for embedding deletion audit log.

Feature #252: Cascade delete audit logging
Feature #266: Add details JSONB column and retention policy

This table logs all DELETE operations on the document_embeddings table,
including the source of the delete. This helps diagnose unexpected data loss.
"""

from sqlalchemy import Column, String, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from models.db_models import Base


# Deletion source constants
DELETE_SOURCE_MANUAL = 'manual'           # User manually deleted a document
DELETE_SOURCE_REEMBED = 'reembed'         # Re-embedding operation replaced old embeddings
DELETE_SOURCE_DOCUMENT_DELETE = 'document_delete'  # Document was deleted
DELETE_SOURCE_CASCADE = 'cascade'         # Cascade delete from parent table
DELETE_SOURCE_ORPHAN_CLEANUP = 'orphan_cleanup'    # Orphan cleanup maintenance job
DELETE_SOURCE_RESET_DATABASE = 'reset_database'    # Database reset operation
DELETE_SOURCE_BULK_DELETE = 'bulk_delete'  # Bulk deletion operation
DELETE_SOURCE_TRIGGER = 'trigger'         # PostgreSQL trigger (fallback when source unknown)


class AuditEmbeddingDelete(Base):
    """
    Audit log for document embedding deletions.

    Records every delete operation on the document_embeddings table,
    including the source/reason for the deletion.

    The table is populated by:
    1. PostgreSQL trigger ON DELETE - for direct SQL deletions
    2. Application-level logging - for deletions via the API

    This helps:
    - Diagnose unexpected data loss
    - Track who/what deleted embeddings
    - Monitor for suspicious bulk deletion patterns
    - Provide an audit trail for compliance
    """
    __tablename__ = "audit_embeddings_delete"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # What was deleted
    document_id = Column(String(255), nullable=False, index=True)
    chunk_count = Column(Integer, nullable=False, default=1)

    # When it was deleted
    deleted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Source of the deletion
    source = Column(String(50), nullable=False, default=DELETE_SOURCE_TRIGGER)

    # User action that triggered the deletion (if known)
    user_action = Column(String(255), nullable=True)

    # Additional context (JSON string with stack trace or caller info)
    context = Column(Text, nullable=True)

    # API endpoint or function that triggered the deletion
    api_endpoint = Column(String(255), nullable=True)

    # Structured details as JSONB (Feature #266)
    # Can include: document_title, collection_id, embedding_model, etc.
    details = Column(JSONB, nullable=True)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_count": self.chunk_count,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "source": self.source,
            "user_action": self.user_action,
            "context": self.context,
            "api_endpoint": self.api_endpoint,
            "details": self.details  # Feature #266: JSONB details
        }
