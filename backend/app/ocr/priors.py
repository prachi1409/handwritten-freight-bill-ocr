"""Historical entity/route co-occurrence priors from reviewed tickets only."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.ocr.matching import _collapse, _is_harvestable_name

logger = logging.getLogger(__name__)

PRIOR_FIELDS = (
    "carrier",
    "consignor",
    "consignee",
    "driver_name",
    "origin",
    "destination",
)

PAIR_RELATIONS: Tuple[Tuple[str, str, str], ...] = (
    ("consignor→consignee", "consignor", "consignee"),
    ("consignor→carrier", "consignor", "carrier"),
    ("consignee→carrier", "consignee", "carrier"),
    ("carrier→driver", "carrier", "driver_name"),
    ("origin→destination", "origin", "destination"),
)

TRIPLE_RELATIONS: Tuple[Tuple[str, Tuple[str, str], str], ...] = (
    ("consignor+consignee→carrier", ("consignor", "consignee"), "carrier"),
    ("consignor+carrier→driver", ("consignor", "carrier"), "driver_name"),
)

FULL_RELATIONS: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    ("consignor+consignee+origin+destination→carrier", ("consignor", "consignee", "origin", "destination"), "carrier"),
    ("consignor+carrier+origin→driver", ("consignor", "carrier", "origin"), "driver_name"),
)

_priors_cache: Optional[Dict[str, Any]] = None


def _runtime_path() -> Path:
    storage = Path(getattr(settings, "STORAGE_LOCATION", "./storage/documents")).resolve()
    return storage.parent / "priors.json"


def empty_priors() -> Dict[str, Any]:
    return {
        "version": 1,
        "tickets": {},
        "unigrams": {field: {} for field in PRIOR_FIELDS},
        "pairs": {name: {} for name, _, _ in PAIR_RELATIONS},
        "triples": {name: {} for name, _, _ in TRIPLE_RELATIONS},
        "full": {name: {} for name, _, _ in FULL_RELATIONS},
    }


def invalidate_priors_cache() -> None:
    global _priors_cache
    _priors_cache = None


def load_priors() -> Dict[str, Any]:
    global _priors_cache
    if getattr(settings, "TESTING", False):
        return empty_priors()
    if _priors_cache is not None:
        return _priors_cache
    path = _runtime_path()
    if not path.exists():
        _priors_cache = empty_priors()
        return _priors_cache
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        logger.warning("Could not read priors file: %s", err)
        _priors_cache = empty_priors()
        return _priors_cache
    if not isinstance(payload, dict):
        _priors_cache = empty_priors()
        return _priors_cache
    priors = empty_priors()
    tickets = payload.get("tickets")
    if isinstance(tickets, dict):
        priors["tickets"] = {str(k): _snapshot_fields(v) for k, v in tickets.items() if isinstance(v, dict)}
    _recompute_counts(priors)
    _priors_cache = priors
    return priors


def save_priors(priors: Dict[str, Any]) -> None:
    global _priors_cache
    if getattr(settings, "TESTING", False):
        _priors_cache = priors
        return
    path = _runtime_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(priors, indent=2), encoding="utf-8")
        _priors_cache = priors
    except Exception as err:
        logger.warning("Could not save priors file: %s", err)


def _clean_field(field: str, value: Any) -> Optional[str]:
    item = str(value or "").strip()
    if not item or not _is_harvestable_name(field, item):
        return None
    return item


def _snapshot_fields(data: Optional[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for field in PRIOR_FIELDS:
        cleaned = _clean_field(field, (data or {}).get(field))
        if cleaned:
            out[field] = cleaned
    return out


def _join_keys(parts: Sequence[str]) -> str:
    return "||".join(_collapse(part) for part in parts)


def _bump_unigram(priors: Dict[str, Any], field: str, label: str) -> None:
    bucket = priors["unigrams"].setdefault(field, {})
    key = _collapse(label)
    slot = bucket.setdefault(key, {"label": label, "count": 0})
    slot["label"] = label
    slot["count"] = int(slot.get("count") or 0) + 1


def _bump_edge(store: Dict[str, Any], key: str, payload: Dict[str, Any]) -> None:
    slot = store.setdefault(key, {**payload, "count": 0})
    for field, value in payload.items():
        if field != "count":
            slot[field] = value
    slot["count"] = int(slot.get("count") or 0) + 1


def _recompute_counts(priors: Dict[str, Any]) -> Dict[str, Any]:
    priors["unigrams"] = {field: {} for field in PRIOR_FIELDS}
    priors["pairs"] = {name: {} for name, _, _ in PAIR_RELATIONS}
    priors["triples"] = {name: {} for name, _, _ in TRIPLE_RELATIONS}
    priors["full"] = {name: {} for name, _, _ in FULL_RELATIONS}

    for snapshot in (priors.get("tickets") or {}).values():
        if not isinstance(snapshot, dict):
            continue
        for field in PRIOR_FIELDS:
            label = snapshot.get(field)
            if label:
                _bump_unigram(priors, field, label)
        for name, left, right in PAIR_RELATIONS:
            a, b = snapshot.get(left), snapshot.get(right)
            if not a or not b:
                continue
            _bump_edge(
                priors["pairs"][name],
                _join_keys((a, b)),
                {"left": a, "right": b},
            )
        for name, givens, target in TRIPLE_RELATIONS:
            values = [snapshot.get(field) for field in givens]
            hit = snapshot.get(target)
            if not hit or any(not value for value in values):
                continue
            _bump_edge(
                priors["triples"][name],
                _join_keys([*values, hit]),
                {"given": list(values), "target": hit},
            )
        for name, givens, target in FULL_RELATIONS:
            values = [snapshot.get(field) for field in givens]
            hit = snapshot.get(target)
            if not hit or any(not value for value in values):
                continue
            _bump_edge(
                priors["full"][name],
                _join_keys([*values, hit]),
                {"given": list(values), "target": hit},
            )
    return priors


def observe_reviewed_ticket(
    fields: Optional[Dict[str, Any]],
    *,
    document_id: Optional[Any] = None,
    priors: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Upsert one reviewed ticket snapshot and recompute co-occurrence counts."""
    store = priors if priors is not None else load_priors()
    snapshot = _snapshot_fields(fields)
    if not snapshot:
        return store
    ticket_id = str(document_id) if document_id is not None else f"anon-{len(store.get('tickets') or {})}"
    store.setdefault("tickets", {})[ticket_id] = snapshot
    _recompute_counts(store)
    if priors is None:
        save_priors(store)
    return store


