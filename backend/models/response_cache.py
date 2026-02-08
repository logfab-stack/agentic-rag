"""
SQLAlchemy model for response cache (Feature #352).

Stores cached AI responses keyed by query embedding similarity.
When a new query is semantically close to a cached one (cosine similarity > threshold),
the cached response is returned immediately, saving LLM costs and reducing latency.
"""

from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, Index
from sqlalchemy.sql import func
from models.db_models import Base


class ResponseCache(Base):
    """
    Table for caching AI responses with their query embeddings.

    The query_embedding column uses pgvector's vector type with no fixed dimension,
    allowing different embedding models (OpenAI 1536-dim, Ollama variable) to coexist.
    Similarity searches are done via raw SQL using the <=> (cosine distance) operator.
    """
    __tablename__ = "response_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # The original user query text
    query_text = Column(Text, nullable=False)

    # query_embedding is a pgvector column managed via raw SQL (not mapped here)
    # since SQLAlchemy doesn't natively handle variable-dimension vectors well

    # The AI's complete response text
    response_text = Column(Text, nullable=False)

    # Which tool was used to generate the response (vector_search, sql_analysis, etc.)
    tool_used = Column(String(100), nullable=True)

    # Full tool_details JSON from the original response
    tool_details = Column(JSON, nullable=True)

    # Response source: 'rag', 'direct', 'hybrid'
    response_source = Column(String(20), nullable=True)

    # Which embedding model produced the query_embedding
    embedding_model = Column(String(100), nullable=True)

    # Which LLM model generated the response (e.g. 'ollama:gemma3:12b', 'openrouter:openai/gpt-4o')
    llm_model = Column(String(100), nullable=True)

    # Document IDs scope filter (null = all documents)
    document_ids = Column(JSON, nullable=True)

    # Cache hit tracking
    hit_count = Column(Integer, server_default='0', nullable=False)
    last_hit_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('idx_response_cache_created', 'created_at'),
        Index('idx_response_cache_expires', 'expires_at'),
        Index('idx_response_cache_embedding_model', 'embedding_model'),
        Index('idx_response_cache_llm_model', 'llm_model'),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "query_text": self.query_text,
            "response_text": self.response_text,
            "tool_used": self.tool_used,
            "tool_details": self.tool_details,
            "response_source": self.response_source,
            "embedding_model": self.embedding_model,
            "llm_model": self.llm_model,
            "document_ids": self.document_ids,
            "hit_count": self.hit_count,
            "last_hit_at": self.last_hit_at.isoformat() if self.last_hit_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
