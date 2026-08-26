"""Validation and Normalization layer for OCR extracted Freight Bill data."""

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

    # Remove embedded prefixes like "Bill No:", "Invoice No:", "Vehicle #: ", "Bill #:"
    # Use word boundary \b so "INV-HB-5821" preserves "INV-" prefix!
    cleaned = re.sub(
        r"^(?:cargo\s*manifest\b\s*(?:no|number)?|manifest\b\s*(?:no|number)?|bill\s*of\s*lading\b\s*(?:no|number)?|bol\b\s*(?:no|number)?|bill\b\s*(?:no|number)?|invoice\b\s*(?:no|number)?|inv\b\s*(?:no|number)?|vehicle\b\s*(?:no|number)?|truck\b\s*(?:no|number)?)\s*[:#\s]+",
        "",
        raw,
        flags=re.IGNORECASE
    ).strip()

    if not cleaned or cleaned.upper() in INVALID_STOP_WORDS:
        return None

    # Ensure identifier doesn't consist solely of punctuation or single stop word
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

    # Match numeric amounts with optional currency symbol
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

    # 1. Try DD/MM/YYYY or MM/DD/YYYY
    match_slash = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", val_str)
    if match_slash:
        p1, p2, year = int(match_slash.group(1)), int(match_slash.group(2)), int(match_slash.group(3))
        if p1 > 12:
            day, month = p1, p2
        elif p2 > 12:
            day, month = p2, p1
        else:
            day, month = p1, p2
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


def normalize_freight_data(extracted: Dict[str, Any], raw_text: str = "", base_confidence: float = 0.95) -> Dict[str, Any]:
    """Normalize, clean, and validate extracted freight bill dictionary."""

    bill_number = clean_identifier(extracted.get("bill_number"))
    invoice_number = clean_identifier(extracted.get("invoice_number"))
    vehicle_number = clean_identifier(extracted.get("vehicle_number"))
    bill_date = normalize_date(extracted.get("bill_date"))

    consignor = clean_field_value(extracted.get("consignor"))
    consignee = clean_field_value(extracted.get("consignee"))
    origin = clean_field_value(extracted.get("origin"))
    destination = clean_field_value(extracted.get("destination"))
    weight = clean_field_value(extracted.get("weight"))
    quantity = clean_field_value(extracted.get("quantity"))

    freight_amount = normalize_currency(extracted.get("freight_amount"))
    total_amount = normalize_currency(extracted.get("total_amount"))

    if freight_amount and not total_amount:
        total_amount = freight_amount

    line_items = extracted.get("line_items", [])
    if isinstance(line_items, list):
        cleaned_items = []
        for item in line_items:
            if isinstance(item, dict):
                cleaned_items.append({
                    "item_no": str(item.get("item_no", "1")),
                    "description": clean_field_value(item.get("description")),
                    "quantity": clean_field_value(item.get("quantity")) or quantity,
                    "rate": normalize_currency(item.get("rate")),
                    "amount": normalize_currency(item.get("amount")) or freight_amount
                })
        line_items = cleaned_items

    # Compute dynamic field-level extraction confidence score
    key_fields = [
        bill_number, invoice_number, bill_date, consignor, consignee,
        origin, destination, vehicle_number, weight, quantity, freight_amount, total_amount
    ]
    valid_count = sum(1 for f in key_fields if f is not None)

    is_reviewed = bool(extracted.get("manually_corrected") or extracted.get("reviewed"))

    if is_reviewed:
        # High confidence for manually reviewed & corrected fields
        calc_confidence = round(min(1.0, max(0.85, (valid_count / len(key_fields)))), 2)
    elif not raw_text or not raw_text.strip():
        calc_confidence = 0.0
    else:
        completion_ratio = valid_count / len(key_fields)
        calc_confidence = round(min(1.0, max(0.0, base_confidence * completion_ratio)), 2)

    res = {
        "document_type": "freight_bill",
        "bill_number": bill_number,
        "invoice_number": invoice_number,
        "bill_date": bill_date,
        "consignor": consignor,
        "consignee": consignee,
        "origin": origin,
        "destination": destination,
        "vehicle_number": vehicle_number,
        "weight": weight,
        "quantity": quantity,
        "freight_amount": freight_amount,
        "total_amount": total_amount,
        "ocr_confidence": calc_confidence,
        "line_items": line_items,
        "raw_text": raw_text
    }

    if is_reviewed:
        res["manually_corrected"] = True
        res["reviewed"] = True
        res["reviewed_at"] = extracted.get("reviewed_at")

    return res


def validate_extraction_status(extracted: Dict[str, Any], confidence: float) -> Tuple[DocumentStatus, Optional[str]]:
    """Validate extracted freight bill dictionary and return appropriate DocumentStatus and review reasons."""
    if not extracted:
        return DocumentStatus.REVIEW, "Document contains no extracted data."

    missing_reasons = []

    # 1. Check confidence threshold (skip if manually reviewed & corrected by operator)
    is_reviewed = bool(extracted.get("manually_corrected") or extracted.get("reviewed"))
    if confidence < 0.70 and not is_reviewed:
        missing_reasons.append(f"Low confidence ({confidence * 100:.1f}%)")

    # 2. Check critical identifiers
    has_id = bool(extracted.get("bill_number") or extracted.get("invoice_number"))
    if not has_id:
        missing_reasons.append("Missing Bill/Invoice Number")

    # 3. Check parties & location info
    has_parties = bool(extracted.get("consignor") or extracted.get("consignee"))
    if not has_parties:
        missing_reasons.append("Missing consignor/consignee")

    has_locations = bool(extracted.get("origin") or extracted.get("destination"))
    if not has_locations:
        missing_reasons.append("Missing origin/destination")

    # 4. Check financial fields
    freight_amt = extracted.get("freight_amount")
    total_amt = extracted.get("total_amount")
    if not freight_amt and not total_amt:
        missing_reasons.append("Missing total amount")

    # 5. Check line items vs total amount consistency if multiple line items exist
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
            missing_reasons.append(f"Line item amount sum (${line_sums:,.2f}) does not match total amount ({total_amt})")

    # 6. Count valid extracted fields out of 12
    key_fields = [
        "bill_number", "invoice_number", "bill_date", "consignor", "consignee",
        "origin", "destination", "vehicle_number", "weight", "quantity", "freight_amount", "total_amount"
    ]
    valid_count = sum(1 for k in key_fields if extracted.get(k) is not None)
    if valid_count < 4:
        missing_reasons.append(f"Only {valid_count}/12 fields extracted")

    if missing_reasons:
        msg = f"Document flagged for manual review: {'; '.join(missing_reasons)}."
        return DocumentStatus.REVIEW, msg

    return DocumentStatus.COMPLETED, None
