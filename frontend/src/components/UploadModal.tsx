import { useState, useRef, useCallback } from 'react'
import { X, Upload, FileText, AlertCircle, Loader2, CheckCircle, RefreshCw, AlertTriangle } from 'lucide-react'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { checkEmbeddingHealth, EmbeddingHealthCheckResponse } from '../api/settings'

interface UploadModalProps {
  isOpen: boolean
  onClose: () => void
  onUploadComplete?: () => void
  onUploadSuccess?: (documentTitle: string) => void
  onEmbeddingStatus?: (status: string, warnings: string[], documentTitle: string) => void
}

interface DuplicateDocument {
  id: string
  title: string
  original_filename: string
  created_at: string
}

interface DuplicateCheckResult {
  is_duplicate: boolean
  duplicate_document: DuplicateDocument | null
  match_type: 'filename' | 'content' | 'both' | null
}

type UploadStatus = 'idle' | 'checking' | 'duplicate_warning' | 'embedding_warning' | 'uploading' | 'success' | 'error'

export function UploadModal({ isOpen, onClose, onUploadComplete, onUploadSuccess, onEmbeddingStatus }: UploadModalProps) {
  // Focus trap for accessibility - keeps focus within modal
  const focusTrapRef = useFocusTrap(isOpen)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [comment, setComment] = useState('')
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>('idle')
  const [errorMessage, setErrorMessage] = useState('')
  const [uploadProgress, setUploadProgress] = useState(0)
  const [isNetworkError, setIsNetworkError] = useState(false)
  const [duplicateInfo, setDuplicateInfo] = useState<DuplicateCheckResult | null>(null)
  const [titleError, setTitleError] = useState('')
  const [embeddingHealth, setEmbeddingHealth] = useState<EmbeddingHealthCheckResponse | null>(null)
  const [embeddingWarningMsg, setEmbeddingWarningMsg] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

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

  const resetForm = useCallback(() => {
    setSelectedFile(null)
    setTitle('')
    setComment('')
    setUploadStatus('idle')
    setErrorMessage('')
    setTitleError('')
    setUploadProgress(0)
    setIsNetworkError(false)
    setDuplicateInfo(null)
    setEmbeddingHealth(null)
    setEmbeddingWarningMsg('')
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }, [])

  const handleClose = useCallback(() => {
    resetForm()
    onClose()
  }, [onClose, resetForm])

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    // Validate file type
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    const isValidType = ALLOWED_TYPES.includes(file.type) || ALLOWED_EXTENSIONS.includes(ext)

    if (!isValidType) {
      setErrorMessage(`Unsupported file type. Allowed: PDF, TXT, CSV, Excel, Word, JSON, Markdown`)
      setSelectedFile(null)
      return
    }

    // Validate file size (100MB limit)
    if (file.size > 100 * 1024 * 1024) {
      setErrorMessage('File too large. Maximum size is 100MB.')
      setSelectedFile(null)
      return
    }

    setSelectedFile(file)
    setErrorMessage('')
    // Auto-fill title from filename (without extension)
    if (!title) {
      const nameWithoutExt = file.name.replace(/\.[^/.]+$/, '')
      setTitle(nameWithoutExt)
    }
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()

    const file = e.dataTransfer.files[0]
    if (file) {
      // Create a synthetic event to reuse handleFileSelect logic
      const syntheticEvent = {
        target: { files: [file] }
      } as unknown as React.ChangeEvent<HTMLInputElement>
      handleFileSelect(syntheticEvent)
    }
  }

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
  }

  // Check for duplicate files before uploading
  const checkForDuplicate = async (): Promise<DuplicateCheckResult | null> => {
    if (!selectedFile) return null

    try {
      const formData = new FormData()
      formData.append('file', selectedFile)

      const response = await fetch('/api/documents/check-duplicate', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        console.error('Failed to check for duplicates')
        return null
      }

      return await response.json()
    } catch (error) {
      console.error('Error checking for duplicates:', error)
      return null
    }
  }

  // Perform the actual file upload
  const performUpload = async () => {
    if (!selectedFile) {
      setErrorMessage('Please select a file to upload')
      return
    }
    if (!title.trim()) {
      setTitleError('Document title is required')
      setErrorMessage('Document title is required')
      return
    }

    setUploadStatus('uploading')
    setUploadProgress(0)
    setErrorMessage('')
    setIsNetworkError(false)

    try {
      const formData = new FormData()
      formData.append('file', selectedFile)
      formData.append('title', title.trim())
      if (comment.trim()) {
        formData.append('comment', comment.trim())
      }

      // Simulate progress (since fetch doesn't have built-in progress)
      // Progress increases by 5% every 200ms for smoother visual feedback
      const progressInterval = setInterval(() => {
        setUploadProgress(prev => Math.min(prev + 5, 90))
      }, 200)

      const response = await fetch('/api/documents/upload', {
        method: 'POST',
        body: formData,
      })

      clearInterval(progressInterval)

      if (!response.ok) {
        let errorDetail = 'Upload failed'
        try {
          const error = await response.json()
          errorDetail = error.detail || 'Upload failed'
        } catch {
          // Response body is not JSON (e.g. plain text "Internal Server Error")
          const text = await response.text().catch(() => '')
          errorDetail = text || `Upload failed (HTTP ${response.status})`
        }
        throw new Error(errorDetail)
      }

      // Parse the UploadResponse wrapper (includes document, embedding_status, warnings)
      const uploadResponse = await response.json()
      const embeddingStatus = uploadResponse.embedding_status || 'success'
      const warnings: string[] = uploadResponse.warnings || []

      setUploadProgress(100)
      setUploadStatus('success')

      // Show embedding warning if status is 'failed' or 'partial'
      if (embeddingStatus === 'failed' || embeddingStatus === 'partial') {
        const warningText = warnings.length > 0
          ? warnings.join('; ')
          : embeddingStatus === 'failed'
            ? 'Embeddings could not be generated. The document may not be searchable via semantic search.'
            : 'Some embeddings failed to generate. The document may have partial search coverage.'
        setEmbeddingWarningMsg(warningText)
      }

      // Store the title before resetting
      const uploadedTitle = title.trim()

      // Notify parent about embedding status for toast notifications
      if (onEmbeddingStatus) {
        onEmbeddingStatus(embeddingStatus, warnings, uploadedTitle)
      }

      // Call onUploadComplete if provided
      if (onUploadComplete) {
        onUploadComplete()
      }

      // Call onUploadSuccess with the document title
      if (onUploadSuccess) {
        onUploadSuccess(uploadedTitle)
      }

      // Close modal after brief success display (longer if there's a warning)
      const closeDelay = embeddingStatus === 'failed' || embeddingStatus === 'partial' ? 4000 : 1500
      setTimeout(() => {
        handleClose()
      }, closeDelay)

    } catch (error) {
      setUploadStatus('error')
      setUploadProgress(0)

      // Check if this is a network error
      if (error instanceof TypeError && error.message === 'Failed to fetch') {
        setIsNetworkError(true)
        setErrorMessage('Network error. Please check your connection and try again.')
      } else if (error instanceof Error && error.name === 'AbortError') {
        setIsNetworkError(true)
        setErrorMessage('Upload was interrupted. Please try again.')
      } else {
        setIsNetworkError(false)
        setErrorMessage(error instanceof Error ? error.message : 'Upload failed')
      }
    }
  }

  // Check if a file is unstructured (needs embedding) vs structured (CSV, Excel, JSON)
  const isUnstructuredFile = (file: File): boolean => {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    const structuredExtensions = ['.csv', '.xlsx', '.xls', '.json']
    const structuredTypes = [
      'text/csv', 'application/csv',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'application/vnd.ms-excel',
      'application/json'
    ]
    return !structuredExtensions.includes(ext) && !structuredTypes.includes(file.type)
  }

  // Handle the upload button click - check embedding health and duplicates first
  const handleUpload = async () => {
    // Validate required fields
    if (!selectedFile) {
      setErrorMessage('Please select a file to upload')
      return
    }
    if (!title.trim()) {
      setTitleError('Document title is required')
      setErrorMessage('Document title is required')
      return
    }

    setUploadStatus('checking')
    setErrorMessage('')
    setDuplicateInfo(null)
    setEmbeddingHealth(null)

    // For unstructured files, check embedding model availability first
    if (isUnstructuredFile(selectedFile)) {
      try {
        const healthResult = await checkEmbeddingHealth()
        if (!healthResult.available) {
          // Show embedding warning dialog
          setEmbeddingHealth(healthResult)
          setUploadStatus('embedding_warning')
          return
        }
      } catch (err) {
        console.error('Embedding health check failed:', err)
        // If the health check itself fails, continue anyway (best effort)
      }
    }

    // Check for duplicates
    const duplicateCheck = await checkForDuplicate()

    if (duplicateCheck?.is_duplicate) {
      // Show duplicate warning
      setDuplicateInfo(duplicateCheck)
      setUploadStatus('duplicate_warning')
    } else {
      // No duplicate, proceed with upload
      await performUpload()
    }
  }

  // User chose to proceed despite duplicate warning
  const handleProceedAnyway = async () => {
    setDuplicateInfo(null)
    await performUpload()
  }

  // User chose to cancel the upload
  const handleCancelDuplicate = () => {
    setDuplicateInfo(null)
    setUploadStatus('idle')
  }

  // User chose to upload despite embedding model being unavailable
  const handleProceedWithoutEmbedding = async () => {
    setEmbeddingHealth(null)
    setUploadStatus('checking')

    // Still check for duplicates
    const duplicateCheck = await checkForDuplicate()
    if (duplicateCheck?.is_duplicate) {
      setDuplicateInfo(duplicateCheck)
      setUploadStatus('duplicate_warning')
    } else {
      await performUpload()
    }
  }

  // User chose to cancel upload due to embedding unavailability
  const handleCancelEmbeddingWarning = () => {
    setEmbeddingHealth(null)
    setUploadStatus('idle')
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div
        ref={focusTrapRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-modal-title"
        className="bg-white dark:bg-dark-bg rounded-lg shadow-xl w-full max-w-md mx-4"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-light-border dark:border-dark-border">
          <h2 id="upload-modal-title" className="text-lg font-semibold text-light-text dark:text-dark-text">
            Upload Document
          </h2>
          <button
            onClick={handleClose}
            className="p-1 hover:bg-light-border dark:hover:bg-dark-border rounded transition-colors"
          >
            <X size={20} className="text-light-text-secondary dark:text-dark-text-secondary" />
          </button>
        </div>

        {/* Body */}
        <div className="p-4 space-y-4">
          {/* File Drop Zone */}
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors
              ${selectedFile
                ? 'border-primary bg-primary/5'
                : 'border-light-border dark:border-dark-border hover:border-primary'
              }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileSelect}
              accept=".pdf,.txt,.csv,.xlsx,.xls,.docx,.json,.md"
              className="hidden"
            />

            {selectedFile ? (
              <div className="flex items-center justify-center gap-3">
                <FileText size={24} className="text-primary" />
                <div className="text-left">
                  <p className="text-sm font-medium text-light-text dark:text-dark-text">
                    {selectedFile.name}
                  </p>
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                    {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                </div>
              </div>
            ) : (
              <>
                <Upload size={32} className="mx-auto mb-2 text-light-text-secondary dark:text-dark-text-secondary" />
                <p className="text-sm text-light-text dark:text-dark-text">
                  Drop file here or click to browse
                </p>
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                  PDF, TXT, CSV, Excel, Word, JSON, Markdown (max 100MB)
                </p>
              </>
            )}
          </div>

          {/* Title Input */}
          <div>
            <label className="block text-sm font-medium text-light-text dark:text-dark-text mb-1">
              Document Title *
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value)
                // Clear title error when user starts typing
                if (e.target.value.trim()) {
                  setTitleError('')
                }
              }}
              onBlur={() => {
                // Show error on blur if title is empty but file is selected
                if (selectedFile && !title.trim()) {
                  setTitleError('Document title is required')
                }
              }}
              placeholder="Enter a name for this document"
              className={`w-full px-3 py-2 border rounded-lg
                bg-white dark:bg-dark-sidebar text-light-text dark:text-dark-text
                focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent
                ${titleError ? 'border-red-500 dark:border-red-500' : 'border-light-border dark:border-dark-border'}`}
            />
            {titleError && (
              <p className="mt-1 text-sm text-red-600 dark:text-red-400 flex items-center gap-1">
                <AlertCircle size={14} />
                {titleError}
              </p>
            )}
          </div>

          {/* Comment Input */}
          <div>
            <label className="block text-sm font-medium text-light-text dark:text-dark-text mb-1">
              Comment (optional)
            </label>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Add notes or description"
              rows={2}
              className="w-full px-3 py-2 border border-light-border dark:border-dark-border rounded-lg
                bg-white dark:bg-dark-sidebar text-light-text dark:text-dark-text
                focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent resize-none"
            />
          </div>

          {/* Checking for Duplicates */}
          {uploadStatus === 'checking' && (
            <div className="flex items-center gap-2 text-light-text dark:text-dark-text">
              <Loader2 size={16} className="animate-spin text-primary" />
              <span className="text-sm">Checking for duplicates...</span>
            </div>
          )}

          {/* Embedding Model Warning */}
          {uploadStatus === 'embedding_warning' && embeddingHealth && (
            <div className="p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg space-y-3">
              <div className="flex items-start gap-3">
                <AlertTriangle size={20} className="text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
                <div className="space-y-2">
                  <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                    Embedding Model Not Available
                  </p>
                  <p className="text-sm text-amber-700 dark:text-amber-300">
                    The embedding model <strong>{embeddingHealth.model}</strong> is not reachable.
                    The document will be uploaded but <strong>will not be searchable</strong> via semantic search.
                  </p>
                  <div className="text-xs text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/40 rounded p-2">
                    <p><strong>Reason:</strong> {embeddingHealth.message}</p>
                    <p><strong>Provider:</strong> {embeddingHealth.provider}</p>
                  </div>
                  <p className="text-sm text-amber-700 dark:text-amber-300">
                    Do you want to upload this file anyway?
                  </p>
                </div>
              </div>
              <div className="flex gap-2 ml-8">
                <button
                  onClick={handleCancelEmbeddingWarning}
                  className="px-3 py-1.5 text-sm bg-white dark:bg-dark-sidebar border border-amber-300 dark:border-amber-700
                    text-amber-800 dark:text-amber-200 rounded-lg hover:bg-amber-50 dark:hover:bg-amber-900/40 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleProceedWithoutEmbedding}
                  className="px-3 py-1.5 text-sm bg-amber-600 text-white rounded-lg
                    hover:bg-amber-700 transition-colors"
                >
                  Upload Anyway
                </button>
              </div>
            </div>
          )}

          {/* Duplicate Warning */}
          {uploadStatus === 'duplicate_warning' && duplicateInfo && (
            <div className="p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg space-y-3">
              <div className="flex items-start gap-3">
                <AlertTriangle size={20} className="text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
                <div className="space-y-2">
                  <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                    Duplicate File Detected
                  </p>
                  <p className="text-sm text-amber-700 dark:text-amber-300">
                    {duplicateInfo.match_type === 'both' && (
                      <>This file has the same name and content as an existing document.</>
                    )}
                    {duplicateInfo.match_type === 'content' && (
                      <>This file has the same content as an existing document (uploaded with a different name).</>
                    )}
                    {duplicateInfo.match_type === 'filename' && (
                      <>A document with this filename already exists.</>
                    )}
                  </p>
                  {duplicateInfo.duplicate_document && (
                    <div className="text-xs text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/40 rounded p-2">
                      <p><strong>Existing document:</strong> {duplicateInfo.duplicate_document.title}</p>
                      <p><strong>Original filename:</strong> {duplicateInfo.duplicate_document.original_filename}</p>
                      <p><strong>Uploaded:</strong> {new Date(duplicateInfo.duplicate_document.created_at).toLocaleString()}</p>
                    </div>
                  )}
                  <p className="text-sm text-amber-700 dark:text-amber-300">
                    Do you want to upload this file anyway?
                  </p>
                </div>
              </div>
              <div className="flex gap-2 ml-8">
                <button
                  onClick={handleCancelDuplicate}
                  className="px-3 py-1.5 text-sm bg-white dark:bg-dark-sidebar border border-amber-300 dark:border-amber-700
                    text-amber-800 dark:text-amber-200 rounded-lg hover:bg-amber-50 dark:hover:bg-amber-900/40 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleProceedAnyway}
                  className="px-3 py-1.5 text-sm bg-amber-600 text-white rounded-lg
                    hover:bg-amber-700 transition-colors"
                >
                  Upload Anyway
                </button>
              </div>
            </div>
          )}

          {/* Progress Bar */}
          {uploadStatus === 'uploading' && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Loader2 size={16} className="animate-spin text-primary" />
                <span className="text-sm text-light-text dark:text-dark-text">
                  Uploading... {uploadProgress}%
                </span>
              </div>
              <div className="w-full bg-light-border dark:bg-dark-border rounded-full h-2">
                <div
                  className="bg-primary h-2 rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          )}

          {/* Success Message */}
          {uploadStatus === 'success' && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                <CheckCircle size={16} />
                <span className="text-sm">Document uploaded successfully!</span>
              </div>
              {/* Embedding Warning after upload */}
              {embeddingWarningMsg && (
                <div className="flex items-start gap-2 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
                  <AlertTriangle size={16} className="text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
                  <span className="text-sm text-amber-700 dark:text-amber-300">{embeddingWarningMsg}</span>
                </div>
              )}
            </div>
          )}

          {/* Error Message */}
          {errorMessage && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
                <AlertCircle size={16} />
                <span className="text-sm">{errorMessage}</span>
              </div>
              {/* Retry Button for Network Errors */}
              {isNetworkError && uploadStatus === 'error' && (
                <button
                  onClick={handleUpload}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-white rounded-lg
                    hover:bg-primary-hover transition-colors"
                >
                  <RefreshCw size={14} />
                  Retry Upload
                </button>
              )}
            </div>
          )}
        </div>

        {/* Footer - Hide when showing warnings (actions are in the warning) */}
        {uploadStatus !== 'duplicate_warning' && uploadStatus !== 'embedding_warning' && (
          <div className="flex justify-end gap-3 p-4 border-t border-light-border dark:border-dark-border">
            <button
              onClick={handleClose}
              className="px-4 py-2 text-sm text-light-text-secondary dark:text-dark-text-secondary
                hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleUpload}
              disabled={!selectedFile || !title.trim() || uploadStatus === 'uploading' || uploadStatus === 'checking'}
              className="px-4 py-2 text-sm bg-primary text-white rounded-lg
                hover:bg-primary-hover transition-colors
                disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {uploadStatus === 'uploading' ? 'Uploading...' : uploadStatus === 'checking' ? 'Checking...' : 'Upload'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default UploadModal
