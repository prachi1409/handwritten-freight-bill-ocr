"""Post-OCR matching: gold gazetteers, aliases, glyph confusion, ZIP and street hints."""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.config import settings
from app.ocr.normalizer import is_form_header_value, looks_like_ocr_junk
from app.ocr.zip_data import REGIONAL_ZIPS

logger = logging.getLogger(__name__)

NAME_FIELDS = (
    "carrier",
    "consignor",
    "consignee",
    "driver_name",
    "origin",
    "destination",
    "driver_signature",
)
ID_FIELDS = ("bill_number", "invoice_number", "vehicle_number")
PLACE_FIELDS = ("origin", "destination")

SEED_GAZETTEER: Dict[str, List[str]] = {
    "carrier": [
        "CALIFORNIA MATERIALS, INC.",
        "California Materials, Inc.",
    ],
    "consignor": [
        "Clean Planet",
        "Clean Planet Hooper",
        "Bell Marine",
        "Granite Vernalis",
        "California Materials, Inc.",
    ],
    "consignee": [
        "Aquamarine",
        "Aquamarine Contractors Inc.",
        "A&A Concrete",
        "CORONE & CO",
        "AA Concrete",
    ],
    "driver_name": [
        "Isaac Cordero",
        "Mike Gordon",
    ],
    "origin": [
        "North Hooper",
        "N. Hooper St.",
        "Stockton, CA",
        "Vernalis, CA",
    ],
    "destination": [
        "Discovery Bay",
        "Discovery Bay, CA",
        "Tracy, CA",
    ],
    "driver_signature": [
        "Isaac Cordero",
        "Mike Gordon",
    ],
}

SEED_STREETS_BY_ZIP: Dict[str, List[str]] = {
    "95213": ["North Hooper St", "N. Hooper St."],
    "95204": ["North Hooper St"],
    "94505": ["Orwood Rd"],
    "95385": ["Vernalis Rd"],
}

SEED_STREETS_BY_CITY: Dict[str, List[str]] = {
    "stockton": ["North Hooper St", "N. Hooper St.", "N. Hooper St"],
    "discovery bay": ["Orwood Rd"],
    "vernalis": ["Vernalis Rd"],
    "tracy": ["W. Linne Rd", "Linne Rd"],
}

_ID_CONFUSION = str.maketrans({
    "O": "0", "o": "0",
    "I": "1", "l": "1",
    "S": "5", "s": "5",
    "Z": "2", "z": "2",
})
_NAME_DIGIT_TO_LETTER = str.maketrans({
    "0": "O",
    "1": "I",
    "5": "S",
})
_STREET_SUFFIX = (
    r"st|street|rd|road|ave|avenue|blvd|dr|drive|ln|lane|way|ct|court|hwy|highway"
)
_STREET_RE = re.compile(
    rf"(.+?\s+(?:{_STREET_SUFFIX})\.?)\b",
    re.IGNORECASE,
)

_memory_cache: Optional[Dict[str, Any]] = None


def _collapse(text: str) -> str:
    return re.sub(r"[^a-z0-9&]+", "", (text or "").lower())


def _runtime_path() -> Path:
    storage = Path(getattr(settings, "STORAGE_LOCATION", "./storage/documents")).resolve()
    return storage.parent / "gazetteer.json"


