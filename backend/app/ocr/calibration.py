"""Point 4: isotonic calibration of raw field confidence from reviewer accept/reject labels."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.ocr.matching import _collapse
from app.ocr.normalizer import ALL_SCHEMA_FIELDS

logger = logging.getLogger(__name__)

# Tighter auto-post bar: numeric / financial fields where a miss is costly.
NUMERIC_THRESHOLD_FIELDS = frozenset(
    {
        "weight",
        "quantity",
        "freight_amount",
        "fuel_surcharge",
        "handling_charge",
        "total_amount",
        "rate",
    }
)
# Looser bar: handwritten names and places that are inherently noisy.
NAME_THRESHOLD_FIELDS = frozenset(
    {
        "consignee",
        "consignor",
        "carrier",
        "driver_name",
        "origin",
        "destination",
        "driver_signature",
        "consignee_signature",
    }
)

STATUS_CALIBRATED = "calibrated"
STATUS_FALLBACK = "fallback_insufficient_data"
STATUS_EMPTY = "empty_field"
STATUS_REVIEWED = "reviewed_gold"

_calibration_cache: Optional[Dict[str, Any]] = None


def _runtime_path() -> Path:
    storage = Path(getattr(settings, "STORAGE_LOCATION", "./storage/documents")).resolve()
    return storage.parent / "calibration.json"


def empty_calibration_store() -> Dict[str, Any]:
    return {"version": 1, "examples": []}


def invalidate_calibration_cache() -> None:
    global _calibration_cache
    _calibration_cache = None


def _min_samples() -> int:
    try:
        return max(1, int(getattr(settings, "CALIBRATION_MIN_SAMPLES", 20) or 20))
    except (TypeError, ValueError):
        return 20


def _min_positives() -> int:
    try:
        return max(0, int(getattr(settings, "CALIBRATION_MIN_POSITIVES", 3) or 3))
    except (TypeError, ValueError):
        return 3


def _min_negatives() -> int:
    try:
        return max(0, int(getattr(settings, "CALIBRATION_MIN_NEGATIVES", 3) or 3))
    except (TypeError, ValueError):
        return 3


def field_auto_post_threshold(field: str) -> float:
    """Configurable per-field auto-post threshold. Numeric is tighter; names are looser."""
    try:
        if field in NUMERIC_THRESHOLD_FIELDS:
            return float(getattr(settings, "CONFIDENCE_THRESHOLD_NUMERIC", 0.90) or 0.90)
        if field in NAME_THRESHOLD_FIELDS:
            return float(getattr(settings, "CONFIDENCE_THRESHOLD_NAME", 0.70) or 0.70)
        return float(getattr(settings, "CONFIDENCE_THRESHOLD_DEFAULT", 0.80) or 0.80)
    except (TypeError, ValueError):
        return 0.80


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in {"none", "null", "n/a", "unknown"}


def _values_match(left: Any, right: Any) -> bool:
    return _collapse(str(left or "")) == _collapse(str(right or "")) and bool(_collapse(str(left or "")))


def label_review_outcome(predicted: Any, gold: Any) -> Optional[int]:
    """1 if the prediction was accepted, 0 if the reviewer corrected/cleared it, None if no prediction."""
    if not _has_value(predicted):
        return None
    if not _has_value(gold):
        return 0
    return 1 if _values_match(predicted, gold) else 0


def prediction_features(
    field: str,
    *,
    raw_confidence: float,
    extracted: Optional[Dict[str, Any]] = None,
    field_candidates: Optional[Dict[str, Any]] = None,
    joint_decode: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Prediction-time evidence only. Never includes reviewer gold/corrections."""
    chosen = None
    if isinstance(extracted, dict):
        chosen = extracted.get(field)
    rows = []
    if isinstance(field_candidates, dict):
        rows = [row for row in (field_candidates.get(field) or []) if isinstance(row, dict)]
    chosen_key = _collapse(str(chosen or ""))
    rank = None
    fuzzy = None
    prior_p = 0.0
    prior_count = 0
    sources: List[str] = []
    for index, row in enumerate(rows):
        if chosen_key and _collapse(str(row.get("value") or "")) == chosen_key:
            rank = index + 1
            fuzzy = row.get("fuzzy_score")
            prior_p = float(row.get("prior_probability") or 0.0)
            prior_count = int(row.get("prior_count") or 0)
            sources = list(row.get("sources") or [])
            break
    joint_contrib = None
    if isinstance(joint_decode, dict):
        contrib = (joint_decode.get("field_contributions") or {}).get(field) or {}
        if isinstance(contrib, dict):
            joint_contrib = contrib.get("unary_fuzzy")
    return {
        "raw_confidence": round(float(raw_confidence or 0.0), 4),
        "fuzzy_score": None if fuzzy is None else round(float(fuzzy), 4),
        "prior_probability": round(prior_p, 4),
        "prior_count": prior_count,
        "has_historical_support": prior_count > 0,
        "candidate_rank": rank,
        "sources": sources,
        "joint_unary_fuzzy": joint_contrib,
        "ocr_evidence": bool(sources and ("ocr" in sources or "ocr_text" in sources)),
    }


