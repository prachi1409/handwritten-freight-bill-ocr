"""Point 4 confidence calibration: labels, isotonic fit, thresholds, leakage, fallback."""

from app.db.models import DocumentStatus
from app.ocr.calibration import (
    STATUS_CALIBRATED,
    STATUS_FALLBACK,
    apply_calibration_to_status,
    attach_field_calibration,
    calibrate_field_score,
    field_auto_post_threshold,
    label_review_outcome,
    prediction_features,
    record_review_calibration,
    record_review_outcomes,
)
from app.ocr.normalizer import calculate_field_confidences


def _store(field, pairs, document_prefix="hist"):
    return {
        "version": 1,
        "examples": [
            {
                "document_id": f"{document_prefix}-{index}",
                "field": field,
                "raw_confidence": raw,
                "label": label,
            }
            for index, (raw, label) in enumerate(pairs)
        ],
    }


def _enough_pairs():
    lows = [(0.20 + i * 0.02, 0) for i in range(10)]
    highs = [(0.80 + i * 0.01, 1) for i in range(10)]
    return lows + highs


def test_isotonic_calibration_with_sufficient_labels():
    store = _store("weight", _enough_pairs())
    low = calibrate_field_score("weight", 0.25, store=store)
    high = calibrate_field_score("weight", 0.92, store=store)
    assert low["calibration_status"] == STATUS_CALIBRATED
    assert high["calibration_status"] == STATUS_CALIBRATED
    assert low["calibration_method"] == "isotonic"
    assert high["calibrated_confidence"] > low["calibrated_confidence"]
    assert high["calibrated_confidence"] >= 0.7
    assert low["calibrated_confidence"] <= 0.3


def test_insufficient_data_uses_fallback():
    store = _store("weight", [(0.4, 0), (0.5, 1), (0.9, 1), (0.85, 0), (0.7, 1)])
    result = calibrate_field_score("weight", 0.88, store=store)
    assert result["calibration_status"] == STATUS_FALLBACK
    assert result["calibration_available"] is False
    assert result["calibrated_confidence"] == 0.88
    assert result["raw_confidence"] == 0.88
    assert result["sample_count"] == 5


def test_zero_examples_do_not_crash():
    result = calibrate_field_score("consignee", 0.85, store={"version": 1, "examples": []})
    assert result["calibration_status"] == STATUS_FALLBACK
    assert result["calibrated_confidence"] == 0.85
    empty_doc = attach_field_calibration({"consignee": "Acme", "field_confidence": {"consignee": 0.85}}, {})
    assert empty_doc["fields"]["consignee"]["calibration_status"] == STATUS_FALLBACK


def test_accepted_prediction_is_positive_label():
    assert label_review_outcome("Aquamarine Contractors Inc.", "Aquamarine Contractors Inc.") == 1
    assert label_review_outcome("CALIFORNIA MATERIALS, INC.", "California Materials, Inc.") == 1


def test_corrected_prediction_is_negative_label():
    assert label_review_outcome("Aggmaxine Cont", "Aquamarine Contractors Inc.") == 0
    assert label_review_outcome("Mike Gordon", "") == 0
    assert label_review_outcome(None, "Clean Planet") is None
    assert label_review_outcome("", "Clean Planet") is None


def test_reviewer_correction_is_not_prediction_time_input():
    store = {"version": 1, "examples": []}
    before = {
        "consignee": "Aggmaxine Cont",
        "field_confidence": {"consignee": 0.85},
    }
    after = {"consignee": "Aquamarine Contractors Inc."}
    record_review_outcomes(before, after, document_id="ticket-1", store=store)
    row = store["examples"][0]
    assert row["label"] == 0
    assert "predicted" not in row
    assert "gold" not in row
    assert "corrected" not in row
    assert after["consignee"] not in str(row)

    feats = prediction_features(
        "consignee",
        raw_confidence=0.85,
        extracted={"consignee": "Aggmaxine Cont"},
        field_candidates={"consignee": [{"value": "Aggmaxine Cont", "fuzzy_score": 0.9, "prior_probability": 0.0, "prior_count": 0, "sources": ["ocr"]}]},
        joint_decode={"field_contributions": {"consignee": {"unary_fuzzy": 0.9}}},
    )
    assert "gold" not in feats
    assert "corrected" not in feats
    assert "label" not in feats
    assert feats["raw_confidence"] == 0.85
    assert "Aquamarine Contractors Inc." not in str(feats)


