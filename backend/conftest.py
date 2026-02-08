"""
Pytest configuration and fixtures for test isolation.

This module provides test fixtures that ensure tests use separate
directories and databases from production data.
"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path
from typing import Generator


# Test directory paths
TEST_UPLOAD_DIR = Path(__file__).parent / "test_uploads"
TEST_DB_PATH = Path(__file__).parent / "test_embeddings.db"


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """
    Session-level fixture to set up test environment variables.
    This runs once before all tests and ensures tests use test directories.
    """
    # Store original environment
    original_env = {}

    # Set test environment variables
    test_env = {
        "UPLOAD_DIR": str(TEST_UPLOAD_DIR),
        "EMBEDDING_DB_PATH": str(TEST_DB_PATH),
        "DATABASE_URL": "sqlite:///./test_app.db",
        "TESTING": "true",
    }

    for key, value in test_env.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = value

    # Create test directories
    TEST_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    yield

    # Restore original environment
    for key, original_value in original_env.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


@pytest.fixture(scope="function")
def test_upload_dir() -> Generator[Path, None, None]:
    """
    Function-level fixture that provides a clean test upload directory
    for each test. Automatically cleans up after the test.

    Usage:
        def test_upload(test_upload_dir):
            file_path = test_upload_dir / "test_file.txt"
            file_path.write_text("test content")
            # Directory is automatically cleaned up after test
    """
    # Create unique temp directory for this test
    temp_dir = Path(tempfile.mkdtemp(prefix="test_upload_", dir=TEST_UPLOAD_DIR))

    yield temp_dir

    # Cleanup: Remove all files created during test
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="function")
def cleanup_test_files():
    """
    Fixture to track and cleanup test files created during a test.

    Usage:
        def test_something(cleanup_test_files):
            file_path = create_test_file()
            cleanup_test_files.add(file_path)
            # File is automatically deleted after test
    """
    files_to_cleanup = []

    class FileTracker:
        def add(self, path):
            """Add a file or directory to cleanup list."""
            files_to_cleanup.append(Path(path))

        def cleanup_now(self):
            """Manually trigger cleanup."""
            for path in files_to_cleanup:
                if path.exists():
                    if path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        path.unlink(missing_ok=True)
            files_to_cleanup.clear()

    tracker = FileTracker()
    yield tracker

    # Cleanup all tracked files
    tracker.cleanup_now()


@pytest.fixture(scope="function", autouse=True)
def cleanup_test_uploads_after_test():
    """
    Auto-cleanup fixture that removes ALL files from test_uploads
    after each test function. This ensures tests don't pollute
    the test directory.
    """
    yield

    # Remove all files in test_uploads directory (but keep the directory itself)
    if TEST_UPLOAD_DIR.exists():
        for item in TEST_UPLOAD_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)


@pytest.fixture(scope="function")
def mock_upload_dir(monkeypatch, tmp_path) -> Path:
    """
    Fixture that temporarily overrides the UPLOAD_DIR to use a
    temporary directory. Useful for testing upload functionality
    without affecting any real directories.

    Usage:
        def test_upload_endpoint(mock_upload_dir):
            # All uploads go to mock_upload_dir
            # Automatically cleaned up after test
    """
    # Patch the upload directory
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

    # If api.documents is already imported, patch it too
    try:
        from api import documents
        monkeypatch.setattr(documents, "UPLOAD_DIR", tmp_path)
    except ImportError:
        pass

    return tmp_path


@pytest.fixture(scope="session")
def cleanup_test_db_on_exit():
    """
    Session-level fixture that cleans up test database files
    when all tests are complete.
    """
    yield

    # Cleanup test database files
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink(missing_ok=True)

    # Cleanup WAL and SHM files if they exist
    for ext in ["-wal", "-shm"]:
        db_file = Path(str(TEST_DB_PATH) + ext)
        if db_file.exists():
            db_file.unlink(missing_ok=True)


@pytest.fixture(scope="function")
def verify_no_production_pollution():
    """
    Verification fixture that ensures tests haven't created any
    files in the production uploads directory.

    Usage:
        def test_something(verify_no_production_pollution):
            # Your test code
            # Verification happens automatically after test
    """
    production_upload_dir = Path(__file__).parent / "uploads"

    # Get initial state of production directory
    initial_files = set()
    if production_upload_dir.exists():
        initial_files = set(production_upload_dir.rglob("*"))

    yield

    # Verify no new files were created
    if production_upload_dir.exists():
        final_files = set(production_upload_dir.rglob("*"))
        new_files = final_files - initial_files

        if new_files:
            # List the offending files
            file_list = "\n".join(f"  - {f.relative_to(production_upload_dir)}" for f in new_files)
            raise AssertionError(
                f"Test created files in production uploads directory!\n"
                f"Files created:\n{file_list}\n"
                f"Tests should only use test_uploads directory."
            )