def fit_isotonic(xs: Sequence[float], ys: Sequence[float]) -> List[Tuple[float, float]]:
    """PAVA isotonic regression. Returns non-decreasing (x_anchor, y_hat) points."""
    paired = sorted(
        ((float(x), float(y)) for x, y in zip(xs, ys)),
        key=lambda item: item[0],
    )
    if not paired:
        return []
    blocks: List[List[float]] = []
    for x, y in paired:
        blocks.append([x, x, y, 1.0])
        while len(blocks) >= 2:
            prev = blocks[-2]
            cur = blocks[-1]
            if (prev[2] / prev[3]) <= (cur[2] / cur[3]) + 1e-12:
                break
            merged = [
                prev[0],
                cur[1],
                prev[2] + cur[2],
                prev[3] + cur[3],
            ]
            blocks[-2:] = [merged]
    points: List[Tuple[float, float]] = []
    for x0, x1, total, n in blocks:
        anchor = (float(x0) + float(x1)) / 2.0
        hat = max(0.0, min(1.0, float(total) / float(n)))
        points.append((anchor, hat))
    return points


def predict_isotonic(points: Sequence[Tuple[float, float]], raw: float) -> float:
    if not points:
        return max(0.0, min(1.0, float(raw)))
    x = float(raw)
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for index in range(1, len(points)):
        x0, y0 = points[index - 1]
        x1, y1 = points[index]
        if x <= x1:
            if abs(x1 - x0) < 1e-12:
                return y1
            ratio = (x - x0) / (x1 - x0)
            return max(0.0, min(1.0, y0 + ratio * (y1 - y0)))
    return points[-1][1]


def load_calibration_store() -> Dict[str, Any]:
    global _calibration_cache
    if getattr(settings, "TESTING", False):
        return empty_calibration_store()
    if _calibration_cache is not None:
        return _calibration_cache
    path = _runtime_path()
    if not path.exists():
        _calibration_cache = empty_calibration_store()
        return _calibration_cache
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        logger.warning("Could not read calibration file: %s", err)
        _calibration_cache = empty_calibration_store()
        return _calibration_cache
    store = empty_calibration_store()
    rows = payload.get("examples") if isinstance(payload, dict) else None
    if isinstance(rows, list):
        store["examples"] = [row for row in rows if isinstance(row, dict)]
    _calibration_cache = store
    return store


def save_calibration_store(store: Dict[str, Any]) -> None:
    global _calibration_cache
    if getattr(settings, "TESTING", False):
        _calibration_cache = store
        return
    path = _runtime_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, indent=2), encoding="utf-8")
        _calibration_cache = store
    except Exception as err:
        logger.warning("Could not save calibration file: %s", err)


