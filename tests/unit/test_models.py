"""
Unit Tests for Core Pydantic Domain Models.
Document Intelligence Pipeline - Milestone 1
"""

import pytest
from pydantic import ValidationError

from src.core.models import (
    AnomalyFlag,
    AnomalySeverity,
    ConfidenceBreakdown,
    DocumentUploadResponse,
    ExtractedField,
    HealthResponse,
    LineItem,
    NormalizedInvoice,
    RawInvoicePayload,
    ValidationRuleResult,
)


class TestExtractedField:
    def test_extracted_field_valid_string(self):
        field = ExtractedField[str](value="Acme Corp", confidence=0.95)
        assert field.value == "Acme Corp"
        assert field.confidence == 0.95
        assert field.page_number == 1
        assert field.bounding_box is None
        assert field.is_confident(threshold=0.90) is True
        assert field.is_confident(threshold=0.98) is False

    def test_extracted_field_valid_float(self):
        field = ExtractedField[float](
            value=500.25, confidence=0.88, bounding_box=[0.1, 0.2, 0.3, 0.4]
        )
        assert field.value == 500.25
        assert field.confidence == 0.88
        assert field.bounding_box == [0.1, 0.2, 0.3, 0.4]

    def test_extracted_field_confidence_bounds(self):
        # Confidence must be between 0.0 and 1.0
        with pytest.raises(ValidationError):
            ExtractedField[str](value="Bad", confidence=1.5)

        with pytest.raises(ValidationError):
            ExtractedField[str](value="Bad", confidence=-0.1)

    def test_extracted_field_raw_text(self):
        field = ExtractedField[str](value="12345", confidence=0.9, raw_text="Invoice # 12345")
        assert field.raw_text == "Invoice # 12345"


class TestLineItem:
    def test_valid_line_item(self):
        item = LineItem(
            description="Software Subscription",
            quantity=2.0,
            unit_price=50.0,
            total_amount=100.0,
            tax_amount=10.0,
            confidence=0.99,
        )
        assert item.description == "Software Subscription"
        assert item.quantity == 2.0
        assert item.unit_price == 50.0
        assert item.total_amount == 100.0
        assert item.tax_amount == 10.0
        assert item.has_math_discrepancy() is False

    def test_line_item_math_discrepancy(self):
        item = LineItem(
            description="Bad math item",
            quantity=2.0,
            unit_price=50.0,
            total_amount=120.0,
            confidence=0.9,
        )
        assert item.has_math_discrepancy() is True

    def test_optional_fields_line_item(self):
        item = LineItem(description="Misc item")
        assert item.quantity is None
        assert item.unit_price is None
        assert item.total_amount is None
        assert item.confidence == 1.0
        assert item.has_math_discrepancy() is False


class TestAnomalyFlag:
    def test_anomaly_flag_creation(self):
        flag = AnomalyFlag(
            code="EXTREME_AMOUNT",
            message="Invoice amount exceeds outlier threshold.",
            severity=AnomalySeverity.WARNING,
            field="total_amount",
            details={"threshold": 50000.0, "actual": 1250000.0},
        )
        assert flag.code == "EXTREME_AMOUNT"
        assert flag.severity == AnomalySeverity.WARNING
        assert flag.details["actual"] == 1250000.0


class TestValidationRuleResult:
    def test_validation_rule_result(self):
        res = ValidationRuleResult(
            rule_name="vendor_known_check",
            passed=True,
            message="Vendor found in catalog",
            score=0.98,
        )
        assert res.rule_name == "vendor_known_check"
        assert res.passed is True
        assert res.score == 0.98


class TestConfidenceBreakdown:
    def test_confidence_breakdown(self):
        breakdown = ConfidenceBreakdown(
            overall=0.95,
            vendor=0.98,
            invoice_id=0.90,
            date=0.92,
            total=0.99,
            line_items=0.95,
            field_scores={"VendorName": 0.98},
        )
        assert breakdown.overall == 0.95
        assert breakdown.field_scores["VendorName"] == 0.98


