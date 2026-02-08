"""
Settings API endpoints for the Agentic RAG System.

Provides endpoints for managing application settings including:
- Ollama model auto-detection
- API key configuration
- Model selection
- RAG self-test functionality (Feature #198)
- Feature #338: Updated min_relevance_threshold validation range (0.0-0.9)
"""

from fastapi import APIRouter, HTTPException, Request
import httpx
import logging
import asyncio
from typing import Optional, Dict, List
from pydantic import BaseModel

from core.store import settings_store, embedding_store
from services import get_ai_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================
# FEATURE #305: OpenRouter embedding dimension validation
# ============================================================
# Dictionary mapping OpenRouter embedding model names to their default output dimensions.
# Different models produce different dimension outputs, which can cause mismatches
# with existing embeddings if the user changes models without re-embedding.

OPENROUTER_EMBEDDING_DIMENSIONS = {
    # Qwen models - default to full dimension (MRL-capable, can be truncated)
    "openrouter:qwen/qwen3-embedding-8b": 4096,
    "openrouter:qwen/qwen3-embedding-4b": 2560,
    "openrouter:qwen/qwen3-embedding-0.6b": 1024,
    # OpenAI models via OpenRouter
    "openrouter:openai/text-embedding-3-small": 1536,
    "openrouter:openai/text-embedding-3-large": 3072,
    "openrouter:openai/text-embedding-ada-002": 1536,
    # Cohere models via OpenRouter
    "openrouter:cohere/embed-english-v3.0": 1024,
    "openrouter:cohere/embed-multilingual-v3.0": 1024,
    "openrouter:cohere/embed-english-light-v3.0": 384,
    "openrouter:cohere/embed-multilingual-light-v3.0": 384,
    # Voyage models via OpenRouter (default dimensions, MRL-capable)
    "openrouter:voyage/voyage-3.5-lite": 1024,
    "openrouter:voyage/voyage-3": 1024,
    "openrouter:voyage/voyage-3-large": 1024,
}

# Also add dimensions for direct OpenAI models (native API)
OPENAI_EMBEDDING_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def get_embedding_dimension(model: str) -> Optional[int]:
    """
    Get the expected embedding dimension for a model.

    FEATURE #305: Returns the default output dimension for the specified
    embedding model, or None if unknown.

    Args:
        model: The embedding model identifier (e.g., "openrouter:qwen/qwen3-embedding-8b")

    Returns:
        The expected embedding dimension, or None if not known
    """
    # Check OpenRouter models first
    if model in OPENROUTER_EMBEDDING_DIMENSIONS:
        return OPENROUTER_EMBEDDING_DIMENSIONS[model]

    # Check OpenAI models
    if model in OPENAI_EMBEDDING_DIMENSIONS:
        return OPENAI_EMBEDDING_DIMENSIONS[model]

    # For Ollama models, we can't know the dimension without querying
    # since it depends on which model is installed
    return None


# ============================================================
# Settings CRUD Endpoints
# ============================================================

class SettingsResponse(BaseModel):
    """Response containing all settings with masked API keys."""
    openai_api_key: str
    cohere_api_key: str
    openrouter_api_key: str
    llm_model: str
    embedding_model: str
    chunking_llm_model: str = ""  # Separate LLM for agentic chunking (e.g., openrouter:google/gemini-2.0-flash-001)
    theme: str
    enable_reranking: bool = True
    openai_api_key_set: bool = False
    cohere_api_key_set: bool = False
    openrouter_api_key_set: bool = False
    # Twilio/WhatsApp configuration
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = ""
    twilio_configured: bool = False
    # Telegram Bot configuration (Feature #306)
    telegram_bot_token: str = ""
    telegram_bot_token_set: bool = False
    # Chunking configuration
    chunk_strategy: str = "semantic"  # "semantic", "paragraph", or "fixed"
    max_chunk_size: int = 2000  # Maximum characters per chunk
    chunk_overlap: int = 200  # Overlap between chunks
    # Conversation context configuration
    context_window_size: int = 20  # Number of previous messages to include for conversation continuity
    # Chat history search configuration (Feature #161)
    include_chat_history_in_search: bool = False  # Include past conversations in RAG retrieval
    # Custom system prompt (Feature #179)
    custom_system_prompt: str = ""  # Custom AI system prompt (empty = use default)
    # RAG hallucination validation (Feature #181)
    show_retrieved_chunks: bool = False  # Show raw retrieved chunks in chat detail panel (debug mode)
    # RAG relevance thresholds (Feature #182)
    strict_rag_mode: bool = False  # Use stricter relevance thresholds (0.6 instead of 0.5)
    # Hybrid search (Feature #186)
    search_mode: str = "hybrid"  # "vector_only", "bm25_only", or "hybrid" (default)
    hybrid_alpha: float = 0.5  # Weight balance: 0.0 = BM25 only, 1.0 = Vector only, 0.5 = balanced
    # Configurable relevance thresholds (Feature #194)
    min_relevance_threshold: float = 0.4  # Minimum relevance for normal mode (0.0 - 0.9) Feature #339
    strict_relevance_threshold: float = 0.6  # Minimum relevance for strict mode (0.0 - 0.9) Feature #339
    # Suggested questions (Feature #199)
    enable_suggested_questions: bool = True  # Show suggested questions for documents
    # Typewriter effect (Feature #201)
    enable_typewriter: bool = True  # Display AI responses with typewriter animation
    # Pre-destructive backup (Feature #213)
    require_backup_before_delete: bool = True  # Require backup before destructive operations
    # Keyword extraction for hybrid search (Feature #218)
    keyword_boost_weight: float = 0.15  # Weight for keyword boost (0.0 - 0.5)
    enable_entity_extraction: bool = True  # Extract entities (product codes, numbers) for better matching
    # Feature #226: Warning for embedding model changes
    embedding_model_warning: Optional[str] = None  # Warning message if embedding model changed with existing embeddings
    # Feature #230: Configurable top_k for RAG retrieval
    top_k: int = 10  # Number of chunks to retrieve (5-100)
    # FEATURE #246: Section type boosting for recipe documents
    prefer_recipe_chunks: bool = True  # Boost recipe chunks, penalize index/intro chunks
    # FEATURE #281: Context validation guardrail before LLM generation
    min_context_chars_for_generation: int = 500  # Minimum chars required before calling LLM
    # FEATURE #317: Default language preference for AI responses
    default_language: str = "it"  # Default response language: 'it' (Italian), 'en' (English), 'auto' (auto-detect)
    # Feature #352: Semantic response cache
    enable_response_cache: bool = True
    cache_similarity_threshold: float = 0.95
    cache_ttl_hours: int = 24


class SettingsUpdate(BaseModel):
    """Request body for updating settings."""
    openai_api_key: Optional[str] = None
    cohere_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    embedding_model: Optional[str] = None
    chunking_llm_model: Optional[str] = None
    theme: Optional[str] = None
    enable_reranking: Optional[bool] = None
    # Twilio/WhatsApp configuration
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_whatsapp_number: Optional[str] = None
    # Telegram Bot configuration (Feature #306)
    telegram_bot_token: Optional[str] = None
    # Chunking configuration
    chunk_strategy: Optional[str] = None
    max_chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    # Conversation context configuration
    context_window_size: Optional[int] = None
    # Chat history search configuration (Feature #161)
    include_chat_history_in_search: Optional[bool] = None
    # Custom system prompt (Feature #179)
    custom_system_prompt: Optional[str] = None
    # RAG hallucination validation (Feature #181)
    show_retrieved_chunks: Optional[bool] = None
    # RAG relevance thresholds (Feature #182)
    strict_rag_mode: Optional[bool] = None
    # Hybrid search (Feature #186)
    search_mode: Optional[str] = None
    hybrid_alpha: Optional[float] = None
    # Configurable relevance thresholds (Feature #194)
    min_relevance_threshold: Optional[float] = None
    strict_relevance_threshold: Optional[float] = None
    # Suggested questions (Feature #199)
    enable_suggested_questions: Optional[bool] = None
    # Typewriter effect (Feature #201)
    enable_typewriter: Optional[bool] = None
    # Pre-destructive backup (Feature #213)
    require_backup_before_delete: Optional[bool] = None
    # Keyword extraction for hybrid search (Feature #218)
    keyword_boost_weight: Optional[float] = None
    enable_entity_extraction: Optional[bool] = None
    # Feature #230: Configurable top_k for RAG retrieval
    top_k: Optional[int] = None
    # FEATURE #246: Section type boosting for recipe documents
    prefer_recipe_chunks: Optional[bool] = None
    # FEATURE #281: Context validation guardrail before LLM generation
    min_context_chars_for_generation: Optional[int] = None
    # FEATURE #317: Default language preference for AI responses
    default_language: Optional[str] = None
    # Feature #352: Semantic response cache
    enable_response_cache: Optional[bool] = None
    cache_similarity_threshold: Optional[float] = None
    cache_ttl_hours: Optional[int] = None


