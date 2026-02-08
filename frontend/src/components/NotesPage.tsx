import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  StickyNote,
  Search,
  Filter,
  Plus,
  Pencil,
  Trash2,
  FileText,
  Tag,
  Calendar,
  X,
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronUp
} from 'lucide-react'
import { fetchNotes, deleteNote, updateNote, type Note, type NoteListResponse, type NoteUpdate } from '../api/notes'
import type { Document } from '../types'
import { ConfirmDeleteModal } from './ConfirmDeleteModal'
import { AddNoteModal } from './AddNoteModal'
import { useToast } from './Toast'

interface NotesPageProps {
  documents: Document[]
  onRefreshDocuments?: () => void
}

export function NotesPage({ documents }: NotesPageProps) {
  const navigate = useNavigate()
  const { showToast } = useToast()

  // State
  const [notes, setNotes] = useState<Note[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterDocument, setFilterDocument] = useState<string>('')
  const [filterTag, setFilterTag] = useState<string>('')
  const [allTags, setAllTags] = useState<string[]>([])
  const [showFilters, setShowFilters] = useState(false)
  const [pagination, setPagination] = useState<{
    page: number
    per_page: number
    total: number
    total_pages: number
  }>({
    page: 1,
    per_page: 20,
    total: 0,
    total_pages: 1
  })

  // Modal states
  const [isAddNoteModalOpen, setIsAddNoteModalOpen] = useState(false)
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false)
  const [deletingNote, setDeletingNote] = useState<Note | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  // Inline edit state
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null)
  const [editContent, setEditContent] = useState('')
  const [editDocumentId, setEditDocumentId] = useState<string>('')
  const [editTags, setEditTags] = useState<string[]>([])
  const [editTagInput, setEditTagInput] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  // Fetch notes with filters
  const loadNotes = useCallback(async () => {
    setIsLoading(true)
    try {
      const response: NoteListResponse = await fetchNotes({
        page: pagination.page,
        per_page: pagination.per_page,
        document_id: filterDocument || undefined,
        tag: filterTag || undefined
      })

      // Apply search filter client-side
      let filteredNotes = response.notes
      if (searchQuery.trim()) {
        const lowerQuery = searchQuery.toLowerCase()
        filteredNotes = filteredNotes.filter(note =>
          note.content.toLowerCase().includes(lowerQuery) ||
          note.tags.some(tag => tag.toLowerCase().includes(lowerQuery))
        )
      }

      setNotes(filteredNotes)
      setPagination(prev => ({
        ...prev,
        total: searchQuery ? filteredNotes.length : response.total,
        total_pages: searchQuery ? Math.ceil(filteredNotes.length / prev.per_page) : response.total_pages
      }))

      // Extract all unique tags for filter dropdown
      const tags = new Set<string>()
      response.notes.forEach(note => {
        note.tags.forEach(tag => tags.add(tag))
      })
      setAllTags(Array.from(tags).sort())
    } catch (error) {
      console.error('Failed to load notes:', error)
      showToast('error', 'Failed to load notes')
    } finally {
      setIsLoading(false)
    }
  }, [pagination.page, pagination.per_page, filterDocument, filterTag, searchQuery, showToast])

  // Load notes on mount and when filters change
  useEffect(() => {
    loadNotes()
  }, [loadNotes])

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setPagination(prev => ({ ...prev, page: 1 }))
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Get document title by ID
  const getDocumentTitle = (documentId: string | null) => {
    if (!documentId) return null
    const doc = documents.find(d => d.id === documentId)
    return doc ? (doc.title || doc.original_filename) : 'Unknown Document'
  }

  // Handle delete
  const handleDeleteClick = (note: Note) => {
    setDeletingNote(note)
    setIsDeleteModalOpen(true)
  }

  const confirmDelete = async () => {
    if (!deletingNote) return

    setIsDeleting(true)
    try {
      await deleteNote(deletingNote.id)
      setNotes(prev => prev.filter(n => n.id !== deletingNote.id))
      showToast('success', 'Note deleted successfully')
      setIsDeleteModalOpen(false)
      setDeletingNote(null)
    } catch (error) {
      console.error('Failed to delete note:', error)
      showToast('error', 'Failed to delete note')
    } finally {
      setIsDeleting(false)
    }
  }

  // Handle inline edit
  const startEditing = (note: Note) => {
    setEditingNoteId(note.id)
    setEditContent(note.content)
    setEditDocumentId(note.document_id || '')
    setEditTags([...note.tags])
    setEditTagInput('')
  }

  const cancelEditing = () => {
    setEditingNoteId(null)
    setEditContent('')
    setEditDocumentId('')
    setEditTags([])
    setEditTagInput('')
  }

  const addEditTag = () => {
    const trimmedTag = editTagInput.trim().toLowerCase()
    if (trimmedTag && !editTags.includes(trimmedTag)) {
      setEditTags([...editTags, trimmedTag])
      setEditTagInput('')
    }
  }

  const removeEditTag = (tagToRemove: string) => {
    setEditTags(editTags.filter(tag => tag !== tagToRemove))
  }

  const saveEdit = async () => {
    if (!editingNoteId || !editContent.trim()) return

    setIsSaving(true)
    try {
      const update: NoteUpdate = {
        content: editContent.trim(),
        document_id: editDocumentId || null,
        tags: editTags
      }

      const updatedNote = await updateNote(editingNoteId, update)
      setNotes(prev => prev.map(n => n.id === editingNoteId ? updatedNote : n))
      showToast('success', 'Note updated successfully')
      cancelEditing()
    } catch (error) {
      console.error('Failed to update note:', error)
      showToast('error', 'Failed to update note')
    } finally {
      setIsSaving(false)
    }
  }

  // Handle note created from modal
  const handleNoteCreated = () => {
    setIsAddNoteModalOpen(false)
    loadNotes()
  }

  // Clear filters
  const clearFilters = () => {
    setSearchQuery('')
    setFilterDocument('')
    setFilterTag('')
    setPagination(prev => ({ ...prev, page: 1 }))
  }

  const hasActiveFilters = searchQuery || filterDocument || filterTag

  // Format date
  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  }

  // Truncate content for preview
  const truncateContent = (content: string, maxLength: number = 200) => {
    if (content.length <= maxLength) return content
    return content.substring(0, maxLength).trim() + '...'
  }

  return (
    <div className="min-h-screen bg-light-bg dark:bg-dark-bg">
      {/* Header */}
      <header className="sticky top-0 z-10 bg-light-bg dark:bg-dark-bg border-b border-light-border dark:border-dark-border px-4 py-4">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-4">
              <button
                onClick={() => navigate('/')}
                className="p-2 hover:bg-light-sidebar dark:hover:bg-dark-sidebar rounded-lg transition-colors"
                aria-label="Go back"
              >
                <ArrowLeft size={20} className="text-light-text dark:text-dark-text" />
              </button>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                  <StickyNote className="text-primary" size={20} />
                </div>
                <div>
                  <h1 className="text-xl font-semibold text-light-text dark:text-dark-text">
                    Notes
                  </h1>
                  <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                    {pagination.total} {pagination.total === 1 ? 'note' : 'notes'}
                  </p>
                </div>
              </div>
            </div>
            <button
              onClick={() => setIsAddNoteModalOpen(true)}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors"
            >
              <Plus size={20} />
              <span className="hidden sm:inline">New Note</span>
            </button>
          </div>

          {/* Search and Filters */}
          <div className="flex flex-col sm:flex-row gap-3">
            {/* Search Box */}
            <div className="relative flex-1">
              <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary" />
              <input
                type="text"
                placeholder="Search notes..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 border border-light-border dark:border-dark-border rounded-lg bg-light-sidebar dark:bg-dark-sidebar text-light-text dark:text-dark-text placeholder:text-light-text-secondary dark:placeholder:text-dark-text-secondary focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
              />
            </div>

            {/* Filter Toggle Button */}
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={`flex items-center gap-2 px-4 py-2.5 border rounded-lg transition-colors ${
                hasActiveFilters
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-light-border dark:border-dark-border text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar'
              }`}
            >
              <Filter size={18} />
              <span>Filters</span>
              {showFilters ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
            </button>
          </div>

          {/* Filter Dropdowns */}
          {showFilters && (
            <div className="flex flex-wrap gap-3 mt-3 p-4 bg-light-sidebar dark:bg-dark-sidebar rounded-lg">
              {/* Document Filter */}
              <div className="flex-1 min-w-[200px]">
                <label className="flex items-center gap-1 text-sm text-light-text-secondary dark:text-dark-text-secondary mb-1">
                  <FileText size={14} />
                  Document
                </label>
                <select
                  value={filterDocument}
                  onChange={(e) => {
                    setFilterDocument(e.target.value)
                    setPagination(prev => ({ ...prev, page: 1 }))
                  }}
                  className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  <option value="">All Documents</option>
                  {documents.map((doc) => (
                    <option key={doc.id} value={doc.id}>
                      {doc.title || doc.original_filename}
                    </option>
                  ))}
                </select>
              </div>

              {/* Tag Filter */}
              <div className="flex-1 min-w-[200px]">
                <label className="flex items-center gap-1 text-sm text-light-text-secondary dark:text-dark-text-secondary mb-1">
                  <Tag size={14} />
                  Tag
                </label>
                <select
                  value={filterTag}
                  onChange={(e) => {
                    setFilterTag(e.target.value)
                    setPagination(prev => ({ ...prev, page: 1 }))
                  }}
                  className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  <option value="">All Tags</option>
                  {allTags.map((tag) => (
                    <option key={tag} value={tag}>
                      {tag}
                    </option>
                  ))}
                </select>
              </div>

              {/* Clear Filters */}
              {hasActiveFilters && (
                <div className="flex items-end">
                  <button
                    onClick={clearFilters}
                    className="px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                  >
                    Clear Filters
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-4 py-6">
        {isLoading ? (
          /* Loading State */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[...Array(6)].map((_, i) => (
              <div
                key={i}
                className="animate-pulse bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-4 h-48"
              >
                <div className="h-4 bg-light-border dark:bg-dark-border rounded w-3/4 mb-3"></div>
                <div className="h-3 bg-light-border dark:bg-dark-border rounded w-full mb-2"></div>
                <div className="h-3 bg-light-border dark:bg-dark-border rounded w-5/6 mb-2"></div>
                <div className="h-3 bg-light-border dark:bg-dark-border rounded w-2/3"></div>
              </div>
            ))}
          </div>
        ) : notes.length === 0 ? (
          /* Empty State */
          <div className="text-center py-16">
            <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-4">
              <StickyNote className="text-primary" size={32} />
            </div>
            <h2 className="text-xl font-semibold text-light-text dark:text-dark-text mb-2">
              {hasActiveFilters ? 'No notes found' : 'No notes yet'}
            </h2>
            <p className="text-light-text-secondary dark:text-dark-text-secondary mb-6 max-w-md mx-auto">
              {hasActiveFilters
                ? 'Try adjusting your search or filters to find what you\'re looking for.'
                : 'Create your first note to save insights and information for future queries.'}
            </p>
            {hasActiveFilters ? (
              <button
                onClick={clearFilters}
                className="px-4 py-2 border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors"
              >
                Clear Filters
              </button>
            ) : (
              <button
                onClick={() => setIsAddNoteModalOpen(true)}
                className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors"
              >
                Create Your First Note
              </button>
            )}
          </div>
        ) : (
          /* Notes Grid */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {notes.map((note) => (
              <div
                key={note.id}
                className="bg-white dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg overflow-hidden hover:shadow-md transition-shadow"
              >
                {editingNoteId === note.id ? (
                  /* Edit Mode */
                  <div className="p-4">
                    <textarea
                      value={editContent}
                      onChange={(e) => setEditContent(e.target.value)}
                      rows={4}
                      className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text resize-none focus:outline-none focus:ring-2 focus:ring-primary mb-3"
                      placeholder="Note content..."
                      disabled={isSaving}
                    />

                    <div className="mb-3">
                      <label className="flex items-center gap-1 text-xs text-light-text-secondary dark:text-dark-text-secondary mb-1">
                        <FileText size={12} />
                        Document
                      </label>
                      <select
                        value={editDocumentId}
                        onChange={(e) => setEditDocumentId(e.target.value)}
                        className="w-full px-2 py-1.5 text-sm border border-light-border dark:border-dark-border rounded bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
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

                    <div className="mb-3">
                      <label className="flex items-center gap-1 text-xs text-light-text-secondary dark:text-dark-text-secondary mb-1">
                        <Tag size={12} />
                        Tags
                      </label>
                      <div className="flex gap-2 mb-2">
                        <input
                          type="text"
                          value={editTagInput}
                          onChange={(e) => setEditTagInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault()
                              addEditTag()
                            }
                          }}
                          placeholder="Add tag..."
                          className="flex-1 px-2 py-1.5 text-sm border border-light-border dark:border-dark-border rounded bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
                          disabled={isSaving}
                        />
                        <button
                          onClick={addEditTag}
                          disabled={!editTagInput.trim() || isSaving}
                          className="px-2 py-1.5 bg-primary/10 text-primary rounded hover:bg-primary/20 disabled:opacity-50"
                        >
                          <Plus size={16} />
                        </button>
                      </div>
                      {editTags.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {editTags.map((tag) => (
                            <span
                              key={tag}
                              className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary/10 text-primary text-xs rounded-full"
                            >
                              {tag}
                              <button
                                onClick={() => removeEditTag(tag)}
                                disabled={isSaving}
                                className="hover:bg-primary/20 rounded-full"
                              >
                                <X size={12} />
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="flex gap-2 justify-end">
                      <button
                        onClick={cancelEditing}
                        disabled={isSaving}
                        className="px-3 py-1.5 text-sm border border-light-border dark:border-dark-border rounded text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-bg transition-colors disabled:opacity-50"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={saveEdit}
                        disabled={isSaving || !editContent.trim()}
                        className="px-3 py-1.5 text-sm bg-primary text-white rounded hover:bg-primary-hover transition-colors disabled:opacity-50 flex items-center gap-1"
                      >
                        {isSaving ? (
                          <>
                            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                            </svg>
                            Saving...
                          </>
                        ) : (
                          <>
                            <Check size={16} />
                            Save
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                ) : (
                  /* View Mode */
                  <>
                    <div className="p-4">
                      {/* Content Preview */}
                      <p className="text-light-text dark:text-dark-text text-sm mb-3 whitespace-pre-wrap">
                        {truncateContent(note.content)}
                      </p>

                      {/* Document Link */}
                      {note.document_id && (
                        <div className="flex items-center gap-1.5 text-xs text-light-text-secondary dark:text-dark-text-secondary mb-2">
                          <FileText size={12} />
                          <span className="truncate">{getDocumentTitle(note.document_id)}</span>
                        </div>
                      )}

                      {/* Tags */}
                      {note.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mb-2">
                          {note.tags.map((tag) => (
                            <span
                              key={tag}
                              className="px-2 py-0.5 bg-primary/10 text-primary text-xs rounded-full"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Meta Info */}
                      <div className="flex items-center gap-3 text-xs text-light-text-secondary dark:text-dark-text-secondary">
                        <span className="flex items-center gap-1">
                          <Calendar size={12} />
                          {formatDate(note.created_at)}
                        </span>
                        {note.has_embedding && (
                          <span className="text-green-600 dark:text-green-400">Embedded</span>
                        )}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex border-t border-light-border dark:border-dark-border">
                      <button
                        onClick={() => startEditing(note)}
                        className="flex-1 flex items-center justify-center gap-1.5 py-2.5 text-sm text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-bg transition-colors"
                      >
                        <Pencil size={14} />
                        Edit
                      </button>
                      <div className="w-px bg-light-border dark:border-dark-border" />
                      <button
                        onClick={() => handleDeleteClick(note)}
                        className="flex-1 flex items-center justify-center gap-1.5 py-2.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                      >
                        <Trash2 size={14} />
                        Delete
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {!isLoading && pagination.total_pages > 1 && (
          <div className="flex justify-center items-center gap-4 mt-8">
            <button
              onClick={() => setPagination(prev => ({ ...prev, page: prev.page - 1 }))}
              disabled={pagination.page <= 1}
              className="px-4 py-2 border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
              Page {pagination.page} of {pagination.total_pages}
            </span>
            <button
              onClick={() => setPagination(prev => ({ ...prev, page: prev.page + 1 }))}
              disabled={pagination.page >= pagination.total_pages}
              className="px-4 py-2 border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        )}
      </main>

      {/* Delete Confirmation Modal */}
      <ConfirmDeleteModal
        isOpen={isDeleteModalOpen}
        onClose={() => {
          setIsDeleteModalOpen(false)
          setDeletingNote(null)
        }}
        onConfirm={confirmDelete}
        title="Delete Note"
        message="Are you sure you want to delete this note? This action cannot be undone."
        itemName={deletingNote ? truncateContent(deletingNote.content, 50) : undefined}
        isDeleting={isDeleting}
      />

      {/* Add Note Modal */}
      <AddNoteModal
        isOpen={isAddNoteModalOpen}
        onClose={handleNoteCreated}
        onShowToast={(message, type) => showToast(type, message)}
        documents={documents}
      />
    </div>
  )
}

export default NotesPage
