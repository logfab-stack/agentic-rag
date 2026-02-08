"""
Telegram Service for processing messages through the RAG pipeline.

Feature #309: Telegram service for RAG processing

This service handles:
- Mapping Telegram chat_id to virtual conversations
- Processing messages through the existing RAG/chat pipeline
- Collecting non-streaming responses for Telegram
- Truncating responses to Telegram's 4096 character limit
- Storing message history linked to chat_id
- Special commands: /start, /reset, /help
- Auto-expire conversations after 24h of inactivity
"""

import logging
import re
import time
from typing import Optional, Dict, Any, List, Tuple, Callable
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.ai_service import get_ai_service
from services.security_service import get_security_service
from core.store_postgres import ConversationStorePostgres, MessageStorePostgres, CollectionStorePostgres
from core.store import settings_store
from core.config import settings  # Feature #331: Get agentic splitter timeout setting
from models.conversation import (
    ConversationCreate, ConversationUpdate, MessageCreate,
    ConversationInDB, MessageInDB
)
from models.db_models import DBConversation, DBCollection
from models.telegram import DBTelegramUser

logger = logging.getLogger(__name__)

# Telegram message length limit (4096 UTF-8 characters)
TELEGRAM_MAX_LENGTH = 4096
TELEGRAM_TRUNCATION_SUFFIX = "... [continua]"

# Token estimation constants (same as WhatsApp service)
DEFAULT_CONTEXT_WINDOW_SIZE = 20
MAX_CONTEXT_TOKENS = 8000
CHARS_PER_TOKEN = 4

# Conversation expiry timeout (24 hours)
CONVERSATION_EXPIRY_HOURS = 24

# Progress message rate limiting (Feature #332)
PROGRESS_MESSAGE_MIN_INTERVAL = 30  # seconds between progress messages

# Command keywords for reset conversation
RESET_COMMANDS = ['/reset', 'reset', 'nuova chat', 'nuova conversazione', 'ricomincia', 'restart', 'new chat', '/nuova']

# Command keywords for help
HELP_COMMANDS = ['/help', 'help', 'aiuto', 'comandi', 'commands', '?', '/start', '/aiuto']

# Command keywords for listing collections
LIST_COLLECTIONS_COMMANDS = ['/collezioni', '/collections', 'collezioni', 'collections', 'cartelle', 'folders']

# Command keywords for setting default collection (expects argument)
SET_COLLECTION_COMMANDS = ['/setcollezione', '/setcollection', 'setcollezione', 'setcollection', 'usa collezione', 'usa cartella']

# Command keywords for listing documents (expects optional collection argument)
LIST_DOCS_COMMANDS = ['/docs', '/documenti', 'documenti', 'documents', 'lista documenti', 'my docs']

# Command keywords for deleting documents (expects document name argument)
DELETE_DOC_COMMANDS = ['/elimina', '/delete', 'elimina', 'delete', 'rimuovi', 'cancella']

# Help message response (Telegram supports Markdown)
HELP_MESSAGE = """*Comandi disponibili:*

*Cerca informazioni*
Fai una domanda sui documenti caricati nel sistema.
_Esempio: "Quali sono i requisiti per le scialuppe di salvataggio?"_

*Nuova conversazione*
Scrivi /reset o "nuova chat" per iniziare una nuova conversazione.

*Gestione Documenti*
- /docs - Mostra i tuoi documenti
- /docs NomeCollezione - Mostra documenti in una collezione
- /elimina NomeDocumento - Elimina un documento

*Gestione Collezioni*
- /collezioni - Mostra le collezioni disponibili
- /setcollezione Nome - Imposta la collezione predefinita

*Aiuto*
Scrivi /help o "aiuto" per vedere questo messaggio.

_Le tue conversazioni vengono salvate e puoi continuare dove hai lasciato. Dopo 24 ore di inattivita, la conversazione viene archiviata automaticamente._"""

# Collections list message template
COLLECTIONS_LIST_HEADER = """*Collezioni disponibili:*

"""

COLLECTIONS_LIST_EMPTY = """*Collezioni disponibili:*

_Nessuna collezione trovata._

Per creare una collezione, vai all'interfaccia web."""

# Set collection response templates
SET_COLLECTION_SUCCESS = """*Collezione impostata!*

La tua collezione predefinita e ora:
*{collection_name}*

I nuovi documenti verranno salvati in questa collezione."""

SET_COLLECTION_CREATED = """*Collezione creata e impostata!*

Ho creato la nuova collezione:
*{collection_name}*

I nuovi documenti verranno salvati in questa collezione."""

SET_COLLECTION_NOT_FOUND = """*Collezione non trovata*

La collezione "{collection_name}" non esiste.

Usa /collezioni per vedere le collezioni disponibili."""

SET_COLLECTION_USAGE = """*Utilizzo corretto:*

/setcollezione NomeCollezione

_Esempio: "/setcollezione Normative Nautiche"_

Usa /collezioni per vedere le collezioni disponibili."""

# Reset confirmation message
RESET_MESSAGE = """*Conversazione resettata!*

Ho creato una nuova conversazione per te. La cronologia precedente e stata archiviata.

Come posso aiutarti?"""

# Start message for new users
START_MESSAGE = """*Benvenuto!*

Sono il tuo assistente RAG. Puoi chiedermi informazioni sui documenti caricati nel sistema.

*Comandi disponibili:*
- /help - Mostra i comandi
- /reset - Nuova conversazione
- /docs - Mostra i tuoi documenti
- /collezioni - Mostra collezioni

_Fai una domanda per iniziare!_"""

# Documents list message templates
DOCS_LIST_HEADER = """*I tuoi documenti:*

"""

DOCS_LIST_COLLECTION_HEADER = """*Documenti in "{collection_name}":*

"""

DOCS_LIST_EMPTY = """*Nessun documento trovato*

Non hai ancora caricato documenti.

_Inviami un file (PDF, TXT, Word, CSV, Excel, JSON, Markdown) per caricarlo nel sistema._"""

DOCS_LIST_COLLECTION_EMPTY = """*Nessun documento in "{collection_name}"*

La collezione e vuota o non esiste.

Usa /collezioni per vedere le collezioni disponibili."""

# Delete document response templates
DELETE_DOC_SUCCESS = """*Documento eliminato!*

Il documento *{doc_title}* e stato eliminato con successo."""

DELETE_DOC_NOT_FOUND = """*Documento non trovato*

Non ho trovato un documento con il nome "{doc_name}".

Usa /docs per vedere i tuoi documenti."""

DELETE_DOC_USAGE = """*Utilizzo corretto:*

/elimina NomeDocumento

_Esempio: "/elimina Report Vendite 2024"_

Usa /docs per vedere i tuoi documenti."""

DELETE_DOC_CONFIRM = """*Conferma eliminazione*

Stai per eliminare il documento:
*{doc_title}*

Questa azione e irreversibile.

_Rispondi "si" o "conferma" per procedere, oppure "no" per annullare._"""


# =========================================================================
# Feature #332: Progress Reporter for Document Processing
# =========================================================================

