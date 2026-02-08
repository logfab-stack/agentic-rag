<p align="center">
  <h1 align="center">🤖 Agentic RAG</h1>
  <p align="center">
    An intelligent document assistant with agentic retrieval, hybrid search, and multi-format support.
    <br />
    Built with FastAPI, React, PostgreSQL/pgvector, and LangChain.
  </p>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#docker-deployment">Docker</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#api-reference">API</a> •
  <a href="#license">License</a>
</p>

---

## What is Agentic RAG?

Agentic RAG is a **production-ready Retrieval-Augmented Generation system** that goes beyond simple document Q&A. It combines semantic vector search with SQL-based tabular analysis, using an agentic architecture that autonomously decides _how_ to answer your questions.

Upload your documents — PDFs, Word files, spreadsheets, CSVs — and have a natural conversation with an AI that retrieves, analyzes, and cross-references your data intelligently.

### Key Differentiators

- **🧠 Agentic Semantic Chunking** — Instead of fixed-size chunks, an LLM analyzes your text and splits it at natural topic boundaries, preserving semantic coherence
- **🔀 Hybrid Search** — Combines BM25 keyword matching with vector semantic search via Reciprocal Rank Fusion, delivering the best of both approaches
- **📊 Structured + Unstructured** — Text documents are vectorized for semantic search; tabular data (CSV, Excel, JSON) is stored for SQL queries. The agent picks the right tool automatically
- **💬 Multi-Channel** — Chat via the web UI, Telegram bot, or WhatsApp
- **🏭 Production-Ready** — Automatic backups, health checks, audit logging, rate limiting, security headers, and async document processing

---

## Features

### 📄 Document Management
- Upload **PDF, TXT, Word (.docx), Markdown, CSV, Excel (.xlsx), JSON**
- Organize documents into **collections**
- Preview content, add names and notes
- Duplicate detection and file size limits (100MB)
- Background async processing queue with progress indicators
- Soft delete with recovery

### 🔍 Intelligent Search & Retrieval
- **Semantic vector search** via PostgreSQL pgvector
- **BM25 keyword search** for exact terms, acronyms, and technical jargon
- **Hybrid Reciprocal Rank Fusion** combining both approaches
- **Re-ranking** with Cohere API or local Cross-Encoder models
- **Agentic chunking** — LLM-based semantic splitting instead of fixed-size chunks
- **Anti-hallucination guardrails** — the system knows when it doesn't know

### 🤖 AI Chat
- **ReAct Agent** architecture with tool calling
- Automatic selection between **RAG** (text search) and **SQL** (tabular queries)
- **Streaming responses** via WebSocket
- **Conversational context** — query rewriting for follow-up questions
- **Suggested follow-up questions** after each response
- **Response caching** to reduce API costs
- **Bilingual** support (Italian & English)

### 🔧 LLM Providers
- **OpenAI** — GPT-4o, GPT-4o-mini (default)
- **OpenRouter** — Access 100+ models (Llama, Mistral, Claude, etc.)
- **Ollama** — Run models locally with auto-detection of installed models
- All configurable from the Settings UI — no code changes needed

### 📱 Multi-Channel Bots
- **Telegram Bot** — Full document Q&A via Telegram, with document upload support
- **WhatsApp Bot** — Integration via Twilio API
- **Ngrok tunneling** — For webhook testing during local development

### 🛡️ Production Infrastructure
- **Automatic daily backups** with configurable retention
- **Health checks** — `/api/health`, `/api/ready`, `/api/live`, embedding integrity
- **Audit logging** for document operations
- **Rate limiting** via SlowAPI
- **Security headers** and request tracing
- **File integrity verification** scheduler
- **Structured JSON logging**

### 📊 Admin & Analytics
- **Dashboard** with system analytics
- **Maintenance panel** — re-embedding, soft delete management, integrity checks
- **Feedback system** — rate AI responses and individual chunks
- **Export** conversations and analysis results
- **Notes** — personal annotations on documents

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, FastAPI, LangChain/LangGraph |
| **Frontend** | React 18, TypeScript 5, Tailwind CSS, Zustand, React Query |
| **Database** | PostgreSQL 16 with pgvector extension |
| **LLM** | OpenAI / OpenRouter / Ollama |
| **Embeddings** | OpenAI text-embedding-3-small / Ollama / OpenRouter |
| **Re-ranking** | Cohere / Cross-Encoder |
| **Deployment** | Docker Compose (4 services) |
| **Messaging** | Telegram Bot API, Twilio (WhatsApp) |

---

