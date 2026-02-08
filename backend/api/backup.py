"""
Backup API endpoints for the Agentic RAG System.

Provides full data backup and restore functionality.
"""

import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from io import BytesIO


def utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.store import document_store, collection_store, settings_store
from core.dependencies import get_conversation_store, get_message_store, get_document_store, get_collection_store
from core.store_postgres import ConversationStorePostgres, MessageStorePostgres, DocumentStorePostgres, CollectionStorePostgres
from models.document import DocumentInDB
from models.collection import CollectionInDB
from models.conversation import Conversation, Message, ConversationCreate, MessageCreate

router = APIRouter()


class BackupMetadata(BaseModel):
    """Metadata about the backup file."""
    version: str = "1.0"
    created_at: str
    app_name: str = "Agentic RAG System"
    document_count: int
    collection_count: int
    conversation_count: int
    message_count: int


class BackupResponse(BaseModel):
    """Response model for backup creation."""
    success: bool
    message: str
    filename: str
    size_bytes: int
    metadata: BackupMetadata


def serialize_document(doc) -> Dict[str, Any]:
    """Serialize a document to a JSON-serializable dict."""
    return {
        "id": doc.id,
        "title": doc.title,
        "comment": doc.comment,
        "original_filename": doc.original_filename,
        "mime_type": doc.mime_type,
        "file_size": doc.file_size,
        "document_type": doc.document_type,
        "collection_id": doc.collection_id,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


def serialize_collection(col) -> Dict[str, Any]:
    """Serialize a collection to a JSON-serializable dict."""
    return {
        "id": col.id,
        "name": col.name,
        "description": col.description,
        "created_at": col.created_at.isoformat() if col.created_at else None,
        "updated_at": col.updated_at.isoformat() if col.updated_at else None,
    }


def serialize_conversation(conv) -> Dict[str, Any]:
    """Serialize a conversation to a JSON-serializable dict."""
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }


def serialize_message(msg) -> Dict[str, Any]:
    """Serialize a message to a JSON-serializable dict."""
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "role": msg.role,
        "content": msg.content,
        "tool_used": msg.tool_used,
        "tool_details": msg.tool_details,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.post("/", response_class=StreamingResponse)
async def create_backup(
    document_store_pg = Depends(get_document_store),
    collection_store_pg = Depends(get_collection_store),
    conversation_store_pg: ConversationStorePostgres = Depends(get_conversation_store),
    message_store_pg: MessageStorePostgres = Depends(get_message_store)
):
    """
    Create a full backup of all data.

    Returns a ZIP file containing:
    - manifest.json: Backup metadata
    - documents.json: All document metadata
    - collections.json: All collections
    - conversations.json: All conversations with messages
    - settings.json: Non-sensitive settings
    - files/: Directory with all uploaded files
    """
    try:
        # Gather all data
        documents = await document_store_pg.get_all()
        collections = await collection_store_pg.get_all()
        conversations = await conversation_store_pg.get_all()
        all_messages = await message_store_pg.get_all()

        # Get settings (excluding sensitive API keys)
        all_settings = settings_store.get_all()
        safe_settings = {
            k: v for k, v in all_settings.items()
            if 'api_key' not in k.lower()
        }

        # Create backup metadata
        now = utc_now()
        metadata = BackupMetadata(
            created_at=now.isoformat(),
            document_count=len(documents),
            collection_count=len(collections),
            conversation_count=len(conversations),
            message_count=len(all_messages),
        )

        # Create ZIP file in memory
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add manifest
            zip_file.writestr(
                'manifest.json',
                json.dumps(metadata.model_dump(), indent=2)
            )

            # Add documents metadata
            docs_data = [serialize_document(doc) for doc in documents]
            zip_file.writestr(
                'documents.json',
                json.dumps(docs_data, indent=2)
            )

            # Add collections
            cols_data = [serialize_collection(col) for col in collections]
            zip_file.writestr(
                'collections.json',
                json.dumps(cols_data, indent=2)
            )

            # Add conversations with their messages
            convs_data = []
            for conv in conversations:
                conv_dict = serialize_conversation(conv)
                # Find messages for this conversation
                conv_messages = [
                    serialize_message(msg) for msg in all_messages
                    if msg.conversation_id == conv.id
                ]
                conv_dict['messages'] = sorted(
                    conv_messages,
                    key=lambda m: m['created_at'] or ''
                )
                convs_data.append(conv_dict)

            zip_file.writestr(
                'conversations.json',
                json.dumps(convs_data, indent=2)
            )

            # Add settings (without API keys)
            zip_file.writestr(
                'settings.json',
                json.dumps(safe_settings, indent=2)
            )

            # Add uploaded files
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
            if os.path.exists(uploads_dir):
                for doc in documents:
                    # Try to find the file by document ID
                    for filename in os.listdir(uploads_dir):
                        if filename.startswith(doc.id):
                            file_path = os.path.join(uploads_dir, filename)
                            if os.path.isfile(file_path):
                                # Store with original filename in archive
                                archive_name = f"files/{doc.id}_{doc.original_filename}"
                                zip_file.write(file_path, archive_name)
                                break

        # Prepare response
        zip_buffer.seek(0)

        # Generate filename with timestamp
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        filename = f"rag_backup_{timestamp}.zip"

        # Return as streaming response
        return StreamingResponse(
            zip_buffer,
            media_type='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'X-Backup-Document-Count': str(len(documents)),
                'X-Backup-Collection-Count': str(len(collections)),
                'X-Backup-Conversation-Count': str(len(conversations)),
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create backup: {str(e)}"
        )


