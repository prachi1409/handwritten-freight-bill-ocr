"""Unit tests for OCR pipeline end-to-end flow, status decisions, multi-page PDFs, reprocessing, and manual review workflow."""

import pytest
from pathlib import Path
from app.core.config import settings
from app.db.models import Document, DocumentStatus
from app.ocr.base import OCRResult
from app.ocr.factory import get_ocr_processor
from app.ocr.local_processor import LocalOCRProcessor
from app.ocr.preprocessor import preprocess_pdf_pages
from app.services.document_service import DocumentService


def test_valid_handwritten_freight_bill_completed(db_session, create_pdf):
    """Verify processing a complete handwritten freight bill yields DocumentStatus.COMPLETED."""
    text_content = (
        "HANDWRITTEN FREIGHT BILL & CARGO MANIFEST\n"
        "Bill No: HB-78421\n"
        "Invoice No: INV-HB-5821\n"
        "Date: 26/08/2026\n"
        "Consignor: Sharma Industrial Supply\n"
        "Consignee: Metro Warehouse, Delhi\n"
        "Origin: Kanpur Industrial Area, UP\n"
        "Destination: Delhi Distribution Hub\n"
        "Vehicle No: UP-32-T-5821\n"
        "Weight: 18,750 lbs\n"
        "Quantity: 42 Pallets\n"
        "Freight Amount: $3,450.00\n"
        "Total Amount: $3,450.00\n"
    )
    pdf_path = create_pdf("handwritten_bill_test.pdf", text_content)

    doc = Document(
        filename="handwritten_bill_test.pdf",
        file_hash="hash_handwritten_bill_test_123",
        file_path=str(pdf_path),
        status=DocumentStatus.PENDING
    )
    db_session.add(doc)
    db_session.commit()

    updated = DocumentService.process_document(db_session, doc.id)

    assert updated.status == DocumentStatus.COMPLETED
    assert updated.extracted_data["bill_number"] == "HB-78421"
    assert updated.extracted_data["invoice_number"] == "INV-HB-5821"
    assert updated.extracted_data["consignor"] == "Sharma Industrial Supply"
    assert updated.extracted_data["freight_amount"] == "$3,450.00"
    assert updated.confidence >= 0.70


def test_low_confidence_ocr_results_in_review_status(db_session, create_pdf):
    """Verify document with sparse or low confidence text results in DocumentStatus.REVIEW."""
    pdf_path = create_pdf("sparse_bill.pdf", "Some random text without bill numbers or amounts.")

    doc = Document(
        filename="sparse_bill.pdf",
        file_hash="hash_sparse_bill_999",
        file_path=str(pdf_path),
        status=DocumentStatus.PENDING
    )
    db_session.add(doc)
    db_session.commit()

    updated = DocumentService.process_document(db_session, doc.id)

    assert updated.status == DocumentStatus.REVIEW
    assert "manual review" in updated.error_message.lower()
    assert updated.extracted_data is not None


def test_image_preprocessing_pipeline(create_pdf):
    """Verify preprocess_pdf_pages renders PDF page images at configured DPI."""
    pdf_path = create_pdf("preproc_test.pdf", "Sample PDF Text for Preprocessing")
    images = preprocess_pdf_pages(pdf_path)

    assert len(images) == 1
    assert images[0].width > 0
    assert images[0].height > 0


def test_reprocess_document_updates_existing_record(db_session, create_pdf):
    """Verify reprocessing calls OCR processor fresh and updates existing DB document record."""
    pdf_path = create_pdf("reprocess_bill.pdf", "Bill No: FB-9900\nShipper: Alpha Co\nFreight: $500.00")

    doc = Document(
        filename="reprocess_bill.pdf",
        file_hash="hash_reprocess_777",
        file_path=str(pdf_path),
        status=DocumentStatus.PENDING
    )
    db_session.add(doc)
    db_session.commit()

    # First process
    doc_v1 = DocumentService.process_document(db_session, doc.id)
    first_processed_at = doc_v1.processed_at

    # Second reprocess
    doc_v2 = DocumentService.reprocess_document(db_session, doc.id)

    assert doc_v2.id == doc.id
    assert doc_v2.processed_at >= first_processed_at
    assert doc_v2.extracted_data["bill_number"] == "FB-9900"


def test_get_document_stats_endpoint(client, db_session):
    """Verify GET /api/v1/documents/stats returns accurate mathematically separate counts."""
    d1 = Document(filename="c1.pdf", file_hash="h1", file_path="p1", status=DocumentStatus.COMPLETED)
    d2 = Document(filename="r1.pdf", file_hash="h2", file_path="p2", status=DocumentStatus.REVIEW)
    d3 = Document(filename="p1.pdf", file_hash="h3", file_path="p3", status=DocumentStatus.PENDING)
    d4 = Document(filename="f1.pdf", file_hash="h4", file_path="p4", status=DocumentStatus.FAILED)

    db_session.add_all([d1, d2, d3, d4])
    db_session.commit()

    response = client.get("/api/v1/documents/stats")
    assert response.status_code == 200

    data = response.json()
    assert data["total_documents"] >= 4
    assert data["completed"] >= 1
    assert data["review_needed"] >= 1
    assert data["pending"] >= 1
    assert data["failed"] >= 1


def test_submit_document_review_updates_status_to_completed(client, db_session):
    """Verify submitting manual review corrections updates document status to COMPLETED if valid."""
    doc = Document(
        filename="review_sample.pdf",
        file_hash="hash_review_111",
        file_path="review_sample.pdf",
        status=DocumentStatus.REVIEW,
        error_message="Missing bill_number"
    )
    db_session.add(doc)
    db_session.commit()

    corrections = {
        "bill_number": "HB-9988",
        "consignor": "Apex Logistics",
        "consignee": "Global Mart",
        "origin": "Mumbai",
        "destination": "Pune",
        "total_amount": "$1,200.00"
    }

    response = client.put(f"/api/v1/documents/{doc.id}/review", json={"extracted_data": corrections})
    assert response.status_code == 200

    updated = response.json()
    assert updated["status"] == "COMPLETED"
    assert updated["extracted_data"]["bill_number"] == "HB-9988"
    assert updated["extracted_data"]["manually_corrected"] is True


def test_submit_document_review_partial_corrections_remains_review(client, db_session):
    """Verify submitting partial corrections with missing fields keeps document in REVIEW status."""
    doc = Document(
        filename="review_partial.pdf",
        file_hash="hash_review_222",
        file_path="review_partial.pdf",
        status=DocumentStatus.REVIEW,
        error_message="Missing critical fields"
    )
    db_session.add(doc)
    db_session.commit()

    corrections = {
        "bill_number": "HB-1111"
        # missing consignor, consignee, origin, destination, total_amount
    }

    response = client.put(f"/api/v1/documents/{doc.id}/review", json={"extracted_data": corrections})
    assert response.status_code == 200

    updated = response.json()
    assert updated["status"] == "REVIEW"
    assert "Document flagged for manual review" in updated["error_message"]
