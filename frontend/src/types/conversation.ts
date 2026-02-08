/**
 * Conversation-related types for the Agentic RAG System
 */

export interface Conversation {
  id: string;
  title: string;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface ConversationCreate {
  title?: string;
}

export interface ConversationUpdate {
  title?: string;
  is_archived?: boolean;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  tool_used?: string;
  tool_details?: Record<string, unknown>;
  response_source?: 'rag' | 'direct' | 'hybrid';  // Feature #67: Response source indicator
  created_at: string;
}

export interface MessageCreate {
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  tool_used?: string;
  tool_details?: Record<string, unknown>;
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[];
}
