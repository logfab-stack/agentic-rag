"""
In-memory document and collection store for development.
Will be replaced with PostgreSQL/SQLAlchemy in production.
"""

from typing import Dict, List, Optional
from datetime import datetime, timezone
from models.document import DocumentInDB, DocumentCreate, DocumentUpdate
from models.collection import CollectionInDB, CollectionCreate, CollectionUpdate
import uuid


def utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)
import base64
from cryptography.fernet import Fernet
import os


class DocumentStore:
    """In-memory document storage for development."""

    def __init__(self):
        self._documents: Dict[str, DocumentInDB] = {}

    def create(self, doc: DocumentCreate) -> DocumentInDB:
        """Create a new document."""
        doc_id = str(uuid.uuid4())
        now = utc_now()

        document = DocumentInDB(
            id=doc_id,
            title=doc.title,
            comment=doc.comment,
            original_filename=doc.original_filename,
            mime_type=doc.mime_type,
            file_size=doc.file_size,
            document_type=doc.document_type,
            collection_id=doc.collection_id,
            content_hash=doc.content_hash,
            created_at=now,
            updated_at=now
        )

        self._documents[doc_id] = document
        return document

    def find_by_filename(self, filename: str) -> Optional[DocumentInDB]:
        """Find a document by its original filename."""
        for doc in self._documents.values():
            if doc.original_filename == filename:
                return doc
        return None

    def find_by_content_hash(self, content_hash: str) -> Optional[DocumentInDB]:
        """Find a document by its content hash."""
        for doc in self._documents.values():
            if doc.content_hash == content_hash:
                return doc
        return None

    def get(self, doc_id: str) -> Optional[DocumentInDB]:
        """Get a document by ID."""
        return self._documents.get(doc_id)

    def get_all(self) -> List[DocumentInDB]:
        """Get all documents."""
        return list(self._documents.values())

    def update(self, doc_id: str, update: DocumentUpdate) -> Optional[DocumentInDB]:
        """Update a document. Returns None if not found."""
        if doc_id not in self._documents:
            return None

        doc = self._documents[doc_id]
        update_data = update.model_dump(exclude_unset=True)

        # Update only provided fields
        for field, value in update_data.items():
            if hasattr(doc, field):
                setattr(doc, field, value)

        doc.updated_at = utc_now()
        self._documents[doc_id] = doc
        return doc

    def delete(self, doc_id: str) -> bool:
        """Delete a document. Returns True if deleted, False if not found."""
        if doc_id in self._documents:
            del self._documents[doc_id]
            return True
        return False

    def clear(self):
        """Clear all documents (for testing)."""
        self._documents.clear()


# Global document store instance
document_store = DocumentStore()


class CollectionStore:
    """In-memory collection storage for development."""

    def __init__(self):
        self._collections: Dict[str, CollectionInDB] = {}

    def create(self, collection: CollectionCreate) -> CollectionInDB:
        """Create a new collection."""
        collection_id = str(uuid.uuid4())
        now = utc_now()

        new_collection = CollectionInDB(
            id=collection_id,
            name=collection.name,
            description=collection.description,
            created_at=now,
            updated_at=now
        )

        self._collections[collection_id] = new_collection
        return new_collection

    def get(self, collection_id: str) -> Optional[CollectionInDB]:
        """Get a collection by ID."""
        return self._collections.get(collection_id)

    def get_all(self) -> List[CollectionInDB]:
        """Get all collections sorted by name."""
        return sorted(self._collections.values(), key=lambda c: c.name.lower())

    def update(self, collection_id: str, update: CollectionUpdate) -> Optional[CollectionInDB]:
        """Update a collection. Returns None if not found."""
        if collection_id not in self._collections:
            return None

        collection = self._collections[collection_id]
        update_data = update.model_dump(exclude_unset=True)

        # Update only provided fields
        for field, value in update_data.items():
            if hasattr(collection, field):
                setattr(collection, field, value)

        collection.updated_at = utc_now()
        self._collections[collection_id] = collection
        return collection

    def delete(self, collection_id: str) -> bool:
        """Delete a collection. Returns True if deleted, False if not found."""
        if collection_id in self._collections:
            del self._collections[collection_id]
            return True
        return False

    def clear(self):
        """Clear all collections (for testing)."""
        self._collections.clear()


