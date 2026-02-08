import { useState, useRef, useEffect } from 'react'
import {
  MessageSquarePlus,
  ChevronDown,
  ChevronRight,
  FileText,
  Upload,
  Folder,
  FolderPlus,
  Pencil,
  MessageCircle,
  File,
  FileSpreadsheet,
  FileCode,
  Trash2,
  Search,
  X,
  AlertTriangle,
  MoreVertical,
  Archive,
  ArchiveRestore,
  Download
} from 'lucide-react'
import type { Document, Conversation, Collection } from '../types'

// Helper function to get file type icon based on mime type
function getFileIcon(mimeType: string | undefined) {
  if (!mimeType) return FileText;
  if (mimeType.includes('pdf')) return FileText;
  if (mimeType.includes('spreadsheet') || mimeType.includes('csv') || mimeType.includes('excel')) return FileSpreadsheet;
  if (mimeType.includes('json') || mimeType.includes('markdown')) return FileCode;
  if (mimeType.includes('word') || mimeType.includes('document')) return FileText;
  return File;
}

// Helper function to get file type label
function getFileTypeLabel(mimeType: string | undefined): string {
  if (!mimeType) return 'FILE';
  if (mimeType.includes('pdf')) return 'PDF';
  if (mimeType.includes('csv')) return 'CSV';
  if (mimeType.includes('spreadsheet') || mimeType.includes('excel')) return 'XLSX';
  if (mimeType.includes('json')) return 'JSON';
  if (mimeType.includes('markdown')) return 'MD';
  if (mimeType.includes('word') || mimeType.includes('document')) return 'DOCX';
  if (mimeType.includes('text/plain')) return 'TXT';
  return 'FILE';
}

