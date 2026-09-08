"""Evaluation harness: scoring only. Does not change OCR extraction."""

import json

from app.db.models import DocumentStatus
from app.ocr.evaluation import (
    aggregate_results,
    comparable_value,
    format_report,
    has_eval_value,
    load_eval_dataset,
    score_bill,
    values_match,
)


def test_value_comparison_uses_collapse_and_currency():
    assert values_match("carrier", "CMAT", "c-mat")
    assert values_match("consignee", "CORONE & CO", "Corone & Co")
    assert values_match("freight_amount", "$1,200.00", "1200")
    assert values_match("total_amount", "$10.00", "$10")
    assert not values_match("carrier", "CMAT", "ACME")
    assert comparable_value("carrier", "C-MAT") == comparable_value("carrier", "cmat")


def test_missing_prediction_and_missing_gold():
    bill = {"id": "b1", "path": "x.pdf", "gold": {"carrier": "CMAT", "consignee": None}}
    result = score_bill(
        bill,
        extracted={"carrier": "", "consignee": "BETA"},
        raw_ocr={},
        status=DocumentStatus.REVIEW,
    )
    assert result["fields"]["carrier"]["outcome"] == "missing_prediction"
    assert result["fields"]["consignee"]["outcome"] == "gold_missing"
    assert result["fields"]["consignee"]["gold_present"] is False


def test_topk_recall_and_joint_selection():
    bill = {"id": "b2", "path": "x.pdf", "gold": {"carrier": "CMAT", "consignee": "CORONE"}}
    extracted = {"carrier": "CMAT", "consignee": "WRONG"}
    raw_ocr = {
        "field_candidates": {
            "carrier": [{"value": "CMAT"}, {"value": "ACME"}],
            "consignee": [{"value": "ACME"}, {"value": "BETA"}],
        },
        "joint_decode": {"selected": {"carrier": "CMAT", "consignee": "CORONE"}},
    }
    result = score_bill(bill, extracted=extracted, raw_ocr=raw_ocr, status=DocumentStatus.REVIEW)
    assert result["fields"]["carrier"]["topk_hit"] is True
    assert result["fields"]["consignee"]["topk_hit"] is False
    assert result["fields"]["carrier"]["joint_correct"] is True
    assert result["fields"]["consignee"]["joint_correct"] is True
    summary = aggregate_results([result])
    assert summary["fields"]["carrier"]["topk_recall"] == 1.0
    assert summary["fields"]["consignee"]["topk_recall"] == 0.0
    assert summary["fields"]["carrier"]["joint_accuracy"] == 1.0
    assert summary["fields"]["consignee"]["joint_accuracy"] == 1.0


def test_groq_fallback_metrics():
    bill = {"id": "b3", "path": "x.pdf", "gold": {"carrier": "CMAT"}}
    raw_ocr = {
        "groq_fallback": {
            "groq_fallback_called": True,
            "groq_fallback_fields": ["consignee", "driver_name"],
            "decisions": [
                {"field": "consignee", "action": "accept_groq"},
                {"field": "driver_name", "action": "keep_deterministic_disagreement"},
            ],
        }
    }
    result = score_bill(
        bill,
        extracted={"carrier": "CMAT"},
        raw_ocr=raw_ocr,
        status=DocumentStatus.REVIEW,
    )
    assert result["groq"]["called"] is True
    assert result["groq"]["accepted"] == ["consignee"]
    assert result["groq"]["disagreements"] == ["driver_name"]
    summary = aggregate_results([result])
    assert summary["groq"]["bills_called"] == 1
    assert summary["groq"]["fallback_call_rate"] == 1.0
    assert summary["groq"]["avg_fields_requested"] == 2.0
    assert summary["groq"]["fields_rescued"] == 1
    assert summary["groq"]["disagreement_count"] == 1


