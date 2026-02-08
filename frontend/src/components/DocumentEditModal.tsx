/**
 * DocumentEditModal - Modal for editing document name, comment, and collection
 */

import { useState, useEffect } from 'react';
import { X, Save, Loader2, FolderInput } from 'lucide-react';
import type { Document, DocumentUpdate, Collection } from '../types';
import { updateDocument } from '../api';

interface DocumentEditModalProps {
  document: Document | null;
  isOpen: boolean;
  onClose: () => void;
  onSave: (updatedDoc: Document) => void;
  collections?: Collection[];
}

export function DocumentEditModal({
  document,
  isOpen,
  onClose,
  onSave,
  collections = [],
}: DocumentEditModalProps) {
  const [title, setTitle] = useState('');
  const [comment, setComment] = useState('');
  const [collectionId, setCollectionId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form when document changes
  useEffect(() => {
    if (document) {
      setTitle(document.title);
      setComment(document.comment || '');
      setCollectionId(document.collection_id);
      setError(null);
    }
  }, [document]);

  if (!isOpen || !document) {
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSaving(true);

    try {
      const update: DocumentUpdate = {
        title: title.trim(),
        comment: comment.trim() || undefined,
        collection_id: collectionId,
      };

      const updatedDoc = await updateDocument(document.id, update);
      onSave(updatedDoc);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save changes');
    } finally {
      setIsSaving(false);
    }
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
      onClick={handleBackdropClick}
    >
      <div className="bg-light-bg dark:bg-dark-bg rounded-lg shadow-xl w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-light-border dark:border-dark-border">
          <h2 className="text-lg font-semibold text-light-text dark:text-dark-text">
            Edit Document
          </h2>
          <button
            onClick={onClose}
            className="text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Document Name */}
          <div>
            <label
              htmlFor="doc-title"
              className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
            >
              Document Name
            </label>
            <input
              id="doc-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
              placeholder="Enter document name"
              required
              minLength={1}
              maxLength={255}
            />
            <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
              Original file: {document.original_filename}
            </p>
          </div>

          {/* Comment */}
          <div>
            <label
              htmlFor="doc-comment"
              className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
            >
              Comment / Notes
            </label>
            <textarea
              id="doc-comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary resize-none"
              placeholder="Add a comment or description..."
              rows={3}
              maxLength={1000}
            />
          </div>

          {/* Collection Selector */}
          <div>
            <label
              htmlFor="doc-collection"
              className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
            >
              <span className="flex items-center gap-2">
                <FolderInput size={16} />
                Move to Collection
              </span>
            </label>
            <select
              id="doc-collection"
              value={collectionId || ''}
              onChange={(e) => setCollectionId(e.target.value || null)}
              className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="">Uncategorized</option>
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>
                  {collection.name}
                </option>
              ))}
            </select>
            <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
              {collectionId
                ? `Currently in: ${collections.find((c) => c.id === collectionId)?.name || 'Unknown'}`
                : 'Document is uncategorized'}
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div className="text-red-500 text-sm bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text transition-colors"
              disabled={isSaving}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={isSaving || !title.trim()}
            >
              {isSaving ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save size={16} />
                  Save Changes
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default DocumentEditModal;
