#!/usr/bin/env python3
"""
Feature #278: Validate chunk text before LLM context building

Tests that verify the validate_chunks() function correctly filters chunks
by minimum text length and logs appropriate warnings.

USAGE:
------
cd backend
python tests/test_chunk_validation.py
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch, MagicMock
import logging

# Set up logging to capture warnings
logging.basicConfig(level=logging.WARNING)


class TestChunkValidation(unittest.TestCase):
    """Tests for Feature #278: Validate chunk text before LLM context building"""

    def setUp(self):
        """Set up test fixtures"""
        # Import here to avoid import issues before path setup
        from services.ai_service import AIService
        self.ai_service = AIService()

    def test_validate_chunks_filters_short_text(self):
        """Test that chunks with text shorter than min_text_length are filtered out"""
        chunks = [
            {"chunk_id": "chunk_1", "document_id": "doc_1", "text": "This is a short text."},  # 21 chars
            {"chunk_id": "chunk_2", "document_id": "doc_1", "text": "This is a much longer text that should pass the validation because it has more than 50 characters in it."},  # 106 chars
            {"chunk_id": "chunk_3", "document_id": "doc_1", "text": ""},  # 0 chars (empty)
            {"chunk_id": "chunk_4", "document_id": "doc_1", "text": "A" * 49},  # 49 chars (just under)
            {"chunk_id": "chunk_5", "document_id": "doc_1", "text": "B" * 50},  # 50 chars (exactly at threshold)
        ]

        # Test with default min_text_length (50)
        valid_chunks = self.ai_service.validate_chunks(chunks, min_text_length=50)

        # Should have 2 valid chunks (chunk_2 with 106 chars and chunk_5 with exactly 50 chars)
        self.assertEqual(len(valid_chunks), 2)

        # Verify the correct chunks passed
        chunk_ids = [c["chunk_id"] for c in valid_chunks]
        self.assertIn("chunk_2", chunk_ids)
        self.assertIn("chunk_5", chunk_ids)
        self.assertNotIn("chunk_1", chunk_ids)
        self.assertNotIn("chunk_3", chunk_ids)
        self.assertNotIn("chunk_4", chunk_ids)

    def test_validate_chunks_configurable_min_length(self):
        """Test that min_text_length is configurable"""
        chunks = [
            {"chunk_id": "chunk_1", "document_id": "doc_1", "text": "Short"},  # 5 chars
            {"chunk_id": "chunk_2", "document_id": "doc_1", "text": "This is longer text"},  # 19 chars
        ]

        # With min_text_length=10, only chunk_2 should pass
        valid_chunks = self.ai_service.validate_chunks(chunks, min_text_length=10)
        self.assertEqual(len(valid_chunks), 1)
        self.assertEqual(valid_chunks[0]["chunk_id"], "chunk_2")

        # With min_text_length=3, both should pass
        valid_chunks = self.ai_service.validate_chunks(chunks, min_text_length=3)
        self.assertEqual(len(valid_chunks), 2)

    def test_validate_chunks_logs_warnings(self):
        """Test that warnings are logged for filtered chunks"""
        chunks = [
            {"chunk_id": "test_chunk_short", "document_id": "test_doc", "text": "Too short"},
        ]

        with self.assertLogs('services.ai_service', level='WARNING') as log:
            self.ai_service.validate_chunks(chunks, min_text_length=50)
            # Check that warning was logged
            self.assertTrue(any('[Feature #278]' in msg and 'text too short' in msg for msg in log.output))

    def test_validate_chunks_empty_input(self):
        """Test with empty chunk list"""
        valid_chunks = self.ai_service.validate_chunks([], min_text_length=50)
        self.assertEqual(len(valid_chunks), 0)

    def test_validate_chunks_all_valid(self):
        """Test when all chunks are valid (no filtering needed)"""
        chunks = [
            {"chunk_id": "chunk_1", "document_id": "doc_1", "text": "A" * 100},
            {"chunk_id": "chunk_2", "document_id": "doc_1", "text": "B" * 200},
        ]

        valid_chunks = self.ai_service.validate_chunks(chunks, min_text_length=50)
        self.assertEqual(len(valid_chunks), 2)

    def test_validate_chunks_whitespace_handling(self):
        """Test that whitespace-only text is handled correctly"""
        chunks = [
            {"chunk_id": "chunk_1", "document_id": "doc_1", "text": "   "},  # Only whitespace
            {"chunk_id": "chunk_2", "document_id": "doc_1", "text": "  Valid text with spaces  "},  # 24 chars after strip
        ]

        # With min_text_length=10, only chunk_2 should pass (after stripping whitespace)
        valid_chunks = self.ai_service.validate_chunks(chunks, min_text_length=10)
        self.assertEqual(len(valid_chunks), 1)
        self.assertEqual(valid_chunks[0]["chunk_id"], "chunk_2")

    def test_filter_valid_chunks_includes_min_length_check(self):
        """Test that _filter_valid_chunks also applies minimum text length filtering"""
        # Create mock chunks that have text (but short text)
        chunks = [
            {"chunk_id": "chunk_1", "document_id": "doc_1", "text": "Short"},  # 5 chars
            {"chunk_id": "chunk_2", "document_id": "doc_1", "text": "A" * 100},  # 100 chars
        ]

        with patch.object(self.ai_service, '_get_chunk_text_with_fallback') as mock_fallback:
            # Mock the fallback to return the text as-is
            def side_effect(chunk):
                text = chunk.get("text", "")
                return (text, "primary") if text else (None, "none")
            mock_fallback.side_effect = side_effect

            valid_chunks, error_response = self.ai_service._filter_valid_chunks(chunks, "test query")

            # Should only have chunk_2 (the one with 100 chars)
            self.assertEqual(len(valid_chunks), 1)
            self.assertEqual(valid_chunks[0]["chunk_id"], "chunk_2")
            self.assertIsNone(error_response)


class TestChunkValidationIntegration(unittest.TestCase):
    """Integration tests using actual settings"""

    def setUp(self):
        """Set up test fixtures"""
        from services.ai_service import AIService
        self.ai_service = AIService()

    @patch('services.ai_service.settings_store')
    def test_validate_chunks_uses_settings(self, mock_settings):
        """Test that validate_chunks reads min_chunk_text_length from settings"""
        mock_settings.get.return_value = '100'  # Settings return strings

        chunks = [
            {"chunk_id": "chunk_1", "document_id": "doc_1", "text": "A" * 99},  # Under 100
            {"chunk_id": "chunk_2", "document_id": "doc_1", "text": "B" * 100},  # Exactly 100
        ]

        valid_chunks = self.ai_service.validate_chunks(chunks)  # No explicit min_text_length

        # Should call settings_store.get with 'min_chunk_text_length'
        mock_settings.get.assert_called_with('min_chunk_text_length', 50)

        # With setting of 100, only chunk_2 should pass
        self.assertEqual(len(valid_chunks), 1)
        self.assertEqual(valid_chunks[0]["chunk_id"], "chunk_2")


def run_tests():
    """Run all tests"""
    print("=" * 70)
    print("Feature #278: Validate chunk text before LLM context building")
    print("=" * 70)
    print()

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestChunkValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestChunkValidationIntegration))

    # Run tests with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print()
    print("=" * 70)
    if result.wasSuccessful():
        print("✅ All tests PASSED")
    else:
        print("❌ Some tests FAILED")
        print(f"   Failures: {len(result.failures)}")
        print(f"   Errors: {len(result.errors)}")
    print("=" * 70)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
