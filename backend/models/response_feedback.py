"""
SQLAlchemy model for response-level feedback (Feature #350).

Stores user feedback (thumbs up/down) on AI responses, along with
the query, response text, retrieved chunks, and metadata. This enables
analysis of where the RAG pipeline succeeds or fails at the response level.
"""

from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, ForeignKey, Index
from sqlalchemy.sql import func
from models.db_models import Base


class ResponseFeedback(Base):
    """
    Table for storing user feedback on AI responses.

    Each record captures a thumbs up/down rating on an assistant message,
    along with the full context: user query, AI response, retrieved chunks,
    and which tools/models were used.
    """
    __tablename__ = "response_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Link to the specific assistant message being rated
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Link to the conversation for grouping
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)

    # The user's question that triggered this response
    query = Column(Text, nullable=False)

    # The AI's response text
    response = Column(Text, nullable=False)

    # User rating: +1 for thumbs up, -1 for thumbs down
    rating = Column(Integer, nullable=False)

    # JSONB: chunks retrieved and their relevance scores
    # Format: [{"chunk_id": "...", "text": "...", "score": 0.85, "document_title": "..."}]
    retrieved_chunks = Column(JSON, nullable=True)

    # Which embedding model was active when this response was generated
    embedding_model = Column(String(100), nullable=True)

    # Which tool was used (vector_search, sql_analysis, etc.)
    tool_used = Column(String(100), nullable=True)

    # Response source: 'rag', 'direct', or 'hybrid'
    response_source = Column(String(20), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_response_feedback_message', 'message_id'),
        Index('idx_response_feedback_conversation', 'conversation_id'),
        Index('idx_response_feedback_rating', 'rating'),
        Index('idx_response_feedback_created', 'created_at'),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "query": self.query,
            "response": self.response,
            "rating": self.rating,
            "retrieved_chunks": self.retrieved_chunks,
            "embedding_model": self.embedding_model,
            "tool_used": self.tool_used,
            "response_source": self.response_source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
