import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Upload,
  FileText,
  FileSpreadsheet,
  FileCode,
  File,
  FileQuestion,
  Folder,
  FolderPlus,
  FolderOpen,
  Pencil,
  Trash2,
  Search,
  X,
  AlertTriangle,
  Grid3X3,
  List,
  ChevronRight,
  GripVertical,
  ArrowLeft,
  Loader2,
  CheckCircle,
  Database
} from 'lucide-react'
import type { Document, Collection, DocumentUpdate } from '../types'
import { updateDocument } from '../api/documents'
import { UploadModal } from './UploadModal'
import { DocumentEditModal } from './DocumentEditModal'
import { DocumentDetailsModal } from './DocumentDetailsModal'
import { ConfirmDeleteModal } from './ConfirmDeleteModal'
import { NewCollectionModal } from './NewCollectionModal'
import { EditCollectionModal } from './EditCollectionModal'
import { useToast } from './Toast'
import { deleteDocument, fetchCollections, deleteCollection } from '../api'

// Types for multi-file upload
interface UploadingFile {
  id: string
  file: File
  title: string
  progress: number
  status: 'pending' | 'uploading' | 'success' | 'error'
  error?: string
}

// Allowed file types for upload
const ALLOWED_TYPES = [
  'application/pdf',
  'text/plain',
  'text/csv',
  'application/csv',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/json',
  'text/markdown',
  'text/x-markdown',
]

const ALLOWED_EXTENSIONS = ['.pdf', '.txt', '.csv', '.xlsx', '.xls', '.docx', '.json', '.md']

// Helper function to get file type icon based on mime type
function getFileIcon(mimeType: string | undefined) {
  if (!mimeType) return FileText
  if (mimeType.includes('pdf')) return FileText
  if (mimeType.includes('spreadsheet') || mimeType.includes('csv') || mimeType.includes('excel')) return FileSpreadsheet
  if (mimeType.includes('json') || mimeType.includes('markdown')) return FileCode
  if (mimeType.includes('word') || mimeType.includes('document')) return FileText
  return File
}

// Helper function to get file type label
function getFileTypeLabel(mimeType: string | undefined): string {
  if (!mimeType) return 'FILE'
  if (mimeType.includes('pdf')) return 'PDF'
  if (mimeType.includes('csv')) return 'CSV'
  if (mimeType.includes('spreadsheet') || mimeType.includes('excel')) return 'XLSX'
  if (mimeType.includes('json')) return 'JSON'
  if (mimeType.includes('markdown')) return 'MD'
  if (mimeType.includes('word') || mimeType.includes('document')) return 'DOCX'
  if (mimeType.includes('text/plain')) return 'TXT'
  return 'FILE'
}

