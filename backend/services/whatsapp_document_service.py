"""
WhatsApp Document Upload Service.

Handles document uploads via WhatsApp:
- Downloads files from Twilio MediaUrl with authentication
- Validates file types and sizes
- Processes documents through the ingestion pipeline
- Sends confirmation messages back to users

File size limit: 16MB (Twilio WhatsApp limit)
"""

import logging
import httpx
import uuid
import os
import json
import base64
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timezone

from core.store import settings_store, embedding_store

logger = logging.getLogger(__name__)

# File upload settings (from documents.py)
UPLOAD_DIR = Path(__file__).parent.parent / "uploads"

# Ollama settings
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# WhatsApp file size limit (16MB)
WHATSAPP_MAX_FILE_SIZE = 16 * 1024 * 1024

# Supported file types for WhatsApp document upload
# Maps MIME types to extensions
SUPPORTED_MIME_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/json": "json",
    "text/markdown": "md",
}

# Reverse mapping: extension to MIME type
EXTENSION_TO_MIME = {v: k for k, v in SUPPORTED_MIME_TYPES.items()}

# Additional content type variations that Twilio might send
CONTENT_TYPE_ALIASES = {
    "application/csv": "text/csv",
    "text/x-markdown": "text/markdown",
    "application/x-pdf": "application/pdf",
    "application/msword": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # Old .doc format mapped to docx handler
}

# Confirmation messages (Italian)
UPLOAD_SUCCESS_MESSAGE = """📄 *Documento caricato!*

Nome: {document_name}
Tipo: {document_type}
Dimensione: {file_size}
{embedding_line}{collection_line}
Il documento è stato elaborato e aggiunto al sistema. Ora puoi fare domande sul suo contenuto."""

# Feature #200: Suggested questions template (Italian)
SUGGESTED_QUESTIONS_HEADER = "\n\n💡 *Domande suggerite:*"
SUGGESTED_QUESTIONS_TEMPLATE = """{header}
{questions}"""

# Line showing embedding count (for unstructured documents)
UPLOAD_SUCCESS_EMBEDDING_LINE = "🔍 Embedding: {num_chunks} chunk generati\n"

UPLOAD_SUCCESS_MESSAGE_COLLECTION_LINE = "📁 Collezione: {collection_name}\n"

UPLOAD_PROCESSING_MESSAGE = """⏳ *Documento ricevuto!*

Sto elaborando il documento "{document_name}"...
Ti invierò una conferma quando sarà pronto."""

UPLOAD_ERROR_UNSUPPORTED_FORMAT = """❌ *Formato non supportato*

Il file "{filename}" non è in un formato supportato.

📋 *Formati supportati:*
- PDF (.pdf)
- Word (.docx)
- Excel (.xlsx, .xls)
- CSV (.csv)
- JSON (.json)
- Testo (.txt)
- Markdown (.md)

Prova a caricare un file in uno di questi formati."""

UPLOAD_ERROR_TOO_LARGE = """❌ *File troppo grande*

Il file "{filename}" supera il limite di 16MB per WhatsApp.

Dimensione file: {file_size}
Limite: 16MB

Prova a comprimere il file o dividere in parti più piccole."""

UPLOAD_ERROR_DOWNLOAD_FAILED = """❌ *Errore nel download*

Non sono riuscito a scaricare il file "{filename}".

Errore: {error}

Prova a inviare nuovamente il documento."""

UPLOAD_ERROR_PROCESSING_FAILED = """❌ *Errore nell'elaborazione*

Il file "{filename}" è stato scaricato ma l'elaborazione è fallita.

Errore: {error}

Il documento potrebbe essere corrotto o in un formato non valido."""


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def get_friendly_document_type(mime_type: str) -> str:
    """Get user-friendly document type name."""
    type_names = {
        "application/pdf": "PDF",
        "text/plain": "Testo",
        "text/csv": "CSV (Tabella)",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
        "application/vnd.ms-excel": "Excel",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
        "application/json": "JSON (Tabella)",
        "text/markdown": "Markdown",
    }
    return type_names.get(mime_type, "Documento")


