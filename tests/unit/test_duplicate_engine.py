"""
tests/unit/test_duplicate_engine.py

Unit tests for 7-Day Sliding Window Duplicate Detection Engine.
"""

import uuid
from datetime import datetime, timedelta, UTC
import pytest

from src.core.models import ExtractedField, NormalizedInvoice, LineItem
from src.services.detection.duplicate_engine import DuplicateDetectionEngine


def create_invoice(
    vendor: str = "Amazon Web Services",
    amount: float = 1000.0,
    invoice_date: str = "2026-08-01",
    invoice_id: str = "INV-001",
    currency: str = "USD",
    doc_id: str | None = None,
) -> NormalizedInvoice:
    """Helper to construct NormalizedInvoice models for testing."""
    d_id = doc_id or str(uuid.uuid4())
    return NormalizedInvoice(
        id=str(uuid.uuid4()),
        document_id=d_id,
        correlation_id=str(uuid.uuid4()),
        vendor_name=ExtractedField(value=vendor, confidence=0.98),
        vendor_canonical=vendor,
        invoice_id=ExtractedField(value=invoice_id, confidence=0.95),
        invoice_date=ExtractedField(value=invoice_date, confidence=0.99),
        total_amount=ExtractedField(value=amount, confidence=0.99),
        currency=ExtractedField(value=currency, confidence=1.0),
        currency_iso=currency,
        line_items=[],
    )


class TestDuplicateDetectionEngine:
    """Test suite for DuplicateDetectionEngine."""

    def test_no_duplicates_on_empty_corpus(self):
        engine = DuplicateDetectionEngine(window_days=7)
        inv = create_invoice()
        is_dup, dup_of, details = engine.check_duplicate(inv, [])
        assert is_dup is False
        assert dup_of is None
        assert details is None

    def test_exact_duplicate_same_vendor_amount_date(self):
        engine = DuplicateDetectionEngine(window_days=7)
        original = create_invoice(vendor="Microsoft Corporation", amount=450.0, invoice_date="2026-08-10", invoice_id="MS-100")
        candidate = create_invoice(vendor="Microsoft Corporation", amount=450.0, invoice_date="2026-08-10", invoice_id="MS-200")

        is_dup, dup_of, details = engine.check_duplicate(candidate, [original])
        assert is_dup is True
        assert dup_of == original.id
        assert details is not None
        assert details["matching_vendor"] == "microsoft corporation"

    def test_duplicate_within_7_day_window(self):
        engine = DuplicateDetectionEngine(window_days=7)
        original = create_invoice(vendor="Amazon Web Services", amount=1200.0, invoice_date="2026-08-01")
        # 5 days later
        candidate = create_invoice(vendor="Amazon Web Services", amount=1200.0, invoice_date="2026-08-06")

        is_dup, dup_of, details = engine.check_duplicate(candidate, [original])
        assert is_dup is True
        assert dup_of == original.id

    def test_no_duplicate_outside_7_day_window(self):
        engine = DuplicateDetectionEngine(window_days=7)
        original = create_invoice(vendor="Amazon Web Services", amount=1200.0, invoice_date="2026-08-01")
        # 10 days later (outside 7-day window)
        candidate = create_invoice(vendor="Amazon Web Services", amount=1200.0, invoice_date="2026-08-11", invoice_id="DIFF-INV")

        is_dup, dup_of, _ = engine.check_duplicate(candidate, [original])
        assert is_dup is False
        assert dup_of is None

    def test_duplicate_secondary_match_same_invoice_id_across_any_date(self):
        engine = DuplicateDetectionEngine(window_days=7)
        original = create_invoice(vendor="Google LLC", amount=300.0, invoice_date="2026-01-01", invoice_id="GCP-EXACT-001")
        # 60 days later, but identical invoice ID
        candidate = create_invoice(vendor="Google LLC", amount=300.0, invoice_date="2026-03-01", invoice_id="GCP-EXACT-001")

        is_dup, dup_of, details = engine.check_duplicate(candidate, [original])
        assert is_dup is True
        assert dup_of == original.id
        assert details["match_type"] == "exact_invoice_id"

    def test_no_duplicate_different_vendors_same_amount(self):
        engine = DuplicateDetectionEngine(window_days=7)
        original = create_invoice(vendor="Amazon Web Services", amount=500.0, invoice_date="2026-08-01")
        candidate = create_invoice(vendor="Microsoft Corporation", amount=500.0, invoice_date="2026-08-01")

        is_dup, _, _ = engine.check_duplicate(candidate, [original])
        assert is_dup is False

    def test_no_duplicate_same_vendor_different_amount(self):
        engine = DuplicateDetectionEngine(window_days=7)
        original = create_invoice(vendor="Slack Technologies", amount=200.0, invoice_date="2026-08-01")
        candidate = create_invoice(vendor="Slack Technologies", amount=800.0, invoice_date="2026-08-01", invoice_id="SLACK-02")

        is_dup, _, _ = engine.check_duplicate(candidate, [original])
        assert is_dup is False

    def test_enrich_with_duplicate_flags_mutates_model(self):
        engine = DuplicateDetectionEngine(window_days=7)
        original = create_invoice(vendor="Acme Corporation", amount=150.0, invoice_date="2026-08-01")
        candidate = create_invoice(vendor="Acme Corporation", amount=150.0, invoice_date="2026-08-03")

        enriched = engine.enrich_with_duplicate_flags(candidate, [original])
        assert enriched.is_duplicate is True
        assert enriched.duplicate_of_id == original.id
        assert enriched.status == "NEEDS_REVIEW"
        assert any(flag.code == "DUPLICATE_SUBMISSION" for flag in enriched.anomalies)
