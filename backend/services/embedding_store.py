"""
Persistent embedding storage with PostgreSQL/pgvector (primary) and SQLite (fallback).

When PostgreSQL with pgvector is available, uses it for efficient vector similarity search.
When PostgreSQL is unavailable, falls back to SQLite for persistent storage with
Python-based cosine similarity computation.

In both cases, embeddings persist across backend restarts.

RACE CONDITION FIX (Feature #119):
- Removed application-level _chunk_counter
- Using database-generated IDs (SERIAL for PostgreSQL, AUTOINCREMENT for SQLite)
- chunk_id is now derived from database-generated ID after insertion
"""

import json
import logging
import math
import os
import sqlite3
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SQLiteEmbeddingStore:
    """
    SQLite-backed persistent embedding storage.
    Used as fallback when PostgreSQL/pgvector is not available.
    Stores embeddings as JSON-serialized vectors in a SQLite database file.

    Race condition fix: Uses AUTOINCREMENT for thread-safe ID generation.
    """

    def __init__(self, db_path: str = None):
        """Initialize SQLite embedding store."""
        if db_path is None:
            # Store in the backend directory
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(backend_dir, "embeddings.db")

        self._db_path = db_path
        self._lock = threading.Lock()

        # Initialize database
        self._initialize_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a new SQLite connection (one per thread for thread safety)."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read performance
        conn.execute("PRAGMA synchronous=NORMAL")  # Good balance of safety and speed
        return conn

    def _initialize_db(self):
        """Create tables if they don't exist."""
        try:
            conn = self._get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS document_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL UNIQUE,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_embeddings_document_id
                ON document_embeddings(document_id)
            """)
            conn.commit()

            # Get count for logging only
            row = conn.execute("SELECT COUNT(*) as cnt FROM document_embeddings").fetchone()
            existing_count = row['cnt'] if row else 0

            conn.close()
            logger.info(f"SQLite embedding store initialized at {self._db_path} "
                        f"(existing chunks: {existing_count})")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite embedding store: {e}")
            raise

    def add_chunks(self, document_id: str, chunks: List[Dict]) -> int:
        """Add text chunks with embeddings for a document."""
        with self._lock:
            try:
                conn = self._get_connection()
                added_count = 0
                for chunk_data in chunks:
                    embedding_json = json.dumps(chunk_data.get("embedding", []))
                    metadata_json = json.dumps(chunk_data.get("metadata", {}))

                    # Insert without chunk_id first
                    cursor = conn.execute(
                        """INSERT INTO document_embeddings
                           (document_id, chunk_id, text, embedding, metadata)
                           VALUES (?, ?, ?, ?, ?)""",
                        (document_id, "temp", chunk_data.get("text", ""),
                         embedding_json, metadata_json)
                    )

                    # Get the database-generated ID
                    row_id = cursor.lastrowid
                    chunk_id = f"chunk_{row_id}"

                    # Update with the correct chunk_id
                    conn.execute(
                        "UPDATE document_embeddings SET chunk_id = ? WHERE id = ?",
                        (chunk_id, row_id)
                    )

                    added_count += 1

                conn.commit()
                conn.close()
                logger.info(f"Added {added_count} chunks for document {document_id} to SQLite")
                return added_count
            except Exception as e:
                logger.error(f"SQLite error adding chunks: {e}")
                return 0

    def get_chunks(self, document_id: str) -> List[Dict]:
        """Get all chunks for a document."""
        try:
            conn = self._get_connection()
            rows = conn.execute(
                "SELECT chunk_id, text, embedding, metadata FROM document_embeddings WHERE document_id = ?",
                (document_id,)
            ).fetchall()
            conn.close()

            return [
                {
                    "chunk_id": row['chunk_id'],
                    "text": row['text'],
                    "embedding": json.loads(row['embedding']),
                    "metadata": json.loads(row['metadata']) if row['metadata'] else {}
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"SQLite error getting chunks: {e}")
            return []

    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict]:
        """
        Feature #279: Get a single chunk by its chunk_id.

        This provides direct lookup by chunk_id for the fallback chain
        when recovering missing chunk text.

        Args:
            chunk_id: The unique chunk identifier (e.g., 'chunk_123')

        Returns:
            Dict with chunk_id, document_id, text, embedding, metadata, or None if not found
        """
        try:
            conn = self._get_connection()
            row = conn.execute(
                "SELECT document_id, chunk_id, text, embedding, metadata FROM document_embeddings WHERE chunk_id = ?",
                (chunk_id,)
            ).fetchone()
            conn.close()

            if row:
                return {
                    "chunk_id": row['chunk_id'],
                    "document_id": row['document_id'],
                    "text": row['text'],
                    "embedding": json.loads(row['embedding']),
                    "metadata": json.loads(row['metadata']) if row['metadata'] else {}
                }
            return None
        except Exception as e:
            logger.error(f"[Feature #279] SQLite error getting chunk by id {chunk_id}: {e}")
            return None

    def get_all_chunks(self) -> List[Dict]:
        """Get all chunks from all documents."""
        try:
            conn = self._get_connection()
            rows = conn.execute(
                "SELECT document_id, chunk_id, text, embedding, metadata FROM document_embeddings"
            ).fetchall()
            conn.close()

            return [
                {
                    "chunk_id": row['chunk_id'],
                    "document_id": row['document_id'],
                    "text": row['text'],
                    "embedding": json.loads(row['embedding']),
                    "metadata": json.loads(row['metadata']) if row['metadata'] else {}
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"SQLite error getting all chunks: {e}")
            return []

    def search_similar(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        document_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """Search for similar chunks using cosine similarity (computed in Python)."""
        try:
            conn = self._get_connection()
            if document_ids:
                placeholders = ','.join('?' for _ in document_ids)
                rows = conn.execute(
                    f"SELECT document_id, chunk_id, text, embedding, metadata "
                    f"FROM document_embeddings WHERE document_id IN ({placeholders})",
                    document_ids
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT document_id, chunk_id, text, embedding, metadata FROM document_embeddings"
                ).fetchall()
            conn.close()

            results = []
            skipped_count = 0
            query_dim = len(query_embedding)

            for row in rows:
                embedding = json.loads(row['embedding'])

                # Validate embedding integrity
                validation_result = self._validate_embedding(
                    embedding,
                    query_dim,
                    row['chunk_id'],
                    row['document_id']
                )

                if not validation_result["valid"]:
                    skipped_count += 1
                    logger.warning(
                        f"Skipping invalid embedding: {validation_result['reason']} "
                        f"(document_id={row['document_id']}, chunk_id={row['chunk_id']})"
                    )
                    continue

                similarity = self._cosine_similarity(query_embedding, embedding)
                results.append({
                    "chunk_id": row['chunk_id'],
                    "document_id": row['document_id'],
                    "text": row['text'],
                    "embedding": embedding,
                    "metadata": json.loads(row['metadata']) if row['metadata'] else {},
                    "similarity": similarity
                })

            if skipped_count > 0:
                logger.info(f"Skipped {skipped_count} invalid embeddings during similarity search")

            results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
            return results[:top_k]
        except Exception as e:
            logger.error(f"SQLite error during similarity search: {e}")
            return []

    def delete_document(self, document_id: str) -> bool:
        """Delete all chunks for a document."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.execute(
                    "DELETE FROM document_embeddings WHERE document_id = ?",
                    (document_id,)
                )
                conn.commit()
                deleted = cursor.rowcount
                conn.close()
                logger.info(f"Deleted {deleted} chunks for document {document_id} from SQLite")
                return deleted > 0
            except Exception as e:
                logger.error(f"SQLite error deleting document chunks: {e}")
                return False

    def update_document_title(self, document_id: str, new_title: str) -> int:
        """Update document_title in metadata for all chunks of a document."""
        with self._lock:
            try:
                conn = self._get_connection()
                # Get all chunks for this document
                rows = conn.execute(
                    "SELECT id, metadata FROM document_embeddings WHERE document_id = ?",
                    (document_id,)
                ).fetchall()

                updated_count = 0
                for row in rows:
                    chunk_id = row['id']
                    metadata_json = row['metadata']
                    metadata = json.loads(metadata_json) if metadata_json else {}

                    # Update the document_title in metadata
                    metadata['document_title'] = new_title

                    # Save back to database
                    conn.execute(
                        "UPDATE document_embeddings SET metadata = ? WHERE id = ?",
                        (json.dumps(metadata), chunk_id)
                    )
                    updated_count += 1

                conn.commit()
                conn.close()
                logger.info(f"Updated title in {updated_count} chunks for document {document_id} in SQLite")
                return updated_count
            except Exception as e:
                logger.error(f"SQLite error updating document title: {e}")
                return 0

    def get_embedding_count_for_document(self, document_id: str) -> int:
        """Get the number of embeddings for a specific document."""
        try:
            conn = self._get_connection()
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM document_embeddings WHERE document_id = ?",
                (document_id,)
            ).fetchone()
            conn.close()
            return row['cnt'] if row else 0
        except Exception as e:
            logger.error(f"SQLite error getting embedding count for document {document_id}: {e}")
            return 0

    def get_document_count(self) -> int:
        """Get the number of documents with embeddings."""
        try:
            conn = self._get_connection()
            row = conn.execute(
                "SELECT COUNT(DISTINCT document_id) as cnt FROM document_embeddings"
            ).fetchone()
            conn.close()
            return row['cnt'] if row else 0
        except Exception as e:
            logger.error(f"SQLite error getting document count: {e}")
            return 0

    def get_chunk_count(self) -> int:
        """Get the total number of chunks."""
        try:
            conn = self._get_connection()
            row = conn.execute("SELECT COUNT(*) as cnt FROM document_embeddings").fetchone()
            conn.close()
            return row['cnt'] if row else 0
        except Exception as e:
            logger.error(f"SQLite error getting chunk count: {e}")
            return 0

    def get_integrity_stats(self) -> Dict:
        """
        Get embedding integrity statistics.

        Returns:
            Dict with:
                - total_chunks (int): Total number of embeddings
                - valid_chunks (int): Number of valid embeddings
                - invalid_chunks (int): Number of invalid embeddings
                - invalid_reasons (Dict[str, int]): Map of reason -> count
                - dimensions (Dict[int, int]): Map of dimension -> count
        """
        try:
            conn = self._get_connection()
            rows = conn.execute("SELECT chunk_id, document_id, embedding FROM document_embeddings").fetchall()
            conn.close()

            if not rows:
                return {
                    "total_chunks": 0,
                    "valid_chunks": 0,
                    "invalid_chunks": 0,
                    "invalid_reasons": {},
                    "dimensions": {}
                }

            total = len(rows)
            valid = 0
            invalid = 0
            invalid_reasons = {}
            dimension_counts = {}

            # Use first valid embedding's dimension as expected dimension
            expected_dim = None
            for row in rows:
                embedding = json.loads(row['embedding'])
                if embedding:
                    expected_dim = len(embedding)
                    break

            if expected_dim is None:
                # No valid embeddings found
                expected_dim = 0

            for row in rows:
                embedding = json.loads(row['embedding'])
                dim = len(embedding) if embedding else 0
                dimension_counts[dim] = dimension_counts.get(dim, 0) + 1

                validation = self._validate_embedding(
                    embedding,
                    expected_dim,
                    row['chunk_id'],
                    row['document_id']
                )

                if validation["valid"]:
                    valid += 1
                else:
                    invalid += 1
                    reason = validation["reason"]
                    invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1

            return {
                "total_chunks": total,
                "valid_chunks": valid,
                "invalid_chunks": invalid,
                "invalid_reasons": invalid_reasons,
                "dimensions": dimension_counts
            }
        except Exception as e:
            logger.error(f"SQLite error getting integrity stats: {e}")
            return {
                "total_chunks": 0,
                "valid_chunks": 0,
                "invalid_chunks": 0,
                "invalid_reasons": {"error": str(e)},
                "dimensions": {}
            }

    def check_dimension_consistency(self) -> Dict:
        """
        Check embedding dimension consistency across all stored documents.

        Returns:
            Dict with:
                - consistent (bool): True if all embeddings have the same dimension
                - dimensions (Dict[int, int]): Map of dimension -> count of chunks
                - embedding_sources (Dict[str, int]): Map of embedding_source -> count
                - warning (str): Warning message if inconsistent
        """
        try:
            conn = self._get_connection()
            rows = conn.execute("SELECT embedding, metadata FROM document_embeddings").fetchall()
            conn.close()

            if not rows:
                return {"consistent": True, "dimensions": {}, "embedding_sources": {}}

            # Count dimensions and sources
            dimension_counts = {}
            source_counts = {}

            for row in rows:
                # Get dimension
                embedding = json.loads(row['embedding'])
                dim = len(embedding) if embedding else 0
                dimension_counts[dim] = dimension_counts.get(dim, 0) + 1

                # Get embedding source from metadata
                metadata = json.loads(row['metadata']) if row['metadata'] else {}
                source = metadata.get("embedding_source", "unknown")
                source_counts[source] = source_counts.get(source, 0) + 1

            # Check consistency
            consistent = len(dimension_counts) == 1
            warning = None

            if not consistent:
                dim_list = ", ".join([f"{dim}d ({count} chunks)" for dim, count in sorted(dimension_counts.items())])
                warning = (
                    f"Inconsistent embedding dimensions detected! Found {len(dimension_counts)} different dimensions: {dim_list}. "
                    f"This will cause search errors. Please delete all documents and re-embed them with the same model."
                )
                logger.warning(warning)

            return {
                "consistent": consistent,
                "dimensions": dimension_counts,
                "embedding_sources": source_counts,
                "warning": warning
            }
        except Exception as e:
            logger.error(f"SQLite error checking dimension consistency: {e}")
            return {"consistent": True, "dimensions": {}, "embedding_sources": {}, "error": str(e)}

    def clear(self):
        """Clear all embeddings."""
        with self._lock:
            try:
                conn = self._get_connection()
                conn.execute("DELETE FROM document_embeddings")
                conn.commit()
                conn.close()
                logger.info("Cleared all embeddings from SQLite")
            except Exception as e:
                logger.error(f"SQLite error clearing embeddings: {e}")

    @staticmethod
    def _validate_embedding(
        embedding: List[float],
        expected_dimension: int,
        chunk_id: str,
        document_id: str
    ) -> Dict:
        """
        Validate embedding vector integrity.

        Returns:
            Dict with 'valid' (bool) and 'reason' (str) fields.
        """
        # Check if embedding exists
        if not embedding:
            return {"valid": False, "reason": "Empty embedding vector"}

        # Check dimension match
        if len(embedding) != expected_dimension:
            return {
                "valid": False,
                "reason": f"Dimension mismatch: expected {expected_dimension}, got {len(embedding)}"
            }

        # Check for invalid float values (NaN, Inf)
        if not all(math.isfinite(x) for x in embedding):
            return {"valid": False, "reason": "Contains NaN or Inf values"}

        # Check for all-zero vector
        if all(x == 0.0 for x in embedding):
            return {"valid": False, "reason": "All-zero vector"}

        return {"valid": True, "reason": ""}

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)


