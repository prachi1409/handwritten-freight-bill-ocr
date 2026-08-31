"""Local / offline text and OCR extraction processor using PyMuPDF 300 DPI rendering and RapidOCR vision engine with spatial layout geometry."""

import io
import os
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any

import numpy as np
from PIL import Image
import pymupdf as fitz

from app.core.config import settings
from app.ocr.base import BaseOCRProcessor, OCRResult
from app.ocr.field_extractor import extract_freight_fields_from_text
from app.ocr.spatial_extractor import extract_fields_via_spatial_layout
from app.ocr.intelligence import build_document_intelligence
from app.ocr.layout import extract_layout_blocks
from app.ocr.normalizer import normalize_freight_data
from app.ocr.preprocessor import preprocess_pdf_pages_with_meta

logger = logging.getLogger(__name__)

_RAPID_OCR_ENGINE = None


def get_rapid_ocr_engine():
    """Lazy initialize and return cached RapidOCR vision engine."""
    global _RAPID_OCR_ENGINE
    if _RAPID_OCR_ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            logger.info("Initializing RapidOCR local vision engine...")
            _RAPID_OCR_ENGINE = RapidOCR()
            logger.info("RapidOCR engine initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize RapidOCR engine: {e}", exc_info=True)
            _RAPID_OCR_ENGINE = False
    return _RAPID_OCR_ENGINE


def _text_is_sparse(text: str) -> bool:
    """True when extracted text is too thin to trust for field parsing."""
    if not text or not text.strip():
        return True
    alnum = sum(ch.isalnum() for ch in text)
    return alnum < 40


def _choose_ocr_text(native_text: str, image_text: str) -> Tuple[str, str]:
    """Determine whether to use native PDF text layer or RapidOCR image text."""
    if not _text_is_sparse(native_text):
        return native_text, "pdf_text"
    if image_text and image_text.strip():
        return image_text, "preprocessed_image"
    return native_text or image_text or "", "empty"


def _extract_native_pdf_text(path: Path) -> str:
    """Read the PDF text layer using PyMuPDF."""
    pages_text: List[str] = []
    doc = fitz.open(path)
    try:
        for idx, page in enumerate(doc, start=1):
            page_txt = page.get_text("text") or ""
            if page_txt.strip():
                pages_text.append(f"--- PAGE {idx} ---\n{page_txt.strip()}")
    finally:
        doc.close()
    return "\n\n".join(pages_text)


def _ocr_preprocessed_images_via_rapidocr(images: List[Image.Image]) -> Tuple[str, List[float], List[Dict[str, Any]]]:
    """Run RapidOCR vision engine directly over preprocessed 300 DPI page images, returning text, confidences, and spatial items."""
    engine = get_rapid_ocr_engine()
    if not engine:
        logger.warning("RapidOCR engine is unavailable. Skipping image OCR.")
        return "", [], []

    pages_text: List[str] = []
    all_confidences: List[float] = []
    spatial_items: List[Dict[str, Any]] = []

    for idx, img in enumerate(images, start=1):
        img_np = np.array(img.convert("RGB"))
        ocr_result, elapse = engine(img_np)

        page_lines: List[str] = []
        if ocr_result:
            for item in ocr_result:
                if len(item) >= 2:
                    bbox = item[0]
                    text = item[1].strip()
                    conf = float(item[2]) if len(item) >= 3 else 0.85

                    if text:
                        page_lines.append(text)
                        all_confidences.append(conf)

                        xs = [pt[0] for pt in bbox]
                        ys = [pt[1] for pt in bbox]
                        min_x, max_x = min(xs), max(xs)
                        min_y, max_y = min(ys), max(ys)

                        spatial_items.append({
                            "bbox": [min_x, min_y, max_x, max_y],
                            "center_x": (min_x + max_x) / 2.0,
                            "center_y": (min_y + max_y) / 2.0,
                            "width": max_x - min_x,
                            "height": max_y - min_y,
                            "text": text,
                            "conf": conf,
                            "page": idx,
                        })

        if page_lines:
            pages_text.append(f"--- PAGE {idx} ---\n" + "\n".join(page_lines))

    return "\n\n".join(pages_text), all_confidences, spatial_items


