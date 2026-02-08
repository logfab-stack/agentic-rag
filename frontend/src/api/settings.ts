/**
 * Settings API client for the Agentic RAG System
 */

const API_BASE = '/api';

/**
 * Application settings response from backend
 */
export interface SettingsResponse {
  openai_api_key: string;
  cohere_api_key: string;
  openrouter_api_key: string;
  llm_model: string;
  embedding_model: string;
  chunking_llm_model: string;
  theme: string;
  enable_reranking: boolean;
  openai_api_key_set: boolean;
  cohere_api_key_set: boolean;
  openrouter_api_key_set: boolean;
  // Twilio/WhatsApp configuration
  twilio_account_sid: string;
  twilio_auth_token: string;
  twilio_whatsapp_number: string;
  twilio_configured: boolean;
  chunk_strategy: string;
  max_chunk_size: number;
  chunk_overlap: number;
  // Conversation context configuration
  context_window_size: number;
  // Chat history search (Feature #161)
  include_chat_history_in_search: boolean;
  // Custom system prompt (Feature #179)
  custom_system_prompt: string;
  // RAG hallucination validation (Feature #181)
  show_retrieved_chunks: boolean;
  // RAG relevance thresholds (Feature #182)
  strict_rag_mode: boolean;
  // Hybrid search (Feature #186)
  search_mode: string;  // "vector_only", "bm25_only", or "hybrid"
  hybrid_alpha: number;  // 0.0-1.0, weight balance between BM25 and vector search
  // Configurable relevance thresholds (Feature #194)
  min_relevance_threshold: number;  // 0.1-0.9, threshold for normal mode
  strict_relevance_threshold: number;  // 0.1-0.9, threshold for strict mode
  // Suggested questions (Feature #199)
  enable_suggested_questions: boolean;  // Show suggested questions for documents
  // Typewriter effect (Feature #201)
  enable_typewriter: boolean;  // Enable typewriter animation for AI responses
  // Feature #226 + Feature #305: Embedding model change warning
  embedding_model_warning?: string;  // Warning message if embedding model changed with existing embeddings
  // Telegram Bot configuration (Feature #306)
  telegram_bot_token_set: boolean;
  // Advanced RAG settings
  keyword_boost_weight: number;
  enable_entity_extraction: boolean;
  top_k: number;
  min_context_chars_for_generation: number;
  default_language: string;
  // Semantic response cache (Feature #352)
  enable_response_cache: boolean;
  cache_similarity_threshold: number;
  cache_ttl_hours: number;
}

/**
 * Settings update request
 */
export interface SettingsUpdate {
  openai_api_key?: string;
  cohere_api_key?: string;
  openrouter_api_key?: string;
  llm_model?: string;
  embedding_model?: string;
  chunking_llm_model?: string;
  theme?: string;
  enable_reranking?: boolean;
  // Twilio/WhatsApp configuration
  twilio_account_sid?: string;
  twilio_auth_token?: string;
  twilio_whatsapp_number?: string;
  chunk_strategy?: string;
  max_chunk_size?: number;
  chunk_overlap?: number;
  // Conversation context configuration
  context_window_size?: number;
  // Chat history search (Feature #161)
  include_chat_history_in_search?: boolean;
  // Custom system prompt (Feature #179)
  custom_system_prompt?: string;
  // RAG hallucination validation (Feature #181)
  show_retrieved_chunks?: boolean;
  // RAG relevance thresholds (Feature #182)
  strict_rag_mode?: boolean;
  // Hybrid search (Feature #186)
  search_mode?: string;
  hybrid_alpha?: number;
  // Configurable relevance thresholds (Feature #194)
  min_relevance_threshold?: number;
  strict_relevance_threshold?: number;
  // Suggested questions (Feature #199)
  enable_suggested_questions?: boolean;
  // Typewriter effect (Feature #201)
  enable_typewriter?: boolean;
  // Semantic response cache (Feature #352)
  enable_response_cache?: boolean;
  cache_similarity_threshold?: number;
  cache_ttl_hours?: number;
}

/**
 * Fetch current application settings
 */
