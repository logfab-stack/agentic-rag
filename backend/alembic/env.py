"""Alembic environment configuration for sync SQLAlchemy migrations."""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool, create_engine
from sqlalchemy.engine import Connection

from alembic import context

# Add parent directory to path so we can import from our app
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import Base from our models - this contains all table metadata
from models.db_models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target_metadata to our Base.metadata for autogenerate support
target_metadata = Base.metadata

# Get database URL from environment variable or use default
# Use sync URL for migrations (not async)
database_url = os.getenv(
    "DATABASE_SYNC_URL",
    "postgresql://postgres:postgres@localhost:5432/agentic_rag"
)

# Ensure we use sync psycopg2 driver (not asyncpg)
if database_url.startswith("postgresql+asyncpg://"):
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

# Override the sqlalchemy.url in alembic.ini
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # Enable type comparison for autogenerate
        compare_server_default=True,  # Enable default comparison
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    Uses sync engine for migrations (simpler and more reliable).
    """
    # Create sync engine for migrations
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # Enable type comparison for autogenerate
            compare_server_default=True,  # Enable default comparison
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
