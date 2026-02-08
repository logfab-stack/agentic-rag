/**
 * Collection API client for the Agentic RAG System
 */

import type { Collection, CollectionCreate, CollectionUpdate, CollectionWithDocuments } from '../types';

const API_BASE = '/api';

/**
 * Fetch all collections
 */
export async function fetchCollections(): Promise<Collection[]> {
  const response = await fetch(`${API_BASE}/collections/`);
  if (!response.ok) {
    throw new Error(`Failed to fetch collections: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Fetch a single collection by ID with its documents
 */
export async function fetchCollection(id: string): Promise<CollectionWithDocuments> {
  const response = await fetch(`${API_BASE}/collections/${id}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch collection: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Create a new collection
 */
export async function createCollection(collection: CollectionCreate): Promise<Collection> {
  const response = await fetch(`${API_BASE}/collections/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(collection),
  });
  if (!response.ok) {
    throw new Error(`Failed to create collection: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Update a collection's name or description
 */
export async function updateCollection(id: string, update: CollectionUpdate): Promise<Collection> {
  const response = await fetch(`${API_BASE}/collections/${id}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    throw new Error(`Failed to update collection: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Delete a collection (documents are moved to uncategorized)
 */
export async function deleteCollection(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/collections/${id}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(`Failed to delete collection: ${response.statusText}`);
  }
}
