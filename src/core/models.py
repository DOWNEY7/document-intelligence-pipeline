"""
Core Domain Models for Document Intelligence Pipeline.

Strict Pydantic V2 schemas for field extraction, line items, anomaly detection,
raw extraction persistence, normalized invoice records, and API contracts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class AnomalySeverity(str, Enum):
    """Severity levels for anomaly and validation flags."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ConfidenceTier(str, Enum):
    """Classification tiers for canonical vendor matching confidence."""
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    UNKNOWN = "UNKNOWN"


class SpendCategory(str, Enum):
    """11 Canonical Spend Taxonomy Categories."""
    SOFTWARE_CLOUD = "Software & Cloud Services"
    HARDWARE_EQUIPMENT = "Hardware & Equipment"
    OFFICE_SUPPLIES = "Office Supplies"
    TRAVEL_TRANSPORTATION = "Travel & Transportation"
    MEALS_ENTERTAINMENT = "Meals & Entertainment"
    PROFESSIONAL_SERVICES = "Professional Services"
    MARKETING_ADVERTISING = "Marketing & Advertising"
    FACILITIES_REAL_ESTATE = "Facilities & Real Estate"
    LOGISTICS_FREIGHT = "Logistics & Freight"
    TELECOMMUNICATIONS = "Telecommunications"
    MISCELLANEOUS_OTHER = "Miscellaneous / Other"


class VendorMatchResult(BaseModel):
    """
    Structured outcome of canonical vendor fuzzy resolution.
    """
    model_config = ConfigDict(populate_by_name=True)

    canonical_name: str = Field(description="Resolved canonical vendor name or cleaned raw name")
    vendor_id: str | None = Field(default=None, description="Registered canonical vendor ID")
    match_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Fuzzy match confidence score (0-100)")
    is_known_vendor: bool = Field(default=False, description="True if score meets known vendor threshold (>= 70.0)")
    confidence_tier: ConfidenceTier | str = Field(default=ConfidenceTier.UNKNOWN, description="Confidence classification tier")
    default_category: str | None = Field(default=None, description="Default spend category associated with vendor")
    raw_vendor: str | None = Field(default=None, description="Original input vendor string")

    def as_tuple(self) -> tuple[str, str | None, float, bool]:
        """Convenience tuple unpacking: (canonical_name, vendor_id, match_score, is_known_vendor)."""
        return self.canonical_name, self.vendor_id, self.match_score, self.is_known_vendor


