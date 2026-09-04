"""Freight-bill field extraction from OCR text, entities, and form fields with stacked multi-column layout support."""

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from app.ocr.normalizer import compact_digits_to_clock, is_form_header_value, looks_like_ocr_junk, parse_boxed_month_day_year

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
        "origen", "lugar_de_carga", "point_of_origin", "pointoforigin",
    ),
    "destination": (
        "destination", "place_of_delivery", "delivery_location", "dest_city", "to_location",
        "destino", "lugar_de_descarga", "point_of_destination", "pointofdestination",
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
    if is_form_header_value(value):
        rest_lines = [ln.strip() for ln in text[match.end():].splitlines() if ln.strip()]
        for next_line in rest_lines[:6]:
            if not is_form_header_value(next_line):
                return next_line
        return None
    return value


def parse_mashed_cargo_line(raw_text: str) -> Dict[str, Any]:
    """Pull quantity, commodity, weight, and times from a glued scale-ticket row."""
    out: Dict[str, Any] = {}
    if not raw_text:
        return out

    rock = re.search(
        r"(\d+\s*[x×]\s*\d+\s+[A-Za-z]+(?:\s+[A-Za-z]+)?)",
        raw_text,
        re.IGNORECASE,
    )
    if rock:
        desc = rock.group(1).strip()
        out["commodity_description"] = desc
        qty = re.match(r"(\d+)", desc)
        if qty:
            out["quantity"] = qty.group(1)

    for line in raw_text.splitlines():
        glued_wt_times = re.search(
            r"(\d+\.\d{2})(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})",
            line,
        )
        is_scale = bool(re.search(r"\d+\s*[x×]\s*\d+", line, re.IGNORECASE)) or bool(
            re.search(r"\d{6,}\s+\d+(?:\.\d+)?\s+\d{1,2}:\d{2}", line)
        ) or bool(re.search(r"\d{6,}\d+\.\d{2}\d{1,2}:\d{2}", line)) or bool(glued_wt_times)
        if not is_scale:
            continue
        if glued_wt_times:
            pickup, delivery = glued_wt_times.group(2), glued_wt_times.group(3)
            try:
                h1, h2 = int(pickup.split(":")[0]), int(delivery.split(":")[0])
                if h1 > 12 and h2 <= 12 and pickup.startswith("1"):
                    pickup = pickup[1:]
            except ValueError:
                pass
            out.setdefault("weight", glued_wt_times.group(1))
            out.setdefault("pickup_time", pickup)
            out.setdefault("delivery_time", delivery)
        clocks = re.findall(
            r"(?<!\d)(\d{1,2}:\d{2}(?:\s*[AaPp]\.?\s*[Mm]\.?)?)(?!\d)",
            line,
        )
        if len(clocks) >= 2:
            out["pickup_time"] = clocks[-2]
            out["delivery_time"] = clocks[-1]
        mashed = re.search(
            r"(?:\b(?:tag|ticket)\s*(?:number|#)?\s*)?(\d{6,})\s+(\d+(?:\.\d+)?)\s+\d{1,2}:\d{2}",
            line,
            re.IGNORECASE,
        )
        if mashed:
            out["weight"] = mashed.group(2)
        else:
            glued = re.search(r"(\d{6,})(\d+\.\d{2})(\d{1,2}:\d{2})", line)
            if glued:
                out["weight"] = glued.group(2)
            else:
                wt = re.search(r"(?<!\d)(\d+\.\d{2})(?!\d)", line)
                if wt:
                    out["weight"] = wt.group(1)
        if out.get("weight") or len(clocks) >= 2:
            break

    return out


_WEAK_TOKEN = re.compile(r"^[A-Za-z]{1,4}[+.]?$")


def extract_letterhead_carrier(raw_text: str) -> Optional[str]:
    """First letterhead line that looks like a registered company name."""
    for ln in (raw_text or "").splitlines()[:25]:
        line = ln.strip()
        if len(line) < 8 or is_form_header_value(line):
            continue
        if re.search(r"\b(INC|LLC|CORP|LTD)\.?\b", line, re.IGNORECASE):
            letters = re.sub(r"[^A-Za-z]", "", line)
            if len(letters) >= 8:
                return line
    return None


def extract_route_after_point_headers(raw_text: str) -> Dict[str, Any]:
    """Read origin/destination lines after glued POINT OF ORIGIN / DESTINATION headers."""
    out: Dict[str, Any] = {}
    lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]
    start = None
    for i, ln in enumerate(lines):
        collapsed = re.sub(r"[^A-Za-z]+", "", ln.upper())
        if "POINTOFORIGIN" in collapsed or "POINTOFDESTINATION" in collapsed:
            start = i
            break
    if start is None:
        return out
    geo: List[str] = []
    for ln in lines[start + 1 : start + 14]:
        if is_form_header_value(ln):
            continue
        if re.match(r"^(YR|MO|DAY|DATE)[\s.]*\d*$", ln, re.IGNORECASE):
            continue
        if re.match(r"^YR\.?\s*\d+", ln, re.IGNORECASE):
            continue
        if re.search(r"load|commodity|tag\s*number|weight|unload", ln, re.IGNORECASE) and len(ln) < 24:
            break
        geo.append(ln)
        if len(geo) >= 6:
            break
    if not geo:
        return out
    out["origin"] = geo[0]
    dest_parts: List[str] = []
    for part in geo[1:]:
        if re.search(r"load|commodity|tag|weight|unload", part, re.IGNORECASE):
            break
        dest_parts.append(part)
    if dest_parts:
        out["destination"] = " ".join(dest_parts[:4])
    return out


