"""Validation, Field Confidence, and Normalization layer for OCR extracted Freight Bill data."""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from app.db.models import DocumentStatus

logger = logging.getLogger(__name__)

EXACT_LABEL_STOP_WORDS = {
    "HANDWRITTEN", "BILL", "NUMBER", "NO", "NUM", "INVOICE", "VEHICLE",
    "TRUCK", "DATE", "WEIGHT", "FREIGHT", "TOTAL", "AMOUNT", "N/A",
    "NONE", "NULL", "UNKNOWN", "CARGO", "ITEM", "VAL", "VALUE",
    "NAME", "DESCRIPTION", "LOCATION", "CONSIGNEE", "SHIPPER", "CONSIGOR", "CONSIGNOR",
    "RECEIVER", "CARRIER", "COMMODITY", "QUANTITY", "DRIVER", "SPECIAL", "INSTRUCTIONS",
    "ORIGIN", "DESTINATION", "TIME", "PICKUP", "DELIVERY", "RECIEVER",
    "BILLNO", "BILLNUMBER", "INVOICENUMBER", "VEHICLENUMBER", "FREIGHTAMOUNT", "TOTALAMOUNT",
    "FREIGHTBILL", "BILLOFLADING",
    "SPECIALINSTRUCTIONS", "DRIVERNAME", "COMMODITYDESCRIPTION", "COMODTVDESCRPTON", "PICKUPIDELIVERYTIME",
    "EREGHTAMOUNT", "DESTNATON", "NVOICE", "NOMBER", "NVOICENOMBER", "MANIFEST", "BILL OF LADING",
    "DE", "DEL", "LA", "EL", "LOS", "LAS", "OF", "THE", "AND",
    "ADDRESS", "SUBHAUL", "TAGNUMBER", "STREETCITY", "STREETANDCITY",
    "POINTOFORIGIN", "POINTOFDESTINATION",
    "ARRIVED", "DEPART", "REMARKS", "TONNAGE", "HOURLY", "LOADING", "UNLOADING",
    "BILLTO", "JOBNAME", "TRAILEROWNER", "TRUCKNO", "TRUCKLICENSE", "TRAILERLICENSE",
    "PAYROLL", "SIGNATURE", "START",
    "MILES", "HOURS", "TOTALHOURS", "MHOURS", "STARTHOURS", "TOTALMILES", "STARTMILES",
}

_HEADER_COLLAPSED_FRAGMENTS = (
    "POINTOFORIGIN", "POINTOFDESTINATION", "SUBHAUL", "TAGNUMBER",
    "STREETCITY", "STREETANDCITY", "ADDRESSORJOB",
    "TRAILEROWNER", "TRUCKLICENSE", "TRAILERLICENSE",
)

ALL_SCHEMA_FIELDS = (
    "bill_number",
    "bill_date",
    "carrier",
    "invoice_number",
    "consignor",
    "consignee",
    "origin",
    "destination",
    "commodity_description",
    "quantity",
    "weight",
    "freight_amount",
    "fuel_surcharge",
    "handling_charge",
    "total_amount",
    "vehicle_number",
    "driver_name",
    "pickup_time",
    "delivery_time",
    "special_instructions",
    "driver_signature",
    "consignee_signature",
    "received_datetime",
)

CRITICAL_FIELDS = (
    "bill_number",
    "consignor",
    "consignee",
    "origin",
    "destination",
    "freight_amount",
    "total_amount",
)

# Scale tickets often have no dollar amounts. A saved review still completes.
REVIEW_OPTIONAL_CRITICAL = frozenset({"freight_amount", "total_amount"})


def is_invalid_label_value(val: str) -> bool:
    """True if string is purely a form label header."""
    if not val:
        return True
    if re.search(r"\d", str(val)):
        return False
    clean = re.sub(r"[^A-Za-z]+", "", str(val).upper())
    if not clean:
        return False
    return clean in EXACT_LABEL_STOP_WORDS