def test_current_ticket_labels_are_excluded_from_fit():
    pairs = _enough_pairs()
    store = _store("consignee", pairs)
    leak = [
        {"document_id": "current", "field": "consignee", "raw_confidence": 0.90, "label": 0}
        for _ in range(20)
    ]
    store["examples"].extend(leak)
    held_out = calibrate_field_score("consignee", 0.90, store=store, exclude_document_id="current")
    leaked = calibrate_field_score("consignee", 0.90, store=store)
    assert held_out["sample_count"] == 20
    assert leaked["sample_count"] == 40
    assert held_out["calibrated_confidence"] >= 0.8
    assert leaked["calibrated_confidence"] < held_out["calibrated_confidence"]


def test_per_field_thresholds_are_respected():
    assert field_auto_post_threshold("weight") == 0.90
    assert field_auto_post_threshold("total_amount") == 0.90
    assert field_auto_post_threshold("rate") == 0.90
    assert field_auto_post_threshold("consignee") == 0.70
    assert field_auto_post_threshold("driver_name") == 0.70
    assert field_auto_post_threshold("bill_number") == 0.80


def test_numeric_field_is_more_conservative_than_name_field():
    store = {"version": 1, "examples": []}
    numeric = calibrate_field_score("weight", 0.85, store=store)
    name = calibrate_field_score("consignee", 0.85, store=store)
    assert numeric["threshold"] == 0.90
    assert name["threshold"] == 0.70
    assert name["auto_post"] is True
    assert numeric["auto_post"] is False


def test_noisy_name_field_uses_lower_threshold():
    result = calibrate_field_score("consignee", 0.72, store={"version": 1, "examples": []})
    assert result["threshold"] == 0.70
    assert result["auto_post"] is True
    tight = calibrate_field_score("total_amount", 0.72, store={"version": 1, "examples": []})
    assert tight["threshold"] == 0.90
    assert tight["auto_post"] is False


def test_raw_and_calibrated_confidence_are_both_exposed():
    store = _store("origin", _enough_pairs())
    extracted = {
        "origin": "Stockton, CA",
        "field_confidence": {"origin": 0.85},
    }
    raw_ocr = {"field_candidates": {}, "joint_decode": {}}
    payload = attach_field_calibration(extracted, raw_ocr, store=store)
    row = payload["fields"]["origin"]
    assert row["raw_confidence"] == 0.85
    assert "calibrated_confidence" in row
    assert extracted["field_confidence"]["origin"] == 0.85
    assert extracted["field_calibration"]["fields"]["origin"]["calibrated_confidence"] == row["calibrated_confidence"]
    assert raw_ocr["field_calibration"]["fields"]["origin"]["raw_confidence"] == 0.85


def test_calibration_review_only_when_isotonic_available():
    fallback = {
        "fields": {
            "weight": {
                "calibration_status": STATUS_FALLBACK,
                "auto_post": False,
                "calibrated_confidence": 0.40,
                "threshold": 0.90,
            }
        }
    }
    status, warnings = apply_calibration_to_status(DocumentStatus.COMPLETED, [], fallback)
    assert status == DocumentStatus.COMPLETED
    assert warnings == []

    calibrated = {
        "fields": {
            "weight": {
                "calibration_status": STATUS_CALIBRATED,
                "auto_post": False,
                "calibrated_confidence": 0.40,
                "threshold": 0.90,
            }
        }
    }
    status, warnings = apply_calibration_to_status(DocumentStatus.COMPLETED, [], calibrated)
    assert status == DocumentStatus.REVIEW
    assert any("weight" in item for item in warnings)


