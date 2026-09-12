"""Point 8: deterministic layout/template classification is metadata only."""

from app.ocr.calibration import attach_field_calibration
from app.ocr.candidates import generate_field_candidates
from app.ocr.consistency import attach_consistency_checks
from app.ocr.decode import decode_joint_assignment
from app.ocr.layout_classifier import (
    LAYOUT_HANDWRITTEN,
    LAYOUT_INVOICE,
    LAYOUT_STANDARD,
    LAYOUT_TABLE,
    LAYOUT_UNKNOWN,
    attach_layout_classification,
    classify_document_layout,
    classify_layout_safe,
)
from app.ocr.matching import _empty_memory
from app.ocr.priors import empty_priors
from app.ocr.vision_fallback import run_vision_fallback, select_rescue_fields


_STANDARD_TEXT = """
FREIGHT BILL
Bill No: 16766-1
Consignor: Bell Marine Terminal
Consignee: Corone and Company
Origin: Houston Texas
Destination: Dallas Texas
Carrier: CMAT
Shipper: Bell Marine Terminal
Point of Origin: Houston
Point of Destination: Dallas
Commodity Description: Sand and gravel
Weight: 40000
Freight Amount: 100.00
Total Amount: 100.00
"""

_INVOICE_TEXT = """
INVOICE
Invoice Number: INV-4411
Invoice Date: 2024-03-01
Bill To: Acme Manufacturing LLC
Subtotal: 450.00
Sales Tax: 50.00
Amount Due: 500.00
Remit Payment to the lockbox listed below.
Please pay this invoice within thirty days of the invoice date.
"""

_TABLE_TEXT = """
Quantity Description Rate Amount Tag Number
12 Sand 10.00 120.00 4124
8 Gravel 12.00 96.00 4125
4 Dirt 9.00 36.00 4126
6 Rock 11.00 66.00 4127
2 Fill 8.00 16.00 4128
"""

_HANDWRITTEN_TEXT = "ab 19"

_UNKNOWN_TEXT = (
    "This warehouse memo discusses pallet movement, weather delays, and shift notes. "
    "Staff inspected the yard after lunch and recorded that the forklift was serviced. "
    "Nothing here resembles a printed freight form or a commercial invoice layout."
)


def _header_blocks(*labels, page_height=1000.0):
    blocks = []
    x = 40.0
    for index, label in enumerate(labels):
        y = 30.0 + index * 18.0
        blocks.append({
            "page": 1,
            "text": label,
            "bbox": [x, y, x + 240.0, y + 14.0],
            "reading_order": index + 1,
        })
    return {"block_count": len(blocks), "blocks": blocks}


def _table_spatial_items():
    items = []
    xs = [80.0, 280.0, 480.0, 680.0]
    ys = [250.0, 330.0, 410.0, 490.0, 570.0]
    labels = ["qty", "desc", "rate", "amt"]
    for row, y in enumerate(ys):
        for col, x in enumerate(xs):
            items.append({
                "bbox": [x, y, x + 70.0, y + 18.0],
                "center_x": x + 35.0,
                "center_y": y + 9.0,
                "width": 70.0,
                "height": 18.0,
                "text": f"{labels[col]}-{row}",
                "conf": 0.9,
                "page": 1,
            })
    return items


def _payload_ok(result, expected_class):
    assert result["layout_class"] == expected_class
    assert result["method"] == "deterministic"
    assert result["confidence"] == result["layout_confidence"]
    assert "field_calibration" not in result
    assert result.get("error") in (None, "")


def test_standard_freight_bill_layout():
    result = classify_document_layout(
        _STANDARD_TEXT,
        page_count=1,
        layout=_header_blocks("FREIGHT BILL", "Bill No: 16766-1", "Consignor", "Consignee"),
        text_source="pdf_text",
    )
    _payload_ok(result, LAYOUT_STANDARD)
    assert "freight_bill_keywords" in result["evidence"]
    assert result["confidence"] >= 0.70


def test_invoice_style_layout():
    result = classify_document_layout(
        _INVOICE_TEXT,
        page_count=1,
        layout=_header_blocks("INVOICE", "Invoice Number: INV-4411"),
        text_source="pdf_text",
    )
    _payload_ok(result, LAYOUT_INVOICE)
    assert "invoice_keywords" in result["evidence"]
    assert result["confidence"] >= 0.70


