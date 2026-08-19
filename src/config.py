"""
Application Configuration Module.

Provides centralized, type-safe settings management using Pydantic Settings V2.
Handles environment variables, default paths, directory provisioning, logging,
and offline mock fallback detection.
"""

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and environment configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # General Project Info
    PROJECT_NAME: str = "Document Intelligence Pipeline"
    APP_NAME: str = "Document Intelligence Pipeline"
    VERSION: str = "0.1.0"
    APP_VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: list[str] = ["*"]

    # Azure Document Intelligence Settings
    AZURE_FORM_RECOGNIZER_ENDPOINT: str | None = Field(
        default=None,
        description="Azure Document Intelligence / Form Recognizer Endpoint URL",
    )
    AZURE_FORM_RECOGNIZER_KEY: str | None = Field(
        default=None,
        description="Azure Document Intelligence API Key",
    )
    USE_MOCK_AZURE: bool = Field(
        default=True,
        description="Explicit flag to force mock extractor even if credentials exist",
    )

    # Azure Cosmos DB Settings (Dual Storage)
    AZURE_COSMOS_ENDPOINT: str | None = Field(
        default=None,
        description="Azure Cosmos DB Account Endpoint URL",
    )
    AZURE_COSMOS_KEY: str | None = Field(
        default=None,
        description="Azure Cosmos DB Primary/Secondary Key",
    )
    AZURE_COSMOS_DATABASE: str = Field(
        default="document_intelligence_db",
        description="Cosmos DB database name",
    )
    AZURE_COSMOS_RAW_CONTAINER: str = Field(
        default="raw_extractions",
        description="Container name for raw extraction payloads",
    )
    AZURE_COSMOS_NORMALIZED_CONTAINER: str = Field(
        default="normalized_invoices",
        description="Container name for normalized invoice records",
    )
    USE_MOCK_COSMOS: bool = Field(
        default=True,
        description="Explicit flag to force local SQLite/JSON storage for Cosmos DB",
    )

    # Storage Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = Path("data")
    UPLOAD_DIR: Path = Path("data/uploads")
    STORE_DIR: Path = Path("data/store")
    FIXTURES_DIR: Path = Path("tests/fixtures")

    # Upload Constraints
    MAX_UPLOAD_SIZE_MB: int = 25
    MAX_UPLOAD_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB
    ALLOWED_EXTENSIONS: set[str] = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}
    ALLOWED_MIME_TYPES: set[str] = {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/tiff",
        "image/bmp",
    }

    # Duplicate & Anomaly Thresholds
    DUPLICATE_WINDOW_DAYS: int = 7
    FUZZY_MATCH_HIGH_CONFIDENCE_THRESHOLD: float = 85.0
    FUZZY_MATCH_LOW_CONFIDENCE_THRESHOLD: float = 70.0
    EXTREME_AMOUNT_THRESHOLD: float = 50000.0

    @property
    def is_azure_configured(self) -> bool:
        """Check if live Azure Document Intelligence credentials are validly populated."""
        return bool(
            self.AZURE_FORM_RECOGNIZER_ENDPOINT
            and self.AZURE_FORM_RECOGNIZER_KEY
            and str(self.AZURE_FORM_RECOGNIZER_ENDPOINT).strip() != ""
            and str(self.AZURE_FORM_RECOGNIZER_KEY).strip() != ""
            and not str(self.AZURE_FORM_RECOGNIZER_ENDPOINT).startswith("https://your-resource")
        )

    @property
    def is_mock_azure(self) -> bool:
        """Return True if mock extractor should be used (either forced or unconfigured)."""
        return self.USE_MOCK_AZURE or not self.is_azure_configured

    @property
    def is_cosmos_configured(self) -> bool:
        """Check if live Cosmos DB credentials are validly populated."""
        return bool(
            self.AZURE_COSMOS_ENDPOINT
            and self.AZURE_COSMOS_KEY
            and str(self.AZURE_COSMOS_ENDPOINT).strip() != ""
            and str(self.AZURE_COSMOS_KEY).strip() != ""
        )

    @property
    def is_mock_cosmos(self) -> bool:
        """Return True if local storage repository should be used."""
        return self.USE_MOCK_COSMOS or not self.is_cosmos_configured

    def ensure_directories(self) -> None:
        """Ensure all required runtime data directories exist."""
        for directory in [self.DATA_DIR, self.UPLOAD_DIR, self.STORE_DIR]:
            directory.mkdir(parents=True, exist_ok=True)

    def setup_logging(self) -> None:
        """Configure structured console logging."""
        numeric_level = getattr(logging, self.LOG_LEVEL.upper(), logging.INFO)
        logging.basicConfig(
            level=numeric_level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


@lru_cache
def get_settings() -> Settings:
    """Factory function returning cached application settings singleton."""
    app_settings = Settings()
    app_settings.ensure_directories()
    return app_settings


settings: Settings = get_settings()
