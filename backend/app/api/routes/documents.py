"""Document management, upload, listing, serving, and reprocessing API routes."""

import logging
import re
from pathlib import Path
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.document import (
    DocumentResponse,
    DocumentUploadResponse,
    IngestionBatchResult,
    DocumentStatsResponse,
    DocumentReviewRequest,
    DocumentTranslateResponse,
    DocumentDeleteAllResponse,
    DocumentReprocessAllResponse,
)
from app.ocr.report_pdf import build_extraction_report_pdf, render_first_page_png
from app.services.document_service import DocumentService
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get(
    "",
    response_model=List[DocumentResponse],
    summary="List Freight Bill Documents",
    description="Retrieve a list of ingested freight bill documents ordered by creation date descending."
)
def list_documents(
    skip: int = 0,
    limit: int = 100,
    q: Optional[str] = None,
    db: Session = Depends(get_db)
) -> List[DocumentResponse]:
    """List all documents."""
    return DocumentService.list_documents(db=db, skip=skip, limit=limit, q=q)


@router.delete(
    "",
    response_model=DocumentDeleteAllResponse,
    summary="Delete All Freight Bill Documents",
    description="Delete every document record and its stored PDF. This cannot be undone.",
)
def delete_all_documents(
    db: Session = Depends(get_db),
) -> DocumentDeleteAllResponse:
    """Remove all ingested freight bills and files."""
    deleted = DocumentService.delete_all_documents(db=db)
    return DocumentDeleteAllResponse(
        deleted_count=deleted,
        message=f"Deleted {deleted} document{'s' if deleted != 1 else ''}.",
    )


@router.get(
    "/stats",
    response_model=DocumentStatsResponse,
    summary="Get Document Status Statistics",
    description="Retrieve counts for total, completed, review needed, pending, and failed documents."
)
def get_document_stats(
    db: Session = Depends(get_db)
) -> DocumentStatsResponse:
    """Get status count statistics."""
    return DocumentService.get_document_stats(db=db)


@router.post(
    "/scan",
    response_model=IngestionBatchResult,
    summary="Scan Input Folder for New Freight Bills",
    description="Scans input_doc_location directory for un-ingested PDF files and processes them."
)
@router.post(
    "/scan-folder",
    response_model=IngestionBatchResult,
    summary="Scan Input Folder (Alias)",
    description="Alias for scanning input folder."
)
def scan_documents(
    db: Session = Depends(get_db)
) -> IngestionBatchResult:
    """Scan input directory and ingest new files."""
    from app.core.config import settings
    from app.ingestion.scanner import process_ingestion_batch
    return process_ingestion_batch(db=db, input_dir=settings.INPUT_DOC_LOCATION)


@router.post(
    "/reprocess-all",
    response_model=DocumentReprocessAllResponse,
    summary="Reprocess All Freight Bill Documents",
    description=(
        "Reprocess every ingested bill with Groq Vision as the first field layer. "
        "Overwrites extracted_data. Runs sequentially to avoid provider rate limits."
    ),
)
def reprocess_all_documents(
    db: Session = Depends(get_db),
) -> DocumentReprocessAllResponse:
    """Reprocess every document using the same Groq-primary path as a single reprocess."""
    result = DocumentService.reprocess_all_documents(db=db)
    processed = result["processed_count"]
    failed = result["failed_count"]
    total = result["total_count"]
    if total == 0:
        message = "No documents to reprocess."
    elif failed:
        message = (
            f"Reprocessed {processed} of {total} bill{'s' if total != 1 else ''} "
            f"({failed} failed)."
        )
    else:
        message = f"Reprocessed {processed} bill{'s' if processed != 1 else ''}."
    return DocumentReprocessAllResponse(
        processed_count=processed,
        failed_count=failed,
        total_count=total,
        message=message,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get Document Details",
    description="Fetch document details and extracted OCR JSON data by document ID."
)
def get_document(
    document_id: UUID,
    db: Session = Depends(get_db)
) -> DocumentResponse:
    """Get single document details by UUID."""
    doc = DocumentService.get_document_by_id(db=db, document_id=document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload Freight Bill Document",
    description="Upload a freight bill as PDF, JPG, PNG, or TIFF. Saves file as UUID in storage/documents.",
)
def upload_document(
    file: UploadFile = File(..., description="Freight bill PDF or scan image"),
    db: Session = Depends(get_db)
) -> DocumentUploadResponse:
    """Upload a PDF document."""
    return DocumentService.upload_document(db=db, file=file)


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentResponse,
    summary="Reprocess Freight Bill Document",
    description="Trigger OCR pipeline reprocessing on a document by ID."
)
def reprocess_document(
    document_id: UUID,
    db: Session = Depends(get_db)
) -> DocumentResponse:
    """Reprocess document and extract structured data."""
    return DocumentService.reprocess_document(db=db, document_id=document_id)


