import { useState, useCallback, useMemo } from 'react'
import { clsx } from 'clsx'
import { User, Bot, Database, Search, FileText, Wrench, ChevronDown, ChevronUp, Code, Download, CheckCircle, AlertCircle, StickyNote, BookMarked, ThumbsUp, ThumbsDown } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { exportResultsAsCSV } from '../api/export'
import { submitFeedback, submitResponseFeedback } from '../api/feedback'
import { TypewriterText } from './TypewriterText'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp?: Date
  toolUsed?: string
  toolDetails?: Record<string, unknown>
  responseSource?: 'rag' | 'direct' | 'hybrid'
  usedUserNotes?: boolean  // Indicates if user notes were used as sources
  isNew?: boolean  // Feature #201: Indicates this is a newly received message (for typewriter effect)
  isPending?: boolean  // Feature #275: Indicates message is being sent (optimistic UI)
  isPlaceholder?: boolean  // Feature #299: Placeholder message while waiting for AI response
}

interface ChatMessageProps {
  message: Message
  conversationId?: string  // Feature #350: Conversation ID for response feedback
  onShowToast?: (message: string, type: 'success' | 'error') => void
  onAddNote?: (content: string) => void  // Handler to open add note modal with prefilled content
  enableTypewriter?: boolean  // Feature #201: Enable typewriter effect for new messages
  onTypewriterComplete?: () => void  // Feature #201: Callback when typewriter animation completes
}

// Type for chunk feedback state
type FeedbackState = 'none' | 'up' | 'down' | 'loading'

// Interface for vector search chunk results
interface VectorSearchChunk {
  chunk_id?: string
  document_title?: string
  text?: string
  score?: number
  similarity?: number
}

