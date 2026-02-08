/**
 * Conversation API client for the Agentic RAG System
 */

import type { Conversation, ConversationCreate, ConversationUpdate, ConversationWithMessages, Message, MessageCreate } from '../types';

const API_BASE = '/api';

/**
 * Paginated response for conversations list
 */
export interface ConversationListResponse {
  conversations: Conversation[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

/**
 * Fetch all conversations, optionally filtered by search query
 * @param search - Optional search query to filter conversations by title or message content
 * @param includeArchived - If true, include archived conversations (default: true)
 * @param page - Page number (default: 1)
 * @param perPage - Items per page (default: 100 to get all in most cases)
 */
export async function fetchConversations(
  search?: string,
  includeArchived: boolean = true,
  page: number = 1,
  perPage: number = 100
): Promise<Conversation[]> {
  const params = new URLSearchParams();
  if (search && search.trim()) {
    params.set('search', search.trim());
  }
  params.set('include_archived', String(includeArchived));
  params.set('page', String(page));
  params.set('per_page', String(perPage));

  let endpoint = `${API_BASE}/conversations/`;
  const queryString = params.toString();
  if (queryString) {
    endpoint += `?${queryString}`;
  }

  const response = await fetch(endpoint);
  if (!response.ok) {
    throw new Error(`Failed to fetch conversations: ${response.statusText}`);
  }
  const data: ConversationListResponse = await response.json();
  return data.conversations;
}

/**
 * Fetch conversations with full pagination info
 * @param search - Optional search query to filter conversations by title or message content
 * @param includeArchived - If true, include archived conversations (default: true)
 * @param page - Page number (default: 1)
 * @param perPage - Items per page (default: 20)
 */
export async function fetchConversationsPaginated(
  search?: string,
  includeArchived: boolean = true,
  page: number = 1,
  perPage: number = 20
): Promise<ConversationListResponse> {
  const params = new URLSearchParams();
  if (search && search.trim()) {
    params.set('search', search.trim());
  }
  params.set('include_archived', String(includeArchived));
  params.set('page', String(page));
  params.set('per_page', String(perPage));

  let endpoint = `${API_BASE}/conversations/`;
  const queryString = params.toString();
  if (queryString) {
    endpoint += `?${queryString}`;
  }

  const response = await fetch(endpoint);
  if (!response.ok) {
    throw new Error(`Failed to fetch conversations: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Fetch a single conversation with all its messages
 */
export async function fetchConversation(id: string): Promise<ConversationWithMessages> {
  const response = await fetch(`${API_BASE}/conversations/${id}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch conversation: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Create a new conversation
 */
export async function createConversation(data?: ConversationCreate): Promise<Conversation> {
  const response = await fetch(`${API_BASE}/conversations/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data || {}),
  });
  if (!response.ok) {
    throw new Error(`Failed to create conversation: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Update a conversation (title and/or is_archived)
 */
export async function updateConversation(id: string, update: ConversationUpdate): Promise<Conversation> {
  const response = await fetch(`${API_BASE}/conversations/${id}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    throw new Error(`Failed to update conversation: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Archive a conversation
 */
export async function archiveConversation(id: string): Promise<Conversation> {
  return updateConversation(id, { is_archived: true });
}

/**
 * Unarchive a conversation
 */
export async function unarchiveConversation(id: string): Promise<Conversation> {
  return updateConversation(id, { is_archived: false });
}

/**
 * Rename a conversation
 */
export async function renameConversation(id: string, title: string): Promise<Conversation> {
  return updateConversation(id, { title });
}

/**
 * Delete a conversation
 */
export async function deleteConversation(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/conversations/${id}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(`Failed to delete conversation: ${response.statusText}`);
  }
}

/**
 * Add a message to a conversation
 */
export async function addMessage(conversationId: string, message: Omit<MessageCreate, 'conversation_id'>): Promise<Message> {
  const response = await fetch(`${API_BASE}/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      ...message,
      conversation_id: conversationId,
    }),
  });
  if (!response.ok) {
    throw new Error(`Failed to add message: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Export a conversation as Markdown or JSON
 * @param conversationId - The ID of the conversation to export
 * @param format - 'markdown' or 'json'
 */
export async function exportConversation(conversationId: string, format: 'markdown' | 'json' = 'markdown'): Promise<void> {
  const response = await fetch(`${API_BASE}/conversations/${conversationId}/export?format=${format}`);
  if (!response.ok) {
    throw new Error(`Failed to export conversation: ${response.statusText}`);
  }

  // Get the content and filename from response
  const contentDisposition = response.headers.get('Content-Disposition');
  const filenameMatch = contentDisposition?.match(/filename="(.+)"/);
  const filename = filenameMatch ? filenameMatch[1] : `conversation.${format === 'json' ? 'json' : 'md'}`;

  // Get the content
  const content = format === 'json' ? JSON.stringify(await response.json(), null, 2) : await response.text();

  // Create blob and trigger download
  const blob = new Blob([content], { type: format === 'json' ? 'application/json' : 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
