/**
 * SettingsModal - Modal for configuring API keys, models, and theme
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { X, Save, Loader2, Eye, EyeOff, Sun, Moon, Monitor, RefreshCw, Check, Download, HardDrive, FileText, FolderOpen, MessageSquare, Upload, AlertTriangle, CheckCircle2, XCircle, Trash2, Phone, Bot, RotateCcw, Play, ChevronDown } from 'lucide-react';
import { fetchOllamaModels, OllamaModel, fetchOpenRouterModels, OpenRouterModel, fetchSettings, updateSettings, fetchBackupStatus, createBackup, restoreBackup, BackupStatusResponse, RestoreResponse, testConnection, resetDatabase, ResetDatabaseResponse, checkEmbeddingHealth, EmbeddingHealthCheckResponse, getSystemPrompt, updateSystemPrompt, getSystemPromptPresets, testSystemPrompt, SystemPromptResponse, SystemPromptPreset, SystemPromptTestResponse } from '../api/settings';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { FeedbackAnalytics } from './FeedbackAnalytics';
import { NgrokStatus } from './NgrokStatus';

interface Settings {
  openai_api_key: string;
  cohere_api_key: string;
  openrouter_api_key: string;
  llm_model: string;
  embedding_model: string;
  chunking_llm_model: string;
  theme: 'light' | 'dark' | 'system';
  enable_reranking: boolean;
  openai_api_key_set?: boolean;
  cohere_api_key_set?: boolean;
  openrouter_api_key_set?: boolean;
  // Twilio/WhatsApp configuration
  twilio_account_sid: string;
  twilio_auth_token: string;
  twilio_whatsapp_number: string;
  twilio_configured?: boolean;
  chunk_strategy: 'agentic' | 'semantic' | 'paragraph' | 'fixed';
  max_chunk_size: number;
  chunk_overlap: number;
  // Conversation context configuration
  context_window_size: number;
  // Chat history search (Feature #161)
  include_chat_history_in_search: boolean;
  // Custom system prompt (Feature #179)
  custom_system_prompt: string;
}

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave?: (settings: Settings) => void;
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
  chunk_strategy: 'semantic',
  max_chunk_size: 2000,
  chunk_overlap: 200,
  context_window_size: 20,
  include_chat_history_in_search: false,
  custom_system_prompt: ''
};

// Recommended chunking LLM models
const CHUNKING_LLM_OPTIONS = [
  { value: '', label: 'Same as Chat LLM (default)' },
  { value: 'openrouter:google/gemini-2.0-flash-001', label: 'Gemini 2.0 Flash (Recommended - fast & cheap)' },
  { value: 'openrouter:openai/gpt-4o-mini', label: 'GPT-4o Mini via OpenRouter' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini (OpenAI direct)' },
];

// API key validation
interface ApiKeyValidation {
  isValid: boolean;
  error: string | null;
}

/**
 * Validates OpenAI API key format
 * OpenAI keys typically start with "sk-" and are 40+ characters
 */
const validateOpenAIKey = (key: string): ApiKeyValidation => {
  if (!key || key.trim() === '') {
    return { isValid: true, error: null }; // Empty is valid (optional field)
  }

  const trimmedKey = key.trim();

  // OpenAI keys must start with "sk-"
  if (!trimmedKey.startsWith('sk-')) {
    return {
      isValid: false,
      error: 'OpenAI API keys must start with "sk-" (e.g., sk-...)'
    };
  }

  // OpenAI keys are typically 40+ characters
  if (trimmedKey.length < 40) {
    return {
      isValid: false,
      error: 'OpenAI API key is too short. Valid keys are at least 40 characters.'
    };
  }

  // Check for obviously invalid characters (should be alphanumeric, hyphens, underscores)
  if (!/^sk-[a-zA-Z0-9_-]+$/.test(trimmedKey)) {
    return {
      isValid: false,
      error: 'OpenAI API key contains invalid characters. Keys should only contain letters, numbers, hyphens, and underscores.'
    };
  }

  return { isValid: true, error: null };
};

/**
 * Validates Cohere API key format
 * Cohere keys are typically 40+ character alphanumeric strings
 */
const validateCohereKey = (key: string): ApiKeyValidation => {
  if (!key || key.trim() === '') {
    return { isValid: true, error: null }; // Empty is valid (optional field)
  }

  const trimmedKey = key.trim();

  // Cohere keys are typically 40+ characters
  if (trimmedKey.length < 20) {
    return {
      isValid: false,
      error: 'Cohere API key is too short. Valid keys are at least 20 characters.'
    };
  }

  // Check for obviously invalid characters (should be alphanumeric)
  if (!/^[a-zA-Z0-9_-]+$/.test(trimmedKey)) {
    return {
      isValid: false,
      error: 'Cohere API key contains invalid characters. Keys should only contain letters, numbers, hyphens, and underscores.'
    };
  }

  return { isValid: true, error: null };
};

/**
 * Validates OpenRouter API key format
 * OpenRouter keys typically start with "sk-or-" and are 40+ characters
 */
const validateOpenRouterKey = (key: string): ApiKeyValidation => {
  if (!key || key.trim() === '') {
    return { isValid: true, error: null }; // Empty is valid (optional field)
  }

  const trimmedKey = key.trim();

  // OpenRouter keys must start with "sk-or-"
  if (!trimmedKey.startsWith('sk-or-')) {
    return {
      isValid: false,
      error: 'OpenRouter API keys must start with "sk-or-" (e.g., sk-or-...)'
    };
  }

  // OpenRouter keys are typically 40+ characters
  if (trimmedKey.length < 40) {
    return {
      isValid: false,
      error: 'OpenRouter API key is too short. Valid keys are at least 40 characters.'
    };
  }

  // Check for obviously invalid characters (should be alphanumeric, hyphens, underscores)
  if (!/^sk-or-[a-zA-Z0-9_-]+$/.test(trimmedKey)) {
    return {
      isValid: false,
      error: 'OpenRouter API key contains invalid characters. Keys should only contain letters, numbers, hyphens, and underscores.'
    };
  }

  return { isValid: true, error: null };
};

