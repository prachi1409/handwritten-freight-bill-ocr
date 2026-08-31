"""Unit tests for document scanning and ingestion service."""

import shutil
from app.db.models import Document, DocumentStatus
from app.ingestion.scanner import process_ingestion_batch


def test_batch_ingestion_new_files(db_session, create_pdf, tmp_path):
    """Verify batch ingestion scans folder and inserts & processes documents."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    pdf1 = create_pdf("bill_001.pdf", "Bill 1 Content")
    pdf2 = create_pdf("bill_002.pdf", "Bill 2 Content")

    shutil.copy(pdf1, input_dir / "bill_001.pdf")
    shutil.copy(pdf2, input_dir / "bill_002.pdf")

    result = process_ingestion_batch(db_session, input_dir)

    assert result.total_scanned == 2
    assert result.ingested_count == 2
    assert result.duplicate_count == 0
    assert result.invalid_count == 0
    assert result.failed_count == 0

    # Verify Database records
    docs = db_session.query(Document).all()
    assert len(docs) == 2
    assert {d.original_filename for d in docs} == {"bill_001.pdf", "bill_002.pdf"}
    assert all(d.status in [DocumentStatus.REVIEW, DocumentStatus.COMPLETED, DocumentStatus.PENDING] for d in docs)
    assert all(d.created_at is not None for d in docs)


def test_batch_ingestion_duplicate_detection(db_session, create_pdf, tmp_path):
    """Verify duplicate file with identical content is detected by SHA-256 hash and skipped."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    original_pdf = create_pdf("bill_original.pdf", "Identical Freight Data 555")

    # Copy original file to input folder under two different names
    shutil.copy(original_pdf, input_dir / "bill_001.pdf")
    shutil.copy(original_pdf, input_dir / "bill_001_copy.pdf")

    result = process_ingestion_batch(db_session, input_dir)

    assert result.total_scanned == 2
    assert result.ingested_count == 1
    assert result.duplicate_count == 1

    # Verify DB only contains 1 document row
    docs = db_session.query(Document).all()
    assert len(docs) == 1
    assert docs[0].original_filename == "bill_001.pdf"


def test_batch_ingestion_handles_invalid_files(db_session, create_pdf, tmp_path):
    """Verify corrupted PDF in batch is marked INVALID without crashing batch."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    valid_pdf = create_pdf("valid_bill.pdf", "Valid Content")
    shutil.copy(valid_pdf, input_dir / "valid_bill.pdf")

    # Create invalid corrupt pdf
    corrupt_pdf = input_dir / "corrupt_bill.pdf"
    corrupt_pdf.write_bytes(b"INVALID CORRUPTED DATA")

    result = process_ingestion_batch(db_session, input_dir)

    assert result.total_scanned == 2
    assert result.ingested_count == 1
    assert result.invalid_count == 1

    # DB should contain only valid document
    docs = db_session.query(Document).all()
    assert len(docs) == 1
    assert docs[0].original_filename == "valid_bill.pdf"
