"""
Document API endpoints for the Agentic RAG System.

Feature #324: Added rate limiting to prevent API abuse.
Feature #327: Standardized error handling with user-friendly messages.
"""

import os
import io
import json
import uuid
import hashlib
import aiofiles
import pandas as pd
import httpx
import time
import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException, status, UploadFile, File, Form, Depends, Request

# Feature #324: Rate limiting
from core.rate_limit import limiter
from core.config import settings

# Feature #327: Standardized error handling
from core.errors import (
    NotFoundError, ValidationError, ServiceError, handle_exception,
    ErrorCode, raise_api_error, wrap_or_reraise
)
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel
from models.document import Document, DocumentCreate, DocumentUpdate, UploadResponse
# Feature #261: Import document status constants for type-safe status handling
# Feature #297: Added DOCUMENT_STATUS_VERIFICATION_FAILED
# Feature #330: Added DOCUMENT_STATUS_QUEUED for background processing
from models import (
    DOCUMENT_STATUS_UPLOADING,
    DOCUMENT_STATUS_QUEUED,
    DOCUMENT_STATUS_PROCESSING,
    DOCUMENT_STATUS_READY,
    DOCUMENT_STATUS_EMBEDDING_FAILED,
    DOCUMENT_STATUS_FILE_MISSING,
    DOCUMENT_STATUS_VERIFICATION_FAILED
)
from core.store import embedding_store, settings_store
from core.dependencies import get_document_store, get_document_rows_store
from core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError  # Feature #294: Handle unique constraint violations
import logging
from openai import OpenAI

# Feature #267: Import document audit logging service
from services.document_audit_service import (
    log_document_uploaded,
    log_embedding_started,
    log_embedding_completed,
    log_embedding_failed,
    log_document_deleted,
    log_re_embed_started,
    log_re_embed_completed,
    get_document_history
)

# Ollama settings
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

logger = logging.getLogger(__name__)

router = APIRouter()

# File upload settings
UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_MIME_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/json": "json",
    "text/markdown": "md",
}

# Ensure upload directory exists
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class DuplicateCheckResponse(BaseModel):
    """Response model for duplicate check endpoint."""
    is_duplicate: bool
    duplicate_document: Optional[Document] = None
    match_type: Optional[str] = None  # 'filename', 'content', 'both', or 'content_other_collection'
    other_collection_name: Optional[str] = None  # Feature #262: Name of collection if duplicate found elsewhere


def compute_file_hash(content: bytes) -> str:
    """Compute SHA-256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


async def check_file_integrity_and_update_status(
    document_id: str,
    document_store,
    raise_if_missing: bool = True
) -> Tuple[Optional[Path], bool]:
    """
    Feature #255: Check if a document's file exists on disk and update status accordingly.

    This function verifies file integrity when accessing a document (view, re-embed, etc.).
    If the file is missing, it updates the document status to 'file_missing' and optionally
    raises an HTTP 404 error.

    Args:
        document_id: The ID of the document to check
        document_store: The document store dependency for database operations
        raise_if_missing: If True, raises HTTPException when file is missing

    Returns:
        Tuple of (file_path or None, file_exists boolean)

    Raises:
        HTTPException: If file is missing and raise_if_missing is True
    """
    from core.database import SessionLocal
    from models.db_models import DBDocument, FILE_STATUS_MISSING, FILE_STATUS_OK

    file_path = None
    file_exists = False
    expected_path = None

    # Get file path from database
    with SessionLocal() as session:
        db_doc = session.query(DBDocument).filter(DBDocument.id == document_id).first()
        if not db_doc:
            if raise_if_missing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Document with ID '{document_id}' not found"
                )
            return None, False

        # Feature #253: Prefer file_path, fallback to url for backwards compatibility
        if db_doc.file_path:
            expected_path = Path(db_doc.file_path)
            if expected_path.exists():
                file_path = expected_path
                file_exists = True
        elif db_doc.url:
            expected_path = Path(db_doc.url)
            if expected_path.exists():
                file_path = expected_path
                file_exists = True
                logger.warning(f"[Feature #255] Document {document_id} using deprecated 'url' field")

    # Legacy fallback: check for file by ID pattern
    if not file_exists:
        for ext in ['pdf', 'txt', 'docx', 'md']:
            potential_path = UPLOAD_DIR / f"{document_id}.{ext}"
            if potential_path.exists():
                file_path = potential_path
                file_exists = True
                expected_path = potential_path
                logger.warning(f"[Feature #255] Document {document_id} found by ID pattern fallback")
                break

    # Legacy fallback: search by stem
    if not file_exists:
        for uploaded_file in UPLOAD_DIR.iterdir():
            if uploaded_file.stem == document_id:
                file_path = uploaded_file
                file_exists = True
                expected_path = uploaded_file
                logger.warning(f"[Feature #255] Document {document_id} found by stem search fallback")
                break

    # Update document status based on file existence
    if not file_exists:
        # File is missing - update status to 'file_missing'
        logger.warning(f"[Feature #255] File not found on disk for document {document_id}, expected path: {expected_path}")

        # Update the document status in DB using synchronous session with explicit commit
        # This ensures the status update is persisted even if HTTPException is raised
        with SessionLocal() as session:
            db_doc = session.query(DBDocument).filter(DBDocument.id == document_id).first()
            if db_doc:
                db_doc.file_status = FILE_STATUS_MISSING
                session.commit()
                logger.info(f"[Feature #255] Updated document {document_id} status to 'file_missing'")

        if raise_if_missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found on disk. The file may have been deleted. Expected path: {expected_path}"
            )
    else:
        # File exists - ensure status is 'ok' (in case it was previously marked as missing)
        with SessionLocal() as session:
            db_doc = session.query(DBDocument).filter(DBDocument.id == document_id).first()
            if db_doc and getattr(db_doc, 'file_status', 'ok') == FILE_STATUS_MISSING:
                logger.info(f"[Feature #255] File found for document {document_id}, restoring status to 'ok'")
                db_doc.file_status = FILE_STATUS_OK
                session.commit()

    return file_path, file_exists


def parse_structured_data(file_path: Path, mime_type: str) -> tuple[List[dict], List[str]]:
    """
    Parse structured data (CSV, Excel, JSON) and return rows and schema.

    NOTE: This is a CPU-bound blocking operation. For async contexts,
    use parse_structured_data_async() instead.

    Args:
        file_path: Path to the uploaded file
        mime_type: MIME type of the file

    Returns:
        Tuple of (list of row dicts, list of column names)
    """
    try:
        if mime_type == "text/csv":
            df = pd.read_csv(file_path)
        elif mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            # Modern Excel format (.xlsx) - use openpyxl engine
            df = pd.read_excel(file_path, engine='openpyxl')
        elif mime_type == "application/vnd.ms-excel":
            # Old Excel format (.xls) - use xlrd engine
            df = pd.read_excel(file_path, engine='xlrd')
        elif mime_type == "application/json":
            with open(file_path, 'r') as f:
                data = json.load(f)
            # Handle JSON array or object with records
            if isinstance(data, list):
                df = pd.DataFrame(data)
            elif isinstance(data, dict):
                # Try to find a list within the dict
                for key, value in data.items():
                    if isinstance(value, list):
                        df = pd.DataFrame(value)
                        break
                else:
                    # Single object, wrap in list
                    df = pd.DataFrame([data])
            else:
                return [], []
        else:
            return [], []

        # Convert DataFrame to list of dicts
        # Replace NaN with None for JSON compatibility
        df = df.fillna("")
        rows = df.to_dict(orient='records')
        schema = list(df.columns)

        logger.info(f"Parsed {len(rows)} rows with schema: {schema}")
        return rows, schema

    except Exception as e:
        logger.error(f"Error parsing structured data: {e}")
        return [], []


def extract_text_from_file(file_path: Path, mime_type: str) -> str:
    """
    Extract text content from unstructured documents (PDF, TXT, Word, Markdown).

    NOTE: This is a CPU-bound blocking operation. For async contexts,
    use extract_text_from_file_async() instead.

    Args:
        file_path: Path to the uploaded file
        mime_type: MIME type of the file

    Returns:
        Extracted text content
    """
    try:
        if mime_type == "text/plain" or mime_type == "text/markdown":
            # Plain text or Markdown - just read the file
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()

        elif mime_type == "application/pdf":
            # PDF extraction using pypdf
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(file_path))
                text_parts = []
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                return "\n\n".join(text_parts)
            except Exception as e:
                logger.error(f"Error extracting PDF text: {e}")
                return ""

        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            # Word document extraction using python-docx
            try:
                from docx import Document as DocxDocument
                doc = DocxDocument(str(file_path))
                text_parts = []
                for paragraph in doc.paragraphs:
                    if paragraph.text.strip():
                        text_parts.append(paragraph.text)
                return "\n\n".join(text_parts)
            except Exception as e:
                logger.error(f"Error extracting Word document text: {e}")
                return ""

        else:
            logger.warning(f"Unsupported mime type for text extraction: {mime_type}")
            return ""

    except Exception as e:
        logger.error(f"Error extracting text from file: {e}")
        return ""


# Feature #333: Async wrappers for CPU-bound operations
# These functions use run_in_executor to prevent blocking the event loop
# during document processing, ensuring the API remains responsive.

async def parse_structured_data_async(file_path: Path, mime_type: str) -> tuple[List[dict], List[str]]:
    """
    Async wrapper for parse_structured_data using thread pool.

    Feature #333: Prevents blocking the event loop during CSV/Excel/JSON parsing.
    This allows the server to handle concurrent requests during document processing.

    Args:
        file_path: Path to the uploaded file
        mime_type: MIME type of the file

    Returns:
        Tuple of (list of row dicts, list of column names)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, parse_structured_data, file_path, mime_type)


async def extract_text_from_file_async(file_path: Path, mime_type: str) -> str:
    """
    Async wrapper for extract_text_from_file using thread pool.

    Feature #333: Prevents blocking the event loop during PDF/Word/text extraction.
    This allows the server to handle concurrent requests during document processing.

    Args:
        file_path: Path to the uploaded file
        mime_type: MIME type of the file

    Returns:
        Extracted text content
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, extract_text_from_file, file_path, mime_type)


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """
    Split text into chunks with overlap for better context preservation.

    Args:
        text: The text to split
        chunk_size: Maximum characters per chunk
        overlap: Number of characters to overlap between chunks

    Returns:
        List of text chunks
    """
    if not text or len(text.strip()) == 0:
        return []

    # Clean up text - normalize whitespace
    text = ' '.join(text.split())

    chunks = []
    start = 0

    while start < len(text):
        # Find end position
        end = start + chunk_size

        # If we're not at the end, try to break at a sentence or word boundary
        if end < len(text):
            # Try to find a sentence break (., !, ?)
            for sep in ['. ', '! ', '? ', '\n']:
                last_sep = text.rfind(sep, start, end)
                if last_sep > start + chunk_size // 2:
                    end = last_sep + len(sep)
                    break
            else:
                # Fall back to word boundary
                last_space = text.rfind(' ', start, end)
                if last_space > start + chunk_size // 2:
                    end = last_space + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Move start position with overlap
        start = end - overlap if end < len(text) else end

    return chunks


def generate_embeddings(texts: List[str], api_key: str, model: str = "text-embedding-3-small") -> List[List[float]]:
    """
    Generate embeddings for a list of texts using OpenAI API.

    Args:
        texts: List of text strings to embed
        api_key: OpenAI API key
        model: Embedding model to use

    Returns:
        List of embedding vectors
    """
    if not texts or not api_key:
        return []

    try:
        client = OpenAI(api_key=api_key)

        # OpenAI has a limit of how many texts can be embedded at once
        # Process in batches of 100
        all_embeddings = []
        batch_size = 100

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = client.embeddings.create(
                model=model,
                input=batch
            )

            # Extract embeddings from response
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        logger.info(f"Generated {len(all_embeddings)} embeddings using {model}")
        return all_embeddings

    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        return []


async def generate_embeddings_async(texts: List[str], api_key: str, model: str = "text-embedding-3-small") -> List[List[float]]:
    """
    Async wrapper for generate_embeddings using thread pool.

    Feature #333: Prevents blocking the event loop during OpenAI embedding API calls.
    This allows the server to handle concurrent requests during document processing.

    Args:
        texts: List of text strings to embed
        api_key: OpenAI API key
        model: Embedding model to use

    Returns:
        List of embedding vectors
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, generate_embeddings, texts, api_key, model)


def retry_failed_embeddings(
    failed_indices: List[int],
    chunks: List[str],
    api_key: str,
    model: str,
    max_retries: int = 3
) -> Tuple[List[Tuple[int, List[float]]], List[int]]:
    """
    Retry generating embeddings for failed chunks with exponential backoff.

    Args:
        failed_indices: List of indices where embeddings failed
        chunks: Original list of all text chunks
        api_key: OpenAI API key
        model: Embedding model to use
        max_retries: Maximum number of retry attempts

    Returns:
        Tuple of (successful_embeddings, still_failed_indices)
        where successful_embeddings is a list of (index, embedding) tuples
    """
    successful_embeddings = []
    still_failed = list(failed_indices)

    for attempt in range(max_retries):
        if not still_failed:
            break

        # Exponential backoff: 2^attempt seconds (1s, 2s, 4s)
        if attempt > 0:
            backoff_time = 2 ** attempt
            logger.info(f"Retry attempt {attempt + 1}/{max_retries} after {backoff_time}s backoff")
            time.sleep(backoff_time)

        # Try to generate embeddings for failed chunks
        failed_texts = [chunks[i] for i in still_failed]
        logger.info(f"Retrying {len(failed_texts)} failed chunks (attempt {attempt + 1}/{max_retries})")

        try:
            client = OpenAI(api_key=api_key)

            # Process in smaller batches for retry (reduce chance of rate limit)
            batch_size = 10
            new_still_failed = []

            for batch_start in range(0, len(still_failed), batch_size):
                batch_indices = still_failed[batch_start:batch_start + batch_size]
                batch_texts = [chunks[i] for i in batch_indices]

                try:
                    response = client.embeddings.create(
                        model=model,
                        input=batch_texts
                    )

                    # Extract embeddings and associate with original indices
                    batch_embeddings = [item.embedding for item in response.data]

                    if len(batch_embeddings) == len(batch_indices):
                        # All embeddings in this batch succeeded
                        for idx, embedding in zip(batch_indices, batch_embeddings):
                            successful_embeddings.append((idx, embedding))
                    else:
                        # Partial failure in batch - mark all as failed
                        logger.warning(f"Partial failure in retry batch: expected {len(batch_indices)}, got {len(batch_embeddings)}")
                        new_still_failed.extend(batch_indices)

                except Exception as batch_error:
                    logger.error(f"Error retrying batch: {batch_error}")
                    new_still_failed.extend(batch_indices)

            still_failed = new_still_failed

            if not still_failed:
                logger.info(f"All failed chunks recovered after {attempt + 1} retries")
                break

        except Exception as e:
            logger.error(f"Error during retry attempt {attempt + 1}: {e}")
            # Keep all as failed for next attempt

    return successful_embeddings, still_failed


