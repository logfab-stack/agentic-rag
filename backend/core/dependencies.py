"""
Dependency injection for stores.
Provides both PostgreSQL and fallback in-memory stores.
Wraps sync in-memory stores to provide async interface.
"""

import logging
from typing import AsyncGenerator, Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from core.database import get_db, test_connection
from core.store_postgres import (
    DocumentStorePostgres,
    CollectionStorePostgres,
    DocumentRowsStorePostgres,
    ConversationStorePostgres,
    MessageStorePostgres,
)
from core.store import (
    document_store as in_memory_document_store,
    collection_store as in_memory_collection_store,
    document_rows_store as in_memory_document_rows_store,
    DocumentStore,
    CollectionStore,
    DocumentRowsStore,
)
from models.document import DocumentInDB, DocumentCreate, DocumentUpdate
from models.collection import CollectionInDB, CollectionCreate, CollectionUpdate

logger = logging.getLogger(__name__)

# Check if PostgreSQL is available
_postgres_available: Optional[bool] = None


def set_postgres_available(available: bool) -> None:
    """Set PostgreSQL availability status (called during startup)."""
    global _postgres_available
    _postgres_available = available
    if available:
        logger.info("PostgreSQL available - using PostgreSQL stores")
    else:
        logger.warning("PostgreSQL unavailable - using in-memory stores")


def is_postgres_available() -> bool:
    """Check if PostgreSQL is available (cached)."""
    global _postgres_available
    if _postgres_available is None:
        _postgres_available = test_connection()
        if _postgres_available:
            logger.info("PostgreSQL available - using PostgreSQL stores")
        else:
            logger.warning("PostgreSQL unavailable - using in-memory stores")
    return _postgres_available


class AsyncDocumentStoreWrapper:
    """Wrapper to make in-memory DocumentStore async-compatible."""

    def __init__(self, store: DocumentStore):
        self._store = store

    async def create(self, doc: DocumentCreate) -> DocumentInDB:
        return self._store.create(doc)

    async def find_by_filename(self, filename: str) -> Optional[DocumentInDB]:
        return self._store.find_by_filename(filename)

    async def find_by_content_hash(self, content_hash: str) -> Optional[DocumentInDB]:
        return self._store.find_by_content_hash(content_hash)

    async def get(self, doc_id: str) -> Optional[DocumentInDB]:
        return self._store.get(doc_id)

    async def get_all(self) -> List[DocumentInDB]:
        return self._store.get_all()

    async def update(self, doc_id: str, update: DocumentUpdate) -> Optional[DocumentInDB]:
        return self._store.update(doc_id, update)

    async def delete(self, doc_id: str) -> bool:
        return self._store.delete(doc_id)


class AsyncCollectionStoreWrapper:
    """Wrapper to make in-memory CollectionStore async-compatible."""

    def __init__(self, store: CollectionStore):
        self._store = store

    async def create(self, collection: CollectionCreate) -> CollectionInDB:
        return self._store.create(collection)

    async def get(self, collection_id: str) -> Optional[CollectionInDB]:
        return self._store.get(collection_id)

    async def get_all(self) -> List[CollectionInDB]:
        return self._store.get_all()

    async def update(self, collection_id: str, update: CollectionUpdate) -> Optional[CollectionInDB]:
        return self._store.update(collection_id, update)

    async def delete(self, collection_id: str) -> bool:
        return self._store.delete(collection_id)


class AsyncDocumentRowsStoreWrapper:
    """Wrapper to make in-memory DocumentRowsStore async-compatible."""

    def __init__(self, store: DocumentRowsStore):
        self._store = store

    async def add_rows(self, dataset_id: str, rows: List[Dict], schema: List[str]) -> int:
        return self._store.add_rows(dataset_id, rows, schema)

    async def get_rows(self, dataset_id: str) -> List[Dict]:
        return self._store.get_rows(dataset_id)

    async def get_all_datasets(self) -> Dict[str, int]:
        return self._store.get_all_datasets()

    async def delete_dataset(self, dataset_id: str) -> bool:
        return self._store.delete_dataset(dataset_id)

    async def get_schema(self, dataset_id: str) -> List[str]:
        return self._store.get_schema(dataset_id)

    async def aggregate(self, dataset_id: str, column: str, operation: str) -> Optional[float]:
        return self._store.aggregate(dataset_id, column, operation)


async def get_document_store(db: AsyncSession = Depends(get_db)):
    """Get document store (PostgreSQL or in-memory fallback)."""
    if is_postgres_available():
        return DocumentStorePostgres(db)
    return AsyncDocumentStoreWrapper(in_memory_document_store)


async def get_collection_store(db: AsyncSession = Depends(get_db)):
    """Get collection store (PostgreSQL or in-memory fallback)."""
    if is_postgres_available():
        return CollectionStorePostgres(db)
    return AsyncCollectionStoreWrapper(in_memory_collection_store)


async def get_document_rows_store(db: AsyncSession = Depends(get_db)):
    """Get document rows store (PostgreSQL or in-memory fallback)."""
    if is_postgres_available():
        return DocumentRowsStorePostgres(db)
    return AsyncDocumentRowsStoreWrapper(in_memory_document_rows_store)


async def get_conversation_store(db: AsyncSession = Depends(get_db)):
    """Get conversation store (PostgreSQL only - no fallback)."""
    if not is_postgres_available():
        logger.error("PostgreSQL required for conversation store")
        raise RuntimeError("Database not available")
    return ConversationStorePostgres(db)


async def get_message_store(db: AsyncSession = Depends(get_db)):
    """Get message store (PostgreSQL only - no fallback)."""
    if not is_postgres_available():
        logger.error("PostgreSQL required for message store")
        raise RuntimeError("Database not available")
    return MessageStorePostgres(db)