def is_form_header_value(val: Any) -> bool:
    """True for printed form chrome (ADDRESS, POINT OF DESTINATION, SUB-HAUL#) used as a field value."""
    if val is None:
        return True
    text = str(val).strip()
    if not text:
        return True
    if is_invalid_label_value(text):
        return True
    collapsed = re.sub(r"[^A-Za-z]+", "", text.upper())
    if any(frag in collapsed for frag in _HEADER_COLLAPSED_FRAGMENTS):
        return True
    if re.search(r"point\s+of\s+(origin|destination)", text, re.IGNORECASE):
        return True
    if re.search(r"sub[\s-]*haul", text, re.IGNORECASE) and not re.search(r"[A-Za-z]{4,}\s+(LLC|INC|CORP)", text, re.IGNORECASE):
        if len(collapsed) <= 16:
            return True
    return False


def looks_like_ocr_junk(val: Any) -> bool:
    """True for glyph salad (Qee, BElIm Ae ME, RN Alo YRZ) that should not be stored as a name."""
    if val is None:
        return False
    text = str(val).strip()
    if not text:
        return False
    if is_form_header_value(text):
        return True
    letters = re.sub(r"[^A-Za-z]", "", text)
    if 0 < len(letters) <= 3:
        return True
    # CMAT MO/DAY/YR boxes glued onto a place (e.g. "YRZ5 Stockton Discavery Bay CA").
    if re.match(r"^(?:YRZ?\d|YR\.?\s*\d|MO\.?\s*\d|DAY\.?\s*\d)", text, re.IGNORECASE):
        return True
    if re.match(r"^[A-Z]{2,4}\d+\s+[A-Za-z]", text):
        return True
    tokens = re.findall(r"[A-Za-z]+", text)
    if not tokens:
        return False
    if len(tokens) >= 3 and all(len(t) <= 3 for t in tokens):
        return True
    if "/" in text and not re.search(
        r"discovery|hooper|stockton|tracy|vernalis|palm|orwood|manteca",
        text,
        re.I,
    ):
        return True
    if len(tokens) >= 4 and re.search(r"\d", text) and not re.search(
        r"\b(st|rd|ave|ca|stockton|tracy|discovery|hooper|bay)\b",
        text,
        re.I,
    ):
        return True
    for token in tokens:
        if len(token) <= 7:
            flips = sum(1 for a, b in zip(token, token[1:]) if a.isupper() != b.isupper())
            if flips >= 3:
                return True
    return False


def clean_field_value(value: Optional[Any]) -> Optional[str]:
    """Clean text field value and reject generic stop words and label headers."""
    if value is None:
        return None
    val_str = str(value).strip()
    if not val_str or is_form_header_value(val_str):
        return None
    val_str = re.sub(
        r"^(?:address|street(?:\s+and)?\s+city|tag\s*(?:number|#)?|sub[\s-]*haul\s*#?)\s*[:#-]?\s*",
        "",
        val_str,
        flags=re.IGNORECASE,
    ).strip()
    if not val_str or is_form_header_value(val_str):
        return None
    return val_str


