"""
Response Cache Service (Feature #352).

Provides semantic response caching: stores complete AI responses keyed by
query embedding similarity. Uses pgvector's cosine distance operator for
fast similarity matching against cached query embeddings.

Uses sync SessionLocal for lookup/store (called from ai_service.chat() which
mixes sync/async), and async_engine for admin endpoints.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import text

from core.database import SessionLocal, async_engine

logger = logging.getLogger(__name__)


class ResponseCacheService:
    """Service for semantic response caching using pgvector similarity search."""

    def lookup(
        self,
        query_embedding: List[float],
        threshold: float,
        document_ids: Optional[List[str]],
        embedding_model: str,
        llm_model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Look up a cached response by query embedding similarity.

        Uses pgvector's <=> (cosine distance) operator. Returns the best match
        if its similarity >= threshold, otherwise None.

        Args:
            query_embedding: The query's embedding vector
            threshold: Minimum cosine similarity (0.0-1.0) to consider a cache hit
            document_ids: Document scope filter (None = all documents)
            embedding_model: Must match the model used for cached embeddings
            llm_model: Must match the LLM model that generated the cached response

        Returns:
            Dict with cached response fields + similarity score, or None
        """
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        # Build document_ids filter
        if document_ids is not None:
            doc_ids_json = json.dumps(sorted(document_ids))
            doc_filter = "AND CAST(document_ids AS text) = :doc_ids"
        else:
            doc_ids_json = None
            doc_filter = "AND document_ids IS NULL"

        # Build llm_model filter
        if llm_model:
            llm_filter = "AND llm_model = :llm_model"
        else:
            llm_filter = ""

        sql = text(f"""
            SELECT id, query_text, response_text, tool_used, tool_details,
                   response_source, embedding_model, llm_model, document_ids,
                   hit_count, last_hit_at, created_at, expires_at,
                   1 - (query_embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM response_cache
            WHERE (expires_at IS NULL OR expires_at > now())
              AND embedding_model = :model
              {llm_filter}
              {doc_filter}
              AND query_embedding IS NOT NULL
            ORDER BY query_embedding <=> CAST(:embedding AS vector)
            LIMIT 1
        """)

        params = {
            "embedding": embedding_str,
            "model": embedding_model,
        }
        if llm_model:
            params["llm_model"] = llm_model
        if doc_ids_json is not None:
            params["doc_ids"] = doc_ids_json

        session = SessionLocal()
        try:
            result = session.execute(sql, params)
            row = result.fetchone()

            if row is None:
                return None

            similarity = float(row.similarity)
            if similarity < threshold:
                logger.debug(
                    f"[Feature #352] Cache near-miss: similarity={similarity:.4f} < threshold={threshold}"
                )
                return None

            # Cache hit! Increment hit_count and update last_hit_at
            update_sql = text("""
                UPDATE response_cache
                SET hit_count = hit_count + 1, last_hit_at = now()
                WHERE id = :cache_id
            """)
            session.execute(update_sql, {"cache_id": row.id})
            session.commit()

            logger.info(
                f"[Feature #352] Cache HIT id={row.id} similarity={similarity:.4f} "
                f"hits={row.hit_count + 1} llm={row.llm_model}"
            )

            return {
                "id": row.id,
                "query_text": row.query_text,
                "response_text": row.response_text,
                "tool_used": row.tool_used,
                "tool_details": row.tool_details,
                "response_source": row.response_source,
                "embedding_model": row.embedding_model,
                "llm_model": row.llm_model,
                "document_ids": row.document_ids,
                "similarity": similarity,
            }
        except Exception as e:
            session.rollback()
            logger.error(f"[Feature #352] Cache lookup error: {e}")
            return None
        finally:
            session.close()

    def store(
        self,
        query_text: str,
        query_embedding: List[float],
        response_text: str,
        tool_used: Optional[str],
        tool_details: Optional[Dict],
        response_source: Optional[str],
        embedding_model: str,
        document_ids: Optional[List[str]],
        llm_model: Optional[str] = None,
        ttl_hours: int = 24,
    ) -> None:
        """
        Store a response in the cache.

        Args:
            query_text: The original user query
            query_embedding: The query's embedding vector
            response_text: The AI's complete response
            tool_used: Which tool generated the response
            tool_details: Full tool_details from the response
            response_source: 'rag', 'direct', etc.
            embedding_model: Which model produced the embedding
            document_ids: Document scope filter (None = all documents)
            llm_model: Which LLM model generated the response
            ttl_hours: Hours until this cache entry expires
        """
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        doc_ids_json = json.dumps(sorted(document_ids)) if document_ids else None
        tool_details_json = json.dumps(tool_details) if tool_details else None
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

        sql = text("""
            INSERT INTO response_cache
                (query_text, query_embedding, response_text, tool_used, tool_details,
                 response_source, embedding_model, llm_model, document_ids, expires_at)
            VALUES
                (:query_text, CAST(:embedding AS vector), :response_text, :tool_used,
                 CAST(:tool_details AS jsonb), :response_source, :model, :llm_model,
                 CAST(:doc_ids AS jsonb), :expires_at)
        """)

        params = {
            "query_text": query_text,
            "embedding": embedding_str,
            "response_text": response_text,
            "tool_used": tool_used,
            "tool_details": tool_details_json,
            "response_source": response_source,
            "model": embedding_model,
            "llm_model": llm_model,
            "doc_ids": doc_ids_json,
            "expires_at": expires_at,
        }

        session = SessionLocal()
        try:
            session.execute(sql, params)
            session.commit()
            logger.info(
                f"[Feature #352] Cached response for query: '{query_text[:80]}...' "
                f"(tool={tool_used}, llm={llm_model}, ttl={ttl_hours}h)"
            )
        except Exception as e:
            session.rollback()
            logger.error(f"[Feature #352] Cache store error: {e}")
        finally:
            session.close()

    def invalidate_all(self) -> int:
        """Delete all cache entries. Returns count deleted."""
        session = SessionLocal()
        try:
            result = session.execute(text("DELETE FROM response_cache"))
            count = result.rowcount
            session.commit()
            logger.info(f"[Feature #352] Invalidated all cache entries: {count} deleted")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"[Feature #352] Cache invalidate_all error: {e}")
            return 0
        finally:
            session.close()

    def invalidate_by_document(self, document_id: str) -> int:
        """
        Invalidate cache entries that may reference a specific document.

        Deletes entries where:
        - document_ids contains this doc ID, OR
        - document_ids IS NULL (all-docs scope, affected by any doc change)
        """
        sql = text("""
            DELETE FROM response_cache
            WHERE document_ids IS NULL
               OR document_ids::text LIKE :pattern
        """)
        pattern = f'%"{document_id}"%'

        session = SessionLocal()
        try:
            result = session.execute(sql, {"pattern": pattern})
            count = result.rowcount
            session.commit()
            if count > 0:
                logger.info(
                    f"[Feature #352] Invalidated {count} cache entries for document {document_id}"
                )
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"[Feature #352] Cache invalidate_by_document error: {e}")
            return 0
        finally:
            session.close()

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics (async, for admin endpoints)."""
        try:
            async with async_engine.connect() as conn:
                result = await conn.execute(text("""
                    SELECT
                        COUNT(*) AS total_entries,
                        COALESCE(SUM(hit_count), 0) AS total_hits,
                        COALESCE(AVG(hit_count), 0) AS avg_hits,
                        MIN(created_at) AS oldest_entry,
                        COUNT(*) FILTER (WHERE expires_at IS NOT NULL AND expires_at < now()) AS expired_entries
                    FROM response_cache
                """))
                row = result.fetchone()

                return {
                    "total_entries": row.total_entries if row else 0,
                    "total_hits": int(row.total_hits) if row else 0,
                    "avg_hits": round(float(row.avg_hits), 2) if row else 0,
                    "oldest_entry": row.oldest_entry.isoformat() if row and row.oldest_entry else None,
                    "expired_entries": row.expired_entries if row else 0,
                }
        except Exception as e:
            logger.error(f"[Feature #352] Cache get_stats error: {e}")
            return {
                "total_entries": 0,
                "total_hits": 0,
                "avg_hits": 0,
                "oldest_entry": None,
                "expired_entries": 0,
                "error": str(e),
            }

    def cleanup_expired(self) -> int:
        """Delete expired cache entries. Returns count deleted."""
        session = SessionLocal()
        try:
            result = session.execute(
                text("DELETE FROM response_cache WHERE expires_at IS NOT NULL AND expires_at < now()")
            )
            count = result.rowcount
            session.commit()
            if count > 0:
                logger.info(f"[Feature #352] Cleaned up {count} expired cache entries")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"[Feature #352] Cache cleanup_expired error: {e}")
            return 0
        finally:
            session.close()


# Singleton instance
response_cache_service = ResponseCacheService()
