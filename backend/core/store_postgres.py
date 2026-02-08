"""
PostgreSQL-backed storage implementations using SQLAlchemy.
These replace the in-memory stores for production persistence.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from sqlalchemy import select, update, delete, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.document import DocumentInDB, DocumentCreate, DocumentUpdate
from models.collection import CollectionInDB, CollectionCreate, CollectionUpdate
from models.conversation import ConversationInDB, ConversationCreate, ConversationUpdate, MessageInDB, MessageCreate
from models.db_models import (
    DBDocument, DBCollection, DBDocumentRow, DBConversation, DBMessage, DBSetting
)

logger = logging.getLogger(__name__)


class DocumentStorePostgres:
    """PostgreSQL-backed document storage."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, doc: DocumentCreate) -> DocumentInDB:
        """Create a new document."""
        db_doc = DBDocument(
            title=doc.title,
            comment=doc.comment,
            original_filename=doc.original_filename,
            mime_type=doc.mime_type,
            file_size=doc.file_size,
            document_type=doc.document_type,
            collection_id=doc.collection_id,
            content_hash=doc.content_hash,
            url=doc.url,
            file_path=doc.file_path,  # Feature #253: Store explicit file path
            schema_info=doc.schema_info,
            status=getattr(doc, 'status', 'processing'),  # Feature #258: Start with processing status
        )

        self.db.add(db_doc)
        await self.db.flush()
        await self.db.refresh(db_doc)

        return self._to_pydantic(db_doc)

    async def find_by_filename(self, filename: str) -> Optional[DocumentInDB]:
        """Find a document by its original filename."""
        stmt = select(DBDocument).where(DBDocument.original_filename == filename)
        result = await self.db.execute(stmt)
        db_doc = result.scalar_one_or_none()
        return self._to_pydantic(db_doc) if db_doc else None

    async def find_by_content_hash(
        self, content_hash: str, collection_id: Optional[str] = None
    ) -> Optional[DocumentInDB]:
        """Find a document by its content hash within a specific collection.

        Feature #262: Per-collection duplicate detection.
        The same document can exist in different collections, but not within the same collection.

        Args:
            content_hash: The hash of the file content
            collection_id: Optional collection ID to search within. If None, searches uncategorized documents.
                          If a special value '__any__' is passed, searches across all collections (legacy behavior).

        Returns:
            The matching document if found, None otherwise.
        """
        if collection_id == '__any__':
            # Legacy behavior: search across all collections
            stmt = select(DBDocument).where(DBDocument.content_hash == content_hash)
        elif collection_id is None:
            # Search only within uncategorized documents (NULL collection_id)
            stmt = select(DBDocument).where(
                DBDocument.content_hash == content_hash,
                DBDocument.collection_id.is_(None)
            )
        else:
            # Search within a specific collection
            stmt = select(DBDocument).where(
                DBDocument.content_hash == content_hash,
                DBDocument.collection_id == collection_id
            )
        result = await self.db.execute(stmt)
        db_doc = result.scalar_one_or_none()
        return self._to_pydantic(db_doc) if db_doc else None

    async def get(self, doc_id: str) -> Optional[DocumentInDB]:
        """Get a document by ID."""
        stmt = select(DBDocument).where(DBDocument.id == doc_id)
        result = await self.db.execute(stmt)
        db_doc = result.scalar_one_or_none()
        return self._to_pydantic(db_doc) if db_doc else None

    async def get_all(self) -> List[DocumentInDB]:
        """Get all documents."""
        stmt = select(DBDocument).order_by(DBDocument.created_at.desc())
        result = await self.db.execute(stmt)
        db_docs = result.scalars().all()
        return [self._to_pydantic(doc) for doc in db_docs]

    async def update(self, doc_id: str, update_data: DocumentUpdate) -> Optional[DocumentInDB]:
        """Update a document. Returns None if not found."""
        stmt = select(DBDocument).where(DBDocument.id == doc_id)
        result = await self.db.execute(stmt)
        db_doc = result.scalar_one_or_none()

        if not db_doc:
            return None

        # Update only provided fields
        update_dict = update_data.model_dump(exclude_unset=True)
        for field, value in update_dict.items():
            if hasattr(db_doc, field):
                setattr(db_doc, field, value)

        db_doc.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(db_doc)

        return self._to_pydantic(db_doc)

    async def delete(self, doc_id: str) -> bool:
        """Delete a document. Returns True if deleted, False if not found."""
        stmt = delete(DBDocument).where(DBDocument.id == doc_id)
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def delete_all(self) -> int:
        """Delete all documents. Returns count of deleted documents."""
        stmt = delete(DBDocument)
        result = await self.db.execute(stmt)
        return result.rowcount

    def _to_pydantic(self, db_doc: DBDocument) -> DocumentInDB:
        """Convert SQLAlchemy model to Pydantic model."""
        return DocumentInDB(
            id=db_doc.id,
            title=db_doc.title,
            comment=db_doc.comment,
            original_filename=db_doc.original_filename,
            mime_type=db_doc.mime_type,
            file_size=db_doc.file_size,
            document_type=db_doc.document_type,
            collection_id=db_doc.collection_id,
            content_hash=db_doc.content_hash,
            schema_info=db_doc.schema_info,
            url=db_doc.url,
            file_path=db_doc.file_path,  # Feature #253: Include explicit file path
            embedding_status=db_doc.embedding_status,  # Feature #251
            file_status=getattr(db_doc, 'file_status', 'ok'),  # Feature #254
            status=getattr(db_doc, 'status', 'ready'),  # Feature #258: Unified status
            chunk_count=getattr(db_doc, 'chunk_count', 0),  # Feature #260
            embedding_model=getattr(db_doc, 'embedding_model', None),  # Feature #259
            created_at=db_doc.created_at,
            updated_at=db_doc.updated_at,
        )


