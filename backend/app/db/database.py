"""Database initialization and session management with safe startup connection logging."""

import logging
from typing import Any, Dict, Generator
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine
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


def log_database_connection_info(database_url: str):
    """Log safe database backend, host, and database name without exposing credentials."""
    try:
        parsed = urlparse(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
        scheme = parsed.scheme or "sqlite"
        db_type = "PostgreSQL" if "postgres" in scheme else scheme.upper()
        host = parsed.hostname or "localhost"
        db_name = (parsed.path or "").strip("/")

        logger.info(f"Database backend: {db_type}")
        logger.info(f"Database host: {host}")
        logger.info(f"Database name: {db_name or 'default'}")
    except Exception as e:
        logger.info(f"Database connection configured: {database_url[:20]}...")


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


def init_db() -> None:
    """Initialize database tables using metadata."""
    try:
        log_database_connection_info(settings.DATABASE_URL)
        logger.info("Initializing database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database tables: {e}")
        raise
