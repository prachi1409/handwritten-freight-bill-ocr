"""Bill-level consistency and anomaly checks. Analysis only — never overwrites extracted fields."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.ocr.matching import _collapse
from app.ocr.normalizer import normalize_currency
from app.ocr.priors import associated_given, associated_pair, load_priors

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

CODE_CONSIGNOR_EQUALS_CONSIGNEE = "CONSIGNOR_EQUALS_CONSIGNEE"
CODE_FREIGHT_EXCEEDS_TOTAL = "FREIGHT_EXCEEDS_TOTAL"
CODE_LINE_ITEM_SUM_MISMATCH = "LINE_ITEM_SUM_MISMATCH"
CODE_LINE_ITEM_ARITHMETIC = "LINE_ITEM_QTY_RATE_AMOUNT_MISMATCH"
CODE_NEGATIVE_VALUE = "NEGATIVE_VALUE"
CODE_HISTORICAL_CONFLICT = "HISTORICAL_RELATIONSHIP_CONFLICT"

# Already turned into REVIEW strings by validate_extraction_data — do not duplicate.
VALIDATE_OWNED_CODES = frozenset(
    {CODE_FREIGHT_EXCEEDS_TOTAL, CODE_LINE_ITEM_SUM_MISMATCH}
)
# New impossibilities that should join the existing warning→REVIEW path.
REVIEW_ERROR_CODES = frozenset(
    {CODE_CONSIGNOR_EQUALS_CONSIGNEE, CODE_NEGATIVE_VALUE}
)

_SIGNED_NUMBER = re.compile(
    r"(?P<sign>-)?\s*(?:US\$|\$|₹|€|£)?\s*(?P<num>[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _line_item_tolerance() -> float:
    try:
        return max(0.0, float(getattr(settings, "CONSISTENCY_LINE_ITEM_TOLERANCE", 0.05) or 0.05))
    except (TypeError, ValueError):
        return 0.05


def _prior_min_count() -> int:
    try:
        return max(1, int(getattr(settings, "CONSISTENCY_PRIOR_MIN_COUNT", 3) or 3))
    except (TypeError, ValueError):
        return 3


def _prior_min_prob() -> float:
    try:
        return min(1.0, max(0.0, float(getattr(settings, "CONSISTENCY_PRIOR_MIN_PROBABILITY", 0.70) or 0.70)))
    except (TypeError, ValueError):
        return 0.70


def _prior_weak_prob() -> float:
    try:
        return min(1.0, max(0.0, float(getattr(settings, "CONSISTENCY_PRIOR_WEAK_PROBABILITY", 0.20) or 0.20)))
    except (TypeError, ValueError):
        return 0.20


def parse_signed_number(value: Any) -> Optional[float]:
    """Parse a signed numeric/money value. Returns None when missing or unparseable."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    paren = text.startswith("(") and text.endswith(")")
    match = _SIGNED_NUMBER.search(text)
    if not match:
        return None
    try:
        number = float(match.group("num").replace(",", ""))
    except ValueError:
        return None
    if paren or match.group("sign") == "-":
        return -abs(number)
    return number


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _finding(
    code: str,
    severity: str,
    message: str,
    fields: Sequence[str],
    observed: Dict[str, Any],
    *,
    expected_relationship: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
        "fields_involved": list(fields),
        "observed_values": observed,
    }
    if expected_relationship:
        row["expected_relationship"] = expected_relationship
    if evidence:
        row["evidence"] = evidence
    return row