class CollectionStorePostgres:
    """PostgreSQL-backed collection storage."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, collection: CollectionCreate) -> CollectionInDB:
        """Create a new collection."""
        db_collection = DBCollection(
            name=collection.name,
            description=collection.description,
        )

        self.db.add(db_collection)
        await self.db.flush()
        await self.db.refresh(db_collection)

        return self._to_pydantic(db_collection)

    async def get(self, collection_id: str) -> Optional[CollectionInDB]:
        """Get a collection by ID."""
        stmt = select(DBCollection).where(DBCollection.id == collection_id)
        result = await self.db.execute(stmt)
        db_collection = result.scalar_one_or_none()
        return self._to_pydantic(db_collection) if db_collection else None

    async def get_all(self) -> List[CollectionInDB]:
        """Get all collections sorted by name."""
        stmt = select(DBCollection).order_by(DBCollection.name)
        result = await self.db.execute(stmt)
        db_collections = result.scalars().all()
        return [self._to_pydantic(col) for col in db_collections]

    async def update(self, collection_id: str, update_data: CollectionUpdate) -> Optional[CollectionInDB]:
        """Update a collection. Returns None if not found."""
        stmt = select(DBCollection).where(DBCollection.id == collection_id)
        result = await self.db.execute(stmt)
        db_collection = result.scalar_one_or_none()

        if not db_collection:
            return None

        # Update only provided fields
        update_dict = update_data.model_dump(exclude_unset=True)
        for field, value in update_dict.items():
            if hasattr(db_collection, field):
                setattr(db_collection, field, value)

        db_collection.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(db_collection)

        return self._to_pydantic(db_collection)

    async def delete(self, collection_id: str) -> bool:
        """Delete a collection. Returns True if deleted, False if not found."""
        stmt = delete(DBCollection).where(DBCollection.id == collection_id)
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def delete_all(self) -> int:
        """Delete all collections. Returns count of deleted collections."""
        stmt = delete(DBCollection)
        result = await self.db.execute(stmt)
        return result.rowcount

    def _to_pydantic(self, db_collection: DBCollection) -> CollectionInDB:
        """Convert SQLAlchemy model to Pydantic model."""
        return CollectionInDB(
            id=db_collection.id,
            name=db_collection.name,
            description=db_collection.description,
            created_at=db_collection.created_at,
            updated_at=db_collection.updated_at,
        )


class DocumentRowsStorePostgres:
    """PostgreSQL-backed structured document rows storage."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def add_rows(self, dataset_id: str, rows: List[Dict], schema: List[str]) -> int:
        """Add rows for a dataset."""
        db_rows = [
            DBDocumentRow(dataset_id=dataset_id, row_data=row_data)
            for row_data in rows
        ]

        self.db.add_all(db_rows)
        await self.db.flush()

        return len(db_rows)

    async def get_rows(self, dataset_id: str) -> List[Dict]:
        """Get all rows for a dataset."""
        stmt = select(DBDocumentRow).where(DBDocumentRow.dataset_id == dataset_id)
        result = await self.db.execute(stmt)
        db_rows = result.scalars().all()

        return [{"row_id": row.id, "data": row.row_data} for row in db_rows]

    async def get_all_datasets(self) -> Dict[str, int]:
        """Get all dataset IDs and their row counts."""
        stmt = select(
            DBDocumentRow.dataset_id,
            func.count(DBDocumentRow.id).label('count')
        ).group_by(DBDocumentRow.dataset_id)

        result = await self.db.execute(stmt)
        return {row.dataset_id: row.count for row in result}

    async def delete_dataset(self, dataset_id: str) -> bool:
        """Delete all rows for a dataset."""
        stmt = delete(DBDocumentRow).where(DBDocumentRow.dataset_id == dataset_id)
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def get_schema(self, dataset_id: str) -> List[str]:
        """Get column names from first row."""
        stmt = select(DBDocumentRow).where(
            DBDocumentRow.dataset_id == dataset_id
        ).limit(1)

        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()

        if row and row.row_data:
            return list(row.row_data.keys())
        return []

    async def aggregate(self, dataset_id: str, column: str, operation: str) -> Optional[float]:
        """
        Perform aggregation on a column.
        Note: For PostgreSQL JSONB, this requires raw SQL or application-level aggregation.
        """
        rows = await self.get_rows(dataset_id)
        if not rows:
            return None

        values = []
        for row in rows:
            val = row["data"].get(column)
            if val is not None:
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    pass

        if not values:
            return None

        if operation == "sum":
            return sum(values)
        elif operation == "avg":
            return sum(values) / len(values)
        elif operation == "min":
            return min(values)
        elif operation == "max":
            return max(values)
        elif operation == "count":
            return len(values)

        return None


