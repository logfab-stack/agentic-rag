"""
Example tests demonstrating proper test isolation.

These tests show how to use the test fixtures to ensure
tests don't pollute production data.
"""

import pytest
from pathlib import Path


def test_basic_test_upload_dir(test_upload_dir):
    """
    Example: Using test_upload_dir fixture.

    This test demonstrates how to use a clean temporary directory
    that's automatically cleaned up after the test.
    """
    # Create a test file in the test directory
    test_file = test_upload_dir / "example.txt"
    test_file.write_text("This is test content")

    # Verify file was created
    assert test_file.exists()
    assert test_file.read_text() == "This is test content"

    # No cleanup needed - fixture handles it automatically


def test_cleanup_tracker(cleanup_test_files):
    """
    Example: Using cleanup_test_files fixture.

    This test demonstrates tracking files for automatic cleanup.
    """
    # Create a file somewhere
    test_file = Path("temp_test_file.txt")
    test_file.write_text("temporary content")

    # Register it for cleanup
    cleanup_test_files.add(test_file)

    # File exists during test
    assert test_file.exists()

    # File will be automatically deleted after test


def test_mock_upload_directory(mock_upload_dir):
    """
    Example: Using mock_upload_dir fixture.

    This test demonstrates overriding the UPLOAD_DIR
    to use a temporary directory.
    """
    # The mock_upload_dir is now the active upload directory
    # Any code that uses UPLOAD_DIR will use this temp directory

    # Create a file in the mock upload directory
    uploaded_file = mock_upload_dir / "uploaded_document.pdf"
    uploaded_file.write_bytes(b"%PDF-1.4 fake pdf content")

    # Verify file exists in mock directory
    assert uploaded_file.exists()
    assert uploaded_file.parent == mock_upload_dir

    # Everything is automatically cleaned up


def test_production_pollution_verification(verify_no_production_pollution, test_upload_dir):
    """
    Example: Using verify_no_production_pollution fixture.

    This test will FAIL if it creates any files in the
    production uploads directory (backend/uploads/).
    """
    # This is safe - uses test directory
    safe_file = test_upload_dir / "safe_file.txt"
    safe_file.write_text("This won't pollute production")

    # This would cause the test to FAIL:
    # production_dir = Path("backend/uploads")
    # bad_file = production_dir / "polluting_file.txt"
    # bad_file.write_text("This would fail the test")

    assert safe_file.exists()


def test_multiple_fixtures_together(
    test_upload_dir,
    cleanup_test_files,
    verify_no_production_pollution
):
    """
    Example: Using multiple fixtures together.

    This test combines several fixtures for comprehensive
    test isolation and cleanup.
    """
    # Create files in test directory
    file1 = test_upload_dir / "document1.txt"
    file1.write_text("Document 1 content")

    file2 = test_upload_dir / "document2.txt"
    file2.write_text("Document 2 content")

    # Register additional files for cleanup
    extra_file = Path("extra_temp.txt")
    extra_file.write_text("extra content")
    cleanup_test_files.add(extra_file)

    # Verify files exist
    assert file1.exists()
    assert file2.exists()
    assert extra_file.exists()

    # All files automatically cleaned up
    # Production directory verified to be untouched


def test_environment_variables_are_set():
    """
    Example: Verifying test environment is configured.

    This test checks that the test environment variables
    are properly set by the setup_test_environment fixture.
    """
    import os

    # These environment variables are automatically set for tests
    assert os.getenv("TESTING") == "true"

    # Upload directory points to test directory
    upload_dir = os.getenv("UPLOAD_DIR")
    assert upload_dir is not None
    assert "test_uploads" in upload_dir

    # Database uses test database
    db_path = os.getenv("EMBEDDING_DB_PATH")
    assert db_path is not None
    assert "test_" in db_path


def test_auto_cleanup_after_each_test(test_upload_dir):
    """
    Example: Demonstrating auto-cleanup behavior.

    Files created in test_upload_dir are automatically
    removed after each test, so tests don't interfere
    with each other.
    """
    # Create a file
    test_file = test_upload_dir / "auto_cleanup_test.txt"
    test_file.write_text("This file will be auto-deleted")

    assert test_file.exists()

    # No cleanup code needed - fixture does it automatically


@pytest.mark.parametrize("filename,content", [
    ("test1.txt", "content 1"),
    ("test2.txt", "content 2"),
    ("test3.txt", "content 3"),
])
def test_parametrized_with_fixtures(test_upload_dir, filename, content):
    """
    Example: Using fixtures with parametrized tests.

    Each parametrized test gets a fresh test_upload_dir.
    """
    # Create file with parametrized name and content
    test_file = test_upload_dir / filename
    test_file.write_text(content)

    # Verify
    assert test_file.exists()
    assert test_file.read_text() == content

    # Each parametrized test gets its own clean directory


def test_manual_cleanup_if_needed(cleanup_test_files):
    """
    Example: Manually triggering cleanup during test.

    Sometimes you need to cleanup files during the test,
    not just at the end.
    """
    # Create some files
    file1 = Path("temp1.txt")
    file1.write_text("temp")
    cleanup_test_files.add(file1)

    file2 = Path("temp2.txt")
    file2.write_text("temp")
    cleanup_test_files.add(file2)

    # Verify they exist
    assert file1.exists()
    assert file2.exists()

    # Manually trigger cleanup NOW
    cleanup_test_files.cleanup_now()

    # Files are gone
    assert not file1.exists()
    assert not file2.exists()

    # Can create more files after manual cleanup
    file3 = Path("temp3.txt")
    file3.write_text("new temp")
    cleanup_test_files.add(file3)

    # This will be cleaned up at end of test


def test_working_with_real_paths(test_upload_dir):
    """
    Example: Working with absolute paths in tests.

    Sometimes you need absolute paths for testing
    file operations.
    """
    # test_upload_dir is already a Path object
    assert isinstance(test_upload_dir, Path)

    # Get absolute path
    absolute_path = test_upload_dir.resolve()
    assert absolute_path.is_absolute()

    # Create nested directories
    nested_dir = test_upload_dir / "subdir" / "nested"
    nested_dir.mkdir(parents=True, exist_ok=True)

    nested_file = nested_dir / "file.txt"
    nested_file.write_text("nested content")

    # Verify structure
    assert nested_file.exists()
    assert nested_file.parent.name == "nested"

    # All automatically cleaned up


if __name__ == "__main__":
    # Run tests with: pytest backend/tests/test_example.py -v
    pytest.main([__file__, "-v"])
