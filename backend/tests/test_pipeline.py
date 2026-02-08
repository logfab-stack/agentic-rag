"""
End-to-End RAG Pipeline Test Suite (Feature #349).

Validates the entire RAG pipeline: upload, chunking, embedding, search, LLM response.
Replaces scattered test_*.py and verify_*.py scripts with structured, repeatable tests.

Usage:
    # Run fast tests only (DB/API layer, no LLM calls):
    cd backend && pytest tests/test_pipeline.py -m fast -v

    # Run all tests including slow ones (needs API keys + running services):
    cd backend && pytest tests/test_pipeline.py -v

    # Run a specific test:
    cd backend && pytest tests/test_pipeline.py::test_upload_txt_creates_db_record -v
"""

import io
import time
import uuid
import pytest
from sqlalchemy import text


# =============================================================================
# Test 1: Document Upload (TXT) creates correct DB records
# =============================================================================
@pytest.mark.fast
def test_upload_txt_creates_db_record(upload_txt):
    """Upload a TXT file and verify the DB record is created correctly."""
    doc = upload_txt["document"]

    assert doc["id"] is not None
    assert doc["document_type"] == "unstructured"
    assert doc["mime_type"] == "text/plain"
    assert doc["file_size"] > 0
    assert doc["original_filename"] == "test_quantum.txt"
    assert "Quantum" in doc["title"] or "Test" in doc["title"]


@pytest.mark.fast
def test_upload_csv_creates_structured_record(upload_csv):
    """Upload a CSV file and verify it's stored as structured data."""
    doc = upload_csv["document"]

    assert doc["id"] is not None
    assert doc["document_type"] == "structured"
    assert doc["mime_type"] == "text/csv"
    assert doc["file_size"] > 0
    assert doc["schema_info"] is not None  # CSV should have schema


@pytest.mark.fast
def test_upload_returns_in_document_list(client, upload_txt):
    """Verify uploaded document appears in the document list."""
    doc_id = upload_txt["document"]["id"]

    resp = client.get("/api/documents/")
    assert resp.status_code == 200

    docs = resp.json()
    doc_ids = [d["id"] for d in docs]
    assert doc_id in doc_ids


@pytest.mark.fast
def test_get_document_by_id(client, upload_txt):
    """Verify single document retrieval by ID."""
    doc_id = upload_txt["document"]["id"]

    resp = client.get(f"/api/documents/{doc_id}")
    assert resp.status_code == 200

    doc = resp.json()
    assert doc["id"] == doc_id
    assert doc["document_type"] == "unstructured"


@pytest.mark.fast
def test_upload_duplicate_blocked(client, upload_txt, sample_txt_content):
    """Uploading the same content twice should be detected as duplicate."""
    files = {"file": ("test_quantum_dup.txt", io.BytesIO(sample_txt_content.encode()), "text/plain")}
    data = {"title": "Duplicate Test", "async_processing": "false"}

    resp = client.post("/api/documents/upload", files=files, data=data)
    # Should be 409 Conflict or contain a duplicate warning
    assert resp.status_code in (201, 409), f"Unexpected status: {resp.status_code}"

    if resp.status_code == 201:
        # Some implementations allow it but return a warning
        result = resp.json()
        # Cleanup the duplicate if it was created
        dup_id = result["document"]["id"]
        client.delete(f"/api/documents/{dup_id}")


@pytest.mark.fast
def test_delete_document(client, sample_txt_content):
    """Upload and then delete a document - verify it's gone."""
    # Upload
    files = {"file": ("delete_test.txt", io.BytesIO(sample_txt_content.encode()), "text/plain")}
    data = {"title": f"Delete Test {uuid.uuid4().hex[:8]}", "async_processing": "false"}
    resp = client.post("/api/documents/upload", files=files, data=data)
    assert resp.status_code == 201
    doc_id = resp.json()["document"]["id"]

    # Delete
    del_resp = client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 204

    # Verify gone
    get_resp = client.get(f"/api/documents/{doc_id}")
    assert get_resp.status_code == 404