async def retry_failed_ollama_embeddings(
    failed_indices: List[int],
    chunks: List[str],
    model: str,
    max_retries: int = 3
) -> Tuple[List[Tuple[int, List[float]]], List[int]]:
    """
    Retry generating embeddings for failed chunks using Ollama with exponential backoff.

    Args:
        failed_indices: List of indices where embeddings failed
        chunks: Original list of all text chunks
        model: Ollama model to use
        max_retries: Maximum number of retry attempts

    Returns:
        Tuple of (successful_embeddings, still_failed_indices)
    """
    successful_embeddings = []
    still_failed = list(failed_indices)

    for attempt in range(max_retries):
        if not still_failed:
            break

        # Exponential backoff
        if attempt > 0:
            backoff_time = 2 ** attempt
            logger.info(f"Retry attempt {attempt + 1}/{max_retries} after {backoff_time}s backoff")
            await asyncio.sleep(backoff_time)

        logger.info(f"Retrying {len(still_failed)} failed chunks with Ollama (attempt {attempt + 1}/{max_retries})")

        try:
            # FEATURE #142: Increased timeout from 60s to 180s for retry
            async with httpx.AsyncClient(timeout=180.0) as client:
                new_still_failed = []

                for idx in still_failed:
                    text = chunks[idx]
                    try:
                        response = await client.post(
                            f"{OLLAMA_BASE_URL}/api/embeddings",
                            json={"model": model, "prompt": text}
                        )

                        if response.status_code == 200:
                            data = response.json()
                            embedding = data.get("embedding", [])
                            if embedding:
                                successful_embeddings.append((idx, embedding))
                            else:
                                new_still_failed.append(idx)
                        else:
                            new_still_failed.append(idx)

                    except Exception as e:
                        logger.error(f"Error retrying chunk {idx}: {e}")
                        new_still_failed.append(idx)

                still_failed = new_still_failed

                if not still_failed:
                    logger.info(f"All failed chunks recovered after {attempt + 1} retries")
                    break

        except Exception as e:
            logger.error(f"Error during Ollama retry attempt {attempt + 1}: {e}")

    return successful_embeddings, still_failed


# ========== FEATURE #301: OpenRouter Embedding Provider ==========
OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"


async def generate_openrouter_embeddings(
    texts: List[str],
    api_key: str,
    model: str = "qwen/qwen3-embedding-8b"
) -> List[List[float]]:
    """
    Generate embeddings for a list of texts using OpenRouter API.

    FEATURE #301: OpenRouter embedding provider backend.

    Args:
        texts: List of text strings to embed
        api_key: OpenRouter API key
        model: Embedding model to use (default: qwen/qwen3-embedding-8b)

    Returns:
        List of embedding vectors
    """
    if not texts:
        return []

    if not api_key:
        logger.error("[Feature #301] OpenRouter API key not configured")
        return []

    try:
        # Process in batches of 100 (matching OpenAI's limit)
        batch_size = 100
        all_embeddings = []

        async with httpx.AsyncClient(timeout=120.0) as client:
            for batch_start in range(0, len(texts), batch_size):
                batch = texts[batch_start:batch_start + batch_size]
                batch_embeddings = None

                # Retry with exponential backoff for rate limits
                for retry in range(4):  # 0, 1, 2, 3 = up to 4 attempts
                    try:
                        response = await client.post(
                            OPENROUTER_EMBEDDINGS_URL,
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                                "HTTP-Referer": "http://localhost:3009",  # Required by OpenRouter
                                "X-Title": "Agentic RAG System"
                            },
                            json={
                                "model": model,
                                "input": batch
                            }
                        )

                        if response.status_code == 200:
                            data = response.json()
                            # OpenRouter uses OpenAI-compatible format: response.data[].embedding
                            batch_embeddings = [item["embedding"] for item in data.get("data", [])]
                            if len(batch_embeddings) == len(batch):
                                break  # Success
                            else:
                                logger.warning(f"[Feature #301] Batch returned {len(batch_embeddings)}/{len(batch)} embeddings")
                                batch_embeddings = None

                        elif response.status_code == 429:
                            # Rate limited - exponential backoff
                            backoff_time = 2 ** retry  # 1s, 2s, 4s, 8s
                            logger.warning(f"[Feature #301] Rate limited (429). Waiting {backoff_time}s before retry {retry + 1}/4")
                            await asyncio.sleep(backoff_time)

                        elif response.status_code == 401:
                            logger.error(f"[Feature #301] Authentication failed (401). Check OpenRouter API key.")
                            return all_embeddings  # Return what we have

                        elif response.status_code == 400:
                            logger.error(f"[Feature #301] Bad request (400): {response.text[:500]}")
                            return all_embeddings  # Return what we have

                        else:
                            logger.warning(f"[Feature #301] OpenRouter returned {response.status_code}: {response.text[:200]}")
                            if retry < 3:
                                backoff_time = 2 ** retry
                                await asyncio.sleep(backoff_time)

                    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
                        logger.warning(f"[Feature #301] Timeout for batch {batch_start//batch_size} (attempt {retry + 1}/4): {e}")
                        if retry < 3:
                            await asyncio.sleep(2 ** retry)

                    except Exception as e:
                        logger.warning(f"[Feature #301] Error for batch {batch_start//batch_size} (attempt {retry + 1}/4): {e}")
                        if retry < 3:
                            await asyncio.sleep(2 ** retry)

                if batch_embeddings:
                    all_embeddings.extend(batch_embeddings)
                else:
                    logger.warning(f"[Feature #301] Batch {batch_start//batch_size} failed after 4 attempts")

        logger.info(f"[Feature #301] Generated {len(all_embeddings)}/{len(texts)} embeddings using OpenRouter {model}")
        return all_embeddings

    except httpx.ConnectError:
        logger.error("[Feature #301] Cannot connect to OpenRouter API")
        return []
    except Exception as e:
        logger.error(f"[Feature #301] Error generating OpenRouter embeddings: {e}")
        return []


async def retry_failed_openrouter_embeddings(
    failed_indices: List[int],
    chunks: List[str],
    api_key: str,
    model: str,
    max_retries: int = 3
) -> Tuple[List[Tuple[int, List[float]]], List[int]]:
    """
    Retry generating embeddings for failed chunks using OpenRouter with exponential backoff.

    FEATURE #301: Partial failure recovery for OpenRouter embeddings.

    Args:
        failed_indices: List of indices where embeddings failed
        chunks: Original list of all text chunks
        api_key: OpenRouter API key
        model: OpenRouter embedding model to use
        max_retries: Maximum number of retry attempts

    Returns:
        Tuple of (successful_embeddings, still_failed_indices)
        where successful_embeddings is a list of (index, embedding) tuples
    """
    successful_embeddings = []
    still_failed = list(failed_indices)

    if not api_key:
        logger.error("[Feature #301] Cannot retry without OpenRouter API key")
        return successful_embeddings, still_failed

    for attempt in range(max_retries):
        if not still_failed:
            break

        # Exponential backoff
        if attempt > 0:
            backoff_time = 2 ** attempt
            logger.info(f"[Feature #301] Retry attempt {attempt + 1}/{max_retries} after {backoff_time}s backoff")
            await asyncio.sleep(backoff_time)

        logger.info(f"[Feature #301] Retrying {len(still_failed)} failed chunks with OpenRouter (attempt {attempt + 1}/{max_retries})")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                new_still_failed = []

                # Process in smaller batches for retry (reduce chance of rate limit)
                batch_size = 10

                for batch_start in range(0, len(still_failed), batch_size):
                    batch_indices = still_failed[batch_start:batch_start + batch_size]
                    batch_texts = [chunks[i] for i in batch_indices]

                    try:
                        response = await client.post(
                            OPENROUTER_EMBEDDINGS_URL,
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                                "HTTP-Referer": "http://localhost:3009",
                                "X-Title": "Agentic RAG System"
                            },
                            json={
                                "model": model,
                                "input": batch_texts
                            }
                        )

                        if response.status_code == 200:
                            data = response.json()
                            batch_embeddings = [item["embedding"] for item in data.get("data", [])]

                            if len(batch_embeddings) == len(batch_indices):
                                # All embeddings in this batch succeeded
                                for idx, embedding in zip(batch_indices, batch_embeddings):
                                    successful_embeddings.append((idx, embedding))
                            else:
                                # Partial failure in batch - mark all as failed
                                logger.warning(f"[Feature #301] Partial failure in retry batch: expected {len(batch_indices)}, got {len(batch_embeddings)}")
                                new_still_failed.extend(batch_indices)

                        elif response.status_code == 429:
                            # Rate limited during retry - add back to failed and try later
                            logger.warning(f"[Feature #301] Rate limited during retry batch")
                            new_still_failed.extend(batch_indices)
                            await asyncio.sleep(2)  # Short wait before continuing

                        else:
                            logger.warning(f"[Feature #301] Retry batch failed with status {response.status_code}")
                            new_still_failed.extend(batch_indices)

                    except Exception as batch_error:
                        logger.error(f"[Feature #301] Error retrying batch: {batch_error}")
                        new_still_failed.extend(batch_indices)

                still_failed = new_still_failed

                if not still_failed:
                    logger.info(f"[Feature #301] All failed chunks recovered after {attempt + 1} retries")
                    break

        except Exception as e:
            logger.error(f"[Feature #301] Error during OpenRouter retry attempt {attempt + 1}: {e}")

    return successful_embeddings, still_failed


async def wait_for_ollama_ready(embedding_model: str, max_wait: int = 60) -> bool:
    """
    FEATURE #142: Wait for Ollama GPU readiness before embedding generation.

    After semantic chunking with an LLM model (e.g. qwen3:32b), the LLM may still
    be loaded in VRAM. This function waits for the LLM to be unloaded and then
    warms up the embedding model before batch embedding generation.

    Args:
        embedding_model: The Ollama embedding model name (without 'ollama:' prefix)
        max_wait: Maximum seconds to wait for LLM model to unload (default 60)

    Returns:
        True if ready, False if timeout/error (will proceed anyway)
    """
    start_time = time.time()

    # Step 1: Check which models are currently loaded in Ollama
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
            if response.status_code == 200:
                data = response.json()
                loaded_models = data.get("models", [])
                loaded_names = [m.get("name", "").split(":")[0] for m in loaded_models]
                logger.info(f"[GPU Readiness] Currently loaded Ollama models: {loaded_names}")

                # Check if the embedding model is already loaded (ideal case)
                embedding_base = embedding_model.split(":")[0]
                if embedding_base in loaded_names and len(loaded_models) == 1:
                    logger.info(f"[GPU Readiness] Embedding model '{embedding_model}' already loaded. Ready!")
                    return True

                # If other models (LLM) are loaded, wait for them to unload
                non_embedding_models = [n for n in loaded_names if n != embedding_base]
                if non_embedding_models:
                    logger.info(f"[GPU Readiness] Waiting for models to unload: {non_embedding_models}")

                    elapsed = 0
                    while elapsed < max_wait:
                        await asyncio.sleep(2)
                        elapsed = time.time() - start_time

                        try:
                            ps_response = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
                            if ps_response.status_code == 200:
                                ps_data = ps_response.json()
                                current_models = ps_data.get("models", [])
                                current_names = [m.get("name", "").split(":")[0] for m in current_models]

                                # Check if LLM models have been unloaded
                                still_loaded = [n for n in current_names if n != embedding_base]
                                if not still_loaded:
                                    logger.info(f"[GPU Readiness] LLM models unloaded after {elapsed:.1f}s. GPU is free.")
                                    break
                                else:
                                    logger.info(f"[GPU Readiness] Still waiting... loaded: {current_names} ({elapsed:.1f}s/{max_wait}s)")
                        except Exception as e:
                            logger.warning(f"[GPU Readiness] Error checking model status: {e}")
                    else:
                        logger.warning(f"[GPU Readiness] Timeout after {max_wait}s waiting for LLM to unload. Proceeding anyway.")
            else:
                logger.warning(f"[GPU Readiness] /api/ps returned status {response.status_code}. Skipping readiness check.")
    except httpx.ConnectError:
        logger.warning("[GPU Readiness] Cannot connect to Ollama for readiness check. Skipping.")
        return False
    except Exception as e:
        logger.warning(f"[GPU Readiness] Error during readiness check: {e}. Skipping.")
        return False

    # Step 2: Warmup the embedding model by sending a small test request
    logger.info(f"[GPU Readiness] Warming up embedding model '{embedding_model}'...")
    warmup_backoffs = [5, 10, 20]

    for attempt, backoff in enumerate(warmup_backoffs):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                warmup_response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/embeddings",
                    json={"model": embedding_model, "prompt": "test"}
                )
                if warmup_response.status_code == 200:
                    warmup_data = warmup_response.json()
                    if warmup_data.get("embedding"):
                        total_wait = time.time() - start_time
                        logger.info(f"[GPU Readiness] ✅ Embedding model '{embedding_model}' warmed up successfully. Total wait: {total_wait:.1f}s")
                        return True
                    else:
                        logger.warning(f"[GPU Readiness] Warmup returned empty embedding (attempt {attempt + 1}/3)")
                else:
                    logger.warning(f"[GPU Readiness] Warmup failed with status {warmup_response.status_code} (attempt {attempt + 1}/3)")
        except Exception as e:
            logger.warning(f"[GPU Readiness] Warmup error (attempt {attempt + 1}/3): {e}")

        if attempt < len(warmup_backoffs) - 1:
            logger.info(f"[GPU Readiness] Retrying warmup in {backoff}s...")
            await asyncio.sleep(backoff)

    total_wait = time.time() - start_time
    logger.error(f"[GPU Readiness] ⚠️ Warmup failed after 3 attempts ({total_wait:.1f}s). Proceeding anyway - batch embedding may still work.")
    return False


async def generate_ollama_embeddings(texts: List[str], model: str = None) -> List[List[float]]:
    """
    Generate embeddings for a list of texts using Ollama API.

    Args:
        texts: List of text strings to embed
        model: Ollama embedding model to use. If None, reads from settings.
               [Feature #233] Removed hardcoded 'nomic-embed-text' default.

    Returns:
        List of embedding vectors
    """
    # [Feature #233] Get model from settings if not provided
    if model is None:
        configured_model = settings_store.get('embedding_model', 'text-embedding-3-small')
        # Parse 'ollama:' prefix if present (e.g., 'ollama:bge-m3:latest' -> 'bge-m3:latest')
        if configured_model.startswith('ollama:'):
            model = configured_model[7:]
        else:
            model = configured_model
        logger.info(f"[Feature #233] Using configured embedding model: {model}")
    if not texts:
        return []

    # FEATURE #142: Increased timeout from 60s to 180s for GPU model loading
    embed_start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            all_embeddings = []
            failed_count = 0

            for i, text in enumerate(texts):
                embedding = None
                # FEATURE #142: Per-chunk retry with backoff instead of returning [] on first error
                for retry in range(3):
                    try:
                        response = await client.post(
                            f"{OLLAMA_BASE_URL}/api/embeddings",
                            json={
                                "model": model,
                                "prompt": text
                            }
                        )

                        if response.status_code == 200:
                            data = response.json()
                            embedding = data.get("embedding", [])
                            if embedding:
                                break  # Success
                            else:
                                logger.warning(f"Empty embedding for chunk {i} (attempt {retry + 1}/3): {text[:50]}...")
                        elif response.status_code == 500:
                            logger.warning(f"Ollama 500 error for chunk {i} (attempt {retry + 1}/3): {response.text[:200]}")
                        else:
                            logger.error(f"Ollama embedding error for chunk {i}: {response.status_code} - {response.text[:200]}")

                    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
                        logger.warning(f"Timeout for chunk {i} (attempt {retry + 1}/3): {e}")
                    except Exception as e:
                        logger.warning(f"Error for chunk {i} (attempt {retry + 1}/3): {e}")

                    # Wait before retry (5s between retries)
                    if retry < 2:
                        logger.info(f"Retrying chunk {i} in 5s...")
                        await asyncio.sleep(5)

                if embedding:
                    all_embeddings.append(embedding)
                else:
                    # FEATURE #142: Don't return [] on first error - log warning and continue
                    logger.warning(f"⚠️ Chunk {i} failed after 3 attempts, skipping (text: '{text[:80]}...')")
                    failed_count += 1

            embed_duration = time.time() - embed_start_time
            logger.info(f"Generated {len(all_embeddings)}/{len(texts)} embeddings using Ollama {model} in {embed_duration:.1f}s ({failed_count} failed)")
            return all_embeddings

    except httpx.ConnectError:
        logger.error("Cannot connect to Ollama. Make sure Ollama is running.")
        return []
    except Exception as e:
        logger.error(f"Error generating Ollama embeddings: {e}")
        return []


