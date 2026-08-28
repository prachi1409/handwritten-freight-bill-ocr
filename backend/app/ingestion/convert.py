"""Convert raster scans (JPG/PNG/TIFF) into a one-page PDF for the OCR pipeline."""

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
ALLOWED_EXTENSIONS = {".pdf"} | IMAGE_EXTENSIONS


def is_supported_document(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_EXTENSIONS


def convert_image_to_pdf(image_path: Path) -> Path:
    """Write a sibling .pdf next to the image and return that path."""
    source = Path(image_path)
    dest = source.with_suffix(".pdf")
    with Image.open(source) as img:
        rgb = img.convert("RGB")
        rgb.save(dest, "PDF", resolution=150.0)
    logger.info("Converted image '%s' -> '%s'", source.name, dest.name)
    return dest


def ensure_pdf(path: Path) -> Path:
    """Return a PDF path, converting raster images when needed."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return path
    if suffix in IMAGE_EXTENSIONS:
        return convert_image_to_pdf(path)
    raise ValueError(f"Unsupported file type '{path.suffix}'. Use PDF, JPG, PNG, or TIFF.")
