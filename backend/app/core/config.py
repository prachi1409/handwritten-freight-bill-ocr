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
    GROQ_VISION_MAX_EDGE: int = 1536
    ENABLE_ENTITY_MATCHING: bool = True

    GOOGLE_CLOUD_PROJECT_ID: str = ""
    DOCUMENT_AI_LOCATION: str = "us"
    DOCUMENT_AI_PROCESSOR_ID: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    DATABASE_URL: str = "postgresql+psycopg://postgres:password@localhost:5432/freight_ocr"
    STORAGE_LOCATION: str = "./storage/documents"
    INPUT_DOC_LOCATION: str = "./input_doc_location"
    PROCESSED_DOCUMENTS_LOCATION: str = "./processed_documents"

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
        """Return Path object for storage/documents directory."""
        return Path(self.STORAGE_LOCATION).resolve()

    @property
    def input_path(self) -> Path:
        """Return Path object for input document directory."""
        return Path(self.INPUT_DOC_LOCATION).resolve()

    @property
    def processed_path(self) -> Path:
        """Return Path object for processed document directory."""
        return Path(self.PROCESSED_DOCUMENTS_LOCATION).resolve()


settings = Settings()
