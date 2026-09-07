"""Bounded multi-hypothesis joint decoder over Point 2 candidate lists."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.ocr.matching import _collapse
from app.ocr.priors import (
    associated_given,
    associated_pair,
    empty_priors,
    load_priors,
)

# Decode field order: parties and places first, then carrier/driver that depend on them.
DECODE_FIELDS = (
    "consignor",
    "consignee",
    "origin",
    "destination",
    "carrier",
    "driver_name",
)

PAIR_CHECKS: Tuple[Tuple[str, str, str], ...] = (
    ("consignor→consignee", "consignor", "consignee"),
    ("consignor→carrier", "consignor", "carrier"),
    ("consignee→carrier", "consignee", "carrier"),
    ("carrier→driver", "carrier", "driver_name"),
    ("origin→destination", "origin", "destination"),
)

# Isolated, tunable weights. Not the Point 2 0.05 ranking bonus.
JOINT_WEIGHTS = {
    "unary_fuzzy": 1.00,
    "unary_prior": 0.15,
    "pair": 0.15,
    "triple": 0.28,
    "full": 0.32,
    "ocr_guard": 0.50,
    "strong_ocr_fuzzy": 0.92,
    "ocr_guard_margin": 0.12,
}

JOINT_FORMULA = (
    "joint = sum_f(W_fuzzy * fuzzy_f + W_unary_prior * prior_p_f) "
    "+ sum_pairs(W_pair * P(right|left)) "
    "+ W_triple * P(carrier|consignor,consignee) "
    "+ W_triple * P(driver|consignor,carrier) "
    "+ W_full * P(carrier|consignor,consignee,origin,destination) "
    "+ W_full * P(driver|consignor,carrier,origin) "
    "- W_ocr_guard * count(fields where strong OCR was skipped)"
)


def _beam_width() -> int:
    try:
        return max(1, int(getattr(settings, "DECODE_BEAM_WIDTH", 8) or 8))
    except (TypeError, ValueError):
        return 8


def _max_per_field() -> int:
    try:
        return max(1, int(getattr(settings, "DECODE_MAX_PER_FIELD", 4) or 4))
    except (TypeError, ValueError):
        return 4


def _norm(value: Any) -> str:
    return _collapse(str(value or ""))


def _lookup_pair(
    relation: str,
    left: Any,
    right: Any,
    priors: Dict[str, Any],
) -> Tuple[int, float]:
    needle = _norm(right)
    if not _norm(left) or not needle:
        return 0, 0.0
    for label, count, prob in associated_pair(relation, left, priors=priors):
        if _norm(label) == needle:
            return int(count), float(prob)
    return 0, 0.0


def _lookup_given(
    relation: str,
    given: Sequence[Any],
    target: Any,
    *,
    family: str,
    priors: Dict[str, Any],
) -> Tuple[int, float]:
    needle = _norm(target)
    if not needle or any(not _norm(part) for part in given):
        return 0, 0.0
    for label, count, prob in associated_given(relation, given, family=family, priors=priors):
        if _norm(label) == needle:
            return int(count), float(prob)
    return 0, 0.0


def score_assignment(
    assignment: Dict[str, Dict[str, Any]],
    *,
    priors: Dict[str, Any],
    field_candidates: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Score one complete (or partial) field assignment. Weights live in JOINT_WEIGHTS."""
    w = JOINT_WEIGHTS
    unary = 0.0
    contributions: Dict[str, Any] = {}
    relations_used: List[Dict[str, Any]] = []

    def chosen(field: str) -> Optional[str]:
        slot = assignment.get(field)
        if not slot:
            return None
        return slot.get("value")

    for field, slot in assignment.items():
        fuzzy = float(slot.get("fuzzy_score") or 0.0)
        prior_p = float(slot.get("prior_probability") or 0.0)
        u_fuzzy = w["unary_fuzzy"] * fuzzy
        u_prior = w["unary_prior"] * prior_p
        unary += u_fuzzy + u_prior
        contributions[field] = {
            "value": slot.get("value"),
            "unary_fuzzy": round(u_fuzzy, 4),
            "unary_prior": round(u_prior, 4),
            "fuzzy_score": round(fuzzy, 4),
            "prior_count": int(slot.get("prior_count") or 0),
            "prior_probability": round(prior_p, 4),
            "sources": list(slot.get("sources") or []),
            "reason": "unary fuzzy + candidate prior probability",
        }

        if field_candidates:
            pool = field_candidates.get(field) or []
            best_fuzzy = max((float(c.get("fuzzy_score") or 0.0) for c in pool), default=0.0)
            if (
                best_fuzzy >= w["strong_ocr_fuzzy"]
                and best_fuzzy - fuzzy > w["ocr_guard_margin"]
            ):
                unary -= w["ocr_guard"]
                contributions[field]["ocr_guard_penalty"] = w["ocr_guard"]
                contributions[field]["reason"] = (
                    "unary scores minus OCR-guard; a much stronger OCR/gazetteer "
                    "candidate exists for this field"
                )

    rel_total = 0.0

    def add_rel(name: str, count: int, prob: float, weight: float, given: List[Any], target: Any) -> None:
        nonlocal rel_total
        if count <= 0 or prob <= 0:
            return
        contrib = weight * prob
        rel_total += contrib
        relations_used.append({
            "relation": name,
            "given": [str(v) for v in given if v],
            "target": str(target),
            "count": count,
            "probability": round(prob, 4),
            "weight": weight,
            "contribution": round(contrib, 4),
        })

    for name, left_f, right_f in PAIR_CHECKS:
        left, right = chosen(left_f), chosen(right_f)
        count, prob = _lookup_pair(name, left, right, priors)
        add_rel(name, count, prob, w["pair"], [left], right)

    c_count, c_prob = _lookup_given(
        "consignor+consignee→carrier",
        (chosen("consignor"), chosen("consignee")),
        chosen("carrier"),
        family="triples",
        priors=priors,
    )
    add_rel(
        "consignor+consignee→carrier",
        c_count,
        c_prob,
        w["triple"],
        [chosen("consignor"), chosen("consignee")],
        chosen("carrier"),
    )
    d_count, d_prob = _lookup_given(
        "consignor+carrier→driver",
        (chosen("consignor"), chosen("carrier")),
        chosen("driver_name"),
        family="triples",
        priors=priors,
    )
    add_rel(
        "consignor+carrier→driver",
        d_count,
        d_prob,
        w["triple"],
        [chosen("consignor"), chosen("carrier")],
        chosen("driver_name"),
    )
    fc_count, fc_prob = _lookup_given(
        "consignor+consignee+origin+destination→carrier",
        (chosen("consignor"), chosen("consignee"), chosen("origin"), chosen("destination")),
        chosen("carrier"),
        family="full",
        priors=priors,
    )
    add_rel(
        "consignor+consignee+origin+destination→carrier",
        fc_count,
        fc_prob,
        w["full"],
        [chosen("consignor"), chosen("consignee"), chosen("origin"), chosen("destination")],
        chosen("carrier"),
    )
    fd_count, fd_prob = _lookup_given(
        "consignor+carrier+origin→driver",
        (chosen("consignor"), chosen("carrier"), chosen("origin")),
        chosen("driver_name"),
        family="full",
        priors=priors,
    )
    add_rel(
        "consignor+carrier+origin→driver",
        fd_count,
        fd_prob,
        w["full"],
        [chosen("consignor"), chosen("carrier"), chosen("origin")],
        chosen("driver_name"),
    )

    joint = round(unary + rel_total, 4)
    return {
        "joint_score": joint,
        "unary_score": round(unary, 4),
        "relation_score": round(rel_total, 4),
        "field_contributions": contributions,
        "relations_used": relations_used,
        "formula": JOINT_FORMULA,
        "weights": dict(w),
    }


