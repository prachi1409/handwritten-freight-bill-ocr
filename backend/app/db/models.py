"""SQLAlchemy ORM models for freight bill documents."""

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import String, Text, Float, Enum, DateTime, JSON, Uuid, Boolean, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class DocumentStatus(str, enum.Enum):
    """Status of freight bill processing pipeline."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    REVIEW = "REVIEW"
    FAILED = "FAILED"


# JSONB type with fallback to generic JSON for non-PostgreSQL dialects
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Document(Base):
    """Model representing a freight bill document."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True).with_variant(PG_UUID(as_uuid=True), "postgresql"),
        primary_key=True,
        default=uuid.uuid4
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False, length=20),
        default=DocumentStatus.PENDING,
        index=True,
        nullable=False
    )
    document_type: Mapped[str] = mapped_column(String(50), default="freight_bill", nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    overall_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    extracted_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    field_confidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    raw_ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ocr_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    validation_warnings: Mapped[Optional[List[Any]]] = mapped_column(JSONType, nullable=True)

    manual_corrections: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Properties for API / schema backwards compatibility
    @property
    def filename(self) -> str:
        return self.original_filename

    @filename.setter
    def filename(self, value: str) -> None:
        self.original_filename = value

    @property
    def file_path(self) -> str:
        return self.stored_path

    @file_path.setter
    def file_path(self, value: str) -> None:
        self.stored_path = value

    @property
    def confidence(self) -> Optional[float]:
        return self.overall_confidence

    @confidence.setter
    def confidence(self, value: Optional[float]) -> None:
        self.overall_confidence = value

    @property
    def raw_ocr(self) -> Dict[str, Any]:
        return {
            "raw_text": self.raw_ocr_text or "",
            "ocr_metadata": self.ocr_metadata or {},
            "validation_warnings": self.validation_warnings or []
        }

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, original_filename='{self.original_filename}', status='{self.status}')>"
