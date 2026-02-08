import { useState } from 'react'
import { Download, X, FileText, FileCode } from 'lucide-react'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { exportConversation } from '../api'

interface ExportModalProps {
  isOpen: boolean
  onClose: () => void
  conversationId: string
  conversationTitle?: string
  onShowToast?: (message: string, type: 'success' | 'error') => void
}

export function ExportModal({
  isOpen,
  onClose,
  conversationId,
  conversationTitle,
  onShowToast
}: ExportModalProps) {
  const [isExporting, setIsExporting] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState<'markdown' | 'json'>('markdown')

  // Focus trap for accessibility
  const focusTrapRef = useFocusTrap(isOpen)

  if (!isOpen) return null

  const handleExport = async () => {
    setIsExporting(true)
    try {
      await exportConversation(conversationId, selectedFormat)
      onShowToast?.(`Conversation exported as ${selectedFormat === 'markdown' ? 'Markdown' : 'JSON'}`, 'success')
      onClose()
    } catch (error) {
      console.error('Export failed:', error)
      onShowToast?.('Failed to export conversation', 'error')
    } finally {
      setIsExporting(false)
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
        aria-labelledby="export-modal-title"
        className="relative bg-white dark:bg-dark-bg rounded-lg shadow-xl w-full max-w-md mx-4 p-6"
      >
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text rounded transition-colors"
          disabled={isExporting}
          aria-label="Close"
        >
          <X size={20} />
        </button>

        {/* Icon */}
        <div className="flex items-center justify-center mb-4">
          <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
            <Download className="text-primary" size={24} />
          </div>
        </div>

        {/* Title */}
        <h2 id="export-modal-title" className="text-lg font-semibold text-light-text dark:text-dark-text text-center mb-2">
          Export Conversation
        </h2>

        {/* Conversation Name */}
        {conversationTitle && (
          <p className="text-light-text dark:text-dark-text font-medium text-center mb-4 px-4 py-2 bg-light-sidebar dark:bg-dark-sidebar rounded truncate">
            "{conversationTitle}"
          </p>
        )}

        {/* Format Selection */}
        <div className="mb-6">
          <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mb-3 text-center">
            Choose export format:
          </p>

          <div className="grid grid-cols-2 gap-3">
            {/* Markdown Option */}
            <button
              onClick={() => setSelectedFormat('markdown')}
              className={`p-4 rounded-lg border-2 transition-all ${
                selectedFormat === 'markdown'
                  ? 'border-primary bg-primary/10'
                  : 'border-light-border dark:border-dark-border hover:border-primary/50'
              }`}
            >
              <FileText
                size={32}
                className={`mx-auto mb-2 ${
                  selectedFormat === 'markdown' ? 'text-primary' : 'text-light-text-secondary dark:text-dark-text-secondary'
                }`}
              />
              <p className={`font-medium ${
                selectedFormat === 'markdown' ? 'text-primary' : 'text-light-text dark:text-dark-text'
              }`}>
                Markdown
              </p>
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                .md file
              </p>
            </button>

            {/* JSON Option */}
            <button
              onClick={() => setSelectedFormat('json')}
              className={`p-4 rounded-lg border-2 transition-all ${
                selectedFormat === 'json'
                  ? 'border-primary bg-primary/10'
                  : 'border-light-border dark:border-dark-border hover:border-primary/50'
              }`}
            >
              <FileCode
                size={32}
                className={`mx-auto mb-2 ${
                  selectedFormat === 'json' ? 'text-primary' : 'text-light-text-secondary dark:text-dark-text-secondary'
                }`}
              />
              <p className={`font-medium ${
                selectedFormat === 'json' ? 'text-primary' : 'text-light-text dark:text-dark-text'
              }`}>
                JSON
              </p>
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">
                .json file
              </p>
            </button>
          </div>
        </div>

        {/* Format Description */}
        <div className="text-xs text-light-text-secondary dark:text-dark-text-secondary mb-6 p-3 bg-light-sidebar dark:bg-dark-sidebar rounded">
          {selectedFormat === 'markdown' ? (
            <p>Exports as readable Markdown with title, messages, and sources as footnotes. Great for sharing or printing.</p>
          ) : (
            <p>Exports complete conversation data including all metadata and tool details. Ideal for backup or programmatic use.</p>
          )}
        </div>

        {/* Buttons */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            disabled={isExporting}
            className="flex-1 py-2 px-4 border border-light-border dark:border-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleExport}
            disabled={isExporting}
            className="flex-1 py-2 px-4 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors disabled:opacity-50 flex items-center justify-center"
          >
            {isExporting ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Exporting...
              </>
            ) : (
              <>
                <Download size={16} className="mr-2" />
                Export
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ExportModal
