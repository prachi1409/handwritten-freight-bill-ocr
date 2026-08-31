"""Spatial OCR Extraction Module using Bounding Box Geometry and Proximity Analysis."""

import re
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Label aliases and regex patterns for spatial matching
LABEL_PATTERNS = {
    "bill_number": [r"bill\s*no", r"bill\s*num", r"bill\s*#", r"bol\s*no", r"waybill"],
    "invoice_number": [r"invoice\s*num", r"invoice\s*no", r"inv\s*no", r"inv\s*#"],
    "bill_date": [r"date", r"dated", r"ship\s*date"],
    "consignor": [r"consignor", r"shipper", r"billed\s*from"],
    "consignee": [r"consignee", r"receiver", r"billed\s*to"],
    "origin": [r"origin", r"pickup\s*loc"],
    "destination": [r"destnaton", r"destination", r"delivery\s*loc"],
    "vehicle_number": [r"vehicle", r"truck\s*no"],
    "weight": [r"weight", r"gross\s*wt", r"weght"],
    "carrier": [r"carrier\s*name\b", r"carrier\b", r"hauler", r"transporter"],
    "commodity_description": [r"commodity\s*description", r"commodity", r"comodtv", r"cargo\s*desc"],
    "quantity": [r"quantity", r"qty", r"ouantty", r"pallets"],
    "driver_name": [r"driver", r"operator"],
    "pickup_time": [r"pickup\s*time", r"pickup"],
    "delivery_time": [r"delivery\s*time", r"delivery"],
    "freight_amount": [r"ereghtamount", r"freight\s*amount", r"freight\s*charges"],
    "fuel_surcharge": [r"fuel\s*surcharge", r"fuel\s*charge"],
    "handling_charge": [r"handling\s*charge", r"handling"],
    "total_amount": [r"total\s*amount", r"grand\s*total"],
    "special_instructions": [r"special", r"instructions", r"remarks"],
}

LABEL_STOP_WORDS = {
    "CONSIGNOR", "SHIPPER", "CONSIGNEE", "RECEIVER", "BILL", "NO", "NUMBER",
    "INVOICE", "NVOICE", "NOMBER", "NVOICENOMBER", "DATE", "ORIGIN", "DESTNATON", "DESTINATION", "VEHICLE", "WEIGHT", "WEGHT", "CARRIER",
    "COMMODITY", "COMODTVDESCRPTON", "COMMODITYDESCRIPTION", "QUANTITY", "OUANTTY", "DRIVER", "DRIVERNAME",
    "PICKUP", "DELIVERY", "TIME", "PICKUPIDELIVERYTIME", "FREIGHT", "EREGHTAMOUNT", "AMOUNT",
    "TOTAL", "SPECIAL", "SPECIALNSTRUCTIONS", "INSTRUCTIONS", "HANDWRITTEN", "MANIFEST", "CARGO",
    "NAME", "DESCRIPTION", "LOCATION", "RECIEVER", "LADING", "BILL OF LADING", "FREIGHT BILL"
}

BANNER_HEADER_WORDS = {
    "FREIGHT MANIFEST & CARRIERBILL", "FREIGHT MANIFEST & BILL OF LADING",
    "CARRIER FREIGHT MANIFEST", "FREIGHT BILL & CARGO MANIFEST", "FREIGHT MANIFEST",
    "BILL OF LADING", "FREIGHT BILL", "CARRIER BILL", "BILL OF LADING & RECEIPT"
}


def is_label_text(text: str) -> bool:
    """Check if string is purely a label header or stop word."""
    if not text:
        return True
    clean = re.sub(r"[^A-Za-z]+", "", text.upper())
    if not clean:
        return False
    if clean in LABEL_STOP_WORDS:
        return True
    if any(sw in clean for sw in ("CONSIGNOR", "CONSIGNEE", "BILLNO", "INVOICENUMBER", "NVOICENOMBER", "VEHICLENUMBER", "FREIGHTAMOUNT", "TOTALAMOUNT", "SPECIALINSTRUCTIONS", "DRIVERNAME")):
        return True
    return False


def is_banner_header(text: str) -> bool:
    """True if string is form title/banner text like 'FREIGHT MANIFEST & BILL OF LADING'."""
    if not text:
        return False
    clean = text.strip().upper()
    if clean in BANNER_HEADER_WORDS or "MANIFEST &" in clean or "BILL OF LADING" in clean:
        return True
    return False


def clean_spatial_value(val: Optional[str]) -> Optional[str]:
    """Clean spatial candidate value and reject any label words."""
    if not val:
        return None
    cleaned = str(val).strip()
    cleaned = re.sub(r"^[:# \t.-]+|[:# \t.-]+$", "", cleaned).strip()
    if not cleaned or is_label_text(cleaned) or is_banner_header(cleaned):
        return None
    return cleaned