# Global collection store instance
collection_store = CollectionStore()


class SettingsStore:
    """
    File-based settings storage with encryption for API keys.
    Persists settings to a JSON file so they survive across sessions.
    API keys are encrypted using Fernet (symmetric encryption).
    """

    SETTINGS_FILE = "settings.json"  # Relative to backend directory
    KEY_FILE = ".encryption_key"  # Hidden file for encryption key

    def __init__(self):
        # Default settings
        self._default_settings: Dict[str, str] = {
            'openai_api_key': '',
            'cohere_api_key': '',
            'openrouter_api_key': '',
            'twilio_account_sid': '',
            'twilio_auth_token': '',
            'twilio_whatsapp_number': '',
            'telegram_bot_token': '',  # Feature #306: Telegram Bot configuration
            'llm_model': 'gpt-4o',
            'embedding_model': 'text-embedding-3-small',
            'chunking_llm_model': '',
            'theme': 'system',
            'context_window_size': '20',  # Number of previous messages to include for conversation continuity
            'custom_system_prompt': '',  # Feature #179: Custom AI system prompt (empty = use default)
            # Feature #194: Configurable relevance thresholds
            'min_relevance_threshold': '0.4',  # Default threshold for normal mode (0.0 - 0.9) Feature #339
            'strict_relevance_threshold': '0.6',  # Threshold when strict_rag_mode is enabled (0.0 - 0.9) Feature #339
            # Feature #199: Suggested questions
            'enable_suggested_questions': 'true',  # Show suggested questions for documents
            # Feature #201: Typewriter effect
            'enable_typewriter': 'true',  # Display AI responses with typewriter animation
            # Feature #212: Automatic daily backup system
            'enable_auto_backup': 'false',  # Enable automatic daily backups
            'backup_time': '02:00',  # Time for daily backup (HH:MM format, 24-hour)
            'backup_retention_days': '7',  # Number of days to keep old backups
            # Feature #230: Configurable top_k for RAG retrieval
            'top_k': '10',  # Number of chunks to retrieve (5-100, default: 10)
            # Feature #317: Default language preference for AI responses
            'default_language': 'it'  # Default to Italian ('it', 'en', 'auto' for auto-detect)
        }
        self._settings: Dict[str, str] = self._default_settings.copy()
        # Initialize encryption
        self._cipher = self._get_or_create_cipher()
        # Load settings from file on startup
        self._load_from_file()

    def _get_backend_dir(self) -> str:
        """Get the backend directory path."""
        module_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.dirname(module_dir)

    def _get_settings_path(self) -> str:
        """Get the absolute path to the settings file."""
        return os.path.join(self._get_backend_dir(), self.SETTINGS_FILE)

    def _get_key_path(self) -> str:
        """Get the absolute path to the encryption key file."""
        return os.path.join(self._get_backend_dir(), self.KEY_FILE)

    def _get_or_create_cipher(self) -> Fernet:
        """Get or create the encryption cipher."""
        key_path = self._get_key_path()

        if os.path.exists(key_path):
            # Load existing key
            with open(key_path, 'rb') as f:
                key = f.read()
        else:
            # Generate new key
            key = Fernet.generate_key()
            # Save key to file with restricted permissions
            with open(key_path, 'wb') as f:
                f.write(key)
            # Set file permissions to read/write for owner only (0o600)
            os.chmod(key_path, 0o600)

        return Fernet(key)

    def _encrypt_value(self, value: str) -> str:
        """Encrypt a value and return base64-encoded string."""
        if not value:
            return ''
        encrypted = self._cipher.encrypt(value.encode())
        return base64.b64encode(encrypted).decode()

    def _decrypt_value(self, encrypted_value: str) -> str:
        """Decrypt a base64-encoded encrypted value."""
        if not encrypted_value:
            return ''
        try:
            encrypted = base64.b64decode(encrypted_value.encode())
            decrypted = self._cipher.decrypt(encrypted)
            return decrypted.decode()
        except Exception:
            # If decryption fails, return empty string (corrupted data)
            return ''

    def _load_from_file(self) -> None:
        """Load settings from the JSON file if it exists and decrypt API keys."""
        import json
        import logging
        logger = logging.getLogger(__name__)

        settings_path = self._get_settings_path()
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r') as f:
                    stored = json.load(f)
                    # Merge with defaults (in case new settings were added)
                    self._settings = {**self._default_settings, **stored}

                    needs_migration = False
                    # Decrypt API keys or migrate from plain text
                    for key in ['openai_api_key', 'cohere_api_key', 'openrouter_api_key', 'twilio_account_sid', 'twilio_auth_token', 'telegram_bot_token']:
                        if key in self._settings and self._settings[key]:
                            # Try to decrypt - if it fails, assume it's plain text
                            decrypted = self._decrypt_value(self._settings[key])
                            if not decrypted and self._settings[key]:
                                # Decryption failed but value exists - must be plain text
                                logger.info(f"Migrating {key} from plain text to encrypted format")
                                needs_migration = True
                                # Keep plain text in memory, it will be encrypted on next save
                            else:
                                # Successfully decrypted
                                self._settings[key] = decrypted

                    # If we detected plain text keys, save immediately to encrypt them
                    if needs_migration:
                        logger.info("Migrating plain text API keys to encrypted format")
                        self._save_to_file()

                    logger.info(f"Loaded settings from {settings_path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load settings from {settings_path}: {e}")
                self._settings = self._default_settings.copy()
        else:
            # Try to restore from PostgreSQL backup
            if not self._load_from_postgres():
                logger.info(f"No settings file found at {settings_path}, using defaults")

    def _load_from_postgres(self) -> bool:
        """Try to restore settings from PostgreSQL backup. Returns True if successful."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            from core.dependencies import is_postgres_available
            if not is_postgres_available():
                return False
            from core.database import SessionLocal
            from models.db_models import DBSetting
            db = SessionLocal()
            try:
                rows = db.query(DBSetting).all()
                if not rows:
                    return False
                restored = {row.key: row.value for row in rows}
                self._settings = {**self._default_settings, **restored}
                # Decrypt API keys
                for key in ['openai_api_key', 'cohere_api_key', 'openrouter_api_key',
                            'twilio_account_sid', 'twilio_auth_token', 'telegram_bot_token']:
                    if key in self._settings and self._settings[key]:
                        decrypted = self._decrypt_value(self._settings[key])
                        if decrypted:
                            self._settings[key] = decrypted
                logger.info(f"Restored {len(restored)} settings from PostgreSQL backup")
                self._save_to_file()  # Regenerate settings.json
                return True
            except Exception as e:
                logger.warning(f"Failed to restore settings from PostgreSQL: {e}")
                return False
            finally:
                db.close()
        except Exception:
            return False

    def _sync_to_postgres(self, settings_to_save: dict) -> None:
        """Sync settings to PostgreSQL as backup (best-effort, non-blocking)."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            from core.dependencies import is_postgres_available
            if not is_postgres_available():
                return
            from core.database import SessionLocal
            from models.db_models import DBSetting
            db = SessionLocal()
            try:
                for key, value in settings_to_save.items():
                    existing = db.query(DBSetting).filter_by(key=key).first()
                    if existing:
                        existing.value = str(value)
                    else:
                        db.add(DBSetting(key=key, value=str(value)))
                db.commit()
                logger.info("Synced settings to PostgreSQL backup")
            except Exception as e:
                db.rollback()
                logger.warning(f"Failed to sync settings to PostgreSQL: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Cannot sync to PostgreSQL: {e}")

    def _save_to_file(self) -> None:
        """Save current settings to the JSON file with encrypted API keys."""
        import json
        import logging
        logger = logging.getLogger(__name__)

        settings_path = self._get_settings_path()
        try:
            # Create a copy for saving with encrypted API keys
            settings_to_save = self._settings.copy()

            # Encrypt API keys before saving
            for key in ['openai_api_key', 'cohere_api_key', 'openrouter_api_key', 'twilio_account_sid', 'twilio_auth_token', 'telegram_bot_token']:
                if key in settings_to_save and settings_to_save[key]:
                    settings_to_save[key] = self._encrypt_value(settings_to_save[key])

            with open(settings_path, 'w') as f:
                json.dump(settings_to_save, f, indent=2)
            logger.info(f"Saved settings to {settings_path} with encrypted API keys")

            # Sync to PostgreSQL backup
            self._sync_to_postgres(settings_to_save)
        except IOError as e:
            logger.error(f"Failed to save settings to {settings_path}: {e}")

    def get(self, key: str, default: any = None) -> Optional[str]:
        """Get a setting value by key with optional default."""
        return self._settings.get(key, default)

    def get_all(self) -> Dict[str, str]:
        """Get all settings."""
        return self._settings.copy()

    def get_all_masked(self) -> Dict[str, str]:
        """Get all settings with API keys masked."""
        result = self._settings.copy()
        # Mask API keys - show first 4 and last 4 chars if long enough
        for key in ['openai_api_key', 'cohere_api_key', 'openrouter_api_key', 'twilio_account_sid', 'twilio_auth_token', 'telegram_bot_token']:
            value = result.get(key, '')
            if value and len(value) > 10:
                result[key] = value[:4] + '****' + value[-4:]
            elif value:
                result[key] = '****'
        return result

    def set(self, key: str, value: str) -> None:
        """Set a setting value and persist to file."""
        self._settings[key] = value
        self._save_to_file()

    def update(self, settings: Dict[str, str]) -> Dict[str, str]:
        """Update multiple settings at once. Returns updated settings."""
        for key, value in settings.items():
            if key in self._settings or key in ['openai_api_key', 'cohere_api_key', 'openrouter_api_key', 'twilio_account_sid', 'twilio_auth_token', 'twilio_whatsapp_number', 'telegram_bot_token', 'llm_model', 'embedding_model', 'chunking_llm_model', 'theme', 'enable_reranking', 'chunk_strategy', 'max_chunk_size', 'chunk_overlap', 'context_window_size', 'include_chat_history_in_search', 'custom_system_prompt', 'show_retrieved_chunks', 'strict_rag_mode', 'search_mode', 'hybrid_alpha', 'min_relevance_threshold', 'strict_relevance_threshold', 'enable_suggested_questions', 'enable_typewriter', 'enable_auto_backup', 'backup_time', 'backup_retention_days', 'require_backup_before_delete', 'top_k', 'enable_response_cache', 'cache_similarity_threshold', 'cache_ttl_hours']:
                self._settings[key] = value
        # Persist to file
        self._save_to_file()
        return self.get_all_masked()

    def has_openai_key(self) -> bool:
        """Check if OpenAI API key is configured."""
        key = self._settings.get('openai_api_key', '')
        return bool(key and len(key) > 0)

    def has_cohere_key(self) -> bool:
        """Check if Cohere API key is configured."""
        key = self._settings.get('cohere_api_key', '')
        return bool(key and len(key) > 0)

    def has_openrouter_key(self) -> bool:
        """Check if OpenRouter API key is configured."""
        key = self._settings.get('openrouter_api_key', '')
        return bool(key and len(key) > 0)

    def has_twilio_config(self) -> bool:
        """Check if Twilio is fully configured (SID, token, and WhatsApp number)."""
        sid = self._settings.get('twilio_account_sid', '')
        token = self._settings.get('twilio_auth_token', '')
        number = self._settings.get('twilio_whatsapp_number', '')
        return bool(sid and token and number)

    def has_telegram_token(self) -> bool:
        """Check if Telegram Bot Token is configured (Feature #306)."""
        token = self._settings.get('telegram_bot_token', '')
        return bool(token and len(token) > 0)

    def ensure_db_sync(self) -> None:
        """Sync current settings to PostgreSQL. Called after DB is confirmed available at startup."""
        import logging
        logger = logging.getLogger(__name__)
        settings_to_save = self._settings.copy()
        for key in ['openai_api_key', 'cohere_api_key', 'openrouter_api_key',
                    'twilio_account_sid', 'twilio_auth_token', 'telegram_bot_token']:
            if key in settings_to_save and settings_to_save[key]:
                settings_to_save[key] = self._encrypt_value(settings_to_save[key])
        self._sync_to_postgres(settings_to_save)
        logger.info("Initial settings sync to PostgreSQL completed")

    def clear(self):
        """Reset all settings to defaults (for testing)."""
        self._settings = self._default_settings.copy()
        self._save_to_file()