export async function fetchSettings(): Promise<SettingsResponse> {
  const response = await fetch(`${API_BASE}/settings/`);
  if (!response.ok) {
    throw new Error(`Failed to fetch settings: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Update application settings
 */
export async function updateSettings(updates: SettingsUpdate): Promise<SettingsResponse> {
  const response = await fetch(`${API_BASE}/settings/`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(updates),
  });
  if (!response.ok) {
    throw new Error(`Failed to update settings: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Represents an Ollama model with its details
 */
export interface OllamaModel {
  name: string;
  value: string;  // The value to use for selection (e.g., "ollama:llama3")
  label: string;  // Human-readable label
  size?: string;
  family?: string;
  parameter_size?: string;
  is_embedding: boolean;
}

/**
 * Response from the Ollama models endpoint
 */
export interface OllamaModelsResponse {
  available: boolean;
  models: OllamaModel[];
  embedding_models: OllamaModel[];
  error?: string;
}

/**
 * Fetch available Ollama models
 *
 * Queries the backend which in turn queries the local Ollama installation
 * to detect installed models.
 */
export async function fetchOllamaModels(): Promise<OllamaModelsResponse> {
  try {
    const response = await fetch(`${API_BASE}/settings/models/ollama`);
    if (!response.ok) {
      throw new Error(`Failed to fetch Ollama models: ${response.statusText}`);
    }
    return response.json();
  } catch (error) {
    // Return a default response indicating Ollama is not available
    return {
      available: false,
      models: [],
      embedding_models: [],
      error: error instanceof Error ? error.message : 'Failed to connect to backend'
    };
  }
}

/**
 * Backup status response from backend
 */
export interface BackupStatusResponse {
  documents: number;
  collections: number;
  conversations: number;
  messages: number;
  uploaded_files_count: number;
  uploaded_files_size_bytes: number;
  uploaded_files_size_human: string;
}

/**
 * Fetch backup status (data counts)
 */
export async function fetchBackupStatus(): Promise<BackupStatusResponse> {
  const response = await fetch(`${API_BASE}/backup/status`);
  if (!response.ok) {
    throw new Error(`Failed to fetch backup status: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Create and download a full backup
 *
 * Triggers the backup creation and downloads the resulting ZIP file.
 */
export async function createBackup(): Promise<void> {
  const response = await fetch(`${API_BASE}/backup/`, {
    method: 'POST',
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to create backup: ${errorText}`);
  }

  // Get filename from Content-Disposition header or use default
  const contentDisposition = response.headers.get('Content-Disposition');
  let filename = 'rag_backup.zip';
  if (contentDisposition) {
    const match = contentDisposition.match(/filename="?([^";\n]+)"?/);
    if (match) {
      filename = match[1];
    }
  }

  // Download the file
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);
}

/**
 * Response from restore operation
 */
export interface RestoreResponse {
  success: boolean;
  message: string;
  documents_restored: number;
  collections_restored: number;
  conversations_restored: number;
  messages_restored: number;
  files_restored: number;
}

/**
 * Restore data from a backup file
 *
 * Uploads a backup ZIP file and restores all data from it.
 * Warning: This will clear all existing data before restoring.
 */
export async function restoreBackup(file: File): Promise<RestoreResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE}/backup/restore`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to restore backup' }));
    throw new Error(errorData.detail || 'Failed to restore backup');
  }

  return response.json();
}

/**
 * Represents an OpenRouter model with its details
 */
export interface OpenRouterModel {
  id: string;
  value: string;  // The value to use for selection (e.g., "openrouter:anthropic/claude-3.5-sonnet")
  label: string;  // Human-readable label
  context_length: number;
  pricing: {
    prompt: string;
    completion: string;
  };
}

/**
 * Response from the OpenRouter models endpoint
 */
export interface OpenRouterModelsResponse {
  available: boolean;
  models: OpenRouterModel[];
  error?: string;
}

/**
 * Fetch available OpenRouter models
 *
 * Queries the backend which in turn queries the OpenRouter API
 * to fetch available models.
 */
export async function fetchOpenRouterModels(): Promise<OpenRouterModelsResponse> {
  try {
    const response = await fetch(`${API_BASE}/settings/models/openrouter`);
    if (!response.ok) {
      throw new Error(`Failed to fetch OpenRouter models: ${response.statusText}`);
    }
    return response.json();
  } catch (error) {
    // Return a default response indicating OpenRouter is not available
    return {
      available: false,
      models: [],
      error: error instanceof Error ? error.message : 'Failed to connect to backend'
    };
  }
}

/**
 * Test connection response from backend
 */
export interface TestConnectionResponse {
  success: boolean;
  message: string;
  provider: string;
}

/**
 * Test connection to an API provider
 *
 * Tests if the configured API key is valid and the service is reachable.
 *
 * @param provider - The provider to test ("openrouter", "openai", "cohere", "ollama", "twilio")
 * @returns Test connection result with success status and message
 */
export async function testConnection(provider: string): Promise<TestConnectionResponse> {
  const response = await fetch(`${API_BASE}/settings/test-connection`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ provider }),
  });

  if (!response.ok) {
    throw new Error(`Failed to test connection: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Response from embedding health check
 */
