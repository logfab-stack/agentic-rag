import { useState, useEffect } from 'react'
import { Lightbulb, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react'

interface SuggestedQuestionsProps {
  documentId?: string | null
  onQuestionClick: (question: string) => void
  enabled?: boolean
  className?: string
}

interface SuggestedQuestionsResponse {
  document_id: string
  questions: string[]
  cached: boolean
}

/**
 * SuggestedQuestions component - displays clickable question suggestions for a document
 *
 * Feature #199: Shows 3-5 suggested questions based on document content
 * to help users understand what they can ask about the document.
 */
export function SuggestedQuestions({
  documentId,
  onQuestionClick,
  enabled = true,
  className = ''
}: SuggestedQuestionsProps) {
  const [questions, setQuestions] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(true)
  const [cachedDoc, setCachedDoc] = useState<string | null>(null)

  // Fetch suggested questions when document changes
  useEffect(() => {
    if (!enabled || !documentId || documentId === cachedDoc) {
      return
    }

    const fetchSuggestedQuestions = async () => {
      setLoading(true)
      setError(null)

      try {
        const response = await fetch(`/api/documents/${documentId}/suggested-questions`)

        if (!response.ok) {
          throw new Error('Failed to fetch suggested questions')
        }

        const data: SuggestedQuestionsResponse = await response.json()
        setQuestions(data.questions || [])
        setCachedDoc(documentId)
      } catch (err) {
        console.error('Error fetching suggested questions:', err)
        setError('Could not load suggested questions')
        setQuestions([])
      } finally {
        setLoading(false)
      }
    }

    fetchSuggestedQuestions()
  }, [documentId, enabled, cachedDoc])

  // Clear questions when document is deselected
  useEffect(() => {
    if (!documentId) {
      setQuestions([])
      setCachedDoc(null)
    }
  }, [documentId])

  // Handle regenerate button click
  const handleRegenerate = async () => {
    if (!documentId) return

    setLoading(true)
    setError(null)

    try {
      const response = await fetch(`/api/documents/${documentId}/suggested-questions?regenerate=true`)

      if (!response.ok) {
        throw new Error('Failed to regenerate suggested questions')
      }

      const data: SuggestedQuestionsResponse = await response.json()
      setQuestions(data.questions || [])
    } catch (err) {
      console.error('Error regenerating suggested questions:', err)
      setError('Could not regenerate questions')
    } finally {
      setLoading(false)
    }
  }

  // Don't render if disabled or no questions available (and not loading)
  if (!enabled || (!loading && questions.length === 0 && !error)) {
    return null
  }

  return (
    <div className={`bg-primary/5 dark:bg-primary/10 rounded-xl border border-primary/20 ${className}`}>
      {/* Header with toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 text-left hover:bg-primary/5 dark:hover:bg-primary/10 rounded-t-xl transition-colors"
      >
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-primary/20">
            <Lightbulb size={16} className="text-primary" />
          </div>
          <span className="text-sm font-medium text-light-text dark:text-dark-text">
            Suggested Questions
          </span>
          {questions.length > 0 && (
            <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
              ({questions.length})
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Regenerate button */}
          {questions.length > 0 && !loading && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                handleRegenerate()
              }}
              className="p-1.5 rounded-lg hover:bg-primary/20 text-light-text-secondary dark:text-dark-text-secondary hover:text-primary transition-colors"
              title="Regenerate questions"
            >
              <RefreshCw size={14} />
            </button>
          )}
          {expanded ? (
            <ChevronUp size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
          ) : (
            <ChevronDown size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
          )}
        </div>
      </button>

      {/* Questions list */}
      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          {loading ? (
            <div className="flex items-center gap-2 py-2">
              <div className="animate-spin">
                <RefreshCw size={14} className="text-primary" />
              </div>
              <span className="text-sm text-light-text-secondary dark:text-dark-text-secondary">
                Generating questions...
              </span>
            </div>
          ) : error ? (
            <p className="text-sm text-red-500 py-2">{error}</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {questions.map((question, index) => (
                <button
                  key={index}
                  onClick={() => onQuestionClick(question)}
                  className="text-left px-3 py-2 text-sm bg-white dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg hover:border-primary hover:bg-primary/5 dark:hover:bg-primary/10 transition-colors text-light-text dark:text-dark-text"
                >
                  {question}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default SuggestedQuestions
