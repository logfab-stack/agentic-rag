/**
 * DocsPage - In-app documentation with comprehensive guides and API reference
 *
 * Features:
 * - Left sidebar navigation with section links
 * - Search functionality across all documentation
 * - Multiple sections covering all aspects of the system
 * - Dark mode support
 * - Responsive design for mobile
 */

import { useState, useEffect, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  ArrowLeft,
  Book,
  Search,
  X,
  Home,
  Download,
  Settings,
  FileText,
  MessageSquare,
  Wrench,
  AlertTriangle,
  Code,
  ChevronRight,
  ChevronDown,
  Upload,
  Key,
  Zap,
  Table,
  BookOpen,
  Copy,
  Check
} from 'lucide-react'

// Documentation sections
const DOC_SECTIONS = [
  {
    id: 'introduction',
    title: 'Introduction',
    icon: Home,
    subsections: [
      { id: 'what-is', title: 'What is Agentic RAG?' },
      { id: 'architecture', title: 'System Architecture' },
      { id: 'requirements', title: 'Requirements' }
    ]
  },
  {
    id: 'installation',
    title: 'Installation',
    icon: Download,
    subsections: [
      { id: 'backend-setup', title: 'Backend Setup' },
      { id: 'frontend-setup', title: 'Frontend Setup' },
      { id: 'database-setup', title: 'PostgreSQL Setup' },
      { id: 'ollama-setup', title: 'Ollama Setup (Optional)' }
    ]
  },
  {
    id: 'configuration',
    title: 'Configuration',
    icon: Settings,
    subsections: [
      { id: 'api-keys', title: 'API Keys' },
      { id: 'llm-models', title: 'LLM Models' },
      { id: 'embedding-models', title: 'Embedding Models' },
      { id: 'rag-settings', title: 'RAG Settings' }
    ]
  },
  {
    id: 'documents',
    title: 'Document Management',
    icon: FileText,
    subsections: [
      { id: 'uploading', title: 'Uploading Documents' },
      { id: 'collections', title: 'Collections' },
      { id: 'supported-formats', title: 'Supported Formats' },
      { id: 'document-preview', title: 'Document Preview' }
    ]
  },
  {
    id: 'chat-rag',
    title: 'Chat & RAG',
    icon: MessageSquare,
    subsections: [
      { id: 'asking-questions', title: 'Asking Questions' },
      { id: 'semantic-search', title: 'Semantic Search' },
      { id: 'citations', title: 'Citations & Sources' },
      { id: 'hybrid-search', title: 'Hybrid Search (BM25 + Vector)' }
    ]
  },
  {
    id: 'structured-data',
    title: 'Structured Data',
    icon: Table,
    subsections: [
      { id: 'csv-excel', title: 'CSV & Excel Files' },
      { id: 'json-files', title: 'JSON Files' },
      { id: 'sql-queries', title: 'Automatic SQL Queries' },
      { id: 'data-analysis', title: 'Data Analysis' }
    ]
  },
  {
    id: 'admin',
    title: 'Admin & Maintenance',
    icon: Wrench,
    subsections: [
      { id: 'health-check', title: 'Health Check' },
      { id: 'vacuum-cleanup', title: 'Vacuum & Cleanup' },
      { id: 're-embedding', title: 'Re-embedding Documents' },
      { id: 'backup-restore', title: 'Backup & Restore' }
    ]
  },
  {
    id: 'troubleshooting',
    title: 'Troubleshooting',
    icon: AlertTriangle,
    subsections: [
      { id: 'common-issues', title: 'Common Issues' },
      { id: 'memory-problems', title: 'Memory Problems' },
      { id: 'retrieval-issues', title: 'Retrieval Issues' },
      { id: 'api-errors', title: 'API Errors' }
    ]
  },
  {
    id: 'api-reference',
    title: 'API Reference',
    icon: Code,
    subsections: [
      { id: 'documents-api', title: 'Documents API' },
      { id: 'collections-api', title: 'Collections API' },
      { id: 'chat-api', title: 'Chat API' },
      { id: 'settings-api', title: 'Settings API' }
    ]
  }
]

// Code block component with copy functionality
function CodeBlock({ code, language = 'bash' }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="relative group">
      <pre className="bg-gray-900 dark:bg-gray-950 text-gray-100 rounded-lg p-4 overflow-x-auto text-sm font-mono">
        <code className={`language-${language}`}>{code}</code>
      </pre>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 p-2 rounded bg-gray-700 hover:bg-gray-600 opacity-0 group-hover:opacity-100 transition-opacity"
        title="Copy to clipboard"
      >
        {copied ? <Check size={16} className="text-green-400" /> : <Copy size={16} className="text-gray-300" />}
      </button>
    </div>
  )
}