def rebuild_priors_from_records(
    records: Iterable[Dict[str, Any]],
    *,
    document_ids: Optional[Iterable[Any]] = None,
    persist: bool = False,
) -> Dict[str, Any]:
    """Rebuild priors from reviewed extraction dicts. Each record counts once."""
    priors = empty_priors()
    ids = list(document_ids) if document_ids is not None else []
    for index, data in enumerate(records):
        if not isinstance(data, dict):
            continue
        ticket_id = str(ids[index]) if index < len(ids) and ids[index] is not None else f"gold-{index}"
        snapshot = _snapshot_fields(data)
        if snapshot:
            priors["tickets"][ticket_id] = snapshot
    _recompute_counts(priors)
    if persist:
        save_priors(priors)
    return priors


def rebuild_priors_from_database() -> Optional[Dict[str, Any]]:
    """Replace priors.json using only documents with manual_corrections=True."""
    if getattr(settings, "TESTING", False):
        return None
    try:
        from app.db.database import SessionLocal
        from app.db.models import Document
    except Exception as err:
        logger.warning("Priors rebuild skipped: %s", err)
        return None
    db = SessionLocal()
    try:
        rows = db.query(Document.id, Document.extracted_data).filter(
            Document.manual_corrections.is_(True),
            Document.extracted_data.isnot(None),
        ).all()
    except Exception as err:
        logger.warning("Priors rebuild query failed: %s", err)
        return None
    finally:
        db.close()

    records = [data for _, data in rows if isinstance(data, dict)]
    ids = [doc_id for doc_id, data in rows if isinstance(data, dict)]
    priors = rebuild_priors_from_records(records, document_ids=ids, persist=True)
    logger.info(
        "Priors rebuilt from %s reviewed ticket(s); %s consignor→consignee pairs",
        len(priors.get("tickets") or {}),
        len(priors.get("pairs", {}).get("consignor→consignee") or {}),
    )
    return priors


