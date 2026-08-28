"""Unit tests for OCR processor factory and Google Document AI field mapping."""

from types import SimpleNamespace
from unittest.mock import patch

from app.ocr.document_ai import GoogleDocumentAIProcessor
from app.ocr.factory import get_ocr_processor
from app.ocr.field_extractor import map_label_to_field
from app.ocr.local_processor import LocalOCRProcessor
from app.ocr.mock_ai import MockDocumentAIProcessor


def test_factory_uses_local_processor_when_testing(monkeypatch):
    """conftest sets TESTING=True so unit tests never call Google Cloud."""
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "TESTING", True)
    monkeypatch.setattr(config_mod.settings, "OCR_PROVIDER", "document_ai")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "proj")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "proc")

    processor = get_ocr_processor()
    assert isinstance(processor, LocalOCRProcessor)


def test_factory_uses_document_ai_when_configured(monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "TESTING", False)
    monkeypatch.setattr(config_mod.settings, "OCR_PROVIDER", "document_ai")
    monkeypatch.setattr(config_mod.settings, "USE_MOCK_OCR", False)
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "proj-123")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "processor-abc")

    processor = get_ocr_processor()
    assert isinstance(processor, GoogleDocumentAIProcessor)


def test_factory_falls_back_to_local_without_credentials(monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "TESTING", False)
    monkeypatch.setattr(config_mod.settings, "OCR_PROVIDER", "document_ai")
    monkeypatch.setattr(config_mod.settings, "USE_MOCK_OCR", False)
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "")

    processor = get_ocr_processor()
    assert isinstance(processor, LocalOCRProcessor)


def test_factory_uses_mock_when_requested(monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "TESTING", False)
    monkeypatch.setattr(config_mod.settings, "OCR_PROVIDER", "mock")
    monkeypatch.setattr(config_mod.settings, "USE_MOCK_OCR", False)
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "")

    processor = get_ocr_processor()
    assert isinstance(processor, MockDocumentAIProcessor)


def test_map_label_to_field_aliases():
    assert map_label_to_field("job_number") == "bill_number"
    assert map_label_to_field("Shipper Name") == "consignor"
    assert map_label_to_field("BOL Number") == "bill_number"
    assert map_label_to_field("unknown_label") is None


def test_document_ai_maps_entities_and_fills_from_text(monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "proj")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "proc")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_APPLICATION_CREDENTIALS", "")

    raw_text = (
        "FREIGHT BILL\n"
        "Bill No: HB-78421\n"
        "Invoice No: INV-100\n"
        "Date: 26/08/2026\n"
        "Consignor: Apex Logistics\n"
        "Consignee: Global Mart\n"
        "Origin: Houston, TX\n"
        "Destination: Dallas, TX\n"
        "Vehicle No: TX-1234\n"
        "Weight: 10,000 lbs\n"
        "Quantity: 12 Pallets\n"
        "Freight Amount: $1,200.00\n"
        "Total Amount: $1,200.00\n"
    )
    entity = SimpleNamespace(
        type_="shipper_name",
        mention_text="Apex Logistics",
        normalized_value=None,
        confidence=0.92,
    )
    document = SimpleNamespace(text=raw_text, entities=[entity], pages=[])

    processor = GoogleDocumentAIProcessor()
    result = processor.build_result(document)

    assert result.processor == "google-cloud-documentai"
    assert result.extracted_data["consignor"] == "Apex Logistics"
    assert result.extracted_data["bill_number"] == "HB-78421"
    assert result.extracted_data["total_amount"] == "$1,200.00"
    assert result.raw_ocr["source"] == "google-cloud-documentai"
    assert result.raw_ocr["entities"][0]["type"] == "shipper_name"


def test_document_ai_maps_form_fields(monkeypatch):
    from app.core import config as config_mod
    monkeypatch.setattr(config_mod.settings, "GOOGLE_CLOUD_PROJECT_ID", "proj")
    monkeypatch.setattr(config_mod.settings, "DOCUMENT_AI_PROCESSOR_ID", "proc")
    monkeypatch.setattr(config_mod.settings, "GOOGLE_APPLICATION_CREDENTIALS", "")

    raw_text = "Bill NoHB-55OriginHouston"
    name_anchor = SimpleNamespace(
        text_segments=[SimpleNamespace(start_index=0, end_index=7)]
    )
    value_anchor = SimpleNamespace(
        text_segments=[SimpleNamespace(start_index=7, end_index=12)]
    )
    origin_name_anchor = SimpleNamespace(
        text_segments=[SimpleNamespace(start_index=12, end_index=18)]
    )
    origin_value_anchor = SimpleNamespace(
        text_segments=[SimpleNamespace(start_index=18, end_index=25)]
    )
    form_fields = [
        SimpleNamespace(
            field_name=SimpleNamespace(text_anchor=name_anchor, confidence=0.9, mention_text=None),
            field_value=SimpleNamespace(text_anchor=value_anchor, mention_text=None),
        ),
        SimpleNamespace(
            field_name=SimpleNamespace(text_anchor=origin_name_anchor, confidence=0.8, mention_text=None),
            field_value=SimpleNamespace(text_anchor=origin_value_anchor, mention_text=None),
        ),
    ]
    page = SimpleNamespace(
        layout=SimpleNamespace(confidence=0.88),
        form_fields=form_fields,
    )
    document = SimpleNamespace(text=raw_text, entities=[], pages=[page])

    processor = GoogleDocumentAIProcessor()
    result = processor.build_result(document)

    assert result.extracted_data["bill_number"] == "HB-55"
    assert result.extracted_data["origin"] == "Houston"
    assert result.raw_ocr["page_count"] == 1
    assert result.raw_ocr["form_fields"][0]["name"] == "Bill No"


def test_document_ai_falls_back_to_local_on_api_error(monkeypatch, create_pdf):
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
        result = processor.process_document(pdf_path)

    assert result.processor == "local-ocr-processor"
    assert result.extracted_data["bill_number"] == "FB-9900"
