"""Mock Google Document AI OCR Processor for development and testing."""

import logging
from pathlib import Path
from datetime import datetime, timezone
from app.ocr.base import BaseOCRProcessor, OCRResult

logger = logging.getLogger(__name__)


class MockDocumentAIProcessor(BaseOCRProcessor):
    """Mock Document AI OCR Processor implementation used when GCP billing is disabled."""

    def process_document(self, file_path: Path) -> OCRResult:
        """Simulate Document AI extraction on a freight bill PDF file."""
        path = Path(file_path)
        logger.info(f"Processing document '{path.name}' via Mock Document AI Processor...")

        if not path.exists():
            raise FileNotFoundError(f"Source file not found for OCR processing: '{path}'")

        filename_clean = path.stem.replace("_", " ").replace("-", " ").title()
        hash_seed = abs(hash(path.name)) % 10000

        extracted_data = {
            "shipper_name": "ABC Industrial Supply Co.",
            "consignee_name": "XYZ Logistics Hub",
            "truck_number": f"TX-{5000 + (hash_seed % 4000)}",
            "bill_number": f"FB-10{hash_seed:04d}",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "origin": "Houston Industrial Plant, TX",
            "destination": "Dallas Construction Site, TX",
            "description": f"Handwritten Freight Bill - {filename_clean}",
            "quantity": "42 Pallets",
            "weight": "18,500 lbs",
            "freight_amount": f"${2450 + (hash_seed % 1000)}.00"
        }

        raw_text = (
            f"HANDWRITTEN FREIGHT BILL\n"
            f"Bill No: {extracted_data['bill_number']}\n"
            f"Date: {extracted_data['date']}\n"
            f"Shipper Name: {extracted_data['shipper_name']}\n"
            f"Consignee Name: {extracted_data['consignee_name']}\n"
            f"Truck Number: {extracted_data['truck_number']}\n"
            f"Origin: {extracted_data['origin']}\n"
            f"Destination: {extracted_data['destination']}\n"
            f"Cargo Description: {extracted_data['description']}\n"
            f"Quantity: {extracted_data['quantity']}\n"
            f"Weight: {extracted_data['weight']}\n"
            f"Freight Amount: {extracted_data['freight_amount']}"
        )

        raw_ocr = {
            "processor_id": "mock-google-document-ai-v1",
            "source": "mock-google-document-ai",
            "status": "COMPLETED",
            "raw_text": raw_text,
            "entities": [
                {"type": key, "text": str(val), "confidence": 0.95}
                for key, val in extracted_data.items()
            ]
        }

        return OCRResult(
            extracted_data=extracted_data,
            raw_text=raw_text,
            raw_ocr=raw_ocr,
            confidence=0.95,
            processor="mock-google-document-ai"
        )

