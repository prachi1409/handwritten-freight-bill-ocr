"""FastAPI Application Main Entrypoint."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.routes import health, documents
from app.core.config import settings
from app.db.database import init_db

# Configure application logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for setup and teardown."""
    logger.info(f"Starting {settings.PROJECT_NAME} backend...")
    # Ensure input/output directories exist
    settings.input_path.mkdir(parents=True, exist_ok=True)
    settings.processed_path.mkdir(parents=True, exist_ok=True)

    if not settings.TESTING:
        try:
            init_db()
        except Exception as e:
            logger.warning(f"Database initialization deferred (Database not reachable): {e}")

    yield

    logger.info("Shutting down application...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0-day2",
    description="Backend API for Handwritten Freight Bill OCR - Day 2 Ingestion",
    lifespan=lifespan
)

# Enable CORS for React Frontend
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(health.router)
app.include_router(documents.router, prefix="/api/v1")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
