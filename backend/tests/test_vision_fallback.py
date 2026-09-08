"""Point 7: Groq Vision is a field-aware fallback, not the default extractor."""

from app.db.models import DocumentStatus
from app.ocr.calibration import attach_field_calibration
from app.ocr.consistency import attach_consistency_checks
from app.ocr.normalizer import normalize_freight_data, validate_extraction_status
from app.ocr.vision_fallback import (
    REASON_AMBIGUOUS,
    REASON_LOW_CONF,
    REASON_MISSING,
    apply_accepted_fallback,
    apply_fallback_disagreement_to_status,
    apply_fallback_metadata,
    merge_fallback_fields,
    run_vision_fallback,
    select_rescue_fields,
)


def _complete_fields(**overrides):
    data = {
        "bill_number": "16766-1",
        "invoice_number": "INV-1",
        "consignor": "BELL MARINE",
        "consignee": "CORONE & CO",
        "origin": "HOUSTON",
        "destination": "DALLAS",
        "freight_amount": "$100.00",
        "total_amount": "$100.00",
        "carrier": "CMAT",
        "driver_name": "JOHN SMITH",
        "weight": "40000",
    }
    data.update(overrides)
    return data


def _high_conf(extracted):
    return {key: 0.95 for key in extracted if extracted.get(key)}


def _extracted(fields=None, confidence=None):
    data = _complete_fields(**(fields or {}))
    data["field_confidence"] = confidence if confidence is not None else _high_conf(data)
    return data


def test_high_confidence_does_not_call_groq():
    extracted = _extracted()
    calls = []

    def vision_fn(*_args, **_kwargs):
        calls.append(1)
        return {"consignee": "SHOULD NOT BE USED"}

    report = run_vision_fallback(extracted, {"field_confidence": extracted["field_confidence"]}, vision_fn=vision_fn)
    assert select_rescue_fields(extracted) == []
    assert report["groq_fallback_called"] is False
    assert report["status"] == "not_needed"
    assert calls == []
    assert report["accepted"] == {}


def test_missing_critical_field_selects_that_field():
    extracted = _extracted({"consignee": ""}, {**_high_conf(_complete_fields()), "consignee": 0.0})
    plan = select_rescue_fields(extracted)
    names = [row["field"] for row in plan]
    assert "consignee" in names
    reasons = next(row["reasons"] for row in plan if row["field"] == "consignee")
    assert REASON_MISSING in reasons


def test_low_confidence_selects_field():
    extracted = _extracted(confidence={**_high_conf(_complete_fields()), "consignee": 0.41})
    plan = select_rescue_fields(extracted)
    row = next(item for item in plan if item["field"] == "consignee")
    assert REASON_LOW_CONF in row["reasons"]


def test_ambiguous_candidates_select_field():
    extracted = _extracted()
    raw_ocr = {
        "field_confidence": extracted["field_confidence"],
        "field_candidates": {
            "carrier": [
                {"value": "CMAT", "final_candidate_score": 0.82, "sources": ["ocr"]},
                {"value": "ACME FREIGHT", "final_candidate_score": 0.80, "sources": ["gazetteer"]},
            ]
        },
    }
    plan = select_rescue_fields(extracted, raw_ocr)
    row = next(item for item in plan if item["field"] == "carrier")
    assert REASON_AMBIGUOUS in row["reasons"]


def test_only_uncertain_fields_are_selected():
    extracted = _extracted(
        {"driver_name": ""},
        {**_high_conf(_complete_fields()), "consignee": 0.35, "driver_name": 0.0},
    )
    names = {row["field"] for row in select_rescue_fields(extracted)}
    assert "consignee" in names
    assert "driver_name" in names
    assert "consignor" not in names
    assert "origin" not in names
    assert "total_amount" not in names


