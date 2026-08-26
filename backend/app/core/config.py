"""Application configuration settings."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment configuration settings for Handwritten Freight Bill OCR."""

    PROJECT_NAME: str = "Handwritten Freight Bill OCR"
    DEBUG: bool = False
    TESTING: bool = False

    GOOGLE_CLOUD_PROJECT_ID: str
    DOCUMENT_AI_LOCATION: str = "us"
    DOCUMENT_AI_PROCESSOR_ID: str
    

    DATABASE_URL: str = "postgresql+psycopg://postgres:password@localhost:5432/freight_ocr"
    INPUT_DOC_LOCATION: str = "./input_doc_location"
    PROCESSED_DOCUMENTS_LOCATION: str = "./processed_documents"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def input_path(self) -> Path:
        """Return Path object for input document directory."""
        return Path(self.INPUT_DOC_LOCATION).resolve()

    @property
    def processed_path(self) -> Path:
        """Return Path object for processed document directory."""
        return Path(self.PROCESSED_DOCUMENTS_LOCATION).resolve()


settings = Settings()

