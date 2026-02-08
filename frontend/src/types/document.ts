/**
 * Document types for the Agentic RAG System
 */

// Document embedding status types (Feature #251)
export type EmbeddingStatus = 'ready' | 'processing' | 'embedding_failed';

// Document file status types (Feature #254)
export type FileStatus = 'ok' | 'file_missing';

// Unified document status types (Feature #258)
export type DocumentStatus = 'uploading' | 'processing' | 'ready' | 'embedding_failed' | 'file_missing';

export interface Document {
  id: string;
  title: string;
  comment: string | null;
  original_filename: string;
  mime_type: string;
  file_size: number;
  document_type: 'structured' | 'unstructured';
  collection_id: string | null;
  schema_info: string | null;
  // Feature #251: Track embedding status for documents
  embedding_status: EmbeddingStatus;
  // Feature #254: Track file existence status for orphaned record detection
  file_status?: FileStatus;
  // Feature #258: Unified document processing status
  status?: DocumentStatus;
  // Feature #260: Store chunk/embedding count for quick health checks
  chunk_count?: number;
  // Feature #259: Track which embedding model was used for this document
  embedding_model?: string | null;
  // Note: 'url' field intentionally excluded to prevent exposing internal file paths
  created_at: string;
  updated_at: string;
}

export interface DocumentUpdate {
  title?: string;
  comment?: string;
  collection_id?: string | null;
}

export interface DocumentCreate {
  title: string;
  comment?: string;
  original_filename: string;
  mime_type: string;
  file_size: number;
  document_type?: 'structured' | 'unstructured';
  collection_id?: string;
}

export interface UploadResponse {
  document: Document;
  embedding_status: 'success' | 'partial' | 'failed' | 'skipped';
  warnings: string[];
}

export interface DocumentPreview {
  document_id: string;
  document_type: 'structured' | 'unstructured';
  preview_type: 'table' | 'text';
  content?: string;  // Text content for unstructured
  rows?: Record<string, unknown>[];  // Table rows for structured
  columns?: string[];  // Column headers for structured
  total_rows?: number;  // Total rows count for structured
  preview_rows?: number;  // Number of rows in preview
}
