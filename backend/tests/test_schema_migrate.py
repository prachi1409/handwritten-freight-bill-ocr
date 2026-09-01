"""Tests for adding missing documents columns on an existing table."""

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.db.database import Base, ensure_documents_schema


def test_ensure_documents_schema_adds_filename():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE documents (id VARCHAR(36) PRIMARY KEY)"))

    ensure_documents_schema(engine)

    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(documents)")).fetchall()
    names = {row[1] for row in rows}
    assert "filename" in names
    assert "file_hash" in names
    assert "status" in names
    engine.dispose()