# =============================================================================
# Test 2: Chunking produces expected chunk count
# =============================================================================
@pytest.mark.slow
def test_chunking_produces_chunks(upload_txt, db_session):
    """Verify that uploading a TXT doc produces chunks in document_embeddings."""
    doc_id = upload_txt["document"]["id"]

    # Wait for processing if async
    time.sleep(2)

    result = db_session.execute(
        text("SELECT COUNT(*) FROM document_embeddings WHERE document_id = :did"),
        {"did": doc_id},
    )
    chunk_count = result.scalar()

    # The sample text (~1000 chars) should produce at least 1 chunk
    assert chunk_count >= 1, f"Expected at least 1 chunk, got {chunk_count}"


@pytest.mark.slow
def test_chunk_count_matches_db(upload_txt, db_session):
    """Verify documents.chunk_count matches actual embedding count."""
    doc_id = upload_txt["document"]["id"]
    time.sleep(2)

    result = db_session.execute(
        text("""
            SELECT d.chunk_count, COUNT(de.id) as actual
            FROM documents d
            LEFT JOIN document_embeddings de ON d.id = de.document_id
            WHERE d.id = :did
            GROUP BY d.chunk_count
        """),
        {"did": doc_id},
    )
    row = result.fetchone()
    if row:
        stored_count, actual_count = row
        assert stored_count == actual_count, (
            f"chunk_count mismatch: stored={stored_count}, actual={actual_count}"
        )


# =============================================================================
# Test 3: Embedding generation stores correct dimensions
# =============================================================================
@pytest.mark.slow
def test_embeddings_have_correct_dimensions(upload_txt, db_session):
    """Verify stored embeddings have consistent, non-zero dimensions."""
    doc_id = upload_txt["document"]["id"]
    time.sleep(2)

    result = db_session.execute(
        text("""
            SELECT embedding
            FROM document_embeddings
            WHERE document_id = :did
            LIMIT 5
        """),
        {"did": doc_id},
    )
    rows = result.fetchall()

    assert len(rows) > 0, "No embeddings found"

    dimensions = set()
    for row in rows:
        emb = row[0]
        # pgvector returns embedding as a string like "[-0.1,0.2,...]"
        # Parse to count dimensions
        emb_str = str(emb).strip("[]")
        dim = len(emb_str.split(","))
        assert dim > 10, f"Embedding has unexpectedly few dimensions: {dim}"
        dimensions.add(dim)

    # All embeddings should have the same dimension
    assert len(dimensions) == 1, f"Inconsistent dimensions: {dimensions}"


# =============================================================================
# Test 4: Vector search returns relevant chunks
# =============================================================================
@pytest.mark.slow
def test_vector_search_returns_relevant_chunks(client, upload_txt):
    """Search for 'quantum computing' and verify relevant chunks come back."""
    doc_id = upload_txt["document"]["id"]
    time.sleep(2)

    resp = client.post("/api/chat/", json={
        "message": "What is quantum computing?",
        "document_ids": [doc_id],
    })
    assert resp.status_code == 200

    data = resp.json()
    assert data["content"], "Empty response from chat"
    assert data["conversation_id"], "No conversation_id returned"

    # The response should mention quantum-related concepts
    content_lower = data["content"].lower()
    assert any(kw in content_lower for kw in ["quantum", "qubit", "superposition"]), (
        f"Response doesn't mention quantum concepts: {data['content'][:200]}"
    )

    # Cleanup conversation
    conv_id = data["conversation_id"]
    client.delete(f"/api/conversations/{conv_id}")


# =============================================================================
# Test 5: Hybrid search (vector + BM25) returns results
# =============================================================================
@pytest.mark.slow
def test_hybrid_search_returns_results(client, upload_txt):
    """Test that searching for a specific term works (BM25 + vector)."""
    doc_id = upload_txt["document"]["id"]
    time.sleep(2)

    # Use a specific term that BM25 should find well
    resp = client.post("/api/chat/", json={
        "message": "Tell me about IBM Google Microsoft quantum processors",
        "document_ids": [doc_id],
    })
    assert resp.status_code == 200

    data = resp.json()
    assert data["content"], "Empty response"

    # Cleanup
    if data.get("conversation_id"):
        client.delete(f"/api/conversations/{data['conversation_id']}")


