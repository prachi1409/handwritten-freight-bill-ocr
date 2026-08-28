"""Unit tests for PDF document validator."""

from app.ingestion.validator import validate_pdf


def test_valid_pdf_passes_validation(create_pdf):
    """Verify genuine PyMuPDF PDF returns is_valid=True."""
    pdf_path = create_pdf("valid_bill.pdf", "Freight Bill #1001")
    result = validate_pdf(pdf_path)

    assert result.is_valid is True
    assert result.page_count == 1
    assert result.error_message is None


def test_non_pdf_extension_fails_validation(tmp_path):
    """Verify non-PDF extension is rejected."""
    txt_path = tmp_path / "freight_notes.txt"
    txt_path.write_text("Driver notes...")

    result = validate_pdf(txt_path)

    assert result.is_valid is False
    assert "PDF" in result.error_message or "extension" in result.error_message.lower()


def test_missing_file_fails_validation(tmp_path):
    """Verify missing file returns is_valid=False."""
    missing_path = tmp_path / "ghost.pdf"
    result = validate_pdf(missing_path)

    assert result.is_valid is False
    assert "does not exist" in result.error_message


def test_corrupted_pdf_fails_validation(tmp_path):
    """Verify corrupted PDF structure is caught gracefully without raising exceptions."""
    corrupt_path = tmp_path / "corrupt.pdf"
    corrupt_path.write_bytes(b"THIS IS NOT A REAL PDF HEADER OR DATA")

    result = validate_pdf(corrupt_path)

    assert result.is_valid is False
    assert result.error_message is not None
    assert "Corrupted" in result.error_message or "Failed" in result.error_message