# Global settings store instance
settings_store = SettingsStore()


class DocumentRowsStore:
    """
    In-memory storage for structured document rows (CSV/Excel data).
    Each row is stored as a dict and linked to a dataset_id (document ID).
    """

    def __init__(self):
        # Structure: {dataset_id: [{"row_id": 1, "data": {...}}, ...]}
        self._rows: Dict[str, List[Dict]] = {}
        self._row_counter: int = 0

    def add_rows(self, dataset_id: str, rows: List[Dict], schema: List[str]) -> int:
        """
        Add rows for a dataset.

        Args:
            dataset_id: The document ID this data belongs to
            rows: List of row dictionaries
            schema: Column names/headers

        Returns:
            Number of rows added
        """
        if dataset_id not in self._rows:
            self._rows[dataset_id] = []

        for row_data in rows:
            self._row_counter += 1
            self._rows[dataset_id].append({
                "row_id": self._row_counter,
                "data": row_data
            })

        return len(rows)

    def get_rows(self, dataset_id: str) -> List[Dict]:
        """Get all rows for a dataset."""
        return self._rows.get(dataset_id, [])

    def get_all_datasets(self) -> Dict[str, int]:
        """Get all dataset IDs and their row counts."""
        return {ds_id: len(rows) for ds_id, rows in self._rows.items()}

    def delete_dataset(self, dataset_id: str) -> bool:
        """Delete all rows for a dataset."""
        if dataset_id in self._rows:
            del self._rows[dataset_id]
            return True
        return False

    def query_sql(self, dataset_id: str, query_func) -> List[Dict]:
        """
        Execute a query function on the dataset rows.

        Args:
            dataset_id: The dataset to query
            query_func: A function that takes list of rows and returns filtered/transformed data

        Returns:
            Query results
        """
        rows = self.get_rows(dataset_id)
        return query_func(rows)

    def get_schema(self, dataset_id: str) -> List[str]:
        """Get column names from first row."""
        rows = self.get_rows(dataset_id)
        if rows and len(rows) > 0:
            return list(rows[0]["data"].keys())
        return []

    def aggregate(self, dataset_id: str, column: str, operation: str) -> Optional[float]:
        """
        Perform aggregation on a column.

        Args:
            dataset_id: The dataset to query
            column: Column name to aggregate
            operation: 'sum', 'avg', 'min', 'max', 'count'

        Returns:
            Aggregated value or None if column not found
        """
        rows = self.get_rows(dataset_id)
        if not rows:
            return None

        values = []
        for row in rows:
            val = row["data"].get(column)
            if val is not None:
                try:
                    # Try to convert to float for numeric operations
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

    def clear(self):
        """Clear all rows (for testing)."""
        self._rows.clear()
        self._row_counter = 0


# Global document rows store instance
document_rows_store = DocumentRowsStore()


# Import the PostgreSQL-backed embedding store at module level
# This is imported at the end to avoid circular dependencies
def _get_embedding_store():
    """Lazy import of embedding store to avoid circular dependencies."""
    from services.embedding_store import embedding_store as _store
    return _store

# Create a module-level reference that will be initialized on first access
class _EmbeddingStoreProxy:
    """Proxy to lazily initialize the embedding store."""
    def __init__(self):
        self._store = None

    def _ensure_initialized(self):
        if self._store is None:
            self._store = _get_embedding_store()
        return self._store

    def __getattr__(self, name):
        return getattr(self._ensure_initialized(), name)

embedding_store = _EmbeddingStoreProxy()
