"""Document scanner and ingestion orchestrator."""

import logging
from pathlib import Path
from typing import List, Union
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentStatus
from app.ingestion.archive import archive_inbox_file
from app.ingestion.hasher import calculate_file_hash
from app.ingestion.validator import validate_pdf
from app.ingestion.convert import ALLOWED_EXTENSIONS, IMAGE_EXTENSIONS, convert_image_to_pdf
from app.schemas.document import IngestionBatchResult, IngestionItemDetail

logger = logging.getLogger(__name__)


def find_pdf_files(directory_path: Union[str, Path]) -> List[Path]:
    """Scan directory for ingestible documents (PDF and raster images)."""
    path = Path(directory_path)
    if not path.exists() or not path.is_dir():
        logger.warning(f"Input directory does not exist or is not a directory: {path}")
        return []

    files = [
        f for f in path.iterdir()
        if f.is_file()
        and f.suffix.lower() in ALLOWED_EXTENSIONS
        and not f.name.lower().startswith("temp_")
    ]
    files = [
        f for f in files
        if not (
            f.suffix.lower() in IMAGE_EXTENSIONS
            and f.with_suffix(".pdf").exists()
        )
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def process_ingestion_batch(db: Session, input_dir: Union[str, Path]) -> IngestionBatchResult:
    """Scan directory, validate documents, compute SHA-256 hashes, detect duplicates,

    record new pending documents in the database, and trigger OCR extraction pipeline.

    Args:
        db: SQLAlchemy Database Session.
        input_dir: Path to directory containing incoming freight bills.

    Returns:
        IngestionBatchResult detailing batch run statistics and individual file details.
    """
    dir_path = Path(input_dir).resolve()
    logger.info(f"Scanning input directory: '{dir_path}'...")

    pdf_files = find_pdf_files(dir_path)
    total_found = len(pdf_files)
    logger.info(f"Found {total_found} document(s) in '{dir_path}'")

    result = IngestionBatchResult(total_scanned=total_found)

    for pdf_path in pdf_files:
        filename = pdf_path.name
        logger.info(
            f"[{result.ingested_count + result.duplicate_count + result.invalid_count + result.failed_count + 1}"
            f"/{total_found}] Processing '{filename}'..."
        )

        try:
            # 1. Validate PDF structure
            work_path = pdf_path
            if pdf_path.suffix.lower() in IMAGE_EXTENSIONS:
                work_path = convert_image_to_pdf(pdf_path)

            validation = validate_pdf(work_path)
            if not validation.is_valid:
                logger.warning(f"Invalid PDF '{filename}': {validation.error_message}")
                result.invalid_count += 1
                result.items.append(IngestionItemDetail(
                    filename=filename,
                    status="INVALID",
                    message=validation.error_message
                ))
                continue

            # 2. Calculate SHA-256 hash
            file_hash = calculate_file_hash(work_path)
            logger.info(f"Hash calculated for '{filename}': {file_hash}")

            # 3. Check for duplicates in Database based on file_hash
            existing_doc = db.query(Document).filter(Document.file_hash == file_hash).first()
            if existing_doc:
                logger.info(f"Skipping duplicate file: '{filename}' (Matches existing doc ID {existing_doc.id})")
                archive_inbox_file(pdf_path, dest_name=filename)
                if work_path != pdf_path:
                    archive_inbox_file(work_path, dest_name=work_path.name)
                result.duplicate_count += 1
                result.items.append(IngestionItemDetail(
                    filename=filename,
                    status="DUPLICATE",
                    file_hash=file_hash,
                    message=f"Duplicate content matches document ID {existing_doc.id}",
                    document_id=existing_doc.id
                ))
                continue

            # 4. Insert new PENDING Document row
            new_doc = Document(
                filename=filename,
                file_hash=file_hash,
                file_path=str(work_path),
                status=DocumentStatus.PENDING
            )
            db.add(new_doc)
            db.commit()
            db.refresh(new_doc)

            # 5. Automatically trigger OCR extraction pipeline for newly ingested document
            try:
                from app.services.document_service import DocumentService
                processed_doc = DocumentService.process_document(db, new_doc.id)
                final_status = processed_doc.status.value
            except Exception as proc_err:
                logger.error(f"OCR processing failed during ingestion of '{filename}': {proc_err}", exc_info=True)
                final_status = "FAILED"

            if work_path != pdf_path:
                archive_inbox_file(pdf_path, dest_name=filename)

            logger.info(f"New document ingested and processed successfully: '{filename}' (ID: {new_doc.id}, status: {final_status})")
            result.ingested_count += 1
            result.items.append(IngestionItemDetail(
                filename=filename,
                status="INGESTED",
                file_hash=file_hash,
                document_id=new_doc.id,
                message=f"Successfully ingested and processed with status '{final_status}'"
            ))

        except Exception as e:
            db.rollback()
            logger.error(f"Unexpected error processing '{filename}': {e}", exc_info=True)
            result.failed_count += 1
            result.items.append(IngestionItemDetail(
                filename=filename,
                status="FAILED",
                message=f"Processing error: {str(e)}"
            ))

    logger.info(
        f"Ingestion batch completed. Scanned: {result.total_scanned}, "
        f"Ingested: {result.ingested_count}, Duplicates: {result.duplicate_count}, "
        f"Invalid: {result.invalid_count}, Failed: {result.failed_count}"
    )

    return result
