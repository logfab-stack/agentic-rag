/**
 * DocumentScopeSelector - Feature #205
 *
 * A dropdown selector for choosing which documents or collection to scope the RAG search to.
 * Allows users to select:
 * - All Documents (default)
 * - A specific collection
 * - Individual document(s)
 */

import { useState, useRef, useEffect } from 'react'
import { FileStack, ChevronDown, Check, FolderOpen, FileText, X } from 'lucide-react'

interface Document {
  id: string
  title: string
  document_type?: string
  collection_id?: string | null
}

interface Collection {
  id: string
  name: string
}

export interface DocumentScope {
  type: 'all' | 'collection' | 'documents'
  collectionId?: string
  documentIds?: string[]
  label: string  // Human-readable label for the chip
}

interface DocumentScopeSelectorProps {
  documents: Document[]
  collections: Collection[]
  scope: DocumentScope
  onScopeChange: (scope: DocumentScope) => void
  disabled?: boolean
}

export function DocumentScopeSelector({
  documents,
  collections,
  scope,
  onScopeChange,
  disabled = false
}: DocumentScopeSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set())
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Initialize selectedDocIds from scope
  useEffect(() => {
    if (scope.type === 'documents' && scope.documentIds) {
      setSelectedDocIds(new Set(scope.documentIds))
    } else {
      setSelectedDocIds(new Set())
    }
  }, [scope])

  const handleSelectAll = () => {
    onScopeChange({ type: 'all', label: 'All Documents' })
    setIsOpen(false)
  }

  const handleSelectCollection = (collection: Collection) => {
    onScopeChange({
      type: 'collection',
      collectionId: collection.id,
      label: collection.name
    })
    setIsOpen(false)
  }

  const handleToggleDocument = (doc: Document) => {
    const newSelected = new Set(selectedDocIds)
    if (newSelected.has(doc.id)) {
      newSelected.delete(doc.id)
    } else {
      newSelected.add(doc.id)
    }
    setSelectedDocIds(newSelected)

    if (newSelected.size === 0) {
      // If no documents selected, fall back to "All"
      onScopeChange({ type: 'all', label: 'All Documents' })
    } else if (newSelected.size === 1) {
      const selectedDoc = documents.find(d => newSelected.has(d.id))
      onScopeChange({
        type: 'documents',
        documentIds: Array.from(newSelected),
        label: selectedDoc?.title || 'Selected Document'
      })
    } else {
      onScopeChange({
        type: 'documents',
        documentIds: Array.from(newSelected),
        label: `${newSelected.size} documents`
      })
    }
  }

  const handleClearScope = (e: React.MouseEvent) => {
    e.stopPropagation()
    onScopeChange({ type: 'all', label: 'All Documents' })
    setSelectedDocIds(new Set())
  }

  // Group documents by collection
  const uncategorizedDocs = documents.filter(d => !d.collection_id)
  const docsByCollection = collections.reduce((acc, col) => {
    acc[col.id] = documents.filter(d => d.collection_id === col.id)
    return acc
  }, {} as Record<string, Document[]>)

  const showClearButton = scope.type !== 'all'

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Selector Button */}
      <button
        type="button"
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 text-sm rounded-lg border transition-colors ${
          scope.type === 'all'
            ? 'text-light-text-secondary dark:text-dark-text-secondary border-light-border dark:border-dark-border hover:border-primary hover:text-primary'
            : 'text-primary border-primary bg-primary/5 hover:bg-primary/10'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        title="Select documents or collection to search"
      >
        <FileStack size={14} />
        <span className="max-w-[120px] truncate">{scope.label}</span>
        {showClearButton ? (
          <span
            role="button"
            tabIndex={0}
            onClick={handleClearScope}
            onKeyDown={(e) => e.key === 'Enter' && handleClearScope(e as unknown as React.MouseEvent)}
            className="ml-0.5 p-0.5 hover:bg-primary/20 rounded cursor-pointer"
            title="Clear selection"
          >
            <X size={12} />
          </span>
        ) : (
          <ChevronDown size={14} className={`transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        )}
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="absolute bottom-full left-0 mb-2 w-72 max-h-80 overflow-y-auto bg-light-sidebar dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg shadow-lg z-50">
          {/* All Documents Option */}
          <button
            type="button"
            onClick={handleSelectAll}
            className={`w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-primary/5 dark:hover:bg-primary/10 transition-colors ${
              scope.type === 'all' ? 'bg-primary/10' : ''
            }`}
          >
            <div className="flex items-center gap-2">
              <FileStack size={16} className="text-primary" />
              <span className="text-sm text-light-text dark:text-dark-text">All Documents</span>
            </div>
            {scope.type === 'all' && <Check size={16} className="text-primary" />}
          </button>

          {/* Divider */}
          <div className="border-t border-light-border dark:border-dark-border my-1" />

          {/* Collections Section */}
          {collections.length > 0 && (
            <>
              <div className="px-4 py-1.5">
                <span className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
                  Collections
                </span>
              </div>
              {collections.map(collection => (
                <button
                  key={collection.id}
                  type="button"
                  onClick={() => handleSelectCollection(collection)}
                  className={`w-full flex items-center justify-between px-4 py-2 text-left hover:bg-primary/5 dark:hover:bg-primary/10 transition-colors ${
                    scope.type === 'collection' && scope.collectionId === collection.id ? 'bg-primary/10' : ''
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <FolderOpen size={14} className="text-amber-500" />
                    <span className="text-sm text-light-text dark:text-dark-text truncate">
                      {collection.name}
                    </span>
                    <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                      ({docsByCollection[collection.id]?.length || 0})
                    </span>
                  </div>
                  {scope.type === 'collection' && scope.collectionId === collection.id && (
                    <Check size={16} className="text-primary" />
                  )}
                </button>
              ))}
              <div className="border-t border-light-border dark:border-dark-border my-1" />
            </>
          )}

          {/* Documents Section */}
          <div className="px-4 py-1.5">
            <span className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
              Documents {selectedDocIds.size > 0 && `(${selectedDocIds.size} selected)`}
            </span>
          </div>

          {/* Uncategorized documents */}
          {uncategorizedDocs.map(doc => (
            <button
              key={doc.id}
              type="button"
              onClick={() => handleToggleDocument(doc)}
              className={`w-full flex items-center justify-between px-4 py-2 text-left hover:bg-primary/5 dark:hover:bg-primary/10 transition-colors ${
                selectedDocIds.has(doc.id) ? 'bg-primary/10' : ''
              }`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <FileText size={14} className="text-light-text-secondary dark:text-dark-text-secondary flex-shrink-0" />
                <span className="text-sm text-light-text dark:text-dark-text truncate">
                  {doc.title}
                </span>
                {doc.document_type && (
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary flex-shrink-0">
                    {doc.document_type === 'structured' ? 'Data' : 'Text'}
                  </span>
                )}
              </div>
              {selectedDocIds.has(doc.id) && <Check size={16} className="text-primary flex-shrink-0" />}
            </button>
          ))}

          {/* Documents by collection */}
          {collections.map(collection => {
            const collectionDocs = docsByCollection[collection.id] || []
            if (collectionDocs.length === 0) return null
            return (
              <div key={collection.id}>
                <div className="px-4 py-1 mt-1">
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary flex items-center gap-1">
                    <FolderOpen size={10} />
                    {collection.name}
                  </span>
                </div>
                {collectionDocs.map(doc => (
                  <button
                    key={doc.id}
                    type="button"
                    onClick={() => handleToggleDocument(doc)}
                    className={`w-full flex items-center justify-between px-4 pl-6 py-2 text-left hover:bg-primary/5 dark:hover:bg-primary/10 transition-colors ${
                      selectedDocIds.has(doc.id) ? 'bg-primary/10' : ''
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <FileText size={14} className="text-light-text-secondary dark:text-dark-text-secondary flex-shrink-0" />
                      <span className="text-sm text-light-text dark:text-dark-text truncate">
                        {doc.title}
                      </span>
                      {doc.document_type && (
                        <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary flex-shrink-0">
                          {doc.document_type === 'structured' ? 'Data' : 'Text'}
                        </span>
                      )}
                    </div>
                    {selectedDocIds.has(doc.id) && <Check size={16} className="text-primary flex-shrink-0" />}
                  </button>
                ))}
              </div>
            )
          })}

          {documents.length === 0 && (
            <div className="px-4 py-3 text-sm text-light-text-secondary dark:text-dark-text-secondary text-center">
              No documents uploaded yet
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default DocumentScopeSelector
