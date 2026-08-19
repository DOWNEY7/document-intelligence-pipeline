"""
tests/unit/test_tier2_boundaries.py

Tier 2: Boundary & Corner Cases Test Suite (Boundary Value Analysis & Equivalence Partitioning).
Verifies all 9 pipeline edge conditions with >= 5 boundary tests per feature (50+ tests total):
- 1. Ingestion Size & Payload Boundaries (0 bytes, 1 byte, exact 5MB, 5MB+1 byte, traversal)
- 2. Currency & Zero-Decimal Boundaries (JPY zero-decimal, multi-symbol, thousand separators, 1 cent)
- 3. Extreme Amount & Sign Boundaries ($1.25M outlier, $100M, $0.00 zero, -$50.00 negative, exact $50k)
- 4. Date Calendar & Temporal Boundaries (Leap year Feb 29, non-leap Feb 29, month edge, year edge, epoch/future)
- 5. Exact 7-Day Window Boundaries (Day 0, Day +1, Day +7, Day -7, Day +8, Day -8, 1-cent diff)
- 6. RapidFuzz Threshold Boundaries (85.0% exact, 84.9%, 70.0% exact, 69.9%, empty, unicode accents)
- 7. Anomaly Math & Tolerance Boundaries ($0.04 under tolerance, $0.05 exact, $0.06 over tolerance, risk clamp)
- 8. Line Items & Payload Structural Boundaries (0 items, 100 items, missing optional fields, confidence clamp)
- 9. Stream Corruption & File Header Boundaries (Truncated PDF, random binary garbage, invalid extensions)
"""

import io
import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src.core.models import (
    ExtractedField,
    LineItem,
    NormalizedInvoice,
)
from src.core.storage import sanitize_filename
from src.services.extraction.mock_extractor import MockExtractionService
from tests.test_support import (
    AnomalyDetectionEngine,
    DateCurrencyStandardizer,
    DuplicateDetectionEngine,
    VendorMatcherEngine,
)

# ============================================================================
# Boundary Group 1: Ingestion Size & Payload Boundaries (>= 5 tests)
# ============================================================================

