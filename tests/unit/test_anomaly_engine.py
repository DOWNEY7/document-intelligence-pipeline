"""
tests/unit/test_anomaly_engine.py

Unit tests for Anomaly Detection Engine and Risk Scorer.
"""

import uuid
from datetime import UTC, datetime, timedelta

from src.core.models import (
    AnomalyFlag,
    AnomalySeverity,
    ExtractedField,
    LineItem,
    NormalizedInvoice,
)
from src.services.detection.anomaly_engine import (
    AnomalyDetectionEngine,
    DetectionService,
)


def make_test_invoice(
    vendor: str = "Amazon Web Services",
    is_known_vendor: bool = True,
    amount: float = 1200.0,
    invoice_date: str = "2026-08-01",
    currency: str = "USD",
    line_items: list[LineItem] | None = None,
) -> NormalizedInvoice:
    return NormalizedInvoice(
        id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        vendor_name=ExtractedField(value=vendor, confidence=0.98),
        vendor_canonical=vendor,
        is_known_vendor=is_known_vendor,
        invoice_id=ExtractedField(value="INV-1234", confidence=0.95),
        invoice_date=ExtractedField(value=invoice_date, confidence=0.99),
        total_amount=ExtractedField(value=amount, confidence=0.99),
        currency=ExtractedField(value=currency, confidence=1.0),
        currency_iso=currency,
        line_items=line_items or [],
    )


class TestAnomalyDetectionEngine:
    """Tests covering all 6 anomaly rules and risk scoring."""

    def test_clean_invoice_produces_no_anomalies(self):
        engine = AnomalyDetectionEngine()
        inv = make_test_invoice(
            vendor="Amazon Web Services",
            amount=500.0,
            invoice_date="2026-08-15",
            currency="USD",
        )
        flags = engine.detect(inv)
        assert len(flags) == 0

    def test_extreme_amount_absolute_high(self):
        engine = AnomalyDetectionEngine()
        inv = make_test_invoice(amount=2_500_000.0)
        flags = engine.detect(inv)
        assert any(f.code == "EXTREME_AMOUNT" and f.severity == AnomalySeverity.CRITICAL for f in flags)

    def test_extreme_amount_suspiciously_low(self):
        engine = AnomalyDetectionEngine()
        inv = make_test_invoice(amount=0.005)
        flags = engine.detect(inv)
        assert any(f.code == "EXTREME_AMOUNT" for f in flags)

    def test_unrecognized_vendor_anomaly(self):
        engine = AnomalyDetectionEngine()
        inv = make_test_invoice(vendor="Unknown Random LLC", is_known_vendor=False)
        flags = engine.detect(inv)
        assert any(f.code == "UNRECOGNIZED_VENDOR" for f in flags)

    def test_currency_mismatch_anomaly(self):
        engine = AnomalyDetectionEngine()
        inv = make_test_invoice(currency="XYZ")
        flags = engine.detect(inv)
        assert any(f.code == "CURRENCY_MISMATCH" for f in flags)

    def test_line_item_math_discrepancy(self):
        engine = AnomalyDetectionEngine()
        items = [
            LineItem(description="Item 1", quantity=1.0, unit_price=100.0, total_amount=100.0),
            LineItem(description="Item 2", quantity=2.0, unit_price=50.0, total_amount=100.0),
        ]
        # Total items = 200, but invoice total declared as 500
        inv = make_test_invoice(amount=500.0, line_items=items)
        flags = engine.detect(inv)
        assert any(f.code == "LINE_ITEM_MATH" for f in flags)

    def test_date_anomaly_far_future(self):
        engine = AnomalyDetectionEngine()
        # 1 year in the future
        future_date = (datetime.now(UTC) + timedelta(days=365)).strftime("%Y-%m-%d")
        inv = make_test_invoice(invoice_date=future_date)
        flags = engine.detect(inv)
        assert any(f.code == "DATE_ANOMALY" for f in flags)

    def test_date_anomaly_far_past(self):
        engine = AnomalyDetectionEngine()
        # 5 years in past
        past_date = (datetime.now(UTC) - timedelta(days=1825)).strftime("%Y-%m-%d")
        inv = make_test_invoice(invoice_date=past_date)
        flags = engine.detect(inv)
        assert any(f.code == "DATE_ANOMALY" for f in flags)

    def test_missing_fields_zero_total(self):
        engine = AnomalyDetectionEngine()
        inv = make_test_invoice(amount=0.0)
        flags = engine.detect(inv)
        assert any(f.code == "MISSING_FIELDS" and f.field == "total_amount" for f in flags)

    def test_composite_risk_score_calculation(self):
        flags = [
            AnomalyFlag(code="EXTREME_AMOUNT", message="high", severity=AnomalySeverity.CRITICAL),
            AnomalyFlag(code="UNRECOGNIZED_VENDOR", message="unknown", severity=AnomalySeverity.WARNING),
            AnomalyFlag(code="LINE_ITEM_MATH", message="math", severity=AnomalySeverity.WARNING),
        ]
        score = AnomalyDetectionEngine.compute_risk_score(flags)
        assert 0.0 < score <= 1.0
        assert score >= 0.40  # Critical gives at least 0.40

    def test_detection_service_unified_workflow(self):
        service = DetectionService()
        existing = [
            make_test_invoice(vendor="Amazon Web Services", amount=150.0, invoice_date="2026-08-01"),
        ]
        # Duplicate + unrecognized vendor
        candidate = make_test_invoice(
            vendor="Amazon Web Services",
            amount=150.0,
            invoice_date="2026-08-03",
        )
        enriched = service.run_detection(candidate, existing)
        assert enriched.is_duplicate is True
        assert enriched.risk_score > 0.0