async def process_unstructured_document(
    document_id: str,
    file_path: Path,
    mime_type: str,
    document_title: str,
    document_rows_store=None
) -> Tuple[int, Optional[str], Optional[str]]:
    """
    Process an unstructured document: extract text, chunk it, and generate embeddings.

    FEATURE #132: Uses intelligent semantic chunking with LLM-based splitting
    to preserve document structure and keep related content together.

    FEATURE #216: For PDFs with tables, performs hybrid processing:
    - Table data is stored in document_rows for SQL queries
    - Text content is stored as embeddings for semantic search

    Supports both OpenAI and Ollama embedding models. If OpenAI API key is not configured
    or is invalid, will attempt to use Ollama as a fallback.

    FEATURE #122: Validates that ALL chunks get embeddings before storing.
    If partial failure occurs, retries failed chunks with exponential backoff.

    FEATURE #259: Returns the embedding model used for tracking in documents table.

    Args:
        document_id: The document ID
        file_path: Path to the uploaded file
        mime_type: MIME type of the file
        document_title: Title of the document for metadata
        document_rows_store: Optional store for structured table data (Feature #216)

    Returns:
        Tuple of (number of chunks created, warning message if partial failure, embedding model used)
    """
    # Get API key and embedding model from settings
    api_key = settings_store.get('openai_api_key')
    embedding_model = settings_store.get('embedding_model') or 'text-embedding-3-small'
    llm_model = settings_store.get('llm_model') or 'gpt-4o-mini'

    # FEATURE #144: Get separate chunking LLM model (falls back to chat llm_model)
    chunking_llm_model = settings_store.get('chunking_llm_model', '')

    # FEATURE #134: Extract structured document elements (preserves headings, lists, tables)
    from services.document_structure_extractor import DocumentStructureExtractor
    from services.chunking import SemanticChunker
    from services.agentic_splitter import AgenticSplitter

    structure_extractor = DocumentStructureExtractor()

    # FEATURE #216: Use hybrid extraction for PDFs to get both tables and text
    # Feature #333: Use run_in_executor to prevent blocking event loop during structure extraction
    loop = asyncio.get_event_loop()
    hybrid_result = None
    if mime_type == "application/pdf":
        hybrid_result = await loop.run_in_executor(
            None, structure_extractor.extract_hybrid_pdf, file_path
        )
        structured_elements = hybrid_result['text_elements']

        # Store table data if found
        if hybrid_result['has_tables'] and document_rows_store:
            for table_info in hybrid_result['table_data']:
                rows = table_info['rows']
                schema = table_info['schema']
                if rows and schema:
                    try:
                        await document_rows_store.add_rows(document_id, rows, schema)
                        logger.info(f"[Feature #216] Stored {len(rows)} table rows for PDF document {document_id}")
                    except Exception as e:
                        logger.error(f"[Feature #216] Failed to store table rows: {e}")
    else:
        structured_elements = await loop.run_in_executor(
            None, structure_extractor.extract_structure, file_path, mime_type
        )

    # Get chunking configuration from settings
    chunk_strategy = settings_store.get('chunk_strategy', 'semantic')
    max_chunk_size = int(settings_store.get('max_chunk_size', 2000))
    chunk_overlap = int(settings_store.get('chunk_overlap', 200))

    logger.info(f"Using chunk_strategy: {chunk_strategy}, max_chunk_size: {max_chunk_size}, overlap: {chunk_overlap}")

    # FEATURE #136: Use AgenticSplitter for 'agentic' strategy
    if chunk_strategy == 'agentic':
        # FEATURE #144: Determine which LLM model and API key to use for chunking
        # If chunking_llm_model is set, use it; otherwise fall back to chat llm_model
        chunking_model = chunking_llm_model if chunking_llm_model else llm_model
        chunking_api_key = api_key  # default to OpenAI key

        # If chunking model uses OpenRouter, use the OpenRouter API key instead
        if chunking_model.startswith('openrouter:'):
            openrouter_key = settings_store.get('openrouter_api_key', '')
            if openrouter_key:
                chunking_api_key = openrouter_key
                logger.info(f"[Feature #144] Using OpenRouter API key for chunking LLM: {chunking_model}")
            else:
                logger.warning(f"[Feature #144] Chunking model is OpenRouter ({chunking_model}) but no OpenRouter API key configured. Falling back to chat LLM: {llm_model}")
                chunking_model = llm_model
                chunking_api_key = api_key

        logger.info(f"[Feature #144] Chunking LLM: {chunking_model} (separate from chat LLM: {llm_model})")

        # Feature #331: Get timeout setting from config
        agentic_timeout = settings.AGENTIC_SPLITTER_TIMEOUT_SECONDS

        agentic_splitter = AgenticSplitter(
            api_key=chunking_api_key,
            llm_model=chunking_model,
            ollama_base_url=OLLAMA_BASE_URL,
            min_chunk_size=200,
            max_chunk_size=max_chunk_size,
            ideal_chunk_size=max_chunk_size // 2,
            timeout_seconds=agentic_timeout,  # Feature #331: Configurable timeout
        )
        logger.info(f"Using AgenticSplitter (LLM available: {agentic_splitter.has_llm}, timeout: {agentic_timeout}s)")

        if structured_elements:
            logger.info(f"Extracted {len(structured_elements)} structured elements from document {document_id}")
            semantic_chunks = await agentic_splitter.split_elements(structured_elements, document_title=document_title)
        else:
            logger.warning(f"Structure extraction failed, falling back to plain text for agentic splitting")
            # Feature #333: Use async wrapper to prevent blocking event loop
            text = await extract_text_from_file_async(file_path, mime_type)
            if not text:
                logger.warning(f"No text extracted from document {document_id}")
                return 0, "No text content could be extracted from the document", None
            logger.info(f"Extracted {len(text)} characters from document {document_id}")
            semantic_chunks = await agentic_splitter.split(text, document_title=document_title)
    else:
        # Use existing SemanticChunker for 'semantic', 'paragraph', 'fixed' strategies
        chunker = SemanticChunker(
            api_key=api_key,
            llm_model=llm_model,
            ollama_base_url=OLLAMA_BASE_URL,
            max_chunk_size=max_chunk_size,
            chunk_overlap=chunk_overlap
        )

        # Determine whether to use LLM based on chunk_strategy
        use_llm = chunk_strategy == 'semantic'
        logger.info(f"Using SemanticChunker with use_llm={use_llm}")

        # Create semantic chunks from structured elements
        if structured_elements:
            logger.info(f"Extracted {len(structured_elements)} structured elements from document {document_id}")
            semantic_chunks = await chunker.chunk_structured_elements(structured_elements, use_llm=use_llm)
        else:
            # Fallback to text extraction if structure extraction failed
            logger.warning(f"Structure extraction failed, falling back to plain text extraction")
            # Feature #333: Use async wrapper to prevent blocking event loop
            text = await extract_text_from_file_async(file_path, mime_type)
            if not text:
                logger.warning(f"No text extracted from document {document_id}")
                return 0, "No text content could be extracted from the document", None

            logger.info(f"Extracted {len(text)} characters from document {document_id}")
            semantic_chunks = await chunker.chunk_text(text, use_llm=use_llm)

    if not semantic_chunks:
        logger.warning(f"No chunks created for document {document_id}")
        return 0, "Document text could not be split into chunks", None

    # Extract text from semantic chunks for embedding
    # Use get_full_text() to include context_prefix in the embedding
    # This helps with retrieval for queries that span chunk boundaries
    chunks = [chunk.get_full_text() for chunk in semantic_chunks]
    chunk_metadata_list = [chunk.to_dict()['metadata'] for chunk in semantic_chunks]

    logger.info(f"Created {len(chunks)} semantic chunks for document {document_id}")

    # FEATURE #142: Wait for Ollama GPU readiness after semantic chunking
    # If we used semantic/agentic chunking with Ollama LLM, the LLM model may still be
    # loaded in VRAM. We need to wait for it to unload before requesting embeddings.
    if chunk_strategy in ('semantic', 'agentic') and embedding_model.startswith('ollama:'):
        ollama_embed_model = embedding_model[7:]  # Remove 'ollama:' prefix
        logger.info(f"[Feature #142] Checking GPU readiness before embedding with '{ollama_embed_model}'...")
        gpu_ready_start = time.time()
        await wait_for_ollama_ready(ollama_embed_model, max_wait=60)
        gpu_ready_duration = time.time() - gpu_ready_start
        logger.info(f"[Feature #142] GPU readiness check completed in {gpu_ready_duration:.1f}s")
    elif not embedding_model.startswith('ollama:') and chunk_strategy in ('semantic', 'agentic'):
        # Also check for Ollama fallback case - if no OpenAI key, we'll use Ollama
        api_key_check = settings_store.get('openai_api_key')
        if not (api_key_check and api_key_check.startswith('sk-') and len(api_key_check) > 20 and not api_key_check.startswith('sk-test')):
            # [Feature #233] Use configured embedding model instead of hardcoded 'nomic-embed-text'
            # The embedding_model here doesn't have 'ollama:' prefix (due to elif condition),
            # so we use it directly as the model name for Ollama GPU readiness check
            logger.info(f"[Feature #142] No valid OpenAI key, will fallback to Ollama. Checking GPU readiness for '{embedding_model}'...")
            gpu_ready_start = time.time()
            await wait_for_ollama_ready(embedding_model, max_wait=60)
            gpu_ready_duration = time.time() - gpu_ready_start
            logger.info(f"[Feature #142] GPU readiness check (fallback) completed in {gpu_ready_duration:.1f}s")

    # Try to generate embeddings
    embeddings = []
    embedding_source = None
    use_ollama = False
    use_openrouter = False  # Feature #302: Track OpenRouter usage for retry logic

    # Get OpenRouter API key for potential use
    openrouter_api_key = settings_store.get('openrouter_api_key', '')

    # ========== FEATURE #302: Check for OpenRouter embedding model ==========
    if embedding_model.startswith('openrouter:'):
        openrouter_model = embedding_model[11:]  # Remove 'openrouter:' prefix
        logger.info(f"[Feature #302] Using OpenRouter embedding model: {openrouter_model}")
        if openrouter_api_key:
            embeddings = await generate_openrouter_embeddings(chunks, openrouter_api_key, openrouter_model)
            embedding_source = f"openrouter:{openrouter_model}"
            use_openrouter = True
        else:
            logger.error(f"[Feature #302] OpenRouter embedding model configured ({openrouter_model}) but no OpenRouter API key set")
            embeddings = []
    # Check if embedding model is an Ollama model (starts with 'ollama:')
    elif embedding_model.startswith('ollama:'):
        ollama_model = embedding_model[7:]  # Remove 'ollama:' prefix
        logger.info(f"Using Ollama embedding model: {ollama_model}")
        embeddings = await generate_ollama_embeddings(chunks, ollama_model)
        embedding_source = f"ollama:{ollama_model}"
        use_ollama = True
    # Check if we have a valid-looking OpenAI API key
    elif api_key and api_key.startswith('sk-') and len(api_key) > 20 and not api_key.startswith('sk-test'):
        logger.info(f"Using OpenAI embedding model: {embedding_model}")
        # Feature #333: Use async wrapper to prevent blocking event loop
        embeddings = await generate_embeddings_async(chunks, api_key, embedding_model)
        embedding_source = f"openai:{embedding_model}"
        use_ollama = False
    else:
        # ========== FEATURE #302: Updated fallback chain: OpenAI → OpenRouter → Ollama ==========
        logger.info(f"[Feature #302] No valid OpenAI API key - checking fallback chain")

        # Try OpenRouter as fallback if API key is configured
        if openrouter_api_key:
            # Use a default OpenRouter embedding model
            default_openrouter_model = "qwen/qwen3-embedding-8b"
            logger.info(f"[Feature #302] Trying OpenRouter fallback with model: {default_openrouter_model}")
            embeddings = await generate_openrouter_embeddings(chunks, openrouter_api_key, default_openrouter_model)

            if embeddings and len(embeddings) == len(chunks):
                embedding_source = f"openrouter:{default_openrouter_model}"
                logger.info(f"[Feature #302] Successfully generated embeddings with OpenRouter fallback: {default_openrouter_model}")
                use_openrouter = True
            else:
                logger.warning(f"[Feature #302] OpenRouter fallback failed, trying Ollama...")
                embeddings = []  # Reset for Ollama attempt

        # If OpenRouter failed or not configured, try Ollama
        if not embeddings:
            # Feature #231: Use ONLY the configured model, no hardcoded fallback list
            logger.info(f"[Feature #231] Using configured embedding model: {embedding_model}")

            # Parse embedding model from settings (e.g., 'ollama:snowflake-arctic-embed2:latest' -> 'snowflake-arctic-embed2:latest')
            if embedding_model.startswith('ollama:'):
                ollama_model = embedding_model[7:]  # Remove 'ollama:' prefix
            else:
                # If embedding_model doesn't have 'ollama:' prefix, use it as-is
                # This could be a model name like 'text-embedding-3-small' which won't work with Ollama
                logger.warning(f"[Feature #231] Configured embedding model '{embedding_model}' does not have 'ollama:' prefix. Attempting to use it with Ollama anyway.")
                ollama_model = embedding_model

            logger.info(f"[Feature #231] Using configured Ollama embedding model: {ollama_model}")
            embeddings = await generate_ollama_embeddings(chunks, ollama_model)

            if embeddings and len(embeddings) == len(chunks):
                embedding_source = f"ollama:{ollama_model}"
                logger.info(f"[Feature #231] Successfully generated embeddings with configured Ollama model: {ollama_model}")
                use_ollama = True
            else:
                # Clear error message instead of trying other models
                logger.error(f"[Feature #231] Failed to generate embeddings with configured model '{ollama_model}'")
                embeddings = []  # Ensure empty for validation below

    # ========== FEATURE #122: STRICT VALIDATION ==========
    # Validate that ALL chunks got embeddings before storing
    total_chunks = len(chunks)
    total_embeddings = len(embeddings)

    logger.info(f"Embedding generation result: {total_embeddings}/{total_chunks} chunks")

    if total_embeddings == 0:
        logger.error(f"❌ CRITICAL: Zero embeddings generated for document {document_id} (expected {total_chunks})")
        return 0, f"Failed to generate any embeddings. All {total_chunks} chunks failed.", None

    if total_embeddings != total_chunks:
        # PARTIAL FAILURE DETECTED
        logger.warning(f"⚠️  PARTIAL FAILURE: Only {total_embeddings}/{total_chunks} embeddings generated for document {document_id}")

        # Identify which chunks failed
        failed_indices = list(set(range(total_chunks)) - set(range(total_embeddings)))
        logger.error(f"Failed chunk indices: {failed_indices}")

        # Log details about each failed chunk
        for idx in failed_indices[:10]:  # Log first 10 to avoid spam
            logger.error(f"  - Chunk {idx}: '{chunks[idx][:100]}...'")
        if len(failed_indices) > 10:
            logger.error(f"  ... and {len(failed_indices) - 10} more failed chunks")

        # ========== RETRY WITH EXPONENTIAL BACKOFF ==========
        logger.info(f"🔄 Starting retry process for {len(failed_indices)} failed chunks...")

        if use_openrouter:
            # Feature #302: Retry with OpenRouter
            model_name = embedding_source.split(':', 1)[1] if ':' in embedding_source else "qwen/qwen3-embedding-8b"
            logger.info(f"[Feature #302] Retrying failed chunks with OpenRouter model: {model_name}")
            retry_embeddings, still_failed = await retry_failed_openrouter_embeddings(
                failed_indices, chunks, openrouter_api_key, model_name, max_retries=3
            )
        elif use_ollama:
            # Extract model name from embedding_source
            # [Feature #233] Use configured embedding model as fallback instead of hardcoded 'nomic-embed-text'
            configured_model = settings_store.get('embedding_model', 'text-embedding-3-small')
            fallback_model = configured_model[7:] if configured_model.startswith('ollama:') else configured_model
            model_name = embedding_source.split(':', 1)[1] if ':' in embedding_source else fallback_model
            retry_embeddings, still_failed = await retry_failed_ollama_embeddings(
                failed_indices, chunks, model_name, max_retries=3
            )
        else:
            retry_embeddings, still_failed = retry_failed_embeddings(
                failed_indices, chunks, api_key, embedding_model, max_retries=3
            )

        # Merge retry results into main embeddings list
        # Convert embeddings list to dict for easier insertion
        embeddings_dict = {i: embeddings[i] for i in range(len(embeddings))}

        for idx, embedding in retry_embeddings:
            embeddings_dict[idx] = embedding
            logger.info(f"✅ Recovered chunk {idx} after retry")

        # Convert back to list, sorted by index
        embeddings = [embeddings_dict[i] for i in sorted(embeddings_dict.keys()) if i in embeddings_dict]

        # Final validation after retries
        if still_failed:
            logger.error(f"❌ FAILED AFTER RETRIES: {len(still_failed)} chunks still failed")
            logger.error(f"Permanently failed chunk indices: {still_failed}")

            # Log specific details about permanently failed chunks
            for idx in still_failed[:5]:
                logger.error(f"  - Permanently failed chunk {idx}: '{chunks[idx][:100]}...'")

            warning_msg = (
                f"⚠️ WARNING: Partial embedding failure. "
                f"{len(still_failed)}/{total_chunks} chunks failed even after 3 retry attempts. "
                f"Document may have incomplete search coverage. "
                f"Failed chunks: {still_failed[:10]}"
            )
            return len(embeddings), warning_msg, embedding_source
        else:
            logger.info(f"✅ All failed chunks recovered after retry!")
            # Continue with full embeddings list

    # Final sanity check
    if len(embeddings) != len(chunks):
        logger.error(f"❌ VALIDATION FAILED: embeddings count ({len(embeddings)}) != chunks count ({len(chunks)})")
        return 0, f"Embedding validation failed: {len(embeddings)}/{len(chunks)} succeeded", None

    logger.info(f"✅ Validation passed: All {len(chunks)} chunks have embeddings using {embedding_source}")

    # Get embedding dimension from first embedding
    embedding_dimension = len(embeddings[0]) if embeddings else 0
    logger.info(f"Embedding dimension: {embedding_dimension}")

    # Store chunks with embeddings
    # FEATURE #132: Include rich semantic metadata from chunker
    chunk_data = []
    for i, (chunk_text_content, embedding, chunk_meta) in enumerate(zip(chunks, embeddings, chunk_metadata_list)):
        # Merge chunker metadata with embedding metadata
        combined_metadata = {
            "document_title": document_title,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "embedding_source": embedding_source,
            "embedding_dimension": embedding_dimension,
            # FEATURE #132: Add semantic metadata
            "section_title": chunk_meta.get("section_title"),
            "chunk_type": chunk_meta.get("chunk_type"),
            "position_in_doc": chunk_meta.get("position_in_doc"),
            "total_sections": chunk_meta.get("total_sections"),
            "char_count": chunk_meta.get("char_count"),
            # FEATURE #133: Add context overlap metadata
            "context_prefix": chunk_meta.get("context_prefix"),
            "has_context": chunk_meta.get("has_context", False)
        }

        chunk_data.append({
            "text": chunk_text_content,
            "embedding": embedding,
            "metadata": combined_metadata
        })

    num_stored = embedding_store.add_chunks(document_id, chunk_data)
    logger.info(f"Stored {num_stored} chunks with embeddings for document {document_id}")

    # Feature #186: Also add chunks to BM25 index for hybrid search
    try:
        from services.bm25_service import bm25_service
        bm25_stored = bm25_service.add_chunks(document_id, chunk_data)
        logger.info(f"[Feature #186] Stored {bm25_stored} chunks in BM25 index for document {document_id}")
    except Exception as e:
        logger.warning(f"[Feature #186] Failed to add chunks to BM25 index: {e}")

    # Validate that embeddings were actually stored
    if num_stored == 0:
        logger.error(f"❌ STORAGE FAILED: Failed to store any embeddings for document {document_id}")
        return 0, "Embedding storage failed - no chunks were stored in the database", None
    elif num_stored != len(chunk_data):
        logger.warning(f"⚠️  STORAGE PARTIAL: Only stored {num_stored}/{len(chunk_data)} embeddings for document {document_id}")
        warning_msg = f"Partial storage: Only {num_stored}/{len(chunk_data)} chunks were stored in database"
        return num_stored, warning_msg, embedding_source

    # Feature #259: Return embedding_source for tracking which model was used
    return num_stored, None, embedding_source


