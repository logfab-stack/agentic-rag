import { useState, useEffect, useCallback, useRef } from 'react'
import { BrowserRouter as Router, Routes, Route, useNavigate, useParams, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Menu, X, AlertTriangle, Home, Plus } from 'lucide-react'
import { Sidebar, ChatArea, Message, UploadModal, DocumentEditModal, DocumentDetailsModal, SettingsModal, ConfirmDeleteModal, NewCollectionModal, EditCollectionModal, WelcomeModal, ExportModal, AddNoteModal, ToastProvider, useToast, WhatsAppAdmin, TelegramAdmin, NotesPage, AdminMaintenancePage, SettingsPage, DocsPage, NavSidebar, DocumentsPage, Dashboard, type DocumentScope } from './components'
import { createConversation, fetchConversations, fetchConversation, sendChatMessage, deleteConversation, deleteDocument, fetchCollections, deleteCollection, archiveConversation, unarchiveConversation, renameConversation } from './api'
import type { Document, Conversation, Collection } from './types'

// Generate unique ID for messages
const generateId = () => crypto.randomUUID()

// ChatPage component with proper sidebar and chat area
const ChatPage = () => {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false)
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)
  const [isDetailsModalOpen, setIsDetailsModalOpen] = useState(false)
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false)
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deletingConversation, setDeletingConversation] = useState<Conversation | null>(null)
  const [isDeleteDocModalOpen, setIsDeleteDocModalOpen] = useState(false)
  const [isDeletingDocument, setIsDeletingDocument] = useState(false)
  const [deletingDocument, setDeletingDocument] = useState<Document | null>(null)
  const [editingDocument, setEditingDocument] = useState<Document | null>(null)
  const [viewingDocument, setViewingDocument] = useState<Document | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [isNewCollectionModalOpen, setIsNewCollectionModalOpen] = useState(false)
  const [isEditCollectionModalOpen, setIsEditCollectionModalOpen] = useState(false)
  const [editingCollection, setEditingCollection] = useState<Collection | null>(null)
  const [isDeleteCollectionModalOpen, setIsDeleteCollectionModalOpen] = useState(false)
  const [deletingCollection, setDeletingCollection] = useState<Collection | null>(null)
  const [isDeletingCollection, setIsDeletingCollection] = useState(false)
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false)
  const [isWelcomeModalOpen, setIsWelcomeModalOpen] = useState(false)
  const [conversationError, setConversationError] = useState<string | null>(null)
  const [conversationSearchQuery, setConversationSearchQuery] = useState('')
  const [isRenameModalOpen, setIsRenameModalOpen] = useState(false)
  const [renamingConversation, setRenamingConversation] = useState<Conversation | null>(null)
  const [renameTitle, setRenameTitle] = useState('')
  const [isExportModalOpen, setIsExportModalOpen] = useState(false)
  const [exportingConversation, setExportingConversation] = useState<Conversation | null>(null)
  const [isAddNoteModalOpen, setIsAddNoteModalOpen] = useState(false)
  const [addNoteContent, setAddNoteContent] = useState('')
  // Feature #205: Document scope selector state
  const [documentScope, setDocumentScope] = useState<DocumentScope>({ type: 'all', label: 'All Documents' })
  const navigate = useNavigate()
  const { conversationId } = useParams<{ conversationId: string }>()
  const location = useLocation() // Track location changes for back button navigation
  const { showToast } = useToast()
  const [currentPath, setCurrentPath] = useState(window.location.pathname)
  // Feature #274: Ref to track when we should skip reloading conversation
  // This prevents the race condition where navigating after sending a message
  // would trigger loadConversation() which overwrites the locally-set messages
  const skipNextConversationLoadRef = useRef(false)

  // Listen for popstate events (browser back/forward) to update currentPath
  // This ensures sidebar highlight updates correctly when using browser navigation
  useEffect(() => {
    const handlePopState = () => {
      // Use setTimeout to ensure the browser URL has updated
      setTimeout(() => {
        setCurrentPath(window.location.pathname)
      }, 0)
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  // Also sync currentPath when location changes via React Router
  useEffect(() => {
    setCurrentPath(location.pathname)
  }, [location.pathname])

  // Apply theme from localStorage on mount
  // This ensures theme persists after React mounts (handles HMR/StrictMode cases)
  useEffect(() => {
    try {
      const savedSettings = localStorage.getItem('rag-settings')
      if (savedSettings) {
        const parsed = JSON.parse(savedSettings)
        const theme = parsed.theme || 'system'
        const root = document.documentElement

        if (theme === 'system') {
          const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
          root.classList.toggle('dark', prefersDark)
        } else {
          root.classList.toggle('dark', theme === 'dark')
        }
      }
    } catch (e) {
      console.warn('Failed to apply theme from localStorage:', e)
    }
  }, [])

  // Fetch documents from API
  const fetchDocumentsFromApi = useCallback(async () => {
    try {
      const response = await fetch('/api/documents/')
      if (response.ok) {
        const data = await response.json()
        setDocuments(data)
      }
    } catch (error) {
      console.error('Failed to fetch documents:', error)
    }
  }, [])

  // Load conversations
  const loadConversations = useCallback(async (searchQuery?: string) => {
    try {
      const data = await fetchConversations(searchQuery)
      setConversations(data)
    } catch (error) {
      console.error('Failed to load conversations:', error)
    }
  }, [])

  // Load collections
  const loadCollections = useCallback(async () => {
    try {
      const data = await fetchCollections()
      setCollections(data)
    } catch (error) {
      console.error('Failed to load collections:', error)
    }
  }, [])

  // Load a specific conversation
  const loadConversation = useCallback(async (id: string) => {
    // Clear any previous error state
    setConversationError(null)
    try {
      const data = await fetchConversation(id)
      setCurrentConversationId(id)
      // Convert API messages to UI message format
      setMessages(data.messages.map(msg => ({
        id: msg.id,
        role: msg.role,
        content: msg.content,
        timestamp: new Date(msg.created_at),
        toolUsed: msg.tool_used,
        toolDetails: msg.tool_details,
        responseSource: msg.response_source
      })))
    } catch (error) {
      console.error('Failed to load conversation:', error)
      // Set error state for invalid/not-found conversation
      setConversationError(`Conversation not found. The conversation with ID "${id}" does not exist or may have been deleted.`)
      setMessages([])
      setCurrentConversationId(null)
    }
  }, [])

  // Fetch data on mount
  useEffect(() => {
    fetchDocumentsFromApi()
    loadConversations()
    loadCollections()
  }, [fetchDocumentsFromApi, loadConversations, loadCollections])

  // Handle conversation search with debouncing
  useEffect(() => {
    const debounceTimer = setTimeout(() => {
      loadConversations(conversationSearchQuery || undefined)
    }, 300) // 300ms debounce

    return () => clearTimeout(debounceTimer)
  }, [conversationSearchQuery, loadConversations])

  // Check for first launch and show welcome modal
  useEffect(() => {
    const hasSeenWelcome = localStorage.getItem('rag-welcome-seen')
    if (!hasSeenWelcome) {
      setIsWelcomeModalOpen(true)
    }
  }, [])

  // Load conversation when URL parameter changes
  // Use location.pathname to ensure proper state updates on browser back button navigation
  useEffect(() => {
    // Check if we're on the home page by pathname
    // This ensures proper state clearing when using browser back button
    const isHomePage = location.pathname === '/'

    if (isHomePage) {
      // On home page, always clear conversation state
      setMessages([])
      setCurrentConversationId(null)
      setConversationError(null)
    } else if (conversationId) {
      // Feature #274: Skip loading if we just sent a message and already have the data
      // This prevents the race condition where the API fetch would overwrite local messages
      if (skipNextConversationLoadRef.current) {
        skipNextConversationLoadRef.current = false
        return
      }
      // On conversation page, load the conversation
      loadConversation(conversationId)
    }
  }, [conversationId, loadConversation, location.pathname])

  // Feature #275/#299: Memoized message handler with optimistic UI updates
  const handleSendMessage = useCallback(async (content: string, scope?: DocumentScope) => {
    // Generate message IDs for tracking
    const userMessageId = generateId()
    const placeholderMessageId = generateId()

    // Feature #275: Add user message to UI immediately with isPending=true
    const userMessage: Message = {
      id: userMessageId,
      role: 'user',
      content,
      timestamp: new Date(),
      isPending: true  // Show sending state
    }

    // Feature #299: Add placeholder assistant message with loading indicator
    const placeholderMessage: Message = {
      id: placeholderMessageId,
      role: 'assistant',
      content: 'Analyzing your question...',
      timestamp: new Date(),
      isPlaceholder: true  // Shows loading animation
    }

    // Add both messages immediately for responsive UI
    setMessages(prev => [...prev, userMessage, placeholderMessage])

    // Show loading indicator (for ChatInput disabled state)
    setIsLoading(true)

    // Track when we started loading to ensure minimum display time
    const loadingStartTime = Date.now()
    const MINIMUM_LOADING_DURATION = 500 // ms - reduced since placeholder provides visual feedback

    try {
      // Get model from settings
      const savedSettings = localStorage.getItem('rag-settings')
      const settings = savedSettings ? JSON.parse(savedSettings) : {}
      const model = settings.llm_model || undefined

      // Feature #205: Build request with document scope
      const currentScope = scope || documentScope
      const requestPayload: Parameters<typeof sendChatMessage>[0] = {
        message: content,
        conversation_id: currentConversationId || undefined,
        model
      }

      // Add document_ids or collection_id based on scope type
      if (currentScope.type === 'documents' && currentScope.documentIds && currentScope.documentIds.length > 0) {
        requestPayload.document_ids = currentScope.documentIds
      } else if (currentScope.type === 'collection' && currentScope.collectionId) {
        requestPayload.collection_id = currentScope.collectionId
      }

      // Send message to backend API
      const response = await sendChatMessage(requestPayload)

      // Calculate how long the request took
      const elapsedTime = Date.now() - loadingStartTime

      // If the response came back too quickly, wait a bit longer
      // to ensure users see the thinking indicator
      if (elapsedTime < MINIMUM_LOADING_DURATION) {
        await new Promise(resolve => setTimeout(resolve, MINIMUM_LOADING_DURATION - elapsedTime))
      }

      // Feature #299: Replace placeholder with actual assistant message
      // Also update user message to remove pending state
      setMessages(prev => prev.map(msg => {
        if (msg.id === userMessageId) {
          return { ...msg, isPending: false }
        }
        if (msg.id === placeholderMessageId) {
          // Replace placeholder with actual response
          return {
            id: response.id,
            role: 'assistant' as const,
            content: response.content,
            timestamp: new Date(response.created_at),
            toolUsed: response.tool_used || undefined,
            toolDetails: response.tool_details || undefined,
            responseSource: response.response_source || undefined,
            isNew: true,  // Feature #201: Enable typewriter effect for this new message
            isPlaceholder: false
          }
        }
        return msg
      }))

      // Update conversation ID if a new one was created
      if (!currentConversationId && response.conversation_id) {
        setCurrentConversationId(response.conversation_id)
        // Feature #274: Skip the next conversation load to prevent race condition
        // We already have the messages locally, no need to fetch from API
        skipNextConversationLoadRef.current = true
        navigate(`/chat/${response.conversation_id}`)
        // Refresh conversation list to show the new conversation
        await loadConversations()
      }
    } catch (error) {
      console.error('Failed to send message:', error)
      // Feature #299: Remove placeholder and show error toast
      setMessages(prev => prev
        .filter(msg => msg.id !== placeholderMessageId)  // Remove placeholder
        .map(msg => msg.id === userMessageId ? { ...msg, isPending: false } : msg)  // Update user message
      )
      // Feature #299: Show error toast instead of adding error message
      showToast('error', 'Failed to send message. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }, [currentConversationId, documentScope, loadConversations, navigate, showToast])

  const handleNewChat = async () => {
    try {
      // Create a new conversation via API
      const newConversation = await createConversation()
      // Optimistically add new conversation to the list immediately
      setConversations(prev => [newConversation, ...prev])
      // Clear messages and set current conversation
      setMessages([])
      setCurrentConversationId(newConversation.id)
      // Navigate to the new conversation
      navigate(`/chat/${newConversation.id}`)
      // No need to refetch - optimistic update already added the conversation
    } catch (error) {
      console.error('Failed to create new conversation:', error)
      // Fallback: just clear messages locally
      setMessages([])
      setCurrentConversationId(null)
      navigate('/')
    }
  }

  const handleSelectConversation = (id: string) => {
    navigate(`/chat/${id}`)
  }

  const handleSettingsClick = () => {
    navigate('/settings')
  }

  const handleUploadClick = () => {
    setIsUploadModalOpen(true)
  }

  const handleNewCollectionClick = () => {
    setIsNewCollectionModalOpen(true)
  }

  const handleCollectionCreated = (newCollection: Collection) => {
    // Add the new collection to the list
    setCollections(prev => [...prev, newCollection])
  }

  const handleEditCollection = (collection: Collection) => {
    setEditingCollection(collection)
    setIsEditCollectionModalOpen(true)
  }

  const handleCollectionUpdated = (updatedCollection: Collection) => {
    // Update the collection in the list
    setCollections(prev =>
      prev.map(c => c.id === updatedCollection.id ? updatedCollection : c)
    )
  }

  const handleDeleteCollection = (collection: Collection) => {
    setDeletingCollection(collection)
    setIsDeleteCollectionModalOpen(true)
  }

  const confirmDeleteCollection = async () => {
    if (!deletingCollection) return

    setIsDeletingCollection(true)
    try {
      await deleteCollection(deletingCollection.id)

      // Remove from local state
      setCollections(prev => prev.filter(c => c.id !== deletingCollection.id))

      // Refresh documents list since docs are moved to uncategorized
      await fetchDocumentsFromApi()

      // Show success toast
      showToast('success', `Collection "${deletingCollection.name}" deleted. Documents moved to Uncategorized.`)

      // Close modal
      setIsDeleteCollectionModalOpen(false)
      setDeletingCollection(null)
    } catch (error) {
      console.error('Failed to delete collection:', error)
      showToast('error', 'Failed to delete collection. Please try again.')
    } finally {
      setIsDeletingCollection(false)
    }
  }

  const handleUploadComplete = () => {
    fetchDocumentsFromApi() // Refresh document list after upload
  }

  const handleUploadSuccess = (_documentTitle: string) => {
    // Embedding-specific toasts are handled by handleEmbeddingStatus
  }

  const handleEmbeddingStatus = (status: string, warnings: string[], documentTitle: string) => {
    const warningDetail = warnings.length > 0 ? ` — ${warnings.join('; ')}` : ''

    if (status === 'failed') {
      showToast('error', `Embedding failed for "${documentTitle}" — the document will not be searchable via RAG${warningDetail}`, 8000)
    } else if (status === 'partial') {
      showToast('warning', `Partial embedding for "${documentTitle}" — some chunks were not processed${warningDetail}`, 8000)
    } else if (status === 'skipped') {
      showToast('info', `Document "${documentTitle}" uploaded — embedding skipped (structured data)`)
    } else {
      // success
      showToast('success', `Document "${documentTitle}" uploaded and indexed successfully!`)
    }
  }

  const handleEditDocument = (doc: Document) => {
    setEditingDocument(doc)
    setIsEditModalOpen(true)
  }

  const handleEditSave = (updatedDoc: Document) => {
    // Update the document in the local list
    setDocuments(prev => prev.map(d => d.id === updatedDoc.id ? updatedDoc : d))
  }

  const handleViewDocument = (doc: Document) => {
    setViewingDocument(doc)
    setIsDetailsModalOpen(true)
  }

  const handleDeleteConversation = (conversation: Conversation) => {
    setDeletingConversation(conversation)
    setIsDeleteModalOpen(true)
  }

  const handleArchiveConversation = async (conversation: Conversation) => {
    try {
      await archiveConversation(conversation.id)
      showToast('success', `Conversation "${conversation.title || 'New Conversation'}" archived`)
      await loadConversations()
    } catch (error) {
      console.error('Failed to archive conversation:', error)
      showToast('error', 'Failed to archive conversation. Please try again.')
    }
  }

  const handleUnarchiveConversation = async (conversation: Conversation) => {
    try {
      await unarchiveConversation(conversation.id)
      showToast('success', `Conversation "${conversation.title || 'New Conversation'}" restored`)
      await loadConversations()
    } catch (error) {
      console.error('Failed to unarchive conversation:', error)
      showToast('error', 'Failed to restore conversation. Please try again.')
    }
  }

  const handleRenameConversation = (conversation: Conversation) => {
    setRenamingConversation(conversation)
    setRenameTitle(conversation.title || '')
    setIsRenameModalOpen(true)
  }

  const confirmRenameConversation = async () => {
    if (!renamingConversation || !renameTitle.trim()) return

    try {
      await renameConversation(renamingConversation.id, renameTitle.trim())
      showToast('success', 'Conversation renamed successfully')
      await loadConversations()
      setIsRenameModalOpen(false)
      setRenamingConversation(null)
      setRenameTitle('')
    } catch (error) {
      console.error('Failed to rename conversation:', error)
      showToast('error', 'Failed to rename conversation. Please try again.')
    }
  }

  const confirmDeleteConversation = async () => {
    if (!deletingConversation) return

    setIsDeleting(true)
    try {
      await deleteConversation(deletingConversation.id)

      // If we're deleting the current conversation, navigate to home
      if (currentConversationId === deletingConversation.id) {
        setMessages([])
        setCurrentConversationId(null)
        navigate('/')
      }

      // Refresh conversation list
      await loadConversations()

      // Close modal
      setIsDeleteModalOpen(false)
      setDeletingConversation(null)
    } catch (error) {
      console.error('Failed to delete conversation:', error)
    } finally {
      setIsDeleting(false)
    }
  }

  const handleDeleteDocument = (doc: Document) => {
    setDeletingDocument(doc)
    setIsDeleteDocModalOpen(true)
  }

  const confirmDeleteDocument = async () => {
    if (!deletingDocument) return

    setIsDeletingDocument(true)
    try {
      await deleteDocument(deletingDocument.id)

      // Remove from local state
      setDocuments(prev => prev.filter(d => d.id !== deletingDocument.id))

      // Show success toast
      showToast('success', `Document "${deletingDocument.title}" deleted successfully!`)

      // Close modal
      setIsDeleteDocModalOpen(false)
      setDeletingDocument(null)
    } catch (error) {
      console.error('Failed to delete document:', error)
      showToast('error', 'Failed to delete document. Please try again.')
    } finally {
      setIsDeletingDocument(false)
    }
  }

  // Close mobile sidebar when navigating to a conversation
  const handleSelectConversationMobile = (id: string) => {
    handleSelectConversation(id)
    setIsMobileSidebarOpen(false)
  }

  // Handle export conversation
  const handleExportConversation = (conversation: Conversation) => {
    setExportingConversation(conversation)
    setIsExportModalOpen(true)
  }

  // Handle add note from assistant message
  const handleAddNote = (content: string) => {
    setAddNoteContent(content)
    setIsAddNoteModalOpen(true)
  }

  return (
    <div className="flex h-screen relative">
      {/* Mobile Menu Button - Only visible on small screens */}
      <button
        onClick={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
        className="md:hidden fixed top-4 left-4 z-50 w-11 h-11 flex items-center justify-center bg-light-sidebar dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg shadow-lg"
        aria-label={isMobileSidebarOpen ? 'Close menu' : 'Open menu'}
      >
        {isMobileSidebarOpen ? (
          <X size={24} className="text-light-text dark:text-dark-text" />
        ) : (
          <Menu size={24} className="text-light-text dark:text-dark-text" />
        )}
      </button>

      {/* Mobile Overlay */}
      {isMobileSidebarOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/50 z-30"
          onClick={() => setIsMobileSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar - Hidden on mobile by default, shown as overlay when toggled */}
      <div className={`
        ${isMobileSidebarOpen ? 'translate-x-0' : '-translate-x-full'}
        md:translate-x-0
        fixed md:static
        z-40
        transition-transform duration-300 ease-in-out
      `}>
        <Sidebar
          key={currentPath === '/' ? 'home' : 'chat'}
          onNewChat={() => {
            handleNewChat()
            setIsMobileSidebarOpen(false)
          }}
          onSettingsClick={() => {
            handleSettingsClick()
            setIsMobileSidebarOpen(false)
          }}
          onUploadClick={() => {
            handleUploadClick()
            setIsMobileSidebarOpen(false)
          }}
          onNewCollectionClick={() => {
            handleNewCollectionClick()
            setIsMobileSidebarOpen(false)
          }}
          onEditCollection={(collection) => {
            handleEditCollection(collection)
            setIsMobileSidebarOpen(false)
          }}
          onDeleteCollection={(collection) => {
            handleDeleteCollection(collection)
            setIsMobileSidebarOpen(false)
          }}
          onEditDocument={(doc) => {
            handleEditDocument(doc)
            setIsMobileSidebarOpen(false)
          }}
          onViewDocument={(doc) => {
            handleViewDocument(doc)
            setIsMobileSidebarOpen(false)
          }}
          onDeleteDocument={(doc) => {
            handleDeleteDocument(doc)
            setIsMobileSidebarOpen(false)
          }}
          onDeleteConversation={handleDeleteConversation}
          onArchiveConversation={handleArchiveConversation}
          onUnarchiveConversation={handleUnarchiveConversation}
          onRenameConversation={handleRenameConversation}
          onExportConversation={handleExportConversation}
          onWhatsAppAdminClick={() => {
            navigate('/admin/whatsapp')
            setIsMobileSidebarOpen(false)
          }}
          onNotesClick={() => {
            navigate('/notes')
            setIsMobileSidebarOpen(false)
          }}
          onMaintenanceClick={() => {
            navigate('/admin/maintenance')
            setIsMobileSidebarOpen(false)
          }}
          onDocsClick={() => {
            navigate('/docs')
            setIsMobileSidebarOpen(false)
          }}
          documents={documents}
          conversations={conversations}
          collections={collections}
          currentConversationId={conversationId || null}
          currentPath={currentPath}
          onSelectConversation={handleSelectConversationMobile}
          conversationSearchQuery={conversationSearchQuery}
          onConversationSearchChange={setConversationSearchQuery}
        />
      </div>

      {/* Main chat area - Full width on mobile */}
      {conversationError ? (
        /* Conversation Not Found Error Display */
        <div className="flex-1 flex flex-col items-center justify-center p-8 bg-light-bg dark:bg-dark-bg">
          <div className="max-w-md w-full text-center">
            {/* Error Icon */}
            <div className="mx-auto w-16 h-16 rounded-full bg-red-100 dark:bg-red-900/20 flex items-center justify-center mb-6">
              <AlertTriangle className="w-8 h-8 text-red-600 dark:text-red-400" />
            </div>

            {/* Error Title */}
            <h1 className="text-2xl font-semibold text-light-text dark:text-dark-text mb-3">
              Conversation Not Found
            </h1>

            {/* Error Message */}
            <p className="text-light-text-secondary dark:text-dark-text-secondary mb-8">
              The conversation you're looking for doesn't exist or may have been deleted.
              You can go back to the home page or start a new chat.
            </p>

            {/* Action Buttons */}
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <button
                onClick={() => navigate('/')}
                className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-lg border border-light-border dark:border-dark-border text-light-text dark:text-dark-text hover:bg-light-sidebar dark:hover:bg-dark-sidebar transition-colors min-h-[44px]"
              >
                <Home className="w-5 h-5" />
                Go Home
              </button>
              <button
                onClick={handleNewChat}
                className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors min-h-[44px]"
              >
                <Plus className="w-5 h-5" />
                Start New Chat
              </button>
            </div>
          </div>
        </div>
      ) : (
        <ChatArea
          messages={messages}
          onSendMessage={handleSendMessage}
          isLoading={isLoading}
          onShowToast={(message, type) => showToast(type, message)}
          conversationId={currentConversationId || undefined}
          conversationTitle={conversations.find(c => c.id === currentConversationId)?.title}
          onExportClick={currentConversationId ? () => {
            const conv = conversations.find(c => c.id === currentConversationId)
            if (conv) handleExportConversation(conv)
          } : undefined}
          onAddNote={handleAddNote}
          documents={documents.map(d => ({ id: d.id, title: d.title, document_type: d.document_type, collection_id: d.collection_id }))}
          collections={collections.map(c => ({ id: c.id, name: c.name }))}
          scope={documentScope}
          onScopeChange={setDocumentScope}
          enableSuggestedQuestions={(() => {
            try {
              const savedSettings = localStorage.getItem('rag-settings')
              if (savedSettings) {
                const parsed = JSON.parse(savedSettings)
                return parsed.enable_suggested_questions !== false
              }
            } catch (e) {}
            return true
          })()}
          enableTypewriter={(() => {
            try {
              const savedSettings = localStorage.getItem('rag-settings')
              if (savedSettings) {
                const parsed = JSON.parse(savedSettings)
                return parsed.enable_typewriter !== false
              }
            } catch (e) {}
            return true  // Default enabled
          })()}
        />
      )}

      {/* Upload Modal */}
      <UploadModal
        isOpen={isUploadModalOpen}
        onClose={() => setIsUploadModalOpen(false)}
        onUploadComplete={handleUploadComplete}
        onUploadSuccess={handleUploadSuccess}
        onEmbeddingStatus={handleEmbeddingStatus}
      />

      {/* Document Edit Modal */}
      <DocumentEditModal
        document={editingDocument}
        isOpen={isEditModalOpen}
        onClose={() => {
          setIsEditModalOpen(false)
          setEditingDocument(null)
        }}
        onSave={handleEditSave}
        collections={collections}
      />

      {/* Document Details Modal */}
      <DocumentDetailsModal
        document={viewingDocument}
        isOpen={isDetailsModalOpen}
        onClose={() => {
          setIsDetailsModalOpen(false)
          setViewingDocument(null)
        }}
        onDocumentUpdated={fetchDocumentsFromApi}
      />

      {/* Settings Modal */}
      <SettingsModal
        isOpen={isSettingsModalOpen}
        onClose={() => setIsSettingsModalOpen(false)}
      />

      {/* Delete Conversation Confirmation Modal */}
      <ConfirmDeleteModal
        isOpen={isDeleteModalOpen}
        onClose={() => {
          setIsDeleteModalOpen(false)
          setDeletingConversation(null)
        }}
        onConfirm={confirmDeleteConversation}
        title="Delete Conversation"
        message="Are you sure you want to delete this conversation? This action cannot be undone."
        itemName={deletingConversation?.title}
        isDeleting={isDeleting}
      />

      {/* Delete Document Confirmation Modal */}
      <ConfirmDeleteModal
        isOpen={isDeleteDocModalOpen}
        onClose={() => {
          setIsDeleteDocModalOpen(false)
          setDeletingDocument(null)
        }}
        onConfirm={confirmDeleteDocument}
        title="Delete Document"
        message="Are you sure you want to delete this document? This action cannot be undone."
        itemName={deletingDocument?.title}
        isDeleting={isDeletingDocument}
      />

      {/* New Collection Modal */}
      <NewCollectionModal
        isOpen={isNewCollectionModalOpen}
        onClose={() => setIsNewCollectionModalOpen(false)}
        onCreated={handleCollectionCreated}
      />

      {/* Edit Collection Modal */}
      <EditCollectionModal
        isOpen={isEditCollectionModalOpen}
        collection={editingCollection}
        onClose={() => {
          setIsEditCollectionModalOpen(false)
          setEditingCollection(null)
        }}
        onUpdated={handleCollectionUpdated}
      />

      {/* Delete Collection Confirmation Modal */}
      <ConfirmDeleteModal
        isOpen={isDeleteCollectionModalOpen}
        onClose={() => {
          setIsDeleteCollectionModalOpen(false)
          setDeletingCollection(null)
        }}
        onConfirm={confirmDeleteCollection}
        title="Delete Collection"
        message="Are you sure you want to delete this collection? Documents in this collection will be moved to Uncategorized."
        itemName={deletingCollection?.name}
        isDeleting={isDeletingCollection}
      />

      {/* Welcome Modal - shown on first launch */}
      <WelcomeModal
        isOpen={isWelcomeModalOpen}
        onClose={() => {
          setIsWelcomeModalOpen(false)
          localStorage.setItem('rag-welcome-seen', 'true')
        }}
      />

      {/* Rename Conversation Modal */}
      {isRenameModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setIsRenameModalOpen(false)}>
          <div
            className="bg-white dark:bg-dark-sidebar rounded-lg shadow-xl p-6 w-full max-w-md mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text mb-4">
              Rename Conversation
            </h2>
            <input
              type="text"
              value={renameTitle}
              onChange={(e) => setRenameTitle(e.target.value)}
              placeholder="Enter new title..."
              className="w-full px-4 py-3 border border-light-border dark:border-dark-border rounded-lg bg-light-bg dark:bg-dark-bg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && renameTitle.trim()) {
                  confirmRenameConversation()
                } else if (e.key === 'Escape') {
                  setIsRenameModalOpen(false)
                }
              }}
            />
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setIsRenameModalOpen(false)
                  setRenamingConversation(null)
                  setRenameTitle('')
                }}
                className="px-4 py-2 text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={confirmRenameConversation}
                disabled={!renameTitle.trim()}
                className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Rename
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Export Conversation Modal */}
      <ExportModal
        isOpen={isExportModalOpen}
        onClose={() => {
          setIsExportModalOpen(false)
          setExportingConversation(null)
        }}
        conversationId={exportingConversation?.id || ''}
        conversationTitle={exportingConversation?.title}
        onShowToast={(message, type) => showToast(type, message)}
      />

      {/* Add Note Modal */}
      <AddNoteModal
        isOpen={isAddNoteModalOpen}
        onClose={() => {
          setIsAddNoteModalOpen(false)
          setAddNoteContent('')
        }}
        onShowToast={(message, type) => showToast(type, message)}
        documents={documents}
        prefillContent={addNoteContent}
      />
    </div>
  )
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 2,
    },
  },
})

