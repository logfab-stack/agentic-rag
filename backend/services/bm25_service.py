"""
BM25 Index Service for Hybrid Search (Feature #186).

This service manages BM25 keyword-based search indexes for document chunks.
BM25 excels at finding exact keyword matches (like acronyms "GMDSS") that
pure vector search might miss.

The hybrid search combines:
- Vector search: Semantic similarity (good for meaning/concepts)
- BM25 search: Keyword matching (good for acronyms, technical terms)

Uses Reciprocal Rank Fusion (RRF) to combine results from both methods.
"""

import json
import logging
import os
import pickle
import re
import threading
from typing import Dict, List, Optional, Tuple
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


class BM25IndexService:
    """
    Service for managing BM25 keyword-based search indexes.

    The index is stored in a pickle file for persistence across restarts.
    Each chunk is tokenized and indexed for BM25 search.
    """

    # File path for persistent BM25 index
    INDEX_FILE = "bm25_index.pkl"

    def __init__(self):
        """Initialize the BM25 index service."""
        self._index: Optional[BM25Okapi] = None
        self._corpus: List[List[str]] = []  # Tokenized documents
        self._chunk_metadata: List[Dict] = []  # Metadata for each chunk (document_id, chunk_id, text)
        self._lock = threading.Lock()
        self._initialized = False

        # Load existing index from disk if available
        self._load_index()

    def _get_index_path(self) -> str:
        """Get the absolute path to the BM25 index file."""
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(backend_dir, self.INDEX_FILE)

    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize text for BM25 indexing.

        Uses simple word tokenization with:
        - Lowercase conversion
        - Alphanumeric preservation (keeps acronyms like GMDSS)
        - Preserves numbers and technical terms
        """
        if not text:
            return []

        # Convert to lowercase for case-insensitive matching
        text = text.lower()

        # Split on whitespace and punctuation, keeping alphanumeric sequences
        # This preserves acronyms like "GMDSS" and technical terms
        tokens = re.findall(r'\b[a-z0-9]+(?:[\'-][a-z0-9]+)*\b', text)

        # Filter out very short tokens (single characters) unless they're numbers
        tokens = [t for t in tokens if len(t) > 1 or t.isdigit()]

        return tokens

    def _save_index(self) -> None:
        """Save the current index to disk."""
        try:
            index_path = self._get_index_path()
            data = {
                'corpus': self._corpus,
                'chunk_metadata': self._chunk_metadata
            }
            with open(index_path, 'wb') as f:
                pickle.dump(data, f)
            logger.info(f"Saved BM25 index to {index_path} ({len(self._corpus)} chunks)")
        except Exception as e:
            logger.error(f"Failed to save BM25 index: {e}")

    def _load_index(self) -> None:
        """Load the index from disk if available."""
        try:
            index_path = self._get_index_path()
            if os.path.exists(index_path):
                with open(index_path, 'rb') as f:
                    data = pickle.load(f)
                    self._corpus = data.get('corpus', [])
                    self._chunk_metadata = data.get('chunk_metadata', [])

                if self._corpus:
                    self._index = BM25Okapi(self._corpus)
                    self._initialized = True
                    logger.info(f"Loaded BM25 index from {index_path} ({len(self._corpus)} chunks)")
            else:
                logger.info("No existing BM25 index found, starting fresh")
        except Exception as e:
            logger.error(f"Failed to load BM25 index: {e}")
            self._corpus = []
            self._chunk_metadata = []
            self._index = None

    def rebuild_from_embedding_store(self) -> int:
        """
        Rebuild the BM25 index from the current embedding store.

        This is useful when the index gets out of sync or for initial setup.

        Returns:
            Number of chunks indexed
        """
        with self._lock:
            try:
                from core.store import embedding_store

                # Get all chunks from embedding store
                all_chunks = embedding_store.get_all_chunks()

                if not all_chunks:
                    logger.info("No chunks found in embedding store to build BM25 index")
                    self._corpus = []
                    self._chunk_metadata = []
                    self._index = None
                    self._save_index()
                    return 0

                # Build new corpus and metadata
                new_corpus = []
                new_metadata = []

                for chunk in all_chunks:
                    text = chunk.get('text', '')
                    tokens = self._tokenize(text)

                    if tokens:  # Only index non-empty chunks
                        new_corpus.append(tokens)
                        new_metadata.append({
                            'document_id': chunk.get('document_id'),
                            'chunk_id': chunk.get('chunk_id'),
                            'text': text,
                            'metadata': chunk.get('metadata', {})
                        })

                # Update index
                self._corpus = new_corpus
                self._chunk_metadata = new_metadata

                if self._corpus:
                    self._index = BM25Okapi(self._corpus)
                    self._initialized = True
                else:
                    self._index = None

                # Persist to disk
                self._save_index()

                logger.info(f"Rebuilt BM25 index with {len(self._corpus)} chunks")
                return len(self._corpus)

            except Exception as e:
                logger.error(f"Error rebuilding BM25 index: {e}")
                return 0

    def add_chunks(self, document_id: str, chunks: List[Dict]) -> int:
        """
        Add chunks for a document to the BM25 index.

        Args:
            document_id: The document ID
            chunks: List of chunk dictionaries with 'text', 'chunk_id', and optional 'metadata'

        Returns:
            Number of chunks added
        """
        with self._lock:
            try:
                added_count = 0

                for chunk in chunks:
                    text = chunk.get('text', '')
                    tokens = self._tokenize(text)

                    if tokens:  # Only index non-empty chunks
                        self._corpus.append(tokens)
                        self._chunk_metadata.append({
                            'document_id': document_id,
                            'chunk_id': chunk.get('chunk_id', f'chunk_{len(self._corpus)}'),
                            'text': text,
                            'metadata': chunk.get('metadata', {})
                        })
                        added_count += 1

                # Rebuild BM25 index with new corpus
                if self._corpus:
                    self._index = BM25Okapi(self._corpus)
                    self._initialized = True

                # Save to disk
                self._save_index()

                logger.info(f"[BM25] Added {added_count} chunks for document {document_id}")
                return added_count

            except Exception as e:
                logger.error(f"Error adding chunks to BM25 index: {e}")
                return 0

    def delete_document(self, document_id: str) -> int:
        """
        Remove all chunks for a document from the BM25 index.

        Args:
            document_id: The document ID to remove

        Returns:
            Number of chunks removed
        """
        with self._lock:
            try:
                # Find indices of chunks to remove
                indices_to_remove = [
                    i for i, meta in enumerate(self._chunk_metadata)
                    if meta.get('document_id') == document_id
                ]

                if not indices_to_remove:
                    return 0

                # Remove in reverse order to maintain indices
                for idx in sorted(indices_to_remove, reverse=True):
                    del self._corpus[idx]
                    del self._chunk_metadata[idx]

                # Rebuild BM25 index
                if self._corpus:
                    self._index = BM25Okapi(self._corpus)
                else:
                    self._index = None

                # Save to disk
                self._save_index()

                removed_count = len(indices_to_remove)
                logger.info(f"[BM25] Removed {removed_count} chunks for document {document_id}")
                return removed_count

            except Exception as e:
                logger.error(f"Error deleting document from BM25 index: {e}")
                return 0

    def _expand_query_entities(self, query: str) -> List[str]:
        """
        Feature #218: Expand query to include product code variations.

        Converts natural language product references to potential code formats:
        - "Navigat 100" -> also search for "navigat/100", "navigat-100", "navigat100"
        - This enables matching against codes like "NAVIGAT/100/0/10/4"

        Args:
            query: The original search query

        Returns:
            List of additional tokens to include in search
        """
        expanded_tokens = []

        # Find product name + number patterns (e.g., "Navigat 100")
        product_patterns = re.findall(r'([A-Za-z]+)\s+(\d+)', query)
        for name, number in product_patterns:
            name_lower = name.lower()
            # Add various code formats that might appear in documents
            expanded_tokens.extend([
                f"{name_lower}/{number}",      # navigat/100
                f"{name_lower}-{number}",      # navigat-100
                f"{name_lower}{number}",       # navigat100
            ])
            logger.info(f"[Feature #218] Expanded '{name} {number}' to code variations: {expanded_tokens[-3:]}")

        # Also expand standalone product codes with separators
        # e.g., "VFR-X1M" -> tokenize as "vfr", "x1m"
        code_patterns = re.findall(r'([A-Za-z0-9]+)[/\-_]([A-Za-z0-9]+)', query)
        for part1, part2 in code_patterns:
            expanded_tokens.append(part1.lower())
            expanded_tokens.append(part2.lower())

        return expanded_tokens

    def search(
        self,
        query: str,
        top_k: int = 20,
        document_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Search the BM25 index for relevant chunks.

        Feature #218: Enhanced with query expansion for product code variations.

        Args:
            query: The search query
            top_k: Maximum number of results to return
            document_ids: Optional list of document IDs to restrict search to

        Returns:
            List of result dictionaries with chunk info and BM25 scores
        """
        if not self._index or not self._corpus:
            logger.warning("[BM25] Search called but index is empty")
            return []

        try:
            # Tokenize query
            query_tokens = self._tokenize(query)

            # Feature #218: Expand query with product code variations
            expanded_tokens = self._expand_query_entities(query)
            if expanded_tokens:
                query_tokens.extend(expanded_tokens)
                logger.info(f"[Feature #218] Expanded BM25 query tokens: {query_tokens}")

            if not query_tokens:
                logger.warning(f"[BM25] Empty query after tokenization: '{query}'")
                return []

            logger.info(f"[BM25] Searching for: {query_tokens}")

            # Get BM25 scores for all documents
            scores = self._index.get_scores(query_tokens)

            # Build results with scores
            results = []
            for idx, score in enumerate(scores):
                if score > 0:  # Only include chunks with positive score
                    metadata = self._chunk_metadata[idx]

                    # Filter by document_ids if specified
                    if document_ids and metadata.get('document_id') not in document_ids:
                        continue

                    results.append({
                        'chunk_id': metadata.get('chunk_id'),
                        'document_id': metadata.get('document_id'),
                        'text': metadata.get('text', ''),
                        'metadata': metadata.get('metadata', {}),
                        'bm25_score': float(score),
                        'type': 'document_chunk'  # Mark as document chunk for consistency
                    })

            # Sort by score descending and limit
            results.sort(key=lambda x: x['bm25_score'], reverse=True)
            results = results[:top_k]

            logger.info(f"[BM25] Found {len(results)} results for query: {query[:50]}...")

            return results

        except Exception as e:
            logger.error(f"Error searching BM25 index: {e}")
            return []

    def get_stats(self) -> Dict:
        """Get statistics about the BM25 index."""
        return {
            'initialized': self._initialized,
            'total_chunks': len(self._corpus),
            'total_documents': len(set(m.get('document_id') for m in self._chunk_metadata)),
            'index_file_exists': os.path.exists(self._get_index_path())
        }

    def clear(self) -> None:
        """Clear the BM25 index completely."""
        with self._lock:
            self._corpus = []
            self._chunk_metadata = []
            self._index = None
            self._initialized = False

            # Remove index file
            index_path = self._get_index_path()
            if os.path.exists(index_path):
                os.remove(index_path)

            logger.info("[BM25] Index cleared")


