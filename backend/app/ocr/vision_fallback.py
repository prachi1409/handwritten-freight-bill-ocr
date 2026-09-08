"""Field-aware Groq Vision fallback for uncertain extraction results."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.ocr.calibration import STATUS_CALIBRATED, field_auto_post_threshold
from app.ocr.decode import DECODE_FIELDS
from app.ocr.matching import _collapse, is_gazetteer_near_miss, is_letterhead_as_party, is_weak_entity_stub
from app.ocr.normalizer import is_form_header_value, looks_like_ocr_junk

logger = logging.getLogger(__name__)

REASON_MISSING = "missing_field"
REASON_LOW_CONF = "low_confidence"
REASON_WEAK_OCR = "weak_ocr_stub"
REASON_AMBIGUOUS = "candidate_ambiguity"
REASON_JOINT = "joint_decode_uncertain"
REASON_CONSISTENCY = "consistency_conflict"

RESCUE_FIELDS = (
    "bill_number",
    "bill_date",
    "consignor",
    "consignee",
    "origin",
    "destination",
    "freight_amount",
    "total_amount",
    "carrier",
    "driver_name",
    "weight",
    "commodity_description",
)

# Asked on the same Groq call when rescue already fired. Does not start a new call.
SAME_CALL_FIELDS = (
    "bill_date",
    "commodity_description",
    "quantity",
    "vehicle_number",
    "pickup_time",
    "delivery_time",
    "line_items",
)

CONSISTENCY_TRIGGER_CODES = frozenset(
    {
        "HISTORICAL_RELATIONSHIP_CONFLICT",
        "CONSIGNOR_EQUALS_CONSIGNEE",
    }
)


def _cfg_enabled() -> bool:
    return bool(getattr(settings, "GROQ_VISION_FALLBACK_ENABLED", True))


def _max_fields() -> int:
    try:
        return max(0, int(getattr(settings, "GROQ_VISION_FALLBACK_MAX_FIELDS", 8) or 8))
    except (TypeError, ValueError):
        return 6


def _min_confidence() -> float:
    try:
        return min(1.0, max(0.0, float(getattr(settings, "GROQ_VISION_FALLBACK_MIN_CONFIDENCE", 0.80) or 0.80)))
    except (TypeError, ValueError):
        return 0.80


def _ambiguity_gap() -> float:
    try:
        return min(1.0, max(0.0, float(getattr(settings, "GROQ_VISION_AMBIGUITY_MAX_GAP", 0.08) or 0.08)))
    except (TypeError, ValueError):
        return 0.08


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return _line_item_count(value) > 0
    text = str(value).strip()
    return bool(text) and text.lower() not in {"none", "null", "n/a", "unknown", "—"}


def _line_item_count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    count = 0
    for row in value:
        if not isinstance(row, dict):
            continue
        if any(_has_value(val) for key, val in row.items() if key != "item_no"):
            count += 1
    return count


def _usable_line_items(value: Any) -> bool:
    return _line_item_count(value) >= 2


def _times_from_line_items(items: Any) -> Dict[str, str]:
    rows = [row for row in (items or []) if isinstance(row, dict)]
    if not rows:
        return {}
    first, last = rows[0], rows[-1]
    out: Dict[str, str] = {}
    pickup = first.get("load_arrive") or first.get("pickup_time")
    delivery = (
        last.get("unload_depart")
        or last.get("unload_arrive")
        or last.get("load_depart")
        or last.get("delivery_time")
    )
    if _has_value(pickup):
        out["pickup_time"] = str(pickup).strip()
    if _has_value(delivery):
        out["delivery_time"] = str(delivery).strip()
    return out


def _calibration_fields(extracted: Optional[Dict[str, Any]], raw_ocr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    for source in (raw_ocr, extracted):
        block = (source or {}).get("field_calibration") if isinstance(source, dict) else None
        if isinstance(block, dict) and isinstance(block.get("fields"), dict):
            return block["fields"]
    return {}


def _field_confidence_map(extracted: Optional[Dict[str, Any]], raw_ocr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(extracted, dict) and isinstance(extracted.get("field_confidence"), dict):
        return extracted["field_confidence"]
    if isinstance(raw_ocr, dict) and isinstance(raw_ocr.get("field_confidence"), dict):
        return raw_ocr["field_confidence"]
    return {}


def field_confidence_signal(
    field: str,
    extracted: Optional[Dict[str, Any]],
    raw_ocr: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the confidence used for fallback. Calibrated only when Point 4 actually fitted."""
    row = _calibration_fields(extracted, raw_ocr).get(field) or {}
    heuristic = 0.0
    conf_map = _field_confidence_map(extracted, raw_ocr)
    try:
        heuristic = float(conf_map.get(field) if conf_map.get(field) is not None else row.get("raw_confidence") or 0.0)
    except (TypeError, ValueError):
        heuristic = 0.0
    calibrated_available = bool(row.get("calibration_available") and row.get("calibration_status") == STATUS_CALIBRATED)
    try:
        calibrated = float(row.get("calibrated_confidence") or heuristic)
    except (TypeError, ValueError):
        calibrated = heuristic
    threshold = field_auto_post_threshold(field)
    try:
        if row.get("threshold") is not None:
            threshold = float(row["threshold"])
    except (TypeError, ValueError):
        pass
    used = calibrated if calibrated_available else heuristic
    value = (extracted or {}).get(field)
    cand_vals = [row.get("value") for row in _candidate_rows(raw_ocr, field)]
    near_miss = is_gazetteer_near_miss(field, value, cand_vals if cand_vals else None)
    strong = bool(
        _has_value(value)
        and used >= max(threshold, _min_confidence())
        and not is_weak_entity_stub(field, value)
        and not is_letterhead_as_party(field, value, carrier=(extracted or {}).get("carrier"))
        and not looks_like_ocr_junk(value)
        and not near_miss
    )
    return {
        "heuristic": heuristic,
        "calibrated": calibrated,
        "calibrated_available": calibrated_available,
        "used": used,
        "threshold": threshold,
        "strong": strong,
    }


