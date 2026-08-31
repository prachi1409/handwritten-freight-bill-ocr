"""File storage management for document files."""

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """Service handling physical file persistence and relative path resolution."""

    @staticmethod
    def get_storage_dir() -> Path:
        """Ensure and return the configured storage directory Path."""
        storage_dir = settings.storage_path
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir

    @staticmethod
    def save_uploaded_file(file_bytes: bytes, original_filename: str) -> Tuple[str, str, Path]:
        """Save file bytes into storage location with UUID filename.

        Args:
            file_bytes: Raw binary bytes of uploaded PDF or document.
            original_filename: Original filename uploaded by user.

        Returns:
            Tuple of (stored_filename, relative_stored_path, absolute_physical_path).
        """
        storage_dir = StorageService.get_storage_dir()
        file_uuid = uuid.uuid4().hex
        # Standardize stored file suffix to .pdf
        stored_filename = f"{file_uuid}.pdf"
        
        abs_path = storage_dir / stored_filename
        with open(abs_path, "wb") as f:
            f.write(file_bytes)

        # Store relative path e.g. "storage/documents/8a9c7d...pdf"
        try:
            backend_root = Path(__file__).resolve().parent.parent.parent
            relative_path = abs_path.relative_to(backend_root).as_posix()
        except Exception:
            relative_path = f"storage/documents/{stored_filename}"

        logger.info(f"Saved physical document: '{stored_filename}' -> '{abs_path}' (relative: '{relative_path}')")
        return stored_filename, relative_path, abs_path

    @staticmethod
    def resolve_path(stored_path: str) -> Path:
        """Safely resolve a stored relative or absolute path to an absolute physical Path object.

        Args:
            stored_path: Relative or absolute path string stored in database.

        Returns:
            Absolute Path object.
        """
        if not stored_path:
            raise FileNotFoundError("Stored path is empty.")

        path_obj = Path(stored_path)
        if path_obj.is_absolute():
            return path_obj.resolve()

        backend_root = Path(__file__).resolve().parent.parent.parent
        resolved = (backend_root / stored_path).resolve()
        
        # Fallback check directly in storage dir if relative path resolution fails
        if not resolved.exists():
            fallback = settings.storage_path / path_obj.name
            if fallback.exists():
                return fallback.resolve()

        return resolved

    @staticmethod
    def file_exists(stored_path: str) -> bool:
        """Check if physical file exists on disk."""
        try:
            return StorageService.resolve_path(stored_path).exists()
        except Exception:
            return False