class TestRawInvoicePayload:
    def test_raw_payload_creation(self):
        raw = RawInvoicePayload(
            document_id="doc-123",
            correlation_id="corr-456",
            filename="invoice.pdf",
            raw_fields={
                "VendorName": ExtractedField[str](value="Acme Corp", confidence=0.95),
            },
            raw_items=[
                LineItem(description="Service A", quantity=1.0, unit_price=100.0, total_amount=100.0)
            ],
            confidence_scores={"vendor_name": 0.95},
            extraction_engine="mock_fallback",
        )
        assert raw.document_id == "doc-123"
        assert raw.raw_fields["VendorName"].value == "Acme Corp"
        assert len(raw.raw_items) == 1
        assert raw.extraction_engine == "mock_fallback"


class TestNormalizedInvoice:
    def test_normalized_invoice_serialization(self, sample_normalized_invoice: NormalizedInvoice):
        data = sample_normalized_invoice.model_dump()
        assert data["document_id"] == "test-doc-uuid-1234"
        assert data["vendor_name"]["value"] == "Amazon Web Services Inc."
        assert data["total_amount"]["value"] == 1420.50
        assert len(data["line_items"]) == 1
        assert data["status"] == "SUCCESS"
        assert data["currency_iso"] == "USD"

    def test_normalized_invoice_json_roundtrip(self, sample_normalized_invoice: NormalizedInvoice):
        json_str = sample_normalized_invoice.model_dump_json()
        loaded = NormalizedInvoice.model_validate_json(json_str)
        assert loaded.document_id == sample_normalized_invoice.document_id
        assert loaded.vendor_name.value == sample_normalized_invoice.vendor_name.value
        assert loaded.total_amount.value == sample_normalized_invoice.total_amount.value
        assert loaded.vendor_canonical == "Amazon Web Services Inc."

    def test_normalized_invoice_missing_required_fields(self):
        with pytest.raises(ValidationError):
            NormalizedInvoice(
                document_id="doc-1",
                # missing vendor_name, invoice_id, invoice_date, total_amount
            )

    def test_normalized_invoice_validator_currency_sync(self):
        inv = NormalizedInvoice(
            document_id="doc-eur",
            vendor_name=ExtractedField[str](value="Google Ireland", confidence=0.95),
            invoice_id=ExtractedField[str](value="GOOG-01", confidence=0.95),
            invoice_date=ExtractedField[str](value="2026-08-01", confidence=0.95),
            total_amount=ExtractedField[float](value=2180.75, confidence=0.95),
            currency=ExtractedField[str](value="EUR", confidence=0.95),
        )
        assert inv.currency_iso == "EUR"
        assert inv.vendor_raw == "Google Ireland"
        assert inv.vendor_canonical == "Google Ireland"


class TestDocumentUploadResponse:
    def test_document_upload_response(self, sample_normalized_invoice: NormalizedInvoice):
        resp = DocumentUploadResponse(
            document_id=sample_normalized_invoice.document_id,
            correlation_id=sample_normalized_invoice.correlation_id,
            filename=sample_normalized_invoice.filename,
            file_hash="abcdef123456",
            status="SUCCESS",
            extraction_engine="mock_fallback",
            extracted_data=sample_normalized_invoice,
        )
        assert resp.status == "SUCCESS"
        assert resp.extracted_data.total_amount.value == 1420.50


class TestHealthResponse:
    def test_health_response_schema(self):
        resp = HealthResponse(
            status="healthy",
            app_name="DocIntel",
            version="0.1.0",
            mock_mode=True,
            azure_configured=False,
            upload_dir_status="ok",
            upload_dir_path="data/uploads",
            timestamp="2026-08-19T01:00:00Z",
        )
        assert resp.status == "healthy"
        assert resp.mock_mode is True
        assert resp.app_name == "DocIntel"