def test_table_heavy_layout():
    result = classify_document_layout(
        _TABLE_TEXT,
        page_count=1,
        layout={"block_count": 20, "blocks": []},
        spatial_items=_table_spatial_items(),
        text_source="pdf_text",
    )
    _payload_ok(result, LAYOUT_TABLE)
    assert "table_headers" in result["evidence"] or "table_structure" in result["evidence"]


def test_handwritten_heavy_low_ocr_density():
    result = classify_document_layout(
        _HANDWRITTEN_TEXT,
        page_count=1,
        layout={"block_count": 1, "blocks": []},
        spatial_items=[],
        text_source="preprocessed_image",
    )
    _payload_ok(result, LAYOUT_HANDWRITTEN)
    assert "low_ocr_density" in result["evidence"] or "handwriting_indicators" in result["evidence"]


def test_unknown_generic_document():
    result = classify_document_layout(
        _UNKNOWN_TEXT,
        page_count=1,
        layout={"block_count": 12, "blocks": []},
        text_source="pdf_text",
    )
    _payload_ok(result, LAYOUT_UNKNOWN)
    assert result["confidence"] < 0.55


def test_strong_evidence_matches_expected_class():
    result = classify_document_layout(
        _STANDARD_TEXT,
        page_count=1,
        layout=_header_blocks("FREIGHT BILL", "Bill of Lading", "Bill No: 12"),
        text_source="pdf_text",
    )
    assert result["layout_class"] == LAYOUT_STANDARD
    assert result["confidence"] >= 0.70
    assert "freight_header_region" in result["evidence"] or "bill_number_region" in result["evidence"]


def test_weak_evidence_is_unknown():
    result = classify_document_layout(
        "Carrier noted on file. This warehouse receipt describes pallet movement in the yard "
        "after the morning inspection, including forklift service notes and shift comments "
        "from the supervisor who walked the lot twice.",
        page_count=1,
        layout={"block_count": 10, "blocks": []},
        text_source="pdf_text",
    )
    assert result["layout_class"] == LAYOUT_UNKNOWN
    assert result["confidence"] < 0.55


def test_classification_failure_does_not_fail_processing(create_pdf, monkeypatch):
    from app.ocr import layout_classifier as lc
    from app.ocr.local_processor import LocalOCRProcessor

    def boom(*_args, **_kwargs):
        raise RuntimeError("classifier exploded")

    monkeypatch.setattr(lc, "classify_document_layout", boom)
    pdf_path = create_pdf(
        "layout_fail.pdf",
        "HANDWRITTEN FREIGHT BILL\nBill No: HB-2\nConsignor: A\nConsignee: B\n"
        "Origin: Houston\nDestination: Dallas\nTotal Amount: $20.00\n",
    )
    result = LocalOCRProcessor().process_document(pdf_path)
    assert result.extracted_data.get("bill_number")
    assert result.raw_ocr["layout_classification"]["layout_class"] == LAYOUT_UNKNOWN
    assert result.raw_ocr["layout_classification"]["evidence"] == ["classification_failed"]
    assert result.raw_ocr["layout_classification"]["error"]


def test_classification_metadata_is_persisted(create_pdf):
    from app.ocr.local_processor import LocalOCRProcessor

    pdf_path = create_pdf(
        "layout_meta.pdf",
        "FREIGHT BILL\nBill No: HB-8\nConsignor: Acme\nConsignee: Beta\n"
        "Origin: Houston\nDestination: Dallas\nCarrier: CMAT\nTotal Amount: $20.00\n",
    )
    result = LocalOCRProcessor().process_document(pdf_path)
    payload = result.raw_ocr["layout_classification"]
    assert payload["layout_class"] in {
        LAYOUT_STANDARD,
        LAYOUT_INVOICE,
        LAYOUT_TABLE,
        LAYOUT_HANDWRITTEN,
        LAYOUT_UNKNOWN,
    }
    assert payload["method"] == "deterministic"
    assert "confidence" in payload
    assert "layout_confidence" in payload
    assert isinstance(payload.get("evidence"), list)
    assert "raw_text" not in payload
    assert result.extracted_data.get("layout_class") is None


