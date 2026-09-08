"""Supabase Storage upload/download for bill PDFs."""

import httpx

from app.core.config import Settings, settings
from app.services import storage_service as storage_mod
from app.services.storage_service import StorageService


def test_supabase_url_from_pooler_database_url():
    cfg = Settings(
        DATABASE_URL="postgresql+psycopg://postgres.abc123xyz:secret@aws-0-us-east-1.pooler.supabase.com:5432/postgres",
        SUPABASE_URL="",
        SUPABASE_SERVICE_ROLE_KEY="role",
        TESTING=False,
    )
    assert cfg.supabase_project_url == "https://abc123xyz.supabase.co"
    assert cfg.supabase_storage_enabled is True


def test_supabase_disabled_during_tests():
    assert settings.TESTING is True
    assert settings.supabase_storage_enabled is False


def test_save_uploaded_file_posts_to_supabase(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "STORAGE_LOCATION", str(tmp_path))
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "service-role-test")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_BUCKET", "freight-bills")
    storage_mod._bucket_ready = False

    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path))
        if method == "POST" and path == "/bucket":
            return httpx.Response(200, json={"name": "freight-bills"})
        if method == "POST" and path.startswith("/object/"):
            return httpx.Response(200, json={"Key": path})
        return httpx.Response(404, text="no")

    monkeypatch.setattr(StorageService, "_request", staticmethod(fake_request))
    payload = b"%PDF-1.4 fake"
    stored_filename, relative_path, abs_path = StorageService.save_uploaded_file(payload, "bill.pdf")
    assert abs_path.exists()
    assert abs_path.read_bytes() == payload
    assert stored_filename.endswith(".pdf")
    assert relative_path.endswith(stored_filename)
    assert any(method == "POST" and path.startswith("/object/freight-bills/documents/") for method, path in calls)


def test_resolve_path_downloads_when_local_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "STORAGE_LOCATION", str(tmp_path))
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "service-role-test")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_BUCKET", "freight-bills")
    storage_mod._bucket_ready = True

    def fake_request(method, path, **kwargs):
        if method == "GET" and "/object/freight-bills/documents/" in path:
            return httpx.Response(200, content=b"%PDF-1.4 from-cloud")
        return httpx.Response(404, text="missing")

    monkeypatch.setattr(StorageService, "_request", staticmethod(fake_request))
    restored = StorageService.resolve_path("storage/documents/abc123.pdf")
    assert restored.exists()
    assert restored.read_bytes() == b"%PDF-1.4 from-cloud"
    assert restored.name == "abc123.pdf"


def test_delete_stored_file_removes_supabase_object(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "STORAGE_LOCATION", str(tmp_path))
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "service-role-test")
    local = tmp_path / "gone.pdf"
    local.write_bytes(b"%PDF-1.4")
    deleted = []

    def fake_request(method, path, **kwargs):
        deleted.append((method, path))
        return httpx.Response(200, json={})

    monkeypatch.setattr(StorageService, "_request", staticmethod(fake_request))
    StorageService.delete_stored_file(str(local))
    assert not local.exists()
    assert any(method == "DELETE" and "gone.pdf" in path for method, path in deleted)