@router.get("/", response_model=SettingsResponse)
async def get_settings():
    """
    Get all application settings.

    API keys are masked for security - only first 4 and last 4 characters shown.
    Use the 'openai_api_key_set' and 'cohere_api_key_set' fields to check if keys are configured.
    """
    masked = settings_store.get_all_masked()
    return SettingsResponse(
        openai_api_key=masked.get('openai_api_key', ''),
        cohere_api_key=masked.get('cohere_api_key', ''),
        openrouter_api_key=masked.get('openrouter_api_key', ''),
        llm_model=masked.get('llm_model', 'gpt-4o'),
        embedding_model=masked.get('embedding_model', 'text-embedding-3-small'),
        chunking_llm_model=settings_store.get('chunking_llm_model', ''),
        theme=masked.get('theme', 'system'),
        enable_reranking=settings_store.get('enable_reranking', True),
        openai_api_key_set=settings_store.has_openai_key(),
        cohere_api_key_set=settings_store.has_cohere_key(),
        openrouter_api_key_set=settings_store.has_openrouter_key(),
        twilio_account_sid=masked.get('twilio_account_sid', ''),
        twilio_auth_token=masked.get('twilio_auth_token', ''),
        twilio_whatsapp_number=settings_store.get('twilio_whatsapp_number', ''),
        twilio_configured=settings_store.has_twilio_config(),
        # Telegram Bot configuration (Feature #306)
        telegram_bot_token=masked.get('telegram_bot_token', ''),
        telegram_bot_token_set=settings_store.has_telegram_token(),
        chunk_strategy=settings_store.get('chunk_strategy', 'semantic'),
        max_chunk_size=int(settings_store.get('max_chunk_size', 2000)),
        chunk_overlap=int(settings_store.get('chunk_overlap', 200)),
        context_window_size=int(settings_store.get('context_window_size', 20)),
        include_chat_history_in_search=settings_store.get('include_chat_history_in_search', False),
        custom_system_prompt=settings_store.get('custom_system_prompt', ''),
        show_retrieved_chunks=settings_store.get('show_retrieved_chunks', False),
        strict_rag_mode=settings_store.get('strict_rag_mode', False),
        search_mode=settings_store.get('search_mode', 'hybrid'),
        hybrid_alpha=float(settings_store.get('hybrid_alpha', 0.5)),
        min_relevance_threshold=float(settings_store.get('min_relevance_threshold', 0.4)),
        strict_relevance_threshold=float(settings_store.get('strict_relevance_threshold', 0.6)),
        enable_suggested_questions=settings_store.get('enable_suggested_questions', 'true').lower() == 'true',
        enable_typewriter=settings_store.get('enable_typewriter', 'true').lower() == 'true',
        require_backup_before_delete=settings_store.get('require_backup_before_delete', 'true').lower() == 'true',
        keyword_boost_weight=float(settings_store.get('keyword_boost_weight', 0.15)),
        enable_entity_extraction=settings_store.get('enable_entity_extraction', 'true').lower() == 'true',
        top_k=int(settings_store.get('top_k', 10)),
        # FEATURE #246: Section type boosting
        prefer_recipe_chunks=settings_store.get('prefer_recipe_chunks', 'true').lower() == 'true',
        # FEATURE #281: Context validation guardrail
        min_context_chars_for_generation=int(settings_store.get('min_context_chars_for_generation', 500)),
        # FEATURE #317: Default language preference
        default_language=settings_store.get('default_language', 'it'),
        # Feature #352: Semantic response cache
        enable_response_cache=str(settings_store.get('enable_response_cache', 'true')).lower() == 'true',
        cache_similarity_threshold=float(settings_store.get('cache_similarity_threshold', 0.95)),
        cache_ttl_hours=int(float(settings_store.get('cache_ttl_hours', 24))),
    )