def test_extracted_fields_remain_unchanged(create_pdf, monkeypatch):
    from app.ocr.local_processor import LocalOCRProcessor

    pdf_path = create_pdf(
        "layout_stable.pdf",
        "FREIGHT BILL\nBill No: HB-7\nConsignor: Acme Logistics\nConsignee: Beta LLC\n"
        "Origin: Houston\nDestination: Dallas\nTotal Amount: $20.00\n",
    )

    def fake_unknown(*_a, **_k):
        return {
            "layout_class": LAYOUT_UNKNOWN,
            "confidence": 0.2,
            "layout_confidence": 0.2,
            "method": "deterministic",
            "evidence": ["forced"],
            "features": {},
            "error": None,
        }

    def fake_invoice(*_a, **_k):
        payload = dict(fake_unknown())
        payload["layout_class"] = LAYOUT_INVOICE
        payload["confidence"] = 0.9
        payload["layout_confidence"] = 0.9
        return payload

    monkeypatch.setattr("app.ocr.local_processor.classify_layout_safe", fake_unknown)
    first = LocalOCRProcessor().process_document(pdf_path).extracted_data
    monkeypatch.setattr("app.ocr.local_processor.classify_layout_safe", fake_invoice)
    second = LocalOCRProcessor().process_document(pdf_path).extracted_data
    keys = ("bill_number", "consignor", "consignee", "origin", "destination", "total_amount")
    for key in keys:
        assert first.get(key) == second.get(key)


def test_groq_fallback_decision_ignores_layout_class():
    extracted = {
        "consignor": "BELL MARINE",
        "consignee": "",
        "carrier": "CMAT",
        "origin": "North Hooper",
        "destination": "Discovery Bay, CA",
        "bill_number": "16766-1",
        "invoice_number": "INV-1",
        "freight_amount": "$100.00",
        "total_amount": "$100.00",
        "driver_name": "JOHN SMITH",
        "weight": "40000",
        "field_confidence": {
            "consignor": 0.95,
            "consignee": 0.0,
            "carrier": 0.95,
            "origin": 0.95,
            "destination": 0.95,
            "bill_number": 0.95,
            "invoice_number": 0.95,
            "freight_amount": 0.95,
            "total_amount": 0.95,
            "driver_name": 0.95,
            "weight": 0.95,
        },
    }
    raw = {"field_confidence": extracted["field_confidence"]}
    raw_with_layout = {
        **raw,
        "layout_classification": {
            "layout_class": LAYOUT_INVOICE,
            "confidence": 0.91,
            "layout_confidence": 0.91,
            "method": "deterministic",
            "evidence": ["forced"],
        },
    }
    assert [row["field"] for row in select_rescue_fields(extracted, raw)] == [
        row["field"] for row in select_rescue_fields(extracted, raw_with_layout)
    ]
    calls = []

    def vision_fn(*_a, **_k):
        calls.append(1)
        return {"consignee": "CORONE & CO"}

    left = run_vision_fallback(extracted, raw, vision_fn=vision_fn)
    right = run_vision_fallback(extracted, raw_with_layout, vision_fn=vision_fn)
    assert left["groq_fallback_fields"] == right["groq_fallback_fields"]
    assert left["accepted"] == right["accepted"]
    assert len(calls) == 2


def _candidate_inputs():
    gaz = {"consignor": ["Clean Planet", "Bell Marine"]}
    mem = _empty_memory()
    mem["names"] = {"consignor": list(gaz["consignor"])}
    mem["aliases"] = {"consignor": {}}
    cheap = {"consignor": "Clean Planet"}
    return cheap, gaz, mem


def test_candidate_generation_unchanged_by_layout_metadata():
    cheap, gaz, mem = _candidate_inputs()
    left = generate_field_candidates(cheap, gazetteer=gaz, memory=mem, priors=empty_priors())
    right = generate_field_candidates(cheap, gazetteer=gaz, memory=mem, priors=empty_priors())
    assert left == right
    payload = classify_document_layout(_STANDARD_TEXT, page_count=1, text_source="pdf_text")
    assert payload["layout_class"] == LAYOUT_STANDARD
    assert generate_field_candidates(cheap, gazetteer=gaz, memory=mem, priors=empty_priors()) == left


