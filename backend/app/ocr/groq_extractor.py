"""Groq LLM mapper: OCR text or page images → freight JSON."""

import base64
import io
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

import httpx

from app.core.config import settings
from app.ocr.field_extractor import FREIGHT_FIELD_KEYS
from app.ocr.normalizer import is_form_header_value, looks_like_ocr_junk

logger = logging.getLogger(__name__)

_SYSTEM = """You extract freight-bill / bill-of-lading / carta de porte fields.
The OCR text may be English, Spanish, French, Portuguese, German, or Hindi (Devanagari).
Return a single JSON object with exactly these keys:
bill_number, bill_date, carrier, invoice_number, consignor, consignee, origin,
destination, commodity_description, quantity, weight, freight_amount, fuel_surcharge,
handling_charge, total_amount, vehicle_number, driver_name, pickup_time, delivery_time,
special_instructions, driver_signature, consignee_signature, received_datetime, line_items.
Rules:
- Map labels in any of those languages onto these English keys
  (e.g. remitente/expedidor → consignor, destinatario/consignatario → consignee,
  origen → origin, destino → destination,
  importe del flete → freight_amount, importe total → total_amount,
  número de vehículo → vehicle_number, nombre del conductor → driver_name,
  hora de recogida → pickup_time, hora de entrega → delivery_time,
  instrucciones especiales → special_instructions,
  firma del conductor → driver_signature, firma del destinatario → consignee_signature,
  fecha/hora de recepción → received_datetime,
  carta de porte / n.º de factura / conocimiento de embarque / guía → bill_number,
  número de factura → invoice_number).
- Values may sit on the line below the label. Read the next line.
- Use empty string when the value is not in the text. Never output N/A, unknown, none, or not detected.
- Do not invent numbers, names, or amounts.
- line_items is a list of objects with item_no, description, quantity, rate, amount.
- Keep names and places in the original language. Use ISO dates YYYY-MM-DD when you can parse a date.
- For bill_number / invoice_number written in Devanagari (e.g. एफबी-१०२३६, आईएनवी-६२१), transliterate to Latin IDs (FB-10236, INV-621). Do not leave those fields empty.
- Never copy printed form labels as values (ADDRESS, SHIPPER, CONSIGNEE, SUB-HAUL, TAG NUMBER, POINT OF ORIGIN, POINT OF DESTINATION, DATE, WEIGHT). If the next line is the real value, use that.
- Shipper maps to consignor. Receiver maps to consignee. Never put the same string in consignor and consignee.
- Ticket / "No. 16766-1" maps to bill_number, not invoice_number, unless the label is invoice.
- Compact times like 930 or 1020 mean 9:30 and 10:20.
- If a table has several load rows, put each in line_items (tag, weight, load_arrive, load_depart, unload_arrive, unload_depart). Header pickup_time is the first load arrived; delivery_time is the last unload departed.
- Weight must be a single number (optionally with lbs). If a row glues weight and clock times (e.g. 27.02 5:20 5:27), put 27.02 in weight.
- If OCR text is unreadable garbage, return empty string. Do not copy it.
"""

_VISION_SYSTEM = """You read a scanned freight-bill / bill-of-lading / scale ticket, including messy handwriting.
Return a single JSON object with exactly these keys:
bill_number, bill_date, carrier, invoice_number, consignor, consignee, origin,
destination, commodity_description, quantity, weight, freight_amount, fuel_surcharge,
handling_charge, total_amount, vehicle_number, driver_name, pickup_time, delivery_time,
special_instructions, driver_signature, consignee_signature, received_datetime, line_items.
Rules:
- Read handwritten ink, not only printed headers.
- The company in the letterhead (e.g. CALIFORNIA MATERIALS, INC.) is the carrier, not the shipper.
- Permit / MC / CA numbers (e.g. CA0385520) are not invoice_number.
- Ticket "No. 16766-1" is bill_number, not invoice_number, unless the label says invoice.
- Shipper / sub-hauler → consignor. Consignee / receiver is a different party. Never copy the same string into both.
- Compact times like 930 or 1020 mean 9:30 and 10:20.
- Tagline text such as AGGREGATES TRUCKING is not the carrier legal name if a company name with INC/LLC is on the page.
- If a table has load rows, put each in line_items (tag, weight, load_arrive, load_depart, unload_arrive, unload_depart). Header pickup_time is first load in; delivery_time is last unload out.
- Empty string when you cannot read a value. Do not invent. Do not copy printed labels (SHIPPER, ADDRESS, POINT OF ORIGIN).
"""

