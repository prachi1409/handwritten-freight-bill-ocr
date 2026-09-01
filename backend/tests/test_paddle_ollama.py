"""Tests for PaddleOCR result parsing and Ollama JSON mapping."""

from app.ocr.field_extractor import merge_structured_and_text_fields
from app.ocr.ollama_extractor import parse_llm_fields, _extract_json_object
from app.ocr.paddle_ocr import parse_paddle_result


def test_parse_paddle_v2_lines():
    raw = [[
        [[[0, 0], [10, 0], [10, 10], [0, 10]], ("Bill No FB-88402", 0.98)],
        [[[0, 20], [10, 20], [10, 30], [0, 30]], ("Consignor Acme", 0.91)],
    ]]
    text = parse_paddle_result(raw)
    assert "FB-88402" in text
    assert "Acme" in text


def test_parse_paddle_v3_dict():
    text = parse_paddle_result({"rec_texts": ["Freight Bill", "Total $10.00"]})
    assert "Freight Bill" in text
    assert "$10.00" in text


def test_parse_empty_paddle_result():
    assert parse_paddle_result(None) == ""
    assert parse_paddle_result([]) == ""


def test_extract_json_object_from_fenced_response():
    payload = _extract_json_object('```json\n{"bill_number": "HB-1"}\n```')
    assert payload["bill_number"] == "HB-1"


def test_parse_llm_fields_keeps_schema_only():
    parsed = parse_llm_fields({
        "bill_number": "HB-9",
        "extra": "ignore",
        "line_items": [{"description": "steel", "amount": "10"}],
    })
    assert parsed["bill_number"] == "HB-9"
    assert parsed["consignor"] == ""
    assert parsed["line_items"][0]["description"] == "steel"
    assert "extra" not in parsed


def test_merge_prefers_llm_then_regex():
    llm = {
        "bill_number": "HB-LLM",
        "consignor": "",
        "line_items": [],
    }
    text = "Bill No: HB-REGEX\nConsignor: Acme Logistics"
    merged = merge_structured_and_text_fields(llm, text)
    assert merged["bill_number"] == "HB-LLM"
    assert "Acme" in (merged.get("consignor") or "")
