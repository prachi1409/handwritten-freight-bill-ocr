"""Tests for moving processed inbox PDFs into processed_documents."""

from pathlib import Path

from app.core.config import settings
from app.db.models import Document
from app.ingestion.archive import archive_inbox_file
from app.ingestion.scanner import find_pdf_files, process_ingestion_batch


def test_archive_moves_file_from_inbox_to_processed(monkeypatch, tmp_path, create_pdf):
    inbox = tmp_path / "input_doc_location"
    processed = tmp_path / "processed_documents"
    inbox.mkdir()
    processed.mkdir()
    monkeypatch.setattr(settings, "INPUT_DOC_LOCATION", str(inbox))
    monkeypatch.setattr(settings, "PROCESSED_DOCUMENTS_LOCATION", str(processed))

    src = inbox / "bill_001.pdf"
    Path(create_pdf("src.pdf", "Bill No: HB-1")).replace(src)

    dest = archive_inbox_file(src)
    assert dest is not None
    assert dest.exists()
    assert not src.exists()
    assert dest.parent.resolve() == processed.resolve()


def test_archive_leaves_files_outside_inbox(create_pdf):
    outside = Path(create_pdf("outside.pdf", "Bill"))
    dest = archive_inbox_file(outside)
    assert dest == outside
    assert outside.exists()


def test_find_pdf_files_skips_temp_uploads(tmp_path):
    (tmp_path / "keep.pdf").write_bytes(b"%PDF-1.4 test")
    (tmp_path / "temp_abc.pdf").write_bytes(b"%PDF-1.4 test")
    names = {p.name for p in find_pdf_files(tmp_path)}
    assert "keep.pdf" in names
    assert "temp_abc.pdf" not in names


def test_scan_archives_processed_file(monkeypatch, db_session, create_pdf, tmp_path):
    inbox = tmp_path / "input_doc_location"
    processed = tmp_path / "processed_documents"
    inbox.mkdir()
    processed.mkdir()
    monkeypatch.setattr(settings, "INPUT_DOC_LOCATION", str(inbox))
    monkeypatch.setattr(settings, "PROCESSED_DOCUMENTS_LOCATION", str(processed))

    target = inbox / "scan_bill.pdf"
    Path(create_pdf(
        "scan_bill.pdf",
        "Bill No: HB-99\nConsignor: A\nConsignee: B\nOrigin: X\nDestination: Y\nTotal Amount: $10.00",
    )).replace(target)

    result = process_ingestion_batch(db_session, inbox)
    assert result.ingested_count == 1
    assert not target.exists()
    assert len(list(processed.glob("*.pdf"))) == 1
    doc = db_session.query(Document).one()
    assert Path(doc.file_path).parent.resolve() == processed.resolve()