// WhatsApp Admin Page wrapper
const WhatsAppAdminPage = () => {
  const navigate = useNavigate()

  return (
    <WhatsAppAdmin onBack={() => navigate('/')} />
  )
}

// Telegram Admin Page wrapper
const TelegramAdminPage = () => {
  const navigate = useNavigate()

  return (
    <TelegramAdmin onBack={() => navigate('/')} />
  )
}

// Notes Page wrapper with documents fetching
const NotesPageWrapper = () => {
  const [documents, setDocuments] = useState<Document[]>([])

  // Fetch documents from API
  const fetchDocumentsFromApi = useCallback(async () => {
    try {
      const response = await fetch('/api/documents/')
      if (response.ok) {
        const data = await response.json()
        setDocuments(data)
      }
    } catch (error) {
      console.error('Failed to fetch documents:', error)
    }
  }, [])

  // Load documents on mount
  useEffect(() => {
    fetchDocumentsFromApi()
  }, [fetchDocumentsFromApi])

  return (
    <NotesPage documents={documents} onRefreshDocuments={fetchDocumentsFromApi} />
  )
}

// Layout wrapper that includes the NavSidebar
const AppLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <div className="flex h-screen">
      {/* Fixed Navigation Sidebar */}
      <NavSidebar />
      {/* Main content area with left margin to account for fixed sidebar (only on desktop) */}
      <div className="flex-1 ml-0 md:ml-16">
        {children}
      </div>
    </div>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <ToastProvider>
          <AppLayout>
            <Routes>
              <Route path="/" element={<ChatPage />} />
              <Route path="/chat/:conversationId" element={<ChatPage />} />
              <Route path="/documents" element={<DocumentsPage />} />
              <Route path="/admin/whatsapp" element={<WhatsAppAdminPage />} />
              <Route path="/admin/telegram" element={<TelegramAdminPage />} />
              <Route path="/admin/maintenance" element={<AdminMaintenancePage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/notes" element={<NotesPageWrapper />} />
              <Route path="/docs" element={<DocsPage />} />
              <Route path="/dashboard" element={<Dashboard />} />
            </Routes>
          </AppLayout>
        </ToastProvider>
      </Router>
    </QueryClientProvider>
  )
}

export default App