def test_heuristic_field_confidence_unchanged_by_calibration_module():
    extracted = {"bill_number": "HB-1", "weight": "12.5"}
    raw = calculate_field_confidences(extracted)
    assert raw["bill_number"] == 0.95
    assert raw["weight"] == 0.88
    row = calibrate_field_score("weight", raw["weight"], store={"version": 1, "examples": []})
    assert row["raw_confidence"] == 0.88
    assert row["calibrated_confidence"] == 0.88


def _carrier_row(store, document_id):
    rows = [
        row
        for row in store.get("examples") or []
        if row.get("document_id") == document_id and row.get("field") == "carrier"
    ]
    return rows


def test_first_review_accepted_is_positive():
    store = {"version": 1, "examples": []}
    _meta, store = record_review_calibration(
        {"carrier": "CMAT", "field_confidence": {"carrier": 0.85}},
        {"carrier": "CMAT"},
        document_id="rev-accept",
        ocr_metadata={},
        store=store,
    )
    rows = _carrier_row(store, "rev-accept")
    assert len(rows) == 1
    assert rows[0]["label"] == 1
    assert rows[0]["raw_confidence"] == 0.85


def test_first_review_corrected_is_negative():
    store = {"version": 1, "examples": []}
    _meta, store = record_review_calibration(
        {"carrier": "CMAT", "field_confidence": {"carrier": 0.82}},
        {"carrier": "ACME"},
        document_id="rev-correct",
        ocr_metadata={},
        store=store,
    )
    rows = _carrier_row(store, "rev-correct")
    assert len(rows) == 1
    assert rows[0]["label"] == 0


def test_first_review_cleared_field_is_negative():
    store = {"version": 1, "examples": []}
    _meta, store = record_review_calibration(
        {"carrier": "CMAT", "field_confidence": {"carrier": 0.80}},
        {"carrier": ""},
        document_id="rev-clear",
        ocr_metadata={},
        store=store,
    )
    rows = _carrier_row(store, "rev-clear")
    assert len(rows) == 1
    assert rows[0]["label"] == 0


def test_empty_prediction_skips_label():
    store = {"version": 1, "examples": []}
    _meta, store = record_review_calibration(
        {"carrier": "", "field_confidence": {"carrier": 0.0}},
        {"carrier": "CMAT"},
        document_id="rev-empty",
        ocr_metadata={},
        store=store,
    )
    assert _carrier_row(store, "rev-empty") == []


def test_rereview_does_not_label_gold_against_gold():
    store = {"version": 1, "examples": []}
    meta, store = record_review_calibration(
        {"carrier": "CMAT", "field_confidence": {"carrier": 0.84}},
        {"carrier": "ACME", "manually_corrected": True, "reviewed": True},
        document_id="rev-rereview",
        ocr_metadata={},
        store=store,
    )
    assert _carrier_row(store, "rev-rereview")[0]["label"] == 0
    gold_now = {
        "carrier": "ACME",
        "manually_corrected": True,
        "reviewed": True,
        "field_confidence": {"carrier": 0.99},
    }
    meta, store = record_review_calibration(
        gold_now,
        {"carrier": "ACME"},
        document_id="rev-rereview",
        ocr_metadata=meta,
        store=store,
    )
    rows = _carrier_row(store, "rev-rereview")
    assert len(rows) == 1
    assert rows[0]["label"] == 0
    assert rows[0]["raw_confidence"] == 0.84
    assert meta["calibration_prediction"]["fields"]["carrier"] == "CMAT"
    assert "ACME" not in str(rows[0])


def test_rereview_changed_again_still_uses_original_prediction():
    store = {"version": 1, "examples": []}
    meta, store = record_review_calibration(
        {"carrier": "CMAT", "field_confidence": {"carrier": 0.81}},
        {"carrier": "ACME"},
        document_id="rev-again",
        ocr_metadata={},
        store=store,
    )
    gold_now = {"carrier": "ACME", "reviewed": True, "manually_corrected": True}
    _meta, store = record_review_calibration(
        gold_now,
        {"carrier": "BETA FREIGHT"},
        document_id="rev-again",
        ocr_metadata=meta,
        store=store,
    )
    rows = _carrier_row(store, "rev-again")
    assert len(rows) == 1
    assert rows[0]["label"] == 0
    assert meta["calibration_prediction"]["fields"]["carrier"] == "CMAT"


