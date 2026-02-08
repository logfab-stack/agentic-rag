"""
WhatsApp Document Delete Service.

Handles document deletion via WhatsApp:
- Delete commands: /elimina, /delete, elimina, cancella, rimuovi
- Fuzzy name matching to find documents
- Ownership verification (only documents uploaded by the WhatsApp user)
- Confirmation prompt flow before deletion
- Actual document deletion with cleanup

Feature #174: Delete Documents via WhatsApp
"""

import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import DBDocument
from core.store import embedding_store

logger = logging.getLogger(__name__)

# Command keywords for deleting documents
DELETE_DOCUMENT_COMMANDS = ['/elimina', '/delete', 'elimina', 'delete', 'cancella', 'rimuovi']

# Command keywords for confirming deletion
DELETE_CONFIRM_COMMANDS = ['sì', 'si', 'yes', 'conferma', 'confirm', 'ok']

# Command keywords for canceling deletion
DELETE_CANCEL_COMMANDS = ['no', 'annulla', 'cancel', 'abort']

# Message templates
DELETE_USAGE_MESSAGE = """📋 *Come eliminare un documento:*

Scrivi uno di questi comandi seguito dal nome del documento:
• /elimina Nome Documento
• /delete nome documento
• elimina nome documento
• cancella nome documento

_Esempio: "/elimina Normativa SOLAS"_

Il documento verrà cercato tra quelli che hai caricato tu via WhatsApp."""

DELETE_CONFIRM_PROMPT = """⚠️ *Conferma eliminazione*

Stai per eliminare il documento:
📄 *{document_name}*
📁 Collezione: {collection_name}
📅 Caricato il: {upload_date}

*Questa azione è irreversibile!*

Rispondi con:
• "sì" o "conferma" per eliminare
• "no" o "annulla" per annullare"""

DELETE_SUCCESS_MESSAGE = """✅ *Documento eliminato!*

Ho eliminato il documento:
📄 *{document_name}*

{embeddings_info}"""

DELETE_CANCELLED_MESSAGE = """❌ *Eliminazione annullata*

Il documento "{document_name}" non è stato eliminato."""

DELETE_NOT_FOUND_MESSAGE = """⚠️ *Documento non trovato*

Non ho trovato nessun documento con il nome "{search_query}" tra quelli che hai caricato tu.

💡 *Suggerimento:*
Puoi eliminare solo i documenti che hai caricato tu via WhatsApp.
Prova con un nome diverso o verifica che il documento esista."""

DELETE_MULTIPLE_FOUND_MESSAGE = """⚠️ *Più documenti trovati*

Ho trovato {count} documenti che corrispondono a "{search_query}":

{document_list}

Specifica il nome completo del documento che vuoi eliminare."""

DELETE_NOT_OWNER_MESSAGE = """⚠️ *Accesso negato*

Il documento "{document_name}" non è stato caricato da te via WhatsApp.

Puoi eliminare solo i documenti che hai caricato tu stesso."""

DELETE_ERROR_MESSAGE = """⚠️ *Errore*

Si è verificato un errore durante l'eliminazione del documento.

Errore: {error}

Riprova più tardi."""

# Pending deletion state storage (in-memory for simplicity)
# In production, this should be stored in Redis or database
_pending_deletions: Dict[str, Dict[str, Any]] = {}


def normalize_phone_number(phone: str) -> str:
    """Normalize phone number for consistent lookup."""
    if phone.startswith("whatsapp:"):
        phone = phone[9:]
    return phone.strip()


def is_delete_command(message: str) -> Tuple[bool, Optional[str]]:
    """
    Check if the message is a delete command.

    Args:
        message: Message text to check

    Returns:
        Tuple of (is_delete_command, document_name_arg)
    """
    normalized = message.lower().strip()
    original = message.strip()

    for cmd in DELETE_DOCUMENT_COMMANDS:
        cmd_lower = cmd.lower()
        if normalized == cmd_lower:
            # Command without argument
            return (True, None)
        if normalized.startswith(cmd_lower + ' '):
            # Extract the document name (preserve original case)
            arg_start = len(cmd_lower) + 1
            arg = original[arg_start:].strip()
            return (True, arg if arg else None)

    return (False, None)


