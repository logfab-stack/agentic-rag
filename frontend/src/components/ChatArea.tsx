import { useRef, useEffect, useState, useCallback } from 'react'
import { ChatMessage, Message } from './ChatMessage'
import { ChatInput } from './ChatInput'
import { SuggestedQuestions } from './SuggestedQuestions'
import { type DocumentScope } from './DocumentScopeSelector'
import { MessageSquare, Download, FileStack, ChevronDown, FileText } from 'lucide-react'

// Feature #299: Tool status messages removed - now using placeholder messages in the message list
// for optimistic UI updates. The placeholder message shows inline loading animation.

interface DocumentInfo {
  id: string
  title: string
  document_type?: string
  collection_id?: string | null
}

interface CollectionInfo {
  id: string
  name: string
}

interface ChatAreaProps {
  messages: Message[]
  onSendMessage: (message: string, scope?: DocumentScope) => void
  isLoading?: boolean
  onShowToast?: (message: string, type: 'success' | 'error') => void
  conversationTitle?: string
  onExportClick?: () => void
  onAddNote?: (content: string) => void  // Handler to open add note modal
  documents?: DocumentInfo[]  // Available documents for suggested questions
  collections?: CollectionInfo[]  // Feature #205: Available collections
  enableSuggestedQuestions?: boolean  // Feature #199: Whether to show suggested questions
  enableTypewriter?: boolean  // Feature #201: Whether to enable typewriter effect for new messages
  conversationId?: string  // Feature #350: Current conversation ID for response feedback
  // Feature #205: Document scope state management
  scope?: DocumentScope
  onScopeChange?: (scope: DocumentScope) => void
}

