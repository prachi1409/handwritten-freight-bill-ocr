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
        original_filename="handwritten_bill_test.pdf",
        stored_filename="handwritten_bill_test.pdf",
        stored_path=str(pdf_path),
        file_hash="hash_handwritten_bill_test_123",
        status=DocumentStatus.PENDING
    )
    db_session.add(doc)
    db_session.commit()

    updated = DocumentService.process_document(db_session, doc.id)

    assert updated.status == DocumentStatus.COMPLETED
    assert updated.extracted_data["bill_number"] == "HB-78421"
    assert updated.extracted_data.get("invoice_number") in (None, "")
    assert updated.extracted_data["consignor"] == "Sharma Industrial Supply"
    assert updated.extracted_data["freight_amount"] == "$3,450.00"
    assert updated.overall_confidence >= 0.70


def test_freight_amount_vs_total_amount_separation(db_session, create_pdf):
    """Benchmark test: Ensure Freight Amount ($848.89) and Total Amount ($916.80) are never confused or copied."""
    text_content = (
        "FREIGHT BILL & MANIFEST\n"
        "Bill No: FB-10238\n"
        "Invoice No: INV-87924\n"
        "Date: 8/24/26\n"
        "Carrier: Midwest Hauling LLC\n"
        "Consignor: Acme Steel Corp\n"
        "Consignee: Costco Wholesale #221\n"
        "Origin: Chicago, IL\n"
        "Destination: Memphis, TN\n"
        "Commodity Description: Building Materials\n"
        "Quantity: 21\n"
        "Weight: 43,533 lbs\n"
        "Freight Amount: 848.89\n"
        "Total Amount: 916.80\n"
        "Vehicle Number: #261\n"
        "Driver Name: Roberto Nunez\n"
    )
    pdf_path = create_pdf("freight_bill_clean_005.pdf", text_content)

    doc = Document(
        original_filename="freight_bill_clean_005.pdf",
        stored_filename="freight_bill_clean_005.pdf",
        stored_path=str(pdf_path),
        file_hash="hash_clean_005_test",
        status=DocumentStatus.PENDING
    )
    db_session.add(doc)
    db_session.commit()

    updated = DocumentService.process_document(db_session, doc.id)

    assert updated.status == DocumentStatus.COMPLETED
    assert updated.extracted_data["bill_number"] == "FB-10238"
    assert updated.extracted_data["freight_amount"] == "$848.89"
    assert updated.extracted_data["total_amount"] == "$916.80"
    assert updated.extracted_data["freight_amount"] != updated.extracted_data["total_amount"]


def test_low_confidence_ocr_results_in_review_status(db_session, create_pdf):
    """Verify document with sparse or low confidence text results in DocumentStatus.REVIEW."""
    pdf_path = create_pdf("sparse_bill.pdf", "Some random text without bill numbers or amounts.")

    doc = Document(
        original_filename="sparse_bill.pdf",
        stored_filename="sparse_bill.pdf",
        stored_path=str(pdf_path),
        file_hash="hash_sparse_bill_999",
        status=DocumentStatus.PENDING
    )
    db_session.add(doc)
    db_session.commit()

    updated = DocumentService.process_document(db_session, doc.id)

    assert updated.status == DocumentStatus.REVIEW
    assert updated.error_message is not None
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
        original_filename="reprocess_bill.pdf",
        stored_filename="reprocess_bill.pdf",
        stored_path=str(pdf_path),
        file_hash="hash_reprocess_777",
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
    d1 = Document(original_filename="c1.pdf", stored_filename="c1.pdf", stored_path="p1", file_hash="h1", status=DocumentStatus.COMPLETED)
    d2 = Document(original_filename="r1.pdf", stored_filename="r1.pdf", stored_path="p2", file_hash="h2", status=DocumentStatus.REVIEW)
    d3 = Document(original_filename="p1.pdf", stored_filename="p1.pdf", stored_path="p3", file_hash="h3", status=DocumentStatus.PENDING)
    d4 = Document(original_filename="f1.pdf", stored_filename="f1.pdf", stored_path="p4", file_hash="h4", status=DocumentStatus.FAILED)

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
        original_filename="review_sample.pdf",
        stored_filename="review_sample.pdf",
        stored_path="review_sample.pdf",
        file_hash="hash_review_111",
        status=DocumentStatus.REVIEW,
        error_message="Missing bill_number"
    )
    db_session.add(doc)
    db_session.commit()

    corrections = {
        "bill_number": "HB-9988",
        "invoice_number": "INV-9988",
        "consignor": "Apex Logistics",
        "consignee": "Global Mart",
        "origin": "Mumbai",
        "destination": "Pune",
        "freight_amount": "$1,200.00",
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
        original_filename="review_partial.pdf",
        stored_filename="review_partial.pdf",
        stored_path="review_partial.pdf",
        file_hash="hash_review_222",
        status=DocumentStatus.REVIEW,
        error_message="Missing critical fields"
    )
    db_session.add(doc)
    db_session.commit()

    corrections = {
        "bill_number": "HB-1111"
    }

    response = client.put(f"/api/v1/documents/{doc.id}/review", json={"extracted_data": corrections})
    assert response.status_code == 200

    updated = response.json()
    assert updated["status"] == "REVIEW"
    assert updated["error_message"] is not None


