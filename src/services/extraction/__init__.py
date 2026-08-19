"""
Document Extraction Subsystem.

Provides Azure Document Intelligence prebuilt-invoice integration,
offline mock fixture matching, and dynamic heuristic extraction.
"""

from src.services.extraction.azure_client import (
    AzureAnalysisError,
    AzureAuthenticationError,
    AzureConfigurationError,
    AzureDocumentIntelligenceClient,
    ExtractionError,
)
from src.services.extraction.mock_extractor import (
    FIXTURE_REGISTRY,
    MockExtractionService,
)
from src.services.extraction.service import (
    ExtractionService,
    get_extraction_service,
)

__all__ = [
    "FIXTURE_REGISTRY",
    "AzureAnalysisError",
    "AzureAuthenticationError",
    "AzureConfigurationError",
    "AzureDocumentIntelligenceClient",
    "ExtractionError",
    "ExtractionService",
    "MockExtractionService",
    "get_extraction_service",
]
