"""API still exposes Points 1–5 metadata for the reviewer UI without recomputing it."""

from app.db.models import Document, DocumentStatus


def test_document_get_passes_through_reviewer_metadata(client, db_session):
    meta = {
        "field_candidates": {
            "carrier": [
                {
                    "value": "ACME FREIGHT, INC.",
                    "fuzzy_score": 0.91,
                    "prior_count": 0,
                    "sources": ["ocr", "gazetteer"],
                }
            ]
        },
        "joint_decode": {
            "selected": {"carrier": "ACME FREIGHT, INC."},
            "joint_score": 2.1,
            "relations_used": [],
        },
        "field_calibration": {
            "fields": {
                "carrier": {
                    "raw_confidence": 0.85,
                    "calibrated_confidence": 0.85,
                    "calibration_status": "fallback_insufficient_data",
                    "calibration_available": False,
                    "threshold": 0.70,
                    "auto_post": True,
                }
            }
        },
        "consistency_checks": {
            "checks": [
                {
                    "code": "HISTORICAL_RELATIONSHIP_CONFLICT",
                    "severity": "warning",
                    "message": "carrier conflicts with strong historical consignor+consignee→carrier.",
                    "fields_involved": ["carrier"],
                }
            ]
        },
    }
    doc = Document(
        original_filename="reviewer_meta.pdf",
        stored_filename="reviewer_meta.pdf",
        stored_path="reviewer_meta.pdf",
        file_hash="hash-reviewer-meta-001",
        status=DocumentStatus.REVIEW,
        extracted_data={"carrier": "ACME FREIGHT, INC.", "consignor": "Clean Planet"},
        field_confidence={"carrier": 0.85},
        ocr_metadata=meta,
        validation_warnings=["Missing critical field(s): bill_number"],
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    response = client.get(f"/api/v1/documents/{doc.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["extracted_data"]["carrier"] == "ACME FREIGHT, INC."
    assert body["field_confidence"]["carrier"] == 0.85
    assert body["ocr_metadata"]["field_candidates"]["carrier"][0]["value"] == "ACME FREIGHT, INC."
    assert body["ocr_metadata"]["joint_decode"]["selected"]["carrier"] == "ACME FREIGHT, INC."
    assert body["ocr_metadata"]["field_calibration"]["fields"]["carrier"]["calibration_status"] == "fallback_insufficient_data"
    assert body["ocr_metadata"]["consistency_checks"]["checks"][0]["code"] == "HISTORICAL_RELATIONSHIP_CONFLICT"
    assert body["validation_warnings"][0].startswith("Missing critical")


def test_review_endpoint_still_accepts_extracted_data_only(client, db_session):
    doc = Document(
        original_filename="reviewer_save.pdf",
        stored_filename="reviewer_save.pdf",
        stored_path="reviewer_save.pdf",
        file_hash="hash-reviewer-save-001",
        status=DocumentStatus.REVIEW,
        extracted_data={"carrier": "ACME FREIGHT, INC."},
        ocr_metadata={"field_candidates": {"carrier": [{"value": "CALIFORNIA MATERIALS, INC.", "sources": ["gazetteer"]}]}},
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
        "total_amount": "$1,200.00",
        "carrier": "CALIFORNIA MATERIALS, INC.",
    }
    response = client.put(f"/api/v1/documents/{doc.id}/review", json={"extracted_data": corrections})
    assert response.status_code == 200
    updated = response.json()
    assert updated["extracted_data"]["carrier"] == "CALIFORNIA MATERIALS, INC."
    assert updated["extracted_data"]["manually_corrected"] is True
    assert updated["manual_corrections"] is True