// Helper function to format date
function formatDate(dateString: string | undefined): string {
  if (!dateString) return '';
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

interface SidebarProps {
  onNewChat?: () => void
  onSettingsClick?: () => void
  onUploadClick?: () => void
  onNewCollectionClick?: () => void
  onEditCollection?: (collection: Collection) => void
  onDeleteCollection?: (collection: Collection) => void
  onEditDocument?: (doc: Document) => void
  onViewDocument?: (doc: Document) => void
  onDeleteDocument?: (doc: Document) => void
  onDeleteConversation?: (conversation: Conversation) => void
  onArchiveConversation?: (conversation: Conversation) => void
  onUnarchiveConversation?: (conversation: Conversation) => void
  onRenameConversation?: (conversation: Conversation) => void
  onExportConversation?: (conversation: Conversation) => void
  onWhatsAppAdminClick?: () => void
  onNotesClick?: () => void
  onMaintenanceClick?: () => void
  onDocsClick?: () => void
  documents?: Document[]
  conversations?: Conversation[]
  collections?: Collection[]
  currentConversationId?: string | null
  currentPath?: string  // Used to force re-render on navigation
  onSelectConversation?: (id: string) => void
  conversationSearchQuery?: string
  onConversationSearchChange?: (query: string) => void
}

export function Sidebar({
  onNewChat,
  onSettingsClick: _onSettingsClick,
  onUploadClick,
  onNewCollectionClick,
  onEditCollection,
  onDeleteCollection,
  onEditDocument,
  onViewDocument,
  onDeleteDocument,
  onDeleteConversation,
  onArchiveConversation,
  onUnarchiveConversation,
  onRenameConversation,
  onExportConversation,
  onWhatsAppAdminClick: _onWhatsAppAdminClick,
  onNotesClick: _onNotesClick,
  onMaintenanceClick: _onMaintenanceClick,
  onDocsClick: _onDocsClick,
  documents = [],
  conversations = [],
  collections = [],
  currentConversationId: _currentConversationId,
  currentPath,
  onSelectConversation,
  conversationSearchQuery = '',
  onConversationSearchChange
}: SidebarProps) {
  const [isDocumentsExpanded, setIsDocumentsExpanded] = useState(true)
  const [isCollectionsExpanded, setIsCollectionsExpanded] = useState(true)
  const [isArchivedExpanded, setIsArchivedExpanded] = useState(false)
  // State for filtering documents by collection
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null)
  // State for context menu
  const [contextMenuConversation, setContextMenuConversation] = useState<Conversation | null>(null)
  const [contextMenuPosition, setContextMenuPosition] = useState<{ x: number; y: number } | null>(null)
  const contextMenuRef = useRef<HTMLDivElement>(null)

  // Close context menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (contextMenuRef.current && !contextMenuRef.current.contains(event.target as Node)) {
        setContextMenuConversation(null)
        setContextMenuPosition(null)
      }
    }

    if (contextMenuConversation) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [contextMenuConversation])

  // Split conversations into active and archived
  const activeConversations = conversations.filter(c => !c.is_archived)
  const archivedConversations = conversations.filter(c => c.is_archived)

  // Handle context menu open
  const handleContextMenu = (e: React.MouseEvent, conversation: Conversation) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenuConversation(conversation)
    setContextMenuPosition({ x: e.clientX, y: e.clientY })
  }

  // Handle context menu button click
  const handleMenuButtonClick = (e: React.MouseEvent, conversation: Conversation) => {
    e.stopPropagation()
    const rect = (e.target as HTMLElement).getBoundingClientRect()
    setContextMenuConversation(conversation)
    setContextMenuPosition({ x: rect.left, y: rect.bottom })
  }

  // Derive active conversation ID from currentPath prop
  // This ensures the sidebar updates correctly when using browser back/forward buttons
  // since parent component passes location.pathname which triggers re-render
  const activeConversationId = currentPath?.startsWith('/chat/')
    ? currentPath.replace('/chat/', '')
    : null

  // Filter documents based on selected collection
  const filteredDocuments = selectedCollectionId === null
    ? documents  // Show all documents when no collection is selected
    : documents.filter(doc => doc.collection_id === selectedCollectionId)

  // Get the selected collection name for display
  const selectedCollectionName = selectedCollectionId
    ? collections.find(c => c.id === selectedCollectionId)?.name || 'Unknown'
    : 'All Documents'

  return (
    <aside className="w-72 md:w-64 bg-light-sidebar dark:bg-dark-sidebar border-r border-light-border dark:border-dark-border flex flex-col h-screen">
      {/* New Chat Button - with padding on mobile for menu button */}
      <div className="p-4 pt-16 md:pt-4 border-b border-light-border dark:border-dark-border">
        <button
          onClick={onNewChat}
          className="w-full min-h-[44px] py-3 px-4 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors flex items-center justify-center gap-2"
        >
          <MessageSquarePlus size={18} />
          New Chat
        </button>
      </div>

      {/* Scrollable Content Area */}
      <div className="flex-1 overflow-y-auto">
        {/* Conversation History Section */}
        <div className="p-2">
          <h3 className="text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider px-2 py-2">
            Conversations
          </h3>

          {/* Search Input */}
          <div className="relative mb-2 px-2">
            <div className="relative">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary"
              />
              <input
                type="text"
                placeholder="Search conversations..."
                value={conversationSearchQuery}
                onChange={(e) => onConversationSearchChange?.(e.target.value)}
                className="w-full min-h-[36px] pl-9 pr-8 py-2 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent text-light-text dark:text-dark-text placeholder:text-light-text-secondary dark:placeholder:text-dark-text-secondary"
              />
              {conversationSearchQuery && (
                <button
                  onClick={() => onConversationSearchChange?.('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text"
                  title="Clear search"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          </div>

          <nav className="space-y-1">
            {activeConversations.length === 0 ? (
              <p className="text-light-text-secondary dark:text-dark-text-secondary text-sm p-2">
                {conversationSearchQuery
                  ? `No conversations found matching "${conversationSearchQuery}"`
                  : 'No conversations yet. Click "New Chat" to start!'}
              </p>
            ) : (
              activeConversations.map(conversation => (
                <div
                  key={conversation.id}
                  onContextMenu={(e) => handleContextMenu(e, conversation)}
                  className={`group w-full flex items-center gap-2 px-2 py-1 text-sm text-left rounded-lg transition-colors ${
                    activeConversationId === conversation.id
                      ? 'bg-primary/10 text-primary'
                      : 'text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border'
                  }`}
                >
                  <button
                    onClick={() => onSelectConversation?.(conversation.id)}
                    className="flex items-center gap-2 flex-1 min-w-0 min-h-[44px] py-2"
                  >
                    <MessageCircle size={16} className="flex-shrink-0" />
                    <span className="truncate">{conversation.title || 'New Conversation'}</span>
                  </button>
                  <button
                    onClick={(e) => handleMenuButtonClick(e, conversation)}
                    className="opacity-100 md:opacity-0 group-hover:opacity-100 min-w-[36px] min-h-[36px] flex items-center justify-center hover:bg-light-border dark:hover:bg-dark-border rounded transition-opacity"
                    title="More options"
                  >
                    <MoreVertical size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
                  </button>
                </div>
              ))
            )}
          </nav>

          {/* Archived Section */}
          {archivedConversations.length > 0 && (
            <div className="mt-3">
              <button
                onClick={() => setIsArchivedExpanded(!isArchivedExpanded)}
                className="w-full flex items-center justify-between px-2 py-2 text-left hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
              >
                <span className="flex items-center gap-2">
                  <Archive size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
                  <span className="text-xs font-medium text-light-text-secondary dark:text-dark-text-secondary">
                    Archived ({archivedConversations.length})
                  </span>
                </span>
                {isArchivedExpanded ? (
                  <ChevronDown size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
                ) : (
                  <ChevronRight size={14} className="text-light-text-secondary dark:text-dark-text-secondary" />
                )}
              </button>

              {isArchivedExpanded && (
                <nav className="mt-1 space-y-1">
                  {archivedConversations.map(conversation => (
                    <div
                      key={conversation.id}
                      onContextMenu={(e) => handleContextMenu(e, conversation)}
                      className={`group w-full flex items-center gap-2 px-2 py-1 text-sm text-left rounded-lg transition-colors opacity-70 ${
                        activeConversationId === conversation.id
                          ? 'bg-primary/10 text-primary'
                          : 'text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border'
                      }`}
                    >
                      <button
                        onClick={() => onSelectConversation?.(conversation.id)}
                        className="flex items-center gap-2 flex-1 min-w-0 min-h-[44px] py-2"
                      >
                        <Archive size={16} className="flex-shrink-0 text-light-text-secondary dark:text-dark-text-secondary" />
                        <span className="truncate">{conversation.title || 'New Conversation'}</span>
                      </button>
                      <button
                        onClick={(e) => handleMenuButtonClick(e, conversation)}
                        className="opacity-100 md:opacity-0 group-hover:opacity-100 min-w-[36px] min-h-[36px] flex items-center justify-center hover:bg-light-border dark:hover:bg-dark-border rounded transition-opacity"
                        title="More options"
                      >
                        <MoreVertical size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
                      </button>
                    </div>
                  ))}
                </nav>
              )}
            </div>
          )}
        </div>

        {/* Collections Section - Expandable */}
        <div className="p-2 border-t border-light-border dark:border-dark-border">
          <button
            onClick={() => setIsCollectionsExpanded(!isCollectionsExpanded)}
            className="w-full min-h-[44px] flex items-center justify-between px-2 py-2 text-left hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
          >
            <span className="flex items-center gap-2">
              <Folder size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
              <span className="text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider">
                Collections
              </span>
            </span>
            {isCollectionsExpanded ? (
              <ChevronDown size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
            ) : (
              <ChevronRight size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
            )}
          </button>

          {isCollectionsExpanded && (
            <div className="mt-2 space-y-2">
              {/* New Collection Button */}
              <button
                onClick={onNewCollectionClick}
                className="w-full min-h-[44px] py-3 px-3 border border-dashed border-light-border dark:border-dark-border rounded-lg text-sm text-light-text-secondary dark:text-dark-text-secondary hover:border-primary hover:text-primary transition-colors flex items-center justify-center gap-2"
              >
                <FolderPlus size={14} />
                New Collection
              </button>

              {/* Collections List */}
              <div className="space-y-1">
                {collections.length === 0 ? (
                  <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary px-2">
                    No collections yet. Create one to organize your documents!
                  </p>
                ) : (
                  collections.map(collection => (
                    <div
                      key={collection.id}
                      onClick={() => setSelectedCollectionId(
                        selectedCollectionId === collection.id ? null : collection.id
                      )}
                      className={`group flex items-center gap-2 px-2 py-1.5 min-h-[44px] text-sm rounded cursor-pointer ${
                        selectedCollectionId === collection.id
                          ? 'bg-primary/10 text-primary border border-primary/30'
                          : 'text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border'
                      }`}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          setSelectedCollectionId(
                            selectedCollectionId === collection.id ? null : collection.id
                          );
                        }
                      }}
                      title={selectedCollectionId === collection.id
                        ? "Click to show all documents"
                        : `Click to filter documents by "${collection.name}"`}
                    >
                      <Folder size={14} className={`flex-shrink-0 ${
                        selectedCollectionId === collection.id ? 'text-primary' : 'text-primary'
                      }`} />
                      <div className="flex-1 min-w-0">
                        <span className="truncate block">{collection.name}</span>
                        {collection.description && (
                          <span className={`text-xs truncate block ${
                            selectedCollectionId === collection.id
                              ? 'text-primary/70'
                              : 'text-light-text-secondary dark:text-dark-text-secondary'
                          }`}>
                            {collection.description}
                          </span>
                        )}
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onEditCollection?.(collection);
                        }}
                        className="opacity-100 md:opacity-0 group-hover:opacity-100 min-w-[36px] min-h-[36px] flex items-center justify-center hover:bg-primary/20 rounded transition-opacity"
                        title="Edit collection"
                      >
                        <Pencil size={14} className="text-light-text-secondary dark:text-dark-text-secondary hover:text-primary" />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteCollection?.(collection);
                        }}
                        className="opacity-100 md:opacity-0 group-hover:opacity-100 min-w-[36px] min-h-[36px] flex items-center justify-center hover:bg-red-100 dark:hover:bg-red-900/20 rounded transition-opacity"
                        title="Delete collection"
                      >
                        <Trash2 size={14} className="text-light-text-secondary dark:text-dark-text-secondary hover:text-red-500" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {/* Documents Section - Expandable */}
        <div className="p-2 border-t border-light-border dark:border-dark-border">
          <button
            onClick={() => setIsDocumentsExpanded(!isDocumentsExpanded)}
            className="w-full min-h-[44px] flex items-center justify-between px-2 py-2 text-left hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
          >
            <span className="flex items-center gap-2">
              <FileText size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
              <span className="text-xs font-semibold text-light-text-secondary dark:text-dark-text-secondary uppercase tracking-wider">
                Documents
              </span>
            </span>
            {isDocumentsExpanded ? (
              <ChevronDown size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
            ) : (
              <ChevronRight size={16} className="text-light-text-secondary dark:text-dark-text-secondary" />
            )}
          </button>

          {isDocumentsExpanded && (
            <div className="mt-2 space-y-2">
              {/* Upload Button */}
              <button
                onClick={onUploadClick}
                className="w-full min-h-[44px] py-3 px-3 border border-dashed border-light-border dark:border-dark-border rounded-lg text-sm text-light-text-secondary dark:text-dark-text-secondary hover:border-primary hover:text-primary transition-colors flex items-center justify-center gap-2"
              >
                <Upload size={14} />
                Upload Document
              </button>

              {/* Collections/Documents Tree */}
              <div className="space-y-1">
                {/* Filter Header - shows current filter state */}
                <div
                  onClick={() => selectedCollectionId && setSelectedCollectionId(null)}
                  className={`flex items-center gap-2 px-2 py-1.5 text-sm ${
                    selectedCollectionId === null
                      ? 'text-primary font-medium'
                      : 'text-light-text-secondary dark:text-dark-text-secondary cursor-pointer hover:text-primary'
                  }`}
                  role={selectedCollectionId ? "button" : undefined}
                  tabIndex={selectedCollectionId ? 0 : undefined}
                  onKeyDown={(e) => {
                    if (selectedCollectionId && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault();
                      setSelectedCollectionId(null);
                    }
                  }}
                  title={selectedCollectionId ? "Click to show all documents" : undefined}
                >
                  <Folder size={14} />
                  <span>{selectedCollectionName}</span>
                  {selectedCollectionId && (
                    <span className="text-xs bg-primary/20 text-primary px-1.5 py-0.5 rounded ml-auto">
                      {filteredDocuments.length}
                    </span>
                  )}
                </div>
                {filteredDocuments.length === 0 ? (
                  <div className="px-2 pl-4 py-2">
                    <div className="flex flex-col items-center text-center p-4 border border-dashed border-light-border dark:border-dark-border rounded-lg bg-light-bg/50 dark:bg-dark-bg/50">
                      <FileText size={32} className="text-light-text-secondary dark:text-dark-text-secondary mb-2 opacity-50" />
                      <p className="text-sm text-light-text-secondary dark:text-dark-text-secondary font-medium mb-1">
                        {selectedCollectionId ? 'No documents in this collection' : 'No documents yet'}
                      </p>
                      <p className="text-xs text-light-text-secondary dark:text-dark-text-secondary opacity-75 mb-3">
                        {selectedCollectionId
                          ? 'Move documents to this collection or upload new ones'
                          : 'Click "Upload Document" above to add your first file (PDF, TXT, Word, CSV, Excel, JSON, or Markdown)'}
                      </p>
                      <button
                        onClick={selectedCollectionId ? () => setSelectedCollectionId(null) : onUploadClick}
                        className="text-xs text-primary hover:text-primary-hover underline cursor-pointer font-medium"
                      >
                        {selectedCollectionId ? '← Show all documents' : 'Upload your first document →'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="pl-6 space-y-1">
                    {filteredDocuments.map(doc => {
                      const FileIcon = getFileIcon(doc.mime_type);
                      return (
                        <div
                          key={doc.id}
                          onClick={() => onViewDocument?.(doc)}
                          className="group flex items-center gap-2 px-2 py-2 min-h-[44px] text-sm text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border rounded cursor-pointer"
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              onViewDocument?.(doc);
                            }
                          }}
                        >
                          <FileIcon size={16} className="text-light-text-secondary dark:text-dark-text-secondary flex-shrink-0" />
                          {/* Warning icon for documents with embedding failures */}
                          {doc.comment && doc.comment.includes('WARNING') && doc.document_type === 'unstructured' && (
                            <span title="Embedding warning: this document may not be fully searchable">
                              <AlertTriangle
                                size={14}
                                className="text-amber-500 dark:text-amber-400 flex-shrink-0"
                              />
                            </span>
                          )}
                          <div className="flex-1 min-w-0">
                            <span className="truncate block">{doc.title}</span>
                            <div className="flex items-center gap-2 text-xs text-light-text-secondary dark:text-dark-text-secondary">
                              <span className="bg-light-border dark:bg-dark-border px-1.5 py-0.5 rounded text-[10px] font-medium">
                                {getFileTypeLabel(doc.mime_type)}
                              </span>
                              <span>{formatDate(doc.created_at)}</span>
                            </div>
                          </div>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onEditDocument?.(doc);
                            }}
                            className="opacity-100 md:opacity-0 group-hover:opacity-100 min-w-[36px] min-h-[36px] flex items-center justify-center hover:bg-primary/20 rounded transition-opacity"
                            title="Edit document"
                          >
                            <Pencil size={16} className="text-light-text-secondary dark:text-dark-text-secondary hover:text-primary" />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteDocument?.(doc);
                            }}
                            className="opacity-100 md:opacity-0 group-hover:opacity-100 min-w-[36px] min-h-[36px] flex items-center justify-center hover:bg-red-100 dark:hover:bg-red-900/20 rounded transition-opacity"
                            title="Delete document"
                          >
                            <Trash2 size={16} className="text-light-text-secondary dark:text-dark-text-secondary hover:text-red-500" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Navigation is now handled by NavSidebar - removed duplicate buttons */}

      {/* Context Menu */}
      {contextMenuConversation && contextMenuPosition && (
        <div
          ref={contextMenuRef}
          className="fixed z-50 bg-white dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg shadow-lg py-1 min-w-[160px]"
          style={{
            left: Math.min(contextMenuPosition.x, window.innerWidth - 180),
            top: Math.min(contextMenuPosition.y, window.innerHeight - 150),
          }}
        >
          <button
            onClick={() => {
              onRenameConversation?.(contextMenuConversation)
              setContextMenuConversation(null)
              setContextMenuPosition(null)
            }}
            className="w-full px-4 py-2 text-left text-sm text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border flex items-center gap-3 transition-colors"
          >
            <Pencil size={16} />
            Rename
          </button>
          <button
            onClick={() => {
              onExportConversation?.(contextMenuConversation)
              setContextMenuConversation(null)
              setContextMenuPosition(null)
            }}
            className="w-full px-4 py-2 text-left text-sm text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border flex items-center gap-3 transition-colors"
          >
            <Download size={16} />
            Export
          </button>
          {contextMenuConversation.is_archived ? (
            <button
              onClick={() => {
                onUnarchiveConversation?.(contextMenuConversation)
                setContextMenuConversation(null)
                setContextMenuPosition(null)
              }}
              className="w-full px-4 py-2 text-left text-sm text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border flex items-center gap-3 transition-colors"
            >
              <ArchiveRestore size={16} />
              Unarchive
            </button>
          ) : (
            <button
              onClick={() => {
                onArchiveConversation?.(contextMenuConversation)
                setContextMenuConversation(null)
                setContextMenuPosition(null)
              }}
              className="w-full px-4 py-2 text-left text-sm text-light-text dark:text-dark-text hover:bg-light-border dark:hover:bg-dark-border flex items-center gap-3 transition-colors"
            >
              <Archive size={16} />
              Archive
            </button>
          )}
          <div className="border-t border-light-border dark:border-dark-border my-1" />
          <button
            onClick={() => {
              onDeleteConversation?.(contextMenuConversation)
              setContextMenuConversation(null)
              setContextMenuPosition(null)
            }}
            className="w-full px-4 py-2 text-left text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-3 transition-colors"
          >
            <Trash2 size={16} />
            Delete
          </button>
        </div>
      )}
    </aside>
  )
}

export default Sidebar
