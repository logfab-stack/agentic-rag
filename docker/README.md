# Docker Deployment Guide

This guide explains how to deploy the Agentic RAG System using Docker Compose.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.0+
- At least 4GB RAM available for containers
- OpenAI API key (or Ollama for local inference)

## Quick Start

### 1. Clone and Configure

```bash
# Clone the repository (if not already done)
git clone <repository-url>
cd RAG_4

# Copy and edit environment variables
cp .env.docker.example .env
```

Edit `.env` with your settings:
- **Required**: `OPENAI_API_KEY`
- **Recommended**: `COHERE_API_KEY` (for re-ranking)
- **Important**: Change `POSTGRES_PASSWORD` and `SECRET_KEY` for production

### 2. Start Services

```bash
# Start all services (PostgreSQL, Backend, Frontend)
docker compose -f docker-compose.prod.yml up -d

# Or include Ollama for local LLM inference
docker compose -f docker-compose.prod.yml --profile ollama up -d
```

### 3. Access the Application

- **Web Interface**: http://localhost:80 (or your configured FRONTEND_PORT)
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/health

## Services Overview

| Service | Description | Port | Health Check |
|---------|-------------|------|--------------|
| postgres | PostgreSQL 16 with pgvector | 5432 | pg_isready |
| backend | FastAPI application | 8000 | /api/ready |
| frontend | React app with nginx | 80 | /health |
| ollama | Local LLM (optional) | 11434 | /api/version |

## Architecture

```
                    ┌─────────────┐
                    │   Client    │
                    └──────┬──────┘
                           │ :80
                    ┌──────▼──────┐
                    │   nginx     │
                    │  (frontend) │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │ /api/*     │ /*         │
              │            │            │
       ┌──────▼──────┐    Static files
       │   backend   │    (React app)
       │  (FastAPI)  │
       └──────┬──────┘
              │
    ┌─────────┼─────────┐
    │         │         │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐
│postgres│ │OpenAI │ │Ollama │
│pgvector│ │  API  │ │(opt.) │
└────────┘ └───────┘ └───────┘
```

## Configuration

### Environment Variables

All configuration is done through environment variables. See `.env.docker.example` for a complete list.

**Key variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_PASSWORD` | Database password | postgres |
| `OPENAI_API_KEY` | OpenAI API key | (required) |
| `COHERE_API_KEY` | Cohere re-ranker API key | (optional) |
| `SECRET_KEY` | Encryption key | (change in prod) |
| `FRONTEND_PORT` | Public web port | 80 |
| `BACKEND_PORT` | API port | 8000 |
| `BACKEND_WORKERS` | Uvicorn workers | 2 |

### Using Ollama (Local LLM)

To use local models instead of OpenAI:

```bash
# Start with Ollama profile
docker compose -f docker-compose.prod.yml --profile ollama up -d

# Wait for Ollama to start, then pull a model
docker exec -it agentic-rag-ollama ollama pull llama3.2

# Configure the app to use Ollama models via the Settings UI
```

Set in `.env`:
```env
DEFAULT_LLM_MODEL=ollama:llama3.2
DEFAULT_EMBEDDING_MODEL=ollama:nomic-embed-text
```

## Data Persistence

All data is stored in Docker volumes:

| Volume | Purpose |
|--------|---------|
| `agentic-rag-postgres-data` | Database files |
| `agentic-rag-uploads` | Uploaded documents |
| `agentic-rag-logs` | Application logs |
| `agentic-rag-backups` | Automatic backups |
| `agentic-rag-bm25` | BM25 search index |
| `agentic-rag-ollama-data` | Ollama models (if used) |

## Operations

### View Logs

```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f backend

# Last 100 lines
docker compose -f docker-compose.prod.yml logs --tail=100 backend
```

### Health Checks

```bash
# Check all services
docker compose -f docker-compose.prod.yml ps

# Check specific endpoint
curl http://localhost:8000/api/health
curl http://localhost:8000/api/ready
```

### Restart Services

```bash
# Restart all
docker compose -f docker-compose.prod.yml restart

