"""Tests for document intelligence, image conversion, layout, and search."""

from pathlib import Path

from PIL import Image
from app.db.models import Document, DocumentStatus
from app.ingestion.convert import convert_image_to_pdf, ensure_pdf
from app.ocr.intelligence import classify_document_type
from app.ocr.layout import extract_layout_blocks
from app.ocr.local_processor import LocalOCRProcessor


def test_classify_freight_bill_from_keywords():
    text = "Freight Bill No 1 Consignor Acme Consignee Beta Shipper"
    assert classify_document_type(text) == "freight_bill"
    assert classify_document_type("hello world") == "unknown"


def test_convert_png_to_pdf(tmp_path):
    img_path = tmp_path / "scan.png"
    Image.new("RGB", (80, 80), "white").save(img_path)
    pdf_path = convert_image_to_pdf(img_path)
    assert pdf_path.suffix == ".pdf"
    assert pdf_path.exists()
    assert ensure_pdf(img_path) == pdf_path


def test_layout_extracts_blocks(create_pdf):
    pdf_path = create_pdf("layout_bill.pdf", "Bill No: HB-1\nConsignor: Acme Logistics")
    layout = extract_layout_blocks(pdf_path)
    assert layout["block_count"] >= 1
    joined = " ".join(b["text"] for b in layout["blocks"])
    assert "HB-1" in joined or "Bill" in joined
    assert "bbox" in layout["blocks"][0]


def test_local_processor_includes_intelligence_and_layout(create_pdf):
    pdf_path = create_pdf(
        "intel_bill.pdf",
        "HANDWRITTEN FREIGHT BILL\nBill No: HB-2\nConsignor: A\nConsignee: B\n"
        "Origin: Houston\nDestination: Dallas\nTotal Amount: $20.00\n",
    )
    result = LocalOCRProcessor().process_document(pdf_path)
    assert "document_intelligence" in result.raw_ocr
    assert result.raw_ocr["document_intelligence"]["document_type"] == "freight_bill"
    assert "layout" in result.raw_ocr
    assert result.extracted_data.get("scan_quality") is not None


def test_png_upload_converts_and_processes(client, tmp_path, db_session):
    img_path = tmp_path / "scan_bill.png"
    Image.new("RGB", (120, 160), "white").save(img_path)

    with open(img_path, "rb") as f:
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("scan_bill.png", f, "image/png")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["REVIEW", "COMPLETED", "PENDING"]
    assert data["document_id"] is not None
    doc = db_session.query(Document).filter(Document.original_filename == "scan_bill.png").first()
    assert doc is not None
    assert Path(doc.stored_path).suffix.lower() == ".pdf"


def test_list_documents_search_query(client, db_session):
    d1 = Document(
        original_filename="alpha_bill.pdf",
        stored_filename="alpha_bill.pdf",
        stored_path="p1",
        file_hash="h-alpha",
        status=DocumentStatus.COMPLETED,
        extracted_data={"bill_number": "HB-ALPHA"},
    )
    d2 = Document(
        original_filename="beta_bill.pdf",
        stored_filename="beta_bill.pdf",
        stored_path="p2",
        file_hash="h-beta",
        status=DocumentStatus.COMPLETED,
        extracted_data={"bill_number": "HB-BETA"},
    )
    db_session.add_all([d1, d2])
    db_session.commit()

    response = client.get("/api/v1/documents", params={"q": "ALPHA"})
    assert response.status_code == 200
    names = {row["filename"] for row in response.json()}
    assert "alpha_bill.pdf" in names
    assert "beta_bill.pdf" not in names


def test_render_first_page_png(create_pdf):
    from app.ocr.report_pdf import render_first_page_png

    path = create_pdf("bill_preview.pdf", "CALIFORNIA MATERIALS BILL")
    png = render_first_page_png(path)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 200


def test_document_preview_endpoint(client, db_session, create_pdf):
    pdf_path = create_pdf("ui_bill.pdf", "Freight Bill Preview")
    doc = Document(
        original_filename="ui_bill.pdf",
        stored_filename="ui_bill.pdf",
        stored_path=str(pdf_path),
        file_hash="hash-ui-preview",
        status=DocumentStatus.COMPLETED,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    response = client.get(f"/api/v1/documents/{doc.id}/preview")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_extraction_report_pdf_includes_bill_and_fields(create_pdf):
    import pymupdf as fitz
    from app.ocr.report_pdf import build_extraction_report_pdf

    path = create_pdf("cmat_bill.pdf", "CALIFORNIA MATERIALS BILL")
    pdf_bytes = build_extraction_report_pdf(
        path,
        {
            "consignor": "Clean Planet",
            "pickup_time": "6:00",
            "delivery_time": "12:55",
            "line_items": [
                {"item_no": "1", "tag": "684781", "weight": "2022", "load_arrive": "6:00", "unload_depart": "7:10"},
            ],
        },
        source_filename="bill2.png",
        status="REVIEW",
        confidence=0.87,
    )
    assert pdf_bytes[:5] == b"%PDF-"
    report = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        assert report.page_count >= 2
        text = "".join(page.get_text() for page in report)
        assert "Extraction report" in text
        assert "Clean Planet" in text
        assert "6:00" in text
        assert "12:55" in text
        assert "684781" in text
    finally:
        report.close()


def test_document_report_endpoint(client, db_session, create_pdf):
    pdf_path = create_pdf("ui_report.pdf", "Freight Bill Report")
    doc = Document(
        original_filename="ui_report.pdf",
        stored_filename="ui_report.pdf",
        stored_path=str(pdf_path),
        file_hash="hash-ui-report",
        status=DocumentStatus.COMPLETED,
        extracted_data={"carrier": "California Materials, Inc.", "weight": "12.85"},
        overall_confidence=0.9,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    response = client.get(f"/api/v1/documents/{doc.id}/report")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "extraction_report.pdf" in response.headers.get("content-disposition", "")
    assert response.content[:5] == b"%PDF-"