def recover_aggregate_commodity(raw_text: str) -> Dict[str, Any]:
    """Recover '1 x 4 Rock' from a size×product token, even when a tag is glued on."""
    out: Dict[str, Any] = {}
    if not raw_text:
        return out
    named = re.search(
        r"(\d+)\s*[x×]\s*(\d+)\s+(Rock|Gravel|Sand|Dirt|Base|Stone)\b",
        raw_text,
        re.IGNORECASE,
    )
    if named:
        out["quantity"] = named.group(1)
        out["commodity_description"] = f"{named.group(1)} x {named.group(2)} {named.group(3).title()}"
        return out
    glued = re.search(
        r"(?:(?<=\n)|(?<=\s)|^)(?:(\d)\s*)?[x×]\s*(\d)\s*([A-Za-z]{3,8})(\d{5,})",
        raw_text,
        re.IGNORECASE,
    )
    if glued:
        qty = glued.group(1) or "1"
        size = glued.group(2)
        word = glued.group(3)
        if re.match(r"[br]o?c?k", word, re.IGNORECASE):
            word = "Rock"
        else:
            word = word.title()
        out["quantity"] = qty
        out["commodity_description"] = f"{qty} x {size} {word}"
    return out


def pick_extracted_value(field: str, spatial_val: Any, text_val: Any) -> Any:
    """Prefer regex when spatial grabbed a weak token (CMa+) or a form header."""
    if spatial_val and (is_form_header_value(spatial_val) or (
        field in ("consignor", "consignee", "origin", "destination", "commodity_description", "driver_name")
        and looks_like_ocr_junk(spatial_val)
    )):
        spatial_val = None
    if text_val and (is_form_header_value(text_val) or (
        field in ("consignor", "consignee", "origin", "destination", "commodity_description")
        and looks_like_ocr_junk(text_val)
    )):
        text_val = None
    if not spatial_val:
        return text_val
    if not text_val:
        return spatial_val
    if field in (
        "consignor", "consignee", "carrier", "origin", "destination",
        "driver_name", "commodity_description",
    ):
        spat = str(spatial_val).strip()
        text = str(text_val).strip()
        if _WEAK_TOKEN.match(spat) and len(re.sub(r"[^A-Za-z]", "", text)) >= 6:
            return text_val
        spat_key = re.sub(r"[^A-Za-z0-9]+", "", spat).lower()
        text_key = re.sub(r"[^A-Za-z0-9]+", "", text).lower()
        if spat_key and text_key.startswith(spat_key) and len(text) > len(spat):
            return text_val
        if field == "commodity_description" and re.search(r"\d{5,}", spat) and not re.search(r"\d{5,}", text):
            return text_val
        spat_letters = len(re.sub(r"[^A-Za-z]", "", spat))
        text_letters = len(re.sub(r"[^A-Za-z]", "", text))
        if text_letters >= spat_letters + 6:
            return text_val
    return spatial_val