def _empty_result() -> Dict[str, Any]:
    return {
        "selected": {},
        "joint_score": 0.0,
        "unary_score": 0.0,
        "relation_score": 0.0,
        "field_contributions": {},
        "relations_used": [],
        "formula": JOINT_FORMULA,
        "weights": dict(JOINT_WEIGHTS),
        "searched": 0,
    }


def decode_joint_assignment(
    field_candidates: Optional[Dict[str, List[Dict[str, Any]]]],
    *,
    priors: Optional[Dict[str, Any]] = None,
    beam_width: Optional[int] = None,
    max_per_field: Optional[int] = None,
) -> Dict[str, Any]:
    """Pick a globally consistent assignment from Point 2 candidates only."""
    pools = field_candidates or {}
    if not isinstance(pools, dict) or not pools:
        return _empty_result()
    store = priors if priors is not None else load_priors()
    if not store:
        store = empty_priors()
    width = max(1, int(beam_width if beam_width is not None else _beam_width()))
    cap = max(1, int(max_per_field if max_per_field is not None else _max_per_field()))

    # Beam of (assignment, score_payload). Re-score fully after each field.
    beam: List[Dict[str, Dict[str, Any]]] = [{}]
    searched = 0

    for field in DECODE_FIELDS:
        raw_opts = [c for c in (pools.get(field) or []) if isinstance(c, dict) and c.get("value")]
        if not raw_opts:
            continue
        options = raw_opts[: min(len(raw_opts), cap)]
        nxt: List[Tuple[float, Dict[str, Dict[str, Any]], Dict[str, Any]]] = []
        for assignment in beam:
            for cand in options:
                probed = dict(assignment)
                probed[field] = cand
                searched += 1
                scored = score_assignment(probed, priors=store, field_candidates=pools)
                nxt.append((scored["joint_score"], probed, scored))
        nxt.sort(key=lambda item: item[0], reverse=True)
        # Keep unique assignments by collapsed values.
        unique: List[Tuple[float, Dict[str, Dict[str, Any]], Dict[str, Any]]] = []
        seen = set()
        for score, probed, payload in nxt:
            key = tuple((f, _norm(probed[f]["value"])) for f in DECODE_FIELDS if f in probed)
            if key in seen:
                continue
            seen.add(key)
            unique.append((score, probed, payload))
            if len(unique) >= width:
                break
        beam = [probed for _score, probed, _payload in unique] or beam

    if not beam or not beam[0]:
        result = _empty_result()
        result["searched"] = searched
        return result

    best = beam[0]
    payload = score_assignment(best, priors=store, field_candidates=pools)
    payload["selected"] = {field: slot.get("value") for field, slot in best.items()}
    payload["searched"] = searched
    return payload
