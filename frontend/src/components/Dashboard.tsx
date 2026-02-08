/**
 * Dashboard - System metrics overview (Feature #355)
 * Displays key system metrics in a card-based layout with auto-refresh.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BarChart3,
  FileText,
  Layers,
  MessageSquare,
  Database,
  Cpu,
  Brain,
  Shield,
  ThumbsUp,
  RefreshCw,
  Loader2,
  AlertCircle,
  ArrowLeft,
  HardDrive,
  Zap
} from 'lucide-react'

interface DashboardData {
  documents: { total: number; unstructured: number; structured: number; with_embeddings: number }
  chunks: { total: number; bm25_indexed: number }
  conversations: { total: number; messages: number }
  storage: { db_size: string; db_size_bytes: number }
  models: { llm: string; embedding: string; chunking: string }
  feedback: { total: number; positive: number; negative: number; positive_rate: number }
  system: { memory_mb: number; memory_percent: number; disk_percent: number }
  embedding_coverage: { total_unstructured: number; with_embeddings: number; percent: number }
  cache?: { total_entries: number; total_hits: number; avg_hits: number; oldest_entry: string | null; expired_entries: number }
}

const AUTO_REFRESH_INTERVAL = 30000 // 30 seconds

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const navigate = useNavigate()

  const fetchDashboard = useCallback(async (showSpinner = true) => {
    if (showSpinner) setIsLoading(true)
    else setIsRefreshing(true)
    setError(null)

    try {
      const response = await fetch('/api/admin/maintenance/dashboard')
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const result: DashboardData = await response.json()
      setData(result)
      setLastRefresh(new Date())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [])

  // Initial load
  useEffect(() => {
    fetchDashboard()
  }, [fetchDashboard])

  // Auto-refresh
  useEffect(() => {
    intervalRef.current = setInterval(() => {
      fetchDashboard(false)
    }, AUTO_REFRESH_INTERVAL)

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [fetchDashboard])

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center bg-light-bg dark:bg-dark-bg">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin text-primary mx-auto mb-3" />
          <p className="text-light-text-secondary dark:text-dark-text-secondary">Loading dashboard...</p>
        </div>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="h-full flex items-center justify-center bg-light-bg dark:bg-dark-bg">
        <div className="text-center max-w-md">
          <AlertCircle className="w-10 h-10 text-red-500 mx-auto mb-3" />
          <p className="text-red-600 dark:text-red-400 mb-4">{error}</p>
          <button
            onClick={() => fetchDashboard()}
            className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="h-full overflow-y-auto bg-light-bg dark:bg-dark-bg">
      <div className="max-w-6xl mx-auto p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/')}
              className="p-2 rounded-lg hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors"
              title="Back to Chat"
            >
              <ArrowLeft size={20} className="text-light-text-secondary dark:text-dark-text-secondary" />
            </button>
            <BarChart3 size={28} className="text-indigo-500" />
            <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">System Dashboard</h1>
          </div>
          <div className="flex items-center gap-3">
            {lastRefresh && (
              <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary hidden sm:inline">
                Updated {lastRefresh.toLocaleTimeString()}
              </span>
            )}
            <div className="flex items-center gap-1.5 text-xs text-light-text-secondary dark:text-dark-text-secondary">
              <div className={`w-2 h-2 rounded-full ${isRefreshing ? 'bg-yellow-400 animate-pulse' : 'bg-green-400'}`} />
              <span className="hidden sm:inline">Auto-refresh 30s</span>
            </div>
            <button
              onClick={() => fetchDashboard(false)}
              disabled={isRefreshing}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-light-border dark:border-dark-border text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors disabled:opacity-50"
            >
              <RefreshCw size={14} className={isRefreshing ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>
        </div>

        {/* Error banner (non-blocking) */}
        {error && data && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg flex items-center gap-2 text-red-600 dark:text-red-400 text-sm">
            <AlertCircle size={16} />
            <span>Refresh failed: {error}</span>
          </div>
        )}

        {/* Top Row - Key Counts */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          <MetricCard
            icon={FileText}
            iconColor="text-blue-500"
            label="Documents"
            value={data.documents.total}
            detail={`${data.documents.unstructured} text / ${data.documents.structured} tabular`}
          />
          <MetricCard
            icon={Layers}
            iconColor="text-purple-500"
            label="Total Chunks"
            value={data.chunks.total.toLocaleString()}
            detail={`${data.chunks.bm25_indexed.toLocaleString()} BM25 indexed`}
          />
          <MetricCard
            icon={MessageSquare}
            iconColor="text-green-500"
            label="Conversations"
            value={data.conversations.total}
            detail={`${data.conversations.messages.toLocaleString()} messages`}
          />
          <MetricCard
            icon={Database}
            iconColor="text-cyan-500"
            label="Database Size"
            value={data.storage.db_size}
          />
        </div>

        {/* Middle Row - Models & Coverage */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <ModelCard label="Active LLM" model={data.models.llm} icon={Brain} iconColor="text-orange-500" />
          <ModelCard label="Embedding Model" model={data.models.embedding} icon={Cpu} iconColor="text-teal-500" />
          <div className="bg-white dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border p-5">
            <div className="flex items-center gap-2 mb-3">
              <Shield size={18} className="text-emerald-500" />
              <span className="text-sm font-medium text-light-text-secondary dark:text-dark-text-secondary">Embedding Coverage</span>
            </div>
            <div className="text-2xl font-bold text-light-text dark:text-dark-text mb-2">
              {data.embedding_coverage.percent}%
            </div>
            <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5 mb-2">
              <div
                className="h-2.5 rounded-full transition-all duration-500 bg-emerald-500"
                style={{ width: `${Math.min(data.embedding_coverage.percent, 100)}%` }}
              />
            </div>
            <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
              {data.embedding_coverage.with_embeddings} / {data.embedding_coverage.total_unstructured} unstructured docs
            </p>
          </div>
        </div>

        {/* Bottom Row - Feedback, Cache & System */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Feedback Card */}
          <div className="bg-white dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border p-5">
            <div className="flex items-center gap-2 mb-3">
              <ThumbsUp size={18} className="text-yellow-500" />
              <span className="text-sm font-medium text-light-text-secondary dark:text-dark-text-secondary">Response Feedback</span>
            </div>
            {data.feedback.total > 0 ? (
              <>
                <div className="flex items-baseline gap-2 mb-2">
                  <span className="text-2xl font-bold text-light-text dark:text-dark-text">
                    {data.feedback.positive_rate}%
                  </span>
                  <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">positive</span>
                </div>
                <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5 mb-3">
                  <div
                    className="h-2.5 rounded-full transition-all duration-500 bg-green-500"
                    style={{ width: `${Math.min(data.feedback.positive_rate, 100)}%` }}
                  />
                </div>
                <div className="flex items-center gap-4 text-sm">
                  <span className="text-green-600 dark:text-green-400">{data.feedback.positive} positive</span>
                  <span className="text-red-600 dark:text-red-400">{data.feedback.negative} negative</span>
                  <span className="text-light-text-secondary dark:text-dark-text-secondary">{data.feedback.total} total</span>
                </div>
              </>
            ) : (
              <p className="text-light-text-secondary dark:text-dark-text-secondary text-sm">No feedback collected yet</p>
            )}
          </div>

          {/* Response Cache Card (Feature #352) */}
          <div className="bg-white dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border p-5">
            <div className="flex items-center gap-2 mb-3">
              <Zap size={18} className="text-green-500" />
              <span className="text-sm font-medium text-light-text-secondary dark:text-dark-text-secondary">Response Cache</span>
            </div>
            {data.cache && data.cache.total_entries > 0 ? (
              <>
                <div className="flex items-baseline gap-2 mb-3">
                  <span className="text-2xl font-bold text-light-text dark:text-dark-text">
                    {data.cache.total_entries}
                  </span>
                  <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">entries</span>
                </div>
                <div className="flex items-center gap-4 text-sm">
                  <span className="text-green-600 dark:text-green-400">{data.cache.total_hits} hits</span>
                  <span className="text-light-text-secondary dark:text-dark-text-secondary">{data.cache.avg_hits} avg/entry</span>
                </div>
              </>
            ) : (
              <p className="text-light-text-secondary dark:text-dark-text-secondary text-sm">No cached responses yet</p>
            )}
          </div>

          {/* System Resources Card */}
          <div className="bg-white dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border p-5">
            <div className="flex items-center gap-2 mb-4">
              <HardDrive size={18} className="text-rose-500" />
              <span className="text-sm font-medium text-light-text-secondary dark:text-dark-text-secondary">System Resources</span>
            </div>
            <div className="space-y-4">
              <ResourceBar
                label="Process Memory"
                value={data.system.memory_mb}
                unit="MB"
                percent={data.system.memory_percent}
              />
              <ResourceBar
                label="Disk Usage"
                percent={data.system.disk_percent}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function MetricCard({
  icon: Icon,
  iconColor,
  label,
  value,
  detail
}: {
  icon: React.ElementType
  iconColor: string
  label: string
  value: string | number
  detail?: string
}) {
  return (
    <div className="bg-white dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border p-5">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={18} className={iconColor} />
        <span className="text-sm font-medium text-light-text-secondary dark:text-dark-text-secondary">{label}</span>
      </div>
      <div className="text-2xl font-bold text-light-text dark:text-dark-text">{value}</div>
      {detail && (
        <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-1">{detail}</p>
      )}
    </div>
  )
}

function ModelCard({
  label,
  model,
  icon: Icon,
  iconColor
}: {
  label: string
  model: string
  icon: React.ElementType
  iconColor: string
}) {
  return (
    <div className="bg-white dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border p-5">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={18} className={iconColor} />
        <span className="text-sm font-medium text-light-text-secondary dark:text-dark-text-secondary">{label}</span>
      </div>
      <div className="text-lg font-bold text-light-text dark:text-dark-text truncate" title={model}>
        {model || 'Not configured'}
      </div>
    </div>
  )
}

function ResourceBar({
  label,
  value,
  unit,
  percent
}: {
  label: string
  value?: number
  unit?: string
  percent: number
}) {
  const barColor = percent > 90 ? 'bg-red-500' : percent > 70 ? 'bg-yellow-500' : 'bg-blue-500'

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm text-light-text dark:text-dark-text">{label}</span>
        <span className="text-sm font-medium text-light-text dark:text-dark-text">
          {value !== undefined ? `${value} ${unit}` : ''} ({percent}%)
        </span>
      </div>
      <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </div>
    </div>
  )
}

export default Dashboard