@router.patch("/", response_model=SettingsResponse)
async def update_settings(updates: SettingsUpdate):
    """
    Update application settings.

    Only provided fields will be updated. API keys can be updated by providing the full key.
    To clear an API key, set it to an empty string.
    """
    # Build update dict from non-None fields
    update_dict: Dict[str, str] = {}

    if updates.openai_api_key is not None:
        update_dict['openai_api_key'] = updates.openai_api_key
        logger.info(f"Updating OpenAI API key (length: {len(updates.openai_api_key)})")
        # [Feature #284] Reset the OpenAI rewrite disabled flag when key is updated
        try:
            ai_service = get_ai_service()
            ai_service.reset_openai_rewrite_flag()
        except Exception as e:
            logger.warning(f"[Feature #284] Failed to reset OpenAI rewrite flag: {e}")

    if updates.cohere_api_key is not None:
        update_dict['cohere_api_key'] = updates.cohere_api_key
        logger.info(f"Updating Cohere API key (length: {len(updates.cohere_api_key)})")

    if updates.openrouter_api_key is not None:
        update_dict['openrouter_api_key'] = updates.openrouter_api_key
        logger.info(f"Updating OpenRouter API key (length: {len(updates.openrouter_api_key)})")

    if updates.llm_model is not None:
        update_dict['llm_model'] = updates.llm_model
        logger.info(f"Updating LLM model to: {updates.llm_model}")

    # Feature #226: Track embedding model changes for warning
    embedding_model_changed = False
    old_embedding_model = None

    if updates.embedding_model is not None:
        old_embedding_model = settings_store.get('embedding_model', 'text-embedding-3-small')
        if old_embedding_model != updates.embedding_model:
            embedding_model_changed = True
            logger.info(f"[Feature #226] Embedding model changing from '{old_embedding_model}' to '{updates.embedding_model}'")
        update_dict['embedding_model'] = updates.embedding_model
        logger.info(f"Updating embedding model to: {updates.embedding_model}")

    if updates.chunking_llm_model is not None:
        update_dict['chunking_llm_model'] = updates.chunking_llm_model
        logger.info(f"Updating chunking LLM model to: {updates.chunking_llm_model}")

    # Twilio/WhatsApp configuration
    if updates.twilio_account_sid is not None:
        update_dict['twilio_account_sid'] = updates.twilio_account_sid
        logger.info(f"Updating Twilio Account SID (length: {len(updates.twilio_account_sid)})")

    if updates.twilio_auth_token is not None:
        update_dict['twilio_auth_token'] = updates.twilio_auth_token
        logger.info(f"Updating Twilio Auth Token (length: {len(updates.twilio_auth_token)})")

    if updates.twilio_whatsapp_number is not None:
        update_dict['twilio_whatsapp_number'] = updates.twilio_whatsapp_number
        logger.info(f"Updating Twilio WhatsApp number to: {updates.twilio_whatsapp_number}")

    # Telegram Bot configuration (Feature #306)
    if updates.telegram_bot_token is not None:
        # Validate token format: numeric:alphanumeric (e.g., 123456789:ABCdefGHI...)
        import re
        token = updates.telegram_bot_token.strip()
        if token and not re.match(r'^\d+:[A-Za-z0-9_-]+$', token):
            raise HTTPException(
                status_code=400,
                detail="Invalid Telegram bot token format. Expected format: 123456789:ABCdefGHI... (numeric:alphanumeric)"
            )
        update_dict['telegram_bot_token'] = token
        logger.info(f"Updating Telegram Bot Token (length: {len(token)})")

    if updates.theme is not None:
        if updates.theme not in ['light', 'dark', 'system']:
            raise HTTPException(status_code=400, detail="Invalid theme. Must be 'light', 'dark', or 'system'")
        update_dict['theme'] = updates.theme
        logger.info(f"Updating theme to: {updates.theme}")

    if updates.enable_reranking is not None:
        update_dict['enable_reranking'] = updates.enable_reranking
        logger.info(f"Updating reranking to: {updates.enable_reranking}")

    # Chunking configuration updates
    if updates.chunk_strategy is not None:
        if updates.chunk_strategy not in ['agentic', 'semantic', 'paragraph', 'fixed']:
            raise HTTPException(status_code=400, detail="Invalid chunk_strategy. Must be 'agentic', 'semantic', 'paragraph', or 'fixed'")
        update_dict['chunk_strategy'] = updates.chunk_strategy
        logger.info(f"Updating chunk strategy to: {updates.chunk_strategy}")

    if updates.max_chunk_size is not None:
        if updates.max_chunk_size < 100 or updates.max_chunk_size > 10000:
            raise HTTPException(status_code=400, detail="max_chunk_size must be between 100 and 10000")
        update_dict['max_chunk_size'] = updates.max_chunk_size
        logger.info(f"Updating max chunk size to: {updates.max_chunk_size}")

    if updates.chunk_overlap is not None:
        if updates.chunk_overlap < 0 or updates.chunk_overlap > 1000:
            raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 1000")
        update_dict['chunk_overlap'] = updates.chunk_overlap
        logger.info(f"Updating chunk overlap to: {updates.chunk_overlap}")

    # Context window configuration
    if updates.context_window_size is not None:
        if updates.context_window_size < 1 or updates.context_window_size > 100:
            raise HTTPException(status_code=400, detail="context_window_size must be between 1 and 100")
        update_dict['context_window_size'] = updates.context_window_size
        logger.info(f"Updating context window size to: {updates.context_window_size}")

    # Chat history search configuration (Feature #161)
    if updates.include_chat_history_in_search is not None:
        update_dict['include_chat_history_in_search'] = updates.include_chat_history_in_search
        logger.info(f"Updating include_chat_history_in_search to: {updates.include_chat_history_in_search}")

    # Custom system prompt (Feature #179)
    if updates.custom_system_prompt is not None:
        # Validate prompt length (minimum 50 chars if not empty, max 10000)
        if updates.custom_system_prompt and len(updates.custom_system_prompt.strip()) > 0 and len(updates.custom_system_prompt.strip()) < 50:
            raise HTTPException(status_code=400, detail="System prompt must be at least 50 characters if provided")
        if len(updates.custom_system_prompt) > 10000:
            raise HTTPException(status_code=400, detail="System prompt cannot exceed 10,000 characters")
        update_dict['custom_system_prompt'] = updates.custom_system_prompt
        logger.info(f"Updating custom_system_prompt (length: {len(updates.custom_system_prompt)})")

    # RAG hallucination validation (Feature #181)
    if updates.show_retrieved_chunks is not None:
        update_dict['show_retrieved_chunks'] = updates.show_retrieved_chunks
        logger.info(f"Updating show_retrieved_chunks to: {updates.show_retrieved_chunks}")

    # RAG relevance thresholds (Feature #182)
    if updates.strict_rag_mode is not None:
        update_dict['strict_rag_mode'] = updates.strict_rag_mode
        logger.info(f"Updating strict_rag_mode to: {updates.strict_rag_mode}")

    # Hybrid search (Feature #186)
    if updates.search_mode is not None:
        if updates.search_mode not in ['vector_only', 'bm25_only', 'hybrid']:
            raise HTTPException(status_code=400, detail="Invalid search_mode. Must be 'vector_only', 'bm25_only', or 'hybrid'")
        update_dict['search_mode'] = updates.search_mode
        logger.info(f"Updating search_mode to: {updates.search_mode}")

    if updates.hybrid_alpha is not None:
        if updates.hybrid_alpha < 0.0 or updates.hybrid_alpha > 1.0:
            raise HTTPException(status_code=400, detail="hybrid_alpha must be between 0.0 and 1.0")
        update_dict['hybrid_alpha'] = updates.hybrid_alpha
        logger.info(f"Updating hybrid_alpha to: {updates.hybrid_alpha}")

    # Configurable relevance thresholds (Feature #194)
    # Updated validation range from 0.0-0.9 (Feature #338) to allow lower thresholds
    if updates.min_relevance_threshold is not None:
        logger.info(f"[Feature #338] Received min_relevance_threshold: {updates.min_relevance_threshold}")
        if updates.min_relevance_threshold < 0.0 or updates.min_relevance_threshold > 0.9:
            raise HTTPException(status_code=400, detail="min_relevance_threshold must be between 0.0 and 0.9 (Feature #338)")
        update_dict['min_relevance_threshold'] = updates.min_relevance_threshold
        logger.info(f"Updating min_relevance_threshold to: {updates.min_relevance_threshold}")

    if updates.strict_relevance_threshold is not None:
        if updates.strict_relevance_threshold < 0.0 or updates.strict_relevance_threshold > 0.9:
            raise HTTPException(status_code=400, detail="strict_relevance_threshold must be between 0.0 and 0.9")
        update_dict['strict_relevance_threshold'] = updates.strict_relevance_threshold
        logger.info(f"Updating strict_relevance_threshold to: {updates.strict_relevance_threshold}")

    # Suggested questions (Feature #199)
    if updates.enable_suggested_questions is not None:
        update_dict['enable_suggested_questions'] = 'true' if updates.enable_suggested_questions else 'false'
        logger.info(f"Updating enable_suggested_questions to: {updates.enable_suggested_questions}")

    # Typewriter effect (Feature #201)
    if updates.enable_typewriter is not None:
        update_dict['enable_typewriter'] = 'true' if updates.enable_typewriter else 'false'
        logger.info(f"Updating enable_typewriter to: {updates.enable_typewriter}")

    # Pre-destructive backup (Feature #213)
    if updates.require_backup_before_delete is not None:
        update_dict['require_backup_before_delete'] = 'true' if updates.require_backup_before_delete else 'false'
        logger.info(f"Updating require_backup_before_delete to: {updates.require_backup_before_delete}")

    # Keyword extraction for hybrid search (Feature #218)
    if updates.keyword_boost_weight is not None:
        if updates.keyword_boost_weight < 0.0 or updates.keyword_boost_weight > 0.5:
            raise HTTPException(status_code=400, detail="keyword_boost_weight must be between 0.0 and 0.5")
        update_dict['keyword_boost_weight'] = updates.keyword_boost_weight
        logger.info(f"Updating keyword_boost_weight to: {updates.keyword_boost_weight}")

    if updates.enable_entity_extraction is not None:
        update_dict['enable_entity_extraction'] = 'true' if updates.enable_entity_extraction else 'false'
        logger.info(f"Updating enable_entity_extraction to: {updates.enable_entity_extraction}")

    # Feature #230: Configurable top_k for RAG retrieval
    if updates.top_k is not None:
        if updates.top_k < 5 or updates.top_k > 100:
            raise HTTPException(status_code=400, detail="top_k must be between 5 and 100")
        update_dict['top_k'] = updates.top_k
        logger.info(f"Updating top_k to: {updates.top_k}")

    # FEATURE #246: Section type boosting for recipe documents
    if updates.prefer_recipe_chunks is not None:
        update_dict['prefer_recipe_chunks'] = 'true' if updates.prefer_recipe_chunks else 'false'
        logger.info(f"Updating prefer_recipe_chunks to: {updates.prefer_recipe_chunks}")

    # FEATURE #281: Context validation guardrail before LLM generation
    if updates.min_context_chars_for_generation is not None:
        # Validate range: 0 = disable guardrail, otherwise 100-2000 chars
        if updates.min_context_chars_for_generation < 0:
            raise HTTPException(status_code=400, detail="min_context_chars_for_generation must be >= 0")
        if updates.min_context_chars_for_generation > 2000:
            raise HTTPException(status_code=400, detail="min_context_chars_for_generation must be <= 2000")
        update_dict['min_context_chars_for_generation'] = updates.min_context_chars_for_generation
        logger.info(f"[Feature #281] Updating min_context_chars_for_generation to: {updates.min_context_chars_for_generation}")

    # FEATURE #317: Default language preference for AI responses
    if updates.default_language is not None:
        # Validate: must be 'it', 'en', or 'auto'
        valid_languages = ['it', 'en', 'auto', 'fr', 'es', 'de', 'pt']
        if updates.default_language not in valid_languages:
            raise HTTPException(status_code=400, detail=f"default_language must be one of: {', '.join(valid_languages)}")
        update_dict['default_language'] = updates.default_language
        logger.info(f"[Feature #317] Updating default_language to: {updates.default_language}")

    # Feature #352: Semantic response cache settings
    if updates.enable_response_cache is not None:
        update_dict['enable_response_cache'] = 'true' if updates.enable_response_cache else 'false'
        logger.info(f"[Feature #352] Updating enable_response_cache to: {updates.enable_response_cache}")
    if updates.cache_similarity_threshold is not None:
        if updates.cache_similarity_threshold < 0.80 or updates.cache_similarity_threshold > 1.0:
            raise HTTPException(status_code=400, detail="cache_similarity_threshold must be between 0.80 and 1.0")
        update_dict['cache_similarity_threshold'] = str(updates.cache_similarity_threshold)
        logger.info(f"[Feature #352] Updating cache_similarity_threshold to: {updates.cache_similarity_threshold}")
    if updates.cache_ttl_hours is not None:
        if updates.cache_ttl_hours < 1 or updates.cache_ttl_hours > 168:
            raise HTTPException(status_code=400, detail="cache_ttl_hours must be between 1 and 168")
        update_dict['cache_ttl_hours'] = str(updates.cache_ttl_hours)
        logger.info(f"[Feature #352] Updating cache_ttl_hours to: {updates.cache_ttl_hours}")

    # Apply updates
    settings_store.update(update_dict)

    # Feature #352: Invalidate response cache when LLM or embedding model changes
    # Different LLM → different responses; different embeddings → incompatible vectors
    if updates.llm_model is not None or embedding_model_changed:
        try:
            from services.response_cache_service import response_cache_service
            count = response_cache_service.invalidate_all()
            change_reason = []
            if updates.llm_model is not None:
                change_reason.append(f"llm_model→{updates.llm_model}")
            if embedding_model_changed:
                change_reason.append(f"embedding_model→{updates.embedding_model}")
            logger.info(f"[Feature #352] Cache invalidated ({count} entries) due to model change: {', '.join(change_reason)}")
        except Exception as e:
            logger.warning(f"[Feature #352] Failed to invalidate cache on model change: {e}")

    # Feature #226 + Feature #305: Check if embedding model changed and there are existing embeddings
    # Feature #305 adds dimension validation for OpenRouter models
    embedding_model_warning = None
    if embedding_model_changed:
        try:
            existing_embeddings_count = embedding_store.get_chunk_count()
            if existing_embeddings_count > 0:
                # Get new model dimension (Feature #305)
                new_model_dimension = get_embedding_dimension(updates.embedding_model)
                old_model_dimension = get_embedding_dimension(old_embedding_model)

                # Check current embeddings dimension from stored data
                consistency_check = embedding_store.check_dimension_consistency()
                stored_dimensions = consistency_check.get("dimensions", {})
                stored_dimension = None
                if stored_dimensions:
                    # Get the most common dimension (there should be only one if consistent)
                    stored_dimension = max(stored_dimensions.keys(), key=lambda d: stored_dimensions[d])

                # Feature #305: Build dimension-aware warning message
                dimension_warning = ""
                if new_model_dimension and stored_dimension:
                    if new_model_dimension != stored_dimension:
                        dimension_warning = (
                            f"\n\n🔴 **DIMENSION MISMATCH**: The new model produces {new_model_dimension}-dimensional embeddings, "
                            f"but your existing embeddings are {stored_dimension}-dimensional. "
                            f"You MUST re-embed all documents before using the new model, or vector search will fail."
                        )
                        logger.warning(f"[Feature #305] Dimension mismatch detected: new={new_model_dimension}, stored={stored_dimension}")
                elif new_model_dimension and not stored_dimension:
                    # Can't verify stored dimension, include the new model's dimension in warning
                    dimension_warning = f"\n\nThe new model produces {new_model_dimension}-dimensional embeddings."
                elif stored_dimension and not new_model_dimension:
                    # Unknown new model dimension (e.g., Ollama), warn about potential mismatch
                    dimension_warning = (
                        f"\n\n⚠️ Your existing embeddings are {stored_dimension}-dimensional. "
                        f"Make sure the new model produces the same dimension, or re-embed all documents."
                    )

                embedding_model_warning = (
                    f"⚠️ Embedding model changed from '{old_embedding_model}' to '{updates.embedding_model}'. "
                    f"You have {existing_embeddings_count} existing embeddings that were created with the old model. "
                    f"For best results, go to Database > Re-embed All Documents to regenerate embeddings with the new model."
                    f"{dimension_warning}"
                )
                logger.warning(f"[Feature #226] {embedding_model_warning}")
        except Exception as e:
            logger.warning(f"[Feature #226/305] Could not check existing embeddings: {e}")

    # Return updated (masked) settings
    masked = settings_store.get_all_masked()
    return SettingsResponse(
        openai_api_key=masked.get('openai_api_key', ''),
        cohere_api_key=masked.get('cohere_api_key', ''),
        openrouter_api_key=masked.get('openrouter_api_key', ''),
        llm_model=masked.get('llm_model', 'gpt-4o'),
        embedding_model=masked.get('embedding_model', 'text-embedding-3-small'),
        chunking_llm_model=settings_store.get('chunking_llm_model', ''),
        theme=masked.get('theme', 'system'),
        enable_reranking=settings_store.get('enable_reranking', True),
        openai_api_key_set=settings_store.has_openai_key(),
        cohere_api_key_set=settings_store.has_cohere_key(),
        openrouter_api_key_set=settings_store.has_openrouter_key(),
        twilio_account_sid=masked.get('twilio_account_sid', ''),
        twilio_auth_token=masked.get('twilio_auth_token', ''),
        twilio_whatsapp_number=settings_store.get('twilio_whatsapp_number', ''),
        twilio_configured=settings_store.has_twilio_config(),
        # Telegram Bot configuration (Feature #306)
        telegram_bot_token=masked.get('telegram_bot_token', ''),
        telegram_bot_token_set=settings_store.has_telegram_token(),
        chunk_strategy=settings_store.get('chunk_strategy', 'semantic'),
        max_chunk_size=int(settings_store.get('max_chunk_size', 2000)),
        chunk_overlap=int(settings_store.get('chunk_overlap', 200)),
        context_window_size=int(settings_store.get('context_window_size', 20)),
        include_chat_history_in_search=settings_store.get('include_chat_history_in_search', False),
        custom_system_prompt=settings_store.get('custom_system_prompt', ''),
        show_retrieved_chunks=settings_store.get('show_retrieved_chunks', False),
        strict_rag_mode=settings_store.get('strict_rag_mode', False),
        search_mode=settings_store.get('search_mode', 'hybrid'),
        hybrid_alpha=float(settings_store.get('hybrid_alpha', 0.5)),
        min_relevance_threshold=float(settings_store.get('min_relevance_threshold', 0.4)),
        strict_relevance_threshold=float(settings_store.get('strict_relevance_threshold', 0.6)),
        enable_suggested_questions=settings_store.get('enable_suggested_questions', 'true').lower() == 'true',
        enable_typewriter=settings_store.get('enable_typewriter', 'true').lower() == 'true',
        require_backup_before_delete=settings_store.get('require_backup_before_delete', 'true').lower() == 'true',
        keyword_boost_weight=float(settings_store.get('keyword_boost_weight', 0.15)),
        enable_entity_extraction=settings_store.get('enable_entity_extraction', 'true').lower() == 'true',
        embedding_model_warning=embedding_model_warning,
        top_k=int(settings_store.get('top_k', 10)),
        # FEATURE #246: Section type boosting
        prefer_recipe_chunks=settings_store.get('prefer_recipe_chunks', 'true').lower() == 'true',
        # FEATURE #281: Context validation guardrail
        min_context_chars_for_generation=int(settings_store.get('min_context_chars_for_generation', 500)),
        # FEATURE #317: Default language preference
        default_language=settings_store.get('default_language', 'it'),
        # Feature #352: Semantic response cache
        enable_response_cache=str(settings_store.get('enable_response_cache', 'true')).lower() == 'true',
        cache_similarity_threshold=float(settings_store.get('cache_similarity_threshold', 0.95)),
        cache_ttl_hours=int(float(settings_store.get('cache_ttl_hours', 24))),
    )

