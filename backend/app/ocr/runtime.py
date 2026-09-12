"""Per-request OCR runtime flags. Upload stays cheap-first; reprocess can enable Groq primary."""

from __future__ import annotations

from contextvars import ContextVar

from app.core.config import settings

# True only inside DocumentService.reprocess_document.
groq_vision_primary = ContextVar("groq_vision_primary", default=False)


def groq_vision_primary_enabled() -> bool:
    """Reprocess-only: Groq Vision is the first field extractor. Uploads never set this."""
    if getattr(settings, "TESTING", False):
        return False
    if not getattr(settings, "GROQ_VISION_PRIMARY_ON_REPROCESS", True):
        return False
    if not getattr(settings, "ENABLE_GROQ_VISION", True):
        return False
    return bool(groq_vision_primary.get())