def test_joint_decoding_unchanged_by_layout_metadata():
    cheap, gaz, mem = _candidate_inputs()
    cands = generate_field_candidates(cheap, gazetteer=gaz, memory=mem, priors=empty_priors())
    left = decode_joint_assignment(cands)
    right = decode_joint_assignment(cands)
    assert left == right
    classify_document_layout(_INVOICE_TEXT, page_count=1, text_source="pdf_text")
    assert decode_joint_assignment(cands) == left


def test_calibration_unchanged_by_layout_metadata():
    extracted = {"consignor": "Clean Planet", "field_confidence": {"consignor": 0.85}}
    raw = {"field_candidates": {}, "joint_decode": {"selected": {}, "relations_used": []}}
    attach_field_calibration(extracted, raw)
    without = dict(raw["field_calibration"])
    extracted2 = {"consignor": "Clean Planet", "field_confidence": {"consignor": 0.85}}
    raw2 = {
        "field_candidates": {},
        "joint_decode": {"selected": {}, "relations_used": []},
        "layout_classification": {
            "layout_class": LAYOUT_TABLE,
            "confidence": 0.8,
            "layout_confidence": 0.8,
            "method": "deterministic",
            "evidence": ["forced"],
        },
    }
    attach_field_calibration(extracted2, raw2)
    assert raw2["field_calibration"] == without
    assert extracted2["consignor"] == "Clean Planet"


def test_consistency_unchanged_by_layout_metadata():
    extracted = {
        "consignor": "Acme",
        "consignee": "Beta",
        "freight_amount": "$10.00",
        "total_amount": "$10.00",
    }
    raw = {}
    attach_consistency_checks(extracted, raw)
    without = dict(raw["consistency_checks"])
    extracted2 = dict(extracted)
    raw2 = {
        "layout_classification": {
            "layout_class": LAYOUT_HANDWRITTEN,
            "confidence": 0.7,
            "layout_confidence": 0.7,
            "method": "deterministic",
            "evidence": ["forced"],
        }
    }
    attach_consistency_checks(extracted2, raw2)
    assert raw2["consistency_checks"] == without
    assert extracted2["consignor"] == "Acme"
    assert extracted2["consignee"] == "Beta"


def test_attach_does_not_write_extracted_values():
    extracted = {"consignee": "CORONE & CO", "carrier": "CMAT"}
    raw_ocr = {}
    payload = attach_layout_classification(
        raw_ocr,
        raw_text=_STANDARD_TEXT,
        page_count=1,
        text_source="pdf_text",
    )
    assert raw_ocr["layout_classification"]["layout_class"] == payload["layout_class"]
    assert extracted == {"consignee": "CORONE & CO", "carrier": "CMAT"}


def test_safe_wrapper_returns_unknown_on_error(monkeypatch):
    from app.ocr import layout_classifier as lc

    def boom(*_args, **_kwargs):
        raise ValueError("bad")

    monkeypatch.setattr(lc, "classify_document_layout", boom)
    payload = classify_layout_safe("anything")
    assert payload["layout_class"] == LAYOUT_UNKNOWN
    assert payload["error"]


def test_field_regions_are_label_hints_not_extracted_values():
    from app.ocr.layout_classifier import collect_field_regions, classify_document_layout

    items = [
        {
            "text": "TRUCKNO.",
            "bbox": [100.0, 200.0, 180.0, 220.0],
            "center_x": 140.0,
            "center_y": 210.0,
            "width": 80.0,
            "height": 20.0,
            "conf": 0.9,
            "page": 1,
        }
    ]
    regions = collect_field_regions(items, page_width=800, page_height=1000)
    assert "vehicle_number" in regions
    assert regions["vehicle_number"]["source"] == "spatial_label"
    result = classify_document_layout(
        "CALIFORNIA MATERIALS TRUCK NO COMMODITY",
        page_count=1,
        spatial_items=items,
        text_source="preprocessed_image",
    )
    assert result.get("field_regions", {}).get("vehicle_number")
    assert "extracted_data" not in result
