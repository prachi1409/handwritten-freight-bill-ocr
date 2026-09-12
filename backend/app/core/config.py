"""Application configuration settings."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment configuration settings for Handwritten Freight Bill OCR."""

    PROJECT_NAME: str = "Handwritten Freight Bill OCR"
    DEBUG: bool = False
    TESTING: bool = False
    
    # OCR Provider: 'local' (default vision OCR), 'document_ai' (Google Cloud), or 'mock'
    OCR_PROVIDER: str = "local"
    USE_MOCK_OCR: bool = False

    # Image Preprocessing Settings for Handwritten Document Enhancement
    ENABLE_IMAGE_PREPROCESSING: bool = True
    TARGET_DPI: int = 300
    CONTRAST_ENHANCEMENT: float = 1.2
    DESKEW_IMAGE: bool = True

    # Groq LLM: map OCR text onto freight JSON; vision reads the page image (handwriting)
    ENABLE_GROQ: bool = True
    ENABLE_GROQ_VISION: bool = True
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    GROQ_VISION_MODEL: str = "qwen/qwen3.6-27b"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_VISION_MAX_PAGES: int = 2
    GROQ_VISION_MAX_EDGE: int = 1024
    # Point 7: Groq Vision is a field-aware rescue, not the default extractor.
    GROQ_VISION_FALLBACK_ENABLED: bool = True
    GROQ_VISION_FALLBACK_MAX_FIELDS: int = 8
    GROQ_VISION_FALLBACK_MIN_CONFIDENCE: float = 0.80
    GROQ_VISION_AMBIGUITY_MAX_GAP: float = 0.08
    # Reprocess only: send the page to Groq Vision first, then gazetteer snap.
    # New uploads stay cheap-first + rescue.
    GROQ_VISION_PRIMARY_ON_REPROCESS: bool = True
    ENABLE_ENTITY_MATCHING: bool = True
    CANDIDATE_TOP_K: int = 5
    DECODE_BEAM_WIDTH: int = 8
    DECODE_MAX_PER_FIELD: int = 4
    DECODE_APPLY_SELECTED: bool = True
    PRIOR_INJECT_WHEN_OCR_WEAK: bool = True
    PRIOR_INJECT_MIN_COUNT: int = 1
    PRIOR_INJECT_MAX: int = 5
    PRIOR_FILL_MIN_COUNT: int = 3
    PRIOR_FILL_MIN_PROBABILITY: float = 0.80
    # Point 4: isotonic calibration. Do not fit below these counts (per field).
    CALIBRATION_MIN_SAMPLES: int = 20
    CALIBRATION_MIN_POSITIVES: int = 3
    CALIBRATION_MIN_NEGATIVES: int = 3
    # Auto-post thresholds: numeric/financial tighter, handwritten names looser.
    CONFIDENCE_THRESHOLD_DEFAULT: float = 0.80
    CONFIDENCE_THRESHOLD_NUMERIC: float = 0.90
    CONFIDENCE_THRESHOLD_NAME: float = 0.70
    # Point 5: consistency/anomaly analysis (does not overwrite extracted fields).
    CONSISTENCY_LINE_ITEM_TOLERANCE: float = 0.05
    CONSISTENCY_PRIOR_MIN_COUNT: int = 3
    CONSISTENCY_PRIOR_MIN_PROBABILITY: float = 0.70
    CONSISTENCY_PRIOR_WEAK_PROBABILITY: float = 0.20

    GOOGLE_CLOUD_PROJECT_ID: str = ""
    DOCUMENT_AI_LOCATION: str = "us"
    DOCUMENT_AI_PROCESSOR_ID: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    DATABASE_URL: str = "postgresql+psycopg://postgres:password@localhost:5432/freight_ocr"
    STORAGE_LOCATION: str = "./storage/documents"
    INPUT_DOC_LOCATION: str = "./input_doc_location"
    PROCESSED_DOCUMENTS_LOCATION: str = "./processed_documents"
    # Supabase Storage for bill PDFs (private bucket). Service role is required.
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "freight-bills"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def document_ai_configured(self) -> bool:
        """True when Document AI project and processor IDs are set."""
        return bool(
            (self.GOOGLE_CLOUD_PROJECT_ID or "").strip()
            and (self.DOCUMENT_AI_PROCESSOR_ID or "").strip()
        )

    @property
    def storage_path(self) -> Path:
        """Return Path object for storage/documents directory (backend-root relative)."""
        path = Path(self.STORAGE_LOCATION)
        if path.is_absolute():
            return path
        backend_root = Path(__file__).resolve().parent.parent.parent
        return (backend_root / path).resolve()

    @property
    def supabase_project_url(self) -> str:
        """Explicit SUPABASE_URL, or derived from a Supabase DATABASE_URL."""
        explicit = (self.SUPABASE_URL or "").strip().rstrip("/")
        if explicit:
            return explicit
        from urllib.parse import unquote, urlparse

        parsed = urlparse(self.DATABASE_URL or "")
        user = unquote(parsed.username or "")
        host = parsed.hostname or ""
        if user.startswith("postgres.") and "supabase.com" in host:
            ref = user.split(".", 1)[1]
            if ref:
                return f"https://{ref}.supabase.co"
        if host.startswith("db.") and host.endswith(".supabase.co"):
            parts = host.split(".")
            if len(parts) >= 3:
                return f"https://{parts[1]}.supabase.co"
        return ""

    @property
    def supabase_storage_enabled(self) -> bool:
        """True when the backend can upload/download PDFs in Supabase Storage."""
        if self.TESTING:
            return False
        return bool(self.supabase_project_url and (self.SUPABASE_SERVICE_ROLE_KEY or "").strip())

    @property
    def input_path(self) -> Path:
        """Return Path object for input document directory."""
        return Path(self.INPUT_DOC_LOCATION).resolve()

    @property
    def processed_path(self) -> Path:
        """Return Path object for processed document directory."""
        return Path(self.PROCESSED_DOCUMENTS_LOCATION).resolve()


settings = Settings()