class ConversationStorePostgres:
    """PostgreSQL-backed conversation storage."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, conversation: ConversationCreate) -> ConversationInDB:
        """Create a new conversation."""
        db_conversation = DBConversation(
            title=conversation.title,
        )

        self.db.add(db_conversation)
        await self.db.flush()
        await self.db.refresh(db_conversation)

        return self._to_pydantic(db_conversation)

    async def get(self, conversation_id: str) -> Optional[ConversationInDB]:
        """Get a conversation by ID."""
        stmt = select(DBConversation).where(DBConversation.id == conversation_id)
        result = await self.db.execute(stmt)
        db_conversation = result.scalar_one_or_none()
        return self._to_pydantic(db_conversation) if db_conversation else None

    async def get_all(self) -> List[ConversationInDB]:
        """Get all conversations sorted by updated_at desc."""
        stmt = select(DBConversation).order_by(DBConversation.updated_at.desc())
        result = await self.db.execute(stmt)
        db_conversations = result.scalars().all()
        return [self._to_pydantic(conv) for conv in db_conversations]

    async def update(self, conversation_id: str, update_data: ConversationUpdate) -> Optional[ConversationInDB]:
        """Update a conversation. Returns None if not found."""
        stmt = select(DBConversation).where(DBConversation.id == conversation_id)
        result = await self.db.execute(stmt)
        db_conversation = result.scalar_one_or_none()

        if not db_conversation:
            return None

        # Update only provided fields
        update_dict = update_data.model_dump(exclude_unset=True)
        for field, value in update_dict.items():
            if hasattr(db_conversation, field):
                setattr(db_conversation, field, value)

        db_conversation.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(db_conversation)

        return self._to_pydantic(db_conversation)

    async def delete(self, conversation_id: str) -> bool:
        """Delete a conversation. Returns True if deleted, False if not found."""
        stmt = delete(DBConversation).where(DBConversation.id == conversation_id)
        result = await self.db.execute(stmt)
        return result.rowcount > 0

    async def delete_all(self) -> int:
        """Delete all conversations. Returns count of deleted conversations."""
        stmt = delete(DBConversation)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    def _to_pydantic(self, db_conversation: DBConversation) -> ConversationInDB:
        """Convert SQLAlchemy model to Pydantic model."""
        return ConversationInDB(
            id=db_conversation.id,
            title=db_conversation.title,
            is_archived=db_conversation.is_archived,
            created_at=db_conversation.created_at,
            updated_at=db_conversation.updated_at,
        )


class MessageStorePostgres:
    """PostgreSQL-backed message storage."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, message: MessageCreate) -> MessageInDB:
        """Create a new message."""
        db_message = DBMessage(
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            tool_used=message.tool_used,
            tool_details=message.tool_details,
            response_source=message.response_source,
        )

        self.db.add(db_message)
        await self.db.flush()
        await self.db.refresh(db_message)

        # Update conversation's updated_at
        stmt = update(DBConversation).where(
            DBConversation.id == message.conversation_id
        ).values(updated_at=datetime.now(timezone.utc))
        await self.db.execute(stmt)

        return self._to_pydantic(db_message)

    async def get_by_conversation(self, conversation_id: str) -> List[MessageInDB]:
        """Get all messages for a conversation."""
        stmt = select(DBMessage).where(
            DBMessage.conversation_id == conversation_id
        ).order_by(DBMessage.created_at.asc())

        result = await self.db.execute(stmt)
        db_messages = result.scalars().all()
        return [self._to_pydantic(msg) for msg in db_messages]

    async def get_all(self) -> List[MessageInDB]:
        """Get all messages across all conversations."""
        stmt = select(DBMessage).order_by(DBMessage.created_at.asc())
        result = await self.db.execute(stmt)
        db_messages = result.scalars().all()
        return [self._to_pydantic(msg) for msg in db_messages]

    async def delete_all(self) -> int:
        """Delete all messages. Returns count of deleted messages."""
        stmt = delete(DBMessage)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    def _to_pydantic(self, db_message: DBMessage) -> MessageInDB:
        """Convert SQLAlchemy model to Pydantic model."""
        return MessageInDB(
            id=db_message.id,
            conversation_id=db_message.conversation_id,
            role=db_message.role,
            content=db_message.content,
            tool_used=db_message.tool_used,
            tool_details=db_message.tool_details,
            response_source=db_message.response_source,
            created_at=db_message.created_at,
        )


class SettingsStorePostgres:
    """PostgreSQL-backed settings storage."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, key: str) -> Optional[str]:
        """Get a setting value by key."""
        stmt = select(DBSetting).where(DBSetting.key == key)
        result = await self.db.execute(stmt)
        db_setting = result.scalar_one_or_none()
        return db_setting.value if db_setting else None

    async def get_all(self) -> Dict[str, str]:
        """Get all settings."""
        stmt = select(DBSetting)
        result = await self.db.execute(stmt)
        db_settings = result.scalars().all()
        return {setting.key: setting.value for setting in db_settings}

    async def set(self, key: str, value: str) -> None:
        """Set a setting value."""
        stmt = select(DBSetting).where(DBSetting.key == key)
        result = await self.db.execute(stmt)
        db_setting = result.scalar_one_or_none()

        if db_setting:
            # Update existing
            db_setting.value = value
            db_setting.updated_at = datetime.now(timezone.utc)
        else:
            # Create new
            db_setting = DBSetting(key=key, value=value)
            self.db.add(db_setting)

        await self.db.flush()

    async def update(self, settings: Dict[str, str]) -> Dict[str, str]:
        """Update multiple settings at once."""
        for key, value in settings.items():
            await self.set(key, value)
        return await self.get_all()
