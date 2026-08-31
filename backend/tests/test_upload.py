"""Unit tests for document upload API endpoint (POST /api/v1/documents/upload)."""

from app.db.models import Document, DocumentStatus


def test_successful_pdf_upload(client, create_pdf, db_session):
    """Verify uploading a valid PDF returns HTTP 200 and processes document in DB."""
    pdf_path = create_pdf("sample_bill.pdf", "Freight Bill #99001")

    with open(pdf_path, "rb") as f:
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("sample_bill.pdf", f, "application/pdf")}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "sample_bill.pdf"
    assert data["status"] in ["REVIEW", "COMPLETED", "PENDING"]
    assert data["document_id"] is not None
    assert data["file_hash"] is not None
    assert "processed successfully" in data["message"] or "uploaded successfully" in data["message"]

    # Verify Database record exists
    doc = db_session.query(Document).filter(Document.original_filename == "sample_bill.pdf").first()
    assert doc is not None
    assert doc.status in [DocumentStatus.REVIEW, DocumentStatus.COMPLETED, DocumentStatus.PENDING]
    assert doc.file_hash == data["file_hash"]


def test_invalid_file_extension_rejection(client):
    """Verify non-PDF file upload is rejected with HTTP 400."""
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("notes.txt", b"Plain text notes", "text/plain")}
    )

    assert response.status_code == 400
    assert "Supported types" in response.json()["detail"]


def test_corrupted_pdf_rejection(client):
    """Verify corrupted PDF structure is rejected with HTTP 400."""
    corrupt_data = b"NOT A VALID PDF HEADER"
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("fake_bill.pdf", corrupt_data, "application/pdf")}
    )

    assert response.status_code == 400
    assert "Invalid PDF file" in response.json()["detail"]


def test_duplicate_pdf_upload_detection(client, create_pdf, db_session):
    """Verify uploading duplicate PDF content returns DUPLICATE status without creating a 2nd DB record."""
    pdf_path = create_pdf("original_bill.pdf", "Unique Cargo Manifest 777")

    # First Upload
    with open(pdf_path, "rb") as f:
        resp1 = client.post(
            "/api/v1/documents/upload",
            files={"file": ("original_bill.pdf", f, "application/pdf")}
        )
    assert resp1.status_code == 200
    doc_id_1 = resp1.json()["document_id"]
    assert resp1.json()["status"] in ["REVIEW", "COMPLETED", "PENDING"]

    # Second Upload (Same file content, different uploaded filename)
    with open(pdf_path, "rb") as f:
        resp2 = client.post(
            "/api/v1/documents/upload",
            files={"file": ("duplicate_bill.pdf", f, "application/pdf")}
        )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "DUPLICATE"
    assert data2["document_id"] == doc_id_1
    assert "Duplicate document detected" in data2["message"]

    # Check Database has exactly 1 record
    all_docs = db_session.query(Document).all()
    assert len(all_docs) == 1


def test_missing_upload_file(client):
    """Verify request without file parameter returns 422 validation error."""
    response = client.post("/api/v1/documents/upload")
    assert response.status_code == 422
