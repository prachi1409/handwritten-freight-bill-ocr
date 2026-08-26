"""Google Document AI OCR Processor implementation."""

import logging
from pathlib import Path
from typing import Any, Dict, List
from app.core.config import settings
from app.ocr.base import BaseOCRProcessor, OCRResult
from app.ocr.normalizer import normalize_freight_data

logger = logging.getLogger(__name__)


class GoogleDocumentAIProcessor(BaseOCRProcessor):
    """Real Google Document AI Processor implementation."""

    def __init__(self):
        self.project_id = settings.GOOGLE_CLOUD_PROJECT_ID
        self.location = settings.DOCUMENT_AI_LOCATION or "us"
        self.processor_id = settings.DOCUMENT_AI_PROCESSOR_ID
        self.processor_name = (
            f"projects/{self.project_id}/locations/{self.location}/processors/{self.processor_id}"
        )

    def process_document(self, file_path: Path) -> OCRResult:
        """Process document using Google Document AI Client API with Local OCR fallback on API errors."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found for Document AI processing: '{path}'")

        try:
            from google.cloud import documentai_v1 as documentai
        except ImportError as e:
            logger.error("google-cloud-documentai package is not installed.")
            raise RuntimeError("google-cloud-documentai dependency missing") from e

        opts = {"api_endpoint": f"{self.location}-documentai.googleapis.com"}
        client = documentai.DocumentProcessorServiceClient(client_options=opts)

        logger.info(f"Reading document file bytes: '{path.name}'...")
        with open(path, "rb") as pdf_file:
            image_content = pdf_file.read()

        raw_document = documentai.RawDocument(
            content=image_content,
            mime_type="application/pdf"
        )
        request = documentai.ProcessRequest(
            name=self.processor_name,
            raw_document=raw_document
        )

        try:
            logger.info(f"Sending request to Google Document AI processor '{self.processor_name}'...")
            result = client.process_document(request=request)
            doc = result.document
            raw_text = doc.text or ""
            if not raw_text.strip() and not doc.entities:
                raise ValueError("Google Document AI returned empty text and no entities.")
        except Exception as api_err:
            logger.warning(
                f"Google Document AI API call failed or returned empty result ({api_err}). "
                "Falling back to Local OCR Processor."
            )
            from app.ocr.local_processor import LocalOCRProcessor
            return LocalOCRProcessor().process_document(path)

        extracted_dict: Dict[str, Any] = {}
        entities_list: List[Dict[str, Any]] = []

        if doc.entities:
            for entity in doc.entities:
                val = entity.mention_text or (entity.normalized_value.text if entity.normalized_value else "")
                key_norm = entity.type_.lower()
                extracted_dict[key_norm] = val
                entities_list.append({
                    "type": entity.type_,
                    "mention_text": val,
                    "confidence": entity.confidence
                })

        confidence = 0.90
        if doc.entities:
            scores = [e.confidence for e in doc.entities if e.confidence]
            if scores:
                confidence = sum(scores) / len(scores)

        raw_data = {
            "bill_number": (
                extracted_dict.get("bill_number") or
                extracted_dict.get("manifest_number") or
                extracted_dict.get("bol_number") or
                extracted_dict.get("bill_of_lading") or
                extracted_dict.get("job_number")
            ),
            "invoice_number": extracted_dict.get("invoice_number"),
            "bill_date": extracted_dict.get("bill_date") or extracted_dict.get("date"),
            "consignor": extracted_dict.get("consignor") or extracted_dict.get("shipper_name") or extracted_dict.get("shipper"),
            "consignee": extracted_dict.get("consignee") or extracted_dict.get("consignee_name") or extracted_dict.get("receiver"),
            "origin": extracted_dict.get("origin") or extracted_dict.get("pickup_location"),
            "destination": extracted_dict.get("destination") or extracted_dict.get("delivery_location"),
            "vehicle_number": extracted_dict.get("vehicle_number") or extracted_dict.get("truck_number") or extracted_dict.get("truck"),
            "weight": extracted_dict.get("weight"),
            "quantity": extracted_dict.get("quantity"),
            "freight_amount": extracted_dict.get("freight_amount"),
            "total_amount": extracted_dict.get("total_amount"),
            "line_items": extracted_dict.get("line_items", [])
        }

        # Run through normalizer
        normalized = normalize_freight_data(raw_data, raw_text=raw_text, base_confidence=confidence)

        raw_ocr = {
            "processor_id": self.processor_id,
            "source": "google-cloud-documentai",
            "raw_text": raw_text,
            "ocr_confidence": normalized["ocr_confidence"],
            "entities": entities_list
        }

        return OCRResult(
            extracted_data=normalized,
            raw_text=raw_text,
            raw_ocr=raw_ocr,
            confidence=normalized["ocr_confidence"],
            processor="google-cloud-documentai"
        )
