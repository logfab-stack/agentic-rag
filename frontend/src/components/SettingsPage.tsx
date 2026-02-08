/**
 * SettingsPage - Full page settings interface organized into sections
 *
 * This replaces the modal-based settings with a full page layout featuring:
 * - Section 1: API Keys (OpenAI, Cohere, OpenRouter with test buttons)
 * - Section 2: Model Selection (LLM, Embedding, Chunking LLM)
 * - Section 3: WhatsApp/Twilio Integration
 * - Section 4: RAG Configuration (chunking, overlap, context, etc.)
 * - Section 5: Appearance (Theme)
 * - Section 6: Backup & Restore
 * - Section 7: Danger Zone (Reset Database)
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Settings,
  Key,
  Brain,
  Phone,
  Sliders,
  Palette,
  HardDrive,
  AlertTriangle,
  Eye,
  EyeOff,
  RefreshCw,
  Loader2,
  Check,
  CheckCircle2,
  XCircle,
  Save,
  Download,
  Upload,
  Trash2,
  FileText,
  FolderOpen,
  MessageSquare,
  Sun,
  Moon,
  Monitor,
  Bot,
  RotateCcw,
  Play,
  ChevronDown,
  Activity,
  Server,
  Clock,
  Calendar,
  X,
  Send,
  BookOpen,
  Zap,
  Database,
  Search,
  Shield
} from 'lucide-react'
import {
  fetchOllamaModels,
  OllamaModel,
  fetchOpenRouterModels,
  OpenRouterModel,
  fetchSettings,
  updateSettings,
  fetchBackupStatus,
  createBackup,
  restoreBackup,
  BackupStatusResponse,
  RestoreResponse,
  testConnection,
  getResetDatabasePreview,
  resetDatabase,
  ResetDatabaseResponse,
  ResetDatabasePreviewResponse,
  checkEmbeddingHealth,
  EmbeddingHealthCheckResponse,
  getSystemPrompt,
  updateSystemPrompt,
  getSystemPromptPresets,
  testSystemPrompt,
  SystemPromptResponse,
  SystemPromptPreset,
  SystemPromptTestResponse,
  runSelfTest,
  SelfTestResponse,
  ComponentTestResult,
  DocumentTestResult,
  // Automatic Backup API (Feature #221)
  getAutoBackupStatus,
  configureAutoBackup,
  runAutoBackupNow,
  listAutoBackups,
  AutoBackupStatusResponse,
  AutoBackupListResponse,
  // Pre-Destructive Backup Undo API (Feature #222)
  getLastDestructiveBackup,
  restoreFromPreDestructiveBackup,
  LastDestructiveBackupResponse,
  PreDestructiveRestoreResponse
} from '../api/settings'
import { useToast } from './Toast'
import { FeedbackAnalytics } from './FeedbackAnalytics'
import { NgrokStatus } from './NgrokStatus'
import { TelegramWebhookStatus } from './TelegramWebhookStatus'

interface Settings {
  openai_api_key: string
  cohere_api_key: string
  openrouter_api_key: string
  llm_model: string
  embedding_model: string
  chunking_llm_model: string
  theme: 'light' | 'dark' | 'system'
  enable_reranking: boolean
  openai_api_key_set?: boolean
  cohere_api_key_set?: boolean
  openrouter_api_key_set?: boolean
  twilio_account_sid: string
  twilio_auth_token: string
  twilio_whatsapp_number: string
  twilio_configured?: boolean
  // Telegram Bot configuration (Feature #306)
  telegram_bot_token: string
  telegram_bot_token_set?: boolean
  chunk_strategy: 'agentic' | 'semantic' | 'paragraph' | 'fixed'
  max_chunk_size: number
  chunk_overlap: number
  context_window_size: number
  include_chat_history_in_search: boolean
  custom_system_prompt: string
  // RAG hallucination validation (Feature #181)
  show_retrieved_chunks: boolean
  // RAG relevance thresholds (Feature #182)
  strict_rag_mode: boolean
  // Hybrid search (Feature #186)
  search_mode: string
  hybrid_alpha: number
  // Configurable relevance thresholds (Feature #194)
  min_relevance_threshold: number
  strict_relevance_threshold: number
  // Suggested questions (Feature #199)
  enable_suggested_questions: boolean
  // Typewriter effect (Feature #201)
  enable_typewriter: boolean
  // Pre-destructive backup (Feature #213)
  require_backup_before_delete: boolean
  // Keyword extraction for hybrid search (Feature #218)
  keyword_boost_weight: number
  enable_entity_extraction: boolean
  // Configurable top_k for RAG retrieval (Feature #230)
  top_k: number
  // Context validation guardrail (Feature #281)
  min_context_chars_for_generation: number
  // Default language preference (Feature #317)
  default_language: 'it' | 'en' | 'auto' | 'fr' | 'es' | 'de' | 'pt'
  // Semantic response cache (Feature #352)
  enable_response_cache: boolean
  cache_similarity_threshold: number
  cache_ttl_hours: number
}

const DEFAULT_SETTINGS: Settings = {
  openai_api_key: '',
  cohere_api_key: '',
  openrouter_api_key: '',
  llm_model: 'gpt-4o',
  embedding_model: 'text-embedding-3-small',
  chunking_llm_model: '',
  theme: 'system',
  enable_reranking: true,
  twilio_account_sid: '',
  twilio_auth_token: '',
  twilio_whatsapp_number: '',
  // Telegram Bot configuration (Feature #306)
  telegram_bot_token: '',
  chunk_strategy: 'semantic',
  max_chunk_size: 2000,
  chunk_overlap: 200,
  context_window_size: 20,
  include_chat_history_in_search: false,
  custom_system_prompt: '',
  show_retrieved_chunks: false,
  strict_rag_mode: false,
  search_mode: 'hybrid',
  hybrid_alpha: 0.5,
  min_relevance_threshold: 0.4,
  strict_relevance_threshold: 0.6,
  enable_suggested_questions: true,
  enable_typewriter: true,
  require_backup_before_delete: true,
  keyword_boost_weight: 0.15,
  enable_entity_extraction: true,
  top_k: 10,
  min_context_chars_for_generation: 500,
  default_language: 'it',
  enable_response_cache: true,
  cache_similarity_threshold: 0.95,
  cache_ttl_hours: 24
}

// Recommended chunking LLM models
const CHUNKING_LLM_OPTIONS = [
  { value: '', label: 'Same as Chat LLM (default)' },
  { value: 'openrouter:google/gemini-2.0-flash-001', label: 'Gemini 2.0 Flash (Recommended - fast & cheap)' },
  { value: 'openrouter:openai/gpt-4o-mini', label: 'GPT-4o Mini via OpenRouter' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini (OpenAI direct)' },
]

// API key validation
interface ApiKeyValidation {
  isValid: boolean
  error: string | null
}

const validateOpenAIKey = (key: string): ApiKeyValidation => {
  if (!key || key.trim() === '') return { isValid: true, error: null }
  const trimmedKey = key.trim()
  if (!trimmedKey.startsWith('sk-')) {
    return { isValid: false, error: 'OpenAI API keys must start with "sk-"' }
  }
  if (trimmedKey.length < 40) {
    return { isValid: false, error: 'OpenAI API key is too short' }
  }
  if (!/^sk-[a-zA-Z0-9_-]+$/.test(trimmedKey)) {
    return { isValid: false, error: 'OpenAI API key contains invalid characters' }
  }
  return { isValid: true, error: null }
}

const validateCohereKey = (key: string): ApiKeyValidation => {
  if (!key || key.trim() === '') return { isValid: true, error: null }
  const trimmedKey = key.trim()
  if (trimmedKey.length < 20) {
    return { isValid: false, error: 'Cohere API key is too short' }
  }
  if (!/^[a-zA-Z0-9_-]+$/.test(trimmedKey)) {
    return { isValid: false, error: 'Cohere API key contains invalid characters' }
  }
  return { isValid: true, error: null }
}

const validateOpenRouterKey = (key: string): ApiKeyValidation => {
  if (!key || key.trim() === '') return { isValid: true, error: null }
  const trimmedKey = key.trim()
  if (!trimmedKey.startsWith('sk-or-')) {
    return { isValid: false, error: 'OpenRouter API keys must start with "sk-or-"' }
  }
  if (trimmedKey.length < 40) {
    return { isValid: false, error: 'OpenRouter API key is too short' }
  }
  if (!/^sk-or-[a-zA-Z0-9_-]+$/.test(trimmedKey)) {
    return { isValid: false, error: 'OpenRouter API key contains invalid characters' }
  }
  return { isValid: true, error: null }
}

// Static models
const OPENAI_LLM_MODELS = [
  { value: 'gpt-4o', label: 'GPT-4o (Recommended)', provider: 'openai' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini (Faster, cheaper)', provider: 'openai' },
  { value: 'gpt-4-turbo', label: 'GPT-4 Turbo', provider: 'openai' },
  { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo (Budget)', provider: 'openai' },
]

const OPENAI_EMBEDDING_MODELS = [
  { value: 'text-embedding-3-small', label: 'text-embedding-3-small (Recommended)', provider: 'openai' },
  { value: 'text-embedding-3-large', label: 'text-embedding-3-large (Higher quality)', provider: 'openai' },
  { value: 'text-embedding-ada-002', label: 'text-embedding-ada-002 (Legacy)', provider: 'openai' },
]

// OpenRouter embedding models - shown when OpenRouter API key is configured
const OPENROUTER_EMBEDDING_MODELS = [
  { value: 'openrouter:qwen/qwen3-embedding-8b', label: 'Qwen3 Embedding 8B (Recommended - fast)', provider: 'openrouter', pricing: '$0.015/1M tokens' },
  { value: 'openrouter:openai/text-embedding-3-small', label: 'OpenAI text-embedding-3-small via OpenRouter', provider: 'openrouter', pricing: '$0.02/1M tokens' },
  { value: 'openrouter:openai/text-embedding-3-large', label: 'OpenAI text-embedding-3-large via OpenRouter', provider: 'openrouter', pricing: '$0.13/1M tokens' },
  { value: 'openrouter:cohere/embed-english-v3.0', label: 'Cohere Embed English v3.0', provider: 'openrouter', pricing: '$0.10/1M tokens' },
  { value: 'openrouter:voyage/voyage-3.5-lite', label: 'Voyage 3.5 Lite (High quality)', provider: 'openrouter', pricing: '$0.02/1M tokens' },
]

const THEME_OPTIONS = [
  { value: 'light' as const, label: 'Light', icon: Sun },
  { value: 'dark' as const, label: 'Dark', icon: Moon },
  { value: 'system' as const, label: 'System', icon: Monitor },
]

// Helper function to extract provider and group OpenRouter models
const extractProvider = (modelId: string): string => {
  const parts = modelId.split('/')
  if (parts.length > 1) {
    const provider = parts[0]
    return provider.charAt(0).toUpperCase() + provider.slice(1)
  }
  return 'Other'
}

interface GroupedModels {
  provider: string
  models: OpenRouterModel[]
}

const filterAndGroupModels = (
  models: OpenRouterModel[],
  searchTerm: string
): { groups: GroupedModels[]; totalMatches: number; truncated: boolean } => {
  const filtered = searchTerm.trim() === ''
    ? models
    : models.filter(m =>
        m.label.toLowerCase().includes(searchTerm.toLowerCase()) ||
        m.value.toLowerCase().includes(searchTerm.toLowerCase())
      )

  const totalMatches = filtered.length
  const maxResults = 50
  const truncated = totalMatches > maxResults
  const limited = truncated ? filtered.slice(0, maxResults) : filtered

  const groupedMap = limited.reduce((acc, model) => {
    const provider = extractProvider(model.value)
    if (!acc[provider]) acc[provider] = []
    acc[provider].push(model)
    return acc
  }, {} as Record<string, OpenRouterModel[]>)

  const groups = Object.keys(groupedMap)
    .sort()
    .map(provider => ({ provider, models: groupedMap[provider] }))

  return { groups, totalMatches, truncated }
}

export function SettingsPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()

  // Settings state
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS)
  const [isSaving, setIsSaving] = useState(false)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)

  // Visibility toggles for sensitive fields
  const [showOpenAIKey, setShowOpenAIKey] = useState(false)
  const [showCohereKey, setShowCohereKey] = useState(false)
  const [showOpenRouterKey, setShowOpenRouterKey] = useState(false)
  const [showTwilioSid, setShowTwilioSid] = useState(false)
  const [showTwilioToken, setShowTwilioToken] = useState(false)
  const [showTelegramToken, setShowTelegramToken] = useState(false)

  // API key validation states
  const [openAIKeyError, setOpenAIKeyError] = useState<string | null>(null)
  const [cohereKeyError, setCohereKeyError] = useState<string | null>(null)
  const [openRouterKeyError, setOpenRouterKeyError] = useState<string | null>(null)

  // Ollama models state
  const [ollamaLLMModels, setOllamaLLMModels] = useState<OllamaModel[]>([])
  const [ollamaEmbeddingModels, setOllamaEmbeddingModels] = useState<OllamaModel[]>([])
  const [ollamaAvailable, setOllamaAvailable] = useState(false)
  const [ollamaError, setOllamaError] = useState<string | null>(null)
  const [isLoadingOllama, setIsLoadingOllama] = useState(false)

  // OpenRouter models state
  const [openRouterModels, setOpenRouterModels] = useState<OpenRouterModel[]>([])
  const [openRouterAvailable, setOpenRouterAvailable] = useState(false)
  const [openRouterError, setOpenRouterError] = useState<string | null>(null)
  const [isLoadingOpenRouter, setIsLoadingOpenRouter] = useState(false)
  const [modelSearch, setModelSearch] = useState('')

  // Backup state
  const [backupStatus, setBackupStatus] = useState<BackupStatusResponse | null>(null)
  const [isLoadingBackup, setIsLoadingBackup] = useState(false)
  const [isCreatingBackup, setIsCreatingBackup] = useState(false)

  // Automatic backup state (Feature #221)
  const [autoBackupStatus, setAutoBackupStatus] = useState<AutoBackupStatusResponse | null>(null)
  const [autoBackupList, setAutoBackupList] = useState<AutoBackupListResponse | null>(null)
  const [isLoadingAutoBackup, setIsLoadingAutoBackup] = useState(false)
  const [isRunningAutoBackup, setIsRunningAutoBackup] = useState(false)
  const [autoBackupHour, setAutoBackupHour] = useState(2)
  const [autoBackupMinute, setAutoBackupMinute] = useState(0)

  // Restore state
  const [isRestoring, setIsRestoring] = useState(false)
  const [restoreError, setRestoreError] = useState<string | null>(null)
  const [restoreSuccess, setRestoreSuccess] = useState<RestoreResponse | null>(null)
  const [showRestoreConfirm, setShowRestoreConfirm] = useState(false)
  const [selectedRestoreFile, setSelectedRestoreFile] = useState<File | null>(null)
  const restoreFileInputRef = useRef<HTMLInputElement>(null)

  // Test connection state
  const [testingConnection, setTestingConnection] = useState<{
    openai: boolean
    cohere: boolean
    openrouter: boolean
    ollama: boolean
    twilio: boolean
    telegram: boolean
  }>({
    openai: false,
    cohere: false,
    openrouter: false,
    ollama: false,
    twilio: false,
    telegram: false,
  })
  const [connectionStatus, setConnectionStatus] = useState<{
    openai: { success: boolean; message: string } | null
    cohere: { success: boolean; message: string } | null
    openrouter: { success: boolean; message: string } | null
    ollama: { success: boolean; message: string } | null
    twilio: { success: boolean; message: string } | null
    telegram: { success: boolean; message: string } | null
  }>({
    openai: null,
    cohere: null,
    openrouter: null,
    ollama: null,
    twilio: null,
    telegram: null,
  })

  // Embedding health state
  const [embeddingHealth, setEmbeddingHealth] = useState<EmbeddingHealthCheckResponse | null>(null)
  const [isCheckingEmbedding, setIsCheckingEmbedding] = useState(false)

  // Reset database state (Feature #214: Double confirmation)
  const [showResetConfirm, setShowResetConfirm] = useState(false)
  const [resetConfirmationText, setResetConfirmationText] = useState('')
  const [isResetting, setIsResetting] = useState(false)
  const [resetError, setResetError] = useState<string | null>(null)
  const [resetSuccess, setResetSuccess] = useState<ResetDatabaseResponse | null>(null)
  const [resetPreview, setResetPreview] = useState<ResetDatabasePreviewResponse | null>(null)
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)
  const [countdownSeconds, setCountdownSeconds] = useState(0)  // 10-second countdown (Feature #223)

  // Undo destructive operation state (Feature #222)
  const [lastBackup, setLastBackup] = useState<LastDestructiveBackupResponse | null>(null)
  const [isUndoing, setIsUndoing] = useState(false)
  const [undoResult, setUndoResult] = useState<PreDestructiveRestoreResponse | null>(null)
  const [showUndoOption, setShowUndoOption] = useState(false)
  const [undoCountdown, setUndoCountdown] = useState(0)  // Countdown before auto-dismiss

  // System prompt state (Feature #179)
  const [_systemPromptData, setSystemPromptData] = useState<SystemPromptResponse | null>(null)
  const [systemPromptPresets, setSystemPromptPresets] = useState<SystemPromptPreset[]>([])
  const [isLoadingSystemPrompt, setIsLoadingSystemPrompt] = useState(false)
  const [systemPromptError, setSystemPromptError] = useState<string | null>(null)
  const [isSavingSystemPrompt, setIsSavingSystemPrompt] = useState(false)
  const [systemPromptSaveSuccess, setSystemPromptSaveSuccess] = useState(false)
  const [isTestingPrompt, setIsTestingPrompt] = useState(false)
  const [testPromptMessage, setTestPromptMessage] = useState('Hello! Can you tell me about yourself?')
  const [testPromptResult, setTestPromptResult] = useState<SystemPromptTestResponse | null>(null)
  const [showPresetDropdown, setShowPresetDropdown] = useState(false)

  // RAG Self-Test state (Feature #198)
  const [isRunningSelfTest, setIsRunningSelfTest] = useState(false)
  const [selfTestResult, setSelfTestResult] = useState<SelfTestResponse | null>(null)
  const [selfTestError, setSelfTestError] = useState<string | null>(null)

  // Load functions
  const loadOllamaModels = useCallback(async () => {
    setIsLoadingOllama(true)
    setOllamaError(null)
    try {
      const response = await fetchOllamaModels()
      setOllamaAvailable(response.available)
      setOllamaLLMModels(response.models)
      setOllamaEmbeddingModels(response.embedding_models)
      if (response.error) setOllamaError(response.error)
    } catch (err) {
      setOllamaError(err instanceof Error ? err.message : 'Failed to fetch Ollama models')
      setOllamaAvailable(false)
    } finally {
      setIsLoadingOllama(false)
    }
  }, [])

  const loadOpenRouterModels = useCallback(async () => {
    setIsLoadingOpenRouter(true)
    setOpenRouterError(null)
    try {
      const response = await fetchOpenRouterModels()
      setOpenRouterAvailable(response.available)
      setOpenRouterModels(response.models)
      if (response.error) setOpenRouterError(response.error)
    } catch (err) {
      setOpenRouterError(err instanceof Error ? err.message : 'Failed to fetch OpenRouter models')
      setOpenRouterAvailable(false)
    } finally {
      setIsLoadingOpenRouter(false)
    }
  }, [])

  const loadBackupStatus = useCallback(async () => {
    setIsLoadingBackup(true)
    try {
      const status = await fetchBackupStatus()
      setBackupStatus(status)
    } catch (err) {
      console.error('Failed to fetch backup status:', err)
    } finally {
      setIsLoadingBackup(false)
    }
  }, [])

  // Load automatic backup status (Feature #221)
  const loadAutoBackupStatus = useCallback(async () => {
    setIsLoadingAutoBackup(true)
    try {
      const [status, list] = await Promise.all([
        getAutoBackupStatus(),
        listAutoBackups()
      ])
      setAutoBackupStatus(status)
      setAutoBackupList(list)
      setAutoBackupHour(status.backup_hour)
      setAutoBackupMinute(status.backup_minute)
    } catch (err) {
      console.error('Failed to fetch auto backup status:', err)
    } finally {
      setIsLoadingAutoBackup(false)
    }
  }, [])

  const loadSettings = useCallback(async () => {
    try {
      const backendSettings = await fetchSettings()
      setSettings({
        ...DEFAULT_SETTINGS,
        openai_api_key: backendSettings.openai_api_key_set ? '' : '',
        cohere_api_key: backendSettings.cohere_api_key_set ? '' : '',
        openrouter_api_key: backendSettings.openrouter_api_key_set ? '' : '',
        llm_model: backendSettings.llm_model || DEFAULT_SETTINGS.llm_model,
        embedding_model: backendSettings.embedding_model || DEFAULT_SETTINGS.embedding_model,
        chunking_llm_model: backendSettings.chunking_llm_model !== undefined ? backendSettings.chunking_llm_model : DEFAULT_SETTINGS.chunking_llm_model,
        theme: (backendSettings.theme as Settings['theme']) || DEFAULT_SETTINGS.theme,
        enable_reranking: backendSettings.enable_reranking !== undefined ? backendSettings.enable_reranking : DEFAULT_SETTINGS.enable_reranking,
        openai_api_key_set: backendSettings.openai_api_key_set,
        cohere_api_key_set: backendSettings.cohere_api_key_set,
        openrouter_api_key_set: backendSettings.openrouter_api_key_set,
        twilio_account_sid: backendSettings.twilio_configured ? '' : '',
        twilio_auth_token: backendSettings.twilio_configured ? '' : '',
        twilio_whatsapp_number: backendSettings.twilio_whatsapp_number || '',
        twilio_configured: backendSettings.twilio_configured,
        // Telegram Bot configuration (Feature #306)
        telegram_bot_token: backendSettings.telegram_bot_token_set ? '' : '',
        telegram_bot_token_set: backendSettings.telegram_bot_token_set,
        chunk_strategy: (backendSettings.chunk_strategy as Settings['chunk_strategy']) || DEFAULT_SETTINGS.chunk_strategy,
        max_chunk_size: backendSettings.max_chunk_size || DEFAULT_SETTINGS.max_chunk_size,
        chunk_overlap: backendSettings.chunk_overlap !== undefined ? backendSettings.chunk_overlap : DEFAULT_SETTINGS.chunk_overlap,
        context_window_size: backendSettings.context_window_size !== undefined ? backendSettings.context_window_size : DEFAULT_SETTINGS.context_window_size,
        include_chat_history_in_search: backendSettings.include_chat_history_in_search !== undefined ? backendSettings.include_chat_history_in_search : DEFAULT_SETTINGS.include_chat_history_in_search,
        custom_system_prompt: backendSettings.custom_system_prompt !== undefined ? backendSettings.custom_system_prompt : DEFAULT_SETTINGS.custom_system_prompt,
        show_retrieved_chunks: backendSettings.show_retrieved_chunks !== undefined ? backendSettings.show_retrieved_chunks : DEFAULT_SETTINGS.show_retrieved_chunks,
        strict_rag_mode: backendSettings.strict_rag_mode !== undefined ? backendSettings.strict_rag_mode : DEFAULT_SETTINGS.strict_rag_mode,
        search_mode: backendSettings.search_mode !== undefined ? backendSettings.search_mode : DEFAULT_SETTINGS.search_mode,
        hybrid_alpha: backendSettings.hybrid_alpha !== undefined ? backendSettings.hybrid_alpha : DEFAULT_SETTINGS.hybrid_alpha,
        min_relevance_threshold: backendSettings.min_relevance_threshold !== undefined ? backendSettings.min_relevance_threshold : DEFAULT_SETTINGS.min_relevance_threshold,
        strict_relevance_threshold: backendSettings.strict_relevance_threshold !== undefined ? backendSettings.strict_relevance_threshold : DEFAULT_SETTINGS.strict_relevance_threshold,
        enable_suggested_questions: backendSettings.enable_suggested_questions !== undefined ? backendSettings.enable_suggested_questions : DEFAULT_SETTINGS.enable_suggested_questions,
        enable_typewriter: backendSettings.enable_typewriter !== undefined ? backendSettings.enable_typewriter : DEFAULT_SETTINGS.enable_typewriter,
        keyword_boost_weight: backendSettings.keyword_boost_weight !== undefined ? backendSettings.keyword_boost_weight : DEFAULT_SETTINGS.keyword_boost_weight,
        enable_entity_extraction: backendSettings.enable_entity_extraction !== undefined ? backendSettings.enable_entity_extraction : DEFAULT_SETTINGS.enable_entity_extraction,
        top_k: backendSettings.top_k !== undefined ? backendSettings.top_k : DEFAULT_SETTINGS.top_k,
        min_context_chars_for_generation: backendSettings.min_context_chars_for_generation !== undefined ? backendSettings.min_context_chars_for_generation : DEFAULT_SETTINGS.min_context_chars_for_generation,
        default_language: backendSettings.default_language !== undefined ? (backendSettings.default_language as Settings['default_language']) : DEFAULT_SETTINGS.default_language,
        enable_response_cache: backendSettings.enable_response_cache !== undefined ? backendSettings.enable_response_cache : DEFAULT_SETTINGS.enable_response_cache,
        cache_similarity_threshold: backendSettings.cache_similarity_threshold !== undefined ? backendSettings.cache_similarity_threshold : DEFAULT_SETTINGS.cache_similarity_threshold,
        cache_ttl_hours: backendSettings.cache_ttl_hours !== undefined ? backendSettings.cache_ttl_hours : DEFAULT_SETTINGS.cache_ttl_hours
      })
    } catch (e) {
      console.error('Failed to load settings from backend:', e)
      const savedSettings = localStorage.getItem('rag-settings')
      if (savedSettings) {
        try {
          const parsed = JSON.parse(savedSettings)
          setSettings({ ...DEFAULT_SETTINGS, ...parsed })
        } catch (parseErr) {
          console.error('Failed to parse saved settings:', parseErr)
        }
      }
    }
  }, [])

  const checkEmbeddingModelHealth = useCallback(async () => {
    setIsCheckingEmbedding(true)
    try {
      const result = await checkEmbeddingHealth()
      setEmbeddingHealth(result)
    } catch (err) {
      setEmbeddingHealth({
        available: false,
        model: 'unknown',
        provider: 'unknown',
        message: err instanceof Error ? err.message : 'Failed to check embedding model',
      })
    } finally {
      setIsCheckingEmbedding(false)
    }
  }, [])

  // Load system prompt data (Feature #179)
  const loadSystemPrompt = useCallback(async () => {
    setIsLoadingSystemPrompt(true)
    setSystemPromptError(null)
    try {
      const [promptData, presetsData] = await Promise.all([
        getSystemPrompt(),
        getSystemPromptPresets()
      ])
      setSystemPromptData(promptData)
      setSystemPromptPresets(presetsData.presets)
      setSettings(prev => ({
        ...prev,
        custom_system_prompt: promptData.custom_prompt
      }))
    } catch (err) {
      setSystemPromptError(err instanceof Error ? err.message : 'Failed to load system prompt')
    } finally {
      setIsLoadingSystemPrompt(false)
    }
  }, [])

  // Save custom system prompt (Feature #179)
  const handleSaveSystemPrompt = async (promptText: string) => {
    setIsSavingSystemPrompt(true)
    setSystemPromptError(null)
    setSystemPromptSaveSuccess(false)
    try {
      const result = await updateSystemPrompt(promptText)
      setSystemPromptData(result)
      setSettings(prev => ({ ...prev, custom_system_prompt: promptText }))
      setSystemPromptSaveSuccess(true)
      setTimeout(() => setSystemPromptSaveSuccess(false), 3000)
    } catch (err) {
      setSystemPromptError(err instanceof Error ? err.message : 'Failed to save system prompt')
    } finally {
      setIsSavingSystemPrompt(false)
    }
  }

  // Test system prompt (Feature #179)
  const handleTestPrompt = async () => {
    setIsTestingPrompt(true)
    setTestPromptResult(null)
    try {
      const result = await testSystemPrompt(testPromptMessage, settings.custom_system_prompt || undefined)
      setTestPromptResult(result)
    } catch (err) {
      setTestPromptResult({
        success: false,
        response: '',
        prompt_used: '',
        error: err instanceof Error ? err.message : 'Failed to test prompt'
      })
    } finally {
      setIsTestingPrompt(false)
    }
  }

  // Apply preset (Feature #179)
  const handleApplyPreset = (preset: SystemPromptPreset) => {
    setSettings(prev => ({
      ...prev,
      custom_system_prompt: preset.text
    }))
    setShowPresetDropdown(false)
    setHasUnsavedChanges(true)
  }

  // Reset to default prompt (Feature #179)
  const handleResetToDefault = () => {
    setSettings(prev => ({
      ...prev,
      custom_system_prompt: ''
    }))
    setHasUnsavedChanges(true)
  }

  // Load data on mount
  useEffect(() => {
    loadSettings()
    loadOllamaModels()
    loadBackupStatus()
    loadAutoBackupStatus()
    checkEmbeddingModelHealth()
    loadSystemPrompt()
  }, [loadSettings, loadOllamaModels, loadBackupStatus, loadAutoBackupStatus, checkEmbeddingModelHealth, loadSystemPrompt])

  // Apply theme when it changes
  useEffect(() => {
    const applyTheme = (theme: 'light' | 'dark' | 'system') => {
      const root = document.documentElement
      if (theme === 'system') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
        root.classList.toggle('dark', prefersDark)
      } else {
        root.classList.toggle('dark', theme === 'dark')
      }
    }
    applyTheme(settings.theme)
  }, [settings.theme])

  // Update setting helper
  const updateSetting = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettings(prev => ({ ...prev, [key]: value }))
    setHasUnsavedChanges(true)

    // Feature #31: Immediately persist theme to localStorage so it survives page refresh
    if (key === 'theme') {
      try {
        const savedSettings = localStorage.getItem('rag-settings')
        const currentSettings = savedSettings ? JSON.parse(savedSettings) : {}
        currentSettings.theme = value
        localStorage.setItem('rag-settings', JSON.stringify(currentSettings))
      } catch (e) {
        console.warn('Failed to save theme to localStorage:', e)
      }
    }

    // Real-time validation for API keys
    if (key === 'openai_api_key') {
      const validation = validateOpenAIKey(value as string)
      setOpenAIKeyError(validation.error)
    }
    if (key === 'cohere_api_key') {
      const validation = validateCohereKey(value as string)
      setCohereKeyError(validation.error)
    }
    if (key === 'openrouter_api_key') {
      const validation = validateOpenRouterKey(value as string)
      setOpenRouterKeyError(validation.error)
      if (validation.isValid && value && (value as string).length > 40) {
        loadOpenRouterModels()
      }
    }
  }

  // Save settings
  const handleSave = async () => {
    // Validate API keys before saving
    const openAIValidation = validateOpenAIKey(settings.openai_api_key)
    const cohereValidation = validateCohereKey(settings.cohere_api_key)
    const openRouterValidation = validateOpenRouterKey(settings.openrouter_api_key)

    if (!openAIValidation.isValid || !cohereValidation.isValid || !openRouterValidation.isValid) {
      setOpenAIKeyError(openAIValidation.error)
      setCohereKeyError(cohereValidation.error)
      setOpenRouterKeyError(openRouterValidation.error)
      showToast('error', 'Please fix the API key format errors before saving.')
      return
    }

    setOpenAIKeyError(null)
    setCohereKeyError(null)
    setOpenRouterKeyError(null)
    setIsSaving(true)

    try {
      const updatePayload: Record<string, string | boolean | number> = {
        llm_model: settings.llm_model,
        embedding_model: settings.embedding_model,
        chunking_llm_model: settings.chunking_llm_model,
        theme: settings.theme,
        enable_reranking: settings.enable_reranking,
        chunk_strategy: settings.chunk_strategy,
        max_chunk_size: settings.max_chunk_size,
        chunk_overlap: settings.chunk_overlap,
        context_window_size: settings.context_window_size,
        include_chat_history_in_search: settings.include_chat_history_in_search,
        custom_system_prompt: settings.custom_system_prompt,
        show_retrieved_chunks: settings.show_retrieved_chunks,
        strict_rag_mode: settings.strict_rag_mode,
        search_mode: settings.search_mode,
        hybrid_alpha: settings.hybrid_alpha,
        min_relevance_threshold: settings.min_relevance_threshold,
        strict_relevance_threshold: settings.strict_relevance_threshold,
        enable_suggested_questions: settings.enable_suggested_questions,
        enable_typewriter: settings.enable_typewriter,
        keyword_boost_weight: settings.keyword_boost_weight,
        enable_entity_extraction: settings.enable_entity_extraction,
        top_k: settings.top_k,
        min_context_chars_for_generation: settings.min_context_chars_for_generation,
        default_language: settings.default_language,
        enable_response_cache: settings.enable_response_cache,
        cache_similarity_threshold: settings.cache_similarity_threshold,
        cache_ttl_hours: settings.cache_ttl_hours
      }

      // Only update API keys if they were actually entered
      if (settings.openai_api_key?.trim()) {
        updatePayload.openai_api_key = settings.openai_api_key
      }
      if (settings.cohere_api_key?.trim()) {
        updatePayload.cohere_api_key = settings.cohere_api_key
      }
      if (settings.openrouter_api_key?.trim()) {
        updatePayload.openrouter_api_key = settings.openrouter_api_key
      }
      if (settings.twilio_account_sid?.trim()) {
        updatePayload.twilio_account_sid = settings.twilio_account_sid
      }
      if (settings.twilio_auth_token?.trim()) {
        updatePayload.twilio_auth_token = settings.twilio_auth_token
      }
      if (settings.twilio_whatsapp_number?.trim()) {
        updatePayload.twilio_whatsapp_number = settings.twilio_whatsapp_number
      }
      // Telegram Bot configuration (Feature #306)
      if (settings.telegram_bot_token?.trim()) {
        updatePayload.telegram_bot_token = settings.telegram_bot_token
      }

      const response = await updateSettings(updatePayload)

      // Feature #305: Show embedding model warning if returned
      if (response.embedding_model_warning) {
        // Show a longer-lasting warning toast for dimension mismatch
        const isDimensionMismatch = response.embedding_model_warning.includes('DIMENSION MISMATCH')
        showToast(
          'warning',
          response.embedding_model_warning,
          isDimensionMismatch ? 15000 : 10000  // Show longer for dimension mismatch
        )
      }

      // Also save to localStorage as backup (without API keys for security)
      const localSettings = {
        llm_model: settings.llm_model,
        embedding_model: settings.embedding_model,
        chunking_llm_model: settings.chunking_llm_model,
        theme: settings.theme,
        enable_reranking: settings.enable_reranking,
        chunk_strategy: settings.chunk_strategy,
        max_chunk_size: settings.max_chunk_size,
        chunk_overlap: settings.chunk_overlap,
        context_window_size: settings.context_window_size,
        include_chat_history_in_search: settings.include_chat_history_in_search,
        show_retrieved_chunks: settings.show_retrieved_chunks,
        strict_rag_mode: settings.strict_rag_mode,
        search_mode: settings.search_mode,
        hybrid_alpha: settings.hybrid_alpha,
        min_relevance_threshold: settings.min_relevance_threshold,
        strict_relevance_threshold: settings.strict_relevance_threshold,
        enable_suggested_questions: settings.enable_suggested_questions,
        enable_typewriter: settings.enable_typewriter,
        keyword_boost_weight: settings.keyword_boost_weight,
        enable_entity_extraction: settings.enable_entity_extraction,
        top_k: settings.top_k,
        min_context_chars_for_generation: settings.min_context_chars_for_generation,
        default_language: settings.default_language,
        enable_response_cache: settings.enable_response_cache,
        cache_similarity_threshold: settings.cache_similarity_threshold,
        cache_ttl_hours: settings.cache_ttl_hours
      }
      localStorage.setItem('rag-settings', JSON.stringify(localSettings))

      setHasUnsavedChanges(false)
      showToast('success', 'Settings saved successfully!')

      // Reload settings to update the "Configured" indicators
      await loadSettings()
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Failed to save settings')
    } finally {
      setIsSaving(false)
    }
  }

  // Test connection handler
  const handleTestConnection = async (provider: 'openai' | 'cohere' | 'openrouter' | 'ollama' | 'twilio' | 'telegram') => {
    setTestingConnection(prev => ({ ...prev, [provider]: true }))
    setConnectionStatus(prev => ({ ...prev, [provider]: null }))

    try {
      const result = await testConnection(provider)
      setConnectionStatus(prev => ({
        ...prev,
        [provider]: { success: result.success, message: result.message }
      }))
      setTimeout(() => {
        setConnectionStatus(prev => ({ ...prev, [provider]: null }))
      }, 5000)
    } catch (error) {
      setConnectionStatus(prev => ({
        ...prev,
        [provider]: {
          success: false,
          message: error instanceof Error ? error.message : 'Failed to test connection'
        }
      }))
      setTimeout(() => {
        setConnectionStatus(prev => ({ ...prev, [provider]: null }))
      }, 5000)
    } finally {
      setTestingConnection(prev => ({ ...prev, [provider]: false }))
    }
  }

  // Backup handlers
  const handleCreateBackup = async () => {
    setIsCreatingBackup(true)
    try {
      await createBackup()
      showToast('success', 'Backup created and downloaded successfully!')
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Failed to create backup')
    } finally {
      setIsCreatingBackup(false)
    }
  }

  const handleRestoreFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      if (!file.name.endsWith('.zip')) {
        setRestoreError('Please select a valid .zip backup file')
        return
      }
      setSelectedRestoreFile(file)
      setShowRestoreConfirm(true)
      setRestoreError(null)
      setRestoreSuccess(null)
    }
  }

  const handleConfirmRestore = async () => {
    if (!selectedRestoreFile) return

    setIsRestoring(true)
    setRestoreError(null)
    setRestoreSuccess(null)
    setShowRestoreConfirm(false)

    try {
      const result = await restoreBackup(selectedRestoreFile)
      setRestoreSuccess(result)
      loadBackupStatus()
      if (restoreFileInputRef.current) {
        restoreFileInputRef.current.value = ''
      }
      setSelectedRestoreFile(null)
      showToast('success', 'Backup restored successfully!')
    } catch (err) {
      setRestoreError(err instanceof Error ? err.message : 'Failed to restore backup')
    } finally {
      setIsRestoring(false)
    }
  }

  const handleCancelRestore = () => {
    setShowRestoreConfirm(false)
    setSelectedRestoreFile(null)
    if (restoreFileInputRef.current) {
      restoreFileInputRef.current.value = ''
    }
  }

  // Automatic backup handlers (Feature #221)
  const handleToggleAutoBackup = async (enabled: boolean) => {
    try {
      const result = await configureAutoBackup({
        enabled,
        backup_hour: autoBackupHour,
        backup_minute: autoBackupMinute
      })
      setAutoBackupStatus(result)
      showToast('success', enabled ? 'Automatic backups enabled' : 'Automatic backups disabled')
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Failed to configure automatic backup')
    }
  }

  const handleUpdateAutoBackupTime = async () => {
    try {
      const result = await configureAutoBackup({
        enabled: autoBackupStatus?.enabled ?? false,
        backup_hour: autoBackupHour,
        backup_minute: autoBackupMinute
      })
      setAutoBackupStatus(result)
      showToast('success', `Backup time updated to ${autoBackupHour.toString().padStart(2, '0')}:${autoBackupMinute.toString().padStart(2, '0')} UTC`)
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Failed to update backup time')
    }
  }

  const handleRunAutoBackupNow = async () => {
    setIsRunningAutoBackup(true)
    try {
      const result = await runAutoBackupNow()
      if (result.success) {
        showToast('success', 'Backup completed successfully')
        loadAutoBackupStatus()
      } else {
        showToast('error', result.error || 'Backup failed')
      }
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Failed to run backup')
    } finally {
      setIsRunningAutoBackup(false)
    }
  }

  // Reset database handlers (Feature #214: Double confirmation)
  const handleResetDatabase = async () => {
    setShowResetConfirm(true)
    setResetConfirmationText('')
    setResetError(null)
    setResetSuccess(null)
    setResetPreview(null)
    setCountdownSeconds(0)
    setIsLoadingPreview(true)

    try {
      // Fetch preview with counts and confirmation token
      const preview = await getResetDatabasePreview()
      setResetPreview(preview)
    } catch (error) {
      setResetError(error instanceof Error ? error.message : 'Failed to get reset preview')
    } finally {
      setIsLoadingPreview(false)
    }
  }

  const handleCancelReset = () => {
    setShowResetConfirm(false)
    setResetConfirmationText('')
    setResetError(null)
    setResetPreview(null)
    setCountdownSeconds(0)
  }

  // Start countdown when user types correct confirmation phrase
  const handleConfirmationTextChange = (text: string) => {
    setResetConfirmationText(text)
    // Start 10-second countdown when user types "DELETE ALL DATA" (Feature #223)
    if (text === 'DELETE ALL DATA' && countdownSeconds === 0) {
      setCountdownSeconds(10)
      const interval = setInterval(() => {
        setCountdownSeconds(prev => {
          if (prev <= 1) {
            clearInterval(interval)
            return 0
          }
          return prev - 1
        })
      }, 1000)
    } else if (text !== 'DELETE ALL DATA') {
      setCountdownSeconds(0)
    }
  }

  const handleConfirmReset = async () => {
    if (resetConfirmationText !== 'DELETE ALL DATA') {
      setResetError('Please type "DELETE ALL DATA" to confirm')
      return
    }

    if (!resetPreview?.confirmation_token) {
      setResetError('No confirmation token. Please start the reset process again.')
      return
    }

    if (countdownSeconds > 0) {
      setResetError(`Please wait ${countdownSeconds} more seconds before confirming`)
      return
    }

    setIsResetting(true)
    setResetError(null)
    setResetSuccess(null)
    setShowUndoOption(false)
    setUndoResult(null)

    try {
      const result = await resetDatabase(resetConfirmationText, resetPreview.confirmation_token)
      setResetSuccess(result)
      setShowResetConfirm(false)
      setResetConfirmationText('')
      setResetPreview(null)
      loadBackupStatus()
      await loadSettings()

      // Feature #222: Fetch last backup info and show Undo option
      try {
        const backupInfo = await getLastDestructiveBackup()
        setLastBackup(backupInfo)
        if (backupInfo.available) {
          setShowUndoOption(true)
          // Start 30-second countdown before auto-dismissing Undo option
          setUndoCountdown(30)
          const countdownInterval = setInterval(() => {
            setUndoCountdown(prev => {
              if (prev <= 1) {
                clearInterval(countdownInterval)
                setShowUndoOption(false)
                // Reload after countdown expires without Undo
                window.location.href = '/'
                return 0
              }
              return prev - 1
            })
          }, 1000)
        } else {
          // No backup available, reload after 3 seconds
          setTimeout(() => {
            window.location.href = '/'
          }, 3000)
        }
      } catch {
        // If we can't get backup info, just reload
        setTimeout(() => {
          window.location.href = '/'
        }, 3000)
      }
    } catch (error) {
      setResetError(error instanceof Error ? error.message : 'Failed to reset database')
    } finally {
      setIsResetting(false)
    }
  }

  // Feature #222: Handle Undo (restore from pre-destructive backup)
  const handleUndoReset = async () => {
    if (!lastBackup?.backup?.path) {
      setResetError('No backup available to restore from')
      return
    }

    setIsUndoing(true)
    setResetError(null)

    try {
      const result = await restoreFromPreDestructiveBackup(lastBackup.backup.path)
      setUndoResult(result)
      setShowUndoOption(false)

      if (result.success) {
        // Show success message and reload
        setTimeout(() => {
          window.location.href = '/'
        }, 3000)
      }
    } catch (error) {
      setResetError(error instanceof Error ? error.message : 'Failed to restore from backup')
    } finally {
      setIsUndoing(false)
    }
  }

  // Feature #222: Dismiss Undo option and proceed with reload
  const handleDismissUndo = () => {
    setShowUndoOption(false)
    window.location.href = '/'
  }

  // RAG Self-Test handler (Feature #198)
  const handleRunSelfTest = async () => {
    setIsRunningSelfTest(true)
    setSelfTestError(null)
    setSelfTestResult(null)

    try {
      const result = await runSelfTest()
      setSelfTestResult(result)
      showToast(
        result.overall_status === 'pass' ? 'success' : result.overall_status === 'partial' ? 'warning' : 'error',
        result.overall_status === 'pass'
          ? 'All tests passed!'
          : result.overall_status === 'partial'
            ? 'Some tests passed with warnings'
            : 'Tests failed - check results'
      )
    } catch (error) {
      setSelfTestError(error instanceof Error ? error.message : 'Failed to run self-test')
      showToast('error', 'Self-test failed')
    } finally {
      setIsRunningSelfTest(false)
    }
  }

  // Scroll to section
  const scrollToSection = (sectionId: string) => {
    const element = document.getElementById(sectionId)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  return (
    <div className="min-h-screen bg-light-bg dark:bg-dark-bg">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-light-sidebar dark:bg-dark-sidebar border-b border-light-border dark:border-dark-border">
        <div className="max-w-4xl mx-auto px-4 py-4">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/')}
              className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
              aria-label="Back to home"
            >
              <ArrowLeft className="w-5 h-5 text-light-text dark:text-dark-text" />
            </button>
            <div className="flex items-center gap-2">
              <Settings className="w-6 h-6 text-primary" />
              <h1 className="text-xl font-semibold text-light-text dark:text-dark-text">
                Settings
              </h1>
            </div>
            {hasUnsavedChanges && (
              <span className="text-xs px-2 py-1 bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 rounded-full">
                Unsaved changes
              </span>
            )}
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="ml-auto px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors flex items-center gap-2 disabled:opacity-50"
            >
              {isSaving ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save size={16} />
                  Save Settings
                </>
              )}
            </button>
          </div>

          {/* Quick navigation */}
          <div className="flex flex-wrap gap-2 mt-4">
            {[
              { id: 'api-keys', label: 'API Keys', icon: Key },
              { id: 'models', label: 'Models', icon: Brain },
              { id: 'whatsapp', label: 'WhatsApp', icon: Phone },
              { id: 'telegram', label: 'Telegram', icon: Send },
              { id: 'rag-config', label: 'RAG Config', icon: Sliders },
              { id: 'ai-behavior', label: 'AI Behavior', icon: Bot },
              { id: 'appearance', label: 'Appearance', icon: Palette },
              { id: 'backup', label: 'Backup', icon: HardDrive },
              { id: 'system', label: 'System', icon: Server },
              { id: 'config-guide', label: 'Guide', icon: BookOpen },
              { id: 'danger', label: 'Danger Zone', icon: AlertTriangle },
            ].map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => scrollToSection(id)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text hover:bg-light-border dark:hover:bg-dark-border rounded-full transition-colors"
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
        {/* Section 1: API Keys */}
        <section id="api-keys" className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-6 py-4 border-b border-light-border dark:border-dark-border">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <Key className="w-5 h-5 text-primary" />
              API Keys
            </h2>
            <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
              Configure API keys for LLM and embedding services
            </p>
          </div>
          <div className="p-6 space-y-6">
            {/* OpenAI API Key */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label htmlFor="openai-key" className="text-sm font-medium text-light-text dark:text-dark-text">
                  OpenAI API Key
                </label>
                {settings.openai_api_key_set && !settings.openai_api_key && (
                  <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                    <Check size={14} />
                    Configured
                  </span>
                )}
              </div>
              <div className="relative">
                <input
                  id="openai-key"
                  type={showOpenAIKey ? 'text' : 'password'}
                  value={settings.openai_api_key}
                  onChange={(e) => updateSetting('openai_api_key', e.target.value)}
                  className={`w-full px-3 py-2 pr-10 border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 font-mono text-sm ${
                    openAIKeyError ? 'border-red-500 focus:ring-red-500' : 'border-light-border dark:border-dark-border focus:ring-primary'
                  }`}
                  placeholder={settings.openai_api_key_set ? "Enter new key to update..." : "sk-..."}
                />
                <button
                  type="button"
                  onClick={() => setShowOpenAIKey(!showOpenAIKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text"
                >
                  {showOpenAIKey ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {openAIKeyError && (
                <p className="text-xs text-red-500 dark:text-red-400">{openAIKeyError}</p>
              )}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleTestConnection('openai')}
                  disabled={testingConnection.openai || (!settings.openai_api_key && !settings.openai_api_key_set)}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {testingConnection.openai ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                  Test Connection
                </button>
                {connectionStatus.openai && (
                  <span className={`flex items-center gap-1 text-xs ${connectionStatus.openai.success ? 'text-green-600' : 'text-red-600'}`}>
                    {connectionStatus.openai.success ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                    {connectionStatus.openai.message}
                  </span>
                )}
              </div>
            </div>

            {/* Cohere API Key */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label htmlFor="cohere-key" className="text-sm font-medium text-light-text dark:text-dark-text">
                  Cohere API Key
                </label>
                {settings.cohere_api_key_set && !settings.cohere_api_key && (
                  <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                    <Check size={14} />
                    Configured
                  </span>
                )}
              </div>
              <div className="relative">
                <input
                  id="cohere-key"
                  type={showCohereKey ? 'text' : 'password'}
                  value={settings.cohere_api_key}
                  onChange={(e) => updateSetting('cohere_api_key', e.target.value)}
                  className={`w-full px-3 py-2 pr-10 border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 font-mono text-sm ${
                    cohereKeyError ? 'border-red-500 focus:ring-red-500' : 'border-light-border dark:border-dark-border focus:ring-primary'
                  }`}
                  placeholder={settings.cohere_api_key_set ? "Enter new key to update..." : "..."}
                />
                <button
                  type="button"
                  onClick={() => setShowCohereKey(!showCohereKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text"
                >
                  {showCohereKey ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {cohereKeyError && (
                <p className="text-xs text-red-500 dark:text-red-400">{cohereKeyError}</p>
              )}
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                Optional - used for re-ranking search results
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleTestConnection('cohere')}
                  disabled={testingConnection.cohere || (!settings.cohere_api_key && !settings.cohere_api_key_set)}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {testingConnection.cohere ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                  Test Connection
                </button>
                {connectionStatus.cohere && (
                  <span className={`flex items-center gap-1 text-xs ${connectionStatus.cohere.success ? 'text-green-600' : 'text-red-600'}`}>
                    {connectionStatus.cohere.success ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                    {connectionStatus.cohere.message}
                  </span>
                )}
              </div>
            </div>

            {/* OpenRouter API Key */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label htmlFor="openrouter-key" className="text-sm font-medium text-light-text dark:text-dark-text">
                  OpenRouter API Key
                </label>
                {settings.openrouter_api_key_set && !settings.openrouter_api_key && (
                  <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                    <Check size={14} />
                    Configured
                  </span>
                )}
              </div>
              <div className="relative">
                <input
                  id="openrouter-key"
                  type={showOpenRouterKey ? 'text' : 'password'}
                  value={settings.openrouter_api_key}
                  onChange={(e) => updateSetting('openrouter_api_key', e.target.value)}
                  className={`w-full px-3 py-2 pr-10 border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 font-mono text-sm ${
                    openRouterKeyError ? 'border-red-500 focus:ring-red-500' : 'border-light-border dark:border-dark-border focus:ring-primary'
                  }`}
                  placeholder={settings.openrouter_api_key_set ? "Enter new key to update..." : "sk-or-..."}
                />
                <button
                  type="button"
                  onClick={() => setShowOpenRouterKey(!showOpenRouterKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text"
                >
                  {showOpenRouterKey ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {openRouterKeyError && (
                <p className="text-xs text-red-500 dark:text-red-400">{openRouterKeyError}</p>
              )}
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                Optional - access multiple AI models (Claude, GPT-4, Llama, etc.) through one API
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleTestConnection('openrouter')}
                  disabled={testingConnection.openrouter || (!settings.openrouter_api_key && !settings.openrouter_api_key_set)}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {testingConnection.openrouter ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                  Test Connection
                </button>
                {connectionStatus.openrouter && (
                  <span className={`flex items-center gap-1 text-xs ${connectionStatus.openrouter.success ? 'text-green-600' : 'text-red-600'}`}>
                    {connectionStatus.openrouter.success ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                    {connectionStatus.openrouter.message}
                  </span>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Section 2: Model Selection */}
        <section id="models" className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-6 py-4 border-b border-light-border dark:border-dark-border">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
                  <Brain className="w-5 h-5 text-purple-500" />
                  Model Selection
                </h2>
                <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Choose LLM and embedding models
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={loadOpenRouterModels}
                  disabled={isLoadingOpenRouter}
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors disabled:opacity-50"
                >
                  <RefreshCw size={14} className={isLoadingOpenRouter ? 'animate-spin' : ''} />
                  {isLoadingOpenRouter ? 'Loading...' : 'Load OpenRouter'}
                </button>
                <button
                  type="button"
                  onClick={loadOllamaModels}
                  disabled={isLoadingOllama}
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors disabled:opacity-50"
                >
                  <RefreshCw size={14} className={isLoadingOllama ? 'animate-spin' : ''} />
                  {isLoadingOllama ? 'Detecting...' : 'Detect Ollama'}
                </button>
              </div>
            </div>
          </div>
          <div className="p-6 space-y-6">
            {/* Status messages */}
            {openRouterError && (
              <div className="text-xs text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 rounded-lg">
                {openRouterError}
              </div>
            )}
            {openRouterAvailable && !openRouterError && (
              <div className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-3 py-2 rounded-lg">
                OpenRouter connected: {openRouterModels.length} model{openRouterModels.length !== 1 ? 's' : ''} available
              </div>
            )}
            {ollamaError && (
              <div className="text-xs text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 rounded-lg">
                {ollamaError}
              </div>
            )}
            {ollamaAvailable && !ollamaError && (
              <div className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-3 py-2 rounded-lg">
                Ollama detected: {ollamaLLMModels.length} LLM model{ollamaLLMModels.length !== 1 ? 's' : ''}, {ollamaEmbeddingModels.length} embedding model{ollamaEmbeddingModels.length !== 1 ? 's' : ''}
              </div>
            )}

            {/* LLM Model */}
            <div className="space-y-2">
              <label htmlFor="llm-model" className="text-sm font-medium text-light-text dark:text-dark-text">
                LLM Model
              </label>
              {openRouterModels.length > 0 && (
                <div className="mb-2">
                  <input
                    type="text"
                    placeholder="Search OpenRouter models..."
                    value={modelSearch}
                    onChange={(e) => setModelSearch(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
                  />
                  {modelSearch.trim() !== '' && (() => {
                    const { totalMatches, truncated } = filterAndGroupModels(openRouterModels, modelSearch)
                    return (
                      <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                        {truncated ? `Showing 50 of ${totalMatches} matching models` : `${totalMatches} model${totalMatches !== 1 ? 's' : ''} found`}
                      </p>
                    )
                  })()}
                </div>
              )}
              <select
                id="llm-model"
                value={settings.llm_model}
                onChange={(e) => updateSetting('llm_model', e.target.value)}
                className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
                size={openRouterModels.length > 0 ? 10 : undefined}
              >
                <optgroup label="OpenAI (Cloud)">
                  {OPENAI_LLM_MODELS.map((model) => (
                    <option key={model.value} value={model.value}>{model.label}</option>
                  ))}
                </optgroup>
                {openRouterModels.length > 0 && (() => {
                  const { groups, totalMatches } = filterAndGroupModels(openRouterModels, modelSearch)
                  if (totalMatches === 0) {
                    return (
                      <optgroup label="OpenRouter">
                        <option disabled>No models match your search</option>
                      </optgroup>
                    )
                  }
                  return groups.map(group => (
                    <optgroup key={group.provider} label={`OpenRouter - ${group.provider}`}>
                      {group.models.map((model) => (
                        <option key={model.value} value={model.value}>{model.label}</option>
                      ))}
                    </optgroup>
                  ))
                })()}
                {ollamaLLMModels.length > 0 && (
                  <optgroup label="Ollama (Local)">
                    {ollamaLLMModels.map((model) => (
                      <option key={model.value} value={model.value}>
                        {model.label} {model.size ? `[${model.size}]` : ''}
                      </option>
                    ))}
                  </optgroup>
                )}
                {!ollamaAvailable && (
                  <optgroup label="Ollama (Local)" disabled>
                    <option disabled>Start Ollama to see local models</option>
                  </optgroup>
                )}
              </select>
            </div>

            {/* Embedding Model */}
            <div className="space-y-2">
              <label htmlFor="embedding-model" className="text-sm font-medium text-light-text dark:text-dark-text">
                Embedding Model
              </label>
              <select
                id="embedding-model"
                value={settings.embedding_model}
                onChange={(e) => updateSetting('embedding_model', e.target.value)}
                className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <optgroup label="OpenAI (Cloud)">
                  {OPENAI_EMBEDDING_MODELS.map((model) => (
                    <option key={model.value} value={model.value}>{model.label}</option>
                  ))}
                </optgroup>
                {settings.openrouter_api_key_set && (
                  <optgroup label="OpenRouter (Cloud)">
                    {OPENROUTER_EMBEDDING_MODELS.map((model) => (
                      <option key={model.value} value={model.value}>
                        {model.label} {model.pricing ? `[${model.pricing}]` : ''}
                      </option>
                    ))}
                  </optgroup>
                )}
                {ollamaEmbeddingModels.length > 0 && (
                  <optgroup label="Ollama (Local)">
                    {ollamaEmbeddingModels.map((model) => (
                      <option key={model.value} value={model.value}>
                        {model.label} {model.size ? `[${model.size}]` : ''}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
              <div className="flex items-center gap-2 mt-2">
                {isCheckingEmbedding ? (
                  <span className="flex items-center gap-2 text-xs text-light-text-secondary">
                    <Loader2 size={14} className="animate-spin" />
                    Checking embedding model...
                  </span>
                ) : embeddingHealth && (
                  <span className={`flex items-center gap-2 text-xs ${embeddingHealth.available ? 'text-green-600' : 'text-red-600'}`}>
                    {embeddingHealth.available ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                    {embeddingHealth.message}
                  </span>
                )}
                <button
                  type="button"
                  onClick={checkEmbeddingModelHealth}
                  disabled={isCheckingEmbedding}
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors disabled:opacity-50"
                >
                  <RefreshCw size={14} className={isCheckingEmbedding ? 'animate-spin' : ''} />
                </button>
              </div>
            </div>

            {/* Chunking LLM Model */}
            {settings.chunk_strategy === 'agentic' && (
              <div className="space-y-2">
                <label htmlFor="chunking-llm-model" className="text-sm font-medium text-light-text dark:text-dark-text">
                  Chunking LLM Model
                </label>
                <select
                  id="chunking-llm-model"
                  value={settings.chunking_llm_model}
                  onChange={(e) => updateSetting('chunking_llm_model', e.target.value)}
                  className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  {CHUNKING_LLM_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                  {ollamaLLMModels.length > 0 && (
                    <optgroup label="Ollama (Local)">
                      {ollamaLLMModels.map((model) => (
                        <option key={`chunking-${model.value}`} value={model.value}>
                          {model.label} {model.size ? `[${model.size}]` : ''}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                  Separate LLM for agentic chunking to avoid GPU conflicts
                </p>
              </div>
            )}
          </div>
        </section>

        {/* Section 3: WhatsApp/Twilio Integration */}
        <section id="whatsapp" className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-6 py-4 border-b border-light-border dark:border-dark-border">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <Phone className="w-5 h-5 text-green-500" />
              WhatsApp Integration (Twilio)
              {settings.twilio_configured && (
                <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400 ml-2">
                  <Check size={14} />
                  Configured
                </span>
              )}
            </h2>
            <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
              Connect your RAG system to WhatsApp via Twilio
            </p>
          </div>
          <div className="p-6 space-y-4">
            {/* Twilio Account SID */}
            <div className="space-y-2">
              <label htmlFor="twilio-sid" className="text-sm font-medium text-light-text dark:text-dark-text">
                Account SID
              </label>
              <div className="relative">
                <input
                  id="twilio-sid"
                  type={showTwilioSid ? 'text' : 'password'}
                  value={settings.twilio_account_sid}
                  onChange={(e) => updateSetting('twilio_account_sid', e.target.value)}
                  className="w-full px-3 py-2 pr-10 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary font-mono text-sm"
                  placeholder={settings.twilio_configured ? "Enter new SID to update..." : "AC..."}
                />
                <button
                  type="button"
                  onClick={() => setShowTwilioSid(!showTwilioSid)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary hover:text-light-text"
                >
                  {showTwilioSid ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            {/* Twilio Auth Token */}
            <div className="space-y-2">
              <label htmlFor="twilio-token" className="text-sm font-medium text-light-text dark:text-dark-text">
                Auth Token
              </label>
              <div className="relative">
                <input
                  id="twilio-token"
                  type={showTwilioToken ? 'text' : 'password'}
                  value={settings.twilio_auth_token}
                  onChange={(e) => updateSetting('twilio_auth_token', e.target.value)}
                  className="w-full px-3 py-2 pr-10 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary font-mono text-sm"
                  placeholder={settings.twilio_configured ? "Enter new token to update..." : "Your auth token"}
                />
                <button
                  type="button"
                  onClick={() => setShowTwilioToken(!showTwilioToken)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary hover:text-light-text"
                >
                  {showTwilioToken ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            {/* Twilio WhatsApp Number */}
            <div className="space-y-2">
              <label htmlFor="twilio-whatsapp" className="text-sm font-medium text-light-text dark:text-dark-text">
                WhatsApp Number
              </label>
              <input
                id="twilio-whatsapp"
                type="text"
                value={settings.twilio_whatsapp_number}
                onChange={(e) => updateSetting('twilio_whatsapp_number', e.target.value)}
                className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary font-mono text-sm"
                placeholder="+14155238886"
              />
            </div>

            {/* Test Twilio Connection */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => handleTestConnection('twilio')}
                disabled={testingConnection.twilio || (!settings.twilio_account_sid && !settings.twilio_configured)}
                className="flex items-center gap-2 px-3 py-1.5 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {testingConnection.twilio ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Test Twilio Connection
              </button>
              {connectionStatus.twilio && (
                <span className={`flex items-center gap-1 text-xs ${connectionStatus.twilio.success ? 'text-green-600' : 'text-red-600'}`}>
                  {connectionStatus.twilio.success ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                  {connectionStatus.twilio.message}
                </span>
              )}
            </div>

            {/* Ngrok Webhook URL */}
            <div className="mt-4 pt-4 border-t border-light-border dark:border-dark-border">
              <NgrokStatus autoRefreshInterval={30000} />
            </div>
          </div>
        </section>

        {/* Section 3b: Telegram Bot Integration (Feature #306) */}
        <section id="telegram" className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-6 py-4 border-b border-light-border dark:border-dark-border">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <Send className="w-5 h-5 text-blue-400" />
              Telegram Bot Integration
              {settings.telegram_bot_token_set && (
                <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400 ml-2">
                  <Check size={14} />
                  Configured
                </span>
              )}
            </h2>
            <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
              Connect your RAG system to Telegram via Bot API
            </p>
          </div>
          <div className="p-6 space-y-4">
            {/* Telegram Bot Token */}
            <div className="space-y-2">
              <label htmlFor="telegram-token" className="text-sm font-medium text-light-text dark:text-dark-text">
                Bot Token
              </label>
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                Get your bot token from <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">@BotFather</a> on Telegram
              </p>
              <div className="relative">
                <input
                  id="telegram-token"
                  type={showTelegramToken ? 'text' : 'password'}
                  value={settings.telegram_bot_token}
                  onChange={(e) => updateSetting('telegram_bot_token', e.target.value)}
                  className="w-full px-3 py-2 pr-10 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary font-mono text-sm"
                  placeholder={settings.telegram_bot_token_set ? "Enter new token to update..." : "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"}
                />
                <button
                  type="button"
                  onClick={() => setShowTelegramToken(!showTelegramToken)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary hover:text-light-text"
                >
                  {showTelegramToken ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                Token format: <code className="bg-light-bg dark:bg-dark-bg px-1 rounded">123456789:ABCdef...</code> (numeric:alphanumeric)
              </p>
            </div>

            {/* Test Telegram Connection */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => handleTestConnection('telegram')}
                disabled={testingConnection.telegram || (!settings.telegram_bot_token && !settings.telegram_bot_token_set)}
                className="flex items-center gap-2 px-3 py-1.5 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {testingConnection.telegram ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Test Telegram Connection
              </button>
              {connectionStatus.telegram && (
                <span className={`flex items-center gap-1 text-xs ${connectionStatus.telegram.success ? 'text-green-600' : 'text-red-600'}`}>
                  {connectionStatus.telegram.success ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                  {connectionStatus.telegram.message}
                </span>
              )}
            </div>

            {/* Telegram Webhook Status (Feature #313) */}
            <TelegramWebhookStatus
              autoRefreshInterval={60000}
              isBotTokenConfigured={settings.telegram_bot_token_set || false}
            />
          </div>
        </section>

        {/* Section 4: RAG Configuration */}
        <section id="rag-config" className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-6 py-4 border-b border-light-border dark:border-dark-border">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <Sliders className="w-5 h-5 text-blue-500" />
              RAG Configuration
            </h2>
            <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
              Configure chunking, context, and search settings
            </p>
          </div>
          <div className="p-6 space-y-6">
            {/* Enable Reranking */}
            <div className="flex items-center justify-between p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
              <div className="flex-1">
                <label className="text-sm font-medium text-light-text dark:text-dark-text">
                  Enable Cohere Reranking
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Improves search relevance by reranking results using Cohere's API
                </p>
              </div>
              <button
                type="button"
                onClick={() => updateSetting('enable_reranking', !settings.enable_reranking)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  settings.enable_reranking ? 'bg-primary' : 'bg-light-border dark:bg-dark-border'
                }`}
                role="switch"
                aria-checked={settings.enable_reranking}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    settings.enable_reranking ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

            {/* Chunking Strategy */}
            <div className="space-y-2 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
              <label htmlFor="chunk-strategy" className="text-sm font-medium text-light-text dark:text-dark-text">
                Chunking Strategy
              </label>
              <select
                id="chunk-strategy"
                value={settings.chunk_strategy}
                onChange={(e) => updateSetting('chunk_strategy', e.target.value as Settings['chunk_strategy'])}
                className="w-full px-3 py-2 text-sm bg-white dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg focus:ring-2 focus:ring-primary text-light-text dark:text-dark-text"
              >
                <option value="agentic">Agentic Splitter (LLM-powered, recommended)</option>
                <option value="semantic">Semantic (structure-aware)</option>
                <option value="paragraph">Paragraph-based</option>
                <option value="fixed">Fixed-size chunks</option>
              </select>
            </div>

            {/* Max Chunk Size */}
            <div className="space-y-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
              <div className="flex items-center justify-between">
                <div>
                  <label htmlFor="max-chunk-size" className="text-sm font-medium text-light-text dark:text-dark-text">
                    Max Chunk Size
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Maximum characters per chunk (100-10000)
                  </p>
                </div>
                <span className="text-sm font-mono text-light-text dark:text-dark-text">{settings.max_chunk_size}</span>
              </div>
              <input
                id="max-chunk-size"
                type="range"
                min="100"
                max="10000"
                step="100"
                value={settings.max_chunk_size}
                onChange={(e) => updateSetting('max_chunk_size', parseInt(e.target.value))}
                className="w-full h-2 bg-light-border dark:bg-dark-border rounded-lg appearance-none cursor-pointer accent-primary"
              />
            </div>

            {/* Chunk Overlap */}
            <div className="space-y-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
              <div className="flex items-center justify-between">
                <div>
                  <label htmlFor="chunk-overlap" className="text-sm font-medium text-light-text dark:text-dark-text">
                    Chunk Overlap
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Characters to overlap between chunks (0-1000)
                  </p>
                </div>
                <span className="text-sm font-mono text-light-text dark:text-dark-text">{settings.chunk_overlap}</span>
              </div>
              <input
                id="chunk-overlap"
                type="range"
                min="0"
                max="1000"
                step="50"
                value={settings.chunk_overlap}
                onChange={(e) => updateSetting('chunk_overlap', parseInt(e.target.value))}
                className="w-full h-2 bg-light-border dark:bg-dark-border rounded-lg appearance-none cursor-pointer accent-primary"
              />
            </div>

            {/* Context Window Size */}
            <div className="space-y-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
              <div className="flex items-center justify-between">
                <div>
                  <label htmlFor="context-window-size" className="text-sm font-medium text-light-text dark:text-dark-text">
                    Context Window Size
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Number of previous messages to include (1-100)
                  </p>
                </div>
                <span className="text-sm font-mono text-light-text dark:text-dark-text">{settings.context_window_size}</span>
              </div>
              <input
                id="context-window-size"
                type="range"
                min="1"
                max="100"
                step="1"
                value={settings.context_window_size}
                onChange={(e) => updateSetting('context_window_size', parseInt(e.target.value))}
                className="w-full h-2 bg-light-border dark:bg-dark-border rounded-lg appearance-none cursor-pointer accent-primary"
              />
            </div>

            {/* Retrieved Chunks Count (top_k) - Feature #230 */}
            <div className="p-4 bg-light-bg dark:bg-dark-bg rounded-lg border border-green-200 dark:border-green-800">
              <div className="flex items-center justify-between mb-2">
                <div className="flex-1">
                  <label htmlFor="top-k-setting" className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                    <span className="px-1.5 py-0.5 text-[10px] font-bold bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 rounded">RETRIEVAL</span>
                    Numero di chunks da recuperare
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Number of document chunks to retrieve per query (5-100)
                  </p>
                </div>
                <span className="text-sm font-mono bg-green-50 dark:bg-green-900/30 px-2 py-1 rounded text-green-700 dark:text-green-300">{settings.top_k}</span>
              </div>
              <input
                id="top-k-setting"
                type="range"
                min="5"
                max="100"
                step="5"
                value={settings.top_k}
                onChange={(e) => updateSetting('top_k', parseInt(e.target.value))}
                className="w-full h-2 bg-light-border dark:bg-dark-border rounded-lg appearance-none cursor-pointer accent-green-500"
              />
              <div className="flex justify-between mt-1">
                <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">5</span>
                <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">100</span>
              </div>
              <div className="mt-3 p-3 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800">
                <p className="text-xs text-green-800 dark:text-green-200">
                  <strong>Suggerimento:</strong> Valori pi alti = risultati pi completi ma pi lenti e costosi.
                  Consigliato: <strong>10-20</strong> per query specifiche, <strong>50+</strong> per elenchi completi come "elencami tutte le ricette".
                </p>
              </div>
            </div>

            {/* Minimum Context Characters (Feature #281) */}
            <div className="p-4 bg-light-bg dark:bg-dark-bg rounded-lg border border-orange-200 dark:border-orange-800">
              <div className="flex items-center justify-between mb-2">
                <div className="flex-1">
                  <label htmlFor="min-context-chars-setting" className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                    <span className="px-1.5 py-0.5 text-[10px] font-bold bg-orange-100 dark:bg-orange-900 text-orange-700 dark:text-orange-300 rounded">GUARDRAIL</span>
                    Minimum Context Characters
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Block LLM call if retrieved context is below this threshold (prevents hallucination)
                  </p>
                </div>
                <span className="text-sm font-mono bg-orange-50 dark:bg-orange-900/30 px-2 py-1 rounded text-orange-700 dark:text-orange-300">
                  {settings.min_context_chars_for_generation === 0 ? 'Disabled' : `${settings.min_context_chars_for_generation} chars`}
                </span>
              </div>
              <input
                id="min-context-chars-setting"
                type="range"
                min="0"
                max="2000"
                step="100"
                value={settings.min_context_chars_for_generation}
                onChange={(e) => updateSetting('min_context_chars_for_generation', parseInt(e.target.value))}
                className="w-full h-2 bg-light-border dark:bg-dark-border rounded-lg appearance-none cursor-pointer accent-orange-500"
              />
              <div className="flex justify-between mt-1">
                <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">0 (Off)</span>
                <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">2000</span>
              </div>
              <div className="mt-3 p-3 bg-orange-50 dark:bg-orange-900/20 rounded-lg border border-orange-200 dark:border-orange-800">
                <p className="text-xs text-orange-800 dark:text-orange-200">
                  <strong>Context Guardrail:</strong> If the retrieved document context has fewer characters than this threshold,
                  the system will return an error instead of calling the LLM. This prevents hallucinations when there's insufficient context.
                  Set to <strong>0</strong> to disable. Recommended: <strong>500-800</strong> chars.
                </p>
              </div>
            </div>

            {/* Default Language (Feature #317) */}
            <div className="space-y-2 p-4 bg-light-bg dark:bg-dark-bg rounded-lg border border-green-200 dark:border-green-800">
              <label htmlFor="default-language" className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                <span className="px-1.5 py-0.5 text-[10px] font-bold bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 rounded">LANGUAGE</span>
                AI Response Language
              </label>
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                Force the AI to respond in a specific language, or auto-detect from user query
              </p>
              <select
                id="default-language"
                value={settings.default_language}
                onChange={(e) => updateSetting('default_language', e.target.value as Settings['default_language'])}
                className="w-full px-3 py-2 text-sm bg-white dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg focus:ring-2 focus:ring-primary text-light-text dark:text-dark-text"
              >
                <option value="it">🇮🇹 Italian (Italiano) - Default</option>
                <option value="en">🇬🇧 English</option>
                <option value="auto">🌐 Auto-detect from query</option>
                <option value="fr">🇫🇷 French (Français)</option>
                <option value="es">🇪🇸 Spanish (Español)</option>
                <option value="de">🇩🇪 German (Deutsch)</option>
                <option value="pt">🇵🇹 Portuguese (Português)</option>
              </select>
              <div className="mt-2 p-2 bg-green-50 dark:bg-green-900/20 rounded-lg">
                <p className="text-xs text-green-800 dark:text-green-200">
                  <strong>Tip:</strong> Setting a specific language forces all AI responses in that language.
                  "Auto-detect" analyzes each query and responds in the same language as the user.
                </p>
              </div>
            </div>

            {/* Include Chat History in Search */}
            <div className="flex items-center justify-between p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
              <div className="flex-1 mr-4">
                <label className="text-sm font-medium text-light-text dark:text-dark-text">
                  Include Chat History in Search
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Embed past conversations to provide context during RAG searches
                </p>
              </div>
              <button
                type="button"
                onClick={() => updateSetting('include_chat_history_in_search', !settings.include_chat_history_in_search)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  settings.include_chat_history_in_search ? 'bg-primary' : 'bg-light-border dark:bg-dark-border'
                }`}
                role="switch"
                aria-checked={settings.include_chat_history_in_search}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    settings.include_chat_history_in_search ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

            {/* Strict RAG Mode - Feature #182 */}
            <div className="flex items-center justify-between p-4 bg-light-bg dark:bg-dark-bg rounded-lg border border-blue-200 dark:border-blue-800">
              <div className="flex-1 mr-4">
                <label className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                  <span className="px-1.5 py-0.5 text-[10px] font-bold bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 rounded">QUALITY</span>
                  Strict RAG Mode
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Use stricter relevance thresholds (60% instead of 50%) to prevent irrelevant document citations
                </p>
              </div>
              <button
                type="button"
                onClick={() => updateSetting('strict_rag_mode', !settings.strict_rag_mode)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  settings.strict_rag_mode ? 'bg-blue-500' : 'bg-light-border dark:bg-dark-border'
                }`}
                role="switch"
                aria-checked={settings.strict_rag_mode}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    settings.strict_rag_mode ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

            {/* Configurable Relevance Thresholds - Feature #194 */}
            <div className="p-4 bg-light-bg dark:bg-dark-bg rounded-lg border border-blue-200 dark:border-blue-800">
              <label className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2 mb-2">
                <span className="px-1.5 py-0.5 text-[10px] font-bold bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 rounded">THRESHOLD</span>
                Relevance Thresholds
              </label>
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mb-4">
                Lower values show more results but may include less relevant chunks. Higher values are stricter and may miss some relevant information.
              </p>

              {/* Normal Mode Threshold */}
              <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm text-light-text dark:text-dark-text">
                    Normal Mode Threshold
                  </label>
                  <span className="text-sm font-mono bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded text-blue-600 dark:text-blue-400">
                    {(settings.min_relevance_threshold * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary whitespace-nowrap">0%</span>
                  <input
                    type="range"
                    min="0.0"
                    max="0.9"
                    step="0.01"
                    value={settings.min_relevance_threshold}
                    onChange={(e) => updateSetting('min_relevance_threshold', parseFloat(e.target.value))}
                    className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-blue-500"
                  />
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary whitespace-nowrap">90%</span>
                </div>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1 italic">
                  Used when Strict RAG Mode is OFF (default: 40%)
                </p>
              </div>

              {/* Strict Mode Threshold */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm text-light-text dark:text-dark-text">
                    Strict Mode Threshold
                  </label>
                  <span className="text-sm font-mono bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded text-blue-600 dark:text-blue-400">
                    {(settings.strict_relevance_threshold * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary whitespace-nowrap">0%</span>
                  <input
                    type="range"
                    min="0.0"
                    max="0.9"
                    step="0.01"
                    value={settings.strict_relevance_threshold}
                    onChange={(e) => updateSetting('strict_relevance_threshold', parseFloat(e.target.value))}
                    className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-blue-500"
                  />
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary whitespace-nowrap">90%</span>
                </div>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1 italic">
                  Used when Strict RAG Mode is ON (default: 60%)
                </p>
              </div>

              {/* Current Active Threshold Indicator */}
              <div className="mt-4 p-2 bg-white dark:bg-dark-sidebar rounded border border-gray-200 dark:border-gray-700">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-light-text-secondary dark:text-dark-text-secondary">
                    Currently active threshold:
                  </span>
                  <span className={`font-semibold ${settings.strict_rag_mode ? 'text-orange-600 dark:text-orange-400' : 'text-green-600 dark:text-green-400'}`}>
                    {settings.strict_rag_mode
                      ? `${(settings.strict_relevance_threshold * 100).toFixed(0)}% (Strict Mode)`
                      : `${(settings.min_relevance_threshold * 100).toFixed(0)}% (Normal Mode)`
                    }
                  </span>
                </div>
              </div>
            </div>

            {/* Hybrid Search Mode - Feature #186 */}
            <div className="p-4 bg-light-bg dark:bg-dark-bg rounded-lg border border-purple-200 dark:border-purple-800">
              <label className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2 mb-2">
                <span className="px-1.5 py-0.5 text-[10px] font-bold bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300 rounded">HYBRID</span>
                Search Mode
              </label>
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mb-3">
                Hybrid search combines semantic (vector) and keyword (BM25) search for better accuracy with acronyms and technical terms.
              </p>
              <select
                value={settings.search_mode}
                onChange={(e) => updateSetting('search_mode', e.target.value)}
                className="w-full p-2 border rounded-lg bg-white dark:bg-dark-bg border-light-border dark:border-dark-border text-sm"
              >
                <option value="hybrid">Hybrid (Vector + BM25) - Recommended</option>
                <option value="vector_only">Vector Only (Semantic Search)</option>
                <option value="bm25_only">BM25 Only (Keyword Search)</option>
              </select>
            </div>

            {/* Hybrid Alpha (Weight Balance) - Feature #186 */}
            {settings.search_mode === 'hybrid' && (
              <div className="p-4 bg-light-bg dark:bg-dark-bg rounded-lg border border-purple-200 dark:border-purple-800">
                <label className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2 mb-2">
                  <span className="px-1.5 py-0.5 text-[10px] font-bold bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300 rounded">HYBRID</span>
                  Vector/Keyword Balance
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mb-3">
                  Adjust the weight between vector (semantic) and BM25 (keyword) search. 0.5 = balanced.
                </p>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary whitespace-nowrap">BM25</span>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.1"
                    value={settings.hybrid_alpha}
                    onChange={(e) => updateSetting('hybrid_alpha', parseFloat(e.target.value))}
                    className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-purple-500"
                  />
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary whitespace-nowrap">Vector</span>
                </div>
                <div className="text-center text-xs text-light-text-secondary dark:text-dark-text-secondary mt-2">
                  Current: {(settings.hybrid_alpha * 100).toFixed(0)}% Vector, {((1 - settings.hybrid_alpha) * 100).toFixed(0)}% BM25
                </div>
              </div>
            )}

            {/* Entity Extraction Toggle - Feature #218 */}
            <div className="flex items-center justify-between p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
              <div className="flex-1 mr-4">
                <label className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                  <span className="px-1.5 py-0.5 text-[10px] font-bold bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300 rounded">HYBRID</span>
                  Entity Extraction
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Extract product codes, numbers, and proper nouns from queries for better matching (e.g., &quot;Navigat 100&quot; matches &quot;NAVIGAT/100&quot;)
                </p>
              </div>
              <button
                type="button"
                onClick={() => updateSetting('enable_entity_extraction', !settings.enable_entity_extraction)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  settings.enable_entity_extraction ? 'bg-purple-500' : 'bg-light-border dark:bg-dark-border'
                }`}
                role="switch"
                aria-checked={settings.enable_entity_extraction}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    settings.enable_entity_extraction ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

            {/* Keyword Boost Weight Slider - Feature #218 */}
            {settings.enable_entity_extraction && (
              <div className="p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                <label className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2 mb-2">
                  <span className="px-1.5 py-0.5 text-[10px] font-bold bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300 rounded">HYBRID</span>
                  Keyword Boost Weight
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mb-3">
                  How much to boost results containing exact keyword matches. Higher = stronger preference for exact matches.
                </p>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary whitespace-nowrap">Low</span>
                  <input
                    type="range"
                    min="0"
                    max="0.5"
                    step="0.05"
                    value={settings.keyword_boost_weight}
                    onChange={(e) => updateSetting('keyword_boost_weight', parseFloat(e.target.value))}
                    className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-purple-500"
                  />
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary whitespace-nowrap">High</span>
                </div>
                <div className="text-center text-xs text-light-text-secondary dark:text-dark-text-secondary mt-2">
                  Current: {(settings.keyword_boost_weight * 100).toFixed(0)}% boost per keyword match
                </div>
              </div>
            )}

            {/* Response Cache Toggle - Feature #352 */}
            <div className="flex items-center justify-between p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
              <div className="flex-1 mr-4">
                <label className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                  <span className="px-1.5 py-0.5 text-[10px] font-bold bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 rounded">CACHE</span>
                  Enable Response Cache
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Cache AI responses for similar queries. Reduces latency and LLM costs for repeated questions.
                </p>
              </div>
              <button
                type="button"
                onClick={() => updateSetting('enable_response_cache', !settings.enable_response_cache)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  settings.enable_response_cache ? 'bg-green-500' : 'bg-light-border dark:bg-dark-border'
                }`}
                role="switch"
                aria-checked={settings.enable_response_cache}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    settings.enable_response_cache ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

            {/* Cache Settings - Feature #352 */}
            {settings.enable_response_cache && (
              <>
                <div className="p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                  <label className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2 mb-2">
                    <span className="px-1.5 py-0.5 text-[10px] font-bold bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 rounded">CACHE</span>
                    Similarity Threshold
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mb-3">
                    How similar a new query must be to a cached query to return the cached response. Higher = stricter matching.
                  </p>
                  <div className="flex items-center gap-4">
                    <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary whitespace-nowrap">0.80</span>
                    <input
                      type="range"
                      min="0.80"
                      max="1.00"
                      step="0.01"
                      value={settings.cache_similarity_threshold}
                      onChange={(e) => updateSetting('cache_similarity_threshold', parseFloat(e.target.value))}
                      className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-green-500"
                    />
                    <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary whitespace-nowrap">1.00</span>
                  </div>
                  <div className="text-center text-xs text-light-text-secondary dark:text-dark-text-secondary mt-2">
                    Current: {settings.cache_similarity_threshold.toFixed(2)} ({settings.cache_similarity_threshold >= 0.98 ? 'Very strict' : settings.cache_similarity_threshold >= 0.95 ? 'Strict' : settings.cache_similarity_threshold >= 0.90 ? 'Moderate' : 'Relaxed'})
                  </div>
                </div>

                <div className="p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                  <label className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2 mb-2">
                    <span className="px-1.5 py-0.5 text-[10px] font-bold bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 rounded">CACHE</span>
                    Cache TTL (hours)
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mb-3">
                    How long cached responses remain valid before expiring. Shorter = fresher answers after document changes.
                  </p>
                  <input
                    type="number"
                    min="1"
                    max="168"
                    value={settings.cache_ttl_hours}
                    onChange={(e) => updateSetting('cache_ttl_hours', Math.max(1, Math.min(168, parseInt(e.target.value) || 24)))}
                    className="w-24 px-3 py-1.5 text-sm rounded-lg border border-light-border dark:border-dark-border bg-white dark:bg-dark-bg text-light-text dark:text-dark-text"
                  />
                  <span className="ml-2 text-xs text-light-text-secondary dark:text-dark-text-secondary">hours (1-168)</span>
                </div>
              </>
            )}

            {/* Show Retrieved Chunks (Debug Mode) - Feature #181 */}
            <div className="flex items-center justify-between p-4 bg-light-bg dark:bg-dark-bg rounded-lg border border-dashed border-amber-300 dark:border-amber-700">
              <div className="flex-1 mr-4">
                <label className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                  <span className="px-1.5 py-0.5 text-[10px] font-bold bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300 rounded">DEBUG</span>
                  Show Retrieved Chunks
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Display raw retrieved chunks in chat details panel for debugging RAG responses
                </p>
              </div>
              <button
                type="button"
                onClick={() => updateSetting('show_retrieved_chunks', !settings.show_retrieved_chunks)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  settings.show_retrieved_chunks ? 'bg-amber-500' : 'bg-light-border dark:bg-dark-border'
                }`}
                role="switch"
                aria-checked={settings.show_retrieved_chunks}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    settings.show_retrieved_chunks ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
          </div>
        </section>

        {/* Section 5: AI Behavior (Feature #179) */}
        <section id="ai-behavior" className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-6 py-4 border-b border-light-border dark:border-dark-border">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <Bot className="w-5 h-5 text-cyan-500" />
              AI Behavior
            </h2>
            <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
              Customize how the AI assistant responds
            </p>
          </div>
          <div className="p-6 space-y-4">
            {/* Custom System Prompt */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <label htmlFor="system-prompt" className="text-sm font-medium text-light-text dark:text-dark-text">
                    Custom System Prompt
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Customize how the AI assistant responds. Leave empty to use the default prompt.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {/* Preset Templates Dropdown */}
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setShowPresetDropdown(!showPresetDropdown)}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors"
                    >
                      <span>Templates</span>
                      <ChevronDown size={14} />
                    </button>
                    {showPresetDropdown && (
                      <div className="absolute right-0 mt-1 w-64 bg-white dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg shadow-lg z-50">
                        {systemPromptPresets.map((preset) => (
                          <button
                            key={preset.name}
                            type="button"
                            onClick={() => handleApplyPreset(preset)}
                            className="w-full text-left px-3 py-2 hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors first:rounded-t-lg last:rounded-b-lg"
                          >
                            <span className="block text-sm font-medium text-light-text dark:text-dark-text">
                              {preset.label}
                            </span>
                            <span className="block text-xs text-light-text-secondary dark:text-dark-text-secondary">
                              {preset.description}
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  {/* Reset to Default Button */}
                  <button
                    type="button"
                    onClick={handleResetToDefault}
                    disabled={!settings.custom_system_prompt}
                    className="flex items-center gap-1 px-3 py-1.5 text-xs border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Reset to default prompt"
                  >
                    <RotateCcw size={14} />
                    <span>Reset</span>
                  </button>
                </div>
              </div>

              {/* Textarea for System Prompt */}
              <textarea
                id="system-prompt"
                value={settings.custom_system_prompt}
                onChange={(e) => updateSetting('custom_system_prompt', e.target.value)}
                className="w-full h-48 px-3 py-2 text-sm border border-light-border dark:border-dark-border rounded-lg bg-white dark:bg-dark-bg text-light-text dark:text-dark-text font-mono resize-y focus:ring-2 focus:ring-primary/20 focus:border-primary"
                placeholder={isLoadingSystemPrompt ? 'Loading...' : 'Enter custom system prompt here, or leave empty to use the default.\n\nExample:\nYou are a helpful assistant that always responds in bullet points.\n\nAvailable placeholders:\n- The prompt will be passed directly to the AI model\n- Include instructions for tone, format, and behavior'}
              />

              {/* Character Count and Validation */}
              <div className="flex items-center justify-between text-xs text-light-text-secondary dark:text-dark-text-secondary">
                <div className="flex items-center gap-2">
                  <span>{settings.custom_system_prompt.length.toLocaleString()} / 10,000 characters</span>
                  {settings.custom_system_prompt.length > 0 && settings.custom_system_prompt.length < 50 && (
                    <span className="text-yellow-600 dark:text-yellow-400">
                      (minimum 50 characters required)
                    </span>
                  )}
                  {settings.custom_system_prompt.length > 8000 && (
                    <span className="text-yellow-600 dark:text-yellow-400">
                      (prompt is getting long, may impact response quality)
                    </span>
                  )}
                </div>
                {settings.custom_system_prompt ? (
                  <span className="text-primary">Custom prompt active</span>
                ) : (
                  <span>Using default prompt</span>
                )}
              </div>

              {/* Save/Test Buttons for System Prompt */}
              <div className="flex items-center gap-2 pt-2 border-t border-light-border dark:border-dark-border">
                <button
                  type="button"
                  onClick={() => handleSaveSystemPrompt(settings.custom_system_prompt)}
                  disabled={isSavingSystemPrompt || (settings.custom_system_prompt.length > 0 && settings.custom_system_prompt.length < 50)}
                  className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isSavingSystemPrompt ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <Save size={14} />
                      Save Prompt
                    </>
                  )}
                </button>
                <button
                  type="button"
                  onClick={handleTestPrompt}
                  disabled={isTestingPrompt || !settings.llm_model}
                  className="flex items-center gap-2 px-4 py-2 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isTestingPrompt ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      Testing...
                    </>
                  ) : (
                    <>
                      <Play size={14} />
                      Test Prompt
                    </>
                  )}
                </button>
                {systemPromptSaveSuccess && (
                  <span className="flex items-center gap-1 text-sm text-green-600 dark:text-green-400">
                    <CheckCircle2 size={14} />
                    Saved!
                  </span>
                )}
              </div>

              {/* Test Prompt Input and Result */}
              {(isTestingPrompt || testPromptResult) && (
                <div className="space-y-2 pt-2">
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={testPromptMessage}
                      onChange={(e) => setTestPromptMessage(e.target.value)}
                      placeholder="Enter test message..."
                      className="flex-1 px-3 py-2 text-sm border border-light-border dark:border-dark-border rounded-lg bg-white dark:bg-dark-bg text-light-text dark:text-dark-text focus:ring-2 focus:ring-primary/20 focus:border-primary"
                    />
                  </div>
                  {testPromptResult && (
                    <div className={`p-3 rounded-lg text-sm ${
                      testPromptResult.success
                        ? 'bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-200'
                        : 'bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200'
                    }`}>
                      {testPromptResult.success ? (
                        <>
                          <p className="font-medium mb-1">AI Response:</p>
                          <p className="whitespace-pre-wrap">{testPromptResult.response}</p>
                        </>
                      ) : (
                        <>
                          <p className="font-medium">Error:</p>
                          <p>{testPromptResult.error}</p>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* System Prompt Error */}
              {systemPromptError && (
                <div className="flex items-center gap-2 p-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg">
                  <AlertTriangle size={14} />
                  {systemPromptError}
                </div>
              )}
            </div>

            {/* Suggested Questions Toggle (Feature #199) */}
            <div className="flex items-center justify-between pt-4 border-t border-light-border dark:border-dark-border">
              <div>
                <label className="text-sm font-medium text-light-text dark:text-dark-text">
                  Suggested Questions
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Show AI-generated question suggestions when viewing documents to help users get started
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={settings.enable_suggested_questions ?? true}
                onClick={() => updateSetting('enable_suggested_questions', !(settings.enable_suggested_questions ?? true))}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 ${
                  (settings.enable_suggested_questions ?? true)
                    ? 'bg-primary'
                    : 'bg-gray-300 dark:bg-gray-600'
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                    (settings.enable_suggested_questions ?? true) ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            {/* Typewriter Effect Toggle (Feature #201) */}
            <div className="flex items-center justify-between pt-4 border-t border-light-border dark:border-dark-border">
              <div>
                <label className="text-sm font-medium text-light-text dark:text-dark-text">
                  Typewriter Effect
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Display AI responses with a typewriter animation, character by character
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={settings.enable_typewriter ?? true}
                onClick={() => updateSetting('enable_typewriter', !(settings.enable_typewriter ?? true))}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 ${
                  (settings.enable_typewriter ?? true)
                    ? 'bg-primary'
                    : 'bg-gray-300 dark:bg-gray-600'
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                    (settings.enable_typewriter ?? true) ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
          </div>
        </section>

        {/* Section 6: Appearance */}
        <section id="appearance" className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-6 py-4 border-b border-light-border dark:border-dark-border">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <Palette className="w-5 h-5 text-pink-500" />
              Appearance
            </h2>
            <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
              Customize the look and feel
            </p>
          </div>
          <div className="p-6">
            <div className="flex gap-3">
              {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => updateSetting('theme', value)}
                  className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border transition-colors ${
                    settings.theme === value
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-light-border dark:border-dark-border text-light-text dark:text-dark-text hover:border-primary/50'
                  }`}
                >
                  <Icon size={18} />
                  <span className="text-sm font-medium">{label}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* Section 6: Backup & Restore */}
        <section id="backup" className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-6 py-4 border-b border-light-border dark:border-dark-border">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
                  <HardDrive className="w-5 h-5 text-indigo-500" />
                  Backup & Restore
                </h2>
                <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Create and restore data backups
                </p>
              </div>
              <button
                type="button"
                onClick={loadBackupStatus}
                disabled={isLoadingBackup}
                className="flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors disabled:opacity-50"
              >
                <RefreshCw size={14} className={isLoadingBackup ? 'animate-spin' : ''} />
                {isLoadingBackup ? 'Loading...' : 'Refresh'}
              </button>
            </div>
          </div>
          <div className="p-6 space-y-4">
            {/* Backup Status */}
            {backupStatus && (
              <div className="grid grid-cols-2 gap-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                <div className="flex items-center gap-2 text-sm">
                  <FileText size={16} className="text-light-text-secondary" />
                  <span className="text-light-text-secondary">Documents:</span>
                  <span className="font-medium text-light-text dark:text-dark-text">{backupStatus.documents}</span>
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <FolderOpen size={16} className="text-light-text-secondary" />
                  <span className="text-light-text-secondary">Collections:</span>
                  <span className="font-medium text-light-text dark:text-dark-text">{backupStatus.collections}</span>
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <MessageSquare size={16} className="text-light-text-secondary" />
                  <span className="text-light-text-secondary">Conversations:</span>
                  <span className="font-medium text-light-text dark:text-dark-text">{backupStatus.conversations}</span>
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <HardDrive size={16} className="text-light-text-secondary" />
                  <span className="text-light-text-secondary">Files:</span>
                  <span className="font-medium text-light-text dark:text-dark-text">
                    {backupStatus.uploaded_files_count} ({backupStatus.uploaded_files_size_human})
                  </span>
                </div>
              </div>
            )}

            {/* Backup Button */}
            <button
              type="button"
              onClick={handleCreateBackup}
              disabled={isCreatingBackup}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg border border-primary text-primary hover:bg-primary hover:text-white transition-colors disabled:opacity-50"
            >
              {isCreatingBackup ? (
                <>
                  <Loader2 size={18} className="animate-spin" />
                  Creating Backup...
                </>
              ) : (
                <>
                  <Download size={18} />
                  Create Full Backup
                </>
              )}
            </button>

            <div className="border-t border-light-border dark:border-dark-border my-4" />

            {/* Automatic Backup Section (Feature #212) */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                    <Clock size={16} className="text-primary" />
                    Automatic Daily Backup
                  </h4>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Schedule automatic backups to run daily at a specified time
                  </p>
                </div>
                <button
                  type="button"
                  onClick={loadAutoBackupStatus}
                  disabled={isLoadingAutoBackup}
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors disabled:opacity-50"
                >
                  <RefreshCw size={14} className={isLoadingAutoBackup ? 'animate-spin' : ''} />
                  {isLoadingAutoBackup ? 'Loading...' : 'Refresh'}
                </button>
              </div>

              {/* Auto Backup Toggle */}
              <div className="flex items-center justify-between p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-5 rounded-full flex items-center transition-colors cursor-pointer ${
                    autoBackupStatus?.enabled ? 'bg-primary justify-end' : 'bg-gray-300 dark:bg-gray-600 justify-start'
                  }`}
                    onClick={() => handleToggleAutoBackup(!autoBackupStatus?.enabled)}
                  >
                    <div className="w-4 h-4 rounded-full bg-white shadow-sm mx-0.5" />
                  </div>
                  <span className="text-sm text-light-text dark:text-dark-text">
                    {autoBackupStatus?.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
                {autoBackupStatus?.enabled && (
                  <span className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1">
                    <Check size={12} />
                    Active
                  </span>
                )}
              </div>

              {/* Backup Time Configuration */}
              <div className="space-y-2">
                <label className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                  Backup Time (UTC)
                </label>
                <div className="flex items-center gap-2">
                  <select
                    value={autoBackupHour}
                    onChange={(e) => setAutoBackupHour(Number(e.target.value))}
                    className="px-3 py-2 rounded-lg border border-light-border dark:border-dark-border bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text text-sm"
                  >
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={i}>{i.toString().padStart(2, '0')}</option>
                    ))}
                  </select>
                  <span className="text-light-text dark:text-dark-text">:</span>
                  <select
                    value={autoBackupMinute}
                    onChange={(e) => setAutoBackupMinute(Number(e.target.value))}
                    className="px-3 py-2 rounded-lg border border-light-border dark:border-dark-border bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text text-sm"
                  >
                    {[0, 15, 30, 45].map((m) => (
                      <option key={m} value={m}>{m.toString().padStart(2, '0')}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={handleUpdateAutoBackupTime}
                    className="px-3 py-2 rounded-lg bg-primary text-white text-sm hover:bg-primary/90 transition-colors"
                  >
                    Save Time
                  </button>
                </div>
              </div>

              {/* Auto Backup Status */}
              {autoBackupStatus && (
                <div className="grid grid-cols-2 gap-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg text-xs">
                  <div className="flex items-center gap-2">
                    <Clock size={14} className="text-light-text-secondary" />
                    <span className="text-light-text-secondary">Scheduled:</span>
                    <span className="font-medium text-light-text dark:text-dark-text">
                      {autoBackupStatus.backup_time_formatted}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Calendar size={14} className="text-light-text-secondary" />
                    <span className="text-light-text-secondary">Last Backup:</span>
                    <span className="font-medium text-light-text dark:text-dark-text">
                      {autoBackupStatus.last_backup_time
                        ? new Date(autoBackupStatus.last_backup_time).toLocaleString()
                        : 'Never'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {autoBackupStatus.last_backup_status === 'success' ? (
                      <Check size={14} className="text-green-500" />
                    ) : autoBackupStatus.last_backup_status === 'failed' ? (
                      <X size={14} className="text-red-500" />
                    ) : (
                      <Clock size={14} className="text-gray-400" />
                    )}
                    <span className="text-light-text-secondary">Status:</span>
                    <span className={`font-medium ${
                      autoBackupStatus.last_backup_status === 'success'
                        ? 'text-green-600 dark:text-green-400'
                        : autoBackupStatus.last_backup_status === 'failed'
                        ? 'text-red-600 dark:text-red-400'
                        : 'text-light-text dark:text-dark-text'
                    }`}>
                      {autoBackupStatus.last_backup_status === 'never'
                        ? 'No backup yet'
                        : autoBackupStatus.last_backup_status}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <HardDrive size={14} className="text-light-text-secondary" />
                    <span className="text-light-text-secondary">Retention:</span>
                    <span className="font-medium text-light-text dark:text-dark-text">
                      {autoBackupStatus.daily_retention} daily, {autoBackupStatus.weekly_retention} weekly
                    </span>
                  </div>
                  {autoBackupStatus.next_backup_time && (
                    <div className="col-span-2 flex items-center gap-2 pt-2 border-t border-light-border dark:border-dark-border">
                      <Calendar size={14} className="text-primary" />
                      <span className="text-light-text-secondary">Next Backup:</span>
                      <span className="font-medium text-primary">
                        {new Date(autoBackupStatus.next_backup_time).toLocaleString()}
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Run Backup Now Button */}
              <button
                type="button"
                onClick={handleRunAutoBackupNow}
                disabled={isRunningAutoBackup}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg border border-light-border dark:border-dark-border text-light-text dark:text-dark-text hover:bg-light-bg dark:hover:bg-dark-bg transition-colors disabled:opacity-50"
              >
                {isRunningAutoBackup ? (
                  <>
                    <Loader2 size={18} className="animate-spin" />
                    Running Backup...
                  </>
                ) : (
                  <>
                    <Play size={18} />
                    Run Backup Now
                  </>
                )}
              </button>

              {/* Auto Backup Error */}
              {autoBackupStatus?.last_backup_error && (
                <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
                  <span className="font-medium">Last Error:</span> {autoBackupStatus.last_backup_error}
                </div>
              )}
            </div>

            <div className="border-t border-light-border dark:border-dark-border my-4" />

            {/* Restore Section */}
            <h4 className="text-sm font-medium text-light-text dark:text-dark-text">Restore from Backup</h4>

            {showRestoreConfirm && selectedRestoreFile && (
              <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 space-y-3">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-0.5" size={20} />
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200">Confirm Restore</p>
                    <p className="text-xs text-yellow-700 dark:text-yellow-300">
                      This will <strong>replace all existing data</strong> with "{selectedRestoreFile.name}".
                    </p>
                  </div>
                </div>
                <div className="flex gap-2 justify-end">
                  <button type="button" onClick={handleCancelRestore} className="px-3 py-1.5 text-sm text-light-text-secondary hover:text-light-text transition-colors">
                    Cancel
                  </button>
                  <button type="button" onClick={handleConfirmRestore} className="px-3 py-1.5 text-sm bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 transition-colors">
                    Yes, Restore Data
                  </button>
                </div>
              </div>
            )}

            {!showRestoreConfirm && (
              <>
                <input type="file" ref={restoreFileInputRef} accept=".zip" onChange={handleRestoreFileSelect} className="hidden" />
                <button
                  type="button"
                  onClick={() => restoreFileInputRef.current?.click()}
                  disabled={isRestoring}
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg border border-light-border dark:border-dark-border text-light-text dark:text-dark-text hover:bg-light-bg dark:hover:bg-dark-bg transition-colors disabled:opacity-50"
                >
                  {isRestoring ? (
                    <>
                      <Loader2 size={18} className="animate-spin" />
                      Restoring...
                    </>
                  ) : (
                    <>
                      <Upload size={18} />
                      Select Backup File to Restore
                    </>
                  )}
                </button>
              </>
            )}

            {restoreSuccess && (
              <div className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-3 py-2 rounded-lg">
                <div className="flex items-center gap-2">
                  <Check size={14} />
                  <span className="font-medium">Restore completed!</span>
                </div>
                <div className="pl-5 mt-1">
                  Documents: {restoreSuccess.documents_restored}, Collections: {restoreSuccess.collections_restored}, Conversations: {restoreSuccess.conversations_restored}
                </div>
              </div>
            )}

            {restoreError && (
              <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
                {restoreError}
              </div>
            )}

            <div className="border-t border-light-border dark:border-dark-border my-4" />

            {/* Automatic Backup Section (Feature #221) */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                    <Clock size={16} className="text-primary" />
                    Automatic Daily Backup
                  </h4>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Schedule automatic backups with rotation policy (7 daily + 4 weekly)
                  </p>
                </div>
                <button
                  type="button"
                  onClick={loadAutoBackupStatus}
                  disabled={isLoadingAutoBackup}
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors disabled:opacity-50"
                >
                  <RefreshCw size={14} className={isLoadingAutoBackup ? 'animate-spin' : ''} />
                </button>
              </div>

              {/* Enable/Disable Toggle */}
              <div className="flex items-center justify-between p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                <div className="flex items-center gap-3">
                  <div className={`w-3 h-3 rounded-full ${autoBackupStatus?.enabled ? 'bg-green-500' : 'bg-gray-400'}`} />
                  <span className="text-sm text-light-text dark:text-dark-text">
                    {autoBackupStatus?.enabled ? 'Automatic backups enabled' : 'Automatic backups disabled'}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => handleToggleAutoBackup(!autoBackupStatus?.enabled)}
                  className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    autoBackupStatus?.enabled
                      ? 'bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/30'
                      : 'bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900/20 dark:text-green-400 dark:hover:bg-green-900/30'
                  }`}
                >
                  {autoBackupStatus?.enabled ? 'Disable' : 'Enable'}
                </button>
              </div>

              {/* Backup Time Configuration */}
              <div className="flex items-center gap-4 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                <div className="flex-1">
                  <label className="text-xs text-light-text-secondary dark:text-dark-text-secondary block mb-1">
                    Backup Time (UTC)
                  </label>
                  <div className="flex items-center gap-2">
                    <select
                      value={autoBackupHour}
                      onChange={(e) => setAutoBackupHour(parseInt(e.target.value))}
                      className="px-3 py-1.5 rounded-lg border border-light-border dark:border-dark-border bg-light-sidebar dark:bg-dark-sidebar text-light-text dark:text-dark-text text-sm"
                    >
                      {Array.from({ length: 24 }, (_, i) => (
                        <option key={i} value={i}>{i.toString().padStart(2, '0')}</option>
                      ))}
                    </select>
                    <span className="text-light-text-secondary">:</span>
                    <select
                      value={autoBackupMinute}
                      onChange={(e) => setAutoBackupMinute(parseInt(e.target.value))}
                      className="px-3 py-1.5 rounded-lg border border-light-border dark:border-dark-border bg-light-sidebar dark:bg-dark-sidebar text-light-text dark:text-dark-text text-sm"
                    >
                      {[0, 15, 30, 45].map((m) => (
                        <option key={m} value={m}>{m.toString().padStart(2, '0')}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={handleUpdateAutoBackupTime}
                      disabled={(autoBackupHour === autoBackupStatus?.backup_hour && autoBackupMinute === autoBackupStatus?.backup_minute)}
                      className="px-3 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                    >
                      Update
                    </button>
                  </div>
                </div>
              </div>

              {/* Status Info */}
              {autoBackupStatus && (
                <div className="grid grid-cols-2 gap-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg text-sm">
                  <div>
                    <span className="text-light-text-secondary dark:text-dark-text-secondary">Last Backup:</span>
                    <span className={`ml-2 font-medium ${
                      autoBackupStatus.last_backup_status === 'success' ? 'text-green-600 dark:text-green-400' :
                      autoBackupStatus.last_backup_status === 'failed' ? 'text-red-600 dark:text-red-400' :
                      'text-light-text dark:text-dark-text'
                    }`}>
                      {autoBackupStatus.last_backup_time
                        ? new Date(autoBackupStatus.last_backup_time).toLocaleString()
                        : 'Never'}
                    </span>
                  </div>
                  <div>
                    <span className="text-light-text-secondary dark:text-dark-text-secondary">Status:</span>
                    <span className={`ml-2 font-medium ${
                      autoBackupStatus.last_backup_status === 'success' ? 'text-green-600 dark:text-green-400' :
                      autoBackupStatus.last_backup_status === 'failed' ? 'text-red-600 dark:text-red-400' :
                      'text-light-text dark:text-dark-text'
                    }`}>
                      {autoBackupStatus.last_backup_status === 'success' ? '✓ Success' :
                       autoBackupStatus.last_backup_status === 'failed' ? '✗ Failed' :
                       'Never run'}
                    </span>
                  </div>
                  {autoBackupStatus.next_backup_time && (
                    <div className="col-span-2">
                      <span className="text-light-text-secondary dark:text-dark-text-secondary">Next Backup:</span>
                      <span className="ml-2 font-medium text-light-text dark:text-dark-text">
                        {new Date(autoBackupStatus.next_backup_time).toLocaleString()}
                      </span>
                    </div>
                  )}
                  {autoBackupStatus.last_backup_error && (
                    <div className="col-span-2 text-xs text-red-600 dark:text-red-400 mt-1">
                      Error: {autoBackupStatus.last_backup_error}
                    </div>
                  )}
                </div>
              )}

              {/* Run Backup Now Button */}
              <button
                type="button"
                onClick={handleRunAutoBackupNow}
                disabled={isRunningAutoBackup || autoBackupStatus?.backup_in_progress}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg border border-primary text-primary hover:bg-primary hover:text-white transition-colors disabled:opacity-50"
              >
                {isRunningAutoBackup || autoBackupStatus?.backup_in_progress ? (
                  <>
                    <Loader2 size={18} className="animate-spin" />
                    Running Backup...
                  </>
                ) : (
                  <>
                    <Play size={18} />
                    Run Backup Now
                  </>
                )}
              </button>

              {/* Recent Backups List */}
              {autoBackupList && autoBackupList.count > 0 && (
                <div className="space-y-2">
                  <h5 className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary">
                    Recent Automatic Backups ({autoBackupList.count})
                  </h5>
                  <div className="max-h-32 overflow-y-auto space-y-1">
                    {autoBackupList.backups.slice(0, 5).map((backup, index) => (
                      <div
                        key={index}
                        className="flex items-center justify-between text-xs p-2 bg-light-bg dark:bg-dark-bg rounded"
                      >
                        <div className="flex items-center gap-2">
                          <span className={backup.is_weekly ? 'text-blue-600 dark:text-blue-400' : 'text-light-text-secondary'}>
                            {backup.is_weekly ? '📅 Weekly' : '📆 Daily'}
                          </span>
                          <span className="text-light-text dark:text-dark-text">{backup.name}</span>
                        </div>
                        <span className="text-light-text-secondary">{backup.total_size_human}</span>
                      </div>
                    ))}
                  </div>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                    Retention: {autoBackupStatus?.daily_retention} daily + {autoBackupStatus?.weekly_retention} weekly backups
                  </p>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* Feedback Analytics */}
        <FeedbackAnalytics className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border" />

        {/* Section 7: System (Feature #198) */}
        <section id="system" className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-6 py-4 border-b border-light-border dark:border-dark-border">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <Server className="w-5 h-5" />
              System
            </h2>
            <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
              System diagnostics and RAG pipeline testing
            </p>
          </div>
          <div className="p-6 space-y-4">
            {/* RAG Self-Test */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-sm font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                    <Activity size={16} className="text-primary" />
                    RAG Pipeline Self-Test
                  </span>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Test all RAG components: embedding model, vector store, reranking, and LLM connectivity
                  </p>
                </div>
                <button
                  onClick={handleRunSelfTest}
                  disabled={isRunningSelfTest}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {isRunningSelfTest ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      Running...
                    </>
                  ) : (
                    <>
                      <Play size={16} />
                      Run Self-Test
                    </>
                  )}
                </button>
              </div>

              {/* Self-Test Error */}
              {selfTestError && (
                <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg flex items-center gap-2">
                  <XCircle size={14} />
                  {selfTestError}
                </div>
              )}

              {/* Self-Test Results */}
              {selfTestResult && (
                <div className="space-y-3 bg-light-bg dark:bg-dark-bg rounded-lg p-4 border border-light-border dark:border-dark-border">
                  {/* Overall Status */}
                  <div className={`flex items-center gap-2 ${
                    selfTestResult.overall_status === 'pass'
                      ? 'text-green-600 dark:text-green-400'
                      : selfTestResult.overall_status === 'partial'
                        ? 'text-yellow-600 dark:text-yellow-400'
                        : 'text-red-600 dark:text-red-400'
                  }`}>
                    {selfTestResult.overall_status === 'pass' ? (
                      <CheckCircle2 size={18} />
                    ) : selfTestResult.overall_status === 'partial' ? (
                      <AlertTriangle size={18} />
                    ) : (
                      <XCircle size={18} />
                    )}
                    <span className="font-medium">
                      {selfTestResult.overall_status === 'pass'
                        ? 'All Tests Passed'
                        : selfTestResult.overall_status === 'partial'
                          ? 'Partial Success'
                          : 'Tests Failed'}
                    </span>
                    <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                      ({selfTestResult.summary.components_passed}/{selfTestResult.summary.components_total} components)
                    </span>
                  </div>

                  {/* Component Tests */}
                  <div className="space-y-2">
                    <span className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
                      Component Tests
                    </span>
                    <div className="grid gap-2">
                      {selfTestResult.component_tests.map((test: ComponentTestResult, index: number) => (
                        <div
                          key={index}
                          className={`flex items-center justify-between p-2 rounded-lg ${
                            test.passed
                              ? 'bg-green-50 dark:bg-green-900/20'
                              : 'bg-red-50 dark:bg-red-900/20'
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            {test.passed ? (
                              <CheckCircle2 size={14} className="text-green-600 dark:text-green-400" />
                            ) : (
                              <XCircle size={14} className="text-red-600 dark:text-red-400" />
                            )}
                            <span className="text-sm font-medium capitalize text-light-text dark:text-dark-text">
                              {test.component.replace('_', ' ')}
                            </span>
                          </div>
                          <span className={`text-xs ${
                            test.passed
                              ? 'text-green-600 dark:text-green-400'
                              : 'text-red-600 dark:text-red-400'
                          }`}>
                            {test.message.length > 50 ? test.message.substring(0, 50) + '...' : test.message}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Document Tests (if any) */}
                  {selfTestResult.document_tests.length > 0 && (
                    <div className="space-y-2">
                      <span className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
                        Document Retrieval Tests ({selfTestResult.summary.documents_passed}/{selfTestResult.summary.documents_tested} passed)
                      </span>
                      <div className="grid gap-2 max-h-40 overflow-y-auto">
                        {selfTestResult.document_tests.map((test: DocumentTestResult, index: number) => (
                          <div
                            key={index}
                            className={`flex items-center justify-between p-2 rounded-lg ${
                              test.passed
                                ? 'bg-green-50 dark:bg-green-900/20'
                                : 'bg-red-50 dark:bg-red-900/20'
                            }`}
                          >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              {test.passed ? (
                                <CheckCircle2 size={14} className="text-green-600 dark:text-green-400 flex-shrink-0" />
                              ) : (
                                <XCircle size={14} className="text-red-600 dark:text-red-400 flex-shrink-0" />
                              )}
                              <span className="text-sm truncate text-light-text dark:text-dark-text">
                                {test.document_name}
                              </span>
                            </div>
                            <span className={`text-xs flex-shrink-0 ml-2 ${
                              test.passed
                                ? 'text-green-600 dark:text-green-400'
                                : 'text-red-600 dark:text-red-400'
                            }`}>
                              {test.chunks_retrieved} chunks
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* No documents message */}
                  {selfTestResult.document_tests.length === 0 && (
                    <div className="text-xs text-light-text-secondary dark:text-dark-text-secondary bg-light-bg dark:bg-dark-bg p-2 rounded-lg">
                      No unstructured documents found for RAG testing. Upload text documents (PDF, TXT, Word, Markdown) to test document retrieval.
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </section>

        {/* Section: Configuration Guide */}
        <section id="config-guide" className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-6 py-4 border-b border-light-border dark:border-dark-border">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-amber-500" />
              Configuration Guide
            </h2>
            <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
              How to configure your RAG system for optimal document retrieval
            </p>
          </div>
          <div className="p-6 space-y-5">

            {/* Pipeline Overview */}
            <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
              <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-100 flex items-center gap-2 mb-2">
                <Zap size={16} />
                How the RAG Pipeline Works
              </h3>
              <div className="text-xs text-blue-800 dark:text-blue-200 space-y-1">
                <p>When you upload a document, the system processes it in 4 stages:</p>
                <ol className="list-decimal list-inside space-y-1 mt-2 ml-2">
                  <li><strong>Extraction</strong> &mdash; Text and tables are extracted from the file (PDF, Word, etc.)</li>
                  <li><strong>Chunking</strong> &mdash; The text is split into semantic chunks using the selected strategy</li>
                  <li><strong>Embedding</strong> &mdash; Each chunk is converted to a vector using the embedding model</li>
                  <li><strong>Indexing</strong> &mdash; Vectors are stored in PostgreSQL with HNSW index for fast search</li>
                </ol>
                <p className="mt-2">When you ask a question, the system searches both by <strong>semantic similarity</strong> (vector) and <strong>keyword matching</strong> (BM25), then re-ranks results for accuracy.</p>
              </div>
            </div>

            {/* Chunking Strategy */}
            <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800">
              <h3 className="text-sm font-semibold text-green-900 dark:text-green-100 flex items-center gap-2 mb-2">
                <Sliders size={16} />
                Chunking Strategy
              </h3>
              <div className="text-xs text-green-800 dark:text-green-200 space-y-2">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="p-2 bg-white/50 dark:bg-black/20 rounded">
                    <p className="font-bold">Agentic (Recommended)</p>
                    <p>Uses an LLM to find natural topic transitions. Best for technical/regulatory documents. Slower but highest quality.</p>
                  </div>
                  <div className="p-2 bg-white/50 dark:bg-black/20 rounded">
                    <p className="font-bold">Semantic</p>
                    <p>Detects document structure (headings, sections, lists). Good balance of speed and quality. No LLM cost.</p>
                  </div>
                  <div className="p-2 bg-white/50 dark:bg-black/20 rounded">
                    <p className="font-bold">Fixed Size</p>
                    <p>Splits at fixed character intervals. Fast but may break mid-sentence. Use only for simple text.</p>
                  </div>
                </div>
                <p className="mt-1"><strong>Tip:</strong> For the Chunking LLM, use a small fast model (e.g., gemma3:4b). The task is simple &mdash; it only needs to find where topics change.</p>
              </div>
            </div>

            {/* Embedding Models */}
            <div className="p-4 bg-purple-50 dark:bg-purple-900/20 rounded-lg border border-purple-200 dark:border-purple-800">
              <h3 className="text-sm font-semibold text-purple-900 dark:text-purple-100 flex items-center gap-2 mb-2">
                <Database size={16} />
                Embedding Models
              </h3>
              <div className="text-xs text-purple-800 dark:text-purple-200 space-y-2">
                <p>The embedding model converts text chunks into numerical vectors for similarity search. <strong>Changing the model requires re-embedding all documents.</strong></p>
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-purple-300 dark:border-purple-700">
                        <th className="py-1 pr-3">Model</th>
                        <th className="py-1 pr-3">Dims</th>
                        <th className="py-1 pr-3">HNSW Index</th>
                        <th className="py-1 pr-3">Quality</th>
                        <th className="py-1">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b border-purple-200 dark:border-purple-800">
                        <td className="py-1 pr-3 font-medium">bge-m3 (Ollama)</td>
                        <td className="py-1 pr-3">1024</td>
                        <td className="py-1 pr-3 text-green-600 dark:text-green-400">Yes</td>
                        <td className="py-1 pr-3">Excellent (111 languages)</td>
                        <td className="py-1">Free</td>
                      </tr>
                      <tr className="border-b border-purple-200 dark:border-purple-800">
                        <td className="py-1 pr-3 font-medium">text-embedding-3-small (OpenAI)</td>
                        <td className="py-1 pr-3">1536</td>
                        <td className="py-1 pr-3 text-green-600 dark:text-green-400">Yes</td>
                        <td className="py-1 pr-3">Excellent</td>
                        <td className="py-1">$0.02/1M tokens</td>
                      </tr>
                      <tr>
                        <td className="py-1 pr-3 font-medium">qwen3-embedding (Ollama)</td>
                        <td className="py-1 pr-3">4096</td>
                        <td className="py-1 pr-3 text-red-600 dark:text-red-400">No (too large)</td>
                        <td className="py-1 pr-3">Good</td>
                        <td className="py-1">Free</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p className="mt-1"><strong>Important:</strong> Models with &gt;2000 dimensions cannot use HNSW vector indexing in PostgreSQL. This means search falls back to sequential scan, which is much slower as your document collection grows.</p>
              </div>
            </div>

            {/* Search Configuration */}
            <div className="p-4 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
              <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-100 flex items-center gap-2 mb-2">
                <Search size={16} />
                Search &amp; Retrieval
              </h3>
              <div className="text-xs text-amber-800 dark:text-amber-200 space-y-2">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="p-2 bg-white/50 dark:bg-black/20 rounded">
                    <p className="font-bold">Hybrid Search (Recommended)</p>
                    <p>Combines vector similarity + BM25 keyword matching. Essential for technical documents with acronyms (GMDSS, VHF, ISO, etc.) that pure vector search might miss.</p>
                  </div>
                  <div className="p-2 bg-white/50 dark:bg-black/20 rounded">
                    <p className="font-bold">Cohere Reranking</p>
                    <p>After initial retrieval, Cohere re-orders results by topical relevance. Significantly improves accuracy for domain-specific queries. Requires Cohere API key.</p>
                  </div>
                </div>
                <p><strong>Hybrid Alpha (0.0-1.0):</strong> Controls the balance between BM25 keywords (0.0) and vector similarity (1.0). Default 0.6 favors semantic understanding while still catching exact terms.</p>
              </div>
            </div>

            {/* Quality Tips */}
            <div className="p-4 bg-rose-50 dark:bg-rose-900/20 rounded-lg border border-rose-200 dark:border-rose-800">
              <h3 className="text-sm font-semibold text-rose-900 dark:text-rose-100 flex items-center gap-2 mb-2">
                <Shield size={16} />
                Quality Tips
              </h3>
              <div className="text-xs text-rose-800 dark:text-rose-200 space-y-1">
                <ul className="list-disc list-inside space-y-1">
                  <li><strong>Strict RAG Mode:</strong> Enable this to prevent the AI from hallucinating. It will only answer based on retrieved documents.</li>
                  <li><strong>Show Retrieved Chunks:</strong> Enable this to see which document sections the AI used. Useful for verifying answer accuracy.</li>
                  <li><strong>Relevance Threshold:</strong> Lower values (0.3-0.5) return more results. Higher values (0.7-0.9) are stricter but may miss relevant content.</li>
                  <li><strong>Retrieved Chunks Count (top_k):</strong> How many chunks to feed the AI. More chunks = more context but higher token cost. 5-10 is a good range.</li>
                  <li><strong>Re-embed after model change:</strong> If you change the embedding model, you must re-embed all documents from the document management page.</li>
                </ul>
              </div>
            </div>

            {/* Current Configuration Summary */}
            <div className="p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-2">Current Configuration</h3>
              <div className="text-xs text-gray-700 dark:text-gray-300 grid grid-cols-2 md:grid-cols-3 gap-2">
                <div><span className="text-gray-500">Embedding:</span> <strong>{settings.embedding_model || 'Not set'}</strong></div>
                <div><span className="text-gray-500">Chunking:</span> <strong>{settings.chunk_strategy || 'agentic'}</strong></div>
                <div><span className="text-gray-500">Search:</span> <strong>{settings.search_mode || 'vector_only'}</strong></div>
                <div><span className="text-gray-500">Reranking:</span> <strong>{settings.enable_reranking ? 'Enabled' : 'Disabled'}</strong></div>
                <div><span className="text-gray-500">Strict Mode:</span> <strong>{settings.strict_rag_mode ? 'On' : 'Off'}</strong></div>
                <div><span className="text-gray-500">Chunk Size:</span> <strong>{settings.max_chunk_size}</strong></div>
              </div>
            </div>

          </div>
        </section>

        {/* Section 8: Danger Zone */}
        <section id="danger" className="rounded-xl border-2 border-red-500 dark:border-red-600 bg-red-50 dark:bg-red-900/10 overflow-hidden">
          <div className="px-6 py-4 border-b border-red-300 dark:border-red-700">
            <h2 className="text-lg font-semibold text-red-700 dark:text-red-400 flex items-center gap-2">
              <AlertTriangle className="w-5 h-5" />
              Danger Zone
            </h2>
            <p className="text-sm text-red-600 dark:text-red-300 mt-1">
              Destructive actions that cannot be undone
            </p>
          </div>
          <div className="p-6 space-y-4">
            {/* Feature #213: Pre-destructive backup toggle */}
            <div className="bg-white dark:bg-dark-bg border border-amber-300 dark:border-amber-700 rounded-lg p-4">
              <div className="flex items-start gap-4">
                <div className="flex-shrink-0 pt-0.5">
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={settings.require_backup_before_delete}
                      onChange={(e) => setSettings(prev => ({ ...prev, require_backup_before_delete: e.target.checked }))}
                      className="sr-only peer"
                    />
                    <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-amber-300 dark:peer-focus:ring-amber-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-amber-500"></div>
                  </label>
                </div>
                <div className="flex-grow">
                  <div className="flex items-center gap-2">
                    <HardDrive size={16} className="text-amber-600 dark:text-amber-400" />
                    <span className="font-medium text-amber-800 dark:text-amber-200">Backup Before Delete</span>
                  </div>
                  <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
                    Automatically create a backup before any destructive operation (reset database, bulk delete, collection cascade delete). Recommended to keep enabled for data safety.
                  </p>
                  {settings.require_backup_before_delete && (
                    <p className="text-xs text-green-600 dark:text-green-400 mt-2 flex items-center gap-1">
                      <CheckCircle2 size={12} />
                      Backups will be saved to <code className="bg-amber-100 dark:bg-amber-900/30 px-1 rounded">backend/backups/pre-delete/</code>
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Feature #214: Double confirmation with data preview and countdown */}
            {showResetConfirm && (
              <div className="bg-white dark:bg-dark-bg border border-red-300 dark:border-red-700 rounded-lg p-4 space-y-4">
                <div className="space-y-2">
                  <p className="text-sm font-medium text-red-800 dark:text-red-200">⚠️ Confirm Database Reset</p>
                  <p className="text-xs text-red-700 dark:text-red-300">
                    This will <strong>permanently delete ALL</strong> your data. Settings will be preserved.
                  </p>
                </div>

                {/* Data preview showing what will be deleted */}
                {isLoadingPreview ? (
                  <div className="flex items-center justify-center py-4">
                    <Loader2 size={20} className="animate-spin text-red-500" />
                    <span className="ml-2 text-sm text-red-600">Loading data preview...</span>
                  </div>
                ) : resetPreview && (
                  <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-3 space-y-2">
                    <p className="text-xs font-medium text-red-800 dark:text-red-200 flex items-center gap-1">
                      <AlertTriangle size={14} />
                      The following will be permanently deleted:
                    </p>
                    <ul className="text-xs text-red-700 dark:text-red-300 space-y-1 pl-5 list-disc">
                      <li><strong>{resetPreview.documents_count}</strong> documents</li>
                      <li><strong>{resetPreview.collections_count}</strong> collections</li>
                      <li><strong>{resetPreview.conversations_count}</strong> conversations</li>
                      <li><strong>{resetPreview.messages_count}</strong> messages</li>
                      <li><strong>{resetPreview.files_count}</strong> uploaded files ({resetPreview.total_size_human})</li>
                    </ul>
                  </div>
                )}

                {/* Confirmation input */}
                <div>
                  <label htmlFor="reset-confirmation" className="block text-xs font-medium text-red-800 dark:text-red-200 mb-1">
                    Type <span className="font-mono font-bold bg-red-100 dark:bg-red-900/30 px-1 rounded">DELETE ALL DATA</span> to confirm:
                  </label>
                  <input
                    id="reset-confirmation"
                    type="text"
                    value={resetConfirmationText}
                    onChange={(e) => handleConfirmationTextChange(e.target.value)}
                    className="w-full px-3 py-2 border border-red-300 dark:border-red-700 rounded-lg bg-white dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-red-500 font-mono"
                    placeholder="DELETE ALL DATA"
                    disabled={isResetting || isLoadingPreview}
                  />
                </div>

                {/* Countdown timer (Feature #223: 10-second countdown) */}
                {resetConfirmationText === 'DELETE ALL DATA' && countdownSeconds > 0 && (
                  <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded-lg p-3">
                    <p className="text-sm text-amber-800 dark:text-amber-200 flex items-center gap-2">
                      <Loader2 size={16} className="animate-spin" />
                      Please wait <strong className="text-lg">{countdownSeconds}</strong> seconds before confirming...
                    </p>
                  </div>
                )}

                {/* Action buttons */}
                <div className="flex gap-2 justify-end">
                  <button
                    type="button"
                    onClick={handleCancelReset}
                    disabled={isResetting}
                    className="px-3 py-1.5 text-sm text-light-text-secondary hover:text-light-text transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirmReset}
                    disabled={isResetting || resetConfirmationText !== 'DELETE ALL DATA' || countdownSeconds > 0 || !resetPreview}
                    className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 flex items-center gap-2"
                  >
                    {isResetting ? (
                      <>
                        <Loader2 size={14} className="animate-spin" />
                        Resetting...
                      </>
                    ) : countdownSeconds > 0 ? (
                      <>
                        <Loader2 size={14} className="animate-spin" />
                        Wait {countdownSeconds}s...
                      </>
                    ) : (
                      <>
                        <Trash2 size={14} />
                        Reset Database
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

            {!showResetConfirm && (
              <button
                type="button"
                onClick={handleResetDatabase}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors font-medium"
              >
                <Trash2 size={18} />
                Reset Database
              </button>
            )}

            {resetSuccess && (
              <div className="space-y-3">
                <div className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-3 py-2 rounded-lg">
                  <div className="flex items-center gap-2">
                    <Check size={14} />
                    <span className="font-medium">Database reset successfully!</span>
                  </div>
                  <p className="pl-5 mt-1 text-green-700 dark:text-green-300">
                    Deleted: {resetSuccess.documents_deleted} documents, {resetSuccess.collections_deleted} collections, {resetSuccess.conversations_deleted} conversations
                  </p>
                </div>

                {/* Feature #222: Undo option */}
                {showUndoOption && lastBackup?.available && (
                  <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded-lg p-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium text-amber-800 dark:text-amber-200 flex items-center gap-2">
                          <RotateCcw size={16} />
                          Undo available ({undoCountdown}s)
                        </p>
                        <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
                          A backup was created before the reset. You can restore your data.
                        </p>
                        {lastBackup?.backup && (
                          <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                            {lastBackup.backup.documents_count} documents, {lastBackup.backup.collections_count} collections
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={handleDismissUndo}
                          className="px-2 py-1 text-xs text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-800/30 rounded transition-colors"
                          disabled={isUndoing}
                        >
                          Dismiss
                        </button>
                        <button
                          type="button"
                          onClick={handleUndoReset}
                          disabled={isUndoing}
                          className="px-3 py-1.5 text-sm bg-amber-600 text-white rounded-lg hover:bg-amber-700 transition-colors disabled:opacity-50 flex items-center gap-2"
                        >
                          {isUndoing ? (
                            <>
                              <Loader2 size={14} className="animate-spin" />
                              Restoring...
                            </>
                          ) : (
                            <>
                              <RotateCcw size={14} />
                              Undo Reset
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Undo result */}
                {undoResult?.success && (
                  <div className="text-xs text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 px-3 py-2 rounded-lg">
                    <div className="flex items-center gap-2">
                      <Check size={14} />
                      <span className="font-medium">Data restored successfully!</span>
                    </div>
                    <p className="pl-5 mt-1">
                      Restored: {undoResult.documents_restored} documents, {undoResult.collections_restored} collections, {undoResult.files_restored} files
                    </p>
                    <p className="pl-5 mt-1 text-blue-500 dark:text-blue-400">Reloading app...</p>
                    {undoResult.note && (
                      <p className="pl-5 mt-1 text-blue-500 dark:text-blue-400 italic text-[10px]">{undoResult.note}</p>
                    )}
                  </div>
                )}

                {!showUndoOption && !undoResult && (
                  <p className="text-xs text-green-600 dark:text-green-400">Reloading app...</p>
                )}
              </div>
            )}

            {resetError && (
              <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
                {resetError}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

export default SettingsPage