def is_confirmation_response(message: str) -> Tuple[bool, bool]:
    """
    Check if the message is a confirmation/cancel response.

    Args:
        message: Message text to check

    Returns:
        Tuple of (is_response, is_confirmed)
        - is_response: True if this is a confirm/cancel response
        - is_confirmed: True if confirmed, False if cancelled
    """
    normalized = message.lower().strip()

    # Check for confirmation
    for cmd in DELETE_CONFIRM_COMMANDS:
        if normalized == cmd.lower():
            return (True, True)

    # Check for cancellation
    for cmd in DELETE_CANCEL_COMMANDS:
        if normalized == cmd.lower():
            return (True, False)

    return (False, False)


def has_pending_deletion(phone_number: str) -> bool:
    """Check if a user has a pending deletion."""
    normalized = normalize_phone_number(phone_number)
    return normalized in _pending_deletions


def get_pending_deletion(phone_number: str) -> Optional[Dict[str, Any]]:
    """Get pending deletion info for a user."""
    normalized = normalize_phone_number(phone_number)
    return _pending_deletions.get(normalized)


def set_pending_deletion(phone_number: str, document_info: Dict[str, Any]) -> None:
    """Set pending deletion for a user."""
    normalized = normalize_phone_number(phone_number)
    _pending_deletions[normalized] = {
        **document_info,
        "created_at": datetime.now(timezone.utc)
    }
    logger.info(f"WhatsApp Delete: Set pending deletion for {normalized}: {document_info['document_name']}")


def clear_pending_deletion(phone_number: str) -> None:
    """Clear pending deletion for a user."""
    normalized = normalize_phone_number(phone_number)
    if normalized in _pending_deletions:
        del _pending_deletions[normalized]
        logger.info(f"WhatsApp Delete: Cleared pending deletion for {normalized}")


def check_document_ownership(document: DBDocument, phone_number: str) -> bool:
    """
    Check if a document was uploaded by a specific WhatsApp user.

    Documents uploaded via WhatsApp have a comment containing:
    "Caricato via WhatsApp da {phone_number}"

    Args:
        document: The document to check
        phone_number: The phone number to verify ownership

    Returns:
        True if the document was uploaded by this phone number
    """
    if not document.comment:
        return False

    normalized_phone = normalize_phone_number(phone_number)

    # Check for the WhatsApp upload marker in the comment
    pattern = r'Caricato via WhatsApp da ([+\d]+)'
    match = re.search(pattern, document.comment)

    if match:
        uploader_phone = match.group(1)
        return uploader_phone == normalized_phone

    return False


def fuzzy_match_title(query: str, title: str) -> float:
    """
    Calculate a simple fuzzy match score between query and title.

    Args:
        query: Search query
        title: Document title

    Returns:
        Match score between 0 and 1
    """
    query_lower = query.lower().strip()
    title_lower = title.lower().strip()

    # Exact match
    if query_lower == title_lower:
        return 1.0

    # Contains match
    if query_lower in title_lower:
        return 0.8 + (len(query_lower) / len(title_lower)) * 0.2

    # Word-based matching
    query_words = set(query_lower.split())
    title_words = set(title_lower.split())

    if query_words.issubset(title_words):
        return 0.7 + (len(query_words) / len(title_words)) * 0.2

    common_words = query_words.intersection(title_words)
    if common_words:
        return len(common_words) / max(len(query_words), len(title_words)) * 0.6

    return 0.0