## Quick Start

### Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- **PostgreSQL 15+** with [pgvector](https://github.com/pgvector/pgvector) extension
- **OpenAI API key** (or Ollama for local models)

### One-Command Setup

```bash
git clone https://github.com/logfab-stack/agentic-rag.git
cd agentic-rag
./init.sh
```

The setup script will:
1. ✅ Check prerequisites (Python, Node, PostgreSQL, pgvector)
2. ✅ Create Python virtual environment and install dependencies
3. ✅ Install frontend dependencies
4. ✅ Start both backend and frontend servers

### Manual Setup

<details>
<summary>Click to expand manual setup instructions</summary>

**1. Database**

```bash
# Create PostgreSQL database
createdb agentic_rag

# Enable pgvector extension
psql -d agentic_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**2. Backend**

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys and database URL

# Run database migrations
alembic upgrade head

# Start server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**3. Frontend**

```bash
cd frontend
npm install
npm run dev
```

</details>

### Access the Application

| Service | URL |
|---------|-----|
| 🌐 Web UI | http://localhost:3000 |
| 🔌 API | http://localhost:8000 |
| 📚 API Docs (Swagger) | http://localhost:8000/docs |

### First Steps

1. Open **Settings** → enter your **OpenAI API key**
2. Upload a document (PDF, Word, CSV, etc.)
3. Start chatting — ask questions about your documents!

---

## Docker Deployment

The recommended way to run in production:

```bash
# Copy and edit environment config
cp .env.docker.example .env

# Start all services
docker compose -f docker-compose.prod.yml up -d
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| **PostgreSQL** | 5432 | Database with pgvector |
| **Backend** | 8000 | FastAPI application |
| **Frontend** | 3000 | React app served via Nginx |
| **Ollama** (optional) | 11434 | Local LLM inference |

### With Local LLM (Ollama)

```bash
# Include Ollama with GPU support
docker compose -f docker-compose.prod.yml --profile ollama up -d
```

### SSL/TLS

```bash
# HTTPS with SSL certificates
docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml up -d
```

### Persistent Data

All data is stored in Docker volumes:
- `postgres_data` — Database
- `backend_uploads` — Uploaded documents
- `backend_backups` — Automatic backups
- `backend_logs` — Application logs

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │   Chat   │ │Documents │ │Dashboard │ │   Settings   │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘   │
└───────┼─────────────┼────────────┼──────────────┼───────────┘
        │  REST API + WebSocket    │              │
┌───────┼─────────────┼────────────┼──────────────┼───────────┐
│       ▼             ▼            ▼              ▼           │
│                    FastAPI Backend                           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │               ReAct Agent (LangChain)               │    │
│  │                                                     │    │
│  │  ┌─────────────┐  ┌──────────────┐  ┌───────────┐  │    │
│  │  │  RAG Tool   │  │   SQL Tool   │  │ Chat Tool │  │    │
│  │  │ (text docs) │  │(tabular data)│  │ (general) │  │    │
│  │  └──────┬──────┘  └──────┬───────┘  └───────────┘  │    │
│  └─────────┼────────────────┼──────────────────────────┘    │
│            │                │                               │
│  ┌─────────▼────────┐  ┌───▼──────────────┐                │
│  │  Hybrid Search   │  │  SQL Generation  │                │
│  │ Vector + BM25    │  │  (Pandas/SQL)    │                │
│  │ + Re-ranking     │  │                  │                │
│  └─────────┬────────┘  └───┬──────────────┘                │
└────────────┼────────────────┼───────────────────────────────┘
             │                │
    ┌────────▼────────────────▼────────┐
    │    PostgreSQL + pgvector         │
    │  ┌────────────┐ ┌────────────┐   │
    │  │  Vectors   │ │ Structured │   │
    │  │ (embeddings│ │   (rows,   │   │
    │  │  + chunks) │ │  metadata) │   │
    │  └────────────┘ └────────────┘   │
    └──────────────────────────────────┘
```

### Ingestion Pipeline

```
Document Upload
      │
      ├── Text (PDF, DOCX, TXT, MD)
      │     │
      │     ▼
      │   Agentic Semantic Chunking
      │     │  (LLM detects topic changes)
      │     ▼
      │   Generate Embeddings
      │     │
      │     ▼
      │   Store in pgvector
      │
      └── Tabular (CSV, XLSX, JSON)
            │
            ▼
          Parse with Pandas
            │
            ▼
          Extract Schema + Rows
            │
            ▼
          Store as JSONB in PostgreSQL
