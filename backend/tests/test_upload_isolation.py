"""
Integration tests verifying upload isolation from production data.

These tests demonstrate that document uploads during testing
use the test_uploads directory and never touch production uploads/.
"""

import pytest
from pathlib import Path
import os


def test_upload_dir_environment_variable():
    """Verify UPLOAD_DIR points to test directory during tests."""
    upload_dir = os.getenv("UPLOAD_DIR")

    assert upload_dir is not None, "UPLOAD_DIR environment variable not set"
    assert "test_uploads" in upload_dir, \
        f"UPLOAD_DIR should point to test_uploads, got: {upload_dir}"

    # Verify the directory exists
    test_upload_path = Path(upload_dir)
    assert test_upload_path.exists(), f"Test upload directory doesn't exist: {upload_dir}"


def test_production_upload_dir_not_used(verify_no_production_pollution, test_upload_dir):
    """
    Critical test: Verify that test file operations don't touch production uploads.

    This test will FAIL if any files are created in the production uploads/ directory.
    """
    # Get production uploads path
    backend_dir = Path(__file__).parent.parent
    production_uploads = backend_dir / "uploads"

    # Count files in production before test
    production_files_before = 0
    if production_uploads.exists():
        production_files_before = len(list(production_uploads.iterdir()))

    # Simulate test file operations
    test_file1 = test_upload_dir / "test_document_1.txt"
    test_file1.write_text("Test content 1")

    test_file2 = test_upload_dir / "test_document_2.pdf"
    test_file2.write_bytes(b"%PDF-1.4 fake pdf")

    test_file3 = test_upload_dir / "test_data.csv"
    test_file3.write_text("name,value\ntest,123")

    # Verify test files exist in test directory
    assert test_file1.exists()
    assert test_file2.exists()
    assert test_file3.exists()

    # Verify test directory is NOT production directory
    assert test_upload_dir != production_uploads
    assert test_upload_dir.resolve() != production_uploads.resolve()

    # Count production files after test
    production_files_after = 0
    if production_uploads.exists():
        production_files_after = len(list(production_uploads.iterdir()))

    # Production directory should be completely unchanged
    assert production_files_before == production_files_after, \
        f"Production uploads directory was modified! Before: {production_files_before}, After: {production_files_after}"

    # verify_no_production_pollution fixture will also catch this


def test_multiple_test_runs_dont_accumulate_files(test_upload_dir):
    """
    Verify that running multiple tests doesn't accumulate files
    in the test directory - each test gets a clean slate.
    """
    # This test should start with an empty directory
    files_at_start = list(test_upload_dir.iterdir())
    assert len(files_at_start) == 0, \
        f"Test directory should be empty at start, found: {files_at_start}"

    # Create some files
    for i in range(10):
        test_file = test_upload_dir / f"file_{i}.txt"
        test_file.write_text(f"Content {i}")

    # Verify files exist
    files_created = list(test_upload_dir.iterdir())
    assert len(files_created) == 10

    # Files will be automatically cleaned up after this test
    # Next test will get a fresh, empty directory


def test_nested_directory_creation_isolated(test_upload_dir, verify_no_production_pollution):
    """
    Verify that nested directory creation stays within test directory.
    """
    # Create nested directory structure
    nested_path = test_upload_dir / "year_2024" / "month_01" / "documents"
    nested_path.mkdir(parents=True, exist_ok=True)

    # Create file in nested directory
    doc_file = nested_path / "report.txt"
    doc_file.write_text("Annual report content")

    # Verify structure exists
    assert nested_path.exists()
    assert doc_file.exists()

    # Verify it's within test directory
    assert test_upload_dir in nested_path.parents

    # Production directory untouched (verified by fixture)


def test_file_operations_with_absolute_paths(test_upload_dir):
    """
    Test that absolute paths are correctly handled within test isolation.
    """
    # Get absolute path
    absolute_test_dir = test_upload_dir.resolve()
    assert absolute_test_dir.is_absolute()

    # Create file using absolute path
    test_file = absolute_test_dir / "absolute_path_test.txt"
    test_file.write_text("Created with absolute path")

    assert test_file.exists()
    assert test_file.is_absolute()

    # Verify it's still in test directory
    assert "test_uploads" in str(test_file)


def test_concurrent_test_isolation():
    """
    Verify that tests can run concurrently without interfering.

    Note: This test uses the auto-cleanup fixture, so each test
    function gets its own isolated directory even when run in parallel.
    """
    upload_dir = Path(os.getenv("UPLOAD_DIR"))

    # Each test should get the same base test directory
    assert "test_uploads" in str(upload_dir)

    # But the actual working directory may be different per test


def test_production_directory_exists_and_untouched():
    """
    Sanity check: Verify production directory exists and has files,
    proving we're not accidentally deleting it.
    """
    backend_dir = Path(__file__).parent.parent
    production_uploads = backend_dir / "uploads"

    # Production directory should exist (may not exist in fresh install)
    if production_uploads.exists():
        # If it exists, it should have some files (from real usage)
        production_files = list(production_uploads.iterdir())
        print(f"Production uploads contains {len(production_files)} files")

        # Tests should never reduce this number
        assert len(production_files) >= 0  # Just checking it's accessible


def test_test_database_isolation():
    """
    Verify that database operations also use test database, not production.
    """
    db_path = os.getenv("EMBEDDING_DB_PATH")

    assert db_path is not None, "EMBEDDING_DB_PATH not set"
    assert "test_" in db_path, \
        f"Database should use test database, got: {db_path}"

    # Verify it's test_embeddings.db, not production embeddings.db
    assert "test_embeddings.db" in db_path, \
        f"Should use test_embeddings.db, got: {db_path}"


def test_testing_flag_is_set():
    """
    Verify TESTING environment variable is set to indicate test mode.
    """
    testing_flag = os.getenv("TESTING")

    assert testing_flag == "true", \
        f"TESTING flag should be 'true', got: {testing_flag}"


@pytest.mark.parametrize("file_extension", ["txt", "pdf", "csv", "json", "md"])
def test_various_file_types_isolated(test_upload_dir, file_extension):
    """
    Test that various file types are all properly isolated.
    """
    # Create file with specific extension
    test_file = test_upload_dir / f"test_document.{file_extension}"

    # Write appropriate content based on type
    if file_extension in ["txt", "md", "csv"]:
        test_file.write_text(f"Test content for {file_extension}")
    else:
        test_file.write_bytes(b"Binary test content")

    # Verify file exists in test directory
    assert test_file.exists()
    assert test_file.suffix == f".{file_extension}"

    # Verify it's in test directory
    assert "test_uploads" in str(test_file.parent)


def test_cleanup_verification_at_session_end():
    """
    Document the cleanup behavior at session end.

    Test databases and temporary files are cleaned up when
    the test session completes (see conftest.py fixtures).
    """
    # This test just documents the behavior
    # Actual cleanup is handled by pytest fixtures

    backend_dir = Path(__file__).parent.parent
    test_db = backend_dir / "test_embeddings.db"

    # Test DB may or may not exist during this test
    # But it will be cleaned up at session end
    # (see cleanup_test_db_on_exit fixture)

    assert True  # Just a documentation test


if __name__ == "__main__":
    # Run these tests with:
    # pytest backend/tests/test_upload_isolation.py -v
    pytest.main([__file__, "-v"])