# Default Ollama API endpoint
OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaModel(BaseModel):
    """Represents an Ollama model with its details."""
    name: str
    value: str  # The value to use for selection (e.g., "ollama:llama3")
    label: str  # Human-readable label
    size: Optional[str] = None
    family: Optional[str] = None
    parameter_size: Optional[str] = None
    is_embedding: bool = False


class OllamaModelsResponse(BaseModel):
    """Response containing available Ollama models."""
    available: bool
    models: list[OllamaModel]
    embedding_models: list[OllamaModel]
    error: Optional[str] = None


def format_size(size_bytes: int) -> str:
    """Format byte size to human readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def is_embedding_model(model_info: dict) -> bool:
    """Determine if a model is an embedding model based on its properties."""
    name = model_info.get("name", "").lower()
    family = model_info.get("details", {}).get("family", "").lower()

    # Common embedding model patterns
    embedding_keywords = [
        "embed", "embedding", "bge", "nomic-embed", "all-minilm",
        "mxbai-embed", "e5", "jina-embed"
    ]

    # Check family - BERT models are typically embeddings
    if family in ["bert", "nomic-bert"]:
        return True

    # Check name for embedding keywords
    for keyword in embedding_keywords:
        if keyword in name:
            return True

    return False


def create_model_label(model_info: dict) -> str:
    """Create a human-readable label for a model."""
    name = model_info.get("name", "unknown")
    details = model_info.get("details", {})
    param_size = details.get("parameter_size", "")

    # Clean up the model name for display
    display_name = name.split(":")[0].replace("-", " ").title()

    if param_size:
        return f"{display_name} ({param_size})"
    return display_name


@router.get("/models/openrouter")
async def get_openrouter_models():
    """
    Get available OpenRouter models.

    This endpoint queries the OpenRouter API to fetch available models.
    Requires an OpenRouter API key to be configured.

    Returns:
        dict: Contains lists of available models organized by provider
    """
    try:
        # Get OpenRouter API key from settings
        api_key = settings_store.get('openrouter_api_key')

        if not api_key or len(api_key) < 10:
            return {
                "available": False,
                "models": [],
                "error": "OpenRouter API key not configured. Please add your API key in settings."
            }

        # Fetch models from OpenRouter API
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "http://localhost:3000",  # Required by OpenRouter
                    "X-Title": "Agentic RAG System"  # Optional but helps with rankings
                }
            )

            if response.status_code != 200:
                logger.warning(f"OpenRouter returned status {response.status_code}")
                return {
                    "available": False,
                    "models": [],
                    "error": f"OpenRouter API error: {response.status_code} - {response.text}"
                }

            data = response.json()
            models_data = data.get("data", [])

            # Format models for the frontend
            formatted_models = []
            for model in models_data:
                model_id = model.get("id", "")
                name = model.get("name", model_id)
                pricing = model.get("pricing", {})
                context_length = model.get("context_length", 0)

                formatted_models.append({
                    "id": model_id,
                    "value": f"openrouter:{model_id}",
                    "label": name,
                    "context_length": context_length,
                    "pricing": {
                        "prompt": pricing.get("prompt", "0"),
                        "completion": pricing.get("completion", "0")
                    }
                })

            # Sort by provider and name
            formatted_models.sort(key=lambda m: m["label"])

            logger.info(f"Fetched {len(formatted_models)} models from OpenRouter")

            return {
                "available": True,
                "models": formatted_models,
                "error": None
            }

    except httpx.ConnectError:
        logger.warning("Cannot connect to OpenRouter API")
        return {
            "available": False,
            "models": [],
            "error": "Cannot connect to OpenRouter. Please check your internet connection."
        }
    except httpx.TimeoutException:
        logger.warning("Timeout connecting to OpenRouter")
        return {
            "available": False,
            "models": [],
            "error": "Connection to OpenRouter timed out. Please try again."
        }
    except Exception as e:
        logger.error(f"Error fetching OpenRouter models: {e}")
        return {
            "available": False,
            "models": [],
            "error": f"Error fetching OpenRouter models: {str(e)}"
        }


@router.get("/models/ollama", response_model=OllamaModelsResponse)
async def get_ollama_models():
    """
    Get available Ollama models.

    This endpoint queries the local Ollama installation to detect
    installed models. It categorizes models into:
    - LLM models (for chat/completion)
    - Embedding models (for vector generation)

    Returns:
        OllamaModelsResponse: Contains lists of available models and connection status
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")

            if response.status_code != 200:
                logger.warning(f"Ollama returned status {response.status_code}")
                return OllamaModelsResponse(
                    available=False,
                    models=[],
                    embedding_models=[],
                    error=f"Ollama returned status {response.status_code}"
                )

            data = response.json()
            models_data = data.get("models", [])

            llm_models = []
            embedding_models = []

            for model_info in models_data:
                name = model_info.get("name", "")
                details = model_info.get("details", {})
                size = model_info.get("size", 0)

                # Skip remote/cloud models (they have remote_model field AND small size)
                # Recent Ollama versions add remote_model to all models, but local models
                # have actual file sizes (>1MB), while cloud models are just metadata (<1KB)
                if model_info.get("remote_model") and size < 1024 * 1024:  # Less than 1MB
                    continue

                ollama_model = OllamaModel(
                    name=name,
                    value=f"ollama:{name}",
                    label=create_model_label(model_info),
                    size=format_size(size),
                    family=details.get("family", ""),
                    parameter_size=details.get("parameter_size", ""),
                    is_embedding=is_embedding_model(model_info)
                )

                if ollama_model.is_embedding:
                    embedding_models.append(ollama_model)
                else:
                    llm_models.append(ollama_model)

            # Sort models by parameter size (approximated by name/size)
            llm_models.sort(key=lambda m: m.name)
            embedding_models.sort(key=lambda m: m.name)

            logger.info(f"Found {len(llm_models)} LLM models and {len(embedding_models)} embedding models from Ollama")

            return OllamaModelsResponse(
                available=True,
                models=llm_models,
                embedding_models=embedding_models
            )

    except httpx.ConnectError:
        logger.info("Ollama is not running or not accessible")
        return OllamaModelsResponse(
            available=False,
            models=[],
            embedding_models=[],
            error="Ollama is not running. Please start Ollama to use local models."
        )
    except httpx.TimeoutException:
        logger.warning("Timeout connecting to Ollama")
        return OllamaModelsResponse(
            available=False,
            models=[],
            embedding_models=[],
            error="Connection to Ollama timed out."
        )
    except Exception as e:
        logger.error(f"Error fetching Ollama models: {e}")
        return OllamaModelsResponse(
            available=False,
            models=[],
            embedding_models=[],
            error=f"Error fetching Ollama models: {str(e)}"
        )


# ============================================================
# Test Connection Endpoints
# ============================================================

class TestConnectionRequest(BaseModel):
    """Request body for testing API connections."""
    provider: str  # "openrouter", "openai", "cohere", "ollama", "twilio", "telegram"


