/**
 * EditCollectionModal - Modal for editing/renaming a collection
 */

import { useState, useEffect } from 'react';
import { X, FolderEdit, Loader2 } from 'lucide-react';
import type { Collection, CollectionUpdate } from '../types';
import { updateCollection } from '../api';
import { useFocusTrap } from '../hooks/useFocusTrap';

interface EditCollectionModalProps {
  isOpen: boolean;
  collection: Collection | null;
  onClose: () => void;
  onUpdated: (collection: Collection) => void;
}

export function EditCollectionModal({
  isOpen,
  collection,
  onClose,
  onUpdated,
}: EditCollectionModalProps) {
  // Focus trap for accessibility - keeps focus within modal
  const focusTrapRef = useFocusTrap(isOpen);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isUpdating, setIsUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize form when collection changes
  useEffect(() => {
    if (collection) {
      setName(collection.name);
      setDescription(collection.description || '');
    }
  }, [collection]);

  if (!isOpen || !collection) {
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsUpdating(true);

    try {
      const updateData: CollectionUpdate = {
        name: name.trim(),
        description: description.trim() || null,
      };

      const updatedCollection = await updateCollection(collection.id, updateData);
      onUpdated(updatedCollection);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update collection');
    } finally {
      setIsUpdating(false);
    }
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleClose = () => {
    setError(null);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
      onClick={handleBackdropClick}
    >
      <div
        ref={focusTrapRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-collection-modal-title"
        className="bg-light-bg dark:bg-dark-bg rounded-lg shadow-xl w-full max-w-md mx-4 overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-light-border dark:border-dark-border">
          <h2 id="edit-collection-modal-title" className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
            <FolderEdit size={20} className="text-primary" />
            Edit Collection
          </h2>
          <button
            onClick={handleClose}
            className="text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Collection Name */}
          <div>
            <label
              htmlFor="edit-collection-name"
              className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
            >
              Collection Name <span className="text-red-500">*</span>
            </label>
            <input
              id="edit-collection-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
              placeholder="Enter collection name"
              required
              minLength={1}
              maxLength={255}
              autoFocus
            />
          </div>

          {/* Description */}
          <div>
            <label
              htmlFor="edit-collection-description"
              className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
            >
              Description <span className="text-light-text-secondary dark:text-dark-text-secondary">(optional)</span>
            </label>
            <textarea
              id="edit-collection-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary resize-none"
              placeholder="Add a description for this collection..."
              rows={3}
              maxLength={1000}
            />
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
              onClick={handleClose}
              className="px-4 py-2 text-sm text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text transition-colors"
              disabled={isUpdating}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={isUpdating || !name.trim()}
            >
              {isUpdating ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <FolderEdit size={16} />
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

export default EditCollectionModal;
