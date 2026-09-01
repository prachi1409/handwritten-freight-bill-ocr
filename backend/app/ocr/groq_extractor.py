"""Groq LLM mapper: OCR text (English, Spanish, and other high-resource languages) → freight JSON."""

import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.ocr.field_extractor import FREIGHT_FIELD_KEYS

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
"""


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


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
            merged[key] = val
    return merged


def extract_fields_with_groq(raw_text: str) -> Optional[Dict[str, Any]]:
    """Call Groq chat completions. Returns None if disabled, unconfigured, or the call fails."""
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

    model = (getattr(settings, "GROQ_MODEL", None) or "openai/gpt-oss-20b").strip()
    url = (getattr(settings, "GROQ_BASE_URL", None) or "https://api.groq.com/openai/v1").rstrip("/")
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": "OCR text:\n" + text[:12000]},
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
    except httpx.HTTPStatusError as err:
        detail = ""
        try:
            detail = err.response.text[:300]
        except Exception:
            detail = str(err)
        logger.warning(
            "Groq field extraction failed (%s %s). Using regex/spatial fields. %s",
            err.response.status_code,
            err.request.url,
            detail,
        )
        return None
    except Exception as err:
        logger.warning("Groq field extraction failed (%s). Using regex/spatial fields.", err)
        return None

    choices = body.get("choices") or []
    content = ""
    if choices:
        content = ((choices[0].get("message") or {}).get("content")) or ""
    parsed = _extract_json_object(content)
    if not parsed:
        logger.warning("Groq returned non-JSON. Using regex/spatial fields.")
        return None

    fields = parse_llm_fields(parsed)
    filled = sum(1 for key in FREIGHT_FIELD_KEYS if fields.get(key) not in (None, "", []))
    logger.info("Groq extracted %s/%s freight fields via model '%s'", filled, len(FREIGHT_FIELD_KEYS), model)
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
