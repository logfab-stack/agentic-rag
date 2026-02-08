"""
AI Service for handling LLM interactions in the Agentic RAG System.

This service manages connections to OpenAI and Ollama for chat completions,
and implements tool calling for SQL analysis and document listing.

Feature #229: Added support for broad/listing queries with high top_k retrieval.
"""

import os
import json
import logging
import httpx
import re
from typing import Optional, List, Dict, Any, Tuple
from openai import OpenAI, OpenAIError, AuthenticationError, RateLimitError, APIConnectionError

# Initialize logger first
logger = logging.getLogger(__name__)

# Cohere reranking - use httpx directly to avoid SDK compatibility issues with Python 3.14
# The Cohere SDK v5 uses Pydantic V1 which is incompatible with Python 3.14
# Fix #195: Replace cohere.Client.rerank() with direct httpx POST request
COHERE_API_URL = "https://api.cohere.com/v1/rerank"

# Language detection
try:
    from langdetect import detect, LangDetectException
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    logger.warning("langdetect not available, falling back to keyword-based detection")

from core.store import document_store, document_rows_store, embedding_store, settings_store
from core.database import SessionLocal
from models.db_models import DBDocument, DBDocumentRow, DBCollection
from models.user_note import UserNote
from models.chunk_feedback import ChunkFeedback
from models.message_embedding import MessageEmbedding
from services.response_cache_service import response_cache_service

# Default Ollama URL
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Feature #285: Maximum synonyms per word to prevent query explosion
# Synonym expansion can add too many terms, causing noisy retrieval
MAX_SYNONYMS_PER_WORD = 3


class OllamaConnectionError(Exception):
    """Custom exception for Ollama connection errors."""
    pass


def _get_documents_sync():
    """
    Synchronous helper to get all documents from PostgreSQL.
    Needed for tool detection which runs in sync context.

    Feature #289: Only returns documents with status='ready' to prevent
    querying documents that are still being processed.
    """
    try:
        from models.db_models import DOCUMENT_STATUS_READY
        with SessionLocal() as session:
            # Feature #289: Filter to only include status='ready' documents
            documents = session.query(DBDocument).filter(
                DBDocument.status == DOCUMENT_STATUS_READY
            ).all()
            # Convert to simple objects with necessary fields
            # Feature #342: Added schema_info for _get_available_topics() structured data handling
            return [type('Doc', (), {
                'id': d.id,
                'document_type': d.document_type,
                'title': d.title,
                'original_filename': d.original_filename,
                'mime_type': d.mime_type,
                'schema_info': d.schema_info
            })() for d in documents]
    except Exception as e:
        logger.error(f"Error getting documents sync: {e}")
        return []


def _get_document_by_id_sync(doc_id: str):
    """
    Synchronous helper to get a single document by ID from PostgreSQL.
    Used by cross_document_query execution.
    """
    try:
        with SessionLocal() as session:
            doc = session.query(DBDocument).filter(DBDocument.id == doc_id).first()
            if doc:
                return type('Doc', (), {
                    'id': doc.id,
                    'document_type': doc.document_type,
                    'title': doc.title,
                    'original_filename': doc.original_filename,
                    'mime_type': doc.mime_type,
                    'schema_info': doc.schema_info
                })()
            return None
    except Exception as e:
        logger.error(f"Error getting document by ID sync: {e}")
        return None


def _get_document_rows_sync(dataset_id: str):
    """
    Synchronous helper to get document rows from PostgreSQL.
    Used by cross_document_query execution.
    """
    try:
        with SessionLocal() as session:
            rows = session.query(DBDocumentRow).filter(
                DBDocumentRow.dataset_id == dataset_id
            ).all()
            return [{"data": row.row_data} for row in rows]
    except Exception as e:
        logger.error(f"Error getting document rows sync: {e}")
        return []


def _get_collections_sync():
    """
    Feature #316: Synchronous helper to get all collections from PostgreSQL.
    Used by _get_available_topics to show collection names as topics.
    """
    try:
        with SessionLocal() as session:
            collections = session.query(DBCollection).all()
            # Convert to simple objects with necessary fields
            return [type('Collection', (), {
                'id': c.id,
                'name': c.name,
                'description': c.description
            })() for c in collections]
    except Exception as e:
        logger.error(f"Error getting collections sync: {e}")
        return []


def ensure_chunk_text(chunk: Dict) -> Tuple[Optional[str], str]:
    """
    Feature #279: Ensure a chunk has text content, attempting recovery if missing.

    This is a standalone utility function that checks if a chunk has text and
    if not, attempts to recover the text from the document_embeddings table
    using direct chunk_id lookup.

    The function implements a fallback chain:
    1. Check if chunk already has non-empty text (return immediately)
    2. Direct lookup by chunk_id from document_embeddings table
    3. Scan document chunks by document_id to find matching chunk_id
    4. Return None if text cannot be recovered

    Args:
        chunk: Dict with chunk data, must contain at least 'chunk_id'.
               Optional: 'text', 'document_id', 'metadata'

    Returns:
        Tuple of (text, source):
        - text: The chunk text or None if not found
        - source: 'existing' | 'fallback_direct_lookup' | 'fallback_document_scan' | 'none'

    Example:
        text, source = ensure_chunk_text({"chunk_id": "chunk_123", "text": ""})
        if text is None:
            logger.error(f"Could not recover text for chunk")
    """
    chunk_id = chunk.get("chunk_id", "unknown")
    document_id = chunk.get("document_id", "unknown")

    # Check if chunk already has text
    existing_text = chunk.get("text", "")
    if existing_text and existing_text.strip():
        return existing_text, "existing"

    logger.info(f"[Feature #279] ensure_chunk_text: chunk {chunk_id} has empty text, attempting recovery")

    # Fallback 1: Direct lookup by chunk_id
    try:
        if chunk_id and chunk_id != "unknown":
            stored_chunk = embedding_store.get_chunk_by_id(chunk_id)
            if stored_chunk:
                stored_text = stored_chunk.get("text", "")
                if stored_text and stored_text.strip():
                    logger.info(
                        f"[Feature #279] ensure_chunk_text: recovered {len(stored_text)} chars "
                        f"for chunk {chunk_id} via direct lookup"
                    )
                    return stored_text, "fallback_direct_lookup"
    except Exception as e:
        logger.warning(f"[Feature #279] ensure_chunk_text: direct lookup error for {chunk_id}: {e}")

    # Fallback 2: Scan document chunks
    try:
        if document_id and document_id != "unknown":
            doc_chunks = embedding_store.get_chunks(document_id)
            for stored_chunk in doc_chunks:
                if stored_chunk.get("chunk_id") == chunk_id:
                    stored_text = stored_chunk.get("text", "")
                    if stored_text and stored_text.strip():
                        logger.info(
                            f"[Feature #279] ensure_chunk_text: recovered {len(stored_text)} chars "
                            f"for chunk {chunk_id} via document scan"
                        )
                        return stored_text, "fallback_document_scan"
                    break
    except Exception as e:
        logger.warning(f"[Feature #279] ensure_chunk_text: document scan error for {chunk_id}: {e}")

    # All fallbacks failed
    logger.error(
        f"[Feature #279] ensure_chunk_text: FAILED to recover text for chunk {chunk_id} "
        f"(document_id={document_id}). All fallback sources exhausted."
    )
    return None, "none"


class AIService:
    """Service for AI/LLM interactions."""

    def __init__(self):
        """Initialize the AI service."""
        self.openai_client: Optional[OpenAI] = None
        self.model = os.getenv("DEFAULT_LLM_MODEL", "gpt-4o-mini")
        # [Feature #243] Flag to disable LLM query rewrite after 401 error
        self._openai_rewrite_disabled: bool = False
        self._initialize_openai()

    def _initialize_openai(self):
        """Initialize OpenAI client if API key is available."""
        # First try environment variable, then fall back to settings store
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key == "sk-your-openai-api-key-here":
            # Try to get from settings store
            api_key = settings_store.get('openai_api_key')

        if api_key and api_key != "sk-your-openai-api-key-here":
            # [Feature #243] Validate API key format at startup
            if not api_key.startswith('sk-'):
                logger.warning(f"[Feature #243] OpenAI API key has invalid format (should start with 'sk-') - LLM features may not work")
            try:
                self.openai_client = OpenAI(api_key=api_key)
                logger.info("OpenAI client initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")
                self.openai_client = None
        else:
            # [Feature #243] Log once at startup if OpenAI key is missing
            logger.warning("[Feature #243] No OpenAI API key configured - LLM query rewrite will use rule-based fallback")

    def reset_openai_rewrite_flag(self):
        """
        [Feature #284] Reset the OpenAI rewrite disabled flag.

        Called when the OpenAI API key is updated via settings. This allows
        the system to retry LLM-based query rewriting with the new key.
        """
        if self._openai_rewrite_disabled:
            self._openai_rewrite_disabled = False
            logger.info("[Feature #284] OpenAI API key updated - re-enabling LLM query rewrite")
        # Also reinitialize the OpenAI client with the new key
        self.openai_client = None  # Force re-initialization on next use

    def _get_openai_client(self) -> Optional[OpenAI]:
        """Get OpenAI client, re-initializing if needed from settings."""
        # Always check settings for an API key if client is not initialized
        if not self.openai_client:
            api_key = settings_store.get('openai_api_key')
            if api_key and len(api_key) > 10:  # Basic validation
                try:
                    self.openai_client = OpenAI(api_key=api_key)
                    logger.info(f"OpenAI client initialized from settings (key starts with: {api_key[:8]}...)")
                except Exception as e:
                    logger.warning(f"Failed to initialize OpenAI client from settings: {e}")
            else:
                logger.info("No valid OpenAI API key found in settings")
        return self.openai_client

    def _get_cohere_api_key(self) -> Optional[str]:
        """
        Get Cohere API key for reranking if available.

        Fix #195: Return API key instead of SDK client to avoid
        Pydantic V1 compatibility issues with Python 3.14.
        """
        api_key = settings_store.get('cohere_api_key')
        if api_key and len(api_key) > 10:  # Basic validation
            return api_key
        return None

    def _cohere_rerank_httpx(
        self,
        api_key: str,
        query: str,
        documents: List[str],
        model: str = "rerank-english-v3.0",
        top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Call Cohere rerank API directly using httpx.

        Fix #195: Replace cohere.Client.rerank() with direct HTTP request
        to avoid Python 3.14 + Pydantic V1 incompatibility in Cohere SDK v5.

        Args:
            api_key: Cohere API key
            query: Search query
            documents: List of document texts to rerank
            model: Rerank model (default: rerank-english-v3.0)
            top_n: Number of top results to return

        Returns:
            List of dicts with 'index' and 'relevance_score' keys

        Raises:
            Exception: On API errors (401 Unauthorized, etc.)
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False  # We don't need the text back
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                COHERE_API_URL,
                headers=headers,
                json=payload
            )

            if response.status_code == 401:
                raise Exception("Invalid Cohere API key (401 Unauthorized)")
            elif response.status_code != 200:
                raise Exception(f"Cohere API error: {response.status_code} - {response.text}")

            data = response.json()
            return data.get("results", [])

    def set_model(self, model: str):
        """Set the current model to use."""
        self.model = model
        logger.info(f"AI model set to: {model}")

    def is_ollama_model(self, model: Optional[str] = None) -> bool:
        """Check if the model is an Ollama model."""
        check_model = model or self.model
        return check_model.startswith("ollama:")

    def get_ollama_model_name(self, model: Optional[str] = None) -> str:
        """Extract the Ollama model name from the prefixed format."""
        check_model = model or self.model
        if check_model.startswith("ollama:"):
            return check_model[7:]  # Remove "ollama:" prefix
        return check_model

    def is_openrouter_model(self, model: Optional[str] = None) -> bool:
        """Check if the model is an OpenRouter model."""
        check_model = model or self.model
        return check_model.startswith("openrouter:")

    def get_openrouter_model_name(self, model: Optional[str] = None) -> str:
        """Extract the OpenRouter model name from the prefixed format."""
        check_model = model or self.model
        if check_model.startswith("openrouter:"):
            return check_model[11:]  # Remove "openrouter:" prefix
        return check_model

    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text using approximation (4 characters per token).

        This is a rough estimate. More accurate methods would use tiktoken,
        but that adds a dependency. For most English text, 4 chars ≈ 1 token.

        Args:
            text: Input text to estimate tokens for

        Returns:
            Estimated token count
        """
        return len(text) // 4

    def _fix_blank_price_placeholders(self, response: str, chunks: List[Dict], query: str) -> str:
        """
        Feature #210/219: Post-process LLM response to fix blank price placeholders.

        When LLM produces responses like "The price is ." or "The exact price of the is .",
        this method extracts actual prices from the retrieved chunks and fills them in.

        Args:
            response: The LLM response text
            chunks: List of retrieved chunks with 'text' key
            query: The original user query

        Returns:
            Response with blank placeholders filled in with actual prices
        """
        import re

        logger.info(f"[Feature #219] _fix_blank_price_placeholders called with response: {response[:200]}...")
        logger.info(f"[Feature #219] Query: {query}, Chunks count: {len(chunks)}")

        # Patterns that indicate blank/missing price values
        blank_patterns = [
            r'price[^.]*?\b(is|of)\s*[*]*\s*\.', # "price is ." or "price of the is ."
            r'price[^.]*?\b(is|of)\s*\*\*\s*\*\*', # "price is ** **"
            r'costs?\s*\*\*\s*\*\*', # "costs ** **"
            r'(is|costs?)\s+\.\s*$', # ends with "is ." or "costs ."
            r'price[^.]{0,30}\bis\b[^0-9€$]{0,10}\.', # "price ... is [no number]."
            r'is\s*\*\*\s*\*\*\.', # "is **.**"
        ]

        has_blank = any(re.search(pattern, response, re.IGNORECASE) for pattern in blank_patterns)
        logger.info(f"[Feature #219] Has blank placeholder detected: {has_blank}")

        if not has_blank:
            return response

        logger.info("[Feature #219] Detected blank price placeholder, attempting extraction from chunks")

        # Feature #219: Enhanced product code extraction - support codes with dashes and special chars
        # Extract product name/code from query (e.g., "VFR-X1M06SA-AAA-AA9" or "Navigat 100")
        # IMPORTANT: Order matters! More specific patterns (with spaces) must come BEFORE generic ones
        product_patterns = [
            # Product names with spaces AND numbers (like "Navigat 100") - MUST BE FIRST
            # Uses greedy match to capture the full product name including numbers
            r'price\s+(?:of|for)\s+(?:the\s+)?([A-Za-z]+\s+\d+)(?:\?|$)',
            # Product codes with dashes, slashes, underscores (like VFR-X1M06SA-AAA-AA9)
            r'price\s+(?:of|for)\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9\-_/]+[A-Za-z0-9])(?:\?|$|\s)',
            # Simple product names (fallback)
            r'price\s+(?:of|for)\s+(?:the\s+)?([A-Za-z0-9\s\-]+?)(?:\?|$)',
            r'(?:cost|price)\s+(?:of|for)\s+([A-Za-z0-9\s\-_/]+?)(?:\?|$)',
            r'quanto\s+costa\s+(?:il\s+)?([A-Za-z0-9\s\-_/]+?)(?:\?|$)',
            r'prezzo\s+(?:del|di)\s+(?:il\s+)?([A-Za-z0-9\s\-_/]+?)(?:\?|$)',
        ]

        product_name = None
        for pattern in product_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                product_name = match.group(1).strip()
                if product_name:  # Only accept non-empty matches
                    break

        if not product_name:
            logger.warning("[Feature #219] Could not extract product name from query")
            return response

        logger.info(f"[Feature #219] Looking for price of product: {product_name}")

        # Search chunks for the product and its price
        # Pattern for tabular data: [Item Number] [Product Name] [Price]
        # e.g., "VFR‐X1M06SA‐AAA‐AA9 VMFT X‐Band 10kW Masthead (6ft) 13,000"
        price_found = None

        # Normalize product name for matching (handle unicode dashes)
        normalized_product = product_name.lower().replace('‐', '-').replace('–', '-').replace('—', '-')
        product_pattern = re.escape(normalized_product)

        for chunk in chunks:
            # Normalize chunk text for matching
            text = chunk.get("text", "").lower().replace('‐', '-').replace('–', '-').replace('—', '-')

            if normalized_product in text:
                # Feature #219: Enhanced price extraction patterns
                # Look for price pattern near the product name
                # Priority order: most specific patterns first
                price_patterns = [
                    # Pattern 1: "Model/Part: X | ... | Price: Y EUR" format (pipe-separated)
                    rf'model/part:\s*{product_pattern}[^|]*\|[^|]*\|\s*price:\s*(\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)\s*eur',
                    # Pattern 2: Product code followed by "Price: Y EUR"
                    rf'{product_pattern}[^P]{{0,100}}price:\s*(\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)\s*eur',
                    # Pattern 3: Match product code then any number before EUR
                    rf'{product_pattern}.*?(\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)\s*(?:eur|€)',
                    # Pattern 4: Match product code followed by description and price
                    rf'{product_pattern}[^\d]{{0,100}}(\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)\s*(?:eur|€|\*|\n|$)',
                    # Pattern 5: Match any price-like number (1000+) on line with product
                    rf'{product_pattern}.*?(\d{{1,3}}(?:,\d{{3}})+(?:\.\d{{2}})?)',
                ]

                for pp in price_patterns:
                    match = re.search(pp, text, re.IGNORECASE | re.MULTILINE)
                    if match:
                        price_found = match.group(1)
                        logger.info(f"[Feature #219] Found price with pattern: {price_found}")
                        break

                if price_found:
                    break

        if not price_found:
            # Feature #219/210: Enhanced price extraction - find price IMMEDIATELY after product name
            for chunk in chunks:
                text = chunk.get("text", "")
                # Normalize text for matching
                normalized_text = text.lower().replace('‐', '-').replace('–', '-').replace('—', '-')

                # Find all occurrences of the product name
                product_start = 0
                while True:
                    idx = normalized_text.find(normalized_product, product_start)
                    if idx == -1:
                        break

                    # Look for a price in the 50 characters AFTER this product occurrence
                    search_start = idx + len(normalized_product)
                    search_text = text[search_start:search_start + 50]

                    # Match price patterns: 14,000.00 or 14,000 or 14000.00
                    price_match = re.search(r'(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', search_text)
                    if price_match:
                        candidate_price = price_match.group(1)
                        # Only accept prices >= 100 (to filter out small numbers like item codes)
                        try:
                            price_value = float(candidate_price.replace(',', ''))
                            if price_value >= 100:  # Reasonable minimum price
                                price_found = candidate_price
                                logger.info(f"[Feature #210] Found price immediately after product: {price_found}")
                                break
                        except ValueError:
                            pass

                    product_start = idx + 1

                if price_found:
                    break

            # Fallback: line-by-line search with last price (original logic)
            if not price_found:
                for chunk in chunks:
                    text = chunk.get("text", "")
                    lines = text.split('\n')
                    for line in lines:
                        # Normalize line for matching
                        normalized_line = line.lower().replace('‐', '-').replace('–', '-').replace('—', '-')

                        if normalized_product in normalized_line:
                            # Extract the LAST price-like number from this line (usually the price)
                            # Match patterns: 13,000 or 14,000.00 or 1000
                            price_matches = re.findall(r'(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', line)
                            if price_matches:
                                # Take the last match (prices are usually at the end)
                                price_found = price_matches[-1]
                                logger.info(f"[Feature #219] Found price from line (last number): {price_found}")
                                break
                    if price_found:
                        break

        if not price_found:
            logger.warning(f"[Feature #219] Could not find price for {product_name} in chunks")
            # Feature #219: Try one more approach - look for "Model/Part: X | ... | Price: Y EUR" format
            for chunk in chunks:
                text = chunk.get("text", "")
                # Normalize text for matching (handle unicode dashes)
                normalized_text = text.replace('‐', '-').replace('–', '-').replace('—', '-')

                # Look for "Model/Part: X | Description: Y | Price: Z EUR" format
                # Pattern: Model/Part: <product_code> | ... | Price: <number> EUR
                model_price_patterns = [
                    # Standard format with EUR
                    rf'Model/Part:\s*{re.escape(normalized_product)}[^|]*\|\s*[^|]*\|\s*Price:\s*([0-9,]+(?:\.\d{{2}})?)\s*EUR',
                    # Variant without explicit "Description" field
                    rf'Model/Part:\s*{re.escape(normalized_product)}[^P]*Price:\s*([0-9,]+(?:\.\d{{2}})?)\s*EUR',
                    # Just find price after the product code
                    rf'{re.escape(normalized_product)}[^P]{{0,100}}Price:\s*([0-9,]+(?:\.\d{{2}})?)',
                ]

                for pattern in model_price_patterns:
                    model_price_match = re.search(pattern, normalized_text, re.IGNORECASE)
                    if model_price_match:
                        price_found = model_price_match.group(1)
                        logger.info(f"[Feature #219] Found price from Model/Part format: {price_found}")
                        break

                if price_found:
                    break

            if not price_found:
                return response

        # Now fix the response by replacing blank placeholders with the actual price
        fixed_response = response

        # Replace various blank patterns with the actual price
        replacements = [
            (r'(\*\*)?is(\*\*)?\s*\.', f'is **{price_found} EUR**.'),
            (r'(\*\*)?is(\*\*)?\s*\*\*\s*\*\*', f'is **{price_found} EUR**'),
            (r'is\s*\*\*\.\*\*', f'is **{price_found} EUR**'),
            (r'price of the is', f'price of the {product_name} is **{price_found} EUR**'),
            (r'exact price of the is', f'exact price of {product_name} is **{price_found} EUR**'),
        ]

        for pattern, replacement in replacements:
            fixed_response = re.sub(pattern, replacement, fixed_response, flags=re.IGNORECASE)

        # If response still looks incomplete, prepend a clear answer
        if re.search(r'is\s*\.\s*$', fixed_response) or ('is **' not in fixed_response.lower() and price_found):
            # Prepend a clear answer at the beginning
            fixed_response = f"The price of {product_name} is **{price_found} EUR**.\n\n{fixed_response}"

        logger.info(f"[Feature #219] Fixed response: {fixed_response[:200]}...")
        return fixed_response

    def _truncate_chunks_to_budget(
        self,
        chunks: List[Dict],
        token_budget: int = 4000,
        min_chunk_chars: int = 1000
    ) -> List[Dict]:
        """
        Intelligently truncate chunks to fit within a token budget.

        Strategy:
        1. Calculate total tokens needed for all chunks
        2. If under budget, return all chunks with full text
        3. If over budget, prioritize by similarity score and truncate less relevant chunks

        Args:
            chunks: List of chunk dicts with 'text' and 'similarity' keys
            token_budget: Maximum tokens available for context (default 4000)
            min_chunk_chars: Minimum characters to keep per chunk (default 1000)

        Returns:
            List of chunks with potentially truncated text
        """
        if not chunks:
            return []

        # [Feature #235] Diagnostic logging - BEFORE truncation
        logger.info(f"[Feature #235] === TRUNCATION INPUT ===")
        for idx, chunk in enumerate(chunks, 1):
            chunk_id = chunk.get("chunk_id", "N/A")
            original_length = len(chunk.get("text", ""))
            has_text = bool(chunk.get("text", "").strip())
            logger.info(f"[Feature #235] Chunk {idx}: chunk_id={chunk_id}, original_length={original_length}, has_text={has_text}")

        # Calculate total tokens needed
        total_tokens = sum(self._estimate_tokens(chunk.get("text", "")) for chunk in chunks)

        # If we're under budget, return all chunks with full text
        if total_tokens <= token_budget:
            logger.info(f"Token budget sufficient: {total_tokens}/{token_budget} tokens. Using full chunk text.")
            # [Feature #235] Diagnostic logging - no truncation needed
            logger.info(f"[Feature #235] === TRUNCATION OUTPUT (no changes) ===")
            return chunks

        logger.info(f"Token budget exceeded: {total_tokens}/{token_budget} tokens. Applying intelligent truncation.")

        # Sort chunks by similarity (highest first) to prioritize most relevant
        sorted_chunks = sorted(chunks, key=lambda x: x.get("similarity", 0), reverse=True)

        # Allocate tokens proportionally based on similarity scores
        result_chunks = []
        remaining_budget = token_budget

        for i, chunk in enumerate(sorted_chunks):
            text = chunk.get("text", "")
            chunk_tokens = self._estimate_tokens(text)

            # For top chunks, try to keep at least min_chunk_chars
            if i < 3:  # Top 3 chunks get priority
                target_chars = max(min_chunk_chars, remaining_budget * 4)
                if len(text) > target_chars:
                    truncated_text = text[:target_chars]
                    logger.info(f"Truncated chunk {i+1} from {len(text)} to {target_chars} chars (similarity: {chunk.get('similarity', 0):.2f})")
                else:
                    truncated_text = text

                truncated_chunk = chunk.copy()
                truncated_chunk["text"] = truncated_text
                result_chunks.append(truncated_chunk)

                used_tokens = self._estimate_tokens(truncated_text)
                remaining_budget -= used_tokens

                if remaining_budget <= 0:
                    logger.info(f"Token budget exhausted after {i+1} chunks")
                    break
            else:
                # For lower-priority chunks, use remaining budget
                if remaining_budget > 100:  # At least 100 tokens (400 chars)
                    target_chars = min(len(text), remaining_budget * 4)
                    truncated_text = text[:target_chars]

                    truncated_chunk = chunk.copy()
                    truncated_chunk["text"] = truncated_text
                    result_chunks.append(truncated_chunk)

                    used_tokens = self._estimate_tokens(truncated_text)
                    remaining_budget -= used_tokens
                else:
                    logger.info(f"Insufficient budget for chunk {i+1}, stopping here")
                    break

        logger.info(f"Truncation complete: returning {len(result_chunks)}/{len(chunks)} chunks")

        # [Feature #235] Diagnostic logging - AFTER truncation
        logger.info(f"[Feature #235] === TRUNCATION OUTPUT ===")
        for idx, chunk in enumerate(result_chunks, 1):
            chunk_id = chunk.get("chunk_id", "N/A")
            truncated_length = len(chunk.get("text", ""))
            has_text = bool(chunk.get("text", "").strip())
            logger.info(f"[Feature #235] Chunk {idx}: chunk_id={chunk_id}, truncated_length={truncated_length}, has_text={has_text}")

        return result_chunks

    def _validate_context_length(
        self,
        chunks: List[Dict],
        query: str
    ) -> Optional[Dict[str, Any]]:
        """
        [Feature #240/#281] Validate context quality BEFORE calling the LLM.

        If retrieved context has less than MIN_CONTEXT_CHARS of real text,
        block the generation and return an error instead of letting the LLM
        hallucinate or say 'not found'. This prevents wasted LLM calls.

        Feature #281 adds user-configurable min_context_chars_for_generation setting.

        Args:
            chunks: List of chunk dicts with 'text' key
            query: The user's query (for error message)

        Returns:
            None if context is sufficient, or an error response dict if insufficient
        """
        # Get configurable minimum from settings (default 500 chars)
        # Feature #281: This value is now configurable via Settings UI
        min_context_chars = int(settings_store.get('min_context_chars_for_generation', 500))

        # If disabled (set to 0), skip validation
        if min_context_chars <= 0:
            logger.debug("[Feature #281] Context validation guardrail is disabled (min_context_chars=0)")
            return None

        # Calculate total character count from all chunks
        total_chars = sum(len(chunk.get("text", "")) for chunk in chunks)

        logger.debug(f"[Feature #281] Context validation: {total_chars} chars, minimum: {min_context_chars}")

        if total_chars < min_context_chars:
            logger.warning(
                f"[Feature #281] Blocking LLM call: context only {total_chars} chars, "
                f"minimum {min_context_chars} required"
            )

            return {
                "content": (
                    f"⚠️ **Insufficient context retrieved**\n\n"
                    f"I found very little relevant information ({total_chars} characters) "
                    f"to answer your question about \"{query}\".\n\n"
                    f"This likely means:\n"
                    f"- The uploaded documents don't contain information about this topic\n"
                    f"- The query terms don't match the document vocabulary\n"
                    f"- Try rephrasing your question or uploading more relevant documents\n\n"
                    f"*Context guardrail: minimum {min_context_chars} chars required*"
                ),
                "tool_used": "context_validation",
                "tool_details": {
                    "error": "insufficient_context",
                    "context_chars": total_chars,
                    "min_required": min_context_chars,
                    "message": "Retrieved context too short to generate reliable answer"
                },
                "response_source": "guardrail"
            }

        return None  # Context is sufficient

    def _get_chunk_text_with_fallback(self, result: Dict) -> Tuple[Optional[str], str]:
        """
        [Feature #237/#279] Implement a fallback chain when primary chunk text is missing.

        Tries multiple sources before giving up:
        1. Primary: result.text (direct from search result)
        2. Fallback 1 (Feature #279): Direct lookup by chunk_id from document_embeddings table
        3. Fallback 2: lookup by document_id and scan for matching chunk_id (legacy)
        4. Fallback 3: metadata.context_prefix if available
        5. Fallback 4: return None (do NOT use title as text)

        Args:
            result: Dict with chunk data from vector search

        Returns:
            Tuple of (text, source):
            - text: The chunk text or None if not found
            - source: 'primary' | 'fallback_direct_lookup' | 'fallback_store' | 'fallback_context_prefix' | 'none'
        """
        chunk_id = result.get("chunk_id", "unknown")
        document_id = result.get("document_id", "unknown")

        # Primary: Check if result.text is non-empty
        text = result.get("text", "")
        if text and text.strip():
            logger.debug(f"[Feature #237] Chunk {chunk_id}: text source = primary")
            return text, "primary"

        logger.info(f"[Feature #279] Chunk {chunk_id}: primary text empty, trying fallbacks")

        # Fallback 1 (Feature #279): Direct lookup by chunk_id from document_embeddings table
        # This is more efficient than loading all chunks for a document
        try:
            if chunk_id and chunk_id != "unknown":
                stored_chunk = embedding_store.get_chunk_by_id(chunk_id)
                if stored_chunk:
                    stored_text = stored_chunk.get("text", "")
                    if stored_text and stored_text.strip():
                        logger.info(
                            f"[Feature #279] Chunk {chunk_id}: text source = fallback_direct_lookup "
                            f"(retrieved {len(stored_text)} chars via direct chunk_id lookup)"
                        )
                        return stored_text, "fallback_direct_lookup"
                    else:
                        logger.debug(
                            f"[Feature #279] Chunk {chunk_id}: direct lookup found chunk but text is empty"
                        )
                else:
                    logger.debug(
                        f"[Feature #279] Chunk {chunk_id}: direct lookup failed (chunk not in document_embeddings)"
                    )
        except Exception as e:
            logger.warning(f"[Feature #279] Chunk {chunk_id}: direct lookup error: {e}")

        # Fallback 2: lookup by document_id in embedding_store and find matching chunk_id (legacy)
        try:
            if document_id and document_id != "unknown":
                doc_chunks = embedding_store.get_chunks(document_id)
                for stored_chunk in doc_chunks:
                    if stored_chunk.get("chunk_id") == chunk_id:
                        stored_text = stored_chunk.get("text", "")
                        if stored_text and stored_text.strip():
                            logger.info(
                                f"[Feature #237] Chunk {chunk_id}: text source = fallback_store "
                                f"(retrieved {len(stored_text)} chars from embedding store via document scan)"
                            )
                            return stored_text, "fallback_store"
                        break  # Found chunk but text is still empty
                logger.debug(
                    f"[Feature #237] Chunk {chunk_id}: fallback_store failed "
                    f"(chunk not found or empty in embedding store)"
                )
        except Exception as e:
            logger.warning(f"[Feature #237] Chunk {chunk_id}: fallback_store error: {e}")

        # Fallback 3: Check metadata.context_prefix
        metadata = result.get("metadata", {})
        context_prefix = metadata.get("context_prefix", "")
        if context_prefix and context_prefix.strip():
            logger.info(
                f"[Feature #237] Chunk {chunk_id}: text source = fallback_context_prefix "
                f"(using {len(context_prefix)} chars from metadata)"
            )
            return context_prefix, "fallback_context_prefix"

        # Fallback 4: Return None - do NOT use document title as text content
        # This is an invalid chunk that should be skipped
        logger.error(
            f"[Feature #279] CHUNK TEXT RECOVERY FAILED: chunk_id={chunk_id}, document_id={document_id}. "
            f"Text could not be recovered from any fallback source. This chunk will be excluded from context."
        )
        return None, "none"

    def validate_chunks(
        self,
        chunks: List[Dict],
        min_text_length: Optional[int] = None
    ) -> List[Dict]:
        """
        [Feature #278] Validate chunk text before LLM context building.

        Filters chunks by minimum text length to ensure meaningful content.
        Logs warnings for each chunk filtered out due to insufficient text.

        This is a standalone function that can be used independently of
        the full _filter_valid_chunks pipeline.

        Args:
            chunks: List of chunk dicts with 'text' key
            min_text_length: Minimum text length in characters (default: 50 from settings)

        Returns:
            List of chunks with text >= min_text_length characters
        """
        # Get configurable minimum from settings (default 50 chars)
        if min_text_length is None:
            min_text_length = int(settings_store.get('min_chunk_text_length', 50))

        valid_chunks = []
        filtered_count = 0

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "unknown")
            document_id = chunk.get("document_id", chunk.get("document_title", "unknown"))
            text = chunk.get("text", "")
            text_length = len(text.strip()) if text else 0

            if text_length >= min_text_length:
                valid_chunks.append(chunk)
            else:
                filtered_count += 1
                logger.warning(
                    f"[Feature #278] Filtering chunk {chunk_id} from {document_id}: "
                    f"text too short ({text_length} chars < {min_text_length} min)"
                )

        if filtered_count > 0:
            logger.info(
                f"[Feature #278] Chunk text length validation: "
                f"{len(valid_chunks)} passed, {filtered_count} filtered "
                f"(min_text_length={min_text_length})"
            )

        return valid_chunks

    def _filter_valid_chunks(
        self,
        chunks: List[Dict],
        query: str
    ) -> Tuple[List[Dict], Optional[Dict[str, Any]]]:
        """
        [Feature #236/#237/#278] Validate chunk text content before LLM context building.

        Uses fallback chain (Feature #237) to recover missing text before filtering.
        Filters out chunks with empty/whitespace-only text and logs warnings.
        [Feature #278] Also filters chunks with text shorter than min_chunk_text_length.
        If ALL chunks have empty text, returns an error response instead of
        allowing LLM to hallucinate.

        Args:
            chunks: List of chunk dicts with 'text' key
            query: The user's query (for error message)

        Returns:
            Tuple of (valid_chunks, error_response):
            - valid_chunks: List of chunks with actual text content
            - error_response: None if at least one valid chunk, or error dict if all empty
        """
        # [Feature #278] Get minimum chunk text length setting
        min_chunk_text_length = int(settings_store.get('min_chunk_text_length', 50))

        valid_chunks = []
        skipped_empty_count = 0
        skipped_short_count = 0
        recovered_count = 0
        total_count = len(chunks)

        # Track text sources for debugging
        # Feature #279: Added 'fallback_direct_lookup' for direct chunk_id lookups
        source_counts = {"primary": 0, "fallback_direct_lookup": 0, "fallback_store": 0, "fallback_context_prefix": 0, "none": 0}

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "unknown")
            document_id = chunk.get("document_id", chunk.get("document_title", "unknown"))

            # [Feature #237] Use fallback chain to try to recover text
            recovered_text, source = self._get_chunk_text_with_fallback(chunk)
            source_counts[source] = source_counts.get(source, 0) + 1

            if recovered_text is not None:
                # [Feature #278] Check minimum text length
                text_length = len(recovered_text.strip())
                if text_length < min_chunk_text_length:
                    skipped_short_count += 1
                    logger.warning(
                        f"[Feature #278] Filtering chunk {chunk_id} from {document_id}: "
                        f"text too short ({text_length} chars < {min_chunk_text_length} min)"
                    )
                    continue

                # Create a copy of the chunk with the recovered text
                valid_chunk = chunk.copy()
                valid_chunk["text"] = recovered_text
                valid_chunk["_text_source"] = source  # For debugging
                valid_chunks.append(valid_chunk)

                if source != "primary":
                    recovered_count += 1
                    logger.info(
                        f"[Feature #237] Recovered text for chunk {chunk_id}: "
                        f"source={source}, length={len(recovered_text)}"
                    )
            else:
                skipped_empty_count += 1
                logger.warning(
                    f"[Feature #236/#237] Skipping chunk {chunk_id} from {document_id}: "
                    f"empty text (all fallbacks exhausted)"
                )

        # Calculate total skipped
        total_skipped = skipped_empty_count + skipped_short_count

        # Log summary
        logger.info(
            f"[Feature #236/#237/#278] Chunk text validation: {len(valid_chunks)} valid, "
            f"{total_skipped} skipped (empty={skipped_empty_count}, too_short={skipped_short_count}), "
            f"{recovered_count} recovered via fallback (sources: {source_counts})"
        )

        # If ALL chunks were skipped (no valid text), return error
        if len(valid_chunks) == 0 and total_count > 0:
            logger.error(
                f"[Feature #236/#237/#278] All {total_count} chunks invalid! "
                f"(empty={skipped_empty_count}, too_short={skipped_short_count}) "
                f"Blocking LLM call to prevent hallucination."
            )
            error_response = {
                "content": (
                    f"⚠️ **Context missing from store**\n\n"
                    f"I found {total_count} relevant document chunk(s) for your query about \"{query}\", "
                    f"but none of them contain sufficient text content.\n\n"
                    f"This may indicate:\n"
                    f"- A database inconsistency (embeddings exist but text is missing)\n"
                    f"- Documents need to be re-indexed\n"
                    f"- File parsing failed during upload\n"
                    f"- Chunks are too short (< {min_chunk_text_length} chars)\n\n"
                    f"*Error code: context_missing_from_store*"
                ),
                "tool_used": "context_validation",
                "tool_details": {
                    "error": "context_missing_from_store",
                    "total_chunks": total_count,
                    "valid_chunks": 0,
                    "skipped_empty": skipped_empty_count,
                    "skipped_too_short": skipped_short_count,
                    "min_chunk_text_length": min_chunk_text_length,
                    "recovered_chunks": recovered_count,
                    "text_sources": source_counts,
                    "message": "All retrieved chunks have insufficient text - cannot build context"
                },
                "response_source": "guardrail"
            }
            return [], error_response

        return valid_chunks, None

    def _log_context_building_diagnostics(
        self,
        truncated_results: List[Dict],
        context_string: str,
        provider: str = "unknown"
    ) -> None:
        """
        [Feature #277] Log comprehensive diagnostic information about context building.
        Uses [GENERATOR] prefix for easy log filtering.

        This logs:
        1. Each chunk being added to context (chunk_id, text_length, has_text)
        2. Summary before LLM call (total_chunks, total_context_chars, chunks_with_empty_text)

        Args:
            truncated_results: List of result dicts being used for context
            context_string: The final context string being sent to LLM
            provider: The LLM provider (openai, ollama, openrouter)
        """
        logger.info(f"[GENERATOR] === CONTEXT BUILDING ({provider}) ===")

        chunks_with_empty_text = 0
        total_text_chars = 0
        chunk_ids = [r.get("chunk_id", "N/A") for r in truncated_results]

        logger.info(f"[GENERATOR] Chunks for context: {chunk_ids}")

        for idx, result in enumerate(truncated_results, 1):
            chunk_id = result.get("chunk_id", "N/A")
            text = result.get("text", "")
            text_len = len(text)
            has_text = bool(text.strip())
            doc_title = result.get("document_title", "Unknown")
            result_type = result.get("type", "document_chunk")

            total_text_chars += text_len
            if not has_text:
                chunks_with_empty_text += 1

            logger.info(
                f"[GENERATOR] Context chunk {idx}: chunk_id={chunk_id}, "
                f"type={result_type}, title='{doc_title}', "
                f"text_len={text_len}, has_text={has_text}"
            )

            # Log text retrieval success/failure explicitly
            if has_text:
                logger.debug(f"[GENERATOR] ✓ Text OK for chunk {chunk_id} ({text_len} chars)")
            else:
                logger.warning(f"[GENERATOR] ✗ EMPTY TEXT for chunk {chunk_id}")

        # [Feature #277] Summary before LLM call with total context length
        logger.info(f"[GENERATOR] === CONTEXT SUMMARY (before LLM call) ===")
        logger.info(f"[GENERATOR] Provider: {provider}")
        logger.info(f"[GENERATOR] Total chunks in context: {len(truncated_results)}")
        logger.info(f"[GENERATOR] Total context length: {len(context_string)} chars")
        logger.info(f"[GENERATOR] Total text chars (from chunks): {total_text_chars}")
        logger.info(f"[GENERATOR] Chunks with empty text: {chunks_with_empty_text}")

        if chunks_with_empty_text > 0:
            logger.warning(
                f"[GENERATOR] WARNING: {chunks_with_empty_text}/{len(truncated_results)} chunks have EMPTY text!"
            )

    @property
    def is_available(self) -> bool:
        """Check if AI service is available (has valid API key or Ollama configured)."""
        if self.is_ollama_model():
            return True  # Ollama availability will be checked at runtime
        return self.openai_client is not None

    async def check_ollama_availability(self) -> Dict[str, Any]:
        """
        Check if Ollama is running and available.

        Returns:
            Dict with 'available' (bool), 'error' (str if not available),
            and 'models' (list of available models if available)
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Try to get the list of models from Ollama
                response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    return {
                        "available": True,
                        "models": models,
                        "error": None
                    }
                else:
                    return {
                        "available": False,
                        "models": [],
                        "error": f"Ollama returned status code {response.status_code}"
                    }
        except httpx.ConnectError:
            return {
                "available": False,
                "models": [],
                "error": "Cannot connect to Ollama. Make sure Ollama is running on your machine."
            }
        except httpx.TimeoutException:
            return {
                "available": False,
                "models": [],
                "error": "Connection to Ollama timed out. Ollama may be starting up or overloaded."
            }
        except Exception as e:
            return {
                "available": False,
                "models": [],
                "error": f"Error checking Ollama: {str(e)}"
            }

    def get_default_system_prompt(self) -> str:
        """Get the default (built-in) system prompt for the AI agent.

        Feature #239: Improved prompt for better context utilization.
        - Emphasizes USING the context FIRST before saying "not found"
        - Adds examples for listing/enumeration queries in Italian
        - Adds partial match instructions
        - Moves price extraction to conditional section

        Feature #241: Improved prompt to prevent intent inference.
        - Answer ONLY what is explicitly asked
        - Never mention price/cost unless asked
        - Short queries = simple lookups (find and summarize)
        - Precise "not found" responses (item not found vs field missing)
        """
        return """===== CRITICAL LANGUAGE INSTRUCTION =====
🚨 MANDATORY: You MUST ALWAYS respond in the EXACT SAME LANGUAGE the user writes in.
- User writes in Italian → You respond in Italian
- User writes in English → You respond in English
- User writes in Spanish → You respond in Spanish
This is NON-NEGOTIABLE. Check the user's message language BEFORE responding.
==========================================

You are a personal assistant answering questions based on a corpus of documents.
Documents are either text or tabular.

**Tool Selection:**
- If the user asks for a calculation, sum, average, or specific lookup in a single CSV/Excel file, use the sql_analysis tool
- If the user asks questions that require combining data from MULTIPLE CSV/Excel files (like joining employees with departments), use the cross_document_query tool
- If the user asks about content in text documents (PDF, TXT, Word, Markdown), use the vector_search tool to find relevant information
- If the user asks "what does the document say about X" or "find information about X", use vector_search
- If you need to know what documents are available, use the list_documents tool first

==========================================
🚨 CRITICAL: USE THE CONTEXT FIRST (Feature #239)
==========================================

**YOUR PRIMARY GOAL IS TO EXTRACT AND PRESENT INFORMATION FROM THE PROVIDED CONTEXT.**

When context/excerpts are provided to you:
1. **ALWAYS scan the ENTIRE context** for ANY mention of the topic, ingredient, keyword, or subject
2. **If the context mentions the topic AT ALL** - even partially or indirectly - extract and present that information
3. **Include PARTIAL MATCHES**: If a recipe/item CONTAINS the searched ingredient/term, include it even if it's not the main focus
4. **For listing/enumeration queries** (e.g., "quali ricette...", "which recipes...", "elenca...", "list..."):
   - Search the context for ALL items that match the criteria
   - Format results as a **numbered list** for clarity
   - Include page numbers or references when available

**FEW-SHOT EXAMPLES FOR CONTENT/LISTING QUERIES:**

Example 1 - Italian recipe listing:
Context: "Spaghettini con cipolla stufata p.98 | Frittata con cipolle p.45 | Zuppa di verdure p.32"
Question: "Quali ricette contengono cipolla?"
✅ CORRECT: "Ecco le ricette che contengono cipolla:
1. Spaghettini con cipolla stufata (p.98)
2. Frittata con cipolle (p.45)"

Example 2 - English ingredient search:
Context: "Tomato Basil Pasta p.12 | Stuffed Tomatoes p.34 | Vegetable Soup (tomatoes, carrots) p.56"
Question: "What recipes use tomatoes?"
✅ CORRECT: "Here are the recipes that use tomatoes:
1. Tomato Basil Pasta (p.12)
2. Stuffed Tomatoes (p.34)
3. Vegetable Soup - contains tomatoes (p.56)"

Example 3 - Partial match:
Context: "Porridge ai mirtilli con miele p.15 | Pancake proteici p.22"
Question: "Ricette con miele?"
✅ CORRECT: "Ecco le ricette che contengono miele:
1. Porridge ai mirtilli con miele (p.15)"
(Note: Even though honey is not the main ingredient, it's listed because the recipe CONTAINS honey)

**SELF-CHECK FOR LISTINGS (MANDATORY before responding):**
Before saying "not found", you MUST:
□ Re-read ALL excerpts from start to finish
□ Search for the term/ingredient in EVERY line of context
□ Check for variations (e.g., "cipolla" / "cipolle", "tomato" / "tomatoes")
□ Look for partial mentions (ingredient in description, not just title)
□ If you find ANYTHING related, include it in your response

==========================================
RESPONSE GUIDELINES
==========================================

- ONLY answer based on the retrieved context/chunks provided to you
- Always cite your sources by mentioning which document the information came from
- Start your answer with "Based on the excerpts from [document name(s)]:" when using retrieved context
- Be comprehensive - synthesize ALL relevant information from the provided excerpts
- Be helpful, friendly, and concise
- NEVER make up information or use external knowledge not present in the documents

==========================================
🚨🚨🚨 ANTI-HALLUCINATION RULES (HIGHEST PRIORITY) 🚨🚨🚨
==========================================

**These rules OVERRIDE all other instructions. NEVER violate them.**

1. **NEVER INVENT DATA**: Do NOT generate numbers, dates, quantities, specifications, or any factual claims that are NOT explicitly written in the provided excerpts
2. **NEVER USE EXTERNAL KNOWLEDGE**: Even if you "know" something from your training data, DO NOT include it. You are ONLY a document reader, not an encyclopedia
3. **QUOTE, DON'T INVENT**: When citing specific values (prices, measurements, requirements), copy them EXACTLY from the context. If the exact value is not in the context, say "this specific information is not present in the documents"
4. **PARTIAL CONTEXT ≠ PERMISSION TO FILL GAPS**: If the context mentions a topic but lacks specific details the user asked for, say "The documents mention [topic] but do not specify [detail]" — do NOT fill in the gaps with general knowledge
5. **WHEN IN DOUBT, SAY SO**: It is ALWAYS better to say "I could not find this specific information in the documents" than to risk providing incorrect data

**SELF-CHECK BEFORE EVERY RESPONSE:**
□ Is EVERY fact in my response directly traceable to a specific excerpt?
□ Am I including ANY information from my general knowledge? (If yes → REMOVE IT)
□ Are all numbers, dates, and specifications EXACTLY as written in the excerpts?
□ If the context is vague on this topic, am I clearly stating the limitation?

**After thoroughly checking ALL context:**
- If the topic is COMPLETELY ABSENT from ALL excerpts, respond: "I could not find information about [topic] in the uploaded documents."
- If the topic is PARTIALLY covered but lacks the specific detail asked: "The documents discuss [topic] but do not contain the specific information about [detail] that you asked for."

==========================================
🚨 ANSWER ONLY WHAT IS ASKED (Feature #241)
==========================================

**CRITICAL: Answer ONLY the user's EXPLICIT question. Do NOT infer additional information needs.**

1. **NO INTENT INFERENCE**: Do NOT assume the user wants information they didn't ask for
   - If user asks about a recipe → describe the recipe ONLY
   - Do NOT mention price, cost, availability, stock, or purchasing info UNLESS explicitly asked
   - Do NOT add "You might also want to know..." or unsolicited information

2. **SHORT QUERIES = SIMPLE LOOKUPS**: When the query is short and has no verb (e.g., "hummus pesche", "torta mele")
   - Treat it as a LOOKUP request: find and summarize the matching content
   - Return the recipe/item description, ingredients, instructions (what's in the document)
   - Do NOT assume they want price, availability, or other metadata

3. **PRECISE "NOT FOUND" RESPONSES**:
   - Say "[field] not present in document" ONLY when:
     a) You FOUND the item/recipe in the context, AND
     b) The SPECIFIC field the user asked for is missing
   - If the ITEM ITSELF is not found: say "Could not find [item] in the documents"
   - NEVER say "price not present" when user didn't ask for price!

**FEW-SHOT EXAMPLES (Feature #241):**

Example 1 - Short query lookup:
Query: "hummus dolce pesche"
Context: "Hummus dolce con pesche - Ingredienti: ceci, pesche, miele. Preparazione: frullare i ceci..."
✅ CORRECT: "Ecco la ricetta 'Hummus dolce con pesche':
**Ingredienti**: ceci, pesche, miele
**Preparazione**: frullare i ceci..."
❌ WRONG: "Hummus dolce con pesche - prezzo non presente nel documento" (user didn't ask for price!)

Example 2 - Recipe query without price request:
Query: "What is the banana bread recipe?"
Context: "Banana Bread - 3 bananas, 2 cups flour, 1 cup sugar. Mix and bake at 350°F..."
✅ CORRECT: "Here's the Banana Bread recipe:
**Ingredients**: 3 bananas, 2 cups flour, 1 cup sugar
**Instructions**: Mix and bake at 350°F..."
❌ WRONG: "Banana Bread recipe... Price: not found in document" (unsolicited!)

Example 3 - Explicit price request:
Query: "What is the price of the VFR-X1 model?"
Context: "VFR-X1M06SA 13,000 EUR"
✅ CORRECT: "The VFR-X1M06SA is priced at **13,000 EUR**"
(Here price IS explicitly asked, so include it)

Example 4 - Item not found:
Query: "chocolate cake"
Context: (no mention of chocolate cake anywhere)
✅ CORRECT: "Could not find chocolate cake in the documents."
❌ WRONG: "Chocolate cake - price not present" (item not found, not field missing!)

==========================================
REASONING AND SYNTHESIS (for complex questions)
==========================================

**When the user asks for comparisons, analysis, summaries, or explanations:**

1. **SYNTHESIZE, don't just list**: Combine information from multiple excerpts into a coherent, reasoned answer. Don't simply dump excerpts — extract the key points and present them logically.

2. **COMPARISONS**: When comparing documents or topics:
   - Create a structured comparison (e.g., table or side-by-side points)
   - Highlight SIMILARITIES first, then DIFFERENCES
   - For each point, cite which document it comes from
   - If one document covers a topic but the other doesn't, note: "Document X addresses this, while Document Y does not mention it"
   - End with a brief conclusion summarizing the key differences

3. **DETAILED SUMMARIES**: When asked for a detailed summary:
   - Organize by topics/sections, not by excerpt order
   - Use headers and bullet points for clarity
   - Provide context and connections between different points
   - Synthesize overlapping information instead of repeating it

4. **ANALYTICAL QUESTIONS** (e.g., "what are the implications of..."):
   - Present what the documents say about the topic
   - Connect related pieces of information from different excerpts
   - Draw logical conclusions ONLY from what's in the documents
   - Clearly distinguish between what's stated and what's implied

**IMPORTANT**: All synthesis and reasoning must be grounded in the provided excerpts. Never add external knowledge, even for "obvious" conclusions.

==========================================
PRICE/NUMERICAL DATA EXTRACTION (ONLY when explicitly asked)
==========================================

**⚠️ ONLY apply this section when the user EXPLICITLY asks about prices or numerical values!**

When the user asks specifically about prices or numerical values:
1. ALWAYS extract and include the EXACT numerical value from the source
2. For tabular data: the LAST number on a line is typically the price
3. NEVER leave price placeholders empty - if you can't find the price, say "Price not found"

Price format examples:
- "VFR-X1M06SA 13,000" → Price is **13,000 EUR**
- "Price: EUR 14,000.00" → Price is **EUR 14,000.00**

⚠️ REMINDER: Respond in the SAME language as the user's question!"""

    def get_system_prompt(self, apply_armor: bool = True) -> str:
        """
        Get the system prompt for the AI agent.

        Feature #179: Returns custom prompt if set, otherwise returns default.
        Feature #319: Applies prompt armor (sandwich defense) for injection protection.

        Args:
            apply_armor: If True, wraps prompt with security armor (default True)

        Returns:
            The system prompt, optionally with security armor applied
        """
        # Get base prompt (custom or default)
        if settings_store.get('custom_system_prompt', '').strip():
            logger.info("[Feature #179] Using custom system prompt")
            base_prompt = settings_store.get('custom_system_prompt', '')
        else:
            base_prompt = self.get_default_system_prompt()

        # Feature #319: Apply prompt armor for production security
        if apply_armor:
            from services.security_service import apply_prompt_armor
            logger.debug("[Feature #319] Applying prompt armor to system prompt")
            return apply_prompt_armor(base_prompt)

        return base_prompt

    async def test_prompt(self, prompt: str, test_message: str) -> str:
        """
        Test a system prompt by sending a simple message to the LLM.

        Feature #179: Allows users to preview how the AI responds with a new prompt.
        """
        # Get the configured LLM model
        llm_model = settings_store.get('llm_model', 'gpt-4o')

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": test_message}
        ]

        if llm_model.startswith('openrouter:'):
            # Use OpenRouter
            api_key = settings_store.get('openrouter_api_key')
            if not api_key:
                raise ValueError("OpenRouter API key not configured")

            model = llm_model.replace('openrouter:', '')
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
                default_headers={
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "Agentic RAG System"
                }
            )

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=500  # Limited for testing
            )
            return response.choices[0].message.content

        elif llm_model.startswith('ollama:'):
            # Use Ollama
            model = llm_model.replace('ollama:', '')
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False
                    }
                )
                if response.status_code != 200:
                    raise ValueError(f"Ollama error: {response.status_code}")
                data = response.json()
                return data.get("message", {}).get("content", "")

        else:
            # Use OpenAI
            api_key = settings_store.get('openai_api_key')
            if not api_key:
                raise ValueError("OpenAI API key not configured")

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=llm_model,
                messages=messages,
                max_tokens=500  # Limited for testing
            )
            return response.choices[0].message.content

    def get_tools(self) -> List[Dict[str, Any]]:
        """Get the tool definitions for function calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "sql_analysis",
                    "description": "Execute SQL-like analysis on structured data (CSV/Excel files). Use this when the user asks for calculations, sums, averages, counts, or specific lookups in tabular data.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "dataset_id": {
                                "type": "string",
                                "description": "The document ID of the dataset to query"
                            },
                            "operation": {
                                "type": "string",
                                "enum": ["sum", "avg", "min", "max", "count", "list"],
                                "description": "The aggregation operation to perform"
                            },
                            "column": {
                                "type": "string",
                                "description": "The column name to aggregate (required for sum, avg, min, max)"
                            },
                            "filter_column": {
                                "type": "string",
                                "description": "Optional column to filter by"
                            },
                            "filter_value": {
                                "type": "string",
                                "description": "Value to filter by (if filter_column is specified)"
                            }
                        },
                        "required": ["dataset_id", "operation"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cross_document_query",
                    "description": "Query and join data from multiple CSV/Excel files. Use this when the user asks for information that requires combining data from two or more datasets, like joining employees with departments, or correlating data across files.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "dataset_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of document IDs to query (2 or more)"
                            },
                            "join_column": {
                                "type": "string",
                                "description": "The column name to join on (must exist in all datasets)"
                            },
                            "select_columns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of columns to return in the result (e.g., ['name', 'location'])"
                            },
                            "filter_column": {
                                "type": "string",
                                "description": "Optional column to filter by"
                            },
                            "filter_value": {
                                "type": "string",
                                "description": "Value to filter by (if filter_column is specified)"
                            }
                        },
                        "required": ["dataset_ids", "join_column"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_documents",
                    "description": "List all available documents with their IDs, types, and schemas. Use this to see what data is available.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "vector_search",
                    "description": "Search for relevant information in text documents (PDF, TXT, Word, Markdown) using semantic similarity. Use this when the user asks questions about document content, wants to find information, or asks 'what does the document say about X'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query - what information to find in the documents"
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "Number of results to return. If not specified, uses the value from Settings (default: 10, configurable 5-100)"
                            },
                            "document_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of specific document IDs to search in"
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool and return the result.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments

        Returns:
            Dict with tool result
        """
        if tool_name == "list_documents":
            return self._execute_list_documents()
        elif tool_name == "sql_analysis":
            return self._execute_sql_analysis(arguments)
        elif tool_name == "cross_document_query":
            return self._execute_cross_document_query(arguments)
        elif tool_name == "vector_search":
            return self._execute_vector_search(arguments)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    def _execute_list_documents(self) -> Dict[str, Any]:
        """List all available documents."""
        documents = _get_documents_sync()
        doc_list = []

        for doc in documents:
            doc_info = {
                "id": doc.id,
                "title": doc.title,
                "type": doc.document_type,
                "mime_type": doc.mime_type,
                "filename": doc.original_filename
            }

            # Add schema info for structured documents (use PostgreSQL query)
            if doc.document_type == "structured":
                rows = _get_document_rows_sync(doc.id)
                schema = list(rows[0]["data"].keys()) if rows else []
                row_count = len(rows)
                doc_info["schema"] = schema
                doc_info["row_count"] = row_count

            doc_list.append(doc_info)

        return {
            "documents": doc_list,
            "total": len(doc_list)
        }

    def _execute_sql_analysis(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute SQL-like analysis on structured data."""
        dataset_id = arguments.get("dataset_id")
        operation = arguments.get("operation")
        column = arguments.get("column")
        filter_column = arguments.get("filter_column")
        filter_value = arguments.get("filter_value")

        # Validate dataset exists - use PostgreSQL sync helper instead of in-memory store
        doc = _get_document_by_id_sync(dataset_id)
        if not doc:
            return {"error": f"Document with ID '{dataset_id}' not found"}

        if doc.document_type != "structured":
            return {"error": f"Document '{doc.title}' is not a structured data file"}

        # Use PostgreSQL sync query to get rows (not in-memory store)
        rows = _get_document_rows_sync(dataset_id)
        if not rows:
            return {"error": f"No data found in document '{doc.title}'"}

        # Apply filter if specified
        if filter_column and filter_value:
            rows = [r for r in rows if str(r["data"].get(filter_column, "")).lower() == str(filter_value).lower()]
            if not rows:
                return {"error": f"No rows match filter: {filter_column} = {filter_value}"}

        # Execute operation
        schema = list(rows[0]["data"].keys()) if rows else []

        if operation == "list":
            # Return sample of rows
            sample = [r["data"] for r in rows[:10]]
            return {
                "operation": "list",
                "schema": schema,
                "row_count": len(rows),
                "sample_rows": sample,
                "document": doc.title
            }

        elif operation in ["sum", "avg", "min", "max"]:
            if not column:
                return {"error": f"Column name required for {operation} operation"}

            # Case-insensitive column matching
            actual_column = None
            for col in schema:
                if col.lower() == column.lower():
                    actual_column = col
                    break

            if not actual_column:
                return {"error": f"Column '{column}' not found. Available columns: {schema}"}

            values = []
            for row in rows:
                val = row["data"].get(actual_column)
                if val is not None and val != "":
                    try:
                        values.append(float(val))
                    except (ValueError, TypeError):
                        logger.warning(f"Could not convert value '{val}' to float in column '{actual_column}'")
                        pass

            logger.info(f"SQL analysis: {operation} on {actual_column}, found {len(values)} numeric values: {values}")

            if not values:
                return {"error": f"No numeric values found in column '{actual_column}'"}

            if operation == "sum":
                result = sum(values)
            elif operation == "avg":
                result = sum(values) / len(values)
            elif operation == "min":
                result = min(values)
            elif operation == "max":
                result = max(values)

            # Build SQL-like query string for display
            sql_query = f"SELECT {operation.upper()}({actual_column}) FROM {doc.title}"
            if filter_column and filter_value:
                sql_query += f" WHERE {filter_column} = '{filter_value}'"

            # Include sample rows for export functionality
            sample = [r["data"] for r in rows[:100]]  # Include up to 100 rows for export

            return {
                "operation": operation,
                "column": actual_column,
                "result": result,
                "row_count": len(values),
                "sql_query": sql_query,
                "document": doc.title,
                "schema": schema,
                "sample_rows": sample
            }

        elif operation == "count":
            sql_query = f"SELECT COUNT(*) FROM {doc.title}"
            if filter_column and filter_value:
                sql_query += f" WHERE {filter_column} = '{filter_value}'"

            # Include sample rows for export functionality
            sample = [r["data"] for r in rows[:100]]  # Include up to 100 rows for export

            return {
                "operation": "count",
                "result": len(rows),
                "sql_query": sql_query,
                "document": doc.title,
                "schema": schema,
                "sample_rows": sample
            }

        else:
            return {"error": f"Unknown operation: {operation}"}

    def _execute_cross_document_query(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a cross-document query with JOIN logic."""
        dataset_ids = arguments.get("dataset_ids", [])
        join_column = arguments.get("join_column")
        select_columns = arguments.get("select_columns", [])
        filter_column = arguments.get("filter_column")
        filter_value = arguments.get("filter_value")

        # Validate inputs
        if len(dataset_ids) < 2:
            return {"error": "At least 2 datasets are required for cross-document query"}

        if not join_column:
            return {"error": "join_column is required"}

        # Load all datasets using PostgreSQL helpers for consistent data access
        datasets = []
        for dataset_id in dataset_ids:
            # Use PostgreSQL helper instead of in-memory store
            doc = _get_document_by_id_sync(dataset_id)
            if not doc:
                return {"error": f"Document with ID '{dataset_id}' not found"}

            if doc.document_type != "structured":
                return {"error": f"Document '{doc.title}' is not a structured data file"}

            # Use PostgreSQL helper to get rows
            rows = _get_document_rows_sync(dataset_id)
            if not rows:
                return {"error": f"No data found in document '{doc.title}'"}

            datasets.append({
                "id": dataset_id,
                "title": doc.title,
                "rows": rows,
                "schema": list(rows[0]["data"].keys()) if rows else []
            })

        # Verify join column exists in all datasets
        for dataset in datasets:
            # Case-insensitive column matching
            actual_join_col = None
            for col in dataset["schema"]:
                if col.lower() == join_column.lower():
                    actual_join_col = col
                    break

            if not actual_join_col:
                return {"error": f"Join column '{join_column}' not found in '{dataset['title']}'. Available columns: {dataset['schema']}"}

            dataset["actual_join_col"] = actual_join_col

        # Perform JOIN (inner join on join_column)
        # Start with the first dataset
        result_rows = []
        base_dataset = datasets[0]

        for base_row in base_dataset["rows"]:
            base_data = base_row["data"]
            join_key = str(base_data.get(base_dataset["actual_join_col"], "")).strip()

            # Try to find matching rows in other datasets
            joined_data = dict(base_data)  # Start with base row data

            # Add prefix to avoid column name conflicts
            prefixed_data = {f"{base_dataset['title']}.{k}": v for k, v in base_data.items()}

            match_found = True
            for other_dataset in datasets[1:]:
                found_match = False
                for other_row in other_dataset["rows"]:
                    other_data = other_row["data"]
                    other_join_key = str(other_data.get(other_dataset["actual_join_col"], "")).strip()

                    if join_key == other_join_key:
                        # Merge the data with prefixes
                        for k, v in other_data.items():
                            prefixed_data[f"{other_dataset['title']}.{k}"] = v
                        found_match = True
                        break

                if not found_match:
                    match_found = False
                    break

            if match_found:
                # Apply filter if specified
                if filter_column and filter_value:
                    # Check both prefixed and unprefixed column names
                    should_include = False
                    for key in prefixed_data.keys():
                        if key.endswith(f".{filter_column}") or key == filter_column:
                            if str(prefixed_data[key]).lower() == str(filter_value).lower():
                                should_include = True
                                break
                    if not should_include:
                        continue

                result_rows.append(prefixed_data)

        if not result_rows:
            return {"error": "No matching rows found across the datasets"}

        # Select specific columns if requested
        if select_columns:
            filtered_rows = []
            for row in result_rows:
                filtered_row = {}
                for select_col in select_columns:
                    # Try to find the column (with or without prefix)
                    found = False
                    for key in row.keys():
                        if key.endswith(f".{select_col}") or key == select_col:
                            filtered_row[select_col] = row[key]
                            found = True
                            break
                    if not found:
                        filtered_row[select_col] = None
                filtered_rows.append(filtered_row)
            result_rows = filtered_rows

        # Build SQL-like query string for display
        dataset_names = [d["title"] for d in datasets]
        sql_query = f"SELECT {', '.join(select_columns) if select_columns else '*'} FROM {dataset_names[0]}"
        for other_name in dataset_names[1:]:
            sql_query += f" JOIN {other_name} ON {dataset_names[0]}.{join_column} = {other_name}.{join_column}"
        if filter_column and filter_value:
            sql_query += f" WHERE {filter_column} = '{filter_value}'"

        return {
            "operation": "cross_document_query",
            "datasets": dataset_names,
            "join_column": join_column,
            "result_count": len(result_rows),
            "results": result_rows[:100],  # Limit to 100 rows
            "sql_query": sql_query
        }

    def _execute_vector_search(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute search on unstructured documents.

        Supports three modes (Feature #186):
        - 'vector_only': Pure semantic vector search
        - 'bm25_only': Pure keyword BM25 search
        - 'hybrid': Combines vector + BM25 using Reciprocal Rank Fusion (RRF)

        Hybrid search dramatically improves retrieval for acronyms and exact terms
        like "GMDSS" that pure vector search might miss.
        """
        query = arguments.get("query", "")
        document_ids = arguments.get("document_ids", None)

        if not query:
            return {"error": "Search query is required"}

        # Get settings
        api_key = settings_store.get('openai_api_key')
        embedding_model = settings_store.get('embedding_model') or 'text-embedding-3-small'
        enable_reranking = settings_store.get('enable_reranking', True)  # Default to True

        # Feature #230: Read top_k from settings if not provided in arguments
        settings_top_k = int(settings_store.get('top_k', 10))
        top_k = arguments.get("top_k", settings_top_k)
        logger.info(f"[Feature #230] Using top_k: {top_k} (from {'arguments' if 'top_k' in arguments else 'settings'})")

        # Feature #186: Hybrid search settings
        search_mode = settings_store.get('search_mode', 'hybrid')  # 'vector_only', 'bm25_only', 'hybrid'
        hybrid_alpha = float(settings_store.get('hybrid_alpha', 0.5))  # Weight for vector vs BM25
        logger.info(f"[Feature #186] Search mode: {search_mode}, hybrid_alpha: {hybrid_alpha}")

        # Check if we have any embeddings
        total_chunks = embedding_store.get_chunk_count()
        if total_chunks == 0:
            return {
                "error": "No text documents with embeddings found. Please upload a text document (PDF, TXT, Word, or Markdown) first."
            }

        # Determine embedding source and dimension from stored chunks (check first chunk's metadata)
        all_chunks = embedding_store.get_all_chunks()
        embedding_source = None
        stored_dimension = None
        if all_chunks:
            chunk_metadata = all_chunks[0].get("metadata", {})
            embedding_source = chunk_metadata.get("embedding_source", "")
            stored_dimension = chunk_metadata.get("embedding_dimension", None)
            logger.info(f"Stored embeddings: source={embedding_source}, dimension={stored_dimension}")

        # Feature #211/#216: Preprocess query for better semantic search
        # Feature #216: Use LLM-based reformulation for better keyword extraction
        # Remove imperative verbs and filler words that don't contribute to semantic matching
        # Original query is preserved for BM25/reranking (which needs the full context)
        original_query = query
        query_for_embedding = self._reformulate_query_with_llm(query)

        # Generate embedding for the query using the same source as the stored embeddings
        query_embedding = None

        # If embeddings were made with Ollama, use Ollama for query embedding
        # Feature #211: Use preprocessed query for embedding generation
        if embedding_source and embedding_source.startswith("ollama:"):
            ollama_model = embedding_source.split(":", 1)[1]
            try:
                import httpx
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{OLLAMA_BASE_URL}/api/embeddings",
                        json={"model": ollama_model, "prompt": query_for_embedding}
                    )
                    if response.status_code == 200:
                        query_embedding = response.json().get("embedding", [])
                        logger.info(f"Generated query embedding using Ollama {ollama_model}")
            except Exception as e:
                logger.error(f"Error generating Ollama query embedding: {e}")
                return {"error": f"Failed to generate query embedding with Ollama: {str(e)}"}
        # Try OpenAI if we have a valid API key
        elif api_key and api_key.startswith('sk-') and len(api_key) > 20 and not api_key.startswith('sk-test'):
            try:
                client = OpenAI(api_key=api_key)
                response = client.embeddings.create(
                    model=embedding_model,
                    input=[query_for_embedding]
                )
                query_embedding = response.data[0].embedding
                logger.info(f"Generated query embedding using OpenAI {embedding_model}")
            except Exception as e:
                logger.error(f"Error generating OpenAI query embedding: {e}")
                return {"error": f"Failed to generate query embedding: {str(e)}"}
        else:
            # No valid OpenAI key, use the configured embedding model from settings
            # Feature #231: Use ONLY the configured model, no hardcoded fallback list
            try:
                import httpx
                # Parse embedding model from settings (e.g., 'ollama:snowflake-arctic-embed2:latest' -> 'snowflake-arctic-embed2:latest')
                if embedding_model.startswith('ollama:'):
                    ollama_model = embedding_model[7:]  # Remove 'ollama:' prefix
                else:
                    ollama_model = embedding_model  # Use as-is if no prefix

                logger.info(f"[Feature #231] Using configured embedding model: {ollama_model}")

                try:
                    with httpx.Client(timeout=30.0) as client:
                        response = client.post(
                            f"{OLLAMA_BASE_URL}/api/embeddings",
                            json={"model": ollama_model, "prompt": query_for_embedding}
                        )
                        if response.status_code == 200:
                            query_embedding = response.json().get("embedding", [])
                            if query_embedding:
                                logger.info(f"[Feature #231] Generated query embedding using configured Ollama model: {ollama_model}")
                        else:
                            logger.error(f"[Feature #231] Ollama embedding failed with status {response.status_code}: {response.text}")
                            return {"error": f"Failed to generate embedding with configured model '{ollama_model}'. Status: {response.status_code}. Please ensure the model is installed in Ollama."}
                except Exception as inner_e:
                    logger.error(f"[Feature #231] Error calling Ollama for embedding: {inner_e}")
                    return {"error": f"Failed to generate embedding with configured model '{ollama_model}': {str(inner_e)}. Please ensure Ollama is running and the model is installed."}
            except Exception as e:
                logger.error(f"[Feature #231] Error generating query embedding: {e}")
                return {"error": f"Failed to generate query embedding: {str(e)}"}

        if not query_embedding:
            return {"error": "Could not generate query embedding. Please configure an OpenAI API key or ensure Ollama is running with an embedding model."}

        # Validate embedding dimensions match
        query_dimension = len(query_embedding)
        logger.info(f"Query embedding dimension: {query_dimension}")

        if stored_dimension and query_dimension != stored_dimension:
            warning_msg = (
                f"Embedding dimension mismatch! Query embedding has {query_dimension} dimensions, "
                f"but stored document embeddings have {stored_dimension} dimensions. "
                f"This will cause incorrect search results. "
                f"Please use the same embedding model ({embedding_source}) for all documents and queries, "
                f"or re-embed all documents with the current model."
            )
            logger.error(warning_msg)
            return {
                "error": warning_msg,
                "query_dimension": query_dimension,
                "stored_dimension": stored_dimension,
                "stored_embedding_source": embedding_source
            }

        # Retrieve more chunks for reranking (20 instead of 5)
        # If reranking is enabled, we retrieve more chunks and let Cohere rerank them
        initial_top_k = 20 if enable_reranking else top_k

        # Feature #186: Import BM25 service for hybrid search
        from services.bm25_service import bm25_service, reciprocal_rank_fusion

        # ====================================================================
        # FEATURE #186: Hybrid Search Implementation
        # ====================================================================
        vector_results = []
        bm25_results = []

        # Run vector search if mode is vector_only or hybrid
        if search_mode in ['vector_only', 'hybrid']:
            vector_results = embedding_store.search_similar(
                query_embedding,
                top_k=initial_top_k,
                document_ids=document_ids
            )
            # Mark document chunks with type='document_chunk' for distinction
            for result in vector_results:
                result['type'] = 'document_chunk'
            logger.info(f"[Feature #186] Vector search found {len(vector_results)} results")

            # [Feature #277] Diagnostic logging with [RETRIEVER] prefix for easy filtering
            if vector_results:
                chunk_ids = [r.get("chunk_id", "N/A") for r in vector_results]
                logger.info(f"[RETRIEVER] === POST-RETRIEVAL RESULTS ({len(vector_results)} chunks) ===")
                logger.info(f"[RETRIEVER] Chunk IDs: {chunk_ids}")
                for rank, result in enumerate(vector_results, 1):
                    doc_id = result.get("document_id", "N/A")
                    chunk_id = result.get("chunk_id", "N/A")
                    metadata = result.get("metadata", {})
                    doc_title = metadata.get("document_title", result.get("document_title", "Unknown"))
                    text = result.get("text", "")
                    text_len = len(text) if text else 0
                    text_preview = text[:120].replace('\n', ' ') if text else "[EMPTY TEXT]"
                    similarity = result.get("similarity", 0)
                    # Log text length early to identify empty chunks
                    if text_len == 0:
                        logger.warning(f"[RETRIEVER] Rank {rank}: EMPTY CHUNK - chunk_id={chunk_id}, doc_id={doc_id}")
                    logger.info(
                        f"[RETRIEVER] Rank {rank}: chunk_id={chunk_id}, doc_id={doc_id}, "
                        f"title='{doc_title}', similarity={similarity:.4f}, "
                        f"text_len={text_len}, preview='{text_preview}...'"
                    )

        # Run BM25 search if mode is bm25_only or hybrid
        if search_mode in ['bm25_only', 'hybrid']:
            bm25_results = bm25_service.search(
                query,
                top_k=initial_top_k,
                document_ids=document_ids
            )
            logger.info(f"[Feature #186] BM25 search found {len(bm25_results)} results")

        # Combine results based on search mode
        if search_mode == 'hybrid' and vector_results and bm25_results:
            # Use Reciprocal Rank Fusion to combine results
            doc_results = reciprocal_rank_fusion(
                vector_results=vector_results,
                bm25_results=bm25_results,
                k=60,  # RRF constant
                alpha=hybrid_alpha  # Weight balance
            )
            logger.info(f"[Feature #186] RRF fused into {len(doc_results)} unique results")
        elif search_mode == 'bm25_only':
            doc_results = bm25_results
            # Convert BM25 score to similarity for consistent downstream processing
            for result in doc_results:
                if 'bm25_score' in result and 'similarity' not in result:
                    # Normalize BM25 score to 0-1 range (approximately)
                    result['similarity'] = min(1.0, result['bm25_score'] / 20.0)
        else:
            # vector_only or hybrid with only one source returning results
            doc_results = vector_results if vector_results else bm25_results
        # ====================================================================

        # Search user notes (Feature #147)
        # Notes are searched regardless of document_ids filter since they're separate from documents
        logger.info(f"[Feature #147] Starting user notes search with query embedding dim={len(query_embedding)}")
        note_results = self._search_user_notes(query_embedding, top_k=initial_top_k)
        logger.info(f"[Feature #147] Found {len(doc_results)} document chunks and {len(note_results)} user notes")

        # Search chat history (Feature #161)
        # Past conversations are searched to provide "as we discussed before" type context
        # We don't pass exclude_conversation_id here since we don't have the current conversation context
        chat_history_results = self._search_chat_history(query_embedding, top_k=initial_top_k)
        logger.info(f"[Feature #161] Found {len(chat_history_results)} relevant past conversations")

        # Merge document chunks, notes, and chat history, sort by similarity
        results = doc_results + note_results + chat_history_results
        results.sort(key=lambda x: x.get("similarity", 0), reverse=True)

        # Feature #214: Apply keyword boost for exact matches
        # Boost results that contain exact keywords from the query (product codes, numbers, etc.)
        results = self._apply_keyword_boost(results, original_query)

        # Feature #152: Apply feedback boost based on accumulated user feedback
        # This boosts/penalizes chunks based on feedback from similar queries
        results = self._apply_feedback_boost(results, query_embedding)

        # FEATURE #246: Apply section type boost/penalty
        # Boosts recipe chunks (1.2x) and penalizes index (0.5x) / intro (0.8x) chunks
        results = self._apply_section_type_boost(results)

        if not results:
            return {
                "query": query,
                "results": [],
                "message": "No relevant results found."
            }

        # Apply Cohere reranking if enabled
        # Fix #195: Use httpx directly instead of Cohere SDK to avoid Python 3.14 + Pydantic V1 issues
        reranked = False
        rerank_warning = None
        results_before_truncation = len(results)

        if enable_reranking:
            cohere_api_key = self._get_cohere_api_key()
            if cohere_api_key:
                try:
                    # Prepare documents for reranking
                    documents = [result.get("text", "") for result in results]

                    # Call Cohere rerank API via httpx (Fix #195)
                    rerank_results = self._cohere_rerank_httpx(
                        api_key=cohere_api_key,
                        query=query,
                        documents=documents,
                        model='rerank-english-v3.0',
                        top_n=top_k
                    )

                    # Reorder results based on Cohere's ranking
                    # [Feature #238] Track original text lengths for validation
                    original_text_lengths = {i: len(results[i].get("text", "") or "") for i in range(len(results))}

                    reranked_results = []
                    for rerank_result in rerank_results:
                        idx = rerank_result.get("index", 0)
                        relevance = rerank_result.get("relevance_score", 0.0)
                        original_result = results[idx]
                        # Store raw Cohere score for debugging
                        original_result['raw_cohere_score'] = relevance
                        original_result['similarity'] = relevance  # Will be normalized below
                        original_result['reranked'] = True
                        reranked_results.append(original_result)

                    # [Feature #315] Normalize Cohere scores to 0.4-1.0 range
                    # Cohere returns very low scores (0.001-0.1) which get filtered by relevance threshold
                    # Same normalization approach as RRF scores in bm25_service.py (lines 471-491)
                    if reranked_results:
                        raw_scores = [r.get('raw_cohere_score', 0) for r in reranked_results]
                        max_cohere = max(raw_scores)
                        min_cohere = min(raw_scores)
                        cohere_range = max_cohere - min_cohere

                        for result in reranked_results:
                            raw_score = result.get('raw_cohere_score', 0)
                            if cohere_range > 0:
                                # Min-max normalization to 0-1 range, then scale to 0.4-1.0
                                normalized = (raw_score - min_cohere) / cohere_range
                                result['similarity'] = 0.4 + (normalized * 0.6)
                            elif max_cohere > 0:
                                # All same score, give reasonable similarity (0.7)
                                result['similarity'] = 0.7
                            else:
                                result['similarity'] = 0.0

                        logger.info(f"[Feature #315] Normalized Cohere scores from {min_cohere:.4f}-{max_cohere:.4f} to 0.40-1.00 range")

                    # [Feature #238] Validate that reranker preserved chunk text, IDs, and metadata
                    text_loss_detected = False
                    for i, result in enumerate(reranked_results):
                        # Get the original index this result came from
                        orig_idx = rerank_results[i].get("index", 0) if i < len(rerank_results) else -1
                        orig_text_len = original_text_lengths.get(orig_idx, 0)
                        current_text_len = len(result.get("text", "") or "")

                        # Check if text was lost (original had text but reranked doesn't)
                        if orig_text_len > 0 and current_text_len == 0:
                            logger.error(
                                f"[Feature #238] TEXT LOST IN RERANKING: "
                                f"chunk_id={result.get('chunk_id', 'N/A')}, "
                                f"document_id={result.get('document_id', 'N/A')}, "
                                f"original_text_len={orig_text_len}, current_text_len={current_text_len}"
                            )
                            text_loss_detected = True

                        # Validate essential fields are present
                        if not result.get("chunk_id"):
                            logger.error(f"[Feature #238] MISSING chunk_id in reranked result at position {i}")
                        if not result.get("document_id"):
                            logger.error(f"[Feature #238] MISSING document_id in reranked result at position {i}")
                        if result.get("metadata") is None:
                            logger.warning(f"[Feature #238] MISSING metadata in reranked result at position {i}")

                    if not text_loss_detected:
                        logger.info(f"[Feature #238] Reranker validation PASSED: all {len(reranked_results)} results preserved text and IDs")

                    results = reranked_results
                    reranked = True
                    logger.info(f"Successfully reranked {len(results)} results using Cohere via httpx (from {results_before_truncation} initial results)")

                    # [Feature #277] Diagnostic logging with [RERANKER] prefix for easy filtering
                    chunk_ids = [r.get("chunk_id", "N/A") for r in results]
                    logger.info(f"[RERANKER] === POST-RERANK RESULTS ({len(results)} chunks) ===")
                    logger.info(f"[RERANKER] Reranked chunk IDs: {chunk_ids}")
                    for rank, result in enumerate(results, 1):
                        doc_id = result.get("document_id", "N/A")
                        chunk_id = result.get("chunk_id", "N/A")
                        metadata = result.get("metadata", {})
                        doc_title = metadata.get("document_title", result.get("document_title", "Unknown"))
                        text = result.get("text", "")
                        text_len = len(text) if text else 0
                        text_preview = text[:120].replace('\n', ' ') if text else "[EMPTY TEXT]"
                        normalized_score = result.get("similarity", 0)  # After reranking, similarity holds normalized score
                        raw_cohere_score = result.get("raw_cohere_score", 0)  # [Feature #315] Original Cohere score
                        logger.info(
                            f"[RERANKER] Rank {rank}: chunk_id={chunk_id}, doc_id={doc_id}, "
                            f"title='{doc_title}', normalized_score={normalized_score:.4f}, "
                            f"raw_cohere_score={raw_cohere_score:.4f}, "
                            f"text_len={text_len}, preview='{text_preview}...'"
                        )

                except Exception as e:
                    logger.warning(f"Cohere reranking failed: {e}. Falling back to vector search results.")
                    logger.warning(f"Truncating results from {results_before_truncation} to {top_k} due to reranking failure")
                    # Fallback: use original vector search results
                    results = results[:top_k]
                    rerank_warning = f"Reranking failed: {str(e)}. Showing top {top_k} of {results_before_truncation} results based on vector similarity."
            else:
                # No Cohere API key available, use original results
                logger.info(f"Cohere API key not configured. Truncating results from {results_before_truncation} to {top_k}")
                results = results[:top_k]
                if enable_reranking:  # User wanted reranking but no API key
                    rerank_warning = f"Reranking is enabled but Cohere API key not configured. Showing top {top_k} of {results_before_truncation} results based on vector similarity."
        else:
            # Reranking disabled, use original results
            logger.info(f"Reranking disabled. Using top {top_k} of {results_before_truncation} results")
            results = results[:top_k]

        # FEATURE #182/194: Apply relevance threshold filtering to discard low-quality chunks
        # This prevents irrelevant documents from being cited
        # Feature #194: Read configurable thresholds from settings
        # Feature #229: Allow override via arguments for listing queries
        strict_rag_mode = settings_store.get('strict_rag_mode', False)
        if "similarity_threshold" in arguments:
            # Feature #229: Use provided threshold (e.g., lower for listing queries)
            min_relevance_threshold = float(arguments["similarity_threshold"])
            logger.info(f"[Feature #229] Using custom similarity_threshold from arguments: {min_relevance_threshold}")
        elif strict_rag_mode:
            min_relevance_threshold = float(settings_store.get('strict_relevance_threshold', 0.6))
        else:
            min_relevance_threshold = float(settings_store.get('min_relevance_threshold', 0.4))

        pre_filter_count = len(results)
        filtered_results = [r for r in results if r.get("similarity", 0) >= min_relevance_threshold]
        discarded_count = pre_filter_count - len(filtered_results)

        if discarded_count > 0:
            logger.info(f"[Feature #182] Discarded {discarded_count}/{pre_filter_count} chunks with relevance < {min_relevance_threshold} (strict_mode={strict_rag_mode})")

        # If all results were filtered out, return empty with graceful degradation suggestions
        # [Feature #318] Instead of just saying "not found", provide alternative suggestions
        if not filtered_results and results:
            logger.info(f"[Feature #182] All {pre_filter_count} results filtered out due to low relevance")
            logger.info(f"[Feature #318] Generating graceful degradation suggestions for query: {query}")

            # Generate suggestions from discarded results
            suggestions = self._generate_graceful_degradation_suggestions(
                query=query,
                discarded_results=results,  # Pass original results (the discarded ones)
                user_lang=self._detect_language(query)
            )

            # Format the graceful degradation response
            user_lang = self._detect_language(query)
            graceful_message = self._format_graceful_degradation_response(
                query=query,
                suggestions=suggestions,
                user_lang=user_lang,
                relevance_threshold=min_relevance_threshold
            )

            return {
                "query": query,
                "results": [],
                "message": graceful_message,
                "relevance_threshold": min_relevance_threshold,
                "discarded_chunks": pre_filter_count,
                "strict_mode": strict_rag_mode,
                "graceful_degradation": suggestions  # Include structured suggestions for frontend
            }

        results = filtered_results

        # Format results with source attribution
        formatted_results = []
        for result in results:
            result_type = result.get("type", "document_chunk")

            # Handle user notes (Feature #147)
            if result_type == "user_note":
                # User note: use pre-formatted title and include note metadata
                formatted_results.append({
                    "chunk_id": result.get("chunk_id"),
                    "text": result.get("text", ""),
                    "document_id": result.get("document_id"),  # May be None
                    "document_title": result.get("document_title", "User Note"),
                    "similarity": round(result.get("similarity", 0), 4),
                    "raw_similarity": round(result.get("raw_similarity", 0), 4),
                    "boost_factor": result.get("boost_factor", 1.0),
                    "type": "user_note",
                    "note_id": result.get("note_id"),
                    "tags": result.get("tags", []),
                    "reranked": result.get("reranked", False)
                })
            # Handle conversation context (Feature #161)
            elif result_type == "conversation_context":
                # Past Q&A pair from conversation history
                formatted_results.append({
                    "chunk_id": result.get("message_id"),  # Use message_id as chunk_id
                    "text": result.get("text", ""),
                    "document_id": None,
                    "document_title": result.get("source", "Previous Conversation"),
                    "similarity": round(result.get("similarity", 0), 4),
                    "type": "conversation_context",
                    "conversation_id": result.get("conversation_id"),
                    "message_id": result.get("message_id"),
                    "reranked": result.get("reranked", False)
                })
            else:
                # Document chunk: original logic
                doc_id = result.get("document_id")
                metadata = result.get("metadata", {})

                # Query document store first for current title
                doc = document_store.get(doc_id)
                if doc:
                    # Use current title from document store (handles renames)
                    doc_title = doc.title
                else:
                    # Fall back to metadata title if document was deleted
                    doc_title = metadata.get("document_title", "Unknown Document")
                    logger.warning(f"Document {doc_id} not found in store, using metadata title: {doc_title}")

                # FEATURE #133: Include context overlap metadata in search results
                # This helps the LLM know when text includes context from a previous chunk
                context_prefix = metadata.get("context_prefix")
                has_context = metadata.get("has_context", False)

                formatted_results.append({
                    "chunk_id": result.get("chunk_id", f"{doc_id}_{result.get('chunk_index', 0)}"),  # Include chunk_id for feedback
                    "text": result.get("text", ""),
                    "document_id": doc_id,
                    "document_title": doc_title,
                    "similarity": round(result.get("similarity", 0), 4),
                    "type": "document_chunk",
                    "chunk_index": metadata.get("chunk_index", 0),
                    "total_chunks": metadata.get("total_chunks", 1),
                    "reranked": result.get("reranked", False),
                    # FEATURE #133: Context overlap fields
                    "has_context": has_context,
                    "context_prefix": context_prefix  # None if no previous context
                })

        response = {
            "query": query,
            "results": formatted_results,
            "total_results": len(formatted_results),
            "reranked": reranked,
            "results_before_reranking": results_before_truncation
        }

        # Include warning if reranking failed
        if rerank_warning:
            response["warning"] = rerank_warning

        return response

    def _search_user_notes(
        self,
        query_embedding: List[float],
        top_k: int = 5
    ) -> List[Dict]:
        """
        Search user notes by vector similarity with boost factor applied.

        Args:
            query_embedding: The query vector embedding
            top_k: Maximum number of notes to return

        Returns:
            List of note results with boosted similarity scores and type='user_note' flag
        """
        try:
            from sqlalchemy import text as sa_text

            with SessionLocal() as session:
                query_dim = len(query_embedding)
                logger.info(f"[Feature #147] Searching user notes with query dim={query_dim}")

                # Use SQLAlchemy ORM with pgvector cosine_distance method
                # This is the same approach used in embedding_store.py
                query = session.query(
                    UserNote,
                    (1 - UserNote.embedding.cosine_distance(query_embedding)).label('similarity')
                ).filter(
                    UserNote.embedding.isnot(None)
                ).order_by(
                    sa_text('similarity DESC')
                ).limit(top_k * 2)  # Get extra for filtering

                raw_results = query.all()
                logger.info(f"[Feature #147] Found {len(raw_results)} notes with embeddings")

                if not raw_results:
                    return []

                results = []
                skipped_count = 0

                for note, raw_similarity in raw_results:
                    # Get embedding dimension for validation
                    note_embedding = list(note.embedding) if note.embedding is not None else []

                    # Validate embedding dimension
                    if len(note_embedding) != query_dim:
                        skipped_count += 1
                        logger.warning(
                            f"[Feature #147] Skipping note {note.id}: dimension mismatch "
                            f"(expected {query_dim}, got {len(note_embedding)})"
                        )
                        continue

                    # Apply boost factor to similarity score
                    boosted_similarity = float(raw_similarity) * note.boost_factor
                    # Cap at 1.0 to avoid inflated scores
                    boosted_similarity = min(boosted_similarity, 1.0)

                    # Build display title for the note
                    if note.tags:
                        note_title = f"User Note ({', '.join(note.tags[:3])})"
                    else:
                        note_title = "User Note"

                    results.append({
                        "chunk_id": f"note_{note.id}",
                        "text": note.content,
                        "document_id": note.document_id,  # May be None
                        "document_title": note_title,
                        "similarity": boosted_similarity,
                        "raw_similarity": float(raw_similarity),
                        "boost_factor": note.boost_factor,
                        "type": "user_note",
                        "note_id": note.id,
                        "tags": note.tags or [],
                        "metadata": {
                            "note_id": note.id,
                            "tags": note.tags or [],
                            "boost_factor": note.boost_factor,
                            "created_at": note.created_at.isoformat() if note.created_at else None
                        }
                    })

                if skipped_count > 0:
                    logger.info(f"[Feature #147] Skipped {skipped_count} notes with dimension mismatch")

                # Sort by boosted similarity and return top_k
                results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
                logger.info(f"[Feature #147] Returning {min(top_k, len(results))} user notes")
                return results[:top_k]

        except Exception as e:
            logger.error(f"[Feature #147] Error searching user notes: {e}")
            return []

    def embed_user_message(
        self,
        message_id: str,
        conversation_id: str,
        content: str
    ) -> bool:
        """
        Generate and store embedding for a user message (Feature #161).

        This enables chat history search - user questions are embedded
        so they can be retrieved as relevant context for similar future queries.

        Args:
            message_id: The ID of the message being embedded
            conversation_id: The conversation this message belongs to
            content: The message text to embed

        Returns:
            True if embedding was created successfully, False otherwise
        """
        # Check if chat history search is enabled
        include_history = settings_store.get('include_chat_history_in_search', False)
        if not include_history:
            logger.debug(f"[Feature #161] Chat history search disabled, skipping embedding for message {message_id}")
            return False

        if not content or len(content.strip()) < 5:
            logger.debug(f"[Feature #161] Message too short to embed: {message_id}")
            return False

        try:
            # Get embedding configuration
            api_key = settings_store.get('openai_api_key')
            embedding_model = settings_store.get('embedding_model') or 'text-embedding-3-small'

            embedding = None
            embedding_source = None

            # Try OpenAI first
            if api_key and api_key.startswith('sk-') and len(api_key) > 20:
                try:
                    client = OpenAI(api_key=api_key)
                    response = client.embeddings.create(
                        model=embedding_model,
                        input=[content]
                    )
                    embedding = response.data[0].embedding
                    embedding_source = f"openai:{embedding_model}"
                    logger.info(f"[Feature #161] Generated embedding for message {message_id} using OpenAI ({len(embedding)} dims)")
                except Exception as e:
                    logger.warning(f"[Feature #161] OpenAI embedding failed for message {message_id}: {e}")

            # Fallback to Ollama using configured embedding model
            # Feature #231: Use ONLY the configured model, no hardcoded fallback list
            if embedding is None:
                try:
                    import httpx
                    # Parse embedding model from settings (e.g., 'ollama:snowflake-arctic-embed2:latest' -> 'snowflake-arctic-embed2:latest')
                    if embedding_model.startswith('ollama:'):
                        ollama_model = embedding_model[7:]  # Remove 'ollama:' prefix
                    else:
                        ollama_model = embedding_model  # Use as-is if no prefix

                    logger.info(f"[Feature #231] Using configured embedding model for message embedding: {ollama_model}")

                    try:
                        with httpx.Client(timeout=30.0) as client:
                            response = client.post(
                                f"{OLLAMA_BASE_URL}/api/embeddings",
                                json={"model": ollama_model, "prompt": content}
                            )
                            if response.status_code == 200:
                                embedding = response.json().get("embedding", [])
                                if embedding:
                                    embedding_source = f"ollama:{ollama_model}"
                                    logger.info(f"[Feature #161] Generated embedding for message {message_id} using Ollama ({len(embedding)} dims)")
                            else:
                                logger.warning(f"[Feature #231] Ollama embedding failed with status {response.status_code}")
                    except Exception as inner_e:
                        logger.warning(f"[Feature #231] Error calling Ollama for message embedding: {inner_e}")
                except Exception as e:
                    logger.warning(f"[Feature #161] Ollama embedding failed for message {message_id}: {e}")

            if embedding is None:
                logger.warning(f"[Feature #161] Could not generate embedding for message {message_id} - no embedding model available")
                return False

            # Store the embedding
            # [Feature #242] Fix FK constraint error by verifying message exists before inserting
            # The message may not be committed yet (only flushed in the main async transaction)
            # We retry a few times with a short delay to wait for the commit
            import time
            from models.db_models import DBMessage

            max_retries = 5
            retry_delay = 0.2  # 200ms between retries

            with SessionLocal() as session:
                # Check if embedding already exists
                existing = session.query(MessageEmbedding).filter(
                    MessageEmbedding.message_id == message_id
                ).first()

                if existing:
                    logger.info(f"[Feature #161] Embedding already exists for message {message_id}")
                    return True

                # [Feature #242] Wait for the message to be committed before inserting embedding
                # This handles the case where the message is flushed but not yet committed
                message_exists = False
                for attempt in range(max_retries):
                    msg_check = session.query(DBMessage).filter(
                        DBMessage.id == message_id
                    ).first()
                    if msg_check:
                        message_exists = True
                        logger.debug(f"[Feature #242] Message {message_id} found on attempt {attempt + 1}")
                        break

                    if attempt < max_retries - 1:
                        logger.debug(f"[Feature #242] Message {message_id} not yet committed, waiting... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        # Expire session cache to see new data
                        session.expire_all()

                if not message_exists:
                    logger.warning(f"[Feature #242] Message {message_id} not found after {max_retries} attempts, skipping embedding")
                    return False

                # Create new embedding record
                try:
                    msg_embedding = MessageEmbedding(
                        message_id=message_id,
                        conversation_id=conversation_id,
                        embedding=embedding,
                        embedding_source=embedding_source,
                        embedding_dimension=str(len(embedding))
                    )
                    session.add(msg_embedding)
                    session.commit()
                    logger.info(f"[Feature #161] Stored embedding for message {message_id}")
                    return True
                except Exception as insert_error:
                    # [Feature #242] Handle FK constraint errors gracefully
                    session.rollback()
                    error_str = str(insert_error).lower()
                    if 'foreign key' in error_str or 'violates foreign key constraint' in error_str:
                        logger.warning(f"[Feature #242] FK constraint error for message {message_id} - message may have been deleted: {insert_error}")
                    else:
                        logger.error(f"[Feature #242] Failed to insert embedding for message {message_id}: {insert_error}")
                    return False

        except Exception as e:
            logger.error(f"[Feature #161] Error embedding message {message_id}: {e}")
            return False

    def _search_chat_history(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        exclude_conversation_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search past conversation Q&A pairs by vector similarity (Feature #161).

        Finds relevant past user questions and their assistant responses to provide
        "as we discussed before..." type context.

        Args:
            query_embedding: The query vector to search against
            top_k: Maximum number of results to return
            exclude_conversation_id: Conversation to exclude (typically current conversation)

        Returns:
            List of results containing past Q&A pairs with similarity scores
        """
        # Check if chat history search is enabled
        include_history = settings_store.get('include_chat_history_in_search', False)
        if not include_history:
            logger.debug(f"[Feature #161] Chat history search disabled")
            return []

        try:
            from sqlalchemy import text as sa_text
            from models.db_models import DBMessage

            query_dim = len(query_embedding)
            logger.info(f"[Feature #161] Searching chat history with query dim={query_dim}")

            with SessionLocal() as session:
                # Check if any message embeddings exist
                total_embeddings = session.query(MessageEmbedding).count()
                if total_embeddings == 0:
                    logger.info(f"[Feature #161] No message embeddings found")
                    return []

                # Get a sample embedding to check dimensions
                sample = session.query(MessageEmbedding).first()
                if sample and sample.embedding_dimension:
                    stored_dim = int(sample.embedding_dimension)
                    if stored_dim != query_dim:
                        logger.warning(f"[Feature #161] Dimension mismatch: query={query_dim}, stored={stored_dim}")
                        return []

                # Search using pgvector cosine distance
                # Lower distance = more similar (0 = identical)
                # We want to find message embeddings similar to the query
                # Exclude the current conversation to avoid retrieving the same context

                # Format embedding as PostgreSQL array string
                # We interpolate this directly into SQL since we generate it ourselves (safe)
                embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

                if exclude_conversation_id:
                    sql = sa_text(f"""
                        SELECT
                            me.id,
                            me.message_id,
                            me.conversation_id,
                            me.embedding_source,
                            1 - (me.embedding <=> '{embedding_str}'::vector) as similarity
                        FROM message_embeddings me
                        WHERE me.conversation_id != :exclude_conv
                        ORDER BY me.embedding <=> '{embedding_str}'::vector
                        LIMIT :limit
                    """)
                    results = session.execute(
                        sql,
                        {
                            "exclude_conv": exclude_conversation_id,
                            "limit": top_k * 2  # Get more to filter
                        }
                    ).fetchall()
                else:
                    sql = sa_text(f"""
                        SELECT
                            me.id,
                            me.message_id,
                            me.conversation_id,
                            me.embedding_source,
                            1 - (me.embedding <=> '{embedding_str}'::vector) as similarity
                        FROM message_embeddings me
                        ORDER BY me.embedding <=> '{embedding_str}'::vector
                        LIMIT :limit
                    """)
                    results = session.execute(
                        sql,
                        {
                            "limit": top_k * 2
                        }
                    ).fetchall()

                # For each matching user message, get the conversation context
                chat_context_results = []
                for row in results:
                    message_id = row[1]
                    conv_id = row[2]
                    similarity = float(row[4]) if row[4] else 0.0

                    # Filter by minimum similarity
                    if similarity < 0.5:  # Lower threshold for chat history
                        continue

                    # Get the user message and the following assistant response
                    user_msg = session.query(DBMessage).filter(
                        DBMessage.id == message_id
                    ).first()

                    if not user_msg:
                        continue

                    # Get the next assistant message in the same conversation
                    assistant_msg = session.query(DBMessage).filter(
                        DBMessage.conversation_id == conv_id,
                        DBMessage.role == "assistant",
                        DBMessage.created_at > user_msg.created_at
                    ).order_by(DBMessage.created_at.asc()).first()

                    # Format the Q&A pair as context
                    context_text = f"User asked: {user_msg.content}"
                    if assistant_msg:
                        # Truncate long responses
                        response = assistant_msg.content[:500] + "..." if len(assistant_msg.content) > 500 else assistant_msg.content
                        context_text += f"\n\nAssistant answered: {response}"

                    # Apply boost factor (lower than documents, higher than user notes)
                    boost_factor = 0.8  # Chat history gets 80% weight compared to documents
                    boosted_similarity = similarity * boost_factor

                    chat_context_results.append({
                        "text": context_text,
                        "similarity": boosted_similarity,
                        "source": "Previous Conversation",
                        "type": "conversation_context",
                        "conversation_id": conv_id,
                        "message_id": message_id
                    })

                chat_context_results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
                logger.info(f"[Feature #161] Found {len(chat_context_results)} relevant past conversations")
                return chat_context_results[:top_k]

        except Exception as e:
            logger.error(f"[Feature #161] Error searching chat history: {e}")
            return []

    def _get_feedback_scores(
        self,
        query_embedding: List[float],
        chunk_ids: List[str],
        similarity_threshold: float = 0.85
    ) -> Dict[str, float]:
        """
        Get accumulated feedback scores for chunks based on similar queries.

        Feature #152: Apply feedback boost in retrieval ranking

        Args:
            query_embedding: The current query vector embedding
            chunk_ids: List of chunk IDs to get feedback for
            similarity_threshold: Minimum cosine similarity for query matching (default 0.85)

        Returns:
            Dict mapping chunk_id -> feedback_score (sum of feedback values from similar queries)
        """
        if not chunk_ids:
            return {}

        try:
            from sqlalchemy import text as sa_text, func

            with SessionLocal() as session:
                # Query chunk_feedback table for similar queries
                # Cosine similarity = 1 - cosine_distance
                # We want similarity > threshold, so cosine_distance < (1 - threshold)
                distance_threshold = 1.0 - similarity_threshold

                # Get feedback records where:
                # 1. chunk_id is in our list of retrieved chunks
                # 2. query_embedding is similar to the current query (cosine similarity > 0.85)
                query = session.query(
                    ChunkFeedback.chunk_id,
                    func.sum(ChunkFeedback.feedback).label('feedback_score'),
                    func.count(ChunkFeedback.id).label('feedback_count')
                ).filter(
                    ChunkFeedback.chunk_id.in_(chunk_ids),
                    ChunkFeedback.query_embedding.cosine_distance(query_embedding) < distance_threshold
                ).group_by(
                    ChunkFeedback.chunk_id
                )

                results = query.all()

                feedback_scores = {}
                for chunk_id, feedback_score, feedback_count in results:
                    feedback_scores[chunk_id] = float(feedback_score) if feedback_score else 0.0
                    logger.info(
                        f"[Feature #152] Chunk {chunk_id}: feedback_score={feedback_score} "
                        f"from {feedback_count} similar queries"
                    )

                if feedback_scores:
                    logger.info(
                        f"[Feature #152] Found feedback for {len(feedback_scores)} chunks "
                        f"from similar queries (threshold={similarity_threshold})"
                    )
                else:
                    logger.info(f"[Feature #152] No feedback found for similar queries")

                return feedback_scores

        except Exception as e:
            logger.error(f"[Feature #152] Error getting feedback scores: {e}")
            return {}

    def _extract_search_entities(self, query: str) -> Dict[str, List[str]]:
        """
        Feature #218: Extract key entities from user queries for hybrid search.

        Extracts:
        - Product codes: Alphanumeric codes with special chars (NAVIGAT/100, ABC-123)
        - Numbers: Model numbers, prices, quantities (100, 14,000.00)
        - Proper nouns: Capitalized words that are likely product/brand names
        - Technical terms: Domain-specific terminology

        This enables matching "Navigat 100" with "NAVIGAT/100/0/10/4" in documents.

        Args:
            query: The user's search query

        Returns:
            Dict with entity types as keys and lists of extracted entities
        """
        entities = {
            'product_codes': [],
            'numbers': [],
            'proper_nouns': [],
            'technical_terms': [],
            'keywords': []
        }

        if not query or not query.strip():
            return entities

        # 1. Extract product codes (alphanumeric with slashes, dashes, underscores)
        # Pattern matches: NAVIGAT/100, ABC-123, VFR-X1M06SA, etc.
        product_code_pattern = r'[A-Z][A-Z0-9]*(?:[/\-_][A-Z0-9]+)+'
        codes = re.findall(product_code_pattern, query, re.IGNORECASE)
        for code in codes:
            entities['product_codes'].append(code.upper())
            # Also extract component parts for flexible matching
            parts = re.split(r'[/\-_]', code)
            for part in parts:
                if len(part) >= 2:
                    entities['keywords'].append(part.upper())

        # 2. Extract product names followed by numbers (e.g., "Navigat 100")
        # This is key for Feature #218 - matching "Navigat 100" with "NAVIGAT/100"
        product_name_number = re.findall(r'([A-Z][a-z]+)\s+(\d+)', query)
        for name, num in product_name_number:
            # Add both the name and the combined form
            entities['proper_nouns'].append(name.upper())
            entities['numbers'].append(num)
            # Also add the combined form that might appear in codes
            entities['keywords'].append(f"{name.upper()}/{num}")
            entities['keywords'].append(f"{name.upper()}-{num}")
            entities['keywords'].append(f"{name.upper()}{num}")

        # 3. Extract standalone numbers (prices, model numbers, quantities)
        # Handles: 100, 14,000.00, 1.5, etc.
        number_pattern = r'\b\d+(?:[,\.]\d+)*\b'
        numbers = re.findall(number_pattern, query)
        for num in numbers:
            entities['numbers'].append(num)
            # Also add cleaned version (no commas) for matching
            clean_num = num.replace(',', '')
            if clean_num != num:
                entities['numbers'].append(clean_num)

        # 4. Extract proper nouns (capitalized words, likely product/brand names)
        # Skip common sentence starters and question words
        skip_words = {
            'what', 'where', 'when', 'how', 'who', 'why', 'which', 'the', 'a', 'an',
            'is', 'are', 'was', 'were', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
            'my', 'your', 'his', 'her', 'its', 'our', 'their', 'this', 'that',
            'qual', 'quale', 'dove', 'quando', 'come', 'perché', 'cosa', 'chi',
            'dammi', 'dimmi', 'trovami', 'mostrami', 'fammi', 'elenca', 'cerca'
        }
        # Find capitalized words that aren't at the start of a sentence
        words = query.split()
        for i, word in enumerate(words):
            # Skip first word (sentence start) and common words
            clean_word = re.sub(r'[^\w]', '', word)
            if clean_word and clean_word[0].isupper() and clean_word.lower() not in skip_words:
                # Check if it's a proper noun (not all caps acronym)
                if not clean_word.isupper() or len(clean_word) <= 2:
                    entities['proper_nouns'].append(clean_word.upper())

        # 5. Extract technical terms (uppercase acronyms like GMDSS, API, etc.)
        acronyms = re.findall(r'\b[A-Z]{2,}\b', query)
        for acronym in acronyms:
            if acronym not in entities['product_codes']:
                entities['technical_terms'].append(acronym)

        # 6. Extract significant words (3+ chars, not stop words)
        stop_words = {
            'the', 'and', 'for', 'with', 'from', 'that', 'this', 'what', 'which',
            'where', 'when', 'how', 'who', 'why', 'can', 'could', 'would', 'should',
            'have', 'has', 'had', 'been', 'being', 'was', 'were', 'are', 'not',
            'but', 'all', 'each', 'every', 'some', 'any', 'most', 'other', 'into',
            'del', 'della', 'dei', 'delle', 'nel', 'nella', 'con', 'per', 'una',
            'uno', 'gli', 'che', 'cosa', 'come', 'qual', 'quale', 'quali', 'dove',
            'quando', 'quanto', 'quanti', 'quanta', 'quante', 'chi', 'perché',
            'dammi', 'dimmi', 'trovami', 'mostrami', 'fammi', 'elenca', 'cerca',
            'give', 'show', 'tell', 'find', 'list', 'search', 'get', 'explain',
            'price', 'cost', 'prezzo', 'costo', 'quanto', 'much', 'many'
        }
        all_words = re.findall(r'\b[A-Za-z0-9]{3,}\b', query)
        for word in all_words:
            if word.lower() not in stop_words:
                entities['keywords'].append(word.upper())

        # Deduplicate all lists
        for key in entities:
            entities[key] = list(set(entities[key]))

        logger.info(f"[Feature #218] Extracted entities from query: {entities}")
        return entities

    def _apply_keyword_boost(
        self,
        results: List[Dict],
        query: str,
        boost_amount: float = None
    ) -> List[Dict]:
        """
        Feature #214/#218: Apply keyword boost to results containing extracted entities.

        Enhanced with Feature #218's entity extraction for better matching:
        - "Navigat 100" matches "NAVIGAT/100/0/10/4" (product code variations)
        - Numbers match even with different formatting (14000 vs 14,000.00)
        - Proper nouns get priority boosting

        Args:
            results: List of retrieval results with 'text' and 'similarity' fields
            query: The original user query
            boost_amount: Amount to add to similarity score (from settings or default 0.15)

        Returns:
            Results list with adjusted similarity scores, re-sorted by boosted score
        """
        if not results or not query:
            return results

        # Feature #218: Check if entity extraction is enabled
        enable_entity_extraction = settings_store.get('enable_entity_extraction', 'true').lower() == 'true'
        if not enable_entity_extraction:
            logger.info("[Feature #218] Entity extraction disabled, using basic keyword boost")

        # Feature #218: Get configurable boost weight from settings
        if boost_amount is None:
            boost_amount = float(settings_store.get('keyword_boost_weight', 0.15))

        # Extract entities using Feature #218's entity extraction
        entities = self._extract_search_entities(query)

        # Combine all extracted entities into a matching set
        all_entities = set()
        for entity_type, entity_list in entities.items():
            for entity in entity_list:
                all_entities.add(entity.lower())

        if not all_entities:
            logger.info("[Feature #218] No entities extracted from query")
            return results

        logger.info(f"[Feature #218] Using {len(all_entities)} entities for keyword boost")

        # Apply boost to results containing extracted entities
        boosted_count = 0
        for result in results:
            text = result.get("text", "").upper()  # Normalize for case-insensitive matching
            matched_entities = []
            match_types = set()

            # Check each entity type with appropriate matching
            for entity_type, entity_list in entities.items():
                for entity in entity_list:
                    entity_upper = entity.upper()

                    # Different matching strategies based on entity type
                    if entity_type == 'product_codes':
                        # Product codes: Check if the code or any part appears
                        if entity_upper in text:
                            matched_entities.append(entity)
                            match_types.add('product_code')
                        # Also check component parts
                        parts = re.split(r'[/\-_]', entity)
                        for part in parts:
                            if len(part) >= 2 and re.search(rf'\b{re.escape(part)}\b', text, re.IGNORECASE):
                                matched_entities.append(part)
                                match_types.add('product_code_part')

                    elif entity_type == 'numbers':
                        # Numbers: Flexible matching (100 matches "100", "100.00", "100,00")
                        # Remove formatting chars for comparison
                        clean_entity = entity.replace(',', '').replace('.', '')
                        # Look for the number with word boundaries
                        if re.search(rf'\b{re.escape(entity)}\b', text):
                            matched_entities.append(entity)
                            match_types.add('number')
                        elif re.search(rf'\b{clean_entity}\b', text):
                            matched_entities.append(entity)
                            match_types.add('number')

                    elif entity_type == 'proper_nouns':
                        # Proper nouns: Word boundary matching
                        if re.search(rf'\b{re.escape(entity_upper)}\b', text):
                            matched_entities.append(entity)
                            match_types.add('proper_noun')

                    elif entity_type == 'technical_terms':
                        # Technical terms: Exact match
                        if re.search(rf'\b{re.escape(entity_upper)}\b', text):
                            matched_entities.append(entity)
                            match_types.add('technical_term')

                    elif entity_type == 'keywords':
                        # Keywords: Word boundary matching
                        if re.search(rf'\b{re.escape(entity_upper)}\b', text):
                            matched_entities.append(entity)
                            match_types.add('keyword')

            if matched_entities:
                original_score = result.get("similarity", 0.0)

                # Calculate boost based on match quality
                # Product codes and proper nouns get higher boost
                base_boost = boost_amount
                if 'product_code' in match_types:
                    base_boost *= 1.5  # 50% extra for product codes
                if 'proper_noun' in match_types:
                    base_boost *= 1.25  # 25% extra for proper nouns

                # Boost proportional to number of matched entities (max 3x boost)
                num_unique_matches = len(set(matched_entities))
                boost = min(base_boost * num_unique_matches, boost_amount * 3)
                boosted_score = min(1.0, original_score + boost)  # Cap at 1.0

                result["similarity"] = boosted_score
                result["keyword_boost"] = True
                result["matched_entities"] = list(set(matched_entities))
                result["match_types"] = list(match_types)
                boosted_count += 1

                logger.debug(f"[Feature #218] Boosted chunk {result.get('chunk_id', '?')}: "
                           f"{original_score:.3f} → {boosted_score:.3f} (matched: {set(matched_entities)}, types: {match_types})")

        if boosted_count > 0:
            logger.info(f"[Feature #218] Applied entity-based boost to {boosted_count}/{len(results)} results")
            # Re-sort by boosted similarity
            results.sort(key=lambda x: x.get("similarity", 0), reverse=True)

        return results

    def _apply_feedback_boost(
        self,
        results: List[Dict],
        query_embedding: List[float],
        boost_factor: float = 0.1
    ) -> List[Dict]:
        """
        Apply feedback-based score boost to retrieval results.

        Feature #152: Apply feedback boost in retrieval ranking

        The boost formula is: final_score = similarity_score * (1 + boost_factor * feedback_score)
        Scores are clamped to [0.0, 1.0] range.

        Args:
            results: List of retrieval results with 'similarity' and 'chunk_id' fields
            query_embedding: The current query vector embedding
            boost_factor: Multiplier for feedback_score (default 0.1)

        Returns:
            Results list with adjusted similarity scores, re-sorted by boosted score
        """
        if not results:
            return results

        # Get chunk IDs from results (filter out user notes which don't have feedback)
        chunk_ids = [
            r.get("chunk_id")
            for r in results
            if r.get("chunk_id") and not r.get("chunk_id", "").startswith("note_")
        ]

        if not chunk_ids:
            logger.info("[Feature #152] No document chunks to boost (only user notes)")
            return results

        # Get feedback scores for these chunks
        feedback_scores = self._get_feedback_scores(query_embedding, chunk_ids)

        if not feedback_scores:
            # No feedback to apply, return original results
            return results

        # Apply boost to each result
        boosted_count = 0
        for result in results:
            chunk_id = result.get("chunk_id")
            if chunk_id and chunk_id in feedback_scores:
                original_score = result.get("similarity", 0.0)
                feedback_score = feedback_scores[chunk_id]

                # Apply boost formula: final_score = similarity_score * (1 + boost_factor * feedback_score)
                boost_multiplier = 1 + (boost_factor * feedback_score)
                boosted_score = original_score * boost_multiplier

                # Clamp to reasonable range [0.0, 1.0]
                boosted_score = max(0.0, min(1.0, boosted_score))

                # Store original score and update similarity
                result["original_similarity"] = original_score
                result["feedback_score"] = feedback_score
                result["feedback_boost_applied"] = True
                result["similarity"] = boosted_score

                boosted_count += 1
                logger.info(
                    f"[Feature #152] Boosted chunk {chunk_id}: "
                    f"{original_score:.4f} -> {boosted_score:.4f} "
                    f"(feedback_score={feedback_score}, multiplier={boost_multiplier:.3f})"
                )

        if boosted_count > 0:
            # Re-sort results by boosted similarity
            results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
            logger.info(
                f"[Feature #152] Applied feedback boost to {boosted_count} chunks, re-sorted results"
            )

        return results

    def _apply_section_type_boost(
        self,
        results: List[Dict]
    ) -> List[Dict]:
        """
        FEATURE #246: Apply section type boost/penalty to retrieval results.

        Boosts recipe chunks and penalizes index/intro chunks for better
        relevance when answering recipe-related questions.

        Default boost factors:
        - recipe: 1.2x (20% boost - most valuable for recipe queries)
        - index: 0.5x (50% penalty - TOC/page listings are rarely useful)
        - intro: 0.8x (20% penalty - background info less useful)
        - general: 1.0x (no change)

        The boost is controlled by the 'prefer_recipe_chunks' setting (default: true).

        Args:
            results: List of retrieval results with 'similarity' and 'metadata' fields

        Returns:
            Results list with adjusted similarity scores, re-sorted by boosted score
        """
        if not results:
            return results

        # Check if section type boosting is enabled
        prefer_recipe_chunks = settings_store.get('prefer_recipe_chunks', 'true')
        if isinstance(prefer_recipe_chunks, str):
            prefer_recipe_chunks = prefer_recipe_chunks.lower() == 'true'

        if not prefer_recipe_chunks:
            logger.info("[Feature #246] Section type boosting disabled (prefer_recipe_chunks=false)")
            return results

        # Import boost factors from chunking module
        from services.chunking import SECTION_TYPE_BOOST, SECTION_TYPE_GENERAL

        boosted_count = 0
        for result in results:
            metadata = result.get("metadata", {})
            section_type = metadata.get("section_type", SECTION_TYPE_GENERAL)
            boost_factor = SECTION_TYPE_BOOST.get(section_type, 1.0)

            if boost_factor != 1.0:
                original_score = result.get("similarity", 0)
                boosted_score = min(1.0, max(0.0, original_score * boost_factor))

                # Store boosting info
                result["raw_similarity"] = original_score
                result["similarity"] = boosted_score
                result["section_type_boost"] = boost_factor
                boosted_count += 1

                logger.debug(
                    f"[Feature #246] Section type boost: chunk={result.get('chunk_id', '?')}, "
                    f"type={section_type}, factor={boost_factor}, "
                    f"score={original_score:.3f} -> {boosted_score:.3f}"
                )

        if boosted_count > 0:
            # Re-sort results by boosted similarity
            results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
            logger.info(
                f"[Feature #246] Applied section type boost to {boosted_count}/{len(results)} chunks, re-sorted results"
            )

        return results

    def _detect_language(self, text: str) -> Optional[str]:
        """
        Detect the language of the text using langdetect with default language fallback.

        Feature #317: Force Italian language responses
        - Uses default_language setting as fallback when detection fails
        - If default_language is 'auto', tries detection and falls back to 'it'
        - Returns language code (e.g., 'en', 'it', 'fr')
        """
        # Get default language setting
        default_lang = settings_store.get('default_language', 'it')

        # If default is not 'auto', use it directly (forces the language)
        if default_lang != 'auto':
            logger.info(f"[Feature #317] Using configured default language: {default_lang}")
            return default_lang

        # Auto mode: try to detect the language
        if not LANGDETECT_AVAILABLE:
            # Fallback to Italian when detection not available
            logger.info("[Feature #317] langdetect not available, defaulting to 'it'")
            return 'it'

        try:
            # langdetect can be unreliable for short text, so we catch exceptions
            lang = detect(text)
            logger.info(f"[Feature #317] Detected language: {lang}")
            return lang
        except LangDetectException:
            # Fallback to Italian when detection fails
            logger.info("[Feature #317] Language detection failed, defaulting to 'it'")
            return 'it'

    def _generate_graceful_degradation_suggestions(
        self,
        query: str,
        discarded_results: List[Dict[str, Any]],
        user_lang: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        [Feature #318] Generate alternative suggestions when RAG results are below threshold.

        When the context quality is too low, instead of just saying 'not found',
        this method provides:
        1. Partial matches from discarded low-relevance results
        2. Rephrasing suggestions
        3. List of similar/related documents that might be relevant
        4. Optional web search fallback suggestion

        Args:
            query: The original user query
            discarded_results: Results that were filtered out due to low relevance
            user_lang: Detected language for the user

        Returns:
            Dict with suggestion data including:
            - similar_topics: List of topics from low-relevance matches
            - suggested_documents: Documents that had some relevance
            - rephrasing_hints: Suggested ways to rephrase the query
            - web_search_enabled: Whether web search fallback is available
        """
        suggestions = {
            "similar_topics": [],
            "suggested_documents": [],
            "rephrasing_hints": [],
            "web_search_enabled": False,
            "partial_matches": []
        }

        # Check if web search fallback is enabled in settings
        web_search_enabled = settings_store.get('web_search_fallback_enabled', False)
        suggestions["web_search_enabled"] = web_search_enabled

        # Extract topics from discarded results (partial matches)
        seen_docs = set()

        for result in discarded_results[:5]:  # Limit to top 5 discarded
            doc_id = result.get("document_id")
            doc_title = result.get("document_title", result.get("metadata", {}).get("document_title", "Unknown"))
            text = result.get("text", "")[:200]  # First 200 chars as preview
            similarity = result.get("similarity", 0)

            # Add to suggested documents if not already seen
            if doc_id and doc_id not in seen_docs:
                seen_docs.add(doc_id)
                suggestions["suggested_documents"].append({
                    "id": doc_id,
                    "title": doc_title,
                    "relevance": round(similarity, 3)
                })

            # Extract potential topic keywords from chunk text
            if text and len(text) > 20:
                # Add partial match preview
                suggestions["partial_matches"].append({
                    "document": doc_title,
                    "preview": text[:150] + "..." if len(text) > 150 else text,
                    "relevance": round(similarity, 3)
                })

        # Generate rephrasing hints based on query analysis
        query_words = query.lower().split()
        if len(query_words) <= 3:
            # Short query - suggest being more specific
            if user_lang == "it":
                suggestions["rephrasing_hints"].append(
                    f"Prova ad aggiungere più dettagli alla tua ricerca, es. '{query} [contesto specifico]'"
                )
            else:
                suggestions["rephrasing_hints"].append(
                    f"Try adding more details to your search, e.g., '{query} [specific context]'"
                )
        else:
            # Longer query - suggest simplifying or using key terms
            key_terms = [w for w in query_words if len(w) > 3][:3]
            if key_terms:
                if user_lang == "it":
                    suggestions["rephrasing_hints"].append(
                        f"Prova una ricerca più semplice con: '{' '.join(key_terms)}'"
                    )
                else:
                    suggestions["rephrasing_hints"].append(
                        f"Try a simpler search with: '{' '.join(key_terms)}'"
                    )

        # Suggest listing documents if no partial matches
        if not suggestions["suggested_documents"]:
            if user_lang == "it":
                suggestions["rephrasing_hints"].append(
                    "Digita 'elenca documenti' per vedere tutti i documenti disponibili"
                )
            else:
                suggestions["rephrasing_hints"].append(
                    "Type 'list documents' to see all available documents"
                )

        logger.info(f"[Feature #318] Generated graceful degradation suggestions: "
                   f"{len(suggestions['suggested_documents'])} docs, "
                   f"{len(suggestions['partial_matches'])} partial matches, "
                   f"{len(suggestions['rephrasing_hints'])} hints")

        return suggestions

    def _format_graceful_degradation_response(
        self,
        query: str,
        suggestions: Dict[str, Any],
        user_lang: Optional[str] = None,
        relevance_threshold: float = 0.4
    ) -> str:
        """
        [Feature #318] Format a user-friendly response when RAG context is insufficient.

        Args:
            query: The original query
            suggestions: Output from _generate_graceful_degradation_suggestions
            user_lang: User's detected language
            relevance_threshold: The threshold that was used

        Returns:
            Formatted message string with alternative suggestions
        """
        # Header message in appropriate language
        if user_lang == "it":
            msg_parts = [
                f"🔍 Non ho trovato informazioni sufficientemente rilevanti per '{query}' "
                f"(soglia: {relevance_threshold:.0%}).\n"
            ]
        elif user_lang == "fr":
            msg_parts = [
                f"🔍 Je n'ai pas trouvé d'informations suffisamment pertinentes pour '{query}' "
                f"(seuil: {relevance_threshold:.0%}).\n"
            ]
        elif user_lang == "es":
            msg_parts = [
                f"🔍 No encontré información suficientemente relevante para '{query}' "
                f"(umbral: {relevance_threshold:.0%}).\n"
            ]
        elif user_lang == "de":
            msg_parts = [
                f"🔍 Ich habe keine ausreichend relevanten Informationen für '{query}' gefunden "
                f"(Schwelle: {relevance_threshold:.0%}).\n"
            ]
        else:
            msg_parts = [
                f"🔍 I couldn't find sufficiently relevant information for '{query}' "
                f"(threshold: {relevance_threshold:.0%}).\n"
            ]

        # Add partial matches section if available
        if suggestions.get("partial_matches"):
            if user_lang == "it":
                msg_parts.append("\n📄 **Risultati parziali trovati** (bassa rilevanza):\n")
            else:
                msg_parts.append("\n📄 **Partial matches found** (low relevance):\n")

            for i, match in enumerate(suggestions["partial_matches"][:3], 1):
                msg_parts.append(
                    f"{i}. **{match['document']}** (relevanza: {match['relevance']:.0%})\n"
                    f"   _{match['preview']}_\n"
                )

        # Add suggested documents section
        if suggestions.get("suggested_documents"):
            if user_lang == "it":
                msg_parts.append("\n📚 **Documenti che potrebbero essere utili**:\n")
            else:
                msg_parts.append("\n📚 **Documents that might be useful**:\n")

            for doc in suggestions["suggested_documents"][:5]:
                msg_parts.append(f"- {doc['title']}\n")

        # Add rephrasing suggestions
        if suggestions.get("rephrasing_hints"):
            if user_lang == "it":
                msg_parts.append("\n💡 **Suggerimenti**:\n")
            else:
                msg_parts.append("\n💡 **Suggestions**:\n")

            for hint in suggestions["rephrasing_hints"]:
                msg_parts.append(f"- {hint}\n")

        # Add web search option if enabled
        if suggestions.get("web_search_enabled"):
            if user_lang == "it":
                msg_parts.append(
                    "\n🌐 *Puoi anche provare a cercare sul web per questa domanda.*"
                )
            else:
                msg_parts.append(
                    "\n🌐 *You can also try searching the web for this question.*"
                )

        return "".join(msg_parts)

    def _detect_and_enhance_not_found_response(
        self,
        synthesized_content: str,
        query: str,
        truncated_results: List[Dict[str, Any]],
        user_lang: Optional[str] = None
    ) -> tuple[str, bool]:
        """
        [Feature #318] Detect if LLM response indicates 'not found' and enhance with suggestions.

        This handles the case where the vector search returns results that pass the
        relevance threshold, but the LLM determines the content doesn't actually
        answer the user's question.

        Args:
            synthesized_content: The LLM's synthesized response
            query: The original user query
            truncated_results: The search results that were provided to the LLM
            user_lang: Detected user language

        Returns:
            Tuple of (enhanced_content, was_enhanced)
        """
        # Patterns that indicate the LLM couldn't find relevant information
        not_found_patterns = [
            # English patterns
            r"no\s+mention\s+of",  # "no mention of X"
            r"no\s+information\s+(?:about|on|regarding|related)",  # "no information about X"
            r"(?:i\s+)?(?:couldn't|could\s+not|cannot|can't)\s+find\s+(?:any\s+)?information",  # "could not find information"
            r"(?:i\s+)?(?:couldn't|could\s+not|cannot|can't)\s+find",  # "couldn't find"
            r"(?:there\s+)?(?:is|are)\s+no\s+(?:relevant\s+)?(?:information|mention|data|content)",  # "there is no information"
            r"(?:no\s+)?(?:relevant\s+)?(?:content|data|info)\s+(?:found|available)",
            r"the\s+(?:documents?|excerpts?)\s+(?:do|does)\s+not\s+(?:contain|mention|include)",
            r"(?:not\s+)?(?:found|mentioned|included|present)\s+in\s+(?:the\s+)?(?:documents?|context|excerpts?)",
            r"no\s+(?:biological|ecological)\s+(?:data|information)",  # specific to nature queries
            # Italian patterns
            r"(?:non\s+)?(?:ci\s+sono|ho\s+trovato|sono\s+presenti)\s+(?:informazioni|menzioni|riferimenti)",
            r"non\s+(?:trovo|riesco\s+a\s+trovare|è\s+presente)",
            r"nessun(?:a|o)?\s+(?:informazione|menzione|riferimento)",
        ]

        # Check if response matches any not-found pattern
        content_lower = synthesized_content.lower()
        is_not_found = any(re.search(pattern, content_lower, re.IGNORECASE) for pattern in not_found_patterns)

        if not is_not_found:
            # Response seems to contain actual information
            return synthesized_content, False

        logger.info(f"[Feature #318] Detected 'not found' response from LLM, enhancing with suggestions")

        # Generate suggestions from the search results that were provided
        suggestions = self._generate_graceful_degradation_suggestions(
            query=query,
            discarded_results=truncated_results,  # These are the results that didn't help
            user_lang=user_lang
        )

        # Build enhanced response
        # Keep a shortened version of the original response as context
        original_summary = synthesized_content.split('\n')[0]  # First line/paragraph
        if len(original_summary) > 200:
            original_summary = original_summary[:200] + "..."

        # Create the enhanced message
        if user_lang == "it":
            enhanced_parts = [
                f"🔍 Non ho trovato informazioni direttamente rilevanti per la tua domanda nei documenti.\n\n"
            ]
        elif user_lang == "fr":
            enhanced_parts = [
                f"🔍 Je n'ai pas trouvé d'informations directement pertinentes pour votre question dans les documents.\n\n"
            ]
        elif user_lang == "es":
            enhanced_parts = [
                f"🔍 No encontré información directamente relevante para tu pregunta en los documentos.\n\n"
            ]
        elif user_lang == "de":
            enhanced_parts = [
                f"🔍 Ich habe keine direkt relevanten Informationen für Ihre Frage in den Dokumenten gefunden.\n\n"
            ]
        else:
            enhanced_parts = [
                f"🔍 I couldn't find directly relevant information for your question in the documents.\n\n"
            ]

        # Add partial matches if available
        if suggestions.get("partial_matches"):
            if user_lang == "it":
                enhanced_parts.append("📄 **Tuttavia, ho trovato alcuni documenti che potrebbero essere correlati**:\n")
            else:
                enhanced_parts.append("📄 **However, I found some documents that might be related**:\n")

            for i, match in enumerate(suggestions["partial_matches"][:3], 1):
                enhanced_parts.append(
                    f"{i}. **{match['document']}** (relevance: {match['relevance']:.0%})\n"
                    f"   _{match['preview']}_\n"
                )
            enhanced_parts.append("\n")

        # Add suggested documents
        if suggestions.get("suggested_documents"):
            if user_lang == "it":
                enhanced_parts.append("📚 **Documenti disponibili che potresti consultare**:\n")
            else:
                enhanced_parts.append("📚 **Available documents you might want to explore**:\n")

            for doc in suggestions["suggested_documents"][:5]:
                enhanced_parts.append(f"- {doc['title']}\n")
            enhanced_parts.append("\n")

        # Add rephrasing suggestions
        if suggestions.get("rephrasing_hints"):
            if user_lang == "it":
                enhanced_parts.append("💡 **Suggerimenti per affinare la ricerca**:\n")
            else:
                enhanced_parts.append("💡 **Suggestions to refine your search**:\n")

            for hint in suggestions["rephrasing_hints"]:
                enhanced_parts.append(f"- {hint}\n")
            enhanced_parts.append("\n")

        # Add web search option if enabled
        if suggestions.get("web_search_enabled"):
            if user_lang == "it":
                enhanced_parts.append(
                    "🌐 *Puoi anche provare a cercare sul web per questa domanda.*\n"
                )
            else:
                enhanced_parts.append(
                    "🌐 *You can also try searching the web for this question.*\n"
                )

        enhanced_content = "".join(enhanced_parts)
        logger.info(f"[Feature #318] Enhanced 'not found' response with {len(suggestions.get('partial_matches', []))} partial matches, "
                   f"{len(suggestions.get('suggested_documents', []))} doc suggestions")

        return enhanced_content, True

    def _extract_document_citations(self, response_text: str) -> List[str]:
        """
        Extract document names mentioned in an LLM response.
        Feature #181: Hallucination detection

        Looks for patterns like:
        - "From document: Title"
        - "**Title**"
        - "document called 'Title'"
        - Sources: Title1, Title2
        - Based on "Title"

        Args:
            response_text: The LLM's response text

        Returns:
            List of document titles/names mentioned in the response
        """
        citations = set()

        # Pattern 1: "From document: Title" or "From 'Title'"
        pattern1 = re.findall(r'[Ff]rom\s+(?:document[:\s]+)?["\']?([^"\':\n]+)["\']?', response_text)
        for match in pattern1:
            cleaned = match.strip().rstrip('.,;:')
            if len(cleaned) > 2 and not cleaned.lower().startswith(('the ', 'a ', 'an ', 'your ', 'my ')):
                citations.add(cleaned)

        # Pattern 2: **Title** (markdown bold often used for doc names)
        pattern2 = re.findall(r'\*\*([^*\n]+)\*\*', response_text)
        for match in pattern2:
            cleaned = match.strip().rstrip('.,;:')
            # Filter out common non-document bold text
            if len(cleaned) > 2 and not cleaned.lower() in ['sources', 'note', 'important', 'warning', 'summary', 'result', 'answer']:
                # Feature #219: Skip prices/currency values - they are NOT document names!
                # Skip patterns like "13,000 EUR", "€500", "$1,234.56", "100 USD", etc.
                if re.match(r'^[\d€$£¥₹,.]+\s*(?:EUR|USD|GBP|JPY|INR|CHF|CAD|AUD|NZD|SEK|NOK|DKK|PLN|CZK|HUF|TRY|BRL|MXN|ZAR|SGD|HKD|KRW|CNY|RUB|THB|MYR|PHP|IDR|VND|TWD|€|\$|£)?$', cleaned, re.IGNORECASE):
                    continue
                # Also skip if it starts with a number (likely a price or quantity)
                if re.match(r'^[\d€$£¥₹]', cleaned):
                    continue
                citations.add(cleaned)

        # Pattern 3: Sources: Title1, Title2
        sources_match = re.search(r'\*?\*?[Ss]ources?\*?\*?[:\s]+([^\n]+)', response_text)
        if sources_match:
            sources_text = sources_match.group(1)
            # Split by comma and clean
            for source in sources_text.split(','):
                cleaned = source.strip().rstrip('.,;:').strip('*').strip()
                if len(cleaned) > 2:
                    citations.add(cleaned)

        # Pattern 4: "Based on excerpts from Title"
        pattern4 = re.findall(r'[Bb]ased on\s+(?:the\s+)?(?:excerpts?\s+from\s+)?["\']?([^"\':\n,]+)["\']?', response_text)
        for match in pattern4:
            cleaned = match.strip().rstrip('.,;:')
            if len(cleaned) > 2 and not cleaned.lower().startswith(('the ', 'a ', 'an ')):
                citations.add(cleaned)

        # Pattern 5: "according to Title" or "as mentioned in Title"
        pattern5 = re.findall(r'(?:[Aa]ccording to|[Mm]entioned in|[Ss]tated in)\s+["\']?([^"\':\n,]+)["\']?', response_text)
        for match in pattern5:
            cleaned = match.strip().rstrip('.,;:')
            if len(cleaned) > 2:
                citations.add(cleaned)

        logger.info(f"[Feature #181] Extracted {len(citations)} citations from response: {citations}")
        return list(citations)

    def _validate_citations(
        self,
        cited_docs: List[str],
        valid_doc_titles: List[str],
        similarity_threshold: float = 0.7
    ) -> tuple[List[str], List[str], bool]:
        """
        Validate cited documents against the list of actually retrieved documents.
        Feature #181: Hallucination detection

        Uses fuzzy matching since LLM might slightly modify document names.

        Args:
            cited_docs: Document names extracted from LLM response
            valid_doc_titles: Actual document titles from vector search results
            similarity_threshold: Minimum similarity ratio for fuzzy matching

        Returns:
            Tuple of (valid_citations, hallucinated_citations, hallucination_detected)
        """
        from difflib import SequenceMatcher

        valid_citations = []
        hallucinated = []

        # Normalize valid titles for comparison
        normalized_valid = {title.lower().strip(): title for title in valid_doc_titles}

        for cited in cited_docs:
            cited_lower = cited.lower().strip()

            # Direct match
            if cited_lower in normalized_valid:
                valid_citations.append(cited)
                continue

            # Fuzzy match
            best_match = None
            best_ratio = 0
            for valid_lower, valid_title in normalized_valid.items():
                ratio = SequenceMatcher(None, cited_lower, valid_lower).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = valid_title

            if best_ratio >= similarity_threshold:
                valid_citations.append(best_match)  # Use the actual valid title
                logger.info(f"[Feature #181] Fuzzy matched '{cited}' to '{best_match}' (ratio: {best_ratio:.2f})")
            else:
                hallucinated.append(cited)
                logger.warning(f"[Feature #181] HALLUCINATION DETECTED: '{cited}' not in valid docs (best match: {best_match} with ratio {best_ratio:.2f})")

        return valid_citations, hallucinated, len(hallucinated) > 0

    def _strip_hallucinated_citations(
        self,
        response_text: str,
        hallucinated: List[str],
        valid_titles: List[str]
    ) -> str:
        """
        Remove hallucinated document citations from the response and fix the Sources section.
        Feature #181: Hallucination detection

        Args:
            response_text: The original LLM response
            hallucinated: List of hallucinated document names to remove
            valid_titles: List of valid document titles to use in Sources

        Returns:
            Cleaned response text with hallucinations removed
        """
        cleaned = response_text

        # Remove references to hallucinated documents
        for halluc in hallucinated:
            # Remove patterns like "From hallucinated_doc:" or "Based on hallucinated_doc"
            patterns_to_remove = [
                rf'[Ff]rom\s+["\']?{re.escape(halluc)}["\']?[:\s]*',
                rf'[Bb]ased on\s+(?:the\s+)?(?:excerpts?\s+from\s+)?["\']?{re.escape(halluc)}["\']?[:\s,]*',
                rf'[Aa]ccording to\s+["\']?{re.escape(halluc)}["\']?[:\s,]*',
                rf'\*\*{re.escape(halluc)}\*\*[:\s,]*',
            ]
            for pattern in patterns_to_remove:
                cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        # Fix the Sources section to only include valid documents
        sources_pattern = r'(\*?\*?[Ss]ources?\*?\*?[:\s]+)[^\n]+'
        if valid_titles:
            new_sources = f"**Sources:** {', '.join(valid_titles)}"
            cleaned = re.sub(sources_pattern, new_sources, cleaned)
        else:
            # Remove Sources section entirely if no valid sources
            cleaned = re.sub(sources_pattern, '', cleaned)

        # Clean up any double spaces or multiple newlines
        cleaned = re.sub(r'  +', ' ', cleaned)
        cleaned = re.sub(r'\n\n\n+', '\n\n', cleaned)

        return cleaned.strip()

    def _is_question_pattern(self, message: str) -> bool:
        """
        Language-agnostic question detection using punctuation and patterns.
        Detects questions based on:
        1. Question marks
        2. Question word patterns (what, how, why, etc.) at start
        3. Interrogative structure
        4. Imperative verbs commonly used to request information
        """
        message_stripped = message.strip()

        # Check for question mark
        if message_stripped.endswith('?'):
            return True

        # Common question word patterns (multilingual)
        # These patterns work across many languages
        question_patterns = [
            # English - interrogatives
            r'^\s*(what|how|why|when|where|who|which|whose|whom|can you|could you|would you|will you|do you|does|did|is|are|was|were|have|has|had|tell me|explain|describe)',
            # English - imperative verbs for requesting information
            r'^\s*(give me|show me|list|find|search|get|retrieve|look up|look for|summarize|outline|provide)',
            # Italian - interrogatives
            r'^\s*(cosa|come|perché|perche|quando|dove|chi|quale|quali|puoi|potresti)',
            # Italian - imperative verbs for requesting information
            r'^\s*(dammi|dimmi|elenca|mostra|cerca|trova|spiega|spiegami|descrivi|riassumi|parlami|fammi vedere|fammi sapere|fammi|trova|cercami|mostrami|elencami|descrivimi|riassumimi)',
            # Spanish
            r'^\s*(qué|cómo|por qué|cuándo|dónde|quién|cuál|cuáles|puedes|podrías|dime|explica|describe|dame|muéstrame|busca|encuentra|lista|enumera|resume)',
            # French
            r'^\s*(quoi|comment|pourquoi|quand|où|qui|quel|quelle|quels|quelles|peux-tu|pourrais-tu|dis-moi|explique|décris|donne-moi|montre-moi|cherche|trouve|liste|résume)',
            # German
            r'^\s*(was|wie|warum|wann|wo|wer|welche|welcher|welches|kannst du|könntest du|sag mir|erkläre|beschreibe|gib mir|zeig mir|such|finde|liste|fasse zusammen)',
            # Portuguese
            r'^\s*(o que|como|por que|quando|onde|quem|qual|quais|você pode|poderia|me diga|explique|descreva|me dê|me mostre|procure|encontre|liste|resuma)',
        ]

        message_lower = message.lower()
        for pattern in question_patterns:
            if re.match(pattern, message_lower, re.IGNORECASE):
                return True

        # Check for Italian/English imperatives anywhere in the message (not just at start)
        # This catches phrases like "per favore elenca..." or "please give me..."
        imperative_keywords = [
            # Italian
            'dammi', 'elenca', 'mostra', 'cerca', 'trova', 'dimmi', 'spiega',
            'descrivi', 'riassumi', 'fammi vedere', 'fammi sapere',
            # English
            'give me', 'show me', 'list', 'find', 'search for', 'tell me',
            'explain', 'describe', 'summarize',
        ]
        for keyword in imperative_keywords:
            if keyword in message_lower:
                return True

        return False

    def _contains_calculation_keywords(self, message: str) -> bool:
        """
        Detect if message contains calculation-related keywords (multilingual).
        These indicate the user wants SQL/aggregation operations.
        """
        message_lower = message.lower()

        # Multilingual calculation keywords
        calc_keywords = [
            # English
            'total', 'sum', 'average', 'avg', 'mean', 'count', 'how many',
            'minimum', 'min', 'maximum', 'max', 'calculate', 'add up',
            'compute', 'aggregate', 'summarize', 'tally',
            # Italian
            'totale', 'somma', 'media', 'quanti', 'quante', 'minimo', 'massimo', 'calcola',
            # Spanish
            'suma', 'promedio', 'cuántos', 'cuántas', 'mínimo', 'máximo', 'calcula',
            # French
            'total', 'somme', 'moyenne', 'combien', 'minimum', 'maximum', 'calcule',
            # German
            'summe', 'durchschnitt', 'wie viele', 'minimum', 'maximum', 'berechne',
            # Portuguese
            'soma', 'média', 'quantos', 'quantas', 'mínimo', 'máximo', 'calcule',
        ]

        return any(keyword in message_lower for keyword in calc_keywords)

    def _contains_list_documents_keywords(self, message: str) -> bool:
        """
        Detect if message is asking to list/show available documents (multilingual).
        Feature #362: Exclude queries that contain search-intent words (e.g. "search in my documents"
        should trigger vector_search, NOT list_documents).
        """
        message_lower = message.lower()

        # Feature #362: If the message contains search-intent words alongside document words,
        # the user wants to SEARCH documents, not LIST them
        search_intent_words = [
            # English
            'search', 'find', 'look for', 'look up', 'looking for', 'query',
            'about', 'information', 'tell me', 'ask',
            # Italian
            'cerca', 'cercare', 'trovare', 'informazioni', 'chiedi', 'chiedere',
            # Spanish
            'buscar', 'busca', 'encontrar', 'información',
            # French
            'chercher', 'cherche', 'trouver', 'information',
            # German
            'suchen', 'such', 'finden', 'information',
        ]

        has_search_intent = any(word in message_lower for word in search_intent_words)

        # Multilingual document listing keywords
        list_keywords = [
            # English
            'what documents', 'which documents', 'what files', 'which files',
            'documents available', 'files available', 'list documents', 'list files',
            'show documents', 'show files', 'available documents', 'available files',
            'documents do i have', 'files do i have', 'my documents', 'my files',
            # Italian
            'quali documenti', 'che documenti', 'che file', 'documenti disponibili',
            'file disponibili', 'mostra documenti', 'elenco documenti', 'lista documenti',
            'i miei documenti', 'i miei file',
            # Spanish
            'qué documentos', 'cuáles documentos', 'qué archivos', 'documentos disponibles',
            'archivos disponibles', 'mostrar documentos', 'listar documentos', 'mis documentos',
            # French
            'quels documents', 'quels fichiers', 'documents disponibles', 'fichiers disponibles',
            'montrer documents', 'lister documents', 'mes documents', 'mes fichiers',
            # German
            'welche dokumente', 'welche dateien', 'verfügbare dokumente', 'verfügbare dateien',
            'dokumente anzeigen', 'dokumente auflisten', 'meine dokumente', 'meine dateien',
            # Portuguese
            'quais documentos', 'quais arquivos', 'documentos disponíveis', 'arquivos disponíveis',
            'mostrar documentos', 'listar documentos', 'meus documentos', 'meus arquivos',
        ]

        has_list_keyword = any(keyword in message_lower for keyword in list_keywords)

        # Feature #362: If user has search intent, they want to search IN documents, not list them
        if has_list_keyword and has_search_intent:
            logger.info(f"[Feature #362] List documents keyword found but search intent detected - deferring to vector search")
            return False

        return has_list_keyword

    def _has_document_context_words(self, message: str) -> bool:
        """
        Detect if message mentions documents/files (multilingual).
        This helps identify document-related queries.
        """
        message_lower = message.lower()

        # Multilingual document context words
        doc_words = [
            # English
            'document', 'documents', 'file', 'files', 'text', 'pdf', 'uploaded',
            # Italian
            'documento', 'documenti', 'file', 'testo', 'caricato', 'caricati',
            # Spanish
            'documento', 'documentos', 'archivo', 'archivos', 'texto', 'cargado',
            # French
            'document', 'documents', 'fichier', 'fichiers', 'texte', 'téléchargé',
            # German
            'dokument', 'dokumente', 'datei', 'dateien', 'text', 'hochgeladen',
            # Portuguese
            'documento', 'documentos', 'arquivo', 'arquivos', 'texto', 'carregado',
        ]

        return any(word in message_lower for word in doc_words)

    def _has_unstructured_document_context_words(self, message: str) -> bool:
        """
        Detect if message mentions words that specifically refer to unstructured documents
        like books, PDFs, manuals, etc. (multilingual).

        This is used to determine if a "calculation-like" question (quante, how many, etc.)
        should be routed to RAG instead of SQL.

        Feature #208: Fix "quante/how many" misclassification as SQL calculation
        """
        message_lower = message.lower()

        # Words that indicate unstructured document context (books, PDFs, manuals, etc.)
        unstructured_words = [
            # English
            'book', 'books', 'pdf', 'manual', 'manuals', 'chapter', 'chapters',
            'page', 'pages', 'paragraph', 'paragraphs', 'article', 'articles',
            'report', 'reports', 'guide', 'guides', 'recipe', 'recipes',
            'text', 'content', 'section', 'sections', 'word document',
            # Italian
            'libro', 'libri', 'manuale', 'manuali', 'capitolo', 'capitoli',
            'pagina', 'pagine', 'paragrafo', 'paragrafi', 'articolo', 'articoli',
            'rapporto', 'rapporti', 'guida', 'guide', 'ricetta', 'ricette',
            'testo', 'contenuto', 'sezione', 'sezioni',
            # Spanish
            'libro', 'libros', 'manual', 'manuales', 'capítulo', 'capítulos',
            'página', 'páginas', 'párrafo', 'párrafos', 'artículo', 'artículos',
            'informe', 'informes', 'guía', 'guías', 'receta', 'recetas',
            'texto', 'contenido', 'sección', 'secciones',
            # French
            'livre', 'livres', 'manuel', 'manuels', 'chapitre', 'chapitres',
            'page', 'pages', 'paragraphe', 'paragraphes', 'article', 'articles',
            'rapport', 'rapports', 'guide', 'guides', 'recette', 'recettes',
            'texte', 'contenu', 'section', 'sections',
            # German
            'buch', 'bücher', 'handbuch', 'handbücher', 'kapitel',
            'seite', 'seiten', 'absatz', 'absätze', 'artikel',
            'bericht', 'berichte', 'leitfaden', 'rezept', 'rezepte',
            'text', 'inhalt', 'abschnitt', 'abschnitte',
            # Portuguese
            'livro', 'livros', 'manual', 'manuais', 'capítulo', 'capítulos',
            'página', 'páginas', 'parágrafo', 'parágrafos', 'artigo', 'artigos',
            'relatório', 'relatórios', 'guia', 'guias', 'receita', 'receitas',
            'texto', 'conteúdo', 'seção', 'seções',
        ]

        return any(word in message_lower for word in unstructured_words)

    def classify_query(self, query: str) -> Dict[str, Any]:
        """
        Feature #286: Classify short queries as lookup instead of Q&A.

        Short queries without verbs (e.g., 'ricette cipolla') should be treated as lookups
        that find and summarize, not as questions requiring clarification.

        Classification logic:
        1. If query has <=3 words and no verbs → 'lookup' (find and summarize)
        2. If query ends with ? or starts with question words → 'question' (Q&A style)
        3. If query contains sum/average/count keywords → 'calculation'
        4. Default → 'question' (treat ambiguous queries as questions)

        Args:
            query: User query to classify

        Returns:
            Dict with:
            - query_type: 'lookup', 'question', or 'calculation'
            - confidence: 0.0 to 1.0
            - reasoning: Explanation for the classification
        """
        if not query or not query.strip():
            return {
                "query_type": "question",
                "confidence": 0.5,
                "reasoning": "Empty query, default to question"
            }

        query_clean = query.strip()
        query_lower = query_clean.lower()

        # Step 1: Check for calculation keywords (highest priority)
        calculation_keywords = [
            # English
            'sum', 'total', 'average', 'avg', 'mean', 'count', 'how many',
            'minimum', 'min', 'maximum', 'max', 'calculate', 'compute',
            # Italian
            'somma', 'totale', 'media', 'quanti', 'quante', 'minimo', 'massimo', 'calcola',
            # Spanish
            'suma', 'promedio', 'cuántos', 'cuántas', 'mínimo', 'máximo', 'calcular',
        ]

        if any(kw in query_lower for kw in calculation_keywords):
            logger.info(f"[Feature #286] classify_query: '{query[:50]}...' → 'calculation' (keyword match)")
            return {
                "query_type": "calculation",
                "confidence": 0.9,
                "reasoning": "Calculation keyword detected"
            }

        # Step 2: Check for question indicators
        question_words = [
            # English
            'what', 'where', 'when', 'who', 'why', 'how', 'which', 'is', 'are', 'do', 'does',
            'can', 'could', 'would', 'should', 'will',
            # Italian
            'cosa', 'dove', 'quando', 'chi', 'perché', 'come', 'quale', 'quali',
            'è', 'sono', 'puoi', 'puó', 'posso',
            # Spanish
            'qué', 'dónde', 'cuándo', 'quién', 'por qué', 'cómo', 'cuál', 'cuáles',
            'es', 'son', 'puedes', 'puede',
        ]

        # Check if query ends with ? or starts with question word
        if query_clean.endswith('?'):
            logger.info(f"[Feature #286] classify_query: '{query[:50]}...' → 'question' (ends with ?)")
            return {
                "query_type": "question",
                "confidence": 0.95,
                "reasoning": "Query ends with question mark"
            }

        first_word = query_lower.split()[0] if query_lower.split() else ""
        if first_word in question_words:
            logger.info(f"[Feature #286] classify_query: '{query[:50]}...' → 'question' (starts with question word)")
            return {
                "query_type": "question",
                "confidence": 0.9,
                "reasoning": f"Query starts with question word '{first_word}'"
            }

        # Step 3: Check for short query without verbs (lookup pattern)
        words = query_lower.split()
        word_count = len(words)

        if word_count <= 3:
            # Check if any word is a verb (imperative or conjugated)
            # Common verbs in Italian, English, Spanish that indicate a request/question
            verb_indicators = [
                # English verbs
                'show', 'give', 'tell', 'find', 'get', 'list', 'describe', 'explain',
                'search', 'look', 'help', 'want', 'need', 'please',
                # Italian verbs (imperatives and common forms)
                'dammi', 'dimmi', 'mostra', 'mostrami', 'trova', 'trovami', 'cerca', 'cercami',
                'elenca', 'elencami', 'spiega', 'spiegami', 'descrivi', 'descrivimi',
                'voglio', 'vorrei', 'fammi', 'aiutami', 'aiuta',
                # Spanish verbs
                'dame', 'dime', 'muestra', 'muéstrame', 'busca', 'búscame', 'encuentra',
                'lista', 'explica', 'describe', 'quiero', 'quisiera', 'ayuda', 'ayúdame',
            ]

            has_verb = any(word in verb_indicators for word in words)

            if not has_verb:
                logger.info(f"[Feature #286] classify_query: '{query[:50]}...' → 'lookup' (short query, no verbs, {word_count} words)")
                return {
                    "query_type": "lookup",
                    "confidence": 0.85,
                    "reasoning": f"Short query ({word_count} words) without verbs - treating as lookup"
                }

        # Step 4: Default to question for longer or ambiguous queries
        logger.info(f"[Feature #286] classify_query: '{query[:50]}...' → 'question' (default, {word_count} words)")
        return {
            "query_type": "question",
            "confidence": 0.6,
            "reasoning": f"Default classification for {word_count}-word query"
        }

    def _classify_query_intent(
        self,
        query: str,
        document_ids: Optional[List[str]] = None,
        use_llm: bool = True
    ) -> Dict[str, Any]:
        """
        Feature #217: LLM-based query intent classification.

        Classifies the user query into one of four intent categories:
        - factual_lookup: Specific facts (price, date, specification, name)
        - conceptual: Broad understanding, explanation, summary
        - calculation: Math operations (sum, average, count, compare numbers)
        - comparison: Comparing entities across documents or within same document

        Args:
            query: User query to classify
            document_ids: Optional list of document IDs being queried
            use_llm: Whether to use LLM for classification (True) or fallback to rules (False)

        Returns:
            Dict with:
            - intent: One of factual_lookup, conceptual, calculation, comparison
            - confidence: 0.0 to 1.0
            - reasoning: Explanation for the classification
            - suggested_tool: Recommended tool (vector_search, sql_analysis, etc.)
            - routing_hints: Additional hints for tool execution
        """
        # Get document context for classification
        documents = _get_documents_sync()
        if document_ids:
            documents = [d for d in documents if d.id in document_ids]

        has_structured = any(d.document_type == "structured" for d in documents)
        has_unstructured = any(d.document_type == "unstructured" for d in documents)

        # Feature #229: Check for listing intent FIRST before LLM classification
        # Listing queries need special handling with high top_k, so we use keyword detection
        # which is more reliable than LLM for this specific intent
        listing_keywords = [
            # English
            'list all', 'show all', 'show me all', 'give me all',
            'enumerate', 'table of contents', 'index', 'toc',
            'what are all', 'every', 'all the', 'complete list',
            'full list', 'everything about', 'all items', 'all entries',
            # Italian
            'elencami', 'elenca tutti', 'elenca tutte', 'mostrami tutti', 'mostrami tutte',
            'lista completa', 'tutti i', 'tutte le', 'indice', 'sommario',
            'elenco completo', 'dammi tutti', 'dammi tutte',
            # Spanish
            'listar todos', 'listar todas', 'mostrar todos', 'mostrar todas',
            'índice', 'tabla de contenido', 'enumerar',
        ]
        query_lower = query.lower()
        if any(kw in query_lower for kw in listing_keywords):
            logger.info(f"[Feature #229] Listing intent detected for query: {query[:50]}...")
            return {
                "intent": "listing",
                "confidence": 0.95,
                "reasoning": "Listing keywords detected - retrieving many chunks for comprehensive listing",
                "suggested_tool": "vector_search",
                "routing_hints": self._generate_routing_hints("listing", has_structured, has_unstructured),
                "method": "rules_priority"
            }

        # Try LLM-based classification first (if enabled and available)
        if use_llm:
            llm_result = self._classify_query_intent_llm(query, has_structured, has_unstructured)
            if llm_result and llm_result.get("confidence", 0) >= 0.7:
                logger.info(f"[Feature #217] LLM classification: {llm_result['intent']} (confidence: {llm_result['confidence']:.2f})")
                return llm_result

        # Fallback to rule-based classification
        logger.info(f"[Feature #217] Using rule-based classification (LLM unavailable or low confidence)")
        return self._classify_query_intent_rules(query, has_structured, has_unstructured)

    def _classify_query_intent_llm(
        self,
        query: str,
        has_structured: bool,
        has_unstructured: bool
    ) -> Optional[Dict[str, Any]]:
        """
        Use LLM to classify query intent.

        This provides more nuanced understanding than keyword matching.
        """
        try:
            # Use a fast, cheap model for classification
            llm_model = settings_store.get('llm_model') or 'gpt-4o-mini'

            # Build the classification prompt
            classification_prompt = f"""You are a query intent classifier for a document Q&A system.

The system has two types of documents:
- STRUCTURED data (CSV, Excel, JSON): Contains tabular data with rows and columns. Good for calculations, aggregations, lookups by field.
- UNSTRUCTURED data (PDF, TXT, Word, Markdown): Contains text content. Good for semantic search, explanations, conceptual questions.

Available document types: {"Structured (tabular)" if has_structured else ""}{" and " if has_structured and has_unstructured else ""}{"Unstructured (text)" if has_unstructured else ""}

Classify the following user query into EXACTLY ONE category:

1. **factual_lookup**: Looking for a specific fact (price, date, name, specification, number)
   Examples: "What is the price of X?", "When was Y founded?", "What's the model number for Z?"

2. **conceptual**: Seeking understanding, explanation, or summary of concepts
   Examples: "Explain how GMDSS works", "Summarize the safety procedures", "What is the difference between X and Y?"

3. **calculation**: Requesting mathematical computation or aggregation
   Examples: "What's the total revenue?", "How many products cost more than $100?", "Calculate the average price"

4. **comparison**: Comparing multiple items, entities, or values
   Examples: "Compare product A and B", "Which is more expensive, X or Y?", "Show differences between models"

5. **listing**: Requesting a comprehensive list, index, table of contents, or enumeration of all items
   Examples: "List all recipes", "Show the table of contents", "What chapters are in the book?", "Elencami tutti i prodotti", "Show me everything about X"

USER QUERY: "{query}"

Respond with ONLY a JSON object (no markdown, no explanation):
{{"intent": "<category>", "confidence": <0.0-1.0>, "reasoning": "<brief explanation>"}}"""

            # Use OpenAI or OpenRouter
            if llm_model.startswith("openrouter:"):
                api_key = settings_store.get('openrouter_api_key')
                if not api_key:
                    return None

                model_name = llm_model.replace("openrouter:", "")
                client = OpenAI(
                    api_key=api_key,
                    base_url="https://openrouter.ai/api/v1"
                )

                response = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": classification_prompt}],
                    temperature=0.0,
                    max_tokens=100
                )
            else:
                # OpenAI
                openai_client = self._get_openai_client()
                if not openai_client:
                    return None

                response = openai_client.chat.completions.create(
                    model=llm_model if not llm_model.startswith("ollama:") else "gpt-4o-mini",
                    messages=[{"role": "user", "content": classification_prompt}],
                    temperature=0.0,
                    max_tokens=100
                )

            # Parse the response
            response_text = response.choices[0].message.content.strip()

            # Handle markdown-wrapped JSON
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                json_lines = [l for l in lines if not l.startswith("```")]
                response_text = "\n".join(json_lines).strip()

            result = json.loads(response_text)
            intent = result.get("intent", "conceptual")
            confidence = float(result.get("confidence", 0.5))
            reasoning = result.get("reasoning", "")

            # Map intent to suggested tool
            tool_mapping = {
                "factual_lookup": "vector_search" if has_unstructured else "sql_analysis",
                "conceptual": "vector_search",
                "calculation": "sql_analysis" if has_structured else "vector_search",
                "comparison": "vector_search" if has_unstructured else "sql_analysis",
                "listing": "vector_search"  # Feature #229: Listing queries need many chunks
            }

            suggested_tool = tool_mapping.get(intent, "vector_search")

            # Generate routing hints
            routing_hints = self._generate_routing_hints(intent, has_structured, has_unstructured)

            return {
                "intent": intent,
                "confidence": confidence,
                "reasoning": reasoning,
                "suggested_tool": suggested_tool,
                "routing_hints": routing_hints,
                "method": "llm"
            }

        except json.JSONDecodeError as e:
            logger.warning(f"[Feature #217] Failed to parse LLM classification response: {e}")
            return None
        except Exception as e:
            logger.warning(f"[Feature #217] LLM classification failed: {e}")
            return None

    def _classify_query_intent_rules(
        self,
        query: str,
        has_structured: bool,
        has_unstructured: bool
    ) -> Dict[str, Any]:
        """
        Rule-based fallback for query intent classification.

        Used when LLM classification is unavailable or returns low confidence.
        """
        query_lower = query.lower()

        # Calculation indicators
        calculation_keywords = [
            'total', 'sum', 'average', 'avg', 'mean', 'count', 'how many',
            'minimum', 'min', 'maximum', 'max', 'calculate', 'add up',
            'compute', 'aggregate', 'tally',
            # Italian
            'totale', 'somma', 'media', 'quanti', 'quante', 'minimo', 'massimo', 'calcola',
            # Spanish
            'cuántos', 'cuántas',
        ]

        # Comparison indicators
        comparison_keywords = [
            'compare', 'comparison', 'versus', 'vs', 'difference between',
            'which is better', 'which is more', 'which is less',
            'higher than', 'lower than', 'more expensive', 'cheaper',
            # Italian
            'confronta', 'confronto', 'differenza tra', 'quale è meglio',
            # Spanish
            'comparar', 'comparación', 'diferencia entre',
        ]

        # Factual lookup indicators (specific facts)
        factual_keywords = [
            'what is the price', 'how much does', 'what is the cost',
            'what is the name', 'what is the date', 'when was',
            'what is the number', 'what is the model', 'what is the specification',
            'qual è il prezzo', 'quanto costa', 'qual è il nome',
            # Specific question patterns
            r'what\s+is\s+the\s+\w+\s+of',
            r'what\s+is\s+\w+\'s\s+\w+',
        ]

        # Conceptual indicators (explanations, summaries)
        conceptual_keywords = [
            'explain', 'describe', 'what is', 'how does', 'why does',
            'tell me about', 'summarize', 'overview', 'introduction to',
            'what are the', 'how to', 'guide to',
            # Italian
            'spiega', 'descrivi', 'cos\'è', 'come funziona', 'perché',
            'parlami di', 'riassumi', 'panoramica',
        ]

        # Feature #229: Listing indicators (comprehensive lists, indexes, TOCs)
        listing_keywords = [
            # English
            'list all', 'show all', 'show me all', 'give me all',
            'enumerate', 'table of contents', 'index', 'toc',
            'what are all', 'every', 'all the', 'complete list',
            'full list', 'everything about', 'all items', 'all entries',
            # Italian
            'elencami', 'elenca tutti', 'elenca tutte', 'mostrami tutti', 'mostrami tutte',
            'lista completa', 'tutti i', 'tutte le', 'indice', 'sommario',
            'elenco completo', 'dammi tutti', 'dammi tutte',
            # Spanish
            'listar todos', 'listar todas', 'mostrar todos', 'mostrar todas',
            'índice', 'tabla de contenido', 'enumerar',
        ]

        # Feature #229: Check for listing intent FIRST (before other checks)
        # This ensures broad queries get high top_k
        if any(kw in query_lower for kw in listing_keywords):
            logger.info(f"[Feature #229] Listing intent detected for query: {query[:50]}...")
            return {
                "intent": "listing",
                "confidence": 0.9,
                "reasoning": "Listing keywords detected - will retrieve many chunks",
                "suggested_tool": "vector_search",
                "routing_hints": self._generate_routing_hints("listing", has_structured, has_unstructured),
                "method": "rules"
            }

        # Check for calculation intent
        if any(kw in query_lower for kw in calculation_keywords):
            # But check if it's about unstructured content (e.g., "how many chapters in the book")
            if self._has_unstructured_document_context_words(query):
                intent = "conceptual"
                suggested_tool = "vector_search"
            else:
                intent = "calculation"
                suggested_tool = "sql_analysis" if has_structured else "vector_search"
            return {
                "intent": intent,
                "confidence": 0.8,
                "reasoning": "Calculation keywords detected",
                "suggested_tool": suggested_tool,
                "routing_hints": self._generate_routing_hints(intent, has_structured, has_unstructured),
                "method": "rules"
            }

        # Check for comparison intent
        if any(kw in query_lower for kw in comparison_keywords):
            return {
                "intent": "comparison",
                "confidence": 0.85,
                "reasoning": "Comparison keywords detected",
                "suggested_tool": "vector_search" if has_unstructured else "sql_analysis",
                "routing_hints": self._generate_routing_hints("comparison", has_structured, has_unstructured),
                "method": "rules"
            }

        # Check for factual lookup intent
        for kw in factual_keywords:
            if isinstance(kw, str) and kw in query_lower:
                return {
                    "intent": "factual_lookup",
                    "confidence": 0.85,
                    "reasoning": "Factual lookup pattern detected",
                    "suggested_tool": "vector_search" if has_unstructured else "sql_analysis",
                    "routing_hints": self._generate_routing_hints("factual_lookup", has_structured, has_unstructured),
                    "method": "rules"
                }
            elif isinstance(kw, str) and kw.startswith('r\''):
                # This is a regex pattern - skip for now
                pass

        # Check for conceptual intent
        if any(kw in query_lower for kw in conceptual_keywords):
            return {
                "intent": "conceptual",
                "confidence": 0.8,
                "reasoning": "Conceptual/explanation keywords detected",
                "suggested_tool": "vector_search",
                "routing_hints": self._generate_routing_hints("conceptual", has_structured, has_unstructured),
                "method": "rules"
            }

        # Default to conceptual for unstructured, factual for structured
        if has_unstructured:
            return {
                "intent": "conceptual",
                "confidence": 0.5,
                "reasoning": "Default classification (unstructured documents available)",
                "suggested_tool": "vector_search",
                "routing_hints": self._generate_routing_hints("conceptual", has_structured, has_unstructured),
                "method": "rules"
            }
        else:
            return {
                "intent": "factual_lookup",
                "confidence": 0.5,
                "reasoning": "Default classification (structured documents only)",
                "suggested_tool": "sql_analysis",
                "routing_hints": self._generate_routing_hints("factual_lookup", has_structured, has_unstructured),
                "method": "rules"
            }

    def _generate_routing_hints(
        self,
        intent: str,
        has_structured: bool,
        has_unstructured: bool
    ) -> Dict[str, Any]:
        """
        Generate routing hints based on intent and available document types.

        Feature #229: For listing queries, use much higher top_k (50) to retrieve
        comprehensive results instead of just a few highly-similar chunks.
        """
        # Feature #229: Determine top_k based on intent
        if intent == "listing":
            top_k = 50  # Retrieve many chunks for comprehensive listings
        elif intent == "conceptual":
            top_k = 5
        else:
            top_k = 3

        hints = {
            "prefer_exact_match": intent == "factual_lookup",
            "use_reranking": intent in ["conceptual", "comparison", "listing"],
            "top_k": top_k,
            "similarity_threshold": 0.3 if intent == "factual_lookup" else 0.2
        }

        if intent == "calculation" and has_structured:
            hints["use_sql"] = True
            hints["aggregation_likely"] = True
        elif intent == "comparison":
            hints["multi_document"] = True
            hints["comparison_mode"] = True
            hints["top_k"] = 10  # Retrieve more chunks to cover multiple documents
        elif intent == "factual_lookup":
            hints["prefer_exact_match"] = True
            hints["extract_specific_value"] = True
        elif intent == "listing":
            # Feature #229: For listing queries, lower similarity threshold
            # to capture more diverse results
            # Feature #232: Use configured min_relevance_threshold instead of hardcoded value
            hints["similarity_threshold"] = float(settings_store.get('min_relevance_threshold', 0.1))
            hints["listing_mode"] = True

        return hints

    def _preprocess_query_for_semantic_search(self, query: str) -> str:
        """
        Feature #211: Preprocess queries for better semantic search.

        Imperative phrases like "dammi una ricetta con il pollo" (give me a recipe with chicken)
        have low semantic similarity with document content because the embedding captures
        the intent verb rather than the actual content being searched for.

        This method:
        1. Removes imperative verbs that don't contribute to semantic matching
        2. Removes filler words like "una", "un", "the", etc.
        3. Preserves the core content that should match document text

        Examples:
        - "dammi una ricetta con il pollo" → "ricetta pollo" (recipe chicken)
        - "show me documents about GMDSS" → "documents GMDSS"
        - "elenca tutti i prodotti" → "prodotti" (products)
        - "give me information about safety" → "information safety"
        """
        if not query or not query.strip():
            return query

        query_lower = query.lower().strip()
        processed = query_lower

        # Step 1: Remove imperative verb phrases (multilingual)
        # These patterns match at the start of the query
        imperative_patterns = [
            # Italian imperative patterns (with optional articles/prepositions)
            r'^dammi\s+(una?\s+)?',
            r'^dimmi\s+(una?\s+)?',
            r'^fammi\s+vedere\s+(una?\s+)?',
            r'^fammi\s+sapere\s+(una?\s+)?',
            r'^fammi\s+(una?\s+)?',
            r'^cercami\s+(una?\s+)?',
            r'^trovami\s+(una?\s+)?',
            r'^mostrami\s+(una?\s+)?',
            r'^elencami\s+(una?\s+)?',
            r'^descrivimi\s+(una?\s+)?',
            r'^spiegami\s+(una?\s+)?',
            r'^riassumimi\s+(una?\s+)?',
            r'^parlami\s+(di\s+)?',
            r'^elenca\s+(tutti\s+)?',
            r'^mostra\s+(tutti\s+)?',
            r'^cerca\s+',
            r'^trova\s+',
            r'^spiega\s+',
            r'^descrivi\s+',
            r'^riassumi\s+',
            # English imperative patterns
            r'^give\s+me\s+(a\s+|an\s+|the\s+|some\s+)?',
            r'^show\s+me\s+(a\s+|an\s+|the\s+|some\s+)?',
            r'^tell\s+me\s+(about\s+)?(a\s+|an\s+|the\s+)?',
            r'^find\s+(me\s+)?(a\s+|an\s+|the\s+|some\s+)?',
            r'^search\s+(for\s+)?(a\s+|an\s+|the\s+)?',
            r'^get\s+(me\s+)?(a\s+|an\s+|the\s+|some\s+)?',
            r'^list\s+(all\s+)?(the\s+)?',
            r'^explain\s+(to\s+me\s+)?',
            r'^describe\s+(to\s+me\s+)?',
            r'^summarize\s+(the\s+)?',
            # Spanish imperative patterns
            r'^dame\s+(una?\s+)?',
            r'^dime\s+(una?\s+)?',
            r'^muéstrame\s+(una?\s+)?',
            r'^busca\s+(una?\s+)?',
            r'^encuentra\s+(una?\s+)?',
            r'^lista\s+(todos?\s+)?',
            r'^enumera\s+(todos?\s+)?',
            r'^explica\s+',
            r'^describe\s+',
            r'^resume\s+',
            # French imperative patterns
            r'^donne-moi\s+(une?\s+)?',
            r'^dis-moi\s+(une?\s+)?',
            r'^montre-moi\s+(une?\s+)?',
            r'^cherche\s+(une?\s+)?',
            r'^trouve\s+(une?\s+)?',
            r'^liste\s+(tous?\s+)?',
            r'^explique\s+',
            r'^décris\s+',
            r'^résume\s+',
            # German imperative patterns
            r'^gib\s+mir\s+(eine?n?\s+)?',
            r'^sag\s+mir\s+(eine?n?\s+)?',
            r'^zeig\s+mir\s+(eine?n?\s+)?',
            r'^such\s+(mir\s+)?(eine?n?\s+)?',
            r'^finde\s+(mir\s+)?(eine?n?\s+)?',
            r'^liste\s+(alle\s+)?',
            r'^erkläre\s+',
            r'^beschreibe\s+',
            r'^fasse\s+zusammen\s+',
            # Portuguese imperative patterns
            r'^me\s+dê\s+(uma?\s+)?',
            r'^me\s+diga\s+(uma?\s+)?',
            r'^me\s+mostre\s+(uma?\s+)?',
            r'^procure\s+(uma?\s+)?',
            r'^encontre\s+(uma?\s+)?',
            r'^liste\s+(todos?\s+)?',
            r'^explique\s+',
            r'^descreva\s+',
            r'^resuma\s+',
        ]

        for pattern in imperative_patterns:
            processed = re.sub(pattern, '', processed, flags=re.IGNORECASE)

        # Step 2: Remove common filler words that don't contribute to semantic matching
        # Only remove these if they're surrounded by spaces or at word boundaries
        filler_patterns = [
            # Italian articles and prepositions
            r'\b(il|lo|la|i|gli|le|un|uno|una)\b',
            r'\b(con|del|della|dei|delle|nel|nella|nei|nelle|sul|sulla)\b',
            r'\b(per|che|di|a|da)\b',
            # English articles and common words
            r'\b(the|a|an|some|any|about|for|with|on|in|at|to)\b',
            # Spanish articles
            r'\b(el|la|los|las|un|una|unos|unas|con|del|de|en|para)\b',
            # French articles
            r'\b(le|la|les|un|une|des|du|de|dans|pour|avec|sur)\b',
            # German articles
            r'\b(der|die|das|ein|eine|einen|einem|mit|in|auf|für)\b',
            # Portuguese articles
            r'\b(o|a|os|as|um|uma|uns|umas|com|do|da|dos|das|em|para)\b',
        ]

        for pattern in filler_patterns:
            processed = re.sub(pattern, ' ', processed, flags=re.IGNORECASE)

        # Step 3: Clean up extra whitespace
        processed = re.sub(r'\s+', ' ', processed).strip()

        # Step 4: If the result is too short or empty, return original query
        # (to avoid over-aggressive stripping)
        if len(processed) < 3:
            logger.info(f"[Feature #211] Query preprocessing result too short, using original: '{query}'")
            return query

        # Step 5 (Feature #220): Expand with synonyms for better semantic matching
        processed = self._expand_query_with_synonyms(processed)

        # Log the transformation for debugging
        if processed != query_lower:
            logger.info(f"[Feature #211/#220] Query preprocessed and expanded: '{query}' → '{processed}'")

        return processed

    def _expand_query_with_synonyms(self, query: str) -> str:
        """
        Feature #220: Expand query with synonyms and related terms for better vector matching.
        Feature #244: Limit synonym expansion for short queries to prevent irrelevant terms.

        This helps when the user's query uses different words than what appears in documents.
        E.g., "ricetta pollo" might match better as "ricetta pollo ingredienti preparazione"

        Short query protection (Feature #244):
        - Queries ≤4 tokens get NO synonym expansion to avoid noise
        - Synonyms are limited to the same semantic domain
        - Category-broadening terms are blacklisted

        Returns the expanded query with additional relevant terms.
        """
        query_lower = query.lower()
        words = query_lower.split()
        token_count = len(words)

        # [Feature #244] SHORT QUERY PROTECTION: Skip synonym expansion for queries ≤4 tokens
        # Short queries like "hummus pesche" should NOT be expanded with unrelated terms
        max_tokens_for_expansion = 4
        if token_count <= max_tokens_for_expansion:
            logger.info(f"[Feature #244] Query too short ({token_count} tokens), skipping synonym expansion: '{query}'")
            return query

        expansions = []

        # [Feature #285] Use module-level constant for max synonyms per word
        # This limits synonym expansion to prevent query explosion
        # (Previously was 2, now configurable via MAX_SYNONYMS_PER_WORD = 3)

        # [Feature #244] BLACKLIST: Category-broadening terms that introduce noise
        # These are too generic and will match unrelated documents
        blacklisted_synonyms = {
            'torta', 'dolce', 'dessert', 'piatto', 'pasto', 'cibo',  # Italian
            'cake', 'sweet', 'dish', 'meal', 'food',  # English
            'gâteau', 'plat', 'repas',  # French
            'kuchen', 'gericht', 'mahlzeit',  # German
            'pastel', 'plato', 'comida',  # Spanish
        }

        # [Feature #244] DOMAIN DETECTION: Group terms by semantic domain
        # Only add synonyms from the same domain as detected in query
        food_domain_terms = {
            # Italian
            'ricetta', 'ricette', 'pollo', 'pesce', 'verdure', 'pasta', 'dolce',
            'cena', 'cucinare', 'ingredienti', 'preparazione', 'carne', 'cipolla',
            'pomodoro', 'aglio', 'formaggio', 'olio', 'sale', 'zucchero',
            'hummus', 'pesche', 'frutta', 'verdura', 'uova', 'latte', 'burro',
            # English
            'recipe', 'recipes', 'chicken', 'fish', 'vegetables', 'pasta',
            'dinner', 'cook', 'ingredients', 'preparation', 'meat', 'onion',
            'tomato', 'garlic', 'cheese', 'oil', 'salt', 'sugar',
        }

        business_domain_terms = {
            # Italian
            'prezzo', 'costo', 'prodotto', 'prodotti', 'listino', 'catalogo',
            'caratteristiche', 'manuale', 'installazione', 'modello',
            # English
            'price', 'cost', 'product', 'products', 'catalog', 'pricing',
            'features', 'manual', 'installation', 'model', 'safety',
        }

        # Detect query domain
        query_is_food_domain = any(term in words for term in food_domain_terms)
        query_is_business_domain = any(term in words for term in business_domain_terms)

        # Define synonym mappings with domain tags
        # [Feature #244] Reorganized with domain awareness
        synonym_map_food = {
            # Italian food/recipe terms - restricted to avoid category broadening
            'ricetta': ['preparazione', 'ingredienti'],
            'ricette': ['preparazione', 'ingredienti'],
            'veloce': ['rapida', 'minuti'],  # Removed 'facile' - too broad
            'velocemente': ['rapidamente'],  # Reduced
            'pollo': ['carne', 'petto'],
            'pesce': ['filetto'],  # Removed 'frutti di mare' - too broad
            'verdure': ['vegetali', 'ortaggi'],
            'pasta': ['spaghetti', 'penne'],  # Removed 'primo' - too broad
            # 'dolce': removed - too category-broadening
            'cena': ['pranzo'],  # Reduced
            'cucinare': ['preparare', 'cottura'],
            # English food terms
            'recipe': ['ingredients', 'preparation'],
            'recipes': ['ingredients'],  # Reduced
            'quick': ['fast', 'minutes'],  # Removed 'easy' - too broad
            'chicken': ['poultry'],  # Reduced, removed 'meat' - too broad
        }

        synonym_map_business = {
            # Italian business/technical terms
            'prezzo': ['costo', 'listino'],
            'costo': ['prezzo', 'importo'],
            'prodotto': ['articolo', 'modello'],
            'prodotti': ['catalogo', 'articoli'],
            'caratteristiche': ['specifiche', 'funzionalità'],
            'manuale': ['guida', 'istruzioni'],
            'installazione': ['setup', 'configurazione'],
            # English business terms
            'price': ['cost', 'pricing'],
            'cost': ['price', 'amount'],
            'product': ['item', 'model'],
            'products': ['catalog', 'items'],
            'features': ['specifications', 'capabilities'],
            'manual': ['guide', 'instructions'],
            'installation': ['setup', 'configuration'],
            'safety': ['security', 'protection'],
        }

        # Multilingual additions (Spanish, French, German) - condensed
        synonym_map_multilingual = {
            'receta': ['ingredientes'],
            'precio': ['costo'],
            'producto': ['artículo'],
            'recette': ['ingrédients'],
            'prix': ['coût'],
            'produit': ['article'],
            'rezept': ['zutaten'],
            'preis': ['kosten'],
            'produkt': ['artikel'],
        }

        # [Feature #244] Select appropriate synonym map based on domain
        if query_is_food_domain and not query_is_business_domain:
            active_synonym_maps = [synonym_map_food, synonym_map_multilingual]
            logger.info(f"[Feature #244] Detected food domain, using food synonyms only")
        elif query_is_business_domain and not query_is_food_domain:
            active_synonym_maps = [synonym_map_business, synonym_map_multilingual]
            logger.info(f"[Feature #244] Detected business domain, using business synonyms only")
        else:
            # Mixed or unknown domain - use both but more conservatively
            active_synonym_maps = [synonym_map_food, synonym_map_business, synonym_map_multilingual]

        # Collect expansions for words in the query
        added_terms = set()
        for word in words:
            synonyms_added_for_word = 0
            word_had_more_synonyms = False  # Track if truncation occurred
            total_available_synonyms = 0  # Count available synonyms before limiting

            for synonym_map in active_synonym_maps:
                if word in synonym_map:
                    # [Feature #285] Count total available synonyms for this word
                    available_in_map = [s for s in synonym_map[word]
                                       if s.lower() not in blacklisted_synonyms
                                       and s.lower() not in query_lower
                                       and s.lower() not in added_terms]
                    total_available_synonyms += len(available_in_map)

                    for synonym in synonym_map[word]:
                        # [Feature #244] Skip blacklisted category-broadening terms
                        if synonym.lower() in blacklisted_synonyms:
                            logger.debug(f"[Feature #244] Skipping blacklisted synonym: '{synonym}'")
                            continue
                        # Don't add if already in query or already added
                        if synonym.lower() not in query_lower and synonym.lower() not in added_terms:
                            expansions.append(synonym)
                            added_terms.add(synonym.lower())
                            synonyms_added_for_word += 1
                            # [Feature #285] Limit synonyms per word using module constant
                            if synonyms_added_for_word >= MAX_SYNONYMS_PER_WORD:
                                word_had_more_synonyms = True
                                break
                    if synonyms_added_for_word >= MAX_SYNONYMS_PER_WORD:
                        break

            # [Feature #285] Log when synonyms are truncated for a word
            if word_had_more_synonyms and total_available_synonyms > MAX_SYNONYMS_PER_WORD:
                logger.info(f"[Feature #285] Synonym truncation for '{word}': {total_available_synonyms} available, limited to {MAX_SYNONYMS_PER_WORD}")

        # Limit total expansions to prevent overly long queries
        max_total_expansions = 6  # Increased slightly since per-word limit is now 3
        if len(expansions) > max_total_expansions:
            logger.info(f"[Feature #285] Total expansion truncation: {len(expansions)} synonyms, limited to {max_total_expansions}")
            expansions = expansions[:max_total_expansions]

        if expansions:
            expanded = query + ' ' + ' '.join(expansions)
            logger.info(f"[Feature #220/#244] Query expanded with synonyms: '{query}' → '{expanded}'")
            return expanded

        return query

    def _rewrite_query_with_context(self, query: str, messages: List[Dict[str, str]]) -> str:
        """
        Feature #344, #345: Conversational Query Rewriting for RAG context.

        Rewrites a user query by resolving pronouns and references using conversation history.
        This enables follow-up questions like "Quali sono i suoi componenti?" to be rewritten
        as "Quali sono i componenti del sistema GMDSS?" when the previous conversation
        was about GMDSS.

        Feature #345 extends this to also detect:
        - Follow-up phrases like "dimmi di più", "continua", "tell me more", "what about"
        - Short queries (1-2 significant words) that likely need context
        - Queries starting with conjunctions ("e", "and", "but")

        Args:
            query: The current user query that may contain pronouns/references
            messages: List of message dictionaries with 'role' and 'content' representing
                     the conversation history

        Returns:
            Rewritten query with pronouns and references resolved, or original query if
            rewriting is disabled or fails
        """
        # Check if conversational rewriting is enabled (default: True)
        enable_conversational_rewrite = settings_store.get('enable_conversational_rewrite', True)
        if not enable_conversational_rewrite:
            logger.info("[Feature #344] Conversational query rewriting disabled")
            return query

        # Need at least 2 messages (previous context + current query) to rewrite
        if not messages or len(messages) < 2:
            logger.info("[Feature #344] Not enough conversation history for rewriting")
            return query

        # Check for pronouns or references that need resolution
        # Common pronouns and references in Italian and English
        pronouns_and_refs = {
            # Italian pronouns and references
            'lui', 'lei', 'loro', 'esso', 'essa', 'essi', 'esse',
            'lo', 'la', 'li', 'le', 'gli', 'ne',
            'suo', 'sua', 'suoi', 'sue',
            'questo', 'questa', 'questi', 'queste',
            'quello', 'quella', 'quelli', 'quelle',
            'ciò', 'ció',
            # English pronouns and references
            'it', 'its', 'they', 'them', 'their', 'theirs',
            'this', 'that', 'these', 'those',
            'he', 'him', 'his', 'she', 'her', 'hers',
            # Common reference phrases
            'stesso', 'stessa', 'stessi', 'stesse',  # same (Italian)
            'precedente', 'sopra', 'suddetto',  # previous, above (Italian)
            'previous', 'above', 'aforementioned', 'same'  # English
        }

        query_lower = query.lower()  # Feature #346: Define early for use in all pattern checks
        query_words = set(query_lower.split())
        has_pronouns = bool(query_words & pronouns_and_refs)

        # Also check for implicit references (questions without explicit subject)
        # Feature #346: Extended patterns for better implicit follow-up detection
        implicit_question_patterns = [
            'quali sono',  # Italian: "what are" (often needs context)
            'com\'è', 'come è',  # Italian: "how is"
            'dove si trova', 'dov\'è',  # Italian: "where is"
            'quando', 'perché', 'why is', 'where is', 'how is',
            'what are', 'what is',
        ]
        has_implicit_ref = any(pattern in query_lower for pattern in implicit_question_patterns)

        # Feature #346: Detect generic questions that are missing an explicit object/subject
        # These are syntactically complete but semantically incomplete without context
        # Examples: "Come funziona?" "Quali sono i requisiti?" "Cosa dice?"
        generic_question_patterns = [
            # Italian generic questions (question word + verb, needs object)
            r'^come funziona\??$',  # "How does it work?" - missing subject
            r'^come funzionano\??$',  # "How do they work?" - missing subject
            r'^quali sono\??$',  # "What are they?" - missing subject
            r'^quali sono i requisiti\??$',  # "What are the requirements?" - for what?
            r'^quali certificati servono\??$',  # "What certificates are needed?" - for what?
            r'^cosa dice\??$',  # "What does it say?" - missing subject
            r'^cosa dicono\??$',  # "What do they say?" - missing subject
            r'^cosa prevede\??$',  # "What does it provide?" - missing subject
            r'^a cosa serve\??$',  # "What is it for?" - missing subject
            r'^quanto costa\??$',  # "How much does it cost?" - missing subject
            r'^quando si usa\??$',  # "When do you use it?" - missing subject
            r'^dove si trova\??$',  # "Where is it located?" - missing subject
            r'^perché serve\??$',  # "Why is it needed?" - missing subject
            # English generic questions
            r'^how does it work\??$',
            r'^how do they work\??$',
            r'^what are they\??$',
            r'^what does it say\??$',
            r'^what is it for\??$',
            r'^how much does it cost\??$',
            r'^when do you use it\??$',
            r'^where is it\??$',
            r'^why is it needed\??$',
        ]
        # Note: 're' is already imported at top of file (line 14)
        has_generic_question = any(re.match(pattern, query_lower.strip()) for pattern in generic_question_patterns)

        # Feature #345: Check for follow-up phrases that require conversation context
        # These are common phrases that refer back to the previous conversation topic
        followup_phrase_patterns = [
            # Italian follow-up phrases
            'dimmi di più',  # tell me more
            'dimmi di piu',  # tell me more (without accent)
            'continua',  # continue
            'vai avanti',  # go ahead
            'prosegui',  # proceed
            'e riguardo a',  # and what about
            'e riguardo',  # and regarding
            'e per quanto riguarda',  # and as for
            'parlami ancora',  # tell me more about
            'approfondisci',  # elaborate
            'più dettagli',  # more details
            'piu dettagli',  # more details (without accent)
            'altri dettagli',  # other details
            'cosa altro',  # what else
            'cos\'altro',  # what else (contracted)
            'e poi',  # and then
            'inoltre',  # furthermore
            'altro',  # anything else
            # English follow-up phrases
            'tell me more',  # common follow-up
            'more about',  # wants more info
            'go on',  # continue
            'continue',  # continue
            'elaborate',  # elaborate
            'more details',  # more details
            'what about',  # what about X?
            'and what about',  # and what about X?
            'what else',  # what else
            'anything else',  # anything else
            'and then',  # and then
            'furthermore',  # furthermore
            'can you explain',  # can you explain more
            'explain more',  # explain more
        ]
        # Note: query_lower already defined at the beginning of this function
        has_followup_phrase = any(pattern in query_lower for pattern in followup_phrase_patterns)

        # Feature #345/#346: Check for short queries that likely need context
        # Feature #346: Improved heuristic - queries with < 6 words without explicit noun subject
        stopwords_for_short_check = {
            'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una', 'di', 'da', 'a', 'in', 'con', 'su', 'per',
            'the', 'a', 'an', 'of', 'to', 'for', 'in', 'on', 'at', 'with', 'and', 'or', 'but',
            # Feature #346: Add question words as stopwords for content word counting
            'come', 'cosa', 'quale', 'quali', 'quando', 'dove', 'perché', 'chi',
            'what', 'which', 'when', 'where', 'why', 'who', 'how'
        }
        query_words_for_count = [w for w in query_lower.split() if w not in stopwords_for_short_check and len(w) > 1]

        # Feature #346: Two-tier short query detection
        # - Very short (<=2 content words): always needs context
        # - Medium short (<6 words total AND <=4 content words AND ends with ?): likely needs context
        is_very_short_query = len(query_words_for_count) <= 2
        total_words = len(query_lower.split())
        is_medium_short_question = (
            total_words < 6 and
            len(query_words_for_count) <= 4 and
            query.strip().endswith('?')
        )
        is_short_query = is_very_short_query or is_medium_short_question

        # Feature #345: Check if query starts with a conjunction (likely a follow-up)
        conjunction_starters = ['e ', 'ed ', 'ma ', 'però ', 'and ', 'but ', 'also ', 'or ']
        starts_with_conjunction = any(query_lower.startswith(conj) for conj in conjunction_starters)

        # Feature #346: Additional check - query ends with '?' and has fewer than 4 content words
        is_question_without_subject = (
            query.strip().endswith('?') and
            len(query_words_for_count) < 4 and
            not has_pronouns and  # If has pronouns, already covered
            not has_implicit_ref  # If has implicit ref patterns, already covered
        )

        # Determine if rewriting is needed based on all context-dependency indicators
        # Feature #346: Include has_generic_question and is_question_without_subject
        needs_rewrite = (
            has_pronouns or
            has_implicit_ref or
            has_followup_phrase or
            starts_with_conjunction or
            has_generic_question or  # Feature #346
            is_question_without_subject  # Feature #346
        )

        # For short queries, also check if they need context (only when there IS conversation history)
        if is_short_query and len(messages) >= 2 and not needs_rewrite:
            # Short queries with conversation history might benefit from context
            # Log this case for monitoring
            logger.info(f"[Feature #346] Short query detected ({len(query_words_for_count)} content words, {total_words} total): '{query}' - will attempt context-aware rewriting")
            needs_rewrite = True

        # If no context-dependency indicators found, no need to rewrite
        if not needs_rewrite:
            logger.info(f"[Feature #346] No context-dependent patterns found in query: '{query[:50]}...'")
            return query

        # Log which pattern triggered the rewrite
        # Feature #346: Extended logging with new detection types
        triggered_by = []
        if has_pronouns:
            triggered_by.append("pronouns")
        if has_implicit_ref:
            triggered_by.append("implicit_question")
        if has_followup_phrase:
            triggered_by.append("followup_phrase")
        if starts_with_conjunction:
            triggered_by.append("conjunction_start")
        if has_generic_question:
            triggered_by.append("generic_question")  # Feature #346
        if is_question_without_subject:
            triggered_by.append("question_without_subject")  # Feature #346
        if is_short_query:
            triggered_by.append("short_query")
        logger.info(f"[Feature #346] Context-aware rewriting triggered by: {', '.join(triggered_by)}")

        # Extract last 3-5 messages as context (configurable)
        max_context_messages = 5
        context_messages = messages[-(max_context_messages + 1):-1]  # Exclude current query

        if not context_messages:
            logger.info("[Feature #344] No previous messages to use as context")
            return query

        # Build context string for LLM
        context_parts = []
        for msg in context_messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            if content:
                # Truncate long messages
                truncated = content[:500] + '...' if len(content) > 500 else content
                context_parts.append(f"{role.upper()}: {truncated}")

        conversation_context = "\n".join(context_parts)

        # Get API key for LLM call
        api_key = settings_store.get('openai_api_key')

        # Build the prompt for query rewriting
        # Feature #345: Enhanced prompt with follow-up phrase examples
        prompt = """Sei un sistema di riscrittura query per un assistente RAG conversazionale.
Il tuo compito è riscrivere la query dell'utente risolvendo pronomi, riferimenti e frasi di follow-up usando il contesto della conversazione.

REGOLE:
1. Identifica a cosa si riferiscono pronomi come "suo", "suoi", "it", "its", "this", "quello", ecc.
2. Sostituisci i pronomi con i termini specifici dal contesto della conversazione
3. Se la domanda è implicita (es. "Quali sono i componenti?"), aggiungi il soggetto dal contesto
4. Per frasi di follow-up come "dimmi di più", "continua", "tell me more", espandi con il topic dal contesto
5. NON aggiungere informazioni non presenti nel contesto
6. NON rispondere alla domanda - riscrivila solo per chiarirla
7. Mantieni la stessa lingua dell'utente (italiano o inglese)
8. Rispondi SOLO con la query riscritta, niente altro

ESEMPI - Pronomi:
Contesto: "USER: Cos'è il GMDSS? ASSISTANT: Il GMDSS è il Global Maritime Distress and Safety System..."
Query: "Quali sono i suoi componenti?"
Riscritta: "Quali sono i componenti del sistema GMDSS?"

Contesto: "USER: Tell me about Python. ASSISTANT: Python is a programming language..."
Query: "What are its main features?"
Riscritta: "What are the main features of Python?"

ESEMPI - Frasi di follow-up (Feature #345):
Contesto: "USER: Parlami del GMDSS. ASSISTANT: Il GMDSS è il sistema..."
Query: "Dimmi di più"
Riscritta: "Dammi più dettagli sul GMDSS (Global Maritime Distress and Safety System)"

Contesto: "USER: What is machine learning? ASSISTANT: Machine learning is..."
Query: "Tell me more"
Riscritta: "Tell me more about machine learning and its applications"

Contesto: "USER: Parlami del Navigat 100. ASSISTANT: Il Navigat 100 è un sistema di navigazione..."
Query: "Continua"
Riscritta: "Continua a parlarmi del sistema di navigazione Navigat 100"

Contesto: "USER: Explain neural networks. ASSISTANT: Neural networks are..."
Query: "And what about training?"
Riscritta: "What about training neural networks? How does the training process work?"

Contesto: "USER: Cos'è il radar? ASSISTANT: Il radar è un sistema..."
Query: "E riguardo alla portata?"
Riscritta: "Qual è la portata del radar e come funziona?"

ESEMPI - Query brevi:
Contesto: "USER: Parlami della bussola giroscopica. ASSISTANT: La bussola giroscopica..."
Query: "Funzionamento?"
Riscritta: "Come funziona la bussola giroscopica?"

ESEMPI - Domande generiche senza oggetto (Feature #346):
Contesto: "USER: Parlami del GMDSS. ASSISTANT: Il GMDSS è il Global Maritime Distress and Safety System..."
Query: "Quali certificati servono?"
Riscritta: "Quali certificati servono per il GMDSS?"

Contesto: "USER: Cos'è il radar? ASSISTANT: Il radar è un sistema di rilevamento..."
Query: "Come funziona?"
Riscritta: "Come funziona il radar?"

Contesto: "USER: Parlami delle ricette vegetariane. ASSISTANT: Le ricette vegetariane sono..."
Query: "E quelle vegane?"
Riscritta: "E per quanto riguarda le ricette vegane?"

Contesto: "USER: Tell me about SSL certificates. ASSISTANT: SSL certificates are..."
Query: "How much do they cost?"
Riscritta: "How much do SSL certificates cost?"

Contesto: "USER: Parlami del Navigat 100. ASSISTANT: Il Navigat 100 è un sistema..."
Query: "E per le barche piccole?"
Riscritta: "Il Navigat 100 è adatto per le barche piccole?"

Se la query è già completa e autonoma, restituiscila INVARIATA.

CONTESTO CONVERSAZIONE:
{context}

QUERY DA RISCRIVERE: {query}

QUERY RISCRITTA:"""

        formatted_prompt = prompt.format(context=conversation_context, query=query)

        # Helper function to process LLM response
        def process_rewrite_response(rewritten: str, provider: str) -> str:
            # Safety checks
            if not rewritten or len(rewritten) < 2:
                logger.warning(f"[Feature #345] {provider} returned empty result, using original query")
                return query

            # Clean up the response - remove quotes if present
            rewritten = rewritten.strip().strip('"').strip("'")

            # If the rewritten query is same as original (LLM decided no change needed)
            if rewritten.lower() == query.lower():
                logger.info(f"[Feature #345] {provider} determined no rewriting needed for: '{query[:50]}...'")
                return query

            logger.info(f"[Feature #345] Query rewritten with context via {provider}: '{query}' → '{rewritten}'")
            return rewritten

        # Try OpenAI first if available
        if api_key:
            try:
                from openai import OpenAI, AuthenticationError
                client = OpenAI(api_key=api_key)

                # Use a fast, cheap model for query rewriting
                rewrite_model = 'gpt-4o-mini'

                response = client.chat.completions.create(
                    model=rewrite_model,
                    messages=[
                        {"role": "user", "content": formatted_prompt}
                    ],
                    max_tokens=200,
                    temperature=0  # Deterministic output
                )

                rewritten = response.choices[0].message.content.strip()
                return process_rewrite_response(rewritten, "OpenAI")

            except AuthenticationError as e:
                logger.warning(f"[Feature #344] OpenAI API key invalid (401) - trying Ollama fallback")
            except Exception as e:
                logger.warning(f"[Feature #344] OpenAI query rewriting failed: {e} - trying Ollama fallback")

        # Fallback to Ollama if OpenAI fails or not available
        try:
            import httpx
            # Get the configured LLM model - prefer a fast model for rewriting
            llm_model = settings_store.get('llm_model') or 'llama3.2:latest'

            # If it's an ollama model, extract the model name
            if llm_model.startswith('ollama:'):
                ollama_model = llm_model[7:]  # Remove 'ollama:' prefix
            elif llm_model.startswith('openai:') or llm_model.startswith('openrouter:'):
                # Can't use non-Ollama models as fallback, use default
                ollama_model = 'llama3.2:latest'
            else:
                ollama_model = llm_model

            logger.info(f"[Feature #344] Using Ollama model '{ollama_model}' for query rewriting")

            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": ollama_model,
                        "prompt": formatted_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0,
                            "num_predict": 200
                        }
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    rewritten = result.get("response", "").strip()
                    return process_rewrite_response(rewritten, "Ollama")
                else:
                    logger.warning(f"[Feature #344] Ollama rewriting failed with status {response.status_code}")
                    return query

        except Exception as e:
            logger.warning(f"[Feature #344] Ollama query rewriting failed: {e}, using original query")
            return query

    def _reformulate_query_with_llm(self, query: str) -> str:
        """
        Feature #216: Use LLM to reformulate queries for better semantic search.

        Transforms imperative commands into keyword-focused queries:
        - "dammi una ricetta con il pollo" → "ricetta pollo"
        - "trovami il prezzo del Navigat" → "prezzo Navigat"

        This is more intelligent than rule-based preprocessing as it understands
        context and extracts the most semantically relevant terms.

        Args:
            query: The original user query

        Returns:
            Reformulated query optimized for semantic search
        """
        # Check if LLM reformulation is enabled (default: True for better search)
        enable_llm_reformulation = settings_store.get('enable_query_reformulation', True)
        if not enable_llm_reformulation:
            logger.info("[Feature #216] LLM query reformulation disabled, using rule-based preprocessing")
            return self._preprocess_query_for_semantic_search(query)

        # [Feature #244] SHORT QUERY OPTIMIZATION: For very short queries (≤2 significant words),
        # skip LLM reformulation entirely and use the query as-is (just cleaned up).
        # This saves API calls and prevents the LLM from adding irrelevant terms.
        # Count significant words (exclude common articles/prepositions)
        stopwords = {'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una', 'con', 'del', 'della',
                     'the', 'a', 'an', 'with', 'of', 'to', 'for', 'in', 'on', 'at'}
        words = query.lower().split()
        significant_words = [w for w in words if w not in stopwords and len(w) > 1]

        if len(significant_words) <= 2:
            # For very short queries, just return cleaned-up version without LLM call
            cleaned = ' '.join(significant_words)
            logger.info(f"[Feature #244] Short query ({len(significant_words)} significant words), skipping LLM: '{query}' → '{cleaned}'")
            return cleaned if cleaned else query

        # [Feature #243] Skip OpenAI rewrite if disabled due to 401 error
        if self._openai_rewrite_disabled:
            # Silently use rule-based fallback - already logged once when disabled
            return self._preprocess_query_for_semantic_search(query)

        # Get the API key
        api_key = settings_store.get('openai_api_key')

        if not api_key:
            logger.warning("[Feature #216] No OpenAI API key, falling back to rule-based preprocessing")
            return self._preprocess_query_for_semantic_search(query)

        try:
            from openai import OpenAI, AuthenticationError
            client = OpenAI(api_key=api_key)

            # Use a fast, cheap model for query reformulation
            reformulation_model = 'gpt-4o-mini'  # Fast and cheap for simple task

            # Feature #220: Enhanced query reformulation with synonym expansion
            # Feature #244: Limit synonym expansion for short queries
            prompt = """Sei un sistema di reformulazione query per ricerca semantica vettoriale.
Il tuo compito è trasformare la query dell'utente in parole chiave ottimizzate per la ricerca.

REGOLE CRITICHE:
1. Rimuovi verbi imperativi (dammi, trovami, mostrami, give me, show me, find)
2. Rimuovi articoli e preposizioni non essenziali (il, la, una, con, del, the, a, with)
3. Estrai i concetti chiave per la ricerca
4. Mantieni nomi propri, codici prodotto e numeri ESATTAMENTE come scritti
5. Rispondi SOLO con le parole chiave, niente altro

REGOLE PER I SINONIMI (Feature #244):
6. Se la query ha ≤4 parole significative, NON aggiungere sinonimi - usa solo le parole chiave originali
7. Se la query ha >4 parole, puoi aggiungere max 2 sinonimi SOLO dallo stesso dominio semantico
8. MAI aggiungere questi termini generici (broadening terms): torta, dolce, dessert, piatto, pasto, cibo, cake, dish, meal, food
9. I sinonimi devono essere specifici, non generici (es: "pollo" può diventare "petto di pollo", ma NON "carne" o "cibo")
10. Max 6-8 parole totali nel risultato

ESEMPI CORRETTI:
- "hummus pesche" → "hummus pesche" (query corta, niente sinonimi)
- "ricetta pollo" → "ricetta pollo" (query corta, niente sinonimi)
- "dammi ricette con il pollo" → "ricette pollo" (rimuovi solo verbo/articoli)
- "trovami una ricetta veloce con le verdure" → "ricetta veloce verdure ortaggi" (query lunga, 1 sinonimo ok)
- "trovami il prezzo del Navigat 100" → "prezzo Navigat 100" (rimuovi verbo/articoli)
- "qual è il costo del modello ABC-123?" → "costo modello ABC-123"
- "show me documents about GMDSS safety" → "GMDSS safety"
- "elenca tutti i prodotti disponibili" → "prodotti"

ESEMPI SBAGLIATI (da evitare):
- "hummus pesche" → "hummus pesche dolce dessert torta" (NO! Non aggiungere termini generici)
- "ricetta pollo" → "ricetta pollo carne cibo piatto" (NO! Query corta + termini generici)

Query da reformulare: """

            response = client.chat.completions.create(
                model=reformulation_model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": query}
                ],
                max_tokens=100,
                temperature=0  # Deterministic output
            )

            reformulated = response.choices[0].message.content.strip()

            # Safety check: if result is empty or too short, use original
            if not reformulated or len(reformulated) < 2:
                logger.warning(f"[Feature #216] LLM returned empty result, using original query")
                return self._preprocess_query_for_semantic_search(query)

            logger.info(f"[Feature #216] Query reformulated via LLM: '{query}' → '{reformulated}'")
            return reformulated

        except AuthenticationError as e:
            # [Feature #243] Disable LLM rewrite for session after 401 error
            self._openai_rewrite_disabled = True
            logger.warning(f"[Feature #243] OpenAI API key invalid (401) - LLM query rewrite disabled, using rule-based fallback")
            return self._preprocess_query_for_semantic_search(query)
        except Exception as e:
            logger.warning(f"[Feature #216] LLM reformulation failed: {e}, falling back to rule-based")
            return self._preprocess_query_for_semantic_search(query)

    def _detect_vector_search_request(self, message: str, document_ids: Optional[List[str]] = None) -> tuple[bool, Optional[Dict[str, Any]]]:
        """
        Detect if a message is requesting information from text documents.
        Uses language-agnostic intent detection instead of hardcoded keywords.
        Returns (is_vector_search, tool_arguments) tuple.

        Args:
            message: User message to analyze
            document_ids: Optional list of document IDs to scope the search to (Feature #205)
        """
        # FEATURE #206: Force RAG when document_ids is explicitly specified
        # When user has selected specific documents, ALWAYS use RAG regardless of question pattern
        # This prevents hallucinations from imperative phrases like "dammi una ricetta", "elenca", "mostra"
        if document_ids and len(document_ids) > 0:
            # Verify the selected documents have unstructured content with embeddings
            documents = _get_documents_sync()
            selected_docs = [d for d in documents if d.id in document_ids]
            has_unstructured = any(d.document_type == "unstructured" for d in selected_docs)

            if has_unstructured:
                logger.info(f"[Feature #206] Forcing RAG due to document_ids filter: {document_ids}")
                return True, {
                    "query": message,
                    "top_k": 5,
                    "document_ids": document_ids
                }
            else:
                # Selected documents are all structured (CSV/Excel) - don't force vector search
                logger.info(f"[Feature #206] document_ids specified but no unstructured docs - using normal detection")

        # STEP 1: Exclude calculation requests (they should go to SQL tool)
        # Feature #208: But allow vector search if message mentions unstructured document context
        # Anti-hallucination fix: Only exclude if there are actually structured documents to query
        if self._contains_calculation_keywords(message):
            # Check if the message mentions unstructured document context (libro, book, PDF, etc.)
            if self._has_unstructured_document_context_words(message):
                logger.info(f"Vector search detection: Calculation keywords found but unstructured context detected (libro, book, PDF, etc.) - proceeding with RAG")
            else:
                # Anti-hallucination: Only exclude from vector search if structured documents exist
                # If we only have unstructured docs, "quanti" in "quanti estintori richiede il regolamento"
                # is a text question, not a SQL calculation request
                documents = _get_documents_sync()
                has_structured = any(d.document_type == "structured" for d in documents)
                if has_structured:
                    logger.info(f"Vector search detection: Excluded due to calculation keywords (structured docs available)")
                    return False, None
                else:
                    logger.info(f"Vector search detection: Calculation keywords found but NO structured docs - proceeding with RAG to avoid hallucination")

        # STEP 2: Check for explicit document listing requests
        if self._contains_list_documents_keywords(message):
            logger.info(f"Vector search detection: Excluded - this is a list documents request")
            return False, None

        # STEP 3: Language-agnostic question detection
        is_question = self._is_question_pattern(message)

        # STEP 3.5: Feature #282 - Classify short queries as lookup
        # Short queries without verbs (e.g., "ricette cipolla") should be treated as lookups
        query_classification = self.classify_query(message)
        is_lookup = query_classification.get("query_type") == "lookup"
        if is_lookup:
            logger.info(f"[Feature #282] Query classified as lookup: '{message[:50]}...' - {query_classification.get('reasoning')}")

        # STEP 4: Check if we have unstructured documents available
        documents = _get_documents_sync()
        # Feature #205: Filter documents if document_ids is specified
        if document_ids:
            documents = [d for d in documents if d.id in document_ids]
            logger.info(f"[Feature #205] Filtered to {len(documents)} documents based on document_ids")
        has_unstructured = any(d.document_type == "unstructured" for d in documents)
        has_embeddings = embedding_store.get_chunk_count() > 0

        logger.info(f"Vector search detection - is_question: {is_question}, is_lookup: {is_lookup}, has_unstructured: {has_unstructured}, has_embeddings: {has_embeddings}")

        # STEP 5: Detect language (optional, for logging/debugging)
        detected_lang = self._detect_language(message)
        if detected_lang:
            logger.info(f"Detected language: {detected_lang}")

        # STEP 5.5: Detect comparison/analysis intent for higher top_k
        comparison_keywords_detect = [
            'confronta', 'confronto', 'differenze', 'differenza', 'paragona',
            'compare', 'comparison', 'differences', 'difference', 'versus', 'vs',
            'rispetto a', 'compared to', 'differ', 'analizza', 'analyze',
        ]
        is_comparison_intent = any(kw in message.lower() for kw in comparison_keywords_detect)
        comparison_top_k = 10 if is_comparison_intent else 5
        if is_comparison_intent:
            logger.info(f"Comparison intent detected - using top_k={comparison_top_k}")

        # STEP 6: Decision logic
        # Feature #282: Route BOTH questions AND lookups to vector search
        # If it's a question OR lookup AND we have text documents with embeddings, use vector search
        if (is_question or is_lookup) and has_unstructured and has_embeddings:
            mode = "lookup" if is_lookup else "question"
            logger.info(f"[Feature #282] Vector search request detected: {mode} about documents")
            return True, {
                "query": message,
                "top_k": comparison_top_k,
                "document_ids": document_ids  # Feature #205: Pass document_ids filter
            }

        # STEP 7: Check for explicit document context mentions
        # Even if not a question, if they mention documents explicitly, use vector search
        if self._has_document_context_words(message) and has_unstructured and has_embeddings:
            logger.info(f"Vector search request detected: explicit document mention")
            return True, {
                "query": message,
                "top_k": comparison_top_k,
                "document_ids": document_ids  # Feature #205: Pass document_ids filter
            }

        # STEP 8 (Feature #362/#363): Default to RAG when documents with embeddings exist
        # If we have unstructured documents with embeddings and the query is NOT a
        # greeting/meta/farewell, always attempt vector search. This ensures the agent
        # consults documents first before falling back to LLM knowledge.
        if has_unstructured and has_embeddings:
            non_document_patterns = [
                r'^(hello|hi|hey|ciao|buongiorno|salve|buonasera)\b',  # Greetings
                r'(what time is it|current time|what day|che ora|che giorno)',  # Time/date
                r'(who are you|what are you|your name|chi sei|come ti chiami)',  # Meta about AI
                r'(how are you|how do you do|come stai|come va)',  # Conversational
                r'^(thank|thanks|grazie|merci|danke)\b',  # Thanks
                r'^(bye|goodbye|cya|arrivederci|addio)\b',  # Farewells
                r'^(ok|okay|va bene|capito|inteso)\s*$',  # Acknowledgments (exact match)
            ]

            message_lower = message.lower().strip()
            is_non_document = any(re.search(p, message_lower, re.IGNORECASE) for p in non_document_patterns)

            if not is_non_document:
                logger.info(f"[Feature #362/#363] Defaulting to RAG - documents with embeddings exist, query is not a greeting/meta")
                return True, {
                    "query": message,
                    "top_k": comparison_top_k,
                    "document_ids": document_ids
                }

        logger.info(f"Vector search detection: No match")
        return False, None

    def _detect_list_documents_request(self, message: str) -> bool:
        """
        Detect if a message is asking about available documents.
        Uses language-agnostic multilingual keyword detection.
        Returns True if the user wants to list/know available documents.
        """
        # Use the helper method which already has multilingual keywords
        return self._contains_list_documents_keywords(message)

    def _detect_vague_query(self, message: str) -> bool:
        """
        Feature #316: Detect vague/generic queries that don't specify what to search for.
        Feature #343: Removed 'parlami' alone to allow 'parlami del [topic]' queries.

        Vague queries like 'Parlami di tutto', 'Cosa c'è?', 'Dimmi qualcosa' should
        trigger topic suggestions instead of returning 'not found'.

        Args:
            message: User message to analyze

        Returns:
            True if the query is vague and should trigger topic suggestions
        """
        message_lower = message.lower().strip()

        # Vague query patterns (multilingual)
        vague_patterns = [
            # Italian
            "parlami di tutto", "parlami di qualcosa", "dimmi tutto",
            "dimmi qualcosa", "cosa c'è", "cosa c'è?", "cosa contiene", "cosa hai",
            "cosa sai", "raccontami", "raccontami tutto", "di cosa parli",
            "di cosa si parla", "argomenti", "temi", "contenuti",
            # English
            "tell me everything", "tell me something", "tell me about everything",
            "what is there", "what do you have", "what do you know",
            "what's in", "what's available", "what topics", "what subjects",
            "show me everything", "everything", "anything", "whatever",
            # Spanish
            "dime todo", "cuéntame todo", "qué hay", "qué tienes", "qué sabes",
            "de qué temas", "contenidos",
            # French
            "dis-moi tout", "raconte-moi tout", "qu'est-ce qu'il y a",
            "quels sujets", "quels thèmes",
            # German
            "erzähl mir alles", "was gibt es", "was hast du", "welche themen",
        ]

        # Check for exact matches or matches at the start
        for pattern in vague_patterns:
            if message_lower == pattern or message_lower.startswith(pattern):
                logger.info(f"[Feature #316] Detected vague query: '{message[:50]}...' (pattern: '{pattern}')")
                return True

        # Check for very short queries that are too generic
        word_count = len(message_lower.split())
        if word_count <= 2:
            # Check if it's a generic question word alone
            generic_starters = [
                "cosa", "what", "qué", "quoi", "was",  # what
                "tutto", "everything", "all", "todo", "tout", "alles",  # everything
                "qualcosa", "something", "algo", "quelque chose", "etwas",  # something
            ]
            if any(message_lower == word or message_lower.startswith(word + " ") or
                   message_lower.startswith(word + "?") for word in generic_starters):
                logger.info(f"[Feature #316] Detected short vague query: '{message}' (generic word)")
                return True

        return False

    def _get_available_topics(self) -> Dict[str, Any]:
        """
        Feature #316: Extract available topics/categories from indexed documents.

        Analyzes document titles, collections, and content to provide a summary
        of available topics that users can ask about.

        Returns:
            Dict with:
            - topics: List of topic strings derived from documents
            - collections: List of collection names
            - document_types: Count of document types
            - total_documents: Total document count
        """
        documents = _get_documents_sync()
        collections = _get_collections_sync()

        if not documents:
            return {
                "topics": [],
                "collections": [],
                "document_types": {"structured": 0, "unstructured": 0},
                "total_documents": 0
            }

        # Extract topics from document titles
        topics = set()
        doc_types = {"structured": 0, "unstructured": 0}

        for doc in documents:
            # Count document types
            if doc.document_type == "structured":
                doc_types["structured"] += 1
            else:
                doc_types["unstructured"] += 1

            # Extract topics from title
            title = doc.title.strip()
            if title:
                # Clean up common file extensions and prefixes
                clean_title = title
                for ext in ['.pdf', '.txt', '.docx', '.md', '.csv', '.xlsx', '.json']:
                    clean_title = clean_title.replace(ext, '')
                clean_title = clean_title.strip()

                if clean_title and len(clean_title) > 2:
                    topics.add(clean_title)

            # For structured data, add column names as potential topics
            if doc.document_type == "structured" and doc.schema_info:
                try:
                    import json
                    schema = json.loads(doc.schema_info) if isinstance(doc.schema_info, str) else doc.schema_info
                    if isinstance(schema, list):
                        # Add meaningful column names as topics
                        for col in schema:
                            if isinstance(col, str) and len(col) > 2:
                                # Skip generic column names
                                if col.lower() not in ['id', 'name', 'date', 'value', 'index', 'row']:
                                    topics.add(col.replace('_', ' ').title())
                except:
                    pass

        # Get collection names
        collection_names = [c.name for c in collections if c.name and c.name != "Uncategorized"]

        # Convert to sorted list, limit to most relevant
        topic_list = sorted(list(topics))[:15]  # Limit to 15 topics

        return {
            "topics": topic_list,
            "collections": collection_names,
            "document_types": doc_types,
            "total_documents": len(documents)
        }

    def _format_topic_suggestion_response(self, topics_data: Dict[str, Any], user_lang: str = "en") -> str:
        """
        Feature #316: Format a helpful response suggesting available topics.

        Args:
            topics_data: Dict from _get_available_topics()
            user_lang: Detected user language code

        Returns:
            Formatted string suggesting available topics
        """
        topics = topics_data.get("topics", [])
        collections = topics_data.get("collections", [])
        doc_types = topics_data.get("document_types", {})
        total = topics_data.get("total_documents", 0)

        if total == 0:
            # No documents uploaded
            messages = {
                "it": "Non hai ancora caricato nessun documento. Carica dei documenti per iniziare a fare domande!",
                "es": "Aún no has subido ningún documento. ¡Sube documentos para empezar a hacer preguntas!",
                "fr": "Vous n'avez pas encore téléchargé de documents. Téléchargez des documents pour commencer à poser des questions!",
                "de": "Sie haben noch keine Dokumente hochgeladen. Laden Sie Dokumente hoch, um Fragen zu stellen!",
            }
            return messages.get(user_lang, "You haven't uploaded any documents yet. Upload documents to start asking questions!")

        # Build response based on language
        if user_lang == "it":
            response_parts = [f"Ho **{total} documento/i** disponibili. Ecco di cosa posso parlarti:\n"]
            if topics:
                response_parts.append("\n**📚 Argomenti disponibili:**\n")
                for topic in topics[:10]:
                    response_parts.append(f"- {topic}\n")
            if collections:
                response_parts.append("\n**📁 Collezioni:**\n")
                for coll in collections[:5]:
                    response_parts.append(f"- {coll}\n")
            if doc_types.get("structured", 0) > 0:
                response_parts.append(f"\n**📊 Dati tabellari:** {doc_types['structured']} file (CSV, Excel) - puoi fare calcoli e analisi\n")
            if doc_types.get("unstructured", 0) > 0:
                response_parts.append(f"\n**📄 Documenti di testo:** {doc_types['unstructured']} file (PDF, TXT, Word)\n")
            response_parts.append("\n💡 **Suggerimento:** Prova a chiedere qualcosa di specifico come:\n")
            if topics:
                response_parts.append(f'- "Parlami di {topics[0]}"\n')
                if len(topics) > 1:
                    response_parts.append(f'- "Cosa dice il documento su {topics[1]}?"\n')
        elif user_lang == "es":
            response_parts = [f"Tengo **{total} documento(s)** disponibles. Esto es de lo que puedo hablarte:\n"]
            if topics:
                response_parts.append("\n**📚 Temas disponibles:**\n")
                for topic in topics[:10]:
                    response_parts.append(f"- {topic}\n")
            if collections:
                response_parts.append("\n**📁 Colecciones:**\n")
                for coll in collections[:5]:
                    response_parts.append(f"- {coll}\n")
            response_parts.append("\n💡 **Sugerencia:** Intenta preguntar algo específico.\n")
        elif user_lang == "fr":
            response_parts = [f"J'ai **{total} document(s)** disponibles. Voici ce dont je peux vous parler:\n"]
            if topics:
                response_parts.append("\n**📚 Sujets disponibles:**\n")
                for topic in topics[:10]:
                    response_parts.append(f"- {topic}\n")
            if collections:
                response_parts.append("\n**📁 Collections:**\n")
                for coll in collections[:5]:
                    response_parts.append(f"- {coll}\n")
            response_parts.append("\n💡 **Conseil:** Essayez de poser une question spécifique.\n")
        elif user_lang == "de":
            response_parts = [f"Ich habe **{total} Dokument(e)** verfügbar. Hier ist, worüber ich sprechen kann:\n"]
            if topics:
                response_parts.append("\n**📚 Verfügbare Themen:**\n")
                for topic in topics[:10]:
                    response_parts.append(f"- {topic}\n")
            if collections:
                response_parts.append("\n**📁 Sammlungen:**\n")
                for coll in collections[:5]:
                    response_parts.append(f"- {coll}\n")
            response_parts.append("\n💡 **Tipp:** Versuchen Sie, eine spezifische Frage zu stellen.\n")
        else:
            # English (default)
            response_parts = [f"I have **{total} document(s)** available. Here's what I can tell you about:\n"]
            if topics:
                response_parts.append("\n**📚 Available Topics:**\n")
                for topic in topics[:10]:
                    response_parts.append(f"- {topic}\n")
            if collections:
                response_parts.append("\n**📁 Collections:**\n")
                for coll in collections[:5]:
                    response_parts.append(f"- {coll}\n")
            if doc_types.get("structured", 0) > 0:
                response_parts.append(f"\n**📊 Tabular Data:** {doc_types['structured']} file(s) (CSV, Excel) - you can ask for calculations and analysis\n")
            if doc_types.get("unstructured", 0) > 0:
                response_parts.append(f"\n**📄 Text Documents:** {doc_types['unstructured']} file(s) (PDF, TXT, Word)\n")
            response_parts.append("\n💡 **Tip:** Try asking something specific like:\n")
            if topics:
                response_parts.append(f'- "Tell me about {topics[0]}"\n')
                if len(topics) > 1:
                    response_parts.append(f'- "What does the document say about {topics[1]}?"\n')

        return "".join(response_parts)

    def _detect_cross_document_request(self, message: str) -> tuple[bool, Optional[Dict[str, Any]]]:
        """
        Detect if a message is requesting a cross-document query.
        Returns (is_cross_document, tool_arguments) tuple.
        """
        message_lower = message.lower()

        # Check for cross-document keywords
        cross_doc_keywords = [
            "join", "combine", "merge", "match", "relate", "across",
            "from both", "from multiple", "from two", "between",
            "employees with departments", "departments with", "with their",
            "correlate", "compare", "link"
        ]

        is_cross_document = any(kw in message_lower for kw in cross_doc_keywords)

        if not is_cross_document:
            return False, None

        # Get available structured documents
        documents = _get_documents_sync()
        structured_docs = [d for d in documents if d.document_type == "structured"]

        if len(structured_docs) < 2:
            return False, None  # Need at least 2 datasets

        # Try to identify which documents are mentioned
        mentioned_docs = []
        for doc in structured_docs:
            if doc.title.lower() in message_lower or doc.original_filename.lower().replace('.csv', '') in message_lower:
                mentioned_docs.append(doc)

        # If less than 2 documents mentioned, use all available structured docs
        if len(mentioned_docs) < 2:
            mentioned_docs = structured_docs[:2]  # Use first 2

        dataset_ids = [doc.id for doc in mentioned_docs]

        # Try to detect join column from message or find common column
        join_column = None

        # Common join column names - ORDERED from most specific to least specific
        # to avoid "id" matching "product_id" before "product_id" is checked
        common_join_cols = ["department_id", "dept_id", "user_id", "employee_id", "product_id", "customer_id", "id"]

        # Check message for column names
        for col_name in common_join_cols:
            if col_name in message_lower:
                join_column = col_name
                break

        # If no join column found in message, find common column between datasets
        # Use PostgreSQL helper to get schemas
        if not join_column:
            schemas = []
            for doc in mentioned_docs:
                rows = _get_document_rows_sync(doc.id)
                if rows:
                    schemas.append(list(rows[0]["data"].keys()))
                else:
                    schemas.append([])
            if len(schemas) >= 2:
                # Find columns that appear in all datasets (case-insensitive)
                common_cols = set([col.lower() for col in schemas[0]])
                for schema in schemas[1:]:
                    common_cols &= set([col.lower() for col in schema])

                if common_cols:
                    # Prefer columns with "_id" or "id" in the name
                    id_cols = [col for col in common_cols if "id" in col]
                    if id_cols:
                        join_column = id_cols[0]
                    else:
                        join_column = list(common_cols)[0]

        if not join_column:
            return False, None  # Cannot determine join column

        return True, {
            "dataset_ids": dataset_ids,
            "join_column": join_column
        }

    def _detect_calculation_request(self, message: str, document_ids: Optional[List[str]] = None) -> tuple[bool, Optional[Dict[str, Any]]]:
        """
        Detect if a message is requesting a calculation on structured data.
        Uses multilingual calculation keyword detection.
        Returns (is_calculation, tool_arguments) tuple.

        Args:
            message: User message to analyze
            document_ids: Optional list of document IDs to scope the query to (Feature #205)

        Feature #208: Now checks if the context refers to unstructured documents,
        in which case RAG should be used instead of SQL.
        """
        # Use the helper method which already has multilingual calculation keywords
        if not self._contains_calculation_keywords(message):
            return False, None

        message_lower = message.lower()

        # Feature #208: Check if message mentions unstructured document context words
        # (libro, book, PDF, recipe, etc.) - these should trigger RAG, not SQL
        if self._has_unstructured_document_context_words(message):
            logger.info(f"Calculation request detection: Skipping SQL - message mentions unstructured document context (libro, book, PDF, etc.)")
            return False, None

        # Get available documents
        documents = _get_documents_sync()

        # Feature #205/208: If document_ids are specified, check if they're all unstructured
        if document_ids:
            filtered_docs = [d for d in documents if d.id in document_ids]
            if filtered_docs:
                # Check if ALL selected documents are unstructured
                all_unstructured = all(d.document_type == "unstructured" for d in filtered_docs)
                if all_unstructured:
                    logger.info(f"Calculation request detection: Skipping SQL - all selected documents ({len(filtered_docs)}) are unstructured")
                    return False, None
                # If document_ids specified, only consider structured docs from that list
                structured_docs = [d for d in filtered_docs if d.document_type == "structured"]
            else:
                structured_docs = [d for d in documents if d.document_type == "structured"]
        else:
            structured_docs = [d for d in documents if d.document_type == "structured"]

        if not structured_docs:
            return False, None

        # Use the first structured document (or try to match by name in message)
        target_doc = None
        for doc in structured_docs:
            if doc.title.lower() in message_lower or doc.original_filename.lower() in message_lower:
                target_doc = doc
                break

        if not target_doc:
            target_doc = structured_docs[0]

        # Determine operation (multilingual)
        operation = "sum"  # default

        # Average keywords (multilingual)
        if any(kw in message_lower for kw in ["average", "avg", "mean", "media", "promedio", "moyenne", "durchschnitt", "média"]):
            operation = "avg"
        # Count keywords (multilingual)
        elif any(kw in message_lower for kw in ["count", "how many", "quanti", "quante", "cuántos", "cuántas", "combien", "wie viele", "quantos", "quantas"]):
            operation = "count"
        # Minimum keywords (multilingual)
        elif any(kw in message_lower for kw in ["minimum", "min", "minimo", "mínimo"]):
            operation = "min"
        # Maximum keywords (multilingual)
        elif any(kw in message_lower for kw in ["maximum", "max", "massimo", "máximo"]):
            operation = "max"

        # Try to detect column name (use PostgreSQL query)
        rows = _get_document_rows_sync(target_doc.id)
        schema = list(rows[0]["data"].keys()) if rows else []
        column = None
        for col in schema:
            if col.lower() in message_lower:
                column = col
                break

        # If no column found but operation requires one, try to find a numeric column
        if not column and operation in ["sum", "avg", "min", "max"]:
            if rows:
                for col in schema:
                    try:
                        val = rows[0]["data"].get(col)
                        float(val)
                        column = col
                        break
                    except (ValueError, TypeError):
                        pass

        return True, {
            "dataset_id": target_doc.id,
            "operation": operation,
            "column": column
        }

    async def _chat_with_openrouter(
        self,
        messages: List[Dict[str, str]],
        model: str,
        document_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Chat using OpenRouter API (OpenAI-compatible).

        Args:
            messages: List of message dictionaries
            model: The OpenRouter model name (without 'openrouter:' prefix)
            document_ids: Optional list of document IDs to scope vector search to (Feature #205)

        Returns:
            Dict with response content and metadata
        """
        # Get OpenRouter API key
        api_key = settings_store.get('openrouter_api_key')

        if not api_key or len(api_key) < 10:
            return {
                "content": "OpenRouter API key not configured. Please add your API key in settings.",
                "tool_used": None,
                "tool_details": None,
                "response_source": "direct"
            }

        try:
            # Create OpenAI client with OpenRouter base URL
            # OpenRouter is OpenAI-compatible, so we can use the OpenAI SDK
            client = OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "http://localhost:3000",  # Required by OpenRouter
                    "X-Title": "Agentic RAG System"  # Optional but helps with rankings
                }
            )

            # Add system prompt to messages
            full_messages = [
                {"role": "system", "content": self.get_system_prompt()},
                *messages
            ]

            # Check for manual tool routing (same as OpenAI path)
            if messages:
                last_message = messages[-1].get("content", "")

                # Feature #217: Query intent classification for smarter routing
                query_classification = self._classify_query_intent(
                    last_message,
                    document_ids=document_ids,
                    use_llm=True
                )
                logger.info(f"[Feature #217] OpenRouter - Query classified as '{query_classification['intent']}' "
                           f"(confidence: {query_classification['confidence']:.2f}, "
                           f"method: {query_classification.get('method', 'unknown')}, "
                           f"suggested_tool: {query_classification['suggested_tool']})")

                # Check for list documents
                is_list_docs = self._detect_list_documents_request(last_message)
                if is_list_docs:
                    tool_result = self._execute_list_documents()
                    documents = tool_result.get("documents", [])
                    total = tool_result.get("total", 0)

                    if total == 0:
                        response_content = "You don't have any documents uploaded yet."
                    else:
                        response_parts = [f"You have **{total} document(s)** available:\n"]
                        for doc in documents:
                            title = doc.get("title", "Untitled")
                            doc_type = doc.get("type", "unknown")
                            response_parts.append(f"\n- **{title}** ({doc_type})")
                        response_content = "".join(response_parts)

                    return {
                        "content": response_content,
                        "tool_used": "list_documents",
                        "tool_details": {
                            "provider": "openrouter",
                            "model": model,
                            "tool_result": tool_result
                        },
                        "response_source": "rag"
                    }

                # Feature #316: Check for vague queries and suggest available topics
                is_vague = self._detect_vague_query(last_message)
                if is_vague:
                    topics_data = self._get_available_topics()
                    user_lang = self._detect_language(last_message) or "en"
                    response_content = self._format_topic_suggestion_response(topics_data, user_lang)
                    logger.info(f"[Feature #316] OpenRouter: Responding to vague query with topic suggestions")

                    return {
                        "content": response_content,
                        "tool_used": "topic_suggestion",
                        "tool_details": {
                            "provider": "openrouter",
                            "model": model,
                            "topics_data": topics_data,
                            "detected_language": user_lang
                        },
                        "response_source": "rag"
                    }

                # Check for SQL analysis (Feature #208: pass document_ids to detect unstructured context)
                is_sql, sql_args = self._detect_calculation_request(last_message, document_ids=document_ids)
                if is_sql and sql_args:
                    tool_result = self._execute_sql_analysis(sql_args)

                    if "error" not in tool_result:
                        result_value = tool_result.get("result", 0)
                        doc_name = tool_result.get("document", "")
                        operation = tool_result.get("operation", "")

                        response_content = f"Based on the data in **{doc_name}**, the {operation} is **{result_value:,.2f}**."

                        return {
                            "content": response_content,
                            "tool_used": "sql_analysis",
                            "tool_details": {
                                "provider": "openrouter",
                                "model": model,
                                "tool_result": tool_result
                            },
                            "response_source": "rag"
                        }

                # Check for vector search (Feature #205: Pass document_ids filter)
                # Feature #344: Rewrite query with conversational context before detection
                query_for_search = self._rewrite_query_with_context(last_message, messages)
                is_vector, search_args = self._detect_vector_search_request(query_for_search, document_ids=document_ids)
                if is_vector and search_args:
                    # Feature #344: Log if query was rewritten
                    if query_for_search != last_message:
                        logger.info(f"[Feature #344] OpenRouter: Using rewritten query for vector search")
                    # Feature #229: Apply routing hints from intent classification
                    routing_hints = query_classification.get("routing_hints", {})
                    if routing_hints.get("top_k"):
                        search_args["top_k"] = routing_hints["top_k"]
                        logger.info(f"[Feature #229] OpenRouter: Applied top_k={routing_hints['top_k']} from routing hints")
                    if routing_hints.get("similarity_threshold"):
                        search_args["similarity_threshold"] = routing_hints["similarity_threshold"]
                        logger.info(f"[Feature #229] OpenRouter: Applied similarity_threshold={routing_hints['similarity_threshold']} from routing hints")

                    tool_result = self._execute_vector_search(search_args)
                    results = tool_result.get("results", [])

                    # [Feature #240] Context validation guardrail - check BEFORE calling LLM
                    # This applies to BOTH empty results AND results with insufficient text
                    context_validation_error = self._validate_context_length(
                        results,  # Check raw results before truncation
                        query=search_args.get("query", last_message)
                    )
                    if context_validation_error:
                        return context_validation_error

                    if not results or "error" in tool_result:
                        # This branch is now only reached if guardrail passes but results are truly empty
                        query = search_args.get("query", "this topic")
                        response_content = f"I could not find information about '{query}' in the uploaded documents."
                        # Initialize tool_details_dict for the no-results case (Fix #191)
                        tool_details_dict = {
                            "provider": "openrouter",
                            "model": model,
                            "tool_result": tool_result,
                            "error": "no_results"
                        }
                        hallucination_detected = False
                    else:
                        # Apply token budget management - Feature #137
                        # OpenRouter models typically have 4096+ token context windows
                        # Reserve ~500 tokens for system prompt, question, and response
                        # Use ~3500 tokens for chunk context
                        # Feature #229: For listing queries, use more results
                        is_listing_query = query_classification.get("intent") == "listing"
                        max_results = routing_hints.get("top_k", 5) if is_listing_query else 5
                        # Feature #229: For listing, increase token budget to accommodate more results
                        token_budget = 8000 if is_listing_query else 3500
                        truncated_results = self._truncate_chunks_to_budget(
                            results[:max_results],  # Use dynamic max_results based on intent
                            token_budget=token_budget,
                            min_chunk_chars=500 if is_listing_query else 1000  # Smaller chunks for listings
                        )

                        # [Feature #240] Context validation guardrail - check BEFORE calling LLM
                        context_validation_error = self._validate_context_length(
                            truncated_results,
                            query=search_args.get("query", last_message)
                        )
                        if context_validation_error:
                            return context_validation_error

                        # [Feature #236] Filter out chunks with empty text before context building
                        valid_chunks, chunk_validation_error = self._filter_valid_chunks(
                            truncated_results,
                            query=search_args.get("query", last_message)
                        )
                        if chunk_validation_error:
                            return chunk_validation_error

                        # Build context with full chunk text (or intelligently truncated if needed)
                        context_parts = ["Here are relevant excerpts:\n\n"]
                        doc_results = {}
                        for i, result in enumerate(valid_chunks):  # [Feature #236] Use filtered valid_chunks
                            doc_title = result.get("document_title", "Unknown")
                            text = result.get("text", "")  # FEATURE #137: Use full text
                            context_parts.append(f"From {doc_title}: {text}\n\n")
                            # Track which documents we used
                            if doc_title not in doc_results:
                                doc_results[doc_title] = []
                            doc_results[doc_title].append(result)

                        # [Feature #235] Diagnostic logging for context building
                        context_string = "".join(context_parts)
                        self._log_context_building_diagnostics(valid_chunks, context_string, provider="openrouter")

                        # Use OpenRouter to synthesize
                        # Feature #210/219: Enhanced prompt for extracting prices from tabular PDF data
                        tabular_instruction = """
🚨 CRITICAL PRICE EXTRACTION RULES (Feature #219):

When answering questions about prices, you MUST follow these rules:

1. FIND THE NUMBER: Look for numerical values in the context (e.g., 13,000 or 14,000.00)
2. INCLUDE THE NUMBER: Your response MUST include the exact numerical value found
3. NEVER USE EMPTY PLACEHOLDERS: Never write "is ." or "is **.**" - always include the actual number

TABULAR DATA FORMAT:
Lines like "VFR‐X1M06SA‐AAA‐AA9 VMFT X‐Band 10kW Masthead (6ft) 13,000" contain:
[Product Code] [Description] [Price]
The LAST number on the line (13,000) is the PRICE.

FEW-SHOT EXAMPLES:
Context: "VFR‐X1M06SA‐AAA‐AA9 VMFT X‐Band 10kW Masthead (6ft) 13,000"
Question: "What is the price of VFR-X1M06SA-AAA-AA9?"
✅ CORRECT: "The price of VFR-X1M06SA-AAA-AA9 is **13,000 EUR**."
❌ WRONG: "The price of VFR-X1M06SA-AAA-AA9 is ."

Context: "Model/Part: NAVIGAT/100 | Price: 14,000 EUR"
Question: "What is the price of Navigat 100?"
✅ CORRECT: "The price of Navigat 100 is **14,000 EUR**."
❌ WRONG: "The price is ." or "The price is **.**"

SELF-CHECK: Before responding, verify you included the actual number!
"""
                        # Feature #286: Classify short queries as lookup instead of Q&A
                        query_type_classification = self.classify_query(last_message)
                        query_type = query_type_classification.get("query_type", "question")

                        # Detect comparison intent
                        comparison_kws = ['confronta', 'confronto', 'differenze', 'compare', 'comparison', 'differences', 'versus', 'vs']
                        is_comparison_or = any(kw in last_message.lower() for kw in comparison_kws)

                        # Build query-type specific instruction
                        query_type_instruction = ""
                        if is_comparison_or:
                            query_type_instruction = """
🔄 COMPARISON/ANALYSIS MODE:
The user is asking for a comparison or analytical response.
- SYNTHESIZE information into a coherent, reasoned answer — do NOT just list excerpts
- For comparisons: identify topics, state what EACH document says, highlight similarities and differences
- Use structured format (headers, bullet points, or comparison table)
- End with a brief conclusion. ALL conclusions must be grounded in the excerpts.
"""
                            logger.info(f"OpenRouter: Using COMPARISON/ANALYSIS mode")
                        elif query_type == "lookup":
                            query_type_instruction = """
🔍 LOOKUP MODE (Feature #286):
This is a SHORT QUERY (keyword-based lookup), NOT a question requiring clarification.
- FIND matching content in the excerpts
- SUMMARIZE what you find directly - do not ask for clarification
- Present the information clearly (title, ingredients, description, etc.)
- If multiple matches, list them all
- Do NOT mention price unless explicitly asked
"""
                            logger.info(f"[Feature #286] OpenRouter: Using LOOKUP mode for short query")
                        elif query_type == "calculation":
                            query_type_instruction = """
📊 CALCULATION MODE (Feature #286):
The user is requesting a calculation or aggregation.
- Focus on numerical data extraction
- Perform the requested calculation if possible
- Present the numerical result prominently
"""
                            logger.info(f"[Feature #286] OpenRouter: Using CALCULATION mode")
                        # For 'question' type, use the default prompt behavior

                        # Feature #345: Use the reformulated query (with context) for LLM synthesis
                        effective_query = search_args.get("query", last_message)
                        anti_hallucination_instruction = """
CRITICAL: ONLY use information explicitly written in the excerpts above. Do NOT add facts, numbers, or specifications from your general knowledge. If the excerpts mention a topic but lack the specific detail asked, say so clearly instead of inventing data."""
                        synthesis_messages = [
                            {"role": "system", "content": self.get_system_prompt()},
                            {"role": "user", "content": f"{''.join(context_parts)}\n\n{tabular_instruction}\n\n{query_type_instruction}\n\n{anti_hallucination_instruction}\n\nBased on these excerpts, answer: {effective_query}"}
                        ]

                        synthesis_response = client.chat.completions.create(
                            model=model,
                            messages=synthesis_messages,
                            temperature=0.1
                        )

                        response_content = synthesis_response.choices[0].message.content

                        # FEATURE #210: Post-process to fix blank price placeholders
                        response_content = self._fix_blank_price_placeholders(
                            response_content, truncated_results, last_message
                        )

                        # FEATURE #181: Validate RAG citations and detect hallucinations
                        source_list = list(doc_results.keys())
                        hallucination_detected = False
                        hallucinated_docs = []

                        # Extract document citations from the response
                        cited_docs = self._extract_document_citations(response_content)
                        if cited_docs:
                            valid_citations, hallucinated_docs, hallucination_detected = self._validate_citations(
                                cited_docs, source_list
                            )

                            if hallucination_detected:
                                logger.warning(f"[Feature #181] Hallucination detected in OpenRouter response: {hallucinated_docs}")
                                # Strip hallucinated citations from response
                                response_content = self._strip_hallucinated_citations(
                                    response_content, hallucinated_docs, source_list
                                )

                        # PROGRAMMATICALLY append sources to ensure they always appear
                        # (LLM often forgets to cite sources even when instructed)
                        if source_list:
                            # Remove any existing Sources line first (we'll add a clean one)
                            response_content = re.sub(r'\n\n\*?\*?[Ss]ources?\*?\*?[:\s]+[^\n]+', '', response_content)
                            response_content += f"\n\n**Sources:** {', '.join(source_list)}"

                        # Build tool_details with optional show_retrieved_chunks debug info
                        show_chunks = settings_store.get('show_retrieved_chunks', False)
                        tool_details_dict = {
                            "provider": "openrouter",
                            "model": model,
                            "tool_result": tool_result,
                            "hallucination_detected": hallucination_detected,
                            "hallucinated_documents": hallucinated_docs if hallucination_detected else []
                        }
                        if show_chunks:
                            tool_details_dict["retrieved_chunks"] = [
                                {
                                    "document_title": r.get("document_title"),
                                    "text": r.get("text", "")[:500] + "..." if len(r.get("text", "")) > 500 else r.get("text", ""),
                                    "similarity": r.get("similarity", 0),
                                    "chunk_id": r.get("chunk_id")
                                }
                                for r in truncated_results
                            ]

                    return {
                        "content": response_content,
                        "tool_used": "vector_search",
                        "tool_details": tool_details_dict,
                        "response_source": "rag",
                        "hallucination_detected": hallucination_detected
                    }

            # Anti-hallucination guardrail for OpenRouter: If no tool was detected but documents
            # with embeddings exist, force a vector search instead of letting the LLM answer
            # from general knowledge (mirrors the Ollama anti-hallucination fallback).
            try:
                documents = _get_documents_sync()
                has_unstructured = any(d.document_type == "unstructured" for d in documents)
                has_embeddings = embedding_store.get_chunk_count() > 0
                if has_unstructured and has_embeddings and messages:
                    last_msg = messages[-1].get("content", "").lower().strip()
                    non_document_patterns = [
                        r'^(hello|hi|hey|ciao|buongiorno|salve|buonasera)\b',
                        r'(who are you|what are you|chi sei|come ti chiami)',
                        r'(how are you|come stai|come va)',
                        r'^(thank|thanks|grazie)\b',
                        r'^(bye|goodbye|arrivederci)\b',
                        r'^(ok|okay|va bene|capito)\s*$',
                    ]
                    is_greeting = any(re.search(p, last_msg, re.IGNORECASE) for p in non_document_patterns)
                    if not is_greeting:
                        logger.warning(f"[Anti-hallucination] OpenRouter fallback reached with documents available - forcing vector search")
                        search_args = {"query": messages[-1].get("content", ""), "top_k": 5, "document_ids": document_ids}
                        tool_result = self._execute_vector_search(search_args)
                        results = tool_result.get("results", [])
                        if results:
                            truncated_results = self._truncate_chunks_to_budget(results[:5], token_budget=3500, min_chunk_chars=1000)
                            valid_chunks, _ = self._filter_valid_chunks(truncated_results, query=messages[-1].get("content", ""))
                            if valid_chunks:
                                context_parts = ["Here are the relevant excerpts from your documents:\n\n"]
                                doc_results = {}
                                for result in valid_chunks:
                                    doc_title = result.get("document_title", "Unknown Document")
                                    if doc_title not in doc_results:
                                        doc_results[doc_title] = []
                                    doc_results[doc_title].append(result)
                                for doc_title, doc_chunks in doc_results.items():
                                    context_parts.append(f"=== From document: {doc_title} ===\n")
                                    for i, chunk in enumerate(doc_chunks):
                                        chunk_text = chunk.get("text", "")
                                        context_parts.append(f"[Excerpt {i+1}]: {chunk_text}\n\n")
                                    context_parts.append("\n")
                                context_string = "".join(context_parts)
                                effective_query = messages[-1].get("content", "")

                                anti_hallucination_instruction = """
CRITICAL: ONLY use information explicitly written in the excerpts above. Do NOT add facts, numbers, or specifications from your general knowledge. If the excerpts mention a topic but lack the specific detail asked, say so clearly instead of inventing data."""

                                synthesis_messages = [
                                    {"role": "system", "content": self.get_system_prompt()},
                                    {"role": "user", "content": f"{context_string}\n\n{anti_hallucination_instruction}\n\nBased on these excerpts, answer: {effective_query}"}
                                ]
                                fallback_response = client.chat.completions.create(
                                    model=model,
                                    messages=synthesis_messages,
                                    temperature=0.1,
                                    max_tokens=2000
                                )
                                synthesized_content = fallback_response.choices[0].message.content
                                source_list = list(doc_results.keys())
                                if source_list:
                                    synthesized_content = re.sub(r'\n\n\*?\*?[Ss]ources?\*?\*?[:\s]+[^\n]+', '', synthesized_content)
                                    synthesized_content += f"\n\n**Sources:** {', '.join(source_list)}"
                                return {
                                    "content": synthesized_content,
                                    "tool_used": "vector_search",
                                    "tool_details": {"provider": "openrouter", "model": model, "anti_hallucination_fallback": True},
                                    "response_source": "rag"
                                }
            except Exception as e:
                logger.warning(f"[Anti-hallucination] OpenRouter fallback vector search failed: {e}")

            # No tool detected - make regular chat call
            response = client.chat.completions.create(
                model=model,
                messages=full_messages,
                temperature=0.7,
                max_tokens=1500
            )

            content = response.choices[0].message.content

            return {
                "content": content,
                "tool_used": None,
                "tool_details": {
                    "provider": "openrouter",
                    "model": model
                },
                "response_source": "direct"
            }

        except Exception as e:
            logger.error(f"Error in OpenRouter chat: {e}")
            return {
                "content": f"Error communicating with OpenRouter: {str(e)}",
                "tool_used": None,
                "tool_details": None,
                "response_source": "direct"
            }

    async def _chat_with_ollama(
        self,
        messages: List[Dict[str, str]],
        model: str,
        document_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Chat using Ollama API.

        Args:
            messages: List of message dictionaries
            model: The Ollama model name (without 'ollama:' prefix)
            document_ids: Optional list of document IDs to scope vector search to (Feature #205)

        Returns:
            Dict with response content and metadata
        """
        # Check if the last message is a calculation request or vector search request
        tool_used = None
        tool_details = None

        if messages:
            last_message = messages[-1].get("content", "")

            # First check for list documents requests
            is_list_docs = self._detect_list_documents_request(last_message)

            if is_list_docs:
                # Execute the list_documents tool
                tool_result = self._execute_list_documents()
                tool_used = "list_documents"
                tool_details = {
                    "provider": "ollama",
                    "model": model,
                    "tool_arguments": {},
                    "tool_result": tool_result
                }

                # Format a response listing the documents
                documents = tool_result.get("documents", [])
                total = tool_result.get("total", 0)

                if total == 0:
                    response_content = "You don't have any documents uploaded yet. You can upload documents using the 'Upload Document' button in the sidebar."
                else:
                    response_parts = [f"You have **{total} document(s)** available:\n"]

                    for doc in documents:
                        doc_type = doc.get("type", "unknown")
                        title = doc.get("title", "Untitled")
                        mime_type = doc.get("mime_type", "")
                        filename = doc.get("filename", "")

                        # Format document info
                        if doc_type == "structured":
                            schema = doc.get("schema", [])
                            row_count = doc.get("row_count", 0)
                            schema_str = ", ".join(schema) if schema else "unknown"
                            response_parts.append(f"\n**{title}** (CSV/Tabular Data)\n")
                            response_parts.append(f"- Type: {doc_type}\n")
                            response_parts.append(f"- Columns: {schema_str}\n")
                            response_parts.append(f"- Rows: {row_count}\n")
                        else:
                            response_parts.append(f"\n**{title}** (Text Document)\n")
                            response_parts.append(f"- Type: {doc_type}\n")
                            response_parts.append(f"- Format: {mime_type}\n")

                    response_parts.append(f"\n---\nYou can ask questions about these documents. For text documents, I'll search semantically. For tabular data, I can perform calculations and lookups.")
                    response_content = "".join(response_parts)

                return {
                    "content": response_content,
                    "tool_used": tool_used,
                    "tool_details": tool_details,
                    "response_source": "rag"
                }

            # Feature #316: Check for vague queries and suggest available topics
            is_vague = self._detect_vague_query(last_message)
            if is_vague:
                topics_data = self._get_available_topics()
                user_lang = self._detect_language(last_message) or "en"
                response_content = self._format_topic_suggestion_response(topics_data, user_lang)
                logger.info(f"[Feature #316] Ollama: Responding to vague query with topic suggestions")

                return {
                    "content": response_content,
                    "tool_used": "topic_suggestion",
                    "tool_details": {
                        "provider": "ollama",
                        "model": model,
                        "topics_data": topics_data,
                        "detected_language": user_lang
                    },
                    "response_source": "rag"
                }

            # Then check for cross-document requests
            is_cross_doc, cross_doc_args = self._detect_cross_document_request(last_message)

            if is_cross_doc and cross_doc_args:
                # Execute the cross_document_query tool
                tool_result = self._execute_cross_document_query(cross_doc_args)

                if "error" not in tool_result:
                    tool_used = "cross_document_query"
                    tool_details = {
                        "provider": "ollama",
                        "model": model,
                        "tool_arguments": cross_doc_args,
                        "tool_result": tool_result
                    }

                    # Format a response with the result
                    datasets = tool_result.get("datasets", [])
                    join_column = tool_result.get("join_column", "")
                    result_count = tool_result.get("result_count", 0)
                    results = tool_result.get("results", [])
                    sql_query = tool_result.get("sql_query", "")

                    response_content = f"I've combined data from **{', '.join(datasets)}** by joining on the **{join_column}** column.\n\n"
                    response_content += f"**Found {result_count} matching record(s):**\n\n"

                    # Show first few results
                    for i, row in enumerate(results[:5]):
                        response_content += f"\n**Record {i+1}:**\n"
                        for key, value in row.items():
                            response_content += f"- {key}: {value}\n"

                    if result_count > 5:
                        response_content += f"\n*...and {result_count - 5} more records*"

                    response_content += f"\n\n**SQL-like Query:** `{sql_query}`"

                    return {
                        "content": response_content,
                        "tool_used": tool_used,
                        "tool_details": tool_details,
                        "response_source": "rag"
                    }

            # Then check for calculation requests (SQL) - Feature #208: pass document_ids
            is_calculation, tool_args = self._detect_calculation_request(last_message, document_ids=document_ids)

            if is_calculation and tool_args:
                # Execute the SQL tool
                tool_result = self._execute_sql_analysis(tool_args)

                if "error" not in tool_result:
                    tool_used = "sql_analysis"
                    tool_details = {
                        "provider": "ollama",
                        "model": model,
                        "tool_arguments": tool_args,
                        "tool_result": tool_result
                    }

                    # Format a response with the result
                    result_value = tool_result.get("result")
                    sql_query = tool_result.get("sql_query", "")
                    doc_name = tool_result.get("document", "")
                    operation = tool_result.get("operation", "")
                    column = tool_result.get("column", "")

                    if operation == "count":
                        response_content = f"Based on the data in **{doc_name}**, the total count is **{int(result_value)}** rows.\n\n**SQL Query:** `{sql_query}`"
                    else:
                        response_content = f"Based on the data in **{doc_name}**, the {operation} of **{column}** is **{result_value:,.2f}**.\n\n**SQL Query:** `{sql_query}`"

                    return {
                        "content": response_content,
                        "tool_used": tool_used,
                        "tool_details": tool_details,
                        "response_source": "rag"
                    }

            # Then check for vector search requests (Feature #205: Pass document_ids filter)
            # Feature #344: Rewrite query with conversational context before detection
            query_for_search = self._rewrite_query_with_context(last_message, messages)
            is_vector_search, search_args = self._detect_vector_search_request(query_for_search, document_ids=document_ids)

            if is_vector_search and search_args:
                # Feature #344: Log if query was rewritten
                if query_for_search != last_message:
                    logger.info(f"[Feature #344] Ollama: Using rewritten query for vector search")
                # Execute the vector search tool
                tool_result = self._execute_vector_search(search_args)

                tool_used = "vector_search"
                tool_details = {
                    "provider": "ollama",
                    "model": model,
                    "tool_arguments": search_args,
                    "tool_result": tool_result
                }

                results = tool_result.get("results", [])
                query = search_args.get("query", "")

                # [Feature #240] Context validation guardrail - check BEFORE calling LLM
                # This applies to BOTH empty results AND results with insufficient text
                context_validation_error = self._validate_context_length(
                    results,  # Check raw results before truncation
                    query=search_args.get("query", last_message)
                )
                if context_validation_error:
                    return context_validation_error

                # Handle case where no results found (only reached if guardrail passes)
                if "error" in tool_result or not results:
                    return {
                        "content": f"I could not find information about '{query}' in the uploaded documents. Please make sure you have uploaded relevant documents, or try rephrasing your question.",
                        "tool_used": tool_used,
                        "tool_details": tool_details,
                        "response_source": "rag"
                    }

                # FEATURE #137: Apply token budget management for Ollama path
                # Ollama models typically have 4096-8192 token context windows
                # Reserve ~500 tokens for system prompt, question, and response overhead
                # For comparison queries, use more results and higher token budget
                comparison_keywords_check = ['confronta', 'confronto', 'differenze', 'compare', 'comparison', 'differences', 'versus', 'vs']
                is_comparison_query = any(kw in last_message.lower() for kw in comparison_keywords_check)
                max_results = 10 if is_comparison_query else 5
                token_budget = 6000 if is_comparison_query else 3500
                truncated_results = self._truncate_chunks_to_budget(
                    results[:max_results],
                    token_budget=token_budget,
                    min_chunk_chars=800 if is_comparison_query else 1000
                )

                # [Feature #236] Filter out chunks with empty text before context building
                valid_chunks, chunk_validation_error = self._filter_valid_chunks(
                    truncated_results,
                    query=search_args.get("query", last_message)
                )
                if chunk_validation_error:
                    return chunk_validation_error

                # Build context string with clear markers
                context_parts = ["Here are the relevant excerpts from your documents:\n\n"]
                doc_results = {}
                for result in valid_chunks:  # [Feature #236] Use filtered valid_chunks
                    doc_title = result.get("document_title", "Unknown Document")
                    if doc_title not in doc_results:
                        doc_results[doc_title] = []
                    doc_results[doc_title].append(result)

                for doc_title, doc_chunks in doc_results.items():
                    context_parts.append(f"=== From document: {doc_title} ===\n")
                    for i, chunk in enumerate(doc_chunks):
                        text = chunk.get("text", "")
                        context_parts.append(f"[Excerpt {i+1}]: {text}\n\n")
                    context_parts.append("\n")

                context_string = "".join(context_parts)

                # [Feature #235] Diagnostic logging for context building
                self._log_context_building_diagnostics(valid_chunks, context_string, provider="ollama")

                # Feature #286: Classify short queries as lookup instead of Q&A
                query_type_classification = self.classify_query(last_message)
                query_type = query_type_classification.get("query_type", "question")

                # Detect comparison intent from keywords
                comparison_keywords = [
                    'confronta', 'confronto', 'differenze', 'differenza', 'paragona',
                    'compare', 'comparison', 'differences', 'difference', 'versus', 'vs',
                    'rispetto a', 'compared to', 'differ', 'simile', 'similar',
                ]
                is_comparison = any(kw in last_message.lower() for kw in comparison_keywords)
                # Also detect when multiple documents are mentioned by name
                if len(doc_results) > 1:
                    is_comparison = is_comparison or any(kw in last_message.lower() for kw in ['tra', 'between', 'and', 'e il', 'e la'])

                # Build query-type specific instruction
                query_type_instruction = ""
                if is_comparison:
                    query_type_instruction = """
🔄 COMPARISON/ANALYSIS MODE:
The user is asking for a comparison or analytical response.
- SYNTHESIZE information from the excerpts into a coherent, reasoned answer
- Do NOT just list excerpts — extract key points and organize them logically
- For comparisons between documents:
  * Identify the specific topics/requirements being compared
  * For each topic, state what EACH document says (citing the source)
  * Highlight similarities and differences clearly
  * Use a structured format (headers, bullet points, or a comparison table)
  * If one document covers a topic but another doesn't, note this explicitly
  * End with a brief conclusion summarizing the key findings
- Remember: ALL conclusions must be grounded in the excerpts. Never add external knowledge.
"""
                    logger.info(f"Ollama: Using COMPARISON/ANALYSIS mode")
                elif query_type == "lookup":
                    query_type_instruction = """
🔍 LOOKUP MODE (Feature #286):
This is a SHORT QUERY (keyword-based lookup), NOT a question requiring clarification.
- FIND matching content in the excerpts
- SUMMARIZE what you find directly - do not ask for clarification
- Present the information clearly (title, ingredients, description, etc.)
- If multiple matches, list them all
- Do NOT mention price unless explicitly asked
"""
                    logger.info(f"[Feature #286] Ollama: Using LOOKUP mode for short query")
                elif query_type == "calculation":
                    query_type_instruction = """
📊 CALCULATION MODE (Feature #286):
The user is requesting a calculation or aggregation.
- Focus on numerical data extraction
- Perform the requested calculation if possible
- Present the numerical result prominently
"""
                    logger.info(f"[Feature #286] Ollama: Using CALCULATION mode")
                # For 'question' type, use the default prompt behavior

                # Create a grounding prompt with the context
                # Feature #239: Improved prompt for better context utilization
                # Feature #345: Use the reformulated query (with context) for LLM synthesis
                effective_query = search_args.get("query", last_message)
                grounding_prompt = f"""{query_type_instruction}

{context_string}

User's question: "{effective_query}"

INSTRUCTIONS:
1. Search the excerpts above for "{effective_query}" or related terms
2. If you find matching content, present ALL matches clearly
3. Partial matches count (e.g., "cipolla stufata" contains "cipolla" → include it)
4. ONLY use information that is EXPLICITLY written in the excerpts above
5. Do NOT add any facts, numbers, or details from your general knowledge
6. If the excerpts mention the topic but lack the specific detail asked, say: "The documents discuss this topic but do not specify [the detail]"
7. If the topic is completely absent from the excerpts, say: "I could not find information about this in the documents"

Answer the user's question based STRICTLY on the excerpts above."""

                # Use Ollama to synthesize the answer
                try:
                    synthesis_messages = [
                        {"role": "system", "content": self.get_system_prompt()},
                        {"role": "user", "content": grounding_prompt}
                    ]

                    # Call Ollama API for synthesis
                    async with httpx.AsyncClient(timeout=120.0) as http_client:
                        ollama_response = await http_client.post(
                            f"{OLLAMA_BASE_URL}/api/chat",
                            json={
                                "model": model,
                                "messages": synthesis_messages,
                                "stream": False,
                                "options": {
                                    "temperature": 0.1  # Very low temperature for strict factual responses (anti-hallucination)
                                }
                            }
                        )

                        if ollama_response.status_code == 200:
                            ollama_data = ollama_response.json()
                            synthesized_content = ollama_data.get("message", {}).get("content", "")

                            # FEATURE #181: Validate RAG citations and detect hallucinations
                            source_list = list(doc_results.keys())
                            hallucination_detected = False
                            hallucinated_docs = []

                            # Extract document citations from the response
                            cited_docs = self._extract_document_citations(synthesized_content)
                            if cited_docs:
                                valid_citations, hallucinated_docs, hallucination_detected = self._validate_citations(
                                    cited_docs, source_list
                                )

                                if hallucination_detected:
                                    logger.warning(f"[Feature #181] Hallucination detected in Ollama response: {hallucinated_docs}")
                                    # Strip hallucinated citations from response
                                    synthesized_content = self._strip_hallucinated_citations(
                                        synthesized_content, hallucinated_docs, source_list
                                    )

                            # PROGRAMMATICALLY append sources to ensure they always appear
                            # (LLM often forgets to cite sources even when instructed)
                            if source_list:
                                # Remove any existing Sources line first (we'll add a clean one)
                                synthesized_content = re.sub(r'\n\n\*?\*?[Ss]ources?\*?\*?[:\s]+[^\n]+', '', synthesized_content)
                                synthesized_content += f"\n\n**Sources:** {', '.join(source_list)}"

                            # Build tool_details with optional show_retrieved_chunks debug info
                            show_chunks = settings_store.get('show_retrieved_chunks', False)
                            enhanced_tool_details = dict(tool_details) if tool_details else {}
                            enhanced_tool_details["hallucination_detected"] = hallucination_detected
                            enhanced_tool_details["hallucinated_documents"] = hallucinated_docs if hallucination_detected else []
                            if show_chunks:
                                enhanced_tool_details["retrieved_chunks"] = [
                                    {
                                        "document_title": r.get("document_title"),
                                        "text": r.get("text", "")[:500] + "..." if len(r.get("text", "")) > 500 else r.get("text", ""),
                                        "similarity": r.get("similarity", 0),
                                        "chunk_id": r.get("chunk_id")
                                    }
                                    for r in truncated_results
                                ]

                            return {
                                "content": synthesized_content,
                                "tool_used": tool_used,
                                "tool_details": enhanced_tool_details,
                                "response_source": "rag",
                                "hallucination_detected": hallucination_detected
                            }
                except Exception as e:
                    logger.error(f"Error synthesizing vector search response with Ollama: {e}")

                # Fallback to simple format if synthesis fails
                # FEATURE #137: Use full chunk text instead of truncated 500 chars
                response_parts = ["Based on searching through your documents:\n"]
                for doc_title, doc_chunks in doc_results.items():
                    response_parts.append(f"\n**From \"{doc_title}\":**\n")
                    for chunk in doc_chunks[:2]:
                        text = chunk.get("text", "")
                        # Use full text, or truncate only if extremely long (>2000 chars)
                        if len(text) > 2000:
                            text = text[:2000] + "..."
                        response_parts.append(f"> {text}\n")
                response_parts.append(f"\n**Sources:** {', '.join(doc_results.keys())}")

                return {
                    "content": "\n".join(response_parts),
                    "tool_used": tool_used,
                    "tool_details": tool_details,
                    "response_source": "rag"
                }

        # First check if Ollama is available
        availability = await self.check_ollama_availability()

        if not availability["available"]:
            # Return user-friendly error with suggestions
            error_message = availability["error"]
            return self._get_ollama_error_response(error_message)

        # Check if the requested model is available
        available_models = availability.get("models", [])
        model_base_name = model.split(":")[0] if ":" in model else model

        # Try to find a matching model
        model_found = any(
            m == model or m.startswith(model_base_name)
            for m in available_models
        )

        if not model_found and available_models:
            # Model not found, suggest available models
            return {
                "content": f"**Ollama Model Not Found**\n\n"
                          f"The model '{model}' is not installed in Ollama.\n\n"
                          f"**Available models:**\n"
                          f"{chr(10).join('- ' + m for m in available_models[:10])}\n\n"
                          f"**To install {model}:**\n"
                          f"```\nollama pull {model}\n```\n\n"
                          f"Or select a different model in Settings.",
                "tool_used": None,
                "tool_details": {
                    "error": "model_not_found",
                    "requested_model": model,
                    "available_models": available_models
                },
                "response_source": "direct"
            }

        # Anti-hallucination guardrail: If we reach this fallback but documents with embeddings exist,
        # the user is probably asking about documents and the detection logic missed it.
        # Instead of letting the LLM answer from general knowledge, inform the user.
        try:
            documents = _get_documents_sync()
            has_unstructured = any(d.document_type == "unstructured" for d in documents)
            has_embeddings = embedding_store.get_chunk_count() > 0
            if has_unstructured and has_embeddings and messages:
                last_msg = messages[-1].get("content", "").lower().strip()
                # Allow greetings and meta-questions to pass through
                non_document_patterns = [
                    r'^(hello|hi|hey|ciao|buongiorno|salve|buonasera)\b',
                    r'(who are you|what are you|chi sei|come ti chiami)',
                    r'(how are you|come stai|come va)',
                    r'^(thank|thanks|grazie)\b',
                    r'^(bye|goodbye|arrivederci)\b',
                    r'^(ok|okay|va bene|capito)\s*$',
                ]
                is_greeting = any(re.search(p, last_msg, re.IGNORECASE) for p in non_document_patterns)
                if not is_greeting:
                    logger.warning(f"[Anti-hallucination] Ollama fallback reached with documents available - forcing vector search")
                    # Force a vector search instead of direct LLM response
                    search_args = {"query": messages[-1].get("content", ""), "top_k": 5, "document_ids": document_ids}
                    tool_result = self._execute_vector_search(search_args)
                    results = tool_result.get("results", [])
                    if results:
                        # Build context and synthesize like normal RAG path
                        truncated_results = self._truncate_chunks_to_budget(results[:5], token_budget=3500, min_chunk_chars=1000)
                        valid_chunks, _ = self._filter_valid_chunks(truncated_results, query=messages[-1].get("content", ""))
                        if valid_chunks:
                            context_parts = ["Here are the relevant excerpts from your documents:\n\n"]
                            doc_results = {}
                            for result in valid_chunks:
                                doc_title = result.get("document_title", "Unknown Document")
                                if doc_title not in doc_results:
                                    doc_results[doc_title] = []
                                doc_results[doc_title].append(result)
                            for doc_title, doc_chunks in doc_results.items():
                                context_parts.append(f"=== From document: {doc_title} ===\n")
                                for i, chunk in enumerate(doc_chunks):
                                    text = chunk.get("text", "")
                                    context_parts.append(f"[Excerpt {i+1}]: {text}\n\n")
                                context_parts.append("\n")
                            context_string = "".join(context_parts)
                            effective_query = messages[-1].get("content", "")
                            grounding_prompt = f"""{context_string}

User's question: "{effective_query}"

INSTRUCTIONS:
1. ONLY use information that is EXPLICITLY written in the excerpts above
2. Do NOT add any facts, numbers, or details from your general knowledge
3. If the excerpts mention the topic but lack the specific detail asked, say: "The documents discuss this topic but do not specify [the detail]"
4. If the topic is completely absent from the excerpts, say: "I could not find information about this in the documents"

Answer the user's question based STRICTLY on the excerpts above."""
                            synthesis_messages = [
                                {"role": "system", "content": self.get_system_prompt()},
                                {"role": "user", "content": grounding_prompt}
                            ]
                            async with httpx.AsyncClient(timeout=120.0) as http_client:
                                ollama_response = await http_client.post(
                                    f"{OLLAMA_BASE_URL}/api/chat",
                                    json={"model": model, "messages": synthesis_messages, "stream": False, "options": {"temperature": 0.1}}
                                )
                                if ollama_response.status_code == 200:
                                    ollama_data = ollama_response.json()
                                    synthesized_content = ollama_data.get("message", {}).get("content", "")
                                    source_list = list(doc_results.keys())
                                    if source_list:
                                        synthesized_content = re.sub(r'\n\n\*?\*?[Ss]ources?\*?\*?[:\s]+[^\n]+', '', synthesized_content)
                                        synthesized_content += f"\n\n**Sources:** {', '.join(source_list)}"
                                    return {
                                        "content": synthesized_content,
                                        "tool_used": "vector_search",
                                        "tool_details": {"provider": "ollama", "model": model, "anti_hallucination_fallback": True},
                                        "response_source": "rag"
                                    }
        except Exception as e:
            logger.warning(f"[Anti-hallucination] Fallback vector search failed: {e}")

        try:
            # Prepare the chat request for Ollama
            chat_messages = [
                {"role": "system", "content": self.get_system_prompt()}
            ]
            chat_messages.extend(messages)

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": model,
                        "messages": chat_messages,
                        "stream": False
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    assistant_message = data.get("message", {}).get("content", "")

                    return {
                        "content": assistant_message,
                        "tool_used": None,
                        "tool_details": {"provider": "ollama", "model": model},
                        "response_source": "direct"
                    }
                else:
                    error_text = response.text
                    logger.error(f"Ollama API error: {response.status_code} - {error_text}")
                    return {
                        "content": f"**Ollama Error**\n\n"
                                  f"Failed to get response from Ollama.\n"
                                  f"Status: {response.status_code}\n"
                                  f"Error: {error_text}\n\n"
                                  f"Please check if the model is properly loaded.",
                        "tool_used": None,
                        "tool_details": {"error": error_text, "status_code": response.status_code},
                        "response_source": "direct"
                    }

        except httpx.ConnectError:
            return self._get_ollama_error_response(
                "Connection to Ollama was lost. The service may have stopped."
            )
        except httpx.TimeoutException:
            return {
                "content": "**Request Timeout**\n\n"
                          "The request to Ollama took too long.\n"
                          "This can happen with complex queries or if the model is still loading.\n\n"
                          "**Suggestions:**\n"
                          "- Wait a moment and try again\n"
                          "- Try a smaller/faster model\n"
                          "- Check Ollama's resource usage",
                "tool_used": None,
                "tool_details": {"error": "timeout"},
                "response_source": "direct"
            }
        except Exception as e:
            logger.error(f"Unexpected error in Ollama chat: {e}")
            return {
                "content": f"**Unexpected Error**\n\n"
                          f"An error occurred while communicating with Ollama:\n"
                          f"{str(e)}\n\n"
                          f"Please try again or switch to OpenAI in Settings.",
                "tool_used": None,
                "tool_details": {"error": str(e)},
                "response_source": "direct"
            }

    def _get_ollama_error_response(self, error_message: str) -> Dict[str, Any]:
        """Generate a user-friendly error response when Ollama is not available."""
        return {
            "content": f"**Ollama is Not Available**\n\n"
                      f"{error_message}\n\n"
                      f"**How to fix this:**\n\n"
                      f"1. **Start Ollama** - Run `ollama serve` in your terminal, or start the Ollama app\n"
                      f"2. **Verify it's running** - Visit http://localhost:11434 in your browser\n"
                      f"3. **Try again** - Once Ollama is running, send your message again\n\n"
                      f"**Alternative:** Switch to OpenAI in Settings\n"
                      f"- Click the Settings icon in the sidebar\n"
                      f"- Select an OpenAI model (like GPT-4o)\n"
                      f"- Enter your OpenAI API key\n"
                      f"- Save and try again",
            "tool_used": None,
            "tool_details": {
                "error": "ollama_not_available",
                "error_message": error_message,
                "suggestion": "start_ollama_or_switch_to_openai"
            },
            "response_source": "direct"
        }

    def _get_api_key_error_response(self, error_type: str = "invalid") -> Dict[str, Any]:
        """Generate a user-friendly error response for API key issues."""
        if error_type == "invalid":
            title = "Invalid OpenAI API Key"
            description = "The OpenAI API key you provided is not valid or has been revoked."
        elif error_type == "rate_limit":
            title = "Rate Limit Exceeded"
            description = "Your OpenAI API key has exceeded its rate limit or quota."
        elif error_type == "connection":
            title = "Connection Error"
            description = "Unable to connect to OpenAI's servers."
        else:
            title = "API Error"
            description = "An error occurred while communicating with OpenAI."

        return {
            "content": f"**{title}**\n\n"
                      f"{description}\n\n"
                      f"**How to fix this:**\n\n"
                      f"1. **Check your API key** - Go to [OpenAI API Keys](https://platform.openai.com/api-keys) and verify your key is active\n"
                      f"2. **Update your key in Settings** - Click the Settings icon in the sidebar and enter a valid API key\n"
                      f"3. **Check your billing** - Ensure your OpenAI account has active billing at [OpenAI Billing](https://platform.openai.com/account/billing)\n\n"
                      f"**Alternative options:**\n"
                      f"- **Use Ollama** - Switch to a local Ollama model in Settings (free, runs on your machine)\n"
                      f"- **Get a new key** - Create a new API key at [OpenAI API Keys](https://platform.openai.com/api-keys)\n\n"
                      f"*Need help?* Visit [OpenAI's documentation](https://platform.openai.com/docs/quickstart) for setup instructions.",
            "tool_used": None,
            "tool_details": {
                "error": f"openai_{error_type}",
                "suggestion": "check_api_key_or_switch_to_ollama"
            },
            "response_source": "direct"
        }

    def _generate_query_embedding(self, query: str) -> Optional[List[float]]:
        """
        Generate an embedding for a query string (Feature #352).

        Reuses the same embedding logic from _execute_vector_search but
        as a standalone method for cache lookup and storage.

        Returns the embedding vector or None on failure.
        """
        api_key = settings_store.get('openai_api_key', '')
        embedding_model = settings_store.get('embedding_model', 'text-embedding-3-small')

        # Check stored embeddings for source info
        all_chunks = embedding_store.get_all_chunks()
        embedding_source = None
        if all_chunks:
            chunk_metadata = all_chunks[0].get("metadata", {})
            embedding_source = chunk_metadata.get("embedding_source", "")

        try:
            # If embeddings were made with Ollama, use Ollama
            if embedding_source and embedding_source.startswith("ollama:"):
                ollama_model = embedding_source.split(":", 1)[1]
                logger.info(f"[Feature #352] Generating cache embedding via Ollama stored source: {ollama_model}")
                import httpx
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{OLLAMA_BASE_URL}/api/embeddings",
                        json={"model": ollama_model, "prompt": query}
                    )
                    if response.status_code == 200:
                        emb = response.json().get("embedding", [])
                        return emb if emb else None
            # Try OpenAI if we have a valid key
            elif api_key and api_key.startswith('sk-') and len(api_key) > 20 and not api_key.startswith('sk-test'):
                logger.info(f"[Feature #352] Generating cache embedding via OpenAI: {embedding_model}")
                client = OpenAI(api_key=api_key)
                response = client.embeddings.create(
                    model=embedding_model,
                    input=[query]
                )
                return response.data[0].embedding
            else:
                # Use configured Ollama embedding model
                import httpx
                if embedding_model.startswith('ollama:'):
                    ollama_model = embedding_model[7:]
                else:
                    ollama_model = embedding_model
                logger.info(f"[Feature #352] Generating cache embedding via Ollama configured: {ollama_model}")
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{OLLAMA_BASE_URL}/api/embeddings",
                        json={"model": ollama_model, "prompt": query}
                    )
                    if response.status_code == 200:
                        emb = response.json().get("embedding", [])
                        return emb if emb else None
                    else:
                        logger.warning(f"[Feature #352] Ollama embedding returned status {response.status_code}")
        except Exception as e:
            logger.warning(f"[Feature #352] Failed to generate query embedding: {e}")
        return None

    def _cache_response(
        self,
        query_text: str,
        query_embedding: Optional[List[float]],
        response: Dict[str, Any],
        document_ids: Optional[List[str]],
    ) -> None:
        """
        Store a response in the cache if caching is enabled and appropriate (Feature #352).

        Only caches vector_search and sql_analysis responses. Skips caching for
        list_documents, topic_suggestion, direct, and other low-cost/volatile responses.
        """
        try:
            cache_enabled = str(settings_store.get('enable_response_cache', 'true')).lower() == 'true'
            if not cache_enabled or not query_embedding:
                logger.debug(f"[Feature #352] Cache store skipped: enabled={cache_enabled}, has_embedding={query_embedding is not None}")
                return

            tool_used = response.get("tool_used")
            # Only cache RAG/SQL responses - skip cheap or volatile response types
            if tool_used not in ("vector_search", "sql_analysis", "cross_document_query"):
                logger.debug(f"[Feature #352] Cache store skipped: tool_used={tool_used} not cacheable")
                return

            content = response.get("content", "")
            if not content or len(content) < 20:
                return

            cache_ttl = int(float(settings_store.get('cache_ttl_hours', '24')))
            embedding_model = settings_store.get('embedding_model', 'text-embedding-3-small')
            llm_model = settings_store.get('llm_model', '')

            response_cache_service.store(
                query_text=query_text,
                query_embedding=query_embedding,
                response_text=content,
                tool_used=tool_used,
                tool_details=response.get("tool_details"),
                response_source=response.get("response_source"),
                embedding_model=embedding_model,
                document_ids=document_ids,
                llm_model=llm_model,
                ttl_hours=cache_ttl,
            )
            logger.info(f"[Feature #352] Response cached: tool={tool_used}, llm={llm_model}, query='{query_text[:60]}...'")
        except Exception as e:
            logger.warning(f"[Feature #352] Failed to cache response: {e}")
            import traceback
            logger.warning(f"[Feature #352] Traceback: {traceback.format_exc()}")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        document_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Process a chat message and return an AI response.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            conversation_id: Optional conversation ID for context
            model: Optional model override (uses self.model if not provided)
            document_ids: Optional list of document IDs to scope the search to (Feature #205)

        Returns:
            Dict with 'content', 'tool_used', and 'tool_details' fields
        """
        # Store document_ids filter in instance for use by detection methods (Feature #205)
        self._document_filter = document_ids
        logger.info(f"[Feature #205] Chat called with document_ids filter: {document_ids}")

        # Feature #352: Semantic response cache check
        _cache_query_embedding = None  # Store for later caching
        cache_enabled = str(settings_store.get('enable_response_cache', 'true')).lower() == 'true'
        if cache_enabled and messages:
            try:
                last_msg = messages[-1].get("content", "")
                if last_msg and len(last_msg) > 3:
                    cache_threshold = float(settings_store.get('cache_similarity_threshold', '0.95'))
                    embedding_model = settings_store.get('embedding_model', 'text-embedding-3-small')
                    llm_model = settings_store.get('llm_model', '')
                    _cache_query_embedding = self._generate_query_embedding(last_msg)
                    logger.info(f"[Feature #352] Cache embedding generated: {_cache_query_embedding is not None} (dim={len(_cache_query_embedding) if _cache_query_embedding else 0})")
                    if _cache_query_embedding:
                        cached = response_cache_service.lookup(
                            query_embedding=_cache_query_embedding,
                            threshold=cache_threshold,
                            document_ids=document_ids,
                            embedding_model=embedding_model,
                            llm_model=llm_model,
                        )
                        if cached:
                            logger.info(f"[Feature #352] Cache HIT (similarity={cached['similarity']:.4f})")
                            return {
                                "content": cached["response_text"],
                                "tool_used": cached.get("tool_used"),
                                "tool_details": cached.get("tool_details"),
                                "response_source": cached.get("response_source"),
                                "cache_hit": True,
                            }
            except Exception as e:
                logger.warning(f"[Feature #352] Cache lookup error: {e}")

        # Get model from settings if not provided
        use_model = model or settings_store.get('llm_model') or self.model

        # Check if using Ollama
        if self.is_ollama_model(use_model):
            ollama_model = self.get_ollama_model_name(use_model)
            result = await self._chat_with_ollama(messages, ollama_model, document_ids=document_ids)
            # Feature #352: Cache the response
            if messages:
                self._cache_response(messages[-1].get("content", ""), _cache_query_embedding, result, document_ids)
            return result

        # Check if using OpenRouter
        if self.is_openrouter_model(use_model):
            openrouter_model = self.get_openrouter_model_name(use_model)
            result = await self._chat_with_openrouter(messages, openrouter_model, document_ids=document_ids)
            # Feature #352: Cache the response
            if messages:
                self._cache_response(messages[-1].get("content", ""), _cache_query_embedding, result, document_ids)
            return result

        # Using OpenAI - try to get or initialize client from settings
        client = self._get_openai_client()
        if not client:
            return self._get_fallback_response(messages)

        # Check for manual tool routing (helps with OpenAI's unreliable function calling)
        if messages:
            last_message = messages[-1].get("content", "")

            # Feature #217: Query intent classification for smarter routing
            query_classification = self._classify_query_intent(
                last_message,
                document_ids=document_ids,
                use_llm=True  # Enable LLM-based classification
            )
            logger.info(f"[Feature #217] Query classified as '{query_classification['intent']}' "
                       f"(confidence: {query_classification['confidence']:.2f}, "
                       f"method: {query_classification.get('method', 'unknown')}, "
                       f"suggested_tool: {query_classification['suggested_tool']})")

            # Store classification for use in tool execution
            self._query_classification = query_classification

            # Check for cross-document requests first (most specific)
            is_cross_doc, cross_doc_args = self._detect_cross_document_request(last_message)
            if is_cross_doc and cross_doc_args:
                tool_result = self._execute_cross_document_query(cross_doc_args)
                if "error" not in tool_result:
                    # Format response
                    datasets = tool_result.get("datasets", [])
                    join_column = tool_result.get("join_column", "")
                    result_count = tool_result.get("result_count", 0)
                    results = tool_result.get("results", [])
                    sql_query = tool_result.get("sql_query", "")

                    # Detect user language for bilingual support
                    user_lang = self._detect_language(last_message)
                    lang_instruction = ""
                    if user_lang and user_lang != "en":
                        lang_names = {"it": "Italian", "fr": "French", "es": "Spanish", "de": "German", "pt": "Portuguese"}
                        lang_name = lang_names.get(user_lang, user_lang)
                        lang_instruction = f" CRITICAL: Respond entirely in {lang_name}. The user wrote in {lang_name}, so you must respond in {lang_name}."

                    # Build result summary for LLM
                    result_summary = f"Cross-document query combining {', '.join(datasets)} by joining on '{join_column}' column.\n"
                    result_summary += f"SQL Query: {sql_query}\n"
                    result_summary += f"Found {result_count} matching records:\n\n"

                    for i, row in enumerate(results[:5]):
                        result_summary += f"Record {i+1}:\n"
                        for key, value in row.items():
                            result_summary += f"  {key}: {value}\n"
                        result_summary += "\n"

                    if result_count > 5:
                        result_summary += f"...and {result_count - 5} more records"

                    # Use LLM to format response in correct language
                    try:
                        # Put language instruction FIRST for maximum visibility
                        synthesis_prompt = f"""{lang_instruction}

{result_summary}

User's question: "{last_message}"

Please provide a clear, friendly response presenting these cross-document query results."""

                        synthesis_messages = [
                            {"role": "system", "content": self.get_system_prompt()},
                            {"role": "user", "content": synthesis_prompt}
                        ]

                        synthesis_response = client.chat.completions.create(
                            model=use_model,
                            messages=synthesis_messages,
                            temperature=0.1,
                            max_tokens=1000
                        )

                        response_content = synthesis_response.choices[0].message.content

                    except Exception as e:
                        logger.error(f"Error synthesizing cross-document response: {e}")
                        # Fallback to English if synthesis fails
                        response_content = f"I've combined data from **{', '.join(datasets)}** by joining on the **{join_column}** column.\n\n"
                        response_content += f"**Found {result_count} matching record(s):**\n\n"

                        for i, row in enumerate(results[:5]):
                            response_content += f"\n**Record {i+1}:**\n"
                            for key, value in row.items():
                                response_content += f"- {key}: {value}\n"

                        if result_count > 5:
                            response_content += f"\n*...and {result_count - 5} more records*"

                        response_content += f"\n\n**SQL-like Query:** `{sql_query}`"

                    return {
                        "content": response_content,
                        "tool_used": "cross_document_query",
                        "tool_details": {
                            "provider": "openai_manual_routing",
                            "model": use_model,
                            "tool_arguments": cross_doc_args,
                            "tool_result": tool_result
                        },
                        "response_source": "rag"
                    }

            # Check for list documents requests
            is_list_docs = self._detect_list_documents_request(last_message)
            if is_list_docs:
                tool_result = self._execute_list_documents()
                documents = tool_result.get("documents", [])
                total = tool_result.get("total", 0)

                # Detect user language for bilingual support
                user_lang = self._detect_language(last_message)
                logger.info(f"[FEATURE_102_DEBUG] List docs - Detected language: {user_lang}, total docs: {total}")
                lang_instruction = ""
                if user_lang and user_lang != "en":
                    lang_names = {"it": "Italian", "fr": "French", "es": "Spanish", "de": "German", "pt": "Portuguese"}
                    lang_name = lang_names.get(user_lang, user_lang)
                    lang_instruction = f" CRITICAL: Respond entirely in {lang_name}. The user wrote in {lang_name}, so you must respond in {lang_name}."
                    logger.info(f"[FEATURE_102_DEBUG] Added language instruction for {lang_name}")

                # Build document summary for LLM
                if total == 0:
                    doc_summary = "No documents are currently uploaded."
                else:
                    doc_parts = [f"Total documents: {total}\n\nDocument list:\n"]
                    for doc in documents:
                        doc_type = doc.get("type", "unknown")
                        title = doc.get("title", "Untitled")
                        if doc_type == "structured":
                            schema = doc.get("schema", [])
                            row_count = doc.get("row_count", 0)
                            schema_str = ", ".join(schema) if schema else "unknown"
                            doc_parts.append(f"- {title} (CSV/Tabular Data, Columns: {schema_str}, Rows: {row_count})\n")
                        else:
                            doc_parts.append(f"- {title} (Text Document, Type: {doc_type})\n")
                    doc_summary = "".join(doc_parts)

                # Use LLM to format response in correct language
                try:
                    # Put language instruction FIRST for maximum visibility
                    synthesis_prompt = f"""{lang_instruction}

{doc_summary}

User's question: "{last_message}"

Please provide a clear, friendly response listing the available documents."""

                    synthesis_messages = [
                        {"role": "system", "content": self.get_system_prompt()},
                        {"role": "user", "content": synthesis_prompt}
                    ]

                    synthesis_response = client.chat.completions.create(
                        model=use_model,
                        messages=synthesis_messages,
                        temperature=0.1,
                        max_tokens=800
                    )

                    response_content = synthesis_response.choices[0].message.content

                except Exception as e:
                    logger.error(f"Error synthesizing list documents response: {e}")
                    # Fallback with language support
                    if total == 0:
                        # Provide fallback in detected language
                        if user_lang == "it":
                            response_content = "Non hai ancora caricato alcun documento. Puoi caricare documenti usando il pulsante 'Carica Documento' nella barra laterale."
                        elif user_lang == "es":
                            response_content = "Aún no tienes documentos cargados. Puedes cargar documentos usando el botón 'Cargar Documento' en la barra lateral."
                        elif user_lang == "fr":
                            response_content = "Vous n'avez pas encore téléchargé de documents. Vous pouvez télécharger des documents en utilisant le bouton 'Télécharger un document' dans la barre latérale."
                        elif user_lang == "de":
                            response_content = "Sie haben noch keine Dokumente hochgeladen. Sie können Dokumente über die Schaltfläche 'Dokument hochladen' in der Seitenleiste hochladen."
                        elif user_lang == "pt":
                            response_content = "Você ainda não enviou nenhum documento. Você pode enviar documentos usando o botão 'Enviar Documento' na barra lateral."
                        else:
                            response_content = "You don't have any documents uploaded yet. You can upload documents using the 'Upload Document' button in the sidebar."
                    else:
                        response_parts = [f"You have **{total} document(s)** available:\n"]
                        for doc in documents:
                            doc_type = doc.get("type", "unknown")
                            title = doc.get("title", "Untitled")
                            if doc_type == "structured":
                                schema = doc.get("schema", [])
                                row_count = doc.get("row_count", 0)
                                schema_str = ", ".join(schema) if schema else "unknown"
                                response_parts.append(f"\n**{title}** (CSV/Tabular Data)\n- Columns: {schema_str}\n- Rows: {row_count}\n")
                            else:
                                response_parts.append(f"\n**{title}** (Text Document)\n- Type: {doc_type}\n")
                        response_content = "".join(response_parts)

                return {
                    "content": response_content,
                    "tool_used": "list_documents",
                    "tool_details": {
                        "provider": "openai_manual_routing",
                        "model": use_model,
                        "tool_arguments": {},
                        "tool_result": tool_result
                    },
                    "response_source": "rag"
                }

            # Feature #316: Check for vague queries and suggest available topics
            is_vague = self._detect_vague_query(last_message)
            if is_vague:
                topics_data = self._get_available_topics()
                user_lang = self._detect_language(last_message) or "en"
                response_content = self._format_topic_suggestion_response(topics_data, user_lang)
                logger.info(f"[Feature #316] OpenAI: Responding to vague query with topic suggestions")

                return {
                    "content": response_content,
                    "tool_used": "topic_suggestion",
                    "tool_details": {
                        "provider": "openai_manual_routing",
                        "model": use_model,
                        "topics_data": topics_data,
                        "detected_language": user_lang
                    },
                    "response_source": "rag"
                }

            # Check for calculation requests (SQL) - CRITICAL FIX for unreliable function calling
            # Feature #208: pass document_ids to detect unstructured context
            is_calculation, tool_args = self._detect_calculation_request(last_message, document_ids=document_ids)
            logger.info(f"Manual tool routing check - is_calculation: {is_calculation}, tool_args: {tool_args}")
            if is_calculation and tool_args:
                tool_result = self._execute_sql_analysis(tool_args)
                if "error" not in tool_result:
                    result_value = tool_result.get("result")
                    sql_query = tool_result.get("sql_query", "")
                    doc_name = tool_result.get("document", "")
                    operation = tool_result.get("operation", "")
                    column = tool_result.get("column", "")

                    # Detect user language for bilingual support
                    user_lang = self._detect_language(last_message)
                    lang_instruction = ""
                    if user_lang and user_lang != "en":
                        lang_names = {"it": "Italian", "fr": "French", "es": "Spanish", "de": "German", "pt": "Portuguese"}
                        lang_name = lang_names.get(user_lang, user_lang)
                        lang_instruction = f" CRITICAL: Respond entirely in {lang_name}. The user wrote in {lang_name}, so you must respond in {lang_name}."

                    # Build result summary for LLM
                    if operation == "count":
                        result_summary = f"The SQL query `{sql_query}` returned a count of {int(result_value)} rows in the document '{doc_name}'."
                    elif operation == "list":
                        sample = tool_result.get("sample_rows", [])
                        result_summary = f"The SQL query `{sql_query}` returned these rows from '{doc_name}':\n"
                        for i, row in enumerate(sample[:10]):
                            result_summary += f"Row {i+1}: {row}\n"
                    else:
                        result_summary = f"The SQL query `{sql_query}` calculated the {operation} of column '{column}' in document '{doc_name}' as {result_value:,.2f}."

                    # Use LLM to format response in correct language
                    try:
                        # Put language instruction FIRST for maximum visibility
                        synthesis_prompt = f"""{lang_instruction}

{result_summary}

User's question: "{last_message}"

Please provide a clear, friendly response to the user's question based on this SQL query result."""

                        synthesis_messages = [
                            {"role": "system", "content": self.get_system_prompt()},
                            {"role": "user", "content": synthesis_prompt}
                        ]

                        synthesis_response = client.chat.completions.create(
                            model=use_model,
                            messages=synthesis_messages,
                            temperature=0.1,
                            max_tokens=500
                        )

                        response_content = synthesis_response.choices[0].message.content

                    except Exception as e:
                        logger.error(f"Error synthesizing SQL response: {e}")
                        # Fallback to English if synthesis fails
                        if operation == "count":
                            response_content = f"Based on the data in **{doc_name}**, the total count is **{int(result_value)}** rows.\n\n**SQL Query:** `{sql_query}`"
                        elif operation == "list":
                            sample = tool_result.get("sample_rows", [])
                            response_content = f"Here are the rows from **{doc_name}**:\n\n"
                            for i, row in enumerate(sample[:10]):
                                response_content += f"**Row {i+1}:** {row}\n"
                        else:
                            response_content = f"Based on the data in **{doc_name}**, the {operation} of **{column}** is **{result_value:,.2f}**.\n\n**SQL Query:** `{sql_query}`"

                    _result = {
                        "content": response_content,
                        "tool_used": "sql_analysis",
                        "tool_details": {
                            "provider": "openai_manual_routing",
                            "model": use_model,
                            "tool_arguments": tool_args,
                            "tool_result": tool_result
                        },
                        "response_source": "rag"
                    }
                    # Feature #352: Cache the response
                    if messages:
                        self._cache_response(messages[-1].get("content", ""), _cache_query_embedding, _result, document_ids)
                    return _result

            # Check for vector search requests (Feature #205: Pass document_ids filter)
            # Feature #344: Rewrite query with conversational context before detection
            query_for_search = self._rewrite_query_with_context(last_message, messages)
            is_vector_search, search_args = self._detect_vector_search_request(query_for_search, document_ids=document_ids)
            if is_vector_search and search_args:
                # Feature #344: Log if query was rewritten
                if query_for_search != last_message:
                    logger.info(f"[Feature #344] OpenAI: Using rewritten query for vector search")
                # Feature #217: Apply routing hints from intent classification
                routing_hints = query_classification.get("routing_hints", {})
                if routing_hints.get("top_k"):
                    search_args["top_k"] = routing_hints["top_k"]
                if routing_hints.get("similarity_threshold"):
                    # Feature #229: Apply similarity threshold for listing queries
                    search_args["similarity_threshold"] = routing_hints["similarity_threshold"]

                logger.info(f"[Feature #217] Vector search with intent '{query_classification['intent']}', "
                           f"routing_hints: {routing_hints}")

                tool_result = self._execute_vector_search(search_args)

                # Handle case where no results found
                # [Feature #318] Use graceful degradation with alternative suggestions
                if "error" in tool_result or not tool_result.get("results"):
                    query = search_args.get("query", "this topic")

                    # Detect user language for bilingual support
                    user_lang = self._detect_language(last_message)

                    # [Feature #318] Check if there's a graceful_degradation message from vector search
                    graceful_message = tool_result.get("message")
                    graceful_suggestions = tool_result.get("graceful_degradation")

                    if graceful_message and graceful_suggestions:
                        # Use the graceful degradation message from vector search
                        no_results_msg = graceful_message
                        logger.info(f"[Feature #318] Using graceful degradation response for OpenAI path")
                    else:
                        # Generate graceful degradation suggestions for completely empty results
                        suggestions = self._generate_graceful_degradation_suggestions(
                            query=query,
                            discarded_results=[],  # No results at all
                            user_lang=user_lang
                        )
                        no_results_msg = self._format_graceful_degradation_response(
                            query=query,
                            suggestions=suggestions,
                            user_lang=user_lang,
                            relevance_threshold=0.0  # No threshold applied when no results
                        )
                        graceful_suggestions = suggestions
                        logger.info(f"[Feature #318] Generated graceful degradation for empty results")

                    return {
                        "content": no_results_msg,
                        "tool_used": "vector_search",
                        "tool_details": {
                            "provider": "openai_manual_routing",
                            "model": use_model,
                            "tool_arguments": search_args,
                            "tool_result": tool_result,
                            "graceful_degradation": graceful_suggestions
                        },
                        "response_source": "rag"
                    }

                results = tool_result.get("results", [])

                # FEATURE #137: Apply token budget management for OpenAI path
                # OpenAI models have larger context windows but we still manage budget
                # Reserve ~1000 tokens for system prompt, question, response overhead
                truncated_results = self._truncate_chunks_to_budget(
                    results[:5],  # Top 5 results
                    token_budget=6000,  # Larger budget for OpenAI models
                    min_chunk_chars=1000
                )

                # [Feature #236] Filter out chunks with empty text before context building
                valid_chunks, chunk_validation_error = self._filter_valid_chunks(
                    truncated_results,
                    query=search_args.get("query", last_message)
                )
                if chunk_validation_error:
                    return chunk_validation_error

                # Build context string with clear markers
                context_parts = ["Here are the relevant excerpts from your documents:\n\n"]
                doc_results = {}
                for result in valid_chunks:  # [Feature #236] Use filtered valid_chunks
                    doc_title = result.get("document_title", "Unknown Document")
                    if doc_title not in doc_results:
                        doc_results[doc_title] = []
                    doc_results[doc_title].append(result)

                for doc_title, doc_chunks in doc_results.items():
                    context_parts.append(f"=== From document: {doc_title} ===\n")
                    for i, chunk in enumerate(doc_chunks):
                        text = chunk.get("text", "")
                        context_parts.append(f"[Excerpt {i+1}]: {text}\n\n")
                    context_parts.append("\n")

                context_string = "".join(context_parts)

                # [Feature #235] Diagnostic logging for context building
                self._log_context_building_diagnostics(valid_chunks, context_string, provider="openai")

                # Detect user language for bilingual support
                user_lang = self._detect_language(last_message)
                lang_instruction = ""
                if user_lang and user_lang != "en":
                    lang_names = {"it": "Italian", "fr": "French", "es": "Spanish", "de": "German", "pt": "Portuguese"}
                    lang_name = lang_names.get(user_lang, user_lang)
                    lang_instruction = f"CRITICAL LANGUAGE RULE: The user wrote in {lang_name}. You MUST respond entirely in {lang_name}. All text including citations and headers must be in {lang_name}.\n\n"

                # Feature #286: Classify short queries as lookup instead of Q&A
                query_type_classification = self.classify_query(last_message)
                query_type = query_type_classification.get("query_type", "question")

                # Detect comparison intent
                comparison_kws_oai = ['confronta', 'confronto', 'differenze', 'compare', 'comparison', 'differences', 'versus', 'vs']
                is_comparison_oai = any(kw in last_message.lower() for kw in comparison_kws_oai)

                # Build query-type specific instruction
                query_type_instruction = ""
                if is_comparison_oai:
                    query_type_instruction = """
🔄 COMPARISON/ANALYSIS MODE:
The user is asking for a comparison or analytical response.
- SYNTHESIZE information into a coherent, reasoned answer — do NOT just list excerpts
- For comparisons: identify topics, state what EACH document says, highlight similarities and differences
- Use structured format (headers, bullet points, or comparison table)
- End with a brief conclusion. ALL conclusions must be grounded in the excerpts.

"""
                    logger.info(f"OpenAI: Using COMPARISON/ANALYSIS mode")
                elif query_type == "lookup":
                    query_type_instruction = """
🔍 LOOKUP MODE (Feature #286):
This is a SHORT QUERY (keyword-based lookup), NOT a question requiring clarification.
- FIND matching content in the excerpts
- SUMMARIZE what you find directly - do not ask for clarification
- Present the information clearly (title, ingredients, description, etc.)
- If multiple matches, list them all
- Do NOT mention price unless explicitly asked

"""
                    logger.info(f"[Feature #286] OpenAI: Using LOOKUP mode for short query")
                elif query_type == "calculation":
                    query_type_instruction = """
📊 CALCULATION MODE (Feature #286):
The user is requesting a calculation or aggregation.
- Focus on numerical data extraction
- Perform the requested calculation if possible
- Present the numerical result prominently

"""
                    logger.info(f"[Feature #286] OpenAI: Using CALCULATION mode")
                # For 'question' type, use the default prompt behavior

                # Create a grounding prompt with the context
                # Feature #239: Improved prompt for better context utilization
                # Feature #345: Use the reformulated query (with context) for LLM synthesis
                # This ensures the LLM understands the user's intent, not just the literal query
                effective_query = search_args.get("query", last_message)
                grounding_prompt = f"""{lang_instruction}{query_type_instruction}{context_string}

User's question: "{effective_query}"

INSTRUCTIONS:
1. Search the excerpts above for relevant information about "{effective_query}"
2. Include partial matches (e.g., "cipolla stufata" matches a search for "cipolla")
3. For listing queries, present ALL matches as a numbered list with page references
4. ONLY use information that is EXPLICITLY written in the excerpts above
5. Do NOT add any facts, numbers, specifications, or details from your general knowledge
6. If the excerpts mention the topic but lack the specific detail asked, say: "The documents discuss this topic but do not specify [the detail]"
7. If the topic is completely absent from the excerpts, say: "I could not find information about this in the documents"
8. Always cite which document(s) the information came from
9. For price queries: include the EXACT numerical value from the excerpt (e.g., **13,000 EUR**)

Answer the user's question based STRICTLY on the excerpts above."""

                # Use LLM to synthesize the answer
                try:
                    synthesis_messages = [
                        {"role": "system", "content": self.get_system_prompt()},
                        {"role": "user", "content": grounding_prompt}
                    ]

                    synthesis_response = client.chat.completions.create(
                        model=use_model,
                        messages=synthesis_messages,
                        temperature=0.1,  # Very low temperature to minimize hallucination
                        max_tokens=1500
                    )

                    synthesized_content = synthesis_response.choices[0].message.content

                    # FEATURE #210: Post-process to fix blank price placeholders
                    synthesized_content = self._fix_blank_price_placeholders(
                        synthesized_content, truncated_results, last_message
                    )

                    # FEATURE #318: Detect and enhance "not found" responses with suggestions
                    user_lang_318 = self._detect_language(last_message)
                    synthesized_content, was_enhanced_318 = self._detect_and_enhance_not_found_response(
                        synthesized_content=synthesized_content,
                        query=last_message,
                        truncated_results=truncated_results,
                        user_lang=user_lang_318
                    )

                    # FEATURE #181: Validate RAG citations and detect hallucinations
                    source_list = list(doc_results.keys())
                    hallucination_detected = False
                    hallucinated_docs = []

                    # Extract document citations from the response
                    cited_docs = self._extract_document_citations(synthesized_content)
                    if cited_docs:
                        valid_citations, hallucinated_docs, hallucination_detected = self._validate_citations(
                            cited_docs, source_list
                        )

                        if hallucination_detected:
                            logger.warning(f"[Feature #181] Hallucination detected in response: {hallucinated_docs}")
                            # Strip hallucinated citations from response
                            synthesized_content = self._strip_hallucinated_citations(
                                synthesized_content, hallucinated_docs, source_list
                            )

                    # PROGRAMMATICALLY append sources to ensure they always appear
                    # (LLM often forgets to cite sources even when instructed)
                    if source_list:
                        # Remove any existing Sources line first (we'll add a clean one)
                        synthesized_content = re.sub(r'\n\n\*?\*?[Ss]ources?\*?\*?[:\s]+[^\n]+', '', synthesized_content)
                        synthesized_content += f"\n\n**Sources:** {', '.join(source_list)}"

                    # Build tool_details with optional show_retrieved_chunks debug info
                    show_chunks = settings_store.get('show_retrieved_chunks', False)
                    tool_details_dict = {
                        "provider": "openai_manual_routing",
                        "model": use_model,
                        "tool_arguments": search_args,
                        "tool_result": tool_result,
                        "hallucination_detected": hallucination_detected,
                        "hallucinated_documents": hallucinated_docs if hallucination_detected else [],
                        # Feature #217: Include query classification in response
                        "query_classification": query_classification
                    }
                    if show_chunks:
                        # Include raw retrieved chunks for debugging
                        tool_details_dict["retrieved_chunks"] = [
                            {
                                "document_title": r.get("document_title"),
                                "text": r.get("text", "")[:500] + "..." if len(r.get("text", "")) > 500 else r.get("text", ""),
                                "similarity": r.get("similarity", 0),
                                "chunk_id": r.get("chunk_id")
                            }
                            for r in truncated_results
                        ]

                    _result = {
                        "content": synthesized_content,
                        "tool_used": "vector_search",
                        "tool_details": tool_details_dict,
                        "response_source": "rag",
                        "hallucination_detected": hallucination_detected
                    }
                    # Feature #352: Cache the response
                    if messages:
                        self._cache_response(messages[-1].get("content", ""), _cache_query_embedding, _result, document_ids)
                    return _result
                except Exception as e:
                    logger.error(f"Error synthesizing vector search response: {e}")
                    # Fallback to simple format if synthesis fails
                    # FEATURE #137: Use full chunk text instead of truncated 500 chars
                    response_parts = ["Based on searching through your documents:\n"]
                    for doc_title, doc_chunks in doc_results.items():
                        response_parts.append(f"\n**From \"{doc_title}\":**\n")
                        for chunk in doc_chunks[:2]:
                            text = chunk.get("text", "")
                            # Use full text, or truncate only if extremely long (>2000 chars)
                            if len(text) > 2000:
                                text = text[:2000] + "..."
                            response_parts.append(f"> {text}\n")
                    response_parts.append(f"\n**Sources:** {', '.join(doc_results.keys())}")

                    return {
                        "content": "\n".join(response_parts),
                        "tool_used": "vector_search",
                        "tool_details": {
                            "provider": "openai_manual_routing",
                            "model": use_model,
                            "tool_arguments": search_args,
                            "tool_result": tool_result
                        },
                        "response_source": "rag"
                    }

        # FEATURE #95: Force RAG for all document questions when documents exist
        # This ensures we always check documents first before generating responses
        if messages:
            last_message = messages[-1].get("content", "")

            # Check if we have documents available
            documents = _get_documents_sync()
            has_unstructured = any(d.document_type == "unstructured" for d in documents)
            has_embeddings = embedding_store.get_chunk_count() > 0

            # Define explicit non-document queries that should NOT use RAG
            non_document_patterns = [
                r'^(hello|hi|hey|ciao|buongiorno|salve)',  # Greetings
                r'(what time is it|current time|what day)',  # Time/date queries
                r'(who are you|what are you|your name)',  # Meta questions about the AI
                r'(how are you|how do you do)',  # Conversational
                r'^(thank|thanks|grazie)',  # Thanks
                r'^(bye|goodbye|cya|arrivederci)',  # Farewells
            ]

            message_lower = last_message.lower().strip()
            is_non_document_query = any(re.search(pattern, message_lower, re.IGNORECASE)
                                       for pattern in non_document_patterns)

            # Force RAG if: documents exist AND embeddings ready AND NOT a non-document query
            if has_unstructured and has_embeddings and not is_non_document_query:
                logger.info(f"[FEATURE #95] Forcing RAG for question: {last_message[:50]}...")
                logger.info(f"[FEATURE #95] has_unstructured={has_unstructured}, has_embeddings={has_embeddings}, is_non_document_query={is_non_document_query}")

                # Force vector search
                search_args = {
                    "query": last_message,
                    "top_k": 5
                }
                tool_result = self._execute_vector_search(search_args)

                # Handle case where no results found or low confidence
                results = tool_result.get("results", [])
                if not results or "error" in tool_result:
                    # No relevant documents found - inform user
                    logger.info(f"[FEATURE #95] No relevant results found in vector search")
                    return {
                        "content": f"I searched through your documents but couldn't find relevant information to answer: \"{last_message}\"\n\nThis could mean:\n- The information isn't in the uploaded documents\n- Try rephrasing your question\n- The query might be too broad or too specific\n\nYou can use 'list documents' to see what's available.",
                        "tool_used": "vector_search",
                        "tool_details": {
                            "provider": "openai_forced_rag",
                            "model": use_model,
                            "tool_arguments": search_args,
                            "tool_result": tool_result,
                            "confidence": "low",
                            "forced": True
                        }
                    }

                # FEATURE #182: Check confidence with improved thresholds
                # Default threshold: 0.5, Strict mode: 0.6
                strict_rag_mode = settings_store.get('strict_rag_mode', False)
                confidence_threshold = 0.6 if strict_rag_mode else 0.5

                min_similarity = min(r.get("similarity", 0) for r in results)
                avg_similarity = sum(r.get("similarity", 0) for r in results) / len(results)

                logger.info(f"[FEATURE #95/#182] Vector search results: {len(results)} chunks, avg_similarity={avg_similarity:.3f}, min_similarity={min_similarity:.3f}, threshold={confidence_threshold} (strict_mode={strict_rag_mode})")

                # If low confidence based on dynamic threshold, inform user
                # [Feature #318] Use graceful degradation with partial matches and suggestions
                if avg_similarity < confidence_threshold:
                    logger.info(f"[FEATURE #182] Low confidence results (avg similarity: {avg_similarity:.3f} < threshold: {confidence_threshold})")
                    logger.info(f"[Feature #318] Generating graceful degradation for low confidence results")

                    # Detect user language
                    user_lang = self._detect_language(last_message)

                    # Generate suggestions from the low-confidence results
                    suggestions = self._generate_graceful_degradation_suggestions(
                        query=search_args.get("query", last_message),
                        discarded_results=results,  # Pass all results as they're low confidence
                        user_lang=user_lang
                    )

                    # Format the response with graceful degradation
                    graceful_message = self._format_graceful_degradation_response(
                        query=search_args.get("query", last_message),
                        suggestions=suggestions,
                        user_lang=user_lang,
                        relevance_threshold=confidence_threshold
                    )

                    return {
                        "content": graceful_message,
                        "tool_used": "vector_search",
                        "tool_details": {
                            "provider": "openai_forced_rag",
                            "model": use_model,
                            "tool_arguments": search_args,
                            "tool_result": tool_result,
                            "confidence": "low",
                            "avg_similarity": avg_similarity,
                            "confidence_threshold": confidence_threshold,
                            "strict_rag_mode": strict_rag_mode,
                            "forced": True,
                            "graceful_degradation": suggestions  # Include structured suggestions
                        }
                    }

                # Good results - build context and synthesize
                # FEATURE #137: Apply token budget management for forced RAG path
                truncated_results = self._truncate_chunks_to_budget(
                    results[:5],  # Top 5 results
                    token_budget=6000,
                    min_chunk_chars=1000
                )

                # [Feature #236] Filter out chunks with empty text before context building
                valid_chunks, chunk_validation_error = self._filter_valid_chunks(
                    truncated_results,
                    query=search_args.get("query", last_message)
                )
                if chunk_validation_error:
                    return chunk_validation_error

                context_parts = ["Here are the relevant excerpts from your documents:\n\n"]
                doc_results = {}
                for result in valid_chunks:  # [Feature #236] Use filtered valid_chunks
                    doc_title = result.get("document_title", "Unknown Document")
                    if doc_title not in doc_results:
                        doc_results[doc_title] = []
                    doc_results[doc_title].append(result)

                for doc_title, doc_chunks in doc_results.items():
                    context_parts.append(f"=== From document: {doc_title} ===\n")
                    for i, chunk in enumerate(doc_chunks):
                        text = chunk.get("text", "")
                        similarity = chunk.get("similarity", 0)
                        context_parts.append(f"[Excerpt {i+1}] (relevance: {similarity:.1%}): {text}\n\n")
                    context_parts.append("\n")

                context_string = "".join(context_parts)

                # [Feature #235] Diagnostic logging for context building
                self._log_context_building_diagnostics(valid_chunks, context_string, provider="openai_forced_rag")

                # Create grounding prompt
                # Feature #239: Improved prompt for better context utilization
                # Feature #345: Use the reformulated query (with context) for LLM synthesis
                effective_query = search_args.get("query", last_message)
                grounding_prompt = f"""{context_string}

User's question: "{effective_query}"

INSTRUCTIONS:
1. Search the excerpts above for relevant information about "{effective_query}"
2. Include partial matches (e.g., "cipolla stufata" matches a search for "cipolla")
3. For listing queries, present ALL matches as a numbered list with page references
4. ONLY use information that is EXPLICITLY written in the excerpts above
5. Do NOT add any facts, numbers, specifications, or details from your general knowledge
6. If the excerpts mention the topic but lack the specific detail asked, say: "The documents discuss this topic but do not specify [the detail]"
7. If the topic is completely absent from the excerpts, say: "I could not find information about this in the documents"
8. Always cite which document(s) the information came from
9. Start your response with "Based on the excerpts from [document name(s)]:"
10. For price queries: include the EXACT numerical value from the excerpt (e.g., **13,000 EUR**)

Answer the user's question based STRICTLY on the excerpts above."""

                # Use LLM to synthesize
                try:
                    synthesis_messages = [
                        {"role": "system", "content": self.get_system_prompt()},
                        {"role": "user", "content": grounding_prompt}
                    ]

                    synthesis_response = client.chat.completions.create(
                        model=use_model,
                        messages=synthesis_messages,
                        temperature=0.1,  # Very low temperature to minimize hallucination
                        max_tokens=1500
                    )

                    synthesized_content = synthesis_response.choices[0].message.content

                    # FEATURE #210: Post-process to fix blank price placeholders
                    synthesized_content = self._fix_blank_price_placeholders(
                        synthesized_content, truncated_results, last_message
                    )

                    # FEATURE #318: Detect and enhance "not found" responses with suggestions (forced RAG path)
                    user_lang_318_forced = self._detect_language(last_message)
                    synthesized_content, was_enhanced_318_forced = self._detect_and_enhance_not_found_response(
                        synthesized_content=synthesized_content,
                        query=last_message,
                        truncated_results=truncated_results,
                        user_lang=user_lang_318_forced
                    )

                    # FEATURE #181: Validate RAG citations and detect hallucinations
                    source_list = list(doc_results.keys())
                    hallucination_detected = False
                    hallucinated_docs = []

                    # Extract document citations from the response (skip if already enhanced by #318)
                    cited_docs = self._extract_document_citations(synthesized_content) if not was_enhanced_318_forced else []
                    if cited_docs:
                        valid_citations, hallucinated_docs, hallucination_detected = self._validate_citations(
                            cited_docs, source_list
                        )

                        if hallucination_detected:
                            logger.warning(f"[Feature #181] Hallucination detected in forced RAG response: {hallucinated_docs}")
                            # Strip hallucinated citations from response
                            synthesized_content = self._strip_hallucinated_citations(
                                synthesized_content, hallucinated_docs, source_list
                            )

                    # PROGRAMMATICALLY append sources to ensure they always appear
                    # (LLM often forgets to cite sources even when instructed)
                    if source_list:
                        # Remove any existing Sources line first (we'll add a clean one)
                        synthesized_content = re.sub(r'\n\n\*?\*?[Ss]ources?\*?\*?[:\s]+[^\n]+', '', synthesized_content)
                        synthesized_content += f"\n\n**Sources:** {', '.join(source_list)}"

                    logger.info(f"[FEATURE #95] RAG synthesis completed successfully")

                    # Build tool_details with optional show_retrieved_chunks debug info
                    show_chunks = settings_store.get('show_retrieved_chunks', False)
                    tool_details_dict = {
                        "provider": "openai_forced_rag",
                        "model": use_model,
                        "tool_arguments": search_args,
                        "tool_result": tool_result,
                        "confidence": "high",
                        "avg_similarity": avg_similarity,
                        "forced": True,
                        "hallucination_detected": hallucination_detected,
                        "hallucinated_documents": hallucinated_docs if hallucination_detected else []
                    }
                    if show_chunks:
                        tool_details_dict["retrieved_chunks"] = [
                            {
                                "document_title": r.get("document_title"),
                                "text": r.get("text", "")[:500] + "..." if len(r.get("text", "")) > 500 else r.get("text", ""),
                                "similarity": r.get("similarity", 0),
                                "chunk_id": r.get("chunk_id")
                            }
                            for r in truncated_results
                        ]

                    _result = {
                        "content": synthesized_content,
                        "tool_used": "vector_search",
                        "tool_details": tool_details_dict,
                        "response_source": "rag",
                        "hallucination_detected": hallucination_detected
                    }
                    # Feature #352: Cache the response
                    if messages:
                        self._cache_response(messages[-1].get("content", ""), _cache_query_embedding, _result, document_ids)
                    return _result
                except Exception as e:
                    logger.error(f"[FEATURE #95] Error synthesizing RAG response: {e}")
                    # Fallback to simple format
                    # FEATURE #137: Use full chunk text instead of truncated 500 chars
                    response_parts = ["Based on searching through your documents:\n"]
                    for doc_title, doc_chunks in doc_results.items():
                        response_parts.append(f"\n**From \"{doc_title}\":**\n")
                        for chunk in doc_chunks[:2]:
                            text = chunk.get("text", "")
                            # Use full text, or truncate only if extremely long (>2000 chars)
                            if len(text) > 2000:
                                text = text[:2000] + "..."
                            response_parts.append(f"> {text}\n")
                    response_parts.append(f"\n**Sources:** {', '.join(doc_results.keys())}")

                    return {
                        "content": "\n".join(response_parts),
                        "tool_used": "vector_search",
                        "tool_details": {
                            "provider": "openai_forced_rag",
                            "model": use_model,
                            "tool_arguments": search_args,
                            "tool_result": tool_result,
                            "forced": True
                        }
                    }
            else:
                logger.info(f"[FEATURE #95] Skipping forced RAG - has_unstructured={has_unstructured}, has_embeddings={has_embeddings}, is_non_document_query={is_non_document_query}")

        try:
            # Prepare messages with system prompt
            chat_messages = [
                {"role": "system", "content": self.get_system_prompt()}
            ]
            chat_messages.extend(messages)

            # Call OpenAI API with tools
            response = client.chat.completions.create(
                model=use_model,
                messages=chat_messages,
                tools=self.get_tools(),
                tool_choice="auto",
                temperature=0.7,
                max_tokens=2000
            )

            response_message = response.choices[0].message

            # Check if model wants to use a tool
            if response_message.tool_calls:
                tool_call = response_message.tool_calls[0]
                tool_name = tool_call.function.name
                tool_arguments = json.loads(tool_call.function.arguments)

                logger.info(f"Tool called: {tool_name} with arguments: {tool_arguments}")

                # Execute the tool
                tool_result = self.execute_tool(tool_name, tool_arguments)

                logger.info(f"Tool result: {tool_result}")

                # Add tool response to messages and get final response
                chat_messages.append(response_message.model_dump())
                chat_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result)
                })

                # Get final response incorporating tool result
                final_response = client.chat.completions.create(
                    model=use_model,
                    messages=chat_messages,
                    temperature=0.7,
                    max_tokens=2000
                )

                assistant_message = final_response.choices[0].message.content

                _result = {
                    "content": assistant_message,
                    "tool_used": tool_name,
                    "tool_details": {
                        "provider": "openai",
                        "model": use_model,
                        "tool_arguments": tool_arguments,
                        "tool_result": tool_result
                    },
                    "response_source": "rag"
                }
                # Feature #352: Cache the response
                if messages:
                    self._cache_response(messages[-1].get("content", ""), _cache_query_embedding, _result, document_ids)
                return _result
            else:
                # No tool called - check anti-hallucination fallback
                assistant_message = response_message.content

                # Anti-hallucination guardrail for OpenAI: If no tool was called but documents exist,
                # force a vector search to ground the response in documents.
                try:
                    ah_documents = _get_documents_sync()
                    ah_has_unstructured = any(d.document_type == "unstructured" for d in ah_documents)
                    ah_has_embeddings = embedding_store.get_chunk_count() > 0
                    if ah_has_unstructured and ah_has_embeddings and messages:
                        ah_last_msg = messages[-1].get("content", "").lower().strip()
                        ah_non_doc_patterns = [
                            r'^(hello|hi|hey|ciao|buongiorno|salve|buonasera)\b',
                            r'(who are you|what are you|chi sei|come ti chiami)',
                            r'(how are you|come stai|come va)',
                            r'^(thank|thanks|grazie)\b',
                            r'^(bye|goodbye|arrivederci)\b',
                            r'^(ok|okay|va bene|capito)\s*$',
                        ]
                        ah_is_greeting = any(re.search(p, ah_last_msg, re.IGNORECASE) for p in ah_non_doc_patterns)
                        if not ah_is_greeting:
                            logger.warning(f"[Anti-hallucination] OpenAI fallback reached with documents available - forcing vector search")
                            ah_search_args = {"query": messages[-1].get("content", ""), "top_k": 5, "document_ids": document_ids}
                            ah_tool_result = self._execute_vector_search(ah_search_args)
                            ah_results = ah_tool_result.get("results", [])
                            if ah_results:
                                ah_truncated = self._truncate_chunks_to_budget(ah_results[:5], token_budget=3500, min_chunk_chars=1000)
                                ah_valid_chunks, _ = self._filter_valid_chunks(ah_truncated, query=messages[-1].get("content", ""))
                                if ah_valid_chunks:
                                    ah_context_parts = ["Here are the relevant excerpts from your documents:\n\n"]
                                    ah_doc_results = {}
                                    for r in ah_valid_chunks:
                                        dt = r.get("document_title", "Unknown Document")
                                        if dt not in ah_doc_results:
                                            ah_doc_results[dt] = []
                                        ah_doc_results[dt].append(r)
                                    for dt, dchunks in ah_doc_results.items():
                                        ah_context_parts.append(f"=== From document: {dt} ===\n")
                                        for ci, ch in enumerate(dchunks):
                                            ah_context_parts.append(f"[Excerpt {ci+1}]: {ch.get('text', '')}\n\n")
                                        ah_context_parts.append("\n")
                                    ah_context_string = "".join(ah_context_parts)
                                    ah_effective_query = messages[-1].get("content", "")
                                    ah_grounding = f"""{ah_context_string}

User's question: "{ah_effective_query}"

INSTRUCTIONS:
1. ONLY use information that is EXPLICITLY written in the excerpts above
2. Do NOT add any facts, numbers, or details from your general knowledge
3. If the excerpts mention the topic but lack the specific detail asked, say: "The documents discuss this topic but do not specify [the detail]"
4. If the topic is completely absent from the excerpts, say: "I could not find information about this in the documents"

Answer the user's question based STRICTLY on the excerpts above."""
                                    ah_synth_messages = [
                                        {"role": "system", "content": self.get_system_prompt()},
                                        {"role": "user", "content": ah_grounding}
                                    ]
                                    ah_response = client.chat.completions.create(
                                        model=use_model,
                                        messages=ah_synth_messages,
                                        temperature=0.1,
                                        max_tokens=2000
                                    )
                                    ah_content = ah_response.choices[0].message.content
                                    ah_source_list = list(ah_doc_results.keys())
                                    if ah_source_list:
                                        ah_content = re.sub(r'\n\n\*?\*?[Ss]ources?\*?\*?[:\s]+[^\n]+', '', ah_content)
                                        ah_content += f"\n\n**Sources:** {', '.join(ah_source_list)}"
                                    return {
                                        "content": ah_content,
                                        "tool_used": "vector_search",
                                        "tool_details": {"provider": "openai", "model": use_model, "anti_hallucination_fallback": True},
                                        "response_source": "rag"
                                    }
                except Exception as ah_err:
                    logger.warning(f"[Anti-hallucination] OpenAI fallback vector search failed: {ah_err}")

                return {
                    "content": assistant_message,
                    "tool_used": None,
                    "tool_details": {"provider": "openai", "model": use_model},
                    "response_source": "direct"
                }

        except AuthenticationError as e:
            logger.error(f"OpenAI Authentication error: {e}")
            return self._get_api_key_error_response("invalid")
        except RateLimitError as e:
            logger.error(f"OpenAI Rate Limit error: {e}")
            return self._get_api_key_error_response("rate_limit")
        except APIConnectionError as e:
            logger.error(f"OpenAI Connection error: {e}")
            return self._get_api_key_error_response("connection")
        except OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")
            # Check if it's an authentication-related error based on error message
            error_str = str(e).lower()
            if "api key" in error_str or "authentication" in error_str or "401" in error_str or "invalid_api_key" in error_str:
                return self._get_api_key_error_response("invalid")
            elif "rate" in error_str or "limit" in error_str or "429" in error_str:
                return self._get_api_key_error_response("rate_limit")
            elif "connection" in error_str or "timeout" in error_str:
                return self._get_api_key_error_response("connection")
            return {
                "content": f"**OpenAI API Error**\n\nAn error occurred while processing your request.\n\n"
                          f"**Error details:** {str(e)}\n\n"
                          f"**Suggestions:**\n"
                          f"- Try again in a few moments\n"
                          f"- Check your API key in Settings\n"
                          f"- Switch to an Ollama model for local processing",
                "tool_used": None,
                "tool_details": {"error": str(e), "error_type": "openai_api_error"},
                "response_source": "direct"
            }
        except Exception as e:
            logger.error(f"Unexpected error in chat: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return self._get_fallback_response(messages)

    def _get_fallback_response(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Generate a fallback response when API is not available."""
        if not messages:
            return {
                "content": "Hello! How can I help you today?",
                "tool_used": None,
                "tool_details": None,
                "response_source": "direct"
            }

        last_message = messages[-1].get("content", "")

        # Simple pattern matching for common greetings
        greetings = ["hello", "hi", "hey", "ciao", "buongiorno", "salve"]
        if any(g in last_message.lower() for g in greetings):
            return {
                "content": "Hello! I'm your AI assistant. I can help you with questions about your documents once you upload them. Currently, the AI backend is running without an API key configured.\n\nTo enable full AI capabilities:\n1. Get an OpenAI API key from https://platform.openai.com\n2. Add it to your backend/.env file as OPENAI_API_KEY=your-key-here\n3. Restart the backend server\n\nIn the meantime, feel free to upload documents and explore the interface!",
                "tool_used": None,
                "tool_details": {"fallback": True},
                "response_source": "direct"
            }

        # Default response for other messages
        return {
            "content": f"I received your message: \"{last_message}\"\n\nI'm currently running in fallback mode because no AI API key is configured. To enable full AI capabilities:\n\n1. Get an OpenAI API key from https://platform.openai.com\n2. Create a .env file in the backend directory\n3. Add: OPENAI_API_KEY=your-key-here\n4. Restart the backend server\n\nOnce configured, I'll be able to:\n- Answer questions about your documents\n- Analyze tabular data with SQL queries\n- Search through text documents semantically",
            "tool_used": None,
            "tool_details": {"fallback": True},
            "response_source": "direct"
        }


# Singleton instance
_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    """Get or create the AI service instance."""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service
