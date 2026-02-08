import { AlertTriangle, X } from 'lucide-react'
import { useFocusTrap } from '../hooks/useFocusTrap'

interface ConfirmDeleteModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  message: string
  itemName?: string
  isDeleting?: boolean
}

export function ConfirmDeleteModal({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  itemName,
  isDeleting = false
}: ConfirmDeleteModalProps) {
  // Focus trap for accessibility - keeps focus within modal
  const focusTrapRef = useFocusTrap(isOpen)

  if (!isOpen) return null

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
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-delete-modal-title"
        aria-describedby="confirm-delete-modal-description"
        className="relative bg-white dark:bg-dark-bg rounded-lg shadow-xl w-full max-w-md mx-4 p-6"
      >
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text rounded transition-colors"
          disabled={isDeleting}
        >
          <X size={20} />
        </button>

        {/* Warning Icon */}
        <div className="flex items-center justify-center mb-4">
          <div className="w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/20 flex items-center justify-center">
            <AlertTriangle className="text-red-500" size={24} />
          </div>
        </div>

        {/* Title */}
        <h2 id="confirm-delete-modal-title" className="text-lg font-semibold text-light-text dark:text-dark-text text-center mb-2">
          {title}
        </h2>

        {/* Message */}
        <p id="confirm-delete-modal-description" className="text-light-text-secondary dark:text-dark-text-secondary text-center mb-2">
          {message}
        </p>

        {/* Item Name */}
        {itemName && (
          <p className="text-light-text dark:text-dark-text font-medium text-center mb-6 px-4 py-2 bg-light-sidebar dark:bg-dark-sidebar rounded truncate">
            "{itemName}"
          </p>
        )}

        {/* Buttons */}
        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            disabled={isDeleting}
            className="flex-1 py-2 px-4 border border-light-border dark:border-dark-border text-light-text dark:text-dark-text rounded-lg hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isDeleting}
            className="flex-1 py-2 px-4 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors disabled:opacity-50 flex items-center justify-center"
          >
            {isDeleting ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Deleting...
              </>
            ) : (
              'Delete'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ConfirmDeleteModal
