/**
 * Feedback API client for the Agentic RAG System
 * Handles thumbs up/down feedback for retrieved chunks
 */

const API_BASE = '/api';

export interface FeedbackCreate {
  chunk_id: string;
  query_text: string;
  feedback: 1 | -1;  // +1 for thumbs up, -1 for thumbs down
}

export interface FeedbackResponse {
  id: number;
  chunk_id: string;
  query_text: string;
  feedback: number;
  created_at: string;
}

export interface ChunkFeedbackStats {
  chunk_id: string;
  total_feedback: number;
  positive_count: number;
  negative_count: number;
  net_score: number;
  feedbacks: FeedbackResponse[];
}

/**
 * Submit feedback for a chunk (thumbs up or thumbs down)
 * Uses upsert behavior - if feedback for the same chunk+query exists, it updates
 */
export async function submitFeedback(feedback: FeedbackCreate): Promise<FeedbackResponse> {
  const response = await fetch(`${API_BASE}/feedback/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(feedback),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to submit feedback: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get all feedback for a specific chunk with aggregated stats
 */
export async function getChunkFeedback(chunkId: string): Promise<ChunkFeedbackStats> {
  const response = await fetch(`${API_BASE}/feedback/chunk/${encodeURIComponent(chunkId)}`);

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to get chunk feedback: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Delete a specific feedback record
 */
export async function deleteFeedback(feedbackId: number): Promise<void> {
  const response = await fetch(`${API_BASE}/feedback/${feedbackId}`, {
    method: 'DELETE',
  });

  if (!response.ok) {
    throw new Error(`Failed to delete feedback: ${response.statusText}`);
  }
}


// Analytics types
export interface TopChunkInfo {
  chunk_id: string;
  document_id: string | null;
  document_name: string | null;
  text_preview: string | null;
  net_score: number;
  positive_count: number;
  negative_count: number;
}

export interface FeedbackTrendItem {
  date: string;
  positive: number;
  negative: number;
  total: number;
}

export interface FeedbackAnalyticsResponse {
  total_feedback: number;
  positive_count: number;
  negative_count: number;
  positive_percentage: number;
  negative_percentage: number;
  top_upvoted_chunks: TopChunkInfo[];
  top_downvoted_chunks: TopChunkInfo[];
  feedback_trend: FeedbackTrendItem[];
}

/**
 * Get comprehensive feedback analytics
 * Returns total counts, percentages, top chunks, and trend data
 */
export async function getFeedbackAnalytics(trendDays: number = 30): Promise<FeedbackAnalyticsResponse> {
  const response = await fetch(`${API_BASE}/feedback/analytics?trend_days=${trendDays}`);

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to get feedback analytics: ${response.statusText}`);
  }

  return response.json();
}


// =============================================================================
// Response-level feedback (Feature #350)
// =============================================================================

export interface ResponseFeedbackCreate {
  message_id: string;
  conversation_id: string;
  rating: 1 | -1;
}

export interface ResponseFeedbackResponse {
  id: number;
  message_id: string;
  conversation_id: string;
  query: string;
  response: string;
  rating: number;
  retrieved_chunks: unknown[] | null;
  embedding_model: string | null;
  tool_used: string | null;
  response_source: string | null;
  created_at: string;
}

/**
 * Submit feedback on an AI response (thumbs up or thumbs down).
 * Upserts: if feedback for the same message exists, updates the rating.
 */
export async function submitResponseFeedback(
  data: ResponseFeedbackCreate
): Promise<ResponseFeedbackResponse> {
  const response = await fetch(`${API_BASE}/response-feedback/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to submit response feedback: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get existing feedback for a specific message.
 * Returns null if no feedback exists (404).
 */
export async function getResponseFeedback(
  messageId: string
): Promise<ResponseFeedbackResponse | null> {
  const response = await fetch(`${API_BASE}/response-feedback/${encodeURIComponent(messageId)}`);

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to get response feedback: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Delete feedback for a specific message.
 */
export async function deleteResponseFeedback(messageId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/response-feedback/${encodeURIComponent(messageId)}`, {
    method: 'DELETE',
  });

  if (!response.ok) {
    throw new Error(`Failed to delete response feedback: ${response.statusText}`);
  }
}