def _check_party_identity(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    ship = data.get("consignor")
    recv = data.get("consignee")
    if not _has_text(ship) or not _has_text(recv):
        return []
    if _collapse(str(ship)) != _collapse(str(recv)):
        return []
    if not _collapse(str(ship)):
        return []
    return [
        _finding(
            CODE_CONSIGNOR_EQUALS_CONSIGNEE,
            SEVERITY_ERROR,
            "Consignor and consignee are the same party.",
            ("consignor", "consignee"),
            {"consignor": ship, "consignee": recv},
            expected_relationship="consignor ≠ consignee",
        )
    ]


def _check_freight_vs_total(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    freight = data.get("freight_amount")
    total = data.get("total_amount")
    if not _has_text(freight) or not _has_text(total):
        return []
    if not normalize_currency(freight) or not normalize_currency(total):
        return []
    freight_n = parse_signed_number(freight)
    total_n = parse_signed_number(total)
    if freight_n is None or total_n is None:
        return []
    if freight_n <= total_n:
        return []
    return [
        _finding(
            CODE_FREIGHT_EXCEEDS_TOTAL,
            SEVERITY_ERROR,
            f"Freight amount ({freight_n:,.2f}) exceeds total amount ({total_n:,.2f}).",
            ("freight_amount", "total_amount"),
            {"freight_amount": freight_n, "total_amount": total_n},
            expected_relationship="freight_amount <= total_amount",
        )
    ]


def _check_line_items(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    items = data.get("line_items") or []
    if not isinstance(items, list) or not items:
        return findings
    tolerance = _line_item_tolerance()
    amounts: List[float] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        qty = parse_signed_number(item.get("quantity"))
        rate = parse_signed_number(item.get("rate"))
        amount = parse_signed_number(item.get("amount"))
        if amount is not None:
            amounts.append(amount)
        if qty is None or rate is None or amount is None:
            continue
        expected = qty * rate
        if abs(expected - amount) <= tolerance:
            continue
        findings.append(
            _finding(
                CODE_LINE_ITEM_ARITHMETIC,
                SEVERITY_WARNING,
                f"Line item {index + 1}: quantity × rate ({expected:,.2f}) does not match amount ({amount:,.2f}).",
                ("line_items",),
                {
                    "index": index,
                    "quantity": qty,
                    "rate": rate,
                    "amount": amount,
                    "expected_amount": round(expected, 4),
                },
                expected_relationship="quantity * rate ≈ amount",
                evidence={"tolerance": tolerance},
            )
        )

    if amounts and _has_text(data.get("total_amount")) and normalize_currency(data.get("total_amount")):
        total_n = parse_signed_number(data.get("total_amount"))
        if total_n is not None:
            item_sum = sum(amounts)
            if item_sum > 0 and abs(item_sum - total_n) > tolerance:
                findings.append(
                    _finding(
                        CODE_LINE_ITEM_SUM_MISMATCH,
                        SEVERITY_ERROR,
                        f"Line item sum ({item_sum:,.2f}) mismatches total amount ({total_n:,.2f}).",
                        ("line_items", "total_amount"),
                        {"line_item_sum": round(item_sum, 4), "total_amount": total_n},
                        expected_relationship="sum(line_item.amount) ≈ total_amount",
                        evidence={"tolerance": tolerance},
                    )
                )
    return findings


def _check_negative_values(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    money_fields = (
        "freight_amount",
        "fuel_surcharge",
        "handling_charge",
        "total_amount",
    )
    other_fields = ("weight", "quantity")
    for field in money_fields + other_fields:
        raw = data.get(field)
        if not _has_text(raw):
            continue
        if field in money_fields and not normalize_currency(raw):
            continue
        number = parse_signed_number(raw)
        if number is None or number >= 0:
            continue
        findings.append(
            _finding(
                CODE_NEGATIVE_VALUE,
                SEVERITY_ERROR,
                f"{field} is negative ({number}).",
                (field,),
                {field: number},
                expected_relationship=f"{field} >= 0",
            )
        )
    for index, item in enumerate(data.get("line_items") or []):
        if not isinstance(item, dict):
            continue
        for field in ("quantity", "rate", "amount"):
            raw = item.get(field)
            if not _has_text(raw):
                continue
            number = parse_signed_number(raw)
            if number is None or number >= 0:
                continue
            findings.append(
                _finding(
                    CODE_NEGATIVE_VALUE,
                    SEVERITY_ERROR,
                    f"Line item {index + 1} {field} is negative ({number}).",
                    ("line_items",),
                    {"index": index, field: number},
                    expected_relationship=f"line_items.{field} >= 0",
                )
            )
    return findings


def _hits_for(
    relation: str,
    given: Sequence[Any],
    *,
    family: Optional[str],
    priors: Dict[str, Any],
) -> List[Tuple[str, int, float]]:
    if any(not _has_text(part) for part in given):
        return []
    if family:
        return associated_given(relation, given, family=family, priors=priors)
    return associated_pair(relation, given[0], priors=priors)


def _historical_conflict(
    relation: str,
    given_fields: Sequence[str],
    given: Sequence[Any],
    target_field: str,
    target_value: Any,
    *,
    family: Optional[str],
    priors: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not _has_text(target_value):
        return None
    hits = _hits_for(relation, given, family=family, priors=priors)
    if not hits:
        return None
    top_label, top_count, top_prob = hits[0]
    if top_count < _prior_min_count() or top_prob < _prior_min_prob():
        return None
    needle = _collapse(str(target_value))
    support = next((row for row in hits if _collapse(row[0]) == needle), None)
    if support:
        _label, support_count, support_prob = support
        if support_count >= _prior_min_count() or support_prob >= _prior_weak_prob():
            return None
    if _collapse(str(top_label)) == needle:
        return None
    observed = {field: value for field, value in zip(given_fields, given)}
    observed[target_field] = target_value
    return _finding(
        CODE_HISTORICAL_CONFLICT,
        SEVERITY_WARNING,
        f"{target_field} conflicts with strong historical {relation}.",
        (*given_fields, target_field),
        observed,
        expected_relationship=relation,
        evidence={
            "relation": relation,
            "given": [str(part) for part in given if _has_text(part)],
            "extracted": str(target_value),
            "usual_value": str(top_label),
            "usual_count": int(top_count),
            "usual_probability": float(top_prob),
            "extracted_prior_count": int(support[1]) if support else 0,
            "extracted_prior_probability": float(support[2]) if support else 0.0,
        },
    )


def _check_historical(data: Dict[str, Any], priors: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    store = priors if priors is not None else load_priors()
    if not store:
        return []
    findings: List[Dict[str, Any]] = []
    warned_targets: set = set()

    def take(finding: Optional[Dict[str, Any]], target: str) -> None:
        if not finding or target in warned_targets:
            return
        findings.append(finding)
        warned_targets.add(target)

    consignor = data.get("consignor")
    consignee = data.get("consignee")
    carrier = data.get("carrier")
    driver = data.get("driver_name")
    origin = data.get("origin")
    destination = data.get("destination")

    take(
        _historical_conflict(
            "consignor+consignee+origin+destination→carrier",
            ("consignor", "consignee", "origin", "destination"),
            (consignor, consignee, origin, destination),
            "carrier",
            carrier,
            family="full",
            priors=store,
        ),
        "carrier",
    )
    take(
        _historical_conflict(
            "consignor+consignee→carrier",
            ("consignor", "consignee"),
            (consignor, consignee),
            "carrier",
            carrier,
            family="triples",
            priors=store,
        ),
        "carrier",
    )
    take(
        _historical_conflict(
            "consignor→carrier",
            ("consignor",),
            (consignor,),
            "carrier",
            carrier,
            family=None,
            priors=store,
        ),
        "carrier",
    )
    take(
        _historical_conflict(
            "consignee→carrier",
            ("consignee",),
            (consignee,),
            "carrier",
            carrier,
            family=None,
            priors=store,
        ),
        "carrier",
    )
    take(
        _historical_conflict(
            "consignor+carrier→driver",
            ("consignor", "carrier"),
            (consignor, carrier),
            "driver_name",
            driver,
            family="triples",
            priors=store,
        ),
        "driver_name",
    )
    take(
        _historical_conflict(
            "carrier→driver",
            ("carrier",),
            (carrier,),
            "driver_name",
            driver,
            family=None,
            priors=store,
        ),
        "driver_name",
    )
    take(
        _historical_conflict(
            "consignor→consignee",
            ("consignor",),
            (consignor,),
            "consignee",
            consignee,
            family=None,
            priors=store,
        ),
        "consignee",
    )
    take(
        _historical_conflict(
            "origin→destination",
            ("origin",),
            (origin,),
            "destination",
            destination,
            family=None,
            priors=store,
        ),
        "destination",
    )
    return findings


def check_bill_consistency(
    extracted_data: Optional[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]] = None,
    *,
    priors: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return structured consistency findings. Does not mutate extracted field values."""
    data = extracted_data if isinstance(extracted_data, dict) else {}
    checks: List[Dict[str, Any]] = []
    checks.extend(_check_party_identity(data))
    checks.extend(_check_freight_vs_total(data))
    checks.extend(_check_line_items(data))
    checks.extend(_check_negative_values(data))
    checks.extend(_check_historical(data, priors))
    return {
        "checks": checks,
        "error_count": sum(1 for row in checks if row.get("severity") == SEVERITY_ERROR),
        "warning_count": sum(1 for row in checks if row.get("severity") == SEVERITY_WARNING),
        "line_item_tolerance": _line_item_tolerance(),
        "prior_min_count": _prior_min_count(),
        "prior_min_probability": _prior_min_prob(),
    }


def consistency_review_messages(payload: Optional[Dict[str, Any]]) -> List[str]:
    """Only new error findings that validate_extraction_data does not already emit."""
    messages: List[str] = []
    for row in (payload or {}).get("checks") or []:
        if not isinstance(row, dict):
            continue
        if row.get("severity") != SEVERITY_ERROR:
            continue
        if row.get("code") in VALIDATE_OWNED_CODES:
            continue
        if row.get("code") not in REVIEW_ERROR_CODES:
            continue
        message = str(row.get("message") or "").strip()
        if message:
            messages.append(message)
    return messages


def apply_consistency_to_status(
    status: Any,
    warnings: Optional[Iterable[str]],
    payload: Optional[Dict[str, Any]],
) -> Tuple[Any, List[str]]:
    from app.db.models import DocumentStatus

    merged = list(warnings or [])
    extra = consistency_review_messages(payload)
    for item in extra:
        if item not in merged:
            merged.append(item)
    if extra and status == DocumentStatus.COMPLETED:
        status = DocumentStatus.REVIEW
    return status, merged


def attach_consistency_checks(
    extracted: Optional[Dict[str, Any]],
    raw_ocr: Optional[Dict[str, Any]] = None,
    *,
    priors: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Write structured findings beside extraction results. Never changes field values."""
    payload = check_bill_consistency(
        extracted,
        metadata=raw_ocr if isinstance(raw_ocr, dict) else None,
        priors=priors,
    )
    snapshot = dict(extracted) if isinstance(extracted, dict) else {}
    payload["extracted_snapshot_unchanged"] = True
    if isinstance(extracted, dict):
        extracted["consistency_checks"] = payload
    if isinstance(raw_ocr, dict):
        raw_ocr["consistency_checks"] = payload
    # Guard: attaching metadata must not alter business fields.
    if isinstance(extracted, dict):
        for key in (
            "consignor",
            "consignee",
            "carrier",
            "driver_name",
            "origin",
            "destination",
            "freight_amount",
            "total_amount",
        ):
            if snapshot.get(key) != extracted.get(key):
                extracted[key] = snapshot.get(key)
    return payload
