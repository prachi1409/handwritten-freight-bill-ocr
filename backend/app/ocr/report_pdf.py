"""Build a downloadable PDF: original bill pages plus extracted fields."""

from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymupdf as fitz

FIELD_GROUPS: List[Tuple[str, List[str]]] = [
    ("Bill identity", ["bill_number", "bill_date", "carrier"]),
    ("Parties & route", ["consignor", "consignee", "origin", "destination"]),
    ("Cargo", ["commodity_description", "quantity", "weight"]),
    ("Charges", ["freight_amount", "fuel_surcharge", "handling_charge", "total_amount"]),
    ("Logistics", ["vehicle_number", "driver_name", "pickup_time", "delivery_time"]),
    ("Proof of delivery", ["special_instructions", "driver_signature", "consignee_signature", "received_datetime"]),
]

_FIELD_LABELS = {
    "pickup_time": "Pickup time (first load in)",
    "delivery_time": "Delivery time (last load out)",
}

PAGE_W = 612.0
PAGE_H = 792.0
MARGIN = 50.0


def render_first_page_png(path: Path, zoom: float = 2.0) -> bytes:
    """Rasterize page 1 so the UI can show the bill without the browser PDF sidebar."""
    pdf = fitz.open(path)
    try:
        if pdf.page_count < 1:
            raise ValueError("Document has no pages")
        pix = pdf[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
    finally:
        pdf.close()


def _label(key: str) -> str:
    if key in _FIELD_LABELS:
        return _FIELD_LABELS[key]
    return key.replace("_", " ").title()


def _value_text(val: Any) -> str:
    if val is None or val == "" or val == [] or val == {}:
        return "Not detected"
    return str(val).strip() or "Not detected"


def _new_page(doc: fitz.Document) -> Tuple[fitz.Page, float]:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    return page, MARGIN + 8


def _need_page(doc: fitz.Document, page: fitz.Page, y: float, need: float) -> Tuple[fitz.Page, float]:
    if y + need <= PAGE_H - MARGIN:
        return page, y
    return _new_page(doc)


def build_extraction_report_pdf(
    bill_path: Path,
    extracted: Optional[Dict[str, Any]] = None,
    *,
    source_filename: str = "",
    status: str = "",
    confidence: Optional[float] = None,
) -> bytes:
    """PDF with original bill page(s) followed by labeled extracted fields."""
    data = extracted if isinstance(extracted, dict) else {}
    out = fitz.open()
    try:
        try:
            src = fitz.open(bill_path)
            try:
                if src.page_count > 0:
                    out.insert_pdf(src)
            finally:
                src.close()
        except Exception:
            png = render_first_page_png(bill_path, zoom=1.6)
            page, _ = _new_page(out)
            page.insert_image(fitz.Rect(36, 36, PAGE_W - 36, PAGE_H - 36), stream=png)

        page, y = _new_page(out)
        page.insert_text((MARGIN, y), "Extraction report", fontsize=16, fontname="hebo")
        y += 22
        meta_bits = []
        if source_filename:
            meta_bits.append(str(source_filename))
        if status:
            meta_bits.append(f"Status: {status}")
        if confidence is not None:
            meta_bits.append(f"Confidence: {confidence * 100:.0f}%")
        if meta_bits:
            page.insert_text((MARGIN, y), "  |  ".join(meta_bits), fontsize=9, fontname="helv")
            y += 18
        page.insert_text(
            (MARGIN, y),
            "Pickup / delivery times on multi-load tickets are first load in and last load out.",
            fontsize=8,
            fontname="helv",
            color=(0.35, 0.40, 0.48),
        )
        y += 20

        content_w = PAGE_W - 2 * MARGIN
        label_w = 170.0
        value_w = content_w - label_w - 8

        for title, keys in FIELD_GROUPS:
            page, y = _need_page(out, page, y, 36)
            page.insert_text((MARGIN, y), title, fontsize=12, fontname="hebo")
            y += 16
            for key in keys:
                val = _value_text(data.get(key))
                page, y = _need_page(out, page, y, 28)
                page.insert_text((MARGIN, y), _label(key), fontsize=9, fontname="hebo", color=(0.35, 0.40, 0.48))
                rect = fitz.Rect(MARGIN + label_w, y - 10, MARGIN + label_w + value_w, y + 36)
                leftover = page.insert_textbox(rect, val, fontsize=10, fontname="helv")
                extra = 14 if leftover >= 0 else 28
                y += extra
            y += 8

        items = data.get("line_items") if isinstance(data.get("line_items"), list) else []
        load_items = [
            item for item in items
            if isinstance(item, dict) and (
                item.get("load_arrive") or item.get("load_depart") or item.get("tag") or item.get("weight")
            )
        ]
        if load_items:
            page, y = _need_page(out, page, y, 40)
            page.insert_text((MARGIN, y), f"Loads ({len(load_items)})", fontsize=12, fontname="hebo")
            y += 16
            headers = "Item  Description          Tag       Weight    Load in   Load out  Unload in  Unload out"
            page.insert_text((MARGIN, y), headers, fontsize=8, fontname="hebo", color=(0.35, 0.40, 0.48))
            y += 14
            for idx, item in enumerate(load_items, start=1):
                page, y = _need_page(out, page, y, 18)
                desc = str(item.get("description") or "—")[:18]
                row = (
                    f"{item.get('item_no') or idx:<5} "
                    f"{desc:<20} "
                    f"{str(item.get('tag') or '—'):<10} "
                    f"{str(item.get('weight') or '—'):<10} "
                    f"{str(item.get('load_arrive') or '—'):<10} "
                    f"{str(item.get('load_depart') or '—'):<10} "
                    f"{str(item.get('unload_arrive') or '—'):<11} "
                    f"{str(item.get('unload_depart') or '—')}"
                )
                page.insert_text((MARGIN, y), row, fontsize=8, fontname="cour")
                y += 13
        elif items:
            page, y = _need_page(out, page, y, 40)
            page.insert_text((MARGIN, y), f"Line items ({len(items)})", fontsize=12, fontname="hebo")
            y += 16
            for idx, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                page, y = _need_page(out, page, y, 16)
                line = (
                    f"{item.get('item_no') or idx}. {item.get('description') or '—'}  "
                    f"qty {item.get('quantity') or '—'}  "
                    f"{item.get('amount') or '—'}"
                )
                page.insert_text((MARGIN, y), line[:110], fontsize=9, fontname="helv")
                y += 14

        buf = BytesIO()
        out.save(buf, deflate=True)
        return buf.getvalue()
    finally:
        out.close()
