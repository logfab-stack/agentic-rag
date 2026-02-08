"""
Pytest fixtures for RAG pipeline tests (Feature #349).

Provides:
- TestClient connected to the real FastAPI app
- Database session fixture for direct DB queries
- Sample test files (TXT, CSV) for upload tests
- Cleanup of test documents after each test
"""

import io
import os
import sys
import uuid
import pytest
from pathlib import Path
from typing import Generator, List

# Ensure backend is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Override the root conftest's SQLite DATABASE_URL - pipeline tests need PostgreSQL
# This must happen before any app imports
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/agentic_rag",
)
os.environ["DATABASE_SYNC_URL"] = os.environ.get(
    "TEST_DATABASE_SYNC_URL",
    "postgresql://postgres:postgres@localhost:5432/agentic_rag",
)


@pytest.fixture(scope="session", autouse=True)
def _restore_pg_env():
    """
    Re-set DATABASE_URL to PostgreSQL AFTER the root conftest overrides it to SQLite.
    Pipeline tests require a real PostgreSQL instance with pgvector.
    """
    os.environ["DATABASE_URL"] = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/agentic_rag",
    )
    os.environ["DATABASE_SYNC_URL"] = os.environ.get(
        "TEST_DATABASE_SYNC_URL",
        "postgresql://postgres:postgres@localhost:5432/agentic_rag",
    )
    # Disable rate limiting for TestClient compatibility
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    # Clear cached settings so they pick up the new URLs
    from functools import lru_cache
    import importlib
    if "core.config" in sys.modules:
        mod = sys.modules["core.config"]
        if hasattr(mod, "get_settings"):
            mod.get_settings.cache_clear()
        importlib.reload(mod)
    yield


@pytest.fixture(scope="session")
def client(_restore_pg_env):
    """
    FastAPI TestClient connected to the real app.

    Uses the actual PostgreSQL database - requires a running PostgreSQL instance.
    The TestClient triggers the app lifespan (DB init, migrations, etc.).
    """
    # Reload core.database and main to pick up the corrected DATABASE_URL
    for mod_name in ["core.database", "core.dependencies", "main"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def db_session(_restore_pg_env):
    """
    Sync SQLAlchemy session for direct DB queries during tests.
    """
    from core.database import SessionLocal
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sample_txt_content() -> str:
    """Sample text content about quantum computing for testing."""
    return (
        "Quantum Computing: An Introduction\n\n"
        "Quantum computing is a type of computation that harnesses quantum mechanical "
        "phenomena such as superposition and entanglement. Unlike classical computers "
        "that use bits (0 or 1), quantum computers use quantum bits or qubits, which "
        "can exist in multiple states simultaneously.\n\n"
        "Key Concepts:\n"
        "1. Superposition: A qubit can be in state |0>, |1>, or any quantum superposition "
        "of these states. This allows quantum computers to process many possibilities at once.\n\n"
        "2. Entanglement: When qubits become entangled, the state of one qubit is directly "
        "related to the state of another, regardless of the distance between them.\n\n"
        "3. Quantum Gates: Operations on qubits are performed using quantum gates, which "
        "are the quantum equivalent of classical logic gates.\n\n"
        "Applications include cryptography, drug discovery, optimization problems, "
        "and machine learning. Companies like IBM, Google, and Microsoft are actively "
        "developing quantum processors with increasing qubit counts.\n\n"
        "Quantum supremacy was first claimed by Google in 2019 when their Sycamore "
        "processor completed a task in 200 seconds that would take a classical "
        "supercomputer approximately 10,000 years."
    )


@pytest.fixture
def sample_csv_content() -> str:
    """Sample CSV data for structured document testing."""
    return (
        "product,category,price,quantity,region\n"
        "Laptop Pro,Electronics,1299.99,150,North America\n"
        "Wireless Mouse,Accessories,29.99,500,Europe\n"
        "USB-C Hub,Accessories,49.99,300,North America\n"
        "4K Monitor,Electronics,599.99,200,Asia Pacific\n"
        "Mechanical Keyboard,Accessories,89.99,400,Europe\n"
        "Webcam HD,Accessories,79.99,250,North America\n"
        "Laptop Stand,Accessories,39.99,350,Asia Pacific\n"
        "External SSD,Storage,119.99,180,Europe\n"
        "Noise Cancelling Headphones,Audio,249.99,220,North America\n"
        "Portable Charger,Accessories,34.99,600,Asia Pacific\n"
    )


@pytest.fixture
def upload_txt(client, sample_txt_content) -> Generator[dict, None, None]:
    """
    Upload a test TXT document and yield the response.
    Cleans up the document after the test.
    """
    unique_title = f"Test Quantum Doc {uuid.uuid4().hex[:8]}"
    files = {"file": ("test_quantum.txt", io.BytesIO(sample_txt_content.encode()), "text/plain")}
    data = {
        "title": unique_title,
        "comment": "Pytest pipeline test document",
        "async_processing": "false",  # Synchronous for predictable testing
    }

    resp = client.post("/api/documents/upload", files=files, data=data)
    assert resp.status_code == 201, f"Upload failed: {resp.status_code} {resp.text}"
    doc_data = resp.json()

    yield doc_data

    # Cleanup: delete the test document
    doc_id = doc_data["document"]["id"]
    client.delete(f"/api/documents/{doc_id}")


@pytest.fixture
def upload_csv(client, sample_csv_content) -> Generator[dict, None, None]:
    """
    Upload a test CSV document and yield the response.
    Cleans up the document after the test.
    """
    unique_title = f"Test Products CSV {uuid.uuid4().hex[:8]}"
    files = {"file": ("test_products.csv", io.BytesIO(sample_csv_content.encode()), "text/csv")}
    data = {
        "title": unique_title,
        "comment": "Pytest pipeline test CSV",
        "async_processing": "false",
    }

    resp = client.post("/api/documents/upload", files=files, data=data)
    assert resp.status_code == 201, f"CSV upload failed: {resp.status_code} {resp.text}"
    doc_data = resp.json()

    yield doc_data

    # Cleanup
    doc_id = doc_data["document"]["id"]
    client.delete(f"/api/documents/{doc_id}")


@pytest.fixture
def uploaded_doc_ids(request) -> List[str]:
    """
    Track document IDs created during a test for cleanup.
    Usage: uploaded_doc_ids.append(doc_id) then auto-cleanup runs after test.
    """
    ids = []
    yield ids
    # Cleanup is handled by individual upload fixtures
