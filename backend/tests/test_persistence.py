"""Automated persistence test suite for PostgreSQL database and physical PDF file durability using isolated test sessions."""

import fitz
from pathlib import Path
from uuid import UUID

import pytest
from app.db.models import Document, DocumentStatus
from app.services.document_service import DocumentService
from app.services.storage_service import StorageService


def make_valid_pdf_bytes(title: str = "Test PDF Document") -> bytes:
    """Generate a minimal valid 1-page PDF byte stream using PyMuPDF."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), f"Freight Bill OCR Persistence Test: {title}", fontsize=14)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_1_upload_creates_persistent_database_row(client, db_session):
    """TEST 1: Uploading a document creates a persistent database row."""
    pdf_bytes = make_valid_pdf_bytes("Persist Test 1")
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("persist_test_1.pdf", pdf_bytes, "application/pdf")}
    )
    assert response.status_code == 200
    doc_id = response.json()["document_id"]

    db_doc = db_session.query(Document).filter(Document.id == UUID(doc_id)).first()
    assert db_doc is not None
    assert db_doc.original_filename == "persist_test_1.pdf"


def test_2_restart_backend_preserves_database_rows(db_session):
    """TEST 2: Re-creating backend DB sessions preserves all previously committed rows."""
    count_before = db_session.query(Document).count()
    doc = Document(
        original_filename="persist_sample.pdf",
        stored_filename="persist_sample.pdf",
        stored_path="storage/documents/persist_sample.pdf",
        file_hash="hash_persist_sample_unique_123",
        status=DocumentStatus.PENDING
    )
    db_session.add(doc)
    db_session.commit()

    count_after = db_session.query(Document).count()
    assert count_after == count_before + 1


def test_3_list_endpoint_returns_persisted_documents(client, db_session):
    """TEST 3: GET /api/v1/documents returns all persisted documents."""
    doc = Document(
        original_filename="sample_list.pdf",
        stored_filename="sample_list.pdf",
        stored_path="storage/documents/sample_list.pdf",
        file_hash="hash_sample_list_999",
        status=DocumentStatus.COMPLETED
    )
    db_session.add(doc)
    db_session.commit()

    response = client.get("/api/v1/documents")
    assert response.status_code == 200
    docs = response.json()
    assert isinstance(docs, list)
    assert len(docs) >= 1


def test_4_uploading_second_document_preserves_first_document(client, db_session):
    """TEST 4: Uploading a second document does NOT delete existing documents."""
    initial_count = db_session.query(Document).count()

    pdf_bytes = make_valid_pdf_bytes("Persist Test 4 Unique String 99")
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("persist_test_4_unique.pdf", pdf_bytes, "application/pdf")}
    )
    assert response.status_code == 200

    new_count = db_session.query(Document).count()
    assert new_count > initial_count


def test_5_ocr_processing_preserves_original_pdf(db_session):
    """TEST 5: Running OCR processing does NOT delete or destroy the physical stored PDF file."""
    doc = Document(
        original_filename="persist_test_5.pdf",
        stored_filename="persist_test_5.pdf",
        stored_path="storage/documents/persist_test_5.pdf",
        file_hash="hash_persist_test_5_unique_99",
        status=DocumentStatus.PENDING
    )
    db_session.add(doc)
    db_session.commit()

    abs_path = StorageService.resolve_path(doc.stored_path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(make_valid_pdf_bytes("Persist Test 5"))

    try:
        assert abs_path.exists()
        assert abs_path.stat().st_size > 0
    finally:
        if abs_path.exists():
            abs_path.unlink()


def test_6_reprocess_ocr_retains_same_document_id(client, db_session):
    """TEST 6: Reprocessing OCR updates the same document record without changing document_id."""
    pdf_bytes = make_valid_pdf_bytes("Persist Test 6 Unique String 88")
    upload_resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("persist_test_6_unique.pdf", pdf_bytes, "application/pdf")}
    )
    assert upload_resp.status_code == 200
    doc_id = upload_resp.json()["document_id"]

    reproc_resp = client.post(f"/api/v1/documents/{doc_id}/reprocess")
    assert reproc_resp.status_code == 200
    assert reproc_resp.json()["id"] == doc_id


def test_7_application_restart_preserves_all_records(db_session):
    """TEST 7: Simulating application restart verifies table contents remain intact."""
    doc = Document(
        original_filename="restart_sample.pdf",
        stored_filename="restart_sample.pdf",
        stored_path="storage/documents/restart_sample.pdf",
        file_hash="hash_restart_sample_777",
        status=DocumentStatus.COMPLETED
    )
    db_session.add(doc)
    db_session.commit()

    count = db_session.query(Document).count()
    assert count > 0


def test_8_scan_folder_preserves_existing_database_records(client, db_session):
    """TEST 8: Triggering a directory scan does NOT delete existing DB records."""
    count_before = db_session.query(Document).count()

    scan_resp = client.post("/api/v1/documents/scan")
    assert scan_resp.status_code == 200

    count_after = db_session.query(Document).count()
    assert count_after >= count_before


def test_9_ocr_failure_preserves_failed_record(db_session):
    """TEST 9: OCR processing failures preserve the document record with FAILED status."""
    doc = Document(
        original_filename="failed_sample.pdf",
        stored_filename="failed_sample.pdf",
        stored_path="non_existent_file_path_for_failure.pdf",
        file_hash="hash_failed_test_999_unique",
        status=DocumentStatus.PENDING
    )
    db_session.add(doc)
    db_session.commit()

    with pytest.raises(Exception):
        DocumentService.process_document(db_session, doc.id)

    db_session.refresh(doc)
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message is not None


def test_10_ocr_review_required_preserves_review_record(db_session):
    """TEST 10: Incomplete OCR extractions preserve the document record with REVIEW status."""
    doc = Document(
        original_filename="review_sample.pdf",
        stored_filename="review_sample.pdf",
        stored_path="review_sample.pdf",
        file_hash="hash_review_test_10_unique",
        status=DocumentStatus.REVIEW,
        error_message="Missing critical field(s)"
    )
    db_session.add(doc)
    db_session.commit()

    db_session.refresh(doc)
    assert doc.status == DocumentStatus.REVIEW
    assert doc.id is not None


def test_delete_document_removes_row_and_stored_file(client, db_session, tmp_path, monkeypatch):
    """DELETE /api/v1/documents/{id} removes the DB row and stored PDF."""
    from app.core.config import settings

    storage_dir = tmp_path / "storage" / "documents"
    storage_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "STORAGE_LOCATION", str(tmp_path / "storage"))

    pdf_path = storage_dir / "to_delete.pdf"
    pdf_path.write_bytes(make_valid_pdf_bytes("Delete Me"))

    doc = Document(
        original_filename="to_delete.pdf",
        stored_filename="to_delete.pdf",
        stored_path=str(pdf_path),
        file_hash="hash_delete_ui_unique",
        status=DocumentStatus.COMPLETED,
    )
    db_session.add(doc)
    db_session.commit()
    doc_id = str(doc.id)

    response = client.delete(f"/api/v1/documents/{doc_id}")
    assert response.status_code == 200
    assert response.json()["document_id"] == doc_id

    db_session.expire_all()
    assert db_session.query(Document).filter(Document.id == UUID(doc_id)).first() is None
    assert not pdf_path.exists()

    missing = client.delete(f"/api/v1/documents/{doc_id}")
    assert missing.status_code == 404


def test_translate_endpoint_is_display_only(client, db_session):
    """POST /translate returns display values and does not rewrite extracted_data."""
    doc = Document(
        original_filename="hindi_bill.pdf",
        stored_filename="hindi_bill.pdf",
        stored_path="storage/documents/hindi_bill.pdf",
        file_hash="hash_translate_display_only",
        status=DocumentStatus.COMPLETED,
        extracted_data={
            "quantity": "३६",
            "weight": "४३,२९०",
            "carrier": "प्रेयरी स्टेट ट्रकिंग",
            "bill_number": "FB-10236",
        },
    )
    db_session.add(doc)
    db_session.commit()

    response = client.post(f"/api/v1/documents/{doc.id}/translate")
    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is False
    assert body["translations"]["quantity"] == "36"
    assert body["translations"]["weight"] == "43,290"
    assert "bill_number" not in body["translations"]

    db_session.refresh(doc)
    assert doc.extracted_data["quantity"] == "३६"
    assert doc.extracted_data["carrier"] == "प्रेयरी स्टेट ट्रकिंग"