async def generate_embeddings_for_reembed(
    document_id: str,
    file_path: Path,
    mime_type: str,
    document_title: str,
) -> Tuple[List[Dict], Optional[str], Optional[str]]:
    """
    Feature #268: Generate embeddings for re-embedding WITHOUT storing them.

    This function performs all the embedding generation steps but returns the
    chunk_data list instead of storing it. This allows the caller to use
    atomic transactions for DELETE old + INSERT new operations.

    Args:
        document_id: The document ID
        file_path: Path to the uploaded file
        mime_type: MIME type of the file
        document_title: Title of the document for metadata

    Returns:
        Tuple of (chunk_data list, warning message if any, embedding_source identifier)
        - chunk_data: List of dicts with 'text', 'embedding', 'metadata' keys
        - warning: Optional warning message for partial failures
        - embedding_source: Model identifier (e.g., 'ollama:bge-m3')
    """
    # Get API key and embedding model from settings
    api_key = settings_store.get('openai_api_key')
    embedding_model = settings_store.get('embedding_model') or 'text-embedding-3-small'
    llm_model = settings_store.get('llm_model') or 'gpt-4o-mini'

    # FEATURE #144: Get separate chunking LLM model (falls back to chat llm_model)
    chunking_llm_model = settings_store.get('chunking_llm_model', '')

    # FEATURE #134: Extract structured document elements
    from services.document_structure_extractor import DocumentStructureExtractor
    from services.chunking import SemanticChunker
    from services.agentic_splitter import AgenticSplitter

    structure_extractor = DocumentStructureExtractor()

    # FEATURE #216: Use hybrid extraction for PDFs
    # Feature #333: Use run_in_executor to prevent blocking event loop during structure extraction
    loop = asyncio.get_event_loop()
    hybrid_result = None
    if mime_type == "application/pdf":
        hybrid_result = await loop.run_in_executor(
            None, structure_extractor.extract_hybrid_pdf, file_path
        )
        structured_elements = hybrid_result['text_elements']
        # Note: Don't store table data in re-embed - it's already stored
    else:
        structured_elements = await loop.run_in_executor(
            None, structure_extractor.extract_structure, file_path, mime_type
        )

    # Get chunking configuration from settings
    chunk_strategy = settings_store.get('chunk_strategy', 'semantic')
    max_chunk_size = int(settings_store.get('max_chunk_size', 2000))
    chunk_overlap = int(settings_store.get('chunk_overlap', 200))

    logger.info(f"[Feature #268] Using chunk_strategy: {chunk_strategy}, max_chunk_size: {max_chunk_size}")

    # Use appropriate splitter based on strategy
    if chunk_strategy == 'agentic':
        chunking_model = chunking_llm_model if chunking_llm_model else llm_model
        chunking_api_key = api_key

        if chunking_model.startswith('openrouter:'):
            openrouter_key = settings_store.get('openrouter_api_key', '')
            if openrouter_key:
                chunking_api_key = openrouter_key

        # Feature #331: Get timeout setting from config
        agentic_timeout = settings.AGENTIC_SPLITTER_TIMEOUT_SECONDS

        agentic_splitter = AgenticSplitter(
            api_key=chunking_api_key,
            llm_model=chunking_model,
            ollama_base_url=OLLAMA_BASE_URL,
            min_chunk_size=200,
            max_chunk_size=max_chunk_size,
            ideal_chunk_size=max_chunk_size // 2,
            timeout_seconds=agentic_timeout,  # Feature #331: Configurable timeout
        )

        if structured_elements:
            semantic_chunks = await agentic_splitter.split_elements(structured_elements, document_title=document_title)
        else:
            # Feature #333: Use async wrapper to prevent blocking event loop
            text = await extract_text_from_file_async(file_path, mime_type)
            if not text:
                return [], "No text content could be extracted from the document", None
            semantic_chunks = await agentic_splitter.split(text, document_title=document_title)
    else:
        chunker = SemanticChunker(
            api_key=api_key,
            llm_model=llm_model,
            ollama_base_url=OLLAMA_BASE_URL,
            max_chunk_size=max_chunk_size,
            chunk_overlap=chunk_overlap
        )

        use_llm = chunk_strategy == 'semantic'

        if structured_elements:
            semantic_chunks = await chunker.chunk_structured_elements(structured_elements, use_llm=use_llm)
        else:
            # Feature #333: Use async wrapper to prevent blocking event loop
            text = await extract_text_from_file_async(file_path, mime_type)
            if not text:
                return [], "No text content could be extracted from the document", None
            semantic_chunks = await chunker.chunk_text(text, use_llm=use_llm)

    if not semantic_chunks:
        return [], "Document text could not be split into chunks", None

    # Extract text from semantic chunks for embedding
    chunks = [chunk.get_full_text() for chunk in semantic_chunks]
    chunk_metadata_list = [chunk.to_dict()['metadata'] for chunk in semantic_chunks]

    logger.info(f"[Feature #268] Created {len(chunks)} semantic chunks for document {document_id}")

    # Wait for Ollama GPU readiness if needed
    if chunk_strategy in ('semantic', 'agentic') and embedding_model.startswith('ollama:'):
        ollama_embed_model = embedding_model[7:]
        await wait_for_ollama_ready(ollama_embed_model, max_wait=60)
    elif not embedding_model.startswith('ollama:') and chunk_strategy in ('semantic', 'agentic'):
        api_key_check = settings_store.get('openai_api_key')
        if not (api_key_check and api_key_check.startswith('sk-') and len(api_key_check) > 20 and not api_key_check.startswith('sk-test')):
            await wait_for_ollama_ready(embedding_model, max_wait=60)

    # Generate embeddings
    embeddings = []
    embedding_source = None
    use_ollama = False
    use_openrouter = False  # Feature #302: Track OpenRouter usage for retry logic

    # Get OpenRouter API key for potential use
    openrouter_api_key = settings_store.get('openrouter_api_key', '')

    # ========== FEATURE #302: Check for OpenRouter embedding model ==========
    if embedding_model.startswith('openrouter:'):
        openrouter_model = embedding_model[11:]  # Remove 'openrouter:' prefix
        logger.info(f"[Feature #302] Using OpenRouter embedding model for re-embed: {openrouter_model}")
        if openrouter_api_key:
            embeddings = await generate_openrouter_embeddings(chunks, openrouter_api_key, openrouter_model)
            embedding_source = f"openrouter:{openrouter_model}"
            use_openrouter = True
        else:
            logger.error(f"[Feature #302] OpenRouter embedding model configured ({openrouter_model}) but no OpenRouter API key set")
            return [], f"OpenRouter API key not configured for model '{openrouter_model}'", None
    elif embedding_model.startswith('ollama:'):
        ollama_model = embedding_model[7:]
        embeddings = await generate_ollama_embeddings(chunks, ollama_model)
        embedding_source = f"ollama:{ollama_model}"
        use_ollama = True
    elif api_key and api_key.startswith('sk-') and len(api_key) > 20 and not api_key.startswith('sk-test'):
        # Feature #333: Use async wrapper to prevent blocking event loop
        embeddings = await generate_embeddings_async(chunks, api_key, embedding_model)
        embedding_source = f"openai:{embedding_model}"
        use_ollama = False
    else:
        # ========== FEATURE #302: Updated fallback chain: OpenAI → OpenRouter → Ollama ==========
        logger.info(f"[Feature #302] No valid OpenAI API key for re-embed - checking fallback chain")

        # Try OpenRouter as fallback if API key is configured
        if openrouter_api_key:
            default_openrouter_model = "qwen/qwen3-embedding-8b"
            logger.info(f"[Feature #302] Trying OpenRouter fallback for re-embed: {default_openrouter_model}")
            embeddings = await generate_openrouter_embeddings(chunks, openrouter_api_key, default_openrouter_model)

            if embeddings and len(embeddings) == len(chunks):
                embedding_source = f"openrouter:{default_openrouter_model}"
                logger.info(f"[Feature #302] Successfully generated embeddings with OpenRouter fallback: {default_openrouter_model}")
                use_openrouter = True
            else:
                logger.warning(f"[Feature #302] OpenRouter fallback failed for re-embed, trying Ollama...")
                embeddings = []  # Reset for Ollama attempt

        # If OpenRouter failed or not configured, try Ollama
        if not embeddings:
            if embedding_model.startswith('ollama:'):
                ollama_model = embedding_model[7:]
            else:
                ollama_model = embedding_model

            embeddings = await generate_ollama_embeddings(chunks, ollama_model)

            if embeddings and len(embeddings) == len(chunks):
                embedding_source = f"ollama:{ollama_model}"
                use_ollama = True
            else:
                return [], f"Failed to generate embeddings with configured model '{ollama_model}'", None

    # Validate embeddings
    total_chunks = len(chunks)
    total_embeddings = len(embeddings)

    if total_embeddings == 0:
        return [], f"Failed to generate any embeddings. All {total_chunks} chunks failed.", None

    if total_embeddings != total_chunks:
        # Retry failed chunks
        failed_indices = list(set(range(total_chunks)) - set(range(total_embeddings)))

        if use_openrouter:
            # Feature #302: Retry with OpenRouter
            model_name = embedding_source.split(':', 1)[1] if ':' in embedding_source else "qwen/qwen3-embedding-8b"
            logger.info(f"[Feature #302] Retrying failed chunks for re-embed with OpenRouter model: {model_name}")
            retry_embeddings, still_failed = await retry_failed_openrouter_embeddings(
                failed_indices, chunks, openrouter_api_key, model_name, max_retries=3
            )
        elif use_ollama:
            configured_model = settings_store.get('embedding_model', 'text-embedding-3-small')
            fallback_model = configured_model[7:] if configured_model.startswith('ollama:') else configured_model
            model_name = embedding_source.split(':', 1)[1] if ':' in embedding_source else fallback_model
            retry_embeddings, still_failed = await retry_failed_ollama_embeddings(
                failed_indices, chunks, model_name, max_retries=3
            )
        else:
            retry_embeddings, still_failed = retry_failed_embeddings(
                failed_indices, chunks, api_key, embedding_model, max_retries=3
            )

        embeddings_dict = {i: embeddings[i] for i in range(len(embeddings))}
        for idx, embedding in retry_embeddings:
            embeddings_dict[idx] = embedding

        embeddings = [embeddings_dict[i] for i in sorted(embeddings_dict.keys()) if i in embeddings_dict]

        if still_failed:
            warning_msg = (
                f"Partial embedding failure. {len(still_failed)}/{total_chunks} chunks failed "
                f"even after 3 retry attempts."
            )
            # Continue with partial embeddings, but note the warning
        else:
            logger.info(f"[Feature #268] All failed chunks recovered after retry")

    # Final validation
    if len(embeddings) != len(chunks):
        return [], f"Embedding validation failed: {len(embeddings)}/{len(chunks)} succeeded", None

    # Get embedding dimension from first embedding
    embedding_dimension = len(embeddings[0]) if embeddings else 0

    # Build chunk_data WITHOUT storing
    chunk_data = []
    for i, (chunk_text_content, embedding, chunk_meta) in enumerate(zip(chunks, embeddings, chunk_metadata_list)):
        combined_metadata = {
            "document_title": document_title,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "embedding_source": embedding_source,
            "embedding_dimension": embedding_dimension,
            "section_title": chunk_meta.get("section_title"),
            "chunk_type": chunk_meta.get("chunk_type"),
            "position_in_doc": chunk_meta.get("position_in_doc"),
            "total_sections": chunk_meta.get("total_sections"),
            "char_count": chunk_meta.get("char_count"),
            "context_prefix": chunk_meta.get("context_prefix"),
            "has_context": chunk_meta.get("has_context", False)
        }

        chunk_data.append({
            "text": chunk_text_content,
            "embedding": embedding,
            "metadata": combined_metadata
        })

    logger.info(f"[Feature #268] Generated {len(chunk_data)} chunk embeddings (NOT YET STORED) for document {document_id}")

    return chunk_data, None, embedding_source