@router.get("/status")
async def backup_status(
    document_store_pg = Depends(get_document_store),
    collection_store_pg = Depends(get_collection_store),
    conversation_store_pg: ConversationStorePostgres = Depends(get_conversation_store),
    message_store_pg: MessageStorePostgres = Depends(get_message_store)
):
    """
    Get current data counts for backup preview.

    Returns counts of documents, collections, conversations, and messages.
    """
    documents = await document_store_pg.get_all()
    collections = await collection_store_pg.get_all()
    conversations = await conversation_store_pg.get_all()
    messages = await message_store_pg.get_all()

    # Calculate uploaded files size
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
    total_files_size = 0
    files_count = 0

    if os.path.exists(uploads_dir):
        for filename in os.listdir(uploads_dir):
            file_path = os.path.join(uploads_dir, filename)
            if os.path.isfile(file_path):
                total_files_size += os.path.getsize(file_path)
                files_count += 1

    return {
        "documents": len(documents),
        "collections": len(collections),
        "conversations": len(conversations),
        "messages": len(messages),
        "uploaded_files_count": files_count,
        "uploaded_files_size_bytes": total_files_size,
        "uploaded_files_size_human": _format_size(total_files_size),
    }


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


class RestoreResponse(BaseModel):
    """Response model for restore operation."""
    success: bool
    message: str
    documents_restored: int
    collections_restored: int
    conversations_restored: int
    messages_restored: int
    files_restored: int


