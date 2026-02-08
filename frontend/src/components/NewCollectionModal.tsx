/**
 * NewCollectionModal - Modal for creating a new collection
 */

import { useState } from 'react';
import { X, FolderPlus, Loader2 } from 'lucide-react';
import type { Collection, CollectionCreate } from '../types';
import { createCollection } from '../api';
import { useFocusTrap } from '../hooks/useFocusTrap';

interface NewCollectionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (collection: Collection) => void;
}

export function NewCollectionModal({
  isOpen,
  onClose,
  onCreated,
}: NewCollectionModalProps) {
  // Focus trap for accessibility - keeps focus within modal
  const focusTrapRef = useFocusTrap(isOpen);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  if (!isOpen) {
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsCreating(true);

    try {
      const collectionData: CollectionCreate = {
        name: name.trim(),
        description: description.trim() || null,
      };

      const newCollection = await createCollection(collectionData);
      onCreated(newCollection);

      // Reset form
      setName('');
      setDescription('');
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create collection');
    } finally {
      setIsCreating(false);
    }
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleClose = () => {
    setName('');
    setDescription('');
    setError(null);
    setNameError(null);
    setTouched(false);
    onClose();
  };

  const validateName = (value: string) => {
    if (!value.trim()) {
      setNameError('Collection name is required');
      return false;
    }
    setNameError(null);
    return true;
  };

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setName(value);
    if (touched) {
      validateName(value);
    }
  };

  const handleNameBlur = () => {
    setTouched(true);
    validateName(name);
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
        aria-labelledby="new-collection-modal-title"
        className="bg-light-bg dark:bg-dark-bg rounded-lg shadow-xl w-full max-w-md mx-4 overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-light-border dark:border-dark-border">
          <h2 id="new-collection-modal-title" className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
            <FolderPlus size={20} className="text-primary" />
            New Collection
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
              htmlFor="collection-name"
              className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
            >
              Collection Name <span className="text-red-500">*</span>
            </label>
            <input
              id="collection-name"
              type="text"
              value={name}
              onChange={handleNameChange}
              onBlur={handleNameBlur}
              className={`w-full px-3 py-2 border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 ${
                nameError
                  ? 'border-red-500 focus:ring-red-500'
                  : 'border-light-border dark:border-dark-border focus:ring-primary'
              }`}
              placeholder="Enter collection name"
              required
              minLength={1}
              maxLength={255}
              autoFocus
              aria-invalid={!!nameError}
              aria-describedby={nameError ? 'collection-name-error' : undefined}
            />
            {nameError && (
              <p id="collection-name-error" className="mt-1 text-sm text-red-500">
                {nameError}
              </p>
            )}
          </div>

          {/* Description */}
          <div>
            <label
              htmlFor="collection-description"
              className="block text-sm font-medium text-light-text dark:text-dark-text mb-1"
            >
              Description <span className="text-light-text-secondary dark:text-dark-text-secondary">(optional)</span>
            </label>
            <textarea
              id="collection-description"
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
              disabled={isCreating}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={isCreating || !name.trim()}
            >
              {isCreating ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <FolderPlus size={16} />
                  Create Collection
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default NewCollectionModal;
