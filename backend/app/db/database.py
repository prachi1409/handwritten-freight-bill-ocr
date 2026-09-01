"""Database initialization and session management."""

import logging
from typing import Any, Dict, Generator, List, Tuple
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


def _postgres_connect_args(database_url: str) -> Dict[str, Any]:
    """Build psycopg connect args for local vs hosted Postgres (e.g. Supabase)."""
    args: Dict[str, Any] = {"connect_timeout": 15}
    parsed = urlparse(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)
    is_local = host in ("localhost", "127.0.0.1", "::1")
    if not is_local and "sslmode" not in query:
        args["sslmode"] = "require"
    return args


connect_args: Dict[str, Any] = {}
if settings.DATABASE_URL.startswith("postgresql"):
    connect_args = _postgres_connect_args(settings.DATABASE_URL)

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG,
    connect_args=connect_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency generator that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _documents_column_ddl(dialect: str) -> List[Tuple[str, str]]:
    """DDL fragments for columns the app expects on documents."""
    if dialect == "postgresql":
        return [
            ("filename", "VARCHAR(255) DEFAULT ''"),
            ("file_hash", "VARCHAR(64) DEFAULT ''"),
            ("file_path", "VARCHAR(512) DEFAULT ''"),
            ("status", "VARCHAR(20) DEFAULT 'PENDING'"),
            ("extracted_data", "JSONB"),
            ("raw_ocr", "JSONB"),
            ("confidence", "DOUBLE PRECISION"),
            ("error_message", "TEXT"),
            ("created_at", "TIMESTAMPTZ DEFAULT NOW()"),
            ("processed_at", "TIMESTAMPTZ"),
        ]
    return [
        ("filename", "VARCHAR(255) DEFAULT ''"),
        ("file_hash", "VARCHAR(64) DEFAULT ''"),
        ("file_path", "VARCHAR(512) DEFAULT ''"),
        ("status", "VARCHAR(20) DEFAULT 'PENDING'"),
        ("extracted_data", "JSON"),
        ("raw_ocr", "JSON"),
        ("confidence", "FLOAT"),
        ("error_message", "TEXT"),
        ("created_at", "DATETIME"),
        ("processed_at", "DATETIME"),
    ]


def ensure_documents_schema(bind=None) -> None:
    """Add any missing documents columns. create_all does not alter existing tables."""
    bind = bind or engine
    import app.db.models  # noqa: F401 — register Document on Base.metadata

    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if "documents" not in tables:
        return

    existing = {col["name"] for col in inspector.get_columns("documents")}
    dialect = bind.dialect.name
    added: List[str] = []
    with bind.begin() as conn:
        for name, ddl in _documents_column_ddl(dialect):
            if name in existing:
                continue
            conn.execute(text(f"ALTER TABLE documents ADD COLUMN {name} {ddl}"))
            added.append(name)
        if dialect == "postgresql":
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_documents_status ON documents (status)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_documents_created_at ON documents (created_at)"
            ))
    if dialect == "postgresql":
        try:
            with bind.begin() as conn:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_documents_file_hash ON documents (file_hash)"
                ))
        except Exception as idx_err:
            logger.warning("Could not create unique file_hash index: %s", idx_err)
    if added:
        logger.info("Added missing documents columns: %s", ", ".join(added))


def init_db() -> None:
    """Initialize database tables using metadata and patch older schemas."""
    try:
        logger.info("Initializing database tables...")
        import app.db.models  # noqa: F401
        Base.metadata.create_all(bind=engine)
        ensure_documents_schema(engine)
        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database tables: {e}")
        raise