export interface EmbeddingHealthCheckResponse {
  available: boolean;
  model: string;
  provider: string;
  message: string;
}

/**
 * Check if the configured embedding model is reachable and functional.
 *
 * This should be called BEFORE starting a document upload to warn the user
 * if embeddings won't be generated for unstructured documents.
 *
 * @returns Health check result with availability status and message
 */
export async function checkEmbeddingHealth(): Promise<EmbeddingHealthCheckResponse> {
  try {
    const response = await fetch('/api/embeddings/health-check');
    if (!response.ok) {
      return {
        available: false,
        model: 'unknown',
        provider: 'unknown',
        message: `Health check failed: ${response.statusText}`,
      };
    }
    return response.json();
  } catch (error) {
    return {
      available: false,
      model: 'unknown',
      provider: 'unknown',
      message: error instanceof Error ? error.message : 'Failed to check embedding model',
    };
  }
}

/**
 * Response from database reset preview (Feature #214)
 */
export interface ResetDatabasePreviewResponse {
  documents_count: number;
  collections_count: number;
  conversations_count: number;
  messages_count: number;
  files_count: number;
  total_size_human: string;
  confirmation_token: string;
  expires_at: string;
}

/**
 * Request body for database reset with double confirmation (Feature #214)
 */
export interface ResetDatabaseRequest {
  confirmation_phrase: string;  // Must be "DELETE ALL"
  confirmation_token: string;   // Token from preview endpoint
}

/**
 * Response from database reset operation
 */
export interface ResetDatabaseResponse {
  success: boolean;
  message: string;
  documents_deleted: number;
  collections_deleted: number;
  conversations_deleted: number;
  messages_deleted: number;
  files_deleted: number;
  embeddings_deleted: number;
}

/**
 * Get a preview of what will be deleted and generate a confirmation token.
 *
 * Feature #214: Double confirmation for database reset.
 * Call this first, then use the returned token with resetDatabase().
 *
 * @returns Preview with counts and confirmation token
 */
