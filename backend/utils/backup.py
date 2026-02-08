"""
Backup Utility for Agentic RAG System (Feature #171)

Provides automatic backup functionality before destructive operations.
Creates timestamped backups of both database records and uploaded files.

Features:
- Export documents, document_rows, document_embeddings to JSON
- Copy uploaded files to backup folder
- Timestamped backup folders (YYYY-MM-DD_HH-MM-SS)
- Auto-cleanup of old backups (keeps last 5)
- Restore functionality from backup folder

Usage:
    from utils.backup import create_backup, restore_backup, list_backups

    # Create backup before destructive operation
    backup_path = create_backup(reason="Before cleanup operation")

    # List available backups
    backups = list_backups()

    # Restore from a backup
    restore_backup("2026-01-28_15-30-00")
"""

import os
import sys
import json
import shutil
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from core.database import engine, init_db_sync
from models.db_models import DBDocument, DBDocumentRow, DBCollection

logger = logging.getLogger(__name__)

# Configuration
BACKUPS_DIR = backend_dir / "backups"
UPLOADS_DIR = backend_dir / "uploads"
MAX_BACKUPS = 5


def _serialize_datetime(obj):
    """JSON serializer for datetime objects."""
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _get_backup_timestamp() -> str:
    """Generate timestamp string for backup folder name."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _ensure_backups_dir():
    """Ensure the backups directory exists."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def _export_documents(session: Session) -> List[Dict[str, Any]]:
    """Export all documents from database to list of dicts."""
    stmt = select(DBDocument)
    result = session.execute(stmt)
    documents = result.scalars().all()

    exported = []
    for doc in documents:
        exported.append({
            'id': doc.id,
            'title': doc.title,
            'comment': doc.comment,
            'original_filename': doc.original_filename,
            'mime_type': doc.mime_type,
            'file_size': doc.file_size,
            'document_type': doc.document_type,
            'collection_id': doc.collection_id,
            'content_hash': doc.content_hash,
            'schema_info': doc.schema_info,
            'url': doc.url,
            'created_at': doc.created_at,
            'updated_at': doc.updated_at,
        })

    return exported


def _export_document_rows(session: Session) -> List[Dict[str, Any]]:
    """Export all document rows from database to list of dicts."""
    stmt = select(DBDocumentRow)
    result = session.execute(stmt)
    rows = result.scalars().all()

    exported = []
    for row in rows:
        exported.append({
            'id': row.id,
            'dataset_id': row.dataset_id,
            'row_data': row.row_data,
            'created_at': row.created_at,
        })

    return exported


def _export_collections(session: Session) -> List[Dict[str, Any]]:
    """Export all collections from database to list of dicts."""
    stmt = select(DBCollection)
    result = session.execute(stmt)
    collections = result.scalars().all()

    exported = []
    for col in collections:
        exported.append({
            'id': col.id,
            'name': col.name,
            'description': col.description,
            'created_at': col.created_at,
            'updated_at': col.updated_at,
        })

    return exported


def _export_embeddings(session: Session) -> List[Dict[str, Any]]:
    """
    Export document embeddings metadata (without vectors for space efficiency).
    Vectors are too large and will be re-generated from the uploaded files.
    """
    try:
        from models.embedding import DocumentEmbedding
        stmt = select(DocumentEmbedding)
        result = session.execute(stmt)
        embeddings = result.scalars().all()

        exported = []
        for emb in embeddings:
            exported.append({
                'id': emb.id,
                'document_id': emb.document_id,
                'chunk_id': emb.chunk_id,
                'text': emb.text,
                # Note: embedding vector not included - too large, will be regenerated
                'chunk_metadata': emb.chunk_metadata,
            })

        return exported
    except Exception as e:
        logger.warning(f"Could not export embeddings (pgvector may not be available): {e}")
        return []


def _copy_uploads(backup_path: Path) -> Dict[str, Any]:
    """Copy all files from uploads directory to backup folder."""
    uploads_backup = backup_path / "uploads"
    uploads_backup.mkdir(parents=True, exist_ok=True)

    stats = {
        'files_copied': 0,
        'total_bytes': 0,
        'failed_files': []
    }

    if not UPLOADS_DIR.exists():
        logger.info("Uploads directory does not exist, nothing to backup")
        return stats

    for file_path in UPLOADS_DIR.iterdir():
        if file_path.is_file():
            try:
                dest = uploads_backup / file_path.name
                shutil.copy2(file_path, dest)
                stats['files_copied'] += 1
                stats['total_bytes'] += file_path.stat().st_size
            except Exception as e:
                logger.error(f"Failed to copy {file_path.name}: {e}")
                stats['failed_files'].append(str(file_path.name))

    return stats