# Feature #330: Queue status endpoint models (defined early for routing priority)
class QueueStatusResponse(BaseModel):
    """Response model for processing queue status."""
    running: bool
    queue_size: int
    max_queue_size: int
    queued_count: int
    processing_count: int
    completed_count: int
    failed_count: int
    total_processed: int
    total_failed: int
    average_processing_time_ms: int
    started_at: Optional[str] = None
    current_item: Optional[dict] = None
    queued_items: List[dict] = []


class DocumentQueueStatusResponse(BaseModel):
    """Response model for individual document queue status."""
    document_id: str
    found: bool
    status: Optional[str] = None  # 'queued', 'processing', 'completed', 'failed'
    queued_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    result: Optional[dict] = None


@router.get("/queue/status", response_model=QueueStatusResponse)
async def get_queue_status():
    """
    Get the status of the document processing queue.

    Feature #330: Returns queue statistics including:
    - Number of documents waiting to be processed
    - Currently processing document
    - Processing statistics (total processed, failures, avg time)
    """
    try:
        from services.document_queue import get_document_queue
        queue = get_document_queue()
        return QueueStatusResponse(**queue.get_queue_status())
    except Exception as e:
        logger.error(f"[Feature #330] Error getting queue status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get queue status: {str(e)}"
        )


@router.get("/queue/status/{document_id}", response_model=DocumentQueueStatusResponse)
async def get_document_queue_status(document_id: str):
    """
    Get the queue status of a specific document.

    Feature #330: Returns the processing status for a document that was
    queued for background processing.
    """
    try:
        from services.document_queue import get_document_queue
        queue = get_document_queue()
        item = queue.get_item_status(document_id)

        if item is None:
            return DocumentQueueStatusResponse(
                document_id=document_id,
                found=False
            )

        return DocumentQueueStatusResponse(
            document_id=document_id,
            found=True,
            status=item.status.value,
            queued_at=item.queued_at.isoformat() if item.queued_at else None,
            started_at=item.started_at.isoformat() if item.started_at else None,
            completed_at=item.completed_at.isoformat() if item.completed_at else None,
            error_message=item.error_message,
            result=item.result
        )
    except Exception as e:
        logger.error(f"[Feature #330] Error getting document queue status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document queue status: {str(e)}"
        )


@router.get("/", response_model=List[Document])
async def list_documents(document_store=Depends(get_document_store)):
    """List all documents."""
    return await document_store.get_all()


@router.get("/{document_id}", response_model=Document)
async def get_document(document_id: str, document_store=Depends(get_document_store)):
    """
    Get a document by ID.

    Feature #293: Verifies file integrity on access and updates status to 'file_missing'
    if the file no longer exists on disk. Returns the document with updated status.
    Feature #327: Uses standardized error responses.
    """
    doc = await document_store.get(document_id)
    if not doc:
        # Feature #327: Use standardized NotFoundError
        raise NotFoundError("Document", document_id)

    # Feature #293: Check file integrity and update status if file is missing
    # Only check for unstructured documents (structured data is stored in DB)
    if doc.document_type == "unstructured":
        try:
            # This updates the status to 'file_missing' if file doesn't exist
            # but doesn't raise an exception (raise_if_missing=False)
            file_path, file_exists = await check_file_integrity_and_update_status(
                document_id,
                document_store,
                raise_if_missing=False
            )

            # If status was updated, refresh the document from the database
            if not file_exists:
                logger.warning(f"[Feature #293] Document {document_id} file is missing, status updated to 'file_missing'")
                doc = await document_store.get(document_id)
        except Exception as e:
            logger.error(f"[Feature #293] Error checking file integrity for {document_id}: {e}")
            # Don't fail the request, just log the error

    return doc


class DocumentPreviewResponse(BaseModel):
    """Response model for document preview endpoint."""
    document_id: str
    document_type: str  # 'structured' or 'unstructured'
    preview_type: str  # 'table' or 'text'
    content: Optional[str] = None  # Text content for unstructured
    rows: Optional[List[dict]] = None  # Table rows for structured
    columns: Optional[List[str]] = None  # Column headers for structured
    total_rows: Optional[int] = None  # Total rows count for structured
    preview_rows: Optional[int] = None  # Number of rows in preview


@router.get("/{document_id}/preview", response_model=DocumentPreviewResponse)
async def get_document_preview(
    document_id: str,
    max_rows: int = 10,
    max_chars: int = 2000,
    document_store=Depends(get_document_store),
    document_rows_store=Depends(get_document_rows_store)
):
    """
    Get a preview of document content.

    For structured data (CSV/Excel/JSON): Returns first N rows as table data.
    For unstructured data (PDF/TXT/Word/MD): Returns text excerpt.

    Args:
        document_id: The document ID
        max_rows: Maximum rows to return for structured data (default 10)
        max_chars: Maximum characters for text preview (default 2000)
    """
    # Get document
    doc = await document_store.get(document_id)
    if not doc:
        # Feature #327: Use standardized NotFoundError
        raise NotFoundError("Document", document_id)

    # Handle structured data (CSV, Excel, JSON)
    if doc.document_type == "structured":
        rows = await document_rows_store.get_rows(document_id)
        columns = await document_rows_store.get_schema(document_id)

        # Get preview rows (limited)
        preview_rows = [row["data"] for row in rows[:max_rows]]

        return DocumentPreviewResponse(
            document_id=document_id,
            document_type="structured",
            preview_type="table",
            rows=preview_rows,
            columns=columns,
            total_rows=len(rows),
            preview_rows=len(preview_rows)
        )

    # Handle unstructured data (PDF, TXT, Word, Markdown)
    else:
        # Feature #255: Check file integrity and update status before proceeding
        # This will raise HTTPException if file is missing and update status to 'file_missing'
        file_path, file_exists = await check_file_integrity_and_update_status(
            document_id,
            document_store,
            raise_if_missing=True
        )

        text_content = ""
        if file_path and file_exists:
            # Extract text from the file
            text_content = extract_text_from_file(file_path, doc.mime_type)

        # Truncate text for preview
        if len(text_content) > max_chars:
            # Try to break at a word boundary
            truncated = text_content[:max_chars]
            last_space = truncated.rfind(' ')
            if last_space > max_chars * 0.8:  # Only break at space if reasonably close
                truncated = truncated[:last_space]
            text_content = truncated + "..."

        return DocumentPreviewResponse(
            document_id=document_id,
            document_type="unstructured",
            preview_type="text",
            content=text_content if text_content else "No preview available. The document content could not be extracted."
        )


@router.post("/", response_model=Document, status_code=status.HTTP_201_CREATED)
async def create_document(document: DocumentCreate, document_store=Depends(get_document_store)):
    """Create a new document."""
    return await document_store.create(document)


@router.patch("/{document_id}", response_model=Document)
async def update_document(document_id: str, update: DocumentUpdate, document_store=Depends(get_document_store)):
    """
    Update a document's name, comment, or collection.

    Only provided fields will be updated.
    """
    doc = await document_store.update(document_id, update)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found"
        )

    # If title was updated, update chunk metadata to keep search results in sync
    if update.title is not None:
        updated_chunks = embedding_store.update_document_title(document_id, update.title)
        logger.info(f"Updated title in {updated_chunks} chunks for document {document_id}")

    return doc


@router.delete("/bulk-cleanup")
async def bulk_cleanup_documents(document_store=Depends(get_document_store)):
    """
    Remove all test documents created by bulk-generate.

    Removes documents with titles starting with 'Test Document'.

    Feature #213: Automatically creates a backup before bulk delete if require_backup_before_delete is enabled.
    """
    from services.pre_destructive_backup import create_pre_destructive_backup

    docs = await document_store.get_all()
    docs_to_delete = [doc for doc in docs if doc.title.startswith("Test Document ")]

    if docs_to_delete:
        # Feature #213: Create pre-destructive backup before bulk delete
        backup_result = await create_pre_destructive_backup(
            operation="bulk-cleanup-documents",
            details={
                "document_count": len(docs_to_delete),
                "document_ids": [doc.id for doc in docs_to_delete[:50]],  # Limit to first 50 for metadata
                "action": "bulk_delete_test_documents"
            }
        )

        if not backup_result['success'] and not backup_result.get('skipped', False):
            # Backup failed and was required - block the operation
            logger.error(f"[Feature #213] Pre-destructive backup failed, blocking bulk delete: {backup_result['error']}")
            return {
                "deleted": 0,
                "message": f"Bulk delete blocked: Pre-destructive backup failed. {backup_result['error']}",
                "backup_failed": True
            }

        if backup_result.get('backup_path'):
            logger.info(f"[Feature #213] Pre-destructive backup created before bulk cleanup at: {backup_result['backup_path']}")

    deleted_count = 0
    for doc in docs_to_delete:
        await document_store.delete(doc.id)
        deleted_count += 1

    return {
        "deleted": deleted_count,
        "message": f"Cleaned up {deleted_count} test documents",
        "backup_path": backup_result.get('backup_path') if docs_to_delete else None
    }


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    document_store=Depends(get_document_store),
    document_rows_store=Depends(get_document_rows_store)
):
    """Delete a document and its associated data."""
    try:
        # Feature #267: Get document info before deletion for audit logging
        doc = await document_store.get(document_id)
        doc_name = doc.title if doc else "Unknown"
        doc_file_size = doc.file_size if doc else None
        doc_chunk_count = doc.chunk_count if doc else None

        # Delete structured data rows if any
        await document_rows_store.delete_dataset(document_id)

        # Delete embeddings if any - run in executor to avoid blocking
        # This ensures synchronous database operations don't block the event loop
        loop = asyncio.get_event_loop()
        embeddings_deleted = await loop.run_in_executor(
            None,
            embedding_store.delete_document,
            document_id
        )

        if embeddings_deleted:
            logger.info(f"Successfully deleted embeddings for document {document_id}")
        else:
            logger.warning(f"No embeddings found for document {document_id}")

        # Feature #186: Also delete from BM25 index
        try:
            from services.bm25_service import bm25_service
            bm25_deleted = bm25_service.delete_document(document_id)
            if bm25_deleted > 0:
                logger.info(f"[Feature #186] Deleted {bm25_deleted} chunks from BM25 index for document {document_id}")
        except Exception as e:
            logger.warning(f"[Feature #186] Failed to delete from BM25 index: {e}")

        # Feature #352: Invalidate response cache entries referencing this document
        try:
            from services.response_cache_service import response_cache_service
            cache_invalidated = response_cache_service.invalidate_by_document(document_id)
            if cache_invalidated > 0:
                logger.info(f"[Feature #352] Invalidated {cache_invalidated} cache entries for document {document_id}")
        except Exception as cache_err:
            logger.warning(f"[Feature #352] Failed to invalidate cache: {cache_err}")

        # Delete the document metadata
        if not await document_store.delete(document_id):
            # Feature #327: Use standardized NotFoundError
            raise NotFoundError("Document", document_id)

        logger.info(f"Successfully deleted document {document_id}")

        # Feature #267: Log document_deleted event
        try:
            await log_document_deleted(
                db=db,
                document_id=document_id,
                document_name=doc_name,
                chunk_count=doc_chunk_count,
                file_size=doc_file_size
            )
            await db.commit()
            logger.info(f"[Feature #267] Logged document_deleted event for document {document_id}")
        except Exception as audit_error:
            logger.error(f"[Feature #267] Failed to log document_deleted event: {audit_error}")

        return None
    except HTTPException:
        # Re-raise HTTP exceptions (including our AppError subclasses)
        raise
    except Exception as e:
        # Feature #327: Use standardized error handling (logs stack trace server-side)
        raise handle_exception(e, context="deleting document")


@router.post("/cleanup-orphaned-embeddings")
async def cleanup_orphaned_embeddings():
    """
    Find and remove orphaned embeddings (embeddings for deleted documents).

    Returns statistics about the cleanup operation.
    """
    try:
        from services.embedding_cleanup import cleanup_orphaned_embeddings as cleanup_func

        # Run cleanup in executor to avoid blocking
        loop = asyncio.get_event_loop()
        stats = await loop.run_in_executor(None, cleanup_func)

        return {
            "success": True,
            "orphaned_found": stats["found"],
            "orphaned_deleted": stats["deleted"],
            "errors": stats["errors"],
            "message": f"Cleaned up {stats['deleted']} orphaned embeddings"
        }
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cleanup failed: {str(e)}"
        )


@router.get("/verify-embedding-cleanup/{document_id}")
async def verify_embedding_cleanup(document_id: str):
    """
    Verify that all embeddings for a document have been deleted.

    Returns verification status.
    """
    try:
        from services.embedding_cleanup import verify_embedding_cleanup as verify_func

        # Run verification in executor to avoid blocking
        loop = asyncio.get_event_loop()
        is_clean = await loop.run_in_executor(None, verify_func, document_id)

        return {
            "document_id": document_id,
            "clean": is_clean,
            "message": "No embeddings remain" if is_clean else "Embeddings still exist"
        }
    except Exception as e:
        logger.error(f"Error during verification: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Verification failed: {str(e)}"
        )


class ReEmbedResponse(BaseModel):
    """Response model for re-embed endpoint."""
    success: bool
    document_id: str
    embedding_count: int
    message: str
    embedding_status: str = "success"  # 'success', 'partial', 'failed'
    warnings: List[str] = []