_VISION_FALLBACK_MODELS = (
    "qwen/qwen3.6-27b",
    "qwen/qwen3.8-27b",
)

_PERMIT_ID_RE = re.compile(r"^CA\d{5,}$", re.IGNORECASE)


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = str(text).strip()
    cleaned = re.sub(r"<think>.*?</think>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    snippet = cleaned[start : i + 1]
                    try:
                        parsed = json.loads(snippet)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break
        start = cleaned.find("{", start + 1)
    return None


def _message_text(body: Optional[Dict[str, Any]]) -> str:
    """Join content + reasoning; Qwen often puts JSON beside thinking tokens."""
    choices = (body or {}).get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    chunks: List[str] = []
    content = msg.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("text", "output_text"):
                chunks.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                chunks.append(part)
    elif content:
        chunks.append(str(content))
    for key in ("reasoning", "reasoning_content"):
        extra = msg.get(key)
        if extra:
            chunks.append(str(extra))
    return "\n".join(chunks)


def parse_llm_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only freight schema keys from an LLM JSON object."""
    fields: Dict[str, Any] = {}
    for key in FREIGHT_FIELD_KEYS:
        val = payload.get(key)
        if val is None:
            fields[key] = ""
        else:
            fields[key] = val
    items = payload.get("line_items")
    fields["line_items"] = items if isinstance(items, list) else []
    return fields


_LLM_EMPTY = {
    "n/a", "na", "none", "null", "nil", "unknown", "-", "—",
    "not detected", "not found", "not specified", "not available",
    "no detectado", "no disponible", "desconocido",
}


def _llm_value_is_empty(val: Any) -> bool:
    if val in (None, "", [], {}):
        return True
    if isinstance(val, str) and val.strip().lower() in _LLM_EMPTY:
        return True
    return False


def apply_llm_fields(base: Dict[str, Any], llm_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Prefer non-empty Groq values; keep regex/spatial values for gaps."""
    merged = dict(base or {})
    for key, val in llm_fields.items():
        if key == "line_items":
            if isinstance(val, list) and val and not merged.get("line_items"):
                merged["line_items"] = val
            continue
        if not _llm_value_is_empty(val):
            if isinstance(val, str) and is_form_header_value(val):
                continue
            if isinstance(val, str) and key in (
                "consignor", "consignee", "origin", "destination",
                "commodity_description", "driver_name",
            ) and looks_like_ocr_junk(val):
                continue
            existing = merged.get(key)
            if (
                existing
                and isinstance(val, str)
                and key in ("consignor", "consignee", "origin", "destination", "commodity_description")
                and not looks_like_ocr_junk(str(existing))
                and looks_like_ocr_junk(val)
            ):
                continue
            merged[key] = val
    ship = re.sub(r"[^a-z0-9]+", "", str(merged.get("consignor") or "").lower())
    recv = re.sub(r"[^a-z0-9]+", "", str(merged.get("consignee") or "").lower())
    if ship and recv and ship == recv:
        merged["consignee"] = None
    return merged


def looks_like_permit_number(val: Any) -> bool:
    """True for carrier permit IDs like CA0385520 that are not invoices."""
    collapsed = re.sub(r"[\s-]+", "", str(val or "").strip())
    return bool(_PERMIT_ID_RE.match(collapsed))


def apply_vision_fields(base: Dict[str, Any], vision_fields: Dict[str, Any]) -> Dict[str, Any]:
    """Merge Groq vision JSON over regex/spatial; drop permit-as-invoice leftovers."""
    merged = apply_llm_fields(base, vision_fields)
    items = vision_fields.get("line_items")
    if isinstance(items, list) and items:
        merged["line_items"] = items
    for key in ("invoice_number", "consignor", "consignee", "origin", "destination", "carrier"):
        if not _llm_value_is_empty(vision_fields.get(key)):
            continue
        existing = merged.get(key)
        if not existing:
            continue
        if key == "invoice_number" and looks_like_permit_number(existing):
            merged[key] = None
        elif is_form_header_value(existing) or looks_like_ocr_junk(str(existing)):
            merged[key] = None
    ship = re.sub(r"[^a-z0-9]+", "", str(merged.get("consignor") or "").lower())
    haul = re.sub(r"[^a-z0-9]+", "", str(merged.get("carrier") or "").lower())
    if ship and haul and ship == haul and _llm_value_is_empty(vision_fields.get("consignor")):
        merged["consignor"] = None
    origin_key = re.sub(r"[^a-z0-9]+", "", str(merged.get("origin") or "").lower())
    if (
        origin_key
        and ship
        and origin_key != ship
        and origin_key in ship
        and len(origin_key) <= 8
        and _llm_value_is_empty(vision_fields.get("origin"))
    ):
        merged["origin"] = None
    return merged


def encode_images_for_groq_vision(
    page_images: Optional[Sequence[Any]],
    max_pages: Optional[int] = None,
    max_edge: Optional[int] = None,
) -> List[str]:
    """JPEG data URLs small enough for Groq vision (max 5 images, ~20MB request)."""
    from PIL import Image

    if not page_images:
        return []
    pages = int(max_pages if max_pages is not None else getattr(settings, "GROQ_VISION_MAX_PAGES", 2) or 2)
    edge = int(max_edge if max_edge is not None else getattr(settings, "GROQ_VISION_MAX_EDGE", 1536) or 1536)
    pages = max(1, min(5, pages))
    edge = max(640, min(2048, edge))
    urls: List[str] = []
    for img in list(page_images)[:pages]:
        if img is None:
            continue
        rgb = img.convert("RGB")
        width, height = rgb.size
        longest = max(width, height)
        if longest > edge:
            ratio = edge / float(longest)
            rgb = rgb.resize(
                (max(1, int(width * ratio)), max(1, int(height * ratio))),
                Image.Resampling.LANCZOS,
            )
        raw = b""
        for quality in (80, 65, 50):
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=quality, optimize=True)
            raw = buf.getvalue()
            if len(raw) <= 1_200_000:
                break
        urls.append("data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii"))
    return urls


