"""
WhatsApp Service for processing messages through the RAG pipeline.

This service handles:
- Mapping WhatsApp phone numbers to virtual conversations
- Processing messages through the existing RAG/chat pipeline
- Collecting non-streaming responses for WhatsApp
- Truncating responses to WhatsApp's character limit
- Storing message history linked to phone numbers
- Special commands: 'reset', 'nuova chat', 'help', 'aiuto'
- Collection commands: 'collezioni', 'setcollezione <nome>'
- Auto-expire conversations after 24h of inactivity
"""

import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.ai_service import get_ai_service
from core.store_postgres import ConversationStorePostgres, MessageStorePostgres, CollectionStorePostgres
from core.store import settings_store
from models.conversation import (
    ConversationCreate, ConversationUpdate, MessageCreate,
    ConversationInDB, MessageInDB
)
from models.db_models import DBConversation, DBCollection
from models.whatsapp import DBWhatsAppUser

logger = logging.getLogger(__name__)

# WhatsApp message length limit
WHATSAPP_MAX_LENGTH = 1600
WHATSAPP_TRUNCATION_SUFFIX = "... [continua]"

# Token estimation constants (same as chat.py)
DEFAULT_CONTEXT_WINDOW_SIZE = 20
MAX_CONTEXT_TOKENS = 8000
CHARS_PER_TOKEN = 4

# Conversation expiry timeout (24 hours = WhatsApp session limit)
CONVERSATION_EXPIRY_HOURS = 24

# Command keywords for reset conversation
RESET_COMMANDS = ['reset', 'nuova chat', 'nuova conversazione', 'ricomincia', 'restart', 'new chat']

# Command keywords for help
HELP_COMMANDS = ['help', 'aiuto', 'comandi', 'commands', '?']

# Command keywords for listing collections
LIST_COLLECTIONS_COMMANDS = ['collezioni', 'collections', '/collection', '/collezioni', 'cartelle', 'folders']

# Command keywords for setting default collection (expects argument)
SET_COLLECTION_COMMANDS = ['setcollezione', 'setcollection', '/setcollection', '/setcollezione', 'usa collezione', 'usa cartella']

# Command keywords for deleting documents (expects argument)
DELETE_DOCUMENT_COMMANDS = ['/elimina', '/delete', 'elimina', 'delete', 'cancella', 'rimuovi']

# Command keywords for listing user's documents
# Note: These commands can optionally have a collection name argument (e.g., "/documenti Normative")
LIST_DOCUMENTS_COMMANDS = ['/documenti', '/documents', '/docs', '/list', 'documenti', 'documents', 'docs', 'miei documenti', 'my documents']

# Patterns for explicit collection specification in upload messages
# e.g., "salva in Normative", "collection: Normative", "cartella Documenti"
COLLECTION_PATTERNS = [
    r'salva\s+in\s+["\']?([^"\'\n]+)["\']?',
    r'collection[:\s]+["\']?([^"\'\n]+)["\']?',
    r'cartella[:\s]+["\']?([^"\'\n]+)["\']?',
    r'nella\s+collezione\s+["\']?([^"\'\n]+)["\']?',
    r'in\s+collezione\s+["\']?([^"\'\n]+)["\']?',
]

# Help message response
HELP_MESSAGE = """🤖 *Comandi disponibili:*

📚 *Cerca informazioni*
Fai una domanda sui documenti caricati nel sistema.
_Esempio: "Quali sono i requisiti per le scialuppe di salvataggio?"_

🔄 *Nuova conversazione*
Scrivi "reset" o "nuova chat" per iniziare una nuova conversazione.

📁 *Gestione Collezioni*
• "collezioni" - Mostra le collezioni disponibili
• "setcollezione Nome" - Imposta la collezione predefinita per i documenti

📄 *Gestione Documenti*
• "documenti" o "/docs" - Mostra i tuoi documenti
• "documenti <collezione>" - Filtra per collezione
• "/elimina Nome" - Elimina un documento caricato da te

❓ *Aiuto*
Scrivi "help" o "aiuto" per vedere questo messaggio.

💡 *Suggerimento*
Le tue conversazioni vengono salvate e puoi continuare dove hai lasciato. Dopo 24 ore di inattività, la conversazione viene archiviata automaticamente."""

# Collections list message template
COLLECTIONS_LIST_HEADER = """📁 *Collezioni disponibili:*

"""

COLLECTIONS_LIST_EMPTY = """📁 *Collezioni disponibili:*

_Nessuna collezione trovata._

Per creare una collezione, vai all'interfaccia web."""

# Set collection response templates
SET_COLLECTION_SUCCESS = """✅ *Collezione impostata!*

La tua collezione predefinita è ora:
📁 *{collection_name}*

I nuovi documenti che carichi via WhatsApp verranno salvati in questa collezione."""

SET_COLLECTION_CREATED = """✅ *Collezione creata e impostata!*

Ho creato la nuova collezione:
📁 *{collection_name}*

I nuovi documenti che carichi via WhatsApp verranno salvati in questa collezione."""

SET_COLLECTION_NOT_FOUND = """⚠️ *Collezione non trovata*

La collezione "{collection_name}" non esiste.

Usa "collezioni" per vedere le collezioni disponibili, oppure specifica un nome per creare una nuova collezione."""

