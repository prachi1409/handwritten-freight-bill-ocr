"""Pydantic schemas for Document model and Ingestion operations."""

from datetime import datetime
from uuid import UUID
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict

from app.db.models import DocumentStatus


class DocumentBase(BaseModel):
    """Base schema for document fields."""
    filename: str
    file_hash: str
    file_path: str
    status: DocumentStatus = DocumentStatus.PENDING


class DocumentCreate(DocumentBase):
    """Schema for document creation."""
    pass


class DocumentResponse(DocumentBase):
    """Schema for document response API outputs."""
    id: UUID
    extracted_data: Optional[Dict[str, Any]] = None
    raw_ocr: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentReviewRequest(BaseModel):
    """Schema for submitting manual review corrections."""
    extracted_data: Dict[str, Any]


class DocumentStatsResponse(BaseModel):
    """Schema for document status count statistics."""
    total_documents: int
    completed: int
    review_needed: int
    pending: int
    failed: int


class IngestionItemDetail(BaseModel):
    """Detail for individual file ingestion attempt."""
    filename: str
    status: str  # INGESTED, DUPLICATE, INVALID, FAILED
    file_hash: Optional[str] = None
    message: Optional[str] = None
    document_id: Optional[UUID] = None


class IngestionBatchResult(BaseModel):
    """Summary of document batch ingestion run."""
    total_scanned: int = 0
    ingested_count: int = 0
    duplicate_count: int = 0
    invalid_count: int = 0
    failed_count: int = 0
    items: List[IngestionItemDetail] = []


class DocumentUploadResponse(BaseModel):
    """Schema for single document upload response."""
    document_id: Optional[UUID] = None
    filename: str
    status: str
    file_hash: Optional[str] = None
    hash: Optional[str] = None
    message: str
