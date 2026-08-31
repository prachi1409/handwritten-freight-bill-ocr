"""Freight-bill field extraction from OCR text, entities, and form fields with stacked multi-column layout support."""

import re
from typing import Any, Dict, List, Optional, Tuple

FREIGHT_FIELD_KEYS = (
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

_FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "bill_number": (
        "bill_number", "purchase_order", "po_number", "bill-number", "bill_no", "billno", "bill_num",
        "job_number", "job_no", "jobnumber",
        "manifest_number", "manifest_no",
        "bol_number", "bol", "bill_of_lading", "billoflading",
        "freight_bill_number", "lr_no", "waybill",
    ),
    "carrier": (
        "carrier", "carrier_name", "hauler", "trucking_company", "transporter",
    ),
    "invoice_number": (
        "invoice_number", "invoice_id", "invoice_no", "invoice", "inv_number", "inv_no", "inv",
    ),
    "bill_date": (
        "bill_date", "invoice_date", "ship_date", "shipping_date", "date", "dated",
    ),
    "consignor": (
        "consignor", "shipper", "shipper_name", "consignor_name", "sender", "from_party", "billed_from",
    ),
    "consignee": (
        "consignee", "receiver", "receiver_name", "consignee_name", "recipient", "to_party", "billed_to",
    ),
    "origin": (
        "origin", "place_of_receipt", "pickup_location", "origin_city", "from_location",
    ),
    "destination": (
        "destination", "place_of_delivery", "delivery_location", "dest_city", "to_location",
    ),
    "commodity_description": (
        "commodity_description", "commodity", "cargo_description", "goods_description",
        "description_of_goods", "description", "item_description",
    ),
    "quantity": (
        "quantity", "no_of_packages", "packages", "units", "qty", "total_quantity",
    ),
    "weight": (
        "weight", "gross_weight", "total_weight", "net_weight", "wt", "charged_weight",
    ),
    "freight_amount": (
        "freight_amount", "freight_charges", "freight_charge", "freight_rate", "freight_cost",
    ),
    "fuel_surcharge": (
        "fuel_surcharge", "fuel_surcharge_amount", "fuel_charge", "fuel",
    ),
    "handling_charge": (
        "handling_charge", "handling_amount", "handling",
    ),
    "total_amount": (
        "total_amount", "total", "total_charge", "net_amount", "invoice_total",
        "amount_due", "grand_total",
    ),
    "vehicle_number": (
        "vehicle_number", "vehicle_no", "truck_number", "truck_no", "trailer_no",
        "container_no", "vehicle_id", "lorry_no",
    ),
    "driver_name": (
        "driver_name", "driver", "operator", "driver_id",
    ),
    "pickup_time": (
        "pickup_time", "pickup_datetime", "time_in", "gate_in",
    ),
    "delivery_time": (
        "delivery_time", "delivery_datetime", "time_out", "gate_out",
    ),
    "special_instructions": (
        "special_instructions", "instructions", "remarks", "notes", "handling_instructions",
    ),
    "driver_signature": (
        "driver_signature", "driver_sig",
    ),
    "consignee_signature": (
        "consignee_signature", "receiver_signature", "consignee_sig",
    ),
    "received_datetime": (
        "received_datetime", "received_date", "delivered_at",
    ),
}

BANNER_STOP_STRINGS = (
    "FREIGHT BILL", "BILL OF LADING", "FREIGHT MANIFEST", "CARRIER BILL",
    "BILL OF LADING & RECEIPT", "FREIGHT MANIFEST & BILL OF LADING",
    "FREIGHT BILL & CARGO MANIFEST", "CARRIER FREIGHT MANIFEST"
)


def normalize_label(label: str) -> str:
    """Lowercase and convert non-alphanumeric characters to underscores."""
    s = str(label or "").strip().lower()
    s = re.sub(r"[^\w]+", "_", s)
    return s.strip("_")