// Documentation content for each section
function DocContent({ sectionId, subsectionId }: { sectionId: string; subsectionId?: string }) {
  const renderContent = () => {
    // Introduction Section
    if (sectionId === 'introduction') {
      if (subsectionId === 'what-is' || !subsectionId) {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">What is Agentic RAG?</h1>
            <p className="text-lg mb-4">
              Agentic RAG (Retrieval-Augmented Generation) is an intelligent document assistant that combines
              the power of large language models with your own documents. It can:
            </p>
            <ul className="list-disc list-inside space-y-2 mb-6 ml-4">
              <li>Answer questions based on your uploaded documents</li>
              <li>Perform semantic search across text documents (PDF, Word, TXT, Markdown)</li>
              <li>Execute SQL queries on structured data (CSV, Excel, JSON)</li>
              <li>Compare and analyze data across multiple documents</li>
              <li>Provide citations and source attribution for its answers</li>
            </ul>
            <div className="bg-primary/10 border border-primary/30 rounded-lg p-4 mb-6">
              <h3 className="font-semibold text-primary mb-2 flex items-center gap-2">
                <Zap size={18} />
                Key Features
              </h3>
              <ul className="space-y-1 text-sm">
                <li>• Hybrid search combining BM25 keyword matching with vector semantic search</li>
                <li>• Multiple LLM support: OpenAI, Ollama (local), OpenRouter</li>
                <li>• Intelligent chunking with context preservation</li>
                <li>• Real-time streaming responses</li>
                <li>• WhatsApp integration for messaging</li>
              </ul>
            </div>
          </>
        )
      }
      if (subsectionId === 'architecture') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">System Architecture</h1>
            <p className="mb-4">The system consists of three main components:</p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Frontend (React)</h3>
            <p className="mb-4">
              A modern React application styled similar to OpenWebUI, featuring:
            </p>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Chat interface with message history</li>
              <li>Document management sidebar</li>
              <li>Settings configuration</li>
              <li>Admin maintenance tools</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Backend (FastAPI)</h3>
            <p className="mb-4">
              Python-based API server using FastAPI with:
            </p>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>LangChain/LangGraph for agent orchestration</li>
              <li>Document ingestion pipeline</li>
              <li>RAG retrieval with re-ranking</li>
              <li>WebSocket for streaming responses</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Database (PostgreSQL + pgvector)</h3>
            <p className="mb-4">
              PostgreSQL database with pgvector extension for vector similarity search:
            </p>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Document metadata storage</li>
              <li>Vector embeddings for semantic search</li>
              <li>Structured data rows for SQL queries</li>
              <li>Conversation history</li>
            </ul>
          </>
        )
      }
      if (subsectionId === 'requirements') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Requirements</h1>
            <h3 className="text-xl font-semibold mb-3">System Requirements</h3>
            <ul className="list-disc list-inside space-y-2 mb-6 ml-4">
              <li><strong>Python:</strong> 3.11 or higher</li>
              <li><strong>Node.js:</strong> 18+ and npm</li>
              <li><strong>PostgreSQL:</strong> 15+ with pgvector extension</li>
              <li><strong>Memory:</strong> At least 4GB RAM (8GB+ recommended for Ollama)</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3">API Keys (Optional)</h3>
            <ul className="list-disc list-inside space-y-2 mb-6 ml-4">
              <li><strong>OpenAI API key:</strong> For GPT models and embeddings</li>
              <li><strong>Cohere API key:</strong> For re-ranking (optional but recommended)</li>
              <li><strong>OpenRouter API key:</strong> For access to multiple LLM providers</li>
            </ul>

            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
              <h4 className="font-semibold text-yellow-800 dark:text-yellow-200 mb-2 flex items-center gap-2">
                <AlertTriangle size={18} />
                Note
              </h4>
              <p className="text-sm text-yellow-700 dark:text-yellow-300">
                You can run the system entirely locally with Ollama without any API keys.
                However, OpenAI embeddings and Cohere re-ranking typically provide better results.
              </p>
            </div>
          </>
        )
      }
    }

    // Installation Section
    if (sectionId === 'installation') {
      if (subsectionId === 'backend-setup' || !subsectionId) {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Backend Setup</h1>
            <p className="mb-4">Follow these steps to set up the Python backend:</p>

            <h3 className="text-xl font-semibold mb-3 mt-6">1. Clone the repository</h3>
            <CodeBlock code="git clone https://github.com/your-repo/agentic-rag.git
cd agentic-rag" />

            <h3 className="text-xl font-semibold mb-3 mt-6">2. Create a virtual environment</h3>
            <CodeBlock code="cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\\Scripts\\activate" />

            <h3 className="text-xl font-semibold mb-3 mt-6">3. Install dependencies</h3>
            <CodeBlock code="pip install -r requirements.txt" />

            <h3 className="text-xl font-semibold mb-3 mt-6">4. Set up environment variables</h3>
            <p className="mb-2">Create a <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded">.env</code> file:</p>
            <CodeBlock code={`DATABASE_URL=postgresql://user:password@localhost:5432/rag_db
OPENAI_API_KEY=sk-...  # Optional
COHERE_API_KEY=...     # Optional`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">5. Start the server</h3>
            <CodeBlock code="uvicorn main:app --reload --port 8000" />
          </>
        )
      }
      if (subsectionId === 'frontend-setup') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Frontend Setup</h1>
            <p className="mb-4">Follow these steps to set up the React frontend:</p>

            <h3 className="text-xl font-semibold mb-3 mt-6">1. Navigate to frontend directory</h3>
            <CodeBlock code="cd frontend" />

            <h3 className="text-xl font-semibold mb-3 mt-6">2. Install dependencies</h3>
            <CodeBlock code="npm install" />

            <h3 className="text-xl font-semibold mb-3 mt-6">3. Start development server</h3>
            <CodeBlock code="npm run dev" />

            <p className="mt-4">The frontend will be available at <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded">http://localhost:3000</code></p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Production Build</h3>
            <CodeBlock code="npm run build" />
          </>
        )
      }
      if (subsectionId === 'database-setup') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">PostgreSQL Setup</h1>
            <p className="mb-4">The system requires PostgreSQL with the pgvector extension.</p>

            <h3 className="text-xl font-semibold mb-3 mt-6">1. Install PostgreSQL</h3>
            <CodeBlock code={`# macOS with Homebrew
brew install postgresql@15

# Ubuntu/Debian
sudo apt install postgresql postgresql-contrib`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">2. Install pgvector extension</h3>
            <CodeBlock code={`# macOS
brew install pgvector

# From source
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
make install`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">3. Create database and enable extension</h3>
            <CodeBlock code={`createdb rag_db
psql rag_db -c "CREATE EXTENSION vector;"`} language="sql" />

            <h3 className="text-xl font-semibold mb-3 mt-6">4. Run migrations</h3>
            <p className="mb-2">The backend will automatically create tables on first run.</p>
          </>
        )
      }
      if (subsectionId === 'ollama-setup') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Ollama Setup (Optional)</h1>
            <p className="mb-4">
              Ollama allows you to run LLMs locally without API keys. This is optional but
              recommended for privacy-sensitive use cases.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">1. Install Ollama</h3>
            <CodeBlock code={`# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.ai/install.sh | sh`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">2. Start Ollama service</h3>
            <CodeBlock code="ollama serve" />

            <h3 className="text-xl font-semibold mb-3 mt-6">3. Pull recommended models</h3>
            <CodeBlock code={`# Chat model
ollama pull llama3.1

# Embedding model
ollama pull nomic-embed-text

# Or for better embeddings
ollama pull bge-m3`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">4. Configure in Settings</h3>
            <p className="mb-2">
              Go to Settings → Model Selection and choose your Ollama models from the dropdown.
              The system will auto-detect installed Ollama models.
            </p>
          </>
        )
      }
    }

    // Configuration Section
    if (sectionId === 'configuration') {
      if (subsectionId === 'api-keys' || !subsectionId) {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">API Keys Configuration</h1>
            <p className="mb-4">
              Configure your API keys in Settings → API Keys section. All keys are stored encrypted.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">OpenAI API Key</h3>
            <p className="mb-2">Required for:</p>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>GPT-4o, GPT-4o-mini chat models</li>
              <li>text-embedding-3-small embeddings (recommended)</li>
            </ul>
            <p className="mb-4">Get your key at <a href="https://platform.openai.com/api-keys" target="_blank" className="text-primary hover:underline">platform.openai.com/api-keys</a></p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Cohere API Key</h3>
            <p className="mb-2">Used for re-ranking search results. Significantly improves retrieval quality.</p>
            <p className="mb-4">Get your key at <a href="https://dashboard.cohere.com/api-keys" target="_blank" className="text-primary hover:underline">dashboard.cohere.com/api-keys</a></p>

            <h3 className="text-xl font-semibold mb-3 mt-6">OpenRouter API Key</h3>
            <p className="mb-2">Access to 200+ models from various providers through a single API.</p>
            <p className="mb-4">Get your key at <a href="https://openrouter.ai/keys" target="_blank" className="text-primary hover:underline">openrouter.ai/keys</a></p>

            <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
              <h4 className="font-semibold text-blue-800 dark:text-blue-200 mb-2 flex items-center gap-2">
                <Key size={18} />
                Testing Keys
              </h4>
              <p className="text-sm text-blue-700 dark:text-blue-300">
                Use the "Test" button next to each API key field to verify your key is working correctly.
              </p>
            </div>
          </>
        )
      }
      if (subsectionId === 'llm-models') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">LLM Model Selection</h1>
            <p className="mb-4">Choose the language model for chat and reasoning tasks.</p>

            <h3 className="text-xl font-semibold mb-3 mt-6">OpenAI Models</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>gpt-4o:</strong> Most capable, best for complex reasoning</li>
              <li><strong>gpt-4o-mini:</strong> Fast and cost-effective, good for most tasks</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Ollama Models (Local)</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>llama3.1:</strong> Excellent open-source model</li>
              <li><strong>mistral:</strong> Fast and capable</li>
              <li><strong>qwen2.5:</strong> Good multilingual support</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">OpenRouter Models</h3>
            <p className="mb-4">
              Access 200+ models including Claude, Gemini, and more. Use the search feature
              in Settings to find specific models.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Chunking LLM</h3>
            <p className="mb-4">
              A separate model can be configured for semantic chunking during document ingestion.
              Gemini 2.0 Flash is recommended for its speed and cost-effectiveness.
            </p>
          </>
        )
      }
      if (subsectionId === 'embedding-models') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Embedding Model Selection</h1>
            <p className="mb-4">
              Embedding models convert text into vectors for semantic search. The quality of
              embeddings directly affects retrieval accuracy.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">OpenAI Embeddings (Recommended)</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>text-embedding-3-small:</strong> Best balance of quality and cost</li>
              <li><strong>text-embedding-3-large:</strong> Higher quality, higher cost</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Ollama Embeddings (Local)</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>bge-m3:</strong> Excellent quality, multilingual</li>
              <li><strong>nomic-embed-text:</strong> Good quality, fast</li>
              <li><strong>mxbai-embed-large:</strong> High quality embeddings</li>
            </ul>

            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 mt-6">
              <h4 className="font-semibold text-yellow-800 dark:text-yellow-200 mb-2 flex items-center gap-2">
                <AlertTriangle size={18} />
                Important
              </h4>
              <p className="text-sm text-yellow-700 dark:text-yellow-300">
                Changing the embedding model requires re-embedding all documents. Use the
                "Re-embed All Documents" feature in Admin Maintenance after changing models.
              </p>
            </div>
          </>
        )
      }
      if (subsectionId === 'rag-settings') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">RAG Configuration</h1>
            <p className="mb-4">Fine-tune the retrieval and generation behavior.</p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Chunking Strategy</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>Semantic:</strong> Uses LLM to find natural break points (recommended)</li>
              <li><strong>Paragraph:</strong> Splits on paragraph boundaries</li>
              <li><strong>Fixed:</strong> Fixed-size chunks with overlap</li>
              <li><strong>Agentic:</strong> Advanced LLM-guided chunking</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Chunk Size Settings</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>Max Chunk Size:</strong> Maximum characters per chunk (default: 2000)</li>
              <li><strong>Chunk Overlap:</strong> Characters of overlap between chunks (default: 200)</li>
              <li><strong>Context Window:</strong> Number of surrounding chunks to include (default: 20)</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Search Mode</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>Hybrid:</strong> Combines vector + BM25 keyword search (recommended)</li>
              <li><strong>Vector Only:</strong> Pure semantic search</li>
              <li><strong>BM25 Only:</strong> Pure keyword search</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Strict RAG Mode</h3>
            <p className="mb-4">
              When enabled, uses stricter relevance thresholds (60% vs 50%) to filter out
              less relevant results. Useful for reducing hallucinations.
            </p>
          </>
        )
      }
    }

    // Documents Section
    if (sectionId === 'documents') {
      if (subsectionId === 'uploading' || !subsectionId) {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Uploading Documents</h1>
            <p className="mb-4">
              Upload documents using the "Upload Document" button in the sidebar or by
              dragging and dropping files.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Upload Steps</h3>
            <ol className="list-decimal list-inside space-y-2 mb-4 ml-4">
              <li>Click "Upload Document" in the sidebar</li>
              <li>Select a file or drag and drop</li>
              <li>Enter a custom name (optional)</li>
              <li>Add a comment/description (optional)</li>
              <li>Select a collection (optional)</li>
              <li>Click "Upload"</li>
            </ol>

            <h3 className="text-xl font-semibold mb-3 mt-6">Processing</h3>
            <p className="mb-4">
              After upload, the system will:
            </p>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Parse the document content</li>
              <li>For text documents: Create semantic chunks and generate embeddings</li>
              <li>For tabular data: Extract schema and store rows for SQL queries</li>
            </ul>

            <div className="bg-primary/10 border border-primary/30 rounded-lg p-4">
              <h4 className="font-semibold text-primary mb-2 flex items-center gap-2">
                <Upload size={18} />
                File Size Limit
              </h4>
              <p className="text-sm">
                Maximum file size is 100MB. For larger files, consider splitting them
                into smaller parts.
              </p>
            </div>
          </>
        )
      }
      if (subsectionId === 'collections') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Collections</h1>
            <p className="mb-4">
              Collections help you organize documents into logical groups.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Creating Collections</h3>
            <ol className="list-decimal list-inside space-y-2 mb-4 ml-4">
              <li>Click "New Collection" in the sidebar</li>
              <li>Enter a name and optional description</li>
              <li>Click "Create"</li>
            </ol>

            <h3 className="text-xl font-semibold mb-3 mt-6">Managing Documents</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Click on a collection to filter documents</li>
              <li>Use the edit button on a document to change its collection</li>
              <li>Deleting a collection moves its documents to "Uncategorized"</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Tips</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Group related documents for better context in RAG queries</li>
              <li>Use descriptive collection names</li>
              <li>Consider organizing by project, topic, or document type</li>
            </ul>
          </>
        )
      }
      if (subsectionId === 'supported-formats') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Supported File Formats</h1>

            <h3 className="text-xl font-semibold mb-3 mt-6">Unstructured (Text) Documents</h3>
            <p className="mb-2">These documents are chunked and embedded for semantic search:</p>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>PDF (.pdf):</strong> Standard PDF documents</li>
              <li><strong>Word (.docx):</strong> Microsoft Word documents</li>
              <li><strong>Text (.txt):</strong> Plain text files</li>
              <li><strong>Markdown (.md):</strong> Markdown formatted text</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Structured (Tabular) Data</h3>
            <p className="mb-2">These documents are parsed and stored for SQL queries:</p>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>CSV (.csv):</strong> Comma-separated values</li>
              <li><strong>Excel (.xlsx, .xls):</strong> Microsoft Excel spreadsheets</li>
              <li><strong>JSON (.json):</strong> JSON arrays or objects</li>
            </ul>

            <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mt-6">
              <h4 className="font-semibold text-blue-800 dark:text-blue-200 mb-2">Note</h4>
              <p className="text-sm text-blue-700 dark:text-blue-300">
                Structured data files are NOT vectorized. Instead, the agent uses SQL queries
                to analyze them. Ask questions like "What is the sum of sales?" or
                "Show me the top 10 items by revenue".
              </p>
            </div>
          </>
        )
      }
      if (subsectionId === 'document-preview') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Document Preview</h1>
            <p className="mb-4">
              Click on any document in the sidebar to open its details view.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Preview Content</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>Text documents:</strong> Shows the first few chunks of text</li>
              <li><strong>Tabular data:</strong> Shows the first rows and column headers</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Document Metadata</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>File name and custom title</li>
              <li>File type and size</li>
              <li>Upload date</li>
              <li>Collection assignment</li>
              <li>Number of chunks (for text documents)</li>
              <li>Schema/headers (for tabular data)</li>
            </ul>
          </>
        )
      }
    }

    // Chat & RAG Section
    if (sectionId === 'chat-rag') {
      if (subsectionId === 'asking-questions' || !subsectionId) {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Asking Questions</h1>
            <p className="mb-4">
              Simply type your question in the chat input and press Enter or click Send.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">How It Works</h3>
            <ol className="list-decimal list-inside space-y-2 mb-4 ml-4">
              <li>The agent analyzes your question</li>
              <li>Decides whether to use vector search (text) or SQL (data)</li>
              <li>Retrieves relevant information from your documents</li>
              <li>Generates a response with citations</li>
            </ol>

            <h3 className="text-xl font-semibold mb-3 mt-6">Question Types</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>Factual:</strong> "What does the document say about X?"</li>
              <li><strong>Analytical:</strong> "Compare X and Y in the documents"</li>
              <li><strong>Data queries:</strong> "What is the total sales for Q1?"</li>
              <li><strong>Summaries:</strong> "Summarize the main points"</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Tips for Better Results</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Be specific in your questions</li>
              <li>Mention document names if asking about specific files</li>
              <li>Use natural language - the agent understands context</li>
            </ul>
          </>
        )
      }
      if (subsectionId === 'semantic-search') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Semantic Search</h1>
            <p className="mb-4">
              Semantic search finds relevant content based on meaning, not just keywords.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">How It Works</h3>
            <ol className="list-decimal list-inside space-y-2 mb-4 ml-4">
              <li>Your question is converted to an embedding vector</li>
              <li>The system finds chunks with similar vector representations</li>
              <li>Results are re-ranked by relevance (if Cohere is configured)</li>
              <li>Top results are used to generate the answer</li>
            </ol>

            <h3 className="text-xl font-semibold mb-3 mt-6">Advantages</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Finds relevant content even without exact keyword matches</li>
              <li>Understands synonyms and related concepts</li>
              <li>Works across languages (with multilingual embeddings)</li>
            </ul>
          </>
        )
      }
      if (subsectionId === 'citations') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Citations & Sources</h1>
            <p className="mb-4">
              The agent provides citations to show where information came from.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Viewing Sources</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Sources are listed at the end of each response</li>
              <li>Click on a source to see more details</li>
              <li>Enable "Show Retrieved Chunks" in Settings to see all retrieved content</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Citation Format</h3>
            <p className="mb-4">
              Citations include the document name and relevance score. Higher scores
              indicate more relevant matches.
            </p>

            <div className="bg-primary/10 border border-primary/30 rounded-lg p-4">
              <h4 className="font-semibold text-primary mb-2">Hallucination Detection</h4>
              <p className="text-sm">
                The system validates that answers are grounded in retrieved content.
                If the agent can't find relevant information, it will say so rather
                than making up an answer.
              </p>
            </div>
          </>
        )
      }
      if (subsectionId === 'hybrid-search') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Hybrid Search (BM25 + Vector)</h1>
            <p className="mb-4">
              Hybrid search combines keyword matching (BM25) with semantic search (vectors)
              for best results.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Why Hybrid?</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>BM25 excels at finding exact terms (acronyms, technical terms)</li>
              <li>Vector search understands meaning and context</li>
              <li>Combined results use Reciprocal Rank Fusion (RRF)</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Configuration</h3>
            <p className="mb-2">In Settings → RAG Configuration:</p>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>Search Mode:</strong> Hybrid (default), Vector Only, or BM25 Only</li>
              <li><strong>Hybrid Alpha:</strong> Balance between methods (0.5 = equal weight)</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Best For</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Technical documentation with acronyms</li>
              <li>Legal/medical documents with specific terms</li>
              <li>Mixed natural language and technical queries</li>
            </ul>
          </>
        )
      }
    }

    // Structured Data Section
    if (sectionId === 'structured-data') {
      if (subsectionId === 'csv-excel' || !subsectionId) {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">CSV & Excel Files</h1>
            <p className="mb-4">
              Structured data files are parsed and stored for SQL-based analysis.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Supported Features</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Automatic header detection</li>
              <li>Schema extraction and storage</li>
              <li>Multiple sheets (Excel)</li>
              <li>Date parsing</li>
              <li>Number detection</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Example Questions</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>"What is the total revenue in the sales.csv?"</li>
              <li>"Show me the top 5 products by quantity"</li>
              <li>"What is the average price per category?"</li>
              <li>"How many orders were placed in January?"</li>
            </ul>
          </>
        )
      }
      if (subsectionId === 'json-files') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">JSON Files</h1>
            <p className="mb-4">
              JSON files are flattened and stored as rows for querying.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Supported Structures</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>Array of objects:</strong> Each object becomes a row</li>
              <li><strong>Nested objects:</strong> Flattened with dot notation</li>
              <li><strong>Single object:</strong> Treated as single row</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Example</h3>
            <CodeBlock code={`[
  {"name": "Product A", "price": 100, "category": "Electronics"},
  {"name": "Product B", "price": 50, "category": "Books"}
]`} language="json" />
          </>
        )
      }
      if (subsectionId === 'sql-queries') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Automatic SQL Queries</h1>
            <p className="mb-4">
              The agent automatically generates SQL queries for structured data questions.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">How It Works</h3>
            <ol className="list-decimal list-inside space-y-2 mb-4 ml-4">
              <li>Agent detects a data analysis question</li>
              <li>Identifies the relevant dataset</li>
              <li>Generates SQL query against JSONB data</li>
              <li>Executes and formats results</li>
            </ol>

            <h3 className="text-xl font-semibold mb-3 mt-6">Query Types</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li><strong>Aggregations:</strong> SUM, AVG, COUNT, MIN, MAX</li>
              <li><strong>Filtering:</strong> WHERE clauses</li>
              <li><strong>Grouping:</strong> GROUP BY</li>
              <li><strong>Sorting:</strong> ORDER BY</li>
              <li><strong>Limiting:</strong> TOP N results</li>
            </ul>
          </>
        )
      }
      if (subsectionId === 'data-analysis') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Data Analysis</h1>
            <p className="mb-4">
              Perform sophisticated analysis across your structured data files.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Cross-Document Analysis</h3>
            <p className="mb-4">
              The agent can query multiple datasets simultaneously:
            </p>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>"Compare sales between file1.csv and file2.csv"</li>
              <li>"What products appear in both datasets?"</li>
              <li>"Calculate total across all uploaded spreadsheets"</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Tips</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Use descriptive file names</li>
              <li>Ensure consistent column naming</li>
              <li>Check the document preview to verify schema</li>
            </ul>
          </>
        )
      }
    }

    // Admin Section
    if (sectionId === 'admin') {
      if (subsectionId === 'health-check' || !subsectionId) {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Health Check</h1>
            <p className="mb-4">
              Monitor system health in Admin → DB Maintenance.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Checks Include</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Database connection status</li>
              <li>Embedding service availability</li>
              <li>LLM API connectivity</li>
              <li>Storage space</li>
            </ul>
          </>
        )
      }
      if (subsectionId === 'vacuum-cleanup') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Vacuum & Cleanup</h1>
            <p className="mb-4">
              Periodically clean up the database for optimal performance.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">Orphan Cleanup</h3>
            <p className="mb-4">
              Removes embeddings and rows that no longer have associated documents.
              This can happen if document deletion was interrupted.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">When to Run</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>After deleting many documents</li>
              <li>If database size seems larger than expected</li>
              <li>As part of regular maintenance</li>
            </ul>
          </>
        )
      }
      if (subsectionId === 're-embedding') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Re-embedding Documents</h1>
            <p className="mb-4">
              Regenerate embeddings for all documents. Required after changing embedding models.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">When to Re-embed</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>After changing embedding model</li>
              <li>If search quality degrades</li>
              <li>After system updates that affect embeddings</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Process</h3>
            <ol className="list-decimal list-inside space-y-2 mb-4 ml-4">
              <li>Go to Admin → DB Maintenance</li>
              <li>Click "Re-embed All Documents"</li>
              <li>Review the estimate (time, document count)</li>
              <li>Click "Start Re-embedding"</li>
              <li>Wait for completion (can take several minutes)</li>
            </ol>

            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
              <h4 className="font-semibold text-yellow-800 dark:text-yellow-200 mb-2 flex items-center gap-2">
                <AlertTriangle size={18} />
                Warning
              </h4>
              <p className="text-sm text-yellow-700 dark:text-yellow-300">
                Re-embedding is resource-intensive. Avoid doing it during heavy usage.
                The BM25 index is also rebuilt during this process.
              </p>
            </div>
          </>
        )
      }
      if (subsectionId === 'backup-restore') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Backup & Restore</h1>
            <p className="mb-4">
              Create full backups of your data and restore when needed.
            </p>

            <h3 className="text-xl font-semibold mb-3 mt-6">What's Backed Up</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>All documents and metadata</li>
              <li>Collections structure</li>
              <li>Conversation history</li>
              <li>Settings (excluding API keys)</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Creating a Backup</h3>
            <ol className="list-decimal list-inside space-y-2 mb-4 ml-4">
              <li>Go to Settings → Backup & Restore</li>
              <li>Click "Create Backup"</li>
              <li>Download the ZIP file</li>
            </ol>

            <h3 className="text-xl font-semibold mb-3 mt-6">Restoring</h3>
            <ol className="list-decimal list-inside space-y-2 mb-4 ml-4">
              <li>Go to Settings → Backup & Restore</li>
              <li>Click "Restore from Backup"</li>
              <li>Select the backup ZIP file</li>
              <li>Confirm the restoration</li>
            </ol>
          </>
        )
      }
    }

    // Troubleshooting Section
    if (sectionId === 'troubleshooting') {
      if (subsectionId === 'common-issues' || !subsectionId) {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Common Issues</h1>

            <h3 className="text-xl font-semibold mb-3 mt-6">Server Won't Start</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Check DATABASE_URL is set correctly</li>
              <li>Ensure PostgreSQL is running</li>
              <li>Verify pgvector extension is installed</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Upload Fails</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Check file size (max 100MB)</li>
              <li>Verify file format is supported</li>
              <li>Check disk space</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Chat Not Working</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Verify API key is set and valid</li>
              <li>Check model selection</li>
              <li>Look for errors in browser console</li>
            </ul>
          </>
        )
      }
      if (subsectionId === 'memory-problems') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Memory Problems</h1>

            <h3 className="text-xl font-semibold mb-3 mt-6">High Memory Usage</h3>
            <p className="mb-4">If you're experiencing high memory usage:</p>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Reduce chunk size in settings</li>
              <li>Process fewer documents at once</li>
              <li>Use a smaller embedding model</li>
              <li>Run database vacuum</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Out of Memory with Ollama</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Use smaller models (7B instead of 70B)</li>
              <li>Reduce context window size</li>
              <li>Close other applications</li>
            </ul>
          </>
        )
      }
      if (subsectionId === 'retrieval-issues') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Retrieval Issues</h1>

            <h3 className="text-xl font-semibold mb-3 mt-6">Poor Search Results</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Enable Cohere re-ranking</li>
              <li>Use hybrid search mode</li>
              <li>Increase context window size</li>
              <li>Try re-embedding documents</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Missing Content</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Check document was fully processed</li>
              <li>Verify embeddings were created (no warning icon)</li>
              <li>Decrease strict mode threshold</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">Acronyms Not Found</h3>
            <p className="mb-4">
              Enable hybrid search mode - BM25 is better at finding exact terms and acronyms.
            </p>
          </>
        )
      }
      if (subsectionId === 'api-errors') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">API Errors</h1>

            <h3 className="text-xl font-semibold mb-3 mt-6">401 Unauthorized</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>API key is invalid or expired</li>
              <li>Key doesn't have required permissions</li>
              <li>Test the key using the "Test" button in Settings</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">429 Rate Limited</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Too many requests to the API</li>
              <li>Wait a few minutes and retry</li>
              <li>Consider upgrading your API plan</li>
            </ul>

            <h3 className="text-xl font-semibold mb-3 mt-6">500 Server Error</h3>
            <ul className="list-disc list-inside space-y-1 mb-4 ml-4">
              <li>Check backend logs for details</li>
              <li>Verify database connection</li>
              <li>Restart the backend server</li>
            </ul>
          </>
        )
      }
    }

    // API Reference Section
    if (sectionId === 'api-reference') {
      if (subsectionId === 'documents-api' || !subsectionId) {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Documents API</h1>

            <h3 className="text-xl font-semibold mb-3 mt-6">POST /api/ingest</h3>
            <p className="mb-2">Upload and process a document.</p>
            <CodeBlock code={`curl -X POST http://localhost:8000/api/ingest \\
  -F "file=@document.pdf" \\
  -F "title=My Document" \\
  -F "comment=Description here"`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">GET /api/documents</h3>
            <p className="mb-2">List all documents.</p>
            <CodeBlock code={`curl http://localhost:8000/api/documents`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">GET /api/documents/&#123;id&#125;</h3>
            <p className="mb-2">Get document details.</p>
            <CodeBlock code={`curl http://localhost:8000/api/documents/abc123`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">DELETE /api/documents/&#123;id&#125;</h3>
            <p className="mb-2">Delete a document.</p>
            <CodeBlock code={`curl -X DELETE http://localhost:8000/api/documents/abc123`} />
          </>
        )
      }
      if (subsectionId === 'collections-api') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Collections API</h1>

            <h3 className="text-xl font-semibold mb-3 mt-6">POST /api/collections</h3>
            <p className="mb-2">Create a new collection.</p>
            <CodeBlock code={`curl -X POST http://localhost:8000/api/collections \\
  -H "Content-Type: application/json" \\
  -d '{"name": "My Collection", "description": "Optional description"}'`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">GET /api/collections</h3>
            <p className="mb-2">List all collections.</p>
            <CodeBlock code={`curl http://localhost:8000/api/collections`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">PATCH /api/collections/&#123;id&#125;</h3>
            <p className="mb-2">Update a collection.</p>
            <CodeBlock code={`curl -X PATCH http://localhost:8000/api/collections/abc123 \\
  -H "Content-Type: application/json" \\
  -d '{"name": "New Name"}'`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">DELETE /api/collections/&#123;id&#125;</h3>
            <p className="mb-2">Delete a collection (documents moved to uncategorized).</p>
            <CodeBlock code={`curl -X DELETE http://localhost:8000/api/collections/abc123`} />
          </>
        )
      }
      if (subsectionId === 'chat-api') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Chat API</h1>

            <h3 className="text-xl font-semibold mb-3 mt-6">POST /api/chat</h3>
            <p className="mb-2">Send a message and get a response.</p>
            <CodeBlock code={`curl -X POST http://localhost:8000/api/chat \\
  -H "Content-Type: application/json" \\
  -d '{
    "message": "What documents do I have?",
    "conversation_id": "optional-id",
    "model": "gpt-4o"
  }'`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">GET /api/conversations</h3>
            <p className="mb-2">List all conversations.</p>
            <CodeBlock code={`curl http://localhost:8000/api/conversations`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">GET /api/conversations/&#123;id&#125;</h3>
            <p className="mb-2">Get conversation with messages.</p>
            <CodeBlock code={`curl http://localhost:8000/api/conversations/abc123`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">DELETE /api/conversations/&#123;id&#125;</h3>
            <p className="mb-2">Delete a conversation.</p>
            <CodeBlock code={`curl -X DELETE http://localhost:8000/api/conversations/abc123`} />
          </>
        )
      }
      if (subsectionId === 'settings-api') {
        return (
          <>
            <h1 className="text-3xl font-bold mb-6">Settings API</h1>

            <h3 className="text-xl font-semibold mb-3 mt-6">GET /api/settings</h3>
            <p className="mb-2">Get all settings (API keys are masked).</p>
            <CodeBlock code={`curl http://localhost:8000/api/settings`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">PATCH /api/settings</h3>
            <p className="mb-2">Update settings.</p>
            <CodeBlock code={`curl -X PATCH http://localhost:8000/api/settings \\
  -H "Content-Type: application/json" \\
  -d '{
    "llm_model": "gpt-4o",
    "enable_reranking": true
  }'`} />

            <h3 className="text-xl font-semibold mb-3 mt-6">GET /api/models/ollama</h3>
            <p className="mb-2">List available Ollama models.</p>
            <CodeBlock code={`curl http://localhost:8000/api/models/ollama`} />
          </>
        )
      }
    }

    // Default content
    return (
      <div className="text-center py-12">
        <Book size={48} className="mx-auto mb-4 text-light-text-secondary dark:text-dark-text-secondary" />
        <h2 className="text-xl font-semibold mb-2">Select a topic</h2>
        <p className="text-light-text-secondary dark:text-dark-text-secondary">
          Choose a section from the sidebar to view documentation.
        </p>
      </div>
    )
  }

  return (
    <div className="prose prose-slate dark:prose-invert max-w-none">
      {renderContent()}
    </div>
  )
}

export function DocsPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedSections, setExpandedSections] = useState<string[]>(['introduction'])
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const contentRef = useRef<HTMLDivElement>(null)

  // Parse URL hash for current section
  const hash = location.hash.replace('#', '')
  const [currentSection, currentSubsection] = hash.split('/').length > 1
    ? hash.split('/')
    : [hash || 'introduction', undefined]

  // Toggle section expansion
  const toggleSection = (sectionId: string) => {
    setExpandedSections(prev =>
      prev.includes(sectionId)
        ? prev.filter(id => id !== sectionId)
        : [...prev, sectionId]
    )
  }

  // Navigate to section
  const navigateToSection = (sectionId: string, subsectionId?: string) => {
    const hash = subsectionId ? `${sectionId}/${subsectionId}` : sectionId
    navigate(`/docs#${hash}`)
    setIsMobileMenuOpen(false)

    // Ensure section is expanded
    if (!expandedSections.includes(sectionId)) {
      setExpandedSections(prev => [...prev, sectionId])
    }

    // Scroll to top of content
    contentRef.current?.scrollTo(0, 0)
  }

  // Filter sections based on search
  const filteredSections = DOC_SECTIONS.filter(section => {
    if (!searchQuery) return true
    const query = searchQuery.toLowerCase()
    if (section.title.toLowerCase().includes(query)) return true
    return section.subsections.some(sub =>
      sub.title.toLowerCase().includes(query)
    )
  })

  // Expand matching sections when searching
  useEffect(() => {
    if (searchQuery) {
      const matchingSections = DOC_SECTIONS.filter(section => {
        const query = searchQuery.toLowerCase()
        return section.title.toLowerCase().includes(query) ||
          section.subsections.some(sub => sub.title.toLowerCase().includes(query))
      }).map(s => s.id)
      setExpandedSections(matchingSections)
    }
  }, [searchQuery])

  return (
    <div className="flex h-screen bg-light-bg dark:bg-dark-bg">
      {/* Mobile menu overlay */}
      {isMobileMenuOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={() => setIsMobileMenuOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className={`
        fixed lg:static inset-y-0 left-0 z-50
        w-72 bg-light-sidebar dark:bg-dark-sidebar
        border-r border-light-border dark:border-dark-border
        flex flex-col h-full
        transform transition-transform duration-200
        ${isMobileMenuOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
      `}>
        {/* Header */}
        <div className="p-4 border-b border-light-border dark:border-dark-border">
          <div className="flex items-center gap-3 mb-4">
            <button
              onClick={() => navigate('/')}
              className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg transition-colors"
              title="Back to Chat"
            >
              <ArrowLeft size={20} />
            </button>
            <div className="flex items-center gap-2">
              <BookOpen size={24} className="text-primary" />
              <span className="font-semibold text-lg">Documentation</span>
            </div>
          </div>

          {/* Search */}
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-light-text-secondary dark:text-dark-text-secondary" />
            <input
              type="text"
              placeholder="Search docs..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-8 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-light-border dark:hover:bg-dark-border rounded"
              >
                <X size={14} />
              </button>
            )}
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto p-2">
          {filteredSections.map(section => {
            const Icon = section.icon
            const isExpanded = expandedSections.includes(section.id)
            const isActive = currentSection === section.id

            return (
              <div key={section.id} className="mb-1">
                <button
                  onClick={() => {
                    toggleSection(section.id)
                    if (!isExpanded) {
                      navigateToSection(section.id)
                    }
                  }}
                  className={`
                    w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium
                    transition-colors
                    ${isActive && !currentSubsection
                      ? 'bg-primary/10 text-primary'
                      : 'hover:bg-light-border dark:hover:bg-dark-border'
                    }
                  `}
                >
                  <Icon size={18} className={isActive ? 'text-primary' : 'text-light-text-secondary dark:text-dark-text-secondary'} />
                  <span className="flex-1 text-left">{section.title}</span>
                  {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>

                {isExpanded && (
                  <div className="ml-6 mt-1 space-y-1">
                    {section.subsections
                      .filter(sub => !searchQuery || sub.title.toLowerCase().includes(searchQuery.toLowerCase()))
                      .map(sub => (
                        <button
                          key={sub.id}
                          onClick={() => navigateToSection(section.id, sub.id)}
                          className={`
                            w-full text-left px-3 py-1.5 rounded text-sm
                            transition-colors
                            ${currentSection === section.id && currentSubsection === sub.id
                              ? 'bg-primary/10 text-primary font-medium'
                              : 'text-light-text-secondary dark:text-dark-text-secondary hover:text-light-text dark:hover:text-dark-text hover:bg-light-border dark:hover:bg-dark-border'
                            }
                          `}
                        >
                          {sub.title}
                        </button>
                      ))}
                  </div>
                )}
              </div>
            )
          })}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-light-border dark:border-dark-border">
          <button
            onClick={() => navigate('/')}
            className="w-full py-2 px-4 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors flex items-center justify-center gap-2"
          >
            <MessageSquare size={18} />
            Back to Chat
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Mobile header */}
        <div className="lg:hidden flex items-center gap-3 p-4 border-b border-light-border dark:border-dark-border">
          <button
            onClick={() => setIsMobileMenuOpen(true)}
            className="p-2 hover:bg-light-border dark:hover:bg-dark-border rounded-lg"
          >
            <Book size={20} />
          </button>
          <span className="font-semibold">Documentation</span>
        </div>

        {/* Content */}
        <div
          ref={contentRef}
          className="flex-1 overflow-y-auto p-6 lg:p-12"
        >
          <div className="max-w-4xl mx-auto">
            <DocContent sectionId={currentSection} subsectionId={currentSubsection} />
          </div>
        </div>
      </main>
    </div>
  )
}

export default DocsPage
