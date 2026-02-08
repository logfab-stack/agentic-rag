"""
Collection API endpoints for the Agentic RAG System.

Feature #327: Standardized error handling with user-friendly messages.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from typing import List
from models.collection import Collection, CollectionCreate, CollectionUpdate, CollectionWithDocuments
from models.document import DocumentUpdate
from core.dependencies import get_collection_store, get_document_store
import logging

# Feature #327: Standardized error handling
from core.errors import NotFoundError, handle_exception, ErrorCode, raise_api_error

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[Collection])
async def list_collections(collection_store=Depends(get_collection_store)):
    """List all collections sorted by name."""
    return await collection_store.get_all()


@router.get("/{collection_id}", response_model=CollectionWithDocuments)
async def get_collection(
    collection_id: str,
    collection_store=Depends(get_collection_store),
    document_store=Depends(get_document_store)
):
    """Get a collection by ID with its documents."""
    collection = await collection_store.get(collection_id)
    if not collection:
        # Feature #327: Use standardized NotFoundError
        raise NotFoundError("Collection", collection_id)

    # Get documents in this collection
    all_docs = await document_store.get_all()
    collection_docs = [
        {
            "id": doc.id,
            "title": doc.title,
            "original_filename": doc.original_filename,
            "mime_type": doc.mime_type,
            "created_at": doc.created_at.isoformat() if doc.created_at else None
        }
        for doc in all_docs
        if doc.collection_id == collection_id
    ]

    return CollectionWithDocuments(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
        documents=collection_docs
    )


@router.post("/", response_model=Collection, status_code=status.HTTP_201_CREATED)
async def create_collection(collection: CollectionCreate, collection_store=Depends(get_collection_store)):
    """Create a new collection."""
    logger.info(f"Creating collection: {collection.name}")
    new_collection = await collection_store.create(collection)
    logger.info(f"Created collection: {new_collection.id}")
    return new_collection


@router.patch("/{collection_id}", response_model=Collection)
async def update_collection(collection_id: str, update: CollectionUpdate, collection_store=Depends(get_collection_store)):
    """
    Update a collection's name or description.

    Only provided fields will be updated.
    """
    collection = await collection_store.update(collection_id, update)
    if not collection:
        # Feature #327: Use standardized NotFoundError
        raise NotFoundError("Collection", collection_id)
    return collection


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: str,
    collection_store=Depends(get_collection_store),
    document_store=Depends(get_document_store)
):
    """
    Delete a collection.

    Documents in this collection will have their collection_id set to null (uncategorized).

    Feature #213: Automatically creates a backup before collection delete if require_backup_before_delete is enabled
    and the collection contains documents (cascade effect).
    """
    from services.pre_destructive_backup import create_pre_destructive_backup

    collection = await collection_store.get(collection_id)
    if not collection:
        # Feature #327: Use standardized NotFoundError
        raise NotFoundError("Collection", collection_id)

    # Check for documents in this collection (cascade effect)
    all_docs = await document_store.get_all()
    affected_docs = [doc for doc in all_docs if doc.collection_id == collection_id]

    # Feature #213: Create pre-destructive backup if documents are affected
    if affected_docs:
        backup_result = await create_pre_destructive_backup(
            operation="delete-collection-cascade",
            details={
                "collection_id": collection_id,
                "collection_name": collection.name,
                "affected_documents": len(affected_docs),
                "document_ids": [doc.id for doc in affected_docs[:20]],  # Limit to first 20 for metadata
                "action": "collection_delete_with_cascade"
            }
        )

        if not backup_result['success'] and not backup_result.get('skipped', False):
            # Backup failed and was required - block the operation
            logger.error(f"[Feature #213] Pre-destructive backup failed, blocking collection delete: {backup_result['error']}")
            # Feature #327: Use standardized error response
            raise_api_error(
                ErrorCode.COLLECTION_DELETE_FAILED,
                status_code=500,
                detail="Pre-destructive backup failed. Please try again later.",
                log_message=f"Backup failed: {backup_result['error']}"
            )

        if backup_result.get('backup_path'):
            logger.info(f"[Feature #213] Pre-destructive backup created before collection delete at: {backup_result['backup_path']}")

    # Move documents to uncategorized (set collection_id to None)
    for doc in affected_docs:
        await document_store.update(doc.id, DocumentUpdate(collection_id=None))
        logger.info(f"Moved document {doc.id} to uncategorized")

    # Delete the collection
    await collection_store.delete(collection_id)
    logger.info(f"Deleted collection: {collection_id}")
    return None