def map_label_to_field(label: str) -> Optional[str]:
    """Map a raw label or entity type string to a schema field name."""
    norm = normalize_label(label)
    if not norm:
        return None

    if norm in FREIGHT_FIELD_KEYS:
        return norm

    for field_key, aliases in _FIELD_ALIASES.items():
        if norm in aliases:
            return field_key

    for field_key, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in norm or norm in alias:
                return field_key

    return None


def extract_fields_from_raw_text(raw_text: str) -> Dict[str, Any]:
    """Extract freight bill fields from raw OCR text using pattern matching."""
    res: Dict[str, Any] = {}
    if not raw_text:
        return res

    patterns = {
        "bill_number": r"(?:bill\s*no|bill\s*#|bol\s*no|waybill)[:\s]*([A-Za-z0-9-]+)",
        "invoice_number": r"(?:invoice\s*no|inv\s*no|inv\s*#)[:\s]*([A-Za-z0-9-]+)",
        "bill_date": r"(?:date|dated)[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}[/.-]\d{1,2}[/.-]\d{1,2})",
        "consignor": r"(?:consignor|shipper|billed\s*from)[:\s]*([^\n]+)",
        "consignee": r"(?:consignee|receiver|billed\s*to)[:\s]*([^\n]+)",
        "origin": r"(?:origin|pickup\s*loc)[:\s]*([^\n]+)",
        "destination": r"(?:destination|delivery\s*loc)[:\s]*([^\n]+)",
        "carrier": r"(?:carrier\s*name|carrier|hauler)[:\s]*([^\n]+)",
        "commodity_description": r"(?:commodity\s*description|commodity|cargo\s*desc)[:\s]*([^\n]+)",
        "quantity": r"(?:quantity|qty)[:\s]*([^\n]+)",
        "weight": r"(?:weight|gross\s*wt)[:\s]*([^\n]+)",
        "freight_amount": r"(?:freight\s*amount|freight)[:\s]*([\$₹€£]?\s*[\d,]+\.?\d*)",
        "fuel_surcharge": r"(?:fuel\s*surcharge|fuel\s*charge)[:\s]*([\$₹€£]?\s*[\d,]+\.?\d*)",
        "handling_charge": r"(?:handling\s*charge|handling)[:\s]*([\$₹€£]?\s*[\d,]+\.?\d*)",
        "total_amount": r"(?:total\s*amount|total)[:\s]*([\$₹€£]?\s*[\d,]+\.?\d*)",
        "vehicle_number": r"(?:vehicle\s*number|vehicle|truck\s*no)[:\s]*([A-Za-z0-9-]+)",
        "driver_name": r"(?:driver\s*name|driver|operator)[:\s]*([^\n]+)",
        "special_instructions": r"(?:special\s*instructions|remarks)[:\s]*([^\n]+)",
    }

    for key, pat in patterns.items():
        match = re.search(pat, raw_text, re.IGNORECASE)
        if match:
            v = match.group(1).strip()
            if key == "carrier" and any(b in v.upper() for b in BANNER_STOP_STRINGS):
                continue
            res[key] = v

    # Extract paired Pickup / Delivery times
    time_pairs = re.findall(r"\b([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)\s*[/:-]\s*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)\b", raw_text)
    if time_pairs:
        p_time, d_time = time_pairs[0]
        res["pickup_time"] = p_time.strip()
        res["delivery_time"] = d_time.strip()
    else:
        p_match = re.search(r"(?:pickup\s*time|pickup)[:\s]*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)", raw_text, re.IGNORECASE)
        d_match = re.search(r"(?:delivery\s*time|delivery)[:\s]*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)", raw_text, re.IGNORECASE)
        if p_match:
            res["pickup_time"] = p_match.group(1).strip()
        if d_match:
            res["delivery_time"] = d_match.group(1).strip()

    return res


extract_freight_fields_from_text = extract_fields_from_raw_text


def merge_structured_and_text_fields(
    structured: Dict[str, Any], raw_text: str
) -> Dict[str, Any]:
    """Merge extracted entity fields with text-fallback regex extractions."""
    out = dict(structured)
    text_fields = extract_fields_from_raw_text(raw_text)

    for k, v in text_fields.items():
        if v and not out.get(k):
            out[k] = v

    return out