def _copy_name_lists(src: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for key, values in src.items():
        seen = set()
        clean: List[str] = []
        for val in values:
            item = str(val).strip()
            if not item:
                continue
            key_c = _collapse(item)
            if key_c in seen:
                continue
            seen.add(key_c)
            clean.append(item)
        out[key] = clean
    return out


def _empty_memory() -> Dict[str, Any]:
    return {
        "names": _copy_name_lists(SEED_GAZETTEER),
        "aliases": {key: {} for key in NAME_FIELDS},
        "streets_by_zip": {k: list(v) for k, v in SEED_STREETS_BY_ZIP.items()},
        "streets_by_city": {k: list(v) for k, v in SEED_STREETS_BY_CITY.items()},
        "learned_zips": {},
    }


def _merge_string_list(bucket: List[str], values: Iterable[str]) -> List[str]:
    have = {_collapse(v) for v in bucket}
    for val in values:
        item = str(val).strip()
        col = _collapse(item)
        if item and col and col not in have:
            bucket.append(item)
            have.add(col)
    return bucket


def invalidate_matching_cache() -> None:
    global _memory_cache
    _memory_cache = None


def load_matching_memory() -> Dict[str, Any]:
    """Seed memory plus Review-learned names, aliases, streets, and ZIPs."""
    global _memory_cache
    if getattr(settings, "TESTING", False):
        return _empty_memory()
    if _memory_cache is not None:
        return _memory_cache
    memory = _empty_memory()
    path = _runtime_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as err:
            logger.warning("Could not read gazetteer file: %s", err)
            payload = {}
        if isinstance(payload, dict):
            names = payload.get("names") if isinstance(payload.get("names"), dict) else payload
            for key, values in (names or {}).items():
                if key in ("aliases", "streets_by_zip", "streets_by_city", "learned_zips"):
                    continue
                if isinstance(values, list):
                    _merge_string_list(memory["names"].setdefault(key, []), values)
            aliases = payload.get("aliases") if isinstance(payload.get("aliases"), dict) else {}
            for key, mapping in aliases.items():
                if isinstance(mapping, dict):
                    memory["aliases"].setdefault(key, {}).update(
                        {str(k): str(v) for k, v in mapping.items() if k and v}
                    )
            for zip_code, streets in (payload.get("streets_by_zip") or {}).items():
                if isinstance(streets, list):
                    _merge_string_list(memory["streets_by_zip"].setdefault(str(zip_code), []), streets)
            for city, streets in (payload.get("streets_by_city") or {}).items():
                if isinstance(streets, list):
                    _merge_string_list(memory["streets_by_city"].setdefault(str(city).lower(), []), streets)
            for zip_code, city_state in (payload.get("learned_zips") or {}).items():
                if isinstance(city_state, (list, tuple)) and len(city_state) >= 2:
                    memory["learned_zips"][str(zip_code)] = (str(city_state[0]), str(city_state[1]))
    _memory_cache = memory
    return memory


def load_gazetteer() -> Dict[str, List[str]]:
    """Seed names plus any Review-learned names."""
    return load_matching_memory()["names"]


def save_matching_memory(memory: Dict[str, Any]) -> None:
    if getattr(settings, "TESTING", False):
        return
    path = _runtime_path()
    payload = {
        "names": _copy_name_lists(memory.get("names") or {}),
        "aliases": memory.get("aliases") or {},
        "streets_by_zip": memory.get("streets_by_zip") or {},
        "streets_by_city": memory.get("streets_by_city") or {},
        "learned_zips": {
            zip_code: list(city_state)
            for zip_code, city_state in (memory.get("learned_zips") or {}).items()
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        invalidate_matching_cache()
        _set_cache(memory)
    except Exception as err:
        logger.warning("Could not save gazetteer file: %s", err)


def _set_cache(memory: Dict[str, Any]) -> None:
    global _memory_cache
    _memory_cache = memory


def save_gazetteer(gazetteer: Dict[str, List[str]]) -> None:
    memory = load_matching_memory()
    memory["names"] = _copy_name_lists(gazetteer)
    save_matching_memory(memory)


def add_gazetteer_value(field: str, value: str, gazetteer: Optional[Dict[str, List[str]]] = None) -> Dict[str, List[str]]:
    gaz = gazetteer if gazetteer is not None else load_gazetteer()
    item = str(value or "").strip()
    if not _is_harvestable_name(field, item):
        return gaz
    bucket = gaz.setdefault(field, [])
    col = _collapse(item)
    if col and col not in {_collapse(v) for v in bucket}:
        bucket.append(item)
    return gaz


def _is_harvestable_name(field: str, value: str) -> bool:
    item = str(value or "").strip()
    if not item or is_form_header_value(item) or looks_like_ocr_junk(item):
        return False
    if field in ("driver_name", "driver_signature") and re.fullmatch(r"\d{3,}", item):
        return False
    if sum(ch.isalpha() for ch in item) < 3:
        return False
    if re.search(r"[^\w\s.&,'/#-]", item, re.UNICODE):
        return False
    return True


def _trusted_uncorrected(field: str, value: str) -> bool:
    if not _is_harvestable_name(field, value):
        return False
    if field == "carrier" and re.search(r"\b(inc|llc|corp|co)\.?\b", value, re.I):
        return True
    if field in PLACE_FIELDS:
        return bool(
            re.search(r"\b\d{5}\b", value)
            or re.search(r"\b(CA|Stockton|Tracy|Discovery Bay|Vernalis|Manteca|Lathrop)\b", value, re.I)
        )
    return False


def name_variants(text: str) -> List[str]:
    """OCR guesses: 9 as &, 0/5 as letters."""
    raw = str(text or "").strip()
    if not raw:
        return []
    found = [raw, raw.translate(_NAME_DIGIT_TO_LETTER), raw.replace("9", "&"), raw.replace(" 9 ", " & ")]
    out: List[str] = []
    seen = set()
    for item in found:
        item = re.sub(r"\s+", " ", item).strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def similarity(left: str, right: str) -> float:
    a, b = _collapse(left), _collapse(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        if len(shorter) >= 6 and len(shorter) / len(longer) >= 0.55:
            return 0.92
    return SequenceMatcher(None, a, b).ratio()


def match_gazetteer_name(
    value: Any,
    candidates: Iterable[str],
    *,
    min_ratio: float = 0.86,
) -> Optional[str]:
    """Return canonical gazetteer name when OCR is close enough."""
    text = str(value or "").strip()
    if not text or is_form_header_value(text) or looks_like_ocr_junk(text):
        return None
    if re.fullmatch(r"\d{3,}", text):
        return None
    best_name = None
    best_score = 0.0
    variants = name_variants(text)
    for cand in candidates:
        for variant in variants:
            score = similarity(variant, cand)
            if score > best_score or (
                score == best_score and best_name and len(_collapse(cand)) > len(_collapse(best_name))
            ):
                best_score = score
                best_name = cand
    if not best_name or best_score < min_ratio:
        return None
    ocr_c, hit_c = _collapse(text), _collapse(best_name)
    # Keep a longer, more specific OCR string (Clean Planet Hooper) instead of shrinking it.
    if hit_c and hit_c in ocr_c and len(ocr_c) > len(hit_c) + 2:
        return None
    return best_name


def resolve_alias(field: str, value: Any, aliases: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    table = (aliases or {}).get(field) or {}
    for variant in name_variants(text):
        hit = table.get(_collapse(variant))
        if hit:
            return hit
    return None


def fix_id_glyphs(value: Any) -> Optional[str]:
    """Map O/I/S/Z toward digits only when they sit next to a digit."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or is_form_header_value(text):
        return text
    if not re.search(r"\d", text):
        return text

    def _swap(match: re.Match[str]) -> str:
        return match.group(0).translate(_ID_CONFUSION)

    return re.sub(r"(?<=\d)[OoIlSsZz]|[OoIlSsZz](?=\d)", _swap, text)


def lookup_zip(zip_code: str, learned: Optional[Dict[str, Tuple[str, str]]] = None) -> Optional[Tuple[str, str]]:
    if learned and zip_code in learned:
        return learned[zip_code]
    return REGIONAL_ZIPS.get(zip_code)


def parse_place(text: str) -> Dict[str, Optional[str]]:
    raw = str(text or "").strip()
    zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\b", raw)
    zip_code = zip_match.group(1) if zip_match else None
    street_match = _STREET_RE.search(raw)
    street = re.sub(r"\s+", " ", street_match.group(1)).strip(" ,") if street_match else None
    return {"zip": zip_code, "street": street}


def apply_zip_hints(
    fields: Dict[str, Any],
    learned_zips: Optional[Dict[str, Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """If a place field contains a known ZIP, align city/state."""
    out = dict(fields)
    learned = learned_zips if learned_zips is not None else load_matching_memory()["learned_zips"]
    for key in PLACE_FIELDS:
        raw = str(out.get(key) or "").strip()
        if not raw:
            continue
        match = re.search(r"\b(\d{5})(?:-\d{4})?\b", raw)
        if not match:
            continue
        zip_code = match.group(1)
        city_state = lookup_zip(zip_code, learned)
        if not city_state:
            continue
        city, state = city_state
        street = parse_place(raw)["street"]
        collapsed = _collapse(raw)
        if street:
            out[key] = f"{street}, {city}, {state} {zip_code}"
            continue
        if _collapse(city) in collapsed and state.lower() in raw.lower():
            continue
        if _collapse(city) in collapsed or zip_code in raw:
            out[key] = f"{city}, {state} {zip_code}"
    return out


def apply_street_hints(
    fields: Dict[str, Any],
    memory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Snap a street fragment to a gold street in the same ZIP or city."""
    mem = memory if memory is not None else load_matching_memory()
    out = dict(fields)
    learned = mem.get("learned_zips") or {}
    for key in PLACE_FIELDS:
        raw = str(out.get(key) or "").strip()
        if not raw:
            continue
        parsed = parse_place(raw)
        zip_code = parsed["zip"]
        candidates: List[str] = []
        city = state = None
        if zip_code:
            candidates.extend(mem.get("streets_by_zip", {}).get(zip_code) or [])
            city_state = lookup_zip(zip_code, learned)
            if city_state:
                city, state = city_state
                candidates.extend(mem.get("streets_by_city", {}).get(city.lower()) or [])
        if not candidates:
            for city_name, streets in (mem.get("streets_by_city") or {}).items():
                if _collapse(city_name) and _collapse(city_name) in _collapse(raw):
                    candidates.extend(streets)
                    city = city_name.title() if city_name.islower() else city_name
        if not candidates:
            continue
        street_query = parsed["street"] or raw
        hit = match_gazetteer_name(street_query, candidates, min_ratio=0.84)
        if not hit:
            continue
        if zip_code and city and state:
            out[key] = f"{hit}, {city}, {state} {zip_code}"
        elif city:
            out[key] = f"{hit}, {city}"
        else:
            out[key] = hit
    return out


def apply_entity_matching(
    fields: Optional[Dict[str, Any]],
    gazetteer: Optional[Dict[str, List[str]]] = None,
    memory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Snap names to known entities and fix identifier glyph swaps."""
    if not getattr(settings, "ENABLE_ENTITY_MATCHING", True):
        return dict(fields or {})
    out = dict(fields or {})
    mem = memory if memory is not None else load_matching_memory()
    gaz = gazetteer if gazetteer is not None else mem["names"]
    aliases = mem.get("aliases") or {}
    for key in ID_FIELDS:
        if out.get(key):
            out[key] = fix_id_glyphs(out.get(key))
    for key in NAME_FIELDS:
        raw = out.get(key)
        if not raw:
            continue
        alias = resolve_alias(key, raw, aliases)
        if alias and alias != raw:
            logger.info("Alias matched %s: %r -> %r", key, raw, alias)
            out[key] = alias
            continue
        hit = match_gazetteer_name(raw, gaz.get(key) or [])
        if hit and hit != raw:
            logger.info("Gazetteer matched %s: %r -> %r", key, raw, hit)
            out[key] = hit
    out = apply_zip_hints(out, mem.get("learned_zips") or {})
    return apply_street_hints(out, mem)


def _add_street(memory: Dict[str, Any], street: str, zip_code: Optional[str], city: Optional[str]) -> bool:
    item = re.sub(r"\s+", " ", (street or "").strip(" ,"))
    if not item or looks_like_ocr_junk(item) or is_form_header_value(item):
        return False
    changed = False
    if zip_code:
        before = list(memory["streets_by_zip"].get(zip_code) or [])
        _merge_string_list(memory["streets_by_zip"].setdefault(zip_code, []), [item])
        changed = changed or memory["streets_by_zip"][zip_code] != before
    if city:
        city_key = city.strip().lower()
        before = list(memory["streets_by_city"].get(city_key) or [])
        _merge_string_list(memory["streets_by_city"].setdefault(city_key, []), [item])
        changed = changed or memory["streets_by_city"][city_key] != before
    return changed


def merge_gold_records(
    records: Iterable[Dict[str, Any]],
    *,
    trusted: bool = True,
    memory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge gold (or trusted) extracted records into matching memory."""
    mem = memory if memory is not None else _empty_memory()
    for data in records:
        if not isinstance(data, dict):
            continue
        for key in NAME_FIELDS:
            value = str(data.get(key) or "").strip()
            if not value:
                continue
            if trusted:
                if not _is_harvestable_name(key, value):
                    continue
            elif not _trusted_uncorrected(key, value):
                continue
            _merge_string_list(mem["names"].setdefault(key, []), [value])
        for key in PLACE_FIELDS:
            parsed = parse_place(str(data.get(key) or ""))
            zip_code = parsed["zip"]
            if zip_code:
                city_state = lookup_zip(zip_code, mem.get("learned_zips") or {})
                if city_state:
                    mem["learned_zips"][zip_code] = city_state
                if parsed["street"]:
                    city = city_state[0] if city_state else None
                    _add_street(mem, parsed["street"], zip_code, city)
    return mem


def refresh_gold_from_database() -> None:
    """Pull reviewed tickets (and trusted letterhead/places) into the runtime gazetteer."""
    if getattr(settings, "TESTING", False):
        return
    try:
        from app.db.database import SessionLocal
        from app.db.models import Document
    except Exception as err:
        logger.warning("Gold harvest skipped: %s", err)
        return
    db = SessionLocal()
    try:
        rows = db.query(Document.extracted_data, Document.manual_corrections).filter(
            Document.extracted_data.isnot(None)
        ).all()
    except Exception as err:
        logger.warning("Gold harvest query failed: %s", err)
        return
    finally:
        db.close()

    memory = load_matching_memory()
    gold = [data for data, corrected in rows if corrected and isinstance(data, dict)]
    other = [data for data, corrected in rows if (not corrected) and isinstance(data, dict)]
    merge_gold_records(gold, trusted=True, memory=memory)
    merge_gold_records(other, trusted=False, memory=memory)
    save_matching_memory(memory)
    logger.info(
        "Gold harvest: %s reviewed, %s other documents; %s consignees, %s streets",
        len(gold),
        len(other),
        len(memory["names"].get("consignee") or []),
        sum(len(v) for v in memory["streets_by_zip"].values()),
    )


def learn_gold_values(fields: Optional[Dict[str, Any]]) -> None:
    """Add confirmed names from a reviewed ticket into the runtime gazetteer."""
    if getattr(settings, "TESTING", False):
        return
    memory = merge_gold_records([fields or {}], trusted=True, memory=load_matching_memory())
    save_matching_memory(memory)


def learn_from_correction(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> None:
    """When Review changes a name, keep the gold string and an OCR→gold alias."""
    learn_gold_values(after)
    if getattr(settings, "TESTING", False):
        return
    prev = before or {}
    nxt = after or {}
    memory = load_matching_memory()
    changed = False
    for key in NAME_FIELDS:
        old = str(prev.get(key) or "").strip()
        new = str(nxt.get(key) or "").strip()
        if new and new != old:
            before_len = len(memory["names"].get(key) or [])
            add_gazetteer_value(key, new, memory["names"])
            if len(memory["names"].get(key) or []) != before_len:
                changed = True
            if old and _collapse(old) != _collapse(new):
                memory["aliases"].setdefault(key, {})
                memory["aliases"][key][_collapse(old)] = new
                changed = True
    if changed:
        save_matching_memory(memory)