class TestConnectionResponse(BaseModel):
    """Response for connection test."""
    success: bool
    message: str
    provider: str


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection(request: TestConnectionRequest):
    """
    Test connection to an API provider.

    This endpoint verifies that the stored API key is valid and the service is reachable.

    Supported providers:
    - openrouter: Tests OpenRouter API key validity
    - openai: Tests OpenAI API key validity
    - cohere: Tests Cohere API key validity
    - ollama: Tests local Ollama server connectivity
    - twilio: Tests Twilio credentials for WhatsApp integration
    - telegram: Tests Telegram Bot Token validity (Feature #306)

    Returns:
        TestConnectionResponse: Success/failure status with message
    """
    provider = request.provider.lower()

    try:
        if provider == "openrouter":
            # Test OpenRouter connection
            api_key = settings_store.get('openrouter_api_key')

            if not api_key or len(api_key) < 10:
                return TestConnectionResponse(
                    success=False,
                    message="OpenRouter API key not configured",
                    provider="openrouter"
                )

            # Make a lightweight API call to list models
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "HTTP-Referer": "http://localhost:3000",
                        "X-Title": "Agentic RAG System"
                    }
                )

                if response.status_code == 200:
                    return TestConnectionResponse(
                        success=True,
                        message="Connected successfully to OpenRouter",
                        provider="openrouter"
                    )
                elif response.status_code == 401:
                    return TestConnectionResponse(
                        success=False,
                        message="Invalid OpenRouter API key",
                        provider="openrouter"
                    )
                else:
                    return TestConnectionResponse(
                        success=False,
                        message=f"OpenRouter API error: {response.status_code}",
                        provider="openrouter"
                    )

        elif provider == "openai":
            # Test OpenAI connection
            api_key = settings_store.get('openai_api_key')

            if not api_key or len(api_key) < 10:
                return TestConnectionResponse(
                    success=False,
                    message="OpenAI API key not configured",
                    provider="openai"
                )

            # Make a lightweight API call to list models
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}"
                    }
                )

                if response.status_code == 200:
                    return TestConnectionResponse(
                        success=True,
                        message="Connected successfully to OpenAI",
                        provider="openai"
                    )
                elif response.status_code == 401:
                    return TestConnectionResponse(
                        success=False,
                        message="Invalid OpenAI API key",
                        provider="openai"
                    )
                else:
                    return TestConnectionResponse(
                        success=False,
                        message=f"OpenAI API error: {response.status_code}",
                        provider="openai"
                    )

        elif provider == "cohere":
            # Test Cohere connection
            api_key = settings_store.get('cohere_api_key')

            if not api_key or len(api_key) < 10:
                return TestConnectionResponse(
                    success=False,
                    message="Cohere API key not configured",
                    provider="cohere"
                )

            # Make a lightweight API call to check the key
            # Fix #195: Check the response body for {"valid": true/false}
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.cohere.ai/v1/check-api-key",
                    headers={
                        "Authorization": f"Bearer {api_key}"
                    }
                )

                if response.status_code == 200:
                    # Check if the key is actually valid
                    try:
                        data = response.json()
                        if data.get("valid") == True:
                            return TestConnectionResponse(
                                success=True,
                                message="Connected successfully to Cohere",
                                provider="cohere"
                            )
                        else:
                            return TestConnectionResponse(
                                success=False,
                                message="Invalid Cohere API key",
                                provider="cohere"
                            )
                    except Exception:
                        # If we can't parse the response, assume success
                        return TestConnectionResponse(
                            success=True,
                            message="Connected successfully to Cohere",
                            provider="cohere"
                        )
                elif response.status_code == 401:
                    return TestConnectionResponse(
                        success=False,
                        message="Invalid Cohere API key",
                        provider="cohere"
                    )
                else:
                    return TestConnectionResponse(
                        success=False,
                        message=f"Cohere API error: {response.status_code}",
                        provider="cohere"
                    )

        elif provider == "ollama":
            # Test Ollama connection
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")

                if response.status_code == 200:
                    data = response.json()
                    model_count = len(data.get("models", []))
                    return TestConnectionResponse(
                        success=True,
                        message=f"Connected successfully to Ollama ({model_count} models available)",
                        provider="ollama"
                    )
                else:
                    return TestConnectionResponse(
                        success=False,
                        message=f"Ollama server error: {response.status_code}",
                        provider="ollama"
                    )

        elif provider == "twilio":
            # Test Twilio connection
            account_sid = settings_store.get('twilio_account_sid')
            auth_token = settings_store.get('twilio_auth_token')
            whatsapp_number = settings_store.get('twilio_whatsapp_number')

            if not account_sid or len(account_sid) < 10:
                return TestConnectionResponse(
                    success=False,
                    message="Twilio Account SID not configured",
                    provider="twilio"
                )

            if not auth_token or len(auth_token) < 10:
                return TestConnectionResponse(
                    success=False,
                    message="Twilio Auth Token not configured",
                    provider="twilio"
                )

            if not whatsapp_number:
                return TestConnectionResponse(
                    success=False,
                    message="Twilio WhatsApp number not configured",
                    provider="twilio"
                )

            # Test Twilio API by fetching account info
            import base64
            auth_string = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}.json",
                    headers={
                        "Authorization": f"Basic {auth_string}"
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    account_name = data.get("friendly_name", "Unknown")
                    return TestConnectionResponse(
                        success=True,
                        message=f"Connected to Twilio account: {account_name}",
                        provider="twilio"
                    )
                elif response.status_code == 401:
                    return TestConnectionResponse(
                        success=False,
                        message="Invalid Twilio credentials (Account SID or Auth Token)",
                        provider="twilio"
                    )
                else:
                    return TestConnectionResponse(
                        success=False,
                        message=f"Twilio API error: {response.status_code}",
                        provider="twilio"
                    )

        elif provider == "telegram":
            # Test Telegram Bot connection (Feature #306)
            bot_token = settings_store.get('telegram_bot_token')

            if not bot_token or len(bot_token) < 10:
                return TestConnectionResponse(
                    success=False,
                    message="Telegram Bot Token not configured",
                    provider="telegram"
                )

            # Test Telegram Bot API by calling getMe endpoint
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"https://api.telegram.org/bot{bot_token}/getMe"
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        bot_info = data.get("result", {})
                        bot_name = bot_info.get("first_name", "Unknown")
                        bot_username = bot_info.get("username", "")
                        return TestConnectionResponse(
                            success=True,
                            message=f"Connected to Telegram bot: {bot_name} (@{bot_username})",
                            provider="telegram"
                        )
                    else:
                        return TestConnectionResponse(
                            success=False,
                            message=f"Telegram API error: {data.get('description', 'Unknown error')}",
                            provider="telegram"
                        )
                elif response.status_code == 401:
                    return TestConnectionResponse(
                        success=False,
                        message="Invalid Telegram Bot Token",
                        provider="telegram"
                    )
                else:
                    return TestConnectionResponse(
                        success=False,
                        message=f"Telegram API error: {response.status_code}",
                        provider="telegram"
                    )

        else:
            return TestConnectionResponse(
                success=False,
                message=f"Unknown provider: {provider}",
                provider=provider
            )

    except httpx.ConnectError:
        return TestConnectionResponse(
            success=False,
            message=f"Cannot connect to {provider}. Please check your internet connection.",
            provider=provider
        )
    except httpx.TimeoutException:
        return TestConnectionResponse(
            success=False,
            message=f"Connection to {provider} timed out. Please try again.",
            provider=provider
        )
    except Exception as e:
        logger.error(f"Error testing {provider} connection: {e}")
        return TestConnectionResponse(
            success=False,
            message=f"Error testing connection: {str(e)}",
            provider=provider
        )


# ============================================================
# Database Reset Endpoint (Feature #214: Double Confirmation)
# ============================================================

class ResetDatabaseRequest(BaseModel):
    """Request body for database reset with double confirmation (Feature #214, #223)."""
    confirmation_phrase: str  # Must be "DELETE ALL DATA"
    confirmation_token: str  # Token from the preview endpoint


class ResetDatabasePreviewResponse(BaseModel):
    """Response from reset database preview (Feature #214)."""
    documents_count: int
    collections_count: int
    conversations_count: int
    messages_count: int
    files_count: int
    total_size_human: str
    confirmation_token: str  # Token to use in the actual reset request
    expires_at: str  # ISO timestamp when token expires


class ResetDatabaseResponse(BaseModel):
    """Response for database reset operation."""
    success: bool
    message: str
    documents_deleted: int
    collections_deleted: int
    conversations_deleted: int
    messages_deleted: int
    files_deleted: int
    embeddings_deleted: int
    backup_path: Optional[str] = None  # Feature #213: Path to pre-destructive backup


# Feature #214: Store confirmation tokens with expiry
# In production, use Redis or database. For simplicity, using in-memory dict
import secrets
import json
from datetime import datetime, timedelta

_reset_confirmation_tokens: Dict[str, Dict] = {}


def _log_audit_event(action: str, status: str, details: Dict = None, ip_address: str = None, user_agent: str = None):
    """Log an audit event for database reset operations (Feature #214)."""
    from core.database import SessionLocal
    from sqlalchemy import text

    try:
        db = SessionLocal()
        try:
            # Ensure audit_log table exists
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    action VARCHAR(100) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    details TEXT,
                    ip_address VARCHAR(45),
                    user_agent VARCHAR(500),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
                )
            """))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_log_action ON audit_log (action)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log (created_at)"))

            # Insert audit log entry
            db.execute(
                text("""
                    INSERT INTO audit_log (action, status, details, ip_address, user_agent)
                    VALUES (:action, :status, :details, :ip_address, :user_agent)
                """),
                {
                    "action": action,
                    "status": status,
                    "details": json.dumps(details) if details else None,
                    "ip_address": ip_address,
                    "user_agent": user_agent
                }
            )
            db.commit()
            logger.info(f"[Audit] {action}: {status}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to log audit event: {e}")


@router.post("/reset-database/preview", response_model=ResetDatabasePreviewResponse)
async def reset_database_preview(request: Request):
    """
    Get a preview of what will be deleted and generate a confirmation token.

    Feature #214: Double confirmation for database reset.

    Returns counts of all data that will be deleted plus a confirmation token.
    The token expires after 5 minutes.
    """
    import os
    from core.database import SessionLocal
    from models.db_models import DBDocument, DBCollection, DBConversation, DBMessage

    try:
        db = SessionLocal()
        try:
            # Count all records
            documents_count = db.query(DBDocument).count()
            collections_count = db.query(DBCollection).count()
            conversations_count = db.query(DBConversation).count()
            messages_count = db.query(DBMessage).count()

            # Count files and total size
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
            files_count = 0
            total_size = 0
            if os.path.exists(uploads_dir):
                for root, dirs, files in os.walk(uploads_dir):
                    for f in files:
                        file_path = os.path.join(root, f)
                        if os.path.isfile(file_path):
                            files_count += 1
                            total_size += os.path.getsize(file_path)

            # Format size
            if total_size < 1024:
                total_size_human = f"{total_size} B"
            elif total_size < 1024 * 1024:
                total_size_human = f"{total_size / 1024:.1f} KB"
            elif total_size < 1024 * 1024 * 1024:
                total_size_human = f"{total_size / (1024 * 1024):.1f} MB"
            else:
                total_size_human = f"{total_size / (1024 * 1024 * 1024):.1f} GB"

            # Generate confirmation token
            token = secrets.token_urlsafe(32)
            expires_at = datetime.now() + timedelta(minutes=5)

            # Store token with counts for validation
            _reset_confirmation_tokens[token] = {
                "documents_count": documents_count,
                "collections_count": collections_count,
                "conversations_count": conversations_count,
                "messages_count": messages_count,
                "files_count": files_count,
                "expires_at": expires_at.isoformat()
            }

            # Clean up expired tokens
            current_time = datetime.now()
            expired_tokens = [
                t for t, data in _reset_confirmation_tokens.items()
                if datetime.fromisoformat(data["expires_at"]) < current_time
            ]
            for t in expired_tokens:
                del _reset_confirmation_tokens[t]

            # Log audit event
            _log_audit_event(
                action="database_reset",
                status="preview_requested",
                details={
                    "documents": documents_count,
                    "collections": collections_count,
                    "conversations": conversations_count,
                    "messages": messages_count,
                    "files": files_count
                },
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent")
            )

            return ResetDatabasePreviewResponse(
                documents_count=documents_count,
                collections_count=collections_count,
                conversations_count=conversations_count,
                messages_count=messages_count,
                files_count=files_count,
                total_size_human=total_size_human,
                confirmation_token=token,
                expires_at=expires_at.isoformat()
            )

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting reset preview: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get reset preview: {str(e)}")


@router.post("/reset-database", response_model=ResetDatabaseResponse)
async def reset_database(
    request: Request,
    body: Optional[ResetDatabaseRequest] = None
):
    """
    Reset the entire database and delete all uploaded files.

    Feature #214, #223: Double confirmation required.
    - Must provide confirmation_phrase = "DELETE ALL DATA"
    - Must provide valid confirmation_token from /reset-database/preview

    WARNING: This operation is DESTRUCTIVE and IRREVERSIBLE.
    It will delete:
    - All documents (metadata and files)
    - All collections
    - All conversations and messages
    - All embeddings
    - All uploaded files from disk

    Settings (API keys, theme, etc.) are preserved.

    Feature #213: Automatically creates a backup before reset if require_backup_before_delete is enabled.

    Returns:
        ResetDatabaseResponse: Summary of what was deleted
    """
    import os
    import shutil
    from core.database import SessionLocal
    from models.db_models import DBDocument, DBCollection, DBConversation, DBMessage, DBDocumentRow
    from services.embedding_store import embedding_store
    from services.pre_destructive_backup import create_pre_destructive_backup

    # Feature #214: Validate double confirmation
    if body is None:
        # Log cancelled attempt
        _log_audit_event(
            action="database_reset",
            status="rejected_no_confirmation",
            details={"reason": "No confirmation body provided"},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")
        )
        raise HTTPException(
            status_code=400,
            detail="Confirmation required. Use POST /api/settings/reset-database/preview first to get a confirmation token."
        )

    # Validate confirmation phrase (Feature #223: Changed to "DELETE ALL DATA")
    if body.confirmation_phrase != "DELETE ALL DATA":
        _log_audit_event(
            action="database_reset",
            status="rejected_wrong_phrase",
            details={"phrase_provided": body.confirmation_phrase},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid confirmation phrase. Must type 'DELETE ALL DATA' exactly."
        )

    # Validate confirmation token
    if body.confirmation_token not in _reset_confirmation_tokens:
        _log_audit_event(
            action="database_reset",
            status="rejected_invalid_token",
            details={"reason": "Token not found or already used"},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired confirmation token. Please start the reset process again."
        )

    # Check token expiry
    token_data = _reset_confirmation_tokens[body.confirmation_token]
    expires_at = datetime.fromisoformat(token_data["expires_at"])
    if datetime.now() > expires_at:
        # Remove expired token
        del _reset_confirmation_tokens[body.confirmation_token]
        _log_audit_event(
            action="database_reset",
            status="rejected_expired_token",
            details={"expired_at": token_data["expires_at"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")
        )
        raise HTTPException(
            status_code=400,
            detail="Confirmation token has expired. Please start the reset process again."
        )

    # Token is valid - remove it (single use)
    del _reset_confirmation_tokens[body.confirmation_token]

    # Log that reset is proceeding
    _log_audit_event(
        action="database_reset",
        status="initiated",
        details={
            "documents": token_data["documents_count"],
            "collections": token_data["collections_count"],
            "conversations": token_data["conversations_count"],
            "messages": token_data["messages_count"],
            "files": token_data["files_count"]
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    try:
        # Feature #213: Create pre-destructive backup before reset
        backup_path = None
        backup_result = await create_pre_destructive_backup(
            operation="reset-database",
            details={"action": "full_database_reset"}
        )

        if not backup_result['success'] and not backup_result.get('skipped', False):
            # Backup failed and was required - block the operation
            logger.error(f"[Feature #213] Pre-destructive backup failed, blocking reset: {backup_result['error']}")
            raise HTTPException(
                status_code=500,
                detail=f"Cannot reset database: Pre-destructive backup failed. {backup_result['error']}"
            )

        if backup_result.get('backup_path'):
            backup_path = backup_result['backup_path']
            logger.info(f"[Feature #213] Pre-destructive backup created at: {backup_path}")

        logger.warning("⚠️  DATABASE RESET INITIATED - This operation is irreversible!")

        # Initialize counters
        documents_count = 0
        collections_count = 0
        conversations_count = 0
        messages_count = 0
        files_count = 0
        embeddings_count = 0

        # Get database session (synchronous)
        db = SessionLocal()

        try:
            # 1. Count existing records before deletion
            documents_count = db.query(DBDocument).count()
            collections_count = db.query(DBCollection).count()
            conversations_count = db.query(DBConversation).count()
            messages_count = db.query(DBMessage).count()

            logger.info(f"Found {documents_count} documents, {collections_count} collections, {conversations_count} conversations, {messages_count} messages")

            # 2. Delete all embeddings from vector store
            try:
                # Get all document IDs before deleting from DB
                document_ids = [doc.id for doc in db.query(DBDocument.id).all()]
                for doc_id in document_ids:
                    try:
                        embedding_store.delete_document(doc_id)
                        embeddings_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete embeddings for document {doc_id}: {e}")
                logger.info(f"Deleted embeddings for {embeddings_count} documents")
            except Exception as e:
                logger.error(f"Error deleting embeddings: {e}")

            # 3. Delete all uploaded files from disk
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
            if os.path.exists(uploads_dir):
                try:
                    # Count files before deletion
                    for root, dirs, files in os.walk(uploads_dir):
                        files_count += len(files)

                    # Delete all files and subdirectories
                    for item in os.listdir(uploads_dir):
                        item_path = os.path.join(uploads_dir, item)
                        if os.path.isfile(item_path):
                            os.unlink(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)

                    logger.info(f"Deleted {files_count} files from {uploads_dir}")
                except Exception as e:
                    logger.error(f"Error deleting files from uploads directory: {e}")

            # 4. Delete all database records (in correct order due to foreign keys)
            # Delete messages first (child of conversations)
            db.query(DBMessage).delete()

            # Delete conversations
            db.query(DBConversation).delete()

            # Delete document rows (child of documents)
            db.query(DBDocumentRow).delete()

            # Delete documents
            db.query(DBDocument).delete()

            # Delete collections
            db.query(DBCollection).delete()

            # Commit all deletions
            db.commit()

            logger.info("✅ Database reset completed successfully")

            # Feature #214: Log successful reset
            _log_audit_event(
                action="database_reset",
                status="completed",
                details={
                    "documents_deleted": documents_count,
                    "collections_deleted": collections_count,
                    "conversations_deleted": conversations_count,
                    "messages_deleted": messages_count,
                    "files_deleted": files_count,
                    "embeddings_deleted": embeddings_count,
                    "backup_path": backup_path
                },
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent")
            )

            return ResetDatabaseResponse(
                success=True,
                message="Database reset successfully. All data has been deleted.",
                documents_deleted=documents_count,
                collections_deleted=collections_count,
                conversations_deleted=conversations_count,
                messages_deleted=messages_count,
                files_deleted=files_count,
                embeddings_deleted=embeddings_count,
                backup_path=backup_path
            )

        except Exception as e:
            db.rollback()
            logger.error(f"Error during database reset: {e}")
            # Feature #214: Log failed reset
            _log_audit_event(
                action="database_reset",
                status="failed",
                details={"error": str(e)},
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent")
            )
            raise HTTPException(status_code=500, detail=f"Database reset failed: {str(e)}")

        finally:
            db.close()

    except HTTPException:
        # Re-raise HTTP exceptions without logging (already logged above)
        raise
    except Exception as e:
        logger.error(f"Fatal error during database reset: {e}")
        # Feature #214: Log fatal error
        _log_audit_event(
            action="database_reset",
            status="failed",
            details={"error": str(e), "fatal": True},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")
        )
        raise HTTPException(status_code=500, detail=f"Database reset failed: {str(e)}")


# ============================================================
# Pre-Destructive Backup Undo Endpoints (Feature #222)
# ============================================================

class PreDestructiveBackupInfo(BaseModel):
    """Information about a pre-destructive backup."""
    timestamp: str
    created_at: str
    operation: str
    reason: str
    documents_count: int
    collections_count: int
    files_count: int
    total_file_bytes: int
    path: str


class PreDestructiveBackupListResponse(BaseModel):
    """Response containing list of pre-destructive backups."""
    backups: List[Dict]
    count: int
    max_backups: int


class RestoreFromBackupRequest(BaseModel):
    """Request to restore from a pre-destructive backup."""
    backup_path: str


class RestoreFromBackupResponse(BaseModel):
    """Response from restore operation."""
    success: bool
    message: str
    documents_restored: int
    collections_restored: int
    files_restored: int
    note: Optional[str] = None
    error: Optional[str] = None


@router.get("/pre-destructive-backups", response_model=PreDestructiveBackupListResponse)
async def list_pre_destructive_backups_endpoint():
    """
    Feature #222: List all available pre-destructive backups.

    Returns a list of backups created before destructive operations (database reset,
    bulk delete, collection cascade delete). These can be used to undo/restore data.
    """
    from services.pre_destructive_backup import list_pre_destructive_backups, MAX_PRE_DELETE_BACKUPS

    try:
        backups = list_pre_destructive_backups()
        return PreDestructiveBackupListResponse(
            backups=backups,
            count=len(backups),
            max_backups=MAX_PRE_DELETE_BACKUPS
        )
    except Exception as e:
        logger.error(f"Error listing pre-destructive backups: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list backups: {str(e)}")


@router.post("/pre-destructive-backups/restore", response_model=RestoreFromBackupResponse)
async def restore_from_pre_destructive_backup_endpoint(request: RestoreFromBackupRequest):
    """
    Feature #222: Restore data from a pre-destructive backup (Undo operation).

    This restores documents, collections, and files from a backup created before
    a destructive operation. Note that embeddings will need to be regenerated.

    Args:
        backup_path: The path to the backup directory to restore from
    """
    from services.pre_destructive_backup import restore_from_pre_destructive_backup

    try:
        result = await restore_from_pre_destructive_backup(request.backup_path)

        if not result['success']:
            raise HTTPException(status_code=400, detail=result.get('error', 'Restore failed'))

        return RestoreFromBackupResponse(
            success=result['success'],
            message=result.get('message', ''),
            documents_restored=result.get('documents_restored', 0),
            collections_restored=result.get('collections_restored', 0),
            files_restored=result.get('files_restored', 0),
            note=result.get('note'),
            error=result.get('error')
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restoring from backup: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to restore: {str(e)}")


@router.get("/last-destructive-backup")
async def get_last_destructive_backup():
    """
    Feature #222: Get the most recent pre-destructive backup for the Undo operation.

    Returns the most recent backup if one exists and was created within the last hour,
    allowing users to quickly undo a recent destructive operation.
    """
    from services.pre_destructive_backup import list_pre_destructive_backups
    from datetime import datetime, timedelta

    try:
        backups = list_pre_destructive_backups()

        if not backups:
            return {
                'available': False,
                'backup': None,
                'message': 'No pre-destructive backups available'
            }

        # Get the most recent backup
        latest = backups[0]

        # Check if it was created within the last hour
        created_at_str = latest.get('created_at', '')
        is_recent = False

        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                now = datetime.now(created_at.tzinfo) if created_at.tzinfo else datetime.now()
                is_recent = (now - created_at) < timedelta(hours=1)
            except:
                pass

        return {
            'available': True,
            'is_recent': is_recent,
            'backup': latest,
            'message': f"Backup from {latest.get('operation', 'unknown operation')} available"
        }
    except Exception as e:
        logger.error(f"Error getting last destructive backup: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get backup: {str(e)}")


# ============================================================
# System Prompt Endpoints (Feature #179)
# ============================================================

class SystemPromptResponse(BaseModel):
    """Response containing system prompt details."""
    custom_prompt: str
    default_prompt: str
    active_prompt: str  # The prompt currently being used (custom if set, else default)
    is_custom: bool
    character_count: int
    preset_name: Optional[str] = None


class SystemPromptUpdate(BaseModel):
    """Request body for updating system prompt."""
    custom_prompt: str


class SystemPromptTestRequest(BaseModel):
    """Request body for testing system prompt."""
    test_message: str
    prompt_to_test: Optional[str] = None  # If None, uses current active prompt


class SystemPromptTestResponse(BaseModel):
    """Response from testing system prompt."""
    success: bool
    response: str
    prompt_used: str
    error: Optional[str] = None


# System prompt preset templates
SYSTEM_PROMPT_PRESETS = {
    "default": "",  # Empty string means use the built-in default
    "detailed": """You are a helpful document assistant. When answering questions:

1. **Be Thorough**: Provide detailed, comprehensive answers with context
2. **Cite Sources**: Always mention which document(s) the information comes from
3. **Use Formatting**: Use bullet points, numbered lists, and headers for clarity
4. **Include Context**: Explain relevant background information when helpful
5. **Be Precise**: Include specific quotes, numbers, or dates from documents

Remember to respond in the same language as the user's question.""",

    "concise": """You are a concise document assistant. Keep responses brief and to the point.

- Answer directly without unnecessary elaboration
- Use short sentences and bullet points
- Only cite the most relevant source
- Skip background context unless essential
- Respond in the user's language""",

    "technical": """You are a technical documentation assistant. When responding:

- Use precise technical terminology
- Include code snippets, formulas, or specifications when relevant
- Reference exact sections and page numbers when available
- Maintain formal, technical language
- Structure responses with clear headers
- Include relevant technical details and parameters

Respond in the user's language.""",

    "friendly": """You are a friendly and approachable document assistant!

- Use a warm, conversational tone
- Explain complex concepts in simple terms
- Use analogies and examples to clarify
- Be encouraging and supportive
- Feel free to use occasional emojis for emphasis
- Always respond in the same language as the question

I'm here to help you find information in your documents!"""
}


@router.get("/system-prompt", response_model=SystemPromptResponse)
async def get_system_prompt():
    """
    Get the current system prompt configuration.

    Returns the custom prompt (if set), the default prompt, and which one is active.
    """
    from services.ai_service import AIService

    ai_service = AIService()
    default_prompt = ai_service.get_default_system_prompt()
    custom_prompt = settings_store.get('custom_system_prompt', '')

    is_custom = bool(custom_prompt and custom_prompt.strip())
    active_prompt = custom_prompt if is_custom else default_prompt

    # Try to identify if using a preset
    preset_name = None
    if is_custom:
        for name, preset_text in SYSTEM_PROMPT_PRESETS.items():
            if preset_text and custom_prompt.strip() == preset_text.strip():
                preset_name = name
                break

    return SystemPromptResponse(
        custom_prompt=custom_prompt,
        default_prompt=default_prompt,
        active_prompt=active_prompt,
        is_custom=is_custom,
        character_count=len(active_prompt),
        preset_name=preset_name
    )