def _cleanup_old_backups():
    """Remove old backups, keeping only the most recent MAX_BACKUPS."""
    if not BACKUPS_DIR.exists():
        return

    # Get all backup directories sorted by name (timestamp)
    backup_dirs = sorted([
        d for d in BACKUPS_DIR.iterdir()
        if d.is_dir() and d.name[0].isdigit()  # Starts with digit (timestamp format)
    ], key=lambda x: x.name, reverse=True)

    # Delete excess backups
    for old_backup in backup_dirs[MAX_BACKUPS:]:
        try:
            shutil.rmtree(old_backup)
            logger.info(f"Deleted old backup: {old_backup.name}")
        except Exception as e:
            logger.error(f"Failed to delete old backup {old_backup.name}: {e}")


def create_backup(reason: Optional[str] = None) -> str:
    """
    Create a full backup of documents and uploaded files.

    Args:
        reason: Optional description of why backup is being created

    Returns:
        Path to the created backup folder

    Raises:
        RuntimeError: If backup creation fails
    """
    logger.info("=" * 80)
    logger.info("AUTOMATIC BACKUP - Feature #171")
    logger.info("=" * 80)

    if reason:
        logger.info(f"Reason: {reason}")

    # Initialize database
    init_db_sync()

    # Create backup directory
    _ensure_backups_dir()
    timestamp = _get_backup_timestamp()
    backup_path = BACKUPS_DIR / timestamp
    backup_path.mkdir(parents=True, exist_ok=True)

    logger.info(f"Creating backup in: {backup_path}")

    try:
        with Session(engine) as session:
            # Export database tables to JSON
            logger.info("Exporting database tables...")

            # Documents
            documents = _export_documents(session)
            docs_file = backup_path / "documents.json"
            with open(docs_file, 'w', encoding='utf-8') as f:
                json.dump(documents, f, default=_serialize_datetime, indent=2)
            logger.info(f"  - Exported {len(documents)} documents")

            # Document rows
            rows = _export_document_rows(session)
            rows_file = backup_path / "document_rows.json"
            with open(rows_file, 'w', encoding='utf-8') as f:
                json.dump(rows, f, default=_serialize_datetime, indent=2)
            logger.info(f"  - Exported {len(rows)} document rows")

            # Collections
            collections = _export_collections(session)
            cols_file = backup_path / "collections.json"
            with open(cols_file, 'w', encoding='utf-8') as f:
                json.dump(collections, f, default=_serialize_datetime, indent=2)
            logger.info(f"  - Exported {len(collections)} collections")

            # Embeddings (metadata only)
            embeddings = _export_embeddings(session)
            emb_file = backup_path / "embeddings_metadata.json"
            with open(emb_file, 'w', encoding='utf-8') as f:
                json.dump(embeddings, f, default=_serialize_datetime, indent=2)
            logger.info(f"  - Exported {len(embeddings)} embedding metadata records")

        # Copy uploaded files
        logger.info("Copying uploaded files...")
        file_stats = _copy_uploads(backup_path)
        logger.info(f"  - Copied {file_stats['files_copied']} files ({file_stats['total_bytes']:,} bytes)")
        if file_stats['failed_files']:
            logger.warning(f"  - Failed to copy: {file_stats['failed_files']}")

        # Save backup metadata
        metadata = {
            'timestamp': timestamp,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'reason': reason,
            'documents_count': len(documents),
            'rows_count': len(rows),
            'collections_count': len(collections),
            'embeddings_count': len(embeddings),
            'files_count': file_stats['files_copied'],
            'total_file_bytes': file_stats['total_bytes'],
            'failed_files': file_stats['failed_files'],
        }

        metadata_file = backup_path / "backup_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        # Cleanup old backups
        logger.info("Cleaning up old backups...")
        _cleanup_old_backups()

        logger.info("=" * 80)
        logger.info(f"BACKUP COMPLETE: {backup_path}")
        logger.info("=" * 80)

        return str(backup_path)

    except Exception as e:
        logger.error(f"Backup creation failed: {e}")
        # Try to clean up partial backup
        if backup_path.exists():
            shutil.rmtree(backup_path, ignore_errors=True)
        raise RuntimeError(f"Backup creation failed: {e}")