def test_bill_level_aggregation_and_critical_fields():
    gold = {
        "bill_number": "HB-1",
        "invoice_number": "INV-1",
        "consignor": "A",
        "consignee": "B",
        "origin": "X",
        "destination": "Y",
        "freight_amount": "$10.00",
        "total_amount": "$10.00",
    }
    perfect = score_bill(
        {"id": "ok", "path": "a.pdf", "gold": gold},
        extracted=gold,
        raw_ocr={},
        status=DocumentStatus.COMPLETED,
    )
    broken = score_bill(
        {"id": "bad", "path": "b.pdf", "gold": gold},
        extracted={**gold, "consignee": "WRONG"},
        raw_ocr={},
        status=DocumentStatus.REVIEW,
    )
    assert perfect["all_critical_correct"] is True
    assert broken["all_critical_correct"] is False
    summary = aggregate_results([perfect, broken])
    assert summary["bills_evaluated"] == 2
    assert summary["bill_level"]["all_critical_fields_correct"] == 0.5
    assert summary["bill_level"]["review_rate"] == 0.5
    assert summary["bill_level"]["completed_rate"] == 0.5
    assert summary["bill_level"]["avg_incorrect_fields"] == 0.5
    report = format_report(summary)
    assert "Bills evaluated: 2" in report
    assert "REVIEW" in report


def test_empty_dataset():
    summary = aggregate_results([])
    assert summary["bills_evaluated"] == 0
    assert summary["groq"]["fallback_call_rate"] is None
    assert summary["bill_level"]["avg_incorrect_fields"] is None
    assert "n/a" in format_report(summary)


def test_malformed_and_missing_labels(tmp_path):
    jsonl = tmp_path / "labels.jsonl"
    jsonl.write_text("{not-json\n{\"id\": \"ok\", \"path\": \"a.pdf\", \"gold\": {\"carrier\": \"CMAT\"}}\n", encoding="utf-8")
    rows = load_eval_dataset(jsonl)
    assert any(row.get("error") for row in rows)
    assert any(row.get("id") == "ok" and row["gold"]["carrier"] == "CMAT" for row in rows)

    empty_gold = score_bill(
        {"id": "g", "path": "a.pdf", "gold": {}},
        extracted={"carrier": "CMAT"},
        raw_ocr={},
        status=DocumentStatus.REVIEW,
    )
    assert empty_gold["evaluated_fields"] == 0
    assert empty_gold["fields"]["carrier"]["outcome"] == "gold_missing"


def test_load_json_bills_wrapper(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps(
            {
                "bills": [
                    {
                        "id": "bill_001",
                        "path": "docs/a.pdf",
                        "gold": {"carrier": "CMAT", "consignee": ""},
                        "layout_class": "handwritten_heavy",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = load_eval_dataset(path)
    assert rows[0]["id"] == "bill_001"
    assert has_eval_value(rows[0]["gold"]["consignee"]) is False
    assert rows[0]["layout_class"] == "handwritten_heavy"


def test_layout_distribution_without_gold():
    bill = score_bill(
        {"id": "l1", "path": "a.pdf", "gold": {"carrier": "CMAT"}},
        extracted={"carrier": "CMAT"},
        raw_ocr={"layout_classification": {"layout_class": "standard_freight_bill"}},
        status=DocumentStatus.COMPLETED,
    )
    summary = aggregate_results([bill])
    assert summary["layout"]["predicted_distribution"]["standard_freight_bill"] == 1
    assert summary["layout"]["accuracy"] is None


def test_calibrated_confidence_only_when_available():
    bill = {"id": "c1", "path": "a.pdf", "gold": {"carrier": "CMAT"}}
    extracted = {
        "carrier": "CMAT",
        "field_confidence": {"carrier": 0.85},
        "field_calibration": {
            "fields": {
                "carrier": {
                    "raw_confidence": 0.85,
                    "calibrated_confidence": 0.72,
                    "calibration_available": True,
                    "calibration_status": "calibrated",
                }
            }
        },
    }
    result = score_bill(bill, extracted=extracted, raw_ocr={}, status=DocumentStatus.COMPLETED)
    assert result["fields"]["carrier"]["calibrated_confidence"] == 0.72
    fallback = score_bill(
        bill,
        extracted={
            "carrier": "CMAT",
            "field_confidence": {"carrier": 0.85},
            "field_calibration": {
                "fields": {
                    "carrier": {
                        "raw_confidence": 0.85,
                        "calibrated_confidence": 0.85,
                        "calibration_available": False,
                        "calibration_status": "fallback_insufficient_data",
                    }
                }
            },
        },
        raw_ocr={},
        status=DocumentStatus.COMPLETED,
    )
    assert fallback["fields"]["carrier"]["calibrated_confidence"] is None
    assert fallback["fields"]["carrier"]["raw_confidence"] == 0.85