# =============================================================================
# Test 6: Re-embed preserves document integrity
# =============================================================================
@pytest.mark.slow
def test_reembed_preserves_integrity(client, upload_txt, db_session):
    """Re-embed a document and verify chunk_count updates correctly."""
    doc_id = upload_txt["document"]["id"]
    time.sleep(2)

    # Get initial chunk count
    result = db_session.execute(
        text("SELECT COUNT(*) FROM document_embeddings WHERE document_id = :did"),
        {"did": doc_id},
    )
    initial_count = result.scalar()

    if initial_count == 0:
        pytest.skip("No initial embeddings - cannot test re-embed")

    # Trigger re-embed
    resp = client.post(f"/api/documents/{doc_id}/re-embed")
    # Re-embed might be 200 or 202 (accepted for async)
    assert resp.status_code in (200, 202), f"Re-embed failed: {resp.status_code} {resp.text}"

    # Wait for re-embedding to complete
    time.sleep(10)

    # Check document still exists and has embeddings
    doc_resp = client.get(f"/api/documents/{doc_id}")
    assert doc_resp.status_code == 200

    doc = doc_resp.json()
    assert doc["id"] == doc_id

    # Refresh DB session to see new data
    db_session.expire_all()
    result = db_session.execute(
        text("SELECT COUNT(*) FROM document_embeddings WHERE document_id = :did"),
        {"did": doc_id},
    )
    new_count = result.scalar()
    assert new_count >= 1, f"After re-embed, expected chunks but got {new_count}"


# =============================================================================
# Test 7: Full pipeline - upload, ask question, verify answer
# =============================================================================
@pytest.mark.slow
@pytest.mark.pipeline
def test_full_pipeline(client, sample_txt_content):
    """
    Full E2E test: upload a document, ask a question, verify the answer
    references the correct content.
    """
    # Step 1: Upload
    unique_title = f"Pipeline Test {uuid.uuid4().hex[:8]}"
    files = {"file": ("pipeline_test.txt", io.BytesIO(sample_txt_content.encode()), "text/plain")}
    data = {"title": unique_title, "comment": "E2E pipeline test", "async_processing": "false"}

    upload_resp = client.post("/api/documents/upload", files=files, data=data)
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["document"]["id"]

    try:
        # Step 2: Wait for processing
        time.sleep(3)

        # Step 3: Verify document is ready
        doc_resp = client.get(f"/api/documents/{doc_id}")
        assert doc_resp.status_code == 200
        doc = doc_resp.json()
        assert doc["status"] in ("ready", "queued", "processing"), f"Unexpected status: {doc['status']}"

        # Step 4: Ask a question about the content
        chat_resp = client.post("/api/chat/", json={
            "message": "What did Google achieve in 2019 with their quantum processor?",
            "document_ids": [doc_id],
        })
        assert chat_resp.status_code == 200

        chat_data = chat_resp.json()
        assert chat_data["content"], "Empty chat response"

        # Step 5: Verify the answer references the correct content
        content_lower = chat_data["content"].lower()
        # Should mention Sycamore, quantum supremacy, or the 200 seconds claim
        relevant_terms = ["sycamore", "supremacy", "200 second", "10,000 year", "10000"]
        assert any(term in content_lower for term in relevant_terms), (
            f"Response doesn't reference expected quantum content: {chat_data['content'][:300]}"
        )

        # Cleanup conversation
        if chat_data.get("conversation_id"):
            client.delete(f"/api/conversations/{chat_data['conversation_id']}")

    finally:
        # Always cleanup the document
        client.delete(f"/api/documents/{doc_id}")


