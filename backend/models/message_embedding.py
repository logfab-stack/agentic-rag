"""
SQLAlchemy model for message embeddings with pgvector support.
Message embeddings allow retrieving relevant past Q&A pairs during RAG queries.
Embeddings are created from user questions to enable semantic search of conversation history.
"""

from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from pgvector.sqlalchemy import Vector
from models.db_models import Base, generate_uuid, utc_now
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


class MessageEmbedding(Base):
    """
    Table for storing message embeddings for conversation history search.
    Only user messages are embedded to allow finding relevant past questions.
    When retrieved, the corresponding assistant response provides context.
    """
    __tablename__ = "message_embeddings"

    # Primary key (UUID string like other tables in this project)
    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Foreign key to the message being embedded
    message_id = Column(
        String(36),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True  # One embedding per message
    )

    # The conversation this message belongs to (denormalized for efficient queries)
    conversation_id = Column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False
    )

    # Vector embedding (supports variable dimensions like other pgvector tables)
    # Using Vector(None) to support any dimension (OpenAI and Ollama models)
    embedding = Column(Vector(None), nullable=False)

    # Store the embedding model and dimension for dimension matching
    embedding_source = Column(String(100), nullable=True)  # e.g., "openai:text-embedding-3-small"
    embedding_dimension = Column(String(20), nullable=True)  # e.g., "1536"

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())

    # Relationships
    message = relationship("DBMessage", backref="embedding_record")
    conversation = relationship("DBConversation", backref="message_embeddings")

    # Indexes for performance
    __table_args__ = (
        # Index on message_id for fast lookups
        Index('ix_message_embeddings_message_id', 'message_id'),
        # Index on conversation_id for filtering by conversation
        Index('ix_message_embeddings_conversation_id', 'conversation_id'),
        # Index on created_at for sorting
        Index('ix_message_embeddings_created_at', 'created_at'),
        # Note: Vector index (ivfflat) should be created manually after data exists:
        # CREATE INDEX ix_message_embeddings_vector ON message_embeddings
        # USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
    )

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "embedding": self.embedding if isinstance(self.embedding, list) else (list(self.embedding) if self.embedding else None),
            "embedding_source": self.embedding_source,
            "embedding_dimension": self.embedding_dimension,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
