import { useState, useEffect } from 'react'
import { X, FileText, FileSpreadsheet, FileCode, File, Calendar, HardDrive, FolderOpen, Hash, Eye, ChevronDown, ChevronUp, Loader2, RefreshCw, CheckCircle, AlertTriangle, Cpu, History, Upload, Database, Trash2, Clock, XCircle } from 'lucide-react'
import type { Document, DocumentPreview } from '../types'

// Feature #267: Document history event type
interface DocumentHistoryEvent {
  id: number
  action: string
  status: string
  details?: Record<string, unknown>
  document_id?: string
  document_name?: string
  file_size?: number
  chunk_count?: number
  model_used?: string
  duration_ms?: number
  created_at?: string
}

interface DocumentHistoryResponse {
  document_id: string
  events: DocumentHistoryEvent[]
  total_events: number
}

// Helper function to get file type icon based on mime type
function getFileIcon(mimeType: string | undefined) {
  if (!mimeType) return FileText;
  if (mimeType.includes('pdf')) return FileText;
  if (mimeType.includes('spreadsheet') || mimeType.includes('csv') || mimeType.includes('excel')) return FileSpreadsheet;
  if (mimeType.includes('json') || mimeType.includes('markdown')) return FileCode;
  if (mimeType.includes('word') || mimeType.includes('document')) return FileText;
  return File;
}

// Helper function to get file type label
function getFileTypeLabel(mimeType: string | undefined): string {
  if (!mimeType) return 'FILE';
  if (mimeType.includes('pdf')) return 'PDF';
  if (mimeType.includes('csv')) return 'CSV';
  if (mimeType.includes('spreadsheet') || mimeType.includes('excel')) return 'Excel';
  if (mimeType.includes('json')) return 'JSON';
  if (mimeType.includes('markdown')) return 'Markdown';
  if (mimeType.includes('word') || mimeType.includes('document')) return 'Word';
  if (mimeType.includes('text/plain')) return 'Text';
  return 'File';
}

