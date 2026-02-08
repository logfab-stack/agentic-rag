/**
 * Collection types for the Agentic RAG System
 */

export interface Collection {
  id: string;
  name: string;
  description?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CollectionCreate {
  name: string;
  description?: string | null;
}

export interface CollectionUpdate {
  name?: string;
  description?: string | null;
}

export interface CollectionWithDocuments extends Collection {
  documents: Array<{
    id: string;
    title: string;
    original_filename: string;
    mime_type: string;
    created_at: string | null;
  }>;
}
