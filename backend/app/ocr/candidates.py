"""Top-K entity candidates from cheap OCR, gazetteer, aliases, and historical priors."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.config import settings
from app.ocr.matching import (
    _collapse,
    _is_harvestable_name,
    is_letterhead_as_party,
    is_weak_entity_stub,
    load_matching_memory,
    name_variants,
    resolve_alias,
    similarity,
)
from app.ocr.normalizer import is_form_header_value, looks_like_ocr_junk
from app.ocr.priors import (
    associated_pair,
    carriers_for,
    destinations_for,
    drivers_for,
    load_priors,
)

CANDIDATE_FIELDS = (
    "carrier",
    "consignor",
    "consignee",
    "driver_name",
    "origin",
    "destination",
)

# Below 1-best gazetteer threshold (0.86) so multiple near-misses can surface.
CANDIDATE_MIN_FUZZY = 0.70
# Ranking only: prior cannot overturn a fuzzy gap larger than this.
PRIOR_RANK_BONUS = 0.05


def _top_k() -> int:
    try:
        return max(1, int(getattr(settings, "CANDIDATE_TOP_K", 5) or 5))
    except (TypeError, ValueError):
        return 5


def _usable_query(field: str, value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text or is_form_header_value(text) or looks_like_ocr_junk(text):
        return None
    if field == "driver_name" and text.isdigit():
        return None
    if not _is_harvestable_name(field, text):
        return None
    return text


def _best_fuzzy(query: Optional[str], candidate: str) -> float:
    if not query:
        return 0.0
    best = 0.0
    cand_c = _collapse(candidate)
    for variant in name_variants(query):
        best = max(best, similarity(variant, candidate))
        var_c = _collapse(variant)
        if var_c and cand_c:
            shorter, longer = (var_c, cand_c) if len(var_c) <= len(cand_c) else (cand_c, var_c)
            if len(shorter) >= 6 and longer.startswith(shorter):
                best = max(best, 0.88)
    return round(best, 4)


def _text_mentions(raw_text: str, candidate: str) -> bool:
    blob = _collapse(raw_text or "")
    token = _collapse(candidate)
    return bool(blob and token and token in blob)


def _prior_rows_for_field(
    field: str,
    raw_dict: Dict[str, Any],
    priors: Dict[str, Any],
) -> List[Tuple[str, int, float]]:
    consignor = raw_dict.get("consignor")
    consignee = raw_dict.get("consignee")
    carrier = raw_dict.get("carrier")
    origin = raw_dict.get("origin")
    if field == "carrier":
        if consignor and consignee:
            return carriers_for(consignor, consignee, priors=priors)
        if consignor:
            return associated_pair("consignor→carrier", consignor, priors=priors)
        if consignee:
            return associated_pair("consignee→carrier", consignee, priors=priors)
        return []
    if field == "driver_name":
        if consignor and carrier:
            return drivers_for(consignor, carrier, priors=priors)
        if carrier:
            return associated_pair("carrier→driver", carrier, priors=priors)
        return []
    if field == "destination" and origin:
        return destinations_for(origin, priors=priors)
    if field == "consignee" and consignor:
        return associated_pair("consignor→consignee", consignor, priors=priors)
    return []


def _prior_index(
    field: str,
    raw_dict: Dict[str, Any],
    priors: Dict[str, Any],
) -> Dict[str, Tuple[int, float]]:
    out: Dict[str, Tuple[int, float]] = {}
    for label, count, prob in _prior_rows_for_field(field, raw_dict, priors):
        out[_collapse(label)] = (int(count), float(prob))
    return out


def _has_prior_context(field: str, raw_dict: Dict[str, Any]) -> bool:
    if field == "carrier":
        return bool(raw_dict.get("consignor") or raw_dict.get("consignee"))
    if field == "driver_name":
        return bool(raw_dict.get("carrier") or raw_dict.get("consignor"))
    if field == "destination":
        return bool(raw_dict.get("origin"))
    if field == "consignee":
        return bool(raw_dict.get("consignor"))
    return False


def _inject_priors_enabled() -> bool:
    return bool(getattr(settings, "PRIOR_INJECT_WHEN_OCR_WEAK", True))


def _inject_min_count() -> int:
    try:
        return max(1, int(getattr(settings, "PRIOR_INJECT_MIN_COUNT", 1) or 1))
    except (TypeError, ValueError):
        return 1


def _inject_max() -> int:
    try:
        return max(1, int(getattr(settings, "PRIOR_INJECT_MAX", 5) or 5))
    except (TypeError, ValueError):
        return 5


def _new_slot(value: str) -> Dict[str, Any]:
    return {
        "value": value,
        "source": "",
        "sources": [],
        "fuzzy_score": 0.0,
        "prior_count": 0,
        "prior_probability": 0.0,
        "final_candidate_score": 0.0,
        "score": 0.0,
    }


def _add_source(slot: Dict[str, Any], source: str) -> None:
    if source and source not in slot["sources"]:
        slot["sources"].append(source)


def generate_field_candidates(
    raw_dict: Optional[Dict[str, Any]],
    *,
    context_fields: Optional[Dict[str, Any]] = None,
    priors: Optional[Dict[str, Any]] = None,
    gazetteer: Optional[Dict[str, List[str]]] = None,
    memory: Optional[Dict[str, Any]] = None,
    raw_text: str = "",
    top_k: Optional[int] = None,
    min_fuzzy: float = CANDIDATE_MIN_FUZZY,
) -> Dict[str, List[Dict[str, Any]]]:
    """Return top-K candidates per entity field. Does not change 1-best matching.

    When OCR for a field is empty/junk, route-conditioned priors may be injected
    as candidates (never global unigrams). ``context_fields`` should be the
    matched 1-best values used only for prior lookup.
    """
    data = dict(raw_dict or {})
    context = dict(context_fields) if isinstance(context_fields, dict) else data
    working = dict(context)
    mem = memory if memory is not None else load_matching_memory()
    gaz = gazetteer if gazetteer is not None else mem.get("names") or {}
    prior_store = priors if priors is not None else load_priors()
    aliases = mem.get("aliases") or {}
    limit = max(1, int(top_k if top_k is not None else _top_k()))
    out: Dict[str, List[Dict[str, Any]]] = {}

    for field in CANDIDATE_FIELDS:
        query = _usable_query(field, data.get(field))
        names = list(gaz.get(field) or [])
        pooled: Dict[str, Dict[str, Any]] = {}

        carrier = working.get("carrier") or context.get("carrier")

        def take(value: str, fuzzy: float, source: str) -> None:
            label = str(value or "").strip()
            if not label or not _is_harvestable_name(field, label):
                return
            if is_letterhead_as_party(field, label, carrier=carrier, gazetteer=gaz):
                return
            key = _collapse(label)
            if not key:
                return
            slot = pooled.get(key)
            if slot is None:
                slot = _new_slot(label)
                pooled[key] = slot
            if fuzzy > slot["fuzzy_score"]:
                slot["fuzzy_score"] = round(float(fuzzy), 4)
                slot["value"] = label
            elif abs(fuzzy - slot["fuzzy_score"]) < 1e-9 and source == "gazetteer":
                slot["value"] = label
            _add_source(slot, source)

        if query:
            take(query, 1.0, "ocr")
            alias = resolve_alias(field, query, aliases)
            if alias:
                take(alias, max(_best_fuzzy(query, alias), 0.99), "alias")
            for name in names:
                fuzzy = _best_fuzzy(query, name)
                if fuzzy >= min_fuzzy:
                    take(name, fuzzy, "gazetteer")

        if raw_text:
            for name in names:
                if _text_mentions(raw_text, name):
                    fuzzy = _best_fuzzy(query, name) if query else 0.80
                    if fuzzy >= min_fuzzy or not query:
                        take(name, max(fuzzy, 0.80 if not query else fuzzy), "ocr_text")

        prior_map = _prior_index(field, working, prior_store)
        route_context = _has_prior_context(field, working) and bool(prior_map)
        if (not query or is_weak_entity_stub(field, data.get(field))) and route_context and _inject_priors_enabled():
            injected = 0
            min_count = _inject_min_count()
            for label, count, _prob in _prior_rows_for_field(field, working, prior_store):
                if int(count) < min_count:
                    continue
                take(label, 0.0, "prior")
                injected += 1
                if injected >= min(limit, _inject_max()):
                    break

        ranked: List[Dict[str, Any]] = []
        for slot in pooled.values():
            key = _collapse(slot["value"])
            if key in prior_map:
                count, prob = prior_map[key]
                slot["prior_count"] = count
                slot["prior_probability"] = round(prob, 4)
                _add_source(slot, "prior")
            fuzzy = float(slot["fuzzy_score"] or 0.0)
            if route_context and slot["prior_count"] == 0 and fuzzy < 0.86 and "ocr" not in slot["sources"] and "alias" not in slot["sources"]:
                continue
            slot["final_candidate_score"] = round(fuzzy + PRIOR_RANK_BONUS * float(slot["prior_probability"] or 0.0), 4)
            slot["score"] = slot["final_candidate_score"]
            slot["source"] = slot["sources"][0] if slot["sources"] else "gazetteer"
            ranked.append(slot)

        ranked.sort(
            key=lambda item: (
                -float(item["final_candidate_score"]),
                -float(item["prior_probability"] or 0.0),
                -int(item["prior_count"] or 0),
                str(item["value"]).lower(),
            )
        )
        out[field] = ranked[:limit]
        if out[field] and (
            not _usable_query(field, working.get(field)) or is_weak_entity_stub(field, working.get(field))
        ):
            pick = out[field][0]
            for row in out[field]:
                if not is_weak_entity_stub(field, row.get("value")):
                    pick = row
                    break
            working[field] = pick["value"]

    return out
