/**
 * NgrokStatus - Component to display ngrok tunnel status and webhook URL
 *
 * Shows whether ngrok is running and provides the webhook URL for WhatsApp/Twilio.
 * Includes a copy button for easy clipboard copying.
 */

import { useState, useEffect, useCallback } from 'react'
import { Copy, Check, RefreshCw, Globe, AlertCircle, Loader2 } from 'lucide-react'
import { fetchNgrokStatus, NgrokStatusResponse } from '../api/ngrok'

interface NgrokStatusProps {
  /** Auto-refresh interval in milliseconds (0 to disable) */
  autoRefreshInterval?: number
}

export function NgrokStatus({ autoRefreshInterval = 30000 }: NgrokStatusProps) {
  const [status, setStatus] = useState<NgrokStatusResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const fetchStatus = useCallback(async () => {
    try {
      setError(null)
      const result = await fetchNgrokStatus()
      setStatus(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch ngrok status')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchStatus()

    // Set up auto-refresh if interval > 0
    if (autoRefreshInterval > 0) {
      const interval = setInterval(fetchStatus, autoRefreshInterval)
      return () => clearInterval(interval)
    }
  }, [fetchStatus, autoRefreshInterval])

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy to clipboard:', err)
    }
  }

  const handleRefresh = () => {
    setLoading(true)
    fetchStatus()
  }

  if (loading && !status) {
    return (
      <div className="flex items-center gap-2 p-3 rounded-lg bg-light-sidebar dark:bg-dark-sidebar border border-light-border dark:border-dark-border">
        <Loader2 size={16} className="animate-spin text-light-text-secondary dark:text-dark-text-secondary" />
        <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
          Checking ngrok status...
        </span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
        <AlertCircle size={16} className="text-red-600 dark:text-red-400" />
        <span className="text-sm text-red-600 dark:text-red-400">{error}</span>
        <button
          onClick={handleRefresh}
          className="ml-auto p-1 hover:bg-red-100 dark:hover:bg-red-800/30 rounded"
        >
          <RefreshCw size={14} className="text-red-600 dark:text-red-400" />
        </button>
      </div>
    )
  }

  const isRunning = status?.running || false
  const webhookUrl = status?.webhook_url

  return (
    <div className="space-y-3">
      {/* Status Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Globe size={16} className={isRunning ? 'text-green-500' : 'text-gray-400'} />
          <span className="text-sm font-medium text-light-text dark:text-dark-text">
            Webhook URL (ngrok)
          </span>
          {isRunning ? (
            <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400 font-medium">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
              Running
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-red-600 dark:text-red-400 font-medium">
              <span className="w-2 h-2 rounded-full bg-red-500"></span>
              Not Running
            </span>
          )}
        </div>
        <button
          onClick={handleRefresh}
          disabled={loading}
          className="p-1.5 rounded-lg hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50"
          title="Refresh ngrok status"
        >
          <RefreshCw size={14} className={`text-light-text-secondary dark:text-dark-text-secondary ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Webhook URL Display */}
      {isRunning && webhookUrl ? (
        <div className="flex items-center gap-2">
          <div className="flex-1 relative">
            <input
              type="text"
              readOnly
              value={webhookUrl}
              className="w-full px-3 py-2 pr-10 border border-light-border dark:border-dark-border rounded-lg bg-light-sidebar dark:bg-dark-sidebar text-light-text dark:text-dark-text font-mono text-sm cursor-text"
            />
            <button
              onClick={() => handleCopy(webhookUrl)}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-light-border dark:hover:bg-dark-border transition-colors"
              title="Copy webhook URL"
            >
              {copied ? (
                <Check size={16} className="text-green-500" />
              ) : (
                <Copy size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
              )}
            </button>
          </div>
        </div>
      ) : (
        <div className="p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
          <p className="text-sm text-amber-700 dark:text-amber-400">
            {status?.error || 'ngrok is not running. Start it with: ngrok http 8000'}
          </p>
        </div>
      )}

      {/* Help Text */}
      <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
        Copy this URL to your Twilio WhatsApp Sandbox settings as the webhook endpoint.
        {!isRunning && (
          <span className="block mt-1 text-amber-600 dark:text-amber-400">
            Start ngrok to expose your local server to the internet.
          </span>
        )}
      </p>
    </div>
  )
}

export default NgrokStatus
