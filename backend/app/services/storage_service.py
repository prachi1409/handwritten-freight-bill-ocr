"""File storage: local cache plus optional Supabase Storage for bill PDFs."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_bucket_ready = False


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


class StorageService:
    """Persist PDFs on disk and, when configured, in a private Supabase bucket."""

    @staticmethod
    def get_storage_dir() -> Path:
        """Ensure and return the configured storage directory Path."""
        storage_dir = settings.storage_path
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir

    @staticmethod
    def object_key(stored_path: str) -> str:
        """Map a DB stored_path to the Supabase object key."""
        name = Path(str(stored_path or "").replace("\\", "/")).name
        if not name:
            raise FileNotFoundError("Stored path is empty.")
        if not name.lower().endswith(".pdf"):
            name = f"{name}.pdf"
        return f"documents/{name}"

    @staticmethod
    def save_uploaded_file(file_bytes: bytes, original_filename: str) -> Tuple[str, str, Path]:
        """Save PDF bytes locally and upload to Supabase Storage when enabled.

        Returns:
            Tuple of (stored_filename, relative_stored_path, absolute_physical_path).
        """
        storage_dir = StorageService.get_storage_dir()
        stored_filename = f"{uuid.uuid4().hex}.pdf"
        abs_path = storage_dir / stored_filename
        abs_path.write_bytes(file_bytes)

        try:
            relative_path = abs_path.relative_to(_backend_root()).as_posix()
        except ValueError:
            relative_path = f"storage/documents/{stored_filename}"

        if settings.supabase_storage_enabled:
            StorageService._ensure_bucket()
            StorageService._upload_object(StorageService.object_key(stored_filename), file_bytes)
            logger.info(
                "Uploaded bill to Supabase Storage bucket '%s' key '%s'",
                settings.SUPABASE_STORAGE_BUCKET,
                StorageService.object_key(stored_filename),
            )
        else:
            logger.warning(
                "Supabase Storage is not configured; '%s' is only on local disk. "
                "Set SUPABASE_SERVICE_ROLE_KEY (and optionally SUPABASE_URL) to persist PDFs in Supabase.",
                stored_filename,
            )

        logger.info("Saved physical document: '%s' -> '%s'", stored_filename, abs_path)
        return stored_filename, relative_path, abs_path

    @staticmethod
    def resolve_path(stored_path: str) -> Path:
        """Resolve a DB path to a local file, downloading from Supabase if needed."""
        if not stored_path:
            raise FileNotFoundError("Stored path is empty.")

        path_obj = Path(stored_path)
        if path_obj.is_absolute() and path_obj.exists():
            return path_obj.resolve()

        resolved = (_backend_root() / stored_path).resolve() if not path_obj.is_absolute() else path_obj.resolve()
        if resolved.exists():
            return resolved

        fallback = StorageService.get_storage_dir() / path_obj.name
        if fallback.exists():
            return fallback.resolve()

        if settings.supabase_storage_enabled:
            key = StorageService.object_key(stored_path)
            payload = StorageService._download_object(key)
            cache = StorageService.get_storage_dir() / Path(key).name
            cache.write_bytes(payload)
            logger.info("Hydrated local cache from Supabase Storage: '%s' -> '%s'", key, cache)
            return cache.resolve()

        return resolved if not path_obj.is_absolute() else path_obj.resolve()

    @staticmethod
    def file_exists(stored_path: str) -> bool:
        """True if the PDF is on disk or in Supabase Storage."""
        try:
            if StorageService.resolve_path(stored_path).exists():
                return True
        except FileNotFoundError:
            pass
        except Exception:
            pass
        if not settings.supabase_storage_enabled:
            return False
        try:
            StorageService._object_exists(StorageService.object_key(stored_path))
            return True
        except Exception:
            return False

    @staticmethod
    def delete_stored_file(stored_path: str) -> None:
        """Remove the local cache and the Supabase object when present."""
        if not stored_path:
            return
        try:
            path_obj = Path(stored_path)
            candidates = []
            if path_obj.is_absolute():
                candidates.append(path_obj)
            else:
                candidates.append(_backend_root() / stored_path)
            candidates.append(StorageService.get_storage_dir() / path_obj.name)
            for candidate in candidates:
                if candidate.exists() and candidate.is_file():
                    candidate.unlink(missing_ok=True)
        except Exception as err:
            logger.warning("Could not delete local stored file '%s': %s", stored_path, err)

        if settings.supabase_storage_enabled:
            try:
                StorageService._delete_object(StorageService.object_key(stored_path))
            except Exception as err:
                logger.warning("Could not delete Supabase object for '%s': %s", stored_path, err)

    @staticmethod
    def _headers() -> dict:
        key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
        return {
            "Authorization": f"Bearer {key}",
            "apikey": key,
        }

    @staticmethod
    def _storage_url(path: str) -> str:
        base = settings.supabase_project_url.rstrip("/")
        return f"{base}/storage/v1{path}"

    @staticmethod
    def _request(
        method: str,
        path: str,
        *,
        content: Optional[bytes] = None,
        json: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
        timeout: float = 60.0,
    ) -> httpx.Response:
        headers = StorageService._headers()
        if extra_headers:
            headers.update(extra_headers)
        url = StorageService._storage_url(path)
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, headers=headers, content=content, json=json)
        return response

    @staticmethod
    def _ensure_bucket() -> None:
        global _bucket_ready
        if _bucket_ready:
            return
        bucket = (settings.SUPABASE_STORAGE_BUCKET or "freight-bills").strip() or "freight-bills"
        response = StorageService._request(
            "POST",
            "/bucket",
            json={
                "id": bucket,
                "name": bucket,
                "public": False,
                "fileSizeLimit": 52428800,
            },
        )
        if response.status_code in (200, 201, 409):
            _bucket_ready = True
            return
        # Bucket may already exist (duplicate name returns 400 on some API versions).
        listed = StorageService._request("GET", f"/bucket/{bucket}")
        if listed.status_code == 200:
            _bucket_ready = True
            return
        raise RuntimeError(
            f"Could not create or access Supabase Storage bucket '{bucket}': "
            f"{response.status_code} {response.text[:300]}"
        )

    @staticmethod
    def _upload_object(key: str, file_bytes: bytes) -> None:
        bucket = (settings.SUPABASE_STORAGE_BUCKET or "freight-bills").strip()
        response = StorageService._request(
            "POST",
            f"/object/{bucket}/{key}",
            content=file_bytes,
            extra_headers={
                "Content-Type": "application/pdf",
                "x-upsert": "true",
            },
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Supabase Storage upload failed ({response.status_code}): {response.text[:300]}"
            )

    @staticmethod
    def _download_object(key: str) -> bytes:
        bucket = (settings.SUPABASE_STORAGE_BUCKET or "freight-bills").strip()
        response = StorageService._request("GET", f"/object/{bucket}/{key}")
        if response.status_code == 404:
            raise FileNotFoundError(f"Supabase Storage object not found: {key}")
        if response.status_code != 200:
            raise RuntimeError(
                f"Supabase Storage download failed ({response.status_code}): {response.text[:300]}"
            )
        return response.content

    @staticmethod
    def _object_exists(key: str) -> bool:
        bucket = (settings.SUPABASE_STORAGE_BUCKET or "freight-bills").strip()
        response = StorageService._request("GET", f"/object/info/{bucket}/{key}")
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        # Older APIs may not support /object/info — try a ranged GET.
        head = StorageService._request(
            "GET",
            f"/object/{bucket}/{key}",
            extra_headers={"Range": "bytes=0-0"},
        )
        return head.status_code in (200, 206)

    @staticmethod
    def _delete_object(key: str) -> None:
        bucket = (settings.SUPABASE_STORAGE_BUCKET or "freight-bills").strip()
        response = StorageService._request("DELETE", f"/object/{bucket}/{key}")
        if response.status_code not in (200, 202, 204, 404):
            raise RuntimeError(
                f"Supabase Storage delete failed ({response.status_code}): {response.text[:300]}"
            )