def unglue_ocr_words(value: str) -> str:
    """Insert spaces RapidOCR often drops (GraniteVernalis, CALIFORNIAMATERIALS,INC.)."""
    text = (value or "").strip()
    if not text:
        return text
    text = re.sub(
        r"(?<=[A-Za-z])(MATERIALS|TRUCKING|CONCRETE|LOGISTICS|TRANSPORT|HAULING|EXPRESS|CARRIERS)\b",
        r" \1",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]{2,})([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"\s*,\s*(INC|LLC|CORP|LTD)\.?", r", \1.", text, flags=re.IGNORECASE)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_DEVANAGARI_ID_PREFIXES = (
    (re.compile(r"^एफबी"), "FB"),
    (re.compile(r"^एचबी"), "HB"),
    (re.compile(r"^आईएनवी"), "INV"),
    (re.compile(r"^इन्व"), "INV"),
)


def transliterate_indic_digits(value: str) -> str:
    """Convert Devanagari digits to ASCII (३६ → 36)."""
    return (value or "").translate(_DEVANAGARI_DIGITS)


def transliterate_indic_identifier(value: str) -> str:
    """Map common Hindi freight IDs (एफबी-१०२३६) to Latin (FB-10236)."""
    text = (value or "").translate(_DEVANAGARI_DIGITS)
    for pattern, repl in _DEVANAGARI_ID_PREFIXES:
        text = pattern.sub(repl, text)
    return text


def clean_identifier(value: Optional[Any]) -> Optional[str]:
    """Extract clean identifier value and strip embedded label prefixes."""
    raw = clean_field_value(value)
    if not raw:
        return None

    cleaned = re.sub(
        r"^(?:cargo\s*manifest\b\s*(?:no|number)?|manifest\b\s*(?:no|number)?|bill\s*of\s*lading\b\s*(?:no|number)?|bol\b\s*(?:no|number)?|bill\b\s*(?:no|number)?|invoice\b\s*(?:no|number)?|inv\b\s*(?:no|number)?|vehicle\b\s*(?:no|number)?|truck\b\s*(?:no|number)?)\s*[:#\s]+",
        "",
        raw,
        flags=re.IGNORECASE
    ).strip()

    if not cleaned or is_form_header_value(cleaned):
        return None

    cleaned = transliterate_indic_identifier(cleaned)

    if len(cleaned) < 3 and not re.search(r"[\d०-९]", cleaned):
        return None

    if not re.search(r"[\w]", cleaned, flags=re.UNICODE):
        return None
    if re.fullmatch(r"[\W_]+", cleaned, flags=re.UNICODE):
        return None

    if cleaned.startswith("F3-"):
        cleaned = "FB-" + cleaned[3:]
    elif cleaned.startswith("H3-"):
        cleaned = "HB-" + cleaned[3:]

    return cleaned


def normalize_currency(value: Optional[Any]) -> Optional[str]:
    """Normalize currency values to clean '$X,XXX.XX' format, handling OCR dot artifacts."""
    if value is None:
        return None
    val_str = str(value).strip()
    if not val_str or is_invalid_label_value(val_str):
        return None

    val_str = re.sub(r"(\d)\.(\d{3})\b", r"\1\2", val_str)

    match = re.search(r"[\$₹€£]?\s*([\d,]+\.?\d*)", val_str)
    if not match:
        return None

    num_str = match.group(1).replace(",", "")
    try:
        num = float(num_str)
        return f"${num:,.2f}"
    except ValueError:
        return None


def normalize_date(value: Optional[Any]) -> Optional[str]:
    """Normalize date strings to standard ISO 'YYYY-MM-DD' format."""
    if value is None:
        return None
    val_str = str(value).strip()
    if not val_str or is_form_header_value(val_str):
        return None
    # A lone month/day box (spatial "4") is not a calendar date.
    if re.fullmatch(r"\d{1,2}", val_str):
        return None

    match_slash = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b", val_str)
    if match_slash:
        p1, p2, year = int(match_slash.group(1)), int(match_slash.group(2)), int(match_slash.group(3))
        if year < 100:
            year += 2000
        if p1 > 12:
            day, month = p1, p2
        elif p2 > 12:
            day, month = p2, p1
        else:
            month, day = p1, p2
        try:
            dt = datetime(year, month, day)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    match_iso = re.search(r"\b(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})\b", val_str)
    if match_iso:
        year, month, day = int(match_iso.group(1)), int(match_iso.group(2)), int(match_iso.group(3))
        try:
            dt = datetime(year, month, day)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    mo = re.search(r"\bMO\.?\s*(\d{1,2})\b", val_str, re.IGNORECASE)
    day = re.search(r"\bDAY\.?\s*(\d{1,2})\b", val_str, re.IGNORECASE)
    yr = re.search(r"\bYR\.?\s*(\d{2,4})\b", val_str, re.IGNORECASE)
    if mo and day and yr:
        month, day_n, year = int(mo.group(1)), int(day.group(1)), int(yr.group(1))
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day_n).strftime("%Y-%m-%d")
        except ValueError:
            pass

    boxed = parse_boxed_month_day_year(val_str)
    if boxed:
        return boxed

    return None


