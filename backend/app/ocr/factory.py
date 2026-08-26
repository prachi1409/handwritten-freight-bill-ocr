"""Factory for selecting and instantiating OCR Processors."""

import logging
from app.core.config import settings
from app.ocr.base import BaseOCRProcessor
from app.ocr.local_processor import LocalOCRProcessor
from app.ocr.mock_ai import MockDocumentAIProcessor
from app.ocr.document_ai import GoogleDocumentAIProcessor

logger = logging.getLogger(__name__)


def get_ocr_processor() -> BaseOCRProcessor:
    """Return the configured OCR Processor implementation.

    Checks OCR_PROVIDER setting ('local' vs 'document_ai'). Defaults to LocalOCRProcessor
    when billing is not enabled or if Google Cloud Document AI credentials fail.

    Returns:
        Instance implementing BaseOCRProcessor interface.
    """
    provider = (getattr(settings, "OCR_PROVIDER", "local") or "local").lower()

    if provider == "local" or getattr(settings, "USE_MOCK_OCR", False):
        logger.info("Using Local OCR Processor (OCR_PROVIDER='local')")
        return LocalOCRProcessor()

    if provider == "document_ai":
        if not settings.GOOGLE_CLOUD_PROJECT_ID or not settings.DOCUMENT_AI_PROCESSOR_ID:
            logger.warning(
                "GCP Project ID or Processor ID missing in configuration. "
                "Falling back to Local OCR Processor."
            )
            return LocalOCRProcessor()

        try:
            logger.info("Initializing Google Document AI Processor...")
            return GoogleDocumentAIProcessor()
        except Exception as e:
            logger.warning(
                f"Failed to initialize Google Document AI Processor ({e}). "
                "Falling back to Local OCR Processor."
            )
            return LocalOCRProcessor()

    logger.info("Defaulting to Local OCR Processor.")
    return LocalOCRProcessor()
