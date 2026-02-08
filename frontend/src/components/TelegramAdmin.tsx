/**
 * Telegram Admin Dashboard
 *
 * Feature #314: Telegram admin panel in UI
 *
 * Provides UI for monitoring Telegram Bot activity:
 * - User list with chat_id, username, activity, message counts
 * - Message history per user
 * - Statistics (messages today/week/month)
 * - Send test messages to users
 */

import { useState, useEffect, useCallback } from 'react'
import {
  ArrowLeft,
  MessageSquare,
  Users,
  RefreshCw,
  Search,
  ChevronLeft,
  ChevronRight,
  Clock,
  MessageCircle,
  TrendingUp,
  CheckCircle,
  AlertCircle,
  Send,
  X,
  AtSign
} from 'lucide-react'
import {
  fetchTelegramStats,
  fetchTelegramUsers,
  fetchTelegramUserMessages,
  sendTelegramTestMessage,
  type TelegramUser,
  type TelegramMessage,
  type TelegramStats,
  type TelegramUserListResponse,
  type TelegramMessageListResponse
} from '../api/telegram'

interface TelegramAdminProps {
  onBack: () => void
}

type ViewMode = 'dashboard' | 'messages'

export function TelegramAdmin({ onBack }: TelegramAdminProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('dashboard')
  const [stats, setStats] = useState<TelegramStats | null>(null)
  const [users, setUsers] = useState<TelegramUser[]>([])
  const [totalUsers, setTotalUsers] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedUser, setSelectedUser] = useState<TelegramUser | null>(null)
  const [messages, setMessages] = useState<TelegramMessage[]>([])
  const [messagesPage, setMessagesPage] = useState(1)
  const [messagesTotalPages, setMessagesTotalPages] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingMessages, setIsLoadingMessages] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSendModalOpen, setIsSendModalOpen] = useState(false)
  const [sendMessageText, setSendMessageText] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [sendResult, setSendResult] = useState<{ success: boolean; message: string } | null>(null)

  // Load stats
  const loadStats = useCallback(async () => {
    try {
      const data = await fetchTelegramStats()
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
      const data: TelegramUserListResponse = await fetchTelegramUsers(
        currentPage,
        20,
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
  }, [currentPage, searchQuery])

  // Load messages for selected user
  const loadMessages = useCallback(async (chatId: number, page: number = 1) => {
    setIsLoadingMessages(true)
    try {
      const data: TelegramMessageListResponse = await fetchTelegramUserMessages(chatId, page, 50)
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

  // View user messages
  const handleViewMessages = (user: TelegramUser) => {
    setSelectedUser(user)
    setViewMode('messages')
    loadMessages(user.chat_id)
  }

  // Back to dashboard
  const handleBackToDashboard = () => {
    setViewMode('dashboard')
    setSelectedUser(null)
    setMessages([])
    setMessagesPage(1)
  }

  // Open send message modal
  const handleOpenSendModal = (user: TelegramUser) => {
    setSelectedUser(user)
    setSendMessageText('')
    setSendResult(null)
    setIsSendModalOpen(true)
  }

  // Send test message
  const handleSendMessage = async () => {
    if (!selectedUser || !sendMessageText.trim()) return

    setIsSending(true)
    setSendResult(null)

    try {
      const result = await sendTelegramTestMessage(selectedUser.chat_id, sendMessageText.trim())
      if (result.success) {
        setSendResult({ success: true, message: `Message sent successfully (ID: ${result.message_id})` })
        // Refresh messages if we're viewing this user's messages
        if (viewMode === 'messages') {
          loadMessages(selectedUser.chat_id, 1)
        }
      } else {
        setSendResult({ success: false, message: result.error || 'Failed to send message' })
      }
    } catch (err) {
      setSendResult({ success: false, message: err instanceof Error ? err.message : 'Unknown error' })
    } finally {
      setIsSending(false)
    }
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
  const formatRelativeTime = (dateString: string | null) => {
    if (!dateString) return 'Never'
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

  // Get display name for user
  const getDisplayName = (user: TelegramUser) => {
    if (user.first_name && user.last_name) {
      return `${user.first_name} ${user.last_name}`
    }
    if (user.first_name) return user.first_name
    if (user.username) return `@${user.username}`
    return `Chat ${user.chat_id}`
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
      { label: 'Inbound', value: stats.inbound_messages, icon: MessageSquare, color: 'text-cyan-500' },
      { label: 'Outbound', value: stats.outbound_messages, icon: Send, color: 'text-orange-500' },
    ]

    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-8 gap-4 mb-6">
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
        {/* Header with search */}
        <div className="p-4 border-b border-light-border dark:border-dark-border">
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <Users className="h-5 w-5" />
              Telegram Users
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
                    placeholder="Search users..."
                    className="pl-9 pr-4 py-2 w-full sm:w-48 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  />
                </div>
              </form>

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
            <p>No Telegram users yet.</p>
            <p className="text-sm mt-1">Users will appear here when they message your Telegram Bot.</p>
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
                      <div className="w-10 h-10 rounded-full flex items-center justify-center bg-blue-100 dark:bg-blue-900/30">
                        <AtSign className="h-5 w-5 text-blue-500" />
                      </div>

                      {/* User info */}
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-light-text dark:text-dark-text">
                            {getDisplayName(user)}
                          </span>
                          {user.username && (
                            <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                              @{user.username}
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-light-text-secondary dark:text-dark-text-secondary mt-0.5">
                          Chat ID: {user.chat_id}
                        </div>
                        <div className="flex items-center gap-4 mt-1 text-xs text-light-text-secondary dark:text-dark-text-secondary">
                          <span className="flex items-center gap-1">
                            <MessageSquare className="h-3 w-3" />
                            {user.message_count} messages
                          </span>
                          <span className="flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {formatRelativeTime(user.last_message_at)}
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
                        onClick={() => handleOpenSendModal(user)}
                        className="px-3 py-1.5 text-sm bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded-lg hover:bg-blue-200 dark:hover:bg-blue-900/50 transition-colors flex items-center gap-1"
                      >
                        <Send className="h-4 w-4" />
                        Send
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
                    {getDisplayName(selectedUser)}
                  </span>
                  {selectedUser.username && (
                    <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                      @{selectedUser.username}
                    </span>
                  )}
                  <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                    (ID: {selectedUser.chat_id})
                  </span>
                </div>
              </div>
            </div>

            <button
              onClick={() => handleOpenSendModal(selectedUser)}
              className="px-3 py-1.5 text-sm bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded-lg hover:bg-blue-200 dark:hover:bg-blue-900/50 transition-colors flex items-center gap-1"
            >
              <Send className="h-4 w-4" />
              Send Message
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
                    <p className="text-sm whitespace-pre-wrap">{message.content || '(No content)'}</p>
                    {message.media_type && (
                      <div className="mt-2 text-xs opacity-75">
                        Media: {message.media_type}
                      </div>
                    )}
                    <div className={`text-xs mt-1 ${message.direction === 'outbound' ? 'text-white/70' : 'text-light-text-secondary dark:text-dark-text-secondary'}`}>
                      {formatDate(message.created_at)}
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
                    onClick={() => loadMessages(selectedUser.chat_id, messagesPage - 1)}
                    disabled={messagesPage === 1 || isLoadingMessages}
                    className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors disabled:opacity-50"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => loadMessages(selectedUser.chat_id, messagesPage + 1)}
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

  // Render send message modal
  const renderSendModal = () => {
    if (!isSendModalOpen || !selectedUser) return null

    return (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setIsSendModalOpen(false)}>
        <div
          className="bg-white dark:bg-dark-sidebar rounded-lg shadow-xl p-6 w-full max-w-md mx-4"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-light-text dark:text-dark-text flex items-center gap-2">
              <Send className="h-5 w-5 text-blue-500" />
              Send Test Message
            </h3>
            <button
              onClick={() => setIsSendModalOpen(false)}
              className="p-1 hover:bg-light-border dark:hover:bg-dark-border rounded transition-colors"
            >
              <X className="h-5 w-5 text-light-text-secondary dark:text-dark-text-secondary" />
            </button>
          </div>

          <div className="text-sm text-light-text-secondary dark:text-dark-text-secondary mb-4">
            Sending to: <span className="font-medium text-light-text dark:text-dark-text">{getDisplayName(selectedUser)}</span>
            {selectedUser.username && <span className="ml-1">(@{selectedUser.username})</span>}
          </div>

          <textarea
            value={sendMessageText}
            onChange={(e) => setSendMessageText(e.target.value)}
            placeholder="Enter your message..."
            rows={4}
            className="w-full px-4 py-3 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent resize-none"
            autoFocus
          />

          {sendResult && (
            <div className={`mt-3 p-3 rounded-lg text-sm ${sendResult.success ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400' : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'}`}>
              {sendResult.message}
            </div>
          )}

          <div className="flex justify-end gap-3 mt-4">
            <button
              onClick={() => setIsSendModalOpen(false)}
              className="px-4 py-2 text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSendMessage}
              disabled={!sendMessageText.trim() || isSending}
              className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isSending ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              {isSending ? 'Sending...' : 'Send'}
            </button>
          </div>
        </div>
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
                  <MessageSquare className="h-6 w-6 text-blue-500" />
                  Telegram Admin
                </h1>
                <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                  Monitor Telegram Bot activity and manage users
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

      {/* Send Message Modal */}
      {renderSendModal()}
    </div>
  )
}
