"""
Utility to find and remove orphaned embeddings.

Orphaned embeddings are embeddings that reference documents
that no longer exist in the document_metadata table.
"""

import logging
from typing import List, Dict
from core.store import embedding_store
from core.dependencies import get_document_store

logger = logging.getLogger(__name__)


def find_orphaned_embeddings() -> List[str]:
    """
    Find all document_ids in embedding store that don't have
    corresponding entries in document_metadata.

    Returns:
        List of orphaned document_ids
    """
    try:
        # Get all unique document_ids from embeddings
        if hasattr(embedding_store, '_get_connection'):
            # SQLite backend
            conn = embedding_store._get_connection()
            cursor = conn.execute(
                "SELECT DISTINCT document_id FROM document_embeddings"
            )
            embedding_doc_ids = {row[0] for row in cursor.fetchall()}
            conn.close()
        else:
            # PostgreSQL backend
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                embedding_doc_ids = {
                    row[0] for row in session.query(
                        DocumentEmbedding.document_id
                    ).distinct().all()
                }

        if not embedding_doc_ids:
            logger.info("No embeddings found in database")
            return []

        # Get all document_ids from document_metadata
        # Use direct database access since we're in a sync context
        from core.database import SessionLocal
        from models.document import DocumentMetadata

        with SessionLocal() as session:
            metadata_doc_ids = {
                row[0] for row in session.query(
                    DocumentMetadata.id
                ).all()
            }

        # Find orphaned embeddings
        orphaned_ids = embedding_doc_ids - metadata_doc_ids

        if orphaned_ids:
            logger.warning(f"Found {len(orphaned_ids)} orphaned document embeddings")
            for doc_id in list(orphaned_ids)[:10]:  # Log first 10
                logger.warning(f"  - Orphaned document_id: {doc_id}")
            if len(orphaned_ids) > 10:
                logger.warning(f"  ... and {len(orphaned_ids) - 10} more")
        else:
            logger.info("No orphaned embeddings found")

        return list(orphaned_ids)

    except Exception as e:
        logger.error(f"Error finding orphaned embeddings: {e}")
        return []


def cleanup_orphaned_embeddings() -> Dict[str, int]:
    """
    Find and remove all orphaned embeddings.

    Returns:
        Dictionary with cleanup statistics:
        - found: number of orphaned document_ids found
        - deleted: number of orphaned embeddings deleted
        - errors: number of deletion errors
    """
    stats = {
        "found": 0,
        "deleted": 0,
        "errors": 0
    }

    try:
        orphaned_ids = find_orphaned_embeddings()
        stats["found"] = len(orphaned_ids)

        if not orphaned_ids:
            logger.info("No orphaned embeddings to clean up")
            return stats

        # Delete each orphaned document's embeddings
        for doc_id in orphaned_ids:
            try:
                if embedding_store.delete_document(doc_id):
                    stats["deleted"] += 1
                    logger.info(f"Cleaned up orphaned embeddings for document {doc_id}")
                else:
                    logger.warning(f"No embeddings deleted for orphaned document {doc_id}")
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error deleting orphaned embeddings for {doc_id}: {e}")

        logger.info(
            f"Cleanup complete: {stats['deleted']}/{stats['found']} orphaned "
            f"embeddings deleted, {stats['errors']} errors"
        )

        return stats

    except Exception as e:
        logger.error(f"Error during orphaned embeddings cleanup: {e}")
        return stats


def verify_embedding_cleanup(document_id: str) -> bool:
    """
    Verify that all embeddings for a document have been deleted.

    Args:
        document_id: ID of the document to check

    Returns:
        True if no embeddings remain, False if embeddings still exist
    """
    try:
        if hasattr(embedding_store, '_get_connection'):
            # SQLite backend
            conn = embedding_store._get_connection()
            cursor = conn.execute(
                "SELECT COUNT(*) FROM document_embeddings WHERE document_id = ?",
                (document_id,)
            )
            count = cursor.fetchone()[0]
            conn.close()
        else:
            # PostgreSQL backend
            from core.database import SessionLocal
            from models.embedding import DocumentEmbedding

            with SessionLocal() as session:
                count = session.query(DocumentEmbedding).filter(
                    DocumentEmbedding.document_id == document_id
                ).count()

        if count > 0:
            logger.warning(
                f"Verification failed: {count} embeddings still exist for "
                f"document {document_id}"
            )
            return False

        logger.info(f"Verification passed: No embeddings remain for document {document_id}")
        return True

    except Exception as e:
        logger.error(f"Error verifying embedding cleanup for {document_id}: {e}")
        return False
