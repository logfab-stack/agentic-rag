"""Initial migration with all models

Revision ID: 001
Revises:
Create Date: 2026-01-27 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables for the Agentic RAG System."""

    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create collections table
    op.create_table(
        'collections',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_collections_name'), 'collections', ['name'], unique=True)

    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('original_filename', sa.String(length=500), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('document_type', sa.String(length=20), nullable=False, server_default='unstructured'),
        sa.Column('collection_id', sa.String(length=36), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('schema_info', sa.Text(), nullable=True),
        sa.Column('url', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_documents_collection', 'documents', ['collection_id'])
    op.create_index('idx_documents_created', 'documents', ['created_at'])
    op.create_index('idx_documents_type', 'documents', ['document_type'])
    op.create_index(op.f('ix_documents_title'), 'documents', ['title'])
    op.create_index(op.f('ix_documents_content_hash'), 'documents', ['content_hash'], unique=True)

    # Create document_rows table for structured data
    op.create_table(
        'document_rows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.String(length=36), nullable=False),
        sa.Column('row_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_document_rows_dataset', 'document_rows', ['dataset_id'])

    # Create conversations table
    op.create_table(
        'conversations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_conversations_updated', 'conversations', ['updated_at'])

    # Create messages table
    op.create_table(
        'messages',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('conversation_id', sa.String(length=36), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tool_used', sa.String(length=100), nullable=True),
        sa.Column('tool_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('response_source', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_messages_conversation', 'messages', ['conversation_id'])
    op.create_index('idx_messages_created', 'messages', ['created_at'])

    # Create settings table
    op.create_table(
        'settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )

    # Create document_embeddings table for vector search with pgvector
    op.create_table(
        'document_embeddings',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('document_id', sa.String(length=255), nullable=False),
        sa.Column('chunk_id', sa.String(length=255), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('embedding', sa.Text(), nullable=False),  # pgvector type will be applied
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chunk_id')
    )
    op.create_index('ix_document_embeddings_document_id', 'document_embeddings', ['document_id'])

    # Create vector index for similarity search (requires pgvector extension)
    # Note: This index creation might fail if pgvector is not installed
    # The application will handle this gracefully in init_db()
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_embeddings_embedding_vector
        ON document_embeddings
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    """Drop all tables."""
    # Drop document_embeddings table and its indexes
    op.execute('DROP INDEX IF EXISTS ix_document_embeddings_embedding_vector')
    op.drop_index('ix_document_embeddings_document_id', table_name='document_embeddings')
    op.drop_table('document_embeddings')

    # Drop other tables
    op.drop_table('settings')
    op.drop_index('idx_messages_created', table_name='messages')
    op.drop_index('idx_messages_conversation', table_name='messages')
    op.drop_table('messages')
    op.drop_index('idx_conversations_updated', table_name='conversations')
    op.drop_table('conversations')
    op.drop_index('idx_document_rows_dataset', table_name='document_rows')
    op.drop_table('document_rows')
    op.drop_index(op.f('ix_documents_content_hash'), table_name='documents')
    op.drop_index(op.f('ix_documents_title'), table_name='documents')
    op.drop_index('idx_documents_type', table_name='documents')
    op.drop_index('idx_documents_created', table_name='documents')
    op.drop_index('idx_documents_collection', table_name='documents')
    op.drop_table('documents')
    op.drop_index(op.f('ix_collections_name'), table_name='collections')
    op.drop_table('collections')
