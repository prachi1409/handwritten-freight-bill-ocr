"""Document management, upload, listing, serving, and reprocessing API routes."""

import logging
from pathlib import Path
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.document import DocumentResponse, DocumentUploadResponse, IngestionBatchResult, DocumentStatsResponse, DocumentReviewRequest
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
