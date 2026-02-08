"""
SQLAlchemy model for user notes with pgvector support.
User notes can be retrieved alongside document chunks during RAG queries.
Notes have their own embeddings and a boost factor for ranking priority.
"""

from sqlalchemy import Column, String, Float, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from pgvector.sqlalchemy import Vector
from models.db_models import Base, generate_uuid, utc_now
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


class UserNote(Base):
    """
    Table for storing user notes with their vector embeddings.
    Notes can be retrieved alongside document chunks during RAG search.
    Uses pgvector extension for efficient similarity search.
    """
    __tablename__ = "user_notes"

    # Primary key (UUID string like other tables in this project)
    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Note content
    content = Column(Text, nullable=False)

    # Vector embedding (1024 dimensions - supports OpenAI and most Ollama models)
    # Using Vector(None) to support any dimension like DocumentEmbedding
    embedding = Column(Vector(None), nullable=True)

    # Optional link to a document (ON DELETE SET NULL)
    # Note: Index is defined in __table_args__ to avoid duplicate index creation
    document_id = Column(
        String(36),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True
    )

    # Tags for organization (PostgreSQL TEXT[] array)
    tags = Column(ARRAY(Text), nullable=True, default=[])

    # Boost factor for ranking priority in search results (default 1.5)
    # Higher values make the note appear higher in results
    boost_factor = Column(Float, nullable=False, default=1.5)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now())

    # Relationship to document (optional)
    document = relationship("DBDocument", backref="notes")

    # Indexes for performance
    # Note: ivfflat index on embedding cannot be created at table creation time
    # because Vector(None) doesn't have fixed dimensions. The vector index
    # should be created manually after data is inserted and dimension is known:
    # CREATE INDEX ix_user_notes_embedding_vector ON user_notes
    # USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
    __table_args__ = (
        # Index on document_id for filtering notes by document
        Index('ix_user_notes_document_id', 'document_id'),
        # Index on created_at for sorting
        Index('ix_user_notes_created_at', 'created_at'),
        # GIN index on tags for efficient array searches
        Index(
            'ix_user_notes_tags',
            'tags',
            postgresql_using='gin'
        ),
    )

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "embedding": self.embedding if isinstance(self.embedding, list) else (list(self.embedding) if self.embedding else None),
            "document_id": self.document_id,
            "tags": self.tags or [],
            "boost_factor": self.boost_factor,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