def test_submit_reviewed_scale_ticket_without_amounts_completes(client, db_session):
    """CMAT scale tickets have no freight/total; a saved review should still complete."""
    doc = Document(
        original_filename="cmat_scale.pdf",
        stored_filename="cmat_scale.pdf",
        stored_path="cmat_scale.pdf",
        file_hash="hash_review_scale_333",
        status=DocumentStatus.REVIEW,
        error_message="Missing critical field(s): freight_amount, total_amount",
    )
    db_session.add(doc)
    db_session.commit()

    corrections = {
        "bill_number": "1249-3",
        "consignor": "Clean Planet Hooper",
        "consignee": "Palm Orwood Tract",
        "origin": "North Hooper St",
        "destination": "Discovery Bay, CA",
        "weight": "187.08",
        "quantity": "7",
    }

    response = client.put(f"/api/v1/documents/{doc.id}/review", json={"extracted_data": corrections})
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "COMPLETED"
    assert updated["manual_corrections"] is True


def test_groq_primary_is_off_during_pytest():
    from app.ocr.runtime import groq_vision_primary, groq_vision_primary_enabled

    token = groq_vision_primary.set(True)
    try:
        assert groq_vision_primary_enabled() is False
    finally:
        groq_vision_primary.reset(token)


def test_upload_path_does_not_call_groq_primary(monkeypatch, create_pdf):
    from app.ocr.local_processor import LocalOCRProcessor

    def boom(*_a, **_k):
        raise AssertionError("Groq Vision primary must not run on upload")

    monkeypatch.setattr("app.ocr.groq_extractor.extract_fields_with_groq_vision", boom)
    pdf_path = create_pdf("upload_no_groq_primary.pdf", "Bill No: FB-1\nShipper: Alpha\nFreight: $10.00")
    LocalOCRProcessor().process_document(pdf_path)


def test_reprocess_flag_uses_groq_vision_primary(monkeypatch, create_pdf):
    from app.ocr.local_processor import LocalOCRProcessor
    import app.ocr.local_processor as lp

    monkeypatch.setattr(lp, "groq_vision_primary_enabled", lambda: True)

    def fake_vision(_images, **_k):
        return {
            "destination": "Discovery Bay",
            "consignor": "Bell Marine",
            "consignee": "Aquamarine",
            "origin": "North Hooper",
        }

    monkeypatch.setattr("app.ocr.groq_extractor.extract_fields_with_groq_vision", fake_vision)
    pdf_path = create_pdf("reprocess_groq_primary.pdf", "Bill No: FB-2\nFreight: $10.00")
    result = LocalOCRProcessor().process_document(pdf_path)
    assert (result.raw_ocr or {}).get("groq_vision_primary") is True
    assert str((result.raw_ocr or {}).get("field_source") or "").startswith("groq-vision-primary")
    assert "Discovery" in str(result.extracted_data.get("destination") or "")