// Component to render a single chunk with feedback buttons
function ChunkWithFeedback({
  chunk,
  queryText,
  onShowToast
}: {
  chunk: VectorSearchChunk
  queryText: string
  onShowToast?: (message: string, type: 'success' | 'error') => void
}) {
  const [feedbackState, setFeedbackState] = useState<FeedbackState>('none')

  const handleFeedback = useCallback(async (value: 1 | -1) => {
    if (!chunk.chunk_id) {
      console.warn('No chunk_id available for feedback')
      return
    }

    // Determine new state based on current state and clicked button
    const clickedButton = value === 1 ? 'up' : 'down'
    const currentState = feedbackState

    // If clicking the same button that's already active, we're changing the vote
    // The backend handles upsert, so we just need to update the UI state
    const newState: FeedbackState = currentState === clickedButton ? clickedButton : clickedButton

    setFeedbackState('loading')

    try {
      await submitFeedback({
        chunk_id: chunk.chunk_id,
        query_text: queryText,
        feedback: value
      })

      setFeedbackState(newState)
      onShowToast?.('Thanks for your feedback!', 'success')
    } catch (error) {
      console.error('Failed to submit feedback:', error)
      setFeedbackState(currentState)
      onShowToast?.('Failed to submit feedback', 'error')
    }
  }, [chunk.chunk_id, queryText, feedbackState, onShowToast])

  const isLoading = feedbackState === 'loading'

  return (
    <div className="bg-light-bg dark:bg-dark-bg p-2 rounded text-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {chunk.document_title && (
            <div className="font-semibold text-primary mb-1">
              {chunk.document_title}
            </div>
          )}
          <p className="text-light-text dark:text-dark-text line-clamp-3">
            {chunk.text}
          </p>
          {(chunk.score !== undefined || chunk.similarity !== undefined) && (
            <div className="text-light-text-secondary dark:text-dark-text-secondary mt-1">
              Relevance: {((chunk.similarity || chunk.score || 0) * 100).toFixed(1)}%
            </div>
          )}
        </div>

        {/* Feedback buttons */}
        {chunk.chunk_id && (
          <div className="flex items-center gap-1 flex-shrink-0 ml-2">
            <button
              onClick={() => handleFeedback(1)}
              disabled={isLoading}
              className={clsx(
                "p-1.5 rounded-full transition-all duration-200",
                feedbackState === 'up'
                  ? "bg-green-100 text-green-600 dark:bg-green-900/50 dark:text-green-400"
                  : "text-light-text-secondary dark:text-dark-text-secondary hover:bg-green-50 hover:text-green-600 dark:hover:bg-green-900/30 dark:hover:text-green-400",
                isLoading && "opacity-50 cursor-not-allowed"
              )}
              title={feedbackState === 'up' ? "Remove upvote" : "Helpful"}
              aria-label={feedbackState === 'up' ? "Remove upvote" : "Mark as helpful"}
            >
              <ThumbsUp className={clsx("w-3.5 h-3.5", feedbackState === 'up' && "fill-current")} />
            </button>
            <button
              onClick={() => handleFeedback(-1)}
              disabled={isLoading}
              className={clsx(
                "p-1.5 rounded-full transition-all duration-200",
                feedbackState === 'down'
                  ? "bg-red-100 text-red-600 dark:bg-red-900/50 dark:text-red-400"
                  : "text-light-text-secondary dark:text-dark-text-secondary hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/30 dark:hover:text-red-400",
                isLoading && "opacity-50 cursor-not-allowed"
              )}
              title={feedbackState === 'down' ? "Remove downvote" : "Not helpful"}
              aria-label={feedbackState === 'down' ? "Remove downvote" : "Mark as not helpful"}
            >
              <ThumbsDown className={clsx("w-3.5 h-3.5", feedbackState === 'down' && "fill-current")} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// Component to render vector search results with feedback
function VectorSearchResults({
  query,
  results,
  onShowToast
}: {
  query: string
  results: VectorSearchChunk[]
  onShowToast?: (message: string, type: 'success' | 'error') => void
}) {
  return (
    <div className="space-y-3">
      {query && (
        <div>
          <div className="text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary mb-1 flex items-center gap-1">
            <Search className="w-3 h-3" />
            Search Query
          </div>
          <p className="text-xs text-light-text dark:text-dark-text bg-light-bg dark:bg-dark-bg p-2 rounded">
            "{query}"
          </p>
        </div>
      )}
      {results && results.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary mb-1 flex items-center gap-1">
            <FileText className="w-3 h-3" />
            Retrieved Chunks ({results.length})
          </div>
          <div className="space-y-2">
            {results.slice(0, 5).map((chunk, index) => (
              <ChunkWithFeedback
                key={chunk.chunk_id || index}
                chunk={chunk}
                queryText={query}
                onShowToast={onShowToast}
              />
            ))}
            {results.length > 5 && (
              <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary italic">
                +{results.length - 5} more chunks...
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// Helper function to format tool details for display
function formatToolDetails(
  toolUsed: string,
  toolDetails: Record<string, unknown>,
  onShowToast?: (message: string, type: 'success' | 'error') => void
): React.ReactNode {
  const toolResult = toolDetails.tool_result as Record<string, unknown> | undefined
  const toolArguments = toolDetails.tool_arguments as Record<string, unknown> | undefined

  if (toolUsed === 'sql_analysis') {
    // Display SQL query and result
    const sqlQuery = toolResult?.sql_query as string | undefined
    const result = toolResult?.result
    const document = toolResult?.document as string | undefined
    const operation = toolResult?.operation as string | undefined
    const column = toolResult?.column as string | undefined
    const sampleRows = toolResult?.sample_rows as Array<Record<string, unknown>> | undefined
    const schema = toolResult?.schema as string[] | undefined

    // Handler for exporting data
    const handleExport = async () => {
      try {
        if (!sampleRows || sampleRows.length === 0) {
          onShowToast?.('No data available to export', 'error')
          return
        }

        const filename = document ? `${document.replace(/[^a-z0-9]/gi, '_')}_export.csv` : 'sql_results.csv'
        await exportResultsAsCSV(sampleRows, filename, schema)
        onShowToast?.('CSV file downloaded successfully', 'success')
      } catch (error) {
        console.error('Export failed:', error)
        onShowToast?.('Failed to export data', 'error')
      }
    }

    return (
      <div className="space-y-3">
        {sqlQuery && (
          <div>
            <div className="text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary mb-1 flex items-center gap-1">
              <Code className="w-3 h-3" />
              SQL Query
            </div>
            <pre className="bg-light-bg dark:bg-dark-bg p-2 rounded text-xs overflow-x-auto font-mono">
              {sqlQuery}
            </pre>
          </div>
        )}
        {document && (
          <div className="text-xs">
            <span className="font-semibold text-light-text-secondary dark:text-dark-text-secondary">Document: </span>
            <span className="text-light-text dark:text-dark-text">{document}</span>
          </div>
        )}
        {operation && column && (
          <div className="text-xs">
            <span className="font-semibold text-light-text-secondary dark:text-dark-text-secondary">Operation: </span>
            <span className="text-light-text dark:text-dark-text">{operation} on {column}</span>
          </div>
        )}
        {result !== undefined && (
          <div className="text-xs">
            <span className="font-semibold text-light-text-secondary dark:text-dark-text-secondary">Result: </span>
            <span className="text-light-text dark:text-dark-text font-mono">
              {typeof result === 'number' ? result.toLocaleString() : String(result)}
            </span>
          </div>
        )}
        {/* Export button for tabular data */}
        {sampleRows && sampleRows.length > 0 && (
          <div>
            <button
              onClick={handleExport}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-primary bg-primary/10 hover:bg-primary/20 rounded transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              Export as CSV
            </button>
          </div>
        )}
      </div>
    )
  }

  if (toolUsed === 'vector_search') {
    // Display search query and retrieved chunks with feedback buttons
    const query = toolArguments?.query as string | undefined
    const results = toolResult?.results as VectorSearchChunk[] | undefined

    return (
      <VectorSearchResults
        query={query || ''}
        results={results || []}
        onShowToast={onShowToast}
      />
    )
  }

  if (toolUsed === 'list_documents') {
    // Display document list info
    const documents = toolResult?.documents as Array<{
      title?: string
      type?: string
      mime_type?: string
    }> | undefined
    const total = toolResult?.total as number | undefined

    return (
      <div className="space-y-3">
        <div className="text-xs">
          <span className="font-semibold text-light-text-secondary dark:text-dark-text-secondary">Documents Found: </span>
          <span className="text-light-text dark:text-dark-text">{total ?? documents?.length ?? 0}</span>
        </div>
        {documents && documents.length > 0 && (
          <div>
            <div className="text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary mb-1">
              Document List
            </div>
            <ul className="space-y-1">
              {documents.slice(0, 10).map((doc, index) => (
                <li key={index} className="text-xs bg-light-bg dark:bg-dark-bg p-1.5 rounded flex items-center gap-2">
                  <FileText className="w-3 h-3 text-light-text-secondary dark:text-dark-text-secondary flex-shrink-0" />
                  <span className="text-light-text dark:text-dark-text">{doc.title}</span>
                  <span className="text-light-text-secondary dark:text-dark-text-secondary ml-auto">
                    ({doc.type})
                  </span>
                </li>
              ))}
              {documents.length > 10 && (
                <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary italic">
                  +{documents.length - 10} more documents...
                </p>
              )}
            </ul>
          </div>
        )}
      </div>
    )
  }

  // Fallback: display raw JSON for unknown tools
  return (
    <div>
      <div className="text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary mb-1">
        Tool Details (Raw)
      </div>
      <pre className="bg-light-bg dark:bg-dark-bg p-2 rounded text-xs overflow-x-auto font-mono">
        {JSON.stringify(toolDetails, null, 2)}
      </pre>
    </div>
  )
}

export function ChatMessage({ message, conversationId, onShowToast, onAddNote, enableTypewriter = false, onTypewriterComplete }: ChatMessageProps) {
  const isUser = message.role === 'user'
  const [isExpanded, setIsExpanded] = useState(false)
  const [typewriterDone, setTypewriterDone] = useState(false)

  // Feature #350: Response-level feedback state
  const [responseFeedback, setResponseFeedback] = useState<'none' | 'up' | 'down' | 'loading'>('none')

  const handleResponseFeedback = useCallback(async (value: 1 | -1) => {
    if (!conversationId || !message.id) return

    const clicked = value === 1 ? 'up' : 'down' as const
    const previous = responseFeedback

    // Toggle off if clicking same button
    if (previous === clicked) return

    setResponseFeedback('loading')

    try {
      await submitResponseFeedback({
        message_id: message.id,
        conversation_id: conversationId,
        rating: value,
      })
      setResponseFeedback(clicked)
      onShowToast?.(value === 1 ? 'Thanks for your feedback!' : 'Thanks, we\'ll work on improving.', 'success')
    } catch (error) {
      console.error('Failed to submit response feedback:', error)
      setResponseFeedback(previous)
      onShowToast?.('Failed to submit feedback', 'error')
    }
  }, [conversationId, message.id, responseFeedback, onShowToast])

  const isFeedbackLoading = responseFeedback === 'loading'

  // Check if we have tool details to show
  const hasToolDetails = !isUser && message.toolUsed && message.toolDetails &&
    Object.keys(message.toolDetails).length > 0

  // Determine if we should use typewriter effect:
  // - Must be an assistant message
  // - Must be marked as new
  // - Typewriter must be enabled
  // - Animation not yet completed
  const shouldUseTypewriter = !isUser && message.isNew && enableTypewriter && !typewriterDone

  // Memoized markdown renderer for typewriter effect
  const renderMarkdown = useMemo(() => {
    return (text: string) => (
      <ReactMarkdown
        components={{
          // Make links open in new tab
          a: ({ ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    )
  }, [])

  // Handle typewriter completion
  const handleTypewriterComplete = useCallback(() => {
    setTypewriterDone(true)
    onTypewriterComplete?.()
  }, [onTypewriterComplete])

  return (
    <div
      className={clsx(
        'flex gap-3 p-4',
        isUser ? 'flex-row-reverse' : 'flex-row'
      )}
    >
      {/* Avatar */}
      <div
        className={clsx(
          'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
          isUser
            ? 'bg-primary text-white'
            : 'bg-light-border dark:bg-dark-border text-light-text dark:text-dark-text'
        )}
      >
        {isUser ? (
          <User className="w-5 h-5" />
        ) : (
          <Bot className="w-5 h-5" />
        )}
      </div>

      {/* Message content */}
      <div
        className={clsx(
          'flex flex-col max-w-[70%]',
          isUser ? 'items-end' : 'items-start'
        )}
      >
        {/* Role label */}
        <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary mb-1">
          {isUser ? 'You' : 'Assistant'}
        </span>

        {/* Message bubble - Feature #275: Add opacity when pending */}
        <div
          className={clsx(
            'rounded-2xl px-4 py-2 transition-opacity duration-200',
            isUser
              ? 'bg-primary text-white rounded-tr-sm'
              : 'bg-light-sidebar dark:bg-dark-sidebar text-light-text dark:text-dark-text rounded-tl-sm border border-light-border dark:border-dark-border',
            message.isPending && 'opacity-70'
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : message.isPlaceholder ? (
            // Feature #299: Placeholder message with loading animation
            <div className="flex items-center gap-2">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
              <span className="text-light-text-secondary dark:text-dark-text-secondary text-sm">
                {message.content || 'Thinking...'}
              </span>
            </div>
          ) : (
            <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-headings:mt-3 prose-headings:mb-2 prose-a:text-primary prose-a:no-underline hover:prose-a:underline">
              {shouldUseTypewriter ? (
                <TypewriterText
                  text={message.content}
                  speed={60} // Characters per second - fast but readable
                  mode="character"
                  renderText={renderMarkdown}
                  onComplete={handleTypewriterComplete}
                />
              ) : (
                <ReactMarkdown
                  components={{
                    // Make links open in new tab
                    a: ({ ...props }) => (
                      <a {...props} target="_blank" rel="noopener noreferrer" />
                    ),
                  }}
                >
                  {message.content}
                </ReactMarkdown>
              )}
            </div>
          )}
        </div>

        {/* Response Source Indicator for assistant messages */}
        {!isUser && message.responseSource && (
          <div className={clsx(
            "mt-2 flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium",
            message.responseSource === 'rag' && "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
            message.responseSource === 'direct' && "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
            message.responseSource === 'hybrid' && "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
          )}>
            {message.responseSource === 'rag' && (
              <>
                <CheckCircle className="w-3 h-3" />
                <span>Based on Documents</span>
              </>
            )}
            {message.responseSource === 'direct' && (
              <>
                <AlertCircle className="w-3 h-3" />
                <span>General Knowledge</span>
              </>
            )}
            {message.responseSource === 'hybrid' && (
              <>
                <CheckCircle className="w-3 h-3" />
                <span>Documents + Knowledge</span>
              </>
            )}
          </div>
        )}

        {/* Tool indicator for assistant messages */}
        {!isUser && message.toolUsed && (
          <div className="mt-2 flex items-center gap-1.5 text-xs px-2.5 py-1 bg-primary/10 text-primary rounded-full">
            {message.toolUsed === 'sql_analysis' && <Database className="w-3 h-3" />}
            {message.toolUsed === 'vector_search' && <Search className="w-3 h-3" />}
            {message.toolUsed === 'list_documents' && <FileText className="w-3 h-3" />}
            {!['sql_analysis', 'vector_search', 'list_documents'].includes(message.toolUsed) && (
              <Wrench className="w-3 h-3" />
            )}
            <span className="font-medium">
              {message.toolUsed === 'sql_analysis' && 'SQL Analysis'}
              {message.toolUsed === 'vector_search' && 'Document Search'}
              {message.toolUsed === 'list_documents' && 'Document List'}
              {!['sql_analysis', 'vector_search', 'list_documents'].includes(message.toolUsed) && message.toolUsed}
            </span>
          </div>
        )}

        {/* Expandable Tool Details Section */}
        {hasToolDetails && (
          <div className="mt-2 w-full">
            {/* Show/Hide Details Button */}
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="flex items-center gap-1 text-xs text-light-text-secondary dark:text-dark-text-secondary hover:text-primary transition-colors py-1"
              aria-expanded={isExpanded}
              aria-label={isExpanded ? 'Hide tool details' : 'Show tool details'}
            >
              {isExpanded ? (
                <>
                  <ChevronUp className="w-3 h-3" />
                  Hide Details
                </>
              ) : (
                <>
                  <ChevronDown className="w-3 h-3" />
                  Show Details
                </>
              )}
            </button>

            {/* Expandable Details Panel */}
            {isExpanded && (
              <div className="mt-2 p-3 bg-light-sidebar dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg animate-in slide-in-from-top-2 duration-200">
                {formatToolDetails(message.toolUsed!, message.toolDetails!, onShowToast)}
              </div>
            )}
          </div>
        )}

        {/* User Notes Indicator - shown when response used user notes as sources */}
        {!isUser && message.usedUserNotes && (
          <div className="mt-2 flex items-center gap-1.5 text-xs px-2.5 py-1 bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 rounded-full font-medium">
            <BookMarked className="w-3 h-3" />
            <span>Used Your Notes</span>
          </div>
        )}

        {/* Feature #350: Response-level feedback + Add Note row */}
        {!isUser && !message.isPlaceholder && (
          <div className="mt-2 flex items-center gap-1">
            {/* Thumbs up/down for the whole response */}
            {conversationId && (
              <div className="flex items-center gap-0.5 mr-1">
                <button
                  onClick={() => handleResponseFeedback(1)}
                  disabled={isFeedbackLoading}
                  className={clsx(
                    "p-1.5 rounded-full transition-all duration-200",
                    responseFeedback === 'up'
                      ? "bg-green-100 text-green-600 dark:bg-green-900/50 dark:text-green-400"
                      : "text-light-text-secondary dark:text-dark-text-secondary hover:bg-green-50 hover:text-green-600 dark:hover:bg-green-900/30 dark:hover:text-green-400",
                    isFeedbackLoading && "opacity-50 cursor-not-allowed"
                  )}
                  title="Good response"
                  aria-label="Rate response as good"
                >
                  <ThumbsUp className={clsx("w-3.5 h-3.5", responseFeedback === 'up' && "fill-current")} />
                </button>
                <button
                  onClick={() => handleResponseFeedback(-1)}
                  disabled={isFeedbackLoading}
                  className={clsx(
                    "p-1.5 rounded-full transition-all duration-200",
                    responseFeedback === 'down'
                      ? "bg-red-100 text-red-600 dark:bg-red-900/50 dark:text-red-400"
                      : "text-light-text-secondary dark:text-dark-text-secondary hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/30 dark:hover:text-red-400",
                    isFeedbackLoading && "opacity-50 cursor-not-allowed"
                  )}
                  title="Bad response"
                  aria-label="Rate response as bad"
                >
                  <ThumbsDown className={clsx("w-3.5 h-3.5", responseFeedback === 'down' && "fill-current")} />
                </button>
              </div>
            )}

            {/* Add Note button */}
            {onAddNote && (
              <button
                onClick={() => onAddNote(message.content)}
                className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 text-light-text-secondary dark:text-dark-text-secondary hover:text-primary hover:bg-primary/10 rounded-full transition-colors"
                title="Save this response as a note for future queries"
              >
                <StickyNote className="w-3.5 h-3.5" />
                <span>Add Note</span>
              </button>
            )}
          </div>
        )}

        {/* Timestamp - Feature #275: Show "Sending..." when pending */}
        {message.timestamp && (
          <span className="mt-1 text-xs text-light-text-secondary dark:text-dark-text-secondary">
            {message.isPending ? (
              <span className="flex items-center gap-1">
                <span className="inline-block w-1 h-1 bg-current rounded-full animate-pulse" />
                Sending...
              </span>
            ) : (
              message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            )}
          </span>
        )}
      </div>
    </div>
  )
}

export default ChatMessage
