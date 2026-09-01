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
    "SPECIALINSTRUCTIONS", "DRIVERNAME", "COMMODITYDESCRIPTION", "COMODTVDESCRPTON", "PICKUPIDELIVERYTIME",
    "EREGHTAMOUNT", "DESTNATON", "NVOICE", "NOMBER", "NVOICENOMBER", "MANIFEST", "BILL OF LADING",
    "DE", "DEL", "LA", "EL", "LOS", "LAS", "OF", "THE", "AND",
}

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
    "invoice_number",
    "consignor",
    "consignee",
    "origin",
    "destination",
    "freight_amount",
    "total_amount",
)


def is_invalid_label_value(val: str) -> bool:
    """True if string is purely a form label header."""
    if not val:
        return True
    clean = re.sub(r"[^A-Za-z]+", "", str(val).upper())
    if not clean:
        return False
    return clean in EXACT_LABEL_STOP_WORDS


def clean_field_value(value: Optional[Any]) -> Optional[str]:
    """Clean text field value and reject generic stop words and label headers."""
    if value is None:
        return None
    val_str = str(value).strip()
    if not val_str or is_invalid_label_value(val_str):
        return None
    return val_str


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

    if not cleaned or is_invalid_label_value(cleaned):
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
    if not val_str or is_invalid_label_value(val_str):
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

    return val_str


def normalize_location(value: Optional[Any]) -> Optional[str]:
    """Normalize city/state location string spacing (e.g. 'Columbus,OH' -> 'Columbus, OH')."""
    cleaned = clean_field_value(value)
    if not cleaned:
        return None
    cleaned = re.sub(r"([A-Za-z]+),([A-Za-z]{2})\b", r"\1, \2", cleaned)
    return cleaned


def normalize_weight(value: Optional[Any]) -> Optional[str]:
    """Normalize weight string unit artifacts (e.g. '32,450los' -> '32,450 lbs', '14.920lbs' -> '14,920 lbs')."""
    cleaned = clean_field_value(value)
    if not cleaned:
        return None

    cleaned = re.sub(r"(\d+)\.(\d{3})(?=[a-zA-Z\s]|$)", r"\1,\2", cleaned)
    cleaned = re.sub(r"(\d+(?:,\d{3})*)\s*(?:lbs|los|1os|Ibs|LBS|Ib)\b", r"\1 lbs", cleaned, flags=re.IGNORECASE)

    return cleaned


def calculate_field_confidences(extracted: Dict[str, Any], raw_text: str = "") -> Dict[str, float]:
    """Calculate evidence-based field-level confidence scores (0.0 to 1.0) for every schema field."""
    confidences: Dict[str, float] = {}
    is_manual = bool(extracted.get("manually_corrected") or extracted.get("reviewed"))
    raw_meta = extracted.get("field_metadata") or {}

    for field in ALL_SCHEMA_FIELDS:
        val = extracted.get(field)
        if val is None or str(val).strip() == "" or is_invalid_label_value(str(val)):
            confidences[field] = 0.0
            continue

        if is_manual:
            confidences[field] = 1.0
            continue

        if field in raw_meta and isinstance(raw_meta[field], dict) and "confidence" in raw_meta[field]:
            conf = float(raw_meta[field]["confidence"])
            conf = min(max(conf, 0.50), 0.98)
            confidences[field] = round(conf, 2)
            continue

        base_score = 0.85
        val_str = str(val).strip()

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

        confidences[field] = round(base_score, 2)

    return confidences


def validate_extraction_data(data: Dict[str, Any]) -> Tuple[DocumentStatus, List[str], float]:
    """Validate extraction completeness, financial balance, and strict 8 critical field presence."""
    warnings: List[str] = []
    field_confs = data.get("field_confidence", {})

    present_confs = [c for f, c in field_confs.items() if c > 0.0 and data.get(f) is not None]
    overall_confidence = (sum(present_confs) / len(present_confs)) if present_confs else 0.0
    overall_confidence = round(overall_confidence, 2)

    missing_critical = [f for f in CRITICAL_FIELDS if not data.get(f) or is_invalid_label_value(str(data.get(f)))]

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

    if (data.get("manually_corrected") or data.get("reviewed")) and not missing_critical:
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
        if key in ("bill_number", "invoice_number", "vehicle_number"):
            norm[key] = clean_identifier(val)
        elif key == "bill_date":
            norm[key] = normalize_date(val)
        elif key in ("freight_amount", "fuel_surcharge", "handling_charge", "total_amount"):
            norm[key] = normalize_currency(val)
        elif key == "weight":
            norm[key] = normalize_weight(val)
        elif key in ("origin", "destination"):
            norm[key] = normalize_location(val)
        elif key in ("consignor", "consignee", "carrier", "commodity_description", "driver_name", "special_instructions", "quantity", "pickup_time", "delivery_time"):
            norm[key] = clean_field_value(val)
        else:
            norm[key] = clean_field_value(val)

    if source_data.get("manually_corrected"):
        norm["manually_corrected"] = True
    if source_data.get("reviewed"):
        norm["reviewed"] = True

    items = source_data.get("line_items") or []
    clean_items = []
    for item in items:
        if isinstance(item, dict):
            c_desc = clean_field_value(item.get("description"))
            if c_desc:
                clean_items.append({
                    "item_no": str(item.get("item_no", len(clean_items) + 1)),
                    "description": c_desc,
                    "quantity": clean_field_value(item.get("quantity")),
                    "rate": normalize_currency(item.get("rate")),
                    "amount": normalize_currency(item.get("amount")),
                })
    norm["line_items"] = clean_items

    if "field_metadata" in source_data:
        norm["field_metadata"] = source_data["field_metadata"]

    field_confs = calculate_field_confidences(norm, raw_text=raw_text)
    norm["field_confidence"] = field_confs

    status, warnings, overall_conf = validate_extraction_data(norm)
    norm["status"] = status
    norm["validation_warnings"] = warnings
    norm["ocr_confidence"] = overall_conf

    return norm