class LocalOCRProcessor(BaseOCRProcessor):
    """Offline OCR: preprocess pages to 300 DPI images, then extract text & spatial geometry via RapidOCR."""

    def process_document(self, file_path: Path) -> OCRResult:
        path = Path(file_path).resolve()
        logger.info(f"[OCR Flow] Step 1/5: Processing document '{path.name}' via Local OCR Processor...")

        if not path.exists():
            raise FileNotFoundError(f"Source file not found for local processing: '{path}'")

        file_size_bytes = os.path.getsize(path)
        dpi = getattr(settings, "TARGET_DPI", 300)
        page_images, deskew_angles = preprocess_pdf_pages_with_meta(path)
        page_count = len(page_images)

        img_dims = [f"{img.width}x{img.height}" for img in page_images]
        logger.info(f"[OCR Diagnostic] PDF Path: '{path}'")
        logger.info(f"[OCR Diagnostic] File Size: {file_size_bytes} bytes, Page Count: {page_count}")
        logger.info(f"[OCR Diagnostic] Rendered Image Dims at {dpi} DPI: {img_dims}")

        native_text = ""
        try:
            native_text = _extract_native_pdf_text(path)
        except Exception as e:
            logger.warning(f"[OCR Flow] Native PDF text extraction notice for '{path.name}': {e}")

        image_text = ""
        rapid_confidences: List[float] = []
        spatial_items: List[Dict[str, Any]] = []
        ocr_engine_used = "PyMuPDF Native Text Layer"

        if _text_is_sparse(native_text):
            logger.info(f"[OCR Flow] PDF text layer is sparse/empty for '{path.name}'. Running RapidOCR vision engine over 300 DPI rendered page images...")
            ocr_engine_used = "RapidOCR Vision Engine (ONNX)"
            try:
                image_text, rapid_confidences, spatial_items = _ocr_preprocessed_images_via_rapidocr(page_images)
            except Exception as e:
                logger.error(f"[OCR Flow] RapidOCR vision engine execution error for '{path.name}': {e}", exc_info=True)

        raw_text, text_source = _choose_ocr_text(native_text, image_text)

        logger.info(f"[OCR Diagnostic] Engine Used: {ocr_engine_used}")
        logger.info(f"[OCR Diagnostic] Raw Text Length: {len(raw_text)} chars (Source: {text_source})")
        if raw_text.strip():
            snippet = raw_text.strip()[:300].replace("\n", " ")
            logger.info(f"[OCR Diagnostic] Content Preview: '{snippet}'")

        # 3. Spatial & Text Field Extraction
        raw_dict = {}
        field_meta = {}

        if spatial_items:
            spatial_dict, field_meta = extract_fields_via_spatial_layout(spatial_items)
            text_dict = extract_freight_fields_from_text(raw_text)

            raw_dict = {"document_type": "freight_bill"}
            for k in ("bill_number", "bill_date", "carrier", "invoice_number", "consignor", "consignee", "origin", "destination", "commodity_description", "quantity", "weight", "freight_amount", "total_amount", "vehicle_number", "driver_name", "pickup_time", "delivery_time", "special_instructions"):
                if spatial_dict.get(k):
                    raw_dict[k] = spatial_dict[k]
                else:
                    raw_dict[k] = text_dict.get(k)
            raw_dict["line_items"] = text_dict.get("line_items") or []
        else:
            raw_dict = extract_freight_fields_from_text(raw_text)

        if field_meta:
            raw_dict["field_metadata"] = field_meta

        extracted_field_count = sum(1 for k, v in raw_dict.items() if k not in ("document_type", "line_items", "field_metadata") and v not in (None, "", []))
        logger.info(f"[OCR Flow] Step 3/5: Extracted {extracted_field_count} structured field(s) for '{path.name}':")
        for k, v in raw_dict.items():
            if k not in ("line_items", "field_metadata"):
                logger.info(f"  - {k}: {v!r}")

        # 4. Normalization & Confidence Calculation
        normalized = normalize_freight_data(raw_dict, raw_text=raw_text)
        intel = build_document_intelligence(raw_text, page_images=page_images, page_count=page_count)
        normalized["document_type"] = intel["document_type"]
        normalized["scan_quality"] = intel["quality_score"]

        layout = {"block_count": 0, "blocks": []}
        try:
            layout = extract_layout_blocks(path)
        except Exception as e:
            logger.debug(f"Layout reconstruction skipped for '{path.name}': {e}")

        overall_conf = normalized["ocr_confidence"]
        logger.info(f"[OCR Flow] Step 4/5: Overall Extraction Confidence for '{path.name}': {overall_conf * 100:.1f}%")

        raw_ocr = {
            "processor": "local-ocr-processor",
            "ocr_engine": ocr_engine_used,
            "ocr_text_source": text_source,
            "source": text_source,
            "status": "COMPLETED" if raw_text.strip() else "EMPTY",
            "raw_text": raw_text if raw_text.strip() else "Raw OCR output is empty",
            "ocr_confidence": overall_conf,
            "field_confidence": normalized.get("field_confidence", {}),
            "field_metadata": field_meta,
            "line_items": normalized["line_items"],
            "page_count": page_count,
            "preprocessing": {
                "dpi": dpi,
                "deskew_enabled": bool(getattr(settings, "DESKEW_IMAGE", True)),
                "deskew_angles": deskew_angles,
                "contrast": getattr(settings, "CONTRAST_ENHANCEMENT", 1.2),
            },
            "document_intelligence": intel,
            "layout": layout,
        }

        return OCRResult(
            extracted_data=normalized,
            raw_text=raw_text if raw_text.strip() else "Raw OCR output is empty",
            raw_ocr=raw_ocr,
            confidence=overall_conf,
            processor="local-ocr-processor",
            field_confidence=normalized.get("field_confidence", {}),
            validation_warnings=normalized.get("validation_warnings", []),
            page_count=page_count,
        )
