"""Document OCR processing module."""

from app.ocr.base import BaseOCRProcessor, OCRResult
from app.ocr.factory import get_ocr_processor

__all__ = ["BaseOCRProcessor", "OCRResult", "get_ocr_processor"]