```

---

## Configuration

### Environment Variables

Copy the example and customize:

```bash
cp backend/.env.example backend/.env
```

Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://postgres:postgres@localhost:5432/agentic_rag` |
| `OPENAI_API_KEY` | OpenAI API key | _(set via UI)_ |
| `OPENROUTER_API_KEY` | OpenRouter API key | _(optional)_ |
| `COHERE_API_KEY` | Cohere re-ranking API key | _(optional)_ |
| `OLLAMA_BASE_URL` | Ollama endpoint | `http://localhost:11434` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | _(optional)_ |
| `BACKUP_ENABLED` | Enable automatic backups | `true` |
| `BACKUP_RETENTION_DAYS` | Days to keep backups | `30` |

> 💡 Most settings can be configured from the **Settings UI** — no need to edit files manually.

### Model Selection

Configure via Settings UI or environment:

| Purpose | Options |
|---------|---------|
| **Chat LLM** | GPT-4o, GPT-4o-mini, Ollama models, OpenRouter models |
| **Embeddings** | OpenAI text-embedding-3-small, Ollama, OpenRouter |
| **Re-ranking** | Cohere, Cross-Encoder (local) |

---

## API Reference

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat` | Send message (streaming via WebSocket) |
| `GET` | `/api/documents` | List all documents |
| `POST` | `/api/documents/upload` | Upload and process document |
| `GET` | `/api/documents/{id}` | Get document details |
| `DELETE` | `/api/documents/{id}` | Delete document |
| `GET` | `/api/collections` | List collections |
| `POST` | `/api/collections` | Create collection |
| `GET` | `/api/conversations` | List conversations |
| `GET` | `/api/settings` | Get configuration |
| `PATCH` | `/api/settings` | Update configuration |

### Health & Monitoring

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Detailed health check |
| `GET` | `/api/ready` | Startup readiness probe |
| `GET` | `/api/live` | Liveness probe |
| `GET` | `/api/embeddings/health-check` | Embedding service health |

### Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/admin/maintenance/dashboard` | System dashboard |
| `POST` | `/api/admin/maintenance/reembed` | Re-embed documents |
| `POST` | `/api/backup` | Create manual backup |

Full API documentation available at `/docs` (Swagger UI) when running.

---

## Project Structure

```
agentic-rag/
├── backend/
│   ├── api/                  # REST API route handlers (17 modules)
│   ├── core/                 # Config, database, middleware, errors
│   ├── models/               # Pydantic + SQLAlchemy models
│   ├── services/             # Business logic (23 services)
│   │   ├── ai_service.py         # LLM orchestration, RAG pipeline
│   │   ├── agentic_splitter.py   # Semantic chunking engine
│   │   ├── bm25_service.py       # BM25 keyword search
│   │   ├── embedding_store.py    # Vector storage & retrieval
│   │   ├── telegram_service.py   # Telegram bot handler
│   │   └── ...
│   ├── alembic/              # Database migrations
│   ├── utils/                # Helper functions
│   ├── main.py               # FastAPI app entry point
│   ├── Dockerfile            # Backend container
│   └── requirements.txt      # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── components/       # React components (31 files)
│   │   ├── hooks/            # Custom React hooks
│   │   ├── services/         # API client functions
│   │   ├── types/            # TypeScript interfaces
│   │   └── App.tsx           # Root component & router
│   ├── nginx.conf            # Reverse proxy config
│   ├── Dockerfile            # Frontend container
│   └── package.json          # Node dependencies
├── prompts/                  # AI system prompts
├── docker-compose.prod.yml   # Production deployment
├── docker-compose.ssl.yml    # SSL/TLS overlay
├── .env.docker.example       # Docker env template
├── init.sh                   # One-command local setup
└── README.md
```

---

## Development

### Running Tests

```bash
cd backend
source venv/bin/activate
pytest
```

### Database Migrations

```bash
cd backend
alembic upgrade head        # Apply all migrations
alembic revision --autogenerate -m "description"  # Create new migration
```

### Adding a New Document Type

1. Add parser in `backend/services/`
2. Register in the ingestion pipeline (`backend/api/documents.py`)
3. Update accepted MIME types in frontend upload component

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## Acknowledgments

- [LangChain](https://github.com/langchain-ai/langchain) — LLM framework
- [pgvector](https://github.com/pgvector/pgvector) — Vector similarity search for PostgreSQL
- [FastAPI](https://fastapi.tiangolo.com/) — Modern Python web framework
- [OpenWebUI](https://github.com/open-webui/open-webui) — UI inspiration

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