@router.put(
    "/{document_id}/corrections",
    response_model=DocumentResponse,
    summary="Submit Manual Review Corrections",
    description="Submit corrected extracted fields for a document, re-evaluate validation, and update document status."
)
def submit_document_corrections(
    document_id: UUID,
    payload: DocumentReviewRequest,
    db: Session = Depends(get_db)
) -> DocumentResponse:
    """Save manual review corrections."""
    return DocumentService.submit_document_review(
        db=db,
        document_id=document_id,
        corrected_data=payload.extracted_data
    )


@router.put(
    "/{document_id}/review",
    response_model=DocumentResponse,
    summary="Submit Manual Review (Alias)",
    description="Alias for submit_document_corrections."
)
def submit_document_review_alias(
    document_id: UUID,
    payload: DocumentReviewRequest,
    db: Session = Depends(get_db)
) -> DocumentResponse:
    """Alias for manual review corrections."""
    return DocumentService.submit_document_review(
        db=db,
        document_id=document_id,
        corrected_data=payload.extracted_data
    )


@router.post(
    "/{document_id}/translate",
    response_model=DocumentTranslateResponse,
    summary="Translate Extracted Fields for Display",
    description="Return English display values for Hindi/other-script fields. Does not save to the database.",
)
def translate_document_fields(
    document_id: UUID,
    db: Session = Depends(get_db)
) -> DocumentTranslateResponse:
    """Display-only translation of extracted freight fields."""
    doc = DocumentService.get_document_by_id(db=db, document_id=document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    from app.ocr.groq_extractor import translate_fields_for_display
    result = translate_fields_for_display(doc.extracted_data or {})
    return DocumentTranslateResponse(
        document_id=document_id,
        translations=result.get("translations") or {},
        source=result.get("source") or "digits",
        persisted=False,
    )


@router.delete(
    "/{document_id}",
    summary="Delete Document",
    description="Delete a document record and its physical stored PDF file."
)
def delete_document(
    document_id: UUID,
    db: Session = Depends(get_db)
):
    """Delete document by ID."""
    deleted = DocumentService.delete_document(db=db, document_id=document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"message": "Document deleted successfully", "document_id": document_id}


@router.get(
    "/{document_id}/file",
    summary="Download/View Document PDF File",
    description="Serve the raw PDF file for inline viewing or download."
)
def get_document_file(
    document_id: UUID,
    download: bool = False,
    db: Session = Depends(get_db)
):
    """Serve PDF file binary with inline disposition for browser PDF preview embedding."""
    doc = DocumentService.get_document_by_id(db=db, document_id=document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        abs_path = StorageService.resolve_path(doc.stored_path)
    except Exception as err:
        raise HTTPException(status_code=404, detail=f"File not found on disk: {doc.original_filename}")

    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found on disk: {doc.original_filename}")

    disposition = "attachment" if download else "inline"
    return FileResponse(
        path=abs_path,
        media_type="application/pdf",
        filename=doc.original_filename,
        content_disposition_type=disposition
    )


@router.get(
    "/{document_id}/preview",
    summary="Bill page preview image",
    description="PNG of the first page for the review UI (no PDF viewer chrome).",
)
def get_document_preview(
    document_id: UUID,
    db: Session = Depends(get_db),
):
    """Serve a PNG of page 1 so the left pane can show the bill as an image."""
    doc = DocumentService.get_document_by_id(db=db, document_id=document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        abs_path = StorageService.resolve_path(doc.stored_path)
    except Exception:
        raise HTTPException(status_code=404, detail=f"File not found on disk: {doc.original_filename}")
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found on disk: {doc.original_filename}")
    try:
        png = render_first_page_png(abs_path)
    except Exception as err:
        logger.warning("Bill preview render failed for %s: %s", document_id, err)
        raise HTTPException(status_code=500, detail="Could not render bill preview")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=120"})


def _report_download_name(original_filename: Optional[str]) -> str:
    stem = Path(original_filename or "freight_bill").stem
    safe = re.sub(r"[^\w.\-]+", "_", stem)[:80] or "freight_bill"
    return f"{safe}_extraction_report.pdf"


@router.get(
    "/{document_id}/report",
    summary="Download bill + extraction PDF",
    description="Original bill page(s) followed by extracted fields and load rows.",
)
def get_document_extraction_report(
    document_id: UUID,
    db: Session = Depends(get_db),
):
    """Return a PDF that contains the scanned bill and the structured extraction."""
    doc = DocumentService.get_document_by_id(db=db, document_id=document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        abs_path = StorageService.resolve_path(doc.stored_path)
    except Exception:
        raise HTTPException(status_code=404, detail=f"File not found on disk: {doc.original_filename}")
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found on disk: {doc.original_filename}")
    try:
        pdf_bytes = build_extraction_report_pdf(
            abs_path,
            doc.extracted_data or {},
            source_filename=doc.original_filename or "",
            status=str(getattr(doc.status, "value", doc.status) or ""),
            confidence=doc.overall_confidence,
        )
    except Exception as err:
        logger.warning("Extraction report failed for %s: %s", document_id, err, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not build extraction report")
    filename = _report_download_name(doc.original_filename)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
