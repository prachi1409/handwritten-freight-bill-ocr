"""Offline evaluation of the current OCR pipeline. Does not change extraction."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.db.models import DocumentStatus
from app.ocr.calibration import apply_calibration_to_status, STATUS_CALIBRATED
from app.ocr.candidates import CANDIDATE_FIELDS
from app.ocr.consistency import apply_consistency_to_status
from app.ocr.decode import DECODE_FIELDS
from app.ocr.layout_classifier import LAYOUT_CLASSES
from app.ocr.matching import _collapse
from app.ocr.normalizer import CRITICAL_FIELDS, normalize_currency, validate_extraction_status
from app.ocr.vision_fallback import apply_fallback_disagreement_to_status

logger = logging.getLogger(__name__)

EVAL_FIELDS = (
    "bill_number",
    "bill_date",
    "carrier",
    "consignor",
    "consignee",
    "driver_name",
    "origin",
    "destination",
    "weight",
    "quantity",
    "rate",
    "freight_amount",
    "fuel_surcharge",
    "handling_charge",
    "total_amount",
)

MONEY_FIELDS = frozenset(
    {
        "freight_amount",
        "fuel_surcharge",
        "handling_charge",
        "total_amount",
        "rate",
    }
)

_MISSING_GOLD_TOKENS = frozenset(
    {"", "none", "null", "n/a", "na", "unknown", "—", "-", "missing"}
)


def has_eval_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    return text.lower() not in _MISSING_GOLD_TOKENS


def comparable_value(field: str, value: Any) -> str:
    """Project-native comparison key: currency normalizer for money, else matching collapse."""
    if not has_eval_value(value):
        return ""
    if field in MONEY_FIELDS:
        money = normalize_currency(value)
        if money:
            return _collapse(money)
    return _collapse(str(value))


def values_match(field: str, left: Any, right: Any) -> bool:
    a = comparable_value(field, left)
    b = comparable_value(field, right)
    return bool(a) and a == b


def load_eval_dataset(path: Path) -> List[Dict[str, Any]]:
    """Load JSON, JSONL, or CSV labels. Malformed entries are kept with an error flag."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Evaluation labels not found: {target}")
    suffix = target.suffix.lower()
    if suffix == ".jsonl":
        rows = []
        for line_no, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(_normalize_bill_row(json.loads(line), source=f"{target.name}:{line_no}"))
            except json.JSONDecodeError as err:
                rows.append(_malformed_row(f"{target.name}:{line_no}", f"invalid_json: {err}"))
        return rows
    if suffix == ".csv":
        with target.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [_normalize_bill_row(dict(row), source=f"{target.name}:{index}") for index, row in enumerate(reader, start=2)]
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"Could not parse evaluation labels JSON: {err}") from err
    if isinstance(payload, dict) and isinstance(payload.get("bills"), list):
        items = payload["bills"]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError("Evaluation labels must be a list or an object with a 'bills' array.")
    rows = []
    for index, item in enumerate(items):
        rows.append(_normalize_bill_row(item, source=f"{target.name}[{index}]"))
    return rows


def _malformed_row(bill_id: str, error: str) -> Dict[str, Any]:
    return {
        "id": bill_id,
        "path": "",
        "gold": {},
        "layout_class": None,
        "error": error,
    }


