"""Deterministic freight-bill layout / template classification (metadata only)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

LAYOUT_UNKNOWN = "unknown"
LAYOUT_STANDARD = "standard_freight_bill"
LAYOUT_INVOICE = "invoice_style"
LAYOUT_TABLE = "table_heavy"
LAYOUT_HANDWRITTEN = "handwritten_heavy"

LAYOUT_CLASSES = (
    LAYOUT_UNKNOWN,
    LAYOUT_STANDARD,
    LAYOUT_INVOICE,
    LAYOUT_TABLE,
    LAYOUT_HANDWRITTEN,
)

METHOD_DETERMINISTIC = "deterministic"

_MIN_SCORE = 0.40
_MIN_MARGIN = 0.12
_HEADER_Y = 0.28

_FREIGHT_KEYWORDS = (
    "freight bill",
    "bill of lading",
    "point of origin",
    "point of destination",
    "consignor",
    "consignee",
    "shipper",
    "carrier",
    "waybill",
    "origin",
    "destination",
)
_INVOICE_KEYWORDS = (
    "invoice number",
    "invoice no",
    "invoice date",
    "amount due",
    "bill to",
    "subtotal",
    "sales tax",
    "remit payment",
    "invoice",
)
_TABLE_HEADERS = (
    "quantity",
    "qty",
    "description",
    "unit price",
    "rate",
    "amount",
    "tag number",
    "tag no",
    "hours",
    "tons",
    "line items",
)
_BILL_NUMBER_LABELS = ("bill no", "bill number", "ticket no", "ticket number")
_INVOICE_HEADER = ("invoice", "tax invoice", "commercial invoice")
_FREIGHT_HEADER = ("freight bill", "bill of lading", "straight bill of lading")


def unknown_classification(
    *,
    evidence: Optional[Sequence[str]] = None,
    confidence: float = 0.25,
    error: Optional[str] = None,
    features: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    conf = round(min(1.0, max(0.0, float(confidence))), 2)
    return {
        "layout_class": LAYOUT_UNKNOWN,
        "confidence": conf,
        "layout_confidence": conf,
        "method": METHOD_DETERMINISTIC,
        "evidence": list(evidence or ["weak_or_ambiguous"]),
        "features": features or {},
        "error": error,
    }


def _blob(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _count_hits(blob: str, phrases: Sequence[str]) -> int:
    return sum(1 for phrase in phrases if phrase in blob)


def _alnum_count(text: Optional[str]) -> int:
    return sum(ch.isalnum() for ch in (text or ""))


def _page_extent(
    layout: Optional[Dict[str, Any]],
    spatial_items: Optional[Sequence[Dict[str, Any]]],
    page_images: Optional[Sequence[Any]] = None,
) -> Tuple[float, float]:
    images = list(page_images or [])
    if images:
        try:
            width = float(getattr(images[0], "width", 0) or 0)
            height = float(getattr(images[0], "height", 0) or 0)
            if width > 1 and height > 1:
                return width, height
        except Exception:
            pass
    max_x, max_y = 1.0, 1.0
    for item in list((layout or {}).get("blocks") or []) + list(spatial_items or []):
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox") or [0, 0, 0, 0]
        try:
            max_x = max(max_x, float(bbox[2]))
            max_y = max(max_y, float(bbox[3]))
        except (TypeError, ValueError, IndexError):
            continue
        try:
            max_x = max(max_x, float(item.get("center_x") or 0))
            max_y = max(max_y, float(item.get("center_y") or 0))
        except (TypeError, ValueError):
            continue
    return max(max_x, 1.0), max(max_y, 1.0)


def _iter_located_text(
    layout: Optional[Dict[str, Any]],
    spatial_items: Optional[Sequence[Dict[str, Any]]],
) -> List[Tuple[str, float, float]]:
    rows: List[Tuple[str, float, float]] = []
    for block in (layout or {}).get("blocks") or []:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        bbox = block.get("bbox") or [0, 0, 0, 0]
        try:
            cx = (float(bbox[0]) + float(bbox[2])) / 2.0
            cy = (float(bbox[1]) + float(bbox[3])) / 2.0
        except (TypeError, ValueError, IndexError):
            cx, cy = 0.0, 0.0
        rows.append((text, cx, cy))
    for item in spatial_items or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            cx = float(item.get("center_x") if item.get("center_x") is not None else 0.0)
            cy = float(item.get("center_y") if item.get("center_y") is not None else 0.0)
        except (TypeError, ValueError):
            cx, cy = 0.0, 0.0
        rows.append((text, cx, cy))
    return rows


def _in_header(cy: float, page_height: float) -> bool:
    if cy <= 150:
        return True
    if page_height > 200:
        return cy <= (_HEADER_Y * page_height)
    return False


def _column_row_counts(
    located: Sequence[Tuple[str, float, float]],
    page_width: float,
    page_height: float,
) -> Tuple[int, int]:
    if len(located) < 8 or page_width <= 1 or page_height <= 1:
        return 0, 0
    col_bins: Dict[int, int] = {}
    row_bins: Dict[int, int] = {}
    for _text, cx, cy in located:
        col = int(max(0.0, min(0.99, cx / page_width)) * 8)
        row = int(max(0.0, min(0.99, cy / page_height)) * 16)
        col_bins[col] = col_bins.get(col, 0) + 1
        row_bins[row] = row_bins.get(row, 0) + 1
    strong_cols = sum(1 for count in col_bins.values() if count >= 4)
    strong_rows = sum(1 for count in row_bins.values() if count >= 3)
    return strong_cols, strong_rows


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return round(min(high, max(low, value)), 2)


def classify_document_layout(
    raw_text: Optional[str] = None,
    *,
    page_count: int = 0,
    page_images: Optional[Sequence[Any]] = None,
    layout: Optional[Dict[str, Any]] = None,
    spatial_items: Optional[Sequence[Dict[str, Any]]] = None,
    text_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Score layout families from upstream OCR/structure. Does not read extracted fields."""
    text = raw_text or ""
    blob = _blob(text)
    pages = max(int(page_count or 0), len(page_images or []) or 0, 1)
    blocks = list((layout or {}).get("blocks") or [])
    spatial = [item for item in (spatial_items or []) if isinstance(item, dict)]
    block_count = int((layout or {}).get("block_count") or len(blocks))
    alnum = _alnum_count(text)
    chars_per_page = len(text) / pages
    alnum_per_page = alnum / pages
    page_width, page_height = _page_extent(layout, spatial, page_images)
    located = _iter_located_text(layout, spatial)
    source = (text_source or "").strip() or "unknown"

    features = {
        "page_count": pages,
        "block_count": block_count,
        "spatial_item_count": len(spatial),
        "ocr_alnum": alnum,
        "chars_per_page": round(chars_per_page, 1),
        "text_source": source,
        "page_width": round(page_width, 1),
        "page_height": round(page_height, 1),
    }

    freight_hits = _count_hits(blob, _FREIGHT_KEYWORDS)
    invoice_hits = _count_hits(blob, _INVOICE_KEYWORDS)
    table_hits = _count_hits(blob, _TABLE_HEADERS)
    party_hits = sum(1 for key in ("consignor", "consignee") if key in blob)
    route_hits = sum(1 for key in ("origin", "destination") if key in blob)
    header_freight = False
    header_invoice = False
    header_bill_no = False
    for text_item, _cx, cy in located:
        low = text_item.lower()
        if _in_header(cy, page_height):
            if any(label in low for label in _FREIGHT_HEADER):
                header_freight = True
            if any(label in low for label in _INVOICE_HEADER):
                header_invoice = True
            if any(label in low for label in _BILL_NUMBER_LABELS):
                header_bill_no = True
    if not located:
        header_freight = any(label in blob for label in _FREIGHT_HEADER)
        header_invoice = any(label in blob[:400] for label in _INVOICE_HEADER)
        header_bill_no = any(label in blob[:400] for label in _BILL_NUMBER_LABELS)

    strong_cols, strong_rows = _column_row_counts(located, page_width, page_height)
    density_low = alnum_per_page < 80 or chars_per_page < 160
    density_printed = alnum_per_page >= 120 and chars_per_page >= 220

    scores = {
        LAYOUT_STANDARD: 0.0,
        LAYOUT_INVOICE: 0.0,
        LAYOUT_TABLE: 0.0,
        LAYOUT_HANDWRITTEN: 0.0,
    }
    evidence: List[str] = []

    if density_low:
        scores[LAYOUT_HANDWRITTEN] += 0.45
        evidence.append("low_ocr_density")
    if source in {"preprocessed_image", "empty"} and density_low:
        scores[LAYOUT_HANDWRITTEN] += 0.20
        evidence.append("handwriting_indicators")
    if alnum < 40:
        scores[LAYOUT_HANDWRITTEN] += 0.15
        evidence.append("sparse_ocr_text")
    if density_printed:
        scores[LAYOUT_HANDWRITTEN] -= 0.35

    if freight_hits >= 3:
        scores[LAYOUT_STANDARD] += 0.42
        evidence.append("freight_bill_keywords")
    elif freight_hits >= 2:
        scores[LAYOUT_STANDARD] += 0.22
        evidence.append("freight_bill_keywords")
    if party_hits >= 2:
        scores[LAYOUT_STANDARD] += 0.18
        evidence.append("party_labels")
    if route_hits >= 2:
        scores[LAYOUT_STANDARD] += 0.12
        evidence.append("route_labels")
    if header_freight:
        scores[LAYOUT_STANDARD] += 0.16
        evidence.append("freight_header_region")
    if header_bill_no:
        scores[LAYOUT_STANDARD] += 0.08
        evidence.append("bill_number_region")
    if density_printed and freight_hits >= 2:
        scores[LAYOUT_STANDARD] += 0.10
        evidence.append("printed_form_density")

    if invoice_hits >= 3:
        scores[LAYOUT_INVOICE] += 0.48
        evidence.append("invoice_keywords")
    elif invoice_hits >= 2:
        scores[LAYOUT_INVOICE] += 0.32
        evidence.append("invoice_keywords")
    if header_invoice:
        scores[LAYOUT_INVOICE] += 0.22
        evidence.append("invoice_header_region")
    if "amount due" in blob or "subtotal" in blob:
        scores[LAYOUT_INVOICE] += 0.12
        evidence.append("invoice_totals")
    if invoice_hits >= 2 and freight_hits < 2:
        scores[LAYOUT_STANDARD] -= 0.12

    if table_hits >= 3:
        scores[LAYOUT_TABLE] += 0.40
        evidence.append("table_headers")
    if strong_cols >= 3 and strong_rows >= 3:
        scores[LAYOUT_TABLE] += 0.32
        evidence.append("table_structure")
    elif strong_cols >= 3:
        scores[LAYOUT_TABLE] += 0.18
        evidence.append("aligned_columns")
    if table_hits >= 3 and (strong_cols >= 3 or strong_rows >= 3):
        scores[LAYOUT_TABLE] += 0.12

    for key in list(scores):
        scores[key] = max(0.0, min(1.0, scores[key]))

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_class, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = best_score - second_score
    evidence = list(dict.fromkeys(evidence))

    if best_score < _MIN_SCORE:
        return unknown_classification(
            evidence=evidence or ["weak_or_ambiguous"],
            confidence=min(0.40, best_score if best_score else 0.20),
            features=features,
        )
    if margin < _MIN_MARGIN and second_score >= 0.30:
        return unknown_classification(
            evidence=evidence + ["ambiguous_layout_scores"],
            confidence=_clip(0.20 + best_score * 0.25),
            features=features,
        )

    confidence = _clip(0.52 + 0.35 * best_score + 0.40 * min(margin, 0.4), 0.55, 0.95)
    return {
        "layout_class": best_class,
        "confidence": confidence,
        "layout_confidence": confidence,
        "method": METHOD_DETERMINISTIC,
        "evidence": evidence,
        "features": features,
        "error": None,
    }


def classify_layout_safe(
    raw_text: Optional[str] = None,
    *,
    page_count: int = 0,
    page_images: Optional[Sequence[Any]] = None,
    layout: Optional[Dict[str, Any]] = None,
    spatial_items: Optional[Sequence[Dict[str, Any]]] = None,
    text_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Never raise: unknown classification on any failure so extraction can continue."""
    try:
        return classify_document_layout(
            raw_text,
            page_count=page_count,
            page_images=page_images,
            layout=layout,
            spatial_items=spatial_items,
            text_source=text_source,
        )
    except Exception as err:
        logger.warning("Layout classification failed; using unknown: %s", err)
        return unknown_classification(
            evidence=["classification_failed"],
            confidence=0.0,
            error=f"{type(err).__name__}: {err}",
        )


def attach_layout_classification(
    raw_ocr: Optional[Dict[str, Any]],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Write layout_classification onto OCR metadata only. Does not touch extracted values."""
    payload = classify_layout_safe(**kwargs)
    if isinstance(raw_ocr, dict):
        raw_ocr["layout_classification"] = payload
    return payload