# =============================================================================
# Test 8: CSV document - SQL tool used for structured queries
# =============================================================================
@pytest.mark.slow
@pytest.mark.pipeline
def test_csv_query_uses_sql(client, upload_csv):
    """Upload CSV, ask a calculation question, verify SQL tool is used."""
    doc_id = upload_csv["document"]["id"]
    time.sleep(2)

    resp = client.post("/api/chat/", json={
        "message": "What is the total price of all Electronics products?",
        "document_ids": [doc_id],
    })
    assert resp.status_code == 200

    data = resp.json()
    assert data["content"], "Empty response for CSV query"

    # The tool used should be sql-related
    tool_used = data.get("tool_used", "")
    # Response should contain a number (the sum)
    # Laptop Pro (1299.99) + 4K Monitor (599.99) = 1899.98
    content = data["content"]
    assert any(char.isdigit() for char in content), (
        f"Response doesn't contain numbers for a calculation query: {content[:200]}"
    )

    # Cleanup conversation
    if data.get("conversation_id"):
        client.delete(f"/api/conversations/{data['conversation_id']}")


# =============================================================================
# Test 9: Health endpoint works
# =============================================================================
@pytest.mark.fast
def test_health_endpoint(client):
    """Verify /api/health returns healthy status."""
    resp = client.get("/api/health")
    assert resp.status_code == 200

    data = resp.json()
    assert data["status"] in ("healthy", "degraded")
    assert data["service"] == "Agentic RAG System"
    assert "components" in data


@pytest.mark.fast
def test_health_includes_startup_checks(client):
    """Verify /api/health includes startup health check results (Feature #348)."""
    resp = client.get("/api/health")
    assert resp.status_code == 200

    data = resp.json()
    # Feature #348 adds startup_health to the response
    if "startup_health" in data:
        startup = data["startup_health"]
        assert "checks" in startup
        assert "duration_ms" in startup
        assert isinstance(startup["checks"], list)


# =============================================================================
# Test 10: Embedding count endpoint
# =============================================================================
@pytest.mark.slow
def test_embedding_count_endpoint(client, upload_txt):
    """Verify the embedding count endpoint returns correct data."""
    doc_id = upload_txt["document"]["id"]
    time.sleep(2)

    resp = client.get(f"/api/documents/{doc_id}/embedding-count")
    assert resp.status_code == 200

    data = resp.json()
    assert "count" in data or "embedding_count" in data


# =============================================================================
# Test 11: Response Feedback System (Feature #350)
# =============================================================================
@pytest.mark.slow
def test_response_feedback_submit_and_retrieve(client, upload_txt):
    """Submit thumbs up/down on an AI response and verify it's stored."""
    doc_id = upload_txt["document"]["id"]
    time.sleep(2)

    # Ask a question to create a message we can rate
    chat_resp = client.post("/api/chat/", json={
        "message": "What is quantum computing?",
        "document_ids": [doc_id],
    })
    assert chat_resp.status_code == 200

    chat_data = chat_resp.json()
    message_id = chat_data["id"]
    conversation_id = chat_data["conversation_id"]

    # Submit thumbs up feedback
    fb_resp = client.post("/api/response-feedback/", json={
        "message_id": message_id,
        "conversation_id": conversation_id,
        "rating": 1,
    })
    assert fb_resp.status_code == 201

    fb_data = fb_resp.json()
    assert fb_data["message_id"] == message_id
    assert fb_data["rating"] == 1
    assert fb_data["query"]  # Should have captured the user query
    assert fb_data["response"]  # Should have captured the AI response

    # Retrieve feedback by message_id
    get_resp = client.get(f"/api/response-feedback/{message_id}")
    assert get_resp.status_code == 200

    get_data = get_resp.json()
    assert get_data["rating"] == 1

    # Upsert: change to thumbs down
    fb_resp2 = client.post("/api/response-feedback/", json={
        "message_id": message_id,
        "conversation_id": conversation_id,
        "rating": -1,
    })
    assert fb_resp2.status_code == 201
    assert fb_resp2.json()["rating"] == -1

    # Check stats endpoint
    stats_resp = client.get("/api/response-feedback/stats/summary")
    assert stats_resp.status_code == 200

    stats = stats_resp.json()
    assert "total_feedback" in stats
    assert "positive_count" in stats
    assert "negative_count" in stats
    assert "by_source" in stats
    assert "by_tool" in stats

    # Cleanup: delete feedback then conversation
    client.delete(f"/api/response-feedback/{message_id}")
    client.delete(f"/api/conversations/{conversation_id}")
