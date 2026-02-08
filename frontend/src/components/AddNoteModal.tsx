import { useState, useEffect } from 'react'
import { StickyNote, X, FileText, Tag, Plus } from 'lucide-react'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { createNote, type NoteCreate } from '../api/notes'
import type { Document } from '../types'

interface AddNoteModalProps {
  isOpen: boolean
  onClose: () => void
  onShowToast?: (message: string, type: 'success' | 'error') => void
  documents: Document[]
  prefillContent?: string  // Optional content from assistant message
}

export function AddNoteModal({
  isOpen,
  onClose,
  onShowToast,
  documents,
  prefillContent = ''
}: AddNoteModalProps) {
  const [content, setContent] = useState('')
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>('')
  const [tagsInput, setTagsInput] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [isSaving, setIsSaving] = useState(false)

  // Focus trap for accessibility
  const focusTrapRef = useFocusTrap(isOpen)

  // Reset form when modal opens/closes
  useEffect(() => {
    if (isOpen) {
      setContent(prefillContent)
      setSelectedDocumentId('')
      setTagsInput('')
      setTags([])
    }
  }, [isOpen, prefillContent])

  if (!isOpen) return null

  const handleAddTag = () => {
    const trimmedTag = tagsInput.trim().toLowerCase()
    if (trimmedTag && !tags.includes(trimmedTag)) {
      setTags([...tags, trimmedTag])
      setTagsInput('')
    }
  }

  const handleTagInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleAddTag()
    }
  }

  const handleRemoveTag = (tagToRemove: string) => {
    setTags(tags.filter(tag => tag !== tagToRemove))
  }

  const handleSave = async () => {
    if (!content.trim()) {
      onShowToast?.('Note content cannot be empty', 'error')
      return
    }

    setIsSaving(true)
    try {
      const noteData: NoteCreate = {
        content: content.trim(),
        document_id: selectedDocumentId || null,
        tags: tags.length > 0 ? tags : undefined,
      }

      await createNote(noteData)
      onShowToast?.('Note saved! It will be used in future queries', 'success')
      onClose()
    } catch (error) {
      console.error('Failed to save note:', error)
      onShowToast?.('Failed to save note', 'error')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div
        ref={focusTrapRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-note-modal-title"
        className="relative bg-white dark:bg-dark-bg rounded-lg shadow-xl w-full max-w-lg mx-4 p-6 max-h-[90vh] overflow-y-auto"
      >
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text rounded transition-colors"
          disabled={isSaving}
          aria-label="Close"
        >
          <X size={20} />
        </button>

        {/* Icon */}
        <div className="flex items-center justify-center mb-4">
          <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
            <StickyNote className="text-primary" size={24} />
          </div>
        </div>

        {/* Title */}
        <h2 id="add-note-modal-title" className="text-lg font-semibold text-light-text dark:text-dark-text text-center mb-2">
          Add Note
        </h2>

        <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary text-center mb-6">
          Save insights and information for future queries
        </p>

        {/* Note Content */}
        <div className="mb-4">
          <label
            htmlFor="note-content"
            className="block text-sm font-medium text-light-text dark:text-dark-text mb-2"
          >
            Note Content *
          </label>
          <textarea
            id="note-content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Enter your note here..."
            rows={5}
            className="w-full px-4 py-3 border border-light-border dark:border-dark-border rounded-lg bg-light-sidebar dark:bg-dark-sidebar text-light-text dark:text-dark-text placeholder:text-light-text-secondary dark:placeholder:text-dark-text-secondary focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent resize-none"
            disabled={isSaving}
          />
        </div>

        {/* Document Link (Optional) */}
        <div className="mb-4">
          <label
            htmlFor="note-document"
            className="flex items-center gap-2 text-sm font-medium text-light-text dark:text-dark-text mb-2"
          >
            <FileText size={16} />
            Link to Document (Optional)
          </label>
          <select
            id="note-document"
            value={selectedDocumentId}
            onChange={(e) => setSelectedDocumentId(e.target.value)}
            className="w-full px-4 py-3 border border-light-border dark:border-dark-border rounded-lg bg-light-sidebar dark:bg-dark-sidebar text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
            disabled={isSaving}
          >
            <option value="">No document linked</option>
            {documents.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.title || doc.original_filename}
              </option>
            ))}
          </select>
        </div>

        {/* Tags */}
        <div className="mb-6">
          <label
            htmlFor="note-tags"
            className="flex items-center gap-2 text-sm font-medium text-light-text dark:text-dark-text mb-2"
          >
            <Tag size={16} />
            Tags (Optional)
          </label>

          {/* Tag Input */}
          <div className="flex gap-2 mb-2">
            <input
              id="note-tags"
              type="text"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              onKeyDown={handleTagInputKeyDown}
              placeholder="Add a tag and press Enter"
              className="flex-1 px-4 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-sidebar dark:bg-dark-sidebar text-light-text dark:text-dark-text placeholder:text-light-text-secondary dark:placeholder:text-dark-text-secondary focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
              disabled={isSaving}
            />
            <button
              type="button"
              onClick={handleAddTag}
              disabled={!tagsInput.trim() || isSaving}
              className="px-3 py-2 bg-primary/10 text-primary rounded-lg hover:bg-primary/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Plus size={20} />
            </button>
          </div>

          {/* Tag List */}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1 px-2 py-1 bg-primary/10 text-primary text-sm rounded-full"
                >
                  {tag}
                  <button
                    type="button"
                    onClick={() => handleRemoveTag(tag)}
                    className="hover:bg-primary/20 rounded-full p-0.5"
                    disabled={isSaving}
                    aria-label={`Remove tag ${tag}`}
                  >
                    <X size={14} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Info Box */}
        <div className="text-xs text-light-text-secondary dark:text-dark-text-secondary mb-6 p-3 bg-light-sidebar dark:bg-dark-sidebar rounded-lg">
          <p>
            Notes are automatically embedded and will be retrieved during future queries to provide additional context.
            Linking to a document helps organize notes and improve relevance.
          </p>
        </div>

        {/* Buttons */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            disabled={isSaving}
            className="flex-1 py-2 px-4 border border-light-border dark:border-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving || !content.trim()}
            className="flex-1 py-2 px-4 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors disabled:opacity-50 flex items-center justify-center"
          >
            {isSaving ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Saving...
              </>
            ) : (
              <>
                <StickyNote size={16} className="mr-2" />
                Save Note
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

export default AddNoteModal