class ExtractedField(BaseModel, Generic[T]):
    """
    Generic model for an extracted document field with metadata.

    Attributes:
        value: The extracted and typed field value.
        confidence: Extraction confidence score in the range [0.0, 1.0].
        bounding_box: Optional polygon coordinates (e.g. [x0, y0, x1, y1, x2, y2, x3, y3]).
        page_number: 1-indexed page where field was discovered.
        raw_text: Optional unparsed textual representation from OCR/document.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    value: T
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score between 0 and 1")
    bounding_box: list[float] | None = Field(default=None, description="Bounding polygon coordinates")
    page_number: int | None = Field(default=1, ge=1, description="Page number where field was located")
    raw_text: str | None = Field(default=None, description="Original unparsed text snippet")

    def is_confident(self, threshold: float = 0.75) -> bool:
        """Check if field meets or exceeds a given confidence threshold."""
        return self.confidence >= threshold


class LineItem(BaseModel):
    """
    Model representing an extracted line item on an invoice or receipt.
    """
    model_config = ConfigDict(populate_by_name=True)

    item_id: str | None = Field(default=None, description="Optional item code or SKU")
    description: str | None = Field(default=None, description="Line item description")
    quantity: float | None = Field(default=None, ge=0, description="Item quantity")
    unit_price: float | None = Field(default=None, description="Price per unit")
    total_amount: float | None = Field(default=None, description="Line total amount")
    tax_amount: float | None = Field(default=None, description="Tax component for line item")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Line item extraction confidence")
    category: str | None = Field(default=None, description="Spend taxonomy category for line item")
    page_number: int | None = Field(default=1, ge=1, description="Page number")
    bounding_box: list[float] | None = Field(default=None, description="Bounding polygon coordinates")

    def has_math_discrepancy(self, tolerance: float = 0.05) -> bool:
        """Check if quantity * unit_price != total_amount within numeric tolerance."""
        if self.quantity is not None and self.unit_price is not None and self.total_amount is not None:
            expected = round(self.quantity * self.unit_price, 2)
            actual = round(self.total_amount, 2)
            return abs(expected - actual) > tolerance
        return False


class AnomalyFlag(BaseModel):
    """
    Model for an identified anomaly, duplicate warning, or data validation alert.
    """
    model_config = ConfigDict(populate_by_name=True)

    code: str = Field(description="Structured error/anomaly code (e.g. EXTREME_AMOUNT, DUPLICATE_SUBMISSION)")
    message: str = Field(description="Human-readable explanation of the anomaly")
    severity: AnomalySeverity | str = Field(default=AnomalySeverity.WARNING, description="Anomaly severity level")
    field: str | None = Field(default=None, description="Associated document field name if applicable")
    details: dict[str, Any] | None = Field(default_factory=dict, description="Contextual diagnostic payload")


class ValidationRuleResult(BaseModel):
    """
    Outcome of an individual schema or business rule validation check.
    """
    model_config = ConfigDict(populate_by_name=True)

    rule_name: str
    passed: bool
    message: str
    severity: AnomalySeverity | str = AnomalySeverity.INFO
    score: float | None = None


class ConfidenceBreakdown(BaseModel):
    """
    Granular breakdown of extraction confidence across major invoice components.
    """
    model_config = ConfigDict(populate_by_name=True)

    overall: float = Field(default=1.0, ge=0.0, le=1.0)
    vendor: float = Field(default=1.0, ge=0.0, le=1.0)
    invoice_id: float = Field(default=1.0, ge=0.0, le=1.0)
    date: float = Field(default=1.0, ge=0.0, le=1.0)
    total: float = Field(default=1.0, ge=0.0, le=1.0)
    line_items: float = Field(default=1.0, ge=0.0, le=1.0)
    field_scores: dict[str, float] = Field(default_factory=dict)


class RawInvoicePayload(BaseModel):
    """
    Complete unnormalized extraction payload from Azure Document Intelligence or Mock.
    Persisted to Cosmos DB 'raw_extractions' container for full auditability.
    """
    model_config = ConfigDict(populate_by_name=True)

    document_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique document ID")
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Tracing correlation ID")
    filename: str = Field(description="Original filename of the ingested document")
    storage_path: str | None = Field(default=None, description="Path to persisted source file in data/uploads/")
    file_hash: str | None = Field(default=None, description="SHA-256 hash of the document bytes")
    file_size: int | None = Field(default=None, ge=0, description="Size in bytes")
    content_type: str | None = Field(default="application/pdf", description="MIME type of document")
    raw_fields: dict[str, ExtractedField[Any]] = Field(
        default_factory=dict,
        description="Dictionary of raw extracted key-value fields",
    )
    raw_items: list[LineItem] = Field(
        default_factory=list,
        description="Raw line item objects extracted from document tables",
    )
    confidence_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Confidence scores per extracted field",
    )
    extraction_engine: str = Field(
        default="azure_prebuilt_invoice",
        description="Name of extraction engine (e.g. azure_prebuilt_invoice, mock_fallback)",
    )
    extracted_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 extraction timestamp",
    )
    raw_azure_response: dict[str, Any] | None = Field(
        default=None,
        description="Optional full raw response JSON from Azure SDK",
    )
    raw_text: str | None = Field(
        default=None,
        description="Raw extracted textual content from document",
    )


class NormalizedInvoice(BaseModel):
    """
    Standardized, validated invoice domain model.
    Serves as the primary data contract across M1 extraction, M2 normalization,
    M3 duplicate/anomaly detection, and M4 analytics dashboard.
    """
    model_config = ConfigDict(populate_by_name=True)

    # Identifiers & Tracing
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Primary entity UUID")
    document_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Source document ID")
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Pipeline trace correlation ID")

    # Document File Attributes
    filename: str | None = Field(default="document.pdf", description="Original document filename")
    storage_path: str | None = Field(default=None, description="Local file system path or blob URI for preview")
    file_hash: str | None = Field(default=None, description="SHA-256 hash of source document")
    file_size: int | None = Field(default=None, ge=0, description="File size in bytes")

    # Core Extracted Fields (with confidence and geometry)
    vendor_name: ExtractedField[str] = Field(description="Extracted vendor name")
    invoice_id: ExtractedField[str] = Field(description="Extracted invoice number / identifier")
    invoice_date: ExtractedField[str] = Field(description="Invoice date in ISO 8601 YYYY-MM-DD")
    due_date: ExtractedField[str] | None = Field(default=None, description="Payment due date in YYYY-MM-DD")
    total_amount: ExtractedField[float] = Field(description="Invoice total monetary amount")
    tax_amount: ExtractedField[float] | None = Field(default=None, description="Total tax / VAT amount")
    subtotal_amount: ExtractedField[float] | None = Field(default=None, description="Subtotal amount before tax")
    amount_due: ExtractedField[float] | None = Field(default=None, description="Remaining amount due")
    customer_name: ExtractedField[str] | None = Field(default=None, description="Billed customer or client name")
    purchase_order: ExtractedField[str] | None = Field(default=None, description="Purchase order reference")

    # Currency representation
    currency: ExtractedField[str] | None = Field(default=None, description="Currency field")
    currency_raw: str | None = Field(default="$", description="Raw currency symbol or text from document")
    currency_iso: str = Field(default="USD", description="ISO 4217 3-letter currency code (USD, EUR, GBP, JPY)")

    # Line Items
    line_items: list[LineItem] = Field(default_factory=list, description="Structured line items")

    # Canonical Normalization Attributes (Enriched by M2)
    vendor_raw: str | None = Field(default=None, description="Raw vendor string before fuzzy match")
    vendor_canonical: str | None = Field(default=None, description="Resolved canonical vendor name")
    vendor_id: str | None = Field(default=None, description="Canonical vendor ID in reference table")
    vendor_match_score: float | None = Field(default=None, ge=0.0, le=100.0, description="RapidFuzz match score")
    is_known_vendor: bool = Field(default=True, description="Whether vendor is registered in known vendors table")
    spend_category: str | None = Field(default=None, description="Spend category from 11-category taxonomy")

    # Duplicate & Anomaly Detection Attributes (Enriched by M3)
    is_duplicate: bool = Field(default=False, description="Flag indicating duplicate invoice submission")
    duplicate_of_id: str | None = Field(default=None, description="ID of original invoice if duplicate")
    duplicate_reason: str | None = Field(default=None, description="Explanation of duplicate match")
    duplicate_match_details: dict[str, Any] | None = Field(default_factory=dict)
    has_anomalies: bool = Field(default=False, description="Flag indicating one or more anomalies present")
    anomalies: list[AnomalyFlag] = Field(default_factory=list, description="List of detected anomaly flags")
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Aggregated risk score from 0.0 to 1.0")

    # Pipeline Processing Metadata
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Overall extraction confidence score")
    confidence_breakdown: ConfidenceBreakdown | None = Field(default=None, description="Detailed confidence metrics")
    extraction_engine: str = Field(default="mock_fallback", description="Engine used: azure_prebuilt_invoice or mock_fallback")
    status: str = Field(default="PROCESSED", description="Document status: PENDING, PROCESSED, FLAGGED, ERROR, NEEDS_REVIEW, SUCCESS")
    validation_rules: list[ValidationRuleResult] = Field(default_factory=list, description="Rule evaluation outcomes")
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 creation timestamp",
    )
    updated_at: str | None = Field(default=None, description="ISO 8601 last update timestamp")

    @model_validator(mode="after")
    def sync_model_helpers(self) -> NormalizedInvoice:
        """Synchronize vendor, currency, and anomaly status helpers."""
        if not self.vendor_raw and self.vendor_name and self.vendor_name.value:
            self.vendor_raw = str(self.vendor_name.value)
        if not self.vendor_canonical and self.vendor_raw:
            self.vendor_canonical = self.vendor_raw
        if self.currency and self.currency.value:
            if not self.currency_iso or self.currency_iso == "USD":
                c_val = str(self.currency.value).upper()
                if c_val in ["EUR", "GBP", "JPY", "USD", "CAD", "AUD", "CHF"]:
                    self.currency_iso = c_val
                elif c_val == "€":
                    self.currency_iso = "EUR"
                elif c_val == "£":
                    self.currency_iso = "GBP"
                elif c_val == "¥":
                    self.currency_iso = "JPY"
        if self.anomalies and not self.has_anomalies:
            self.has_anomalies = True
        return self


class DocumentUploadResponse(BaseModel):
    """
    API response model returned by POST /upload and POST /api/v1/upload endpoints.
    """
    model_config = ConfigDict(populate_by_name=True)

    document_id: str = Field(description="Generated unique document ID")
    correlation_id: str = Field(description="Tracing correlation ID")
    filename: str = Field(description="Uploaded filename")
    file_hash: str | None = Field(default=None, description="SHA-256 digest of uploaded file")
    status: str = Field(default="SUCCESS", description="Upload and extraction status")
    extraction_engine: str = Field(description="Engine used for extraction")
    extracted_data: NormalizedInvoice = Field(description="Extracted and normalized invoice payload")
    message: str | None = Field(default=None, description="Informational message or warning")


class HealthCheckResponse(BaseModel):
    """
    API response model returned by GET /health and GET /api/v1/health endpoints.
    """
    model_config = ConfigDict(populate_by_name=True)

    status: str = "healthy"
    app_name: str = "Document Intelligence Pipeline"
    version: str = "0.1.0"
    mock_mode: bool = True
    azure_configured: bool = False
    cosmos_configured: bool = False
    storage_healthy: bool = True
    upload_dir_status: str | None = "ok"
    upload_dir_path: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# Alias for backward/blueprint compatibility
HealthResponse = HealthCheckResponse
NormalizedLineItem = LineItem
