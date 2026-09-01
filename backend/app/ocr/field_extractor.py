"""Freight-bill field extraction from OCR text, entities, and form fields with stacked multi-column layout support."""

import re
import unicodedata
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
        "carta_de_porte", "conocimiento_de_embarque", "guia", "numero_de_guia",
    ),
    "carrier": (
        "carrier", "carrier_name", "hauler", "trucking_company", "transporter",
        "transportista", "porteador",
    ),
    "invoice_number": (
        "invoice_number", "invoice_id", "invoice_no", "invoice", "inv_number", "inv_no", "inv",
    ),
    "bill_date": (
        "bill_date", "invoice_date", "ship_date", "shipping_date", "date", "dated",
    ),
    "consignor": (
        "consignor", "shipper", "shipper_name", "consignor_name", "sender", "from_party", "billed_from",
        "remitente", "expedidor", "cargador",
    ),
    "consignee": (
        "consignee", "receiver", "receiver_name", "consignee_name", "recipient", "to_party", "billed_to",
        "destinatario", "consignatario",
    ),
    "origin": (
        "origin", "place_of_receipt", "pickup_location", "origin_city", "from_location",
        "origen", "lugar_de_carga",
    ),
    "destination": (
        "destination", "place_of_delivery", "delivery_location", "dest_city", "to_location",
        "destino", "lugar_de_descarga",
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


def _fold_ocr_text(text: str) -> str:
    """Strip replacement chars and Latin accents. Keep Indic marks so Hindi IDs stay intact."""
    text = (text or "").replace("\ufffd", "")
    folded = []
    for ch in unicodedata.normalize("NFKD", text):
        if unicodedata.category(ch) == "Mn" and not (0x0900 <= ord(ch) <= 0x0DFF):
            continue
        folded.append(ch)
    return "".join(folded)


def _search_field(text: str, pattern: str) -> Optional[str]:
    """Return first regex group, allowing the value on the following line."""
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip()
    if not value or value in {":", "-", "—"}:
        return None
    if re.match(r"^\([^)]*\)?:?$", value):
        return None
    return value


def extract_fields_from_raw_text(raw_text: str) -> Dict[str, Any]:
    """Extract freight bill fields from raw OCR text using pattern matching."""
    res: Dict[str, Any] = {}
    if not raw_text:
        return res

    raw_text = _fold_ocr_text(raw_text)

    patterns = {
        "bill_number": r"(?:n\.?\s*[ºo°]?\s*de\s+factura|carta\s*de\s*porte|bill\s*number|bill\s*no\.?|bill\s*#|bol\s*no\.?|waybill|gu[ií]a(?:\s*n[úu]m(?:ero)?)?)[:.\s#]+([\w.\u0900-\u097F-]{3,})",
        "invoice_number": r"(?:n[úu]mero\s+de\s+factura|numero\s+de\s+factura|invoice\s*number|invoice\s*no\.?|inv\s*no\.?|inv\s*#)[:.\s#]+([\w.\u0900-\u097F-]{3,})",
        "bill_date": r"(?:date|dated|fecha)[:\s]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}[/.-]\d{1,2}[/.-]\d{1,2})",
        "consignor": r"(?:consignor|shipper|billed\s*from|remitente|expedidor)[:\s]*([^\n]+)",
        "consignee": r"(?:consignee|receiver|billed\s*to|destinatario|consignatario)[:\s]*([^\n]+)",
        "origin": r"(?:origin|pickup\s*loc|origen)[:\s]*([^\n]+)",
        "destination": r"(?:destination|delivery\s*loc|destino)[:\s]*([^\n]+)",
        "carrier": r"(?:carrier\s*name|carrier|hauler|transportista)[:\s]*([^\n]+)",
        "commodity_description": (
            r"(?:commodity\s*description|descripci[oó]n\s+de\s+la\s*mercanc[ií]a|"
            r"descripci[oó]n\s+de\s+la\s*\n\s*mercanc[ií]a)[:\s]*\n?\s*([^\n]+)"
        ),
        "quantity": r"(?:quantity|qty|cantidad)[:\s]*\n?\s*([0-9][0-9,]*)",
        "weight": r"(?:peso\s*\(lb\)|gross\s*wt|weight)[:\s]*\n?\s*([0-9][0-9,]*(?:\.\d+)?)",
        "freight_amount": (
            r"(?:importe\s+del\s+flete|freight\s*amount|freight\s*charges)"
            r"[^\n:]*[:\s]*\n?\s*([\$₹€£]?\s*[0-9][0-9,]*(?:\.\d+)?)"
        ),
        "fuel_surcharge": r"(?:fuel\s*surcharge|fuel\s*charge)[:\s]*\n?\s*([\$₹€£]?\s*[0-9,]+\.?\d*)",
        "handling_charge": r"(?:handling\s*charge|handling)[:\s]*\n?\s*([\$₹€£]?\s*[0-9,]+\.?\d*)",
        "total_amount": (
            r"(?:importe\s+total|total\s*amount|grand\s*total|total\s*a\s*pagar)"
            r"[^\n:]*[:\s]*\n?\s*([\$₹€£]?\s*[0-9][0-9,]*(?:\.\d+)?)"
        ),
        "vehicle_number": (
            r"(?:n[úu]mero\s+de\s+veh[ií]culo|numero\s+de\s+vehiculo|vehicle\s*number|truck\s*no)"
            r"[:\s]*\n?\s*#?\s*([\w.\u0900-\u097F-]{2,})"
        ),
        "driver_name": r"(?:nombre\s+del\s+conductor|driver\s*name|operator)[:\s]*\n?\s*([^\n]+)",
        "pickup_time": (
            r"(?:hora\s+de\s+recogida|pickup\s*time)[:\s]*\n?\s*"
            r"([0-9]{1,2}:[0-9]{2}\s*(?:a\.?\s*m\.?|p\.?\s*m\.?|AM|PM)?)"
        ),
        "delivery_time": (
            r"(?:hora\s+de\s+entrega|delivery\s*time)[:\s]*\n?\s*"
            r"([0-9]{1,2}:[0-9]{2}\s*(?:a\.?\s*m\.?|p\.?\s*m\.?|AM|PM)?)"
        ),
        "special_instructions": (
            r"(?:instrucciones\s+especiales|special\s*instructions|remarks)[:\s]*\n?\s*([^\n]+)"
        ),
        "driver_signature": r"(?:firma\s+del\s+conductor|driver\s*signature)[:\s]*\n?\s*([^\n]+)",
        "consignee_signature": (
            r"(?:firma\s+del\s+destinatario|consignee\s*signature|receiver\s*signature)"
            r"[^\n:]*(?:\n\s*\([^)]*\))?[:\s]*\n?\s*([^\n]+)"
        ),
        "received_datetime": (
            r"(?:fecha/?hora\s+de\s+recepci\w*|received\s*datetime|received\s*date)"
            r"[^\n:]*[:\s]*\n?\s*([^\n]+)"
        ),
    }

    for key, pat in patterns.items():
        value = _search_field(raw_text, pat)
        if not value:
            continue
        if key == "carrier" and any(b in value.upper() for b in BANNER_STOP_STRINGS):
            continue
        res[key] = value

    if not res.get("pickup_time") or not res.get("delivery_time"):
        time_pairs = re.findall(
            r"\b([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)\s*[/:-]\s*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)\b",
            raw_text,
        )
        if time_pairs:
            p_time, d_time = time_pairs[0]
            res.setdefault("pickup_time", p_time.strip())
            res.setdefault("delivery_time", d_time.strip())

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