def _candidate_rows(raw_ocr: Optional[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    rows = ((raw_ocr or {}).get("field_candidates") or {}).get(field) or []
    return [row for row in rows if isinstance(row, dict) and _has_value(row.get("value"))]


def _candidate_score(row: Dict[str, Any]) -> float:
    for key in ("final_candidate_score", "score", "fuzzy_score"):
        try:
            if row.get(key) is not None:
                return float(row[key])
        except (TypeError, ValueError):
            continue
    return 0.0


def _joint_relations_for_field(raw_ocr: Optional[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    joint = (raw_ocr or {}).get("joint_decode") or {}
    relations = joint.get("relations_used") if isinstance(joint, dict) else None
    if not isinstance(relations, list):
        return []
    aliases = {field, field.replace("_name", "")}
    hits = []
    for row in relations:
        if not isinstance(row, dict):
            continue
        relation = str(row.get("relation") or "")
        target = relation.split("→")[-1] if "→" in relation else ""
        if field in relation or target in aliases or any(name in relation for name in aliases):
            hits.append(row)
    return hits


def _consistency_hits(raw_ocr: Optional[Dict[str, Any]], extracted: Optional[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    payload = None
    for source in (raw_ocr, extracted):
        if isinstance(source, dict) and isinstance(source.get("consistency_checks"), dict):
            payload = source["consistency_checks"]
            break
    checks = (payload or {}).get("checks") if isinstance(payload, dict) else None
    if not isinstance(checks, list):
        return []
    hits = []
    for row in checks:
        if not isinstance(row, dict):
            continue
        if row.get("code") not in CONSISTENCY_TRIGGER_CODES:
            continue
        involved = row.get("fields_involved") or []
        if field in involved:
            hits.append(row)
    return hits


def select_rescue_fields(
    extracted: Optional[Dict[str, Any]],
    raw_ocr: Optional[Dict[str, Any]] = None,
    *,
    max_fields: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Pick uncertain fields for VLM rescue. Does not call Groq."""
    data = extracted if isinstance(extracted, dict) else {}
    limit = _max_fields() if max_fields is None else max(0, int(max_fields))
    ranked: List[Tuple[int, Dict[str, Any]]] = []
    for field in RESCUE_FIELDS:
        reasons: List[str] = []
        signal = field_confidence_signal(field, data, raw_ocr)
        empty = not _has_value(data.get(field))
        if empty:
            reasons.append(REASON_MISSING)
        elif (
            is_weak_entity_stub(field, data.get(field))
            or looks_like_ocr_junk(data.get(field))
            or is_gazetteer_near_miss(
                field,
                data.get(field),
                [row.get("value") for row in _candidate_rows(raw_ocr, field)] or None,
            )
        ):
            reasons.append(REASON_WEAK_OCR)
        if signal["calibrated_available"]:
            if signal["used"] < max(float(signal["threshold"]), _min_confidence()):
                reasons.append(REASON_LOW_CONF)
        elif empty or signal["used"] < _min_confidence():
            reasons.append(REASON_LOW_CONF)

        cands = _candidate_rows(raw_ocr, field)
        if len(cands) >= 2:
            gap = abs(_candidate_score(cands[0]) - _candidate_score(cands[1]))
            if gap <= _ambiguity_gap() and _candidate_score(cands[0]) >= 0.70:
                reasons.append(REASON_AMBIGUOUS)

        if field in DECODE_FIELDS:
            relations = _joint_relations_for_field(raw_ocr, field)
            joint = (raw_ocr or {}).get("joint_decode") if isinstance(raw_ocr, dict) else None
            selected = (joint or {}).get("selected") if isinstance(joint, dict) else None
            joint_value = selected.get(field) if isinstance(selected, dict) else None
            if (empty or not signal["strong"]) and not _has_value(joint_value) and not relations:
                reasons.append(REASON_JOINT)

        if _consistency_hits(raw_ocr, data, field):
            reasons.append(REASON_CONSISTENCY)

        reasons = list(dict.fromkeys(reasons))
        if not reasons:
            continue
        priority = 0
        if REASON_MISSING in reasons:
            priority += 8
        if REASON_LOW_CONF in reasons or REASON_WEAK_OCR in reasons:
            priority += 4
        if REASON_AMBIGUOUS in reasons:
            priority += 2
        if REASON_CONSISTENCY in reasons:
            priority += 2
        if REASON_JOINT in reasons:
            priority += 1
        ranked.append(
            (
                -priority,
                {
                    "field": field,
                    "reasons": reasons,
                    "current_value": data.get(field),
                    "confidence": signal,
                },
            )
        )
    ranked.sort(key=lambda item: (item[0], RESCUE_FIELDS.index(item[1]["field"]) if item[1]["field"] in RESCUE_FIELDS else 99))
    return [row for _prio, row in ranked[:limit]]


def augment_same_call_fields(
    plan: Sequence[Dict[str, Any]],
    extracted: Optional[Dict[str, Any]],
    raw_ocr: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """If Groq is already running, also ask it to read date and load rows from the image."""
    if not plan:
        return []
    data = extracted if isinstance(extracted, dict) else {}
    have = {item.get("field") for item in plan}
    extra: List[Dict[str, Any]] = []
    for field in SAME_CALL_FIELDS:
        if field in have:
            continue
        current = data.get(field)
        if field == "line_items":
            if _usable_line_items(current):
                continue
        elif _has_value(current):
            continue
        signal = field_confidence_signal(field, data, raw_ocr) if field != "line_items" else {
            "heuristic": 0.0,
            "calibrated": 0.0,
            "calibrated_available": False,
            "used": 0.0,
            "threshold": 0.0,
            "strong": False,
        }
        extra.append(
            {
                "field": field,
                "reasons": [REASON_MISSING],
                "current_value": current,
                "confidence": signal,
            }
        )
    return list(plan) + extra


def build_fallback_user_text(
    rescue_plan: Sequence[Dict[str, Any]],
    extracted: Optional[Dict[str, Any]],
    raw_ocr: Optional[Dict[str, Any]] = None,
) -> str:
    """Candidate/history context for Groq. Evidence only — not an instruction to pick a list item."""
    lines = [
        "Extract freight-bill fields from this scanned page.",
        "Focus especially on these uncertain fields: "
        + ", ".join(item["field"] for item in rescue_plan if item.get("field")),
        "The candidate lists below are evidence only. Read the image.",
        "You may return a value that is not in the candidate list if the image clearly shows it.",
        "Read every handwritten load row (tag, weight, load in/out, unload in/out) into line_items.",
        "MO / DAY / YR boxes are bill_date (YYYY-MM-DD). JOB DAY is not the date.",
        "Return a single JSON object only. No markdown, no explanation.",
        "",
    ]
    for item in rescue_plan:
        field = item.get("field")
        if not field:
            continue
        current = (extracted or {}).get(field)
        lines.append(f"Field: {field}")
        lines.append(f"Current deterministic prediction: {current if _has_value(current) else '(empty)'}")
        lines.append(f"Why uncertain: {', '.join(item.get('reasons') or [])}")
        cands = _candidate_rows(raw_ocr, field)
        if cands:
            lines.append("Top candidates:")
            for index, row in enumerate(cands[:5], start=1):
                extras = []
                if row.get("fuzzy_score") is not None:
                    extras.append(f"fuzzy {row['fuzzy_score']}")
                if int(row.get("prior_count") or 0) > 0:
                    extras.append(f"prior {row['prior_count']}")
                sources = ",".join(row.get("sources") or ([row.get("source")] if row.get("source") else []))
                extra = f" ({'; '.join(extras)})" if extras else ""
                lines.append(f"  {index}. {row.get('value')} [{sources}]{extra}")
        hist = [h for h in _consistency_hits(raw_ocr, extracted, field) if h.get("evidence")]
        if hist:
            ev = hist[0].get("evidence") or {}
            if ev.get("usual_value"):
                lines.append(
                    f"Historical evidence: usual value {ev.get('usual_value')} "
                    f"({ev.get('usual_count') or 0} tickets)."
                )
        rels = _joint_relations_for_field(raw_ocr, field)
        if rels:
            top = rels[0]
            lines.append(f"Joint-decode relation: {top.get('relation')} → {top.get('target')}")
        lines.append("")
    return "\n".join(lines).strip()


def _bbox_from_meta(raw_ocr: Optional[Dict[str, Any]], field: str) -> Optional[List[float]]:
    meta = ((raw_ocr or {}).get("field_metadata") or {}).get(field) or {}
    loc = meta.get("source_location") if isinstance(meta, dict) else None
    if isinstance(loc, (list, tuple)) and len(loc) >= 4:
        return [float(v) for v in loc[:4]]
    region = (((raw_ocr or {}).get("layout_classification") or {}).get("field_regions") or {}).get(field) or {}
    bbox = region.get("bbox") if isinstance(region, dict) else None
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return [float(v) for v in bbox[:4]]
    return None


def crop_rescue_images(
    page_images: Optional[Sequence[Any]],
    raw_ocr: Optional[Dict[str, Any]],
    rescue_plan: Sequence[Dict[str, Any]],
    *,
    padding: int = 80,
    max_crops: int = 1,
) -> List[Any]:
    """Full page first, then at most one crop. Two images stay under Groq's 7000 ITPM."""
    pages = [img for img in list(page_images or []) if img is not None]
    if not pages:
        return []
    page = pages[0]
    if not hasattr(page, "size") or not hasattr(page, "crop"):
        return pages
    width, height = page.size
    crops: List[Any] = []
    seen: List[Tuple[int, int, int, int]] = []
    fields: List[str] = []
    for item in rescue_plan:
        field = item.get("field")
        if field and field not in fields:
            fields.append(field)
    if "line_items" in fields:
        for extra in ("commodity_description", "weight", "quantity"):
            if extra not in fields:
                fields.append(extra)
    for field in fields:
        if len(crops) >= max_crops:
            break
        bbox = _bbox_from_meta(raw_ocr, field)
        if not bbox:
            continue
        min_x, min_y, max_x, max_y = bbox
        left = max(0, int(min_x - padding))
        top = max(0, int(min_y - padding))
        right = min(width, int(max_x + padding))
        bottom = min(height, int(max_y + padding))
        if right - left < 40 or bottom - top < 40:
            continue
        key = (left, top, right, bottom)
        if key in seen:
            continue
        seen.append(key)
        crops.append(page.crop(key))
    return [page] + crops[:max_crops]


def _values_agree(left: Any, right: Any) -> bool:
    return _collapse(str(left or "")) == _collapse(str(right or "")) and bool(_collapse(str(left or "")))


def _usable_groq_value(field: str, value: Any) -> bool:
    if not _has_value(value):
        return False
    text = str(value).strip()
    if is_form_header_value(text) or looks_like_ocr_junk(text):
        return False
    return True


def merge_fallback_fields(
    deterministic: Optional[Dict[str, Any]],
    groq_fields: Optional[Dict[str, Any]],
    rescue_plan: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge Groq values only for rescued fields. Never silent-overwrite a strong deterministic value."""
    det = deterministic if isinstance(deterministic, dict) else {}
    groq = groq_fields if isinstance(groq_fields, dict) else {}
    accepted: Dict[str, Any] = {}
    decisions: List[Dict[str, Any]] = []
    for item in rescue_plan:
        field = item.get("field")
        if not field:
            continue
        previous = det.get(field)
        groq_value = groq.get(field)
        reasons = list(item.get("reasons") or [])
        signal = item.get("confidence") or {}
        strong = bool(signal.get("strong"))
        if field == "line_items":
            groq_value = groq.get("line_items")
            previous = det.get("line_items")
            usable = _usable_line_items(groq_value)
            prev_n = _line_item_count(previous)
            groq_n = _line_item_count(groq_value)
            action = "keep_deterministic"
            if usable and groq_n > prev_n:
                action = "accept_groq"
                accepted["line_items"] = groq_value
                for key, val in _times_from_line_items(groq_value).items():
                    if not _has_value(det.get(key)) and key not in accepted:
                        accepted[key] = val
            decisions.append(
                {
                    "field": "line_items",
                    "source": "groq_vision_fallback" if action == "accept_groq" else "deterministic",
                    "reason": reasons,
                    "previous_value": prev_n,
                    "groq_value": groq_n if usable else None,
                    "agreed_with_deterministic": prev_n == groq_n and groq_n > 0,
                    "action": action,
                }
            )
            continue
        weak = (
            (not _has_value(previous))
            or (REASON_LOW_CONF in reasons)
            or (REASON_MISSING in reasons)
            or (REASON_WEAK_OCR in reasons)
            or is_weak_entity_stub(field, previous)
            or is_letterhead_as_party(field, previous, carrier=det.get("carrier"))
            or looks_like_ocr_junk(previous)
            or is_gazetteer_near_miss(field, previous)
        )
        usable = _usable_groq_value(field, groq_value)
        agreed = bool(usable and _has_value(previous) and _values_agree(previous, groq_value))
        action = "keep_deterministic"
        if not usable:
            action = "keep_deterministic"
        elif not _has_value(previous):
            action = "accept_groq"
        elif agreed:
            action = "keep_deterministic"
        elif weak and not strong:
            action = "accept_groq"
        elif strong and not agreed:
            action = "keep_deterministic_disagreement"
        else:
            # Ambiguity / consistency on a mid-strength value: Groq may rescue.
            if REASON_AMBIGUOUS in reasons or REASON_CONSISTENCY in reasons:
                if not strong:
                    action = "accept_groq"
                else:
                    action = "keep_deterministic_disagreement"
            else:
                action = "keep_deterministic_disagreement"

        if action == "accept_groq":
            accepted[field] = groq_value
        decisions.append(
            {
                "field": field,
                "source": "groq_vision_fallback" if action == "accept_groq" else "deterministic",
                "reason": reasons,
                "previous_value": previous,
                "groq_value": groq_value if usable else None,
                "agreed_with_deterministic": agreed,
                "action": action,
            }
        )
    return {"accepted": accepted, "decisions": decisions}


def empty_fallback_report(*, called: bool = False, status: str = "skipped") -> Dict[str, Any]:
    return {
        "groq_fallback_called": called,
        "groq_fallback_fields": [],
        "groq_fallback_call_count": 1 if called else 0,
        "status": status,
        "decisions": [],
        "error": None,
    }


def run_vision_fallback(
    extracted: Optional[Dict[str, Any]],
    raw_ocr: Optional[Dict[str, Any]],
    page_images: Optional[Sequence[Any]] = None,
    *,
    deterministic: Optional[Dict[str, Any]] = None,
    vision_fn: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Decide, call Groq Vision for uncertain fields only, and merge carefully."""
    report = empty_fallback_report(called=False, status="disabled" if not _cfg_enabled() else "not_needed")
    if not _cfg_enabled():
        return {**report, "accepted": {}, "plan": []}
    plan = augment_same_call_fields(select_rescue_fields(extracted, raw_ocr), extracted, raw_ocr)
    report["plan"] = plan
    report["groq_fallback_fields"] = [item["field"] for item in plan]
    if not plan:
        return {**report, "accepted": {}, "status": "not_needed"}

    from app.ocr.groq_extractor import extract_fields_with_groq_vision

    caller = vision_fn or extract_fields_with_groq_vision
    context = build_fallback_user_text(plan, extracted, raw_ocr)
    vision_images = crop_rescue_images(page_images, raw_ocr, plan)[:2]
    if len(vision_images) > 1:
        context = (
            "First image is the full page. Later images are zoomed crops of uncertain fields.\n"
            + context
        )
    groq_fields = None
    error = None
    try:
        groq_fields = caller(
            vision_images or page_images,
            focus_fields=[item["field"] for item in plan],
            field_context=context,
        )
    except Exception as err:
        error = f"{type(err).__name__}: {err}"
        logger.warning("Groq vision fallback failed; keeping deterministic extraction: %s", err)
        groq_fields = None

    if groq_fields is not None and not isinstance(groq_fields, dict):
        error = "groq_vision_malformed_response"
        groq_fields = None
    if groq_fields is None and error is None:
        error = "groq_vision_returned_empty"
    merged = merge_fallback_fields(deterministic if deterministic is not None else extracted, groq_fields, plan)
    report.update(
        {
            "groq_fallback_called": True,
            "groq_fallback_call_count": 1,
            "status": "error" if error else "completed",
            "error": error,
            "accepted": merged["accepted"],
            "decisions": merged["decisions"],
            "focus_context": context,
        }
    )
    return report


def apply_fallback_metadata(raw_ocr: Optional[Dict[str, Any]], report: Optional[Dict[str, Any]]) -> None:
    """Annotate ocr_metadata. Does not rewrite Point 2/3 algorithms."""
    if not isinstance(raw_ocr, dict) or not isinstance(report, dict):
        return
    raw_ocr["groq_fallback"] = {
        "groq_fallback_called": report.get("groq_fallback_called"),
        "groq_fallback_fields": list(report.get("groq_fallback_fields") or []),
        "groq_fallback_call_count": report.get("groq_fallback_call_count", 0),
        "status": report.get("status"),
        "error": report.get("error"),
        "decisions": report.get("decisions") or [],
    }
    accepted = report.get("accepted") or {}
    joint = raw_ocr.get("joint_decode")
    if accepted and isinstance(joint, dict):
        selected = dict(joint.get("selected") or {})
        for field, value in accepted.items():
            selected[field] = value
        joint["selected"] = selected
        joint["groq_rescued"] = list(accepted.keys())
        raw_ocr["joint_decode"] = joint


def apply_accepted_fallback(raw_dict: Optional[Dict[str, Any]], report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Copy accepted Groq rescues onto the deterministic field dict."""
    updated = dict(raw_dict or {})
    accepted = (report or {}).get("accepted") or {}
    if accepted:
        updated.update(accepted)
    return updated


def fallback_disagreement_warnings(raw_ocr: Optional[Dict[str, Any]]) -> List[str]:
    payload = (raw_ocr or {}).get("groq_fallback") if isinstance(raw_ocr, dict) else None
    warnings: List[str] = []
    for row in (payload or {}).get("decisions") or []:
        if not isinstance(row, dict) or row.get("action") != "keep_deterministic_disagreement":
            continue
        field = row.get("field")
        if not field:
            continue
        warnings.append(
            f"Groq vision disagreement on {field}: "
            f"deterministic={row.get('previous_value')!r} groq={row.get('groq_value')!r}"
        )
    return warnings


def apply_fallback_disagreement_to_status(
    status: Any,
    warnings: Optional[Sequence[str]],
    raw_ocr: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, List[str]]:
    """Keep deterministic values, but send strong disagreements to the existing REVIEW path."""
    merged = list(warnings or [])
    extra = fallback_disagreement_warnings(raw_ocr)
    if not extra:
        return status, merged
    from app.db.models import DocumentStatus

    for item in extra:
        if item not in merged:
            merged.append(item)
    return DocumentStatus.REVIEW, merged