def _vision_model_candidates() -> List[str]:
    primary = (getattr(settings, "GROQ_VISION_MODEL", None) or "").strip()
    seen: List[str] = []
    for model in [primary, *_VISION_FALLBACK_MODELS]:
        if model and model not in seen:
            seen.append(model)
    return seen


def _model_unavailable(status: int, detail: str) -> bool:
    if status == 404:
        return True
    if status != 400:
        return False
    return bool(re.search(r"model", detail, re.I) and re.search(
        r"not found|decommissioned|does not exist|unknown",
        detail,
        re.I,
    ))


def _qwen_extras(model: str, json_mode: bool) -> Dict[str, Any]:
    extras: Dict[str, Any] = {}
    if "qwen" in (model or "").lower():
        extras["reasoning_effort"] = "none"
        if json_mode:
            extras["reasoning_format"] = "hidden"
    return extras


def _parse_failed_generation(err: httpx.HTTPStatusError) -> Optional[Dict[str, Any]]:
    try:
        payload = err.response.json()
        failed = ((payload.get("error") or {}).get("failed_generation")) or ""
        return _extract_json_object(failed)
    except Exception:
        return None


def _groq_chat_parse(
    messages: List[Dict[str, Any]],
    model: str,
    timeout: float = 60.0,
    *,
    vision: bool = False,
) -> Optional[Dict[str, Any]]:
    """POST chat/completions; vision skips JSON mode first (Qwen+images 400s on json_object)."""
    api_key = (getattr(settings, "GROQ_API_KEY", None) or "").strip()
    url = (getattr(settings, "GROQ_BASE_URL", None) or "https://api.groq.com/openai/v1").rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    token_limit = 4096 if vision else 2048
    text_payload = {
        "model": model,
        "temperature": 0,
        "max_completion_tokens": token_limit,
        "messages": messages,
        **_qwen_extras(model, json_mode=False),
    }
    json_payload = {
        "model": model,
        "temperature": 0,
        "max_completion_tokens": token_limit,
        "response_format": {"type": "json_object"},
        "messages": messages,
        **_qwen_extras(model, json_mode=True),
    }
    payloads = [text_payload, json_payload] if vision else [json_payload, text_payload]
    parsed = None
    last_err = None
    for payload in payloads:
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(f"{url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as err:
            last_err = err
            recovered = _parse_failed_generation(err)
            if recovered:
                return recovered
            detail = ""
            try:
                detail = err.response.text[:400]
            except Exception:
                detail = str(err)
            logger.warning(
                "Groq field extraction failed (%s) model='%s'. %s",
                err.response.status_code,
                model,
                detail,
            )
            if _model_unavailable(err.response.status_code, detail):
                return None
            if err.response.status_code != 400:
                return None
            continue
        except Exception as err:
            logger.warning("Groq field extraction failed (%s). Using regex/spatial fields.", err)
            return None
        parsed = _extract_json_object(_message_text(body))
        if parsed:
            break
        snippet = _message_text(body).strip().replace("\n", " ")[:180]
        logger.warning(
            "Groq returned non-JSON model='%s'. Preview: '%s'",
            model,
            snippet,
        )
    if parsed is None and last_err is not None:
        logger.warning("Groq field extraction failed after retry. Using regex/spatial fields.")
    elif parsed is None:
        logger.warning("Groq returned non-JSON. Using regex/spatial fields.")
    return parsed


def extract_fields_with_groq(raw_text: str) -> Optional[Dict[str, Any]]:
    """Call Groq chat completions on OCR text. Returns None if disabled or the call fails."""
    if getattr(settings, "TESTING", False):
        return None
    if not getattr(settings, "ENABLE_GROQ", False):
        return None
    api_key = (getattr(settings, "GROQ_API_KEY", None) or "").strip()
    if not api_key:
        logger.info("Groq skipped: GROQ_API_KEY is empty")
        return None
    text = (raw_text or "").strip()
    if len(text) < 20:
        logger.info("Groq skipped: OCR text too short (%s chars)", len(text))
        return None
    text = re.sub(
        r"[^\t\n\r\x20-\x7E\u00A0-\u024F\u0900-\u097F\u2010-\u2027]",
        " ",
        text,
    )
    text = re.sub(r"[ \t]{2,}", " ", text)

    model = (getattr(settings, "GROQ_MODEL", None) or "openai/gpt-oss-20b").strip()
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "OCR text:\n" + text[:12000]},
    ]
    parsed = _groq_chat_parse(messages, model, timeout=60.0)
    if parsed is None:
        return None
    fields = parse_llm_fields(parsed)
    filled = sum(1 for key in FREIGHT_FIELD_KEYS if fields.get(key) not in (None, "", []))
    logger.info("Groq extracted %s/%s freight fields via model '%s'", filled, len(FREIGHT_FIELD_KEYS), model)
    return fields