export async function getResetDatabasePreview(): Promise<ResetDatabasePreviewResponse> {
  const response = await fetch(`${API_BASE}/settings/reset-database/preview`, {
    method: 'POST',
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to get reset preview' }));
    throw new Error(errorData.detail || 'Failed to get reset preview');
  }

  return response.json();
}

/**
 * Reset the entire database and delete all uploaded files.
 *
 * Feature #214: Double confirmation required.
 * Must call getResetDatabasePreview() first to get confirmation token.
 *
 * WARNING: This operation is DESTRUCTIVE and IRREVERSIBLE.
 * It will delete all documents, collections, conversations, messages, embeddings, and uploaded files.
 * Settings (API keys, theme, etc.) are preserved.
 *
 * @param confirmationPhrase Must be "DELETE ALL"
 * @param confirmationToken Token from getResetDatabasePreview()
 * @returns Reset operation result with counts of deleted items
 */
export async function resetDatabase(
  confirmationPhrase: string,
  confirmationToken: string
): Promise<ResetDatabaseResponse> {
  const response = await fetch(`${API_BASE}/settings/reset-database`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      confirmation_phrase: confirmationPhrase,
      confirmation_token: confirmationToken,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to reset database' }));
    throw new Error(errorData.detail || 'Failed to reset database');
  }

  return response.json();
}

// ============================================================
// System Prompt API (Feature #179)
// ============================================================

/**
 * System prompt response from backend
 */
export interface SystemPromptResponse {
  custom_prompt: string;
  default_prompt: string;
  active_prompt: string;
  is_custom: boolean;
  character_count: number;
  preset_name?: string;
}

/**
 * System prompt preset
 */
export interface SystemPromptPreset {
  name: string;
  label: string;
  text: string;
  description: string;
  character_count: number;
}

/**
 * System prompt test response
 */
export interface SystemPromptTestResponse {
  success: boolean;
  response: string;
  prompt_used: string;
  error?: string;
}

/**
 * Get the current system prompt configuration
 */
export async function getSystemPrompt(): Promise<SystemPromptResponse> {
  const response = await fetch(`${API_BASE}/settings/system-prompt`);
  if (!response.ok) {
    throw new Error(`Failed to fetch system prompt: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Update the custom system prompt
 */
export async function updateSystemPrompt(customPrompt: string): Promise<SystemPromptResponse> {
  const response = await fetch(`${API_BASE}/settings/system-prompt`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ custom_prompt: customPrompt }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to update system prompt' }));
    throw new Error(errorData.detail || 'Failed to update system prompt');
  }

  return response.json();
}

/**
 * Get available system prompt presets
 */
export async function getSystemPromptPresets(): Promise<{ presets: SystemPromptPreset[] }> {
  const response = await fetch(`${API_BASE}/settings/system-prompt/presets`);
  if (!response.ok) {
    throw new Error(`Failed to fetch presets: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Test a system prompt with a test message
 */
export async function testSystemPrompt(
  testMessage: string,
  promptToTest?: string
): Promise<SystemPromptTestResponse> {
  const response = await fetch(`${API_BASE}/settings/system-prompt/test`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      test_message: testMessage,
      prompt_to_test: promptToTest,
    }),
  });

  if (!response.ok) {
    throw new Error(`Failed to test system prompt: ${response.statusText}`);
  }

  return response.json();
}


// ============================================================
// RAG Self-Test API (Feature #198)
// ============================================================

/**
 * Result of testing a single RAG component
 */
export interface ComponentTestResult {
  component: string;  // "embedding", "vector_store", "reranking", "llm"
  passed: boolean;
  message: string;
  details?: Record<string, unknown>;
}

/**
 * Result of testing RAG on a single document
 */
export interface DocumentTestResult {
  document_id: string;
  document_name: string;
  test_query: string;
  chunks_retrieved: number;
  reranking_applied: boolean;
  llm_response_generated: boolean;
  passed: boolean;
  error?: string;
}

/**
 * Full response from the self-test endpoint
 */
export interface SelfTestResponse {
  success: boolean;
  message: string;
  overall_status: 'pass' | 'partial' | 'fail';
  component_tests: ComponentTestResult[];
  document_tests: DocumentTestResult[];
  summary: {
    components_passed: number;
    components_total: number;
    documents_tested: number;
    documents_passed: number;
  };
}

/**
 * Run automated self-test of the RAG pipeline.
 *
 * Tests all components: embedding model, vector store, reranking, and LLM.
 * Also tests RAG retrieval on uploaded documents.
 *
 * @returns Self-test results with pass/fail status for each component
 */
export async function runSelfTest(): Promise<SelfTestResponse> {
  const response = await fetch(`${API_BASE}/settings/self-test`, {
    method: 'POST',
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to run self-test' }));
    throw new Error(errorData.detail || 'Failed to run self-test');
  }

  return response.json();
}


// ============================================================
// Automatic Backup Scheduler API (Feature #221)
// ============================================================

/**
 * Response from automatic backup status endpoint
 */
export interface AutoBackupStatusResponse {
  enabled: boolean;
  backup_hour: number;
  backup_minute: number;
  backup_time_formatted: string;
  last_backup_time: string | null;
  last_backup_status: string;  // "success", "failed", "never"
  last_backup_error: string | null;
  next_backup_time: string | null;
  backup_in_progress: boolean;
  daily_retention: number;
  weekly_retention: number;
  backups_dir: string;
}

/**
 * Request to configure automatic backup
 */
export interface AutoBackupConfigRequest {
  enabled: boolean;
  backup_hour?: number;  // 0-23
  backup_minute?: number;  // 0-59
}

/**
 * Information about a single automatic backup
 */
export interface AutoBackupInfo {
  name: string;
  timestamp: string;
  created_at: string;
  is_weekly: boolean;
  total_size_bytes: number;
  total_size_human: string;
  path: string;
  database?: {
    success: boolean;
    size_bytes: number;
    size_human: string;
  };
  files?: {
    files_copied: number;
    total_bytes: number;
    size_human: string;
  };
}

/**
 * Response from listing automatic backups
 */
export interface AutoBackupListResponse {
  backups: AutoBackupInfo[];
  count: number;
}

/**
 * Response from running a backup immediately
 */
export interface RunBackupResponse {
  success: boolean;
  message: string;
  backup_path?: string;
  error?: string;
}

/**
 * Get the current status of automatic backup scheduler
 */
export async function getAutoBackupStatus(): Promise<AutoBackupStatusResponse> {
  const response = await fetch(`${API_BASE}/backup/auto/status`);
  if (!response.ok) {
    throw new Error(`Failed to get backup status: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Configure automatic backup settings
 */
export async function configureAutoBackup(config: AutoBackupConfigRequest): Promise<AutoBackupStatusResponse> {
  const response = await fetch(`${API_BASE}/backup/auto/configure`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(config),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to configure backup' }));
    throw new Error(errorData.detail || 'Failed to configure backup');
  }

  return response.json();
}

/**
 * Run an automatic backup immediately
 */
export async function runAutoBackupNow(): Promise<RunBackupResponse> {
  const response = await fetch(`${API_BASE}/backup/auto/run`, {
    method: 'POST',
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to run backup' }));
    throw new Error(errorData.detail || 'Failed to run backup');
  }

  return response.json();
}

/**
 * List all automatic backups
 */
export async function listAutoBackups(): Promise<AutoBackupListResponse> {
  const response = await fetch(`${API_BASE}/backup/auto/list`);
  if (!response.ok) {
    throw new Error(`Failed to list backups: ${response.statusText}`);
  }
  return response.json();
}


// ============================================================
// Pre-Destructive Backup Undo API (Feature #222)
// ============================================================

/**
 * Information about a pre-destructive backup
 */
export interface PreDestructiveBackupInfo {
  timestamp: string;
  created_at: string;
  operation: string;
  reason: string;
  documents_count: number;
  collections_count: number;
  files_count: number;
  total_file_bytes: number;
  path: string;
}

/**
 * Response from listing pre-destructive backups
 */
export interface PreDestructiveBackupListResponse {
  backups: PreDestructiveBackupInfo[];
  count: number;
  max_backups: number;
}

/**
 * Response from restore operation
 */
export interface PreDestructiveRestoreResponse {
  success: boolean;
  message: string;
  documents_restored: number;
  collections_restored: number;
  files_restored: number;
  note?: string;
  error?: string;
}

/**
 * Response from getting the last destructive backup
 */
export interface LastDestructiveBackupResponse {
  available: boolean;
  is_recent?: boolean;
  backup?: PreDestructiveBackupInfo;
  message: string;
}

/**
 * List all pre-destructive backups (Feature #222)
 *
 * Returns all backups created before destructive operations.
 */
export async function listPreDestructiveBackups(): Promise<PreDestructiveBackupListResponse> {
  const response = await fetch(`${API_BASE}/settings/pre-destructive-backups`);
  if (!response.ok) {
    throw new Error(`Failed to list pre-destructive backups: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Restore from a pre-destructive backup (Feature #222 - Undo operation)
 *
 * Restores documents, collections, and files from a backup.
 * Note: Embeddings need to be regenerated after restore.
 *
 * @param backupPath Path to the backup directory
 */
export async function restoreFromPreDestructiveBackup(
  backupPath: string
): Promise<PreDestructiveRestoreResponse> {
  const response = await fetch(`${API_BASE}/settings/pre-destructive-backups/restore`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ backup_path: backupPath }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to restore' }));
    throw new Error(errorData.detail || 'Failed to restore from backup');
  }

  return response.json();
}

/**
 * Get the most recent pre-destructive backup (Feature #222)
 *
 * Returns the most recent backup if available.
 * Useful for implementing "Undo" after a destructive operation.
 */
export async function getLastDestructiveBackup(): Promise<LastDestructiveBackupResponse> {
  const response = await fetch(`${API_BASE}/settings/last-destructive-backup`);
  if (!response.ok) {
    throw new Error(`Failed to get last backup: ${response.statusText}`);
  }
  return response.json();
}
