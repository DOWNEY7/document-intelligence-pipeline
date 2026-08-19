"""
src/services/storage package.

Dual-Storage abstraction providing unified CRUD and audit trail across
local SQLite store and Azure Cosmos DB containers.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.config import Settings, get_settings
from src.services.storage.base import (
    BaseStorageRepository,
    StorageConnectionError,
    StorageDuplicateKeyError,
    StorageError,
    StorageNotFoundError,
)
from src.services.storage.cosmos_client import CosmosStorageRepository
from src.services.storage.local_store import LocalStorageRepository

logger = logging.getLogger(__name__)

_storage_repository_instance: BaseStorageRepository | None = None


def get_storage_repository(
    settings_obj: Settings | None = None,
    db_path: str | Path | None = None,
    force_fresh: bool = False,
) -> BaseStorageRepository:
    """
    Factory resolving the active storage repository.
    Instantiates LocalStorageRepository if in mock mode / credentials absent;
    otherwise instantiates CosmosStorageRepository.
    """
    global _storage_repository_instance

    if _storage_repository_instance is not None and not force_fresh and db_path is None:
        return _storage_repository_instance

    settings = settings_obj or get_settings()

    if settings.is_mock_cosmos or not settings.is_cosmos_configured:
        sqlite_path = db_path or (settings.STORE_DIR / "pipeline_store.db")
        repo = LocalStorageRepository(db_path=sqlite_path)
    else:
        try:
            repo = CosmosStorageRepository(settings_obj=settings)
            repo.initialize()
        except Exception as e:
            logger.warning(
                "Failed to initialize CosmosStorageRepository (%s). Falling back to LocalStorageRepository.",
                e,
            )
            sqlite_path = db_path or (settings.STORE_DIR / "pipeline_store.db")
            repo = LocalStorageRepository(db_path=sqlite_path)

    if db_path is None:
        _storage_repository_instance = repo

    return repo


def reset_storage_repository() -> None:
    """Reset the cached storage singleton (used for test isolation)."""
    global _storage_repository_instance
    _storage_repository_instance = None


__all__ = [
    "BaseStorageRepository",
    "CosmosStorageRepository",
    "LocalStorageRepository",
    "StorageConnectionError",
    "StorageDuplicateKeyError",
    "StorageError",
    "StorageNotFoundError",
    "get_storage_repository",
    "reset_storage_repository",
]