# Restart specific service
docker compose -f docker-compose.prod.yml restart backend
```

### Update to Latest Version

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
```

### Backup

```bash
# Backup database
docker exec agentic-rag-postgres pg_dump -U postgres agentic_rag > backup.sql

# Backup volumes (example with tar)
docker run --rm -v agentic-rag-uploads:/data -v $(pwd):/backup alpine \
  tar czf /backup/uploads-backup.tar.gz -C /data .
```

### Restore Database

```bash
# Stop backend to prevent writes
docker compose -f docker-compose.prod.yml stop backend

# Restore database
docker exec -i agentic-rag-postgres psql -U postgres agentic_rag < backup.sql

# Start backend
docker compose -f docker-compose.prod.yml start backend
```

## Troubleshooting

### Container won't start

```bash
# Check logs for errors
docker compose -f docker-compose.prod.yml logs <service>

# Check if port is in use
lsof -i :8000
lsof -i :5432
```

### Database connection issues

```bash
# Check if postgres is healthy
docker compose -f docker-compose.prod.yml ps postgres

# Try connecting manually
docker exec -it agentic-rag-postgres psql -U postgres -d agentic_rag
```

### pgvector not working

```bash
# Check extension is installed
docker exec -it agentic-rag-postgres psql -U postgres -d agentic_rag \
  -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

### Out of memory

Reduce worker count in `.env`:
```env
BACKEND_WORKERS=1
```

Or increase Docker memory limit in Docker Desktop settings.

## Production Checklist

- [ ] Change `POSTGRES_PASSWORD` to a strong password
- [ ] Generate a secure `SECRET_KEY`
- [ ] Set `OPENAI_API_KEY` (and optionally `COHERE_API_KEY`)
- [ ] Configure `CORS_ORIGINS` with your domain
- [ ] Set up SSL/TLS (see below)
- [ ] Enable security headers (`SECURITY_HEADERS_ENABLED=true`)
- [ ] Configure backup schedule
- [ ] Set up log rotation
- [ ] Monitor container health
- [ ] Test with SSL Labs and Security Headers scanners

## SSL/TLS Configuration (Feature #326)

The application includes built-in support for HTTPS with security headers.

### Quick Start with SSL

```bash
# Option 1: Self-signed certificates (development)
mkdir -p certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/privkey.pem -out certs/fullchain.pem \
  -subj "/CN=localhost"

docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml up -d

# Option 2: Automatic Let's Encrypt via Traefik (production)
export DOMAIN=yourdomain.com
export ACME_EMAIL=your@email.com
docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml \
  --profile traefik up -d
```

### Security Headers

When SSL is enabled, the following security headers are automatically added:

| Header | Purpose |
|--------|---------|
| `Strict-Transport-Security` | Forces HTTPS (HSTS) |
| `X-Frame-Options` | Prevents clickjacking |
| `X-Content-Type-Options` | Prevents MIME sniffing |
| `X-XSS-Protection` | XSS filter |
| `Referrer-Policy` | Controls referrer info |
| `Content-Security-Policy` | Controls resource loading |
| `Permissions-Policy` | Restricts browser features |

### SSL Environment Variables

```env
# Enable SSL mode
SSL_ENABLED=true
FORCE_HTTPS=true

# Certificate paths (for manual certificates)
SSL_CERT_PATH=./certs/fullchain.pem
SSL_KEY_PATH=./certs/privkey.pem

# Domain for Traefik
DOMAIN=yourdomain.com
ACME_EMAIL=admin@example.com

# Security header configuration
HSTS_MAX_AGE=31536000
HSTS_INCLUDE_SUBDOMAINS=true
```

**For detailed SSL setup instructions, see [docs/ssl-setup.md](../docs/ssl-setup.md).**

### Nginx Configuration Files

- `frontend/nginx.conf` - HTTP with security headers
- `frontend/nginx-ssl.conf` - Full HTTPS configuration

## Support

For issues or questions, please open an issue in the project repository.