class EmbeddingCountResponse(BaseModel):
    """Response model for embedding count endpoint."""
    document_id: str
    embedding_count: int
    document_type: str


@router.get("/{document_id}/embedding-count", response_model=EmbeddingCountResponse)
async def get_embedding_count(
    document_id: str,
    document_store=Depends(get_document_store)
):
    """
    Get the embedding count for a specific document.
    Returns 0 for structured documents (they don't have embeddings).

    Feature #260: Uses chunk_count column from documents table for fast lookup
    instead of querying the embeddings table.
    """
    doc = await document_store.get(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found"
        )

    if doc.document_type == "structured":
        return EmbeddingCountResponse(
            document_id=document_id,
            embedding_count=0,
            document_type="structured"
        )

    # Feature #260: Use chunk_count column for fast lookup (maintained by DB triggers)
    # This avoids querying the embeddings table for each request
    return EmbeddingCountResponse(
        document_id=document_id,
        embedding_count=doc.chunk_count,
        document_type=doc.document_type
    )


# ==================== Feature #267: Document History Endpoint ====================

class DocumentHistoryEvent(BaseModel):
    """Single event in document audit history."""
    id: int
    action: str
    status: str
    details: Optional[dict] = None
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    file_size: Optional[int] = None
    chunk_count: Optional[int] = None
    model_used: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: Optional[str] = None


class DocumentHistoryResponse(BaseModel):
    """Response model for document history endpoint."""
    document_id: str
    events: List[DocumentHistoryEvent]
    total_events: int


@router.get("/{document_id}/history", response_model=DocumentHistoryResponse)
async def get_document_history_endpoint(
    document_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    document_store=Depends(get_document_store)
):
    """
    Get the audit history for a specific document.

    Feature #267: Returns all lifecycle events for a document:
    - document_uploaded: When the document was uploaded
    - embedding_started: When embedding generation started
    - embedding_completed: When embedding generation finished successfully
    - embedding_failed: When embedding generation failed
    - document_deleted: When the document was deleted
    - document_re_embed_started: When re-embedding started
    - document_re_embed_completed: When re-embedding completed

    Each event includes metadata such as file_size, chunk_count, model_used, and duration_ms.
    """
    # Verify document exists (or existed - for deleted documents, we still return history)
    doc = await document_store.get(document_id)

    # Get history from audit service
    events = await get_document_history(db, document_id, limit)

    if not events and not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found and has no history"
        )

    return DocumentHistoryResponse(
        document_id=document_id,
        events=[DocumentHistoryEvent(**event) for event in events],
        total_events=len(events)
    )


@router.post("/{document_id}/re-embed", response_model=ReEmbedResponse)
async def re_embed_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    document_store=Depends(get_document_store),
    document_rows_store=Depends(get_document_rows_store)  # FEATURE #216
):
    """
    Re-generate embeddings for an existing unstructured document.

    Feature #295: Atomic transaction for re-embedding.
    Wraps the entire re-embedding process (delete old + create new) in a single
    transaction with rollback on failure to prevent data loss.

    This endpoint is useful when:
    - The embedding model was not available during initial upload
    - Embeddings failed during initial processing
    - You want to re-embed with a different model after changing settings

    Transaction flow:
    1. Set status='processing' at start
    2. Generate new embeddings (without storing)
    3. DELETE old embeddings inside transaction
    4. CREATE new embeddings inside same transaction
    5. On success: commit, set status='ready', update chunk_count
    6. On failure: rollback (old embeddings restored), set status='failed'
    """
    # Get document
    doc = await document_store.get(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found"
        )

    # Only unstructured documents have embeddings
    if doc.document_type == "structured":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Structured documents (CSV, Excel, JSON) do not use embeddings. Only unstructured documents can be re-embedded."
        )

    # Feature #255: Check file integrity and update status before proceeding
    # This will raise HTTPException if file is missing and update status to 'file_missing'
    file_path, file_exists = await check_file_integrity_and_update_status(
        document_id,
        document_store,
        raise_if_missing=True
    )

    logger.info(f"[Feature #295] Re-embedding document {document_id}: {doc.title} (file: {file_path})")

    # Feature #267: Track re-embed timing
    reembed_start_time = time.time()
    embedding_model_for_audit = settings_store.get('embedding_source', 'openai:text-embedding-3-small')

    # ================================================================================
    # Feature #295 STEP 1: Set status='processing' at start
    # ================================================================================
    try:
        update_data = DocumentUpdate(status=DOCUMENT_STATUS_PROCESSING)
        await document_store.update(document_id, update_data)
        await db.commit()
        logger.info(f"[Feature #295] Document {document_id} status set to 'processing' for re-embed")
    except Exception as status_error:
        logger.error(f"[Feature #295] Failed to set processing status: {status_error}")

    # Feature #267: Log re_embed_started event
    try:
        await log_re_embed_started(
            db=db,
            document_id=document_id,
            document_name=doc.title,
            model_used=embedding_model_for_audit
        )
        await db.commit()
        logger.info(f"[Feature #267] Logged re_embed_started event for document {document_id}")
    except Exception as audit_error:
        logger.error(f"[Feature #267] Failed to log re_embed_started event: {audit_error}")

    # ================================================================================
    # Feature #295 STEP 2: Create backup for disaster recovery (Feature #250)
    # ================================================================================
    loop = asyncio.get_event_loop()
    backup_count = await loop.run_in_executor(
        None,
        embedding_store.backup_embeddings_to_table,
        document_id,
        "reembed"
    )
    logger.info(f"[Feature #295/250] Backed up {backup_count} embeddings to backup table for document {document_id}")

    # ================================================================================
    # Feature #295 STEP 3: Generate new embeddings WITHOUT storing them
    # ================================================================================
    try:
        chunk_data, warning_msg, embedding_model_used = await generate_embeddings_for_reembed(
            document_id=document_id,
            file_path=Path(file_path),
            mime_type=doc.mime_type,
            document_title=doc.title
        )

        if not chunk_data:
            # Embedding generation failed - don't start transaction, keep old embeddings
            failure_msg = warning_msg or "No chunks generated"
            logger.error(f"[Feature #295] Embedding generation FAILED for document {document_id}: {failure_msg}")
            logger.info(f"[Feature #295] Old embeddings preserved (generation failed before transaction)")

            # Set status to 'failed'
            update_data = DocumentUpdate(
                comment=f"⚠️ WARNING: Re-embed failed: {failure_msg}",
                status=DOCUMENT_STATUS_EMBEDDING_FAILED
            )
            await document_store.update(document_id, update_data)
            await db.commit()

            return ReEmbedResponse(
                success=False,
                document_id=document_id,
                embedding_count=0,
                message=f"Re-embed failed: {failure_msg} (old embeddings preserved)",
                embedding_status="failed",
                warnings=[failure_msg]
            )

        num_chunks = len(chunk_data)
        logger.info(f"[Feature #295] Generated {num_chunks} embeddings for document {document_id}")

    except Exception as gen_error:
        # Generation exception - don't start transaction, keep old embeddings
        logger.error(f"[Feature #295] Exception during embedding generation for document {document_id}: {gen_error}")

        update_data = DocumentUpdate(
            comment=f"⚠️ WARNING: Re-embed failed: {str(gen_error)}",
            status=DOCUMENT_STATUS_EMBEDDING_FAILED
        )
        await document_store.update(document_id, update_data)
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Re-embed failed during embedding generation: {str(gen_error)}"
        )

    # ================================================================================
    # Feature #295 STEP 4 & 5: Atomic transaction - DELETE old + INSERT new
    # ================================================================================
    logger.info(f"[Feature #295] PHASE 2: Atomic transaction - DELETE old + INSERT new")

    tx_result = await loop.run_in_executor(
        None,
        embedding_store.atomic_reembed_document,
        document_id,
        chunk_data,
        embedding_model_used or "unknown"
    )

    # ================================================================================
    # Feature #295 STEP 6: Handle transaction result
    # ================================================================================
    if not tx_result["success"]:
        # Transaction rolled back - old embeddings preserved (ACID guarantees)
        logger.error(f"[Feature #295] TRANSACTION ROLLBACK for document {document_id}: {tx_result.get('error')}")
        logger.info(f"[Feature #295] Old embeddings preserved due to rollback")

        # Set status to 'failed' (but embeddings are still the old ones)
        update_data = DocumentUpdate(
            comment=f"⚠️ WARNING: Re-embed transaction failed: {tx_result.get('error')} (old embeddings preserved)",
            status=DOCUMENT_STATUS_EMBEDDING_FAILED
        )
        await document_store.update(document_id, update_data)
        await db.commit()

        return ReEmbedResponse(
            success=False,
            document_id=document_id,
            embedding_count=0,
            message=f"Re-embed failed: Transaction rolled back - {tx_result.get('error')} (old embeddings preserved)",
            embedding_status="failed",
            warnings=[tx_result.get('error', 'Transaction failed')]
        )

    # Transaction committed successfully
    logger.info(f"[Feature #295] TRANSACTION COMMIT for document {document_id}: "
               f"deleted={tx_result['deleted_count']}, inserted={tx_result['inserted_count']}")

    # ================================================================================
    # Feature #297: Post re-embed verification check
    # ================================================================================
    verification = await loop.run_in_executor(
        None,
        embedding_store.verify_document_embeddings,
        document_id,
        num_chunks
    )
    logger.info(f"[Feature #297] Post re-embed verification: {verification['message']}")

    if not verification["success"]:
        # Feature #297: Verification failed - log error, optionally trigger retry
        error_type = verification.get("error_type", "unknown")
        should_retry = verification.get("should_retry", False)

        logger.error(f"[Feature #297] ❌ VERIFICATION FAILED for document {document_id}")
        logger.error(f"[Feature #297] Error type: {error_type}, Expected: {num_chunks}, Actual: {verification['actual_count']}")
        logger.error(f"[Feature #297] Blocking LLM call: context only {verification['actual_count']} embeddings")

        # Feature #297: Automatic retry logic (single retry attempt)
        if should_retry:
            logger.info(f"[Feature #297] Attempting automatic retry for document {document_id}")

            # Retry the atomic re-embed
            retry_result = await loop.run_in_executor(
                None,
                embedding_store.atomic_reembed_document,
                document_id,
                chunk_data,
                embedding_model_used or "unknown"
            )

            if retry_result["success"]:
                # Verify the retry
                retry_verification = await loop.run_in_executor(
                    None,
                    embedding_store.verify_document_embeddings,
                    document_id,
                    num_chunks
                )

                if retry_verification["success"]:
                    logger.info(f"[Feature #297] ✅ RETRY SUCCEEDED for document {document_id}")
                    verification = retry_verification  # Use retry result
                else:
                    logger.error(f"[Feature #297] ❌ RETRY VERIFICATION FAILED: {retry_verification['message']}")
            else:
                logger.error(f"[Feature #297] ❌ RETRY TRANSACTION FAILED: {retry_result.get('error')}")

        # If still not successful after potential retry
        if not verification["success"]:
            # Try to restore from backup (Feature #250)
            if backup_count > 0:
                logger.info(f"[Feature #297] Attempting emergency restore from backup table")
                restored = await loop.run_in_executor(
                    None,
                    embedding_store.restore_embeddings_from_backup,
                    document_id
                )
                if restored > 0:
                    logger.info(f"[Feature #297] Emergency restored {restored} embeddings from backup")
                    update_data = DocumentUpdate(
                        comment=f"⚠️ WARNING: Re-embed verification failed (expected {num_chunks}, got {verification['actual_count']}), restored from backup",
                        status=DOCUMENT_STATUS_READY
                    )
                else:
                    # Feature #297: Use verification_failed status
                    update_data = DocumentUpdate(
                        comment=f"⚠️ VERIFICATION FAILED: expected {num_chunks} chunks, found {verification['actual_count']}",
                        status=DOCUMENT_STATUS_VERIFICATION_FAILED
                    )
            else:
                # Feature #297: Use verification_failed status (no backup to restore)
                update_data = DocumentUpdate(
                    comment=f"⚠️ VERIFICATION FAILED: expected {num_chunks} chunks, found {verification['actual_count']}",
                    status=DOCUMENT_STATUS_VERIFICATION_FAILED
                )

            await document_store.update(document_id, update_data)
            await db.commit()

            return ReEmbedResponse(
                success=False,
                document_id=document_id,
                embedding_count=verification["actual_count"],
                message=f"Re-embed verification failed: {verification['message']}",
                embedding_status="verification_failed",
                warnings=[verification['message'], f"Error type: {error_type}"]
            )

    # ================================================================================
    # Feature #295: SUCCESS - commit complete, set status='ready', update chunk_count
    # ================================================================================

    # Clean up backup since transaction succeeded
    backup_deleted = await loop.run_in_executor(
        None,
        embedding_store.delete_backup_for_document,
        document_id
    )
    logger.info(f"[Feature #295/250] Deleted {backup_deleted} backup entries for document {document_id}")

    # Feature #186: Update BM25 index for hybrid search
    try:
        from services.bm25_service import bm25_service
        bm25_service.delete_document(document_id)
        bm25_stored = bm25_service.add_chunks(document_id, chunk_data)
        logger.info(f"[Feature #186/295] Updated BM25 index: {bm25_stored} chunks for document {document_id}")
    except Exception as bm25_error:
        logger.warning(f"[Feature #186/295] Failed to update BM25 index: {bm25_error}")

    # Build success response
    warnings_list = []
    if warning_msg:
        embedding_status_val = "partial"
        warnings_list.append(warning_msg)
        new_comment = f"Re-embedded with warnings: {warning_msg}"
        update_data = DocumentUpdate(
            comment=new_comment,
            status=DOCUMENT_STATUS_READY,
            embedding_model=embedding_model_used,
            chunk_count=num_chunks
        )
        message = f"Re-embedded with {num_chunks} chunks (with warnings)"
    else:
        embedding_status_val = "success"
        current_comment = doc.comment or ""
        if "WARNING" in current_comment:
            clean_comment = current_comment.split("\n\n⚠️ WARNING:")[0].strip()
            if clean_comment:
                update_data = DocumentUpdate(
                    comment=clean_comment,
                    status=DOCUMENT_STATUS_READY,
                    embedding_model=embedding_model_used,
                    chunk_count=num_chunks
                )
            else:
                update_data = DocumentUpdate(
                    comment="Re-embedded successfully",
                    status=DOCUMENT_STATUS_READY,
                    embedding_model=embedding_model_used,
                    chunk_count=num_chunks
                )
        else:
            update_data = DocumentUpdate(
                status=DOCUMENT_STATUS_READY,
                embedding_model=embedding_model_used,
                chunk_count=num_chunks
            )
        message = f"Successfully re-embedded with {num_chunks} chunks"

    await document_store.update(document_id, update_data)
    await db.commit()
    logger.info(f"[Feature #295] Document {document_id} status set to 'ready', chunk_count={num_chunks}")
    logger.info(f"[Feature #295] ✅ Successfully re-embedded document {document_id}: "
               f"{num_chunks} chunks (transaction: {tx_result['transaction_action']})")

    # Feature #267: Log re_embed_completed event
    try:
        reembed_duration = int((time.time() - reembed_start_time) * 1000)
        await log_re_embed_completed(
            db=db,
            document_id=document_id,
            document_name=doc.title,
            chunk_count=num_chunks,
            model_used=embedding_model_used or embedding_model_for_audit,
            duration_ms=reembed_duration
        )
        await db.commit()
        logger.info(f"[Feature #267] Logged re_embed_completed event for document {document_id}")
    except Exception as audit_error:
        logger.error(f"[Feature #267] Failed to log re_embed_completed event: {audit_error}")

    return ReEmbedResponse(
        success=True,
        document_id=document_id,
        embedding_count=num_chunks,
        message=message,
        embedding_status=embedding_status_val,
        warnings=warnings_list
    )