def _examples_for_field(
    field: str,
    store: Dict[str, Any],
    *,
    exclude_document_id: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    skip = str(exclude_document_id) if exclude_document_id is not None else None
    out: List[Dict[str, Any]] = []
    for row in store.get("examples") or []:
        if not isinstance(row, dict) or row.get("field") != field:
            continue
        if skip and str(row.get("document_id") or "") == skip:
            continue
        if row.get("label") not in (0, 1):
            continue
        out.append(row)
    return out


def _can_fit(examples: Sequence[Dict[str, Any]]) -> bool:
    if len(examples) < _min_samples():
        return False
    positives = sum(1 for row in examples if int(row.get("label") or 0) == 1)
    negatives = sum(1 for row in examples if int(row.get("label") or 0) == 0)
    return positives >= _min_positives() and negatives >= _min_negatives()


CALIBRATION_PREDICTION_KEY = "calibration_prediction"


def _is_reviewer_gold(extracted: Optional[Dict[str, Any]]) -> bool:
    """True when extracted_data is a reviewer-submitted correction, not a pipeline prediction."""
    if not isinstance(extracted, dict):
        return False
    return bool(extracted.get("reviewed") or extracted.get("manually_corrected"))


def snapshot_extraction_prediction(extracted: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Minimal pipeline-prediction snapshot for later re-review labels. No gold, images, or text."""
    data = extracted if isinstance(extracted, dict) else {}
    confs = data.get("field_confidence") if isinstance(data.get("field_confidence"), dict) else {}
    fields: Dict[str, Any] = {}
    confidence: Dict[str, Any] = {}
    for field in ALL_SCHEMA_FIELDS:
        if field in data:
            fields[field] = data.get(field)
        if confs.get(field) is not None:
            try:
                confidence[field] = round(float(confs[field]), 4)
            except (TypeError, ValueError):
                continue
    return {"fields": fields, "field_confidence": confidence}


def _before_from_snapshot(snapshot: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return None
    fields = snapshot.get("fields")
    if not isinstance(fields, dict):
        return None
    before = dict(fields)
    confs = snapshot.get("field_confidence")
    if isinstance(confs, dict):
        before["field_confidence"] = confs
    return before


def resolve_calibration_prediction(
    extracted: Optional[Dict[str, Any]],
    ocr_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Pipeline prediction to compare with gold. None if only reviewer gold is available."""
    snapshot = None
    if isinstance(ocr_metadata, dict):
        snapshot = ocr_metadata.get(CALIBRATION_PREDICTION_KEY)
    restored = _before_from_snapshot(snapshot)
    if restored is not None:
        return restored
    if _is_reviewer_gold(extracted):
        return None
    if isinstance(extracted, dict):
        return extracted
    return None


def ensure_calibration_prediction(
    ocr_metadata: Optional[Dict[str, Any]],
    extracted: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Store the original pipeline prediction once. Never replace it with gold."""
    meta = dict(ocr_metadata) if isinstance(ocr_metadata, dict) else {}
    if _before_from_snapshot(meta.get(CALIBRATION_PREDICTION_KEY)) is not None:
        return meta
    if _is_reviewer_gold(extracted) or not isinstance(extracted, dict):
        return meta
    meta[CALIBRATION_PREDICTION_KEY] = snapshot_extraction_prediction(extracted)
    return meta


def record_review_calibration(
    extracted: Optional[Dict[str, Any]],
    corrected: Optional[Dict[str, Any]],
    *,
    document_id: Optional[Any] = None,
    ocr_metadata: Optional[Dict[str, Any]] = None,
    store: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Capture original prediction if needed, then label original vs reviewer gold."""
    meta = ensure_calibration_prediction(ocr_metadata, extracted)
    before = resolve_calibration_prediction(extracted, meta)
    if before is None:
        if store is not None:
            return meta, store
        if getattr(settings, "TESTING", False):
            return meta, empty_calibration_store()
        return meta, load_calibration_store()
    return meta, record_review_outcomes(before, corrected, document_id=document_id, store=store)


def record_review_outcomes(
    before: Optional[Dict[str, Any]],
    after: Optional[Dict[str, Any]],
    *,
    document_id: Optional[Any] = None,
    store: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Append accept/reject labels from a review. Uses the pre-review prediction only."""
    persist = store is None
    if persist and getattr(settings, "TESTING", False):
        return empty_calibration_store()
    if before is None:
        return store if store is not None else load_calibration_store()
    payload = store if store is not None else load_calibration_store()
    predicted = before if isinstance(before, dict) else {}
    gold = after if isinstance(after, dict) else {}
    raw_confs = predicted.get("field_confidence") if isinstance(predicted.get("field_confidence"), dict) else {}
    ticket = str(document_id) if document_id is not None else ""
    kept: List[Dict[str, Any]] = []
    for row in payload.get("examples") or []:
        if not isinstance(row, dict):
            continue
        if ticket and str(row.get("document_id") or "") == ticket:
            continue
        kept.append(row)
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for field in ALL_SCHEMA_FIELDS:
        pred = predicted.get(field)
        label = label_review_outcome(pred, gold.get(field))
        if label is None:
            continue
        try:
            raw = float(raw_confs.get(field) if raw_confs.get(field) is not None else 0.85)
        except (TypeError, ValueError):
            raw = 0.85
        kept.append(
            {
                "document_id": ticket,
                "field": field,
                "raw_confidence": round(max(0.0, min(1.0, raw)), 4),
                "label": int(label),
                "reviewed_at": now,
            }
        )
        added += 1
    payload["examples"] = kept
    if persist:
        save_calibration_store(payload)
    logger.info("Recorded %s calibration label(s) for document %s", added, ticket or "unknown")
    return payload


def calibrate_field_score(
    field: str,
    raw_confidence: float,
    *,
    extracted: Optional[Dict[str, Any]] = None,
    field_candidates: Optional[Dict[str, Any]] = None,
    joint_decode: Optional[Dict[str, Any]] = None,
    exclude_document_id: Optional[Any] = None,
    store: Optional[Dict[str, Any]] = None,
    empty: bool = False,
    reviewed_gold: bool = False,
) -> Dict[str, Any]:
    """Map one field's raw confidence to a calibrated probability and auto-post decision."""
    raw = max(0.0, min(1.0, float(raw_confidence or 0.0)))
    threshold = field_auto_post_threshold(field)
    features = prediction_features(
        field,
        raw_confidence=raw,
        extracted=extracted,
        field_candidates=field_candidates,
        joint_decode=joint_decode,
    )
    payload = {
        "field": field,
        "raw_confidence": round(raw, 4),
        "calibrated_confidence": round(raw, 4),
        "calibration_method": "heuristic_fallback",
        "calibration_status": STATUS_FALLBACK,
        "calibration_available": False,
        "sample_count": 0,
        "positive_count": 0,
        "negative_count": 0,
        "threshold": threshold,
        "auto_post": False,
        "features": features,
    }
    if empty:
        payload["calibrated_confidence"] = 0.0
        payload["calibration_method"] = "empty"
        payload["calibration_status"] = STATUS_EMPTY
        payload["auto_post"] = False
        return payload
    if reviewed_gold:
        payload["calibrated_confidence"] = 1.0
        payload["raw_confidence"] = 1.0
        payload["calibration_method"] = "reviewed_gold"
        payload["calibration_status"] = STATUS_REVIEWED
        payload["auto_post"] = True
        return payload

    source = store if store is not None else load_calibration_store()
    examples = _examples_for_field(field, source, exclude_document_id=exclude_document_id)
    positives = sum(1 for row in examples if int(row.get("label") or 0) == 1)
    negatives = len(examples) - positives
    payload["sample_count"] = len(examples)
    payload["positive_count"] = positives
    payload["negative_count"] = negatives

    if _can_fit(examples):
        points = fit_isotonic(
            [float(row.get("raw_confidence") or 0.0) for row in examples],
            [float(row.get("label") or 0) for row in examples],
        )
        calibrated = predict_isotonic(points, raw)
        payload["calibrated_confidence"] = round(calibrated, 4)
        payload["calibration_method"] = "isotonic"
        payload["calibration_status"] = STATUS_CALIBRATED
        payload["calibration_available"] = True

    payload["auto_post"] = bool(payload["calibrated_confidence"] >= threshold)
    return payload


def calibrate_extracted_fields(
    extracted: Optional[Dict[str, Any]],
    *,
    field_candidates: Optional[Dict[str, Any]] = None,
    joint_decode: Optional[Dict[str, Any]] = None,
    exclude_document_id: Optional[Any] = None,
    store: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = extracted if isinstance(extracted, dict) else {}
    raw_confs = data.get("field_confidence") if isinstance(data.get("field_confidence"), dict) else {}
    reviewed = bool(data.get("manually_corrected") or data.get("reviewed"))
    fields: Dict[str, Any] = {}
    for field in ALL_SCHEMA_FIELDS:
        raw = raw_confs.get(field)
        try:
            raw_f = float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            raw_f = 0.0
        empty = not _has_value(data.get(field)) or raw_f <= 0.0
        fields[field] = calibrate_field_score(
            field,
            raw_f,
            extracted=data,
            field_candidates=field_candidates,
            joint_decode=joint_decode,
            exclude_document_id=exclude_document_id,
            store=store,
            empty=empty and not reviewed,
            reviewed_gold=reviewed and not empty,
        )
    return {
        "fields": fields,
        "feature": "raw_confidence",
        "algorithm": "isotonic_pava",
        "min_samples": _min_samples(),
        "min_positives": _min_positives(),
        "min_negatives": _min_negatives(),
    }


def calibration_review_warnings(payload: Optional[Dict[str, Any]]) -> List[str]:
    """REVIEW warnings only for fields that were actually isotonic-calibrated below threshold."""
    warnings: List[str] = []
    fields = (payload or {}).get("fields") if isinstance(payload, dict) else None
    if not isinstance(fields, dict):
        return warnings
    for field, row in fields.items():
        if not isinstance(row, dict):
            continue
        if row.get("calibration_status") != STATUS_CALIBRATED:
            continue
        if row.get("auto_post"):
            continue
        warnings.append(
            f"Low calibrated confidence for {field} "
            f"({float(row.get('calibrated_confidence') or 0.0):.2f} < {float(row.get('threshold') or 0.0):.2f})"
        )
    return warnings


def attach_field_calibration(
    extracted: Optional[Dict[str, Any]],
    raw_ocr: Optional[Dict[str, Any]] = None,
    *,
    exclude_document_id: Optional[Any] = None,
    store: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Write calibration metadata beside existing extraction results. Does not change field values."""
    meta = raw_ocr if isinstance(raw_ocr, dict) else {}
    payload = calibrate_extracted_fields(
        extracted,
        field_candidates=meta.get("field_candidates"),
        joint_decode=meta.get("joint_decode"),
        exclude_document_id=exclude_document_id,
        store=store,
    )
    if isinstance(extracted, dict):
        extracted["field_calibration"] = payload
    if isinstance(raw_ocr, dict):
        raw_ocr["field_calibration"] = payload
    return payload


def apply_calibration_to_status(
    status: Any,
    warnings: Optional[Iterable[str]],
    calibration: Optional[Dict[str, Any]],
) -> Tuple[Any, List[str]]:
    """Append calibrated-below-threshold warnings. Only those extra warnings can force REVIEW."""
    from app.db.models import DocumentStatus

    merged = list(warnings or [])
    extra = calibration_review_warnings(calibration)
    for item in extra:
        if item not in merged:
            merged.append(item)
    if extra and status == DocumentStatus.COMPLETED:
        status = DocumentStatus.REVIEW
    return status, merged
