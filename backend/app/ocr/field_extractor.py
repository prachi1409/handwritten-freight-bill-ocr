"""Freight-bill field extraction from OCR text, entities, and form fields."""

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

# Map Document AI entity types / form labels onto the freight-bill schema.
_FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "bill_number": (
        "bill_number", "bill-number", "bill_no", "billno", "bill_num",
        "job_number", "job_no", "jobnumber",
        "manifest_number", "manifest_no",
        "bol_number", "bol", "bill_of_lading", "billoflading",
        "freight_bill_number", "lr_no", "waybill",
    ),
    "carrier": (
        "carrier", "carrier_name", "hauler", "trucking_company", "transporter",
    ),
    "invoice_number": (
        "invoice_number", "invoice_no", "invoice", "inv_number", "inv_no", "inv",
    ),
    "bill_date": (
        "bill_date", "invoice_date", "ship_date", "shipping_date", "date", "dated",
    ),
    "consignor": (
        "consignor", "shipper", "shipper_name", "sender", "from_party", "billed_from",
    ),
    "consignee": (
        "consignee", "consignee_name", "receiver", "recipient", "to_party", "billed_to",
    ),
    "origin": (
        "origin", "origin_location", "pickup", "pickup_location", "shipped_from", "source",
    ),
    "destination": (
        "destination", "destination_location", "delivery", "delivery_location",
        "deliver_at", "shipped_to",
    ),
    "commodity_description": (
        "commodity_description", "commodity", "cargo_description", "description_of_articles", "goods_description",
    ),
    "vehicle_number": (
        "vehicle_number", "vehicle_no", "truck_number", "truck_no", "truck",
        "lorry_no", "trailer_no",
    ),
    "weight": (
        "weight", "gross_weight", "net_weight", "total_weight", "wt",
    ),
    "quantity": (
        "quantity", "qty", "packages", "pallets",
    ),
    "freight_amount": (
        "freight_amount", "freight_charges", "freight",
    ),
    "total_amount": (
        "total_amount", "grand_total", "amount_payable", "total",
    ),
    "driver_name": (
        "driver_name", "driver", "operator",
    ),
    "pickup_time": (
        "pickup_time", "pickup_datetime", "time_in",
    ),
    "delivery_time": (
        "delivery_time", "delivery_datetime", "time_out",
    ),
    "special_instructions": (
        "special_instructions", "instructions", "notes", "remarks",
    ),
    "driver_signature": (
        "driver_signature", "driver_sig",
    ),
    "consignee_signature": (
        "consignee_signature", "received_by_signature", "receiver_sig",
    ),
    "received_datetime": (
        "received_datetime", "received_date", "receipt_date",
    ),
}

_ALIAS_TO_FIELD: Dict[str, str] = {}
for _field, _aliases in _FIELD_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_FIELD.setdefault(_alias, _field)