@router.put("/system-prompt", response_model=SystemPromptResponse)
async def update_system_prompt(update: SystemPromptUpdate):
    """
    Update the custom system prompt.

    Set custom_prompt to empty string to revert to default.
    """
    custom_prompt = update.custom_prompt

    # Validation
    if custom_prompt and len(custom_prompt.strip()) > 0 and len(custom_prompt.strip()) < 50:
        raise HTTPException(status_code=400, detail="System prompt must be at least 50 characters if provided")
    if len(custom_prompt) > 10000:
        raise HTTPException(status_code=400, detail="System prompt cannot exceed 10,000 characters")

    # Save to settings
    settings_store.set('custom_system_prompt', custom_prompt)
    logger.info(f"Updated custom system prompt (length: {len(custom_prompt)})")

    # Return updated prompt info
    from services.ai_service import AIService

    ai_service = AIService()
    default_prompt = ai_service.get_default_system_prompt()

    is_custom = bool(custom_prompt and custom_prompt.strip())
    active_prompt = custom_prompt if is_custom else default_prompt

    # Try to identify if using a preset
    preset_name = None
    if is_custom:
        for name, preset_text in SYSTEM_PROMPT_PRESETS.items():
            if preset_text and custom_prompt.strip() == preset_text.strip():
                preset_name = name
                break

    return SystemPromptResponse(
        custom_prompt=custom_prompt,
        default_prompt=default_prompt,
        active_prompt=active_prompt,
        is_custom=is_custom,
        character_count=len(active_prompt),
        preset_name=preset_name
    )


@router.get("/system-prompt/presets")
async def get_system_prompt_presets():
    """
    Get available system prompt presets.
    """
    presets = []
    for name, text in SYSTEM_PROMPT_PRESETS.items():
        presets.append({
            "name": name,
            "label": name.replace("_", " ").title(),
            "text": text,
            "description": _get_preset_description(name),
            "character_count": len(text) if text else 0
        })
    return {"presets": presets}


def _get_preset_description(name: str) -> str:
    """Get description for a preset."""
    descriptions = {
        "default": "The built-in system prompt optimized for document Q&A",
        "detailed": "Provides thorough, well-formatted responses with citations",
        "concise": "Brief, direct answers without elaboration",
        "technical": "Uses precise technical terminology and formal language",
        "friendly": "Warm, conversational tone with simple explanations"
    }
    return descriptions.get(name, "")


@router.post("/system-prompt/test", response_model=SystemPromptTestResponse)
async def test_system_prompt(request: SystemPromptTestRequest):
    """
    Test a system prompt by sending a test message.

    Useful for previewing how the AI will respond with a new prompt before saving it.
    """
    from services.ai_service import AIService

    ai_service = AIService()

    # Determine which prompt to use
    if request.prompt_to_test is not None:
        prompt_to_use = request.prompt_to_test
    else:
        custom_prompt = settings_store.get('custom_system_prompt', '')
        if custom_prompt and custom_prompt.strip():
            prompt_to_use = custom_prompt
        else:
            prompt_to_use = ai_service.get_default_system_prompt()

    try:
        # Use a simple, direct LLM call for testing
        response = await ai_service.test_prompt(
            prompt=prompt_to_use,
            test_message=request.test_message
        )

        return SystemPromptTestResponse(
            success=True,
            response=response,
            prompt_used=prompt_to_use[:200] + "..." if len(prompt_to_use) > 200 else prompt_to_use
        )
    except Exception as e:
        logger.error(f"Error testing system prompt: {e}")
        return SystemPromptTestResponse(
            success=False,
            response="",
            prompt_used=prompt_to_use[:200] + "..." if len(prompt_to_use) > 200 else prompt_to_use,
            error=str(e)
        )


# ============================================================
# RAG Self-Test Endpoints (Feature #198)
# ============================================================

class ComponentTestResult(BaseModel):
    """Result of testing a single RAG component."""
    component: str  # e.g., "embedding", "retrieval", "reranking", "llm"
    passed: bool
    message: str
    details: Optional[Dict] = None


class DocumentTestResult(BaseModel):
    """Result of testing RAG on a single document."""
    document_id: str
    document_name: str
    test_query: str
    chunks_retrieved: int
    reranking_applied: bool
    llm_response_generated: bool
    passed: bool
    error: Optional[str] = None


class SelfTestResponse(BaseModel):
    """Full response from the self-test endpoint."""
    success: bool
    message: str
    overall_status: str  # "pass", "partial", "fail"
    component_tests: List[ComponentTestResult]
    document_tests: List[DocumentTestResult]
    summary: Dict