_BOXED_MO_RE = re.compile(r"\bMO\.?\s*(\d{1,2})\b", re.IGNORECASE)
_BOXED_DAY_RE = re.compile(r"\bDAY\.?\s*(\d{1,2})\b", re.IGNORECASE)
_BOXED_YR_RE = re.compile(r"\bYR\.?\s*(\d{2,4})\b", re.IGNORECASE)


def _boxed_day_match(window: str) -> Optional[re.Match[str]]:
    """Calendar DAY box only — never the CMAT JOB DAY ticket field."""
    for match in _BOXED_DAY_RE.finditer(window):
        prefix = window[max(0, match.start() - 16) : match.start()].upper()
        if re.search(r"JOB\s*$", prefix.strip()):
            continue
        if prefix.rstrip().endswith("JOB"):
            continue
        return match
    return None


def _iso_from_boxed_parts(month: int, day_n: int, year: int) -> Optional[str]:
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day_n).strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_boxed_month_day_year(raw_text: str) -> Optional[str]:
    """Parse form boxes like MO. 2  DAY 2  YR. 26 into YYYY-MM-DD.

    Digits must sit near a YR box (or a DATE header + year) so JOB DAY 1105-2
    is not treated as a calendar day.
    """
    if not raw_text:
        return None
    for yr_m in _BOXED_YR_RE.finditer(raw_text):
        start = max(0, yr_m.start() - 160)
        end = min(len(raw_text), yr_m.end() + 160)
        window = raw_text[start:end]
        mo = _BOXED_MO_RE.search(window)
        day = _boxed_day_match(window)
        if not (mo and day):
            continue
        hit = _iso_from_boxed_parts(int(mo.group(1)), int(day.group(1)), int(yr_m.group(1)))
        if hit:
            return hit
    for date_m in re.finditer(r"\bDATE\b", raw_text, re.IGNORECASE):
        window = raw_text[date_m.start() : min(len(raw_text), date_m.end() + 240)]
        mo = _BOXED_MO_RE.search(window)
        day = _boxed_day_match(window)
        if not (mo and day):
            continue
        yr = _BOXED_YR_RE.search(window)
        year_n = int(yr.group(1)) if yr else None
        if year_n is None:
            year_hit = re.search(r"\b(20\d{2}|2[0-9])\b", window)
            if year_hit:
                year_n = int(year_hit.group(1))
        if year_n is None:
            continue
        hit = _iso_from_boxed_parts(int(mo.group(1)), int(day.group(1)), year_n)
        if hit:
            return hit
    return None


def normalize_location(value: Optional[Any]) -> Optional[str]:
    """Normalize city/state location string spacing (e.g. 'Columbus,OH' -> 'Columbus, OH')."""
    cleaned = clean_field_value(value)
    if not cleaned or is_form_header_value(cleaned):
        return None
    cleaned = unglue_ocr_words(cleaned)
    cleaned = re.sub(r"\b([A-Z])([A-Z][a-z]{2,})\b", r"\1 \2", cleaned)
    cleaned = re.sub(r"\bBd\b", "Rd", cleaned)
    cleaned = re.sub(r"([A-Za-z]+),([A-Za-z]{2})\b", r"\1, \2", cleaned)
    return cleaned


def normalize_weight(value: Optional[Any]) -> Optional[str]:
    """Normalize weight; strip glued clock times (e.g. '27.0215:20 5:27' -> '27.02')."""
    cleaned = clean_field_value(value)
    if not cleaned or is_form_header_value(cleaned):
        return None

    cleaned = re.sub(r"\d{1,2}:\d{2}(?:\s*[AaPp]\.?\s*[Mm]\.?)?", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"(\d+)\.(\d{3})(?=[a-zA-Z\s]|$)", r"\1,\2", cleaned)
    cleaned = re.sub(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:lbs|los|1os|Ibs|LBS|Ib)\b", r"\1 lbs", cleaned, flags=re.IGNORECASE)

    match = re.search(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d+)", cleaned)
    if not match:
        return None
    num = match.group(1)
    if re.search(r"\blbs\b", cleaned, re.IGNORECASE):
        return f"{num} lbs"
    return num