def looks_like_person_name(text: str) -> bool:
    """True for 'Samuel M' / 'Mike Donovan', not labels or ticket numbers."""
    s = (text or "").strip()
    if not s or is_form_header_value(s) or re.search(r"\d{3,}", s):
        return False
    if re.search(r"\b(INC|LLC|CORP|LTD|MATERIALS|CONCRETE)\b", s, re.IGNORECASE):
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z'`.-]{1,24}(?:\s+[A-Za-z][A-Za-z'.]{0,20}){1,2}$", s))


def clocks_on_line(line: str) -> List[str]:
    """Collect colon clocks and compact 930/1020 times from one OCR line."""
    found: List[str] = []
    for match in re.finditer(r"(?<!\d)(\d{1,2}:\d{2})(?!\d)", line):
        found.append(match.group(1))
    compact_hits = re.findall(r"(?<!\d)(\d{3,4})(?!\d)", line)
    compact_clocks = []
    for token in compact_hits:
        clock = compact_digits_to_clock(token)
        if clock:
            compact_clocks.append(clock)
    if len(compact_clocks) >= 3:
        found.extend(compact_clocks)
    elif len(found) < 2 and len(compact_clocks) >= 2:
        found.extend(compact_clocks)
    return found


def parse_load_rows(raw_text: str) -> List[Dict[str, Any]]:
    """Parse scale-ticket rows: tag, weight, load in/out, unload in/out."""
    rows: List[Dict[str, Any]] = []
    if not raw_text:
        return rows
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        weight_match = re.search(r"(?<!\d)(\d{1,3}\.\d{2})(?!\d)", line)
        clocks = clocks_on_line(line)
        tag_match = re.search(r"(?<!\d)(\d{4,8})(?!\d)", line)
        if not ((weight_match and len(clocks) >= 2) or len(clocks) >= 3):
            continue
        row: Dict[str, Any] = {
            "item_no": str(len(rows) + 1),
            "description": "",
            "weight": weight_match.group(1) if weight_match else None,
        }
        if tag_match:
            tag = tag_match.group(1)
            if len(tag) >= 4 and compact_digits_to_clock(tag) is None:
                row["tag"] = tag
        if clocks:
            row["load_arrive"] = clocks[0]
            if len(clocks) > 1:
                row["load_depart"] = clocks[1]
            if len(clocks) > 2:
                row["unload_arrive"] = clocks[2]
            if len(clocks) > 3:
                row["unload_depart"] = clocks[3]
        if row.get("weight") or len(clocks) >= 2:
            rows.append(row)
    return rows