class PostgreSQLEmbeddingStore:
    """
    PostgreSQL-backed embedding storage with pgvector for persistent vector storage.
    Falls back to SQLite persistent storage when PostgreSQL is unavailable.
    All embeddings persist across backend restarts in both modes.

    Race condition fix: Uses SERIAL/SEQUENCE for thread-safe ID generation.
    """

    def __init__(self):
        """Initialize the embedding store with PostgreSQL or SQLite fallback."""
        self._db_available = False
        self._sqlite_store = None  # SQLite fallback (persistent)

        # Try to initialize PostgreSQL
        self._initialize_db()

        # If PostgreSQL not available, initialize SQLite fallback
        if not self._db_available:
            self._initialize_sqlite_fallback()

    def _initialize_db(self):
        """Initialize PostgreSQL database connection and create tables if needed."""
        try:
            from core.database import SessionLocal, test_connection, init_db_sync

            # Test connection
            if not test_connection():
                logger.warning("PostgreSQL not available")
                return

            # Initialize database (create extension and tables)
            if init_db_sync():
                self._db_available = True

                # Get count for logging only
                with SessionLocal() as session:
                    from sqlalchemy import text as sa_text
                    count = session.execute(
                        sa_text("SELECT COUNT(*) FROM document_embeddings")
                    ).scalar()
                    logger.info(f"PostgreSQL embedding store initialized successfully (existing chunks: {count or 0})")
            else:
                logger.warning("Database initialization failed")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL embedding store: {e}")

    def _initialize_sqlite_fallback(self):
        """Initialize SQLite fallback for persistent storage without PostgreSQL."""
        try:
            self._sqlite_store = SQLiteEmbeddingStore()
            logger.info("Using SQLite persistent fallback for embedding storage")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite fallback: {e}")
            # Last resort: in-memory (should never happen since SQLite is always available)
            self._sqlite_store = None

    def add_chunks(
        self,
        document_id: str,
        chunks: List[Dict],
    ) -> int:
        """Add text chunks with embeddings for a document."""
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.add_chunks(document_id, chunks)
            return 0

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding
            from sqlalchemy import text as sa_text

            with SessionLocal() as session:
                added_count = 0
                for chunk_data in chunks:
                    # Create embedding without chunk_id (will use temp value)
                    embedding = DocumentEmbedding(
                        document_id=document_id,
                        chunk_id="temp",  # Temporary, will be updated
                        text=chunk_data.get("text", ""),
                        embedding=chunk_data.get("embedding", []),
                        chunk_metadata=chunk_data.get("metadata", {})
                    )
                    session.add(embedding)
                    session.flush()  # Get the database-generated ID

                    # Now update with the correct chunk_id based on database ID
                    embedding.chunk_id = f"chunk_{embedding.id}"
                    added_count += 1

                session.commit()
                logger.info(f"Added {added_count} chunks for document {document_id} to PostgreSQL")
                return added_count
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"[Feature #226] Database error adding chunks: {e}")
            logger.error(f"[Feature #226] Full traceback:\n{error_details}")

            # Feature #226: Check for dimension mismatch error
            error_str = str(e).lower()
            if 'dimension' in error_str or 'expected' in error_str:
                logger.error(
                    f"[Feature #226] DIMENSION MISMATCH DETECTED! "
                    f"This typically occurs when the embedding model was changed. "
                    f"The database table may have a fixed vector dimension that doesn't match "
                    f"the new embedding model's output. Document: {document_id}, "
                    f"Chunks to store: {len(chunks)}, "
                    f"First chunk embedding dimension: {len(chunks[0].get('embedding', [])) if chunks else 'N/A'}"
                )

            if self._sqlite_store:
                logger.info(f"[Feature #226] Falling back to SQLite store for document {document_id}")
                return self._sqlite_store.add_chunks(document_id, chunks)
            return 0

    def get_chunks(self, document_id: str) -> List[Dict]:
        """Get all chunks for a document."""
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.get_chunks(document_id)
            return []

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                embeddings = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.document_id == document_id
                ).all()

                return [
                    {
                        "chunk_id": emb.chunk_id,
                        "text": emb.text,
                        "embedding": list(emb.embedding) if emb.embedding is not None else [],
                        "metadata": emb.chunk_metadata or {}
                    }
                    for emb in embeddings
                ]
        except Exception as e:
            logger.error(f"Database error getting chunks: {e}")
            if self._sqlite_store:
                return self._sqlite_store.get_chunks(document_id)
            return []

    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict]:
        """
        Feature #279: Get a single chunk by its chunk_id.

        This provides direct lookup by chunk_id for the fallback chain
        when recovering missing chunk text. More efficient than get_chunks()
        when you only need a single chunk.

        Args:
            chunk_id: The unique chunk identifier (e.g., 'chunk_123')

        Returns:
            Dict with chunk_id, document_id, text, embedding, metadata, or None if not found
        """
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.get_chunk_by_id(chunk_id)
            return None

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                emb = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.chunk_id == chunk_id
                ).first()

                if emb:
                    return {
                        "chunk_id": emb.chunk_id,
                        "document_id": emb.document_id,
                        "text": emb.text,
                        "embedding": list(emb.embedding) if emb.embedding is not None else [],
                        "metadata": emb.chunk_metadata or {}
                    }
                return None
        except Exception as e:
            logger.error(f"[Feature #279] Database error getting chunk by id {chunk_id}: {e}")
            if self._sqlite_store:
                return self._sqlite_store.get_chunk_by_id(chunk_id)
            return None

    def get_all_chunks(self) -> List[Dict]:
        """Get all chunks from all documents with document_id attached."""
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.get_all_chunks()
            return []

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                embeddings = session.query(DocumentEmbedding).all()

                return [
                    {
                        "chunk_id": emb.chunk_id,
                        "document_id": emb.document_id,
                        "text": emb.text,
                        "embedding": list(emb.embedding) if emb.embedding is not None else [],
                        "metadata": emb.chunk_metadata or {}
                    }
                    for emb in embeddings
                ]
        except Exception as e:
            logger.error(f"Database error getting all chunks: {e}")
            if self._sqlite_store:
                return self._sqlite_store.get_all_chunks()
            return []

    def search_similar(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        document_ids: Optional[List[str]] = None,
        filter_ready_documents: bool = True
    ) -> List[Dict]:
        """Search for similar chunks using cosine similarity.

        Args:
            query_embedding: The query vector to search for.
            top_k: Maximum number of results to return.
            document_ids: Optional list of document IDs to filter by.
            filter_ready_documents: Feature #289 - If True, only search embeddings
                from documents with status='ready'. Prevents querying documents
                that are still being processed.
        """
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.search_similar(query_embedding, top_k, document_ids)
            return []

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding, EMBEDDING_STATUS_ACTIVE
            from models.db_models import DBDocument, DOCUMENT_STATUS_READY
            from sqlalchemy import text as sa_text

            with SessionLocal() as session:
                # Fetch all candidates first (before pgvector processing)
                # Feature #249: Only search active embeddings (exclude pending_delete and archived)
                query_base = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.status == EMBEDDING_STATUS_ACTIVE
                )

                # Feature #289: Filter to only include embeddings from ready documents
                if filter_ready_documents:
                    query_base = query_base.join(
                        DBDocument,
                        DocumentEmbedding.document_id == DBDocument.id
                    ).filter(
                        DBDocument.status == DOCUMENT_STATUS_READY
                    )

                if document_ids:
                    query_base = query_base.filter(DocumentEmbedding.document_id.in_(document_ids))

                all_embeddings = query_base.all()

                # Validate embeddings before similarity computation
                valid_embeddings = []
                skipped_count = 0
                query_dim = len(query_embedding)

                for emb in all_embeddings:
                    embedding_list = list(emb.embedding) if emb.embedding is not None else []

                    validation_result = self._validate_embedding(
                        embedding_list,
                        query_dim,
                        emb.chunk_id,
                        emb.document_id
                    )

                    if not validation_result["valid"]:
                        skipped_count += 1
                        logger.warning(
                            f"Skipping invalid embedding: {validation_result['reason']} "
                            f"(document_id={emb.document_id}, chunk_id={emb.chunk_id})"
                        )
                        continue

                    valid_embeddings.append(emb)

                if skipped_count > 0:
                    logger.info(f"Skipped {skipped_count} invalid embeddings during similarity search")

                # Now compute similarity only for valid embeddings
                if not valid_embeddings:
                    return []

                valid_ids = [emb.id for emb in valid_embeddings]
                query = session.query(
                    DocumentEmbedding,
                    (1 - DocumentEmbedding.embedding.cosine_distance(query_embedding)).label('similarity')
                ).filter(DocumentEmbedding.id.in_(valid_ids))

                query = query.order_by(sa_text('similarity DESC')).limit(top_k)
                results = query.all()

                return [
                    {
                        "chunk_id": emb.chunk_id,
                        "document_id": emb.document_id,
                        "text": emb.text,
                        "embedding": list(emb.embedding) if emb.embedding is not None else [],
                        "metadata": emb.chunk_metadata or {},
                        "similarity": float(similarity)
                    }
                    for emb, similarity in results
                ]
        except Exception as e:
            logger.error(f"Database error during similarity search: {e}")
            if self._sqlite_store:
                return self._sqlite_store.search_similar(query_embedding, top_k, document_ids)
            return []

    def delete_document(self, document_id: str) -> bool:
        """Delete all chunks for a document."""
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.delete_document(document_id)
            return False

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                deleted = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.document_id == document_id
                ).delete()
                session.commit()
                logger.info(f"Deleted {deleted} chunks for document {document_id}")
                return deleted > 0
        except Exception as e:
            logger.error(f"Database error deleting document chunks: {e}")
            if self._sqlite_store:
                return self._sqlite_store.delete_document(document_id)
            return False

    def soft_delete_document(self, document_id: str) -> int:
        """
        Feature #249: Soft delete embeddings for a document.

        Instead of deleting, marks embeddings as 'pending_delete' with a timestamp.
        Use this during re-embed to preserve old embeddings until new ones are verified.

        Args:
            document_id: The document ID whose embeddings should be soft-deleted

        Returns:
            Number of embeddings marked as pending_delete
        """
        if not self._db_available:
            # SQLite fallback doesn't support soft delete - use hard delete
            if self._sqlite_store:
                logger.warning(f"[Feature #249] SQLite fallback - using hard delete for document {document_id}")
                return self._sqlite_store.delete_document(document_id)
            return 0

        try:
            from core.database import SessionLocal
            from models.embedding import (
                DocumentEmbedding,
                EMBEDDING_STATUS_ACTIVE,
                EMBEDDING_STATUS_PENDING_DELETE
            )
            from datetime import datetime, timezone

            with SessionLocal() as session:
                # Only mark active embeddings as pending_delete
                updated = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.document_id == document_id,
                    DocumentEmbedding.status == EMBEDDING_STATUS_ACTIVE
                ).update({
                    DocumentEmbedding.status: EMBEDDING_STATUS_PENDING_DELETE,
                    DocumentEmbedding.pending_delete_at: datetime.now(timezone.utc)
                })
                session.commit()
                logger.info(f"[Feature #249] Soft-deleted {updated} embeddings for document {document_id}")
                return updated
        except Exception as e:
            logger.error(f"[Feature #249] Database error soft-deleting document {document_id}: {e}")
            return 0

    def restore_soft_deleted(self, document_id: str) -> int:
        """
        Feature #249: Restore soft-deleted embeddings for a document.

        Changes pending_delete embeddings back to active status.
        Use this when re-embedding fails to recover the original embeddings.

        Args:
            document_id: The document ID whose embeddings should be restored

        Returns:
            Number of embeddings restored to active status
        """
        if not self._db_available:
            # SQLite fallback doesn't support soft delete
            logger.warning(f"[Feature #249] SQLite fallback - cannot restore soft-deleted for document {document_id}")
            return 0

        try:
            from core.database import SessionLocal
            from models.embedding import (
                DocumentEmbedding,
                EMBEDDING_STATUS_ACTIVE,
                EMBEDDING_STATUS_PENDING_DELETE
            )

            with SessionLocal() as session:
                # Restore pending_delete embeddings back to active
                updated = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.document_id == document_id,
                    DocumentEmbedding.status == EMBEDDING_STATUS_PENDING_DELETE
                ).update({
                    DocumentEmbedding.status: EMBEDDING_STATUS_ACTIVE,
                    DocumentEmbedding.pending_delete_at: None
                })
                session.commit()
                logger.info(f"[Feature #249] Restored {updated} soft-deleted embeddings for document {document_id}")
                return updated
        except Exception as e:
            logger.error(f"[Feature #249] Database error restoring soft-deleted for document {document_id}: {e}")
            return 0

    def permanently_delete_pending(self, document_id: str) -> int:
        """
        Feature #249: Permanently delete pending_delete embeddings for a document.

        Call this after new embeddings are verified to work correctly.

        Args:
            document_id: The document ID whose pending_delete embeddings should be removed

        Returns:
            Number of embeddings permanently deleted
        """
        if not self._db_available:
            # SQLite fallback - nothing to do (already hard deleted)
            return 0

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding, EMBEDDING_STATUS_PENDING_DELETE

            with SessionLocal() as session:
                deleted = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.document_id == document_id,
                    DocumentEmbedding.status == EMBEDDING_STATUS_PENDING_DELETE
                ).delete()
                session.commit()
                logger.info(f"[Feature #249] Permanently deleted {deleted} pending embeddings for document {document_id}")
                return deleted
        except Exception as e:
            logger.error(f"[Feature #249] Database error permanently deleting pending for document {document_id}: {e}")
            return 0

    def cleanup_stale_pending_delete(self, hours: int = 24) -> int:
        """
        Feature #249: Cleanup stale pending_delete embeddings.

        Permanently deletes embeddings that have been in pending_delete status
        for more than the specified hours. Used for cleanup of aborted operations.

        Args:
            hours: Number of hours after which pending_delete embeddings are considered stale

        Returns:
            Number of embeddings cleaned up
        """
        if not self._db_available:
            return 0

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding, EMBEDDING_STATUS_PENDING_DELETE
            from datetime import datetime, timezone, timedelta

            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

            with SessionLocal() as session:
                deleted = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.status == EMBEDDING_STATUS_PENDING_DELETE,
                    DocumentEmbedding.pending_delete_at.isnot(None),
                    DocumentEmbedding.pending_delete_at < cutoff_time
                ).delete()
                session.commit()
                if deleted > 0:
                    logger.info(f"[Feature #249] Cleaned up {deleted} stale pending_delete embeddings (older than {hours}h)")
                return deleted
        except Exception as e:
            logger.error(f"[Feature #249] Database error cleaning up stale pending_delete: {e}")
            return 0

    def update_document_title(self, document_id: str, new_title: str) -> int:
        """Update document_title in metadata for all chunks of a document."""
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.update_document_title(document_id, new_title)
            return 0

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                # Get all chunks for this document
                chunks = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.document_id == document_id
                ).all()

                updated_count = 0
                for chunk in chunks:
                    # Update the document_title in metadata
                    metadata = chunk.chunk_metadata or {}
                    metadata['document_title'] = new_title
                    chunk.chunk_metadata = metadata
                    updated_count += 1

                session.commit()
                logger.info(f"Updated title in {updated_count} chunks for document {document_id}")
                return updated_count
        except Exception as e:
            logger.error(f"Database error updating document title: {e}")
            if self._sqlite_store:
                return self._sqlite_store.update_document_title(document_id, new_title)
            return 0

    def get_embedding_count_for_document(self, document_id: str) -> int:
        """Get the number of embeddings for a specific document."""
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.get_embedding_count_for_document(document_id)
            return 0

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                count = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.document_id == document_id
                ).count()
                return count
        except Exception as e:
            logger.error(f"Database error getting embedding count for document {document_id}: {e}")
            if self._sqlite_store:
                return self._sqlite_store.get_embedding_count_for_document(document_id)
            return 0

    def get_document_count(self) -> int:
        """Get the number of documents with embeddings."""
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.get_document_count()
            return 0

        try:
            from core.database import SessionLocal
            from sqlalchemy import text as sa_text

            with SessionLocal() as session:
                count = session.execute(
                    sa_text("SELECT COUNT(DISTINCT document_id) FROM document_embeddings")
                ).scalar()
                return count or 0
        except Exception as e:
            logger.error(f"Database error getting document count: {e}")
            if self._sqlite_store:
                return self._sqlite_store.get_document_count()
            return 0

    def get_chunk_count(self) -> int:
        """Get the total number of chunks across all documents."""
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.get_chunk_count()
            return 0

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                count = session.query(DocumentEmbedding).count()
                return count
        except Exception as e:
            logger.error(f"Database error getting chunk count: {e}")
            if self._sqlite_store:
                return self._sqlite_store.get_chunk_count()
            return 0

    def get_integrity_stats(self) -> Dict:
        """
        Get embedding integrity statistics.

        Returns:
            Dict with:
                - total_chunks (int): Total number of embeddings
                - valid_chunks (int): Number of valid embeddings
                - invalid_chunks (int): Number of invalid embeddings
                - invalid_reasons (Dict[str, int]): Map of reason -> count
                - dimensions (Dict[int, int]): Map of dimension -> count
        """
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.get_integrity_stats()
            return {
                "total_chunks": 0,
                "valid_chunks": 0,
                "invalid_chunks": 0,
                "invalid_reasons": {},
                "dimensions": {}
            }

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                embeddings = session.query(DocumentEmbedding).all()

                if not embeddings:
                    return {
                        "total_chunks": 0,
                        "valid_chunks": 0,
                        "invalid_chunks": 0,
                        "invalid_reasons": {},
                        "dimensions": {}
                    }

                total = len(embeddings)
                valid = 0
                invalid = 0
                invalid_reasons = {}
                dimension_counts = {}

                # Use first valid embedding's dimension as expected dimension
                expected_dim = None
                for emb in embeddings:
                    embedding_list = list(emb.embedding) if emb.embedding is not None else []
                    if embedding_list:
                        expected_dim = len(embedding_list)
                        break

                if expected_dim is None:
                    # No valid embeddings found
                    expected_dim = 0

                for emb in embeddings:
                    embedding_list = list(emb.embedding) if emb.embedding is not None else []
                    dim = len(embedding_list)
                    dimension_counts[dim] = dimension_counts.get(dim, 0) + 1

                    validation = self._validate_embedding(
                        embedding_list,
                        expected_dim,
                        emb.chunk_id,
                        emb.document_id
                    )

                    if validation["valid"]:
                        valid += 1
                    else:
                        invalid += 1
                        reason = validation["reason"]
                        invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1

                return {
                    "total_chunks": total,
                    "valid_chunks": valid,
                    "invalid_chunks": invalid,
                    "invalid_reasons": invalid_reasons,
                    "dimensions": dimension_counts
                }
        except Exception as e:
            logger.error(f"Database error getting integrity stats: {e}")
            if self._sqlite_store:
                return self._sqlite_store.get_integrity_stats()
            return {
                "total_chunks": 0,
                "valid_chunks": 0,
                "invalid_chunks": 0,
                "invalid_reasons": {"error": str(e)},
                "dimensions": {}
            }

    def check_dimension_consistency(self) -> Dict:
        """
        Check embedding dimension consistency across all stored documents.

        Returns:
            Dict with:
                - consistent (bool): True if all embeddings have the same dimension
                - dimensions (Dict[int, int]): Map of dimension -> count of chunks
                - embedding_sources (Dict[str, int]): Map of embedding_source -> count
                - warning (str): Warning message if inconsistent
        """
        if not self._db_available:
            if self._sqlite_store:
                return self._sqlite_store.check_dimension_consistency()
            return {"consistent": True, "dimensions": {}, "embedding_sources": {}}

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                embeddings = session.query(DocumentEmbedding).all()

                if not embeddings:
                    return {"consistent": True, "dimensions": {}, "embedding_sources": {}}

                # Count dimensions and sources
                dimension_counts = {}
                source_counts = {}

                for emb in embeddings:
                    # Get dimension
                    dim = len(emb.embedding) if emb.embedding is not None else 0
                    dimension_counts[dim] = dimension_counts.get(dim, 0) + 1

                    # Get embedding source from metadata
                    metadata = emb.chunk_metadata or {}
                    source = metadata.get("embedding_source", "unknown")
                    source_counts[source] = source_counts.get(source, 0) + 1

                # Check consistency
                consistent = len(dimension_counts) == 1
                warning = None

                if not consistent:
                    dim_list = ", ".join([f"{dim}d ({count} chunks)" for dim, count in sorted(dimension_counts.items())])
                    warning = (
                        f"Inconsistent embedding dimensions detected! Found {len(dimension_counts)} different dimensions: {dim_list}. "
                        f"This will cause search errors. Please delete all documents and re-embed them with the same model."
                    )
                    logger.warning(warning)

                return {
                    "consistent": consistent,
                    "dimensions": dimension_counts,
                    "embedding_sources": source_counts,
                    "warning": warning
                }
        except Exception as e:
            logger.error(f"Database error checking dimension consistency: {e}")
            if self._sqlite_store:
                return self._sqlite_store.check_dimension_consistency()
            return {"consistent": True, "dimensions": {}, "embedding_sources": {}, "error": str(e)}

    def clear(self):
        """Clear all embeddings (for testing)."""
        if not self._db_available:
            if self._sqlite_store:
                self._sqlite_store.clear()
            return

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                session.query(DocumentEmbedding).delete()
                session.commit()
                logger.info("Cleared all embeddings from database")
        except Exception as e:
            logger.error(f"Database error clearing embeddings: {e}")
            if self._sqlite_store:
                self._sqlite_store.clear()

    @staticmethod
    def _validate_embedding(
        embedding: List[float],
        expected_dimension: int,
        chunk_id: str,
        document_id: str
    ) -> Dict:
        """
        Validate embedding vector integrity.

        Returns:
            Dict with 'valid' (bool) and 'reason' (str) fields.
        """
        # Check if embedding exists
        if not embedding:
            return {"valid": False, "reason": "Empty embedding vector"}

        # Check dimension match
        if len(embedding) != expected_dimension:
            return {
                "valid": False,
                "reason": f"Dimension mismatch: expected {expected_dimension}, got {len(embedding)}"
            }

        # Check for invalid float values (NaN, Inf)
        if not all(math.isfinite(x) for x in embedding):
            return {"valid": False, "reason": "Contains NaN or Inf values"}

        # Check for all-zero vector
        if all(x == 0.0 for x in embedding):
            return {"valid": False, "reason": "All-zero vector"}

        return {"valid": True, "reason": ""}

    @property
    def storage_backend(self) -> str:
        """Return the current storage backend name."""
        if self._db_available:
            return "postgresql"
        elif self._sqlite_store:
            return "sqlite"
        else:
            return "none"

    def restore_chunks(self, document_id: str, chunks: List[Dict]) -> int:
        """
        Restore chunks for a document from a backup.

        Feature #248: Used for atomic transaction rollback during re-embedding.
        If new embedding generation fails after deleting old embeddings,
        this method restores the original embeddings.

        Args:
            document_id: The document ID to restore chunks for
            chunks: List of chunk dictionaries from get_chunks() output

        Returns:
            Number of chunks restored
        """
        if not chunks:
            logger.info(f"[Feature #248] No chunks to restore for document {document_id}")
            return 0

        # Convert from get_chunks() format to add_chunks() format
        # get_chunks() returns: [{"chunk_id": ..., "text": ..., "embedding": ..., "metadata": ...}]
        # add_chunks() expects: [{"text": ..., "embedding": ..., "metadata": ...}]
        chunks_to_add = [
            {
                "text": chunk.get("text", ""),
                "embedding": chunk.get("embedding", []),
                "metadata": chunk.get("metadata", {})
            }
            for chunk in chunks
        ]

        restored_count = self.add_chunks(document_id, chunks_to_add)
        logger.info(f"[Feature #248] Restored {restored_count} chunks for document {document_id}")
        return restored_count

    # ============== Feature #250: Backup Table Operations ==============

    def backup_embeddings_to_table(self, document_id: str, reason: str = "reembed") -> int:
        """
        Feature #250: Copy embeddings to backup table before re-embed operation.

        Creates a physical backup of all embeddings for a document in the
        embeddings_backup table. This backup can be restored if re-embed fails.

        Args:
            document_id: The document ID to backup embeddings for
            reason: Reason for the backup (default: 'reembed')

        Returns:
            Number of embeddings backed up
        """
        if not self._db_available:
            logger.warning(f"[Feature #250] SQLite fallback - backup table not supported for document {document_id}")
            return 0

        try:
            from core.database import SessionLocal
            from sqlalchemy import text as sa_text
            from datetime import datetime, timezone

            with SessionLocal() as session:
                # Insert into backup table directly using SQL for efficiency
                result = session.execute(sa_text("""
                    INSERT INTO embeddings_backup (
                        original_id, document_id, chunk_id, text, embedding,
                        metadata, status, pending_delete_at, backup_created_at, backup_reason
                    )
                    SELECT
                        id, document_id, chunk_id, text, embedding,
                        metadata, status, pending_delete_at, NOW(), :reason
                    FROM document_embeddings
                    WHERE document_id = :doc_id
                """), {"doc_id": document_id, "reason": reason})

                backup_count = result.rowcount
                session.commit()

                logger.info(f"[Feature #250] Backed up {backup_count} embeddings for document {document_id} (reason: {reason})")
                return backup_count

        except Exception as e:
            logger.error(f"[Feature #250] Error backing up embeddings for document {document_id}: {e}")
            return 0

    def restore_embeddings_from_backup(self, document_id: str) -> int:
        """
        Feature #250: Restore embeddings from backup table.

        Restores all embeddings for a document from the backup table.
        This is called when re-embed fails catastrophically.

        Note: This does NOT delete the backup after restoring - call
        delete_backup_for_document() separately after verification.

        Args:
            document_id: The document ID to restore embeddings for

        Returns:
            Number of embeddings restored
        """
        if not self._db_available:
            logger.warning(f"[Feature #250] SQLite fallback - backup restore not supported for document {document_id}")
            return 0

        try:
            from core.database import SessionLocal
            from sqlalchemy import text as sa_text

            with SessionLocal() as session:
                # First, delete any existing embeddings for this document
                session.execute(sa_text("""
                    DELETE FROM document_embeddings WHERE document_id = :doc_id
                """), {"doc_id": document_id})

                # Restore from backup (use original chunk_id but new auto-generated id)
                result = session.execute(sa_text("""
                    INSERT INTO document_embeddings (
                        document_id, chunk_id, text, embedding, metadata, status, pending_delete_at
                    )
                    SELECT
                        document_id, chunk_id, text, embedding, metadata, 'active', NULL
                    FROM embeddings_backup
                    WHERE document_id = :doc_id
                """), {"doc_id": document_id})

                restored_count = result.rowcount
                session.commit()

                logger.info(f"[Feature #250] Restored {restored_count} embeddings from backup for document {document_id}")
                return restored_count

        except Exception as e:
            logger.error(f"[Feature #250] Error restoring embeddings from backup for document {document_id}: {e}")
            return 0

    def delete_backup_for_document(self, document_id: str) -> int:
        """
        Feature #250: Delete backup for a document after successful re-embed.

        Args:
            document_id: The document ID to delete backup for

        Returns:
            Number of backup entries deleted
        """
        if not self._db_available:
            return 0

        try:
            from core.database import SessionLocal
            from sqlalchemy import text as sa_text

            with SessionLocal() as session:
                result = session.execute(sa_text("""
                    DELETE FROM embeddings_backup WHERE document_id = :doc_id
                """), {"doc_id": document_id})

                deleted_count = result.rowcount
                session.commit()

                logger.info(f"[Feature #250] Deleted {deleted_count} backup entries for document {document_id}")
                return deleted_count

        except Exception as e:
            logger.error(f"[Feature #250] Error deleting backup for document {document_id}: {e}")
            return 0

    def get_backup_stats(self, document_id: Optional[str] = None) -> Dict:
        """
        Feature #250: Get statistics about backups.

        Args:
            document_id: Optional document ID to filter stats

        Returns:
            Dict with backup statistics
        """
        if not self._db_available:
            return {"error": "PostgreSQL not available", "total_backups": 0}

        try:
            from core.database import SessionLocal
            from sqlalchemy import text as sa_text

            with SessionLocal() as session:
                if document_id:
                    # Stats for specific document
                    result = session.execute(sa_text("""
                        SELECT
                            COUNT(*) as count,
                            MIN(backup_created_at) as oldest_backup,
                            MAX(backup_created_at) as newest_backup,
                            backup_reason
                        FROM embeddings_backup
                        WHERE document_id = :doc_id
                        GROUP BY backup_reason
                    """), {"doc_id": document_id})
                    rows = result.fetchall()

                    if not rows:
                        return {"document_id": document_id, "has_backup": False, "total_backups": 0}

                    return {
                        "document_id": document_id,
                        "has_backup": True,
                        "total_backups": sum(row[0] for row in rows),
                        "oldest_backup": rows[0][1].isoformat() if rows[0][1] else None,
                        "newest_backup": rows[0][2].isoformat() if rows[0][2] else None,
                        "by_reason": {row[3]: row[0] for row in rows}
                    }
                else:
                    # Global stats
                    result = session.execute(sa_text("""
                        SELECT
                            COUNT(*) as total_count,
                            COUNT(DISTINCT document_id) as document_count,
                            MIN(backup_created_at) as oldest_backup,
                            MAX(backup_created_at) as newest_backup
                        FROM embeddings_backup
                    """))
                    row = result.fetchone()

                    if not row or row[0] == 0:
                        return {"total_backups": 0, "documents_with_backups": 0}

                    return {
                        "total_backups": row[0],
                        "documents_with_backups": row[1],
                        "oldest_backup": row[2].isoformat() if row[2] else None,
                        "newest_backup": row[3].isoformat() if row[3] else None
                    }

        except Exception as e:
            logger.error(f"[Feature #250] Error getting backup stats: {e}")
            return {"error": str(e), "total_backups": 0}

    def cleanup_old_backups(self, days: int = 7) -> int:
        """
        Feature #250: Clean up backups older than specified days.

        Args:
            days: Number of days after which backups are considered stale

        Returns:
            Number of backups deleted
        """
        if not self._db_available:
            return 0

        try:
            from core.database import SessionLocal
            from sqlalchemy import text as sa_text
            from datetime import datetime, timezone, timedelta

            cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)

            with SessionLocal() as session:
                result = session.execute(sa_text("""
                    DELETE FROM embeddings_backup
                    WHERE backup_created_at < :cutoff
                """), {"cutoff": cutoff_time})

                deleted_count = result.rowcount
                session.commit()

                if deleted_count > 0:
                    logger.info(f"[Feature #250] Cleaned up {deleted_count} old backups (older than {days} days)")

                return deleted_count

        except Exception as e:
            logger.error(f"[Feature #250] Error cleaning up old backups: {e}")
            return 0

    def has_backup_for_document(self, document_id: str) -> bool:
        """
        Feature #250: Check if a backup exists for a document.

        Args:
            document_id: The document ID to check

        Returns:
            True if backup exists, False otherwise
        """
        if not self._db_available:
            return False

        try:
            from core.database import SessionLocal
            from sqlalchemy import text as sa_text

            with SessionLocal() as session:
                result = session.execute(sa_text("""
                    SELECT EXISTS(SELECT 1 FROM embeddings_backup WHERE document_id = :doc_id)
                """), {"doc_id": document_id})
                return result.scalar() or False

        except Exception as e:
            logger.error(f"[Feature #250] Error checking backup for document {document_id}: {e}")
            return False

    def list_documents_with_backups(self) -> List[Dict]:
        """
        Feature #250: List all documents that have backups.

        Returns:
            List of dicts with document_id, backup_count, and backup timestamps
        """
        if not self._db_available:
            return []

        try:
            from core.database import SessionLocal
            from sqlalchemy import text as sa_text

            with SessionLocal() as session:
                result = session.execute(sa_text("""
                    SELECT
                        document_id,
                        COUNT(*) as backup_count,
                        MIN(backup_created_at) as oldest_backup,
                        MAX(backup_created_at) as newest_backup,
                        backup_reason
                    FROM embeddings_backup
                    GROUP BY document_id, backup_reason
                    ORDER BY newest_backup DESC
                """))

                return [
                    {
                        "document_id": row[0],
                        "backup_count": row[1],
                        "oldest_backup": row[2].isoformat() if row[2] else None,
                        "newest_backup": row[3].isoformat() if row[3] else None,
                        "reason": row[4]
                    }
                    for row in result.fetchall()
                ]

        except Exception as e:
            logger.error(f"[Feature #250] Error listing documents with backups: {e}")
            return []


    # ============== Feature #268: Atomic Re-embedding with Transaction Rollback ==============

    def atomic_reembed_document(
        self,
        document_id: str,
        new_chunks: List[Dict],
        embedding_source: str
    ) -> Dict:
        """
        Feature #268: Atomically re-embed a document with transaction rollback.

        Wraps the DELETE of old embeddings and INSERT of new embeddings in a single
        PostgreSQL transaction. If any operation fails, the transaction is rolled back
        and old embeddings are preserved.

        This provides stronger data consistency guarantees than soft-delete:
        - All-or-nothing semantics
        - No orphaned embeddings on partial failure
        - Uses database-level ACID guarantees

        Args:
            document_id: The document ID to re-embed
            new_chunks: List of new chunk dictionaries with:
                - text: Chunk text
                - embedding: Embedding vector
                - metadata: Chunk metadata dict
            embedding_source: The embedding model identifier (e.g., 'ollama:bge-m3')

        Returns:
            Dict with:
                - success (bool): Whether the operation succeeded
                - deleted_count (int): Number of old embeddings deleted
                - inserted_count (int): Number of new embeddings inserted
                - error (str, optional): Error message if failed
                - transaction_action (str): 'commit' or 'rollback'
        """
        if not self._db_available:
            # SQLite fallback doesn't support explicit transactions the same way
            # Fall back to the non-atomic approach
            logger.warning(f"[Feature #268] SQLite fallback - using non-atomic re-embed for document {document_id}")
            if self._sqlite_store:
                # Delete old, then add new (not truly atomic)
                self._sqlite_store.delete_document(document_id)
                inserted = self._sqlite_store.add_chunks(document_id, new_chunks)
                return {
                    "success": True,
                    "deleted_count": -1,  # Unknown count in SQLite fallback
                    "inserted_count": inserted,
                    "transaction_action": "non-atomic-fallback"
                }
            return {
                "success": False,
                "deleted_count": 0,
                "inserted_count": 0,
                "error": "No database available",
                "transaction_action": "none"
            }

        try:
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding, EMBEDDING_STATUS_ACTIVE
            from sqlalchemy import text as sa_text
            from datetime import datetime, timezone

            logger.info(f"[Feature #268] TRANSACTION BEGIN for document {document_id}")

            # Use a single session for the entire transaction
            session = SessionLocal()
            deleted_count = 0
            inserted_count = 0

            try:
                # Step 1: Delete old embeddings (within transaction)
                logger.info(f"[Feature #268] TRANSACTION STEP 1: Deleting old embeddings for document {document_id}")
                deleted_count = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.document_id == document_id
                ).delete()
                logger.info(f"[Feature #268] Deleted {deleted_count} old embeddings (not yet committed)")

                # Step 2: Insert new embeddings (within same transaction)
                logger.info(f"[Feature #268] TRANSACTION STEP 2: Inserting {len(new_chunks)} new embeddings for document {document_id}")

                for chunk_data in new_chunks:
                    # Prepare metadata with embedding source
                    metadata = chunk_data.get("metadata", {}).copy()
                    metadata["embedding_source"] = embedding_source

                    # Create embedding without chunk_id (will use temp value)
                    embedding = DocumentEmbedding(
                        document_id=document_id,
                        chunk_id="temp",  # Temporary, will be updated
                        text=chunk_data.get("text", ""),
                        embedding=chunk_data.get("embedding", []),
                        chunk_metadata=metadata,
                        status=EMBEDDING_STATUS_ACTIVE
                    )
                    session.add(embedding)
                    session.flush()  # Get the database-generated ID

                    # Now update with the correct chunk_id based on database ID
                    embedding.chunk_id = f"chunk_{embedding.id}"
                    inserted_count += 1

                # Step 3: Commit the transaction
                logger.info(f"[Feature #268] TRANSACTION COMMIT for document {document_id}: deleted={deleted_count}, inserted={inserted_count}")
                session.commit()

                return {
                    "success": True,
                    "deleted_count": deleted_count,
                    "inserted_count": inserted_count,
                    "transaction_action": "commit"
                }

            except Exception as tx_error:
                # Rollback on any failure - old embeddings are preserved
                logger.error(f"[Feature #268] TRANSACTION ROLLBACK for document {document_id}: {tx_error}")
                session.rollback()

                return {
                    "success": False,
                    "deleted_count": 0,  # Rolled back, so nothing was deleted
                    "inserted_count": 0,  # Rolled back, so nothing was inserted
                    "error": str(tx_error),
                    "transaction_action": "rollback"
                }

            finally:
                session.close()

        except Exception as e:
            logger.error(f"[Feature #268] Failed to start transaction for document {document_id}: {e}")
            return {
                "success": False,
                "deleted_count": 0,
                "inserted_count": 0,
                "error": str(e),
                "transaction_action": "none"
            }

    def verify_document_embeddings(self, document_id: str, expected_count: int = 0) -> Dict:
        """
        Feature #268/#297: Verify embeddings for a document after re-embed.

        Feature #297 enhancements:
        - Detailed logging with [VERIFICATION] prefix
        - Mismatch detection with specific error types
        - Support for automatic retry recommendations

        Args:
            document_id: The document ID to verify
            expected_count: Expected number of embeddings (0 = just verify at least one exists)

        Returns:
            Dict with:
                - success (bool): Whether verification passed
                - actual_count (int): Number of embeddings found
                - expected_count (int): Expected count (0 means "at least one")
                - message (str): Human-readable verification result
                - error_type (str, optional): Type of verification failure
                - should_retry (bool): Whether automatic retry is recommended
        """
        logger.info(f"[Feature #297] [VERIFICATION] Starting post re-embed verification for document {document_id}")
        logger.info(f"[Feature #297] [VERIFICATION] Expected chunk count: {expected_count}")

        actual_count = self.get_embedding_count_for_document(document_id)
        logger.info(f"[Feature #297] [VERIFICATION] Actual embedding count in database: {actual_count}")

        error_type = None
        should_retry = False

        if expected_count > 0:
            success = actual_count == expected_count
            if success:
                message = f"Verification passed: {actual_count} embeddings match expected {expected_count}"
                logger.info(f"[Feature #297] [VERIFICATION] ✅ SUCCESS - Embedding count matches chunk count")
            else:
                # Determine the type of failure for better diagnostics
                if actual_count == 0:
                    error_type = "zero_embeddings"
                    message = f"Verification FAILED: expected {expected_count} embeddings but found ZERO"
                    should_retry = True  # Zero embeddings likely means a transient error
                    logger.error(f"[Feature #297] [VERIFICATION] ❌ CRITICAL FAILURE - Zero embeddings found, expected {expected_count}")
                elif actual_count < expected_count:
                    error_type = "partial_embeddings"
                    missing = expected_count - actual_count
                    message = f"Verification FAILED: only {actual_count}/{expected_count} embeddings stored ({missing} missing)"
                    should_retry = True  # Partial write may succeed on retry
                    logger.error(f"[Feature #297] [VERIFICATION] ❌ PARTIAL FAILURE - {missing} embeddings missing")
                else:
                    error_type = "excess_embeddings"
                    excess = actual_count - expected_count
                    message = f"Verification FAILED: {actual_count} embeddings found but only {expected_count} expected ({excess} excess)"
                    should_retry = False  # Excess embeddings shouldn't be retried
                    logger.error(f"[Feature #297] [VERIFICATION] ❌ EXCESS FAILURE - {excess} extra embeddings")
        else:
            success = actual_count > 0
            if success:
                message = f"Verification passed: {actual_count} embeddings found"
                logger.info(f"[Feature #297] [VERIFICATION] ✅ SUCCESS - At least one embedding found")
            else:
                error_type = "zero_embeddings"
                message = "Verification FAILED: no embeddings found"
                should_retry = True
                logger.error(f"[Feature #297] [VERIFICATION] ❌ CRITICAL FAILURE - No embeddings found at all")

        result = {
            "success": success,
            "actual_count": actual_count,
            "expected_count": expected_count,
            "message": message,
            "error_type": error_type,
            "should_retry": should_retry
        }

        logger.info(f"[Feature #297] [VERIFICATION] Result: {result}")
        return result


# Global embedding store instance
embedding_store = PostgreSQLEmbeddingStore()
