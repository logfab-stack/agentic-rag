"""
SQLAlchemy model for chunk feedback with pgvector support.

This table stores user feedback (thumbs up/down) on retrieved chunks
for a given query, enabling future improvements to retrieval quality
through learning from user feedback.

Note on indexing (Feature #209):
- Vector indexes are only created if dimensions ≤4000
- For high-dimension embeddings (>4000), sequential scan is used
- Index creation is handled by alembic migration 005
"""

from sqlalchemy import Column, String, Integer, Text, DateTime, Index, UniqueConstraint
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from models.db_models import Base


class ChunkFeedback(Base):
    """
    Table for storing user feedback on retrieved chunks.

    Feedback (+1 for thumbs up, -1 for thumbs down) is stored along with
    the query text and embedding, allowing for:
    - Aggregating feedback per chunk to identify quality issues
    - Similarity search on query embeddings to find related feedback
    - Learning from user preferences to improve retrieval
    """
    __tablename__ = "chunk_feedback"

    # Primary key (SERIAL)
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Reference to the chunk that received feedback
    # References document_embeddings.chunk_id (not a FK since chunks might be deleted)
    chunk_id = Column(String(255), nullable=False, index=True)

    # The query that was performed when this feedback was given
    query_text = Column(Text, nullable=False)

    # Vector embedding of the query (for similarity search on past queries)
    # Using Vector(None) to support any dimension (OpenAI, Ollama, etc.)
    query_embedding = Column(Vector(None), nullable=False)

    # User feedback: +1 for thumbs up, -1 for thumbs down
    feedback = Column(Integer, nullable=False)

    # Timestamp of when feedback was given
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Indexes and constraints
    # Note: Vector index (HNSW) is created conditionally by migration 005
    # based on embedding dimensions
    __table_args__ = (
        # Vector index is created by migration if dimensions permit
        # (see alembic/versions/005_migrate_to_hnsw_index.py)

        # Unique constraint to prevent duplicate feedback for same chunk+query combination
        UniqueConstraint('chunk_id', 'query_text', name='uq_chunk_feedback_chunk_query'),
    )

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "chunk_id": self.chunk_id,
            "query_text": self.query_text,
            "query_embedding": self.query_embedding if isinstance(self.query_embedding, list) else list(self.query_embedding) if self.query_embedding else [],
            "feedback": self.feedback,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
