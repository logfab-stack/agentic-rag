"""
Models package for Agentic RAG System.
"""

from .document import Document, DocumentCreate, DocumentUpdate, DocumentInDB
from .conversation import (
    Conversation, ConversationCreate, ConversationUpdate, ConversationInDB,
    ConversationWithMessages, Message, MessageCreate, MessageInDB
)
# Import DocumentEmbedding to register it with SQLAlchemy metadata
from .embedding import DocumentEmbedding
# Import UserNote to register it with SQLAlchemy metadata
from .user_note import UserNote
# Import ChunkFeedback to register it with SQLAlchemy metadata
from .chunk_feedback import ChunkFeedback
# Import MessageEmbedding to register it with SQLAlchemy metadata (Feature #161)
from .message_embedding import MessageEmbedding
# Import Note Pydantic models for API
from .note import Note, NoteCreate, NoteUpdate, NoteListResponse
# Import WhatsApp models to register them with SQLAlchemy metadata
from .whatsapp import DBWhatsAppUser, DBWhatsAppMessage
# Import Telegram models to register them with SQLAlchemy metadata (Feature #307)
from .telegram import DBTelegramUser, DBTelegramMessage
# Import AuditEmbeddingDelete model (Feature #252)
from .audit_embedding_delete import AuditEmbeddingDelete
# Feature #261: Import document status constants for type-safe status handling
# Feature #297: Added DOCUMENT_STATUS_VERIFICATION_FAILED
# Feature #330: Added DOCUMENT_STATUS_QUEUED for background processing
from .db_models import (
    DOCUMENT_STATUS_UPLOADING,
    DOCUMENT_STATUS_QUEUED,
    DOCUMENT_STATUS_PROCESSING,
    DOCUMENT_STATUS_READY,
    DOCUMENT_STATUS_EMBEDDING_FAILED,
    DOCUMENT_STATUS_FILE_MISSING,
    DOCUMENT_STATUS_VERIFICATION_FAILED
)

__all__ = [
    "Document", "DocumentCreate", "DocumentUpdate", "DocumentInDB",
    "Conversation", "ConversationCreate", "ConversationUpdate", "ConversationInDB",
    "ConversationWithMessages", "Message", "MessageCreate", "MessageInDB",
    "UserNote", "ChunkFeedback", "MessageEmbedding",
    "Note", "NoteCreate", "NoteUpdate", "NoteListResponse",
    "DBWhatsAppUser", "DBWhatsAppMessage",
    "DBTelegramUser", "DBTelegramMessage",  # Feature #307
    # Feature #261: Document status constants
    "DOCUMENT_STATUS_UPLOADING", "DOCUMENT_STATUS_QUEUED", "DOCUMENT_STATUS_PROCESSING",
    "DOCUMENT_STATUS_READY", "DOCUMENT_STATUS_EMBEDDING_FAILED", "DOCUMENT_STATUS_FILE_MISSING",
    "DOCUMENT_STATUS_VERIFICATION_FAILED"  # Feature #297, #330
]