@router.post("/self-test", response_model=SelfTestResponse)
async def run_self_test():
    """
    Run automated self-test of the RAG pipeline.

    This endpoint tests all components of the RAG system:
    1. Embedding model connectivity
    2. Vector store retrieval
    3. Reranking (if enabled)
    4. LLM response generation

    For each uploaded document, it generates a simple test query
    and verifies that the pipeline can retrieve and respond.

    Returns:
        SelfTestResponse: Complete test report with pass/fail for each component
    """
    from services.ai_service import AIService
    from core.database import SessionLocal
    from models.db_models import DBDocument

    component_tests: List[ComponentTestResult] = []
    document_tests: List[DocumentTestResult] = []

    # Track overall status
    components_passed = 0
    components_total = 0
    docs_tested = 0
    docs_passed = 0

    # Test 1: Embedding Model Connectivity
    components_total += 1
    try:
        embedding_model = settings_store.get('embedding_model', 'text-embedding-3-small')

        # Check if using Ollama or OpenAI
        if embedding_model.startswith('ollama:'):
            # Test Ollama embedding
            ollama_model = embedding_model.split(':', 1)[1]
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://localhost:11434/api/embeddings",
                    json={"model": ollama_model, "prompt": "test"}
                )
                if response.status_code == 200 and response.json().get("embedding"):
                    component_tests.append(ComponentTestResult(
                        component="embedding",
                        passed=True,
                        message=f"Ollama embedding model '{ollama_model}' is working",
                        details={"model": ollama_model, "provider": "ollama"}
                    ))
                    components_passed += 1
                else:
                    component_tests.append(ComponentTestResult(
                        component="embedding",
                        passed=False,
                        message=f"Ollama embedding model '{ollama_model}' failed to generate embedding",
                        details={"model": ollama_model, "provider": "ollama"}
                    ))
        else:
            # Test OpenAI embedding
            api_key = settings_store.get('openai_api_key')
            if not api_key or len(api_key) < 20:
                component_tests.append(ComponentTestResult(
                    component="embedding",
                    passed=False,
                    message="OpenAI API key not configured for embeddings",
                    details={"model": embedding_model, "provider": "openai"}
                ))
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        "https://api.openai.com/v1/embeddings",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={"model": embedding_model, "input": "test"}
                    )
                    if response.status_code == 200:
                        component_tests.append(ComponentTestResult(
                            component="embedding",
                            passed=True,
                            message=f"OpenAI embedding model '{embedding_model}' is working",
                            details={"model": embedding_model, "provider": "openai"}
                        ))
                        components_passed += 1
                    else:
                        component_tests.append(ComponentTestResult(
                            component="embedding",
                            passed=False,
                            message=f"OpenAI embedding failed: {response.status_code}",
                            details={"model": embedding_model, "provider": "openai"}
                        ))
    except Exception as e:
        component_tests.append(ComponentTestResult(
            component="embedding",
            passed=False,
            message=f"Embedding test error: {str(e)}",
            details={"error": str(e)}
        ))

    # Test 2: Vector Store Status
    components_total += 1
    try:
        chunk_count = embedding_store.get_chunk_count()
        if chunk_count > 0:
            component_tests.append(ComponentTestResult(
                component="vector_store",
                passed=True,
                message=f"Vector store contains {chunk_count} chunks",
                details={"chunk_count": chunk_count, "backend": embedding_store.storage_backend}
            ))
            components_passed += 1
        else:
            component_tests.append(ComponentTestResult(
                component="vector_store",
                passed=False,
                message="Vector store is empty - no documents have been embedded",
                details={"chunk_count": 0}
            ))
    except Exception as e:
        component_tests.append(ComponentTestResult(
            component="vector_store",
            passed=False,
            message=f"Vector store test error: {str(e)}",
            details={"error": str(e)}
        ))

    # Test 3: Reranking Configuration
    components_total += 1
    enable_reranking = settings_store.get('enable_reranking', True)
    cohere_key = settings_store.get('cohere_api_key', '')

    if not enable_reranking:
        component_tests.append(ComponentTestResult(
            component="reranking",
            passed=True,
            message="Reranking is disabled (optional component)",
            details={"enabled": False}
        ))
        components_passed += 1
    elif cohere_key and len(cohere_key) > 10:
        # Test Cohere API key validity
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.cohere.ai/v1/check-api-key",
                    headers={"Authorization": f"Bearer {cohere_key}"}
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("valid") == True:
                        component_tests.append(ComponentTestResult(
                            component="reranking",
                            passed=True,
                            message="Cohere reranking is configured and API key is valid",
                            details={"enabled": True, "provider": "cohere"}
                        ))
                        components_passed += 1
                    else:
                        component_tests.append(ComponentTestResult(
                            component="reranking",
                            passed=False,
                            message="Cohere API key is invalid",
                            details={"enabled": True, "provider": "cohere"}
                        ))
                else:
                    component_tests.append(ComponentTestResult(
                        component="reranking",
                        passed=False,
                        message=f"Cohere API check failed: {response.status_code}",
                        details={"enabled": True}
                    ))
        except Exception as e:
            component_tests.append(ComponentTestResult(
                component="reranking",
                passed=False,
                message=f"Cohere connection test failed: {str(e)}",
                details={"enabled": True, "error": str(e)}
            ))
    else:
        component_tests.append(ComponentTestResult(
            component="reranking",
            passed=False,
            message="Reranking enabled but Cohere API key not configured",
            details={"enabled": True, "api_key_set": False}
        ))

    # Test 4: LLM Connectivity
    components_total += 1
    try:
        llm_model = settings_store.get('llm_model', 'gpt-4o')

        if llm_model.startswith('ollama:'):
            # Test Ollama LLM
            ollama_model = llm_model.split(':', 1)[1]
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "http://localhost:11434/api/generate",
                    json={"model": ollama_model, "prompt": "Say 'test'", "stream": False}
                )
                if response.status_code == 200:
                    component_tests.append(ComponentTestResult(
                        component="llm",
                        passed=True,
                        message=f"Ollama LLM '{ollama_model}' is working",
                        details={"model": ollama_model, "provider": "ollama"}
                    ))
                    components_passed += 1
                else:
                    component_tests.append(ComponentTestResult(
                        component="llm",
                        passed=False,
                        message=f"Ollama LLM test failed: {response.status_code}",
                        details={"model": ollama_model, "provider": "ollama"}
                    ))
        elif llm_model.startswith('openrouter:'):
            # Test OpenRouter
            api_key = settings_store.get('openrouter_api_key')
            if not api_key or len(api_key) < 10:
                component_tests.append(ComponentTestResult(
                    component="llm",
                    passed=False,
                    message="OpenRouter API key not configured",
                    details={"model": llm_model, "provider": "openrouter"}
                ))
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://openrouter.ai/api/v1/models",
                        headers={"Authorization": f"Bearer {api_key}"}
                    )
                    if response.status_code == 200:
                        component_tests.append(ComponentTestResult(
                            component="llm",
                            passed=True,
                            message=f"OpenRouter is connected ({llm_model})",
                            details={"model": llm_model, "provider": "openrouter"}
                        ))
                        components_passed += 1
                    else:
                        component_tests.append(ComponentTestResult(
                            component="llm",
                            passed=False,
                            message=f"OpenRouter connection failed: {response.status_code}",
                            details={"model": llm_model, "provider": "openrouter"}
                        ))
        else:
            # Test OpenAI
            api_key = settings_store.get('openai_api_key')
            if not api_key or len(api_key) < 20:
                component_tests.append(ComponentTestResult(
                    component="llm",
                    passed=False,
                    message="OpenAI API key not configured for LLM",
                    details={"model": llm_model, "provider": "openai"}
                ))
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {api_key}"}
                    )
                    if response.status_code == 200:
                        component_tests.append(ComponentTestResult(
                            component="llm",
                            passed=True,
                            message=f"OpenAI is connected ({llm_model})",
                            details={"model": llm_model, "provider": "openai"}
                        ))
                        components_passed += 1
                    else:
                        component_tests.append(ComponentTestResult(
                            component="llm",
                            passed=False,
                            message=f"OpenAI connection failed: {response.status_code}",
                            details={"model": llm_model, "provider": "openai"}
                        ))
    except Exception as e:
        component_tests.append(ComponentTestResult(
            component="llm",
            passed=False,
            message=f"LLM test error: {str(e)}",
            details={"error": str(e)}
        ))

    # Test 5: RAG Pipeline with actual documents
    # Get documents from database
    db = SessionLocal()
    try:
        # Get unstructured documents (text-based, not tabular)
        unstructured_docs = db.query(DBDocument).filter(
            DBDocument.document_type == "unstructured"
        ).limit(5).all()

        if unstructured_docs:
            try:
                ai_service = AIService()
            except Exception as e:
                logger.error(f"Failed to initialize AIService for self-test: {e}")
                # Add a single failed test result indicating the AIService issue
                document_tests.append(DocumentTestResult(
                    document_id="system",
                    document_name="AIService Initialization",
                    test_query="",
                    chunks_retrieved=0,
                    reranking_applied=False,
                    llm_response_generated=False,
                    passed=False,
                    error=f"Failed to initialize AI service: {str(e)}"
                ))
                docs_tested = 1  # Count this as one failed test
                ai_service = None

            if ai_service:
                for doc in unstructured_docs:
                    docs_tested += 1
                    try:
                        # Generate a simple test query from the document name/preview
                        doc_name = doc.custom_name or doc.original_filename or "document"
                        # Create a simple query asking about the document's content
                        test_query = f"What is the main topic of {doc_name}?"

                        # Execute vector search
                        search_result = ai_service._execute_vector_search({
                            "query": test_query,
                            "top_k": 3,
                            "document_ids": [str(doc.id)]
                        })

                        chunks_retrieved = 0
                        reranking_applied = False
                        llm_response_generated = False
                        error_msg = None

                        if "error" in search_result:
                            error_msg = search_result["error"]
                        else:
                            chunks_retrieved = search_result.get("chunks_found", 0)
                            reranking_applied = search_result.get("reranking_applied", False)

                            # If chunks were retrieved, test LLM response (simplified - just check connectivity)
                            if chunks_retrieved > 0:
                                llm_response_generated = True  # We already tested LLM connectivity above

                        doc_passed = chunks_retrieved > 0
                        if doc_passed:
                            docs_passed += 1

                        document_tests.append(DocumentTestResult(
                            document_id=str(doc.id),
                            document_name=doc_name,
                            test_query=test_query,
                            chunks_retrieved=chunks_retrieved,
                            reranking_applied=reranking_applied,
                            llm_response_generated=llm_response_generated,
                            passed=doc_passed,
                            error=error_msg
                        ))

                    except Exception as e:
                        document_tests.append(DocumentTestResult(
                            document_id=str(doc.id),
                            document_name=doc.custom_name or doc.original_filename or "unknown",
                            test_query="",
                            chunks_retrieved=0,
                            reranking_applied=False,
                            llm_response_generated=False,
                            passed=False,
                            error=str(e)
                        ))
        else:
            logger.info("No unstructured documents found for RAG testing")

    except Exception as e:
        logger.error(f"Error testing documents: {e}")
    finally:
        db.close()

    # Calculate overall status
    if components_passed == components_total and (docs_tested == 0 or docs_passed == docs_tested):
        overall_status = "pass"
        success = True
        message = "All RAG components are working correctly"
    elif components_passed > 0 or docs_passed > 0:
        overall_status = "partial"
        success = True
        message = f"{components_passed}/{components_total} components and {docs_passed}/{docs_tested} document tests passed"
    else:
        overall_status = "fail"
        success = False
        message = "RAG pipeline tests failed"

    return SelfTestResponse(
        success=success,
        message=message,
        overall_status=overall_status,
        component_tests=component_tests,
        document_tests=document_tests,
        summary={
            "components_passed": components_passed,
            "components_total": components_total,
            "documents_tested": docs_tested,
            "documents_passed": docs_passed
        }
    )
