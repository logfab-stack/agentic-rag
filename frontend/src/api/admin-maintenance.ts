/**
 * Admin Maintenance API client
 *
 * Provides access to database maintenance operations
 */

// ==================== Types ====================

export interface OperationResult {
  success: boolean
  operation: string
  message: string
  details?: Record<string, unknown>
  duration_ms?: number
}

export interface TableSizeInfo {
  table: string
  size_bytes: number
  size_pretty: string
}

export interface IndexInfo {
  name: string
  table: string
  size_pretty: string
  size_bytes: number
  scans: number
  tuples_read: number
}

export interface HealthCheckResult {
  status: string
  database: {
    status: string
    check_duration_ms: number
    database_size_bytes: number
    database_size_pretty: string
    largest_tables: TableSizeInfo[]
    error?: string
  }
  tables: Record<string, number>
  storage: {
    uploads_directory: string
    uploads_count: number
    uploads_size_bytes: number
    uploads_size_pretty: string
  }
  embeddings: {
    total_chunks?: number
    valid_chunks?: number
    invalid_chunks?: number
    dimensions_consistent?: boolean
    error?: string
  }
  indexes: IndexInfo[]
  pgvector_available: boolean
}

export interface ConversationCleanupRequest {
  older_than_days: number
}

// ==================== API Functions ====================

/**
 * Get comprehensive health check with database statistics
 */
export async function fetchHealthCheck(): Promise<HealthCheckResult> {
  const response = await fetch('/api/admin/maintenance/health')
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Health check failed' }))
    throw new Error(error.detail || 'Health check failed')
  }
  return response.json()
}

/**
 * Run VACUUM ANALYZE on all application tables
 */
export async function runVacuumAnalyze(): Promise<OperationResult> {
  const response = await fetch('/api/admin/maintenance/vacuum-analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Vacuum & Analyze failed' }))
    throw new Error(error.detail || 'Vacuum & Analyze failed')
  }
  return response.json()
}

/**
 * Cleanup orphan embeddings and chunks
 */
export async function runCleanupOrphans(): Promise<OperationResult> {
  const response = await fetch('/api/admin/maintenance/cleanup-orphans', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Cleanup failed' }))
    throw new Error(error.detail || 'Cleanup failed')
  }
  return response.json()
}

/**
 * Rebuild database indexes
 */
export async function runRebuildIndexes(): Promise<OperationResult> {
  const response = await fetch('/api/admin/maintenance/rebuild-indexes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Index rebuild failed' }))
    throw new Error(error.detail || 'Index rebuild failed')
  }
  return response.json()
}

/**
 * Cleanup old conversations
 */
export async function runCleanupConversations(request: ConversationCleanupRequest): Promise<OperationResult> {
  const response = await fetch('/api/admin/maintenance/cleanup-conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Conversation cleanup failed' }))
    throw new Error(error.detail || 'Conversation cleanup failed')
  }
  return response.json()
}

/**
 * Create a manual backup and download it
 */
export async function downloadBackup(): Promise<Blob> {
  const response = await fetch('/api/admin/maintenance/backup', {
    method: 'POST'
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Backup failed' }))
    throw new Error(error.detail || 'Backup failed')
  }
  return response.blob()
}

// ==================== Re-embedding API (Feature #187) ====================

export interface ReembedResult {
  success: boolean
  message: string
  total_documents: number
  processed: number
  successful: number
  failed: number
  failed_documents: Array<{
    id: string
    title: string
    error: string
  }>
  duration_ms: number
  new_embedding_model: string
}

export interface ReembedEstimate {
  total_documents: number
  total_size_bytes: number
  total_size_pretty: string
  estimated_duration_ms: number
  estimated_duration_pretty: string
  current_embedding_model: string
  total_existing_embeddings: number
  warning?: string
  error?: string
}

// Feature #189: Re-embed progress tracking
export interface ReembedProgress {
  status: 'idle' | 'in_progress' | 'completed' | 'failed'
  total_documents: number
  processed: number
  successful: number
  failed: number
  current_document_name: string | null
  current_document_id: number | null
  chunks_generated: number
  elapsed_ms: number
  elapsed_pretty: string
  eta_ms: number | null
  eta_pretty: string | null
  percentage: number
  error_message: string | null
}

/**
 * Get an estimate of time required to re-embed all documents
 */
export async function getReembedEstimate(): Promise<ReembedEstimate> {
  const response = await fetch('/api/admin/maintenance/reembed-estimate')
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to get estimate' }))
    throw new Error(error.detail || 'Failed to get estimate')
  }
  return response.json()
}

/**
 * Re-embed all documents with the current embedding model
 *
 * This operation can take several minutes for large document collections.
 * It deletes existing embeddings and regenerates them with the current model.
 *
 * Use getReembedProgress() to poll for real-time progress updates.
 */
export async function runReembedAll(): Promise<ReembedResult> {
  const response = await fetch('/api/admin/maintenance/reembed-all', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Re-embedding failed' }))
    throw new Error(error.detail || 'Re-embedding failed')
  }
  return response.json()
}

/**
 * Get the current progress of the re-embedding operation
 *
 * Feature #189: Real-time progress tracking.
 * Poll this endpoint every 1-2 seconds during re-embed operations.
 */
export async function getReembedProgress(): Promise<ReembedProgress> {
  const response = await fetch('/api/admin/maintenance/reembed-progress')
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to get progress' }))
    throw new Error(error.detail || 'Failed to get progress')
  }
  return response.json()
}


// ==================== Database Health Check API (Feature #271) ====================

export interface DatabaseHealthIssue {
  issue_type: string
  severity: 'critical' | 'warning' | 'info'
  count: number
  description: string
  affected_items: Array<Record<string, unknown>>
  suggested_fix: string
  auto_fixable: boolean
}

export interface DatabaseHealthReport {
  status: 'healthy' | 'warning' | 'critical' | 'info'
  scan_timestamp: string
  scan_duration_ms: number
  total_issues_found: number
  issues: DatabaseHealthIssue[]
  summary: {
    total_documents: number
    total_embeddings: number
    total_conversations: number
    critical_issues: number
    warning_issues: number
    info_issues: number
    auto_fixable_issues: number
  }
}

export interface DatabaseHealthFixRequest {
  fix_types: string[]
  dry_run: boolean
}

export interface DatabaseHealthFixResponse {
  success: boolean
  dry_run: boolean
  fixes_applied: Array<{
    fix_type: string
    fixed_count: number
    dry_run: boolean
  }>
  total_fixed: number
  errors: string[]
  duration_ms: number
}

/**
 * Feature #271: Run comprehensive database health check
 *
 * Checks for:
 * - Orphaned embeddings
 * - Documents without embeddings
 * - Documents with missing files
 * - FK constraint violations
 * - Data consistency issues
 */
export async function fetchDatabaseHealth(): Promise<DatabaseHealthReport> {
  const response = await fetch('/api/admin/maintenance/db-health')
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Health check failed' }))
    throw new Error(error.detail || 'Health check failed')
  }
  return response.json()
}

/**
 * Feature #271: Auto-fix database health issues
 *
 * @param request - Fix request with issue types and dry_run flag
 */
export async function runDatabaseHealthFix(request: DatabaseHealthFixRequest): Promise<DatabaseHealthFixResponse> {
  const response = await fetch('/api/admin/maintenance/db-health/fix', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Auto-fix failed' }))
    throw new Error(error.detail || 'Auto-fix failed')
  }
  return response.json()
}
