"""Image preprocessing for handwritten document OCR."""

import logging
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pymupdf as fitz

from app.core.config import settings

logger = logging.getLogger(__name__)


def _horizontal_projection_variance(bw: Image.Image) -> float:
    """Ink-row variance: higher means text lines are more horizontal (less skewed)."""
    gray = bw.convert("L")
    w, h = gray.size
    if w < 8 or h < 8:
        return 0.0
    pixels = gray.tobytes()
    row_sums = []
    for y in range(h):
        start = y * w
        row = pixels[start:start + w]
        row_sums.append(sum(1 for p in row if p < 160))
    mean = sum(row_sums) / len(row_sums)
    return sum((v - mean) ** 2 for v in row_sums) / len(row_sums)


def deskew_image(img: Image.Image, max_angle: float = 12.0) -> Tuple[Image.Image, float]:
    """Estimate skew from a downscaled copy and rotate the full image."""
    probe = ImageOps.autocontrast(img.convert("L"))
    probe.thumbnail((480, 640), Image.Resampling.BILINEAR)

    best_angle = 0.0
    best_score = -1.0
    angle = -max_angle
    while angle <= max_angle + 1e-6:
        rotated = probe.rotate(angle, expand=True, fillcolor=255)
        score = _horizontal_projection_variance(rotated)
        if score > best_score:
            best_score = score
            best_angle = angle
        angle += 1.0

    if abs(best_angle) < 0.5:
        return img, 0.0

    fill = 255 if img.mode == "L" else (255, 255, 255)
    corrected = img.rotate(
        best_angle,
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor=fill,
    )
    logger.info("Deskewed page by %.1f degrees", best_angle)
    return corrected, best_angle


def enhance_page_image(img: Image.Image) -> Tuple[Image.Image, float]:
    """Grayscale, optional deskew, contrast, sharpen, and mild denoise."""
    deskew_angle = 0.0
    work = img.convert("L")

    if getattr(settings, "DESKEW_IMAGE", True):
        work, deskew_angle = deskew_image(work)

    contrast_factor = getattr(settings, "CONTRAST_ENHANCEMENT", 1.2)
    work = ImageEnhance.Contrast(work).enhance(contrast_factor)
    work = work.filter(ImageFilter.SHARPEN)
    work = work.filter(ImageFilter.MedianFilter(size=3))
    return work.convert("RGB"), deskew_angle


def preprocess_pdf_pages(file_path: Path) -> List[Image.Image]:
    """Render PDF pages at TARGET_DPI and return enhanced RGB images."""
    images, _angles = preprocess_pdf_pages_with_meta(file_path)
    return images


def preprocess_pdf_pages_with_meta(file_path: Path) -> Tuple[List[Image.Image], List[float]]:
    """Like preprocess_pdf_pages, also returning per-page deskew angles."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF document file not found for preprocessing: '{path}'")

    dpi = getattr(settings, "TARGET_DPI", 300)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    processed_images: List[Image.Image] = []
    deskew_angles: List[float] = []

    try:
        doc = fitz.open(path)
        logger.info("Preprocessing %s page(s) for '%s' at %s DPI...", len(doc), path.name, dpi)

        for page_num, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            angle = 0.0

            if getattr(settings, "ENABLE_IMAGE_PREPROCESSING", True):
                img, angle = enhance_page_image(img)

            processed_images.append(img)
            deskew_angles.append(angle)
            logger.info(
                "Page %s/%s preprocessed (%sx%s px, deskew %.1f deg).",
                page_num,
                len(doc),
                img.width,
                img.height,
                angle,
            )

        doc.close()

    except Exception as e:
        logger.warning("Image preprocessing notice for '%s': %s. Falling back to default rendering.", path.name, e)
        processed_images = []
        deskew_angles = []
        doc = fitz.open(path)
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            processed_images.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
            deskew_angles.append(0.0)
        doc.close()

    return processed_images, deskew_angles
