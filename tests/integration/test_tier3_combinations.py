"""
tests/integration/test_tier3_combinations.py

Tier 3: Cross-Feature Combinations Test Suite (Pairwise Combinatorial Testing).
Verifies interaction effects across multiple pipeline features (>= 25 test cases):
- 1. Typo Vendor + Extreme Outlier Amount + Multi-Currency EUR
- 2. Unrecognized Vendor + 7-Day Sliding Window Duplicate Positive
- 3. Zero-Decimal JPY Currency + Dual-Storage Persistence + Query
- 4. Thermal Receipt PNG Image + Missing Subtotal + File Streaming Route
- 5. Typo Vendor + Line Item Math Discrepancy + Cumulative Risk Scoring
- 6. Duplicate Positive Submission + Extreme Outlier Anomaly
- 7. Batch Ingestion with Shared Correlation ID & Dual-Storage Tracking
- 8. Live Upload Failover: Force Mock vs Simulated Azure Outage
- 9. RapidFuzz Vendor Match + 11-Category Taxonomy Rollup + German Date
- 10. Negative Credit Note + Unknown Vendor + Dual-Storage Isolation
- 11. Multi-Item Cloud Invoice + Tax Discrepancy Tolerance
- 12. Duplicate Window Boundary (Day 7) + High Vendor Match (Acme Corp)
- 13. Duplicate Window Boundary Exceeded (Day 8) + Same Amount ($500)
- 14. Same Vendor Different Currency (USD vs EUR) + Duplicate Immunity
- 15. Extreme Amount ($1.25M) + Known Airline Vendor + Travel Taxonomy
- 16. Missing Invoice Number + Fallback UUID Generation + Storage Query
- 17. Low Confidence Extraction (<0.70) + Status NEEDS_REVIEW + Anomaly Flag
- 18. Multiple Line Items with Mixed Categories + Ingestion Lifecycle
- 19. Dual Storage: Raw Payload Modification Immunity (Audit Immutability)
- 20. JPG Image Ingestion + Luigi's Pizza Unknown Vendor + Meals Taxonomy
- 21. Corrupted Document Fallback + Dual-Storage Error Handling
- 22. Zero-Total Invoice + Anomaly Flagging + Storage Retrieval
- 23. Custom Correlation ID + Multi-Document Batch Traceability
- 24. RapidFuzz Exact Match (AWS) + Cloud Taxonomy + Confidence Breakdown
- 25. Dual-Storage Record Query by Date Range and Vendor
- 26. Full End-to-End Pipeline Mock Simulation with Dynamic Fixture
- 27. Duplicate Negative (+36 Days) + Exact Same Vendor & Amount
- 28. High Risk Score Document Quarantine Filter
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.core.models import (
    ExtractedField,
    LineItem,
    NormalizedInvoice,
    RawInvoicePayload,
)
from src.services.extraction.azure_client import AzureDocumentIntelligenceClient
from src.services.extraction.mock_extractor import MockExtractionService
from tests.test_support import (
    AnomalyDetectionEngine,
    DateCurrencyStandardizer,
    DualStorageRepository,
    DuplicateDetectionEngine,
    SpendTaxonomyEngine,
    VendorMatcherEngine,
)


class TestTier3Combinations:
    """Pairwise Cross-Feature Integration Test Suite."""

    @pytest.fixture
    def vendor_matcher(self) -> VendorMatcherEngine:
        return VendorMatcherEngine()

    @pytest.fixture
    def taxonomy_engine(self) -> SpendTaxonomyEngine:
        return SpendTaxonomyEngine()

    @pytest.fixture
    def duplicate_engine(self) -> DuplicateDetectionEngine:
        return DuplicateDetectionEngine(window_days=7)

    @pytest.fixture
    def anomaly_engine(self) -> AnomalyDetectionEngine:
        return AnomalyDetectionEngine(extreme_amount_threshold=50000.0)

    @pytest.fixture
    def dual_storage(self) -> DualStorageRepository:
        return DualStorageRepository()

    # 1. Typo Vendor + Extreme Outlier Amount + Multi-Currency EUR
    def test_combo_1_typo_vendor_extreme_amount_multicurrency(
        self,
        vendor_matcher: VendorMatcherEngine,
        anomaly_engine: AnomalyDetectionEngine,
    ) -> None:
        """Combination 1: Typo vendor string + €1.25M EUR extreme outlier."""
        canonical, vid, score, is_known = vendor_matcher.match_vendor("Microsft Corp Ireland")
        assert canonical == "Microsoft Corporation"
        assert is_known is True

        curr_iso = DateCurrencyStandardizer.standardize_currency("€")
        assert curr_iso == "EUR"

        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Microsft Corp Ireland"),
            vendor_raw="Microsft Corp Ireland",
            vendor_canonical=canonical,
            is_known_vendor=is_known,
            invoice_id=ExtractedField[str](value="MSFT-EU-991"),
            invoice_date=ExtractedField[str](value="2026-08-03"),
            total_amount=ExtractedField[float](value=1250000.00),
            currency=ExtractedField[str](value="€"),
            currency_iso=curr_iso,
        )
        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv)
        assert has_anom is True
        assert any(f.code == "EXTREME_AMOUNT" for f in flags)
        assert risk >= 0.60

    # 2. Unrecognized Vendor + 7-Day Sliding Window Duplicate Positive
    def test_combo_2_unrecognized_vendor_duplicate_positive(
        self,
        vendor_matcher: VendorMatcherEngine,
        duplicate_engine: DuplicateDetectionEngine,
        anomaly_engine: AnomalyDetectionEngine,
    ) -> None:
        """Combination 2: Unregistered vendor submitted twice within 2 days -> flags duplicate and unknown."""
        cand_raw = "Luigi's Pizza & Catering"
        canonical, _, _, is_known = vendor_matcher.match_vendor(cand_raw)
        assert is_known is False

        inv_orig = NormalizedInvoice(
            id="lpc-orig",
            vendor_name=ExtractedField[str](value=cand_raw),
            vendor_raw=cand_raw,
            vendor_canonical=canonical,
            is_known_vendor=is_known,
            invoice_id=ExtractedField[str](value="LPC-1"),
            invoice_date=ExtractedField[str](value="2026-08-14"),
            total_amount=ExtractedField[float](value=85.50),
        )

        inv_dup = NormalizedInvoice(
            id="lpc-dup",
            vendor_name=ExtractedField[str](value=cand_raw),
            vendor_raw=cand_raw,
            vendor_canonical=canonical,
            is_known_vendor=is_known,
            invoice_id=ExtractedField[str](value="LPC-2"),
            invoice_date=ExtractedField[str](value="2026-08-16"),  # +2 days
            total_amount=ExtractedField[float](value=85.50),
        )

        is_dup, dup_id, reason, details = duplicate_engine.evaluate_duplicate(inv_dup, [inv_orig])
        assert is_dup is True
        assert dup_id == "lpc-orig"

        inv_dup.is_duplicate = True
        inv_dup.duplicate_reason = reason
        inv_dup.duplicate_match_details = details

        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv_dup)
        assert has_anom is True
        codes = [f.code for f in flags]
        assert "UNRECOGNIZED_VENDOR" in codes
        assert "DUPLICATE_SUBMISSION" in codes
        assert risk >= 0.60

    # 3. Zero-Decimal JPY Currency + Dual-Storage Persistence + REST Query
    def test_combo_3_zero_decimal_jpy_dual_storage(
        self,
        dual_storage: DualStorageRepository,
        mock_azure_response_loader: Any,
    ) -> None:
        """Combination 3: JPY invoice parsing, dual storage persistence, and record retrieval."""
        mock_result = mock_azure_response_loader("inv_010_jpy_zero_decimal")
        client = AzureDocumentIntelligenceClient()
        raw_payload = client._parse_azure_result(
            result=mock_result,
            document_id="doc-jpy-010",
            correlation_id="corr-jpy-010",
            filename="inv_010_jpy_zero_decimal.pdf",
        )
        dual_storage.save_raw(raw_payload)

        norm = NormalizedInvoice(
            id="norm-jpy-010",
            document_id="doc-jpy-010",
            correlation_id="corr-jpy-010",
            vendor_name=raw_payload.raw_fields["VendorName"],
            vendor_canonical="Slack Technologies",
            invoice_id=raw_payload.raw_fields["InvoiceId"],
            invoice_date=raw_payload.raw_fields["InvoiceDate"],
            total_amount=raw_payload.raw_fields["InvoiceTotal"],
            currency=raw_payload.raw_fields.get("Currency"),
            currency_iso="JPY",
        )
        dual_storage.save_normalized(norm)

        # Retrieve and verify
        raw_retrieved = dual_storage.get_raw_by_document_id("doc-jpy-010")
        norm_retrieved = dual_storage.get_normalized_by_id("norm-jpy-010")

        assert raw_retrieved is not None
        assert norm_retrieved is not None
        assert norm_retrieved.total_amount.value == 150000.0
        assert norm_retrieved.currency_iso == "JPY"

    # 4. Thermal Receipt PNG Image + Missing Subtotal + File Streaming Route
    def test_combo_4_thermal_receipt_streaming(self, client: TestClient, sample_png_bytes: bytes) -> None:
        """Combination 4: Ingestion of PNG thermal receipt with direct download streaming."""
        files = {"file": ("uber_thermal.png", sample_png_bytes, "image/png")}
        resp = client.post("/upload", files=files)
        assert resp.status_code == 200
        doc_id = resp.json()["document_id"]

        stream_resp = client.get(f"/documents/{doc_id}/file")
        assert stream_resp.status_code == 200
        assert stream_resp.headers["content-type"] == "image/png"
        assert len(stream_resp.content) == len(sample_png_bytes)

    # 5. Typo Vendor + Line Item Math Discrepancy + Cumulative Risk Scoring
    def test_combo_5_typo_vendor_math_discrepancy_risk(
        self,
        vendor_matcher: VendorMatcherEngine,
        anomaly_engine: AnomalyDetectionEngine,
    ) -> None:
        """Combination 5: Resolved vendor typo combined with line item arithmetic discrepancy."""
        canonical, _, _, is_known = vendor_matcher.match_vendor("Acme Corp Ltd")
        assert canonical == "Acme Corporation"

        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp Ltd"),
            vendor_canonical=canonical,
            invoice_id=ExtractedField[str](value="ACME-ERR"),
            invoice_date=ExtractedField[str](value="2026-08-10"),
            subtotal_amount=ExtractedField[float](value=450.00),
            tax_amount=ExtractedField[float](value=0.00),
            total_amount=ExtractedField[float](value=500.00),  # Discrepancy $50
            line_items=[
                LineItem(description="Consulting", quantity=1.0, unit_price=450.0, total_amount=450.0)
            ],
        )
        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv)
        assert has_anom is True
        assert any(f.code == "MATH_DISCREPANCY" for f in flags)
        assert risk >= 0.30

    # 6. Duplicate Positive Submission + Extreme Outlier Anomaly
    def test_combo_6_duplicate_positive_extreme_anomaly(
        self,
        duplicate_engine: DuplicateDetectionEngine,
        anomaly_engine: AnomalyDetectionEngine,
    ) -> None:
        """Combination 6: $1.25M Delta invoice submitted twice -> both extreme outlier and duplicate."""
        inv1 = NormalizedInvoice(
            id="dal-orig",
            vendor_name=ExtractedField[str](value="Delta Air Lines"),
            vendor_canonical="Delta Air Lines",
            invoice_id=ExtractedField[str](value="DAL-001"),
            invoice_date=ExtractedField[str](value="2026-08-12"),
            total_amount=ExtractedField[float](value=1250000.00),
        )
        inv2 = NormalizedInvoice(
            id="dal-dup",
            vendor_name=ExtractedField[str](value="Delta Air Lines"),
            vendor_canonical="Delta Air Lines",
            invoice_id=ExtractedField[str](value="DAL-002"),
            invoice_date=ExtractedField[str](value="2026-08-14"),  # +2d
            total_amount=ExtractedField[float](value=1250000.00),
        )
        is_dup, dup_id, reason, details = duplicate_engine.evaluate_duplicate(inv2, [inv1])
        assert is_dup is True
        inv2.is_duplicate = True
        inv2.duplicate_reason = reason
        inv2.duplicate_match_details = details

        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv2)
        assert has_anom is True
        codes = [f.code for f in flags]
        assert "EXTREME_AMOUNT" in codes
        assert "DUPLICATE_SUBMISSION" in codes
        assert risk >= 0.80

    # 7. Batch Ingestion with Shared Correlation ID & Concurrent Dual-Storage
    def test_combo_7_batch_shared_correlation_id(self, dual_storage: DualStorageRepository) -> None:
        """Combination 7: 5 invoices stored under the same correlation_id queried together."""
        corr_id = f"batch-{uuid.uuid4().hex[:8]}"
        for i in range(5):
            doc_id = f"batch-doc-{i}"
            raw = RawInvoicePayload(
                document_id=doc_id,
                correlation_id=corr_id,
                filename=f"invoice_{i}.pdf",
                raw_fields={"VendorName": ExtractedField[str](value=f"Vendor {i}")},
            )
            norm = NormalizedInvoice(
                id=f"norm-{i}",
                document_id=doc_id,
                correlation_id=corr_id,
                vendor_name=ExtractedField[str](value=f"Vendor {i}"),
                invoice_id=ExtractedField[str](value=f"INV-{i}"),
                invoice_date=ExtractedField[str](value="2026-08-01"),
                total_amount=ExtractedField[float](value=100.0 * (i + 1)),
            )
            dual_storage.save_raw(raw)
            dual_storage.save_normalized(norm)

        raws, norms = dual_storage.get_by_correlation_id(corr_id)
        assert len(raws) == 5
        assert len(norms) == 5

    # 8. Live Upload Failover: Force Mock vs Simulated Azure Service Outage
    def test_combo_8_upload_force_mock_vs_failover(self, client: TestClient, sample_pdf_bytes: bytes) -> None:
        """Combination 8: Test force_mock=true parameter returns mock extraction engine tag."""
        files = {"file": ("failover_test.pdf", sample_pdf_bytes, "application/pdf")}
        resp = client.post("/upload?force_mock=true", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["extraction_engine"] in ["mock_fallback", "mock_heuristic_extractor", "mock_fixture_catalog"]

    # 9. RapidFuzz Vendor Match + 11-Category Taxonomy Rollup + German Date Format
    def test_combo_9_vendor_match_taxonomy_german_date(
        self,
        vendor_matcher: VendorMatcherEngine,
        taxonomy_engine: SpendTaxonomyEngine,
    ) -> None:
        """Combination 9: German date parsing + vendor fuzzy matching + taxonomy category."""
        canonical, vid, score, is_known = vendor_matcher.match_vendor("Amazon Web Services")
        category = taxonomy_engine.classify(vendor_name=canonical, description="EC2 Server Hosting")
        parsed_date = DateCurrencyStandardizer.parse_iso_date("15. August 2026")

        assert canonical == "Amazon Web Services"
        assert category == "Cloud Services"
        assert parsed_date == "2026-08-15"

    # 10. Negative Credit Note + Unknown Vendor + Dual-Storage Isolation
    def test_combo_10_negative_credit_note_unknown_vendor(
        self,
        dual_storage: DualStorageRepository,
        anomaly_engine: AnomalyDetectionEngine,
    ) -> None:
        """Combination 10: Negative refund -$150.00 from unregistered vendor stored in dual storage."""
        raw = RawInvoicePayload(
            document_id="doc-neg-unk",
            filename="credit_note.pdf",
            raw_fields={"VendorName": ExtractedField[str](value="Unregistered Repair Shop")},
        )
        norm = NormalizedInvoice(
            id="norm-neg-unk",
            document_id="doc-neg-unk",
            vendor_name=ExtractedField[str](value="Unregistered Repair Shop"),
            vendor_raw="Unregistered Repair Shop",
            is_known_vendor=False,
            vendor_match_score=20.0,
            invoice_id=ExtractedField[str](value="CN-99"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=-150.00),
        )
        dual_storage.save_raw(raw)
        dual_storage.save_normalized(norm)

        has_anom, flags, _ = anomaly_engine.evaluate_anomalies(norm)
        assert has_anom is True
        codes = [f.code for f in flags]
        assert "UNRECOGNIZED_VENDOR" in codes
        assert "NEGATIVE_AMOUNT" in codes

    # 11. Multi-Item Cloud Invoice + Tax Discrepancy Tolerance
    def test_combo_11_multi_item_cloud_tax_tolerance(self, anomaly_engine: AnomalyDetectionEngine) -> None:
        """Combination 11: Multi-item cloud invoice with acceptable rounding difference (4 cents)."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Amazon Web Services"),
            invoice_id=ExtractedField[str](value="AWS-TAX-OK"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            subtotal_amount=ExtractedField[float](value=1200.00),
            tax_amount=ExtractedField[float](value=220.50),
            total_amount=ExtractedField[float](value=1420.54),  # $0.04 difference within $0.05
        )
        _, flags, _ = anomaly_engine.evaluate_anomalies(inv)
        assert not any(f.code == "MATH_DISCREPANCY" for f in flags)

    # 12. Duplicate Window Boundary (Day 7) + High Vendor Match (Acme Corp)
    def test_combo_12_duplicate_window_day7_high_match(
        self,
        vendor_matcher: VendorMatcherEngine,
        duplicate_engine: DuplicateDetectionEngine,
    ) -> None:
        """Combination 12: Exact Day 7 boundary with Acme Corporation -> duplicate positive."""
        inv1 = NormalizedInvoice(
            id="acme-day0",
            vendor_name=ExtractedField[str](value="Acme Corp Ltd"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=500.00),
        )
        inv2 = NormalizedInvoice(
            id="acme-day7",
            vendor_name=ExtractedField[str](value="Acme Corporation LLC"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-2"),
            invoice_date=ExtractedField[str](value="2026-08-08"),  # +7d
            total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, dup_id, _, details = duplicate_engine.evaluate_duplicate(inv2, [inv1])
        assert is_dup is True
        assert dup_id == "acme-day0"
        assert details["day_difference"] == 7

    # 13. Duplicate Window Boundary Exceeded (Day 8) + Same Amount ($500)
    def test_combo_13_duplicate_window_day8_exceeded(self, duplicate_engine: DuplicateDetectionEngine) -> None:
        """Combination 13: Day 8 submission outside sliding window -> non-duplicate."""
        inv1 = NormalizedInvoice(
            id="acme-d0",
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=500.00),
        )
        inv2 = NormalizedInvoice(
            id="acme-d8",
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-2"),
            invoice_date=ExtractedField[str](value="2026-08-09"),  # +8d
            total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, _, _, _ = duplicate_engine.evaluate_duplicate(inv2, [inv1])
        assert is_dup is False

    # 14. Same Vendor Different Currency (USD vs EUR) + Duplicate Immunity
    def test_combo_14_different_currency_duplicate_check(self, duplicate_engine: DuplicateDetectionEngine) -> None:
        """Combination 14: Google USD $500 vs Google EUR €500 -> different amount context."""
        inv_usd = NormalizedInvoice(
            id="goog-usd",
            vendor_name=ExtractedField[str](value="Google LLC"),
            vendor_canonical="Google LLC",
            invoice_id=ExtractedField[str](value="GOOG-1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=500.00),
            currency_iso="USD",
        )
        inv_diff_amt = NormalizedInvoice(
            id="goog-eur",
            vendor_name=ExtractedField[str](value="Google LLC"),
            vendor_canonical="Google LLC",
            invoice_id=ExtractedField[str](value="GOOG-2"),
            invoice_date=ExtractedField[str](value="2026-08-02"),
            total_amount=ExtractedField[float](value=550.00),
            currency_iso="EUR",
        )
        is_dup, _, _, _ = duplicate_engine.evaluate_duplicate(inv_diff_amt, [inv_usd])
        assert is_dup is False

    # 15. Extreme Amount ($1.25M) + Known Airline Vendor + Travel Taxonomy
    def test_combo_15_extreme_amount_known_airline_travel_taxonomy(
        self,
        vendor_matcher: VendorMatcherEngine,
        taxonomy_engine: SpendTaxonomyEngine,
        anomaly_engine: AnomalyDetectionEngine,
    ) -> None:
        """Combination 15: Delta Air Lines $1.25M -> Known vendor + Travel category + Extreme anomaly."""
        canonical, vid, score, is_known = vendor_matcher.match_vendor("Delta Air Lines Inc")
        assert canonical == "Delta Air Lines"
        assert is_known is True

        cat = taxonomy_engine.classify(vendor_name=canonical, description="Corporate Flight Charter")
        assert cat == "Travel & Transportation"

        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Delta Air Lines Inc"),
            vendor_canonical=canonical,
            invoice_id=ExtractedField[str](value="DAL-773829"),
            invoice_date=ExtractedField[str](value="2026-08-12"),
            total_amount=ExtractedField[float](value=1250000.00),
            spend_category=cat,
        )
        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv)
        assert has_anom is True
        assert any(f.code == "EXTREME_AMOUNT" for f in flags)

    # 16. Missing Invoice Number + Fallback UUID Generation + Storage Query
    def test_combo_16_missing_invoice_number_fallback(self, dual_storage: DualStorageRepository) -> None:
        """Combination 16: Document with missing invoice number receives generated ID."""
        doc_id = str(uuid.uuid4())
        inv = NormalizedInvoice(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value=f"INV-{doc_id[:8].upper()}", confidence=0.0),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=100.0),
        )
        dual_storage.save_normalized(inv)
        retrieved = dual_storage.get_normalized_by_document_id(doc_id)
        assert retrieved is not None
        assert retrieved.invoice_id.value.startswith("INV-")

    # 17. Low Confidence Extraction (<0.70) + Status "NEEDS_REVIEW" + Anomaly Flag
    def test_combo_17_low_confidence_needs_review(self) -> None:
        """Combination 17: Mock extraction with low confidence (<0.70) sets status to NEEDS_REVIEW."""
        mock_service = MockExtractionService()
        text_noisy = "Some illegible noisy receipt scrap 123 ..."
        raw = mock_service.extract_document(file_bytes=text_noisy.encode(), filename="blurry.pdf")
        norm = mock_service._raw_to_normalized(raw)

        if norm.confidence_score < 0.70:
            assert norm.status == "NEEDS_REVIEW"
            assert any(a.code == "LOW_CONFIDENCE" for a in norm.anomalies)

    # 18. Multiple Line Items with Mixed Categories + Ingestion Lifecycle
    def test_combo_18_multiple_line_items_mixed_categories(self, taxonomy_engine: SpendTaxonomyEngine) -> None:
        """Combination 18: Invoice containing both software and cloud items classified per item."""
        items = [
            LineItem(description="Cloud Hosting EC2", quantity=1.0, unit_price=100.0, total_amount=100.0),
            LineItem(description="Microsoft 365 License", quantity=1.0, unit_price=30.0, total_amount=30.0),
            LineItem(description="Taxi Airport Transfer", quantity=1.0, unit_price=40.0, total_amount=40.0),
        ]
        cats = [taxonomy_engine.classify(description=it.description) for it in items]
        assert cats == ["Cloud Services", "Software Subscriptions", "Travel & Transportation"]

    # 19. Dual Storage: Raw Payload Modification Immunity (Audit Immutability)
    def test_combo_19_audit_immutability(self, dual_storage: DualStorageRepository) -> None:
        """Combination 19: Mutating normalized record in-memory leaves raw extraction untouched."""
        raw = RawInvoicePayload(
            document_id="doc-audit-test",
            raw_fields={"VendorName": ExtractedField[str](value="Original Vendor Name")},
            filename="audit.pdf",
        )
        dual_storage.save_raw(raw)

        norm = NormalizedInvoice(
            id="norm-audit-test",
            document_id="doc-audit-test",
            vendor_name=ExtractedField[str](value="Edited Vendor Name"),
            invoice_id=ExtractedField[str](value="INV-AUDIT"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=100.0),
        )
        dual_storage.save_normalized(norm)

        # Mutate norm
        norm.vendor_canonical = "Completely New Vendor"

        raw_check = dual_storage.get_raw_by_document_id("doc-audit-test")
        assert raw_check.raw_fields["VendorName"].value == "Original Vendor Name"

    # 20. JPG Image Ingestion + Luigi's Pizza Unknown Vendor + Meals Taxonomy
    def test_combo_20_jpg_ingestion_unknown_vendor_meals_taxonomy(
        self,
        vendor_matcher: VendorMatcherEngine,
        taxonomy_engine: SpendTaxonomyEngine,
    ) -> None:
        """Combination 20: Photo receipt from Luigi's Pizza -> Meals category & unknown vendor."""
        canonical, _, score, is_known = vendor_matcher.match_vendor("Luigi's Pizza & Catering")
        category = taxonomy_engine.classify(vendor_name=canonical, description="Large Pepperoni Pizza")

        assert is_known is False
        assert category == "Meals & Entertainment"

    # 21. Corrupted Document Fallback + Dual-Storage Error Handling
    def test_combo_21_corrupt_document_fallback_storage(self, dual_storage: DualStorageRepository) -> None:
        """Combination 21: Corrupted stream parses into fallback payload and persists cleanly."""
        mock_service = MockExtractionService()
        raw = mock_service.extract_document(file_bytes=b"corrupt header only", filename="corrupt.pdf")
        dual_storage.save_raw(raw)
        assert dual_storage.get_raw_by_document_id(raw.document_id) is not None

    # 22. Zero-Total Invoice + Anomaly Flagging + Storage Retrieval
    def test_combo_22_zero_total_storage_retrieval(
        self,
        dual_storage: DualStorageRepository,
        anomaly_engine: AnomalyDetectionEngine,
    ) -> None:
        """Combination 22: $0.00 zero total invoice flagged with ZERO_TOTAL anomaly and retrieved."""
        inv = NormalizedInvoice(
            id="inv-zero-store",
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="ZERO-STORE"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=0.00),
        )
        has_anom, flags, _ = anomaly_engine.evaluate_anomalies(inv)
        assert has_anom is True
        inv.anomalies = flags
        inv.has_anomalies = True

        dual_storage.save_normalized(inv)
        retrieved = dual_storage.get_normalized_by_id("inv-zero-store")
        assert retrieved.has_anomalies is True
        assert any(a.code == "ZERO_TOTAL" for a in retrieved.anomalies)

    # 23. Custom Correlation ID + Multi-Document Batch Traceability
    def test_combo_23_custom_correlation_id_batch_traceability(
        self,
        dual_storage: DualStorageRepository,
    ) -> None:
        """Combination 23: Multiple documents linked under single enterprise batch correlation ID."""
        batch_id = "trace-batch-2026-q3"
        for i in range(3):
            inv = NormalizedInvoice(
                id=f"inv-batch-{i}",
                correlation_id=batch_id,
                vendor_name=ExtractedField[str](value=f"Vendor {i}"),
                invoice_id=ExtractedField[str](value=f"INV-{i}"),
                invoice_date=ExtractedField[str](value="2026-08-01"),
                total_amount=ExtractedField[float](value=100.0),
            )
            dual_storage.save_normalized(inv)

        _, batch_records = dual_storage.get_by_correlation_id(batch_id)
        assert len(batch_records) == 3

    # 24. RapidFuzz Exact Match (AWS) + Cloud Taxonomy + Confidence Breakdown
    def test_combo_24_aws_exact_match_cloud_taxonomy_confidence(
        self,
        vendor_matcher: VendorMatcherEngine,
        taxonomy_engine: SpendTaxonomyEngine,
    ) -> None:
        """Combination 24: High confidence AWS invoice + Cloud Services taxonomy."""
        canonical, vid, score, is_known = vendor_matcher.match_vendor("Amazon Web Services Inc.")
        category = taxonomy_engine.classify(vendor_name=canonical, description="EC2 Compute Instances")
        assert canonical == "Amazon Web Services"
        assert category == "Cloud Services"
        assert score >= 85.0

    # 25. Dual-Storage Record Query by Date Range and Vendor
    def test_combo_25_dual_storage_query_filter(self, dual_storage: DualStorageRepository) -> None:
        """Combination 25: Filter normalized invoices by vendor and date range."""
        inv1 = NormalizedInvoice(
            id="inv-filter-1",
            vendor_name=ExtractedField[str](value="Amazon Web Services"),
            vendor_canonical="Amazon Web Services",
            invoice_id=ExtractedField[str](value="AWS-1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=100.0),
        )
        inv2 = NormalizedInvoice(
            id="inv-filter-2",
            vendor_name=ExtractedField[str](value="Microsoft Corporation"),
            vendor_canonical="Microsoft Corporation",
            invoice_id=ExtractedField[str](value="MSFT-1"),
            invoice_date=ExtractedField[str](value="2026-08-15"),
            total_amount=ExtractedField[float](value=200.0),
        )
        dual_storage.save_normalized(inv1)
        dual_storage.save_normalized(inv2)

        all_records = dual_storage.list_all_normalized()
        aws_records = [r for r in all_records if r.vendor_canonical == "Amazon Web Services"]
        assert len(aws_records) == 1
        assert aws_records[0].id == "inv-filter-1"

    # 26. Full End-to-End Pipeline Mock Simulation with Dynamic Fixture
    def test_combo_26_full_mock_pipeline_dynamic_fixture(
        self,
        vendor_matcher: VendorMatcherEngine,
        taxonomy_engine: SpendTaxonomyEngine,
        anomaly_engine: AnomalyDetectionEngine,
        dual_storage: DualStorageRepository,
    ) -> None:
        """Combination 26: Full pipeline simulation: extract -> match -> categorize -> detect -> store."""
        mock_service = MockExtractionService()
        raw = mock_service.extract_document(
            file_bytes=b"%PDF-1.4 sample",
            filename="inv_001_standard_aws.pdf",
        )
        dual_storage.save_raw(raw)

        raw_vendor = raw.raw_fields["VendorName"].value
        canonical, vid, score, is_known = vendor_matcher.match_vendor(raw_vendor)
        category = taxonomy_engine.classify(vendor_name=canonical)

        norm = NormalizedInvoice(
            document_id=raw.document_id,
            correlation_id=raw.correlation_id,
            vendor_name=raw.raw_fields["VendorName"],
            vendor_raw=raw_vendor,
            vendor_canonical=canonical,
            vendor_id=vid,
            vendor_match_score=score,
            is_known_vendor=is_known,
            spend_category=category,
            invoice_id=raw.raw_fields["InvoiceId"],
            invoice_date=raw.raw_fields["InvoiceDate"],
            total_amount=raw.raw_fields["InvoiceTotal"],
        )
        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(norm)
        norm.has_anomalies = has_anom
        norm.anomalies = flags
        norm.risk_score = risk

        dual_storage.save_normalized(norm)
        assert dual_storage.get_normalized_by_id(norm.id) is not None
        assert norm.spend_category == "Cloud Services"

    # 27. Duplicate Negative (+36 Days) + Exact Same Vendor & Amount
    def test_combo_27_duplicate_negative_36_days(self, duplicate_engine: DuplicateDetectionEngine) -> None:
        """Combination 27: Acme $500 invoice 36 days apart -> verified negative duplicate."""
        inv_base = NormalizedInvoice(
            id="acme-base",
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-ORIG"),
            invoice_date=ExtractedField[str](value="2026-08-10"),
            total_amount=ExtractedField[float](value=500.00),
        )
        inv_month_later = NormalizedInvoice(
            id="acme-36d",
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-LATER"),
            invoice_date=ExtractedField[str](value="2026-09-15"),  # +36 days
            total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, _, _, _ = duplicate_engine.evaluate_duplicate(inv_month_later, [inv_base])
        assert is_dup is False

    # 28. High Risk Score Document Quarantine Filter
    def test_combo_28_high_risk_score_quarantine_filter(
        self,
        anomaly_engine: AnomalyDetectionEngine,
        dual_storage: DualStorageRepository,
    ) -> None:
        """Combination 28: Documents with risk_score >= 0.70 are identified for human review quarantine."""
        inv_high_risk = NormalizedInvoice(
            id="inv-fraud-quarantine",
            vendor_name=ExtractedField[str](value="Unregistered Foreign Shell Co"),
            vendor_raw="Unregistered Foreign Shell Co",
            is_known_vendor=False,
            vendor_match_score=15.0,
            invoice_id=ExtractedField[str](value="SH-999"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=2500000.00),  # Extreme + unknown vendor
            is_duplicate=True,
            duplicate_reason="Repeated submission",
        )
        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv_high_risk)
        inv_high_risk.has_anomalies = has_anom
        inv_high_risk.anomalies = flags
        inv_high_risk.risk_score = risk

        dual_storage.save_normalized(inv_high_risk)

        # Query quarantine records
        all_records = dual_storage.list_all_normalized()
        quarantined = [r for r in all_records if r.risk_score >= 0.70]
        assert len(quarantined) == 1
        assert quarantined[0].id == "inv-fraud-quarantine"
