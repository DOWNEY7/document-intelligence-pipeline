"""
src/services/storage/local_store.py

High-fidelity SQLite/JSON local repository implementing BaseStorageRepository
for 100% offline execution, testing, and persistence.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from src.core.models import NormalizedInvoice, RawInvoicePayload
from src.services.storage.base import (
    BaseStorageRepository,
    StorageError,
    StorageNotFoundError,
)

logger = logging.getLogger(__name__)


class LocalStorageRepository(BaseStorageRepository):
    """
    SQLite-backed local dual-storage repository.
    Supports in-memory (':memory:') for tests and file-backed for persistent dev.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._local = threading.local()

        if self.db_path != ":memory:":
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)

        self.initialize()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create thread-local SQLite connection with JSON support."""
        if not hasattr(self._local, "connection") or self._local.connection is None:
            # If in-memory, create a single shared memory connection or URI
            if self.db_path == ":memory:":
                # Share connection across threads via check_same_thread=False
                conn = sqlite3.connect(
                    ":memory:",
                    check_same_thread=False,
                    timeout=30.0,
                )
            else:
                conn = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    timeout=30.0,
                )
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for disk files
            if self.db_path != ":memory:":
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            self._local.connection = conn
        return self._local.connection

    def initialize(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS raw_extractions (
                        document_id TEXT PRIMARY KEY,
                        correlation_id TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        extracted_at TEXT NOT NULL,
                        extraction_engine TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_raw_correlation ON raw_extractions(correlation_id);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_raw_extracted_at ON raw_extractions(extracted_at);"
                )

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS normalized_invoices (
                        id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL,
                        correlation_id TEXT NOT NULL,
                        filename TEXT,
                        vendor_raw TEXT,
                        vendor_canonical TEXT,
                        vendor_id TEXT,
                        invoice_id TEXT,
                        invoice_date TEXT,
                        due_date TEXT,
                        total_amount REAL NOT NULL,
                        tax_amount REAL,
                        subtotal_amount REAL,
                        currency_iso TEXT NOT NULL,
                        spend_category TEXT,
                        is_duplicate INTEGER DEFAULT 0,
                        duplicate_of_id TEXT,
                        has_anomalies INTEGER DEFAULT 0,
                        risk_score REAL DEFAULT 0.0,
                        status TEXT DEFAULT 'PROCESSED',
                        created_at TEXT NOT NULL,
                        invoice_json TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_norm_doc_id ON normalized_invoices(document_id);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_norm_corr_id ON normalized_invoices(correlation_id);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_norm_vendor ON normalized_invoices(vendor_canonical);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_norm_date ON normalized_invoices(invoice_date);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_norm_category ON normalized_invoices(spend_category);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_norm_dup ON normalized_invoices(is_duplicate);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_norm_anomaly ON normalized_invoices(has_anomalies);"
                )

    # --- Raw Extractions Container ---

    def save_raw(self, payload: RawInvoicePayload) -> str:
        """Persist raw extraction payload. Deeply isolated via JSON serialization."""
        with self._lock:
            conn = self._get_connection()
            payload_json = payload.model_dump_json()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO raw_extractions (
                            document_id, correlation_id, filename, extracted_at, extraction_engine, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?);
                        """,
                        (
                            payload.document_id,
                            payload.correlation_id,
                            payload.filename,
                            payload.extracted_at,
                            payload.extraction_engine,
                            payload_json,
                        ),
                    )
                return payload.document_id
            except Exception as e:
                logger.exception("Failed to save raw payload %s", payload.document_id)
                raise StorageError(f"Failed to persist raw payload: {e}") from e

    def get_raw(self, document_id: str) -> RawInvoicePayload | None:
        """Retrieve raw extraction payload by document_id."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT payload_json FROM raw_extractions WHERE document_id = ?;",
                (document_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return RawInvoicePayload.model_validate_json(row["payload_json"])

    def get_raw_by_correlation_id(self, correlation_id: str) -> list[RawInvoicePayload]:
        """Retrieve raw payloads matching correlation_id."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT payload_json FROM raw_extractions WHERE correlation_id = ? ORDER BY extracted_at DESC;",
                (correlation_id,),
            )
            rows = cursor.fetchall()
            return [RawInvoicePayload.model_validate_json(r["payload_json"]) for r in rows]

    def list_raw(self, limit: int = 100, offset: int = 0) -> list[RawInvoicePayload]:
        """List raw extraction payloads with pagination."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT payload_json FROM raw_extractions ORDER BY extracted_at DESC LIMIT ? OFFSET ?;",
                (limit, offset),
            )
            rows = cursor.fetchall()
            return [RawInvoicePayload.model_validate_json(r["payload_json"]) for r in rows]

    def delete_raw(self, document_id: str) -> bool:
        """Delete raw extraction payload by document_id."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    "DELETE FROM raw_extractions WHERE document_id = ?;",
                    (document_id,),
                )
                return cursor.rowcount > 0

    # --- Normalized Invoices Container ---

    def save_normalized(self, invoice: NormalizedInvoice) -> str:
        """Persist normalized invoice. Deeply isolated via JSON serialization."""
        with self._lock:
            conn = self._get_connection()
            invoice_json = invoice.model_dump_json()

            total_val = float(invoice.total_amount.value) if invoice.total_amount else 0.0
            tax_val = (
                float(invoice.tax_amount.value)
                if invoice.tax_amount and invoice.tax_amount.value is not None
                else None
            )
            sub_val = (
                float(invoice.subtotal_amount.value)
                if invoice.subtotal_amount and invoice.subtotal_amount.value is not None
                else None
            )
            inv_date = invoice.invoice_date.value if invoice.invoice_date else None
            due_date = invoice.due_date.value if invoice.due_date else None
            inv_id = invoice.invoice_id.value if invoice.invoice_id else None

            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO normalized_invoices (
                            id, document_id, correlation_id, filename, vendor_raw, vendor_canonical,
                            vendor_id, invoice_id, invoice_date, due_date, total_amount, tax_amount,
                            subtotal_amount, currency_iso, spend_category, is_duplicate, duplicate_of_id,
                            has_anomalies, risk_score, status, created_at, invoice_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            invoice.id,
                            invoice.document_id,
                            invoice.correlation_id,
                            invoice.filename,
                            invoice.vendor_raw,
                            invoice.vendor_canonical,
                            invoice.vendor_id,
                            inv_id,
                            inv_date,
                            due_date,
                            total_val,
                            tax_val,
                            sub_val,
                            invoice.currency_iso,
                            invoice.spend_category,
                            1 if invoice.is_duplicate else 0,
                            invoice.duplicate_of_id,
                            1 if invoice.has_anomalies else 0,
                            invoice.risk_score,
                            invoice.status,
                            invoice.created_at,
                            invoice_json,
                        ),
                    )
                return invoice.id
            except Exception as e:
                logger.exception("Failed to save normalized invoice %s", invoice.id)
                raise StorageError(f"Failed to persist normalized invoice: {e}") from e

    def get_normalized(self, entity_id: str) -> NormalizedInvoice | None:
        """Retrieve normalized invoice by entity id."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT invoice_json FROM normalized_invoices WHERE id = ?;",
                (entity_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return NormalizedInvoice.model_validate_json(row["invoice_json"])

    def get_normalized_by_document_id(self, document_id: str) -> NormalizedInvoice | None:
        """Retrieve normalized invoice by source document_id."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT invoice_json FROM normalized_invoices WHERE document_id = ? ORDER BY created_at DESC LIMIT 1;",
                (document_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return NormalizedInvoice.model_validate_json(row["invoice_json"])

    def get_normalized_by_correlation_id(self, correlation_id: str) -> list[NormalizedInvoice]:
        """Retrieve normalized invoices matching correlation_id."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT invoice_json FROM normalized_invoices WHERE correlation_id = ? ORDER BY created_at DESC;",
                (correlation_id,),
            )
            rows = cursor.fetchall()
            return [NormalizedInvoice.model_validate_json(r["invoice_json"]) for r in rows]

    def _build_filter_clause(
        self,
        vendor: str | None = None,
        category: str | None = None,
        is_duplicate: bool | None = None,
        has_anomalies: bool | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[str, list[Any]]:
        """Build SQL WHERE clause and parameter list."""
        clauses: list[str] = []
        params: list[Any] = []

        if vendor:
            clauses.append("(vendor_canonical LIKE ? OR vendor_raw LIKE ?)")
            v_param = f"%{vendor.strip()}%"
            params.extend([v_param, v_param])

        if category:
            clauses.append("spend_category = ?")
            params.append(category.strip())

        if is_duplicate is not None:
            clauses.append("is_duplicate = ?")
            params.append(1 if is_duplicate else 0)

        if has_anomalies is not None:
            clauses.append("has_anomalies = ?")
            params.append(1 if has_anomalies else 0)

        if start_date:
            clauses.append("invoice_date >= ?")
            params.append(start_date.strip())

        if end_date:
            clauses.append("invoice_date <= ?")
            params.append(end_date.strip())

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where_sql, params

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
        with self._lock:
            conn = self._get_connection()
            where_sql, params = self._build_filter_clause(
                vendor=vendor,
                category=category,
                is_duplicate=is_duplicate,
                has_anomalies=has_anomalies,
                start_date=start_date,
                end_date=end_date,
            )
            query = f"SELECT invoice_json FROM normalized_invoices {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?;"
            params.extend([limit, offset])

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [NormalizedInvoice.model_validate_json(r["invoice_json"]) for r in rows]

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
        with self._lock:
            conn = self._get_connection()
            where_sql, params = self._build_filter_clause(
                vendor=vendor,
                category=category,
                is_duplicate=is_duplicate,
                has_anomalies=has_anomalies,
                start_date=start_date,
                end_date=end_date,
            )
            query = f"SELECT COUNT(*) as count FROM normalized_invoices {where_sql};"
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return int(row["count"]) if row else 0

    def delete_normalized(self, entity_id: str) -> bool:
        """Delete normalized invoice by entity id."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    "DELETE FROM normalized_invoices WHERE id = ?;",
                    (entity_id,),
                )
                return cursor.rowcount > 0

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
        """Check repository operational health."""
        try:
            with self._lock:
                conn = self._get_connection()
                cursor = conn.execute("SELECT 1;")
                return cursor.fetchone() is not None
        except Exception:
            return False

    def clear(self) -> None:
        """Purge all records in repository."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("DELETE FROM raw_extractions;")
                conn.execute("DELETE FROM normalized_invoices;")
