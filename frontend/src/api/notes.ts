/**
 * Notes API client for the Agentic RAG System
 */

const API_BASE = '/api';

export interface Note {
  id: string;
  content: string;
  document_id?: string | null;
  tags: string[];
  boost_factor: number;
  has_embedding: boolean;
  created_at: string;
  updated_at: string;
}

export interface NoteCreate {
  content: string;
  document_id?: string | null;
  tags?: string[];
  boost_factor?: number;
}

export interface NoteListResponse {
  notes: Note[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

/**
 * Create a new note
 */
export async function createNote(note: NoteCreate): Promise<Note> {
  const response = await fetch(`${API_BASE}/notes/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(note),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to create note: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Fetch notes with optional filters
 */
export async function fetchNotes(options?: {
  page?: number;
  per_page?: number;
  document_id?: string;
  tag?: string;
}): Promise<NoteListResponse> {
  const params = new URLSearchParams();
  if (options?.page) params.set('page', options.page.toString());
  if (options?.per_page) params.set('per_page', options.per_page.toString());
  if (options?.document_id) params.set('document_id', options.document_id);
  if (options?.tag) params.set('tag', options.tag);

  const url = `${API_BASE}/notes/${params.toString() ? `?${params.toString()}` : ''}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch notes: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get a single note by ID
 */
export async function fetchNote(id: string): Promise<Note> {
  const response = await fetch(`${API_BASE}/notes/${id}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch note: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Update a note
 */
export interface NoteUpdate {
  content?: string;
  document_id?: string | null;
  tags?: string[];
  boost_factor?: number;
}

export async function updateNote(id: string, update: NoteUpdate): Promise<Note> {
  const response = await fetch(`${API_BASE}/notes/${id}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to update note: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Delete a note by ID
 */
export async function deleteNote(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/notes/${id}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(`Failed to delete note: ${response.statusText}`);
  }
}

/**
 * Search notes by content
 */
export async function searchNotes(query: string, options?: {
  page?: number;
  per_page?: number;
  document_id?: string;
  tag?: string;
}): Promise<NoteListResponse> {
  // The API doesn't have a search endpoint yet, so we'll fetch all and filter client-side
  // This is a workaround until backend search is implemented
  const response = await fetchNotes({
    page: options?.page || 1,
    per_page: options?.per_page || 100,
    document_id: options?.document_id,
    tag: options?.tag,
  });

  if (!query.trim()) {
    return response;
  }

  const lowerQuery = query.toLowerCase();
  const filteredNotes = response.notes.filter(note =>
    note.content.toLowerCase().includes(lowerQuery)
  );

  return {
    ...response,
    notes: filteredNotes,
    total: filteredNotes.length,
    total_pages: Math.ceil(filteredNotes.length / (options?.per_page || 100)),
  };
}