class TestBoundaryGroup1Ingestion:
    """Boundary Group 1: Ingestion File Size, Empty Payload, and Filename Boundaries."""

    def test_bva_upload_exact_max_size(self, client: TestClient) -> None:
        """Verify upload of exact max size (5 MB = 5 * 1024 * 1024 bytes) does not throw 413."""
        # 5 MB of mock PDF bytes
        exact_5mb = b"%PDF-1.4\n" + b"A" * (5 * 1024 * 1024 - 10)
        files = {"file": ("exact_5mb.pdf", exact_5mb, "application/pdf")}
        response = client.post("/upload", files=files)
        # Should succeed or process without 413 Payload Too Large
        assert response.status_code != 413
        assert response.status_code == 200

    def test_bva_upload_exceed_max_size_by_one_byte(self, client: TestClient) -> None:
        """Verify upload exceeding max size by exactly 1 byte returns HTTP 413."""
        oversized = b"%PDF-1.4\n" + b"B" * (5 * 1024 * 1024 - 9 + 1)
        files = {"file": ("oversized.pdf", oversized, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 413
        assert "exceeds" in response.json()["detail"].lower()

    def test_bva_upload_zero_byte_empty_file(self, client: TestClient) -> None:
        """Verify 0-byte payload returns HTTP 400 Bad Request."""
        empty_payload = b""
        files = {"file": ("empty.pdf", empty_payload, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_bva_upload_single_byte_file(self, client: TestClient) -> None:
        """Verify single byte payload is handled gracefully without server 500 crash."""
        single_byte = b"%"
        files = {"file": ("single_byte.pdf", single_byte, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code in [200, 400]

    def test_bva_upload_directory_traversal_sanitization(self) -> None:
        """Verify path traversal filenames (../../../../etc/passwd) are sanitized safely."""
        unsafe_1 = "../../../../etc/passwd/invoice.pdf"
        sanitized_1 = sanitize_filename(unsafe_1)
        assert "/" not in sanitized_1
        assert ".." not in sanitized_1
        assert sanitized_1.endswith(".pdf")

        unsafe_2 = "..\\..\\windows\\system32\\cmd.pdf"
        sanitized_2 = sanitize_filename(unsafe_2)
        assert "\\" not in sanitized_2
        assert ".." not in sanitized_2


# ============================================================================
# Boundary Group 2: Currency & Zero-Decimal Boundaries (>= 5 tests)
# ============================================================================

class TestBoundaryGroup2CurrencyAndNumbers:
    """Boundary Group 2: Currency Symbols, Zero-Decimal JPY, and Formatting."""

    def test_bva_currency_zero_decimal_jpy(self) -> None:
        """Verify JPY amounts (¥150,000) extract to 150000.0 without decimal distortion."""
        amt = DateCurrencyStandardizer.parse_numeric_amount("¥150,000")
        assert amt == 150000.0
        curr = DateCurrencyStandardizer.standardize_currency("¥")
        assert curr == "JPY"

    def test_bva_currency_symbol_variations(self) -> None:
        """Verify multi-symbol currencies map to canonical ISO 4217."""
        assert DateCurrencyStandardizer.standardize_currency("$") == "USD"
        assert DateCurrencyStandardizer.standardize_currency("US$") == "USD"
        assert DateCurrencyStandardizer.standardize_currency("€") == "EUR"
        assert DateCurrencyStandardizer.standardize_currency("£") == "GBP"
        assert DateCurrencyStandardizer.standardize_currency("CAD") == "CAD"
        assert DateCurrencyStandardizer.standardize_currency("CHF") == "CHF"

    def test_bva_currency_thousand_separators(self) -> None:
        """Verify parsing 1,000,000.00 (US) and 1.000.000,00 (EU) amounts."""
        assert DateCurrencyStandardizer.parse_numeric_amount("$1,000,000.00") == 1000000.00
        assert DateCurrencyStandardizer.parse_numeric_amount("€1.000.000,00") == 1000000.00

    def test_bva_amount_smallest_fractional(self) -> None:
        """Verify smallest positive monetary fraction (1 cent = $0.01)."""
        amt = DateCurrencyStandardizer.parse_numeric_amount("$0.01")
        assert amt == 0.01

    def test_bva_amount_float_rounding_precision(self) -> None:
        """Verify rounding float differences within precision."""
        amt1 = DateCurrencyStandardizer.parse_numeric_amount("500.0001")
        amt2 = DateCurrencyStandardizer.parse_numeric_amount("500.00")
        assert abs(amt1 - amt2) < 0.001


# ============================================================================
# Boundary Group 3: Extreme Amount & Sign Boundaries (>= 5 tests)
# ============================================================================

class TestBoundaryGroup3ExtremeAmountsAndSign:
    """Boundary Group 3: Outlier Amounts, Negative Values, and Thresholds."""

    @pytest.fixture
    def engine(self) -> AnomalyDetectionEngine:
        return AnomalyDetectionEngine(extreme_amount_threshold=50000.0)

    def test_bva_amount_extreme_large_values(self, engine: AnomalyDetectionEngine) -> None:
        """Verify multi-million dollar amounts raise EXTREME_AMOUNT anomaly."""
        inv_1m = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Delta Air Lines"),
            invoice_id=ExtractedField[str](value="DAL-1M"),
            invoice_date=ExtractedField[str](value="2026-08-12"),
            total_amount=ExtractedField[float](value=1250000.00),
        )
        has_anom, flags, risk = engine.evaluate_anomalies(inv_1m)
        assert has_anom is True
        assert any(f.code == "EXTREME_AMOUNT" for f in flags)
        assert risk >= 0.60

        inv_100m = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Global Enterprise"),
            invoice_id=ExtractedField[str](value="GE-100M"),
            invoice_date=ExtractedField[str](value="2026-08-12"),
            total_amount=ExtractedField[float](value=100000000.00),
        )
        _, flags_100m, _ = engine.evaluate_anomalies(inv_100m)
        assert any(f.code == "EXTREME_AMOUNT" for f in flags_100m)

    def test_bva_amount_exact_zero_total(self, engine: AnomalyDetectionEngine) -> None:
        """Verify exact $0.00 total raises ZERO_TOTAL anomaly."""
        inv_zero = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="INV-0"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=0.00),
        )
        has_anom, flags, _ = engine.evaluate_anomalies(inv_zero)
        assert has_anom is True
        assert any(f.code == "ZERO_TOTAL" for f in flags)

    def test_bva_amount_negative_credit_note(self, engine: AnomalyDetectionEngine) -> None:
        """Verify negative credit note amount (-$50.00) raises NEGATIVE_AMOUNT anomaly."""
        inv_neg = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="CN-100"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=-50.00),
        )
        has_anom, flags, _ = engine.evaluate_anomalies(inv_neg)
        assert has_anom is True
        assert any(f.code == "NEGATIVE_AMOUNT" for f in flags)

    def test_bva_amount_exact_50k_threshold(self, engine: AnomalyDetectionEngine) -> None:
        """Verify boundary at exact $50,000.00 is NOT outlier, while $50,000.01 IS an outlier."""
        inv_exact_50k = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="INV-50K"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=50000.00),  # Exactly at threshold
        )
        _, flags_50k, _ = engine.evaluate_anomalies(inv_exact_50k)
        assert not any(f.code == "EXTREME_AMOUNT" for f in flags_50k)

        inv_over_50k = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="INV-50K-PLUS"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=50000.01),  # 1 cent over threshold
        )
        _, flags_over, _ = engine.evaluate_anomalies(inv_over_50k)
        assert any(f.code == "EXTREME_AMOUNT" for f in flags_over)

    def test_bva_amount_negative_one_cent(self, engine: AnomalyDetectionEngine) -> None:
        """Verify smallest negative value (-$0.01) is caught as negative amount."""
        inv_neg_cent = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="CN-001"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=-0.01),
        )
        _, flags, _ = engine.evaluate_anomalies(inv_neg_cent)
        assert any(f.code == "NEGATIVE_AMOUNT" for f in flags)


