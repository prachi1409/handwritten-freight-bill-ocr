"""Document intelligence: type, page count, and scan-quality heuristics."""

import logging
from typing import Any, Dict, List, Optional

from PIL import Image, ImageStat

logger = logging.getLogger(__name__)

_FREIGHT_KEYWORDS = (
    "freight", "bill of lading", "bill no", "consignor", "consignee",
    "shipper", "waybill", "bol", "cargo", "manifest", "truck",
)


def classify_document_type(raw_text: str) -> str:
    """Return freight_bill when enough logistics keywords appear, else unknown."""
    blob = (raw_text or "").lower()
    hits = sum(1 for kw in _FREIGHT_KEYWORDS if kw in blob)
    return "freight_bill" if hits >= 2 else "unknown"


def assess_page_quality(img: Image.Image) -> Dict[str, Any]:
    """Estimate scan quality from luminance mean and contrast (stddev)."""
    gray = img.convert("L")
    stats = ImageStat.Stat(gray)
    mean = float(stats.mean[0])
    std = float(stats.stddev[0])
    quality = round(min(1.0, max(0.0, std / 55.0)), 2)
    flags: List[str] = []
    if std < 12:
        flags.append("low_contrast")
    if mean < 35:
        flags.append("too_dark")
    if mean > 240:
        flags.append("too_light")
    if gray.width < 600 or gray.height < 600:
        flags.append("low_resolution")
    return {
        "quality_score": quality,
        "mean_luminance": round(mean, 1),
        "contrast_std": round(std, 1),
        "flags": flags,
        "width": gray.width,
        "height": gray.height,
    }


def build_document_intelligence(
    raw_text: str,
    page_images: Optional[List[Image.Image]] = None,
    page_count: int = 0,
) -> Dict[str, Any]:
    """Combine type classification with per-document quality summary."""
    images = page_images or []
    qualities = [assess_page_quality(img) for img in images]
    avg_quality = (
        round(sum(q["quality_score"] for q in qualities) / len(qualities), 2)
        if qualities else 0.0
    )
    flags: List[str] = []
    for q in qualities:
        flags.extend(q.get("flags") or [])
    unique_flags = sorted(set(flags))
    doc_type = classify_document_type(raw_text)
    intel = {
        "document_type": doc_type,
        "page_count": page_count or len(images),
        "quality_score": avg_quality,
        "quality_flags": unique_flags,
        "pages": qualities,
    }
    logger.info(
        "Document intelligence: type=%s pages=%s quality=%s flags=%s",
        doc_type,
        intel["page_count"],
        avg_quality,
        unique_flags,
    )
    return intel
