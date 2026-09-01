"""Local / offline text and OCR extraction processor."""

import io
import logging
from pathlib import Path
from typing import List, Tuple

from PIL import Image
import pymupdf as fitz

from app.core.config import settings
from app.ocr.base import BaseOCRProcessor, OCRResult
from app.ocr.field_extractor import extract_freight_fields_from_text, merge_structured_and_text_fields
from app.ocr.intelligence import build_document_intelligence
from app.ocr.layout import extract_layout_blocks
from app.ocr.normalizer import normalize_freight_data
from app.ocr.ollama_extractor import extract_fields_with_ollama
from app.ocr.paddle_ocr import ocr_images_with_paddle
from app.ocr.preprocessor import preprocess_pdf_pages_with_meta

logger = logging.getLogger(__name__)


def _text_is_sparse(text: str) -> bool:
    """True when extracted text is too thin to trust for field parsing."""
    if not text or not text.strip():
        return True
    alnum = sum(ch.isalnum() for ch in text)
    return alnum < 40


def _extract_native_pdf_text(path: Path) -> str:
    """Read the PDF text layer, with PyMuPDF OCR only if a page has no text."""
    pages_text: List[str] = []
    doc = fitz.open(path)
    try:
        for idx, page in enumerate(doc, start=1):
            page_txt = page.get_text("text") or ""
            if not page_txt.strip():
                try:
                    page_txt = page.get_text("ocr") or ""
                except Exception as ocr_err:
                    logger.debug("Native-page OCR unavailable on page %s: %s", idx, ocr_err)
                    page_txt = ""
            if page_txt.strip():
                pages_text.append(f"--- PAGE {idx} ---\n{page_txt.strip()}")
    finally:
        doc.close()
    return "\n\n".join(pages_text)