def test_empty_deterministic_accepts_groq_value():
    extracted = _extracted({"consignee": ""}, {**_high_conf(_complete_fields()), "consignee": 0.0})
    report = run_vision_fallback(
        extracted,
        {"field_confidence": extracted["field_confidence"]},
        vision_fn=lambda *_a, **_k: {"consignee": "CORONE & CO"},
    )
    assert report["accepted"]["consignee"] == "CORONE & CO"
    decision = next(row for row in report["decisions"] if row["field"] == "consignee")
    assert decision["action"] == "accept_groq"
    assert decision["source"] == "groq_vision_fallback"


def test_weak_deterministic_accepts_groq_rescue():
    extracted = _extracted(
        {"consignee": "C0R0NE"},
        {**_high_conf(_complete_fields()), "consignee": 0.32},
    )
    report = run_vision_fallback(
        extracted,
        {"field_confidence": extracted["field_confidence"]},
        vision_fn=lambda *_a, **_k: {"consignee": "CORONE & CO"},
    )
    assert report["accepted"]["consignee"] == "CORONE & CO"
    decision = next(row for row in report["decisions"] if row["field"] == "consignee")
    assert decision["previous_value"] == "C0R0NE"
    assert decision["source"] == "groq_vision_fallback"


def test_strong_deterministic_disagreement_is_not_overwritten():
    extracted = _extracted()
    raw_ocr = {
        "field_confidence": extracted["field_confidence"],
        "field_candidates": {
            "carrier": [
                {"value": "CMAT", "final_candidate_score": 0.82, "sources": ["ocr"]},
                {"value": "ACME FREIGHT", "final_candidate_score": 0.80, "sources": ["gazetteer"]},
            ]
        },
    }
    report = run_vision_fallback(
        extracted,
        raw_ocr,
        vision_fn=lambda *_a, **_k: {"carrier": "ACME FREIGHT"},
    )
    assert "carrier" not in report["accepted"]
    decision = next(row for row in report["decisions"] if row["field"] == "carrier")
    assert decision["action"] == "keep_deterministic_disagreement"
    assert decision["previous_value"] == "CMAT"
    assert decision["groq_value"] == "ACME FREIGHT"
    assert decision["agreed_with_deterministic"] is False
    merged = apply_accepted_fallback(extracted, report)
    assert merged["carrier"] == "CMAT"


def test_strong_deterministic_agreement_keeps_value():
    extracted = _extracted()
    raw_ocr = {
        "field_confidence": extracted["field_confidence"],
        "field_candidates": {
            "carrier": [
                {"value": "CMAT", "final_candidate_score": 0.82, "sources": ["ocr"]},
                {"value": "CMAT MOBILE", "final_candidate_score": 0.80, "sources": ["ocr"]},
            ]
        },
    }
    report = run_vision_fallback(
        extracted,
        raw_ocr,
        vision_fn=lambda *_a, **_k: {"carrier": "CMAT"},
    )
    assert "carrier" not in report["accepted"]
    decision = next(row for row in report["decisions"] if row["field"] == "carrier")
    assert decision["action"] == "keep_deterministic"
    assert decision["agreed_with_deterministic"] is True
    assert apply_accepted_fallback(extracted, report)["carrier"] == "CMAT"


def test_groq_api_failure_keeps_deterministic():
    extracted = _extracted({"consignee": ""}, {**_high_conf(_complete_fields()), "consignee": 0.0})

    def boom(*_args, **_kwargs):
        raise TimeoutError("groq timeout")

    report = run_vision_fallback(extracted, {"field_confidence": extracted["field_confidence"]}, vision_fn=boom)
    assert report["accepted"] == {}
    assert report["status"] == "error"
    assert "TimeoutError" in (report["error"] or "")
    assert apply_accepted_fallback(extracted, report)["consignor"] == "BELL MARINE"
    assert not apply_accepted_fallback(extracted, report).get("consignee")


def test_groq_malformed_response_keeps_deterministic():
    extracted = _extracted({"consignee": ""}, {**_high_conf(_complete_fields()), "consignee": 0.0})
    report = run_vision_fallback(
        extracted,
        {"field_confidence": extracted["field_confidence"]},
        vision_fn=lambda *_a, **_k: "not-json",
    )
    assert report["accepted"] == {}
    assert report["error"] == "groq_vision_malformed_response"
    assert apply_accepted_fallback(extracted, report)["bill_number"] == "16766-1"