class WhatsAppDeleteService:
    """
    Service for handling document deletion via WhatsApp.

    Provides:
    - Document search by name with fuzzy matching
    - Ownership verification
    - Confirmation prompt flow
    - Document deletion with cleanup
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    async def search_documents_by_name(
        self,
        query: str,
        phone_number: str,
        limit: int = 5
    ) -> List[DBDocument]:
        """
        Search for documents by name that belong to a specific WhatsApp user.

        Args:
            query: Search query (document name or partial name)
            phone_number: Phone number to filter by ownership
            limit: Maximum number of results

        Returns:
            List of matching documents sorted by relevance
        """
        normalized_phone = normalize_phone_number(phone_number)

        # Get all documents that might match (we'll filter and score them)
        stmt = select(DBDocument).where(
            DBDocument.comment.ilike(f"%Caricato via WhatsApp da {normalized_phone}%")
        )
        result = await self.db.execute(stmt)
        documents = list(result.scalars().all())

        logger.info(f"WhatsApp Delete: Found {len(documents)} documents for user {normalized_phone}")

        if not documents:
            return []

        # Score and filter documents
        scored_docs = []
        for doc in documents:
            score = fuzzy_match_title(query, doc.title)
            if score > 0.3:  # Minimum threshold
                scored_docs.append((doc, score))

        # Sort by score descending
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        # Return top matches
        return [doc for doc, score in scored_docs[:limit]]

    async def get_document_by_id(self, document_id: str) -> Optional[DBDocument]:
        """Get a document by ID."""
        stmt = select(DBDocument).where(DBDocument.id == document_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_document(self, document_id: str) -> Tuple[bool, int]:
        """
        Delete a document and its associated data.

        Args:
            document_id: ID of document to delete

        Returns:
            Tuple of (success, embeddings_deleted)
        """
        try:
            # Get document first to verify it exists
            document = await self.get_document_by_id(document_id)
            if not document:
                logger.warning(f"WhatsApp Delete: Document {document_id} not found")
                return (False, 0)

            # Delete document rows if any (for structured data)
            from sqlalchemy import text
            await self.db.execute(
                text("DELETE FROM document_rows WHERE dataset_id = :doc_id"),
                {"doc_id": document_id}
            )

            # Delete embeddings
            import asyncio
            loop = asyncio.get_event_loop()
            embeddings_deleted = await loop.run_in_executor(
                None,
                embedding_store.delete_document,
                document_id
            )

            # Delete the document
            await self.db.execute(
                delete(DBDocument).where(DBDocument.id == document_id)
            )
            await self.db.commit()

            # Delete the file if it exists
            if document.url:
                from pathlib import Path
                file_path = Path(document.url)
                if file_path.exists():
                    try:
                        file_path.unlink()
                        logger.info(f"WhatsApp Delete: Deleted file {file_path}")
                    except Exception as e:
                        logger.warning(f"WhatsApp Delete: Failed to delete file {file_path}: {e}")

            logger.info(f"WhatsApp Delete: Successfully deleted document {document_id}")
            return (True, embeddings_deleted if embeddings_deleted else 0)

        except Exception as e:
            logger.error(f"WhatsApp Delete: Error deleting document {document_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await self.db.rollback()
            return (False, 0)

    async def handle_delete_command(
        self,
        phone_number: str,
        document_name: Optional[str]
    ) -> Dict[str, Any]:
        """
        Handle a delete command from WhatsApp.

        Args:
            phone_number: WhatsApp phone number
            document_name: Name/query of document to delete

        Returns:
            Response dict
        """
        normalized_phone = normalize_phone_number(phone_number)

        # Check for missing argument
        if not document_name:
            return self._make_response(DELETE_USAGE_MESSAGE)

        logger.info(f"WhatsApp Delete: Searching for '{document_name}' for user {normalized_phone}")

        try:
            # Search for matching documents
            matches = await self.search_documents_by_name(document_name, phone_number)

            if not matches:
                response = DELETE_NOT_FOUND_MESSAGE.format(search_query=document_name)
                return self._make_response(response)

            if len(matches) > 1:
                # Multiple matches - ask user to be more specific
                doc_list = "\n".join([
                    f"• {doc.title}" for doc in matches
                ])
                response = DELETE_MULTIPLE_FOUND_MESSAGE.format(
                    count=len(matches),
                    search_query=document_name,
                    document_list=doc_list
                )
                return self._make_response(response)

            # Single match - verify ownership and prompt for confirmation
            document = matches[0]

            if not check_document_ownership(document, phone_number):
                response = DELETE_NOT_OWNER_MESSAGE.format(document_name=document.title)
                return self._make_response(response)

            # Get collection name
            collection_name = "Nessuna"
            if document.collection_id:
                from models.db_models import DBCollection
                stmt = select(DBCollection).where(DBCollection.id == document.collection_id)
                result = await self.db.execute(stmt)
                collection = result.scalar_one_or_none()
                if collection:
                    collection_name = collection.name

            # Format upload date
            upload_date = document.created_at.strftime("%d/%m/%Y %H:%M") if document.created_at else "Sconosciuto"

            # Set pending deletion
            set_pending_deletion(phone_number, {
                "document_id": document.id,
                "document_name": document.title,
                "collection_name": collection_name
            })

            # Return confirmation prompt
            response = DELETE_CONFIRM_PROMPT.format(
                document_name=document.title,
                collection_name=collection_name,
                upload_date=upload_date
            )
            return self._make_response(response)

        except Exception as e:
            logger.error(f"WhatsApp Delete: Error handling delete command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            response = DELETE_ERROR_MESSAGE.format(error=str(e)[:200])
            return self._make_response(response, is_error=True)

    async def handle_confirmation(
        self,
        phone_number: str,
        is_confirmed: bool
    ) -> Dict[str, Any]:
        """
        Handle confirmation/cancellation of pending deletion.

        Args:
            phone_number: WhatsApp phone number
            is_confirmed: True if user confirmed, False if cancelled

        Returns:
            Response dict
        """
        pending = get_pending_deletion(phone_number)

        if not pending:
            # No pending deletion - this shouldn't happen
            logger.warning(f"WhatsApp Delete: No pending deletion for {phone_number}")
            return self._make_response("Non c'è nessuna eliminazione in sospeso.")

        document_name = pending.get("document_name", "Documento")
        document_id = pending.get("document_id")

        # Clear the pending deletion first
        clear_pending_deletion(phone_number)

        if not is_confirmed:
            response = DELETE_CANCELLED_MESSAGE.format(document_name=document_name)
            return self._make_response(response)

        # Perform the deletion
        try:
            success, embeddings_deleted = await self.delete_document(document_id)

            if success:
                embeddings_info = ""
                if embeddings_deleted > 0:
                    embeddings_info = f"🗑️ Eliminati {embeddings_deleted} chunk di testo indicizzati."

                response = DELETE_SUCCESS_MESSAGE.format(
                    document_name=document_name,
                    embeddings_info=embeddings_info
                )
                return self._make_response(response)
            else:
                response = DELETE_ERROR_MESSAGE.format(error="Impossibile eliminare il documento")
                return self._make_response(response, is_error=True)

        except Exception as e:
            logger.error(f"WhatsApp Delete: Error during deletion: {e}")
            import traceback
            logger.error(traceback.format_exc())
            response = DELETE_ERROR_MESSAGE.format(error=str(e)[:200])
            return self._make_response(response, is_error=True)

    def _make_response(self, message: str, is_error: bool = False) -> Dict[str, Any]:
        """Create a standard response dict."""
        return {
            "response": message,
            "conversation_id": None,
            "was_truncated": False,
            "original_length": len(message),
            "truncated_length": len(message),
            "tool_used": None,
            "response_source": "error" if is_error else "command"
        }


# Singleton instance
_whatsapp_delete_service: Optional[WhatsAppDeleteService] = None


async def get_whatsapp_delete_service(db: AsyncSession) -> WhatsAppDeleteService:
    """Get a WhatsAppDeleteService instance with the given database session."""
    return WhatsAppDeleteService(db)
