"""Service layer for document handling and ingestion orchestration."""

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from typing import Any, Dict, List, Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Document, DocumentStatus
from app.ingestion.hasher import calculate_file_hash
from app.ingestion.validator import validate_pdf
from app.ingestion.scanner import process_ingestion_batch
from app.ocr.factory import get_ocr_processor
from app.ocr.normalizer import normalize_freight_data, validate_extraction_status
from app.schemas.document import IngestionBatchResult, DocumentUploadResponse, DocumentStatsResponse

logger = logging.getLogger(__name__)


class DocumentService:
    """High-level service class for document domain logic."""

    @staticmethod
    def upload_document(db: Session, file: UploadFile) -> DocumentUploadResponse:
        """Process an uploaded PDF file: validate, compute SHA-256 hash, detect duplicates,

        save valid document metadata to database, and trigger OCR extraction pipeline.

        Args:
            db: SQLAlchemy Database Session.
            file: FastAPI UploadFile object.

        Returns:
            DocumentUploadResponse object.
        """
        filename = file.filename or ""
        logger.info(f"Received file upload request: '{filename}'")

        # 1. Validate file extension
        if not filename or not filename.lower().endswith(".pdf"):
            msg = f"Invalid file extension for '{filename}'. Only PDF files (.pdf) are supported."
            logger.warning(msg)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=msg
            )

        # 2. Save stream to temporary file in input directory
        input_dir = settings.input_path
        input_dir.mkdir(parents=True, exist_ok=True)
        temp_path = input_dir / f"temp_{uuid.uuid4().hex}.pdf"

        try:
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            logger.error(f"Failed to write uploaded file to disk: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process file upload: {str(e)}"
            )

        try:
            # 3. Validate PDF document structure using PyMuPDF utility
            validation = validate_pdf(temp_path)
            if not validation.is_valid:
                logger.warning(f"Uploaded file '{filename}' failed PDF validation: {validation.error_message}")
                temp_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid PDF file: {validation.error_message}"
                )

            # 4. Calculate SHA-256 hash using chunked hasher utility
            file_hash = calculate_file_hash(temp_path)
            logger.info(f"Calculated SHA-256 hash for uploaded file '{filename}': {file_hash}")

            # 5. Check if document already exists in DB based on file_hash
            existing_doc = db.query(Document).filter(Document.file_hash == file_hash).first()
            if existing_doc:
                logger.info(f"Duplicate document detected: '{filename}' matches existing document ID {existing_doc.id}")
                temp_path.unlink(missing_ok=True)
                return DocumentUploadResponse(
                    document_id=existing_doc.id,
                    filename=existing_doc.filename,
                    status="DUPLICATE",
                    file_hash=file_hash,
                    hash=file_hash,
                    message=f"Duplicate document detected. Already stored with ID {existing_doc.id}"
                )

            # 6. Save file permanently in INPUT_DOC_LOCATION
            target_path = input_dir / filename
            if target_path.exists():
                target_path = input_dir / f"{file_hash[:8]}_{filename}"

            temp_path.replace(target_path)

            # 7. Create database record in PENDING status
            new_doc = Document(
                filename=filename,
                file_hash=file_hash,
                file_path=str(target_path),
                status=DocumentStatus.PENDING
            )
            db.add(new_doc)
            db.commit()
            db.refresh(new_doc)

            logger.info(f"Uploaded document saved successfully: ID {new_doc.id}, path: '{target_path}'")

            # 8. Automatically trigger OCR extraction pipeline for newly uploaded document
            logger.info(f"Triggering OCR pipeline processing for uploaded document ID {new_doc.id}...")
            processed_doc = DocumentService.process_document(db, new_doc.id)

            return DocumentUploadResponse(
                document_id=processed_doc.id,
                filename=processed_doc.filename,
                status=processed_doc.status.value,
                file_hash=processed_doc.file_hash,
                hash=processed_doc.file_hash,
                message=f"Document uploaded and processed successfully with status '{processed_doc.status.value}'."
            )

        except HTTPException:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            db.rollback()
            logger.error(f"Unexpected error during document upload '{filename}': {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected error occurred while processing document: {str(e)}"
            )

    @staticmethod
    def ingest_documents(db: Session, input_dir: Optional[str] = None) -> IngestionBatchResult:
        """Run batch ingestion scanner over target input directory and trigger OCR for new files."""
        target_dir = Path(input_dir) if input_dir else settings.input_path
        return process_ingestion_batch(db, target_dir)

    @staticmethod
    def get_document_by_id(db: Session, document_id: UUID) -> Optional[Document]:
        """Fetch document by primary key ID and auto-process if still PENDING."""
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc and doc.status == DocumentStatus.PENDING:
            logger.info(f"Auto-processing PENDING document ID {doc.id} on fetch...")
            try:
                doc = DocumentService.process_document(db, doc.id)
            except Exception as e:
                logger.error(f"Auto-processing PENDING document ID {doc.id} failed: {e}", exc_info=True)
        return doc

    @staticmethod
    def get_document_by_hash(db: Session, file_hash: str) -> Optional[Document]:
        """Fetch document by SHA-256 hash."""
        return db.query(Document).filter(Document.file_hash == file_hash).first()

    @staticmethod
    def list_documents(db: Session, skip: int = 0, limit: int = 100) -> List[Document]:
        """List documents ordered by creation date descending."""
        return (
            db.query(Document)
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_document_stats(db: Session) -> DocumentStatsResponse:
        """Return document status count statistics from database."""
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
        """Process document using OCR engine and update DB record with validation and state transitions."""
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            logger.error(f"Processing failed: Document ID {document_id} not found in database.")
            raise HTTPException(status_code=404, detail="Document not found")

        file_path = Path(doc.file_path)
        logger.info(f"Starting OCR processing stage 1/4: Document ID {doc.id}, file '{doc.filename}' ({file_path})")

        # 1. Update status to PROCESSING and commit to DB
        doc.status = DocumentStatus.PROCESSING
        db.commit()

        try:
            # 2. Instantiate and run OCR processor (Google Document AI or Local fallback)
            logger.info(f"Starting OCR processing stage 2/4: Calling OCR processor for '{doc.filename}'...")
            processor = get_ocr_processor()
            ocr_result = processor.process_document(file_path)
            logger.info(f"OCR processing stage 2/4 completed: Processor '{ocr_result.processor}', raw confidence {ocr_result.confidence}")

            # 3. Validate extracted fields completeness and assign state (COMPLETED vs REVIEW)
            logger.info(f"Starting OCR processing stage 3/4: Validating extracted schema fields...")
            final_status, review_msg = validate_extraction_status(ocr_result.extracted_data, ocr_result.confidence)

            # Update document record fields
            doc.extracted_data = ocr_result.extracted_data
            doc.raw_ocr = ocr_result.raw_ocr
            doc.confidence = ocr_result.confidence
            doc.status = final_status
            doc.processed_at = datetime.now(timezone.utc)
            doc.error_message = review_msg if final_status == DocumentStatus.REVIEW else None

            db.commit()
            db.refresh(doc)
            logger.info(
                f"OCR processing stage 4/4 completed: Document ID {doc.id} status set to '{doc.status.value}'. "
                f"Confidence: {doc.confidence}, Review Note: '{doc.error_message}'"
            )
            return doc

        except Exception as e:
            db.rollback()
            err_msg = f"OCR processing failure on '{doc.filename}': {str(e)}"
            logger.error(err_msg, exc_info=True)
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            db.commit()
            db.refresh(doc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=err_msg
            )

    @staticmethod
    def submit_document_review(db: Session, document_id: UUID, corrected_data: Dict[str, Any]) -> Document:
        """Submit manual review corrections, run normalizer & validation, and update DB record."""
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # Preserve existing raw_text if present in current doc
        raw_text = ""
        if doc.extracted_data and isinstance(doc.extracted_data, dict):
            raw_text = doc.extracted_data.get("raw_text", "")
        elif doc.raw_ocr and isinstance(doc.raw_ocr, dict):
            raw_text = doc.raw_ocr.get("raw_text", "")

        # Run submitted dictionary through normalizer
        normalized = normalize_freight_data(corrected_data, raw_text=raw_text, base_confidence=doc.confidence or 0.95)

        # Add audit trail metadata
        normalized["reviewed"] = True
        normalized["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        normalized["manually_corrected"] = True

        # Re-evaluate validation status
        final_status, review_msg = validate_extraction_status(normalized, normalized["ocr_confidence"])

        doc.extracted_data = normalized
        doc.status = final_status
        doc.error_message = review_msg if final_status == DocumentStatus.REVIEW else None
        doc.processed_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(doc)
        logger.info(f"Manual review submitted for Document ID {doc.id}. New status: {doc.status.value}, Review note: '{doc.error_message}'")
        return doc

    @staticmethod
    def reprocess_document(db: Session, document_id: UUID) -> Document:
        """Alias for process_document to re-trigger complete extraction and validation pipeline."""
        return DocumentService.process_document(db=db, document_id=document_id)
