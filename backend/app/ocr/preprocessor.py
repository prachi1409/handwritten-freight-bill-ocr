"""Image Preprocessing Module for Handwritten Document OCR Enhancement."""

import logging
from pathlib import Path
from typing import List
from PIL import Image, ImageEnhance, ImageFilter
import pymupdf as fitz  # PyMuPDF

from app.core.config import settings

logger = logging.getLogger(__name__)


def preprocess_pdf_pages(file_path: Path) -> List[Image.Image]:
    """Convert PDF pages to preprocessed PIL Images optimized for handwritten OCR.

    Applies high-DPI rendering (300 DPI), grayscale conversion, contrast enhancement,
    and mild line stroke sharpening while preserving thin ink pen strokes.

    Args:
        file_path: Path to target PDF document on disk.

    Returns:
        List of preprocessed PIL Image objects (one per PDF page).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF document file not found for preprocessing: '{path}'")

    dpi = getattr(settings, "TARGET_DPI", 300)
    zoom = dpi / 72.0  # Standard PDF resolution is 72 DPI
    mat = fitz.Matrix(zoom, zoom)

    processed_images: List[Image.Image] = []

    try:
        doc = fitz.open(path)
        logger.info(f"Preprocessing {len(doc)} page(s) for document '{path.name}' at {dpi} DPI...")

        for page_num, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            if getattr(settings, "ENABLE_IMAGE_PREPROCESSING", True):
                # 1. Convert to Grayscale
                gray_img = img.convert("L")

                # 2. Enhance Contrast (sharpens ink lines against paper background)
                contrast_factor = getattr(settings, "CONTRAST_ENHANCEMENT", 1.2)
                enhanced_img = ImageEnhance.Contrast(gray_img).enhance(contrast_factor)

                # 3. Mild stroke sharpening
                sharpened_img = enhanced_img.filter(ImageFilter.SHARPEN)

                # 4. Convert back to RGB for Document AI / OCR consumers
                final_img = sharpened_img.convert("RGB")
            else:
                final_img = img

            processed_images.append(final_img)
            logger.info(f"Page {page_num}/{len(doc)} preprocessed successfully ({pix.width}x{pix.height} px).")

        doc.close()

    except Exception as e:
        logger.warning(f"Image preprocessing notice for '{path.name}': {e}. Falling back to default rendering.")
        # Fallback rendering if PyMuPDF page pixmap fails
        doc = fitz.open(path)
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            processed_images.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
        doc.close()

    return processed_images

