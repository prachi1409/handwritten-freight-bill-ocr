"""Local / offline text and OCR extraction fallback processor."""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymupdf as fitz  # PyMuPDF
from app.ocr.base import BaseOCRProcessor, OCRResult
from app.ocr.normalizer import normalize_freight_data, clean_identifier, clean_field_value, normalize_currency, normalize_date
from app.ocr.preprocessor import preprocess_pdf_pages

logger = logging.getLogger(__name__)


class LocalOCRProcessor(BaseOCRProcessor):
    """Offline OCR and text extraction processor.

    Extracts text locally using PyMuPDF and preprocessed page images to parse
    structured freight bill fields without requiring external cloud API billing.
    """

    def process_document(self, file_path: Path) -> OCRResult:
        """Process document file locally across all pages and return standardized OCRResult.

        Args:
            file_path: Path to the target PDF file on disk.

        Returns:
            OCRResult object with structured JSON and raw OCR text.
        """
        path = Path(file_path)
        logger.info(f"[OCR Flow] Step 1/5: Processing document '{path.name}' via Local OCR Processor...")

        if not path.exists():
            raise FileNotFoundError(f"Source file not found for local processing: '{path}'")

        # 1. Preprocess all pages (renders 300 DPI images for OCR inspection)
        page_images = preprocess_pdf_pages(path)
        logger.info(f"[OCR Flow] Step 2/5: Preprocessed {len(page_images)} page image(s) for '{path.name}'.")

        # 2. Extract text across all pages using PyMuPDF text & built-in OCR fallback
        raw_text = ""
        try:
            doc = fitz.open(path)
            pages_text = []
            for idx, page in enumerate(doc, start=1):
                page_txt = page.get_text("text")
                # Fallback to PyMuPDF built-in OCR if page has no text layer (scanned/image-only PDF)
                if not page_txt.strip():
                    try:
                        page_txt = page.get_text("ocr")
                    except Exception as ocr_err:
                        logger.debug(f"[OCR Flow] PyMuPDF built-in OCR fallback not available on page {idx}: {ocr_err}")
                        page_txt = ""

                if page_txt.strip():
                    pages_text.append(f"--- PAGE {idx} ---\n" + page_txt.strip())

            doc.close()
            raw_text = "\n\n".join(pages_text)
        except Exception as e:
            logger.warning(f"[OCR Flow] PyMuPDF text extraction notice for '{path.name}': {e}")
            raw_text = ""

        # Log detailed RAW EXTRACTED TEXT diagnostic output
        logger.info(f"[OCR Debug] RAW EXTRACTED TEXT for '{path.name}' (Length: {len(raw_text)} chars):")
        if raw_text.strip():
            snippet = raw_text.strip()[:300].replace("\n", " ")
            logger.info(f"[OCR Debug] Content Preview: '{snippet}'")
        else:
            logger.warning(f"[OCR Debug] RAW EXTRACTED TEXT is EMPTY for '{path.name}'.")

        # 3. Clean and normalize raw OCR text before pattern matching
        cleaned_ocr_text = self._normalize_ocr_text(raw_text)

        # 4. Attempt comprehensive single-line & multiline regex extraction over text
        bill_number = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Bill\s*(?:No|#|Num|Number)|Invoice\s*(?:No|#|Num|Number)|Manifest\s*(?:No|#|Num|Number)|Cargo\s*Manifest\s*(?:No|#|Num|Number)|Bill\s*of\s*Lading\s*(?:No|#|Num|Number)|BOL\s*(?:No|#|Num|Number)|B/L\s*(?:No|#|Num|Number)|Freight\s*Bill\s*(?:No|#|Num|Number)|LR\s*(?:No|#|Num|Number)|GR\s*(?:No|#|Num|Number)|Waybill\s*(?:No|#|Num|Number)|Job\s*(?:No|#|Num|Number)|Tracking\s*(?:No|#|Num|Number))\s*[:#\s-]*([A-Za-z0-9-]+)",
            r"(?:Cargo\s*Manifest|Manifest|Bill\s*of\s*Lading|BOL|B/L|Freight\s*Bill|Bill|LR|GR|Waybill)\s*[:#-]?\s*([A-Za-z0-9-]+)"
        )
        invoice_number = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Invoice\s*(?:No|#|Num|Number)?|Inv\s*(?:No|#|Num|Number)?)\s*[:#\s-]*([A-Za-z0-9-]+)",
            r"(?:Invoice|Inv)\s*[:#\s-]*\n\s*([A-Za-z0-9-]+)"
        )
        bill_date = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Date|Bill\s*Date|Invoice\s*Date|Dated|Ship\s*Date|Shipping\s*Date)[\s:#]*(\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|\d{4}[/.-]\d{1,2}[/.-]\d{1,2})"
        )
        consignor = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Consignor|Shipper|Sender|From\s*Party|Billed\s*From|Shipper\s*Name)[\s\w()]*[:#\s-]*([^\n|]+)",
            r"(?:Consignor|Shipper|Sender|Shipper\s*Name)[\s\w()]*[:#\s-]*\n\s*([^\n|]+)"
        )
        consignee = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Consignee|Receiver|Recipient|To\s*Party|Billed\s*To|Consignee\s*Name)[\s\w()]*[:#\s-]*([^\n|]+)",
            r"(?:Consignee|Receiver|Recipient|Consignee\s*Name)[\s\w()]*[:#\s-]*\n\s*([^\n|]+)"
        )
        origin = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Origin|Pickup|From|Source|Loading\s*From|Shipped\s*From|Origin\s*Location)[\s\w()]*[:#\s-]*([^\n|]+)",
            r"(?:Origin|Pickup|Origin\s*Location)[\s\w()]*[:#\s-]*\n\s*([^\n|]+)"
        )
        destination = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Destination|Delivery|To|Deliver\s*At|Drop|Unloading\s*At|Shipped\s*To|Destination\s*Location)[\s\w()]*[:#\s-]*([^\n|]+)",
            r"(?:Destination|Delivery|Destination\s*Location)[\s\w()]*[:#\s-]*\n\s*([^\n|]+)"
        )
        vehicle_number = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Vehicle\s*(?:No|#|Num|Number)?|Truck\s*(?:No|#|Num|Number)?|Lorry\s*(?:No|#|Num|Number)?|Trailer\s*(?:No|#|Num|Number)?)\s*[:#\s-]*([A-Za-z0-9-]+)"
        )
        weight = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Weight|Gross\s*Weight|Net\s*Weight|Wt|Total\s*Weight)[\s:#]*([0-9,]+\s*(?:lbs|lb|kg|tons)?)"
        )
        quantity = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Quantity|Qty|Packages|No\.\s*of\s*Packages|Pallets|Boxes|Ctns|Pcs|Units)[\s:#]*([0-9,]+\s*(?:Pallets|Pallet|Units|Boxes|Ctns|Pcs)?)"
        )
        freight_amount = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Freight\s*Amount|Freight\s*Charges|Freight)[\s:#]*([\$₹€£]?\s*[0-9,]+\.?\d*)"
        )
        total_amount = self._extract_regex(
            cleaned_ocr_text,
            r"(?:Total\s*Amount|Grand\s*Total|Amount\s*Payable|Total)[\s:#]*([\$₹€£]?\s*[0-9,]+\.?\d*)"
        )

        # Parse line items dynamically if present
        line_items: List[Dict[str, Any]] = []
        item_matches = re.findall(r"(?:Item\s*\d+|Cargo|Goods|Description)[\s:]*([^\n|]+)", cleaned_ocr_text, re.IGNORECASE)
        for idx, match_text in enumerate(item_matches):
            desc = match_text.strip()
            if desc:
                line_items.append({
                    "item_no": str(idx + 1),
                    "description": desc,
                    "quantity": quantity,
                    "rate": None,
                    "amount": freight_amount
                })

        raw_dict = {
            "bill_number": bill_number,
            "invoice_number": invoice_number,
            "bill_date": bill_date,
            "consignor": consignor,
            "consignee": consignee,
            "origin": origin,
            "destination": destination,
            "vehicle_number": vehicle_number,
            "weight": weight,
            "quantity": quantity,
            "freight_amount": freight_amount,
            "total_amount": total_amount,
            "line_items": line_items
        }

        # Log extraction details
        logger.info(f"[OCR Flow] Step 3/5: Field Extraction Results for '{path.name}':")
        for k, v in raw_dict.items():
            if k != "line_items":
                logger.info(f"  - {k}: {repr(v)}")
        logger.info(f"  - line_items count: {len(line_items)}")

        # Normalize and validate extracted dictionary
        normalized = normalize_freight_data(raw_dict, raw_text=raw_text, base_confidence=0.95)
        logger.info(f"[OCR Flow] Step 4/5: Normalized confidence for '{path.name}': {normalized['ocr_confidence'] * 100:.1f}%")

        raw_ocr = {
            "processor": "local-ocr-processor",
            "source": "local",
            "status": "COMPLETED",
            "raw_text": raw_text,
            "ocr_confidence": normalized["ocr_confidence"],
            "line_items": normalized["line_items"],
            "page_count": len(page_images)
        }

        return OCRResult(
            extracted_data=normalized,
            raw_text=raw_text,
            raw_ocr=raw_ocr,
            confidence=normalized["ocr_confidence"],
            processor="local-ocr-processor"
        )

    def _normalize_ocr_text(self, text: str) -> str:
        """Clean whitespace and OCR noise while preserving line boundaries."""
        if not text:
            return ""
        cleaned = text.replace("\xa0", " ").replace("\r\n", "\n")
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        return cleaned.strip()

    def _extract_regex(self, text: str, pattern: str, multiline_fallback: Optional[str] = None) -> str:
        """Utility regex search returning first group string or empty, with optional multiline fallback."""
        if not text:
            return ""
        match = re.search(pattern, text, re.IGNORECASE)
        if match and match.group(1).strip():
            return match.group(1).strip()

        if multiline_fallback:
            match_multi = re.search(multiline_fallback, text, re.IGNORECASE)
            if match_multi and match_multi.group(1).strip():
                return match_multi.group(1).strip()

        return ""
