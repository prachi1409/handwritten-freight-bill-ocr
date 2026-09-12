"""Unit tests for OCR extraction normalizer, validation rules, and status decision logic."""

import pytest
from app.db.models import Document, DocumentStatus
from app.ocr.local_processor import LocalOCRProcessor
from app.ocr.normalizer import (
    clean_field_value,
    clean_identifier,
    normalize_currency,
    normalize_date,
    normalize_freight_data,
    validate_extraction_status,
)
from app.services.document_service import DocumentService


def test_stop_words_rejection():
    """Verify stop words like 'Handwritten', 'NO', 'Bill', 'Invoice' are rejected as values."""
    assert clean_field_value("Handwritten") is None
    assert clean_field_value("NO") is None
    assert clean_field_value("BILL") is None
    assert clean_field_value("INVOICE") is None
    assert clean_field_value("  ") is None
    assert clean_field_value("ADDRESS") is None
    assert clean_field_value("POINT OF DESTINATION") is None
    assert clean_field_value("SUB-HAUL#") is None
    assert clean_field_value("MILES") is None
    assert clean_field_value("MHOURS") is None
    assert clean_field_value("HOURS") is None
    assert clean_identifier("MILES") is None
    assert clean_field_value("Sharma Industrial Supply") == "Sharma Industrial Supply"
    assert clean_field_value("PrairieStateTrucking") == "PrairieStateTrucking"


def test_clean_identifier():
    """Verify embedded prefixes are stripped and clean IDs are preserved."""
    assert clean_identifier("Bill No: HB-78421") == "HB-78421"
    assert clean_identifier("Invoice No: INV-HB-5821") == "INV-HB-5821"
    assert clean_identifier("Vehicle #: UP-32-T-5821") == "UP-32-T-5821"
    assert clean_identifier("NO") is None
    assert clean_identifier("Handwritten") is None
    assert clean_identifier("एफबी-१०२३६") == "FB-10236"
    assert clean_identifier("आईएनवी-६२१") == "INV-621"


def test_currency_normalization():
    """Verify currency amounts are normalized to '$X,XXX.XX' without hallucinating amounts."""
    assert normalize_currency("$3450") == "$3,450.00"
    assert normalize_currency("3450.00") == "$3,450.00"
    assert normalize_currency("$3,450.00") == "$3,450.00"
    assert normalize_currency("INVALID") is None


def test_date_normalization():
    """Verify dates are normalized to ISO 'YYYY-MM-DD'."""
    assert normalize_date("26/08/2026") == "2026-08-26"
    assert normalize_date("2026-08-26") == "2026-08-26"
    assert normalize_date("08/26/2026") == "2026-08-26"
    assert normalize_date("DBTRSETWSBLBMD") is None
    assert normalize_date("MO. 2 DAY 2 YR. 26") == "2026-02-02"
    from app.ocr.normalizer import normalize_freight_data

    salad = normalize_freight_data({"destination": "YRZ5 Stockton Discavery Bay CA"})
    assert salad.get("destination") in (None, "")
    from app.ocr.normalizer import parse_boxed_month_day_year

    assert parse_boxed_month_day_year("JOB DAY 1347-3 NO. CA0385520") is None
    assert parse_boxed_month_day_year("JOB DAY 1105-2\nNo. 9503-4") is None
    assert parse_boxed_month_day_year("DATE\nMO. 4\nDAY 30\n25") == "2025-04-30"
    assert parse_boxed_month_day_year("YR.26\nMO. 2\nDAY 2") == "2026-02-02"
    assert normalize_date("4") is None
    assert normalize_date("30") is None


def test_no_hallucinated_placeholder_values():
    """Verify missing fields remain None rather than hallucinating dummy placeholders."""
    raw = {"bill_number": None, "consignor": None}
    norm = normalize_freight_data(raw, raw_text="some text", base_confidence=0.50)

    assert norm["bill_number"] is None
    assert norm["consignor"] is None
    assert norm["line_items"] == []