def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO format datetime string."""
    if not dt_str:
        return None
    try:
        # Handle ISO format with or without microseconds
        if '.' in dt_str:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return utc_now()


@router.post("/restore", response_model=RestoreResponse)
async def restore_backup(
    file: UploadFile = File(...),
    document_store_pg = Depends(get_document_store),
    collection_store_pg = Depends(get_collection_store),
    conversation_store_pg: ConversationStorePostgres = Depends(get_conversation_store),
    message_store_pg: MessageStorePostgres = Depends(get_message_store)
):
    """
    Restore data from a backup ZIP file.

    This will:
    1. Clear all existing data (documents, collections, conversations, messages)
    2. Restore all data from the backup file
    3. Restore uploaded files to the uploads directory

    Note: API keys are not included in backups and will not be restored.
    """
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Please upload a .zip backup file."
        )

    try:
        # Read the uploaded file into memory
        contents = await file.read()
        zip_buffer = BytesIO(contents)

        documents_restored = 0
        collections_restored = 0
        conversations_restored = 0
        messages_restored = 0
        files_restored = 0

        with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
            # Verify this is a valid backup by checking for manifest
            file_list = zip_file.namelist()
            if 'manifest.json' not in file_list:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid backup file. Missing manifest.json"
                )

            # Read manifest to verify backup version
            manifest_data = json.loads(zip_file.read('manifest.json'))
            if manifest_data.get('app_name') != 'Agentic RAG System':
                raise HTTPException(
                    status_code=400,
                    detail="Invalid backup file. This backup is from a different application."
                )

            # Clear existing data using PostgreSQL stores
            from sqlalchemy import text

            # Clear documents first (before collections due to foreign key)
            await document_store_pg.delete_all()
            await collection_store_pg.delete_all()
            # Clear PostgreSQL conversations and messages
            await conversation_store_pg.delete_all()
            await message_store_pg.delete_all()

            # Restore collections first (documents may reference them)
            if 'collections.json' in file_list:
                collections_data = json.loads(zip_file.read('collections.json'))
                for col_data in collections_data:
                    # Insert collection with specific ID using raw SQL
                    created_at = parse_datetime(col_data.get('created_at')) or utc_now()
                    updated_at = parse_datetime(col_data.get('updated_at')) or utc_now()

                    insert_col_stmt = text("""
                        INSERT INTO collections (id, name, description, created_at, updated_at)
                        VALUES (:id, :name, :description, :created_at, :updated_at)
                    """)
                    await collection_store_pg.db.execute(
                        insert_col_stmt,
                        {
                            'id': col_data['id'],
                            'name': col_data['name'],
                            'description': col_data.get('description'),
                            'created_at': created_at,
                            'updated_at': updated_at
                        }
                    )
                    collections_restored += 1

            # Restore documents using raw SQL to preserve IDs
            if 'documents.json' in file_list:
                documents_data = json.loads(zip_file.read('documents.json'))
                for doc_data in documents_data:
                    created_at = parse_datetime(doc_data.get('created_at')) or utc_now()
                    updated_at = parse_datetime(doc_data.get('updated_at')) or utc_now()

                    insert_doc_stmt = text("""
                        INSERT INTO documents (id, title, comment, original_filename, mime_type,
                                             file_size, document_type, collection_id, content_hash,
                                             schema_info, created_at, updated_at)
                        VALUES (:id, :title, :comment, :original_filename, :mime_type,
                               :file_size, :document_type, :collection_id, :content_hash,
                               :schema_info, :created_at, :updated_at)
                    """)
                    await document_store_pg.db.execute(
                        insert_doc_stmt,
                        {
                            'id': doc_data['id'],
                            'title': doc_data['title'],
                            'comment': doc_data.get('comment'),
                            'original_filename': doc_data['original_filename'],
                            'mime_type': doc_data['mime_type'],
                            'file_size': doc_data['file_size'],
                            'document_type': doc_data.get('document_type', 'unstructured'),
                            'collection_id': doc_data.get('collection_id'),
                            'content_hash': doc_data.get('content_hash'),
                            'schema_info': json.dumps(doc_data.get('schema_info')) if doc_data.get('schema_info') else None,
                            'created_at': created_at,
                            'updated_at': updated_at
                        }
                    )
                    documents_restored += 1

            # Restore conversations and messages using raw SQL inserts to preserve IDs
            if 'conversations.json' in file_list:
                conversations_data = json.loads(zip_file.read('conversations.json'))
                for conv_data in conversations_data:
                    # Insert conversation directly with specific ID
                    created_at = parse_datetime(conv_data.get('created_at')) or utc_now()
                    updated_at = parse_datetime(conv_data.get('updated_at')) or utc_now()

                    insert_conv_stmt = text("""
                        INSERT INTO conversations (id, title, created_at, updated_at)
                        VALUES (:id, :title, :created_at, :updated_at)
                    """)
                    await conversation_store_pg.db.execute(
                        insert_conv_stmt,
                        {
                            'id': conv_data['id'],
                            'title': conv_data.get('title') or 'New Conversation',
                            'created_at': created_at,
                            'updated_at': updated_at
                        }
                    )
                    conversations_restored += 1

                    # Restore messages for this conversation
                    for msg_data in conv_data.get('messages', []):
                        msg_created_at = parse_datetime(msg_data.get('created_at')) or utc_now()

                        insert_msg_stmt = text("""
                            INSERT INTO messages (id, conversation_id, role, content, tool_used, tool_details, response_source, created_at)
                            VALUES (:id, :conversation_id, :role, :content, :tool_used, :tool_details, :response_source, :created_at)
                        """)
                        await message_store_pg.db.execute(
                            insert_msg_stmt,
                            {
                                'id': msg_data['id'],
                                'conversation_id': msg_data['conversation_id'],
                                'role': msg_data['role'],
                                'content': msg_data['content'],
                                'tool_used': msg_data.get('tool_used'),
                                'tool_details': json.dumps(msg_data.get('tool_details')) if msg_data.get('tool_details') else None,
                                'response_source': msg_data.get('response_source'),
                                'created_at': msg_created_at
                            }
                        )
                        messages_restored += 1

                # Flush changes
                await conversation_store_pg.db.flush()

            # Flush all document and collection changes
            await document_store_pg.db.flush()

            # Restore settings (excluding API keys which are not in backup)
            if 'settings.json' in file_list:
                settings_data = json.loads(zip_file.read('settings.json'))
                # Only restore non-sensitive settings
                for key, value in settings_data.items():
                    if 'api_key' not in key.lower():
                        settings_store.set(key, value)

            # Restore uploaded files
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
            os.makedirs(uploads_dir, exist_ok=True)

            for file_name in file_list:
                if file_name.startswith('files/') and not file_name.endswith('/'):
                    # Extract the file
                    file_content = zip_file.read(file_name)
                    # Get just the filename part (after 'files/')
                    target_filename = file_name[6:]  # Remove 'files/' prefix
                    target_path = os.path.join(uploads_dir, target_filename)

                    with open(target_path, 'wb') as f:
                        f.write(file_content)
                    files_restored += 1

        return RestoreResponse(
            success=True,
            message="Backup restored successfully",
            documents_restored=documents_restored,
            collections_restored=collections_restored,
            conversations_restored=conversations_restored,
            messages_restored=messages_restored,
            files_restored=files_restored
        )

    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=400,
            detail="Invalid ZIP file. The file may be corrupted."
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid backup data: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore backup: {str(e)}"
        )


# ============================================================
# Automatic Backup Scheduler Endpoints (Feature #221)
# ============================================================


class AutoBackupConfigRequest(BaseModel):
    """Request model for configuring automatic backups."""
    enabled: bool
    backup_hour: Optional[int] = None  # 0-23
    backup_minute: Optional[int] = None  # 0-59


class AutoBackupStatusResponse(BaseModel):
    """Response model for automatic backup status."""
    enabled: bool
    backup_hour: int
    backup_minute: int
    backup_time_formatted: str
    last_backup_time: Optional[str]
    last_backup_status: str  # "success", "failed", "never"
    last_backup_error: Optional[str]
    next_backup_time: Optional[str]
    backup_in_progress: bool
    daily_retention: int
    weekly_retention: int
    backups_dir: str


class AutoBackupInfo(BaseModel):
    """Information about a single automatic backup."""
    name: str
    timestamp: str
    created_at: str
    is_weekly: bool
    total_size_bytes: int
    total_size_human: str
    path: str


class AutoBackupListResponse(BaseModel):
    """Response model for listing automatic backups."""
    backups: list
    count: int


class RunBackupResponse(BaseModel):
    """Response model for running a backup immediately."""
    success: bool
    message: str
    backup_path: Optional[str] = None
    error: Optional[str] = None


@router.get("/auto/status", response_model=AutoBackupStatusResponse)
async def get_auto_backup_status():
    """
    Get the current status of automatic backup scheduler.

    Returns:
    - enabled: Whether automatic backups are enabled
    - backup_hour/minute: Scheduled backup time (UTC)
    - last_backup_time/status: Information about the last backup
    - next_backup_time: When the next backup is scheduled
    - retention settings
    """
    try:
        from services.backup_scheduler import get_backup_scheduler
        scheduler = get_backup_scheduler()
        status = scheduler.get_status()
        return AutoBackupStatusResponse(**status)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get backup status: {str(e)}"
        )


@router.post("/auto/configure", response_model=AutoBackupStatusResponse)
async def configure_auto_backup(config: AutoBackupConfigRequest):
    """
    Configure automatic backup settings.

    Parameters:
    - enabled: Enable or disable automatic backups
    - backup_hour: Hour to run backup (0-23, UTC)
    - backup_minute: Minute to run backup (0-59)

    When enabled, backups will run daily at the specified time.
    """
    try:
        from services.backup_scheduler import get_backup_scheduler
        scheduler = get_backup_scheduler()

        if config.enabled:
            scheduler.enable(
                hour=config.backup_hour,
                minute=config.backup_minute
            )
        else:
            scheduler.disable()

        status = scheduler.get_status()
        return AutoBackupStatusResponse(**status)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to configure backup: {str(e)}"
        )


@router.post("/auto/run", response_model=RunBackupResponse)
async def run_auto_backup_now():
    """
    Trigger an automatic backup immediately.

    Runs the same backup procedure as the scheduled backup,
    including pg_dump and file backup with rotation policy.
    """
    try:
        from services.backup_scheduler import get_backup_scheduler
        scheduler = get_backup_scheduler()
        result = scheduler.run_now()

        return RunBackupResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            backup_path=result.get("backup_path"),
            error=result.get("error")
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run backup: {str(e)}"
        )


@router.get("/auto/list", response_model=AutoBackupListResponse)
async def list_auto_backups():
    """
    List all automatic backups.

    Returns a list of all backups created by the automatic scheduler,
    including their metadata and size information.
    """
    try:
        from services.backup_scheduler import get_backup_scheduler
        scheduler = get_backup_scheduler()
        backups = scheduler.list_backups()

        return AutoBackupListResponse(
            backups=backups,
            count=len(backups)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list backups: {str(e)}"
        )
