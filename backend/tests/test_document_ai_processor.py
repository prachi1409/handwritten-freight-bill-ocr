"""Unit tests for Google Document AI processor mapping, factory resolution, and fallback mechanisms."""

from unittest.mock import MagicMock, patch
import pytest

from app.ocr.base import OCRResult
from app.ocr.document_ai import GoogleDocumentAIProcessor
from app.ocr.factory import get_ocr_processor
from app.ocr.local_processor import LocalOCRProcessor
from app.ocr.mock_ai import MockDocumentAIProcessor


def test_factory_uses_local_processor_when_testing():
    """When settings.TESTING is True (default in pytest conftest), factory must return LocalOCRProcessor."""
    proc = get_ocr_processor()
    assert isinstance(proc, LocalOCRProcessor)


def test_factory_uses_document_ai_when_configured(monkeypatch):
    """When TESTING is False and provider is document_ai with credentials configured, return GoogleDocumentAIProcessor."""
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "TESTING", False)
    monkeypatch.setattr(config_mod.settings, "OCR_PROVIDER", "document_ai")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "test-project-id")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "test-processor-id")

    proc = get_ocr_processor()
    assert isinstance(proc, GoogleDocumentAIProcessor)


def test_factory_falls_back_to_local_without_credentials(monkeypatch):
    """When OCR_PROVIDER is document_ai but project_id is empty, fall back to LocalOCRProcessor."""
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "TESTING", False)
    monkeypatch.setattr(config_mod.settings, "OCR_PROVIDER", "document_ai")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "")

    proc = get_ocr_processor()
    assert isinstance(proc, LocalOCRProcessor)


def test_factory_uses_mock_when_requested(monkeypatch):
    """When OCR_PROVIDER is mock, return MockDocumentAIProcessor."""
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "TESTING", False)
    monkeypatch.setattr(config_mod.settings, "OCR_PROVIDER", "mock")

    proc = get_ocr_processor()
    assert isinstance(proc, MockDocumentAIProcessor)


def test_map_label_to_field_aliases():
    """Verify raw entity type strings map to standardized schema field names."""
    from app.ocr.field_extractor import map_label_to_field

    assert map_label_to_field("invoice_id") == "invoice_number"
    assert map_label_to_field("shipper_name") == "consignor"
    assert map_label_to_field("receiver_name") == "consignee"
    assert map_label_to_field("total_amount") == "total_amount"
    assert map_label_to_field("carrier_name") == "carrier"
    assert map_label_to_field("purchase_order") == "bill_number"


def test_document_ai_maps_entities_and_fills_from_text(monkeypatch):
    """Verify GoogleDocumentAIProcessor.build_result maps proto entities into normalized json."""
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "proj")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "proc")

    processor = GoogleDocumentAIProcessor()

    entity_inv = MagicMock()
    entity_inv.type_ = "invoice_id"
    entity_inv.mention_text = "INV-998877"
    entity_inv.confidence = 0.96

    entity_total = MagicMock()
    entity_total.type_ = "total_amount"
    entity_total.mention_text = "$4,200.00"
    entity_total.confidence = 0.94

    mock_doc = MagicMock()
    mock_doc.text = (
        "CARRIER FREIGHT MANIFEST\n"
        "Bill No: HB-12345\n"
        "Consignor: Apex Global Corp\n"
        "Consignee: Metro Logistics\n"
        "Origin: Chicago, IL\n"
        "Destination: Dallas, TX\n"
        "Total Amount: $4,200.00\n"
    )
    mock_doc.entities = [entity_inv, entity_total]
    mock_doc.pages = []

    res = processor.build_result(mock_doc)

    assert isinstance(res, OCRResult)
    assert res.processor == "google-cloud-documentai"
    ext = res.extracted_data
    assert ext["invoice_number"] == "INV-998877"
    assert ext["total_amount"] == "$4,200.00"
    assert ext["bill_number"] == "HB-12345"
    assert ext["consignor"] == "Apex Global Corp"
    assert ext["consignee"] == "Metro Logistics"
    assert ext["origin"] == "Chicago, IL"
    assert ext["destination"] == "Dallas, TX"


def test_document_ai_maps_form_fields(monkeypatch):
    """Verify Document AI page form_fields key-value pairs are extracted when entities are absent."""
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "proj")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "proc")

    processor = GoogleDocumentAIProcessor()

    doc_text = "Shipper: Pinnacle Steel\nReceiver: Central Hub\n"

    seg_name = MagicMock(start_index=0, end_index=7)     # 'Shipper'
    seg_val = MagicMock(start_index=9, end_index=23)    # 'Pinnacle Steel'

    field = MagicMock()
    field.field_name.text_anchor.text_segments = [seg_name]
    field.field_value.text_anchor.text_segments = [seg_val]

    page = MagicMock()
    page.layout.confidence = 0.91
    page.form_fields = [field]

    mock_doc = MagicMock()
    mock_doc.text = doc_text
    mock_doc.entities = []
    mock_doc.pages = [page]

    res = processor.build_result(mock_doc)

    ext = res.extracted_data
    assert ext["consignor"] == "Pinnacle Steel"


def test_document_ai_raises_error_on_api_failure(monkeypatch, create_pdf):
    """When Document AI API call fails, processor must raise an exception so status becomes FAILED."""
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "proj")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "proc")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_APPLICATION_CREDENTIALS", "")

    pdf_path = create_pdf(
        "dai_fallback.pdf",
        "Bill No: FB-9900\nConsignor: Alpha Co\nConsignee: Beta LLC\n"
        "Origin: Houston\nDestination: Dallas\nTotal Amount: $500.00\n",
    )
    processor = GoogleDocumentAIProcessor()
    with patch.object(processor, "_call_document_ai", side_effect=RuntimeError("quota exceeded")):
        with pytest.raises(RuntimeError) as exc_info:
            processor.process_document(pdf_path)

    assert "quota exceeded" in str(exc_info.value)