def reciprocal_rank_fusion(
    vector_results: List[Dict],
    bm25_results: List[Dict],
    k: int = 60,
    alpha: float = 0.5
) -> List[Dict]:
    """
    Combine vector and BM25 results using Reciprocal Rank Fusion (RRF).

    RRF score = sum(1 / (k + rank))

    This is a proven method for combining different retrieval approaches.
    The k parameter (typically 60) prevents high-ranking items from dominating.

    Args:
        vector_results: Results from vector similarity search
        bm25_results: Results from BM25 keyword search
        k: RRF constant (higher = more equal weighting, default 60)
        alpha: Weight for vector results vs BM25 (0.5 = equal, >0.5 favors vector)

    Returns:
        Combined and reranked results with RRF scores
    """
    # Build a map of chunk_id -> result for deduplication
    chunk_map: Dict[str, Dict] = {}
    rrf_scores: Dict[str, float] = {}

    # Process vector results
    for rank, result in enumerate(vector_results, start=1):
        chunk_id = result.get('chunk_id', '')
        if not chunk_id:
            continue

        # RRF score contribution from vector search
        rrf_contribution = alpha * (1.0 / (k + rank))
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + rrf_contribution

        # Store result if not already present
        if chunk_id not in chunk_map:
            chunk_map[chunk_id] = result.copy()
            chunk_map[chunk_id]['vector_rank'] = rank
            chunk_map[chunk_id]['bm25_rank'] = None

    # Process BM25 results
    for rank, result in enumerate(bm25_results, start=1):
        chunk_id = result.get('chunk_id', '')
        if not chunk_id:
            continue

        # RRF score contribution from BM25 search
        rrf_contribution = (1 - alpha) * (1.0 / (k + rank))
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + rrf_contribution

        # Store result if not already present, or update with BM25 info
        if chunk_id not in chunk_map:
            chunk_map[chunk_id] = result.copy()
            chunk_map[chunk_id]['vector_rank'] = None
            chunk_map[chunk_id]['bm25_rank'] = rank
        else:
            chunk_map[chunk_id]['bm25_rank'] = rank
            chunk_map[chunk_id]['bm25_score'] = result.get('bm25_score', 0)

    # Build final results with RRF scores
    fused_results = []
    for chunk_id, result in chunk_map.items():
        result['rrf_score'] = rrf_scores.get(chunk_id, 0)
        fused_results.append(result)

    # Sort by RRF score descending
    fused_results.sort(key=lambda x: x.get('rrf_score', 0), reverse=True)

    # Feature #197: Normalize RRF scores to 0-1 range for compatibility with relevance threshold filtering
    # RRF scores are typically in range ~0.01-0.05, which causes all results to be filtered out
    # when min_relevance_threshold (e.g., 0.4) is applied. Normalizing to 0-1 range fixes this.
    if fused_results:
        max_rrf = max(r.get('rrf_score', 0) for r in fused_results)
        min_rrf = min(r.get('rrf_score', 0) for r in fused_results)
        rrf_range = max_rrf - min_rrf

        for result in fused_results:
            raw_rrf = result.get('rrf_score', 0)
            if rrf_range > 0:
                # Normalize to 0-1 range using min-max normalization
                # Add 0.3 offset and scale to 0.3-1.0 range so good results aren't all near 0
                normalized = (raw_rrf - min_rrf) / rrf_range
                # Scale to 0.4-1.0 range so top results pass typical thresholds
                result['similarity'] = 0.4 + (normalized * 0.6)
            elif max_rrf > 0:
                # All same score, give them a reasonable similarity (0.7)
                result['similarity'] = 0.7
            else:
                result['similarity'] = 0.0
            result['raw_rrf_score'] = raw_rrf  # Preserve original for debugging

        logger.info(f"[RRF] Normalized scores from {min_rrf:.4f}-{max_rrf:.4f} to 0.40-1.00 range")

    logger.info(
        f"[RRF] Fused {len(vector_results)} vector + {len(bm25_results)} BM25 results "
        f"into {len(fused_results)} unique results (k={k}, alpha={alpha})"
    )

    return fused_results


# Global BM25 index service instance
bm25_service = BM25IndexService()
