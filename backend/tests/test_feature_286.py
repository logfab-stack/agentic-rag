"""
Feature #286: Test classify_query() function

Tests that short queries are classified as 'lookup', question queries as 'question',
and calculation queries as 'calculation'.
"""

import pytest
import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ai_service import AIService


class TestClassifyQuery:
    """Tests for Feature #286: Classify short queries as lookup instead of Q&A"""

    @pytest.fixture
    def ai_service(self):
        """Create AIService instance for testing"""
        return AIService()

    def test_short_query_no_verbs_is_lookup(self, ai_service):
        """Short queries without verbs should be classified as 'lookup'"""
        # Test Italian short queries
        result = ai_service.classify_query("ricette cipolla")
        assert result["query_type"] == "lookup", f"Expected 'lookup', got {result}"

        result = ai_service.classify_query("torta mele")
        assert result["query_type"] == "lookup", f"Expected 'lookup', got {result}"

        result = ai_service.classify_query("pollo verdure")
        assert result["query_type"] == "lookup", f"Expected 'lookup', got {result}"

    def test_short_query_english_is_lookup(self, ai_service):
        """Short English queries without verbs should be classified as 'lookup'"""
        result = ai_service.classify_query("chicken recipe")
        assert result["query_type"] == "lookup", f"Expected 'lookup', got {result}"

        result = ai_service.classify_query("pasta carbonara")
        assert result["query_type"] == "lookup", f"Expected 'lookup', got {result}"

    def test_question_mark_is_question(self, ai_service):
        """Queries ending with ? should be classified as 'question' (unless calculation keywords present)"""
        # Note: "quante ricette?" and "how many recipes?" contain calculation keywords
        # so they should be classified as 'calculation' (higher priority)
        result = ai_service.classify_query("quante ricette?")
        assert result["query_type"] == "calculation", f"'quante' is calculation keyword, got {result}"

        result = ai_service.classify_query("how many recipes?")
        assert result["query_type"] == "calculation", f"'how many' is calculation keyword, got {result}"

        # Pure question mark queries without calculation keywords
        result = ai_service.classify_query("dove trovo la ricetta?")
        assert result["query_type"] == "question", f"Expected 'question', got {result}"

        result = ai_service.classify_query("what is the recipe?")
        assert result["query_type"] == "question", f"Expected 'question', got {result}"

    def test_question_words_is_question(self, ai_service):
        """Queries starting with question words should be classified as 'question'"""
        # English question words
        result = ai_service.classify_query("what is the recipe for pasta")
        assert result["query_type"] == "question", f"Expected 'question', got {result}"

        result = ai_service.classify_query("how do I make chicken")
        assert result["query_type"] == "question", f"Expected 'question', got {result}"

        # Italian question words
        result = ai_service.classify_query("cosa contiene la ricetta")
        assert result["query_type"] == "question", f"Expected 'question', got {result}"

        result = ai_service.classify_query("come preparo il pollo")
        assert result["query_type"] == "question", f"Expected 'question', got {result}"

    def test_calculation_keywords_is_calculation(self, ai_service):
        """Queries with calculation keywords should be classified as 'calculation'"""
        # English
        result = ai_service.classify_query("how many recipes are there")
        assert result["query_type"] == "calculation", f"Expected 'calculation', got {result}"

        result = ai_service.classify_query("total revenue")
        assert result["query_type"] == "calculation", f"Expected 'calculation', got {result}"

        result = ai_service.classify_query("sum of prices")
        assert result["query_type"] == "calculation", f"Expected 'calculation', got {result}"

        result = ai_service.classify_query("average cost")
        assert result["query_type"] == "calculation", f"Expected 'calculation', got {result}"

        # Italian
        result = ai_service.classify_query("quante ricette ci sono")
        assert result["query_type"] == "calculation", f"Expected 'calculation', got {result}"

        result = ai_service.classify_query("somma dei prezzi")
        assert result["query_type"] == "calculation", f"Expected 'calculation', got {result}"

    def test_short_query_with_verb_is_question(self, ai_service):
        """Short queries WITH verbs should NOT be classified as 'lookup'"""
        # Italian verbs
        result = ai_service.classify_query("dammi ricetta")
        assert result["query_type"] != "lookup", f"Expected NOT 'lookup', got {result}"

        result = ai_service.classify_query("mostrami pollo")
        assert result["query_type"] != "lookup", f"Expected NOT 'lookup', got {result}"

        # English verbs
        result = ai_service.classify_query("show me recipe")
        assert result["query_type"] != "lookup", f"Expected NOT 'lookup', got {result}"

    def test_longer_query_is_question(self, ai_service):
        """Queries with more than 3 words should default to 'question'"""
        result = ai_service.classify_query("tell me about the chicken and vegetables recipe")
        # This should be question since it has > 3 words and starts with "tell"
        assert result["query_type"] == "question", f"Expected 'question', got {result}"

    def test_confidence_levels(self, ai_service):
        """Verify confidence levels are appropriate"""
        # High confidence for clear question mark
        result = ai_service.classify_query("quante ricette?")
        assert result["confidence"] >= 0.9, f"Expected high confidence, got {result['confidence']}"

        # Good confidence for short lookup
        result = ai_service.classify_query("ricette cipolla")
        assert result["confidence"] >= 0.8, f"Expected good confidence, got {result['confidence']}"

        # High confidence for calculation keywords
        result = ai_service.classify_query("total revenue")
        assert result["confidence"] >= 0.8, f"Expected good confidence, got {result['confidence']}"

    def test_empty_query(self, ai_service):
        """Empty queries should default to 'question'"""
        result = ai_service.classify_query("")
        assert result["query_type"] == "question", f"Expected 'question' for empty, got {result}"

        result = ai_service.classify_query("   ")
        assert result["query_type"] == "question", f"Expected 'question' for whitespace, got {result}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
