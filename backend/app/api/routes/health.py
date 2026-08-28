"""Health check endpoint router."""

from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "ocr_provider": (settings.OCR_PROVIDER or "local").lower(),
    }