def extract_fields_with_groq_vision(page_images: Optional[Sequence[Any]]) -> Optional[Dict[str, Any]]:
    """Call a Groq vision model on page images so handwritten values can be read."""
    if getattr(settings, "TESTING", False):
        return None
    if not getattr(settings, "ENABLE_GROQ", False):
        return None
    if not getattr(settings, "ENABLE_GROQ_VISION", True):
        return None
    api_key = (getattr(settings, "GROQ_API_KEY", None) or "").strip()
    if not api_key:
        logger.info("Groq vision skipped: GROQ_API_KEY is empty")
        return None
    data_urls = encode_images_for_groq_vision(page_images)
    if not data_urls:
        logger.info("Groq vision skipped: no page images")
        return None

    user_content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Extract freight-bill fields from this scanned page. "
                "Read handwritten names, places, ticket numbers, weights, and times. "
                "Return a single JSON object only. No markdown, no explanation."
            ),
        }
    ]
    for url in data_urls:
        user_content.append({"type": "image_url", "image_url": {"url": url}})
    messages = [
        {"role": "system", "content": _VISION_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    parsed = None
    used_model = ""
    for model in _vision_model_candidates():
        parsed = _groq_chat_parse(messages, model, timeout=90.0, vision=True)
        if parsed:
            used_model = model
            break
        logger.warning("Groq vision model '%s' returned no JSON. Trying next vision model if any.", model)
    if parsed is None:
        return None
    fields = parse_llm_fields(parsed)
    filled = sum(1 for key in FREIGHT_FIELD_KEYS if fields.get(key) not in (None, "", []))
    logger.info(
        "Groq vision extracted %s/%s freight fields via model '%s' (%s page image(s))",
        filled,
        len(FREIGHT_FIELD_KEYS),
        used_model,
        len(data_urls),
    )
    return fields


TRANSLATABLE_FIELDS = (
    "carrier",
    "consignor",
    "consignee",
    "origin",
    "destination",
    "commodity_description",
    "driver_name",
    "special_instructions",
    "driver_signature",
    "consignee_signature",
)

DIGIT_DISPLAY_FIELDS = ("quantity", "weight", "pickup_time", "delivery_time", "received_datetime")

_TRANSLATE_SYSTEM = """Translate freight-bill field values to English for a reviewer.
Return a JSON object with the same keys you were given.
Rules:
- Translate Hindi/Devanagari (and other non-English) text into natural English.
- Keep recognizable brand and place names (Costco, St. Louis, Midwest).
- Do not invent values. If a value is already English, copy it unchanged.
- Use empty string only when the input value is empty.
"""

_INDIC_RE = re.compile(r"[\u0900-\u097F]")


def contains_indic_script(value: Any) -> bool:
    return bool(_INDIC_RE.search(str(value or "")))


def _groq_configured() -> bool:
    if getattr(settings, "TESTING", False):
        return False
    if not getattr(settings, "ENABLE_GROQ", False):
        return False
    return bool((getattr(settings, "GROQ_API_KEY", None) or "").strip())


def _call_groq_json(system: str, user: str) -> Optional[Dict[str, Any]]:
    api_key = (getattr(settings, "GROQ_API_KEY", None) or "").strip()
    model = (getattr(settings, "GROQ_MODEL", None) or "openai/gpt-oss-20b").strip()
    url = (getattr(settings, "GROQ_BASE_URL", None) or "https://api.groq.com/openai/v1").rstrip("/")
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except Exception as err:
        logger.warning("Groq request failed (%s).", err)
        return None

    choices = body.get("choices") or []
    content = ""
    if choices:
        content = ((choices[0].get("message") or {}).get("content")) or ""
    return _extract_json_object(content)


def translate_fields_for_display(fields: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build display-only English values. Does not persist. IDs/dates/amounts are left alone."""
    from app.ocr.normalizer import transliterate_indic_digits

    source_fields = fields if isinstance(fields, dict) else {}
    translations: Dict[str, str] = {}

    for key in DIGIT_DISPLAY_FIELDS:
        raw = source_fields.get(key)
        if raw in (None, ""):
            continue
        converted = transliterate_indic_digits(str(raw))
        if converted != str(raw):
            translations[key] = converted

    to_translate: Dict[str, str] = {}
    for key in TRANSLATABLE_FIELDS:
        raw = source_fields.get(key)
        if raw in (None, "") or not contains_indic_script(raw):
            continue
        to_translate[key] = str(raw)

    source = "digits"
    if to_translate and _groq_configured():
        payload = _call_groq_json(
            _TRANSLATE_SYSTEM,
            "Translate these fields to English:\n" + json.dumps(to_translate, ensure_ascii=False),
        )
        if payload:
            for key in to_translate:
                english = payload.get(key)
                if english in (None, ""):
                    continue
                english = str(english).strip()
                if english and not _llm_value_is_empty(english):
                    translations[key] = english
            source = "groq"
        else:
            logger.warning("Groq translation failed. Returning digit transliteration only.")
    elif to_translate:
        logger.info("Groq unavailable; English names not generated.")

    return {"translations": translations, "source": source}