def _normalize_bill_row(raw: Any, *, source: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return _malformed_row(source, "row_not_object")
    gold = raw.get("gold") if isinstance(raw.get("gold"), dict) else {}
    if not gold:
        gold = {field: raw.get(field) for field in EVAL_FIELDS if field in raw}
    bill_id = raw.get("id") or raw.get("bill_id") or raw.get("document_id") or Path(str(raw.get("path") or source)).stem
    layout = raw.get("layout_class") or raw.get("layout") or gold.get("layout_class")
    path = str(raw.get("path") or raw.get("file") or raw.get("pdf") or "").strip()
    error = None
    if not path:
        error = "missing_path"
    return {
        "id": str(bill_id),
        "path": path,
        "gold": gold,
        "layout_class": str(layout).strip() if has_eval_value(layout) else None,
        "error": error,
    }


def _candidate_values(raw_ocr: Optional[Dict[str, Any]], field: str) -> List[Any]:
    rows = ((raw_ocr or {}).get("field_candidates") or {}).get(field) or []
    return [row.get("value") for row in rows if isinstance(row, dict)]


def _joint_selected(raw_ocr: Optional[Dict[str, Any]], field: str) -> Any:
    joint = (raw_ocr or {}).get("joint_decode") if isinstance(raw_ocr, dict) else None
    selected = (joint or {}).get("selected") if isinstance(joint, dict) else None
    if isinstance(selected, dict):
        return selected.get(field)
    return None


def _calibration_row(extracted: Optional[Dict[str, Any]], raw_ocr: Optional[Dict[str, Any]], field: str) -> Dict[str, Any]:
    for source in (raw_ocr, extracted):
        block = (source or {}).get("field_calibration") if isinstance(source, dict) else None
        row = (block or {}).get("fields", {}).get(field) if isinstance(block, dict) else None
        if isinstance(row, dict):
            return row
    return {}


def evaluation_status(extracted: Optional[Dict[str, Any]], raw_ocr: Optional[Dict[str, Any]]) -> Tuple[Any, List[str]]:
    """Same COMPLETED/REVIEW rules as document_service, without persisting."""
    data = extracted if isinstance(extracted, dict) else {}
    meta = raw_ocr if isinstance(raw_ocr, dict) else {}
    status, warnings = validate_extraction_status(extracted=data)
    cal = data.get("field_calibration") or meta.get("field_calibration")
    status, warnings = apply_calibration_to_status(status, warnings, cal)
    cons = data.get("consistency_checks") or meta.get("consistency_checks")
    status, warnings = apply_consistency_to_status(status, warnings, cons)
    status, warnings = apply_fallback_disagreement_to_status(status, warnings, meta)
    return status, warnings


def score_field(
    field: str,
    predicted: Any,
    gold: Any,
    *,
    extracted: Optional[Dict[str, Any]] = None,
    raw_ocr: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    gold_present = has_eval_value(gold)
    pred_present = has_eval_value(predicted)
    match = bool(gold_present and pred_present and values_match(field, predicted, gold))
    outcome = "gold_missing"
    if gold_present and match:
        outcome = "correct"
    elif gold_present and not pred_present:
        outcome = "missing_prediction"
    elif gold_present:
        outcome = "incorrect"
    candidates = _candidate_values(raw_ocr, field)
    topk = None
    if gold_present and candidates:
        topk = any(values_match(field, cand, gold) for cand in candidates)
    joint_value = _joint_selected(raw_ocr, field)
    joint = None
    if gold_present and has_eval_value(joint_value):
        joint = values_match(field, joint_value, gold)
    cal = _calibration_row(extracted, raw_ocr, field)
    conf_map = {}
    if isinstance(extracted, dict) and isinstance(extracted.get("field_confidence"), dict):
        conf_map = extracted["field_confidence"]
    elif isinstance(raw_ocr, dict) and isinstance(raw_ocr.get("field_confidence"), dict):
        conf_map = raw_ocr["field_confidence"]
    try:
        raw_conf = float(conf_map.get(field) if conf_map.get(field) is not None else cal.get("raw_confidence") or 0.0)
    except (TypeError, ValueError):
        raw_conf = 0.0
    calibrated = None
    if cal.get("calibration_available") and cal.get("calibration_status") == STATUS_CALIBRATED:
        try:
            calibrated = float(cal.get("calibrated_confidence"))
        except (TypeError, ValueError):
            calibrated = None
    return {
        "field": field,
        "outcome": outcome,
        "gold_present": gold_present,
        "prediction_present": pred_present,
        "correct": match,
        "topk_hit": topk,
        "joint_correct": joint,
        "raw_confidence": round(raw_conf, 4) if pred_present else None,
        "calibrated_confidence": calibrated,
        "predicted": predicted if pred_present else None,
        "gold": gold if gold_present else None,
    }


def score_groq(raw_ocr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = (raw_ocr or {}).get("groq_fallback") if isinstance(raw_ocr, dict) else None
    if not isinstance(payload, dict):
        return {
            "called": False,
            "fields_requested": [],
            "accepted": [],
            "disagreements": [],
            "rescued": [],
        }
    decisions = payload.get("decisions") or []
    accepted = [
        row.get("field")
        for row in decisions
        if isinstance(row, dict) and row.get("action") == "accept_groq"
    ]
    disagreements = [
        row.get("field")
        for row in decisions
        if isinstance(row, dict) and row.get("action") == "keep_deterministic_disagreement"
    ]
    return {
        "called": bool(payload.get("groq_fallback_called")),
        "fields_requested": list(payload.get("groq_fallback_fields") or []),
        "accepted": accepted,
        "disagreements": disagreements,
        "rescued": accepted,
    }


def score_bill(
    bill: Dict[str, Any],
    *,
    extracted: Optional[Dict[str, Any]] = None,
    raw_ocr: Optional[Dict[str, Any]] = None,
    status: Any = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    gold = bill.get("gold") if isinstance(bill.get("gold"), dict) else {}
    data = extracted if isinstance(extracted, dict) else {}
    meta = raw_ocr if isinstance(raw_ocr, dict) else {}
    fields_to_score = list(dict.fromkeys([*EVAL_FIELDS, *gold.keys()]))
    field_rows = {
        field: score_field(field, data.get(field), gold.get(field), extracted=data, raw_ocr=meta)
        for field in fields_to_score
        if field in EVAL_FIELDS or field in gold
    }
    evaluated = [row for row in field_rows.values() if row["gold_present"]]
    correct = [row for row in evaluated if row["outcome"] == "correct"]
    incorrect = [row for row in evaluated if row["outcome"] == "incorrect"]
    missing_pred = [row for row in evaluated if row["outcome"] == "missing_prediction"]
    critical_with_gold = [field for field in CRITICAL_FIELDS if field_rows.get(field, {}).get("gold_present")]
    critical_all_correct = bool(critical_with_gold) and all(
        field_rows[field]["outcome"] == "correct" for field in critical_with_gold
    )
    if status is None and not error:
        status, _warnings = evaluation_status(data, meta)
    layout_pred = ((meta.get("layout_classification") or {}) if isinstance(meta, dict) else {}).get("layout_class")
    layout_gold = bill.get("layout_class")
    layout_correct = None
    if layout_gold:
        layout_correct = str(layout_pred or "") == str(layout_gold)
    status_value = status.value if hasattr(status, "value") else status
    return {
        "id": bill.get("id"),
        "path": bill.get("path"),
        "error": error or bill.get("error"),
        "status": status_value,
        "fields": field_rows,
        "evaluated_fields": len(evaluated),
        "correct_fields": len(correct),
        "incorrect_fields": len(incorrect) + len(missing_pred),
        "field_accuracy": (len(correct) / len(evaluated)) if evaluated else None,
        "critical_fields_with_gold": critical_with_gold,
        "all_critical_correct": critical_all_correct if critical_with_gold else None,
        "groq": score_groq(meta),
        "layout_predicted": layout_pred,
        "layout_gold": layout_gold,
        "layout_correct": layout_correct,
    }


def _empty_field_stats() -> Dict[str, Any]:
    return {
        "evaluated": 0,
        "correct": 0,
        "incorrect": 0,
        "missing_prediction": 0,
        "gold_missing": 0,
        "accuracy": None,
        "topk_evaluated": 0,
        "topk_hits": 0,
        "topk_recall": None,
        "joint_evaluated": 0,
        "joint_correct": 0,
        "joint_accuracy": None,
        "raw_confidence_sum": 0.0,
        "raw_confidence_n": 0,
        "mean_raw_confidence": None,
        "calibrated_confidence_sum": 0.0,
        "calibrated_confidence_n": 0,
        "mean_calibrated_confidence": None,
    }


def aggregate_results(bill_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    scored = [row for row in bill_results if not row.get("error")]
    field_stats = {field: _empty_field_stats() for field in EVAL_FIELDS}
    layout_pred_counts: Counter[str] = Counter()
    layout_eval = 0
    layout_correct = 0
    groq_called = 0
    groq_requested = 0
    groq_accepted = 0
    groq_disagreements = 0
    groq_rescued = 0
    review = 0
    completed = 0
    critical_bills = 0
    critical_all = 0
    incorrect_total = 0

    for bill in scored:
        incorrect_total += int(bill.get("incorrect_fields") or 0)
        status = str(bill.get("status") or "")
        if status == DocumentStatus.REVIEW.value:
            review += 1
        elif status == DocumentStatus.COMPLETED.value:
            completed += 1
        if bill.get("all_critical_correct") is True:
            critical_all += 1
            critical_bills += 1
        elif bill.get("all_critical_correct") is False:
            critical_bills += 1
        groq = bill.get("groq") or {}
        if groq.get("called"):
            groq_called += 1
        groq_requested += len(groq.get("fields_requested") or [])
        groq_accepted += len(groq.get("accepted") or [])
        groq_disagreements += len(groq.get("disagreements") or [])
        groq_rescued += len(groq.get("rescued") or [])
        pred_layout = bill.get("layout_predicted") or "unknown"
        if pred_layout in LAYOUT_CLASSES:
            layout_pred_counts[pred_layout] += 1
        else:
            layout_pred_counts["unknown"] += 1
        if bill.get("layout_gold"):
            layout_eval += 1
            if bill.get("layout_correct"):
                layout_correct += 1
        for field, row in (bill.get("fields") or {}).items():
            stats = field_stats.setdefault(field, _empty_field_stats())
            if not row.get("gold_present"):
                stats["gold_missing"] += 1
                continue
            stats["evaluated"] += 1
            if row.get("outcome") == "correct":
                stats["correct"] += 1
            elif row.get("outcome") == "missing_prediction":
                stats["missing_prediction"] += 1
            else:
                stats["incorrect"] += 1
            if row.get("topk_hit") is not None:
                stats["topk_evaluated"] += 1
                if row.get("topk_hit"):
                    stats["topk_hits"] += 1
            if row.get("joint_correct") is not None:
                stats["joint_evaluated"] += 1
                if row.get("joint_correct"):
                    stats["joint_correct"] += 1
            if row.get("raw_confidence") is not None:
                stats["raw_confidence_sum"] += float(row["raw_confidence"])
                stats["raw_confidence_n"] += 1
            if row.get("calibrated_confidence") is not None:
                stats["calibrated_confidence_sum"] += float(row["calibrated_confidence"])
                stats["calibrated_confidence_n"] += 1

    for stats in field_stats.values():
        if stats["evaluated"]:
            stats["accuracy"] = round(stats["correct"] / stats["evaluated"], 4)
        if stats["topk_evaluated"]:
            stats["topk_recall"] = round(stats["topk_hits"] / stats["topk_evaluated"], 4)
        if stats["joint_evaluated"]:
            stats["joint_accuracy"] = round(stats["joint_correct"] / stats["joint_evaluated"], 4)
        if stats["raw_confidence_n"]:
            stats["mean_raw_confidence"] = round(stats["raw_confidence_sum"] / stats["raw_confidence_n"], 4)
        if stats["calibrated_confidence_n"]:
            stats["mean_calibrated_confidence"] = round(
                stats["calibrated_confidence_sum"] / stats["calibrated_confidence_n"], 4
            )

    n = len(scored)
    layout_gold_accuracy = round(layout_correct / layout_eval, 4) if layout_eval else None
    return {
        "bills_in_dataset": len(bill_results),
        "bills_evaluated": n,
        "bills_skipped": len(bill_results) - n,
        "fields": field_stats,
        "bill_level": {
            "exact_field_accuracy": round(
                sum((bill.get("field_accuracy") or 0.0) for bill in scored) / n, 4
            )
            if n
            else None,
            "all_critical_fields_correct": round(critical_all / critical_bills, 4) if critical_bills else None,
            "critical_bills_evaluated": critical_bills,
            "review_rate": round(review / n, 4) if n else None,
            "completed_rate": round(completed / n, 4) if n else None,
            "review_count": review,
            "completed_count": completed,
            "avg_incorrect_fields": round(incorrect_total / n, 4) if n else None,
        },
        "groq": {
            "bills_evaluated": n,
            "bills_called": groq_called,
            "fallback_call_rate": round(groq_called / n, 4) if n else None,
            "avg_fields_requested": round(groq_requested / groq_called, 4) if groq_called else 0.0,
            "accepted_rescue_fields": groq_accepted,
            "rejected_disagreements": groq_disagreements,
            "fields_rescued": groq_rescued,
            "disagreement_count": groq_disagreements,
        },
        "layout": {
            "predicted_distribution": {name: layout_pred_counts.get(name, 0) for name in LAYOUT_CLASSES},
            "gold_labels": layout_eval,
            "accuracy": layout_gold_accuracy,
        },
    }


def format_report(summary: Dict[str, Any]) -> str:
    fields = summary.get("fields") or {}
    bills = summary.get("bills_evaluated") or 0
    lines = [
        f"Bills evaluated: {bills}",
        f"Bills skipped: {summary.get('bills_skipped') or 0}",
        "",
        "Field accuracy:",
    ]
    for field in EVAL_FIELDS:
        stats = fields.get(field) or {}
        evaluated = stats.get("evaluated") or 0
        if not evaluated:
            lines.append(f"  {field:<18} n/a (no gold)")
            continue
        acc = (stats.get("accuracy") or 0.0) * 100
        lines.append(
            f"  {field:<18} {acc:5.1f}%  "
            f"(n={evaluated} correct={stats.get('correct')} incorrect={stats.get('incorrect')} "
            f"missing={stats.get('missing_prediction')})"
        )
    lines.extend(["", "Top-K candidate recall:"])
    for field in CANDIDATE_FIELDS:
        stats = fields.get(field) or {}
        if not stats.get("topk_evaluated"):
            lines.append(f"  {field:<18} n/a")
            continue
        lines.append(f"  {field:<18} {(stats.get('topk_recall') or 0.0)*100:5.1f}%")
    lines.extend(["", "Joint selection:"])
    for field in DECODE_FIELDS:
        stats = fields.get(field) or {}
        if not stats.get("joint_evaluated"):
            lines.append(f"  {field:<18} n/a")
            continue
        lines.append(f"  {field:<18} {(stats.get('joint_accuracy') or 0.0)*100:5.1f}%")
    groq = summary.get("groq") or {}
    lines.extend(
        [
            "",
            "Groq:",
            f"  fallback call rate: {((groq.get('fallback_call_rate') or 0.0)*100):.1f}% "
            f"({groq.get('bills_called')}/{groq.get('bills_evaluated')})",
            f"  avg fields requested: {groq.get('avg_fields_requested')}",
            f"  fields rescued: {groq.get('fields_rescued')}",
            f"  disagreements: {groq.get('disagreement_count')}",
        ]
    )
    layout = summary.get("layout") or {}
    lines.extend(["", "Layout predicted distribution:"])
    dist = layout.get("predicted_distribution") or {}
    for name in LAYOUT_CLASSES:
        lines.append(f"  {name:<22} {dist.get(name, 0)}")
    if layout.get("gold_labels"):
        lines.append(f"  layout accuracy: {(layout.get('accuracy') or 0.0)*100:.1f}%")
    else:
        lines.append("  layout accuracy: n/a (no gold layout labels)")
    bill = summary.get("bill_level") or {}
    crit = bill.get("all_critical_fields_correct")
    lines.extend(
        [
            "",
            "Bill-level:",
            f"  exact field accuracy: {((bill.get('exact_field_accuracy') or 0.0)*100):.1f}%",
            f"  all critical fields correct: {((crit or 0.0)*100):.1f}%"
            if crit is not None
            else "  all critical fields correct: n/a",
            f"  REVIEW: {((bill.get('review_rate') or 0.0)*100):.1f}% ({bill.get('review_count')})",
            f"  COMPLETED: {((bill.get('completed_rate') or 0.0)*100):.1f}% ({bill.get('completed_count')})",
            f"  avg incorrect fields: {bill.get('avg_incorrect_fields')}",
        ]
    )
    return "\n".join(lines)


def write_outputs(bill_results: Sequence[Dict[str, Any]], summary: Dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bills.json").write_text(json.dumps(list(bill_results), indent=2, default=str), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    csv_path = out_dir / "bills.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "path",
                "status",
                "error",
                "field_accuracy",
                "correct_fields",
                "incorrect_fields",
                "all_critical_correct",
                "groq_called",
                "layout_predicted",
                "layout_gold",
            ]
        )
        for bill in bill_results:
            groq = bill.get("groq") or {}
            writer.writerow(
                [
                    bill.get("id"),
                    bill.get("path"),
                    bill.get("status"),
                    bill.get("error") or "",
                    bill.get("field_accuracy"),
                    bill.get("correct_fields"),
                    bill.get("incorrect_fields"),
                    bill.get("all_critical_correct"),
                    groq.get("called"),
                    bill.get("layout_predicted"),
                    bill.get("layout_gold"),
                ]
            )
    (out_dir / "report.txt").write_text(format_report(summary) + "\n", encoding="utf-8")


def run_pipeline_on_path(file_path: Path):
    """Run the existing OCR processor. Does not alter pipeline internals."""
    from app.ingestion.convert import ensure_pdf
    from app.ocr.factory import get_ocr_processor

    pdf_path = ensure_pdf(Path(file_path))
    processor = get_ocr_processor()
    return processor.process_document(pdf_path)


def evaluate_bills(
    bills: Sequence[Dict[str, Any]],
    *,
    base_dir: Optional[Path] = None,
    run_ocr: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    root = Path(base_dir) if base_dir else Path.cwd()
    for bill in bills:
        if bill.get("error") and not bill.get("path"):
            results.append(score_bill(bill, error=bill.get("error")))
            continue
        path = Path(bill.get("path") or "")
        if not path.is_absolute():
            path = (root / path).resolve()
        if not path.exists():
            results.append(score_bill(bill, error=f"file_not_found: {path}"))
            continue
        if not run_ocr:
            results.append(score_bill(bill, error="ocr_skipped"))
            continue
        try:
            ocr = run_pipeline_on_path(path)
            results.append(
                score_bill(
                    bill,
                    extracted=ocr.extracted_data,
                    raw_ocr=ocr.raw_ocr,
                )
            )
        except Exception as err:
            logger.exception("Evaluation failed for %s", bill.get("id"))
            results.append(score_bill(bill, error=f"{type(err).__name__}: {err}"))
    return results, aggregate_results(results)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the current freight-bill OCR pipeline on labelled bills.")
    parser.add_argument("--labels", required=True, help="JSON, JSONL, or CSV gold labels")
    parser.add_argument("--out", default="eval_results", help="Output directory for reports")
    parser.add_argument("--base-dir", default=".", help="Resolve relative bill paths from this directory")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bills = load_eval_dataset(Path(args.labels))
    results, summary = evaluate_bills(bills, base_dir=Path(args.base_dir), run_ocr=True)
    write_outputs(results, summary, Path(args.out))
    print(format_report(summary))
    print(f"\nWrote reports to {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
