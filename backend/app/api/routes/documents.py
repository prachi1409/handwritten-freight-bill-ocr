"""Document management, upload, listing, and reprocessing API routes."""

import logging
from pathlib import Path
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.document import DocumentResponse, DocumentUploadResponse, IngestionBatchResult, DocumentStatsResponse, DocumentReviewRequest
from app.services.document_service import DocumentService

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
    db: Session = Depends(get_db)
) -> List[DocumentResponse]:
    """List all documents."""
    return DocumentService.list_documents(db=db, skip=skip, limit=limit)


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
    summary="Upload Freight Bill PDF Document",
    description="Upload a handwritten freight bill PDF document for ingestion, validation, and SHA-256 duplicate checking."
)
def upload_document(
    file: UploadFile = File(..., description="Handwritten Freight Bill PDF file"),
    db: Session = Depends(get_db)
) -> DocumentUploadResponse:
    """Upload a PDF document."""
    return DocumentService.upload_document(db=db, file=file)


@router.post(
    "/scan",
    response_model=IngestionBatchResult,
    summary="Scan Input Directory",
    description="Scan the configured input document directory (`INPUT_DOC_LOCATION`) for new PDF files and ingest them."
)
def scan_input_directory(
    db: Session = Depends(get_db)
) -> IngestionBatchResult:
    """Trigger batch scanning over input_doc_location folder."""
    return DocumentService.ingest_documents(db=db)


@router.post(
    "/{document_id}/process",
    response_model=DocumentResponse,
    summary="Process Freight Bill Document via OCR",
    description="Trigger OCR pipeline processing (Mock or Google Document AI) on a document by ID."
)
def process_document(
    document_id: UUID,
    db: Session = Depends(get_db)
) -> DocumentResponse:
    """Process document and extract structured JSON data."""
    return DocumentService.process_document(db=db, document_id=document_id)


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
    "/{document_id}/review",
    response_model=DocumentResponse,
    summary="Submit Manual Review & Corrections",
    description="Submit corrected extracted fields for a document, re-evaluate validation, and update document status."
)
def submit_document_review(
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
    file_path = Path(doc.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found on disk: {doc.filename}")
    
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=doc.filename,
        content_disposition_type=disposition
    )