SET_COLLECTION_USAGE = """⚠️ *Utilizzo corretto:*

setcollezione NomeCollezione

_Esempio: "setcollezione Normative Nautiche"_

Usa "collezioni" per vedere le collezioni disponibili."""

CURRENT_COLLECTION_INFO = """📁 *Collezione corrente:* {collection_name}
"""

# Reset confirmation message
RESET_MESSAGE = """✅ *Conversazione resettata!*

Ho creato una nuova conversazione per te. La cronologia precedente è stata archiviata.

Come posso aiutarti?"""


def estimate_tokens(text: str) -> int:
    """Estimate token count for text (rough approximation)."""
    return len(text) // CHARS_PER_TOKEN


def truncate_messages_to_token_limit(
    messages: List[dict],
    max_tokens: int = MAX_CONTEXT_TOKENS
) -> List[dict]:
    """
    Truncate oldest messages if total tokens exceed the limit.
    Always keeps the most recent message (the current user query).
    """
    if not messages:
        return messages

    total_tokens = sum(estimate_tokens(msg.get("content", "")) for msg in messages)

    if total_tokens <= max_tokens:
        return messages

    result = list(messages)

    while len(result) > 1 and total_tokens > max_tokens:
        removed_msg = result.pop(0)
        removed_tokens = estimate_tokens(removed_msg.get("content", ""))
        total_tokens -= removed_tokens
        logger.info(f"WhatsApp: Truncated oldest message to fit context window. Removed ~{removed_tokens} tokens.")

    return result


