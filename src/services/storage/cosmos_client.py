"""
src/services/storage/cosmos_client.py

Azure Cosmos DB implementation of BaseStorageRepository.
Operates on dual containers: 'raw_extractions' and 'normalized_invoices'.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.config import Settings, get_settings
from src.core.models import NormalizedInvoice, RawInvoicePayload
from src.services.storage.base import (
    BaseStorageRepository,
    StorageConnectionError,
    StorageError,
    StorageNotFoundError,
)

logger = logging.getLogger(__name__)

COSMOS_SYSTEM_PROPERTIES = {"_rid", "_self", "_etag", "_attachments", "_ts"}


def _strip_cosmos_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Remove Azure Cosmos DB system metadata fields."""
    return {k: v for k, v in data.items() if k not in COSMOS_SYSTEM_PROPERTIES}


class CosmosStorageRepository(BaseStorageRepository):
    """
    Azure Cosmos DB repository targeting dual containers:
    1. 'raw_extractions' with partition key '/id' (document_id)
    2. 'normalized_invoices' with partition key '/id' (id)
    """

    def __init__(
        self,
        settings_obj: Settings | None = None,
        max_retries: int = 3,
        base_backoff_sec: float = 0.5,
    ) -> None:
        self.settings = settings_obj or get_settings()
        self.max_retries = max_retries
        self.base_backoff_sec = base_backoff_sec

        self.endpoint = self.settings.AZURE_COSMOS_ENDPOINT
        self.key = self.settings.AZURE_COSMOS_KEY
        self.database_name = self.settings.AZURE_COSMOS_DATABASE
        self.raw_container_name = self.settings.AZURE_COSMOS_RAW_CONTAINER
        self.normalized_container_name = self.settings.AZURE_COSMOS_NORMALIZED_CONTAINER

        self._client: Any = None
        self._database: Any = None
        self._raw_container: Any = None
        self._normalized_container: Any = None
        self._initialized = False

    def _ensure_connected(self) -> None:
        """Lazy connection and database/container provisioner."""
        if self._initialized:
            return

        if not self.endpoint or not self.key:
            raise StorageConnectionError("Cosmos DB credentials (endpoint/key) are not configured.")

        try:
            from azure.cosmos import CosmosClient, PartitionKey
            from azure.cosmos.exceptions import CosmosHttpResponseError

            self._client = CosmosClient(self.endpoint, credential=self.key)
            self._database = self._client.create_database_if_not_exists(id=self.database_name)
            self._raw_container = self._database.create_container_if_not_exists(
                id=self.raw_container_name,
                partition_key=PartitionKey(path="/id"),
            )
            self._normalized_container = self._database.create_container_if_not_exists(
                id=self.normalized_container_name,
                partition_key=PartitionKey(path="/id"),
            )
            self._initialized = True
        except Exception as e:
            logger.exception("Failed to initialize Cosmos DB connection: %s", e)
            raise StorageConnectionError(f"Could not connect to Cosmos DB: {e}") from e

    def _execute_with_retry(self, operation: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a Cosmos DB SDK operation with exponential backoff on 429 / timeouts."""
        self._ensure_connected()
        last_err = None

        for attempt in range(self.max_retries):
            try:
                return operation(*args, **kwargs)
            except Exception as exc:
                last_err = exc
                err_str = str(exc)
                # Check for 429 TooManyRequests or rate limiting
                if "429" in err_str or "RequestRateTooLarge" in err_str:
                    sleep_time = self.base_backoff_sec * (2**attempt)
                    logger.warning("Cosmos 429 rate limit. Retrying in %.2fs (attempt %d/%d)", sleep_time, attempt + 1, self.max_retries)
                    time.sleep(sleep_time)
                else:
                    break

        raise StorageError(f"Cosmos DB operation failed after {self.max_retries} attempts: {last_err}") from last_err

    def initialize(self) -> None:
        """Explicitly initialize connection and provision containers."""
        self._ensure_connected()

    # --- Raw Extractions Container ---

    def save_raw(self, payload: RawInvoicePayload) -> str:
        """Persist raw extraction payload to 'raw_extractions' container."""
        doc = payload.model_dump(mode="json")
        doc["id"] = payload.document_id

        def _op() -> Any:
            return self._raw_container.upsert_item(body=doc)

        self._execute_with_retry(_op)
        return payload.document_id

    def get_raw(self, document_id: str) -> RawInvoicePayload | None:
        """Retrieve raw extraction payload by document_id."""
        self._ensure_connected()
        try:
            item = self._raw_container.read_item(item=document_id, partition_key=document_id)
            cleaned = _strip_cosmos_metadata(item)
            return RawInvoicePayload.model_validate(cleaned)
        except Exception as e:
            if "404" in str(e) or "NotFound" in str(e):
                return None
            logger.warning("Error reading raw document %s from Cosmos: %s", document_id, e)
            return None

    def get_raw_by_correlation_id(self, correlation_id: str) -> list[RawInvoicePayload]:
        """Query raw extraction payloads matching correlation_id."""
        self._ensure_connected()
        query = "SELECT * FROM c WHERE c.correlation_id = @corr_id ORDER BY c.extracted_at DESC"
        parameters = [{"name": "@corr_id", "value": correlation_id}]

        try:
            items = list(
                self._raw_container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True,
                )
            )
            return [RawInvoicePayload.model_validate(_strip_cosmos_metadata(it)) for it in items]
        except Exception as e:
            logger.exception("Error querying raw payloads by correlation_id %s: %s", correlation_id, e)
            return []

    def list_raw(self, limit: int = 100, offset: int = 0) -> list[RawInvoicePayload]:
        """List raw extraction payloads with pagination."""
        self._ensure_connected()
        query = "SELECT * FROM c ORDER BY c.extracted_at DESC OFFSET @offset LIMIT @limit"
        parameters = [{"name": "@offset", "value": offset}, {"name": "@limit", "value": limit}]

        try:
            items = list(
                self._raw_container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True,
                )
            )
            return [RawInvoicePayload.model_validate(_strip_cosmos_metadata(it)) for it in items]
        except Exception as e:
            logger.exception("Error listing raw payloads: %s", e)
            return []

    def delete_raw(self, document_id: str) -> bool:
        """Delete raw extraction payload by document_id."""
        self._ensure_connected()
        try:
            self._raw_container.delete_item(item=document_id, partition_key=document_id)
            return True
        except Exception as e:
            if "404" in str(e) or "NotFound" in str(e):
                return False
            raise StorageError(f"Failed to delete raw document: {e}") from e

    # --- Normalized Invoices Container ---

    def save_normalized(self, invoice: NormalizedInvoice) -> str:
        """Persist normalized invoice to 'normalized_invoices' container."""
        doc = invoice.model_dump(mode="json")
        doc["id"] = invoice.id

        def _op() -> Any:
            return self._normalized_container.upsert_item(body=doc)

        self._execute_with_retry(_op)
        return invoice.id

    def get_normalized(self, entity_id: str) -> NormalizedInvoice | None:
        """Retrieve normalized invoice by entity id."""
        self._ensure_connected()
        try:
            item = self._normalized_container.read_item(item=entity_id, partition_key=entity_id)
            cleaned = _strip_cosmos_metadata(item)
            return NormalizedInvoice.model_validate(cleaned)
        except Exception as e:
            if "404" in str(e) or "NotFound" in str(e):
                return None
            logger.warning("Error reading normalized invoice %s from Cosmos: %s", entity_id, e)
            return None

    def get_normalized_by_document_id(self, document_id: str) -> NormalizedInvoice | None:
        """Retrieve normalized invoice by document_id."""
        self._ensure_connected()
        query = "SELECT * FROM c WHERE c.document_id = @doc_id ORDER BY c.created_at DESC OFFSET 0 LIMIT 1"
        parameters = [{"name": "@doc_id", "value": document_id}]

        try:
            items = list(
                self._normalized_container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True,
                )
            )
            if not items:
                return None
            return NormalizedInvoice.model_validate(_strip_cosmos_metadata(items[0]))
        except Exception as e:
            logger.warning("Error reading normalized invoice for document %s: %s", document_id, e)
            return None

    def get_normalized_by_correlation_id(self, correlation_id: str) -> list[NormalizedInvoice]:
        """Retrieve normalized invoices matching correlation_id."""
        self._ensure_connected()
        query = "SELECT * FROM c WHERE c.correlation_id = @corr_id ORDER BY c.created_at DESC"
        parameters = [{"name": "@corr_id", "value": correlation_id}]

        try:
            items = list(
                self._normalized_container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True,
                )
            )
            return [NormalizedInvoice.model_validate(_strip_cosmos_metadata(it)) for it in items]
        except Exception as e:
            logger.exception("Error querying normalized invoices by correlation_id: %s", e)
            return []

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
        """List normalized invoices with multi-attribute filtering and pagination."""
        self._ensure_connected()
        clauses: list[str] = []
        parameters: list[dict[str, Any]] = []

        if vendor:
            clauses.append("(CONTAINS(LOWER(c.vendor_canonical), @vendor) OR CONTAINS(LOWER(c.vendor_raw), @vendor))")
            parameters.append({"name": "@vendor", "value": vendor.lower()})

        if category:
            clauses.append("c.spend_category = @category")
            parameters.append({"name": "@category", "value": category})

        if is_duplicate is not None:
            clauses.append("c.is_duplicate = @is_dup")
            parameters.append({"name": "@is_dup", "value": is_duplicate})

        if has_anomalies is not None:
            clauses.append("c.has_anomalies = @has_anom")
            parameters.append({"name": "@has_anom", "value": has_anomalies})

        if start_date:
            clauses.append("c.invoice_date.value >= @start_date")
            parameters.append({"name": "@start_date", "value": start_date})

        if end_date:
            clauses.append("c.invoice_date.value <= @end_date")
            parameters.append({"name": "@end_date", "value": end_date})

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM c {where_sql} ORDER BY c.created_at DESC OFFSET @offset LIMIT @limit"
        parameters.extend([{"name": "@offset", "value": offset}, {"name": "@limit", "value": limit}])

        try:
            items = list(
                self._normalized_container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True,
                )
            )
            return [NormalizedInvoice.model_validate(_strip_cosmos_metadata(it)) for it in items]
        except Exception as e:
            logger.exception("Error listing normalized invoices: %s", e)
            return []

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
        self._ensure_connected()
        clauses: list[str] = []
        parameters: list[dict[str, Any]] = []

        if vendor:
            clauses.append("(CONTAINS(LOWER(c.vendor_canonical), @vendor) OR CONTAINS(LOWER(c.vendor_raw), @vendor))")
            parameters.append({"name": "@vendor", "value": vendor.lower()})

        if category:
            clauses.append("c.spend_category = @category")
            parameters.append({"name": "@category", "value": category})

        if is_duplicate is not None:
            clauses.append("c.is_duplicate = @is_dup")
            parameters.append({"name": "@is_dup", "value": is_duplicate})

        if has_anomalies is not None:
            clauses.append("c.has_anomalies = @has_anom")
            parameters.append({"name": "@has_anom", "value": has_anomalies})

        if start_date:
            clauses.append("c.invoice_date.value >= @start_date")
            parameters.append({"name": "@start_date", "value": start_date})

        if end_date:
            clauses.append("c.invoice_date.value <= @end_date")
            parameters.append({"name": "@end_date", "value": end_date})

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT VALUE COUNT(1) FROM c {where_sql}"

        try:
            items = list(
                self._normalized_container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True,
                )
            )
            return int(items[0]) if items else 0
        except Exception as e:
            logger.exception("Error counting normalized records: %s", e)
            return 0

    def delete_normalized(self, entity_id: str) -> bool:
        """Delete normalized invoice by entity id."""
        self._ensure_connected()
        try:
            self._normalized_container.delete_item(item=entity_id, partition_key=entity_id)
            return True
        except Exception as e:
            if "404" in str(e) or "NotFound" in str(e):
                return False
            raise StorageError(f"Failed to delete normalized record: {e}") from e

    # --- Cross-Container Correlation & Audit ---

    def get_by_correlation_id(
        self, correlation_id: str
    ) -> tuple[list[RawInvoicePayload], list[NormalizedInvoice]]:
        """Retrieve both raw extractions and normalized records linked by correlation_id."""
        raws = self.get_raw_by_correlation_id(correlation_id)
        norms = self.get_normalized_by_correlation_id(correlation_id)
        return raws, norms

    def get_audit_trail(self, document_id: str) -> dict[str, Any]:
        """Generate unified audit report combining raw payload and normalized record."""
        raw = self.get_raw(document_id)
        norm = self.get_normalized_by_document_id(document_id)

        if not raw and not norm:
            raise StorageNotFoundError(f"No records found for document_id: {document_id}")

        return {
            "document_id": document_id,
            "correlation_id": (
                raw.correlation_id if raw else (norm.correlation_id if norm else None)
            ),
            "raw_payload": raw.model_dump(mode="json") if raw else None,
            "normalized_record": norm.model_dump(mode="json") if norm else None,
            "has_raw": raw is not None,
            "has_normalized": norm is not None,
        }

    # --- Lifecycle & Administration ---

    def check_health(self) -> bool:
        """Check Cosmos DB operational health."""
        try:
            self._ensure_connected()
            # Perform lightweight read
            query = "SELECT VALUE 1"
            items = list(
                self._raw_container.query_items(
                    query=query,
                    enable_cross_partition_query=True,
                )
            )
            return len(items) >= 0
        except Exception:
            return False

    def clear(self) -> None:
        """Purge records across both containers."""
        self._ensure_connected()
        for c in [self._raw_container, self._normalized_container]:
            try:
                items = list(
                    c.query_items(
                        query="SELECT c.id FROM c",
                        enable_cross_partition_query=True,
                    )
                )
                for item in items:
                    c.delete_item(item=item["id"], partition_key=item["id"])
            except Exception as e:
                logger.warning("Error clearing Cosmos container: %s", e)