def _normalize_key(value: str) -> str:
    """Collapse a label or entity type to a lowercase underscore key."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned


def map_label_to_field(label: str) -> Optional[str]:
    """Map a Document AI entity type or form-field label to a freight schema key."""
    if not label:
        return None
    return _ALIAS_TO_FIELD.get(_normalize_key(label))


def _normalize_ocr_text(text: str) -> str:
    """Clean whitespace and OCR noise while preserving line boundaries."""
    if not text:
        return ""
    cleaned = text.replace("\xa0", " ").replace("\r\n", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def _extract_regex(text: str, pattern: str, multiline_fallback: Optional[str] = None) -> Optional[str]:
    """Return the first regex capture group, or None if not found."""
    if not text:
        return None
    match = re.search(pattern, text, re.IGNORECASE)
    if match and match.group(1).strip():
        return match.group(1).strip()

    if multiline_fallback:
        match_multi = re.search(multiline_fallback, text, re.IGNORECASE)
        if match_multi and match_multi.group(1).strip():
            return match_multi.group(1).strip()

    return None


def extract_freight_fields_from_text(raw_text: str) -> Dict[str, Any]:
    """Parse freight-bill fields from OCR text using label-oriented regex matching."""
    cleaned = _normalize_ocr_text(raw_text)

    bill_number = _extract_regex(
        cleaned,
        r"(?:Bill\s*(?:No|#|Num|Number)|Invoice\s*(?:No|#|Num|Number)|Manifest\s*(?:No|#|Num|Number)|Cargo\s*Manifest\s*(?:No|#|Num|Number)|Bill\s*of\s*Lading\s*(?:No|#|Num|Number)|BOL\s*(?:No|#|Num|Number)|B/L\s*(?:No|#|Num|Number)|Freight\s*Bill\s*(?:No|#|Num|Number)|LR\s*(?:No|#|Num|Number)|GR\s*(?:No|#|Num|Number)|Waybill\s*(?:No|#|Num|Number)|Job\s*(?:No|#|Num|Number)|Tracking\s*(?:No|#|Num|Number))\s*[:#\s-]*([A-Za-z0-9-]+)",
        r"(?:Cargo\s*Manifest|Manifest|Bill\s*of\s*Lading|BOL|B/L|Freight\s*Bill|Bill|LR|GR|Waybill)\s*[:#-]?\s*([A-Za-z0-9-]+)"
    )
    carrier = _extract_regex(
        cleaned,
        r"(?:Carrier|Carrier\s*Name|Hauler|Trucking\s*Company|Transporter)[\s\w()]*[:#\s-]*([^\n|]+)",
        r"(?:Carrier|Hauler)[\s\w()]*[:#\s-]*\n\s*([^\n|]+)"
    )
    invoice_number = _extract_regex(
        cleaned,
        r"(?:Invoice\s*(?:No|#|Num|Number)?|Inv\s*(?:No|#|Num|Number)?)\s*[:#\s-]*([A-Za-z0-9-]+)",
        r"(?:Invoice|Inv)\s*[:#\s-]*\n\s*([A-Za-z0-9-]+)"
    )
    bill_date = _extract_regex(
        cleaned,
        r"(?:Date|Bill\s*Date|Invoice\s*Date|Dated|Ship\s*Date|Shipping\s*Date)[\s:#]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}[/.-]\d{1,2}[/.-]\d{1,2})"
    )
    consignor = _extract_regex(
        cleaned,
        r"(?:Consignor|Shipper|Sender|From\s*Party|Billed\s*From|Shipper\s*Name)[\s\w()]*[:#\s-]*([^\n|]+)",
        r"(?:Consignor|Shipper|Sender|Shipper\s*Name)[\s\w()]*[:#\s-]*\n\s*([^\n|]+)"
    )
    consignee = _extract_regex(
        cleaned,
        r"(?:Consignee|Receiver|Recipient|To\s*Party|Billed\s*To|Consignee\s*Name)[\s\w()]*[:#\s-]*([^\n|]+)",
        r"(?:Consignee|Receiver|Recipient|Consignee\s*Name)[\s\w()]*[:#\s-]*\n\s*([^\n|]+)"
    )
    origin = _extract_regex(
        cleaned,
        r"(?:Origin|Pickup|From|Source|Loading\s*From|Shipped\s*From|Origin\s*Location)[\s\w()]*[:#\s-]*([^\n|]+)",
        r"(?:Origin|Pickup|Origin\s*Location)[\s\w()]*[:#\s-]*\n\s*([^\n|]+)"
    )
    destination = _extract_regex(
        cleaned,
        r"(?:Destination|Delivery|To|Deliver\s*At|Drop|Unloading\s*At|Shipped\s*To|Destination\s*Location)[\s\w()]*[:#\s-]*([^\n|]+)",
        r"(?:Destination|Delivery|Destination\s*Location)[\s\w()]*[:#\s-]*\n\s*([^\n|]+)"
    )
    commodity_description = _extract_regex(
        cleaned,
        r"(?:Commodity\s*Description|Commodity|Cargo\s*Description|Description\s*of\s*Articles)[\s\w()]*[:#\s-]*([^\n|]+)"
    )
    vehicle_number = _extract_regex(
        cleaned,
        r"(?:Vehicle\s*(?:No|#|Num|Number)?|Truck\s*(?:No|#|Num|Number)?|Lorry\s*(?:No|#|Num|Number)?|Trailer\s*(?:No|#|Num|Number)?)\s*[:#\s-]*([A-Za-z0-9#-]+)"
    )
    weight = _extract_regex(
        cleaned,
        r"(?:Weight|Gross\s*Weight|Net\s*Weight|Wt|Total\s*Weight)[\s:#]*([0-9,]+\s*(?:lbs|lb|kg|tons)?)"
    )
    quantity = _extract_regex(
        cleaned,
        r"(?:Quantity|Qty|Packages|No\.\s*of\s*Packages|Pallets|Boxes|Ctns|Pcs|Units)[\s:#]*([0-9,]+\s*(?:Pallets|Pallet|Units|Boxes|Ctns|Pcs)?)"
    )

    # Freight Amount vs Total Amount distinction
    freight_amount = _extract_regex(
        cleaned,
        r"(?:Freight\s*Amount|Freight\s*Charges|Freight)[\s:#]*([\$₹€£]?\s*[0-9,]+\.?\d*)"
    )
    total_amount = _extract_regex(
        cleaned,
        r"(?:Total\s*Amount|Grand\s*Total|Amount\s*Payable|Total)[\s:#]*([\$₹€£]?\s*[0-9,]+\.?\d*)"
    )

    driver_name = _extract_regex(
        cleaned,
        r"(?:Driver\s*Name|Driver|Operator)[\s\w()]*[:#\s-]*([^\n|]+)"
    )
    pickup_time = _extract_regex(
        cleaned,
        r"(?:Pickup\s*Time|Time\s*In|Pickup)[\s\w()]*[:#\s-]*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)"
    )
    delivery_time = _extract_regex(
        cleaned,
        r"(?:Delivery\s*Time|Time\s*Out|Delivery)[\s\w()]*[:#\s-]*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)"
    )
    special_instructions = _extract_regex(
        cleaned,
        r"(?:Special\s*Instructions|Instructions|Notes|Remarks)[\s\w()]*[:#\s-]*([^\n|]+)"
    )
    driver_signature = _extract_regex(
        cleaned,
        r"(?:Driver\s*Signature|Driver\s*Sig)[\s\w()]*[:#\s-]*([^\n|]+)"
    )
    consignee_signature = _extract_regex(
        cleaned,
        r"(?:Consignee\s*Signature|Received\s*By\s*Signature|Receiver\s*Sig)[\s\w()]*[:#\s-]*([^\n|]+)"
    )
    received_datetime = _extract_regex(
        cleaned,
        r"(?:Received\s*Date|Receipt\s*Date|Received\s*Time)[\s\w()]*[:#\s-]*([^\n|]+)"
    )

    line_items: List[Dict[str, Any]] = []
    HEADER_STOP_PHRASES = {"manifest", "cargo manifest", "cargo description", "freight bill", "bill of lading", "description"}
    item_matches = re.findall(
        r"(?:Item\s*\d+)[\s:]*([^\n|]+)",
        cleaned,
        re.IGNORECASE,
    )
    for idx, match_text in enumerate(item_matches):
        desc = match_text.strip()
        if desc and desc.lower() not in HEADER_STOP_PHRASES and not any(sp in desc.lower() for sp in ("cargo manifest", "freight bill & cargo")):
            line_items.append({
                "item_no": str(idx + 1),
                "description": desc,
                "quantity": quantity,
                "rate": None,
                "amount": freight_amount,
            })

    return {
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
        "line_items": line_items,
    }


def merge_structured_and_text_fields(
    structured: Dict[str, Any],
    raw_text: str,
) -> Dict[str, Any]:
    """Prefer Document AI structured values; fill gaps from regex over OCR text."""
    from_text = extract_freight_fields_from_text(raw_text)
    merged: Dict[str, Any] = {"document_type": "freight_bill"}
    for key in FREIGHT_FIELD_KEYS:
        structured_val = structured.get(key)
        if structured_val not in (None, "", []):
            merged[key] = structured_val
        else:
            merged[key] = from_text.get(key)

    structured_items = structured.get("line_items")
    if isinstance(structured_items, list) and structured_items:
        merged["line_items"] = structured_items
    else:
        merged["line_items"] = from_text.get("line_items") or []

    return merged