class WhatsAppService:
    """
    Service class for processing WhatsApp messages through the RAG pipeline.

    Maps phone numbers to conversations and handles message processing.
    Supports special commands: reset/nuova chat (start fresh), help/aiuto (show commands).
    Auto-expires conversations after 24h of inactivity.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize WhatsApp service with database session.

        Args:
            db: Async database session for conversation/message storage
        """
        self.db = db
        self.conversation_store = ConversationStorePostgres(db)
        self.message_store = MessageStorePostgres(db)
        self.ai_service = get_ai_service()

    def _is_command(self, message: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if the message is a special command.

        Args:
            message: Message text to check

        Returns:
            Tuple of (is_command, command_type, argument)
            command_type is 'reset', 'help', 'list_collections', 'set_collection',
            'delete_document', 'list_documents', or None
            argument contains any argument provided (e.g., document name for delete_document)
        """
        normalized = message.lower().strip()
        original = message.strip()

        # Check for reset commands
        for cmd in RESET_COMMANDS:
            if normalized == cmd or normalized.startswith(cmd + ' '):
                return (True, 'reset', None)

        # Check for help commands
        for cmd in HELP_COMMANDS:
            if normalized == cmd or normalized.startswith(cmd + ' '):
                return (True, 'help', None)

        # Check for list collections commands
        for cmd in LIST_COLLECTIONS_COMMANDS:
            if normalized == cmd or normalized.startswith(cmd + ' '):
                return (True, 'list_collections', None)

        # Check for set collection commands (extracts collection name as argument)
        for cmd in SET_COLLECTION_COMMANDS:
            if normalized == cmd:
                # Command without argument
                return (True, 'set_collection', None)
            if normalized.startswith(cmd + ' '):
                # Extract the collection name (preserve original case)
                arg_start = len(cmd) + 1
                arg = original[arg_start:].strip()
                return (True, 'set_collection', arg if arg else None)

        # Check for delete document commands (extracts document name as argument)
        for cmd in DELETE_DOCUMENT_COMMANDS:
            if normalized == cmd:
                # Command without argument
                return (True, 'delete_document', None)
            if normalized.startswith(cmd + ' '):
                # Extract the document name (preserve original case)
                arg_start = len(cmd) + 1
                arg = original[arg_start:].strip()
                return (True, 'delete_document', arg if arg else None)

        # Check for list documents commands (with optional collection filter argument)
        for cmd in LIST_DOCUMENTS_COMMANDS:
            if normalized == cmd:
                # Command without argument
                return (True, 'list_documents', None)
            if normalized.startswith(cmd + ' '):
                # Extract the collection filter (preserve original case)
                arg_start = len(cmd) + 1
                arg = original[arg_start:].strip()
                return (True, 'list_documents', arg if arg else None)

        return (False, None, None)

    def _normalize_phone_number(self, phone: str) -> str:
        """
        Normalize phone number for consistent lookup.

        Removes 'whatsapp:' prefix and standardizes format.

        Args:
            phone: Raw phone number (e.g., "whatsapp:+1234567890")

        Returns:
            Normalized phone number (e.g., "+1234567890")
        """
        # Remove whatsapp: prefix if present
        if phone.startswith("whatsapp:"):
            phone = phone[9:]

        # Strip whitespace
        phone = phone.strip()

        return phone

    def _create_conversation_title(self, phone: str) -> str:
        """
        Create a conversation title from phone number.

        Args:
            phone: Normalized phone number

        Returns:
            Conversation title string
        """
        return f"WhatsApp: {phone}"

    async def _get_whatsapp_user(self, phone_number: str) -> Optional[DBWhatsAppUser]:
        """
        Get WhatsApp user by phone number.

        Args:
            phone_number: Normalized phone number

        Returns:
            DBWhatsAppUser if found, None otherwise
        """
        stmt = select(DBWhatsAppUser).where(DBWhatsAppUser.phone_number == phone_number)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _update_whatsapp_user_conversation(
        self,
        phone_number: str,
        conversation_id: str
    ) -> None:
        """
        Update the conversation_id for a WhatsApp user.

        Args:
            phone_number: Normalized phone number
            conversation_id: New conversation ID to link
        """
        stmt = (
            update(DBWhatsAppUser)
            .where(DBWhatsAppUser.phone_number == phone_number)
            .values(
                conversation_id=conversation_id,
                updated_at=datetime.now(timezone.utc)
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()
        logger.info(f"WhatsApp: Updated user {phone_number} conversation to {conversation_id}")

    async def _is_conversation_expired(self, conversation: DBConversation) -> bool:
        """
        Check if a conversation has expired (no activity for 24+ hours).

        WhatsApp sessions have a 24-hour window, so we auto-expire conversations
        to match this behavior and provide a fresh context.

        Args:
            conversation: The conversation to check

        Returns:
            True if expired (>24h since last update), False otherwise
        """
        if not conversation or not conversation.updated_at:
            return False

        expiry_time = datetime.now(timezone.utc) - timedelta(hours=CONVERSATION_EXPIRY_HOURS)

        # Handle timezone-aware/naive datetime comparison
        conv_updated = conversation.updated_at
        if conv_updated.tzinfo is None:
            conv_updated = conv_updated.replace(tzinfo=timezone.utc)

        is_expired = conv_updated < expiry_time

        if is_expired:
            logger.info(
                f"WhatsApp: Conversation {conversation.id} expired "
                f"(last update: {conv_updated}, expiry: {expiry_time})"
            )

        return is_expired

    async def _archive_conversation(self, conversation_id: str) -> None:
        """
        Archive an expired conversation.

        Args:
            conversation_id: ID of conversation to archive
        """
        await self.conversation_store.update(
            conversation_id,
            ConversationUpdate(is_archived=True)
        )
        logger.info(f"WhatsApp: Archived expired conversation {conversation_id}")

    # =========================================================================
    # Collection Management Methods
    # =========================================================================

    async def _get_all_collections(self) -> List[DBCollection]:
        """
        Get all collections from the database.

        Returns:
            List of DBCollection objects
        """
        stmt = select(DBCollection).order_by(DBCollection.name)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _get_collection_by_name(self, name: str) -> Optional[DBCollection]:
        """
        Get a collection by name (case-insensitive).

        Args:
            name: Collection name to search for

        Returns:
            DBCollection if found, None otherwise
        """
        stmt = select(DBCollection).where(DBCollection.name.ilike(name.strip()))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_collection_by_id(self, collection_id: str) -> Optional[DBCollection]:
        """
        Get a collection by ID.

        Args:
            collection_id: Collection ID

        Returns:
            DBCollection if found, None otherwise
        """
        stmt = select(DBCollection).where(DBCollection.id == collection_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _create_collection(self, name: str, description: str = None) -> DBCollection:
        """
        Create a new collection.

        Args:
            name: Collection name
            description: Optional description

        Returns:
            Newly created DBCollection
        """
        from models.collection import CollectionCreate
        collection_store = CollectionStorePostgres(self.db)
        new_collection = await collection_store.create(
            CollectionCreate(name=name.strip(), description=description)
        )
        logger.info(f"WhatsApp: Created new collection '{name}' with ID {new_collection.id}")
        return new_collection

    async def _update_user_default_collection(
        self,
        phone_number: str,
        collection_id: Optional[str]
    ) -> None:
        """
        Update the default collection for a WhatsApp user.

        Args:
            phone_number: Normalized phone number
            collection_id: Collection ID to set as default (or None to clear)
        """
        stmt = (
            update(DBWhatsAppUser)
            .where(DBWhatsAppUser.phone_number == phone_number)
            .values(
                default_collection_id=collection_id,
                updated_at=datetime.now(timezone.utc)
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()
        logger.info(f"WhatsApp: Updated user {phone_number} default collection to {collection_id}")

    async def get_user_default_collection(self, phone_number: str) -> Optional[DBCollection]:
        """
        Get the default collection for a WhatsApp user.

        Args:
            phone_number: Phone number (with or without 'whatsapp:' prefix)

        Returns:
            DBCollection if user has a default collection set, None otherwise
        """
        normalized_phone = self._normalize_phone_number(phone_number)
        user = await self._get_whatsapp_user(normalized_phone)

        if not user or not user.default_collection_id:
            return None

        return await self._get_collection_by_id(user.default_collection_id)

    def parse_collection_from_message(self, message: str) -> Optional[str]:
        """
        Parse explicit collection name from message text.

        Supports patterns like:
        - "salva in Normative"
        - "collection: Normative"
        - "cartella Documenti"
        - "nella collezione Normative"

        Args:
            message: Message text to parse

        Returns:
            Collection name if found, None otherwise
        """
        for pattern in COLLECTION_PATTERNS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                collection_name = match.group(1).strip()
                # Remove trailing punctuation
                collection_name = collection_name.rstrip('.,!?;:')
                if collection_name:
                    logger.info(f"WhatsApp: Parsed collection name '{collection_name}' from message")
                    return collection_name
        return None

    async def handle_list_collections(self, phone_number: str) -> Dict[str, Any]:
        """
        Handle the 'collezioni' command - list all available collections.

        Args:
            phone_number: WhatsApp phone number

        Returns:
            Response dict for the command
        """
        normalized_phone = self._normalize_phone_number(phone_number)

        try:
            collections = await self._get_all_collections()

            if not collections:
                response = COLLECTIONS_LIST_EMPTY
            else:
                # Build the collections list
                lines = [COLLECTIONS_LIST_HEADER.rstrip()]

                # Get user's current default collection
                user = await self._get_whatsapp_user(normalized_phone)
                default_collection_id = user.default_collection_id if user else None

                for i, col in enumerate(collections, 1):
                    is_default = col.id == default_collection_id
                    marker = " ✓" if is_default else ""
                    lines.append(f"{i}. 📁 {col.name}{marker}")

                if default_collection_id:
                    lines.append("")
                    lines.append("_✓ = collezione predefinita_")

                lines.append("")
                lines.append('_Usa "setcollezione Nome" per impostare la collezione predefinita._')

                response = "\n".join(lines)

            logger.info(f"WhatsApp: Listed {len(collections)} collections for {normalized_phone}")

            return {
                "response": response,
                "conversation_id": None,
                "was_truncated": False,
                "original_length": len(response),
                "truncated_length": len(response),
                "tool_used": None,
                "response_source": "command"
            }
        except Exception as e:
            logger.error(f"WhatsApp: Error listing collections: {e}")
            return {
                "response": "⚠️ Errore nel recuperare le collezioni. Riprova più tardi.",
                "conversation_id": None,
                "was_truncated": False,
                "original_length": 0,
                "truncated_length": 0,
                "tool_used": None,
                "response_source": "error",
                "error": str(e)
            }

    async def handle_set_collection(self, phone_number: str, collection_name: Optional[str]) -> Dict[str, Any]:
        """
        Handle the 'setcollezione' command - set default collection for user.

        If the collection doesn't exist, creates it (configurable behavior).

        Args:
            phone_number: WhatsApp phone number
            collection_name: Name of collection to set as default

        Returns:
            Response dict for the command
        """
        normalized_phone = self._normalize_phone_number(phone_number)

        # Check for missing argument
        if not collection_name:
            return {
                "response": SET_COLLECTION_USAGE,
                "conversation_id": None,
                "was_truncated": False,
                "original_length": len(SET_COLLECTION_USAGE),
                "truncated_length": len(SET_COLLECTION_USAGE),
                "tool_used": None,
                "response_source": "command"
            }

        try:
            # Try to find the collection
            collection = await self._get_collection_by_name(collection_name)
            created_new = False

            # Check setting for auto-creating collections
            auto_create = settings_store.get('whatsapp_auto_create_collections', 'true').lower() == 'true'

            if not collection:
                if auto_create:
                    # Create the collection
                    collection = await self._create_collection(collection_name)
                    created_new = True
                else:
                    response = SET_COLLECTION_NOT_FOUND.format(collection_name=collection_name)
                    return {
                        "response": response,
                        "conversation_id": None,
                        "was_truncated": False,
                        "original_length": len(response),
                        "truncated_length": len(response),
                        "tool_used": None,
                        "response_source": "command"
                    }

            # Update user's default collection
            await self._update_user_default_collection(normalized_phone, collection.id)

            # Return success response
            if created_new:
                response = SET_COLLECTION_CREATED.format(collection_name=collection.name)
            else:
                response = SET_COLLECTION_SUCCESS.format(collection_name=collection.name)

            logger.info(f"WhatsApp: Set default collection for {normalized_phone} to '{collection.name}' (ID: {collection.id})")

            return {
                "response": response,
                "conversation_id": None,
                "was_truncated": False,
                "original_length": len(response),
                "truncated_length": len(response),
                "tool_used": None,
                "response_source": "command"
            }
        except Exception as e:
            logger.error(f"WhatsApp: Error setting collection: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "response": "⚠️ Errore nell'impostare la collezione. Riprova più tardi.",
                "conversation_id": None,
                "was_truncated": False,
                "original_length": 0,
                "truncated_length": 0,
                "tool_used": None,
                "response_source": "error",
                "error": str(e)
            }

    async def get_target_collection(
        self,
        phone_number: str,
        message: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """
        Determine the target collection for a document upload.

        Priority:
        1. Explicit collection specified in message (e.g., "salva in Normative")
        2. User's default collection preference
        3. None (will go to "Uncategorized")

        Args:
            phone_number: WhatsApp phone number
            message: Optional message text that may contain collection name

        Returns:
            Dict with 'id' and 'name' if a collection is determined, None otherwise
        """
        # 1. Check for explicit collection in message
        if message:
            explicit_name = self.parse_collection_from_message(message)
            if explicit_name:
                collection = await self._get_collection_by_name(explicit_name)
                if collection:
                    logger.info(f"WhatsApp: Using explicit collection '{collection.name}' from message")
                    return {"id": collection.id, "name": collection.name}
                else:
                    # Check if we should auto-create
                    auto_create = settings_store.get('whatsapp_auto_create_collections', 'true').lower() == 'true'
                    if auto_create:
                        collection = await self._create_collection(explicit_name)
                        return {"id": collection.id, "name": collection.name}

        # 2. Check user's default collection
        default_collection = await self.get_user_default_collection(phone_number)
        if default_collection:
            logger.info(f"WhatsApp: Using user's default collection '{default_collection.name}'")
            return {"id": default_collection.id, "name": default_collection.name}

        # 3. No collection - will go to Uncategorized
        logger.info("WhatsApp: No collection specified, document will be uncategorized")
        return None

    # =========================================================================
    # Document Management Methods (Feature #174)
    # =========================================================================

    async def handle_list_documents(
        self,
        phone_number: str,
        collection_filter: Optional[str] = None,
        page: int = 1
    ) -> Dict[str, Any]:
        """
        Handle the 'documenti' command - list documents uploaded by this user.

        Supports filtering by collection (e.g., "/documenti Normative") and
        pagination for users with many documents.

        Args:
            phone_number: WhatsApp phone number
            collection_filter: Optional collection name to filter by
            page: Page number for pagination (1-indexed), each page shows 10 docs

        Returns:
            Response dict for the command
        """
        from models.db_models import DBDocument, DBCollection
        from sqlalchemy.orm import selectinload

        normalized_phone = self._normalize_phone_number(phone_number)
        PAGE_SIZE = 10

        try:
            # Build query for documents uploaded by this user
            query = select(DBDocument).options(
                selectinload(DBDocument.collection)  # Eager load collection for efficiency
            ).where(
                DBDocument.comment.ilike(f"%Caricato via WhatsApp da {normalized_phone}%")
            )

            # If collection filter is specified, apply it
            filter_collection = None
            if collection_filter:
                # Find the collection by name (case-insensitive)
                filter_collection = await self._get_collection_by_name(collection_filter)
                if filter_collection:
                    query = query.where(DBDocument.collection_id == filter_collection.id)
                else:
                    # Collection not found - return helpful message
                    response = f"""📄 *Documenti in "{collection_filter}":*

⚠️ Collezione "{collection_filter}" non trovata.

Usa "collezioni" per vedere le collezioni disponibili,
oppure "documenti" senza filtro per vedere tutti i tuoi documenti."""
                    return {
                        "response": response,
                        "conversation_id": None,
                        "was_truncated": False,
                        "original_length": len(response),
                        "truncated_length": len(response),
                        "tool_used": None,
                        "response_source": "command"
                    }

            # Order by creation date (newest first)
            query = query.order_by(DBDocument.created_at.desc())

            # Execute query
            result = await self.db.execute(query)
            all_documents = list(result.scalars().all())
            total_count = len(all_documents)

            if total_count == 0:
                if collection_filter and filter_collection:
                    response = f"""📄 *Documenti in "{filter_collection.name}":*

_Non hai documenti in questa collezione._

Per caricare un documento in questa collezione:
1. Imposta la collezione: "setcollezione {filter_collection.name}"
2. Invia un file via WhatsApp"""
                else:
                    response = """📄 *I tuoi documenti:*

_Non hai ancora caricato nessun documento via WhatsApp._

Per caricare un documento, invia un file (PDF, Word, Excel, CSV, TXT, JSON, Markdown)."""

                return {
                    "response": response,
                    "conversation_id": None,
                    "was_truncated": False,
                    "original_length": len(response),
                    "truncated_length": len(response),
                    "tool_used": None,
                    "response_source": "command"
                }

            # Calculate pagination
            total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE  # Ceiling division
            page = max(1, min(page, total_pages))  # Clamp to valid range
            start_idx = (page - 1) * PAGE_SIZE
            end_idx = start_idx + PAGE_SIZE
            page_documents = all_documents[start_idx:end_idx]

            # Build header
            if collection_filter and filter_collection:
                header = f"📄 *Documenti in \"{filter_collection.name}\" ({total_count}):*\n"
            else:
                header = f"📄 *I tuoi documenti ({total_count}):*\n"

            lines = [header]

            # Helper function to format document type
            def format_doc_type(doc: DBDocument) -> str:
                if doc.document_type == "structured":
                    return "📊"  # Spreadsheet/tabular
                else:
                    # Use mime type for more specific icons
                    if "pdf" in doc.mime_type.lower():
                        return "📕"
                    elif "word" in doc.mime_type.lower() or "docx" in doc.mime_type.lower():
                        return "📘"
                    elif "json" in doc.mime_type.lower():
                        return "📋"
                    elif "markdown" in doc.mime_type.lower() or "md" in doc.mime_type.lower():
                        return "📝"
                    else:
                        return "📄"  # Generic document

            # Format each document with name, type, date, collection
            for i, doc in enumerate(page_documents, start=start_idx + 1):
                upload_date = doc.created_at.strftime("%d/%m/%Y") if doc.created_at else "?"
                type_icon = format_doc_type(doc)

                # Get collection name if exists and not filtering by collection
                collection_name = ""
                if not collection_filter and doc.collection:
                    collection_name = f" 📁 {doc.collection.name}"

                lines.append(f"{i}. {type_icon} *{doc.title}*")
                lines.append(f"   📅 {upload_date}{collection_name}")

            # Add pagination info if more than one page
            if total_pages > 1:
                lines.append("")
                if page < total_pages:
                    remaining = total_count - end_idx
                    lines.append(f"_📖 Pagina {page}/{total_pages} - Digita \"altro\" per vedere altri {min(remaining, PAGE_SIZE)}_")
                else:
                    lines.append(f"_📖 Pagina {page}/{total_pages} (ultima)_")

            # Add footer with helpful commands
            lines.append("")
            if collection_filter:
                lines.append('_📋 "documenti" per vedere tutti i documenti_')
            else:
                lines.append('_📁 "documenti <collezione>" per filtrare per collezione_')
            lines.append('_🗑️ "/elimina Nome" per eliminare un documento_')

            response = "\n".join(lines)

            logger.info(f"WhatsApp: Listed {len(page_documents)}/{total_count} documents for {normalized_phone} (page {page}/{total_pages}, filter: {collection_filter})")

            return {
                "response": response,
                "conversation_id": None,
                "was_truncated": False,
                "original_length": len(response),
                "truncated_length": len(response),
                "tool_used": None,
                "response_source": "command",
                # Additional metadata for pagination state (not sent to user)
                "_pagination": {
                    "total": total_count,
                    "page": page,
                    "total_pages": total_pages,
                    "collection_filter": collection_filter
                }
            }
        except Exception as e:
            logger.error(f"WhatsApp: Error listing documents: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "response": "⚠️ Errore nel recuperare i documenti. Riprova più tardi.",
                "conversation_id": None,
                "was_truncated": False,
                "original_length": 0,
                "truncated_length": 0,
                "tool_used": None,
                "response_source": "error",
                "error": str(e)
            }

    async def handle_delete_document(self, phone_number: str, document_name: Optional[str]) -> Dict[str, Any]:
        """
        Handle the 'elimina' command - initiate document deletion.

        Args:
            phone_number: WhatsApp phone number
            document_name: Name of document to delete

        Returns:
            Response dict for the command
        """
        from services.whatsapp_delete_service import get_whatsapp_delete_service

        try:
            delete_service = await get_whatsapp_delete_service(self.db)
            return await delete_service.handle_delete_command(phone_number, document_name)
        except Exception as e:
            logger.error(f"WhatsApp: Error handling delete command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "response": "⚠️ Errore durante l'eliminazione. Riprova più tardi.",
                "conversation_id": None,
                "was_truncated": False,
                "original_length": 0,
                "truncated_length": 0,
                "tool_used": None,
                "response_source": "error",
                "error": str(e)
            }

    async def handle_delete_confirmation(self, phone_number: str, is_confirmed: bool) -> Dict[str, Any]:
        """
        Handle confirmation/cancellation of pending deletion.

        Args:
            phone_number: WhatsApp phone number
            is_confirmed: True if user confirmed, False if cancelled

        Returns:
            Response dict for the command
        """
        from services.whatsapp_delete_service import get_whatsapp_delete_service

        try:
            delete_service = await get_whatsapp_delete_service(self.db)
            return await delete_service.handle_confirmation(phone_number, is_confirmed)
        except Exception as e:
            logger.error(f"WhatsApp: Error handling delete confirmation: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "response": "⚠️ Errore durante la conferma. Riprova più tardi.",
                "conversation_id": None,
                "was_truncated": False,
                "original_length": 0,
                "truncated_length": 0,
                "tool_used": None,
                "response_source": "error",
                "error": str(e)
            }

    async def get_or_create_conversation(
        self,
        phone_number: str,
        force_new: bool = False
    ) -> ConversationInDB:
        """
        Get existing conversation for phone number or create a new one.

        WhatsApp conversations are identified by a title format:
        "WhatsApp: +1234567890"

        If the existing conversation is expired (>24h of inactivity),
        it will be archived and a new one created.

        Args:
            phone_number: WhatsApp phone number (with or without 'whatsapp:' prefix)
            force_new: If True, always create a new conversation (for reset command)

        Returns:
            ConversationInDB object (existing or newly created)
        """
        normalized_phone = self._normalize_phone_number(phone_number)
        expected_title = self._create_conversation_title(normalized_phone)

        # First, check if user has a linked conversation
        user = await self._get_whatsapp_user(normalized_phone)

        if user and user.conversation_id and not force_new:
            # Load the conversation
            stmt = select(DBConversation).where(DBConversation.id == user.conversation_id)
            result = await self.db.execute(stmt)
            existing_conversation = result.scalar_one_or_none()

            if existing_conversation and not existing_conversation.is_archived:
                # Check if conversation is expired
                if await self._is_conversation_expired(existing_conversation):
                    # Archive the expired conversation
                    await self._archive_conversation(existing_conversation.id)
                    logger.info(f"WhatsApp: Archived expired conversation {existing_conversation.id}")
                else:
                    # Valid, active conversation found
                    logger.info(f"WhatsApp: Found active conversation for {normalized_phone}: {existing_conversation.id}")
                    return ConversationInDB(
                        id=existing_conversation.id,
                        title=existing_conversation.title,
                        is_archived=existing_conversation.is_archived,
                        created_at=existing_conversation.created_at,
                        updated_at=existing_conversation.updated_at,
                    )

        # Look for existing non-archived conversation with this phone number title (fallback)
        if not force_new:
            stmt = select(DBConversation).where(
                DBConversation.title == expected_title,
                DBConversation.is_archived == False
            )
            result = await self.db.execute(stmt)
            existing_conversation = result.scalar_one_or_none()

            if existing_conversation:
                # Check expiry
                if await self._is_conversation_expired(existing_conversation):
                    await self._archive_conversation(existing_conversation.id)
                else:
                    logger.info(f"WhatsApp: Found existing conversation for {normalized_phone}: {existing_conversation.id}")

                    # Update user link if user exists
                    if user:
                        await self._update_whatsapp_user_conversation(normalized_phone, existing_conversation.id)

                    return ConversationInDB(
                        id=existing_conversation.id,
                        title=existing_conversation.title,
                        is_archived=existing_conversation.is_archived,
                        created_at=existing_conversation.created_at,
                        updated_at=existing_conversation.updated_at,
                    )

        # Create new conversation for this phone number
        # For forced new (reset), add timestamp to make title unique
        if force_new:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            new_title = f"{expected_title} ({timestamp})"
        else:
            new_title = expected_title

        conversation_data = ConversationCreate(title=new_title)
        new_conversation = await self.conversation_store.create(conversation_data)
        logger.info(f"WhatsApp: Created new conversation for {normalized_phone}: {new_conversation.id}")

        # Update user link if user exists
        if user:
            await self._update_whatsapp_user_conversation(normalized_phone, new_conversation.id)

        return new_conversation

    async def reset_conversation(self, phone_number: str) -> ConversationInDB:
        """
        Reset conversation for a phone number - archives old and creates new.

        Args:
            phone_number: WhatsApp phone number

        Returns:
            New ConversationInDB object
        """
        normalized_phone = self._normalize_phone_number(phone_number)
        logger.info(f"WhatsApp: Resetting conversation for {normalized_phone}")

        # Archive current conversation if exists
        user = await self._get_whatsapp_user(normalized_phone)
        if user and user.conversation_id:
            await self._archive_conversation(user.conversation_id)

        # Create new conversation
        return await self.get_or_create_conversation(phone_number, force_new=True)

    def truncate_for_whatsapp(self, response: str) -> str:
        """
        Truncate response to fit WhatsApp's character limit.

        If response exceeds 1600 characters, truncates and adds
        "... [continua]" suffix.

        Args:
            response: Original AI response text

        Returns:
            Truncated response (max 1600 chars including suffix)
        """
        if len(response) <= WHATSAPP_MAX_LENGTH:
            return response

        # Calculate max content length accounting for suffix
        max_content = WHATSAPP_MAX_LENGTH - len(WHATSAPP_TRUNCATION_SUFFIX)

        # Truncate at word boundary if possible
        truncated = response[:max_content]

        # Try to find a good break point (space or newline)
        last_space = truncated.rfind(' ')
        last_newline = truncated.rfind('\n')
        break_point = max(last_space, last_newline)

        if break_point > max_content * 0.7:  # Only use break point if it's not too far back
            truncated = truncated[:break_point]

        truncated = truncated.rstrip() + WHATSAPP_TRUNCATION_SUFFIX

        logger.info(f"WhatsApp: Truncated response from {len(response)} to {len(truncated)} chars")

        return truncated

    async def process_message(
        self,
        phone_number: str,
        message_body: str,
        message_sid: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process an incoming WhatsApp message through the RAG pipeline.

        This method:
        1. Checks for special commands (reset, help)
        2. Gets or creates a conversation for the phone number
        3. Checks for conversation expiry (24h)
        4. Saves the user message
        5. Retrieves conversation history for context
        6. Calls the AI service (non-streaming)
        7. Truncates the response for WhatsApp if needed
        8. Saves the assistant response

        Special commands:
        - 'reset', 'nuova chat': Start a fresh conversation
        - 'help', 'aiuto': Show available commands

        Args:
            phone_number: Sender's WhatsApp phone number
            message_body: Text content of the message
            message_sid: Optional Twilio message SID for tracking

        Returns:
            Dict with:
                - response: The AI response text (truncated if needed)
                - conversation_id: ID of the conversation
                - was_truncated: Whether response was truncated
                - tool_used: Tool used by AI (if any)
                - response_source: Source of response (rag/direct/hybrid)
        """
        logger.info("=" * 60)
        logger.info("WHATSAPP MESSAGE PROCESSING")
        logger.info("=" * 60)
        logger.info(f"  Phone: {phone_number}")
        logger.info(f"  Message: {message_body[:100]}{'...' if len(message_body) > 100 else ''}")
        logger.info(f"  MessageSid: {message_sid}")

        try:
            # Import delete service helpers for confirmation check
            from services.whatsapp_delete_service import (
                has_pending_deletion, is_confirmation_response, clear_pending_deletion
            )

            # Step 0A: Check if user has a pending deletion and this is a confirmation/cancel
            if has_pending_deletion(phone_number):
                is_response, is_confirmed = is_confirmation_response(message_body)
                if is_response:
                    logger.info(f"WhatsApp: Handling delete confirmation (confirmed={is_confirmed})")
                    return await self.handle_delete_confirmation(phone_number, is_confirmed)
                else:
                    # User sent something other than confirm/cancel - clear pending and continue
                    logger.info("WhatsApp: User sent non-confirmation message, clearing pending deletion")
                    clear_pending_deletion(phone_number)

            # Step 0B: Check for special commands
            is_command, command_type, command_arg = self._is_command(message_body)

            if is_command:
                logger.info(f"WhatsApp: Detected command: {command_type} (arg: {command_arg})")

                if command_type == 'help':
                    # Return help message without processing through RAG
                    logger.info("WhatsApp: Returning help message")
                    return {
                        "response": HELP_MESSAGE,
                        "conversation_id": None,
                        "was_truncated": False,
                        "original_length": len(HELP_MESSAGE),
                        "truncated_length": len(HELP_MESSAGE),
                        "tool_used": None,
                        "response_source": "command"
                    }

                elif command_type == 'reset':
                    # Reset conversation and return confirmation
                    conversation = await self.reset_conversation(phone_number)
                    logger.info(f"WhatsApp: Conversation reset, new ID: {conversation.id}")
                    return {
                        "response": RESET_MESSAGE,
                        "conversation_id": conversation.id,
                        "was_truncated": False,
                        "original_length": len(RESET_MESSAGE),
                        "truncated_length": len(RESET_MESSAGE),
                        "tool_used": None,
                        "response_source": "command"
                    }

                elif command_type == 'list_collections':
                    # List available collections
                    logger.info("WhatsApp: Listing collections")
                    return await self.handle_list_collections(phone_number)

                elif command_type == 'set_collection':
                    # Set default collection
                    logger.info(f"WhatsApp: Setting collection to '{command_arg}'")
                    return await self.handle_set_collection(phone_number, command_arg)

                elif command_type == 'delete_document':
                    # Delete a document (Feature #174)
                    logger.info(f"WhatsApp: Delete document command with arg '{command_arg}'")
                    return await self.handle_delete_document(phone_number, command_arg)

                elif command_type == 'list_documents':
                    # List user's documents (Feature #175)
                    logger.info(f"WhatsApp: Listing user's documents (collection filter: {command_arg})")
                    return await self.handle_list_documents(phone_number, collection_filter=command_arg)

            # Step 1: Get or create conversation for this phone number
            # This also handles auto-expiry of conversations older than 24h
            conversation = await self.get_or_create_conversation(phone_number)
            conversation_id = conversation.id

            # Step 2: Save user message
            user_message_data = MessageCreate(
                conversation_id=conversation_id,
                role="user",
                content=message_body,
                tool_used=None,
                tool_details=None,
                response_source=None
            )
            await self.message_store.create(user_message_data)
            logger.info(f"WhatsApp: Saved user message to conversation {conversation_id}")

            # Step 3: Get conversation history for context
            conversation_messages = await self.message_store.get_by_conversation(conversation_id)

            # Get context window size from settings
            context_window_size = int(settings_store.get('context_window_size', DEFAULT_CONTEXT_WINDOW_SIZE))

            # Limit to last N messages for context
            if len(conversation_messages) > context_window_size:
                conversation_messages = conversation_messages[-context_window_size:]
                logger.info(f"WhatsApp: Limited context to last {context_window_size} messages")

            # Prepare messages for AI
            ai_messages = [
                {"role": msg.role, "content": msg.content}
                for msg in conversation_messages
            ]

            # Apply token limit truncation
            ai_messages = truncate_messages_to_token_limit(ai_messages)

            # Step 4: Get AI response (non-streaming)
            logger.info(f"WhatsApp: Calling AI service for conversation {conversation_id}")
            ai_response = await self.ai_service.chat(ai_messages, conversation_id)

            original_response = ai_response.get("content", "")
            tool_used = ai_response.get("tool_used")
            tool_details = ai_response.get("tool_details")
            response_source = ai_response.get("response_source")

            logger.info(f"WhatsApp: AI response length: {len(original_response)} chars")
            logger.info(f"WhatsApp: Tool used: {tool_used}, Source: {response_source}")

            # Step 5: Truncate response for WhatsApp if needed
            was_truncated = len(original_response) > WHATSAPP_MAX_LENGTH
            final_response = self.truncate_for_whatsapp(original_response)

            # Step 6: Save assistant message (with full original response for history)
            assistant_message_data = MessageCreate(
                conversation_id=conversation_id,
                role="assistant",
                content=original_response,  # Store full response in history
                tool_used=tool_used,
                tool_details=tool_details,
                response_source=response_source
            )
            await self.message_store.create(assistant_message_data)
            logger.info(f"WhatsApp: Saved assistant response to conversation {conversation_id}")

            # Update conversation timestamp
            await self.conversation_store.update(
                conversation_id,
                ConversationUpdate(title=conversation.title)  # Just to update updated_at
            )

            logger.info("=" * 60)
            logger.info("WHATSAPP MESSAGE PROCESSING COMPLETE")
            logger.info("=" * 60)

            return {
                "response": final_response,
                "conversation_id": conversation_id,
                "was_truncated": was_truncated,
                "original_length": len(original_response),
                "truncated_length": len(final_response),
                "tool_used": tool_used,
                "response_source": response_source
            }

        except Exception as e:
            logger.error(f"WhatsApp: Error processing message: {e}")
            import traceback
            logger.error(traceback.format_exc())

            # Return error response
            error_response = "Mi dispiace, si e' verificato un errore nell'elaborazione del messaggio. Riprova piu' tardi."

            return {
                "response": error_response,
                "conversation_id": None,
                "was_truncated": False,
                "original_length": len(error_response),
                "truncated_length": len(error_response),
                "tool_used": None,
                "response_source": "error",
                "error": str(e)
            }

    async def get_conversation_history(
        self,
        phone_number: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get conversation history for a phone number.

        Args:
            phone_number: WhatsApp phone number
            limit: Maximum number of messages to return

        Returns:
            List of message dictionaries with role, content, and created_at
        """
        normalized_phone = self._normalize_phone_number(phone_number)
        expected_title = self._create_conversation_title(normalized_phone)

        # Find conversation
        stmt = select(DBConversation).where(DBConversation.title == expected_title)
        result = await self.db.execute(stmt)
        conversation = result.scalar_one_or_none()

        if not conversation:
            return []

        # Get messages
        messages = await self.message_store.get_by_conversation(conversation.id)

        # Limit and format
        messages = messages[-limit:] if len(messages) > limit else messages

        return [
            {
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ]
