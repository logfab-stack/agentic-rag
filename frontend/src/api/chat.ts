/**
 * Chat API client for the Agentic RAG System
 */

const API_BASE = '/api';

export interface ChatRequest {
  message: string;
  conversation_id?: string;
  model?: string;
  // Feature #205: Document/collection scoping
  document_ids?: string[];
  collection_id?: string;
}

export interface ChatResponse {
  id: string;
  conversation_id: string;
  role: 'assistant';
  content: string;
  tool_used: string | null;
  tool_details: Record<string, unknown> | null;
  created_at: string;
  response_source?: 'rag' | 'direct' | 'hybrid';  // Feature #67: Response source indicator
}

/**
 * Send a chat message and get an AI response
 */
export async function sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/chat/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Failed to send message: ${response.statusText}`);
  }

  return response.json();
}