@router.post("/check-duplicate", response_model=DuplicateCheckResponse)
async def check_duplicate(
    file: UploadFile = File(...),
    collection_id: Optional[str] = Form(None),
    document_store=Depends(get_document_store)
):
    """
    Check if a file is a duplicate of an existing document.

    Feature #262: Per-collection duplicate detection.
    The same document can now exist in different collections, but not within the same collection.

    Checks both filename and content hash to detect duplicates:
    - Within the target collection: blocks upload if same content exists
    - Across other collections: warns user but allows upload

    Args:
        file: The file to check for duplicates
        collection_id: The target collection ID (None for uncategorized)
    """
    logger.info(f"Checking duplicate for: {file.filename} in collection: {collection_id}")

    # Read file content and compute hash
    content = await file.read()
    content_hash = compute_file_hash(content)
    filename = file.filename or "unknown"

    # Check for content hash match within the target collection (blocking)
    doc_by_hash_same_collection = await document_store.find_by_content_hash(content_hash, collection_id)

    # Check for content hash match in any collection (informational)
    doc_by_hash_any = await document_store.find_by_content_hash(content_hash, '__any__')

    # Check for filename match
    doc_by_filename = await document_store.find_by_filename(filename)

    # Determine match type
    if doc_by_hash_same_collection and doc_by_filename and doc_by_hash_same_collection.id == doc_by_filename.id:
        # Same content and filename in same collection
        return DuplicateCheckResponse(
            is_duplicate=True,
            duplicate_document=doc_by_hash_same_collection,
            match_type="both"
        )
    elif doc_by_hash_same_collection:
        # Same content in same collection (duplicate blocked)
        return DuplicateCheckResponse(
            is_duplicate=True,
            duplicate_document=doc_by_hash_same_collection,
            match_type="content"
        )
    elif doc_by_hash_any and doc_by_hash_any.collection_id != collection_id:
        # Same content exists in a different collection (allowed, but inform user)
        # Get the collection name for the user message
        other_collection_name = None
        if doc_by_hash_any.collection_id:
            # Query collection name
            try:
                from core.database import AsyncSessionLocal
                from models.db_models import DBCollection
                async with AsyncSessionLocal() as session:
                    from sqlalchemy import select
                    stmt = select(DBCollection).where(DBCollection.id == doc_by_hash_any.collection_id)
                    result = await session.execute(stmt)
                    collection = result.scalar_one_or_none()
                    if collection:
                        other_collection_name = collection.name
            except Exception as e:
                logger.warning(f"Could not fetch collection name: {e}")
                other_collection_name = "another collection"
        else:
            other_collection_name = "Uncategorized"

        return DuplicateCheckResponse(
            is_duplicate=False,  # Not a blocking duplicate
            duplicate_document=doc_by_hash_any,
            match_type="content_other_collection",
            other_collection_name=other_collection_name
        )
    elif doc_by_filename:
        return DuplicateCheckResponse(
            is_duplicate=True,
            duplicate_document=doc_by_filename,
            match_type="filename"
        )

    return DuplicateCheckResponse(
        is_duplicate=False,
        duplicate_document=None,
        match_type=None
    )


class BulkGenerateRequest(BaseModel):
    """Request model for bulk document generation."""
    count: int = 100


class BulkGenerateResponse(BaseModel):
    """Response model for bulk document generation."""
    created: int
    message: str


@router.post("/bulk-generate", response_model=BulkGenerateResponse)
async def bulk_generate_documents(request: BulkGenerateRequest, document_store=Depends(get_document_store)):
    """
    Generate multiple test documents for performance testing.

    This endpoint creates placeholder documents in the document store
    without actual file uploads, for testing UI performance with many documents.
    """
    count = min(request.count, 200)  # Cap at 200 for safety

    file_types = [
        ("text/plain", "txt"),
        ("application/pdf", "pdf"),
        ("text/csv", "csv"),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
        ("application/json", "json"),
        ("text/markdown", "md"),
    ]

    doc_types = ["structured", "unstructured"]

    for i in range(count):
        mime_type, ext = file_types[i % len(file_types)]
        doc_type = "structured" if mime_type in ["text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/json"] else "unstructured"

        doc_create = DocumentCreate(
            title=f"Test Document {i + 1:03d}",
            comment=f"Performance test document #{i + 1}",
            original_filename=f"test_document_{i + 1:03d}.{ext}",
            mime_type=mime_type,
            file_size=(i + 1) * 1024,  # Varying sizes
            document_type=doc_type,
            collection_id=None,
            content_hash=f"test_hash_{i + 1:03d}"
        )
        await document_store.create(doc_create)

    return BulkGenerateResponse(
        created=count,
        message=f"Successfully created {count} test documents"
    )


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_UPLOAD)  # Feature #324: Rate limit upload endpoint (default 10/minute)
async def upload_document(
    request: Request,  # Required for rate limiting
    file: UploadFile = File(...),
    title: str = Form(...),
    comment: Optional[str] = Form(None),
    collection_id: Optional[str] = Form(None),
    async_processing: bool = Form(default=True),  # Feature #330: Enable background processing by default
    db: AsyncSession = Depends(get_db),
    document_store=Depends(get_document_store),
    document_rows_store=Depends(get_document_rows_store)
):
    """
    Upload a document file for processing.

    Supported formats: PDF, TXT, CSV, Excel, Word, JSON, Markdown
    Maximum file size: 100MB
    Rate limited to 10 requests per minute (Feature #324).

    Feature #330: async_processing parameter enables background processing.
    When enabled (default), the server returns immediately with status='queued'
    and processes the document in the background. This prevents blocking
    during large document uploads.
    """
    logger.info(f"Uploading document: {file.filename}, content_type: {file.content_type}")

    # Validate file type
    content_type = file.content_type or "application/octet-stream"

    # Handle common mime type variations
    mime_type_map = {
        "application/pdf": "application/pdf",
        "text/plain": "text/plain",
        "text/csv": "text/csv",
        "application/csv": "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel": "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/json": "application/json",
        "text/markdown": "text/markdown",
        "text/x-markdown": "text/markdown",
    }

    # Also detect by file extension if content_type is generic
    ext = Path(file.filename or "").suffix.lower()
    ext_to_mime = {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".json": "application/json",
        ".md": "text/markdown",
    }

    # Normalize content type
    if content_type == "application/octet-stream" and ext in ext_to_mime:
        content_type = ext_to_mime[ext]
    elif content_type in mime_type_map:
        content_type = mime_type_map[content_type]

    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {content_type}. Allowed types: PDF, TXT, CSV, Excel, Word, JSON, Markdown"
        )

    # Feature #360: Validate title length
    if len(title) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title must be 255 characters or less"
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Feature #359: Reject empty files
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is empty (0 bytes)"
        )

    # Validate file size
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is 100MB, got {file_size / (1024*1024):.2f}MB"
        )

    # Compute content hash for duplicate detection
    content_hash = compute_file_hash(content)

    # Feature #294: Check for duplicate content in the same collection before saving file
    # This provides a user-friendly error message before we do any disk I/O
    existing_doc = await document_store.find_by_content_hash(content_hash, collection_id)
    if existing_doc:
        logger.warning(f"[Feature #294] Duplicate detected: content_hash={content_hash[:16]}... already exists in collection={collection_id}")
        collection_name = "Uncategorized" if collection_id is None else "the selected collection"
        if existing_doc.collection_id:
            # Get actual collection name
            try:
                from models.db_models import DBCollection
                from sqlalchemy import select
                stmt = select(DBCollection).where(DBCollection.id == existing_doc.collection_id)
                result = await db.execute(stmt)
                collection_obj = result.scalar_one_or_none()
                if collection_obj:
                    collection_name = f'"{collection_obj.name}"'
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A document with the same content already exists in {collection_name}. "
                   f"Existing document: '{existing_doc.title}' (uploaded {existing_doc.created_at.strftime('%Y-%m-%d %H:%M')})"
        )

    # Generate unique filename and save
    file_id = str(uuid.uuid4())
    file_ext = ALLOWED_MIME_TYPES[content_type]
    saved_filename = f"{file_id}.{file_ext}"
    file_path = UPLOAD_DIR / saved_filename

    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)

    logger.info(f"Saved file to: {file_path}")

    # Determine document type (structured vs unstructured)
    structured_types = ["text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       "application/vnd.ms-excel", "application/json"]
    doc_type = "structured" if content_type in structured_types else "unstructured"

    # Feature #330: Set initial status based on async_processing flag
    # If async_processing is True, document starts as 'queued' and will be processed in background
    # If async_processing is False, document starts as 'processing' and is processed synchronously
    initial_status = DOCUMENT_STATUS_QUEUED if async_processing else DOCUMENT_STATUS_PROCESSING

    # Create document record with file_path field set (Feature #253)
    doc_create = DocumentCreate(
        title=title,
        comment=comment,
        original_filename=file.filename or "unknown",
        mime_type=content_type,
        file_size=file_size,
        document_type=doc_type,
        collection_id=collection_id,
        content_hash=content_hash,
        url=str(file_path),  # Deprecated, kept for backwards compatibility
        file_path=str(file_path),  # Feature #253: Explicit file path storage
        status=initial_status  # Feature #330: Set initial status
    )

    # Create document record
    # Feature #294: Wrap in try/except to handle race condition with unique constraint
    try:
        document = await document_store.create(doc_create)
        logger.info(f"Created document: {document.id}")

        # CRITICAL: Commit the document creation immediately to ensure it's persisted
        # This prevents rollback if subsequent operations (embeddings, row parsing) fail
        await db.commit()
        logger.info(f"Committed document {document.id} to database")
    except IntegrityError as e:
        # Feature #294: Handle unique constraint violation (race condition or API bypass)
        await db.rollback()
        # Clean up the saved file since we can't create the document record
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"[Feature #294] Cleaned up orphaned file: {file_path}")
        except Exception as cleanup_error:
            logger.warning(f"[Feature #294] Failed to clean up file {file_path}: {cleanup_error}")

        logger.warning(f"[Feature #294] IntegrityError during document creation: {e}")
        # Check if it's a duplicate content_hash constraint violation
        if 'content_hash' in str(e).lower() or 'ix_documents_content_hash' in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A document with the same content already exists in this collection. "
                       "Please check your existing documents or upload to a different collection."
            )
        # Re-raise other integrity errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )

    # Validate that document was persisted by re-querying it
    verified_document = await document_store.get(document.id)
    if not verified_document:
        logger.error(f"Document {document.id} was not persisted to database after commit!")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist document to database"
        )
    logger.info(f"Verified document {document.id} exists in database")

    # Feature #267: Log document upload event
    try:
        await log_document_uploaded(
            db=db,
            document_id=document.id,
            document_name=title,
            file_size=file_size,
            details={
                "original_filename": file.filename,
                "mime_type": content_type,
                "document_type": doc_type,
                "collection_id": collection_id,
                "async_processing": async_processing  # Feature #330
            }
        )
        await db.commit()
        logger.info(f"[Feature #267] Logged document_uploaded event for {document.id}")
    except Exception as audit_error:
        logger.warning(f"[Feature #267] Failed to log document_uploaded event: {audit_error}")

    # Feature #330: If async_processing is enabled, queue the document and return immediately
    if async_processing:
        try:
            from services.document_queue import get_document_queue, QueueItem

            queue = get_document_queue()
            queue_item = QueueItem(
                document_id=document.id,
                file_path=str(file_path),
                mime_type=content_type,
                document_title=title,
                document_type=doc_type,
                collection_id=collection_id
            )

            if await queue.enqueue(queue_item):
                logger.info(f"[Feature #330] Document {document.id} queued for background processing")

                # Return immediately with 'queued' status
                return UploadResponse(
                    document=Document.model_validate(document, from_attributes=True),
                    embedding_status="queued",
                    warnings=["Document queued for background processing. Check /api/documents/queue/status for progress."]
                )
            else:
                # Queue is full, fall back to synchronous processing
                logger.warning(f"[Feature #330] Queue full, processing document {document.id} synchronously")
                # Update status from 'queued' to 'processing'
                update_data = DocumentUpdate(status=DOCUMENT_STATUS_PROCESSING)
                document = await document_store.update(document.id, update_data)
                await db.commit()
        except Exception as queue_error:
            # If queueing fails, fall back to synchronous processing
            logger.warning(f"[Feature #330] Queueing failed, processing document {document.id} synchronously: {queue_error}")
            # Update status from 'queued' to 'processing'
            update_data = DocumentUpdate(status=DOCUMENT_STATUS_PROCESSING)
            document = await document_store.update(document.id, update_data)
            await db.commit()

    # For structured data, parse and store rows
    # Wrap in try/except to prevent rollback of document creation
    if doc_type == "structured":
        try:
            # Feature #333: Use async wrapper to prevent blocking event loop
            rows, schema = await parse_structured_data_async(file_path, content_type)
            if rows:
                await document_rows_store.add_rows(document.id, rows, schema)
                # Store schema info in document via update to persist to database
                # Feature #258: Also update status to 'ready' after successful processing
                # Feature #261: Use status constants for type safety
                schema_json = json.dumps(schema)
                update_data = DocumentUpdate(schema_info=schema_json, status=DOCUMENT_STATUS_READY)
                document = await document_store.update(document.id, update_data)
                await db.commit()  # Commit the schema update
                logger.info(f"Stored {len(rows)} rows and schema for document {document.id}")
            else:
                # No rows but successful parse - still mark as ready
                # Feature #261: Use status constants for type safety
                update_data = DocumentUpdate(status=DOCUMENT_STATUS_READY)
                document = await document_store.update(document.id, update_data)
                await db.commit()
        except Exception as e:
            # Log error but don't fail the upload - document is still stored
            logger.error(f"Error processing structured data for document {document.id}: {e}")
            await db.rollback()  # Rollback only the failed row/schema operations
            # Feature #258: Update status to 'ready' for structured docs (they don't need embeddings)
            # Feature #261: Use status constants for type safety
            try:
                update_data = DocumentUpdate(status=DOCUMENT_STATUS_READY)
                document = await document_store.update(document.id, update_data)
                await db.commit()
            except Exception:
                pass
            # Re-fetch the document to return the committed version
            document = await document_store.get(document.id) or document
    else:
        # For unstructured data, extract text and generate embeddings
        embedding_warning = None
        # Feature #267: Track embedding start time for audit logging
        embedding_start_time = time.time()
        embedding_model_for_audit = settings_store.get('embedding_source', 'openai:text-embedding-3-small')

        # Feature #267: Log embedding_started event
        try:
            await log_embedding_started(
                db=db,
                document_id=document.id,
                document_name=title,
                model_used=embedding_model_for_audit,
                file_size=file_size
            )
            await db.commit()
            logger.info(f"[Feature #267] Logged embedding_started event for {document.id}")
        except Exception as audit_error:
            logger.warning(f"[Feature #267] Failed to log embedding_started event: {audit_error}")

        try:
            # FEATURE #122: Updated to handle tuple return value (num_chunks, warning)
            # FEATURE #216: Pass document_rows_store for hybrid PDF processing
            # FEATURE #259: Now also returns embedding_model used
            num_chunks, warning_msg, embedding_model_used = await process_unstructured_document(
                document.id,
                file_path,
                content_type,
                title,
                document_rows_store=document_rows_store
            )

            if num_chunks > 0:
                logger.info(f"Created {num_chunks} embeddings for document {document.id}")
                # Feature #259: Log embedding model used
                if embedding_model_used:
                    logger.info(f"[Feature #259] Used embedding model: {embedding_model_used}")

                # Check if there was a partial failure warning
                if warning_msg:
                    embedding_warning = f"Document uploaded with warnings: {warning_msg}"
                    logger.warning(f"⚠️  Partial success for document {document.id}: {warning_msg}")

                    # Store warning in document metadata
                    # Feature #258: Still set status to 'ready' since we have some embeddings
                    # Feature #259: Also save embedding_model
                    # Feature #261: Use status constants for type safety
                    try:
                        update_data = DocumentUpdate(
                            comment=f"{comment or ''}\n\n⚠️ WARNING: {warning_msg}".strip(),
                            status=DOCUMENT_STATUS_READY,
                            embedding_model=embedding_model_used
                        )
                        document = await document_store.update(document.id, update_data)
                        await db.commit()
                        logger.info(f"Stored warning in document {document.id} metadata")
                    except Exception as meta_error:
                        logger.error(f"Failed to store warning in document metadata: {meta_error}")
                else:
                    # Feature #258: Success case - set status to 'ready'
                    # Feature #259: Also save embedding_model
                    # Feature #261: Use status constants for type safety
                    try:
                        update_data = DocumentUpdate(status=DOCUMENT_STATUS_READY, embedding_model=embedding_model_used)
                        document = await document_store.update(document.id, update_data)
                        await db.commit()
                        logger.info(f"[Feature #258] Document {document.id} status set to 'ready'")
                        logger.info(f"[Feature #259] Document {document.id} embedding_model set to '{embedding_model_used}'")

                        # Feature #267: Log embedding_completed event
                        try:
                            embedding_duration = int((time.time() - embedding_start_time) * 1000)
                            await log_embedding_completed(
                                db=db,
                                document_id=document.id,
                                document_name=title,
                                chunk_count=num_chunks,
                                model_used=embedding_model_used or embedding_model_for_audit,
                                duration_ms=embedding_duration,
                                file_size=file_size
                            )
                            await db.commit()
                            logger.info(f"[Feature #267] Logged embedding_completed event for document {document.id}")
                        except Exception as audit_error:
                            logger.error(f"[Feature #267] Failed to log embedding_completed event: {audit_error}")
                    except Exception as meta_error:
                        logger.error(f"Failed to update document status: {meta_error}")

            elif num_chunks == 0:
                # Embedding generation completely failed
                embedding_warning = warning_msg or "Document uploaded successfully, but embeddings could not be generated. The document may not be searchable via semantic search."
                logger.warning(f"❌ Zero embeddings created for document {document.id}. Document will not be searchable.")

                # Store warning in document metadata so sidebar can show warning icon
                # Feature #258: Set status to 'embedding_failed'
                # Feature #261: Use status constants for type safety
                try:
                    update_data = DocumentUpdate(
                        comment=f"{comment or ''}\n\n⚠️ WARNING: {embedding_warning}".strip(),
                        status=DOCUMENT_STATUS_EMBEDDING_FAILED
                    )
                    document = await document_store.update(document.id, update_data)
                    await db.commit()
                    logger.info(f"[Feature #258] Document {document.id} status set to 'embedding_failed'")

                    # Feature #267: Log embedding_failed event
                    try:
                        embedding_duration = int((time.time() - embedding_start_time) * 1000)
                        await log_embedding_failed(
                            db=db,
                            document_id=document.id,
                            document_name=title,
                            model_used=embedding_model_for_audit,
                            duration_ms=embedding_duration,
                            error_message=embedding_warning
                        )
                        await db.commit()
                        logger.info(f"[Feature #267] Logged embedding_failed event for document {document.id}")
                    except Exception as audit_error:
                        logger.error(f"[Feature #267] Failed to log embedding_failed event: {audit_error}")
                except Exception as meta_error:
                    logger.error(f"Failed to store warning in document metadata: {meta_error}")

        except Exception as e:
            # Log error but don't fail the upload - document is still stored
            embedding_warning = f"Document uploaded successfully, but embedding generation failed: {str(e)}"
            logger.error(f"Error creating embeddings for document {document.id}: {e}")

            # Store warning in document metadata so sidebar can show warning icon
            # Feature #258: Set status to 'embedding_failed'
            # Feature #261: Use status constants for type safety
            try:
                update_data = DocumentUpdate(
                    comment=f"{comment or ''}\n\n⚠️ WARNING: {embedding_warning}".strip(),
                    status=DOCUMENT_STATUS_EMBEDDING_FAILED
                )
                document = await document_store.update(document.id, update_data)
                await db.commit()
                logger.info(f"[Feature #258] Document {document_id} status set to 'embedding_failed' due to exception")

                # Feature #267: Log embedding_failed event
                try:
                    embedding_duration = int((time.time() - embedding_start_time) * 1000)
                    await log_embedding_failed(
                        db=db,
                        document_id=document.id,
                        document_name=title,
                        model_used=embedding_model_for_audit,
                        duration_ms=embedding_duration,
                        error_message=str(e)
                    )
                    await db.commit()
                    logger.info(f"[Feature #267] Logged embedding_failed event for document {document.id}")
                except Exception as audit_error:
                    logger.error(f"[Feature #267] Failed to log embedding_failed event: {audit_error}")
            except Exception as meta_error:
                logger.error(f"Failed to store warning in document metadata: {meta_error}")

    # Build the UploadResponse with embedding status and warnings
    warnings_list = []
    if doc_type == "structured":
        embedding_status = "skipped"  # Structured data doesn't get embeddings
    else:
        if embedding_warning:
            logger.warning(f"Embedding warning for document {document.id}: {embedding_warning}")
            warnings_list.append(embedding_warning)
            # Determine if it was a partial or complete failure
            if "partial" in (embedding_warning or "").lower() or "warnings" in (embedding_warning or "").lower():
                embedding_status = "partial"
            else:
                embedding_status = "failed"
        else:
            embedding_status = "success"

    # Feature #352: Invalidate cache entries with NULL document_ids (all-docs scope)
    # since a new document may change answers to previously cached queries
    try:
        from services.response_cache_service import response_cache_service
        cache_invalidated = response_cache_service.invalidate_by_document(str(document.id))
        if cache_invalidated > 0:
            logger.info(f"[Feature #352] Invalidated {cache_invalidated} cache entries after document upload")
    except Exception as e:
        logger.warning(f"[Feature #352] Failed to invalidate cache after upload: {e}")

    return UploadResponse(
        document=Document.model_validate(document, from_attributes=True),
        embedding_status=embedding_status,
        warnings=warnings_list
    )