class TelegramProgressReporter:
    """
    Rate-limited progress reporter for Telegram document processing.

    Feature #332: Telegram progress feedback during document processing

    Sends progress updates to users while their document is being processed,
    but rate-limits messages to avoid spamming (max 1 message per 30 seconds).
    """

    def __init__(self, chat_id: int, reply_to_message_id: Optional[int] = None):
        """
        Initialize progress reporter.

        Args:
            chat_id: Telegram chat ID to send progress updates to
            reply_to_message_id: Optional message ID to reply to
        """
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.last_message_time: float = 0
        self.messages_sent: int = 0
        self._send_service = None

    def _get_send_service(self):
        """Lazy initialization of send service."""
        if self._send_service is None:
            from services.telegram_send_service import get_telegram_send_service
            self._send_service = get_telegram_send_service()
        return self._send_service

    def _can_send(self) -> bool:
        """Check if enough time has passed since last message."""
        current_time = time.time()
        return (current_time - self.last_message_time) >= PROGRESS_MESSAGE_MIN_INTERVAL

    async def send_progress(self, message: str, force: bool = False) -> bool:
        """
        Send a progress message if rate limit allows.

        Args:
            message: Progress message to send
            force: If True, send regardless of rate limit (for important messages)

        Returns:
            True if message was sent, False if rate limited
        """
        if not force and not self._can_send():
            logger.debug(f"Telegram progress rate limited for chat_id={self.chat_id}")
            return False

        try:
            send_service = self._get_send_service()
            result = await send_service.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown",
                reply_to_message_id=self.reply_to_message_id if self.messages_sent == 0 else None
            )

            if result.get('success'):
                self.last_message_time = time.time()
                self.messages_sent += 1
                logger.info(f"Telegram progress sent to chat_id={self.chat_id}: {message[:50]}...")
                return True
            else:
                logger.warning(f"Failed to send progress to chat_id={self.chat_id}: {result.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Error sending progress to chat_id={self.chat_id}: {e}")
            return False

    async def document_received(self, file_name: str) -> bool:
        """Send initial 'document received' message."""
        message = (
            f"*Documento ricevuto*\n\n"
            f"File: `{file_name}`\n\n"
            f"_Avvio elaborazione..._"
        )
        return await self.send_progress(message, force=True)

    async def processing_started(self, doc_type: str) -> bool:
        """Send message when processing starts."""
        if doc_type == "structured":
            message = (
                "⏳ *Elaborazione in corso...*\n\n"
                "_Analisi dei dati tabellari..._"
            )
        else:
            message = (
                "⏳ *Elaborazione in corso...*\n\n"
                "_Estrazione del testo..._"
            )
        return await self.send_progress(message, force=True)

    async def chunking_progress(self, chunks_created: int) -> bool:
        """Send progress during chunking phase."""
        message = (
            f"⏳ *Elaborazione in corso...*\n\n"
            f"_Creati {chunks_created} chunk finora..._"
        )
        return await self.send_progress(message)

    async def embedding_started(self, chunk_count: int) -> bool:
        """Send message when embedding generation starts."""
        message = (
            f"⏳ *Creazione embeddings...*\n\n"
            f"_Generazione vettori per {chunk_count} chunks..._"
        )
        return await self.send_progress(message)

    async def processing_complete(
        self,
        doc_title: str,
        doc_type: str,
        chunk_count: int = 0,
        row_count: int = 0,
        collection_name: Optional[str] = None
    ) -> bool:
        """Send completion message."""
        collection_info = f"nella collezione *{collection_name}*" if collection_name else "in *Uncategorized*"

        if doc_type == "structured":
            message = (
                f"*Documento caricato!*\n\n"
                f"*{doc_title}*\n\n"
                f"Tipo: Tabellare\n"
                f"Righe: {row_count}\n\n"
                f"Salvato {collection_info}.\n\n"
                f"_Usa domande come \"qual e il totale delle vendite?\" per interrogare i dati._"
            )
        else:
            message = (
                f"*Documento caricato!*\n\n"
                f"*{doc_title}*\n\n"
                f"Tipo: Testuale\n"
                f"Chunks: {chunk_count}\n\n"
                f"Salvato {collection_info}.\n\n"
                f"_Ora puoi fare domande sul contenuto del documento._"
            )
        return await self.send_progress(message, force=True)

    async def processing_error(self, error_msg: str) -> bool:
        """Send error message."""
        message = (
            f"*Errore durante l'elaborazione*\n\n"
            f"{error_msg}"
        )
        return await self.send_progress(message, force=True)


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
        logger.info(f"Telegram: Truncated oldest message to fit context window. Removed ~{removed_tokens} tokens.")

    return result