def list_backups() -> List[Dict[str, Any]]:
    """
    List all available backups with their metadata.

    Returns:
        List of backup metadata dictionaries
    """
    backups = []

    if not BACKUPS_DIR.exists():
        return backups

    for backup_dir in sorted(BACKUPS_DIR.iterdir(), reverse=True):
        if not backup_dir.is_dir():
            continue

        metadata_file = backup_dir / "backup_metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                metadata['path'] = str(backup_dir)
                backups.append(metadata)
            except Exception as e:
                logger.warning(f"Could not read metadata for {backup_dir.name}: {e}")
                # Still include basic info
                backups.append({
                    'timestamp': backup_dir.name,
                    'path': str(backup_dir),
                    'error': str(e)
                })
        else:
            backups.append({
                'timestamp': backup_dir.name,
                'path': str(backup_dir),
                'metadata_missing': True
            })

    return backups


def restore_backup(backup_name: str, restore_files: bool = True) -> Dict[str, Any]:
    """
    Restore database records and optionally uploaded files from a backup.

    WARNING: This will DELETE existing data before restoring!

    Args:
        backup_name: The timestamp name of the backup folder (e.g., "2026-01-28_15-30-00")
        restore_files: Whether to also restore uploaded files

    Returns:
        Dictionary with restore statistics

    Raises:
        FileNotFoundError: If backup folder doesn't exist
        RuntimeError: If restore fails
    """
    backup_path = BACKUPS_DIR / backup_name

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_name}")

    logger.info("=" * 80)
    logger.info(f"RESTORING FROM BACKUP: {backup_name}")
    logger.info("=" * 80)

    init_db_sync()

    stats = {
        'documents_restored': 0,
        'rows_restored': 0,
        'collections_restored': 0,
        'files_restored': 0,
        'errors': []
    }

    try:
        with Session(engine) as session:
            # Clear existing data
            logger.info("Clearing existing data...")

            # Delete in correct order due to foreign keys
            session.execute(text("DELETE FROM document_rows"))
            session.execute(text("DELETE FROM document_embeddings"))
            session.execute(text("DELETE FROM documents"))
            session.execute(text("DELETE FROM collections"))
            session.commit()
            logger.info("  - Existing data cleared")

            # Restore collections first (documents reference them)
            cols_file = backup_path / "collections.json"
            if cols_file.exists():
                with open(cols_file, 'r', encoding='utf-8') as f:
                    collections_data = json.load(f)

                for col_data in collections_data:
                    collection = DBCollection(
                        id=col_data['id'],
                        name=col_data['name'],
                        description=col_data.get('description'),
                    )
                    session.add(collection)
                    stats['collections_restored'] += 1

                session.commit()
                logger.info(f"  - Restored {stats['collections_restored']} collections")

            # Restore documents
            docs_file = backup_path / "documents.json"
            if docs_file.exists():
                with open(docs_file, 'r', encoding='utf-8') as f:
                    documents_data = json.load(f)

                for doc_data in documents_data:
                    document = DBDocument(
                        id=doc_data['id'],
                        title=doc_data['title'],
                        comment=doc_data.get('comment'),
                        original_filename=doc_data['original_filename'],
                        mime_type=doc_data['mime_type'],
                        file_size=doc_data['file_size'],
                        document_type=doc_data.get('document_type', 'unstructured'),
                        collection_id=doc_data.get('collection_id'),
                        content_hash=doc_data.get('content_hash'),
                        schema_info=doc_data.get('schema_info'),
                        url=doc_data.get('url'),
                    )
                    session.add(document)
                    stats['documents_restored'] += 1

                session.commit()
                logger.info(f"  - Restored {stats['documents_restored']} documents")

            # Restore document rows
            rows_file = backup_path / "document_rows.json"
            if rows_file.exists():
                with open(rows_file, 'r', encoding='utf-8') as f:
                    rows_data = json.load(f)

                for row_data in rows_data:
                    row = DBDocumentRow(
                        id=row_data['id'],
                        dataset_id=row_data['dataset_id'],
                        row_data=row_data['row_data'],
                    )
                    session.add(row)
                    stats['rows_restored'] += 1

                session.commit()
                logger.info(f"  - Restored {stats['rows_restored']} document rows")

        # Restore uploaded files
        if restore_files:
            uploads_backup = backup_path / "uploads"
            if uploads_backup.exists():
                # Clear existing uploads
                if UPLOADS_DIR.exists():
                    for f in UPLOADS_DIR.iterdir():
                        if f.is_file():
                            f.unlink()
                else:
                    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

                # Copy files from backup
                for file_path in uploads_backup.iterdir():
                    if file_path.is_file():
                        try:
                            dest = UPLOADS_DIR / file_path.name
                            shutil.copy2(file_path, dest)
                            stats['files_restored'] += 1
                        except Exception as e:
                            stats['errors'].append(f"Failed to restore {file_path.name}: {e}")

                logger.info(f"  - Restored {stats['files_restored']} files")

        logger.info("=" * 80)
        logger.info("RESTORE COMPLETE")
        logger.info(f"  Documents: {stats['documents_restored']}")
        logger.info(f"  Rows: {stats['rows_restored']}")
        logger.info(f"  Collections: {stats['collections_restored']}")
        logger.info(f"  Files: {stats['files_restored']}")
        if stats['errors']:
            logger.warning(f"  Errors: {len(stats['errors'])}")
            for err in stats['errors']:
                logger.warning(f"    - {err}")
        logger.info("=" * 80)

        logger.warning("")
        logger.warning("NOTE: Document embeddings were NOT restored.")
        logger.warning("You will need to re-process documents to regenerate embeddings.")
        logger.warning("")

        return stats

    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise RuntimeError(f"Restore failed: {e}")


