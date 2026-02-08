-- =============================================================================
-- Agentic RAG System - PostgreSQL Initialization Script
-- =============================================================================
-- This script runs automatically when the PostgreSQL container is first created.
-- It sets up the pgvector extension and optimizes settings for the RAG workload.
-- =============================================================================

-- Create pgvector extension (required for semantic search)
CREATE EXTENSION IF NOT EXISTS vector;

-- Additional useful extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- For fuzzy text search
CREATE EXTENSION IF NOT EXISTS unaccent;   -- For accent-insensitive search

-- =============================================================================
-- Performance Tuning for RAG Workloads
-- =============================================================================
-- These settings optimize PostgreSQL for vector similarity searches
-- Adjust based on your available memory and expected workload

-- Memory settings (applied per-connection)
-- Increase work_mem for complex queries with sorting/hashing
ALTER SYSTEM SET work_mem = '64MB';

-- Maintenance operations like VACUUM and CREATE INDEX
ALTER SYSTEM SET maintenance_work_mem = '512MB';

-- Effective cache size hint for query planner (adjust to ~75% of RAM)
ALTER SYSTEM SET effective_cache_size = '2GB';

-- Shared buffers (should be ~25% of total RAM, typically)
-- Default of 128MB is often too low for production
ALTER SYSTEM SET shared_buffers = '512MB';

-- =============================================================================
-- pgvector Index Configuration
-- =============================================================================
-- HNSW index parameters (adjust based on your accuracy/speed requirements)
-- These are applied when indexes are created by the application

-- For HNSW indexes:
-- - ef_construction: Higher = more accurate index, slower build (default: 64)
-- - m: Number of connections per layer (default: 16)

-- Set search performance parameter
-- ef_search: Higher = more accurate search, slower query (default: 40)
ALTER SYSTEM SET hnsw.ef_search = 100;

-- =============================================================================
-- Connection and Query Settings
-- =============================================================================
-- Statement timeout to prevent runaway queries (5 minutes for AI operations)
ALTER SYSTEM SET statement_timeout = '300000';

-- Lock timeout to prevent lock contention
ALTER SYSTEM SET lock_timeout = '10000';

-- Log slow queries for debugging (queries over 1 second)
ALTER SYSTEM SET log_min_duration_statement = 1000;

-- Apply settings
SELECT pg_reload_conf();

-- =============================================================================
-- Verification
-- =============================================================================
-- Verify pgvector is installed
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pgvector extension failed to install';
    END IF;
    RAISE NOTICE 'pgvector extension installed successfully';
END $$;

-- Log successful initialization
DO $$
BEGIN
    RAISE NOTICE '===========================================';
    RAISE NOTICE 'Agentic RAG Database initialized';
    RAISE NOTICE 'pgvector: ENABLED';
    RAISE NOTICE 'pg_trgm: ENABLED';
    RAISE NOTICE '===========================================';
END $$;
