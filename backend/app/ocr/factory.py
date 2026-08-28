"""Factory for selecting and instantiating OCR Processors."""

import logging
from app.core.config import settings
from app.ocr.base import BaseOCRProcessor
from app.ocr.local_processor import LocalOCRProcessor
from app.ocr.mock_ai import MockDocumentAIProcessor
from app.ocr.document_ai import GoogleDocumentAIProcessor

logger = logging.getLogger(__name__)


def get_ocr_processor() -> BaseOCRProcessor:
    """Return the OCR processor for the current environment.

    Production default is Google Document AI. Local OCR is used for unit tests
    and as a fallback when GCP credentials or the API are unavailable.

    OCR_PROVIDER values:
        document_ai — Google Document AI (default)
        local — offline PyMuPDF extraction
        mock — canned freight-bill payload (dev only)
    """
    provider = (settings.OCR_PROVIDER or "document_ai").strip().lower()

    # Unit tests must not call Google Cloud. conftest sets TESTING=True.
    if settings.TESTING:
        logger.info("TESTING=true: using Local OCR Processor")
        return LocalOCRProcessor()

    if provider == "mock" or (settings.USE_MOCK_OCR and not settings.document_ai_configured):
        logger.info("Using Mock Document AI Processor")
        return MockDocumentAIProcessor()

    if provider == "local":
        logger.info("Using Local OCR Processor (OCR_PROVIDER='local')")
        return LocalOCRProcessor()

    # document_ai (default) and any unknown provider: prefer Google when configured
    if not settings.document_ai_configured:
        logger.warning(
            "OCR_PROVIDER is '%s' but GOOGLE_CLOUD_PROJECT_ID or "
            "DOCUMENT_AI_PROCESSOR_ID is missing. Falling back to Local OCR Processor.",
            provider,
        )
        return LocalOCRProcessor()

    try:
        logger.info("Initializing Google Document AI Processor...")
        return GoogleDocumentAIProcessor()
    except Exception as e:
        logger.warning(
            "Failed to initialize Google Document AI Processor (%s). "
            "Falling back to Local OCR Processor.",
            e,
        )
        return LocalOCRProcessor()
