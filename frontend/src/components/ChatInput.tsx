import { useState, useRef, KeyboardEvent, FormEvent, forwardRef, useImperativeHandle } from 'react'
import { Send } from 'lucide-react'
import { DocumentScopeSelector, type DocumentScope } from './DocumentScopeSelector'

interface Document {
  id: string
  title: string
  document_type?: string
  collection_id?: string | null
}

interface Collection {
  id: string
  name: string
}

interface ChatInputProps {
  onSendMessage: (message: string) => void
  disabled?: boolean
  placeholder?: string
  // Feature #205: Document scope selector
  documents?: Document[]
  collections?: Collection[]
  scope?: DocumentScope
  onScopeChange?: (scope: DocumentScope) => void
}

export const ChatInput = forwardRef<HTMLTextAreaElement, ChatInputProps>(function ChatInput({
  onSendMessage,
  disabled = false,
  placeholder = 'Ask a question about your documents...',
  documents = [],
  collections = [],
  scope = { type: 'all', label: 'All Documents' },
  onScopeChange
}, ref) {
  const [message, setMessage] = useState('')
  // Ref to prevent double-submission from rapid clicks
  // Using a ref instead of state because state updates are async and may not prevent rapid clicks
  const isSubmittingRef = useRef(false)
  // Internal ref for the textarea
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Expose the textarea ref to parent components
  useImperativeHandle(ref, () => textareaRef.current as HTMLTextAreaElement)

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()

    // Prevent double-submission from rapid clicks
    if (isSubmittingRef.current) {
      return
    }

    if (message.trim() && !disabled) {
      // Set the flag immediately (synchronously) to block subsequent clicks
      isSubmittingRef.current = true

      const messageToSend = message.trim()
      setMessage('')
      onSendMessage(messageToSend)

      // Reset the flag after a short delay to allow normal subsequent messages
      // This delay ensures the button state has time to update
      setTimeout(() => {
        isSubmittingRef.current = false
      }, 100)
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const handleScopeChange = (newScope: DocumentScope) => {
    if (onScopeChange) {
      onScopeChange(newScope)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="border-t border-light-border dark:border-dark-border p-2 md:p-4">
      <div className="max-w-3xl mx-auto">
        {/* Feature #205: Document Scope Selector - shown when documents exist */}
        {documents.length > 0 && onScopeChange && (
          <div className="flex items-center gap-2 mb-2">
            <DocumentScopeSelector
              documents={documents}
              collections={collections}
              scope={scope}
              onScopeChange={handleScopeChange}
              disabled={disabled}
            />
            {scope.type !== 'all' && (
              <span className="text-xs text-light-text-secondary dark:text-dark-text-secondary">
                Searching in: {scope.label}
              </span>
            )}
          </div>
        )}
        <div className="flex gap-2">
          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className="flex-1 px-3 md:px-4 py-3 border border-light-border dark:border-dark-border rounded-lg bg-white dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary resize-none min-h-[44px] max-h-[200px] text-base"
            style={{
              height: 'auto',
              overflowY: message.split('\n').length > 5 ? 'auto' : 'hidden'
            }}
          />
          <button
            type="submit"
            disabled={disabled || !message.trim()}
            className="min-w-[44px] min-h-[44px] px-3 md:px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
            aria-label="Send message"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
      </div>
    </form>
  )
})

export default ChatInput