def test_unavailable_original_prediction_does_not_fabricate_label():
    historical = {"document_id": "hist-1", "field": "carrier", "raw_confidence": 0.9, "label": 1}
    store = {"version": 1, "examples": [historical]}
    gold_now = {"carrier": "ACME", "reviewed": True, "manually_corrected": True}
    meta, store = record_review_calibration(
        gold_now,
        {"carrier": "ACME"},
        document_id="legacy-no-snapshot",
        ocr_metadata={},
        store=store,
    )
    assert _carrier_row(store, "legacy-no-snapshot") == []
    assert store["examples"] == [historical]
    assert "calibration_prediction" not in meta


def test_historical_examples_still_fit_after_rereview_helper():
    store = _store("weight", _enough_pairs())
    gold_now = {"weight": "12.5", "reviewed": True, "manually_corrected": True}
    _meta, store = record_review_calibration(
        gold_now,
        {"weight": "12.5"},
        document_id="legacy-skip",
        ocr_metadata={},
        store=store,
    )
    row = calibrate_field_score("weight", 0.92, store=store)
    assert row["calibration_status"] == STATUS_CALIBRATED
    assert row["sample_count"] == 20


def test_rereview_keeps_document_excluded_from_its_own_fit():
    store = _store("carrier", _enough_pairs())
    meta, store = record_review_calibration(
        {"carrier": "CMAT", "field_confidence": {"carrier": 0.90}},
        {"carrier": "ACME"},
        document_id="current-rev",
        ocr_metadata={},
        store=store,
    )
    gold_now = {"carrier": "ACME", "reviewed": True, "manually_corrected": True}
    _meta, store = record_review_calibration(
        gold_now,
        {"carrier": "ACME"},
        document_id="current-rev",
        ocr_metadata=meta,
        store=store,
    )
    held_out = calibrate_field_score("carrier", 0.90, store=store, exclude_document_id="current-rev")
    included = calibrate_field_score("carrier", 0.90, store=store)
    assert held_out["sample_count"] == 20
    assert included["sample_count"] == 21
    assert held_out["calibrated_confidence"] >= 0.8


def test_review_endpoint_preserves_original_prediction_snapshot(client, db_session):
    from app.db.models import Document, DocumentStatus

    doc = Document(
        original_filename="calib_rereview.pdf",
        stored_filename="calib_rereview.pdf",
        stored_path="calib_rereview.pdf",
        file_hash="hash-calib-rereview-001",
        status=DocumentStatus.REVIEW,
        extracted_data={"carrier": "CMAT", "consignor": "Bell Marine", "field_confidence": {"carrier": 0.85}},
        field_confidence={"carrier": 0.85},
        ocr_metadata={"field_candidates": {}},
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    first = {
        "bill_number": "HB-1",
        "invoice_number": "INV-1",
        "consignor": "Bell Marine",
        "consignee": "Corone",
        "origin": "Houston",
        "destination": "Dallas",
        "freight_amount": "$10.00",
        "total_amount": "$10.00",
        "carrier": "ACME",
    }
    response = client.put(f"/api/v1/documents/{doc.id}/review", json={"extracted_data": first})
    assert response.status_code == 200
    body = response.json()
    assert body["manual_corrections"] is True
    assert body["extracted_data"]["manually_corrected"] is True
    assert body["extracted_data"]["carrier"] == "ACME"
    snapshot = (body.get("ocr_metadata") or {}).get("calibration_prediction") or {}
    assert snapshot.get("fields", {}).get("carrier") == "CMAT"

    second = dict(first)
    second["carrier"] = "ACME"
    response = client.put(f"/api/v1/documents/{doc.id}/review", json={"extracted_data": second})
    assert response.status_code == 200
    body = response.json()
    assert body["manual_corrections"] is True
    snapshot = (body.get("ocr_metadata") or {}).get("calibration_prediction") or {}
    assert snapshot.get("fields", {}).get("carrier") == "CMAT"
    assert snapshot.get("fields", {}).get("carrier") != "ACME"
