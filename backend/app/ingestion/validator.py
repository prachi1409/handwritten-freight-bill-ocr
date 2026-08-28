"""PDF Document validator using PyMuPDF (pymupdf)."""

import logging
from pathlib import Path
from typing import Optional, Union
import pymupdf as fitz  # PyMuPDF
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    """Result container for PDF validation check."""
    is_valid: bool
    error_message: Optional[str] = None
    page_count: int = 0


def validate_pdf(file_path: Union[str, Path]) -> ValidationResult:
    """Validate that a file exists, is a PDF, and can be read by PyMuPDF.

    Args:
        file_path: Path to the target document.

    Returns:
        ValidationResult indicating validity status and error details if invalid.
    """
    path = Path(file_path)

    if not path.exists():
        msg = f"File does not exist: '{path}'"
        logger.warning(msg)
        return ValidationResult(is_valid=False, error_message=msg)

    if not path.is_file():
        msg = f"Path is not a file: '{path}'"
        logger.warning(msg)
        return ValidationResult(is_valid=False, error_message=msg)

    if path.suffix.lower() != ".pdf":
        from app.ingestion.convert import IMAGE_EXTENSIONS, convert_image_to_pdf
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                path = convert_image_to_pdf(path)
            except Exception as e:
                msg = f"Failed to convert image to PDF: {e}"
                logger.warning("File '%s': %s", path.name, msg)
                return ValidationResult(is_valid=False, error_message=msg)
        else:
            msg = f"Invalid extension '{path.suffix}'. Expected PDF, JPG, PNG, or TIFF"
            logger.warning(f"File '{path.name}': {msg}")
            return ValidationResult(is_valid=False, error_message=msg)

    doc = None
    try:
        doc = fitz.open(path)
        if doc.is_encrypted:
            msg = "PDF document is password encrypted"
            logger.warning(f"File '{path.name}': {msg}")
            return ValidationResult(is_valid=False, error_message=msg)

        page_count = doc.page_count
        if page_count <= 0:
            msg = "PDF document contains 0 pages"
            logger.warning(f"File '{path.name}': {msg}")
            return ValidationResult(is_valid=False, error_message=msg)

        logger.debug(f"File '{path.name}' validated successfully with {page_count} pages.")
        return ValidationResult(is_valid=True, page_count=page_count)

    except fitz.FileDataError as e:
        msg = f"Corrupted or invalid PDF structure: {e}"
        logger.warning(f"File '{path.name}': {msg}")
        return ValidationResult(is_valid=False, error_message=msg)
    except Exception as e:
        msg = f"Failed to open/read PDF: {e}"
        logger.error(f"File '{path.name}': {msg}")
        return ValidationResult(is_valid=False, error_message=msg)
    finally:
        if doc is not None:
            doc.close()

