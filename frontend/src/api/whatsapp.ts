/**
 * WhatsApp Admin API client
 *
 * Provides methods for managing WhatsApp users, viewing messages,
 * and getting statistics for the admin dashboard.
 */

// Types
export interface WhatsAppUser {
  id: string
  phone_number: string
  display_name: string | null
  is_blocked: boolean
  message_count: number
  first_seen_at: string
  last_active_at: string
  created_at: string
  updated_at: string
}

export interface WhatsAppMessage {
  id: string
  user_id: string
  message_sid: string | null
  direction: 'inbound' | 'outbound'
  body: string | null
  media_urls: string[] | null
  status: string | null
  error_message: string | null
  created_at: string
}

export interface WhatsAppUserListResponse {
  users: WhatsAppUser[]
  total: number
  page: number
  per_page: number
  total_pages: number
}

export interface WhatsAppMessageListResponse {
  messages: WhatsAppMessage[]
  total: number
  page: number
  per_page: number
  total_pages: number
  user: WhatsAppUser | null
}

export interface WhatsAppStats {
  total_users: number
  total_messages: number
  messages_today: number
  messages_this_week: number
  messages_this_month: number
  active_users_today: number
  active_users_this_week: number
  blocked_users: number
  inbound_messages: number
  outbound_messages: number
}

const API_BASE = '/api/whatsapp/admin'

/**
 * Fetch WhatsApp statistics
 */
export async function fetchWhatsAppStats(): Promise<WhatsAppStats> {
  const response = await fetch(`${API_BASE}/stats`)
  if (!response.ok) {
    throw new Error(`Failed to fetch WhatsApp stats: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch list of WhatsApp users with pagination
 */
export async function fetchWhatsAppUsers(
  page: number = 1,
  perPage: number = 20,
  blockedOnly: boolean = false,
  search?: string
): Promise<WhatsAppUserListResponse> {
  const params = new URLSearchParams({
    page: page.toString(),
    per_page: perPage.toString(),
  })

  if (blockedOnly) {
    params.append('blocked_only', 'true')
  }

  if (search) {
    params.append('search', search)
  }

  const response = await fetch(`${API_BASE}/users?${params.toString()}`)
  if (!response.ok) {
    throw new Error(`Failed to fetch WhatsApp users: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch a single WhatsApp user by ID
 */
export async function fetchWhatsAppUser(userId: string): Promise<WhatsAppUser> {
  const response = await fetch(`${API_BASE}/users/${userId}`)
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('User not found')
    }
    throw new Error(`Failed to fetch WhatsApp user: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch message history for a user
 */
export async function fetchUserMessages(
  userId: string,
  page: number = 1,
  perPage: number = 50
): Promise<WhatsAppMessageListResponse> {
  const params = new URLSearchParams({
    page: page.toString(),
    per_page: perPage.toString(),
  })

  const response = await fetch(`${API_BASE}/users/${userId}/messages?${params.toString()}`)
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('User not found')
    }
    throw new Error(`Failed to fetch user messages: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Block or unblock a WhatsApp user
 */
export async function setUserBlockStatus(
  userId: string,
  isBlocked: boolean
): Promise<WhatsAppUser> {
  const response = await fetch(`${API_BASE}/users/${userId}/block`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ is_blocked: isBlocked }),
  })

  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('User not found')
    }
    throw new Error(`Failed to update user block status: ${response.statusText}`)
  }
  return response.json()
}