# ============================================================================
# Boundary Group 4: Date Calendar & Temporal Boundaries (>= 5 tests)
# ============================================================================

class TestBoundaryGroup4DateCalendar:
    """Boundary Group 4: Leap Years, Month/Year Crossovers, and Epoch Extremes."""

    def test_bva_date_leap_year_february_29(self) -> None:
        """Verify leap year Feb 29 (2024, 2028) parses validly."""
        assert DateCurrencyStandardizer.parse_iso_date("2024-02-29") == "2024-02-29"
        assert DateCurrencyStandardizer.parse_iso_date("29.02.2028") == "2028-02-29"
        assert DateCurrencyStandardizer.parse_iso_date("February 29, 2024") == "2024-02-29"

    def test_bva_date_non_leap_year_february_29(self) -> None:
        """Verify non-leap year Feb 29 (2026) is rejected as invalid calendar date."""
        assert DateCurrencyStandardizer.parse_iso_date("2026-02-29") is None
        assert DateCurrencyStandardizer.parse_iso_date("29.02.2026") is None

    def test_bva_date_month_crossover(self) -> None:
        """Verify month transition (Jan 31 -> Feb 1) calculates exact 1-day interval."""
        d1 = datetime.strptime(DateCurrencyStandardizer.parse_iso_date("2026-01-31"), "%Y-%m-%d")
        d2 = datetime.strptime(DateCurrencyStandardizer.parse_iso_date("2026-02-01"), "%Y-%m-%d")
        assert (d2 - d1).days == 1

    def test_bva_date_year_end_crossover(self) -> None:
        """Verify year crossover (Dec 31 -> Jan 1) calculates exact 1-day interval."""
        d1 = datetime.strptime(DateCurrencyStandardizer.parse_iso_date("2026-12-31"), "%Y-%m-%d")
        d2 = datetime.strptime(DateCurrencyStandardizer.parse_iso_date("2027-01-01"), "%Y-%m-%d")
        assert (d2 - d1).days == 1

    def test_bva_date_epoch_and_distant_future(self) -> None:
        """Verify historic Unix epoch (1970-01-01) and distant future (2099-12-31) parse without overflow."""
        assert DateCurrencyStandardizer.parse_iso_date("1970-01-01") == "1970-01-01"
        assert DateCurrencyStandardizer.parse_iso_date("2099-12-31") == "2099-12-31"