def _ranked_from_store(
    store: Dict[str, Any],
    predicate,
) -> List[Tuple[str, int, float]]:
    scored: List[Tuple[str, int]] = []
    for slot in store.values():
        if not isinstance(slot, dict):
            continue
        label = predicate(slot)
        if not label:
            continue
        scored.append((str(label), int(slot.get("count") or 0)))
    total = sum(count for _, count in scored) or 1
    scored.sort(key=lambda item: (-item[1], item[0].lower()))
    return [(label, count, round(count / total, 4)) for label, count in scored]


def associated_pair(
    relation: str,
    left: Any,
    priors: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, int, float]]:
    store = (priors if priors is not None else load_priors()).get("pairs", {}).get(relation) or {}
    needle = _collapse(str(left or ""))
    if not needle:
        return []
    return _ranked_from_store(
        store,
        lambda slot: slot.get("right") if _collapse(str(slot.get("left") or "")) == needle else None,
    )


def associated_given(
    relation: str,
    given: Sequence[Any],
    *,
    family: str = "triples",
    priors: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, int, float]]:
    store = (priors if priors is not None else load_priors()).get(family, {}).get(relation) or {}
    needles = [_collapse(str(value or "")) for value in given]
    if any(not item for item in needles):
        return []
    return _ranked_from_store(
        store,
        lambda slot: (
            slot.get("target")
            if [_collapse(str(v or "")) for v in (slot.get("given") or [])] == needles
            else None
        ),
    )


def carriers_for(
    consignor: Any,
    consignee: Any,
    priors: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, int, float]]:
    """Given consignor and consignee, historically associated carriers."""
    hits = associated_given(
        "consignor+consignee→carrier",
        (consignor, consignee),
        family="triples",
        priors=priors,
    )
    if hits:
        return hits
    ship = associated_pair("consignor→carrier", consignor, priors=priors)
    recv = associated_pair("consignee→carrier", consignee, priors=priors)
    if ship and not recv:
        return ship
    if recv and not ship:
        return recv
    return []


def drivers_for(
    consignor: Any,
    carrier: Any,
    priors: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, int, float]]:
    """Given consignor + carrier, historically associated drivers."""
    return associated_given(
        "consignor+carrier→driver",
        (consignor, carrier),
        family="triples",
        priors=priors,
    )


def destinations_for(
    origin: Any,
    priors: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, int, float]]:
    """Given origin, historically associated destinations."""
    return associated_pair("origin→destination", origin, priors=priors)


def consignees_for(
    consignor: Any,
    priors: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, int, float]]:
    return associated_pair("consignor→consignee", consignor, priors=priors)


def likely_entities(
    fields: Optional[Dict[str, Any]],
    priors: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[Tuple[str, int, float]]]:
    """Given currently resolved fields, historically likely related entities."""
    data = fields or {}
    store = priors if priors is not None else load_priors()
    likely: Dict[str, List[Tuple[str, int, float]]] = {}
    consignor = data.get("consignor")
    consignee = data.get("consignee")
    carrier = data.get("carrier")
    origin = data.get("origin")

    if consignor and consignee:
        carriers = carriers_for(consignor, consignee, priors=store)
        if carriers:
            likely["carrier"] = carriers
    elif consignor:
        carriers = associated_pair("consignor→carrier", consignor, priors=store)
        if carriers:
            likely["carrier"] = carriers
        consignees = consignees_for(consignor, priors=store)
        if consignees:
            likely["consignee"] = consignees

    if consignor and carrier:
        drivers = drivers_for(consignor, carrier, priors=store)
        if drivers:
            likely["driver_name"] = drivers
    elif carrier:
        drivers = associated_pair("carrier→driver", carrier, priors=store)
        if drivers:
            likely["driver_name"] = drivers

    if origin:
        dests = destinations_for(origin, priors=store)
        if dests:
            likely["destination"] = dests

    if consignor and consignee and origin and data.get("destination"):
        full = associated_given(
            "consignor+consignee+origin+destination→carrier",
            (consignor, consignee, origin, data.get("destination")),
            family="full",
            priors=store,
        )
        if full:
            likely["carrier"] = full

    return likely
