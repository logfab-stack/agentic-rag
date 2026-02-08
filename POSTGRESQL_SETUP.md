# PostgreSQL + pgvector Setup Guide

## Current Status ✅

**What's Working:**
- ✅ PostgreSQL 15.15 installed and running
- ✅ Database `agentic_rag` exists and is accessible
- ✅ PostgreSQL stores documents, collections, conversations
- ✅ SQLite stores embeddings persistently (`backend/embeddings.db`)
- ✅ **Full application functionality working**

**Optional Enhancement:**
- ⚠️ pgvector extension NOT installed (see below for installation)

## Quick Start: Install pgvector (Optional)

To enable PostgreSQL-based vector storage, run ONE command:

```bash
./build_pgvector_for_pg15.sh
```

This automated script will:
1. Clone pgvector v0.8.1 from GitHub
2. Compile it for your PostgreSQL 15 installation
3. Install the extension (requires sudo password once)
4. Enable it in the `agentic_rag` database
5. Test functionality and clean up

**Time required:** 2-3 minutes

After installation, restart the backend to use PostgreSQL storage instead of SQLite.

## Why PostgreSQL with pgvector?

Currently, the system uses a **SQLite fallback** for embeddings:
- ✅ Embeddings persist across restarts in `backend/embeddings.db`
- ✅ All features work correctly
- ⚠️ Not as scalable as PostgreSQL pgvector for very large datasets

With PostgreSQL + pgvector (optional upgrade):
- ✅ Unified storage (everything in PostgreSQL)
- ✅ Better performance for large-scale vector operations
- ✅ Native database support for similarity search
- ✅ Production-ready for enterprise deployments

## Installation

### macOS (using Homebrew)

```bash
# Install PostgreSQL
brew install postgresql@15

# Start PostgreSQL service
brew services start postgresql@15

# Install pgvector extension
brew install pgvector
```

### Ubuntu/Debian

```bash
# Install PostgreSQL
sudo apt update
sudo apt install postgresql postgresql-contrib

# Install pgvector
sudo apt install postgresql-15-pgvector
```

### Docker (easiest option)

```bash
# Run PostgreSQL with pgvector in Docker
docker run -d \
  --name postgres-pgvector \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=agentic_rag \
  -p 5432:5432 \
  pgvector/pgvector:pg15
```

## Database Setup

### Option 1: Automated Setup Script

Run the provided setup script:

```bash
./setup_database.sh
```

This script will:
1. Check if PostgreSQL is running
2. Create the `agentic_rag` database
3. Enable the pgvector extension
4. Display the connection string

### Option 2: Manual Setup

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database
CREATE DATABASE agentic_rag;

# Connect to the new database
\c agentic_rag

# Enable pgvector extension
CREATE EXTENSION vector;

# Verify extension is enabled
\dx
```

## Configuration

The backend is already configured to use PostgreSQL. The connection settings are in `backend/.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agentic_rag
DATABASE_SYNC_URL=postgresql://postgres:postgres@localhost:5432/agentic_rag
```

Update these values if you use different credentials:
- **Username**: Change `postgres` to your username
- **Password**: Change `postgres` to your password
- **Host**: Change `localhost` if database is on a different server
- **Port**: Change `5432` if using a different port
- **Database**: Change `agentic_rag` to your database name

## Testing the Setup

1. Start the backend server:
```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload
```

2. Check the logs for:
```
INFO:__main__:PostgreSQL connection successful
INFO:__main__:pgvector extension is available
INFO:__main__:Database initialized successfully
```

3. Upload a text document (PDF, TXT, Markdown)
4. Restart the backend server
5. Query the document - it should still be searchable (embeddings persisted!)

## Troubleshooting

### PostgreSQL not running

**Error**: `PostgreSQL not available - using in-memory storage fallback`

**Solution**: Start PostgreSQL:
```bash
# macOS (Homebrew)
brew services start postgresql@15

# Linux (systemd)
sudo systemctl start postgresql

# Docker
docker start postgres-pgvector
```

### pgvector extension not found

**Error**: `pgvector extension not found`

**Solution**: Install pgvector extension:
```bash
# macOS
brew install pgvector

# Ubuntu/Debian
sudo apt install postgresql-15-pgvector

# Or use Docker image with pgvector pre-installed
```

### Connection refused

**Error**: `Database connection test failed`

**Solution**: Check your connection settings in `backend/.env`:
1. Verify the host, port, username, and password
2. Ensure PostgreSQL is running: `pg_isready`
3. Test connection manually: `psql -h localhost -U postgres -d agentic_rag`

### Permission denied

**Error**: `permission denied for database`

**Solution**: Grant permissions to your user:
```sql
-- Connect as superuser
psql -U postgres

-- Grant all privileges
GRANT ALL PRIVILEGES ON DATABASE agentic_rag TO your_username;
```

## Fallback Mode

If PostgreSQL is unavailable, the system automatically falls back to in-memory storage:
- The application continues to work normally
- Embeddings are stored in memory (lost on restart)
- A warning is logged: `Using in-memory fallback storage`

Once PostgreSQL becomes available, restart the backend to use persistent storage.

## Database Schema

The system creates the following table:

```sql
CREATE TABLE document_embeddings (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(255) NOT NULL,
    chunk_id VARCHAR(255) NOT NULL UNIQUE,
    text TEXT NOT NULL,
    embedding VECTOR,  -- pgvector type, supports any dimension
    metadata JSONB,
    INDEX ix_document_embeddings_document_id (document_id),
    INDEX ix_document_embeddings_embedding_vector (embedding) USING ivfflat WITH (lists = 100)
);
```

The `embedding` column uses pgvector's `VECTOR` type for efficient similarity search.

## Performance Tips

1. **Index Tuning**: The default IVFFlat index uses 100 lists. For larger datasets (>100k vectors), increase this:
```sql
CREATE INDEX ON document_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1000);
```

2. **Connection Pooling**: The system uses SQLAlchemy's connection pooling (pool_size=5, max_overflow=10). Adjust in `backend/core/database.py` if needed.

3. **Monitoring**: Check active connections:
```sql
SELECT count(*) FROM pg_stat_activity WHERE datname = 'agentic_rag';
```

## Migration from In-Memory Storage

If you have documents uploaded before this update:
1. Re-upload your documents after setting up PostgreSQL
2. The new embeddings will be stored persistently
3. Old in-memory embeddings will be lost (they were temporary anyway)

## Next Steps

- Configure your OpenAI API key in the UI (Settings)
- Upload documents and test vector search
- Embeddings now persist across restarts!