// Static OpenAI LLM models
const OPENAI_LLM_MODELS = [
  { value: 'gpt-4o', label: 'GPT-4o (Recommended)', provider: 'openai' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini (Faster, cheaper)', provider: 'openai' },
  { value: 'gpt-4-turbo', label: 'GPT-4 Turbo', provider: 'openai' },
  { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo (Budget)', provider: 'openai' },
];

// Static OpenAI embedding models
const OPENAI_EMBEDDING_MODELS = [
  { value: 'text-embedding-3-small', label: 'text-embedding-3-small (Recommended)', provider: 'openai' },
  { value: 'text-embedding-3-large', label: 'text-embedding-3-large (Higher quality)', provider: 'openai' },
  { value: 'text-embedding-ada-002', label: 'text-embedding-ada-002 (Legacy)', provider: 'openai' },
];

// Theme options
const THEME_OPTIONS = [
  { value: 'light' as const, label: 'Light', icon: Sun },
  { value: 'dark' as const, label: 'Dark', icon: Moon },
  { value: 'system' as const, label: 'System', icon: Monitor },
];

/**
 * Extract provider name from OpenRouter model ID
 * e.g., "openai/gpt-4o" -> "OpenAI"
 */
const extractProvider = (modelId: string): string => {
  const parts = modelId.split('/');
  if (parts.length > 1) {
    const provider = parts[0];
    // Capitalize provider name
    return provider.charAt(0).toUpperCase() + provider.slice(1);
  }
  return 'Other';
};

/**
 * Group models by provider and filter by search term
 */
interface GroupedModels {
  provider: string;
  models: OpenRouterModel[];
}

const filterAndGroupModels = (
  models: OpenRouterModel[],
  searchTerm: string
): { groups: GroupedModels[]; totalMatches: number; truncated: boolean } => {
  // Filter by search term
  const filtered = searchTerm.trim() === ''
    ? models
    : models.filter(m =>
        m.label.toLowerCase().includes(searchTerm.toLowerCase()) ||
        m.value.toLowerCase().includes(searchTerm.toLowerCase())
      );

  const totalMatches = filtered.length;
  const maxResults = 50;
  const truncated = totalMatches > maxResults;
  const limited = truncated ? filtered.slice(0, maxResults) : filtered;

  // Group by provider
  const groupedMap = limited.reduce((acc, model) => {
    const provider = extractProvider(model.value);
    if (!acc[provider]) {
      acc[provider] = [];
    }
    acc[provider].push(model);
    return acc;
  }, {} as Record<string, OpenRouterModel[]>);

  // Convert to array and sort providers alphabetically
  const groups = Object.keys(groupedMap)
    .sort()
    .map(provider => ({
      provider,
      models: groupedMap[provider]
    }));

  return { groups, totalMatches, truncated };
};

export function SettingsModal({
  isOpen,
  onClose,
  onSave,
}: SettingsModalProps) {
  // Focus trap for accessibility - keeps focus within modal
  const focusTrapRef = useFocusTrap(isOpen);

  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showOpenAIKey, setShowOpenAIKey] = useState(false);
  const [showCohereKey, setShowCohereKey] = useState(false);
  const [showOpenRouterKey, setShowOpenRouterKey] = useState(false);
  const [showTwilioSid, setShowTwilioSid] = useState(false);
  const [showTwilioToken, setShowTwilioToken] = useState(false);

  // API key validation states
  const [openAIKeyError, setOpenAIKeyError] = useState<string | null>(null);
  const [cohereKeyError, setCohereKeyError] = useState<string | null>(null);
  const [openRouterKeyError, setOpenRouterKeyError] = useState<string | null>(null);

  // Ollama models state
  const [ollamaLLMModels, setOllamaLLMModels] = useState<OllamaModel[]>([]);
  const [ollamaEmbeddingModels, setOllamaEmbeddingModels] = useState<OllamaModel[]>([]);
  const [ollamaAvailable, setOllamaAvailable] = useState(false);
  const [ollamaError, setOllamaError] = useState<string | null>(null);
  const [isLoadingOllama, setIsLoadingOllama] = useState(false);

  // OpenRouter models state
  const [openRouterModels, setOpenRouterModels] = useState<OpenRouterModel[]>([]);
  const [openRouterAvailable, setOpenRouterAvailable] = useState(false);
  const [openRouterError, setOpenRouterError] = useState<string | null>(null);
  const [isLoadingOpenRouter, setIsLoadingOpenRouter] = useState(false);
  const [modelSearch, setModelSearch] = useState('');

  // Backup state
  const [backupStatus, setBackupStatus] = useState<BackupStatusResponse | null>(null);
  const [isLoadingBackup, setIsLoadingBackup] = useState(false);
  const [isCreatingBackup, setIsCreatingBackup] = useState(false);
  const [backupError, setBackupError] = useState<string | null>(null);
  const [backupSuccess, setBackupSuccess] = useState(false);

  // Restore state
  const [isRestoring, setIsRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreSuccess, setRestoreSuccess] = useState<RestoreResponse | null>(null);
  const [showRestoreConfirm, setShowRestoreConfirm] = useState(false);
  const [selectedRestoreFile, setSelectedRestoreFile] = useState<File | null>(null);
  const restoreFileInputRef = useRef<HTMLInputElement>(null);

  // Test connection state
  const [testingConnection, setTestingConnection] = useState<{
    openai: boolean;
    cohere: boolean;
    openrouter: boolean;
    ollama: boolean;
    twilio: boolean;
  }>({
    openai: false,
    cohere: false,
    openrouter: false,
    ollama: false,
    twilio: false,
  });
  const [connectionStatus, setConnectionStatus] = useState<{
    openai: { success: boolean; message: string } | null;
    cohere: { success: boolean; message: string } | null;
    openrouter: { success: boolean; message: string } | null;
    ollama: { success: boolean; message: string } | null;
    twilio: { success: boolean; message: string } | null;
  }>({
    openai: null,
    cohere: null,
    openrouter: null,
    ollama: null,
    twilio: null,
  });

  // Embedding health state
  const [embeddingHealth, setEmbeddingHealth] = useState<EmbeddingHealthCheckResponse | null>(null);
  const [isCheckingEmbedding, setIsCheckingEmbedding] = useState(false);

  // Reset database state
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [resetConfirmationText, setResetConfirmationText] = useState('');
  const [isResetting, setIsResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetSuccess, setResetSuccess] = useState<ResetDatabaseResponse | null>(null);

  // System prompt state (Feature #179)
  const [_systemPromptData, setSystemPromptData] = useState<SystemPromptResponse | null>(null);
  const [systemPromptPresets, setSystemPromptPresets] = useState<SystemPromptPreset[]>([]);
  const [isLoadingSystemPrompt, setIsLoadingSystemPrompt] = useState(false);
  const [systemPromptError, setSystemPromptError] = useState<string | null>(null);
  const [isSavingSystemPrompt, setIsSavingSystemPrompt] = useState(false);
  const [systemPromptSaveSuccess, setSystemPromptSaveSuccess] = useState(false);
  const [isTestingPrompt, setIsTestingPrompt] = useState(false);
  const [testPromptMessage, setTestPromptMessage] = useState('Hello! Can you tell me about yourself?');
  const [testPromptResult, setTestPromptResult] = useState<SystemPromptTestResponse | null>(null);
  const [showPresetDropdown, setShowPresetDropdown] = useState(false);

  // Fetch Ollama models from backend
  const loadOllamaModels = useCallback(async () => {
    setIsLoadingOllama(true);
    setOllamaError(null);
    try {
      const response = await fetchOllamaModels();
      setOllamaAvailable(response.available);
      setOllamaLLMModels(response.models);
      setOllamaEmbeddingModels(response.embedding_models);
      if (response.error) {
        setOllamaError(response.error);
      }
    } catch (err) {
      setOllamaError(err instanceof Error ? err.message : 'Failed to fetch Ollama models');
      setOllamaAvailable(false);
    } finally {
      setIsLoadingOllama(false);
    }
  }, []);

  // Fetch OpenRouter models from backend
  const loadOpenRouterModels = useCallback(async () => {
    setIsLoadingOpenRouter(true);
    setOpenRouterError(null);
    try {
      const response = await fetchOpenRouterModels();
      setOpenRouterAvailable(response.available);
      setOpenRouterModels(response.models);
      if (response.error) {
        setOpenRouterError(response.error);
      }
    } catch (err) {
      setOpenRouterError(err instanceof Error ? err.message : 'Failed to fetch OpenRouter models');
      setOpenRouterAvailable(false);
    } finally {
      setIsLoadingOpenRouter(false);
    }
  }, []);

  // Fetch backup status from backend
  const loadBackupStatus = useCallback(async () => {
    setIsLoadingBackup(true);
    setBackupError(null);
    try {
      const status = await fetchBackupStatus();
      setBackupStatus(status);
    } catch (err) {
      setBackupError(err instanceof Error ? err.message : 'Failed to fetch backup status');
    } finally {
      setIsLoadingBackup(false);
    }
  }, []);

  // Load settings from backend
  const loadSettings = useCallback(async () => {
    try {
      const backendSettings = await fetchSettings();
      setSettings({
        // For API keys, if they're masked (contain ****), we show a placeholder
        // Otherwise use the value from backend
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
        chunk_strategy: (backendSettings.chunk_strategy as Settings['chunk_strategy']) || DEFAULT_SETTINGS.chunk_strategy,
        max_chunk_size: backendSettings.max_chunk_size || DEFAULT_SETTINGS.max_chunk_size,
        chunk_overlap: backendSettings.chunk_overlap !== undefined ? backendSettings.chunk_overlap : DEFAULT_SETTINGS.chunk_overlap,
        context_window_size: backendSettings.context_window_size !== undefined ? backendSettings.context_window_size : DEFAULT_SETTINGS.context_window_size,
        include_chat_history_in_search: backendSettings.include_chat_history_in_search !== undefined ? backendSettings.include_chat_history_in_search : DEFAULT_SETTINGS.include_chat_history_in_search,
        custom_system_prompt: backendSettings.custom_system_prompt !== undefined ? backendSettings.custom_system_prompt : DEFAULT_SETTINGS.custom_system_prompt
      });
    } catch (e) {
      console.error('Failed to load settings from backend:', e);
      // Fall back to localStorage if backend fails
      const savedSettings = localStorage.getItem('rag-settings');
      if (savedSettings) {
        try {
          const parsed = JSON.parse(savedSettings);
          setSettings({ ...DEFAULT_SETTINGS, ...parsed });
        } catch (parseErr) {
          console.error('Failed to parse saved settings:', parseErr);
        }
      }
    }
  }, []);

  // Load system prompt data (Feature #179)
  const loadSystemPrompt = useCallback(async () => {
    setIsLoadingSystemPrompt(true);
    setSystemPromptError(null);
    try {
      const [promptData, presetsData] = await Promise.all([
        getSystemPrompt(),
        getSystemPromptPresets()
      ]);
      setSystemPromptData(promptData);
      setSystemPromptPresets(presetsData.presets);
      // Update settings with the custom prompt
      setSettings(prev => ({
        ...prev,
        custom_system_prompt: promptData.custom_prompt
      }));
    } catch (err) {
      setSystemPromptError(err instanceof Error ? err.message : 'Failed to load system prompt');
    } finally {
      setIsLoadingSystemPrompt(false);
    }
  }, []);

  // Save custom system prompt (Feature #179)
  const handleSaveSystemPrompt = async (promptText: string) => {
    setIsSavingSystemPrompt(true);
    setSystemPromptError(null);
    setSystemPromptSaveSuccess(false);
    try {
      const result = await updateSystemPrompt(promptText);
      setSystemPromptData(result);
      setSettings(prev => ({ ...prev, custom_system_prompt: promptText }));
      setSystemPromptSaveSuccess(true);
      setTimeout(() => setSystemPromptSaveSuccess(false), 3000);
    } catch (err) {
      setSystemPromptError(err instanceof Error ? err.message : 'Failed to save system prompt');
    } finally {
      setIsSavingSystemPrompt(false);
    }
  };

  // Test system prompt (Feature #179)
  const handleTestPrompt = async () => {
    setIsTestingPrompt(true);
    setTestPromptResult(null);
    try {
      const result = await testSystemPrompt(testPromptMessage, settings.custom_system_prompt || undefined);
      setTestPromptResult(result);
    } catch (err) {
      setTestPromptResult({
        success: false,
        response: '',
        prompt_used: '',
        error: err instanceof Error ? err.message : 'Failed to test prompt'
      });
    } finally {
      setIsTestingPrompt(false);
    }
  };

  // Apply preset (Feature #179)
  const handleApplyPreset = (preset: SystemPromptPreset) => {
    setSettings(prev => ({
      ...prev,
      custom_system_prompt: preset.text
    }));
    setShowPresetDropdown(false);
  };

  // Reset to default prompt (Feature #179)
  const handleResetToDefault = () => {
    setSettings(prev => ({
      ...prev,
      custom_system_prompt: ''
    }));
  };

  // Handle backup creation
  const handleCreateBackup = async () => {
    setIsCreatingBackup(true);
    setBackupError(null);
    setBackupSuccess(false);
    try {
      await createBackup();
      setBackupSuccess(true);
      // Clear success message after 3 seconds
      setTimeout(() => setBackupSuccess(false), 3000);
    } catch (err) {
      setBackupError(err instanceof Error ? err.message : 'Failed to create backup');
    } finally {
      setIsCreatingBackup(false);
    }
  };

  // Handle restore file selection
  const handleRestoreFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      if (!file.name.endsWith('.zip')) {
        setRestoreError('Please select a valid .zip backup file');
        return;
      }
      setSelectedRestoreFile(file);
      setShowRestoreConfirm(true);
      setRestoreError(null);
      setRestoreSuccess(null);
    }
  };

  // Handle restore confirmation
  const handleConfirmRestore = async () => {
    if (!selectedRestoreFile) return;

    setIsRestoring(true);
    setRestoreError(null);
    setRestoreSuccess(null);
    setShowRestoreConfirm(false);

    try {
      const result = await restoreBackup(selectedRestoreFile);
      setRestoreSuccess(result);
      // Refresh backup status to show new counts
      loadBackupStatus();
      // Clear the file input
      if (restoreFileInputRef.current) {
        restoreFileInputRef.current.value = '';
      }
      setSelectedRestoreFile(null);
    } catch (err) {
      setRestoreError(err instanceof Error ? err.message : 'Failed to restore backup');
    } finally {
      setIsRestoring(false);
    }
  };

  // Cancel restore
  const handleCancelRestore = () => {
    setShowRestoreConfirm(false);
    setSelectedRestoreFile(null);
    if (restoreFileInputRef.current) {
      restoreFileInputRef.current.value = '';
    }
  };

  // Check embedding model health
  const checkEmbeddingModelHealth = useCallback(async () => {
    setIsCheckingEmbedding(true);
    try {
      const result = await checkEmbeddingHealth();
      setEmbeddingHealth(result);
    } catch (err) {
      setEmbeddingHealth({
        available: false,
        model: 'unknown',
        provider: 'unknown',
        message: err instanceof Error ? err.message : 'Failed to check embedding model',
      });
    } finally {
      setIsCheckingEmbedding(false);
    }
  }, []);

  // Load settings from backend and fetch Ollama models on mount
  useEffect(() => {
    if (isOpen) {
      loadSettings();
      setError(null);
      setBackupSuccess(false);
      setBackupError(null);
      // Clear API key validation errors when modal opens
      setOpenAIKeyError(null);
      setCohereKeyError(null);
      setOpenRouterKeyError(null);
      // Reset password visibility to hidden when modal opens (security)
      setShowOpenAIKey(false);
      setShowCohereKey(false);
      setShowOpenRouterKey(false);
      setShowTwilioSid(false);
      setShowTwilioToken(false);
      // Fetch Ollama models when modal opens
      loadOllamaModels();
      // Check embedding model health
      checkEmbeddingModelHealth();
      // Fetch backup status when modal opens
      loadBackupStatus();
      // Load system prompt data (Feature #179)
      loadSystemPrompt();
      // Reset system prompt UI state
      setSystemPromptError(null);
      setSystemPromptSaveSuccess(false);
      setTestPromptResult(null);
    }
  }, [isOpen, loadSettings, loadOllamaModels, loadOpenRouterModels, loadBackupStatus, checkEmbeddingModelHealth, loadSystemPrompt]);

  // Apply theme when it changes
  useEffect(() => {
    const applyTheme = (theme: 'light' | 'dark' | 'system') => {
      const root = document.documentElement;
      if (theme === 'system') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        root.classList.toggle('dark', prefersDark);
      } else {
        root.classList.toggle('dark', theme === 'dark');
      }
    };
    applyTheme(settings.theme);
  }, [settings.theme]);

  if (!isOpen) {
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSaving(true);

    // Validate API keys before saving
    const openAIValidation = validateOpenAIKey(settings.openai_api_key);
    const cohereValidation = validateCohereKey(settings.cohere_api_key);
    const openRouterValidation = validateOpenRouterKey(settings.openrouter_api_key);

    if (!openAIValidation.isValid || !cohereValidation.isValid || !openRouterValidation.isValid) {
      setOpenAIKeyError(openAIValidation.error);
      setCohereKeyError(cohereValidation.error);
      setOpenRouterKeyError(openRouterValidation.error);
      setIsSaving(false);
      // Set general error message
      setError('Please fix the API key format errors before saving.');
      return;
    }

    // Clear any previous validation errors
    setOpenAIKeyError(null);
    setCohereKeyError(null);
    setOpenRouterKeyError(null);

    try {
      // Build update payload - only include fields that should be updated
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
        custom_system_prompt: settings.custom_system_prompt
      };

      // Only update API keys if they were actually entered (not empty)
      // This prevents overwriting existing keys with empty values
      if (settings.openai_api_key && settings.openai_api_key.trim()) {
        updatePayload.openai_api_key = settings.openai_api_key;
      }
      if (settings.cohere_api_key && settings.cohere_api_key.trim()) {
        updatePayload.cohere_api_key = settings.cohere_api_key;
      }
      if (settings.openrouter_api_key && settings.openrouter_api_key.trim()) {
        updatePayload.openrouter_api_key = settings.openrouter_api_key;
      }
      // Twilio credentials
      if (settings.twilio_account_sid && settings.twilio_account_sid.trim()) {
        updatePayload.twilio_account_sid = settings.twilio_account_sid;
      }
      if (settings.twilio_auth_token && settings.twilio_auth_token.trim()) {
        updatePayload.twilio_auth_token = settings.twilio_auth_token;
      }
      if (settings.twilio_whatsapp_number && settings.twilio_whatsapp_number.trim()) {
        updatePayload.twilio_whatsapp_number = settings.twilio_whatsapp_number;
      }

      // Save to backend
      const response = await updateSettings(updatePayload);

      // Feature #305: Show embedding model warning if returned
      if (response.embedding_model_warning) {
        // Set the error state to show the warning (it's not a fatal error, just a warning)
        setError(`⚠️ ${response.embedding_model_warning}`);
        // Don't close the modal so user can see the warning
        setIsSaving(false);
        return;
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
        include_chat_history_in_search: settings.include_chat_history_in_search
      };
      localStorage.setItem('rag-settings', JSON.stringify(localSettings));

      // Call onSave callback if provided
      onSave?.(settings);

      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings');
    } finally {
      setIsSaving(false);
    }
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const updateSetting = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettings(prev => ({ ...prev, [key]: value }));

    // Real-time validation for API keys
    if (key === 'openai_api_key') {
      const validation = validateOpenAIKey(value as string);
      setOpenAIKeyError(validation.error);
    }
    if (key === 'cohere_api_key') {
      const validation = validateCohereKey(value as string);
      setCohereKeyError(validation.error);
    }
    if (key === 'openrouter_api_key') {
      const validation = validateOpenRouterKey(value as string);
      setOpenRouterKeyError(validation.error);
      // If a valid key is entered, fetch OpenRouter models
      if (validation.isValid && value && (value as string).length > 40) {
        loadOpenRouterModels();
      }
    }
  };

  // Test connection handler
  const handleTestConnection = async (provider: 'openai' | 'cohere' | 'openrouter' | 'ollama' | 'twilio') => {
    setTestingConnection(prev => ({ ...prev, [provider]: true }));
    setConnectionStatus(prev => ({ ...prev, [provider]: null }));

    try {
      const result = await testConnection(provider);
      setConnectionStatus(prev => ({
        ...prev,
        [provider]: { success: result.success, message: result.message }
      }));
      // Clear status after 5 seconds
      setTimeout(() => {
        setConnectionStatus(prev => ({ ...prev, [provider]: null }));
      }, 5000);
    } catch (error) {
      setConnectionStatus(prev => ({
        ...prev,
        [provider]: {
          success: false,
          message: error instanceof Error ? error.message : 'Failed to test connection'
        }
      }));
      // Clear status after 5 seconds
      setTimeout(() => {
        setConnectionStatus(prev => ({ ...prev, [provider]: null }));
      }, 5000);
    } finally {
      setTestingConnection(prev => ({ ...prev, [provider]: false }));
    }
  };

  // Reset database handlers
  const handleResetDatabase = () => {
    setShowResetConfirm(true);
    setResetConfirmationText('');
    setResetError(null);
    setResetSuccess(null);
  };

  const handleCancelReset = () => {
    setShowResetConfirm(false);
    setResetConfirmationText('');
    setResetError(null);
  };

  const handleConfirmReset = async () => {
    if (resetConfirmationText !== 'RESET') {
      setResetError('Please type "RESET" to confirm');
      return;
    }

    setIsResetting(true);
    setResetError(null);
    setResetSuccess(null);

    try {
      const result = await resetDatabase(resetConfirmationText, '');
      setResetSuccess(result);
      setShowResetConfirm(false);
      setResetConfirmationText('');

      // Reload backup status to reflect cleared data
      loadBackupStatus();

      // Re-fetch settings from backend to restore API key indicators
      // This ensures the settings modal shows correct API key status after reset
      await loadSettings();

      // Show success message for 3 seconds then close modal and refresh page
      setTimeout(() => {
        onClose();
        // Reload the entire app to refresh all state
        window.location.reload();
      }, 3000);
    } catch (error) {
      setResetError(error instanceof Error ? error.message : 'Failed to reset database');
    } finally {
      setIsResetting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
      onClick={handleBackdropClick}
    >
      <div
        ref={focusTrapRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-modal-title"
        className="bg-light-bg dark:bg-dark-bg rounded-lg shadow-xl w-full max-w-lg mx-4 overflow-hidden max-h-[90vh] flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-light-border dark:border-dark-border">
          <h2 id="settings-modal-title" className="text-lg font-semibold text-light-text dark:text-dark-text">
            Settings
          </h2>
          <button
            onClick={onClose}
            className="text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Form - Scrollable */}
        <form onSubmit={handleSubmit} className="p-6 space-y-6 overflow-y-auto flex-1">
          {/* API Keys Section */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
              API Keys
            </h3>

            {/* OpenAI API Key */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label
                  htmlFor="openai-key"
                  className="block text-sm font-medium text-light-text dark:text-dark-text"
                >
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
                    openAIKeyError
                      ? 'border-red-500 focus:ring-red-500'
                      : 'border-light-border dark:border-dark-border focus:ring-primary'
                  }`}
                  placeholder={settings.openai_api_key_set ? "Enter new key to update..." : "sk-..."}
                  aria-invalid={!!openAIKeyError}
                  aria-describedby={openAIKeyError ? "openai-key-error" : undefined}
                />
                <button
                  type="button"
                  onClick={() => setShowOpenAIKey(!showOpenAIKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text"
                >
                  {showOpenAIKey ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {openAIKeyError ? (
                <p id="openai-key-error" className="text-xs text-red-500 dark:text-red-400 mt-1" role="alert">
                  {openAIKeyError}
                </p>
              ) : (
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  {settings.openai_api_key_set
                    ? "Key is saved. Enter a new key to replace it."
                    : "Required for LLM and embedding functionality. Keys start with 'sk-'"}
                </p>
              )}
              {/* Test Connection Button */}
              <div className="mt-2">
                <button
                  type="button"
                  onClick={() => handleTestConnection('openai')}
                  disabled={testingConnection.openai || (!settings.openai_api_key && !settings.openai_api_key_set)}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {testingConnection.openai ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      Testing Connection...
                    </>
                  ) : (
                    <>
                      <RefreshCw size={14} />
                      Test Connection
                    </>
                  )}
                </button>
                {connectionStatus.openai && (
                  <div className={`flex items-center gap-2 mt-2 text-xs px-3 py-2 rounded-lg ${
                    connectionStatus.openai.success
                      ? 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20'
                      : 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
                  }`}>
                    {connectionStatus.openai.success ? (
                      <CheckCircle2 size={14} />
                    ) : (
                      <XCircle size={14} />
                    )}
                    {connectionStatus.openai.message}
                  </div>
                )}
              </div>
            </div>

            {/* Cohere API Key */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label
                  htmlFor="cohere-key"
                  className="block text-sm font-medium text-light-text dark:text-dark-text"
                >
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
                    cohereKeyError
                      ? 'border-red-500 focus:ring-red-500'
                      : 'border-light-border dark:border-dark-border focus:ring-primary'
                  }`}
                  placeholder={settings.cohere_api_key_set ? "Enter new key to update..." : "..."}
                  aria-invalid={!!cohereKeyError}
                  aria-describedby={cohereKeyError ? "cohere-key-error" : undefined}
                />
                <button
                  type="button"
                  onClick={() => setShowCohereKey(!showCohereKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text"
                >
                  {showCohereKey ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {cohereKeyError ? (
                <p id="cohere-key-error" className="text-xs text-red-500 dark:text-red-400 mt-1" role="alert">
                  {cohereKeyError}
                </p>
              ) : (
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  {settings.cohere_api_key_set
                    ? "Key is saved. Enter a new key to replace it."
                    : "Optional - used for re-ranking search results. Keys are 40+ characters."}
                </p>
              )}
              {/* Test Connection Button */}
              <div className="mt-2">
                <button
                  type="button"
                  onClick={() => handleTestConnection('cohere')}
                  disabled={testingConnection.cohere || (!settings.cohere_api_key && !settings.cohere_api_key_set)}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {testingConnection.cohere ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      Testing Connection...
                    </>
                  ) : (
                    <>
                      <RefreshCw size={14} />
                      Test Connection
                    </>
                  )}
                </button>
                {connectionStatus.cohere && (
                  <div className={`flex items-center gap-2 mt-2 text-xs px-3 py-2 rounded-lg ${
                    connectionStatus.cohere.success
                      ? 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20'
                      : 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
                  }`}>
                    {connectionStatus.cohere.success ? (
                      <CheckCircle2 size={14} />
                    ) : (
                      <XCircle size={14} />
                    )}
                    {connectionStatus.cohere.message}
                  </div>
                )}
              </div>
            </div>

            {/* OpenRouter API Key */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label
                  htmlFor="openrouter-key"
                  className="block text-sm font-medium text-light-text dark:text-dark-text"
                >
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
                    openRouterKeyError
                      ? 'border-red-500 focus:ring-red-500'
                      : 'border-light-border dark:border-dark-border focus:ring-primary'
                  }`}
                  placeholder={settings.openrouter_api_key_set ? "Enter new key to update..." : "sk-or-..."}
                  aria-invalid={!!openRouterKeyError}
                  aria-describedby={openRouterKeyError ? "openrouter-key-error" : undefined}
                />
                <button
                  type="button"
                  onClick={() => setShowOpenRouterKey(!showOpenRouterKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text"
                >
                  {showOpenRouterKey ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {openRouterKeyError ? (
                <p id="openrouter-key-error" className="text-xs text-red-500 dark:text-red-400 mt-1" role="alert">
                  {openRouterKeyError}
                </p>
              ) : (
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  {settings.openrouter_api_key_set
                    ? "Key is saved. Enter a new key to replace it."
                    : "Optional - access multiple AI models (Claude, GPT-4, Llama, etc.) through one API. Keys start with 'sk-or-'"}
                </p>
              )}
              {/* Test Connection Button */}
              <div className="mt-2">
                <button
                  type="button"
                  onClick={() => handleTestConnection('openrouter')}
                  disabled={testingConnection.openrouter || (!settings.openrouter_api_key && !settings.openrouter_api_key_set)}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {testingConnection.openrouter ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      Testing Connection...
                    </>
                  ) : (
                    <>
                      <RefreshCw size={14} />
                      Test Connection
                    </>
                  )}
                </button>
                {connectionStatus.openrouter && (
                  <div className={`flex items-center gap-2 mt-2 text-xs px-3 py-2 rounded-lg ${
                    connectionStatus.openrouter.success
                      ? 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20'
                      : 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
                  }`}>
                    {connectionStatus.openrouter.success ? (
                      <CheckCircle2 size={14} />
                    ) : (
                      <XCircle size={14} />
                    )}
                    {connectionStatus.openrouter.message}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* WhatsApp/Twilio Integration Section */}
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Phone size={18} className="text-green-500" />
              <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
                WhatsApp Integration (Twilio)
              </h3>
              {settings.twilio_configured && (
                <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                  <Check size={14} />
                  Configured
                </span>
              )}
            </div>

            <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
              Connect your RAG system to WhatsApp via Twilio. Get credentials from{' '}
              <a href="https://console.twilio.com" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                console.twilio.com
              </a>
            </p>

            {/* Twilio Account SID */}
            <div>
              <label
                htmlFor="twilio-sid"
                className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
              >
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
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text"
                >
                  {showTwilioSid ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                Found in Twilio Console dashboard. Starts with "AC"
              </p>
            </div>

            {/* Twilio Auth Token */}
            <div>
              <label
                htmlFor="twilio-token"
                className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
              >
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
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text"
                >
                  {showTwilioToken ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                Found in Twilio Console. Keep this secret!
              </p>
            </div>

            {/* Twilio WhatsApp Number */}
            <div>
              <label
                htmlFor="twilio-whatsapp"
                className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
              >
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
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                Your Twilio WhatsApp Sandbox or Business number (e.g., +14155238886)
              </p>
            </div>

            {/* Test Twilio Connection Button */}
            <div>
              <button
                type="button"
                onClick={() => handleTestConnection('twilio')}
                disabled={testingConnection.twilio || (!settings.twilio_account_sid && !settings.twilio_configured)}
                className="flex items-center gap-2 px-3 py-1.5 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {testingConnection.twilio ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Testing Connection...
                  </>
                ) : (
                  <>
                    <RefreshCw size={14} />
                    Test Twilio Connection
                  </>
                )}
              </button>
              {connectionStatus.twilio && (
                <div className={`flex items-center gap-2 mt-2 text-xs px-3 py-2 rounded-lg ${
                  connectionStatus.twilio.success
                    ? 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20'
                    : 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
                }`}>
                  {connectionStatus.twilio.success ? (
                    <CheckCircle2 size={14} />
                  ) : (
                    <XCircle size={14} />
                  )}
                  {connectionStatus.twilio.message}
                </div>
              )}
            </div>

            {/* Ngrok Webhook URL */}
            <div className="mt-4 pt-4 border-t border-light-border dark:border-dark-border">
              <NgrokStatus autoRefreshInterval={30000} />
            </div>
          </div>

          {/* Model Selection Section */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
                Model Selection
              </h3>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={loadOpenRouterModels}
                  disabled={isLoadingOpenRouter}
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors disabled:opacity-50"
                  title="Fetch OpenRouter models"
                >
                  <RefreshCw size={14} className={isLoadingOpenRouter ? 'animate-spin' : ''} />
                  {isLoadingOpenRouter ? 'Loading...' : 'Load OpenRouter'}
                </button>
                <button
                  type="button"
                  onClick={loadOllamaModels}
                  disabled={isLoadingOllama}
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors disabled:opacity-50"
                  title="Refresh Ollama models"
                >
                  <RefreshCw size={14} className={isLoadingOllama ? 'animate-spin' : ''} />
                  {isLoadingOllama ? 'Detecting...' : 'Detect Ollama'}
                </button>
              </div>
            </div>

            {/* OpenRouter status message */}
            {openRouterError && (
              <div className="text-xs text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 rounded-lg">
                {openRouterError}
              </div>
            )}
            {openRouterAvailable && !openRouterError && (
              <div className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-3 py-2 rounded-lg">
                ✓ OpenRouter connected: {openRouterModels.length} model{openRouterModels.length !== 1 ? 's' : ''} available
              </div>
            )}

            {/* Ollama status message */}
            {ollamaError && (
              <div className="text-xs text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 rounded-lg">
                {ollamaError}
              </div>
            )}
            {ollamaAvailable && !ollamaError && (
              <div className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-3 py-2 rounded-lg">
                ✓ Ollama detected: {ollamaLLMModels.length} LLM model{ollamaLLMModels.length !== 1 ? 's' : ''}, {ollamaEmbeddingModels.length} embedding model{ollamaEmbeddingModels.length !== 1 ? 's' : ''}
              </div>
            )}

            {/* LLM Model */}
            <div>
              <label
                htmlFor="llm-model"
                className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
              >
                LLM Model
              </label>

              {/* OpenRouter Model Search */}
              {openRouterModels.length > 0 && (
                <div className="mb-2">
                  <input
                    type="text"
                    placeholder="Search OpenRouter models (e.g., gpt-4, claude, llama)..."
                    value={modelSearch}
                    onChange={(e) => setModelSearch(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text placeholder-light-text-secondary dark:placeholder-dark-text-secondary focus:outline-none focus:ring-2 focus:ring-primary"
                  />
                  {modelSearch.trim() !== '' && (() => {
                    const { totalMatches, truncated } = filterAndGroupModels(openRouterModels, modelSearch);
                    return (
                      <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                        {truncated
                          ? `Showing 50 of ${totalMatches} matching models`
                          : `${totalMatches} model${totalMatches !== 1 ? 's' : ''} found`}
                      </p>
                    );
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
                    <option key={model.value} value={model.value}>
                      {model.label}
                    </option>
                  ))}
                </optgroup>
                {openRouterModels.length > 0 && (() => {
                  const { groups, totalMatches } = filterAndGroupModels(openRouterModels, modelSearch);
                  if (totalMatches === 0) {
                    return (
                      <optgroup label="OpenRouter (Multi-Provider)">
                        <option disabled>No models match your search</option>
                      </optgroup>
                    );
                  }
                  return groups.map(group => (
                    <optgroup key={group.provider} label={`OpenRouter - ${group.provider}`}>
                      {group.models.map((model) => (
                        <option key={model.value} value={model.value}>
                          {model.label}
                        </option>
                      ))}
                    </optgroup>
                  ));
                })()}
                {ollamaLLMModels.length > 0 && (
                  <optgroup label="Ollama (Local - Auto-detected)">
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
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                {settings.llm_model.startsWith('ollama:')
                  ? 'Ollama models run locally. Make sure Ollama is running on your machine.'
                  : settings.llm_model.startsWith('openrouter:')
                  ? 'OpenRouter provides access to multiple AI providers (Claude, GPT-4, Llama, etc.) through one API.'
                  : 'OpenAI models require an API key. Cloud-based processing.'}
              </p>
            </div>

            {/* Embedding Model */}
            <div>
              <label
                htmlFor="embedding-model"
                className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
              >
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
                    <option key={model.value} value={model.value}>
                      {model.label}
                    </option>
                  ))}
                </optgroup>
                {ollamaEmbeddingModels.length > 0 && (
                  <optgroup label="Ollama (Local - Auto-detected)">
                    {ollamaEmbeddingModels.map((model) => (
                      <option key={model.value} value={model.value}>
                        {model.label} {model.size ? `[${model.size}]` : ''}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                Used for generating document embeddings for semantic search
              </p>

              {/* Embedding Model Status Indicator */}
              <div className="mt-2 flex items-center gap-2">
                {isCheckingEmbedding ? (
                  <div className="flex items-center gap-2 text-xs text-light-text-secondary dark:text-dark-text-secondary">
                    <Loader2 size={14} className="animate-spin" />
                    Checking embedding model...
                  </div>
                ) : embeddingHealth ? (
                  <div className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg w-full ${
                    embeddingHealth.available
                      ? 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20'
                      : 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
                  }`}>
                    {embeddingHealth.available ? (
                      <CheckCircle2 size={14} className="flex-shrink-0" />
                    ) : (
                      <XCircle size={14} className="flex-shrink-0" />
                    )}
                    <span>{embeddingHealth.message}</span>
                  </div>
                ) : null}
                <button
                  type="button"
                  onClick={checkEmbeddingModelHealth}
                  disabled={isCheckingEmbedding}
                  className="flex-shrink-0 flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors disabled:opacity-50"
                  title="Check embedding model status"
                >
                  <RefreshCw size={14} className={isCheckingEmbedding ? 'animate-spin' : ''} />
                </button>
              </div>
            </div>
          </div>

          {/* RAG Options Section */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
              RAG Options
            </h3>

            {/* Enable Reranking Toggle */}
            <div className="flex items-center justify-between p-4 bg-light-sidebar dark:bg-dark-sidebar rounded-lg">
              <div className="flex-1">
                <label htmlFor="enable-reranking" className="text-sm font-medium text-light-text dark:text-dark-text">
                  Enable Cohere Reranking
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Improves search relevance by reranking vector search results using Cohere's rerank API (requires Cohere API key)
                </p>
              </div>
              <label htmlFor="enable-reranking" className="relative inline-flex items-center cursor-pointer ml-4">
                <input
                  id="enable-reranking"
                  type="checkbox"
                  checked={settings.enable_reranking}
                  onChange={(e) => updateSetting('enable_reranking', e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-light-border dark:bg-dark-border peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary/20 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-light-border after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
              </label>
            </div>

            {/* Chunking Strategy */}
            <div className="space-y-3 p-4 bg-light-sidebar dark:bg-dark-sidebar rounded-lg">
              <div>
                <label htmlFor="chunk-strategy" className="text-sm font-medium text-light-text dark:text-dark-text">
                  Chunking Strategy
                </label>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  Method used to split documents into chunks for vector search
                </p>
              </div>
              <select
                id="chunk-strategy"
                value={settings.chunk_strategy}
                onChange={(e) => updateSetting('chunk_strategy', e.target.value as Settings['chunk_strategy'])}
                className="w-full px-3 py-2 text-sm bg-white dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg focus:ring-2 focus:ring-primary/20 focus:border-primary text-light-text dark:text-dark-text"
              >
                <option value="agentic">Agentic Splitter (LLM-powered, recommended)</option>
                <option value="semantic">Semantic (structure-aware)</option>
                <option value="paragraph">Paragraph-based</option>
                <option value="fixed">Fixed-size chunks</option>
              </select>
            </div>

            {/* Chunking LLM Model - Only shown when agentic strategy is selected */}
            {settings.chunk_strategy === 'agentic' && (
              <div className="space-y-3 p-4 bg-light-sidebar dark:bg-dark-sidebar rounded-lg">
                <div>
                  <label htmlFor="chunking-llm-model" className="text-sm font-medium text-light-text dark:text-dark-text">
                    Chunking LLM Model
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Separate LLM for agentic chunking. Use an external fast model (e.g. via OpenRouter) to avoid GPU conflicts with local embedding models.
                  </p>
                </div>
                <select
                  id="chunking-llm-model"
                  value={settings.chunking_llm_model}
                  onChange={(e) => updateSetting('chunking_llm_model', e.target.value)}
                  className="w-full px-3 py-2 text-sm bg-white dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg focus:ring-2 focus:ring-primary/20 focus:border-primary text-light-text dark:text-dark-text"
                >
                  {CHUNKING_LLM_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                  {/* Add Ollama models as options */}
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
                {settings.chunking_llm_model.startsWith('openrouter:') && !settings.openrouter_api_key_set && !settings.openrouter_api_key && (
                  <p className="text-xs text-yellow-600 dark:text-yellow-400 mt-1">
                    ⚠ OpenRouter API key required for this model. Add it in the API Keys section above.
                  </p>
                )}
                {settings.chunking_llm_model === '' && (
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Uses the same model as Chat LLM ({settings.llm_model}). Set a separate model to avoid GPU conflicts.
                  </p>
                )}
              </div>
            )}

            {/* Max Chunk Size */}
            <div className="space-y-3 p-4 bg-light-sidebar dark:bg-dark-sidebar rounded-lg">
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
            <div className="space-y-3 p-4 bg-light-sidebar dark:bg-dark-sidebar rounded-lg">
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
          </div>

          {/* Conversation Context Section */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
              Conversation Context
            </h3>

            {/* Context Window Size */}
            <div className="space-y-3 p-4 bg-light-sidebar dark:bg-dark-sidebar rounded-lg">
              <div className="flex items-center justify-between">
                <div>
                  <label htmlFor="context-window-size" className="text-sm font-medium text-light-text dark:text-dark-text">
                    Context Window Size
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    Number of previous messages to include when continuing a conversation (1-100)
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
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                Higher values preserve more conversation history but increase token usage. Messages are also truncated if they exceed the LLM's token limit.
              </p>
            </div>

            {/* Include Chat History in Search */}
            <div className="space-y-3 p-4 bg-light-sidebar dark:bg-dark-sidebar rounded-lg">
              <div className="flex items-center justify-between">
                <div className="flex-1 mr-4">
                  <label className="text-sm font-medium text-light-text dark:text-dark-text">
                    Include Chat History in Search
                  </label>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                    When enabled, your past conversations will be embedded and used to provide context during RAG searches.
                    This allows the assistant to reference previous discussions ("as we discussed before...").
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => updateSetting('include_chat_history_in_search', !settings.include_chat_history_in_search)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    settings.include_chat_history_in_search
                      ? 'bg-primary'
                      : 'bg-light-border dark:bg-dark-border'
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
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                Note: Only new messages sent after enabling this setting will be embedded. Existing conversations won't be retroactively indexed.
              </p>
            </div>
          </div>

          {/* AI Behavior Section (Feature #179) */}
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Bot size={18} className="text-primary" />
              <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
                AI Behavior
              </h3>
            </div>

            {/* System Prompt */}
            <div className="space-y-3 p-4 bg-light-sidebar dark:bg-dark-sidebar rounded-lg">
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
          </div>

          {/* Theme Section */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
              Theme
            </h3>

            <div className="flex gap-2">
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

          {/* Backup & Export Section */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-light-text dark:text-dark-text uppercase tracking-wider">
                Backup & Export
              </h3>
              <button
                type="button"
                onClick={loadBackupStatus}
                disabled={isLoadingBackup}
                className="flex items-center gap-1 text-xs text-primary hover:text-primary-hover transition-colors disabled:opacity-50"
                title="Refresh backup status"
              >
                <RefreshCw size={14} className={isLoadingBackup ? 'animate-spin' : ''} />
                {isLoadingBackup ? 'Loading...' : 'Refresh'}
              </button>
            </div>

            {/* Backup Status */}
            {backupStatus && (
              <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-4 space-y-3">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="flex items-center gap-2">
                    <FileText size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
                    <span className="text-light-text-secondary dark:text-dark-text-secondary">Documents:</span>
                    <span className="text-light-text dark:text-dark-text font-medium">{backupStatus.documents}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <FolderOpen size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
                    <span className="text-light-text-secondary dark:text-dark-text-secondary">Collections:</span>
                    <span className="text-light-text dark:text-dark-text font-medium">{backupStatus.collections}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <MessageSquare size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
                    <span className="text-light-text-secondary dark:text-dark-text-secondary">Conversations:</span>
                    <span className="text-light-text dark:text-dark-text font-medium">{backupStatus.conversations}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <HardDrive size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
                    <span className="text-light-text-secondary dark:text-dark-text-secondary">Files:</span>
                    <span className="text-light-text dark:text-dark-text font-medium">
                      {backupStatus.uploaded_files_count} ({backupStatus.uploaded_files_size_human})
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Backup Button */}
            <button
              type="button"
              onClick={handleCreateBackup}
              disabled={isCreatingBackup}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg border border-primary text-primary hover:bg-primary hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
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

            {/* Backup success message */}
            {backupSuccess && (
              <div className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-3 py-2 rounded-lg flex items-center gap-2">
                <Check size={14} />
                Backup created and downloaded successfully!
              </div>
            )}

            {/* Backup error message */}
            {backupError && (
              <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
                {backupError}
              </div>
            )}

            <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
              Creates a ZIP file containing all documents, collections, conversations, and settings.
              API keys are not included for security.
            </p>

            {/* Divider */}
            <div className="border-t border-light-border dark:border-dark-border my-4"></div>

            {/* Restore Section */}
            <h4 className="text-sm font-medium text-light-text dark:text-dark-text">
              Restore from Backup
            </h4>

            {/* Restore confirmation dialog */}
            {showRestoreConfirm && selectedRestoreFile && (
              <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 space-y-3">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-0.5" size={20} />
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                      Confirm Restore
                    </p>
                    <p className="text-xs text-yellow-700 dark:text-yellow-300">
                      This will <strong>replace all existing data</strong> with the contents of "{selectedRestoreFile.name}".
                      This action cannot be undone. Make sure you have a backup of your current data if needed.
                    </p>
                  </div>
                </div>
                <div className="flex gap-2 justify-end">
                  <button
                    type="button"
                    onClick={handleCancelRestore}
                    className="px-3 py-1.5 text-sm text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirmRestore}
                    className="px-3 py-1.5 text-sm bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 transition-colors"
                  >
                    Yes, Restore Data
                  </button>
                </div>
              </div>
            )}

            {/* Restore file input and button */}
            {!showRestoreConfirm && (
              <>
                <input
                  type="file"
                  ref={restoreFileInputRef}
                  accept=".zip"
                  onChange={handleRestoreFileSelect}
                  className="hidden"
                  id="restore-file-input"
                />
                <button
                  type="button"
                  onClick={() => restoreFileInputRef.current?.click()}
                  disabled={isRestoring}
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg border border-light-border dark:border-dark-border text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
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

            {/* Restore success message */}
            {restoreSuccess && (
              <div className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-3 py-2 rounded-lg space-y-1">
                <div className="flex items-center gap-2">
                  <Check size={14} />
                  <span className="font-medium">Restore completed successfully!</span>
                </div>
                <div className="pl-5 space-y-0.5">
                  <p>Documents restored: {restoreSuccess.documents_restored}</p>
                  <p>Collections restored: {restoreSuccess.collections_restored}</p>
                  <p>Conversations restored: {restoreSuccess.conversations_restored}</p>
                  <p>Messages restored: {restoreSuccess.messages_restored}</p>
                  {restoreSuccess.files_restored > 0 && (
                    <p>Files restored: {restoreSuccess.files_restored}</p>
                  )}
                </div>
              </div>
            )}

            {/* Restore error message */}
            {restoreError && (
              <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
                {restoreError}
              </div>
            )}

            <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
              Select a backup ZIP file to restore. Warning: This will replace all existing data.
            </p>
          </div>

          {/* Feedback Analytics Section */}
          <FeedbackAnalytics className="border border-light-border dark:border-dark-border rounded-lg p-4" />

          {/* Danger Zone Section */}
          <div className="space-y-4 border-2 border-red-500 dark:border-red-600 rounded-lg p-4 bg-red-50 dark:bg-red-900/10">
            <div className="flex items-center gap-2">
              <AlertTriangle className="text-red-600 dark:text-red-400" size={20} />
              <h3 className="text-sm font-semibold text-red-700 dark:text-red-400 uppercase tracking-wider">
                Danger Zone
              </h3>
            </div>

            <div className="space-y-3">
              <p className="text-sm text-red-700 dark:text-red-300">
                Permanently delete all data and start fresh. This action cannot be undone.
              </p>

              {/* Reset confirmation dialog */}
              {showResetConfirm && (
                <div className="bg-white dark:bg-dark-bg border border-red-300 dark:border-red-700 rounded-lg p-4 space-y-3">
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-red-800 dark:text-red-200">
                      ⚠️ Confirm Database Reset
                    </p>
                    <p className="text-xs text-red-700 dark:text-red-300">
                      This will <strong>permanently delete ALL</strong>:
                    </p>
                    <ul className="text-xs text-red-700 dark:text-red-300 list-disc list-inside space-y-1 pl-2">
                      <li>Documents and uploaded files</li>
                      <li>Collections</li>
                      <li>Conversations and messages</li>
                      <li>Vector embeddings</li>
                    </ul>
                    <p className="text-xs text-red-700 dark:text-red-300">
                      Settings (API keys, theme) will be preserved.
                    </p>
                  </div>

                  <div>
                    <label htmlFor="reset-confirmation" className="block text-xs font-medium text-red-800 dark:text-red-200 mb-1">
                      Type <span className="font-mono font-bold">RESET</span> to confirm:
                    </label>
                    <input
                      id="reset-confirmation"
                      type="text"
                      value={resetConfirmationText}
                      onChange={(e) => setResetConfirmationText(e.target.value)}
                      className="w-full px-3 py-2 border border-red-300 dark:border-red-700 rounded-lg bg-white dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-red-500 font-mono"
                      placeholder="RESET"
                      autoFocus
                      disabled={isResetting}
                    />
                  </div>

                  <div className="flex gap-2 justify-end">
                    <button
                      type="button"
                      onClick={handleCancelReset}
                      disabled={isResetting}
                      className="px-3 py-1.5 text-sm text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text transition-colors disabled:opacity-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={handleConfirmReset}
                      disabled={isResetting || resetConfirmationText !== 'RESET'}
                      className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                      {isResetting ? (
                        <>
                          <Loader2 size={14} className="animate-spin" />
                          Resetting...
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

              {/* Reset button (shown when not confirming) */}
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

              {/* Reset success message */}
              {resetSuccess && (
                <div className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-3 py-2 rounded-lg space-y-1">
                  <div className="flex items-center gap-2">
                    <Check size={14} />
                    <span className="font-medium">Database reset successfully!</span>
                  </div>
                  <div className="pl-5 space-y-0.5">
                    <p>Documents deleted: {resetSuccess.documents_deleted}</p>
                    <p>Collections deleted: {resetSuccess.collections_deleted}</p>
                    <p>Conversations deleted: {resetSuccess.conversations_deleted}</p>
                    <p>Messages deleted: {resetSuccess.messages_deleted}</p>
                    <p>Files deleted: {resetSuccess.files_deleted}</p>
                    <p>Embeddings deleted: {resetSuccess.embeddings_deleted}</p>
                  </div>
                  <p className="pl-5 text-xs mt-2">Reloading app...</p>
                </div>
              )}

              {/* Reset error message */}
              {resetError && (
                <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
                  {resetError}
                </div>
              )}
            </div>
          </div>

          {/* Error Message */}
          {error && (
            <div className="text-red-500 text-sm bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2 border-t border-light-border dark:border-dark-border">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text transition-colors"
              disabled={isSaving}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={isSaving}
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
        </form>
      </div>
    </div>
  );
}

export default SettingsModal;
