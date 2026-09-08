"""Google Document AI OCR Processor implementation."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from app.core.config import settings
from app.ocr.base import BaseOCRProcessor, OCRResult
from app.ocr.field_extractor import map_label_to_field, merge_structured_and_text_fields
from app.ocr.calibration import attach_field_calibration
from app.ocr.consistency import attach_consistency_checks
from app.ocr.decode import resolve_entity_assignment
from app.ocr.matching import apply_entity_matching
from app.ocr.normalizer import normalize_freight_data

logger = logging.getLogger(__name__)


def _anchor_text(doc_text: str, layout: Any) -> str:
    """Slice Document AI layout text_anchor segments out of the full document text."""
    if layout is None:
        return ""

    mention = getattr(layout, "mention_text", None)
    if mention:
        return str(mention).strip()

    text_anchor = getattr(layout, "text_anchor", None)
    if text_anchor is None:
        return ""

    segments = getattr(text_anchor, "text_segments", None) or []
    parts: List[str] = []
    for segment in segments:
        start = int(getattr(segment, "start_index", 0) or 0)
        end = int(getattr(segment, "end_index", 0) or 0)
        parts.append(doc_text[start:end])
    return "".join(parts).strip()


def _entity_value(entity: Any) -> str:
    """Best available mention text for a Document AI entity."""
    mention = getattr(entity, "mention_text", None)
    if mention:
        return str(mention).strip()
    normalized = getattr(entity, "normalized_value", None)
    if normalized is not None:
        text = getattr(normalized, "text", None)
        if text:
            return str(text).strip()
    return ""


class GoogleDocumentAIProcessor(BaseOCRProcessor):
    """Process PDFs with Google Cloud Document AI and map results to freight-bill JSON."""

    def __init__(self):
        self.project_id = settings.GOOGLE_CLOUD_PROJECT_ID
        self.location = settings.DOCUMENT_AI_LOCATION or "us"
        self.processor_id = settings.DOCUMENT_AI_PROCESSOR_ID
        creds_path = (settings.GOOGLE_APPLICATION_CREDENTIALS or "").strip()
        if creds_path:
            resolved = self._resolve_credentials_file(creds_path)
            if resolved.exists():
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(resolved)
                logger.info("Using Document AI credentials file: %s", resolved)
            else:
                logger.warning(
                    "GOOGLE_APPLICATION_CREDENTIALS file not found: '%s'. "
                    "Document AI will use Application Default Credentials if available.",
                    resolved,
                )

    @staticmethod
    def _resolve_credentials_file(creds_path: str) -> Path:
        """Resolve a relative credentials path against cwd and the backend directory."""
        path = Path(creds_path).expanduser()
        if path.is_absolute() and path.exists():
            return path
        cwd_path = (Path.cwd() / path).resolve()
        if cwd_path.exists():
            return cwd_path
        backend_root = Path(__file__).resolve().parents[2]
        backend_path = (backend_root / path).resolve()
        if backend_path.exists():
            return backend_path

        creds_dir = backend_root / "credentials"
        if creds_dir.exists() and creds_dir.is_dir():
            json_files = list(creds_dir.glob("*.json"))
            if json_files:
                return json_files[0]

        return path

    def process_document(self, file_path: Path) -> OCRResult:
        """Send a PDF to Google Document AI API and return normalized freight-bill fields.

        If Document AI fails, raises an exception so the document status becomes FAILED.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found for Document AI processing: '{path}'")

        try:
            document = self._call_document_ai(path)
        except Exception as api_err:
            logger.error("Google Document AI API execution failed for '%s': %s", path.name, api_err)
            raise RuntimeError(f"Google Document AI API Error: {api_err}") from api_err

        result = self.build_result(document)
        self._attach_pipeline_meta(result, path)
        return result

    @staticmethod
    def _attach_pipeline_meta(result: OCRResult, path: Path) -> None:
        from app.ocr.intelligence import build_document_intelligence
        from app.ocr.layout import extract_layout_blocks
        from app.ocr.layout_classifier import classify_layout_safe

        intel = build_document_intelligence(
            result.raw_text,
            page_count=int((result.raw_ocr or {}).get("page_count") or 0),
        )
        result.raw_ocr["document_intelligence"] = intel
        if isinstance(result.extracted_data, dict):
            result.extracted_data["document_type"] = intel["document_type"]
            result.extracted_data["scan_quality"] = intel["quality_score"]
        try:
            result.raw_ocr["layout"] = extract_layout_blocks(path)
        except Exception as e:
            logger.debug("Layout reconstruction skipped: %s", e)
            result.raw_ocr["layout"] = {"block_count": 0, "blocks": []}
        result.raw_ocr["layout_classification"] = classify_layout_safe(
            result.raw_text,
            page_count=int((result.raw_ocr or {}).get("page_count") or 0),
            layout=result.raw_ocr.get("layout"),
            text_source="google-cloud-documentai",
        )

    def _call_document_ai(self, path: Path) -> Any:
        """Invoke the Document AI process_document API and return the Document proto."""
        try:
            from google.cloud import documentai_v1 as documentai
        except ImportError as e:
            raise RuntimeError("google-cloud-documentai dependency missing") from e

        opts = {"api_endpoint": f"{self.location}-documentai.googleapis.com"}
        client = documentai.DocumentProcessorServiceClient(client_options=opts)
        processor_name = client.processor_path(
            self.project_id, self.location, self.processor_id
        )

        logger.info("Reading document file bytes: '%s'...", path.name)
        with open(path, "rb") as pdf_file:
            image_content = pdf_file.read()

        raw_document = documentai.RawDocument(
            content=image_content,
            mime_type="application/pdf",
        )
        request = documentai.ProcessRequest(
            name=processor_name,
            raw_document=raw_document,
        )

        logger.info("Sending request to Google Document AI processor '%s'...", processor_name)
        result = client.process_document(request=request)
        document = result.document
        raw_text = getattr(document, "text", None) or ""
        entities = list(getattr(document, "entities", None) or [])
        if not raw_text.strip() and not entities:
            raise ValueError("Google Document AI returned empty text and no entities.")
        return document

    def build_result(self, document: Any) -> OCRResult:
        """Map a Document AI Document into OCRResult JSON."""
        raw_text = getattr(document, "text", None) or ""
        structured, entities_list, form_fields_list, page_confidences = (
            self._extract_structured_fields(document, raw_text)
        )
        merged = merge_structured_and_text_fields(structured, raw_text)
        cheap_fields = dict(merged)
        merged = apply_entity_matching(merged)
        merged, field_candidates, joint_decode = resolve_entity_assignment(
            merged,
            cheap_fields=cheap_fields,
            raw_text=raw_text,
        )
        merged = apply_entity_matching(merged)

        confidence = 0.90
        entity_scores = [e["confidence"] for e in entities_list if e.get("confidence")]
        if entity_scores:
            confidence = sum(entity_scores) / len(entity_scores)
        elif page_confidences:
            confidence = sum(page_confidences) / len(page_confidences)

        normalized = normalize_freight_data(
            merged, raw_text=raw_text, base_confidence=confidence
        )

        raw_ocr = {
            "processor_id": self.processor_id,
            "source": "google-cloud-documentai",
            "raw_text": raw_text,
            "ocr_confidence": normalized["ocr_confidence"],
            "entities": entities_list,
            "form_fields": form_fields_list,
            "page_count": len(list(getattr(document, "pages", None) or [])),
            "page_confidences": page_confidences,
            "field_candidates": field_candidates,
            "joint_decode": joint_decode,
        }
        attach_field_calibration(normalized, raw_ocr)
        attach_consistency_checks(normalized, raw_ocr)

        return OCRResult(
            extracted_data=normalized,
            raw_text=raw_text,
            raw_ocr=raw_ocr,
            confidence=normalized["ocr_confidence"],
            processor="google-cloud-documentai",
        )

    def _extract_structured_fields(
        self, document: Any, raw_text: str
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[float]]:
        """Collect entity and form-parser fields from a Document AI response."""
        structured: Dict[str, Any] = {key: None for key in (
            "bill_number", "invoice_number", "bill_date", "carrier", "consignor", "consignee",
            "origin", "destination", "vehicle_number", "weight", "quantity",
            "freight_amount", "fuel_surcharge", "handling_charge", "total_amount",
            "driver_name", "pickup_time", "delivery_time", "special_instructions"
        )}
        structured["line_items"] = []

        entities_list: List[Dict[str, Any]] = []
        for entity in list(getattr(document, "entities", None) or []):
            entity_type = getattr(entity, "type_", None) or getattr(entity, "type", "") or ""
            val = _entity_value(entity)
            conf = getattr(entity, "confidence", None)
            entities_list.append({
                "type": entity_type,
                "mention_text": val,
                "confidence": conf,
            })
            field_key = map_label_to_field(str(entity_type))
            if field_key and val and not structured.get(field_key):
                structured[field_key] = val

        form_fields_list: List[Dict[str, Any]] = []
        page_confidences: List[float] = []
        for page in list(getattr(document, "pages", None) or []):
            layout = getattr(page, "layout", None)
            layout_conf = getattr(layout, "confidence", None) if layout is not None else None
            if layout_conf:
                page_confidences.append(float(layout_conf))

            for field in list(getattr(page, "form_fields", None) or []):
                name_layout = getattr(field, "field_name", None)
                value_layout = getattr(field, "field_value", None)
                name = _anchor_text(raw_text, name_layout)
                value = _anchor_text(raw_text, value_layout)
                name_conf = getattr(name_layout, "confidence", None) if name_layout is not None else None
                form_fields_list.append({
                    "name": name,
                    "value": value,
                    "confidence": name_conf,
                })
                field_key = map_label_to_field(name)
                if field_key and value and not structured.get(field_key):
                    structured[field_key] = value

        return structured, entities_list, form_fields_list, page_confidences