class SuggestedQuestionsResponse(BaseModel):
    """Response model for suggested questions endpoint."""
    document_id: str
    questions: List[str]
    cached: bool = False  # Whether questions were loaded from cache


@router.get("/{document_id}/suggested-questions", response_model=SuggestedQuestionsResponse)
async def get_suggested_questions(
    document_id: str,
    regenerate: bool = False,
    document_store=Depends(get_document_store)
):
    """
    Get suggested questions for a document based on its content.

    Feature #199: Generates 3-5 relevant questions that users might ask about
    the document. Questions are generated using an LLM and cached in the
    document's comment field for reuse.

    Args:
        document_id: The document ID
        regenerate: If true, regenerate questions even if cached

    Returns:
        SuggestedQuestionsResponse with list of suggested questions
    """
    # Check if feature is enabled
    enable_suggestions = settings_store.get('enable_suggested_questions', 'true')
    if enable_suggestions.lower() == 'false':
        return SuggestedQuestionsResponse(
            document_id=document_id,
            questions=[],
            cached=False
        )

    # Get document
    doc = await document_store.get(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found"
        )

    # Check for cached questions in document metadata (stored in schema_info for unstructured docs)
    # We use a JSON structure with a "suggested_questions" key
    cached_questions = None
    if not regenerate and doc.schema_info:
        try:
            schema_data = json.loads(doc.schema_info)
            if isinstance(schema_data, dict) and 'suggested_questions' in schema_data:
                cached_questions = schema_data['suggested_questions']
                if cached_questions and isinstance(cached_questions, list):
                    logger.info(f"Returning {len(cached_questions)} cached questions for document {document_id}")
                    return SuggestedQuestionsResponse(
                        document_id=document_id,
                        questions=cached_questions,
                        cached=True
                    )
        except json.JSONDecodeError:
            pass  # schema_info might be plain text for structured docs

    # Generate questions using LLM
    questions = await _generate_suggested_questions(doc)

    # Cache the questions in schema_info
    if questions:
        try:
            # Preserve existing schema_info if it's a dict
            schema_data = {}
            if doc.schema_info:
                try:
                    existing = json.loads(doc.schema_info)
                    if isinstance(existing, dict):
                        schema_data = existing
                    elif isinstance(existing, list):
                        # It's a schema for structured docs, preserve it
                        schema_data = {'schema': existing}
                except json.JSONDecodeError:
                    pass

            schema_data['suggested_questions'] = questions
            update_data = DocumentUpdate(schema_info=json.dumps(schema_data))
            await document_store.update(document_id, update_data)
            logger.info(f"Cached {len(questions)} suggested questions for document {document_id}")
        except Exception as e:
            logger.error(f"Failed to cache suggested questions: {e}")

    return SuggestedQuestionsResponse(
        document_id=document_id,
        questions=questions,
        cached=False
    )


async def _generate_suggested_questions(doc) -> List[str]:
    """
    Generate suggested questions for a document using an LLM.

    Uses the document preview/content to generate 3-5 relevant questions
    that a user might want to ask about the document.

    Args:
        doc: The document object

    Returns:
        List of suggested questions (3-5 items)
    """
    # Get document content preview
    content_preview = ""

    # For unstructured documents, get chunks from embedding store
    if doc.document_type == "unstructured":
        chunks = embedding_store.get_chunks(doc.id)
        if chunks:
            # Get first 3 chunks for context (to stay within token limits)
            for chunk in chunks[:3]:
                content_preview += chunk.get('text', '') + "\n\n"
            content_preview = content_preview[:4000]  # Limit to ~1000 tokens
        else:
            # Fallback: try to read the file
            file_path = UPLOAD_DIR / f"{doc.id}.{doc.mime_type.split('/')[-1]}"
            if not file_path.exists():
                # Try common extensions
                for ext in ['pdf', 'txt', 'docx', 'md']:
                    potential_path = UPLOAD_DIR / f"{doc.id}.{ext}"
                    if potential_path.exists():
                        file_path = potential_path
                        break

            if file_path.exists():
                text = extract_text_from_file(file_path, doc.mime_type)
                content_preview = text[:4000] if text else ""

    # For structured documents, use schema and sample data
    elif doc.document_type == "structured":
        # Get schema info
        if doc.schema_info:
            try:
                schema = json.loads(doc.schema_info)
                if isinstance(schema, list):
                    content_preview = f"This is a {doc.mime_type} file with columns: {', '.join(schema)}\n\n"
                elif isinstance(schema, dict) and 'schema' in schema:
                    content_preview = f"This is a {doc.mime_type} file with columns: {', '.join(schema['schema'])}\n\n"
            except json.JSONDecodeError:
                pass

    if not content_preview:
        logger.warning(f"No content preview available for document {doc.id}")
        return []

    # Build prompt for LLM
    prompt = f"""Based on the following document content, generate exactly 5 relevant questions that a user might want to ask about this document.

Document Title: {doc.title}
Document Type: {doc.document_type}

Content Preview:
{content_preview}

Generate 5 diverse questions that:
1. Are directly answerable from the document content
2. Cover different aspects/topics of the document
3. Are practical and useful for someone reading this document
4. Are concise (under 15 words each)
5. Start with "What", "How", "Why", "Which", "When", or "Explain"

Return ONLY the questions, one per line, without numbering or bullet points."""

    # Call LLM
    api_key = settings_store.get('openai_api_key')
    llm_model = settings_store.get('llm_model', 'gpt-4o-mini')

    questions = []

    # Try OpenAI
    if api_key and api_key.startswith('sk-') and len(api_key) > 20:
        try:
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=llm_model if not llm_model.startswith('ollama:') and not llm_model.startswith('openrouter:') else 'gpt-4o-mini',
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that generates relevant questions about documents."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            response_text = response.choices[0].message.content.strip()
            questions = [q.strip() for q in response_text.split('\n') if q.strip() and len(q.strip()) > 10]
            logger.info(f"Generated {len(questions)} questions using OpenAI for document {doc.id}")
        except Exception as e:
            logger.error(f"Failed to generate questions with OpenAI: {e}")

    # Try OpenRouter if OpenAI failed and OpenRouter key is available
    if not questions:
        openrouter_key = settings_store.get('openrouter_api_key')
        if openrouter_key and len(openrouter_key) > 10:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {openrouter_key}",
                            "HTTP-Referer": "http://localhost:3000",
                            "X-Title": "Agentic RAG System"
                        },
                        json={
                            "model": "google/gemini-2.0-flash-001",  # Fast, cheap model for simple task
                            "messages": [
                                {"role": "system", "content": "You are a helpful assistant that generates relevant questions about documents."},
                                {"role": "user", "content": prompt}
                            ],
                            "max_tokens": 500,
                            "temperature": 0.7
                        }
                    )
                    if response.status_code == 200:
                        data = response.json()
                        response_text = data['choices'][0]['message']['content'].strip()
                        questions = [q.strip() for q in response_text.split('\n') if q.strip() and len(q.strip()) > 10]
                        logger.info(f"Generated {len(questions)} questions using OpenRouter for document {doc.id}")
            except Exception as e:
                logger.error(f"Failed to generate questions with OpenRouter: {e}")

    # Try Ollama as fallback
    if not questions:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Try to find a suitable Ollama model
                response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if response.status_code == 200:
                    models = response.json().get('models', [])
                    # Prefer smaller, faster models for this simple task
                    preferred_models = ['qwen3:8b', 'qwen3:4b', 'llama3.2:3b', 'gemma2:2b', 'phi3:mini']
                    ollama_model = None
                    for pref in preferred_models:
                        for m in models:
                            if pref in m.get('name', ''):
                                ollama_model = m.get('name')
                                break
                        if ollama_model:
                            break

                    if not ollama_model and models:
                        ollama_model = models[0].get('name')

                    if ollama_model:
                        gen_response = await client.post(
                            f"{OLLAMA_BASE_URL}/api/generate",
                            json={
                                "model": ollama_model,
                                "prompt": prompt,
                                "stream": False
                            }
                        )
                        if gen_response.status_code == 200:
                            response_text = gen_response.json().get('response', '').strip()
                            questions = [q.strip() for q in response_text.split('\n') if q.strip() and len(q.strip()) > 10]
                            logger.info(f"Generated {len(questions)} questions using Ollama ({ollama_model}) for document {doc.id}")
        except httpx.ConnectError:
            logger.warning("Ollama not available for question generation")
        except Exception as e:
            logger.error(f"Failed to generate questions with Ollama: {e}")

    # Limit to 5 questions and clean up
    questions = questions[:5]

    # Clean up questions (remove numbering, bullets, etc.)
    cleaned_questions = []
    for q in questions:
        # Remove leading numbers, bullets, dashes
        q = q.lstrip('0123456789.-) ')
        # Ensure it ends with a question mark
        if q and not q.endswith('?'):
            q = q + '?'
        if len(q) > 10:  # Minimum length check
            cleaned_questions.append(q)

    return cleaned_questions[:5]
