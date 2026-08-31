"""Service layer for document handling, upload, storage, and OCR orchestration."""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import UploadFile, HTTPException, status
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Document, DocumentStatus
from app.ingestion.hasher import calculate_file_hash
from app.ingestion.validator import validate_pdf
from app.ingestion.convert import ALLOWED_EXTENSIONS, ensure_pdf
from app.ocr.factory import get_ocr_processor
from app.ocr.normalizer import normalize_freight_data, validate_extraction_status
from app.schemas.document import IngestionBatchResult, DocumentUploadResponse, DocumentStatsResponse
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class DocumentService:
    """High-level service class for document domain logic."""

    @staticmethod
    def upload_document(db: Session, file: UploadFile) -> DocumentUploadResponse:
        """Process an uploaded file: validate, compute SHA-256, detect duplicates,

        save physical file as UUID in storage/documents, save DB record, and run OCR.
        """
        original_filename = file.filename or ""
        logger.info(f"Processing upload request for: '{original_filename}'")

        # 1. Validate file extension
        suffix = Path(original_filename).suffix.lower()
        if not original_filename or suffix not in ALLOWED_EXTENSIONS:
            msg = f"Invalid file extension for '{original_filename}'. Supported types: PDF, JPG, PNG, TIFF."
            logger.warning(msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        # Read binary file bytes into memory
        try:
            file_bytes = file.file.read()
        except Exception as e:
            logger.error(f"Failed to read upload stream for '{original_filename}': {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"File read failure: {e}")

        if not file_bytes:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

        # Save to temporary storage for PDF validation
        temp_dir = settings.storage_path / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / f"temp_{uuid.uuid4().hex}{suffix}"

        try:
            with open(temp_file, "wb") as f:
                f.write(file_bytes)

            # Convert images to PDF if needed
            pdf_path = ensure_pdf(temp_file)
            validation = validate_pdf(pdf_path)
            if not validation.is_valid:
                logger.warning(f"File '{original_filename}' failed PDF validation: {validation.error_message}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid PDF file: {validation.error_message}"
                )

            # Calculate SHA-256 hash
            file_hash = calculate_file_hash(pdf_path)
            logger.info(f"Calculated SHA-256 for '{original_filename}': {file_hash}")

            # Check duplicate in DB
            existing_doc = db.query(Document).filter(Document.file_hash == file_hash).first()
            if existing_doc:
                logger.info(f"Duplicate document detected: '{original_filename}' matches ID {existing_doc.id}")
                return DocumentUploadResponse(
                    document_id=existing_doc.id,
                    filename=existing_doc.original_filename,
                    status="DUPLICATE",
                    file_hash=file_hash,
                    hash=file_hash,
                    message=f"Duplicate document detected. Already stored with ID {existing_doc.id}."
                )

            # Read valid PDF bytes to save permanently in storage/documents/<uuid>.pdf
            with open(pdf_path, "rb") as pdf_f:
                final_pdf_bytes = pdf_f.read()

            stored_filename, relative_path, abs_path = StorageService.save_uploaded_file(
                file_bytes=final_pdf_bytes,
                original_filename=original_filename
            )

            # Count PDF pages
            page_count = 1
            try:
                import pymupdf as fitz
                doc_pdf = fitz.open(abs_path)
                page_count = len(doc_pdf)
                doc_pdf.close()
            except Exception:
                pass

            new_doc = Document(
                original_filename=original_filename,
                stored_filename=stored_filename,
                stored_path=relative_path,
                file_hash=file_hash,
                status=DocumentStatus.PENDING,
                document_type="freight_bill",
                page_count=page_count
            )
            db.add(new_doc)
            db.commit()
            db.refresh(new_doc)

            logger.info(f"Saved DB document ID {new_doc.id}, stored_path: '{new_doc.stored_path}'")

            # Process OCR pipeline
            processed_doc = DocumentService.process_document(db, new_doc.id)

            return DocumentUploadResponse(
                document_id=processed_doc.id,
                filename=processed_doc.original_filename,
                status=processed_doc.status.value,
                file_hash=processed_doc.file_hash,
                hash=processed_doc.file_hash,
                message=f"Document uploaded and processed successfully with status '{processed_doc.status.value}'."
            )

        finally:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)
            leftover_pdf = temp_file.with_suffix(".pdf")
            if leftover_pdf.exists() and leftover_pdf != temp_file:
                leftover_pdf.unlink(missing_ok=True)

    @staticmethod
    def get_document_by_id(db: Session, document_id: UUID) -> Optional[Document]:
        """Fetch document by ID."""
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc and doc.status == DocumentStatus.PENDING:
            try:
                doc = DocumentService.process_document(db, doc.id)
            except Exception as e:
                logger.error(f"Auto-processing PENDING document {doc.id} failed: {e}")
        return doc

    @staticmethod
    def list_documents(
        db: Session,
        skip: int = 0,
        limit: int = 100,
        q: Optional[str] = None,
    ) -> List[Document]:
        """List documents ordered by created_at descending, optionally filtered by search text."""
        query = db.query(Document)
        if q and q.strip():
            term = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    Document.original_filename.ilike(term),
                    cast(Document.extracted_data, String).ilike(term),
                    Document.error_message.ilike(term),
                )
            )
        return (
            query.order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_document_stats(db: Session) -> DocumentStatsResponse:
        """Return status counts."""
        total = db.query(Document).count()
        completed = db.query(Document).filter(Document.status == DocumentStatus.COMPLETED).count()
        review_needed = db.query(Document).filter(Document.status == DocumentStatus.REVIEW).count()
        pending = db.query(Document).filter(Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING])).count()
        failed = db.query(Document).filter(Document.status == DocumentStatus.FAILED).count()

        return DocumentStatsResponse(
            total_documents=total,
            completed=completed,
            review_needed=review_needed,
            pending=pending,
            failed=failed
        )

    @staticmethod
    def process_document(db: Session, document_id: UUID) -> Document:
        """Execute complete OCR pipeline on a document and update DB state."""
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # Resolve physical storage path
        try:
            abs_file_path = StorageService.resolve_path(doc.stored_path)
        except Exception as err:
            doc.status = DocumentStatus.FAILED
            doc.error_message = f"File not found on disk: {err}"
            db.commit()
            db.refresh(doc)
            raise HTTPException(status_code=404, detail=f"File not found on disk: {doc.stored_path}")

        if not abs_file_path.exists():
            doc.status = DocumentStatus.FAILED
            doc.error_message = f"Physical file missing on disk: {abs_file_path}"
            db.commit()
            db.refresh(doc)
            raise HTTPException(status_code=404, detail=f"Physical file missing: {doc.original_filename}")

        doc.status = DocumentStatus.PROCESSING
        db.commit()

        try:
            processor = get_ocr_processor()
            ocr_result = processor.process_document(abs_file_path)

            normalized = normalize_freight_data(
                extracted=ocr_result.extracted_data,
                raw_text=ocr_result.raw_text,
                base_confidence=ocr_result.confidence
            )

            # Deterministic validation
            final_status, warnings = validate_extraction_status(
                extracted=normalized,
                confidence=normalized["ocr_confidence"]
            )

            doc.extracted_data = normalized
            doc.field_confidence = normalized.get("field_confidence", {})
            doc.raw_ocr_text = ocr_result.raw_text
            doc.ocr_metadata = ocr_result.raw_ocr
            doc.validation_warnings = warnings
            doc.overall_confidence = normalized["ocr_confidence"]

            doc.status = final_status
            doc.processed_at = datetime.now(timezone.utc)
            doc.error_message = "; ".join(warnings) if warnings else None

            db.commit()
            db.refresh(doc)
            logger.info(f"Document ID {doc.id} processed successfully. Status: {doc.status.value}, Confidence: {doc.overall_confidence}")
            return doc

        except Exception as e:
            db.rollback()
            err_msg = f"OCR processing failure: {str(e)}"
            logger.error(err_msg, exc_info=True)
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            db.commit()
            db.refresh(doc)
            return doc

    @staticmethod
    def submit_document_review(db: Session, document_id: UUID, corrected_data: Dict[str, Any]) -> Document:
        """Submit manual corrections for a document, re-evaluate validation, and update DB."""
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        raw_text = doc.raw_ocr_text or ""
        corrected_data["manually_corrected"] = True
        corrected_data["reviewed"] = True
        corrected_data["reviewed_at"] = datetime.now(timezone.utc).isoformat()

        normalized = normalize_freight_data(corrected_data, raw_text=raw_text)
        final_status, warnings = validate_extraction_status(normalized, normalized["ocr_confidence"])

        doc.extracted_data = normalized
        doc.field_confidence = normalized.get("field_confidence", {})
        doc.validation_warnings = warnings
        doc.overall_confidence = normalized["ocr_confidence"]
        doc.manual_corrections = True
        doc.status = final_status
        doc.error_message = "; ".join(warnings) if warnings else None
        doc.processed_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(doc)
        logger.info(f"Manual corrections submitted for Document ID {doc.id}. New status: {doc.status.value}")
        return doc

    @staticmethod
    def reprocess_document(db: Session, document_id: UUID) -> Document:
        """Reprocess document by running full OCR extraction and validation again."""
        return DocumentService.process_document(db=db, document_id=document_id)

    @staticmethod
    def delete_document(db: Session, document_id: UUID) -> bool:
        """Delete document record from DB and delete physical file from storage."""
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return False

        try:
            abs_path = StorageService.resolve_path(doc.stored_path)
            if abs_path.exists():
                abs_path.unlink(missing_ok=True)
        except Exception:
            pass

        db.delete(doc)
        db.commit()
        return True