def test_candidate_context_is_passed_to_groq():
    extracted = _extracted()
    raw_ocr = {
        "field_confidence": extracted["field_confidence"],
        "field_candidates": {
            "carrier": [
                {"value": "CMAT", "final_candidate_score": 0.82, "fuzzy_score": 0.82, "prior_count": 4, "sources": ["ocr"]},
                {"value": "ACME FREIGHT", "final_candidate_score": 0.80, "sources": ["gazetteer"]},
            ]
        },
    }
    captured = {}

    def vision_fn(page_images, focus_fields=None, field_context=None):
        captured["focus_fields"] = list(focus_fields or [])
        captured["field_context"] = field_context
        return {"carrier": "CMAT"}

    run_vision_fallback(extracted, raw_ocr, page_images=["img"], vision_fn=vision_fn)
    assert "carrier" in captured["focus_fields"]
    assert "consignor" not in captured["focus_fields"]
    assert "Field: carrier" in captured["field_context"]
    assert "Current deterministic prediction: CMAT" in captured["field_context"]
    assert "CMAT" in captured["field_context"]
    assert "ACME FREIGHT" in captured["field_context"]
    assert "evidence only" in captured["field_context"].lower()


def test_fallback_provenance_is_recorded():
    extracted = _extracted({"consignee": ""}, {**_high_conf(_complete_fields()), "consignee": 0.0})
    raw_ocr = {"field_confidence": extracted["field_confidence"]}
    report = run_vision_fallback(
        extracted,
        raw_ocr,
        vision_fn=lambda *_a, **_k: {"consignee": "CORONE & CO"},
    )
    apply_fallback_metadata(raw_ocr, report)
    meta = raw_ocr["groq_fallback"]
    assert meta["groq_fallback_called"] is True
    assert "consignee" in meta["groq_fallback_fields"]
    decision = next(row for row in meta["decisions"] if row["field"] == "consignee")
    assert REASON_MISSING in decision["reason"]
    assert decision["source"] == "groq_vision_fallback"
    assert decision["previous_value"] in ("", None)
    assert decision["groq_value"] == "CORONE & CO"
    assert "focus_context" not in meta
    assert "GROQ_API_KEY" not in str(meta)


def test_calibration_consistency_and_validation_still_run_after_fallback():
    extracted = _extracted({"consignee": ""}, {**_high_conf(_complete_fields()), "consignee": 0.0})
    raw_ocr = {
        "field_confidence": extracted["field_confidence"],
        "field_candidates": {},
        "joint_decode": {"selected": {}, "relations_used": []},
    }
    report = run_vision_fallback(
        extracted,
        raw_ocr,
        vision_fn=lambda *_a, **_k: {"consignee": "CORONE & CO"},
    )
    merged = apply_accepted_fallback(extracted, report)
    normalized = normalize_freight_data(merged)
    raw_ocr["field_confidence"] = normalized.get("field_confidence", {})
    attach_field_calibration(normalized, raw_ocr)
    attach_consistency_checks(normalized, raw_ocr)
    apply_fallback_metadata(raw_ocr, report)
    status, warnings = validate_extraction_status(extracted=normalized)
    status, warnings = apply_fallback_disagreement_to_status(status, warnings, raw_ocr)
    assert normalized.get("consignee")
    assert raw_ocr["field_calibration"]["fields"]
    assert "checks" in raw_ocr["consistency_checks"]
    assert raw_ocr["groq_fallback"]["groq_fallback_called"] is True
    assert status in {DocumentStatus.REVIEW, DocumentStatus.COMPLETED}