// Helper function to format file size
function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Helper function to format date
function formatDate(dateString: string | undefined): string {
  if (!dateString) return 'Unknown';
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

interface DocumentDetailsModalProps {
  document: Document | null
  isOpen: boolean
  onClose: () => void
  onDocumentUpdated?: () => void  // Callback to refresh document list after re-embed
}

export function DocumentDetailsModal({ document, isOpen, onClose, onDocumentUpdated }: DocumentDetailsModalProps) {
  const [isPreviewExpanded, setIsPreviewExpanded] = useState(false)
  const [preview, setPreview] = useState<DocumentPreview | null>(null)
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)

  // Embedding count state
  const [embeddingCount, setEmbeddingCount] = useState<number | null>(null)
  const [isLoadingEmbeddings, setIsLoadingEmbeddings] = useState(false)

  // Re-embed state
  const [isReEmbedding, setIsReEmbedding] = useState(false)
  const [reEmbedResult, setReEmbedResult] = useState<{success: boolean; message: string} | null>(null)

  // Feature #267: Document history state
  const [isHistoryExpanded, setIsHistoryExpanded] = useState(false)
  const [history, setHistory] = useState<DocumentHistoryEvent[]>([])
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)

  // Reset state when document changes or modal closes
  useEffect(() => {
    if (!isOpen || !document) {
      setIsPreviewExpanded(false)
      setPreview(null)
      setPreviewError(null)
      setEmbeddingCount(null)
      setReEmbedResult(null)
      setIsHistoryExpanded(false)
      setHistory([])
      setHistoryError(null)
    }
  }, [isOpen, document?.id])

  // Fetch embedding count when modal opens for an unstructured document
  useEffect(() => {
    if (isOpen && document && document.document_type === 'unstructured') {
      fetchEmbeddingCount()
    }
  }, [isOpen, document?.id])

  const fetchEmbeddingCount = async () => {
    if (!document) return
    setIsLoadingEmbeddings(true)
    try {
      const response = await fetch(`/api/documents/${document.id}/embedding-count`)
      if (response.ok) {
        const data = await response.json()
        setEmbeddingCount(data.embedding_count)
      }
    } catch (error) {
      console.error('Error fetching embedding count:', error)
    } finally {
      setIsLoadingEmbeddings(false)
    }
  }

  const handleReEmbed = async () => {
    if (!document) return
    setIsReEmbedding(true)
    setReEmbedResult(null)
    try {
      const response = await fetch(`/api/documents/${document.id}/re-embed`, {
        method: 'POST'
      })
      const data = await response.json()
      if (response.ok) {
        setReEmbedResult({
          success: data.success,
          message: data.message
        })
        setEmbeddingCount(data.embedding_count)
        // Notify parent to refresh document list
        onDocumentUpdated?.()
      } else {
        setReEmbedResult({
          success: false,
          message: data.detail || 'Re-embed failed'
        })
      }
    } catch (error) {
      console.error('Error re-embedding document:', error)
      setReEmbedResult({
        success: false,
        message: 'Network error during re-embed'
      })
    } finally {
      setIsReEmbedding(false)
    }
  }

  // Fetch preview when expanded
  useEffect(() => {
    if (isPreviewExpanded && document && !preview && !isLoadingPreview) {
      fetchPreview()
    }
  }, [isPreviewExpanded, document?.id])

  const fetchPreview = async () => {
    if (!document) return

    setIsLoadingPreview(true)
    setPreviewError(null)

    try {
      const response = await fetch(`/api/documents/${document.id}/preview`)
      if (!response.ok) {
        throw new Error('Failed to load preview')
      }
      const data: DocumentPreview = await response.json()
      setPreview(data)
    } catch (error) {
      console.error('Error fetching preview:', error)
      setPreviewError('Failed to load document preview')
    } finally {
      setIsLoadingPreview(false)
    }
  }

  // Feature #267: Fetch history when expanded
  useEffect(() => {
    if (isHistoryExpanded && document && history.length === 0 && !isLoadingHistory) {
      fetchHistory()
    }
  }, [isHistoryExpanded, document?.id])

  const fetchHistory = async () => {
    if (!document) return

    setIsLoadingHistory(true)
    setHistoryError(null)

    try {
      const response = await fetch(`/api/documents/${document.id}/history`)
      if (!response.ok) {
        throw new Error('Failed to load history')
      }
      const data: DocumentHistoryResponse = await response.json()
      setHistory(data.events)
    } catch (error) {
      console.error('Error fetching history:', error)
      setHistoryError('Failed to load document history')
    } finally {
      setIsLoadingHistory(false)
    }
  }

  // Feature #267: Helper to format action names for display
  const formatAction = (action: string): { label: string; icon: React.ReactNode; color: string } => {
    switch (action) {
      case 'document_uploaded':
        return { label: 'Document Uploaded', icon: <Upload size={14} />, color: 'text-blue-600 dark:text-blue-400' }
      case 'embedding_started':
        return { label: 'Embedding Started', icon: <Database size={14} />, color: 'text-yellow-600 dark:text-yellow-400' }
      case 'embedding_completed':
        return { label: 'Embedding Completed', icon: <CheckCircle size={14} />, color: 'text-green-600 dark:text-green-400' }
      case 'embedding_failed':
        return { label: 'Embedding Failed', icon: <XCircle size={14} />, color: 'text-red-600 dark:text-red-400' }
      case 'document_deleted':
        return { label: 'Document Deleted', icon: <Trash2 size={14} />, color: 'text-red-600 dark:text-red-400' }
      case 'document_re_embed_started':
        return { label: 'Re-embed Started', icon: <RefreshCw size={14} />, color: 'text-yellow-600 dark:text-yellow-400' }
      case 'document_re_embed_completed':
        return { label: 'Re-embed Completed', icon: <CheckCircle size={14} />, color: 'text-green-600 dark:text-green-400' }
      default:
        return { label: action, icon: <History size={14} />, color: 'text-gray-600 dark:text-gray-400' }
    }
  }

  // Feature #267: Helper to format duration
  const formatDuration = (ms?: number): string => {
    if (!ms) return '-'
    if (ms < 1000) return `${ms}ms`
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
    return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
  }

  if (!isOpen || !document) return null;

  const FileIcon = getFileIcon(document.mime_type);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-dark-bg rounded-lg shadow-xl w-full max-w-2xl mx-4 overflow-hidden max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-light-border dark:border-dark-border flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-primary/10 rounded-lg">
              <FileIcon size={24} className="text-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-light-text dark:text-dark-text">
                Document Details
              </h2>
              <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                {getFileTypeLabel(document.mime_type)} Document
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
            aria-label="Close modal"
          >
            <X size={20} className="text-light-text-secondary dark:text-dark-text-secondary" />
          </button>
        </div>

        {/* Content - Scrollable */}
        <div className="p-4 space-y-4 overflow-y-auto flex-1">
          {/* Document Name */}
          <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-4">
            <label className="block text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide mb-1">
              Document Name
            </label>
            <p className="text-light-text dark:text-dark-text font-medium text-lg">
              {document.title}
            </p>
          </div>

          {/* Details Grid */}
          <div className="grid grid-cols-2 gap-4">
            {/* Original Filename */}
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <File size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
                <label className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
                  Original Filename
                </label>
              </div>
              <p className="text-light-text dark:text-dark-text text-sm truncate" title={document.original_filename}>
                {document.original_filename}
              </p>
            </div>

            {/* File Size */}
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <HardDrive size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
                <label className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
                  File Size
                </label>
              </div>
              <p className="text-light-text dark:text-dark-text text-sm">
                {formatFileSize(document.file_size)}
              </p>
            </div>

            {/* Document Type */}
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <FolderOpen size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
                <label className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
                  Document Type
                </label>
              </div>
              <p className="text-light-text dark:text-dark-text text-sm capitalize">
                {document.document_type}
              </p>
            </div>

            {/* MIME Type */}
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <Hash size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
                <label className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
                  MIME Type
                </label>
              </div>
              <p className="text-light-text dark:text-dark-text text-sm truncate" title={document.mime_type}>
                {document.mime_type}
              </p>
            </div>
          </div>

          {/* Upload Date - Full Width */}
          <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-3">
            <div className="flex items-center gap-2 mb-1">
              <Calendar size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
              <label className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
                Upload Date
              </label>
            </div>
            <p className="text-light-text dark:text-dark-text text-sm">
              {formatDate(document.created_at)}
            </p>
          </div>

          {/* Comment (if exists) */}
          {document.comment && (
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-3">
              <label className="block text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide mb-1">
                Comment
              </label>
              <p className="text-light-text dark:text-dark-text text-sm">
                {document.comment}
              </p>
            </div>
          )}

          {/* Embedding Status (for unstructured documents) */}
          {document.document_type === 'unstructured' && (
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <Hash size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
                <label className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
                  Embeddings
                </label>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    {isLoadingEmbeddings ? (
                      <Loader2 size={16} className="animate-spin text-primary" />
                    ) : embeddingCount !== null && embeddingCount > 0 ? (
                      <>
                        <CheckCircle size={16} className="text-green-500" />
                        <span className="text-light-text dark:text-dark-text text-sm">
                          {embeddingCount} chunks embedded
                        </span>
                      </>
                    ) : (
                      <>
                        <AlertTriangle size={16} className="text-amber-500" />
                        <span className="text-amber-600 dark:text-amber-400 text-sm font-medium">
                          No embeddings — document not searchable
                        </span>
                      </>
                    )}
                  </div>
                  {/* Feature #259: Show embedding model used */}
                  {document.embedding_model && (
                    <div className="flex items-center gap-2 ml-6">
                      <Cpu size={12} className="text-light-text-secondary dark:text-dark-text-secondary" />
                      <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                        Model: {document.embedding_model}
                      </span>
                    </div>
                  )}
                </div>
                {/* Re-embed button: show for docs with 0 embeddings, or allow re-embed for any */}
                <button
                  onClick={handleReEmbed}
                  disabled={isReEmbedding}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg transition-colors ${
                    isReEmbedding
                      ? 'bg-gray-200 dark:bg-gray-700 text-gray-400 cursor-not-allowed'
                      : embeddingCount === 0
                        ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/50 font-medium'
                        : 'bg-light-border dark:bg-dark-border text-light-text-secondary dark:text-dark-text-secondary hover:bg-gray-200 dark:hover:bg-gray-600'
                  }`}
                  title={embeddingCount === 0 ? "Generate embeddings for this document" : "Re-generate embeddings"}
                >
                  {isReEmbedding ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      <span>Re-embedding...</span>
                    </>
                  ) : (
                    <>
                      <RefreshCw size={14} />
                      <span>{embeddingCount === 0 ? 'Generate Embeddings' : 'Re-embed'}</span>
                    </>
                  )}
                </button>
              </div>
              {/* Re-embed result toast */}
              {reEmbedResult && (
                <div className={`mt-2 p-2 rounded text-sm ${
                  reEmbedResult.success
                    ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-800'
                    : 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800'
                }`}>
                  {reEmbedResult.success ? (
                    <div className="flex items-center gap-1.5">
                      <CheckCircle size={14} />
                      <span>{reEmbedResult.message}</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5">
                      <AlertTriangle size={14} />
                      <span>{reEmbedResult.message}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Collection (if assigned) */}
          {document.collection_id && (
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <FolderOpen size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
                <label className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide">
                  Collection
                </label>
              </div>
              <p className="text-light-text dark:text-dark-text text-sm">
                {document.collection_id}
              </p>
            </div>
          )}

          {/* Content Preview Section */}
          <div className="border border-light-border dark:border-dark-border rounded-lg overflow-hidden">
            {/* Preview Toggle Button */}
            <button
              onClick={() => setIsPreviewExpanded(!isPreviewExpanded)}
              className="w-full flex items-center justify-between p-3 bg-light-sidebar dark:bg-dark-sidebar hover:bg-light-border dark:hover:bg-dark-border transition-colors"
            >
              <div className="flex items-center gap-2">
                <Eye size={16} className="text-primary" />
                <span className="text-sm font-medium text-light-text dark:text-dark-text">
                  Content Preview
                </span>
                {preview && preview.preview_type === 'table' && (
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                    ({preview.preview_rows} of {preview.total_rows} rows)
                  </span>
                )}
              </div>
              {isPreviewExpanded ? (
                <ChevronUp size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
              ) : (
                <ChevronDown size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
              )}
            </button>

            {/* Preview Content */}
            {isPreviewExpanded && (
              <div className="p-3 border-t border-light-border dark:border-dark-border bg-white dark:bg-dark-bg">
                {isLoadingPreview ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 size={24} className="animate-spin text-primary" />
                    <span className="ml-2 text-sm text-light-text-secondary dark:text-dark-text-secondary">
                      Loading preview...
                    </span>
                  </div>
                ) : previewError ? (
                  <div className="text-center py-4">
                    <p className="text-sm text-red-500">{previewError}</p>
                    <button
                      onClick={fetchPreview}
                      className="mt-2 text-sm text-primary hover:underline"
                    >
                      Try again
                    </button>
                  </div>
                ) : preview ? (
                  preview.preview_type === 'table' ? (
                    /* Table Preview for Structured Data */
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-light-border dark:border-dark-border">
                            {preview.columns?.map((column, idx) => (
                              <th
                                key={idx}
                                className="px-3 py-2 text-left text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wide whitespace-nowrap"
                              >
                                {column}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {preview.rows?.map((row, rowIdx) => (
                            <tr
                              key={rowIdx}
                              className="border-b border-light-border dark:border-dark-border last:border-b-0 hover:bg-light-sidebar dark:hover:bg-dark-sidebar"
                            >
                              {preview.columns?.map((column, colIdx) => (
                                <td
                                  key={colIdx}
                                  className="px-3 py-2 text-light-text dark:text-dark-text whitespace-nowrap"
                                >
                                  {String(row[column] ?? '')}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {preview.total_rows && preview.preview_rows && preview.total_rows > preview.preview_rows && (
                        <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-2 text-center">
                          Showing {preview.preview_rows} of {preview.total_rows} rows
                        </p>
                      )}
                    </div>
                  ) : (
                    /* Text Preview for Unstructured Data */
                    <div className="max-h-64 overflow-y-auto">
                      <pre className="text-sm text-light-text dark:text-dark-text whitespace-pre-wrap font-sans leading-relaxed">
                        {preview.content}
                      </pre>
                    </div>
                  )
                ) : null}
              </div>
            )}
          </div>

          {/* Feature #267: Document History Section */}
          <div className="border border-light-border dark:border-dark-border rounded-lg overflow-hidden">
            {/* History Toggle Button */}
            <button
              onClick={() => setIsHistoryExpanded(!isHistoryExpanded)}
              className="w-full flex items-center justify-between p-3 bg-light-sidebar dark:bg-dark-sidebar hover:bg-light-border dark:hover:bg-dark-border transition-colors"
            >
              <div className="flex items-center gap-2">
                <History size={16} className="text-primary" />
                <span className="text-sm font-medium text-light-text dark:text-dark-text">
                  Document History
                </span>
                {history.length > 0 && (
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                    ({history.length} events)
                  </span>
                )}
              </div>
              {isHistoryExpanded ? (
                <ChevronUp size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
              ) : (
                <ChevronDown size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
              )}
            </button>

            {/* History Content */}
            {isHistoryExpanded && (
              <div className="p-3 border-t border-light-border dark:border-dark-border bg-white dark:bg-dark-bg">
                {isLoadingHistory ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 size={24} className="animate-spin text-primary" />
                    <span className="ml-2 text-sm text-light-text-secondary dark:text-dark-text-secondary">
                      Loading history...
                    </span>
                  </div>
                ) : historyError ? (
                  <div className="text-center py-4">
                    <p className="text-sm text-red-500">{historyError}</p>
                    <button
                      onClick={fetchHistory}
                      className="mt-2 text-sm text-primary hover:underline"
                    >
                      Try again
                    </button>
                  </div>
                ) : history.length === 0 ? (
                  <div className="text-center py-4">
                    <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                      No history events recorded yet
                    </p>
                    <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                      Events will appear here after document operations
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {history.map((event) => {
                      const { label, icon, color } = formatAction(event.action)
                      return (
                        <div
                          key={event.id}
                          className="flex items-start gap-3 p-2 rounded-lg hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors"
                        >
                          <div className={`flex-shrink-0 mt-0.5 ${color}`}>
                            {icon}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-2">
                              <span className={`text-sm font-medium ${color}`}>
                                {label}
                              </span>
                              <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary flex-shrink-0">
                                {event.status}
                              </span>
                            </div>
                            <div className="flex items-center gap-3 mt-1 text-xs text-light-text-secondary dark:text-dark-text-secondary">
                              {event.created_at && (
                                <span className="flex items-center gap-1">
                                  <Clock size={10} />
                                  {new Date(event.created_at).toLocaleString()}
                                </span>
                              )}
                              {event.duration_ms && event.duration_ms > 0 && (
                                <span>Duration: {formatDuration(event.duration_ms)}</span>
                              )}
                              {event.chunk_count !== undefined && event.chunk_count > 0 && (
                                <span>{event.chunk_count} chunks</span>
                              )}
                            </div>
                            {event.model_used && (
                              <div className="flex items-center gap-1 mt-1 text-xs text-light-text-secondary dark:text-dark-text-secondary">
                                <Cpu size={10} />
                                <span>Model: {event.model_used}</span>
                              </div>
                            )}
                            {event.details && Object.keys(event.details).length > 0 && 'error' in event.details && (
                              <div className="mt-1 text-xs text-light-text-secondary dark:text-dark-text-secondary">
                                <span className="text-red-500">Error: {String(event.details.error)}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-light-border dark:border-dark-border flex-shrink-0">
          <button
            onClick={onClose}
            className="w-full py-2 px-4 bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export default DocumentDetailsModal
