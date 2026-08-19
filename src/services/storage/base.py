"""
src/services/storage/base.py

Abstract storage repository interface for Document Intelligence dual-storage architecture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.models import NormalizedInvoice, RawInvoicePayload


# ============================================================================
# Storage Exceptions
# ============================================================================

class StorageError(Exception):
    """Base exception for all storage layer failures."""
    pass


class StorageNotFoundError(StorageError):
    """Raised when a requested record is not found."""
    pass


class StorageDuplicateKeyError(StorageError):
    """Raised when attempting to insert an entity with an existing ID."""
    pass


class StorageConnectionError(StorageError):
    """Raised when the storage backend cannot be reached."""
    pass


# ============================================================================
# Abstract Storage Interface
# ============================================================================

class BaseStorageRepository(ABC):
    """
    Abstract repository contract for Document Intelligence dual-storage layer.
    Manages immutable raw extractions and normalized business records.
    """

    # --- Raw Extractions Container (raw_extractions) ---

    @abstractmethod
    def save_raw(self, payload: RawInvoicePayload) -> str:
        """Persist raw extraction payload. Returns document_id."""
        pass

    @abstractmethod
    def get_raw(self, document_id: str) -> RawInvoicePayload | None:
        """Retrieve raw extraction payload by document_id."""
        pass

    @abstractmethod
    def get_raw_by_correlation_id(self, correlation_id: str) -> list[RawInvoicePayload]:
        """Retrieve all raw extraction payloads matching correlation_id."""
        pass

    @abstractmethod
    def list_raw(self, limit: int = 100, offset: int = 0) -> list[RawInvoicePayload]:
        """List raw extraction payloads with pagination."""
        pass

    @abstractmethod
    def delete_raw(self, document_id: str) -> bool:
        """Delete raw extraction payload by document_id."""
        pass

    # --- Normalized Invoices Container (normalized_invoices) ---

    @abstractmethod
    def save_normalized(self, invoice: NormalizedInvoice) -> str:
        """Persist normalized invoice. Returns invoice entity id."""
        pass

    @abstractmethod
    def get_normalized(self, entity_id: str) -> NormalizedInvoice | None:
        """Retrieve normalized invoice by entity id."""
        pass

    @abstractmethod
    def get_normalized_by_document_id(self, document_id: str) -> NormalizedInvoice | None:
        """Retrieve normalized invoice by source document_id."""
        pass

    @abstractmethod
    def get_normalized_by_correlation_id(self, correlation_id: str) -> list[NormalizedInvoice]:
        """Retrieve normalized invoices matching correlation_id."""
        pass

    @abstractmethod
    def list_normalized(
        self,
        limit: int = 100,
        offset: int = 0,
        vendor: str | None = None,
        category: str | None = None,
        is_duplicate: bool | None = None,
        has_anomalies: bool | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[NormalizedInvoice]:
        """List normalized invoices with optional multi-attribute filtering and pagination."""
        pass

    @abstractmethod
    def count_normalized(
        self,
        vendor: str | None = None,
        category: str | None = None,
        is_duplicate: bool | None = None,
        has_anomalies: bool | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        """Count normalized records matching filter criteria."""
        pass

    @abstractmethod
    def delete_normalized(self, entity_id: str) -> bool:
        """Delete normalized invoice by entity id."""
        pass

    # --- Cross-Container Correlation & Audit ---

    @abstractmethod
    def get_by_correlation_id(
        self, correlation_id: str
    ) -> tuple[list[RawInvoicePayload], list[NormalizedInvoice]]:
        """Retrieve both raw extractions and normalized records linked by correlation_id."""
        pass

    @abstractmethod
    def get_audit_trail(self, document_id: str) -> dict[str, Any]:
        """Generate unified audit report combining raw payload and normalized record."""
        pass

    # --- Lifecycle & Administration ---

    @abstractmethod
    def check_health(self) -> bool:
        """Check repository read/write operational health."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Purge all records in repository (used for test isolation)."""
        pass

    @abstractmethod
    def initialize(self) -> None:
        """Provision tables or containers if not already existing."""
        pass