def test_validate_extraction_status_completed():
    """Valid complete freight bill results in DocumentStatus.COMPLETED."""
    data = {
        "bill_number": "HB-78421",
        "invoice_number": "INV-HB-78421",
        "consignor": "Sharma Industrial Supply",
        "consignee": "Metro Warehouse",
        "origin": "Kanpur",
        "destination": "Delhi",
        "freight_amount": "$3,450.00",
        "total_amount": "$3,450.00"
    }
    status, warnings = validate_extraction_status(data, confidence=0.90)

    assert status == DocumentStatus.COMPLETED
    assert warnings == []


def test_validate_extraction_status_review_low_confidence():
    """Low confidence OCR results in DocumentStatus.REVIEW."""
    data = {
        "bill_number": "HB-78421",
        "invoice_number": "INV-HB-78421",
        "consignor": "Sharma Industrial Supply",
        "consignee": "Metro Warehouse",
        "origin": "Kanpur",
        "destination": "Delhi",
        "freight_amount": "$3,450.00",
        "total_amount": "$3,450.00"
    }
    status, warnings = validate_extraction_status(data, confidence=0.50)

    assert status == DocumentStatus.REVIEW
    assert any("Low" in w for w in warnings)


def test_validate_extraction_status_review_missing_critical_fields():
    """Missing critical fields results in DocumentStatus.REVIEW."""
    data = {
        "bill_number": None,
        "consignor": None,
        "origin": None,
        "destination": None
    }
    status, warnings = validate_extraction_status(data, confidence=0.90)

    assert status == DocumentStatus.REVIEW
    assert any("Missing" in w for w in warnings)


def test_validate_extraction_status_missing_optional_field_still_completed():
    """Missing optional fields (e.g. carrier or vehicle_number) still allows COMPLETED status."""
    data = {
        "bill_number": "HB-78421",
        "invoice_number": "INV-HB-78421",
        "consignor": "Sharma Industrial Supply",
        "consignee": "Metro Warehouse",
        "origin": "Kanpur Industrial Area, UP",
        "destination": "Delhi Hub",
        "freight_amount": "$3,450.00",
        "total_amount": "$3,450.00",
        "invoice_number": None,  # unused; bill_number is the ticket id
        "vehicle_number": None  # optional
    }
    status, warnings = validate_extraction_status(data, confidence=0.88)

    assert status == DocumentStatus.COMPLETED
    assert warnings == []


def test_reviewed_scale_ticket_without_amounts_completes():
    """A saved review on a scale ticket with no freight/total is COMPLETED."""
    data = {
        "bill_number": "1249-3",
        "consignor": "Clean Planet Hooper",
        "consignee": "Palm Orwood Tract",
        "origin": "North Hooper St",
        "destination": "Discovery Bay, CA",
        "manually_corrected": True,
        "reviewed": True,
    }
    status, warnings = validate_extraction_status(data, confidence=0.85)

    assert status == DocumentStatus.COMPLETED
    assert any("freight_amount" in w or "total_amount" in w for w in warnings)


def test_line_items_amount_mismatch_flags_review():
    """Verify mismatch between line item amounts sum and total_amount flags document for REVIEW."""
    data = {
        "bill_number": "HB-78421",
        "invoice_number": "INV-HB-78421",
        "consignor": "Sharma Industrial Supply",
        "consignee": "Metro Warehouse",
        "origin": "Kanpur",
        "destination": "Delhi",
        "freight_amount": "$3,450.00",
        "total_amount": "$3,450.00",
        "line_items": [
            {"item_no": "1", "description": "Steel", "amount": "$4,000.00"},
            {"item_no": "2", "description": "Pipes", "amount": "$2,000.00"}
        ]
    }
    status, warnings = validate_extraction_status(data, confidence=0.90)

    assert status == DocumentStatus.REVIEW
    assert any("Line item sum" in w for w in warnings)


def test_failed_document_processing_updates_db(db_session):
    """Verify processing non-existent file sets document status to FAILED with error message."""
    doc = Document(
        original_filename="non_existent.pdf",
        stored_filename="non_existent.pdf",
        stored_path="non_existent_path.pdf",
        file_hash="hash_missing_file_000",
        status=DocumentStatus.PENDING
    )
    db_session.add(doc)
    db_session.commit()

    with pytest.raises(Exception):
        DocumentService.process_document(db_session, doc.id)

    db_session.refresh(doc)
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message is not None
