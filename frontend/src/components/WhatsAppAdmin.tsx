/**
 * WhatsApp Admin Dashboard
 *
 * Provides UI for monitoring WhatsApp activity:
 * - User list with phone numbers, activity, message counts
 * - Message history per user
 * - Statistics (messages today/week/month)
 * - Block/unblock phone numbers
 */

import { useState, useEffect, useCallback } from 'react'
import {
  ArrowLeft,
  MessageSquare,
  Users,
  Shield,
  ShieldOff,
  RefreshCw,
  Search,
  ChevronLeft,
  ChevronRight,
  Phone,
  Clock,
  MessageCircle,
  TrendingUp,
  Ban,
  CheckCircle,
  AlertCircle
} from 'lucide-react'
import {
  fetchWhatsAppStats,
  fetchWhatsAppUsers,
  fetchUserMessages,
  setUserBlockStatus,
  type WhatsAppUser,
  type WhatsAppMessage,
  type WhatsAppStats,
  type WhatsAppUserListResponse,
  type WhatsAppMessageListResponse
} from '../api/whatsapp'

interface WhatsAppAdminProps {
  onBack: () => void
}

type ViewMode = 'dashboard' | 'messages'

export function WhatsAppAdmin({ onBack }: WhatsAppAdminProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('dashboard')
  const [stats, setStats] = useState<WhatsAppStats | null>(null)
  const [users, setUsers] = useState<WhatsAppUser[]>([])
  const [totalUsers, setTotalUsers] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [searchQuery, setSearchQuery] = useState('')
  const [showBlockedOnly, setShowBlockedOnly] = useState(false)
  const [selectedUser, setSelectedUser] = useState<WhatsAppUser | null>(null)
  const [messages, setMessages] = useState<WhatsAppMessage[]>([])
  const [messagesPage, setMessagesPage] = useState(1)
  const [messagesTotalPages, setMessagesTotalPages] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingMessages, setIsLoadingMessages] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  // Load stats
  const loadStats = useCallback(async () => {
    try {
      const data = await fetchWhatsAppStats()
      setStats(data)
    } catch (err) {
      console.error('Failed to load stats:', err)
    }
  }, [])

  // Load users
  const loadUsers = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const data: WhatsAppUserListResponse = await fetchWhatsAppUsers(
        currentPage,
        20,
        showBlockedOnly,
        searchQuery || undefined
      )
      setUsers(data.users)
      setTotalUsers(data.total)
      setTotalPages(data.total_pages)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load users')
    } finally {
      setIsLoading(false)
    }
  }, [currentPage, showBlockedOnly, searchQuery])

  // Load messages for selected user
  const loadMessages = useCallback(async (userId: string, page: number = 1) => {
    setIsLoadingMessages(true)
    try {
      const data: WhatsAppMessageListResponse = await fetchUserMessages(userId, page, 50)
      setMessages(data.messages)
      setMessagesPage(page)
      setMessagesTotalPages(data.total_pages)
      if (data.user) {
        setSelectedUser(data.user)
      }
    } catch (err) {
      console.error('Failed to load messages:', err)
    } finally {
      setIsLoadingMessages(false)
    }
  }, [])

  // Initial load
  useEffect(() => {
    loadStats()
    loadUsers()
  }, [loadStats, loadUsers])

  // Handle search
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setCurrentPage(1)
    loadUsers()
  }

  // Handle block/unblock
  const handleBlockToggle = async (user: WhatsAppUser) => {
    setActionLoading(user.id)
    try {
      const updatedUser = await setUserBlockStatus(user.id, !user.is_blocked)
      setUsers(prev => prev.map(u => u.id === user.id ? updatedUser : u))
      if (selectedUser?.id === user.id) {
        setSelectedUser(updatedUser)
      }
      await loadStats() // Refresh stats
    } catch (err) {
      console.error('Failed to update block status:', err)
    } finally {
      setActionLoading(null)
    }
  }

  // View user messages
  const handleViewMessages = (user: WhatsAppUser) => {
    setSelectedUser(user)
    setViewMode('messages')
    loadMessages(user.id)
  }

  // Back to dashboard
  const handleBackToDashboard = () => {
    setViewMode('dashboard')
    setSelectedUser(null)
    setMessages([])
    setMessagesPage(1)
  }

  // Format date
  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  // Format relative time
  const formatRelativeTime = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return formatDate(dateString)
  }

  // Render stats cards
  const renderStats = () => {
    if (!stats) return null

    const statCards = [
      { label: 'Total Users', value: stats.total_users, icon: Users, color: 'text-blue-500' },
      { label: 'Total Messages', value: stats.total_messages, icon: MessageSquare, color: 'text-green-500' },
      { label: 'Today', value: stats.messages_today, icon: TrendingUp, color: 'text-purple-500' },
      { label: 'This Week', value: stats.messages_this_week, icon: MessageCircle, color: 'text-indigo-500' },
      { label: 'This Month', value: stats.messages_this_month, icon: MessageCircle, color: 'text-teal-500' },
      { label: 'Active Today', value: stats.active_users_today, icon: CheckCircle, color: 'text-emerald-500' },
      { label: 'Blocked', value: stats.blocked_users, icon: Ban, color: 'text-red-500' },
    ]

    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-4 mb-6">
        {statCards.map((stat, idx) => (
          <div
            key={idx}
            className="bg-white dark:bg-dark-sidebar rounded-lg p-4 shadow-sm border border-light-border dark:border-dark-border"
          >
            <div className="flex items-center gap-2 mb-2">
              <stat.icon className={`h-4 w-4 ${stat.color}`} />
              <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                {stat.label}
              </span>
            </div>
            <div className="text-2xl font-bold text-light-text dark:text-dark-text">
              {stat.value.toLocaleString()}
            </div>
          </div>
        ))}
      </div>
    )
  }

  // Render user list
  const renderUserList = () => {
    return (
      <div className="bg-white dark:bg-dark-sidebar rounded-lg shadow-sm border border-light-border dark:border-dark-border">
        {/* Header with search and filters */}
        <div className="p-4 border-b border-light-border dark:border-dark-border">
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <Users className="h-5 w-5" />
              WhatsApp Users
            </h2>

            <div className="flex flex-col sm:flex-row gap-2 w-full sm:w-auto">
              {/* Search */}
              <form onSubmit={handleSearch} className="flex-1 sm:flex-initial">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-light-text-secondary dark:text-dark-text-secondary" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search by phone..."
                    className="pl-9 pr-4 py-2 w-full sm:w-48 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  />
                </div>
              </form>

              {/* Blocked filter */}
              <label className="flex items-center gap-2 text-sm text-light-text dark:text-dark-text cursor-pointer">
                <input
                  type="checkbox"
                  checked={showBlockedOnly}
                  onChange={(e) => {
                    setShowBlockedOnly(e.target.checked)
                    setCurrentPage(1)
                  }}
                  className="rounded border-light-border dark:border-dark-border"
                />
                Blocked only
              </label>

              {/* Refresh */}
              <button
                onClick={() => { loadStats(); loadUsers(); }}
                className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
                title="Refresh"
              >
                <RefreshCw className={`h-4 w-4 text-light-text-secondary dark:text-dark-text-secondary ${isLoading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>
        </div>

        {/* User list */}
        {isLoading ? (
          <div className="p-8 text-center text-light-text-secondary dark:text-dark-text-secondary">
            <RefreshCw className="h-8 w-8 animate-spin mx-auto mb-2" />
            Loading users...
          </div>
        ) : error ? (
          <div className="p-8 text-center">
            <AlertCircle className="h-8 w-8 text-red-500 mx-auto mb-2" />
            <p className="text-red-500">{error}</p>
          </div>
        ) : users.length === 0 ? (
          <div className="p-8 text-center text-light-text-secondary dark:text-dark-text-secondary">
            <Users className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>No WhatsApp users yet.</p>
            <p className="text-sm mt-1">Users will appear here when they message your WhatsApp number.</p>
          </div>
        ) : (
          <>
            <div className="divide-y divide-light-border dark:divide-dark-border">
              {users.map((user) => (
                <div
                  key={user.id}
                  className="p-4 hover:bg-light-bg dark:hover:bg-dark-bg transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      {/* Avatar */}
                      <div className={`w-10 h-10 rounded-full flex items-center justify-center ${user.is_blocked ? 'bg-red-100 dark:bg-red-900/30' : 'bg-green-100 dark:bg-green-900/30'}`}>
                        <Phone className={`h-5 w-5 ${user.is_blocked ? 'text-red-500' : 'text-green-500'}`} />
                      </div>

                      {/* User info */}
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-light-text dark:text-dark-text">
                            {user.phone_number}
                          </span>
                          {user.is_blocked && (
                            <span className="text-xs px-2 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 rounded-full">
                              Blocked
                            </span>
                          )}
                        </div>
                        {user.display_name && (
                          <div className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                            {user.display_name}
                          </div>
                        )}
                        <div className="flex items-center gap-4 mt-1 text-xs text-light-text-secondary dark:text-dark-text-secondary">
                          <span className="flex items-center gap-1">
                            <MessageSquare className="h-3 w-3" />
                            {user.message_count} messages
                          </span>
                          <span className="flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {formatRelativeTime(user.last_active_at)}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleViewMessages(user)}
                        className="px-3 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors flex items-center gap-1"
                      >
                        <MessageSquare className="h-4 w-4" />
                        Messages
                      </button>
                      <button
                        onClick={() => handleBlockToggle(user)}
                        disabled={actionLoading === user.id}
                        className={`px-3 py-1.5 text-sm rounded-lg transition-colors flex items-center gap-1 ${
                          user.is_blocked
                            ? 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50'
                            : 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50'
                        } disabled:opacity-50`}
                      >
                        {actionLoading === user.id ? (
                          <RefreshCw className="h-4 w-4 animate-spin" />
                        ) : user.is_blocked ? (
                          <>
                            <ShieldOff className="h-4 w-4" />
                            Unblock
                          </>
                        ) : (
                          <>
                            <Shield className="h-4 w-4" />
                            Block
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="p-4 border-t border-light-border dark:border-dark-border flex items-center justify-between">
                <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                  Page {currentPage} of {totalPages} ({totalUsers} users)
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                    className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors disabled:opacity-50"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                    disabled={currentPage === totalPages}
                    className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors disabled:opacity-50"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    )
  }

  // Render message history view
  const renderMessageHistory = () => {
    if (!selectedUser) return null

    return (
      <div className="bg-white dark:bg-dark-sidebar rounded-lg shadow-sm border border-light-border dark:border-dark-border">
        {/* Header */}
        <div className="p-4 border-b border-light-border dark:border-dark-border">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={handleBackToDashboard}
                className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
              >
                <ArrowLeft className="h-5 w-5 text-light-text dark:text-dark-text" />
              </button>
              <div>
                <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
                  <MessageSquare className="h-5 w-5" />
                  Message History
                </h2>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                    {selectedUser.phone_number}
                  </span>
                  {selectedUser.is_blocked && (
                    <span className="text-xs px-2 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 rounded-full">
                      Blocked
                    </span>
                  )}
                </div>
              </div>
            </div>

            <button
              onClick={() => handleBlockToggle(selectedUser)}
              disabled={actionLoading === selectedUser.id}
              className={`px-3 py-1.5 text-sm rounded-lg transition-colors flex items-center gap-1 ${
                selectedUser.is_blocked
                  ? 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50'
                  : 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50'
              } disabled:opacity-50`}
            >
              {actionLoading === selectedUser.id ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : selectedUser.is_blocked ? (
                <>
                  <ShieldOff className="h-4 w-4" />
                  Unblock User
                </>
              ) : (
                <>
                  <Shield className="h-4 w-4" />
                  Block User
                </>
              )}
            </button>
          </div>
        </div>

        {/* Messages */}
        {isLoadingMessages ? (
          <div className="p-8 text-center text-light-text-secondary dark:text-dark-text-secondary">
            <RefreshCw className="h-8 w-8 animate-spin mx-auto mb-2" />
            Loading messages...
          </div>
        ) : messages.length === 0 ? (
          <div className="p-8 text-center text-light-text-secondary dark:text-dark-text-secondary">
            <MessageSquare className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>No messages yet.</p>
          </div>
        ) : (
          <>
            <div className="p-4 space-y-4 max-h-[500px] overflow-y-auto">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex ${message.direction === 'outbound' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] rounded-lg p-3 ${
                      message.direction === 'outbound'
                        ? 'bg-primary text-white'
                        : 'bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text'
                    }`}
                  >
                    <p className="text-sm whitespace-pre-wrap">{message.body || '(No content)'}</p>
                    {message.media_urls && message.media_urls.length > 0 && (
                      <div className="mt-2 text-xs opacity-75">
                        {message.media_urls.length} media attachment(s)
                      </div>
                    )}
                    <div className={`text-xs mt-1 ${message.direction === 'outbound' ? 'text-white/70' : 'text-light-text-secondary dark:text-dark-text-secondary'}`}>
                      {formatDate(message.created_at)}
                      {message.status && ` · ${message.status}`}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Pagination */}
            {messagesTotalPages > 1 && (
              <div className="p-4 border-t border-light-border dark:border-dark-border flex items-center justify-between">
                <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                  Page {messagesPage} of {messagesTotalPages}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => loadMessages(selectedUser.id, messagesPage - 1)}
                    disabled={messagesPage === 1 || isLoadingMessages}
                    className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors disabled:opacity-50"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => loadMessages(selectedUser.id, messagesPage + 1)}
                    disabled={messagesPage === messagesTotalPages || isLoadingMessages}
                    className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors disabled:opacity-50"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-light-bg dark:bg-dark-bg">
      {/* Header */}
      <div className="bg-white dark:bg-dark-sidebar border-b border-light-border dark:border-dark-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-4">
              <button
                onClick={onBack}
                className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
              >
                <ArrowLeft className="h-5 w-5 text-light-text dark:text-dark-text" />
              </button>
              <div>
                <h1 className="text-xl font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
                  <MessageSquare className="h-6 w-6 text-green-500" />
                  WhatsApp Admin
                </h1>
                <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                  Monitor WhatsApp activity and manage users
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {viewMode === 'dashboard' ? (
          <>
            {renderStats()}
            {renderUserList()}
          </>
        ) : (
          renderMessageHistory()
        )}
      </div>
    </div>
  )
}