def get_backup_info(backup_name: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about a specific backup.

    Args:
        backup_name: The timestamp name of the backup folder

    Returns:
        Backup metadata dictionary or None if not found
    """
    backup_path = BACKUPS_DIR / backup_name

    if not backup_path.exists():
        return None

    metadata_file = backup_path / "backup_metadata.json"
    if metadata_file.exists():
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        metadata['path'] = str(backup_path)
        return metadata

    return {
        'timestamp': backup_name,
        'path': str(backup_path),
        'metadata_missing': True
    }


# CLI interface
if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description="Backup utility for Agentic RAG System")
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Create backup command
    create_parser = subparsers.add_parser('create', help='Create a new backup')
    create_parser.add_argument('--reason', '-r', help='Reason for backup')

    # List backups command
    list_parser = subparsers.add_parser('list', help='List available backups')

    # Restore command
    restore_parser = subparsers.add_parser('restore', help='Restore from a backup')
    restore_parser.add_argument('backup_name', help='Name of backup to restore')
    restore_parser.add_argument('--no-files', action='store_true', help='Skip file restoration')

    # Info command
    info_parser = subparsers.add_parser('info', help='Get info about a backup')
    info_parser.add_argument('backup_name', help='Name of backup')

    args = parser.parse_args()

    if args.command == 'create':
        backup_path = create_backup(reason=args.reason)
        print(f"\nBackup created: {backup_path}")

    elif args.command == 'list':
        backups = list_backups()
        if backups:
            print("\nAvailable backups:")
            print("-" * 60)
            for b in backups:
                print(f"  {b['timestamp']}")
                if 'documents_count' in b:
                    print(f"    - Documents: {b['documents_count']}, Files: {b.get('files_count', 'N/A')}")
                if 'reason' in b and b['reason']:
                    print(f"    - Reason: {b['reason']}")
            print("-" * 60)
        else:
            print("\nNo backups found.")

    elif args.command == 'restore':
        response = input(f"WARNING: This will DELETE existing data! Restore from '{args.backup_name}'? [y/N]: ")
        if response.lower() == 'y':
            stats = restore_backup(args.backup_name, restore_files=not args.no_files)
            print(f"\nRestore complete: {stats}")
        else:
            print("Restore cancelled.")

    elif args.command == 'info':
        info = get_backup_info(args.backup_name)
        if info:
            print(f"\nBackup: {args.backup_name}")
            print("-" * 40)
            for key, value in info.items():
                print(f"  {key}: {value}")
        else:
            print(f"Backup not found: {args.backup_name}")

    else:
        parser.print_help()