// Helper function to format date
function formatDate(dateString: string | undefined): string {
  if (!dateString) return ''
  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// Helper function to format file size
function formatFileSize(bytes: number | undefined): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function DocumentsPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()

  // State
  const [documents, setDocuments] = useState<Document[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('list')

  // Modal states
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false)
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)
  const [isDetailsModalOpen, setIsDetailsModalOpen] = useState(false)
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false)
  const [isNewCollectionModalOpen, setIsNewCollectionModalOpen] = useState(false)
  const [isEditCollectionModalOpen, setIsEditCollectionModalOpen] = useState(false)
  const [isDeleteCollectionModalOpen, setIsDeleteCollectionModalOpen] = useState(false)

  // Selected items
  const [editingDocument, setEditingDocument] = useState<Document | null>(null)
  const [viewingDocument, setViewingDocument] = useState<Document | null>(null)
  const [deletingDocument, setDeletingDocument] = useState<Document | null>(null)
  const [isDeletingDocument, setIsDeletingDocument] = useState(false)
  const [editingCollection, setEditingCollection] = useState<Collection | null>(null)
  const [deletingCollection, setDeletingCollection] = useState<Collection | null>(null)
  const [isDeletingCollection, setIsDeletingCollection] = useState(false)

  // Drag and drop state
  const [draggingDocumentId, setDraggingDocumentId] = useState<string | null>(null)
  const [dragOverCollectionId, setDragOverCollectionId] = useState<string | null>(null)

  // Context menu state
  const [contextMenuCollection, setContextMenuCollection] = useState<Collection | null>(null)
  const [contextMenuPosition, setContextMenuPosition] = useState<{ x: number; y: number } | null>(null)
  const contextMenuRef = useRef<HTMLDivElement>(null)

  // Multi-file upload state
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([])
  const [showUploadProgress, setShowUploadProgress] = useState(false)
  const [isFileDragOver, setIsFileDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Embedding counts cache for displaying chunks per document
  const [embeddingCounts, setEmbeddingCounts] = useState<Record<string, number>>({})

  // Fetch documents from API
  const fetchDocumentsFromApi = useCallback(async () => {
    try {
      const response = await fetch('/api/documents/')
      if (response.ok) {
        const data: Document[] = await response.json()
        setDocuments(data)

        // Fetch embedding counts for unstructured documents
        const counts: Record<string, number> = {}
        for (const doc of data) {
          if (doc.document_type === 'unstructured') {
            try {
              const countResponse = await fetch(`/api/documents/${doc.id}/embedding-count`)
              if (countResponse.ok) {
                const result = await countResponse.json()
                counts[doc.id] = result.embedding_count
              }
            } catch {
              // Ignore errors for individual counts
            }
          }
        }
        setEmbeddingCounts(counts)
      }
    } catch (error) {
      console.error('Failed to fetch documents:', error)
      showToast('error', 'Failed to load documents')
    } finally {
      setIsLoading(false)
    }
  }, [showToast])

  // Load collections
  const loadCollections = useCallback(async () => {
    try {
      const data = await fetchCollections()
      setCollections(data)
    } catch (error) {
      console.error('Failed to load collections:', error)
    }
  }, [])

  // Load data on mount
  useEffect(() => {
    fetchDocumentsFromApi()
    loadCollections()
  }, [fetchDocumentsFromApi, loadCollections])

  // Close context menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (contextMenuRef.current && !contextMenuRef.current.contains(event.target as Node)) {
        setContextMenuCollection(null)
        setContextMenuPosition(null)
      }
    }

    if (contextMenuCollection) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [contextMenuCollection])

  // Filter documents based on search and collection
  const filteredDocuments = documents.filter(doc => {
    const matchesSearch = !searchQuery ||
      doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (doc.comment && doc.comment.toLowerCase().includes(searchQuery.toLowerCase()))
    // Special handling for 'uncategorized' filter
    const matchesCollection = selectedCollectionId === null ||
      (selectedCollectionId === 'uncategorized' && doc.collection_id === null) ||
      (selectedCollectionId !== 'uncategorized' && doc.collection_id === selectedCollectionId)
    return matchesSearch && matchesCollection
  })

  // Count documents per collection
  const getDocumentCount = (collectionId: string | null) => {
    return documents.filter(d => d.collection_id === collectionId).length
  }

  // Drag handlers
  const handleDragStart = (e: React.DragEvent, documentId: string) => {
    e.dataTransfer.setData('text/plain', documentId)
    e.dataTransfer.effectAllowed = 'move'
    setDraggingDocumentId(documentId)
  }

  const handleDragEnd = () => {
    setDraggingDocumentId(null)
    setDragOverCollectionId(null)
  }

  const handleDragOver = (e: React.DragEvent, collectionId: string | null) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragOverCollectionId(collectionId === null ? 'uncategorized' : collectionId)
  }

  const handleDragLeave = () => {
    setDragOverCollectionId(null)
  }

  const handleDrop = async (e: React.DragEvent, collectionId: string | null) => {
    e.preventDefault()
    const documentId = e.dataTransfer.getData('text/plain')
    setDragOverCollectionId(null)
    setDraggingDocumentId(null)

    if (!documentId) return

    const doc = documents.find(d => d.id === documentId)
    if (!doc || doc.collection_id === collectionId) return

    try {
      const update: DocumentUpdate = { collection_id: collectionId }
      await updateDocument(documentId, update)

      // Update local state
      setDocuments(prev =>
        prev.map(d => d.id === documentId ? { ...d, collection_id: collectionId } : d)
      )

      const collectionName = collectionId
        ? collections.find(c => c.id === collectionId)?.name || 'Unknown'
        : 'Uncategorized'
      showToast('success', `Moved "${doc.title}" to ${collectionName}`)
    } catch (error) {
      console.error('Failed to move document:', error)
      showToast('error', 'Failed to move document')
    }
  }

  // Context menu handler
  const handleCollectionContextMenu = (e: React.MouseEvent, collection: Collection) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenuCollection(collection)
    setContextMenuPosition({ x: e.clientX, y: e.clientY })
  }

  // Get collection name
  const getCollectionName = (collectionId: string | null): string => {
    if (!collectionId) return 'Uncategorized'
    if (collectionId === 'uncategorized') return 'Uncategorized'
    const collection = collections.find(c => c.id === collectionId)
    return collection?.name || 'Unknown'
  }

  // Get selected collection name for display
  const getSelectedCollectionName = (): string => {
    if (selectedCollectionId === null) return 'All Documents'
    if (selectedCollectionId === 'uncategorized') return 'Uncategorized'
    const collection = collections.find(c => c.id === selectedCollectionId)
    return collection?.name || 'Unknown'
  }

  // Handlers
  const handleUploadComplete = () => {
    fetchDocumentsFromApi()
  }

  const handleEmbeddingStatus = (status: string, warnings: string[], documentTitle: string) => {
    const warningDetail = warnings.length > 0 ? ` — ${warnings.join('; ')}` : ''

    if (status === 'failed') {
      showToast('error', `Embedding failed for "${documentTitle}" — the document will not be searchable via RAG${warningDetail}`, 8000)
    } else if (status === 'partial') {
      showToast('warning', `Partial embedding for "${documentTitle}" — some chunks were not processed${warningDetail}`, 8000)
    } else if (status === 'skipped') {
      showToast('info', `Document "${documentTitle}" uploaded — embedding skipped (structured data)`)
    } else {
      showToast('success', `Document "${documentTitle}" uploaded and indexed successfully!`)
    }
  }

  const handleEditDocument = (doc: Document) => {
    setEditingDocument(doc)
    setIsEditModalOpen(true)
  }

  const handleEditSave = (updatedDoc: Document) => {
    setDocuments(prev => prev.map(d => d.id === updatedDoc.id ? updatedDoc : d))
  }

  const handleViewDocument = (doc: Document) => {
    setViewingDocument(doc)
    setIsDetailsModalOpen(true)
  }

  const handleDeleteDocument = (doc: Document) => {
    setDeletingDocument(doc)
    setIsDeleteModalOpen(true)
  }

  const confirmDeleteDocument = async () => {
    if (!deletingDocument) return

    setIsDeletingDocument(true)
    try {
      await deleteDocument(deletingDocument.id)
      setDocuments(prev => prev.filter(d => d.id !== deletingDocument.id))
      showToast('success', `Document "${deletingDocument.title}" deleted successfully!`)
      setIsDeleteModalOpen(false)
      setDeletingDocument(null)
    } catch (error) {
      console.error('Failed to delete document:', error)
      showToast('error', 'Failed to delete document. Please try again.')
    } finally {
      setIsDeletingDocument(false)
    }
  }

  const handleCollectionCreated = (newCollection: Collection) => {
    setCollections(prev => [...prev, newCollection])
  }

  const handleEditCollection = (collection: Collection) => {
    setEditingCollection(collection)
    setIsEditCollectionModalOpen(true)
  }

  const handleCollectionUpdated = (updatedCollection: Collection) => {
    setCollections(prev => prev.map(c => c.id === updatedCollection.id ? updatedCollection : c))
  }

  const handleDeleteCollection = (collection: Collection) => {
    setDeletingCollection(collection)
    setIsDeleteCollectionModalOpen(true)
  }

  const confirmDeleteCollection = async () => {
    if (!deletingCollection) return

    setIsDeletingCollection(true)
    try {
      await deleteCollection(deletingCollection.id)
      setCollections(prev => prev.filter(c => c.id !== deletingCollection.id))
      if (selectedCollectionId === deletingCollection.id) {
        setSelectedCollectionId(null)
      }
      await fetchDocumentsFromApi()
      showToast('success', `Collection "${deletingCollection.name}" deleted. Documents moved to Uncategorized.`)
      setIsDeleteCollectionModalOpen(false)
      setDeletingCollection(null)
    } catch (error) {
      console.error('Failed to delete collection:', error)
      showToast('error', 'Failed to delete collection. Please try again.')
    } finally {
      setIsDeletingCollection(false)
    }
  }

  // Validate file for upload
  const validateFile = (file: File): string | null => {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    const isValidType = ALLOWED_TYPES.includes(file.type) || ALLOWED_EXTENSIONS.includes(ext)

    if (!isValidType) {
      return 'Unsupported file type. Allowed: PDF, TXT, CSV, Excel, Word, JSON, Markdown'
    }

    if (file.size > 100 * 1024 * 1024) {
      return 'File too large. Maximum size is 100MB.'
    }

    return null
  }

  // Handle multi-file upload
  const handleUploadFiles = async (files: File[]) => {
    if (files.length === 0) return

    // Create upload entries
    const newUploads: UploadingFile[] = files.map(file => ({
      id: crypto.randomUUID(),
      file,
      progress: 0,
      status: 'pending',
      title: file.name.replace(/\.[^/.]+$/, '') // Remove extension
    }))

    setUploadingFiles(prev => [...prev, ...newUploads])
    setShowUploadProgress(true)

    // Process each file
    for (const upload of newUploads) {
      const error = validateFile(upload.file)
      if (error) {
        setUploadingFiles(prev => prev.map(u =>
          u.id === upload.id ? { ...u, status: 'error', error } : u
        ))
        continue
      }

      // Update status to uploading
      setUploadingFiles(prev => prev.map(u =>
        u.id === upload.id ? { ...u, status: 'uploading' } : u
      ))

      try {
        const formData = new FormData()
        formData.append('file', upload.file)
        formData.append('title', upload.title)

        // Simulate progress
        const progressInterval = setInterval(() => {
          setUploadingFiles(prev => prev.map(u =>
            u.id === upload.id && u.progress < 90
              ? { ...u, progress: u.progress + 10 }
              : u
          ))
        }, 200)

        const response = await fetch('/api/documents/upload', {
          method: 'POST',
          body: formData,
        })

        clearInterval(progressInterval)

        if (!response.ok) {
          let errorDetail = 'Upload failed'
          try {
            const errorData = await response.json()
            errorDetail = errorData.detail || 'Upload failed'
          } catch {
            const text = await response.text().catch(() => '')
            errorDetail = text || `Upload failed (HTTP ${response.status})`
          }
          throw new Error(errorDetail)
        }

        const result = await response.json()

        // Update status to success
        setUploadingFiles(prev => prev.map(u =>
          u.id === upload.id ? { ...u, status: 'success', progress: 100 } : u
        ))

        // Show appropriate toast based on embedding status
        const embeddingStatus = result.embedding_status || 'success'
        if (embeddingStatus === 'failed') {
          showToast('error', `"${upload.title}" uploaded but embedding failed`)
        } else if (embeddingStatus === 'partial') {
          showToast('warning', `"${upload.title}" uploaded with partial embedding`)
        } else {
          showToast('success', `"${upload.title}" uploaded successfully`)
        }

      } catch (error) {
        setUploadingFiles(prev => prev.map(u =>
          u.id === upload.id ? {
            ...u,
            status: 'error',
            error: error instanceof Error ? error.message : 'Upload failed'
          } : u
        ))
      }
    }

    // Refresh document list
    await fetchDocumentsFromApi()

    // Clear completed uploads after a delay
    setTimeout(() => {
      setUploadingFiles(prev => prev.filter(u => u.status !== 'success'))
      setShowUploadProgress(false)
    }, 3000)
  }

  // Handle file drag events for upload zone
  const handleFileDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    // Only set drag state if dragging files (not documents)
    if (e.dataTransfer.types.includes('Files')) {
      setIsFileDragOver(true)
    }
  }

  const handleFileDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsFileDragOver(false)
  }

  const handleFileDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.dataTransfer.types.includes('Files')) {
      setIsFileDragOver(true)
    }
  }

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsFileDragOver(false)

    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) {
      handleUploadFiles(files)
    }
  }

  // Handle file input change
  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length > 0) {
      handleUploadFiles(files)
    }
    // Reset input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  return (
    <div
      className="flex-1 flex flex-col h-screen bg-light-bg dark:bg-dark-bg overflow-hidden"
      onDragEnter={handleFileDragEnter}
      onDragLeave={handleFileDragLeave}
      onDragOver={handleFileDragOver}
      onDrop={handleFileDrop}
    >
      {/* File drag overlay */}
      {isFileDragOver && (
        <div className="fixed inset-0 z-50 bg-primary/10 border-4 border-dashed border-primary flex items-center justify-center">
          <div className="bg-white dark:bg-dark-sidebar rounded-xl p-8 shadow-2xl text-center">
            <Upload size={48} className="mx-auto mb-4 text-primary" />
            <p className="text-xl font-semibold text-light-text dark:text-dark-text">
              Drop files to upload
            </p>
            <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-2">
              PDF, TXT, CSV, Excel, Word, JSON, Markdown
            </p>
          </div>
        </div>
      )}

      {/* Hidden file input for multi-file selection */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.txt,.csv,.xlsx,.xls,.docx,.json,.md"
        onChange={handleFileInputChange}
        className="hidden"
      />

      {/* Upload progress panel */}
      {showUploadProgress && uploadingFiles.length > 0 && (
        <div className="fixed bottom-4 right-4 z-40 w-80 bg-white dark:bg-dark-sidebar rounded-lg shadow-xl border border-light-border dark:border-dark-border overflow-hidden">
          <div className="px-4 py-3 bg-light-sidebar dark:bg-dark-border flex items-center justify-between">
            <span className="text-sm font-medium text-light-text dark:text-dark-text">
              Uploading {uploadingFiles.length} file{uploadingFiles.length > 1 ? 's' : ''}
            </span>
            <button
              onClick={() => setShowUploadProgress(false)}
              className="p-1 hover:bg-light-border dark:hover:bg-dark-sidebar rounded"
            >
              <X size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
            </button>
          </div>
          <div className="max-h-60 overflow-y-auto">
            {uploadingFiles.map(upload => (
              <div key={upload.id} className="px-4 py-3 border-t border-light-border dark:border-dark-border">
                <div className="flex items-center gap-2 mb-1">
                  {upload.status === 'uploading' && (
                    <Loader2 size={14} className="animate-spin text-primary" />
                  )}
                  {upload.status === 'success' && (
                    <CheckCircle size={14} className="text-green-500" />
                  )}
                  {upload.status === 'error' && (
                    <AlertTriangle size={14} className="text-red-500" />
                  )}
                  {upload.status === 'pending' && (
                    <div className="w-3.5 h-3.5 rounded-full border-2 border-light-border dark:border-dark-border" />
                  )}
                  <span className="text-sm text-light-text dark:text-dark-text truncate flex-1">
                    {upload.file.name}
                  </span>
                </div>
                {upload.status === 'uploading' && (
                  <div className="w-full h-1.5 bg-light-border dark:bg-dark-border rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary transition-all duration-300"
                      style={{ width: `${upload.progress}%` }}
                    />
                  </div>
                )}
                {upload.status === 'error' && upload.error && (
                  <p className="text-xs text-red-500 mt-1">{upload.error}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Header */}
      <header className="px-6 py-4 border-b border-light-border dark:border-dark-border bg-light-sidebar dark:bg-dark-sidebar">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
            <FileText className="text-primary" size={28} />
            Documents
          </h1>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors flex items-center gap-2"
          >
            <Upload size={18} />
            Upload Documents
          </button>
        </div>

        {/* Search and filters */}
        <div className="flex items-center gap-4">
          {/* Search */}
          <div className="relative flex-1 max-w-md">
            <Search
              size={18}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary"
            />
            <input
              type="text"
              placeholder="Search documents..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-10 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text"
              >
                <X size={16} />
              </button>
            )}
          </div>

          {/* View mode toggle */}
          <div className="flex items-center gap-1 p-1 bg-light-border dark:bg-dark-border rounded-lg">
            <button
              onClick={() => setViewMode('list')}
              className={`p-2 rounded ${viewMode === 'list' ? 'bg-white dark:bg-dark-sidebar text-primary' : 'text-light-text-secondary dark:text-dark-text-secondary'}`}
              title="List view"
            >
              <List size={18} />
            </button>
            <button
              onClick={() => setViewMode('grid')}
              className={`p-2 rounded ${viewMode === 'grid' ? 'bg-white dark:bg-dark-sidebar text-primary' : 'text-light-text-secondary dark:text-dark-text-secondary'}`}
              title="Grid view"
            >
              <Grid3X3 size={18} />
            </button>
          </div>
        </div>
      </header>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Collections sidebar */}
        <aside className="w-64 border-r border-light-border dark:border-dark-border bg-light-sidebar dark:bg-dark-sidebar overflow-y-auto flex-shrink-0">
          <div className="p-4">
            {/* Back button and title */}
            <div className="flex items-center gap-2 mb-4">
              <button
                onClick={() => navigate('/')}
                className="p-1.5 text-light-text-secondary dark:text-dark-text-secondary hover:text-primary hover:bg-light-border dark:hover:bg-dark-border rounded transition-colors"
                title="Back to chat"
              >
                <ArrowLeft size={18} />
              </button>
              <h2 className="text-sm font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider flex-1">
                Collections
              </h2>
              <button
                onClick={() => setIsNewCollectionModalOpen(true)}
                className="p-1.5 text-light-text-secondary dark:text-dark-text-secondary hover:text-primary hover:bg-light-border dark:hover:bg-dark-border rounded transition-colors"
                title="New collection"
              >
                <FolderPlus size={18} />
              </button>
            </div>

            {/* All Documents */}
            <button
              onClick={() => setSelectedCollectionId(null)}
              onDragOver={(e) => handleDragOver(e, null)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, null)}
              className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-left transition-colors ${
                selectedCollectionId === null
                  ? 'bg-primary/10 text-primary border border-primary/30'
                  : 'text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border'
              }`}
            >
              <Folder size={18} />
              <span className="flex-1 font-medium">All Documents</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${
                selectedCollectionId === null
                  ? 'bg-primary/20 text-primary'
                  : 'bg-light-border dark:bg-dark-border text-light-text-secondary dark:text-dark-text-secondary'
              }`}>
                {documents.length}
              </span>
            </button>

            {/* Uncategorized - drop target for removing from collections */}
            <button
              onClick={() => setSelectedCollectionId('uncategorized')}
              onDragOver={(e) => handleDragOver(e, null)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, null)}
              className={`w-full flex items-center gap-2 px-3 py-2.5 mt-1 rounded-lg text-left transition-colors ${
                selectedCollectionId === 'uncategorized'
                  ? 'bg-primary/10 text-primary border border-primary/30'
                  : 'text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border'
              } ${dragOverCollectionId === 'uncategorized' ? 'ring-2 ring-primary bg-primary/5' : ''}`}
            >
              <FolderOpen size={18} className={selectedCollectionId === 'uncategorized' ? 'text-primary' : 'text-light-text-secondary dark:text-dark-text-secondary'} />
              <span className="flex-1">Uncategorized</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${
                selectedCollectionId === 'uncategorized'
                  ? 'bg-primary/20 text-primary'
                  : 'bg-light-border dark:bg-dark-border text-light-text-secondary dark:text-dark-text-secondary'
              }`}>
                {getDocumentCount(null)}
              </span>
            </button>

            {/* Divider */}
            {collections.length > 0 && (
              <div className="border-t border-light-border dark:border-dark-border my-3" />
            )}

            {/* Collections list */}
            <div className="space-y-1">
              {collections.map(collection => (
                <div
                  key={collection.id}
                  onContextMenu={(e) => handleCollectionContextMenu(e, collection)}
                  onDragOver={(e) => handleDragOver(e, collection.id)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => handleDrop(e, collection.id)}
                  className={`group flex items-center gap-2 px-3 py-2.5 rounded-lg transition-colors cursor-pointer ${
                    selectedCollectionId === collection.id
                      ? 'bg-primary/10 text-primary border border-primary/30'
                      : 'text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border'
                  } ${dragOverCollectionId === collection.id ? 'ring-2 ring-primary bg-primary/5' : ''}`}
                >
                  <button
                    onClick={() => setSelectedCollectionId(
                      selectedCollectionId === collection.id ? null : collection.id
                    )}
                    className="flex items-center gap-2 flex-1 min-w-0"
                  >
                    <Folder size={18} className={`flex-shrink-0 ${selectedCollectionId === collection.id ? 'text-primary' : 'text-primary/70'}`} />
                    <div className="flex-1 min-w-0">
                      <span className="truncate block">{collection.name}</span>
                      {collection.description && (
                        <span className={`text-xs truncate block ${
                          selectedCollectionId === collection.id
                            ? 'text-primary/70'
                            : 'text-light-text-secondary dark:text-dark-text-secondary'
                        }`}>
                          {collection.description}
                        </span>
                      )}
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      selectedCollectionId === collection.id
                        ? 'bg-primary/20 text-primary'
                        : 'bg-light-border dark:bg-dark-border text-light-text-secondary dark:text-dark-text-secondary'
                    }`}>
                      {getDocumentCount(collection.id)}
                    </span>
                  </button>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleEditCollection(collection)
                      }}
                      className="p-1 hover:bg-light-bg dark:hover:bg-dark-bg rounded"
                      title="Rename collection"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteCollection(collection)
                      }}
                      className="p-1 hover:bg-red-100 dark:hover:bg-red-900/20 text-red-500 rounded"
                      title="Delete collection"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {collections.length === 0 && (
              <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-4 text-center">
                No collections yet.<br />
                Create one to organize your documents.
              </p>
            )}
          </div>
        </aside>

        {/* Documents list/grid */}
        <main className="flex-1 overflow-y-auto p-6">
          {/* Breadcrumb */}
          <div className="flex items-center gap-2 text-sm text-light-text-secondary dark:text-dark-text-secondary mb-4">
            <button
              onClick={() => setSelectedCollectionId(null)}
              className={selectedCollectionId ? 'hover:text-primary' : 'text-light-text dark:text-dark-text font-medium'}
            >
              All Documents
            </button>
            {selectedCollectionId && (
              <>
                <ChevronRight size={14} />
                <span className="text-light-text dark:text-dark-text font-medium">
                  {getSelectedCollectionName()}
                </span>
              </>
            )}
            <span className="ml-auto">
              {filteredDocuments.length} document{filteredDocuments.length !== 1 ? 's' : ''}
            </span>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center h-64">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
          ) : filteredDocuments.length === 0 ? (
            <div
              onClick={() => !searchQuery && fileInputRef.current?.click()}
              className={`flex flex-col items-center justify-center h-64 text-center border-2 border-dashed rounded-xl transition-colors ${
                searchQuery
                  ? 'border-light-border dark:border-dark-border'
                  : 'border-primary/30 hover:border-primary hover:bg-primary/5 cursor-pointer'
              }`}
            >
              <Upload size={48} className="text-light-text-secondary dark:text-dark-text-secondary mb-4 opacity-50" />
              <h3 className="text-lg font-medium text-light-text dark:text-dark-text mb-2">
                {searchQuery ? 'No documents found' : 'No documents yet'}
              </h3>
              <p className="text-light-text-secondary dark:text-dark-text-secondary mb-4">
                {searchQuery
                  ? `No documents match "${searchQuery}"`
                  : 'Drag & drop files here, or click to browse'
                }
              </p>
              {!searchQuery && (
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                  Supported: PDF, TXT, CSV, Excel, Word, JSON, Markdown (max 100MB)
                </p>
              )}
            </div>
          ) : viewMode === 'list' ? (
            /* List View */
            <div className="bg-white dark:bg-dark-sidebar rounded-lg border border-light-border dark:border-dark-border overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-light-border dark:border-dark-border bg-light-bg dark:bg-dark-bg">
                    <th className="text-left px-4 py-3 text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider">Name</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider">Type</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider">Collection</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider">Size</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider">Chunks</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider">Date</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDocuments.map(doc => {
                    const FileIcon = getFileIcon(doc.mime_type)
                    const hasWarning = doc.comment && doc.comment.includes('WARNING') && doc.document_type === 'unstructured'
                    // Feature #258: Use unified status field (with fallbacks for backwards compatibility)
                    const docStatus = doc.status || (doc.file_status === 'file_missing' ? 'file_missing' : doc.embedding_status) || 'ready'
                    const hasEmbeddingFailed = docStatus === 'embedding_failed'
                    const isProcessing = docStatus === 'processing' || docStatus === 'uploading'
                    const hasFileMissing = docStatus === 'file_missing'
                    return (
                      <tr
                        key={doc.id}
                        draggable
                        onDragStart={(e) => handleDragStart(e, doc.id)}
                        onDragEnd={handleDragEnd}
                        onClick={() => handleViewDocument(doc)}
                        className={`border-b border-light-border dark:border-dark-border last:border-b-0 hover:bg-light-bg dark:hover:bg-dark-bg cursor-pointer transition-colors ${
                          draggingDocumentId === doc.id ? 'opacity-50' : ''
                        } ${hasEmbeddingFailed || hasFileMissing ? 'bg-red-50/50 dark:bg-red-900/10' : ''}`}
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3">
                            <GripVertical size={16} className="text-light-text-secondary/50 dark:text-dark-text-secondary/50 cursor-grab" />
                            <FileIcon size={20} className="text-light-text-secondary dark:text-dark-text-secondary flex-shrink-0" />
                            {/* Feature #254: Visual indicator for file missing status */}
                            {hasFileMissing && (
                              <span title="File missing from disk - this is an orphaned record. Go to Admin > Maintenance to clean up.">
                                <FileQuestion
                                  size={16}
                                  className="text-red-500 flex-shrink-0"
                                />
                              </span>
                            )}
                            {/* Feature #251: Visual indicator for embedding status */}
                            {hasEmbeddingFailed && !hasFileMissing && (
                              <span title="Embedding failed - document may not be searchable. Try re-embedding in Admin > Maintenance.">
                                <AlertTriangle
                                  size={16}
                                  className="text-red-500 flex-shrink-0"
                                />
                              </span>
                            )}
                            {isProcessing && (
                              <span title="Document is being processed/re-embedded">
                                <Loader2
                                  size={16}
                                  className="text-primary animate-spin flex-shrink-0"
                                />
                              </span>
                            )}
                            {hasWarning && !hasEmbeddingFailed && !isProcessing && !hasFileMissing && (
                              <span title="Embedding warning">
                                <AlertTriangle
                                  size={16}
                                  className="text-amber-500 flex-shrink-0"
                                />
                              </span>
                            )}
                            <span className="text-light-text dark:text-dark-text truncate max-w-[200px]">
                              {doc.title}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-xs font-medium bg-light-border dark:bg-dark-border px-2 py-1 rounded">
                            {getFileTypeLabel(doc.mime_type)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-light-text-secondary dark:text-dark-text-secondary">
                          {getCollectionName(doc.collection_id)}
                        </td>
                        <td className="px-4 py-3 text-sm text-light-text-secondary dark:text-dark-text-secondary">
                          {formatFileSize(doc.file_size)}
                        </td>
                        <td className="px-4 py-3 text-sm text-light-text-secondary dark:text-dark-text-secondary">
                          {doc.document_type === 'unstructured' && embeddingCounts[doc.id] !== undefined ? (
                            <span className="flex items-center gap-1">
                              <Database size={12} />
                              {embeddingCounts[doc.id]}
                            </span>
                          ) : doc.document_type === 'structured' ? (
                            <span className="text-xs">Tabular</span>
                          ) : (
                            <span>-</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm text-light-text-secondary dark:text-dark-text-secondary">
                          {formatDate(doc.created_at)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                            <button
                              onClick={() => handleEditDocument(doc)}
                              className="p-2 text-light-text-secondary dark:text-dark-text-secondary hover:text-primary hover:bg-light-border dark:hover:bg-dark-border rounded transition-colors"
                              title="Edit document"
                            >
                              <Pencil size={16} />
                            </button>
                            <button
                              onClick={() => handleDeleteDocument(doc)}
                              className="p-2 text-light-text-secondary dark:text-dark-text-secondary hover:text-red-500 hover:bg-red-100 dark:hover:bg-red-900/20 rounded transition-colors"
                              title="Delete document"
                            >
                              <Trash2 size={16} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            /* Grid View */
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {filteredDocuments.map(doc => {
                const FileIcon = getFileIcon(doc.mime_type)
                const hasWarning = doc.comment && doc.comment.includes('WARNING') && doc.document_type === 'unstructured'
                // Feature #258: Use unified status field (with fallbacks for backwards compatibility)
                const docStatus = doc.status || (doc.file_status === 'file_missing' ? 'file_missing' : doc.embedding_status) || 'ready'
                const hasEmbeddingFailed = docStatus === 'embedding_failed'
                const isProcessing = docStatus === 'processing' || docStatus === 'uploading'
                const hasFileMissing = docStatus === 'file_missing'
                return (
                  <div
                    key={doc.id}
                    draggable
                    onDragStart={(e) => handleDragStart(e, doc.id)}
                    onDragEnd={handleDragEnd}
                    onClick={() => handleViewDocument(doc)}
                    className={`group bg-white dark:bg-dark-sidebar rounded-lg border border-light-border dark:border-dark-border p-4 hover:border-primary cursor-grab active:cursor-grabbing transition-all ${
                      draggingDocumentId === doc.id ? 'opacity-50 scale-95' : ''
                    } ${hasEmbeddingFailed || hasFileMissing ? 'border-red-300 dark:border-red-700 bg-red-50/50 dark:bg-red-900/10' : ''}`}
                  >
                    <div className="flex items-start gap-3 mb-3">
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        hasEmbeddingFailed || hasFileMissing ? 'bg-red-100 dark:bg-red-900/30' : 'bg-light-border dark:bg-dark-border'
                      }`}>
                        <FileIcon size={22} className={hasEmbeddingFailed || hasFileMissing ? 'text-red-500' : 'text-light-text-secondary dark:text-dark-text-secondary'} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-sm font-medium text-light-text dark:text-dark-text truncate flex items-center gap-2">
                          {doc.title}
                          {/* Feature #254: Visual indicator for file missing status */}
                          {hasFileMissing && (
                            <span title="File missing from disk - this is an orphaned record. Go to Admin > Maintenance to clean up.">
                              <FileQuestion size={14} className="text-red-500 flex-shrink-0" />
                            </span>
                          )}
                          {/* Feature #251: Visual indicator for embedding status */}
                          {hasEmbeddingFailed && !hasFileMissing && (
                            <span title="Embedding failed - document may not be searchable. Try re-embedding in Admin > Maintenance.">
                              <AlertTriangle size={14} className="text-red-500 flex-shrink-0" />
                            </span>
                          )}
                          {isProcessing && (
                            <span title="Document is being processed/re-embedded">
                              <Loader2 size={14} className="text-primary animate-spin flex-shrink-0" />
                            </span>
                          )}
                          {hasWarning && !hasEmbeddingFailed && !isProcessing && !hasFileMissing && (
                            <AlertTriangle size={14} className="text-amber-500 flex-shrink-0" />
                          )}
                        </h3>
                        <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                          {getFileTypeLabel(doc.mime_type)} • {formatFileSize(doc.file_size)}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center justify-between text-xs text-light-text-secondary dark:text-dark-text-secondary">
                      <span className="truncate">{getCollectionName(doc.collection_id)}</span>
                      <span>{formatDate(doc.created_at)}</span>
                    </div>
                    {/* Chunks count for unstructured documents */}
                    {doc.document_type === 'unstructured' && embeddingCounts[doc.id] !== undefined && (
                      <div className="flex items-center gap-1 text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                        <Database size={12} />
                        <span>{embeddingCounts[doc.id]} chunks</span>
                      </div>
                    )}
                    {doc.document_type === 'structured' && (
                      <div className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                        Tabular data
                      </div>
                    )}
                    <div className="flex items-center justify-end gap-2 mt-3 pt-3 border-t border-light-border dark:border-dark-border opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => handleEditDocument(doc)}
                        className="p-2 text-light-text-secondary dark:text-dark-text-secondary hover:text-primary hover:bg-light-border dark:hover:bg-dark-border rounded transition-colors"
                        title="Edit document"
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        onClick={() => handleDeleteDocument(doc)}
                        className="p-2 text-light-text-secondary dark:text-dark-text-secondary hover:text-red-500 hover:bg-red-100 dark:hover:bg-red-900/20 rounded transition-colors"
                        title="Delete document"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </main>
      </div>

      {/* Modals */}
      <UploadModal
        isOpen={isUploadModalOpen}
        onClose={() => setIsUploadModalOpen(false)}
        onUploadComplete={handleUploadComplete}
        onUploadSuccess={() => {}}
        onEmbeddingStatus={handleEmbeddingStatus}
      />

      <DocumentEditModal
        document={editingDocument}
        isOpen={isEditModalOpen}
        onClose={() => {
          setIsEditModalOpen(false)
          setEditingDocument(null)
        }}
        onSave={handleEditSave}
        collections={collections}
      />

      <DocumentDetailsModal
        document={viewingDocument}
        isOpen={isDetailsModalOpen}
        onClose={() => {
          setIsDetailsModalOpen(false)
          setViewingDocument(null)
        }}
        onDocumentUpdated={fetchDocumentsFromApi}
      />

      <ConfirmDeleteModal
        isOpen={isDeleteModalOpen}
        onClose={() => {
          setIsDeleteModalOpen(false)
          setDeletingDocument(null)
        }}
        onConfirm={confirmDeleteDocument}
        title="Delete Document"
        message="Are you sure you want to delete this document? This action cannot be undone."
        itemName={deletingDocument?.title}
        isDeleting={isDeletingDocument}
      />

      <NewCollectionModal
        isOpen={isNewCollectionModalOpen}
        onClose={() => setIsNewCollectionModalOpen(false)}
        onCreated={handleCollectionCreated}
      />

      <EditCollectionModal
        isOpen={isEditCollectionModalOpen}
        collection={editingCollection}
        onClose={() => {
          setIsEditCollectionModalOpen(false)
          setEditingCollection(null)
        }}
        onUpdated={handleCollectionUpdated}
      />

      <ConfirmDeleteModal
        isOpen={isDeleteCollectionModalOpen}
        onClose={() => {
          setIsDeleteCollectionModalOpen(false)
          setDeletingCollection(null)
        }}
        onConfirm={confirmDeleteCollection}
        title="Delete Collection"
        message="Are you sure you want to delete this collection? Documents in this collection will be moved to Uncategorized."
        itemName={deletingCollection?.name}
        isDeleting={isDeletingCollection}
      />

      {/* Collection Context Menu (right-click) */}
      {contextMenuCollection && contextMenuPosition && (
        <div
          ref={contextMenuRef}
          className="fixed z-50 bg-white dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg shadow-lg py-1 min-w-[160px]"
          style={{
            left: Math.min(contextMenuPosition.x, window.innerWidth - 180),
            top: Math.min(contextMenuPosition.y, window.innerHeight - 100),
          }}
        >
          <button
            onClick={() => {
              handleEditCollection(contextMenuCollection)
              setContextMenuCollection(null)
              setContextMenuPosition(null)
            }}
            className="w-full px-4 py-2 text-left text-sm text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border flex items-center gap-3 transition-colors"
          >
            <Pencil size={16} />
            Rename
          </button>
          <div className="border-t border-light-border dark:border-dark-border my-1" />
          <button
            onClick={() => {
              handleDeleteCollection(contextMenuCollection)
              setContextMenuCollection(null)
              setContextMenuPosition(null)
            }}
            className="w-full px-4 py-2 text-left text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-3 transition-colors"
          >
            <Trash2 size={16} />
            Delete
          </button>
        </div>
      )}
    </div>
  )
}

export default DocumentsPage
