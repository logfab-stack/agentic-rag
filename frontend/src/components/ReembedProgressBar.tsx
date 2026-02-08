/**
 * ReembedProgressBar Component
 *
 * Feature #189: Real-time progress bar for re-embed operations.
 *
 * Displays:
 * - Visual progress bar with smooth animation
 * - Percentage complete
 * - Documents processed / total
 * - Currently processing document name
 * - Elapsed time
 * - Estimated time remaining (ETA)
 * - Chunks generated count
 *
 * Color states:
 * - Blue: In progress
 * - Green: Completed successfully
 * - Red: Failed or has errors
 */

import { type ReembedProgress } from '../api/admin-maintenance'
import { Clock, FileText, Layers, AlertCircle, CheckCircle } from 'lucide-react'

interface ReembedProgressBarProps {
  progress: ReembedProgress
}

export function ReembedProgressBar({ progress }: ReembedProgressBarProps) {
  // Determine the color scheme based on status
  const getColorScheme = () => {
    if (progress.status === 'failed') {
      return {
        bar: 'bg-red-500',
        text: 'text-red-600 dark:text-red-400',
        bg: 'bg-red-100 dark:bg-red-900/30',
        border: 'border-red-200 dark:border-red-800'
      }
    }
    if (progress.status === 'completed') {
      if (progress.failed > 0) {
        // Completed with some failures
        return {
          bar: 'bg-amber-500',
          text: 'text-amber-600 dark:text-amber-400',
          bg: 'bg-amber-100 dark:bg-amber-900/30',
          border: 'border-amber-200 dark:border-amber-800'
        }
      }
      // Fully successful
      return {
        bar: 'bg-green-500',
        text: 'text-green-600 dark:text-green-400',
        bg: 'bg-green-100 dark:bg-green-900/30',
        border: 'border-green-200 dark:border-green-800'
      }
    }
    // In progress
    return {
      bar: 'bg-blue-500',
      text: 'text-blue-600 dark:text-blue-400',
      bg: 'bg-blue-100 dark:bg-blue-900/30',
      border: 'border-blue-200 dark:border-blue-800'
    }
  }

  const colors = getColorScheme()

  return (
    <div className={`rounded-lg p-4 ${colors.bg} border ${colors.border}`}>
      {/* Progress bar container */}
      <div className="mb-4">
        {/* Progress percentage header */}
        <div className="flex justify-between items-center mb-2">
          <span className={`text-sm font-medium ${colors.text}`}>
            {progress.status === 'completed' ? (
              progress.failed > 0 ? 'Completed with errors' : 'Completed!'
            ) : progress.status === 'failed' ? (
              'Failed'
            ) : (
              'Re-embedding in progress...'
            )}
          </span>
          <span className={`text-lg font-bold ${colors.text}`}>
            {progress.percentage}%
          </span>
        </div>

        {/* Progress bar */}
        <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full ${colors.bar} transition-all duration-500 ease-out rounded-full`}
            style={{ width: `${Math.min(progress.percentage, 100)}%` }}
          />
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        {/* Documents processed */}
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-light-text-secondary dark:text-dark-text-secondary" />
          <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
            Documents:
          </span>
          <span className="text-sm font-medium text-light-text dark:text-dark-text">
            {progress.processed} / {progress.total_documents}
          </span>
        </div>

        {/* Chunks generated */}
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-light-text-secondary dark:text-dark-text-secondary" />
          <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
            Chunks:
          </span>
          <span className="text-sm font-medium text-light-text dark:text-dark-text">
            {progress.chunks_generated.toLocaleString()}
          </span>
        </div>

        {/* Elapsed time */}
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-light-text-secondary dark:text-dark-text-secondary" />
          <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
            Elapsed:
          </span>
          <span className="text-sm font-medium text-light-text dark:text-dark-text">
            {progress.elapsed_pretty}
          </span>
        </div>

        {/* ETA */}
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-light-text-secondary dark:text-dark-text-secondary" />
          <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
            ETA:
          </span>
          <span className="text-sm font-medium text-light-text dark:text-dark-text">
            {progress.eta_pretty || (progress.status === 'completed' ? '-' : 'Calculating...')}
          </span>
        </div>
      </div>

      {/* Success/Failure counts */}
      <div className="flex items-center gap-4 mb-3">
        <div className="flex items-center gap-1">
          <CheckCircle className="w-4 h-4 text-green-500" />
          <span className="text-sm text-green-600 dark:text-green-400 font-medium">
            {progress.successful} successful
          </span>
        </div>
        {progress.failed > 0 && (
          <div className="flex items-center gap-1">
            <AlertCircle className="w-4 h-4 text-red-500" />
            <span className="text-sm text-red-600 dark:text-red-400 font-medium">
              {progress.failed} failed
            </span>
          </div>
        )}
      </div>

      {/* Current document being processed */}
      {progress.status === 'in_progress' && progress.current_document_name && (
        <div className="pt-3 border-t border-gray-200 dark:border-gray-600">
          <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
            Currently processing:
          </p>
          <p className="text-sm text-light-text dark:text-dark-text font-medium truncate" title={progress.current_document_name}>
            {progress.current_document_name}
          </p>
        </div>
      )}

      {/* Error message */}
      {progress.error_message && (
        <div className="pt-3 border-t border-red-200 dark:border-red-800 mt-3">
          <p className="text-xs text-red-600 dark:text-red-400">
            Error: {progress.error_message}
          </p>
        </div>
      )}
    </div>
  )
}
