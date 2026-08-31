"""Abstract Base Class interface for Document OCR processors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class OCRResult:
    """Standardized OCR extraction result container."""
    extracted_data: Dict[str, Any]
    raw_text: str
    raw_ocr: Dict[str, Any]
    confidence: float
    processor: str
    field_confidence: Dict[str, float] = field(default_factory=dict)
    ocr_metadata: Dict[str, Any] = field(default_factory=dict)
    validation_warnings: List[str] = field(default_factory=list)
    page_count: int = 1
    processed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseOCRProcessor(ABC):
    """Abstract interface for all OCR processor implementations (Local, Google Document AI, Mock)."""

    @abstractmethod
    def process_document(self, file_path: Path) -> OCRResult:
        """Process document file and return standardized OCRResult.

        Args:
            file_path: Absolute or relative Path to document file on disk.

        Returns:
            OCRResult containing extracted structured fields, field-level confidence, and metadata.
        """
        pass
