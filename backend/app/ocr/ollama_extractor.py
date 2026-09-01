"""Optional Ollama JSON mapper: OCR text → freight-bill fields."""

import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.ocr.field_extractor import FREIGHT_FIELD_KEYS

logger = logging.getLogger(__name__)

_PROMPT = """Extract freight-bill fields from this OCR text.
Return JSON only with these keys:
bill_number, invoice_number, bill_date, consignor, consignee, origin, destination,
vehicle_number, weight, quantity, freight_amount, total_amount, line_items.
Use empty string when unknown. line_items is a list of objects with
item_no, description, quantity, rate, amount.
Do not invent values that are not in the text.

OCR text:
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
    fields: Dict[str, Any] = {key: payload.get(key) or "" for key in FREIGHT_FIELD_KEYS}
    items = payload.get("line_items")
    fields["line_items"] = items if isinstance(items, list) else []
    return fields


def extract_fields_with_ollama(raw_text: str) -> Optional[Dict[str, Any]]:
    """Call a local Ollama model. Returns None if Ollama is off or the call fails."""
    if not getattr(settings, "ENABLE_OLLAMA", False):
        return None
    if getattr(settings, "TESTING", False):
        return None
    text = (raw_text or "").strip()
    if len(text) < 20:
        logger.info("Skipping Ollama: OCR text too short (%s chars)", len(text))
        return None

    base_url = (getattr(settings, "OLLAMA_BASE_URL", None) or "http://127.0.0.1:11434").rstrip("/")
    model = (getattr(settings, "OLLAMA_MODEL", None) or "llama3.1").strip()
    prompt = _PROMPT + text[:8000]

    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            response.raise_for_status()
            body = response.json()
    except Exception as err:
        logger.warning("Ollama field extraction failed (%s). Using regex fields.", err)
        return None

    parsed = _extract_json_object(body.get("response") or "")
    if not parsed:
        logger.warning("Ollama returned non-JSON. Using regex fields.")
        return None

    fields = parse_llm_fields(parsed)
    filled = sum(1 for key in FREIGHT_FIELD_KEYS if fields.get(key))
    logger.info("Ollama extracted %s/%s freight fields via model '%s'", filled, len(FREIGHT_FIELD_KEYS), model)
    return fields
