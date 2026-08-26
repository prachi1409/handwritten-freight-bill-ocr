"""Pytest configuration and shared fixtures."""

import pymupdf as fitz  # PyMuPDF
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.config import settings
settings.TESTING = True

from app.db.database import Base, get_db
from app.main import app


from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="function")
def db_session():
    """Create an isolated in-memory SQLite database session for unit tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """FastAPI TestClient fixture with in-memory DB dependency override."""
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def create_pdf(tmp_path):
    """Factory fixture to generate real, valid sample PDF files on disk."""
    def _create_pdf(filename: str, text: str = "Sample Freight Bill Document") -> Path:
        file_path = tmp_path / filename
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), text)
        doc.save(str(file_path))
        doc.close()
        return file_path

    return _create_pdf