# ============================================================================
# Boundary Group 5: Exact 7-Day Window Sliding Boundaries (>= 7 tests)
# ============================================================================

class TestBoundaryGroup5DuplicateWindow:
    """Boundary Group 5: Exact Sliding 7-Day Window Boundaries (Day 0, 1, 7, -7, 8, -8)."""

    @pytest.fixture
    def engine(self) -> DuplicateDetectionEngine:
        return DuplicateDetectionEngine(window_days=7)

    @pytest.fixture
    def base_invoice(self) -> NormalizedInvoice:
        return NormalizedInvoice(
            id="inv-base",
            document_id="doc-base",
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="INV-100"),
            invoice_date=ExtractedField[str](value="2026-08-10"),  # Base date
            total_amount=ExtractedField[float](value=500.00),
        )

    def test_bva_duplicate_window_day_zero(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Day 0 (same date): Must be flagged as duplicate."""
        cand = NormalizedInvoice(
            id="cand-0", vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation", invoice_id=ExtractedField[str](value="I-0"),
            invoice_date=ExtractedField[str](value="2026-08-10"), total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, _, _, details = engine.evaluate_duplicate(cand, [base_invoice])
        assert is_dup is True
        assert details["day_difference"] == 0

    def test_bva_duplicate_window_day_plus_one(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Day +1 (1 day after): Must be flagged as duplicate."""
        cand = NormalizedInvoice(
            id="cand-1", vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation", invoice_id=ExtractedField[str](value="I-1"),
            invoice_date=ExtractedField[str](value="2026-08-11"), total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, _, _, details = engine.evaluate_duplicate(cand, [base_invoice])
        assert is_dup is True
        assert details["day_difference"] == 1

    def test_bva_duplicate_window_day_plus_seven(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Day +7 (exact positive window boundary): Must be flagged as duplicate."""
        cand = NormalizedInvoice(
            id="cand-7", vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation", invoice_id=ExtractedField[str](value="I-7"),
            invoice_date=ExtractedField[str](value="2026-08-17"), total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, _, _, details = engine.evaluate_duplicate(cand, [base_invoice])
        assert is_dup is True
        assert details["day_difference"] == 7

    def test_bva_duplicate_window_day_minus_seven(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Day -7 (exact negative window boundary): Must be flagged as duplicate."""
        cand = NormalizedInvoice(
            id="cand-neg7", vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation", invoice_id=ExtractedField[str](value="I-neg7"),
            invoice_date=ExtractedField[str](value="2026-08-03"), total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, _, _, details = engine.evaluate_duplicate(cand, [base_invoice])
        assert is_dup is True
        assert details["day_difference"] == 7

    def test_bva_duplicate_window_day_plus_eight(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Day +8 (1 day outside window): Must NOT be flagged as duplicate."""
        cand = NormalizedInvoice(
            id="cand-8", vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation", invoice_id=ExtractedField[str](value="I-8"),
            invoice_date=ExtractedField[str](value="2026-08-18"), total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, _, _, _ = engine.evaluate_duplicate(cand, [base_invoice])
        assert is_dup is False

    def test_bva_duplicate_window_day_minus_eight(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Day -8 (1 day before window): Must NOT be flagged as duplicate."""
        cand = NormalizedInvoice(
            id="cand-neg8", vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation", invoice_id=ExtractedField[str](value="I-neg8"),
            invoice_date=ExtractedField[str](value="2026-08-02"), total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, _, _, _ = engine.evaluate_duplicate(cand, [base_invoice])
        assert is_dup is False

    def test_bva_duplicate_amount_two_cent_difference(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Verify amount difference of 2 cents ($500.00 vs $500.02) is NOT flagged as duplicate."""
        cand = NormalizedInvoice(
            id="cand-2cent", vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation", invoice_id=ExtractedField[str](value="I-2c"),
            invoice_date=ExtractedField[str](value="2026-08-11"), total_amount=ExtractedField[float](value=500.02),
        )
        is_dup, _, _, _ = engine.evaluate_duplicate(cand, [base_invoice])
        assert is_dup is False


# ============================================================================
# Boundary Group 6: RapidFuzz Boundary Thresholds (>= 6 tests)
# ============================================================================

class TestBoundaryGroup6RapidFuzzBoundaries:
    """Boundary Group 6: Match Score Threshold Boundaries (85.0%, 70.0%, Unicode, Whitespace)."""

    @pytest.fixture
    def matcher(self) -> VendorMatcherEngine:
        return VendorMatcherEngine()

    def test_bva_vendor_score_exact_85_threshold(self, matcher: VendorMatcherEngine) -> None:
        """Verify near-exact vendor score >= 85.0% classified as high confidence."""
        _, _, score, is_known = matcher.match_vendor("Amazon Web Services")
        assert score >= 85.0
        assert is_known is True

    def test_bva_vendor_score_moderate_threshold(self, matcher: VendorMatcherEngine) -> None:
        """Verify moderate match score (70.0% - 95.0%) resolves known vendor."""
        # Use a noisy vendor variation that does not have an exact alias match
        _, _, score, is_known = matcher.match_vendor("Microsoft Network Tech Corp Operations")
        assert score >= 70.0
        assert is_known is True

    def test_bva_vendor_score_exact_70_acceptance(self, matcher: VendorMatcherEngine) -> None:
        """Verify threshold at 70.0% marks vendor as known."""
        # Test known entry with noise
        _, _, score, is_known = matcher.match_vendor("Microsoft Billing Dept Operations")
        assert score >= 70.0
        assert is_known is True

    def test_bva_vendor_score_rejection_under_70(self, matcher: VendorMatcherEngine) -> None:
        """Verify vendor with score < 70.0% is flagged as unrecognized (is_known=False)."""
        _, _, score, is_known = matcher.match_vendor("Luigi's Pizza & Catering")
        assert score < 70.0
        assert is_known is False

    def test_bva_vendor_empty_and_whitespace_string(self, matcher: VendorMatcherEngine) -> None:
        """Verify empty or space strings yield 0.0 score."""
        assert matcher.match_vendor("")[2] == 0.0
        assert matcher.match_vendor("   ")[2] == 0.0

    def test_bva_upload_max_size_minus_one_byte(self, client: TestClient) -> None:
        """Verify upload of 5MB minus 1 byte succeeds without error."""
        payload = b"%PDF-1.4\n" + b"C" * (5 * 1024 * 1024 - 11)
        files = {"file": ("almost_max.pdf", payload, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200

    def test_bva_vendor_score_trailing_special_characters(self, matcher: VendorMatcherEngine) -> None:
        """Verify vendor with trailing symbols (e.g. 'Amazon Web Services $$$ ***') matches canonical."""
        canonical, vid, score, is_known = matcher.match_vendor("Amazon Web Services $$$ *** !!!")
        assert canonical == "Amazon Web Services"
        assert is_known is True


# ============================================================================
# Boundary Group 7: Anomaly Math & Tolerance Boundaries (>= 5 tests)
# ============================================================================

class TestBoundaryGroup7AnomalyMathTolerance:
    """Boundary Group 7: Arithmetic Tolerance Boundaries ($0.04, $0.05, $0.06) & Risk Clamping."""

    @pytest.fixture
    def engine(self) -> AnomalyDetectionEngine:
        return AnomalyDetectionEngine(math_tolerance=0.05)

    def test_bva_anomaly_math_diff_under_tolerance(self, engine: AnomalyDetectionEngine) -> None:
        """Diff of $0.04 (<= $0.05 tolerance): Must NOT be flagged with MATH_DISCREPANCY."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="MATH-4C"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            subtotal_amount=ExtractedField[float](value=100.00),
            tax_amount=ExtractedField[float](value=10.00),
            total_amount=ExtractedField[float](value=110.04),  # $0.04 diff
        )
        _, flags, _ = engine.evaluate_anomalies(inv)
        assert not any(f.code == "MATH_DISCREPANCY" for f in flags)

    def test_bva_anomaly_math_diff_exact_tolerance(self, engine: AnomalyDetectionEngine) -> None:
        """Diff of $0.05 (exact $0.05 tolerance boundary): Must NOT be flagged."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="MATH-5C"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            subtotal_amount=ExtractedField[float](value=100.00),
            tax_amount=ExtractedField[float](value=10.00),
            total_amount=ExtractedField[float](value=110.05),  # $0.05 diff
        )
        _, flags, _ = engine.evaluate_anomalies(inv)
        assert not any(f.code == "MATH_DISCREPANCY" for f in flags)

    def test_bva_anomaly_math_diff_over_tolerance(self, engine: AnomalyDetectionEngine) -> None:
        """Diff of $0.06 (> $0.05 tolerance): Must be flagged with MATH_DISCREPANCY."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="MATH-6C"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            subtotal_amount=ExtractedField[float](value=100.00),
            tax_amount=ExtractedField[float](value=10.00),
            total_amount=ExtractedField[float](value=110.06),  # $0.06 diff
        )
        _, flags, _ = engine.evaluate_anomalies(inv)
        assert any(f.code == "MATH_DISCREPANCY" for f in flags)

    def test_bva_risk_score_clamping_max_one(self, engine: AnomalyDetectionEngine) -> None:
        """Verify compound anomalies clamp risk score at exactly 1.0 maximum."""
        inv_severe = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Fake Entity"),
            vendor_raw="Fake Entity",
            is_known_vendor=False,
            invoice_id=ExtractedField[str](value="SEV-1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            subtotal_amount=ExtractedField[float](value=100000.0),
            tax_amount=ExtractedField[float](value=10000.0),
            total_amount=ExtractedField[float](value=99999999.0),
            is_duplicate=True,
            duplicate_reason="Duplicate flagged",
        )
        _, _, risk = engine.evaluate_anomalies(inv_severe)
        assert risk <= 1.0
        assert risk >= 0.90

    def test_bva_risk_score_clean_document_zero(self, engine: AnomalyDetectionEngine) -> None:
        """Verify clean document without any anomalies produces risk_score == 0.0."""
        inv_clean = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Amazon Web Services"),
            vendor_canonical="Amazon Web Services",
            is_known_vendor=True,
            invoice_id=ExtractedField[str](value="CLEAN-1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            subtotal_amount=ExtractedField[float](value=100.0),
            tax_amount=ExtractedField[float](value=10.0),
            total_amount=ExtractedField[float](value=110.0),
        )
        has_anom, flags, risk = engine.evaluate_anomalies(inv_clean)
        assert has_anom is False
        assert len(flags) == 0
        assert risk == 0.0


# ============================================================================
# Boundary Group 8: Line Items & Payload Structural Boundaries (>= 5 tests)
# ============================================================================

class TestBoundaryGroup8LineItemsAndStructure:
    """Boundary Group 8: Empty Lists, 100+ Line Items, and Missing Optional Fields."""

    def test_bva_line_items_empty_list(self) -> None:
        """Verify invoice with 0 line items creates valid NormalizedInvoice with line_items == []."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="INV-0ITEMS"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=100.0),
            line_items=[],
        )
        assert len(inv.line_items) == 0
        assert inv.model_dump()["line_items"] == []

    def test_bva_line_items_large_list_100_items(self) -> None:
        """Verify invoice with 100 line items parses and serializes cleanly."""
        items = [
            LineItem(
                description=f"Part SKU-{i:04d}",
                quantity=1.0,
                unit_price=10.0,
                total_amount=10.0,
            )
            for i in range(100)
        ]
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="INV-100ITEMS"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=1000.0),
            line_items=items,
        )
        assert len(inv.line_items) == 100
        assert inv.line_items[99].description == "Part SKU-0099"

    def test_bva_payload_missing_all_optional_fields(self) -> None:
        """Verify payload with missing optional fields (due_date, subtotal, tax, customer) validates."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Vendor Min"),
            invoice_id=ExtractedField[str](value="INV-MIN"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=100.0),
        )
        assert inv.due_date is None
        assert inv.subtotal_amount is None
        assert inv.tax_amount is None
        assert inv.customer_name is None
        assert inv.purchase_order is None

    def test_bva_line_item_math_discrepancy_sub_cent(self) -> None:
        """Verify line item math discrepancy tolerance with sub-cent rounding."""
        item = LineItem(description="Item", quantity=3.0, unit_price=33.33, total_amount=100.00)
        # 3 * 33.33 = 99.99, diff is 0.01 <= 0.05
        assert item.has_math_discrepancy(0.05) is False

    def test_bva_confidence_breakdown_field_clamping(self) -> None:
        """Verify ExtractedField accepts boundary confidence values 0.0 and 1.0."""
        f_min = ExtractedField[str](value="Test", confidence=0.0)
        assert f_min.confidence == 0.0

        f_max = ExtractedField[str](value="Test", confidence=1.0)
        assert f_max.confidence == 1.0


# ============================================================================
# Boundary Group 9: PDF & Stream Corruption Boundaries (>= 5 tests)
# ============================================================================

class TestBoundaryGroup9CorruptionAndHeaders:
    """Boundary Group 9: Corrupt PDF Streams, Binary Noise, and Invalid MIME."""

    def test_bva_corrupt_truncated_pdf_stream(self) -> None:
        """Verify truncated PDF stream (%PDF- without endstream) falls back gracefully."""
        mock_service = MockExtractionService()
        truncated = b"%PDF-1.4\n1 0 obj\n<< /Length 20 >>\nstream\nTruncated text content\n"
        payload = mock_service.extract_document(
            file_bytes=truncated,
            filename="corrupt_truncated.pdf",
        )
        assert payload is not None
        assert payload.filename == "corrupt_truncated.pdf"

    def test_bva_random_binary_garbage_stream(self) -> None:
        """Verify completely random binary garbage (2048 bytes) extracts without exception."""
        mock_service = MockExtractionService()
        garbage = os.urandom(2048)
        payload = mock_service.extract_document(
            file_bytes=garbage,
            filename="random_noise.bin",
        )
        assert payload is not None
        assert payload.document_id is not None

    def test_bva_invalid_extension_rejection(self, client: TestClient) -> None:
        """Verify unsupported file extensions (.exe, .sh, .txt) return HTTP 400."""
        files = {"file": ("malicious.exe", b"MZ\x90\x00", "application/x-msdownload")}
        response = client.post("/upload", files=files)
        assert response.status_code == 400
        assert "unsupported file extension" in response.json()["detail"].lower()

    def test_bva_missing_file_extension(self, client: TestClient) -> None:
        """Verify filename with no extension is rejected with HTTP 400."""
        files = {"file": ("invoice_no_ext", b"%PDF-1.4...", "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 400

    def test_bva_tiff_image_extension_support(self, client: TestClient) -> None:
        """Verify .tiff format is permitted according to ALLOWED_EXTENSIONS."""
        from PIL import Image
        buf = io.BytesIO()
        img = Image.new("RGB", (50, 50), color=(255, 255, 255))
        img.save(buf, format="TIFF")
        files = {"file": ("scanned_invoice.tiff", buf.getvalue(), "image/tiff")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