class WhatsAppDocumentService:
    """
    Service for handling document uploads via WhatsApp.

    Downloads files from Twilio, validates them, and processes
    through the existing document ingestion pipeline.
    """

    def __init__(self):
        """Initialize the WhatsApp document service."""
        # Ensure upload directory exists
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def _get_twilio_auth(self) -> Optional[Tuple[str, str]]:
        """
        Get Twilio authentication credentials.

        Returns:
            Tuple of (account_sid, auth_token) or None if not configured
        """
        account_sid = settings_store.get('twilio_account_sid', '')
        auth_token = settings_store.get('twilio_auth_token', '')

        if not account_sid or not auth_token:
            return None

        return (account_sid, auth_token)

    def is_supported_format(self, content_type: str, filename: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Check if a file format is supported for document upload.

        Args:
            content_type: MIME type from Twilio
            filename: Original filename (for extension-based detection)

        Returns:
            Tuple of (is_supported, normalized_mime_type)
        """
        # Normalize content type
        normalized = content_type.lower().strip()

        # Check aliases first
        if normalized in CONTENT_TYPE_ALIASES:
            normalized = CONTENT_TYPE_ALIASES[normalized]

        # Check if directly supported
        if normalized in SUPPORTED_MIME_TYPES:
            return True, normalized

        # Try to detect from filename extension
        if filename:
            ext = Path(filename).suffix.lower().lstrip('.')
            if ext in EXTENSION_TO_MIME:
                return True, EXTENSION_TO_MIME[ext]

        return False, None

    async def download_media(
        self,
        media_url: str,
        expected_content_type: Optional[str] = None
    ) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
        """
        Download media from Twilio MediaUrl.

        Twilio media URLs require authentication with Account SID and Auth Token.

        Args:
            media_url: The Twilio MediaUrl to download
            expected_content_type: Expected MIME type (optional)

        Returns:
            Tuple of (content_bytes, actual_content_type, error_message)
        """
        auth = self._get_twilio_auth()
        if not auth:
            return None, None, "Twilio credentials not configured"

        account_sid, auth_token = auth

        try:
            # Create HTTP client with authentication
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Twilio requires Basic Auth for media downloads
                auth_string = f"{account_sid}:{auth_token}"
                auth_bytes = base64.b64encode(auth_string.encode()).decode()
                headers = {
                    "Authorization": f"Basic {auth_bytes}"
                }

                logger.info(f"Downloading media from: {media_url}")

                response = await client.get(media_url, headers=headers, follow_redirects=True)

                if response.status_code != 200:
                    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.error(f"Failed to download media: {error_msg}")
                    return None, None, error_msg

                content = response.content
                actual_content_type = response.headers.get('content-type', '').split(';')[0].strip()

                logger.info(f"Downloaded {len(content)} bytes, content-type: {actual_content_type}")

                return content, actual_content_type, None

        except httpx.TimeoutException:
            return None, None, "Download timeout - file may be too large"
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
            return None, None, str(e)

    async def save_file(
        self,
        content: bytes,
        mime_type: str,
        original_filename: Optional[str] = None
    ) -> Tuple[Optional[Path], str]:
        """
        Save downloaded file to uploads directory.

        Args:
            content: File content bytes
            mime_type: MIME type of the file
            original_filename: Original filename from Twilio

        Returns:
            Tuple of (file_path, generated_file_id)
        """
        # Generate unique file ID
        file_id = str(uuid.uuid4())

        # Get extension from MIME type
        extension = SUPPORTED_MIME_TYPES.get(mime_type, 'bin')

        # Create filename
        saved_filename = f"{file_id}.{extension}"
        file_path = UPLOAD_DIR / saved_filename

        try:
            # Write file
            with open(file_path, 'wb') as f:
                f.write(content)

            logger.info(f"Saved file to: {file_path} ({len(content)} bytes)")
            return file_path, file_id

        except Exception as e:
            logger.error(f"Error saving file: {e}")
            return None, file_id

    async def process_document_upload(
        self,
        media_url: str,
        media_content_type: str,
        original_filename: Optional[str] = None,
        message_text: Optional[str] = None,
        phone_number: Optional[str] = None,
        collection_id: Optional[str] = None,
        collection_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a document upload from WhatsApp.

        This is the main entry point for handling document uploads.

        Args:
            media_url: Twilio MediaUrl for the file
            media_content_type: MIME type from Twilio
            original_filename: Original filename if available
            message_text: Message text (may contain document name/comment)
            phone_number: Sender's phone number
            collection_id: Optional collection ID to assign document to
            collection_name: Optional collection name (for display in response)

        Returns:
            Dict with:
                - success: bool
                - message: Response message to send to user
                - document_id: Created document ID (if successful)
                - error_type: Error type (if failed)
        """
        logger.info("=" * 60)
        logger.info("WHATSAPP DOCUMENT UPLOAD")
        logger.info("=" * 60)
        logger.info(f"  Media URL: {media_url}")
        logger.info(f"  Content Type: {media_content_type}")
        logger.info(f"  Original Filename: {original_filename}")
        logger.info(f"  Message Text: {message_text}")
        logger.info(f"  Phone: {phone_number}")
        logger.info(f"  Collection ID: {collection_id}")
        logger.info(f"  Collection Name: {collection_name}")

        # Step 1: Validate file format
        is_supported, normalized_mime_type = self.is_supported_format(
            media_content_type, original_filename
        )

        if not is_supported:
            logger.warning(f"Unsupported format: {media_content_type}")
            return {
                "success": False,
                "message": UPLOAD_ERROR_UNSUPPORTED_FORMAT.format(
                    filename=original_filename or "documento"
                ),
                "document_id": None,
                "error_type": "unsupported_format"
            }

        # Step 2: Download the file
        content, actual_content_type, download_error = await self.download_media(media_url)

        if download_error:
            logger.error(f"Download failed: {download_error}")
            return {
                "success": False,
                "message": UPLOAD_ERROR_DOWNLOAD_FAILED.format(
                    filename=original_filename or "documento",
                    error=download_error
                ),
                "document_id": None,
                "error_type": "download_failed"
            }

        # Step 3: Validate file size
        file_size = len(content)
        if file_size > WHATSAPP_MAX_FILE_SIZE:
            logger.warning(f"File too large: {file_size} bytes > {WHATSAPP_MAX_FILE_SIZE}")
            return {
                "success": False,
                "message": UPLOAD_ERROR_TOO_LARGE.format(
                    filename=original_filename or "documento",
                    file_size=format_file_size(file_size)
                ),
                "document_id": None,
                "error_type": "file_too_large"
            }

        # Re-check content type from actual download
        if actual_content_type and actual_content_type != normalized_mime_type:
            # Use actual content type if different
            is_supported_actual, normalized_actual = self.is_supported_format(
                actual_content_type, original_filename
            )
            if is_supported_actual:
                normalized_mime_type = normalized_actual
                logger.info(f"Using actual content type: {normalized_mime_type}")

        # Step 4: Save file to uploads directory
        file_path, file_id = await self.save_file(content, normalized_mime_type, original_filename)

        if not file_path:
            return {
                "success": False,
                "message": UPLOAD_ERROR_PROCESSING_FAILED.format(
                    filename=original_filename or "documento",
                    error="Failed to save file"
                ),
                "document_id": None,
                "error_type": "save_failed"
            }

        # Step 5: Determine document name
        # Priority: message_text > original_filename > generated name
        document_name = None
        document_comment = None

        if message_text and message_text.strip():
            # Use message text as document name
            document_name = message_text.strip()[:255]  # Limit to 255 chars
            logger.info(f"Using message text as document name: {document_name}")
        elif original_filename:
            # Use original filename (without extension)
            document_name = Path(original_filename).stem
            logger.info(f"Using original filename as document name: {document_name}")
        else:
            # Generate a name based on upload time
            document_name = f"WhatsApp Upload {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
            logger.info(f"Generated document name: {document_name}")

        # Add source info to comment
        document_comment = f"Caricato via WhatsApp da {phone_number}" if phone_number else "Caricato via WhatsApp"

        # Step 6: Process document through ingestion pipeline
        # FEATURE #176: Added comprehensive logging and embedding count in response
        try:
            logger.info("[Feature #176] Starting pipeline processing...")
            document_id, num_items, warning_msg = await self._process_through_pipeline(
                file_path=file_path,
                file_id=file_id,
                mime_type=normalized_mime_type,
                document_name=document_name,
                document_comment=document_comment,
                file_size=file_size,
                original_filename=original_filename,
                collection_id=collection_id
            )

            if document_id:
                logger.info(f"[Feature #176] Document created successfully: {document_id}")
                logger.info(f"[Feature #176] Processing result: {num_items} items, warning: {warning_msg}")

                # Build collection line for success message
                collection_line = ""
                if collection_name:
                    collection_line = UPLOAD_SUCCESS_MESSAGE_COLLECTION_LINE.format(
                        collection_name=collection_name
                    )

                # FEATURE #176: Build embedding line for unstructured documents
                embedding_line = ""
                structured_types = [
                    "text/csv",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/vnd.ms-excel",
                    "application/json"
                ]
                if normalized_mime_type not in structured_types and num_items > 0:
                    embedding_line = UPLOAD_SUCCESS_EMBEDDING_LINE.format(num_chunks=num_items)
                    logger.info(f"[Feature #176] Adding embedding count to message: {num_items} chunks")

                # Build success message
                success_message = UPLOAD_SUCCESS_MESSAGE.format(
                    document_name=document_name,
                    document_type=get_friendly_document_type(normalized_mime_type),
                    file_size=format_file_size(file_size),
                    embedding_line=embedding_line,
                    collection_line=collection_line
                )

                # FEATURE #176: Add warning to message if present
                if warning_msg:
                    success_message += f"\n\n⚠️ {warning_msg}"
                    logger.info(f"[Feature #176] Added warning to response: {warning_msg}")

                # FEATURE #200: Generate and append suggested questions
                suggested_questions = []
                try:
                    suggested_questions = await self._generate_suggested_questions_italian(
                        document_id=document_id,
                        document_name=document_name,
                        mime_type=normalized_mime_type,
                        file_path=file_path
                    )
                    if suggested_questions:
                        # Format questions as numbered list
                        numbered_questions = "\n".join([f"{i+1}. {q}" for i, q in enumerate(suggested_questions)])
                        questions_section = SUGGESTED_QUESTIONS_TEMPLATE.format(
                            header=SUGGESTED_QUESTIONS_HEADER,
                            questions=numbered_questions
                        )
                        success_message += questions_section
                        logger.info(f"[Feature #200] Added {len(suggested_questions)} suggested questions to message")
                except Exception as sq_error:
                    logger.error(f"[Feature #200] Error adding suggested questions: {sq_error}")
                    # Don't fail the upload if question generation fails

                return {
                    "success": True,
                    "message": success_message,
                    "document_id": document_id,
                    "document_name": document_name,
                    "collection_id": collection_id,
                    "collection_name": collection_name,
                    "num_embeddings": num_items,  # FEATURE #176: Include embedding count
                    "warning": warning_msg,  # FEATURE #176: Include any warning
                    "suggested_questions": suggested_questions,  # FEATURE #200: Include suggested questions
                    "error_type": None
                }
            else:
                raise Exception("Document creation returned no ID")

        except Exception as e:
            logger.error(f"Error processing document: {e}")
            import traceback
            logger.error(traceback.format_exc())

            # Clean up file on failure
            try:
                if file_path.exists():
                    file_path.unlink()
            except Exception:
                pass

            return {
                "success": False,
                "message": UPLOAD_ERROR_PROCESSING_FAILED.format(
                    filename=original_filename or "documento",
                    error=str(e)[:200]
                ),
                "document_id": None,
                "error_type": "processing_failed"
            }

    async def _process_through_pipeline(
        self,
        file_path: Path,
        file_id: str,
        mime_type: str,
        document_name: str,
        document_comment: str,
        file_size: int,
        original_filename: Optional[str],
        collection_id: Optional[str] = None
    ) -> Tuple[Optional[str], int, Optional[str]]:
        """
        Process document through the existing ingestion pipeline.

        Uses the same logic as the /api/documents/upload endpoint.
        FEATURE #176: Added comprehensive logging and returns embedding count.

        Args:
            file_path: Path to saved file
            file_id: Generated file ID
            mime_type: Normalized MIME type
            document_name: Document title
            document_comment: Document comment
            file_size: File size in bytes
            original_filename: Original filename
            collection_id: Optional collection ID to assign document to

        Returns:
            Tuple of (Document ID if successful, number of chunks/rows, warning message)
        """
        import hashlib
        import time
        import asyncio
        from core.dependencies import get_document_store, get_document_rows_store
        from core.database import AsyncSessionLocal
        from models.document import DocumentCreate, DocumentUpdate
        from api.documents import (
            parse_structured_data,
            process_unstructured_document
        )

        logger.info("[Feature #176] Starting document pipeline processing")
        pipeline_start_time = time.time()

        # Compute content hash
        logger.info("[Feature #176] Computing content hash...")
        with open(file_path, 'rb') as f:
            content_hash = hashlib.sha256(f.read()).hexdigest()
        logger.info(f"[Feature #176] Content hash computed: {content_hash[:16]}...")

        # Determine document type
        structured_types = [
            "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "application/json"
        ]
        doc_type = "structured" if mime_type in structured_types else "unstructured"
        logger.info(f"[Feature #176] Document type: {doc_type}")

        # Create database session
        async with AsyncSessionLocal() as db:
            # Get stores
            document_store = await get_document_store(db)
            document_rows_store = await get_document_rows_store(db)

            # Create document record
            logger.info("[Feature #176] Creating document record in database...")
            doc_create = DocumentCreate(
                title=document_name,
                comment=document_comment,
                original_filename=original_filename or f"{file_id}.{SUPPORTED_MIME_TYPES.get(mime_type, 'bin')}",
                mime_type=mime_type,
                file_size=file_size,
                document_type=doc_type,
                collection_id=collection_id,  # Use provided collection_id
                content_hash=content_hash,
                url=str(file_path)
            )

            document = await document_store.create(doc_create)
            await db.commit()
            logger.info(f"[Feature #176] Created document record: {document.id}")

            num_items = 0
            warning_msg = None

            # Process based on document type
            if doc_type == "structured":
                # Parse and store rows
                import json
                logger.info("[Feature #176] Processing structured document...")
                rows, schema = parse_structured_data(file_path, mime_type)
                if rows:
                    await document_rows_store.add_rows(document.id, rows, schema)
                    schema_json = json.dumps(schema)
                    update_data = DocumentUpdate(schema_info=schema_json)
                    await document_store.update(document.id, update_data)
                    await db.commit()
                    num_items = len(rows)
                    logger.info(f"[Feature #176] Stored {num_items} rows for structured document {document.id}")
                else:
                    logger.warning(f"[Feature #176] No rows extracted from structured document")
                    warning_msg = "No rows could be extracted from the tabular file"
            else:
                # Process unstructured document (chunking, embedding)
                logger.info("[Feature #176] Processing unstructured document (chunking + embedding)...")
                logger.info(f"[Feature #176] Starting process_unstructured_document for document {document.id}")
                embedding_start_time = time.time()

                try:
                    # Call with timeout to prevent hanging on large documents
                    # The agentic chunking can be slow, so we allow up to 10 minutes
                    # FEATURE #216: Pass document_rows_store for hybrid PDF processing
                    num_chunks, embedding_warning = await asyncio.wait_for(
                        process_unstructured_document(
                            document.id,
                            file_path,
                            mime_type,
                            document_name,
                            document_rows_store=document_rows_store
                        ),
                        timeout=600.0  # 10 minute timeout
                    )

                    embedding_duration = time.time() - embedding_start_time
                    logger.info(f"[Feature #176] process_unstructured_document completed in {embedding_duration:.1f}s")
                    logger.info(f"[Feature #176] Result: num_chunks={num_chunks}, warning={embedding_warning}")

                    num_items = num_chunks
                    warning_msg = embedding_warning

                    if num_chunks > 0:
                        logger.info(f"[Feature #176] SUCCESS: Created {num_chunks} embeddings for document {document.id}")

                        if embedding_warning:
                            # Update comment with warning
                            update_data = DocumentUpdate(
                                comment=f"{document_comment}\n\n⚠️ {embedding_warning}"
                            )
                            await document_store.update(document.id, update_data)
                            await db.commit()
                            logger.info(f"[Feature #176] Added warning to document comment: {embedding_warning}")
                    else:
                        logger.warning(f"[Feature #176] WARNING: No embeddings created for document {document.id}")
                        if embedding_warning:
                            update_data = DocumentUpdate(
                                comment=f"{document_comment}\n\n⚠️ {embedding_warning}"
                            )
                            await document_store.update(document.id, update_data)
                            await db.commit()
                        else:
                            warning_msg = "No text content could be extracted from the document"

                except asyncio.TimeoutError:
                    embedding_duration = time.time() - embedding_start_time
                    logger.error(f"[Feature #176] TIMEOUT: process_unstructured_document timed out after {embedding_duration:.1f}s")
                    warning_msg = f"Embedding generation timed out after {int(embedding_duration)}s. The document was saved but may not be searchable."
                    update_data = DocumentUpdate(
                        comment=f"{document_comment}\n\n⚠️ {warning_msg}"
                    )
                    await document_store.update(document.id, update_data)
                    await db.commit()

                except Exception as embedding_error:
                    embedding_duration = time.time() - embedding_start_time
                    logger.error(f"[Feature #176] ERROR in process_unstructured_document after {embedding_duration:.1f}s: {embedding_error}")
                    import traceback
                    logger.error(f"[Feature #176] Traceback:\n{traceback.format_exc()}")
                    warning_msg = f"Error during embedding generation: {str(embedding_error)[:100]}"
                    update_data = DocumentUpdate(
                        comment=f"{document_comment}\n\n⚠️ {warning_msg}"
                    )
                    await document_store.update(document.id, update_data)
                    await db.commit()

            pipeline_duration = time.time() - pipeline_start_time
            logger.info(f"[Feature #176] Pipeline completed in {pipeline_duration:.1f}s")
            logger.info(f"[Feature #176] Final result: doc_id={document.id}, items={num_items}, warning={warning_msg}")

            return document.id, num_items, warning_msg

    async def _generate_suggested_questions_italian(
        self,
        document_id: str,
        document_name: str,
        mime_type: str,
        file_path: Path
    ) -> List[str]:
        """
        Feature #200: Generate suggested questions for uploaded document in Italian.

        Uses LLM to analyze document content and generate 3-5 relevant questions
        that users might want to ask about the document.

        Args:
            document_id: The document ID
            document_name: The document title
            mime_type: MIME type of the document
            file_path: Path to the document file

        Returns:
            List of 3-5 suggested questions in Italian
        """
        logger.info(f"[Feature #200] Generating suggested questions for document {document_id}")

        # Check if feature is enabled
        enable_suggestions = settings_store.get('enable_suggested_questions', 'true')
        if enable_suggestions.lower() == 'false':
            logger.info("[Feature #200] Suggested questions feature is disabled")
            return []

        # Get document content preview
        content_preview = ""

        # Determine document type
        structured_types = [
            "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "application/json"
        ]
        is_structured = mime_type in structured_types

        try:
            if is_structured:
                # For structured documents, read and extract schema/sample
                content_preview = await self._get_structured_preview(file_path, mime_type)
            else:
                # For unstructured documents, try to get chunks from embedding store
                chunks = embedding_store.get_chunks(document_id)
                if chunks:
                    # Get first 3 chunks for context
                    for chunk in chunks[:3]:
                        content_preview += chunk.get('text', '') + "\n\n"
                    content_preview = content_preview[:4000]  # Limit to ~1000 tokens
                else:
                    # Fallback: read text from file
                    content_preview = await self._extract_text_preview(file_path, mime_type)

            if not content_preview:
                logger.warning(f"[Feature #200] No content preview available for document {document_id}")
                return []

            # Generate questions using LLM
            questions = await self._call_llm_for_questions(document_name, mime_type, content_preview)
            logger.info(f"[Feature #200] Generated {len(questions)} suggested questions")
            return questions

        except Exception as e:
            logger.error(f"[Feature #200] Error generating suggested questions: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    async def _get_structured_preview(self, file_path: Path, mime_type: str) -> str:
        """Get content preview for structured documents."""
        try:
            import pandas as pd

            if mime_type == "text/csv":
                df = pd.read_csv(file_path, nrows=10)
            elif mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                df = pd.read_excel(file_path, engine='openpyxl', nrows=10)
            elif mime_type == "application/vnd.ms-excel":
                df = pd.read_excel(file_path, engine='xlrd', nrows=10)
            elif mime_type == "application/json":
                with open(file_path, 'r') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    df = pd.DataFrame(data[:10])
                elif isinstance(data, dict):
                    for key, value in data.items():
                        if isinstance(value, list):
                            df = pd.DataFrame(value[:10])
                            break
                    else:
                        df = pd.DataFrame([data])
                else:
                    return ""
            else:
                return ""

            columns = list(df.columns)
            sample_rows = df.to_string(index=False, max_rows=5)
            return f"Colonne: {', '.join(columns)}\n\nRighe di esempio:\n{sample_rows}"

        except Exception as e:
            logger.error(f"[Feature #200] Error reading structured file: {e}")
            return ""

    async def _extract_text_preview(self, file_path: Path, mime_type: str) -> str:
        """Extract text preview from unstructured documents."""
        try:
            if mime_type == "text/plain" or mime_type == "text/markdown":
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()[:4000]

            elif mime_type == "application/pdf":
                from pypdf import PdfReader
                reader = PdfReader(str(file_path))
                text_parts = []
                for page in reader.pages[:5]:  # First 5 pages only
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                return "\n\n".join(text_parts)[:4000]

            elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                from docx import Document as DocxDocument
                doc = DocxDocument(str(file_path))
                text_parts = []
                for paragraph in doc.paragraphs[:50]:  # First 50 paragraphs
                    if paragraph.text.strip():
                        text_parts.append(paragraph.text)
                return "\n\n".join(text_parts)[:4000]

            return ""
        except Exception as e:
            logger.error(f"[Feature #200] Error extracting text: {e}")
            return ""

    async def _call_llm_for_questions(
        self,
        document_name: str,
        mime_type: str,
        content_preview: str
    ) -> List[str]:
        """
        Call LLM to generate suggested questions in Italian.

        Tries OpenAI, OpenRouter, then Ollama as fallbacks.
        """
        # Build prompt for Italian questions
        prompt = f"""Basandoti sul seguente contenuto del documento, genera esattamente 5 domande pertinenti che un utente potrebbe voler chiedere su questo documento.

Titolo del documento: {document_name}
Tipo: {get_friendly_document_type(mime_type)}

Anteprima del contenuto:
{content_preview}

Genera 5 domande diverse che:
1. Siano direttamente rispondibili dal contenuto del documento
2. Coprano diversi aspetti/argomenti del documento
3. Siano pratiche e utili per chi legge questo documento
4. Siano concise (massimo 15 parole ciascuna)
5. Inizino con "Quali", "Come", "Cosa", "Perché", "Quando" o "Spiega"

Restituisci SOLO le domande, una per riga, senza numerazione o punti elenco."""

        questions = []

        # Try OpenAI first
        api_key = settings_store.get('openai_api_key')
        if api_key and api_key.startswith('sk-') and len(api_key) > 20:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                llm_model = settings_store.get('llm_model', 'gpt-4o-mini')
                # Use mini model for efficiency
                model_to_use = llm_model if not llm_model.startswith('ollama:') and not llm_model.startswith('openrouter:') else 'gpt-4o-mini'
                response = client.chat.completions.create(
                    model=model_to_use,
                    messages=[
                        {"role": "system", "content": "Sei un assistente che genera domande pertinenti sui documenti in italiano."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=500,
                    temperature=0.7
                )
                response_text = response.choices[0].message.content.strip()
                questions = [q.strip() for q in response_text.split('\n') if q.strip() and len(q.strip()) > 10]
                logger.info(f"[Feature #200] Generated {len(questions)} questions using OpenAI")
            except Exception as e:
                logger.error(f"[Feature #200] OpenAI failed: {e}")

        # Try OpenRouter if OpenAI failed
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
                                "model": "google/gemini-2.0-flash-001",
                                "messages": [
                                    {"role": "system", "content": "Sei un assistente che genera domande pertinenti sui documenti in italiano."},
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
                            logger.info(f"[Feature #200] Generated {len(questions)} questions using OpenRouter")
                except Exception as e:
                    logger.error(f"[Feature #200] OpenRouter failed: {e}")

        # Try Ollama as fallback
        if not questions:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    # Get available models
                    response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                    if response.status_code == 200:
                        models = response.json().get('models', [])
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
                                logger.info(f"[Feature #200] Generated {len(questions)} questions using Ollama ({ollama_model})")
            except httpx.ConnectError:
                logger.warning("[Feature #200] Ollama not available")
            except Exception as e:
                logger.error(f"[Feature #200] Ollama failed: {e}")

        # Clean up questions
        cleaned_questions = []
        for q in questions[:5]:  # Limit to 5
            # Remove leading numbers, bullets, dashes
            q = q.lstrip('0123456789.-) ')
            # Ensure it ends with a question mark
            if q and not q.endswith('?'):
                q = q + '?'
            if len(q) > 10:
                cleaned_questions.append(q)

        return cleaned_questions[:5]


# Singleton instance
_whatsapp_document_service: Optional[WhatsAppDocumentService] = None


def get_whatsapp_document_service() -> WhatsAppDocumentService:
    """Get the singleton WhatsAppDocumentService instance."""
    global _whatsapp_document_service
    if _whatsapp_document_service is None:
        _whatsapp_document_service = WhatsAppDocumentService()
    return _whatsapp_document_service
