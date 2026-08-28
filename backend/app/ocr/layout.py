"""Lightweight layout reconstruction from PDF text blocks."""

import logging
from pathlib import Path
from typing import Any, Dict, List

import pymupdf as fitz

logger = logging.getLogger(__name__)

_MAX_BLOCKS = 200


def extract_layout_blocks(file_path: Path) -> Dict[str, Any]:
    """Read blocks in visual order with bounding boxes (PDF points)."""
    path = Path(file_path)
    blocks: List[Dict[str, Any]] = []
    doc = fitz.open(path)
    try:
        for page_index, page in enumerate(doc, start=1):
            payload = page.get_text("dict") or {}
            page_blocks = payload.get("blocks") or []
            readable = []
            for block in page_blocks:
                if block.get("type") != 0:
                    continue
                lines = []
                for line in block.get("lines") or []:
                    spans = line.get("spans") or []
                    line_text = "".join(str(span.get("text") or "") for span in spans).strip()
                    if line_text:
                        lines.append(line_text)
                text = " ".join(lines).strip()
                if not text:
                    continue
                bbox = block.get("bbox") or [0, 0, 0, 0]
                readable.append({
                    "page": page_index,
                    "text": text[:500],
                    "bbox": [round(float(v), 2) for v in bbox],
                })
            readable.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
            for order, item in enumerate(readable, start=1):
                item["reading_order"] = order
                blocks.append(item)
                if len(blocks) >= _MAX_BLOCKS:
                    break
            if len(blocks) >= _MAX_BLOCKS:
                break
    finally:
        doc.close()

    logger.info("Layout reconstruction extracted %s text block(s) from '%s'", len(blocks), path.name)
    return {
        "block_count": len(blocks),
        "blocks": blocks,
    }