def apply_load_summary(res: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    """Header pickup = first load in; delivery = last unload out."""
    if not rows:
        return
    commodity = res.get("commodity_description")
    for row in rows:
        if not row.get("description"):
            row["description"] = commodity or "Load"
    res["line_items"] = rows
    first, last = rows[0], rows[-1]
    pickup = first.get("load_arrive")
    delivery = last.get("unload_depart") or last.get("load_depart") or last.get("unload_arrive")
    if pickup:
        res["pickup_time"] = pickup
    if delivery:
        res["delivery_time"] = delivery
    if len(rows) > 1:
        res["quantity"] = str(len(rows))
        weights = []
        for row in rows:
            try:
                weights.append(float(row["weight"]))
            except (TypeError, ValueError, KeyError):
                continue
        if weights:
            total = sum(weights)
            res["weight"] = f"{total:.2f}"


def extract_driver_from_signature_block(raw_text: str) -> Optional[str]:
    """Read a handwritten name from a DRIVER / SIGNATURE footer (value may sit under CONSIGNEE)."""
    lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]
    start = None
    for i, ln in enumerate(lines):
        collapsed = re.sub(r"[^A-Za-z]+", "", ln.upper())
        if collapsed in {"SIGNATURE", "DRIVER", "DRIVERSIGNATURE", "DRIVERSIG"}:
            start = i
    if start is None:
        start = max(0, len(lines) - 16)
    for ln in lines[start:]:
        if looks_like_person_name(ln):
            return ln
    return None


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
        "origin": r"(?:point\s*of\s*origin|pointoforigin|pickup\s*loc|(?<![Oo]f\s)origin|origen)[:\s]*([^\n]+)",
        "destination": r"(?:point\s*of\s*destination|pointofdestination|delivery\s*loc|destnaton|(?<![Oo]f\s)destination|destino)[:\s]*([^\n]+)",
        "carrier": r"(?:carrier\s*name|carrier|(?<!-)hauler|transportista)[:\s]*([^\n]+)",
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
            r"(?:n[úu]mero\s+de\s+veh[ií]culo|numero\s+de\s+vehiculo|vehicle\s*number|truck\s*no\.?|truckno\.?)"
            r"[:\s]*\n?\s*#?\s*([\w.\u0900-\u097F-]{1,})"
        ),
        "driver_name": r"(?:nombre\s+del\s+conductor|driver\s*name|(?<![A-Za-z])driver)[:\s]*\n?\s*([^\n]+)",
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
        if is_form_header_value(value):
            continue
        if key == "special_instructions" and re.search(r"\d{5,}", value):
            continue
        if key == "special_instructions" and len(re.sub(r"[^A-Za-z]", "", value)) < 4:
            continue
        if key == "vehicle_number" and (
            is_form_header_value(value) or not re.search(r"\d", value) or re.search(r"miles|hours", value, re.IGNORECASE)
        ):
            continue
        if key == "driver_name" and (
            is_form_header_value(value) or re.search(r"hours|miles|payroll", value, re.IGNORECASE)
        ):
            continue
        if key in ("consignor", "consignee", "origin", "destination", "commodity_description") and looks_like_ocr_junk(value):
            continue
        res[key] = value

    mashed = parse_mashed_cargo_line(raw_text)
    for key, val in mashed.items():
        if val and not res.get(key):
            res[key] = val

    route = extract_route_after_point_headers(raw_text)
    if route.get("origin") and route.get("destination"):
        res["origin"] = route["origin"]
        res["destination"] = route["destination"]
    else:
        for key, val in route.items():
            if val and (not res.get(key) or is_form_header_value(res.get(key))):
                res[key] = val

    if not res.get("carrier"):
        letterhead = extract_letterhead_carrier(raw_text)
        if letterhead:
            res["carrier"] = letterhead

    if not res.get("bill_number"):
        ticket = re.search(r"(?:^|\n)\s*No\.\s+(\d[\w.-]{2,})\s*(?:\n|$)", raw_text, re.IGNORECASE)
        if ticket and not is_form_header_value(ticket.group(1)):
            res["bill_number"] = ticket.group(1)

    recovered = recover_aggregate_commodity(raw_text)
    for key, val in recovered.items():
        existing = res.get(key)
        if not existing or (key == "commodity_description" and re.search(r"\d{5,}", str(existing))):
            res[key] = val

    if not res.get("bill_date"):
        boxed = parse_boxed_month_day_year(raw_text)
        if boxed:
            res["bill_date"] = boxed

    if not res.get("driver_name") or not looks_like_person_name(str(res.get("driver_name"))):
        footer_driver = extract_driver_from_signature_block(raw_text)
        if footer_driver:
            res["driver_name"] = footer_driver
    if res.get("driver_name") and looks_like_person_name(str(res.get("driver_name"))):
        if not res.get("driver_signature") or is_form_header_value(res.get("driver_signature")):
            res["driver_signature"] = res["driver_name"]

    load_rows = parse_load_rows(raw_text)
    if load_rows:
        apply_load_summary(res, load_rows)

    ship = re.sub(r"[^a-z0-9]+", "", str(res.get("consignor") or "").lower())
    recv = re.sub(r"[^a-z0-9]+", "", str(res.get("consignee") or "").lower())
    if ship and recv and ship == recv:
        res["consignee"] = None

    if not res.get("pickup_time") or not res.get("delivery_time") or (
        res.get("pickup_time") and res.get("delivery_time") and res.get("pickup_time") == res.get("delivery_time")
    ):
        time_pairs = re.findall(
            r"\b([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)\s*[/:-]\s*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM|am|pm)?)\b",
            raw_text,
        )
        if time_pairs:
            p_time, d_time = time_pairs[0]
            res["pickup_time"] = p_time.strip()
            res["delivery_time"] = d_time.strip()

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