export function ChatArea({ messages, onSendMessage, isLoading = false, onShowToast, conversationTitle, onExportClick, onAddNote, documents = [], collections = [], enableSuggestedQuestions = true, enableTypewriter = true, conversationId, scope, onScopeChange }: ChatAreaProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const chatInputRef = useRef<HTMLTextAreaElement>(null)
  // Track previous isLoading state to detect transition from true to false
  const wasLoadingRef = useRef(false)
  // Selected document for suggested questions (Feature #199)
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null)
  const [showDocumentDropdown, setShowDocumentDropdown] = useState(false)

  // Feature #300: Robust scroll-to-bottom helper with retry mechanism
  // Get the scrollable container (parent of messagesEndRef)
  const getScrollContainer = useCallback(() => {
    return messagesEndRef.current?.parentElement?.parentElement
  }, [])

  // Check if we're already at the bottom (within a small threshold)
  const isAtBottom = useCallback(() => {
    const container = getScrollContainer()
    if (!container) return true
    const threshold = 50 // pixels of tolerance
    return container.scrollHeight - container.scrollTop - container.clientHeight < threshold
  }, [getScrollContainer])

  // Feature #300: Scroll to bottom with verification and retry mechanism
  // Uses requestAnimationFrame to wait for DOM update, with automatic retries if scroll fails
  const scrollToBottomWithRetry = useCallback((attempt: number = 1) => {
    // Use requestAnimationFrame to ensure DOM is updated
    requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })

      // Feature #300: Verify scroll worked and retry if needed (up to 3 attempts)
      if (attempt < 3) {
        setTimeout(() => {
          if (!isAtBottom()) {
            // Scroll didn't work (maybe content still loading), retry
            scrollToBottomWithRetry(attempt + 1)
          }
        }, 100 * attempt) // Increasing delay: 100ms, 200ms
      }
    })
  }, [isAtBottom])

  // Feature #300: Scroll to bottom when messages change
  useEffect(() => {
    // Primary scroll
    scrollToBottomWithRetry(1)

    // Feature #300: Additional fallback for long messages that change container height
    // This handles cases where content height changes after initial render (e.g., code blocks)
    const fallbackTimeout = setTimeout(() => {
      if (!isAtBottom()) {
        scrollToBottomWithRetry(1)
      }
    }, 300)

    return () => {
      clearTimeout(fallbackTimeout)
    }
  }, [messages, scrollToBottomWithRetry, isAtBottom])

  // Auto-focus chat input after AI response completes (isLoading transitions from true to false)
  // Also scrolls to bottom when loading state changes (thinking indicator appears)
  useEffect(() => {
    if (wasLoadingRef.current && !isLoading) {
      // Small delay to ensure the UI has settled
      setTimeout(() => {
        chatInputRef.current?.focus()
      }, 100)
    }

    // Feature #300: Scroll when loading indicator appears (using retry mechanism)
    if (isLoading) {
      scrollToBottomWithRetry(1)
    }

    wasLoadingRef.current = isLoading
  }, [isLoading, scrollToBottomWithRetry])

  // Feature #299: Removed thinking status cycling - now using placeholder messages
  // The placeholder message in the message list provides visual feedback

  return (
    <main className="flex-1 flex flex-col bg-light-bg dark:bg-dark-bg w-full">
      {/* Conversation Header with Export Button - Only shown when there are messages */}
      {messages.length > 0 && (
        <div className="sticky top-0 z-10 flex items-center justify-between px-4 py-2 bg-light-bg/95 dark:bg-dark-bg/95 backdrop-blur-sm border-b border-light-border dark:border-dark-border">
          <div className="flex items-center gap-2 ml-12 md:ml-0 min-w-0">
            <MessageSquare size={16} className="text-primary flex-shrink-0" />
            <h2 className="text-sm font-medium text-light-text dark:text-dark-text truncate">
              {conversationTitle || 'New Conversation'}
            </h2>
          </div>
          {onExportClick && (
            <button
              onClick={onExportClick}
              className="flex items-center gap-2 px-3 py-1.5 text-sm text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
              title="Export conversation"
            >
              <Download size={16} />
              <span className="hidden sm:inline">Export</span>
            </button>
          )}
        </div>
      )}
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          // Empty state - with padding for mobile menu button
          <div className="h-full flex flex-col items-center justify-center p-8 pt-16 md:pt-8">
            <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
              <MessageSquare className="w-8 h-8 text-primary" />
            </div>
            <h1 className="text-xl md:text-2xl font-semibold text-light-text dark:text-dark-text mb-2 text-center">
              Agentic RAG System
            </h1>
            <p className="text-light-text-secondary dark:text-dark-text-secondary text-center max-w-md text-sm md:text-base px-4 mb-6">
              Welcome! Upload documents and start asking questions. I can analyze both
              text documents (PDF, TXT, Word, Markdown) and tabular data (CSV, Excel, JSON).
            </p>

            {/* Suggested Questions Section - Feature #199 */}
            {enableSuggestedQuestions && documents.length > 0 && (
              <div className="w-full max-w-xl px-4">
                {/* Document Selector */}
                <div className="relative mb-3">
                  <button
                    onClick={() => setShowDocumentDropdown(!showDocumentDropdown)}
                    className="w-full flex items-center justify-between px-4 py-2.5 bg-light-sidebar dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg hover:border-primary transition-colors text-left"
                  >
                    <div className="flex items-center gap-2">
                      <FileStack size={16} className="text-primary" />
                      <span className="text-sm text-light-text dark:text-dark-text">
                        {selectedDocumentId
                          ? documents.find(d => d.id === selectedDocumentId)?.title || 'Select a document'
                          : 'Select a document for suggestions'}
                      </span>
                    </div>
                    <ChevronDown size={16} className={`text-light-text-secondary dark:text-dark-text-secondary transition-transform ${showDocumentDropdown ? 'rotate-180' : ''}`} />
                  </button>

                  {/* Dropdown Menu */}
                  {showDocumentDropdown && (
                    <div className="absolute top-full left-0 right-0 mt-1 bg-light-sidebar dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg shadow-lg z-10 max-h-60 overflow-y-auto">
                      {documents.map((doc) => (
                        <button
                          key={doc.id}
                          onClick={() => {
                            setSelectedDocumentId(doc.id)
                            setShowDocumentDropdown(false)
                          }}
                          className={`w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-primary/5 dark:hover:bg-primary/10 transition-colors ${
                            selectedDocumentId === doc.id ? 'bg-primary/10' : ''
                          }`}
                        >
                          <FileText size={14} className="text-light-text-secondary dark:text-dark-text-secondary flex-shrink-0" />
                          <span className="text-sm text-light-text dark:text-dark-text truncate">{doc.title}</span>
                          {doc.document_type && (
                            <span className="ml-auto text-xs text-light-text-secondary dark:text-dark-text-secondary">
                              {doc.document_type === 'structured' ? 'Data' : 'Text'}
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Suggested Questions */}
                {selectedDocumentId && (
                  <SuggestedQuestions
                    documentId={selectedDocumentId}
                    onQuestionClick={(question) => onSendMessage(question)}
                    enabled={enableSuggestedQuestions}
                  />
                )}
              </div>
            )}
          </div>
        ) : (
          // Message list - with padding for mobile menu button
          <div className="max-w-3xl mx-auto py-4 pt-16 md:pt-4 px-2 md:px-4">
            {messages.map((message) => (
              <ChatMessage key={message.id} message={message} conversationId={conversationId} onShowToast={onShowToast} onAddNote={onAddNote} enableTypewriter={enableTypewriter} />
            ))}

            {/* Feature #299: Loading indicator removed - now using placeholder messages for optimistic UI
                The placeholder message (isPlaceholder=true) shows the loading animation inline
                with the messages for a more responsive and consistent user experience */}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area - Feature #205: Pass scope selector props */}
      <ChatInput
        ref={chatInputRef}
        onSendMessage={(message) => onSendMessage(message, scope)}
        disabled={isLoading}
        documents={documents}
        collections={collections}
        scope={scope || { type: 'all', label: 'All Documents' }}
        onScopeChange={onScopeChange}
      />
    </main>
  )
}

export default ChatArea
