/**
 * TelegramWebhookStatus - Component to display and manage Telegram webhook registration
 *
 * Feature #313: Telegram webhook registration endpoint
 *
 * Shows the current webhook status with Telegram and provides buttons to
 * register/unregister the webhook.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Globe,
  AlertCircle,
  Loader2,
  RefreshCw,
  Link,
  Unlink,
  CheckCircle2,
  XCircle,
  Clock,
  Copy,
  Check
} from 'lucide-react'
import {
  getWebhookInfo,
  registerWebhook,
  unregisterWebhook,
  WebhookInfoResponse
} from '../api/telegram'

interface TelegramWebhookStatusProps {
  /** Auto-refresh interval in milliseconds (0 to disable) */
  autoRefreshInterval?: number
  /** Whether the bot token is configured */
  isBotTokenConfigured: boolean
}

export function TelegramWebhookStatus({
  autoRefreshInterval = 60000,
  isBotTokenConfigured
}: TelegramWebhookStatusProps) {
  const [webhookInfo, setWebhookInfo] = useState<WebhookInfoResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isRegistering, setIsRegistering] = useState(false)
  const [isUnregistering, setIsUnregistering] = useState(false)
  const [actionResult, setActionResult] = useState<{ success: boolean; message: string } | null>(null)
  const [copied, setCopied] = useState(false)

  const fetchInfo = useCallback(async () => {
    if (!isBotTokenConfigured) {
      setLoading(false)
      setWebhookInfo(null)
      return
    }

    try {
      setError(null)
      const result = await getWebhookInfo()
      setWebhookInfo(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch webhook status')
    } finally {
      setLoading(false)
    }
  }, [isBotTokenConfigured])

  useEffect(() => {
    fetchInfo()

    // Set up auto-refresh if interval > 0 and token is configured
    if (autoRefreshInterval > 0 && isBotTokenConfigured) {
      const interval = setInterval(fetchInfo, autoRefreshInterval)
      return () => clearInterval(interval)
    }
  }, [fetchInfo, autoRefreshInterval, isBotTokenConfigured])

  // Clear action result after 5 seconds
  useEffect(() => {
    if (actionResult) {
      const timer = setTimeout(() => setActionResult(null), 5000)
      return () => clearTimeout(timer)
    }
  }, [actionResult])

  const handleRegister = async () => {
    setIsRegistering(true)
    setActionResult(null)
    try {
      const result = await registerWebhook()
      setActionResult({ success: result.success, message: result.message + (result.description ? ` - ${result.description}` : '') })
      if (result.success) {
        await fetchInfo()
      }
    } catch (err) {
      setActionResult({ success: false, message: err instanceof Error ? err.message : 'Failed to register webhook' })
    } finally {
      setIsRegistering(false)
    }
  }

  const handleUnregister = async () => {
    setIsUnregistering(true)
    setActionResult(null)
    try {
      const result = await unregisterWebhook()
      setActionResult({ success: result.success, message: result.message + (result.description ? ` - ${result.description}` : '') })
      if (result.success) {
        await fetchInfo()
      }
    } catch (err) {
      setActionResult({ success: false, message: err instanceof Error ? err.message : 'Failed to unregister webhook' })
    } finally {
      setIsUnregistering(false)
    }
  }

  const handleRefresh = () => {
    setLoading(true)
    fetchInfo()
  }

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy to clipboard:', err)
    }
  }

  // If bot token is not configured
  if (!isBotTokenConfigured) {
    return (
      <div className="mt-4 pt-4 border-t border-light-border dark:border-dark-border">
        <div className="p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
          <p className="text-sm text-amber-700 dark:text-amber-400">
            Configure your bot token above to manage webhook registration.
          </p>
        </div>
      </div>
    )
  }

  if (loading && !webhookInfo) {
    return (
      <div className="mt-4 pt-4 border-t border-light-border dark:border-dark-border">
        <div className="flex items-center gap-2 p-3 rounded-lg bg-light-sidebar dark:bg-dark-sidebar border border-light-border dark:border-dark-border">
          <Loader2 size={16} className="animate-spin text-light-text-secondary dark:text-dark-text-secondary" />
          <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
            Checking webhook status...
          </span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-4 pt-4 border-t border-light-border dark:border-dark-border">
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
      </div>
    )
  }

  const isRegistered = webhookInfo?.registered || false

  return (
    <div className="mt-4 pt-4 border-t border-light-border dark:border-dark-border space-y-3">
      {/* Status Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Globe size={16} className={isRegistered ? 'text-green-500' : 'text-gray-400'} />
          <span className="text-sm font-medium text-light-text dark:text-dark-text">
            Webhook Status
          </span>
          {isRegistered ? (
            <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400 font-medium">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
              Registered
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400 font-medium">
              <span className="w-2 h-2 rounded-full bg-gray-400"></span>
              Not Registered
            </span>
          )}
        </div>
        <button
          onClick={handleRefresh}
          disabled={loading}
          className="p-1.5 rounded-lg hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50"
          title="Refresh webhook status"
        >
          <RefreshCw size={14} className={`text-light-text-secondary dark:text-dark-text-secondary ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Webhook URL Display (if registered) */}
      {isRegistered && webhookInfo?.url && (
        <div className="flex items-center gap-2">
          <div className="flex-1 relative">
            <input
              type="text"
              readOnly
              value={webhookInfo.url}
              className="w-full px-3 py-2 pr-10 border border-light-border dark:border-dark-border rounded-lg bg-light-sidebar dark:bg-dark-sidebar text-light-text dark:text-dark-text font-mono text-xs cursor-text"
            />
            <button
              onClick={() => handleCopy(webhookInfo.url!)}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-light-border dark:hover:bg-dark-border transition-colors"
              title="Copy webhook URL"
            >
              {copied ? (
                <Check size={14} className="text-green-500" />
              ) : (
                <Copy size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
              )}
            </button>
          </div>
        </div>
      )}

      {/* Status Details (if registered) */}
      {isRegistered && webhookInfo && (
        <div className="text-xs text-light-text-secondary dark:text-dark-text-secondary space-y-1">
          {webhookInfo.pending_update_count > 0 && (
            <div className="flex items-center gap-1">
              <Clock size={12} />
              <span>{webhookInfo.pending_update_count} pending updates</span>
            </div>
          )}
          {webhookInfo.last_error_message && (
            <div className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
              <AlertCircle size={12} />
              <span>Last error: {webhookInfo.last_error_message}</span>
            </div>
          )}
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex items-center gap-2 flex-wrap">
        {!isRegistered ? (
          <button
            onClick={handleRegister}
            disabled={isRegistering}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRegistering ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Link size={14} />
            )}
            Register Webhook
          </button>
        ) : (
          <button
            onClick={handleUnregister}
            disabled={isUnregistering}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isUnregistering ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Unlink size={14} />
            )}
            Unregister Webhook
          </button>
        )}
      </div>

      {/* Action Result */}
      {actionResult && (
        <div className={`flex items-center gap-2 text-sm ${actionResult.success ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
          {actionResult.success ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
          <span>{actionResult.message}</span>
        </div>
      )}

      {/* Help Text */}
      <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
        {isRegistered
          ? "Your bot is receiving updates. Unregister to stop receiving messages."
          : "Register webhook to start receiving Telegram messages. Requires ngrok or a public URL."}
      </p>
    </div>
  )
}

export default TelegramWebhookStatus