def compact_digits_to_clock(value: str) -> Optional[str]:
    """Convert compact handwritten times: 930 → 9:30, 1020 → 10:20."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 3:
        hour, minute = int(digits[0]), int(digits[1:])
    elif len(digits) == 4:
        hour, minute = int(digits[:2]), int(digits[2:])
    else:
        return None
    if hour > 23 or minute > 59:
        return None
    if hour == 0 and minute == 0:
        return None
    return f"{hour}:{minute:02d}"


def normalize_clock_time(value: Optional[Any]) -> Optional[str]:
    """Normalize '5:20', '5:20 AM', or compact '930' / '1020' to H:MM."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or is_form_header_value(text):
        return None
    colon = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if colon:
        hour, minute = int(colon.group(1)), int(colon.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            suffix = re.search(r"\s*([AaPp]\.?\s*[Mm]\.?)", text[colon.end():])
            out = f"{hour}:{minute:02d}"
            if suffix:
                out += " " + re.sub(r"\s+", "", suffix.group(1)).upper().replace(".", "")
            return out
    compact = compact_digits_to_clock(text)
    return compact


def field_shape_ok(field: str, val: Any) -> bool:
    """True when a normalized value looks like the schema field, not OCR chrome."""
    if val is None or str(val).strip() == "":
        return False
    text = str(val).strip()
    if is_form_header_value(text):
        return False
    if field == "bill_date":
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", text))
    if field in ("freight_amount", "fuel_surcharge", "handling_charge", "total_amount"):
        return bool(re.match(r"^\$\d", text))
    if field == "weight":
        return bool(re.search(r"\d", text)) and not re.search(r"\d{1,2}:\d{2}", text)
    if field in ("pickup_time", "delivery_time"):
        return bool(re.search(r"\d{1,2}:\d{2}", text))
    if field == "vehicle_number":
        return bool(re.search(r"\d", text)) and not re.search(r"miles|hours", text, re.IGNORECASE)
    if field == "special_instructions":
        letters = re.sub(r"[^A-Za-z]", "", text)
        return len(letters) >= 4
    if field in ("consignor", "consignee", "origin", "destination", "commodity_description", "driver_name"):
        if re.search(r"hours|miles", text, re.IGNORECASE):
            return False
        return not looks_like_ocr_junk(text)
    return True


def calculate_field_confidences(extracted: Dict[str, Any], raw_text: str = "") -> Dict[str, float]:
    """Calculate evidence-based field-level confidence scores (0.0 to 1.0) for every schema field."""
    confidences: Dict[str, float] = {}
    is_manual = bool(extracted.get("manually_corrected") or extracted.get("reviewed"))

    for field in ALL_SCHEMA_FIELDS:
        val = extracted.get(field)
        if val is None or str(val).strip() == "" or is_form_header_value(str(val)) or not field_shape_ok(field, val):
            confidences[field] = 0.0
            continue

        if is_manual:
            confidences[field] = 1.0
            continue

        val_str = str(val).strip()
        base_score = 0.85

        if field == "bill_number":
            if re.match(r"^[A-Z0-9-]{3,20}$", val_str):
                base_score = 0.95
        elif field == "invoice_number":
            if re.match(r"^INV-[A-Z0-9-]{3,20}$", val_str, re.IGNORECASE):
                base_score = 0.95
        elif field == "bill_date":
            if re.match(r"^\d{4}-\d{2}-\d{2}$", val_str):
                base_score = 0.96
        elif field in ("freight_amount", "fuel_surcharge", "handling_charge", "total_amount"):
            if re.match(r"^\$\d{1,3}(?:,\d{3})*\.\d{2}$", val_str):
                base_score = 0.94
        elif field == "vehicle_number":
            if re.match(r"^[A-Z0-9-]{2,10}$", val_str):
                base_score = 0.95
        elif field == "weight":
            base_score = 0.88

        confidences[field] = round(base_score, 2)

    return confidences


def validate_extraction_data(data: Dict[str, Any]) -> Tuple[DocumentStatus, List[str], float]:
    """Validate extraction completeness, financial balance, and strict 8 critical field presence."""
    warnings: List[str] = []
    field_confs = data.get("field_confidence", {})

    present_confs = [c for f, c in field_confs.items() if c > 0.0 and data.get(f) is not None]
    overall_confidence = (sum(present_confs) / len(present_confs)) if present_confs else 0.0
    overall_confidence = round(overall_confidence, 2)

    missing_critical = [f for f in CRITICAL_FIELDS if not data.get(f) or is_form_header_value(str(data.get(f)))]

    if missing_critical:
        warnings.append(f"Missing critical field(s): {', '.join(missing_critical)}")

    if overall_confidence < 0.70:
        warnings.append(f"Low overall confidence ({overall_confidence*100:.1f}%)")

    frt_val = data.get("freight_amount")
    tot_val = data.get("total_amount")
    if frt_val and tot_val:
        frt_num = normalize_currency(frt_val)
        tot_num = normalize_currency(tot_val)
        if frt_num and tot_num:
            f_amt = float(re.sub(r"[^\d.]", "", frt_num))
            t_amt = float(re.sub(r"[^\d.]", "", tot_num))
            if f_amt > t_amt:
                warnings.append(f"Freight amount (${f_amt:,.2f}) exceeds Total amount (${t_amt:,.2f})")

    items = data.get("line_items") or []
    item_sum = 0.0
    for item in items:
        if isinstance(item, dict) and item.get("amount"):
            clean_a = normalize_currency(item.get("amount"))
            if clean_a:
                item_sum += float(re.sub(r"[^\d.]", "", clean_a))

    if item_sum > 0 and tot_val:
        tot_num = normalize_currency(tot_val)
        if tot_num:
            t_amt = float(re.sub(r"[^\d.]", "", tot_num))
            if abs(item_sum - t_amt) > 0.05:
                warnings.append(f"Line item sum (${item_sum:,.2f}) mismatches total amount (${t_amt:,.2f})")

    reviewed = bool(data.get("manually_corrected") or data.get("reviewed"))
    blocking_missing = list(missing_critical)
    if reviewed:
        blocking_missing = [field for field in missing_critical if field not in REVIEW_OPTIONAL_CRITICAL]
    if reviewed and not blocking_missing:
        return DocumentStatus.COMPLETED, warnings, max(overall_confidence, 0.95)

    status = DocumentStatus.REVIEW if warnings else DocumentStatus.COMPLETED
    return status, warnings, overall_confidence


def validate_extraction_status(
    data: Optional[Dict[str, Any]] = None,
    confidence: Optional[float] = None,
    extracted: Optional[Dict[str, Any]] = None,
) -> Tuple[DocumentStatus, List[str]]:
    target = extracted if isinstance(extracted, dict) else (data if isinstance(data, dict) else {})
    target_copy = dict(target)

    conf = confidence if confidence is not None else target_copy.get("ocr_confidence", 0.85)

    if "field_confidence" not in target_copy or not target_copy["field_confidence"]:
        target_copy["field_confidence"] = {k: conf for k in target_copy.keys() if target_copy.get(k) is not None}
        target_copy["ocr_confidence"] = conf

    status, warnings, _ = validate_extraction_data(target_copy)
    return status, warnings


def normalize_freight_data(
    raw_data: Optional[Dict[str, Any]] = None,
    extracted: Optional[Dict[str, Any]] = None,
    raw_text: str = "",
    base_confidence: Optional[float] = None
) -> Dict[str, Any]:
    """Normalize extracted fields and calculate confidence & status."""
    source_data = extracted if extracted is not None else (raw_data or {})
    norm: Dict[str, Any] = {"document_type": "freight_bill"}

    for key in ALL_SCHEMA_FIELDS:
        val = source_data.get(key)
        if key == "invoice_number":
            norm[key] = None
        elif key in ("bill_number", "vehicle_number"):
            norm[key] = clean_identifier(val)
        elif key == "bill_date":
            norm[key] = normalize_date(val)
        elif key in ("freight_amount", "fuel_surcharge", "handling_charge", "total_amount"):
            norm[key] = normalize_currency(val)
        elif key == "weight":
            norm[key] = normalize_weight(val)
        elif key in ("origin", "destination"):
            loc = normalize_location(val)
            if loc and looks_like_ocr_junk(loc):
                loc = None
            norm[key] = loc
        elif key in ("consignor", "consignee", "carrier", "commodity_description", "driver_name"):
            cleaned = clean_field_value(val)
            cleaned = unglue_ocr_words(cleaned) if cleaned else None
            if cleaned and looks_like_ocr_junk(cleaned):
                cleaned = None
            if key == "driver_name" and cleaned and re.search(r"hours|miles|payroll", cleaned, re.IGNORECASE):
                cleaned = None
            norm[key] = cleaned
        elif key in ("pickup_time", "delivery_time"):
            norm[key] = normalize_clock_time(val)
        elif key == "special_instructions":
            cleaned = clean_field_value(val)
            if cleaned and len(re.sub(r"[^A-Za-z]", "", cleaned)) < 4:
                cleaned = None
            norm[key] = cleaned
        elif key == "quantity":
            norm[key] = clean_field_value(val)
        else:
            norm[key] = clean_field_value(val)

    if not norm.get("bill_date") and raw_text:
        norm["bill_date"] = parse_boxed_month_day_year(raw_text)

    left = re.sub(r"[^a-z0-9]+", "", str(norm.get("consignor") or "").lower())
    right = re.sub(r"[^a-z0-9]+", "", str(norm.get("consignee") or "").lower())
    if left and right and left == right:
        norm["consignee"] = None

    if source_data.get("manually_corrected"):
        norm["manually_corrected"] = True
    if source_data.get("reviewed"):
        norm["reviewed"] = True

    items = source_data.get("line_items") or []
    clean_items = []
    for item in items:
        if isinstance(item, dict):
            c_desc = clean_field_value(item.get("description"))
            has_load = any(item.get(k) for k in ("weight", "load_arrive", "load_depart", "unload_arrive", "unload_depart", "tag"))
            if c_desc or has_load:
                row = {
                    "item_no": str(item.get("item_no", len(clean_items) + 1)),
                    "description": c_desc,
                    "quantity": clean_field_value(item.get("quantity")),
                    "rate": normalize_currency(item.get("rate")),
                    "amount": normalize_currency(item.get("amount")),
                }
                if item.get("tag"):
                    row["tag"] = clean_field_value(item.get("tag"))
                if item.get("weight"):
                    row["weight"] = normalize_weight(item.get("weight"))
                for clock_key in ("load_arrive", "load_depart", "unload_arrive", "unload_depart"):
                    if item.get(clock_key):
                        row[clock_key] = normalize_clock_time(item.get(clock_key))
                clean_items.append(row)
    norm["line_items"] = clean_items

    if "field_metadata" in source_data:
        norm["field_metadata"] = source_data["field_metadata"]
    if "field_calibration" in source_data:
        norm["field_calibration"] = source_data["field_calibration"]
    if "consistency_checks" in source_data:
        norm["consistency_checks"] = source_data["consistency_checks"]

    field_confs = calculate_field_confidences(norm, raw_text=raw_text)
    norm["field_confidence"] = field_confs

    status, warnings, overall_conf = validate_extraction_data(norm)
    norm["status"] = status
    norm["validation_warnings"] = warnings
    norm["ocr_confidence"] = overall_conf

    return norm