def _ocr_pil_image(img: Image.Image, dpi: int) -> str:
    """OCR a preprocessed page image via an in-memory PDF + PyMuPDF OCR."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    width_pt = img.width * 72.0 / float(dpi)
    height_pt = img.height * 72.0 / float(dpi)
    doc = fitz.open()
    try:
        page = doc.new_page(width=width_pt, height=height_pt)
        page.insert_image(page.rect, stream=png_bytes)
        try:
            textpage = page.get_textpage_ocr(dpi=dpi, full=True, language="eng")
            text = page.get_text("text", textpage=textpage) or ""
        except Exception:
            try:
                text = page.get_text("ocr") or ""
            except Exception as ocr_err:
                logger.debug("Preprocessed-image OCR unavailable: %s", ocr_err)
                text = ""
        return text.strip()
    finally:
        doc.close()


def _ocr_preprocessed_images(images: List[Image.Image], dpi: int) -> str:
    pages_text: List[str] = []
    for idx, img in enumerate(images, start=1):
        page_txt = _ocr_pil_image(img, dpi)
        if page_txt:
            pages_text.append(f"--- PAGE {idx} ---\n{page_txt}")
    return "\n\n".join(pages_text)


def _choose_ocr_text(native_text: str, image_text: str) -> Tuple[str, str]:
    """Prefer the PDF text layer when it is rich; otherwise use preprocessed-image OCR."""
    native_sparse = _text_is_sparse(native_text)
    image_sparse = _text_is_sparse(image_text)
    if not native_sparse:
        return native_text, "pdf_text"
    if not image_sparse:
        return image_text, "preprocessed_image"
    if native_text.strip():
        return native_text, "pdf_text"
    return image_text, "preprocessed_image"


class LocalOCRProcessor(BaseOCRProcessor):
    """Offline OCR: preprocess pages, then extract text from the PDF and/or those images."""

    def process_document(self, file_path: Path) -> OCRResult:
        path = Path(file_path)
        logger.info("[OCR Flow] Step 1/5: Processing document '%s' via Local OCR Processor...", path.name)

        if not path.exists():
            raise FileNotFoundError(f"Source file not found for local processing: '{path}'")

        dpi = getattr(settings, "TARGET_DPI", 300)
        page_images, deskew_angles = preprocess_pdf_pages_with_meta(path)
        logger.info("[OCR Flow] Step 2/5: Preprocessed %s page image(s) for '%s'.", len(page_images), path.name)

        native_text = ""
        try:
            native_text = _extract_native_pdf_text(path)
        except Exception as e:
            logger.warning("[OCR Flow] Native PDF text extraction notice for '%s': %s", path.name, e)

        image_text = ""
        paddle_text = ""
        if _text_is_sparse(native_text):
            if getattr(settings, "ENABLE_PADDLE_OCR", True) and not settings.TESTING:
                try:
                    paddle_text = ocr_images_with_paddle(page_images)
                except Exception as e:
                    logger.warning("[OCR Flow] PaddleOCR notice for '%s': %s", path.name, e)
            if _text_is_sparse(paddle_text):
                try:
                    image_text = _ocr_preprocessed_images(page_images, dpi)
                except Exception as e:
                    logger.warning("[OCR Flow] Preprocessed-image OCR notice for '%s': %s", path.name, e)
            else:
                image_text = paddle_text
                logger.info("[OCR Flow] Using PaddleOCR text for '%s' (%s chars).", path.name, len(paddle_text))
        else:
            logger.info(
                "[OCR Flow] PDF text layer is rich; skipping image OCR for '%s'.",
                path.name,
            )

        raw_text, text_source = _choose_ocr_text(native_text, image_text)
        if paddle_text.strip() and text_source == "preprocessed_image" and not _text_is_sparse(paddle_text):
            text_source = "paddleocr"

        logger.info(
            "[OCR Debug] RAW EXTRACTED TEXT for '%s' (source=%s, length=%s):",
            path.name,
            text_source,
            len(raw_text),
        )
        if raw_text.strip():
            snippet = raw_text.strip()[:300].replace("\n", " ")
            logger.info("[OCR Debug] Content Preview: '%s'", snippet)
        else:
            logger.warning("[OCR Debug] RAW EXTRACTED TEXT is EMPTY for '%s'.", path.name)

        regex_dict = extract_freight_fields_from_text(raw_text)
        llm_dict = extract_fields_with_ollama(raw_text)
        if llm_dict:
            raw_dict = merge_structured_and_text_fields(llm_dict, raw_text)
            logger.info("[OCR Flow] Field source for '%s': ollama + regex fallback", path.name)
        else:
            raw_dict = regex_dict
            logger.info("[OCR Flow] Field source for '%s': regex", path.name)

        logger.info("[OCR Flow] Step 3/5: Field Extraction Results for '%s':", path.name)
        for k, v in raw_dict.items():
            if k != "line_items":
                logger.info("  - %s: %r", k, v)
        logger.info("  - line_items count: %s", len(raw_dict.get("line_items") or []))

        normalized = normalize_freight_data(raw_dict, raw_text=raw_text, base_confidence=0.95)
        intel = build_document_intelligence(
            raw_text,
            page_images=page_images,
            page_count=len(page_images),
        )
        normalized["document_type"] = intel["document_type"]
        normalized["scan_quality"] = intel["quality_score"]

        layout = {"block_count": 0, "blocks": []}
        try:
            layout = extract_layout_blocks(path)
        except Exception as e:
            logger.debug("Layout reconstruction skipped for '%s': %s", path.name, e)

        logger.info(
            "[OCR Flow] Step 4/5: Normalized confidence for '%s': %.1f%%",
            path.name,
            normalized["ocr_confidence"] * 100,
        )

        raw_ocr = {
            "processor": "local-ocr-processor",
            "source": "local",
            "status": "COMPLETED",
            "raw_text": raw_text,
            "ocr_confidence": normalized["ocr_confidence"],
            "line_items": normalized["line_items"],
            "page_count": len(page_images),
            "ocr_text_source": text_source,
            "field_source": "ollama+regex" if llm_dict else "regex",
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
            raw_text=raw_text,
            raw_ocr=raw_ocr,
            confidence=normalized["ocr_confidence"],
            processor="local-ocr-processor",
        )