def test_fallback_disabled_is_deterministic(monkeypatch):
    from app.ocr import vision_fallback as vf

    monkeypatch.setattr(vf.settings, "GROQ_VISION_FALLBACK_ENABLED", False)
    extracted = _extracted({"consignee": ""}, {**_high_conf(_complete_fields()), "consignee": 0.0})
    calls = []

    def vision_fn(*_args, **_kwargs):
        calls.append(1)
        return {"consignee": "SHOULD NOT APPLY"}

    report = run_vision_fallback(extracted, {"field_confidence": extracted["field_confidence"]}, vision_fn=vision_fn)
    assert report["status"] == "disabled"
    assert report["groq_fallback_called"] is False
    assert report["accepted"] == {}
    assert calls == []
    assert apply_accepted_fallback(extracted, report).get("consignee") in ("", None)


def test_merge_does_not_blind_update_unrescued_fields():
    deterministic = _complete_fields()
    groq = {**deterministic, "consignor": "WRONG CO", "consignee": "CORONE & CO"}
    plan = [
        {
            "field": "consignee",
            "reasons": [REASON_MISSING],
            "confidence": {"strong": False},
        }
    ]
    # Pretend consignee was empty in deterministic.
    deterministic["consignee"] = ""
    merged = merge_fallback_fields(deterministic, groq, plan)
    assert merged["accepted"] == {"consignee": "CORONE & CO"}
    assert "consignor" not in merged["accepted"]


def test_extractor_still_accepts_fallback_context(monkeypatch):
    from PIL import Image
    from app.ocr import groq_extractor as ge

    monkeypatch.setattr(ge.settings, "TESTING", False)
    monkeypatch.setattr(ge.settings, "ENABLE_GROQ", True)
    monkeypatch.setattr(ge.settings, "ENABLE_GROQ_VISION", True)
    monkeypatch.setattr(ge.settings, "GROQ_API_KEY", "gsk_test")
    captured = {}

    def fake_parse(messages, model, timeout=90.0, vision=False):
        captured["text"] = messages[1]["content"][0]["text"]
        return {"carrier": "CMAT"}

    monkeypatch.setattr(ge, "_groq_chat_parse", fake_parse)
    img = Image.new("RGB", (80, 60), "white")
    fields = ge.extract_fields_with_groq_vision(
        [img],
        focus_fields=["carrier"],
        field_context="Extract freight-bill fields from this scanned page.\nField: carrier\nTop candidates:\n  1. CMAT",
    )
    assert fields["carrier"] == "CMAT"
    assert "Field: carrier" in captured["text"]
    assert "CMAT" in captured["text"]


def test_local_processor_does_not_call_groq_when_fallback_disabled(create_pdf, monkeypatch):
    from app.ocr import groq_extractor as ge
    from app.ocr import vision_fallback as vf
    from app.ocr.local_processor import LocalOCRProcessor

    monkeypatch.setattr(vf.settings, "GROQ_VISION_FALLBACK_ENABLED", False)
    calls = []

    def boom(*_args, **_kwargs):
        calls.append(1)
        raise AssertionError("Groq should not run when fallback is disabled")

    monkeypatch.setattr(ge, "extract_fields_with_groq_vision", boom)
    monkeypatch.setattr(ge, "extract_fields_with_groq", boom)
    pdf_path = create_pdf(
        "fallback_disabled.pdf",
        "HANDWRITTEN FREIGHT BILL\nBill No: HB-9\nConsignor: Acme\nConsignee: Beta\n"
        "Origin: Houston\nDestination: Dallas\nTotal Amount: $20.00\n",
    )
    result = LocalOCRProcessor().process_document(pdf_path)
    assert calls == []
    assert result.raw_ocr["groq_fallback"]["status"] == "disabled"
    assert result.raw_ocr["groq_fallback"]["groq_fallback_called"] is False
    assert "document_intelligence" in result.raw_ocr
    assert result.raw_ocr.get("field_candidates") is not None
    assert result.raw_ocr.get("joint_decode") is not None
    assert result.raw_ocr.get("field_calibration") is not None
    assert result.raw_ocr.get("consistency_checks") is not None
