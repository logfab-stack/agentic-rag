/**
 * Admin Maintenance Page
 *
 * Provides UI for database maintenance operations:
 * - Vacuum & Analyze (PostgreSQL optimization)
 * - Cleanup orphan embeddings/chunks
 * - Health check with statistics
 * - Rebuild pgvector indexes
 * - Cleanup old conversations
 * - Manual backup
 * - Re-embed all documents (Feature #187)
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Database,
  Trash2,
  Activity,
  RefreshCw,
  MessageSquare,
  Download,
  CheckCircle,
  AlertCircle,
  Loader2,
  HardDrive,
  Table,
  Layers,
  Clock,
  Server,
  Zap,
  AlertTriangle,
  Info,
  RotateCcw,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Wrench,
  ChevronDown,
  ChevronUp
} from 'lucide-react'
import {
  fetchHealthCheck,
  runVacuumAnalyze,
  runCleanupOrphans,
  runRebuildIndexes,
  runCleanupConversations,
  downloadBackup,
  getReembedEstimate,
  runReembedAll,
  getReembedProgress,
  fetchDatabaseHealth,
  runDatabaseHealthFix,
  type HealthCheckResult,
  type OperationResult,
  type ReembedEstimate,
  type ReembedResult,
  type ReembedProgress,
  type DatabaseHealthReport,
  type DatabaseHealthFixResponse
} from '../api/admin-maintenance'
import { ReembedProgressBar } from './ReembedProgressBar'
import { useToast } from './Toast'
import { ConfirmDeleteModal } from './ConfirmDeleteModal'

export function AdminMaintenancePage() {
  const navigate = useNavigate()
  const { showToast } = useToast()

  // State
  const [healthData, setHealthData] = useState<HealthCheckResult | null>(null)
  const [isLoadingHealth, setIsLoadingHealth] = useState(true)
  const [operationInProgress, setOperationInProgress] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<OperationResult | null>(null)

  // Cleanup conversations modal state
  const [isCleanupModalOpen, setIsCleanupModalOpen] = useState(false)
  const [cleanupDays, setCleanupDays] = useState(30)

  // Re-embed modal state (Feature #187)
  const [isReembedModalOpen, setIsReembedModalOpen] = useState(false)
  const [reembedEstimate, setReembedEstimate] = useState<ReembedEstimate | null>(null)
  const [isLoadingEstimate, setIsLoadingEstimate] = useState(false)
  const [reembedResult, setReembedResult] = useState<ReembedResult | null>(null)
  // Feature #189: Real-time progress tracking
  const [reembedProgress, setReembedProgress] = useState<ReembedProgress | null>(null)
  const [isPollingProgress, setIsPollingProgress] = useState(false)

  // Confirmation modal state for destructive operations
  const [confirmOperation, setConfirmOperation] = useState<{
    isOpen: boolean
    title: string
    message: string
    operation: (() => Promise<void>) | null
  }>({
    isOpen: false,
    title: '',
    message: '',
    operation: null
  })

  // Feature #271: Database health check state
  const [dbHealthReport, setDbHealthReport] = useState<DatabaseHealthReport | null>(null)
  const [isLoadingDbHealth, setIsLoadingDbHealth] = useState(false)
  const [dbHealthError, setDbHealthError] = useState<string | null>(null)
  const [expandedIssues, setExpandedIssues] = useState<Set<string>>(new Set())
  const [isFixing, setIsFixing] = useState(false)
  const [fixResult, setFixResult] = useState<DatabaseHealthFixResponse | null>(null)

  // Load health data
  const loadHealthData = useCallback(async () => {
    setIsLoadingHealth(true)
    try {
      const data = await fetchHealthCheck()
      setHealthData(data)
    } catch (error) {
      console.error('Failed to load health data:', error)
      showToast('error', 'Failed to load health data')
    } finally {
      setIsLoadingHealth(false)
    }
  }, [showToast])

  // Load health data on mount
  useEffect(() => {
    loadHealthData()
  }, [loadHealthData])

  // Feature #189: Poll for re-embed progress during operation
  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval> | null = null

    if (isPollingProgress && operationInProgress === 'reembed') {
      // Start polling every 1.5 seconds
      intervalId = setInterval(async () => {
        try {
          const progress = await getReembedProgress()
          setReembedProgress(progress)

          // Stop polling when operation is complete or failed
          if (progress.status === 'completed' || progress.status === 'failed') {
            setIsPollingProgress(false)
          }
        } catch (error) {
          console.error('Failed to fetch re-embed progress:', error)
        }
      }, 1500)
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId)
      }
    }
  }, [isPollingProgress, operationInProgress])

  // Handle vacuum & analyze
  const handleVacuumAnalyze = async () => {
    setOperationInProgress('vacuum')
    setLastResult(null)
    try {
      const result = await runVacuumAnalyze()
      setLastResult(result)
      showToast(result.success ? 'success' : 'warning', result.message)
      await loadHealthData()
    } catch (error) {
      console.error('Vacuum & Analyze failed:', error)
      showToast('error', error instanceof Error ? error.message : 'Operation failed')
    } finally {
      setOperationInProgress(null)
    }
  }

  // Handle cleanup orphans
  const handleCleanupOrphans = async () => {
    setOperationInProgress('orphans')
    setLastResult(null)
    try {
      const result = await runCleanupOrphans()
      setLastResult(result)
      showToast(result.success ? 'success' : 'warning', result.message)
      await loadHealthData()
    } catch (error) {
      console.error('Cleanup orphans failed:', error)
      showToast('error', error instanceof Error ? error.message : 'Operation failed')
    } finally {
      setOperationInProgress(null)
    }
  }

  // Handle rebuild indexes
  const handleRebuildIndexes = async () => {
    setOperationInProgress('indexes')
    setLastResult(null)
    try {
      const result = await runRebuildIndexes()
      setLastResult(result)
      showToast(result.success ? 'success' : 'warning', result.message)
      await loadHealthData()
    } catch (error) {
      console.error('Rebuild indexes failed:', error)
      showToast('error', error instanceof Error ? error.message : 'Operation failed')
    } finally {
      setOperationInProgress(null)
    }
  }

  // Handle cleanup conversations
  const handleCleanupConversations = async () => {
    setIsCleanupModalOpen(false)
    setOperationInProgress('conversations')
    setLastResult(null)
    try {
      const result = await runCleanupConversations({ older_than_days: cleanupDays })
      setLastResult(result)
      showToast(result.success ? 'success' : 'warning', result.message)
      await loadHealthData()
    } catch (error) {
      console.error('Cleanup conversations failed:', error)
      showToast('error', error instanceof Error ? error.message : 'Operation failed')
    } finally {
      setOperationInProgress(null)
    }
  }

  // Handle manual backup
  const handleBackup = async () => {
    setOperationInProgress('backup')
    try {
      const blob = await downloadBackup()
      // Create download link
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `rag_backup_${new Date().toISOString().slice(0, 10)}.zip`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
      showToast('success', 'Backup downloaded successfully')
    } catch (error) {
      console.error('Backup failed:', error)
      showToast('error', error instanceof Error ? error.message : 'Backup failed')
    } finally {
      setOperationInProgress(null)
    }
  }

  // Handle opening re-embed modal (Feature #187)
  const handleOpenReembedModal = async () => {
    setIsReembedModalOpen(true)
    setIsLoadingEstimate(true)
    setReembedResult(null)
    try {
      const estimate = await getReembedEstimate()
      setReembedEstimate(estimate)
    } catch (error) {
      console.error('Failed to get re-embed estimate:', error)
      showToast('error', error instanceof Error ? error.message : 'Failed to get estimate')
    } finally {
      setIsLoadingEstimate(false)
    }
  }

  // Handle re-embed all documents (Feature #187 & #189)
  const handleReembedAll = async () => {
    setOperationInProgress('reembed')
    setReembedResult(null)
    setReembedProgress(null)
    // Feature #189: Start polling for progress
    setIsPollingProgress(true)
    try {
      const result = await runReembedAll()
      setReembedResult(result)
      // Stop polling since we have the final result
      setIsPollingProgress(false)
      if (result.success) {
        showToast('success', result.message)
      } else {
        showToast('warning', result.message)
      }
      await loadHealthData()
    } catch (error) {
      console.error('Re-embed failed:', error)
      setIsPollingProgress(false)
      showToast('error', error instanceof Error ? error.message : 'Re-embedding failed')
    } finally {
      setOperationInProgress(null)
    }
  }

  // Show confirmation for destructive operations
  const confirmDestructiveOperation = (
    title: string,
    message: string,
    operation: () => Promise<void>
  ) => {
    setConfirmOperation({
      isOpen: true,
      title,
      message,
      operation
    })
  }

  // Execute confirmed operation
  const executeConfirmedOperation = async () => {
    if (confirmOperation.operation) {
      setConfirmOperation({ isOpen: false, title: '', message: '', operation: null })
      await confirmOperation.operation()
    }
  }

  // Format number with commas
  const formatNumber = (num: number) => {
    return num.toLocaleString()
  }

  // Feature #271: Load database health report
  const loadDbHealth = useCallback(async () => {
    setIsLoadingDbHealth(true)
    setDbHealthError(null)
    try {
      const report = await fetchDatabaseHealth()
      setDbHealthReport(report)
    } catch (error) {
      console.error('Failed to load database health:', error)
      setDbHealthError(error instanceof Error ? error.message : 'Failed to load health report')
    } finally {
      setIsLoadingDbHealth(false)
    }
  }, [])

  // Feature #271: Toggle issue expansion
  const toggleIssueExpanded = (issueType: string) => {
    setExpandedIssues(prev => {
      const newSet = new Set(prev)
      if (newSet.has(issueType)) {
        newSet.delete(issueType)
      } else {
        newSet.add(issueType)
      }
      return newSet
    })
  }

  // Feature #271: Handle auto-fix
  const handleAutoFix = async (fixTypes: string[], dryRun: boolean = false) => {
    setIsFixing(true)
    setFixResult(null)
    try {
      const result = await runDatabaseHealthFix({ fix_types: fixTypes, dry_run: dryRun })
      setFixResult(result)
      if (result.success) {
        if (dryRun) {
          showToast('info', `Dry run: Would fix ${result.total_fixed} issues`)
        } else {
          showToast('success', `Fixed ${result.total_fixed} issues`)
          // Reload health report to show updated state
          await loadDbHealth()
        }
      } else {
        showToast('warning', result.errors.join(', ') || 'Some fixes failed')
      }
    } catch (error) {
      console.error('Auto-fix failed:', error)
      showToast('error', error instanceof Error ? error.message : 'Auto-fix failed')
    } finally {
      setIsFixing(false)
    }
  }

  // Feature #271: Get severity icon and color
  const getSeverityDisplay = (severity: 'critical' | 'warning' | 'info') => {
    switch (severity) {
      case 'critical':
        return {
          icon: <ShieldAlert className="w-5 h-5 text-red-500" />,
          bgClass: 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800',
          textClass: 'text-red-700 dark:text-red-300'
        }
      case 'warning':
        return {
          icon: <AlertTriangle className="w-5 h-5 text-yellow-500" />,
          bgClass: 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800',
          textClass: 'text-yellow-700 dark:text-yellow-300'
        }
      default:
        return {
          icon: <Info className="w-5 h-5 text-blue-500" />,
          bgClass: 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800',
          textClass: 'text-blue-700 dark:text-blue-300'
        }
    }
  }

  return (
    <div className="min-h-screen bg-light-bg dark:bg-dark-bg">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-light-sidebar dark:bg-dark-sidebar border-b border-light-border dark:border-dark-border">
        <div className="max-w-6xl mx-auto px-4 py-4">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/')}
              className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
              aria-label="Back to home"
            >
              <ArrowLeft className="w-5 h-5 text-light-text dark:text-dark-text" />
            </button>
            <div className="flex items-center gap-2">
              <Database className="w-6 h-6 text-primary" />
              <h1 className="text-xl font-semibold text-light-text dark:text-dark-text">
                Database Maintenance
              </h1>
            </div>
            <button
              onClick={loadHealthData}
              disabled={isLoadingHealth || operationInProgress !== null}
              className="ml-auto p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors disabled:opacity-50"
              aria-label="Refresh health data"
            >
              <RefreshCw className={`w-5 h-5 text-light-text-secondary dark:text-dark-text-secondary ${isLoadingHealth ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
        {/* Health Overview */}
        {isLoadingHealth ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 text-primary animate-spin" />
          </div>
        ) : healthData ? (
          <>
            {/* Status Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl p-4 border border-light-border dark:border-dark-border">
                <div className="flex items-center gap-2 mb-2">
                  <Server className="w-5 h-5 text-green-500" />
                  <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">Database</span>
                </div>
                <p className="text-lg font-semibold text-light-text dark:text-dark-text capitalize">
                  {healthData.database.status}
                </p>
                <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                  {healthData.database.database_size_pretty}
                </p>
              </div>

              <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl p-4 border border-light-border dark:border-dark-border">
                <div className="flex items-center gap-2 mb-2">
                  <Layers className={`w-5 h-5 ${healthData.pgvector_available ? 'text-green-500' : 'text-yellow-500'}`} />
                  <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">pgvector</span>
                </div>
                <p className="text-lg font-semibold text-light-text dark:text-dark-text">
                  {healthData.pgvector_available ? 'Available' : 'Not Available'}
                </p>
                <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                  {healthData.embeddings.total_chunks || 0} chunks
                </p>
              </div>

              <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl p-4 border border-light-border dark:border-dark-border">
                <div className="flex items-center gap-2 mb-2">
                  <HardDrive className="w-5 h-5 text-blue-500" />
                  <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">File Storage</span>
                </div>
                <p className="text-lg font-semibold text-light-text dark:text-dark-text">
                  {healthData.storage.uploads_count} files
                </p>
                <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                  {healthData.storage.uploads_size_pretty}
                </p>
              </div>

              <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl p-4 border border-light-border dark:border-dark-border">
                <div className="flex items-center gap-2 mb-2">
                  <Zap className="w-5 h-5 text-purple-500" />
                  <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">Indexes</span>
                </div>
                <p className="text-lg font-semibold text-light-text dark:text-dark-text">
                  {healthData.indexes.length} indexes
                </p>
                <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                  {healthData.database.check_duration_ms}ms check
                </p>
              </div>
            </div>

            {/* Table Row Counts */}
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
              <div className="px-4 py-3 border-b border-light-border dark:border-dark-border">
                <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
                  <Table className="w-5 h-5" />
                  Table Statistics
                </h2>
              </div>
              <div className="p-4">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {Object.entries(healthData.tables)
                    .filter(([_, count]) => count >= 0)
                    .sort((a, b) => b[1] - a[1])
                    .map(([table, count]) => (
                      <div
                        key={table}
                        className="flex justify-between items-center p-3 bg-light-bg dark:bg-dark-bg rounded-lg"
                      >
                        <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                          {table.replace(/_/g, ' ')}
                        </span>
                        <span className="font-medium text-light-text dark:text-dark-text">
                          {formatNumber(count)}
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            </div>

            {/* Maintenance Operations */}
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
              <div className="px-4 py-3 border-b border-light-border dark:border-dark-border">
                <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
                  <Activity className="w-5 h-5" />
                  Maintenance Operations
                </h2>
              </div>
              <div className="p-4 space-y-4">
                {/* Vacuum & Analyze */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                  <div className="flex-1">
                    <h3 className="font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                      <Database className="w-4 h-4 text-blue-500" />
                      Vacuum & Analyze
                    </h3>
                    <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
                      Optimizes PostgreSQL tables and updates query planner statistics.
                    </p>
                  </div>
                  <button
                    onClick={handleVacuumAnalyze}
                    disabled={operationInProgress !== null}
                    className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 whitespace-nowrap"
                  >
                    {operationInProgress === 'vacuum' ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Database className="w-4 h-4" />
                    )}
                    Run Vacuum
                  </button>
                </div>

                {/* Cleanup Orphans */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                  <div className="flex-1">
                    <h3 className="font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                      <Trash2 className="w-4 h-4 text-orange-500" />
                      Cleanup Orphans
                    </h3>
                    <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
                      Removes embeddings and chunks without parent documents.
                    </p>
                  </div>
                  <button
                    onClick={() => confirmDestructiveOperation(
                      'Cleanup Orphan Records',
                      'This will permanently delete orphan embeddings and data rows that no longer belong to any document. This action cannot be undone.',
                      handleCleanupOrphans
                    )}
                    disabled={operationInProgress !== null}
                    className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 whitespace-nowrap"
                  >
                    {operationInProgress === 'orphans' ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Trash2 className="w-4 h-4" />
                    )}
                    Cleanup
                  </button>
                </div>

                {/* Rebuild Indexes */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                  <div className="flex-1">
                    <h3 className="font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                      <RefreshCw className="w-4 h-4 text-purple-500" />
                      Rebuild Indexes
                    </h3>
                    <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
                      Rebuilds all database indexes including pgvector indexes for faster searches.
                    </p>
                  </div>
                  <button
                    onClick={handleRebuildIndexes}
                    disabled={operationInProgress !== null}
                    className="px-4 py-2 bg-purple-500 text-white rounded-lg hover:bg-purple-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 whitespace-nowrap"
                  >
                    {operationInProgress === 'indexes' ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <RefreshCw className="w-4 h-4" />
                    )}
                    Rebuild
                  </button>
                </div>

                {/* Cleanup Conversations */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                  <div className="flex-1">
                    <h3 className="font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                      <MessageSquare className="w-4 h-4 text-red-500" />
                      Cleanup Old Conversations
                    </h3>
                    <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
                      Delete conversations and messages older than a specified number of days.
                    </p>
                  </div>
                  <button
                    onClick={() => setIsCleanupModalOpen(true)}
                    disabled={operationInProgress !== null}
                    className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 whitespace-nowrap"
                  >
                    {operationInProgress === 'conversations' ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <MessageSquare className="w-4 h-4" />
                    )}
                    Cleanup
                  </button>
                </div>

                {/* Manual Backup */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg">
                  <div className="flex-1">
                    <h3 className="font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                      <Download className="w-4 h-4 text-green-500" />
                      Manual Backup
                    </h3>
                    <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
                      Download a complete backup of all documents, collections, and conversations.
                    </p>
                  </div>
                  <button
                    onClick={handleBackup}
                    disabled={operationInProgress !== null}
                    className="px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 whitespace-nowrap"
                  >
                    {operationInProgress === 'backup' ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Download className="w-4 h-4" />
                    )}
                    Download
                  </button>
                </div>

                {/* Re-embed All Documents (Feature #187) */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-light-bg dark:bg-dark-bg rounded-lg border-2 border-dashed border-amber-300 dark:border-amber-700">
                  <div className="flex-1">
                    <h3 className="font-medium text-light-text dark:text-dark-text flex items-center gap-2">
                      <RotateCcw className="w-4 h-4 text-amber-500" />
                      Re-embed All Documents
                      <span className="px-1.5 py-0.5 text-xs font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 rounded">
                        MODEL CHANGE
                      </span>
                    </h3>
                    <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-1">
                      Re-process all documents with the current embedding model. Use after changing the embedding model in Settings.
                    </p>
                  </div>
                  <button
                    onClick={handleOpenReembedModal}
                    disabled={operationInProgress !== null}
                    className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 whitespace-nowrap"
                  >
                    {operationInProgress === 'reembed' ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <RotateCcw className="w-4 h-4" />
                    )}
                    Re-embed
                  </button>
                </div>
              </div>
            </div>

            {/* Last Operation Result */}
            {lastResult && (
              <div className={`rounded-xl border p-4 ${
                lastResult.success
                  ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                  : 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800'
              }`}>
                <div className="flex items-start gap-3">
                  {lastResult.success ? (
                    <CheckCircle className="w-5 h-5 text-green-500 flex-shrink-0 mt-0.5" />
                  ) : (
                    <AlertCircle className="w-5 h-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                  )}
                  <div className="flex-1">
                    <h3 className={`font-medium ${
                      lastResult.success
                        ? 'text-green-800 dark:text-green-200'
                        : 'text-yellow-800 dark:text-yellow-200'
                    }`}>
                      {lastResult.message}
                    </h3>
                    {lastResult.duration_ms !== undefined && (
                      <p className={`text-sm mt-1 ${
                        lastResult.success
                          ? 'text-green-600 dark:text-green-400'
                          : 'text-yellow-600 dark:text-yellow-400'
                      }`}>
                        <Clock className="w-3 h-3 inline mr-1" />
                        Completed in {lastResult.duration_ms}ms
                      </p>
                    )}
                    {lastResult.details && (
                      <details className="mt-2">
                        <summary className={`text-sm cursor-pointer ${
                          lastResult.success
                            ? 'text-green-600 dark:text-green-400'
                            : 'text-yellow-600 dark:text-yellow-400'
                        }`}>
                          View details
                        </summary>
                        <pre className={`mt-2 text-xs overflow-auto p-2 rounded ${
                          lastResult.success
                            ? 'bg-green-100 dark:bg-green-900/40'
                            : 'bg-yellow-100 dark:bg-yellow-900/40'
                        }`}>
                          {JSON.stringify(lastResult.details, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Largest Tables */}
            {healthData.database.largest_tables && healthData.database.largest_tables.length > 0 && (
              <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
                <div className="px-4 py-3 border-b border-light-border dark:border-dark-border">
                  <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
                    <HardDrive className="w-5 h-5" />
                    Largest Tables
                  </h2>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-light-bg dark:bg-dark-bg">
                      <tr>
                        <th className="px-4 py-2 text-left text-sm font-medium text-light-text-secondary dark:text-dark-text-secondary">
                          Table
                        </th>
                        <th className="px-4 py-2 text-right text-sm font-medium text-light-text-secondary dark:text-dark-text-secondary">
                          Size
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {healthData.database.largest_tables.map((table, idx) => (
                        <tr
                          key={table.table}
                          className={idx % 2 === 0 ? '' : 'bg-light-bg/50 dark:bg-dark-bg/50'}
                        >
                          <td className="px-4 py-2 text-sm text-light-text dark:text-dark-text">
                            {table.table}
                          </td>
                          <td className="px-4 py-2 text-sm text-right text-light-text dark:text-dark-text">
                            {table.size_pretty}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Feature #271: Database Health Check Section */}
            <div className="bg-light-sidebar dark:bg-dark-sidebar rounded-xl border border-light-border dark:border-dark-border overflow-hidden">
              <div className="px-4 py-3 border-b border-light-border dark:border-dark-border flex items-center justify-between">
                <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
                  <Shield className="w-5 h-5" />
                  Database Health Check
                </h2>
                <button
                  onClick={loadDbHealth}
                  disabled={isLoadingDbHealth}
                  className="px-3 py-1.5 bg-blue-500 text-white text-sm rounded-lg hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {isLoadingDbHealth ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <RefreshCw className="w-4 h-4" />
                  )}
                  Run Health Check
                </button>
              </div>

              <div className="p-4">
                {!dbHealthReport && !isLoadingDbHealth && !dbHealthError && (
                  <div className="text-center py-8">
                    <Shield className="w-12 h-12 text-gray-400 mx-auto mb-3" />
                    <p className="text-light-text-secondary dark:text-dark-text-secondary">
                      Click "Run Health Check" to scan for database integrity issues
                    </p>
                  </div>
                )}

                {isLoadingDbHealth && (
                  <div className="text-center py-8">
                    <Loader2 className="w-8 h-8 text-blue-500 mx-auto mb-3 animate-spin" />
                    <p className="text-light-text-secondary dark:text-dark-text-secondary">
                      Scanning database for integrity issues...
                    </p>
                  </div>
                )}

                {dbHealthError && (
                  <div className="p-4 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
                    <div className="flex items-center gap-2 text-red-700 dark:text-red-300">
                      <AlertCircle className="w-5 h-5" />
                      <span className="font-medium">Health check failed</span>
                    </div>
                    <p className="mt-1 text-sm text-red-600 dark:text-red-400">{dbHealthError}</p>
                  </div>
                )}

                {dbHealthReport && (
                  <div className="space-y-4">
                    {/* Status Summary */}
                    <div className={`p-4 rounded-lg border ${
                      dbHealthReport.status === 'healthy'
                        ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                        : dbHealthReport.status === 'critical'
                        ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
                        : dbHealthReport.status === 'warning'
                        ? 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800'
                        : 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800'
                    }`}>
                      <div className="flex items-center gap-3">
                        {dbHealthReport.status === 'healthy' ? (
                          <ShieldCheck className="w-8 h-8 text-green-500" />
                        ) : dbHealthReport.status === 'critical' ? (
                          <ShieldAlert className="w-8 h-8 text-red-500" />
                        ) : dbHealthReport.status === 'warning' ? (
                          <AlertTriangle className="w-8 h-8 text-yellow-500" />
                        ) : (
                          <Info className="w-8 h-8 text-blue-500" />
                        )}
                        <div className="flex-1">
                          <h3 className={`font-semibold ${
                            dbHealthReport.status === 'healthy' ? 'text-green-700 dark:text-green-300' :
                            dbHealthReport.status === 'critical' ? 'text-red-700 dark:text-red-300' :
                            dbHealthReport.status === 'warning' ? 'text-yellow-700 dark:text-yellow-300' :
                            'text-blue-700 dark:text-blue-300'
                          }`}>
                            {dbHealthReport.status === 'healthy' ? 'Database is Healthy' :
                             dbHealthReport.status === 'critical' ? 'Critical Issues Found' :
                             dbHealthReport.status === 'warning' ? 'Warnings Found' :
                             'Minor Issues Found'}
                          </h3>
                          <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                            Scanned in {dbHealthReport.scan_duration_ms}ms • {dbHealthReport.summary.total_documents} documents • {dbHealthReport.summary.total_embeddings} embeddings
                          </p>
                        </div>
                        {dbHealthReport.summary.auto_fixable_issues > 0 && (
                          <button
                            onClick={() => {
                              const fixableTypes = dbHealthReport.issues
                                .filter(i => i.auto_fixable)
                                .map(i => i.issue_type)
                              handleAutoFix(fixableTypes, false)
                            }}
                            disabled={isFixing}
                            className="px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                          >
                            {isFixing ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Wrench className="w-4 h-4" />
                            )}
                            Fix All ({dbHealthReport.summary.auto_fixable_issues})
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Issue Counts */}
                    {dbHealthReport.total_issues_found > 0 && (
                      <div className="grid grid-cols-3 gap-3">
                        <div className="p-3 bg-red-50 dark:bg-red-900/20 rounded-lg text-center">
                          <div className="text-2xl font-bold text-red-600 dark:text-red-400">
                            {dbHealthReport.summary.critical_issues}
                          </div>
                          <div className="text-xs text-red-500 dark:text-red-400">Critical</div>
                        </div>
                        <div className="p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg text-center">
                          <div className="text-2xl font-bold text-yellow-600 dark:text-yellow-400">
                            {dbHealthReport.summary.warning_issues}
                          </div>
                          <div className="text-xs text-yellow-500 dark:text-yellow-400">Warnings</div>
                        </div>
                        <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-center">
                          <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                            {dbHealthReport.summary.info_issues}
                          </div>
                          <div className="text-xs text-blue-500 dark:text-blue-400">Info</div>
                        </div>
                      </div>
                    )}

                    {/* Issues List */}
                    {dbHealthReport.issues.length > 0 && (
                      <div className="space-y-2">
                        {dbHealthReport.issues.map((issue) => {
                          const severity = getSeverityDisplay(issue.severity)
                          const isExpanded = expandedIssues.has(issue.issue_type)
                          return (
                            <div
                              key={issue.issue_type}
                              className={`rounded-lg border ${severity.bgClass} overflow-hidden`}
                            >
                              <div
                                className="p-3 cursor-pointer flex items-center gap-3"
                                onClick={() => toggleIssueExpanded(issue.issue_type)}
                              >
                                {severity.icon}
                                <div className="flex-1">
                                  <div className={`font-medium ${severity.textClass}`}>
                                    {issue.description}
                                  </div>
                                  <div className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-0.5">
                                    {issue.auto_fixable ? (
                                      <span className="inline-flex items-center gap-1">
                                        <Wrench className="w-3 h-3" /> Auto-fixable
                                      </span>
                                    ) : (
                                      'Manual fix required'
                                    )}
                                  </div>
                                </div>
                                <div className="flex items-center gap-2">
                                  {issue.auto_fixable && (
                                    <button
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        handleAutoFix([issue.issue_type], false)
                                      }}
                                      disabled={isFixing}
                                      className="px-3 py-1 text-sm bg-green-500 text-white rounded hover:bg-green-600 transition-colors disabled:opacity-50 flex items-center gap-1"
                                    >
                                      <Wrench className="w-3 h-3" />
                                      Fix
                                    </button>
                                  )}
                                  {isExpanded ? (
                                    <ChevronUp className="w-5 h-5 text-light-text-secondary dark:text-dark-text-secondary" />
                                  ) : (
                                    <ChevronDown className="w-5 h-5 text-light-text-secondary dark:text-dark-text-secondary" />
                                  )}
                                </div>
                              </div>

                              {isExpanded && (
                                <div className="px-3 pb-3 border-t border-light-border dark:border-dark-border pt-3">
                                  <div className="text-sm text-light-text-secondary dark:text-dark-text-secondary mb-2">
                                    <strong>Suggested Fix:</strong> {issue.suggested_fix}
                                  </div>
                                  {issue.affected_items.length > 0 && (
                                    <div className="mt-2">
                                      <div className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary mb-1">
                                        Affected Items (showing {Math.min(issue.affected_items.length, 10)} of {issue.count}):
                                      </div>
                                      <pre className="text-xs bg-black/5 dark:bg-white/5 p-2 rounded overflow-x-auto max-h-40">
                                        {JSON.stringify(issue.affected_items, null, 2)}
                                      </pre>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}

                    {/* Fix Result */}
                    {fixResult && (
                      <div className={`p-3 rounded-lg border ${
                        fixResult.success
                          ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                          : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
                      }`}>
                        <div className="flex items-center gap-2">
                          {fixResult.success ? (
                            <CheckCircle className="w-5 h-5 text-green-500" />
                          ) : (
                            <AlertCircle className="w-5 h-5 text-red-500" />
                          )}
                          <span className={fixResult.success ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'}>
                            {fixResult.dry_run ? 'Dry run: ' : ''}
                            {fixResult.total_fixed} issues {fixResult.dry_run ? 'would be' : ''} fixed in {fixResult.duration_ms}ms
                          </span>
                        </div>
                        {fixResult.fixes_applied.length > 0 && (
                          <div className="mt-2 text-sm text-light-text-secondary dark:text-dark-text-secondary">
                            {fixResult.fixes_applied.map((fix, idx) => (
                              <div key={idx}>
                                • {fix.fix_type}: {fix.fixed_count} fixed
                              </div>
                            ))}
                          </div>
                        )}
                        {fixResult.errors.length > 0 && (
                          <div className="mt-2 text-sm text-red-600 dark:text-red-400">
                            Errors: {fixResult.errors.join(', ')}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="text-center py-12">
            <AlertTriangle className="w-12 h-12 text-yellow-500 mx-auto mb-4" />
            <p className="text-light-text-secondary dark:text-dark-text-secondary">
              Failed to load health data. Please try again.
            </p>
          </div>
        )}
      </div>

      {/* Cleanup Conversations Modal */}
      {isCleanupModalOpen && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={() => setIsCleanupModalOpen(false)}
        >
          <div
            className="bg-white dark:bg-dark-sidebar rounded-xl shadow-xl p-6 w-full max-w-md mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-red-100 dark:bg-red-900/30 rounded-lg">
                <AlertTriangle className="w-6 h-6 text-red-500" />
              </div>
              <h2 className="text-lg font-semibold text-light-text dark:text-dark-text">
                Cleanup Old Conversations
              </h2>
            </div>

            <div className="mb-4">
              <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mb-4">
                This will permanently delete all conversations and their messages older than the specified number of days. This action cannot be undone.
              </p>

              <label className="block text-sm font-medium text-light-text dark:text-dark-text mb-2">
                Delete conversations older than:
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={cleanupDays}
                  onChange={(e) => setCleanupDays(Math.max(1, parseInt(e.target.value) || 1))}
                  min={1}
                  className="flex-1 px-3 py-2 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary"
                />
                <span className="text-light-text-secondary dark:text-dark-text-secondary">days</span>
              </div>

              <div className="mt-3 p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
                <p className="text-sm text-yellow-700 dark:text-yellow-300 flex items-start gap-2">
                  <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  <span>
                    Currently showing {healthData?.tables.conversations || 0} conversations
                    and {healthData?.tables.messages || 0} messages in the database.
                  </span>
                </p>
              </div>
            </div>

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setIsCleanupModalOpen(false)}
                className="px-4 py-2 text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCleanupConversations}
                className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors flex items-center gap-2"
              >
                <Trash2 className="w-4 h-4" />
                Delete Conversations
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirmation Modal */}
      <ConfirmDeleteModal
        isOpen={confirmOperation.isOpen}
        onClose={() => setConfirmOperation({ isOpen: false, title: '', message: '', operation: null })}
        onConfirm={executeConfirmedOperation}
        title={confirmOperation.title}
        message={confirmOperation.message}
        isDeleting={false}
      />

      {/* Re-embed All Documents Modal (Feature #187) */}
      {isReembedModalOpen && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={() => !operationInProgress && setIsReembedModalOpen(false)}
        >
          <div
            className="bg-white dark:bg-dark-sidebar rounded-xl shadow-xl p-6 w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
                <AlertTriangle className="w-6 h-6 text-amber-500" />
              </div>
              <h2 className="text-lg font-semibold text-light-text dark:text-dark-text">
                Re-embed All Documents
              </h2>
            </div>

            {/* Loading estimate */}
            {isLoadingEstimate && (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-8 h-8 text-amber-500 animate-spin" />
              </div>
            )}

            {/* Estimate loaded */}
            {!isLoadingEstimate && reembedEstimate && !reembedResult && (
              <>
                <div className="mb-4">
                  <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mb-4">
                    Changing the embedding model requires re-processing all documents. This operation will:
                  </p>
                  <ul className="text-sm text-light-text-secondary dark:text-dark-text-secondary list-disc list-inside space-y-1 mb-4">
                    <li>Delete all existing embeddings</li>
                    <li>Re-chunk and re-embed each document</li>
                    <li>Update document metadata with new embedding source</li>
                  </ul>

                  <div className="bg-light-bg dark:bg-dark-bg rounded-lg p-4 space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-light-text-secondary dark:text-dark-text-secondary">Documents to process:</span>
                      <span className="font-medium text-light-text dark:text-dark-text">{reembedEstimate.total_documents}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-light-text-secondary dark:text-dark-text-secondary">Total file size:</span>
                      <span className="font-medium text-light-text dark:text-dark-text">{reembedEstimate.total_size_pretty}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-light-text-secondary dark:text-dark-text-secondary">Existing embeddings:</span>
                      <span className="font-medium text-light-text dark:text-dark-text">{formatNumber(reembedEstimate.total_existing_embeddings)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-light-text-secondary dark:text-dark-text-secondary">Estimated duration:</span>
                      <span className="font-medium text-amber-600 dark:text-amber-400">{reembedEstimate.estimated_duration_pretty}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-light-text-secondary dark:text-dark-text-secondary">Target embedding model:</span>
                      <span className="font-medium text-primary">{reembedEstimate.current_embedding_model}</span>
                    </div>
                  </div>

                  {reembedEstimate.warning && (
                    <div className="mt-3 p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg">
                      <p className="text-sm text-amber-700 dark:text-amber-300 flex items-start gap-2">
                        <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                        <span>{reembedEstimate.warning}</span>
                      </p>
                    </div>
                  )}

                  {reembedEstimate.total_documents === 0 && (
                    <div className="mt-3 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                      <p className="text-sm text-blue-700 dark:text-blue-300 flex items-start gap-2">
                        <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
                        <span>No documents to re-embed. Upload some documents first.</span>
                      </p>
                    </div>
                  )}
                </div>

                <div className="flex justify-end gap-3">
                  <button
                    onClick={() => setIsReembedModalOpen(false)}
                    disabled={operationInProgress !== null}
                    className="px-4 py-2 text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleReembedAll}
                    disabled={operationInProgress !== null || reembedEstimate.total_documents === 0}
                    className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {operationInProgress === 'reembed' ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Processing...
                      </>
                    ) : (
                      <>
                        <RotateCcw className="w-4 h-4" />
                        Start Re-embedding
                      </>
                    )}
                  </button>
                </div>
              </>
            )}

            {/* Re-embed in progress - Feature #189: Real-time progress bar */}
            {operationInProgress === 'reembed' && !reembedResult && (
              <div className="py-4">
                {reembedProgress ? (
                  <>
                    <ReembedProgressBar progress={reembedProgress} />
                    <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary mt-4 text-center">
                      Please don't close this window while processing.
                    </p>
                  </>
                ) : (
                  <div className="flex flex-col items-center justify-center py-4">
                    <Loader2 className="w-8 h-8 text-amber-500 animate-spin mb-3" />
                    <p className="text-light-text dark:text-dark-text font-medium">Starting re-embed operation...</p>
                  </div>
                )}
              </div>
            )}

            {/* Re-embed result */}
            {reembedResult && (
              <>
                <div className={`rounded-lg p-4 mb-4 ${
                  reembedResult.success
                    ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
                    : 'bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800'
                }`}>
                  <div className="flex items-start gap-3">
                    {reembedResult.success && reembedResult.failed === 0 ? (
                      <CheckCircle className="w-5 h-5 text-green-500 flex-shrink-0 mt-0.5" />
                    ) : (
                      <AlertCircle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
                    )}
                    <div>
                      <h3 className={`font-medium ${
                        reembedResult.success && reembedResult.failed === 0
                          ? 'text-green-800 dark:text-green-200'
                          : 'text-amber-800 dark:text-amber-200'
                      }`}>
                        {reembedResult.message}
                      </h3>
                      <p className="text-sm mt-1 text-light-text-secondary dark:text-dark-text-secondary">
                        <Clock className="w-3 h-3 inline mr-1" />
                        Completed in {reembedResult.duration_ms}ms
                      </p>
                    </div>
                  </div>
                </div>

                <div className="bg-light-bg dark:bg-dark-bg rounded-lg p-4 space-y-2 mb-4">
                  <div className="flex justify-between text-sm">
                    <span className="text-light-text-secondary dark:text-dark-text-secondary">Total documents:</span>
                    <span className="font-medium text-light-text dark:text-dark-text">{reembedResult.total_documents}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-light-text-secondary dark:text-dark-text-secondary">Successfully processed:</span>
                    <span className="font-medium text-green-600 dark:text-green-400">{reembedResult.successful}</span>
                  </div>
                  {reembedResult.failed > 0 && (
                    <div className="flex justify-between text-sm">
                      <span className="text-light-text-secondary dark:text-dark-text-secondary">Failed:</span>
                      <span className="font-medium text-red-600 dark:text-red-400">{reembedResult.failed}</span>
                    </div>
                  )}
                  <div className="flex justify-between text-sm">
                    <span className="text-light-text-secondary dark:text-dark-text-secondary">Embedding model:</span>
                    <span className="font-medium text-primary">{reembedResult.new_embedding_model}</span>
                  </div>
                </div>

                {/* Failed documents list */}
                {reembedResult.failed_documents.length > 0 && (
                  <details className="mb-4">
                    <summary className="text-sm cursor-pointer text-red-600 dark:text-red-400 hover:underline">
                      View {reembedResult.failed_documents.length} failed documents
                    </summary>
                    <div className="mt-2 max-h-40 overflow-y-auto">
                      {reembedResult.failed_documents.map((doc, idx) => (
                        <div
                          key={idx}
                          className="text-xs p-2 bg-red-50 dark:bg-red-900/20 rounded mb-1"
                        >
                          <p className="font-medium text-red-800 dark:text-red-200">{doc.title}</p>
                          <p className="text-red-600 dark:text-red-400">{doc.error}</p>
                        </div>
                      ))}
                    </div>
                  </details>
                )}

                <div className="flex justify-end">
                  <button
                    onClick={() => {
                      setIsReembedModalOpen(false)
                      setReembedResult(null)
                      setReembedProgress(null)
                    }}
                    className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                  >
                    Done
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
