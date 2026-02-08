/**
 * Document API client for the Agentic RAG System
 */

import type { Document, DocumentUpdate, DocumentCreate } from '../types';

const API_BASE = '/api';

/**
 * Fetch all documents
 */
export async function fetchDocuments(): Promise<Document[]> {
  const response = await fetch(`${API_BASE}/documents/`);
  if (!response.ok) {
    throw new Error(`Failed to fetch documents: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Fetch a single document by ID
 */
export async function fetchDocument(id: string): Promise<Document> {
  const response = await fetch(`${API_BASE}/documents/${id}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch document: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Create a new document
 */
export async function createDocument(doc: DocumentCreate): Promise<Document> {
  const response = await fetch(`${API_BASE}/documents/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(doc),
  });
  if (!response.ok) {
    throw new Error(`Failed to create document: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Update a document's title, comment, or collection
 */
export async function updateDocument(id: string, update: DocumentUpdate): Promise<Document> {
  const response = await fetch(`${API_BASE}/documents/${id}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    throw new Error(`Failed to update document: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Delete a document
 */
export async function deleteDocument(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/documents/${id}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(`Failed to delete document: ${response.statusText}`);
  }
}
