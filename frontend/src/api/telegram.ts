/**
 * Telegram Bot API client for webhook management
 *
 * Feature #313: Telegram webhook registration endpoint
 *
 * Provides functions to register/unregister webhooks with Telegram
 * and check the current webhook status.
 */

const API_BASE = '/api/telegram'

/**
 * Response from webhook registration endpoint
 */
export interface RegisterWebhookResponse {
  success: boolean
  message: string
  webhook_url?: string
  description?: string
}

/**
 * Response from webhook info endpoint
 */
export interface WebhookInfoResponse {
  registered: boolean
  url?: string
  has_custom_certificate: boolean
  pending_update_count: number
  last_error_date?: number
  last_error_message?: string
  max_connections?: number
  allowed_updates?: string[]
  ip_address?: string
}

/**
 * Register a webhook URL with Telegram servers.
 *
 * If no URL is provided, the backend will attempt to auto-detect
 * the public URL from ngrok.
 *
 * @param webhookUrl - Optional custom webhook base URL (e.g., https://example.ngrok.io)
 * @returns Registration result with success status and the final webhook URL
 */
export async function registerWebhook(webhookUrl?: string): Promise<RegisterWebhookResponse> {
  const response = await fetch(`${API_BASE}/register-webhook`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ webhook_url: webhookUrl || null }),
  })

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.detail || `Failed to register webhook: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Unregister (delete) the webhook from Telegram servers.
 *
 * After unregistering, Telegram will no longer send updates to your server.
 *
 * @returns Unregistration result with success status
 */
export async function unregisterWebhook(): Promise<RegisterWebhookResponse> {
  const response = await fetch(`${API_BASE}/unregister-webhook`, {
    method: 'DELETE',
  })

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.detail || `Failed to unregister webhook: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Get the current webhook status from Telegram servers.
 *
 * Returns information about the currently registered webhook,
 * including URL, pending updates count, and any errors.
 *
 * @returns Current webhook information
 */
export async function getWebhookInfo(): Promise<WebhookInfoResponse> {
  const response = await fetch(`${API_BASE}/webhook-info`)

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.detail || `Failed to get webhook info: ${response.statusText}`)
  }

  return response.json()
}


// ============================================================================
// Telegram Admin API - Feature #314
// ============================================================================

const ADMIN_API_BASE = '/api/telegram/admin'

// Admin Types
export interface TelegramUser {
  id: string
  chat_id: number
  username: string | null
  first_name: string | null
  last_name: string | null
  message_count: number
  created_at: string
  last_message_at: string | null
}

export interface TelegramMessage {
  id: string
  user_id: string
  telegram_message_id: number | null
  chat_id: number
  direction: 'inbound' | 'outbound'
  content: string | null
  media_type: string | null
  media_file_id: string | null
  created_at: string
}

export interface TelegramUserListResponse {
  users: TelegramUser[]
  total: number
  page: number
  per_page: number
  total_pages: number
}

export interface TelegramMessageListResponse {
  messages: TelegramMessage[]
  total: number
  page: number
  per_page: number
  total_pages: number
  user: TelegramUser | null
}

export interface TelegramStats {
  total_users: number
  total_messages: number
  messages_today: number
  messages_this_week: number
  messages_this_month: number
  active_users_today: number
  active_users_this_week: number
  inbound_messages: number
  outbound_messages: number
}

export interface SendTestMessageResponse {
  success: boolean
  message_id: number | null
  error: string | null
}

/**
 * Fetch Telegram statistics
 */
export async function fetchTelegramStats(): Promise<TelegramStats> {
  const response = await fetch(`${ADMIN_API_BASE}/stats`)
  if (!response.ok) {
    throw new Error(`Failed to fetch Telegram stats: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch list of Telegram users with pagination
 */
export async function fetchTelegramUsers(
  page: number = 1,
  perPage: number = 20,
  search?: string
): Promise<TelegramUserListResponse> {
  const params = new URLSearchParams({
    page: page.toString(),
    per_page: perPage.toString(),
  })

  if (search) {
    params.append('search', search)
  }

  const response = await fetch(`${ADMIN_API_BASE}/users?${params.toString()}`)
  if (!response.ok) {
    throw new Error(`Failed to fetch Telegram users: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch a single Telegram user by chat_id
 */
export async function fetchTelegramUser(chatId: number): Promise<TelegramUser> {
  const response = await fetch(`${ADMIN_API_BASE}/users/${chatId}`)
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('User not found')
    }
    throw new Error(`Failed to fetch Telegram user: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch message history for a user by chat_id
 */
export async function fetchTelegramUserMessages(
  chatId: number,
  page: number = 1,
  perPage: number = 50
): Promise<TelegramMessageListResponse> {
  const params = new URLSearchParams({
    page: page.toString(),
    per_page: perPage.toString(),
  })

  const response = await fetch(`${ADMIN_API_BASE}/users/${chatId}/messages?${params.toString()}`)
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('User not found')
    }
    throw new Error(`Failed to fetch user messages: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Send a test message to a Telegram user
 */
export async function sendTelegramTestMessage(
  chatId: number,
  message: string
): Promise<SendTestMessageResponse> {
  const response = await fetch(`${ADMIN_API_BASE}/send`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ chat_id: chatId, message }),
  })

  if (!response.ok) {
    throw new Error(`Failed to send test message: ${response.statusText}`)
  }
  return response.json()
}