def extract_fields_via_spatial_layout(ocr_items: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Perform bounding box spatial extraction.
    Returns (extracted_fields_dict, field_metadata_dict).
    """

    labels_found: Dict[str, Dict[str, Any]] = {}
    value_candidates: List[Dict[str, Any]] = []

    for item in ocr_items:
        text = item["text"].strip()
        if is_banner_header(text):
            continue

        matched_label_key = None
        for key, patterns in LABEL_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, text, re.IGNORECASE):
                    matched_label_key = key
                    break
            if matched_label_key:
                break

        if matched_label_key and (is_label_text(text) or ":" in text or "AMOUNT" in text.upper() or "NAME" in text.upper()):
            if matched_label_key not in labels_found:
                labels_found[matched_label_key] = item
        elif not is_label_text(text) and not is_banner_header(text):
            value_candidates.append(item)

    extracted_fields: Dict[str, Any] = {}
    field_metadata: Dict[str, Any] = {}

    # Extract Carrier company name from top header area (y <= 150)
    for cand in ocr_items:
        txt = cand["text"].strip()
        if is_banner_header(txt) or is_label_text(txt):
            continue
        c_min_x, c_min_y, c_max_x, c_max_y = cand["bbox"]
        if c_min_y <= 150 and len(txt) >= 4 and not any(kw in txt.upper() for kw in ("MANIFEST", "LADING", "BILL OF", "CONSIGNEE", "SHIPPER")):
            # Check if value is a company name like Summit Line Haul LLC or Apex Freight Carriers
            if any(term in txt.upper() for term in ("LLC", "INC", "CORP", "CARRIERS", "HAUL", "LOGISTICS", "TRANSPORT", "FREIGHT", "EXPRESS")):
                extracted_fields["carrier"] = txt
                field_metadata["carrier"] = {
                    "value": txt,
                    "confidence": round(cand["conf"], 3),
                    "source_text": txt,
                    "source_location": cand["bbox"]
                }
                break

    for label_key, label_item in labels_found.items():
        if label_key == "carrier" and "carrier" in extracted_fields:
            continue

        l_min_x, l_min_y, l_max_x, l_max_y = label_item["bbox"]
        l_cx, l_cy = label_item["center_x"], label_item["center_y"]
        l_h, l_w = label_item["height"], label_item["width"]

        same_line_candidates = []
        below_candidates = []

        for cand in value_candidates:
            c_min_x, c_min_y, c_max_x, c_max_y = cand["bbox"]
            c_cx, c_cy = cand["center_x"], cand["center_y"]

            # Filter candidates for pickup_time / delivery_time to strictly match time format
            if label_key in ("pickup_time", "delivery_time"):
                if not re.search(r"\b[0-9]{1,2}:[0-9]{2}\b", cand["text"]):
                    continue

            if abs(c_cy - l_cy) <= max(l_h * 1.5, 35.0) and c_min_x >= l_min_x - 20:
                dist_x = c_min_x - l_max_x
                same_line_candidates.append((dist_x, cand))

            if c_min_y >= l_max_y - 15 and (c_min_y - l_max_y) <= max(l_h * 4.0, 180.0):
                if abs(c_min_x - l_min_x) <= max(l_w, 350.0):
                    dist_y = c_min_y - l_max_y
                    dist_x = abs(c_min_x - l_min_x)
                    below_candidates.append((dist_y + dist_x * 0.5, cand))

        same_line_candidates.sort(key=lambda x: x[0])
        below_candidates.sort(key=lambda x: x[0])

        best_value = None
        best_cand_item = None

        if same_line_candidates and (label_key in ("freight_amount", "fuel_surcharge", "handling_charge", "total_amount", "bill_number", "invoice_number", "bill_date", "pickup_time", "delivery_time") or not below_candidates):
            for _, cand in same_line_candidates:
                v = clean_spatial_value(cand["text"])
                if v:
                    best_value = v
                    best_cand_item = cand
                    break

        if not best_value and below_candidates:
            for _, cand in below_candidates:
                v = clean_spatial_value(cand["text"])
                if v:
                    best_value = v
                    best_cand_item = cand
                    break

        if best_value and best_cand_item:
            extracted_fields[label_key] = best_value
            field_metadata[label_key] = {
                "value": best_value,
                "confidence": round(best_cand_item["conf"], 3),
                "source_text": best_cand_item["text"],
                "source_location": best_cand_item["bbox"],
            }

    # Extract paired Pickup / Delivery times if present in a single candidate string
    for cand in value_candidates:
        txt = cand["text"].strip()
        times = re.findall(r"\b([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)\b", txt)
        if len(times) >= 2:
            if "pickup_time" not in extracted_fields:
                extracted_fields["pickup_time"] = times[0]
                field_metadata["pickup_time"] = {"value": times[0], "confidence": round(cand["conf"], 3), "source_text": txt, "source_location": cand["bbox"]}
            if "delivery_time" not in extracted_fields:
                extracted_fields["delivery_time"] = times[1]
                field_metadata["delivery_time"] = {"value": times[1], "confidence": round(cand["conf"], 3), "source_text": txt, "source_location": cand["bbox"]}

    return extracted_fields, field_metadata
