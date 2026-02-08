# Test Infrastructure

This directory contains tests for the Agentic RAG System with proper isolation from production data.

## Test Isolation

All tests are configured to use **separate directories and databases** from production:

- **Test Uploads**: `backend/test_uploads/` (instead of `backend/uploads/`)
- **Test Database**: `backend/test_embeddings.db` (instead of `backend/embeddings.db`)
- **Test SQLite**: `backend/test_app.db` (instead of production PostgreSQL)

## Running Tests

```bash
# Run all tests
cd backend
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_documents.py

# Run with coverage
pytest --cov=. --cov-report=html
```

## Writing Tests

### Using Test Fixtures

The `conftest.py` file provides several fixtures for test isolation:

#### 1. Automatic Test Environment (`setup_test_environment`)

This fixture runs automatically for all tests and sets test environment variables:

```python
# No need to import - it runs automatically
def test_something():
    # Environment is automatically configured for testing
    pass
```

#### 2. Clean Upload Directory (`test_upload_dir`)

Provides a clean temporary directory for each test:

```python
def test_file_upload(test_upload_dir):
    # Create test file
    test_file = test_upload_dir / "test.txt"
    test_file.write_text("test content")

    # Test your upload logic
    # ...

    # Directory is automatically cleaned up after test
```

#### 3. File Cleanup Tracker (`cleanup_test_files`)

Track files that should be deleted after the test:

```python
def test_with_cleanup(cleanup_test_files):
    # Create a file
    file_path = Path("some_file.txt")
    file_path.write_text("content")

    # Register for cleanup
    cleanup_test_files.add(file_path)

    # File is automatically deleted after test
```

#### 4. Mock Upload Directory (`mock_upload_dir`)

Override the upload directory for a specific test:

```python
def test_upload_endpoint(mock_upload_dir):
    # All uploads in this test go to mock_upload_dir
    # which is a temporary directory that's auto-cleaned
    pass
```

#### 5. Production Pollution Verification (`verify_no_production_pollution`)

Ensures tests don't accidentally create files in production directories:

```python
def test_safe_operation(verify_no_production_pollution):
    # Your test code
    # If this test creates files in backend/uploads/,
    # the test will FAIL with a clear error message
    pass
```

## Example Tests

### Example 1: Testing Document Upload

```python
import pytest
from pathlib import Path
from api.documents import upload_document

def test_document_upload(test_upload_dir, verify_no_production_pollution):
    """Test document upload uses test directory, not production."""
    # Create test file
    test_file = test_upload_dir / "test_doc.txt"
    test_file.write_text("This is a test document")

    # Upload the document
    result = upload_document(test_file)

    # Verify upload succeeded
    assert result["success"] is True

    # verify_no_production_pollution automatically ensures
    # no files were created in backend/uploads/
```

### Example 2: Testing with Multiple Files

```python
def test_batch_upload(test_upload_dir, cleanup_test_files):
    """Test uploading multiple files."""
    # Create multiple test files
    files = []
    for i in range(5):
        file_path = test_upload_dir / f"file_{i}.txt"
        file_path.write_text(f"Content {i}")
        files.append(file_path)
        cleanup_test_files.add(file_path)

    # Test batch upload
    results = batch_upload(files)

    assert len(results) == 5
    # All files automatically cleaned up
```

### Example 3: Testing Database Operations

```python
def test_database_isolation():
    """Test database operations use test database."""
    from core.database import get_db

    # Database operations automatically use test_app.db
    # instead of production PostgreSQL

    # Your test code here
    pass
```

## Continuous Integration

For CI/CD pipelines, tests are automatically isolated:

```yaml
# .github/workflows/test.yml
- name: Run tests
  run: |
    cd backend
    pytest
    # Tests automatically use test directories
    # No production data is affected
```

## Verification

To verify that tests are properly isolated, you can check:

```bash
# Before running tests
ls backend/uploads/ | wc -l

# Run tests
cd backend && pytest

# After running tests - count should be the same
ls backend/uploads/ | wc -l

# All test files should be in test_uploads (and auto-deleted)
ls backend/test_uploads/
# Should be empty or only contain expected test artifacts
```

## Cleanup

Test artifacts are automatically cleaned up:

- **After each test**: Temporary test directories are removed
- **After test session**: Test database files are cleaned up
- **.gitignore**: Test directories are ignored by git

Manual cleanup (if needed):

```bash
# Remove all test artifacts
cd backend
rm -rf test_uploads/
rm -f test_*.db test_*.db-wal test_*.db-shm
rm -f test_app.db
```

## Common Pitfalls

### ❌ DON'T: Hardcode production paths

```python
# BAD - hardcoded production path
def test_upload():
    file_path = Path("backend/uploads/test.txt")  # ❌
```

### ✅ DO: Use test fixtures

```python
# GOOD - uses test directory
def test_upload(test_upload_dir):
    file_path = test_upload_dir / "test.txt"  # ✅
```

### ❌ DON'T: Import without fixtures

```python
# BAD - imports production config
from api.documents import UPLOAD_DIR  # ❌
```

### ✅ DO: Use mocked directories

```python
# GOOD - uses mocked directory
def test_something(mock_upload_dir):
    # UPLOAD_DIR is automatically mocked  ✅
    pass
```

## Best Practices

1. **Always use fixtures**: Don't create test files in random locations
2. **Verify isolation**: Use `verify_no_production_pollution` for critical tests
3. **Clean up**: Fixtures handle cleanup, but you can also use `cleanup_test_files`
4. **Test data naming**: Use descriptive names like `test_feature127_*.txt`
5. **No manual cleanup**: Let fixtures handle cleanup automatically

## Troubleshooting

### Tests creating files in production uploads/

If tests are creating files in `backend/uploads/`, check:

1. Are you using the test fixtures?
2. Is `setup_test_environment` being loaded?
3. Are you importing `UPLOAD_DIR` before fixtures run?

Solution: Use `mock_upload_dir` fixture to override the directory.

### Test database not isolated

If tests are affecting production database, check:

1. Is `TESTING=true` environment variable set?
2. Is `conftest.py` being loaded by pytest?
3. Are you using the correct database connection?

### Test files not being cleaned up

If test files persist after tests, check:

1. Is `cleanup_test_uploads_after_test` running?
2. Are you creating files outside `test_upload_dir`?
3. Is pytest exiting cleanly (not being killed)?

## Support

For questions about test infrastructure, see:
- `backend/conftest.py` - All fixture definitions
- `backend/tests/test_example.py` - Example test patterns
- Feature #127 - Test isolation requirements
