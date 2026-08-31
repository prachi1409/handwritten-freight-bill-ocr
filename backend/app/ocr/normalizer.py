"""Validation, Field Confidence, and Normalization layer for OCR extracted Freight Bill data."""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from app.db.models import DocumentStatus

logger = logging.getLogger(__name__)

# Stop words and label fragments that must never be treated as valid field values
INVALID_STOP_WORDS = {
    "HANDWRITTEN", "BILL", "NUMBER", "NO", "NUM", "INVOICE", "VEHICLE",
    "TRUCK", "DATE", "WEIGHT", "FREIGHT", "TOTAL", "AMOUNT", "N/A",
    "NONE", "NULL", "UNKNOWN", "CARGO", "ITEM", "VAL", "VALUE"
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


def clean_field_value(value: Optional[Any]) -> Optional[str]:
    """Clean text field value and reject generic stop words."""
    if value is None:
        return None
    val_str = str(value).strip()
    if not val_str:
        return None
    if val_str.upper() in INVALID_STOP_WORDS:
        return None
    return val_str


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

    if not cleaned or cleaned.upper() in INVALID_STOP_WORDS:
        return None

    if re.match(r"^[^a-zA-Z0-9]+$", cleaned):
        return None

    return cleaned


def normalize_currency(value: Optional[Any]) -> Optional[str]:
    """Normalize currency values to clean '$X,XXX.XX' format."""
    if value is None:
        return None
    val_str = str(value).strip()
    if not val_str or val_str.upper() in INVALID_STOP_WORDS:
        return None

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
    if not val_str or val_str.upper() in INVALID_STOP_WORDS:
        return None

    # 1. Try DD/MM/YYYY or MM/DD/YYYY or M/D/YY
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

    # 2. Try YYYY-MM-DD
    match_iso = re.search(r"\b(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})\b", val_str)
    if match_iso:
        year, month, day = int(match_iso.group(1)), int(match_iso.group(2)), int(match_iso.group(3))
        try:
            dt = datetime(year, month, day)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return val_str


def calculate_field_confidences(extracted: Dict[str, Any], raw_text: str = "") -> Dict[str, float]:
    """Calculate evidence-based field-level confidence scores (0.0 to 1.0) for every schema field."""
    confidences: Dict[str, float] = {}
    is_manual = bool(extracted.get("manually_corrected") or extracted.get("reviewed"))

    for field in ALL_SCHEMA_FIELDS:
        val = extracted.get(field)
        if val is None or str(val).strip() == "":
            confidences[field] = 0.0
            continue

        if is_manual:
            confidences[field] = 1.0
            continue

        val_str = str(val).strip()

        # Identifier confidence (bill_number, invoice_number, vehicle_number)
        if field in ("bill_number", "invoice_number", "vehicle_number"):
            if re.search(r"[A-Za-z0-9-]{3,}", val_str):
                confidences[field] = 0.95
            else:
                confidences[field] = 0.75
        # Date confidence
        elif field == "bill_date":
            if re.match(r"^\d{4}-\d{2}-\d{2}$", val_str):
                confidences[field] = 0.96
            else:
                confidences[field] = 0.80
        # Currency amounts
        elif field in ("freight_amount", "total_amount"):
            if re.match(r"^\$\d{1,3}(?:,\d{3})*\.\d{2}$", val_str):
                confidences[field] = 0.94
            else:
                confidences[field] = 0.82
        # Text fields
        else:
            if len(val_str) >= 3:
                confidences[field] = 0.90
            else:
                confidences[field] = 0.70

    return confidences


def normalize_freight_data(extracted: Dict[str, Any], raw_text: str = "", base_confidence: Optional[float] = None) -> Dict[str, Any]:
    """Normalize, clean, and compute field-level confidence for extracted freight bill dictionary.

    NOTE: Never copies freight_amount into total_amount. Missing fields remain None (null).
    """
    bill_number = clean_identifier(extracted.get("bill_number"))
    invoice_number = clean_identifier(extracted.get("invoice_number"))
    vehicle_number = clean_identifier(extracted.get("vehicle_number"))
    bill_date = normalize_date(extracted.get("bill_date"))

    carrier = clean_field_value(extracted.get("carrier"))
    consignor = clean_field_value(extracted.get("consignor"))
    consignee = clean_field_value(extracted.get("consignee"))
    origin = clean_field_value(extracted.get("origin"))
    destination = clean_field_value(extracted.get("destination"))
    commodity_description = clean_field_value(extracted.get("commodity_description"))
    weight = clean_field_value(extracted.get("weight"))
    quantity = clean_field_value(extracted.get("quantity"))

    driver_name = clean_field_value(extracted.get("driver_name"))
    pickup_time = clean_field_value(extracted.get("pickup_time"))
    delivery_time = clean_field_value(extracted.get("delivery_time"))
    special_instructions = clean_field_value(extracted.get("special_instructions"))
    driver_signature = clean_field_value(extracted.get("driver_signature"))
    consignee_signature = clean_field_value(extracted.get("consignee_signature"))
    received_datetime = clean_field_value(extracted.get("received_datetime"))

    freight_amount = normalize_currency(extracted.get("freight_amount"))
    total_amount = normalize_currency(extracted.get("total_amount"))

    # NEVER copy freight_amount to total_amount if total_amount is missing.
    # Total amount remains None (null) if not present on document.

    line_items = extracted.get("line_items", [])
    cleaned_items = []
    if isinstance(line_items, list):
        for idx, item in enumerate(line_items, start=1):
            if isinstance(item, dict):
                cleaned_items.append({
                    "item_no": str(item.get("item_no") or idx),
                    "description": clean_field_value(item.get("description")),
                    "quantity": clean_field_value(item.get("quantity")) or quantity,
                    "rate": normalize_currency(item.get("rate")),
                    "amount": normalize_currency(item.get("amount"))
                })

    data = {
        "document_type": "freight_bill",
        "bill_number": bill_number,
        "bill_date": bill_date,
        "carrier": carrier,
        "invoice_number": invoice_number,
        "consignor": consignor,
        "consignee": consignee,
        "origin": origin,
        "destination": destination,
        "commodity_description": commodity_description,
        "quantity": quantity,
        "weight": weight,
        "freight_amount": freight_amount,
        "total_amount": total_amount,
        "vehicle_number": vehicle_number,
        "driver_name": driver_name,
        "pickup_time": pickup_time,
        "delivery_time": delivery_time,
        "special_instructions": special_instructions,
        "driver_signature": driver_signature,
        "consignee_signature": consignee_signature,
        "received_datetime": received_datetime,
        "line_items": cleaned_items,
        "raw_text": raw_text
    }

    if extracted.get("manually_corrected") or extracted.get("reviewed"):
        data["manually_corrected"] = True
        data["reviewed"] = True
        data["reviewed_at"] = extracted.get("reviewed_at")

    field_confidences = calculate_field_confidences(data, raw_text=raw_text)

    # Calculate overall_confidence as mean of present fields
    present_confidences = [score for field, score in field_confidences.items() if data.get(field) is not None]
    if present_confidences:
        overall_conf = round(sum(present_confidences) / len(present_confidences), 2)
    else:
        overall_conf = 0.0

    data["ocr_confidence"] = overall_conf
    data["field_confidence"] = field_confidences

    return data


def validate_extraction_status(extracted: Dict[str, Any], confidence: float) -> Tuple[DocumentStatus, List[str]]:
    """Validate extracted freight bill dictionary and return appropriate DocumentStatus and validation warnings list."""
    warnings: List[str] = []

    if not extracted:
        return DocumentStatus.REVIEW, ["Document contains no extracted data."]

    is_reviewed = bool(extracted.get("manually_corrected") or extracted.get("reviewed"))
    if confidence < 0.70 and not is_reviewed:
        warnings.append(f"Low overall confidence ({confidence * 100:.1f}%)")

    # Required fields validation
    has_id = bool(extracted.get("bill_number") or extracted.get("invoice_number"))
    if not has_id:
        warnings.append("Missing Bill / Invoice Number")

    has_parties = bool(extracted.get("consignor") or extracted.get("consignee"))
    if not has_parties:
        warnings.append("Missing Consignor / Consignee")

    has_locations = bool(extracted.get("origin") or extracted.get("destination"))
    if not has_locations:
        warnings.append("Missing Origin / Destination")

    freight_amt = extracted.get("freight_amount")
    total_amt = extracted.get("total_amount")
    if not total_amt and not freight_amt:
        warnings.append("Missing Total Amount")

    # Financial consistency checks
    if freight_amt and total_amt:
        try:
            f_val = float(re.sub(r"[^\d.]", "", str(freight_amt)))
            t_val = float(re.sub(r"[^\d.]", "", str(total_amt)))
            if f_val > t_val:
                warnings.append(f"Financial inconsistency: Freight amount ({freight_amt}) exceeds total amount ({total_amt})")
        except Exception:
            pass

    # Line item math consistency
    line_items = extracted.get("line_items", [])
    if isinstance(line_items, list) and len(line_items) > 1 and total_amt:
        line_sums = 0.0
        for item in line_items:
            amt_str = item.get("amount")
            if amt_str:
                m = re.search(r"[\$₹€£]?\s*([\d,]+\.?\d*)", str(amt_str))
                if m:
                    try:
                        line_sums += float(m.group(1).replace(",", ""))
                    except ValueError:
                        pass
        total_num = 0.0
        m_tot = re.search(r"[\$₹€£]?\s*([\d,]+\.?\d*)", str(total_amt))
        if m_tot:
            try:
                total_num = float(m_tot.group(1).replace(",", ""))
            except ValueError:
                pass
        if line_sums > 0 and total_num > 0 and abs(line_sums - total_num) > 1.0:
            warnings.append(f"Line item sum (${line_sums:,.2f}) does not match total amount ({total_amt})")

    if warnings:
        return DocumentStatus.REVIEW, warnings

    return DocumentStatus.COMPLETED, []