class TelegramService:
    """
    Service class for processing Telegram messages through the RAG pipeline.

    Maps chat_id to conversations and handles message processing.
    Supports special commands: /reset (start fresh), /help (show commands).
    Auto-expires conversations after 24h of inactivity.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize Telegram service with database session.

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
            'list_docs', 'delete_doc', or None
            argument contains any argument provided
        """
        normalized = message.lower().strip()
        original = message.strip()

        # Check for reset commands
        for cmd in RESET_COMMANDS:
            if normalized == cmd or normalized.startswith(cmd + ' '):
                return (True, 'reset', None)

        # Check for help commands (includes /start)
        for cmd in HELP_COMMANDS:
            if normalized == cmd or normalized.startswith(cmd + ' '):
                # /start returns the start message, others return help
                if normalized == '/start' or normalized.startswith('/start '):
                    return (True, 'start', None)
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

        # Check for list documents commands (optional collection argument)
        for cmd in LIST_DOCS_COMMANDS:
            if normalized == cmd:
                # Command without argument - list all documents
                return (True, 'list_docs', None)
            if normalized.startswith(cmd + ' '):
                # Extract the collection name (preserve original case)
                arg_start = len(cmd) + 1
                arg = original[arg_start:].strip()
                return (True, 'list_docs', arg if arg else None)

        # Check for delete document commands (expects document name argument)
        for cmd in DELETE_DOC_COMMANDS:
            if normalized == cmd:
                # Command without argument
                return (True, 'delete_doc', None)
            if normalized.startswith(cmd + ' '):
                # Extract the document name (preserve original case)
                arg_start = len(cmd) + 1
                arg = original[arg_start:].strip()
                return (True, 'delete_doc', arg if arg else None)

        return (False, None, None)

    def _create_conversation_title(self, chat_id: int) -> str:
        """
        Create a conversation title from chat_id.

        Args:
            chat_id: Telegram chat ID

        Returns:
            Conversation title string
        """
        return f"Telegram: {chat_id}"

    async def get_or_create_user(
        self,
        chat_id: int,
        user_info: Optional[Dict[str, Any]] = None
    ) -> DBTelegramUser:
        """
        Get existing Telegram user by chat_id or create a new one.

        Args:
            chat_id: Telegram chat ID
            user_info: Optional user info dict from Telegram (username, first_name, etc.)

        Returns:
            DBTelegramUser object (existing or newly created)
        """
        import uuid
        from datetime import datetime, timezone

        # Check if user exists
        stmt = select(DBTelegramUser).where(DBTelegramUser.chat_id == chat_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            # Update user info if provided
            if user_info:
                update_values = {'last_message_at': datetime.now(timezone.utc)}
                if user_info.get('username'):
                    update_values['username'] = user_info.get('username')
                if user_info.get('first_name'):
                    update_values['first_name'] = user_info.get('first_name')
                if user_info.get('last_name'):
                    update_values['last_name'] = user_info.get('last_name')

                stmt = (
                    update(DBTelegramUser)
                    .where(DBTelegramUser.id == user.id)
                    .values(**update_values)
                )
                await self.db.execute(stmt)
                await self.db.commit()

            logger.info(f"Telegram: Found existing user for chat_id={chat_id}")
            return user

        # Create new user
        now = datetime.now(timezone.utc)
        new_user = DBTelegramUser(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            username=user_info.get('username') if user_info else None,
            first_name=user_info.get('first_name') if user_info else None,
            last_name=user_info.get('last_name') if user_info else None,
            created_at=now,
            last_message_at=now
        )
        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)

        logger.info(f"Telegram: Created new user for chat_id={chat_id}")
        return new_user

    async def _get_telegram_user(self, chat_id: int) -> Optional[DBTelegramUser]:
        """
        Get Telegram user by chat_id.

        Args:
            chat_id: Telegram chat ID

        Returns:
            DBTelegramUser if found, None otherwise
        """
        stmt = select(DBTelegramUser).where(DBTelegramUser.chat_id == chat_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _update_telegram_user_conversation(
        self,
        chat_id: int,
        conversation_id: str
    ) -> None:
        """
        Update the conversation_id for a Telegram user.

        Args:
            chat_id: Telegram chat ID
            conversation_id: New conversation ID to link
        """
        stmt = (
            update(DBTelegramUser)
            .where(DBTelegramUser.chat_id == chat_id)
            .values(
                conversation_id=conversation_id,
                last_message_at=datetime.now(timezone.utc)
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()
        logger.info(f"Telegram: Updated user chat_id={chat_id} conversation to {conversation_id}")

    async def _is_conversation_expired(self, conversation: DBConversation) -> bool:
        """
        Check if a conversation has expired (no activity for 24+ hours).

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
                f"Telegram: Conversation {conversation.id} expired "
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
        logger.info(f"Telegram: Archived expired conversation {conversation_id}")

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
        logger.info(f"Telegram: Created new collection '{name}' with ID {new_collection.id}")
        return new_collection

    async def _update_user_default_collection(
        self,
        chat_id: int,
        collection_id: Optional[str]
    ) -> None:
        """
        Update the default collection for a Telegram user.

        Args:
            chat_id: Telegram chat ID
            collection_id: Collection ID to set as default (or None to clear)
        """
        stmt = (
            update(DBTelegramUser)
            .where(DBTelegramUser.chat_id == chat_id)
            .values(
                default_collection_id=collection_id,
                last_message_at=datetime.now(timezone.utc)
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()
        logger.info(f"Telegram: Updated user chat_id={chat_id} default collection to {collection_id}")

    async def handle_list_collections(self, chat_id: int) -> Dict[str, Any]:
        """
        Handle the /collezioni command - list all available collections.

        Args:
            chat_id: Telegram chat ID

        Returns:
            Response dict for the command
        """
        try:
            collections = await self._get_all_collections()

            if not collections:
                response = COLLECTIONS_LIST_EMPTY
            else:
                # Build the collections list
                lines = [COLLECTIONS_LIST_HEADER.rstrip()]

                # Get user's current default collection
                user = await self._get_telegram_user(chat_id)
                default_collection_id = user.default_collection_id if user else None

                for i, col in enumerate(collections, 1):
                    is_default = col.id == default_collection_id
                    marker = " [predefinita]" if is_default else ""
                    lines.append(f"{i}. *{col.name}*{marker}")

                if default_collection_id:
                    lines.append("")
                    lines.append("_[predefinita] = collezione predefinita_")

                lines.append("")
                lines.append('_Usa /setcollezione Nome per impostare la collezione predefinita._')

                response = "\n".join(lines)

            logger.info(f"Telegram: Listed {len(collections)} collections for chat_id={chat_id}")

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
            logger.error(f"Telegram: Error listing collections: {e}")
            return {
                "response": "Errore nel recuperare le collezioni. Riprova piu tardi.",
                "conversation_id": None,
                "was_truncated": False,
                "original_length": 0,
                "truncated_length": 0,
                "tool_used": None,
                "response_source": "error",
                "error": str(e)
            }

    async def handle_set_collection(self, chat_id: int, collection_name: Optional[str]) -> Dict[str, Any]:
        """
        Handle the /setcollezione command - set default collection for user.

        Args:
            chat_id: Telegram chat ID
            collection_name: Name of collection to set as default

        Returns:
            Response dict for the command
        """
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
            auto_create = settings_store.get('telegram_auto_create_collections', 'true').lower() == 'true'

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
            await self._update_user_default_collection(chat_id, collection.id)

            # Return success response
            if created_new:
                response = SET_COLLECTION_CREATED.format(collection_name=collection.name)
            else:
                response = SET_COLLECTION_SUCCESS.format(collection_name=collection.name)

            logger.info(f"Telegram: Set default collection for chat_id={chat_id} to '{collection.name}' (ID: {collection.id})")

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
            logger.error(f"Telegram: Error setting collection: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "response": "Errore nell'impostare la collezione. Riprova piu tardi.",
                "conversation_id": None,
                "was_truncated": False,
                "original_length": 0,
                "truncated_length": 0,
                "tool_used": None,
                "response_source": "error",
                "error": str(e)
            }

    async def handle_list_documents(self, chat_id: int, collection_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Handle the /docs command - list user's documents.

        Feature #312: Telegram bot commands

        Args:
            chat_id: Telegram chat ID
            collection_name: Optional collection name to filter by

        Returns:
            Response dict for the command
        """
        try:
            from core.store_postgres import DocumentStorePostgres
            from models.db_models import DBDocument

            document_store = DocumentStorePostgres(self.db)

            # If collection name is provided, find the collection first
            collection_id = None
            collection = None
            if collection_name:
                collection = await self._get_collection_by_name(collection_name)
                if not collection:
                    response = DOCS_LIST_COLLECTION_EMPTY.format(collection_name=collection_name)
                    return {
                        "response": response,
                        "conversation_id": None,
                        "was_truncated": False,
                        "original_length": len(response),
                        "truncated_length": len(response),
                        "tool_used": None,
                        "response_source": "command"
                    }
                collection_id = collection.id

            # Get documents - filter by collection if specified
            if collection_id:
                stmt = select(DBDocument).where(
                    DBDocument.collection_id == collection_id
                ).order_by(DBDocument.created_at.desc()).limit(50)
            else:
                stmt = select(DBDocument).order_by(DBDocument.created_at.desc()).limit(50)

            result = await self.db.execute(stmt)
            documents = list(result.scalars().all())

            if not documents:
                if collection_name:
                    response = DOCS_LIST_COLLECTION_EMPTY.format(collection_name=collection_name)
                else:
                    response = DOCS_LIST_EMPTY
                return {
                    "response": response,
                    "conversation_id": None,
                    "was_truncated": False,
                    "original_length": len(response),
                    "truncated_length": len(response),
                    "tool_used": None,
                    "response_source": "command"
                }

            # Build the documents list
            if collection_name:
                lines = [DOCS_LIST_COLLECTION_HEADER.format(collection_name=collection.name).rstrip()]
            else:
                lines = [DOCS_LIST_HEADER.rstrip()]

            for i, doc in enumerate(documents, 1):
                # Format document type
                doc_type_emoji = "📄" if doc.document_type == "unstructured" else "📊"

                # Format date
                created_str = doc.created_at.strftime("%d/%m/%Y") if doc.created_at else "N/A"

                # Build line with truncated title if needed
                title = doc.title or doc.original_filename or "Documento senza nome"
                if len(title) > 40:
                    title = title[:37] + "..."

                lines.append(f"{i}. {doc_type_emoji} *{title}*")
                lines.append(f"   _{created_str} - {doc.mime_type or 'unknown'}_")

            lines.append("")
            lines.append(f"_Totale: {len(documents)} documenti_")
            lines.append("")
            lines.append("_Usa /elimina NomeDocumento per eliminare un documento._")

            response = "\n".join(lines)

            # Truncate if too long for Telegram
            if len(response) > TELEGRAM_MAX_LENGTH:
                response = self.truncate_response(response)

            logger.info(f"Telegram: Listed {len(documents)} documents for chat_id={chat_id}")

            return {
                "response": response,
                "conversation_id": None,
                "was_truncated": len(response) > TELEGRAM_MAX_LENGTH,
                "original_length": len(response),
                "truncated_length": len(response),
                "tool_used": None,
                "response_source": "command"
            }
        except Exception as e:
            logger.error(f"Telegram: Error listing documents: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "response": "Errore nel recuperare i documenti. Riprova piu tardi.",
                "conversation_id": None,
                "was_truncated": False,
                "original_length": 0,
                "truncated_length": 0,
                "tool_used": None,
                "response_source": "error",
                "error": str(e)
            }

    async def handle_delete_document(self, chat_id: int, doc_name: Optional[str]) -> Dict[str, Any]:
        """
        Handle the /elimina command - delete a user's document.

        Feature #312: Telegram bot commands

        Args:
            chat_id: Telegram chat ID
            doc_name: Name of document to delete

        Returns:
            Response dict for the command
        """
        # Check for missing argument
        if not doc_name:
            return {
                "response": DELETE_DOC_USAGE,
                "conversation_id": None,
                "was_truncated": False,
                "original_length": len(DELETE_DOC_USAGE),
                "truncated_length": len(DELETE_DOC_USAGE),
                "tool_used": None,
                "response_source": "command"
            }

        try:
            from core.store_postgres import DocumentStorePostgres
            from models.db_models import DBDocument
            from core.store import embedding_store

            document_store = DocumentStorePostgres(self.db)

            # Search for document by title (case-insensitive, partial match)
            stmt = select(DBDocument).where(
                DBDocument.title.ilike(f"%{doc_name}%")
            ).order_by(DBDocument.created_at.desc()).limit(5)

            result = await self.db.execute(stmt)
            matching_docs = list(result.scalars().all())

            if not matching_docs:
                # Also try matching by original filename
                stmt = select(DBDocument).where(
                    DBDocument.original_filename.ilike(f"%{doc_name}%")
                ).order_by(DBDocument.created_at.desc()).limit(5)
                result = await self.db.execute(stmt)
                matching_docs = list(result.scalars().all())

            if not matching_docs:
                response = DELETE_DOC_NOT_FOUND.format(doc_name=doc_name)
                return {
                    "response": response,
                    "conversation_id": None,
                    "was_truncated": False,
                    "original_length": len(response),
                    "truncated_length": len(response),
                    "tool_used": None,
                    "response_source": "command"
                }

            # If multiple matches, return a disambiguation message
            if len(matching_docs) > 1:
                lines = ["*Documenti trovati con questo nome:*", ""]
                for i, doc in enumerate(matching_docs, 1):
                    title = doc.title or doc.original_filename or "Documento senza nome"
                    created_str = doc.created_at.strftime("%d/%m/%Y %H:%M") if doc.created_at else "N/A"
                    lines.append(f"{i}. *{title}*")
                    lines.append(f"   _{created_str}_")
                lines.append("")
                lines.append("_Specifica il nome completo del documento da eliminare._")
                response = "\n".join(lines)
                return {
                    "response": response,
                    "conversation_id": None,
                    "was_truncated": False,
                    "original_length": len(response),
                    "truncated_length": len(response),
                    "tool_used": None,
                    "response_source": "command"
                }

            # Single match - delete the document
            doc_to_delete = matching_docs[0]
            doc_title = doc_to_delete.title or doc_to_delete.original_filename
            doc_id = doc_to_delete.id

            # Delete embeddings first
            try:
                embedding_store.delete_by_document(doc_id)
                logger.info(f"Telegram: Deleted embeddings for document {doc_id}")
            except Exception as e:
                logger.warning(f"Telegram: Error deleting embeddings for document {doc_id}: {e}")

            # Delete the document record
            await document_store.delete(doc_id)
            await self.db.commit()

            logger.info(f"Telegram: Deleted document '{doc_title}' (ID: {doc_id}) for chat_id={chat_id}")

            response = DELETE_DOC_SUCCESS.format(doc_title=doc_title)
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
            logger.error(f"Telegram: Error deleting document: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "response": "Errore nell'eliminare il documento. Riprova piu tardi.",
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
        chat_id: int,
        force_new: bool = False
    ) -> ConversationInDB:
        """
        Get existing conversation for chat_id or create a new one.

        Telegram conversations are identified by a title format:
        "Telegram: 123456789"

        If the existing conversation is expired (>24h of inactivity),
        it will be archived and a new one created.

        Args:
            chat_id: Telegram chat ID
            force_new: If True, always create a new conversation (for reset command)

        Returns:
            ConversationInDB object (existing or newly created)
        """
        expected_title = self._create_conversation_title(chat_id)

        # First, check if user has a linked conversation
        user = await self._get_telegram_user(chat_id)

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
                    logger.info(f"Telegram: Archived expired conversation {existing_conversation.id}")
                else:
                    # Valid, active conversation found
                    logger.info(f"Telegram: Found active conversation for chat_id={chat_id}: {existing_conversation.id}")
                    return ConversationInDB(
                        id=existing_conversation.id,
                        title=existing_conversation.title,
                        is_archived=existing_conversation.is_archived,
                        created_at=existing_conversation.created_at,
                        updated_at=existing_conversation.updated_at,
                    )

        # Look for existing non-archived conversation with this chat_id title (fallback)
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
                    logger.info(f"Telegram: Found existing conversation for chat_id={chat_id}: {existing_conversation.id}")

                    # Update user link if user exists
                    if user:
                        await self._update_telegram_user_conversation(chat_id, existing_conversation.id)

                    return ConversationInDB(
                        id=existing_conversation.id,
                        title=existing_conversation.title,
                        is_archived=existing_conversation.is_archived,
                        created_at=existing_conversation.created_at,
                        updated_at=existing_conversation.updated_at,
                    )

        # Create new conversation for this chat_id
        # For forced new (reset), add timestamp to make title unique
        if force_new:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            new_title = f"{expected_title} ({timestamp})"
        else:
            new_title = expected_title

        conversation_data = ConversationCreate(title=new_title)
        new_conversation = await self.conversation_store.create(conversation_data)
        logger.info(f"Telegram: Created new conversation for chat_id={chat_id}: {new_conversation.id}")

        # Update user link if user exists
        if user:
            await self._update_telegram_user_conversation(chat_id, new_conversation.id)

        return new_conversation

    async def reset_conversation(self, chat_id: int) -> ConversationInDB:
        """
        Reset conversation for a chat_id - archives old and creates new.

        Args:
            chat_id: Telegram chat ID

        Returns:
            New ConversationInDB object
        """
        logger.info(f"Telegram: Resetting conversation for chat_id={chat_id}")

        # Archive current conversation if exists
        user = await self._get_telegram_user(chat_id)
        if user and user.conversation_id:
            await self._archive_conversation(user.conversation_id)

        # Create new conversation
        return await self.get_or_create_conversation(chat_id, force_new=True)

    def truncate_response(self, response: str) -> str:
        """
        Truncate response to fit Telegram's 4096 character limit.

        If response exceeds 4096 characters, truncates and adds
        "... [continua]" suffix.

        Args:
            response: Original AI response text

        Returns:
            Truncated response (max 4096 chars including suffix)
        """
        if len(response) <= TELEGRAM_MAX_LENGTH:
            return response

        # Calculate max content length accounting for suffix
        max_content = TELEGRAM_MAX_LENGTH - len(TELEGRAM_TRUNCATION_SUFFIX)

        # Truncate at word boundary if possible
        truncated = response[:max_content]

        # Try to find a good break point (space or newline)
        last_space = truncated.rfind(' ')
        last_newline = truncated.rfind('\n')
        break_point = max(last_space, last_newline)

        if break_point > max_content * 0.7:  # Only use break point if it's not too far back
            truncated = truncated[:break_point]

        truncated = truncated.rstrip() + TELEGRAM_TRUNCATION_SUFFIX

        logger.info(f"Telegram: Truncated response from {len(response)} to {len(truncated)} chars")

        return truncated

    async def process_message(
        self,
        chat_id: int,
        text: str,
        user_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process an incoming Telegram message through the RAG pipeline.

        This method:
        1. Gets or creates user (to track conversation link)
        2. Checks for special commands (reset, help)
        3. Gets or creates a conversation for the chat_id
        4. Checks for conversation expiry (24h)
        5. Saves the user message
        6. Retrieves conversation history for context
        7. Calls the AI service (non-streaming)
        8. Truncates the response for Telegram if needed
        9. Saves the assistant response

        Special commands:
        - /start: Welcome message
        - /reset, 'nuova chat': Start a fresh conversation
        - /help, 'aiuto': Show available commands

        Args:
            chat_id: Sender's Telegram chat ID
            text: Text content of the message
            user_info: Optional user info from Telegram

        Returns:
            Dict with:
                - response: The AI response text (truncated if needed)
                - conversation_id: ID of the conversation
                - was_truncated: Whether response was truncated
                - tool_used: Tool used by AI (if any)
                - response_source: Source of response (rag/direct/hybrid)
        """
        logger.info("=" * 60)
        logger.info("TELEGRAM MESSAGE PROCESSING")
        logger.info("=" * 60)
        logger.info(f"  Chat ID: {chat_id}")
        logger.info(f"  Message: {text[:100]}{'...' if len(text) > 100 else ''}")
        logger.info(f"  User: {user_info}")

        try:
            # Step 0A: Get or create user
            user = await self.get_or_create_user(chat_id, user_info)

            # Step 0B: Check for special commands
            is_command, command_type, command_arg = self._is_command(text)

            if is_command:
                logger.info(f"Telegram: Detected command: {command_type} (arg: {command_arg})")

                if command_type == 'start':
                    # Return start/welcome message
                    logger.info("Telegram: Returning start message")
                    return {
                        "response": START_MESSAGE,
                        "conversation_id": None,
                        "was_truncated": False,
                        "original_length": len(START_MESSAGE),
                        "truncated_length": len(START_MESSAGE),
                        "tool_used": None,
                        "response_source": "command"
                    }

                elif command_type == 'help':
                    # Return help message without processing through RAG
                    logger.info("Telegram: Returning help message")
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
                    conversation = await self.reset_conversation(chat_id)
                    logger.info(f"Telegram: Conversation reset, new ID: {conversation.id}")
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
                    logger.info("Telegram: Listing collections")
                    return await self.handle_list_collections(chat_id)

                elif command_type == 'set_collection':
                    # Set default collection
                    logger.info(f"Telegram: Setting collection to '{command_arg}'")
                    return await self.handle_set_collection(chat_id, command_arg)

                elif command_type == 'list_docs':
                    # List user's documents (optionally filtered by collection)
                    logger.info(f"Telegram: Listing documents (collection: '{command_arg}')")
                    return await self.handle_list_documents(chat_id, command_arg)

                elif command_type == 'delete_doc':
                    # Delete a document
                    logger.info(f"Telegram: Deleting document '{command_arg}'")
                    return await self.handle_delete_document(chat_id, command_arg)

            # Feature #319: Security analysis of user input
            security_service = get_security_service()
            security_analysis = security_service.analyze_query(text, user_id=f"telegram_{chat_id}")

            # Check if user is blocked due to excessive suspicious queries
            if security_analysis.get("is_blocked"):
                block_msg = security_analysis.get("message", "Troppe richieste sospette. Riprova più tardi.")
                logger.warning(f"[Feature #319] Telegram: Blocked request from chat_id {chat_id}")
                return {
                    "response": f"⚠️ {block_msg}",
                    "conversation_id": None,
                    "was_truncated": False,
                    "original_length": len(block_msg),
                    "truncated_length": len(block_msg),
                    "tool_used": None,
                    "response_source": "security_blocked"
                }

            # Log suspicious queries (but don't block unless rate limited)
            if security_analysis.get("is_suspicious"):
                logger.warning(
                    f"[Feature #319] Telegram: Suspicious query from {chat_id}: "
                    f"risk_score={security_analysis.get('risk_score', 0):.2f}"
                )

            # Step 1: Get or create conversation for this chat_id
            # This also handles auto-expiry of conversations older than 24h
            conversation = await self.get_or_create_conversation(chat_id)
            conversation_id = conversation.id

            # Step 2: Save user message
            user_message_data = MessageCreate(
                conversation_id=conversation_id,
                role="user",
                content=text,
                tool_used=None,
                tool_details=None,
                response_source=None
            )
            await self.message_store.create(user_message_data)
            logger.info(f"Telegram: Saved user message to conversation {conversation_id}")

            # Step 3: Get conversation history for context
            conversation_messages = await self.message_store.get_by_conversation(conversation_id)

            # Get context window size from settings
            context_window_size = int(settings_store.get('context_window_size', DEFAULT_CONTEXT_WINDOW_SIZE))

            # Limit to last N messages for context
            if len(conversation_messages) > context_window_size:
                conversation_messages = conversation_messages[-context_window_size:]
                logger.info(f"Telegram: Limited context to last {context_window_size} messages")

            # Prepare messages for AI
            ai_messages = [
                {"role": msg.role, "content": msg.content}
                for msg in conversation_messages
            ]

            # Apply token limit truncation
            ai_messages = truncate_messages_to_token_limit(ai_messages)

            # Step 4: Get AI response (non-streaming)
            logger.info(f"Telegram: Calling AI service for conversation {conversation_id}")
            ai_response = await self.ai_service.chat(ai_messages, conversation_id)

            original_response = ai_response.get("content", "")
            tool_used = ai_response.get("tool_used")
            tool_details = ai_response.get("tool_details")
            response_source = ai_response.get("response_source")

            logger.info(f"Telegram: AI response length: {len(original_response)} chars")
            logger.info(f"Telegram: Tool used: {tool_used}, Source: {response_source}")

            # Step 5: Truncate response for Telegram if needed
            was_truncated = len(original_response) > TELEGRAM_MAX_LENGTH
            final_response = self.truncate_response(original_response)

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
            logger.info(f"Telegram: Saved assistant response to conversation {conversation_id}")

            # Update conversation timestamp
            await self.conversation_store.update(
                conversation_id,
                ConversationUpdate(title=conversation.title)  # Just to update updated_at
            )

            logger.info("=" * 60)
            logger.info("TELEGRAM MESSAGE PROCESSING COMPLETE")
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
            logger.error(f"Telegram: Error processing message: {e}")
            import traceback
            logger.error(traceback.format_exc())

            # Return error response
            error_response = "Mi dispiace, si e verificato un errore nell'elaborazione del messaggio. Riprova piu tardi."

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
        chat_id: int,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get conversation history for a chat_id.

        Args:
            chat_id: Telegram chat ID
            limit: Maximum number of messages to return

        Returns:
            List of message dictionaries with role, content, and created_at
        """
        expected_title = self._create_conversation_title(chat_id)

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


    # =========================================================================
    # Document Upload Handling (Feature #311)
    # =========================================================================

    async def handle_document_upload(
        self,
        chat_id: int,
        file_id: str,
        file_name: Optional[str],
        mime_type: Optional[str],
        file_size: Optional[int],
        caption: Optional[str],
        user_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Handle document upload from Telegram.

        Feature #311: Telegram document upload handling

        Downloads the file from Telegram servers and processes it through
        the existing document ingestion pipeline.

        Supported formats: PDF, TXT, DOCX, CSV, Excel, JSON, Markdown

        Args:
            chat_id: Telegram chat ID
            file_id: Telegram file_id for downloading
            file_name: Original filename from Telegram
            mime_type: MIME type of the file
            file_size: File size in bytes
            caption: Optional caption sent with the document
            user_info: Optional user info dict from Telegram

        Returns:
            Dict with upload result:
                - success: Whether upload succeeded
                - document_id: ID of created document (if successful)
                - document_name: Name given to document
                - chunk_count: Number of chunks created (for unstructured docs)
                - error: Error message (if failed)
                - error_type: Type of error for user-friendly messages
        """
        logger.info("=" * 60)
        logger.info("TELEGRAM DOCUMENT UPLOAD")
        logger.info("=" * 60)
        logger.info(f"  Chat ID: {chat_id}")
        logger.info(f"  File ID: {file_id}")
        logger.info(f"  File name: {file_name}")
        logger.info(f"  MIME type: {mime_type}")
        logger.info(f"  File size: {file_size}")
        logger.info(f"  Caption: {caption}")

        # Feature #332: Initialize progress reporter for feedback
        progress_reporter = TelegramProgressReporter(chat_id)

        try:
            # Feature #332: Send immediate "document received" message
            await progress_reporter.document_received(file_name or "documento")

            # Get or create user to access default_collection_id
            user = await self.get_or_create_user(chat_id, user_info)
            default_collection_id = user.default_collection_id

            if default_collection_id:
                collection = await self._get_collection_by_id(default_collection_id)
                collection_name = collection.name if collection else "Sconosciuta"
                logger.info(f"  Default collection: {collection_name} ({default_collection_id})")
            else:
                collection_name = "Uncategorized"
                logger.info("  No default collection set (using Uncategorized)")

            # Validate file type
            allowed_extensions = {'.pdf', '.txt', '.csv', '.xlsx', '.xls', '.docx', '.json', '.md'}
            file_ext = ''
            if file_name:
                from pathlib import Path
                file_ext = Path(file_name).suffix.lower()

            # Determine if file type is supported
            is_supported = file_ext in allowed_extensions if file_ext else False

            # Also check MIME type
            allowed_mime_types = {
                'application/pdf',
                'text/plain',
                'text/csv',
                'application/csv',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'application/vnd.ms-excel',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/json',
                'text/markdown',
                'text/x-markdown',
            }

            if mime_type and mime_type.lower() in allowed_mime_types:
                is_supported = True

            if not is_supported:
                error_msg = (
                    f"*Tipo di file non supportato*\n\n"
                    f"Il file `{file_name or 'senza nome'}` non e un formato supportato.\n\n"
                    f"*Formati supportati:*\n"
                    f"- PDF (.pdf)\n"
                    f"- Testo (.txt)\n"
                    f"- Word (.docx)\n"
                    f"- Markdown (.md)\n"
                    f"- CSV (.csv)\n"
                    f"- Excel (.xlsx, .xls)\n"
                    f"- JSON (.json)"
                )
                logger.warning(f"Telegram: Unsupported file type: ext={file_ext}, mime={mime_type}")
                return {
                    'success': False,
                    'error': error_msg,
                    'error_type': 'unsupported_format'
                }

            # Check file size (max 100MB, same as web upload)
            max_file_size = 100 * 1024 * 1024  # 100MB
            if file_size and file_size > max_file_size:
                error_msg = (
                    f"*File troppo grande*\n\n"
                    f"Il file `{file_name}` e troppo grande ({file_size / (1024*1024):.1f} MB).\n\n"
                    f"*Limite massimo:* 100 MB"
                )
                logger.warning(f"Telegram: File too large: {file_size} bytes")
                return {
                    'success': False,
                    'error': error_msg,
                    'error_type': 'file_too_large'
                }

            # Step 1: Get file path from Telegram API
            logger.info("Step 1: Getting file path from Telegram API...")
            file_path = await self._get_telegram_file_path(file_id)

            if not file_path:
                error_msg = (
                    "*Errore download*\n\n"
                    "Impossibile ottenere il percorso del file dai server Telegram.\n\n"
                    "Riprova tra qualche minuto."
                )
                return {
                    'success': False,
                    'error': error_msg,
                    'error_type': 'telegram_api_error'
                }

            # Step 2: Download file from Telegram servers
            logger.info(f"Step 2: Downloading file from Telegram... (path: {file_path})")
            file_content = await self._download_telegram_file(file_path)

            if not file_content:
                error_msg = (
                    "*Errore download*\n\n"
                    "Impossibile scaricare il file dai server Telegram.\n\n"
                    "Riprova tra qualche minuto."
                )
                return {
                    'success': False,
                    'error': error_msg,
                    'error_type': 'download_error'
                }

            logger.info(f"  Downloaded {len(file_content)} bytes")

            # Step 3: Save file to backend/uploads/ with unique filename
            logger.info("Step 3: Saving file to uploads directory...")
            import uuid
            from pathlib import Path

            UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

            unique_id = str(uuid.uuid4())
            # Preserve original extension
            if file_name:
                original_ext = Path(file_name).suffix.lower()
            else:
                # Guess extension from MIME type
                mime_to_ext = {
                    'application/pdf': '.pdf',
                    'text/plain': '.txt',
                    'text/csv': '.csv',
                    'application/csv': '.csv',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
                    'application/vnd.ms-excel': '.xls',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
                    'application/json': '.json',
                    'text/markdown': '.md',
                    'text/x-markdown': '.md',
                }
                original_ext = mime_to_ext.get(mime_type, '.bin')

            saved_filename = f"{unique_id}{original_ext}"
            saved_path = UPLOAD_DIR / saved_filename

            # Write file content
            with open(saved_path, 'wb') as f:
                f.write(file_content)

            logger.info(f"  Saved to: {saved_path}")

            # Step 4: Process document through existing pipeline
            logger.info("Step 4: Processing document...")

            # Use caption as title, or filename, or generate one
            doc_title = caption or file_name or f"Telegram_{unique_id[:8]}"

            result = await self._process_telegram_document(
                file_path=saved_path,
                file_content=file_content,
                file_name=file_name or saved_filename,
                mime_type=mime_type or 'application/octet-stream',
                doc_title=doc_title,
                collection_id=default_collection_id,
                chat_id=chat_id,
                progress_reporter=progress_reporter  # Feature #332: Pass progress reporter
            )

            if not result.get('success'):
                return result

            logger.info("=" * 60)
            logger.info("TELEGRAM DOCUMENT UPLOAD COMPLETE")
            logger.info(f"  Document ID: {result.get('document_id')}")
            logger.info(f"  Chunks: {result.get('chunk_count', 0)}")
            logger.info("=" * 60)

            return result

        except Exception as e:
            logger.error(f"Telegram document upload error: {e}")
            import traceback
            logger.error(traceback.format_exc())

            error_msg = (
                "*Errore durante l'elaborazione*\n\n"
                "Si e verificato un errore durante l'elaborazione del documento.\n\n"
                "Riprova piu tardi o contatta l'assistenza se il problema persiste."
            )
            return {
                'success': False,
                'error': error_msg,
                'error_type': 'processing_error',
                'details': str(e)
            }

    async def _get_telegram_file_path(self, file_id: str) -> Optional[str]:
        """
        Get the file path from Telegram API using getFile method.

        Args:
            file_id: Telegram file_id

        Returns:
            file_path string from Telegram, or None on error
        """
        import httpx
        from core.store import settings_store

        bot_token = settings_store.get('telegram_bot_token', '')
        if not bot_token:
            logger.error("Telegram bot token not configured")
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"https://api.telegram.org/bot{bot_token}/getFile"
                response = await client.post(url, json={"file_id": file_id})

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        return data.get("result", {}).get("file_path")
                    else:
                        logger.error(f"Telegram getFile error: {data.get('description')}")
                else:
                    logger.error(f"Telegram getFile HTTP error: {response.status_code}")

        except Exception as e:
            logger.error(f"Error getting Telegram file path: {e}")

        return None

    async def _download_telegram_file(self, file_path: str) -> Optional[bytes]:
        """
        Download a file from Telegram servers.

        Args:
            file_path: The file_path from getFile API response

        Returns:
            File content as bytes, or None on error
        """
        import httpx
        from core.store import settings_store

        bot_token = settings_store.get('telegram_bot_token', '')
        if not bot_token:
            logger.error("Telegram bot token not configured")
            return None

        try:
            # Telegram file download URL format:
            # https://api.telegram.org/file/bot<token>/<file_path>
            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(download_url)

                if response.status_code == 200:
                    return response.content
                else:
                    logger.error(f"Telegram file download HTTP error: {response.status_code}")

        except Exception as e:
            logger.error(f"Error downloading Telegram file: {e}")

        return None

    async def _process_telegram_document(
        self,
        file_path,
        file_content: bytes,
        file_name: str,
        mime_type: str,
        doc_title: str,
        collection_id: Optional[str],
        chat_id: int,
        progress_reporter: Optional[TelegramProgressReporter] = None  # Feature #332
    ) -> Dict[str, Any]:
        """
        Process a document through the ingestion pipeline.

        This method replicates the logic from the document upload API endpoint
        but adapted for programmatic use from Telegram.

        Feature #332: Now includes progress_reporter for sending feedback to users.

        Args:
            file_path: Path where file is saved
            file_content: File content bytes
            file_name: Original filename
            mime_type: MIME type
            doc_title: Title to give the document
            collection_id: Collection to add document to
            chat_id: Telegram chat ID for logging
            progress_reporter: Optional TelegramProgressReporter for sending progress updates

        Returns:
            Dict with processing result
        """
        import hashlib
        import json
        from pathlib import Path
        from core.store import embedding_store, settings_store
        from core.store_postgres import DocumentStorePostgres, DocumentRowsStorePostgres
        from models.document import DocumentCreate, DocumentUpdate
        from models import (
            DOCUMENT_STATUS_READY,
            DOCUMENT_STATUS_EMBEDDING_FAILED
        )

        try:
            # Normalize MIME type
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

            # Also detect by file extension if needed
            ext = Path(file_name).suffix.lower()
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
            if mime_type in mime_type_map:
                mime_type = mime_type_map[mime_type]
            elif ext in ext_to_mime:
                mime_type = ext_to_mime[ext]

            # Compute content hash
            content_hash = hashlib.sha256(file_content).hexdigest()
            file_size = len(file_content)

            # Initialize stores
            document_store = DocumentStorePostgres(self.db)
            document_rows_store = DocumentRowsStorePostgres(self.db)

            # Check for duplicate content in the same collection
            existing_doc = await document_store.find_by_content_hash(content_hash, collection_id)
            if existing_doc:
                error_msg = (
                    "*Documento duplicato*\n\n"
                    f"Un documento con lo stesso contenuto esiste gia:\n"
                    f"*{existing_doc.title}*\n\n"
                    f"Caricato il: {existing_doc.created_at.strftime('%d/%m/%Y %H:%M')}"
                )
                logger.warning(f"Telegram: Duplicate document detected for chat_id={chat_id}")
                return {
                    'success': False,
                    'error': error_msg,
                    'error_type': 'duplicate'
                }

            # Determine document type
            structured_types = [
                "text/csv",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel",
                "application/json"
            ]
            doc_type = "structured" if mime_type in structured_types else "unstructured"

            # Feature #332: Send processing started message
            if progress_reporter:
                await progress_reporter.processing_started(doc_type)

            # Create document record
            doc_create = DocumentCreate(
                title=doc_title,
                comment=f"Caricato via Telegram (chat_id: {chat_id})",
                original_filename=file_name,
                mime_type=mime_type,
                file_size=file_size,
                document_type=doc_type,
                collection_id=collection_id,
                content_hash=content_hash,
                url=str(file_path),
                file_path=str(file_path)
            )

            document = await document_store.create(doc_create)
            await self.db.commit()
            logger.info(f"Telegram: Created document record: {document.id}")

            chunk_count = 0
            row_count = 0

            # Process based on document type
            if doc_type == "structured":
                # Parse structured data
                from api.documents import parse_structured_data
                rows, schema = parse_structured_data(file_path, mime_type)

                if rows:
                    await document_rows_store.add_rows(document.id, rows, schema)
                    row_count = len(rows)
                    schema_json = json.dumps(schema)
                    update_data = DocumentUpdate(schema_info=schema_json, status=DOCUMENT_STATUS_READY)
                    await document_store.update(document.id, update_data)
                    await self.db.commit()
                    logger.info(f"Telegram: Stored {row_count} rows for structured document")
                else:
                    update_data = DocumentUpdate(status=DOCUMENT_STATUS_READY)
                    await document_store.update(document.id, update_data)
                    await self.db.commit()

                # Build success message for structured doc
                collection_info = f"nella collezione *{(await self._get_collection_by_id(collection_id)).name}*" if collection_id else "in *Uncategorized*"
                success_msg = (
                    f"*Documento caricato!*\n\n"
                    f"*{doc_title}*\n\n"
                    f"Tipo: Tabellare ({ext[1:].upper() if ext else 'dati'})\n"
                    f"Righe: {row_count}\n"
                    f"Colonne: {len(schema) if schema else 0}\n\n"
                    f"Salvato {collection_info}.\n\n"
                    f"_Usa domande come \"qual e il totale delle vendite?\" per interrogare i dati._"
                )

                return {
                    'success': True,
                    'document_id': document.id,
                    'document_name': doc_title,
                    'document_type': 'structured',
                    'row_count': row_count,
                    'chunk_count': 0,
                    'response': success_msg
                }

            else:
                # Process unstructured data - extract text and generate embeddings
                # Feature #335: Use generate_embeddings_for_reembed with correct signature
                # Feature #337: Use processing semaphore to prevent concurrent blocking
                from pathlib import Path
                from api.documents import generate_embeddings_for_reembed, extract_text_from_file
                from services.document_queue import acquire_processing_slot, release_processing_slot

                # First check if document has extractable text
                text_content = extract_text_from_file(file_path, mime_type)

                if not text_content or len(text_content.strip()) < 10:
                    error_msg = (
                        "*Documento vuoto*\n\n"
                        "Non e stato possibile estrarre testo dal documento.\n\n"
                        "Il file potrebbe essere vuoto o in un formato non leggibile."
                    )
                    # Still keep the document but mark status
                    update_data = DocumentUpdate(status=DOCUMENT_STATUS_EMBEDDING_FAILED)
                    await document_store.update(document.id, update_data)
                    await self.db.commit()

                    return {
                        'success': False,
                        'document_id': document.id,
                        'error': error_msg,
                        'error_type': 'empty_document'
                    }

                # Generate embeddings using semantic chunking
                logger.info(f"Telegram: Generating chunks and embeddings for {document.id}")

                # Feature #337: Acquire processing slot before starting embedding generation
                # This ensures only one document is processed at a time, preventing
                # multiple Agentic Splitter operations from overwhelming the backend
                slot_acquired = False
                try:
                    logger.info(f"[Feature #337] Telegram: Waiting for processing slot...")
                    slot_acquired = await acquire_processing_slot(timeout=600.0)  # 10 minute timeout
                    if not slot_acquired:
                        logger.warning(f"[Feature #337] Telegram: Could not acquire processing slot for {document.id}")
                        # Update document status to indicate queue timeout
                        update_data = DocumentUpdate(status=DOCUMENT_STATUS_EMBEDDING_FAILED)
                        await document_store.update(document.id, update_data)
                        await self.db.commit()

                        error_msg = (
                            "*Documento in coda*\n\n"
                            f"*{doc_title}*\n\n"
                            "Il sistema sta elaborando altri documenti.\n\n"
                            "Il tuo documento e stato salvato e verra elaborato automaticamente.\n"
                            "_Puoi rigenerare gli embedding dall'interfaccia web._"
                        )
                        return {
                            'success': True,
                            'document_id': document.id,
                            'document_name': doc_title,
                            'document_type': 'unstructured',
                            'chunk_count': 0,
                            'response': error_msg,
                            'warning': 'queue_timeout'
                        }

                    logger.info(f"[Feature #337] Telegram: Acquired processing slot for {document.id}")

                    # Feature #335: Call generate_embeddings_for_reembed with correct parameters
                    # This function handles chunking, embedding generation, and returns chunk_data
                    chunk_data, warning_msg, embedding_model_used = await generate_embeddings_for_reembed(
                        document_id=str(document.id),
                        file_path=Path(file_path),
                        mime_type=mime_type,
                        document_title=doc_title
                    )

                    chunk_count = len(chunk_data) if chunk_data else 0
                    logger.info(f"Telegram: Generated {chunk_count} chunks with embeddings")

                    # Feature #332: Send chunking progress update
                    if progress_reporter and chunk_count > 0:
                        await progress_reporter.chunking_progress(chunk_count)
                        await progress_reporter.embedding_started(chunk_count)

                    if chunk_data:
                        # Feature #336: Use add_chunks() - correct method for PostgreSQLEmbeddingStore
                        # Prepare chunks with properly merged metadata
                        chunks_to_store = []
                        for chunk_item in chunk_data:
                            chunks_to_store.append({
                                'text': chunk_item['text'],
                                'embedding': chunk_item['embedding'],
                                'metadata': {
                                    'document_id': str(document.id),
                                    'document_title': doc_title,
                                    'chunk_index': chunk_item.get('metadata', {}).get('chunk_index', 0),
                                    'source': 'telegram_upload',
                                    **{k: v for k, v in chunk_item.get('metadata', {}).items()
                                       if k not in ['document_id', 'document_title', 'chunk_index', 'source']}
                                }
                            })

                        stored_count = embedding_store.add_chunks(str(document.id), chunks_to_store)
                        logger.info(f"Telegram: Stored {stored_count} embeddings for document {document.id}")

                    # Update document status to ready
                    update_data = DocumentUpdate(status=DOCUMENT_STATUS_READY)
                    await document_store.update(document.id, update_data)
                    await self.db.commit()

                except Exception as e:
                    logger.error(f"Telegram: Error generating embeddings: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

                    # Mark as embedding failed but keep document
                    update_data = DocumentUpdate(status=DOCUMENT_STATUS_EMBEDDING_FAILED)
                    await document_store.update(document.id, update_data)
                    await self.db.commit()

                    error_msg = (
                        "*Documento caricato con avviso*\n\n"
                        f"*{doc_title}*\n\n"
                        "Il documento e stato salvato ma la generazione degli embedding e fallita.\n\n"
                        "_Puoi rigenerare gli embedding dall'interfaccia web._"
                    )

                    # Feature #332: Send error progress message
                    if progress_reporter:
                        await progress_reporter.processing_error(
                            "Embedding falliti. Documento salvato ma non indicizzato."
                        )

                    return {
                        'success': True,
                        'document_id': document.id,
                        'document_name': doc_title,
                        'document_type': 'unstructured',
                        'chunk_count': 0,
                        'response': error_msg,
                        'warning': 'embedding_failed'
                    }

                finally:
                    # Feature #337: Always release the processing slot
                    if slot_acquired:
                        release_processing_slot()
                        logger.info(f"[Feature #337] Telegram: Released processing slot for {document.id}")

                # Build success message for unstructured doc
                collection_info = ""
                if collection_id:
                    collection = await self._get_collection_by_id(collection_id)
                    collection_info = f"nella collezione *{collection.name}*" if collection else "in *Uncategorized*"
                else:
                    collection_info = "in *Uncategorized*"

                success_msg = (
                    f"*Documento caricato!*\n\n"
                    f"*{doc_title}*\n\n"
                    f"Tipo: Testuale ({ext[1:].upper() if ext else 'testo'})\n"
                    f"Chunks: {chunk_count}\n"
                    f"Caratteri: {len(text_content):,}\n\n"
                    f"Salvato {collection_info}.\n\n"
                    f"_Ora puoi fare domande sul contenuto del documento._"
                )

                return {
                    'success': True,
                    'document_id': document.id,
                    'document_name': doc_title,
                    'document_type': 'unstructured',
                    'chunk_count': chunk_count,
                    'response': success_msg
                }

        except Exception as e:
            logger.error(f"Telegram: Error processing document: {e}")
            import traceback
            logger.error(traceback.format_exc())

            # Feature #332: Send error progress message
            if progress_reporter:
                await progress_reporter.processing_error(
                    "Si e verificato un errore durante l'elaborazione.\n\n"
                    "_Riprova piu tardi._"
                )

            return {
                'success': False,
                'error': f"Errore durante l'elaborazione: {str(e)}",
                'error_type': 'processing_error'
            }


# Singleton pattern for convenience
_telegram_service: Optional[TelegramService] = None


async def get_telegram_service(db: AsyncSession) -> TelegramService:
    """Get or create a TelegramService instance."""
    return TelegramService(db)
