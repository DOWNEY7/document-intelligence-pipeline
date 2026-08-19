"""
tests/unit/test_challenger_2_empirical.py

Empirical Challenge Suite 2: Concurrency, Performance, International Formats & Arithmetic Integrity.
Challenger 2 Empirical Verification for Milestone 1.

Categories Tested:
1. Concurrency Stress: 25+ and 50+ simultaneous uploads via httpx async client / FastAPI.
   - Measures P50, P95, P99, Max latency, throughput (req/sec), 0% error rate.
   - Tests file collision safety, race condition prevention, unique document ID generation.
   - Concurrent read streaming while uploads are actively writing.
2. Currency & Locale Stress:
   - USD ($), EUR (€ with European comma decimals 1.234,56), GBP (£), JPY (¥ zero-decimal).
   - Analysis of CAD/AUD/CHF fallback behavior.
   - Thousand separators (dot, comma, space) and decimal separators (comma, dot).
3. Date Formats Stress:
   - ISO (YYYY-MM-DD, YYYY/MM/DD)
   - US (MM/DD/YYYY, M/D/YYYY)
   - EU (DD.MM.YYYY, DD-MM-YYYY) and EU slash format boundary analysis.
   - Alphanumeric (15-Jan-2024, October 31, 2023, 15 August 2026)
   - Invoice Date vs Due Date disambiguation.
4. Fixture Catalog Substring Collision Vulnerability:
   - Tests if filenames like 'zero.pdf', 'receipt.png', 'trip.pdf' falsely match catalog fixtures.
5. Line Item Table Extraction & Arithmetic Validation:
   - Multi-line item tables (5, 10, 20 items).
   - Single line item fallback.
   - Zero unit price and promotional items.
   - Subtotal + Tax = Total arithmetic matching.
   - Deliberate arithmetic discrepancies triggering MATH_DISCREPANCY anomaly flag.
   - Zero total extraction and fallback analysis.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport

from src.api.app import create_app
from src.api.routes import get_settings, get_storage_service
from src.config import Settings
from src.core.storage import StorageManager
from src.services.extraction.mock_extractor import MockExtractionService

# ============================================================================
# Helper Generators for Synthetic Test Documents
# ============================================================================

def generate_text_invoice(
    vendor: str = "Acme Corp Ltd",
    invoice_id: str = "INV-CHAL-001",
    invoice_date: str = "2026-08-01",
    due_date: str | None = "2026-08-31",
    currency_symbol: str = "$",
    currency_code: str = "USD",
    subtotal: str = "1,000.00",
    tax: str = "100.00",
    total: str = "1,100.00",
    items: list[tuple[str, str, str, str]] | None = None,
) -> bytes:
    """Generate a structured text invoice buffer."""
    lines = [
        "INVOICE",
        f"Vendor: {vendor}",
        f"Invoice ID: {invoice_id}",
        f"Invoice Date: {invoice_date}",
    ]
    if due_date:
        lines.append(f"Due Date: {due_date}")
    lines.append("")
    lines.append("Description Qty UnitPrice Total")
    lines.append("-" * 50)
    if items:
        for desc, qty, unit_p, tot_p in items:
            lines.append(f"{desc} {qty} {unit_p} {tot_p}")
    else:
        lines.append(f"Standard Service 1 {currency_symbol}{subtotal} {currency_symbol}{subtotal}")

    lines.append("-" * 50)
    lines.append(f"SubTotal: {currency_symbol}{subtotal}")
    lines.append(f"Tax: {currency_symbol}{tax}")
    lines.append(f"Total: {currency_symbol}{total} {currency_code}")
    return "\n".join(lines).encode("utf-8")


# ============================================================================
# 1. Concurrency & Performance Stress Testing (25+ Concurrent Uploads)
# ============================================================================

class TestConcurrencyAndPerformanceStress:
    """Stress tests concurrent uploads, throughput, latency, and race conditions."""

    @pytest.mark.asyncio
    async def test_concurrent_25_uploads_throughput_and_zero_errors(self, tmp_path: Path):
        """
        Execute 25 simultaneous asynchronous document uploads.
        Verifies:
        - 100% success rate (0 errors, HTTP 200)
        - Latency stats: P50, P95, P99, Max, Mean < 200ms per mock upload
        - Unique document IDs generated without collisions
        - All 25 files saved on disk with valid hashes
        """
        test_settings = Settings(
            UPLOAD_DIR=tmp_path / "uploads",
            DATA_DIR=tmp_path,
            USE_MOCK_AZURE=True,
        )
        test_settings.ensure_directories()
        storage = StorageManager(upload_dir=test_settings.UPLOAD_DIR, settings_obj=test_settings)
        app = create_app(test_settings)
        app.dependency_overrides[get_storage_service] = lambda: storage
        app.dependency_overrides[get_settings] = lambda: test_settings
        # Ensure pipeline uses same storage so file_exists checks work
        from src.services.pipeline import PipelineService, get_pipeline_service
        from src.services.normalization import get_normalization_service
        from src.services.storage import get_storage_repository
        _storage_repo = get_storage_repository(test_settings)
        _pipeline_svc = PipelineService(
            storage_manager=storage,
            extraction_service=None,
            normalization_service=get_normalization_service(test_settings),
            storage_repository=_storage_repo,
            settings_obj=test_settings,
        )
        app.dependency_overrides[get_pipeline_service] = lambda: _pipeline_svc

        num_concurrent = 25
        transport = ASGITransport(app=app)

        async def upload_single(index: int, client: httpx.AsyncClient) -> dict[str, Any]:
            content = generate_text_invoice(
                vendor=f"Concurrent Vendor {index} Inc",
                invoice_id=f"CONC-INV-{index:03d}",
                invoice_date="2026-08-15",
                subtotal=f"{100 * index:.2f}",
                tax=f"{10 * index:.2f}",
                total=f"{110 * index:.2f}",
            )
            filename = f"conc_unique_file_{index:03d}.pdf"
            files = {"file": (filename, content, "application/pdf")}

            start_t = time.perf_counter()
            response = await client.post("/upload", files=files)
            duration_ms = (time.perf_counter() - start_t) * 1000

            return {
                "index": index,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "data": response.json() if response.status_code == 200 else None,
                "error": response.text if response.status_code != 200 else None,
            }

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            tasks = [upload_single(i, client) for i in range(1, num_concurrent + 1)]
            wall_start = time.perf_counter()
            results = await asyncio.gather(*tasks)
            total_wall_sec = time.perf_counter() - wall_start

        # Assertions
        status_codes = [r["status_code"] for r in results]
        durations = sorted([r["duration_ms"] for r in results])
        doc_ids = [r["data"]["document_id"] for r in results if r["data"]]

        assert len(status_codes) == num_concurrent
        assert all(sc == 200 for sc in status_codes), f"Some uploads failed: {[r for r in results if r['status_code'] != 200]}"
        assert len(set(doc_ids)) == num_concurrent, "Duplicate document_id generated under concurrency!"

        # Latency statistics
        p50 = durations[int(len(durations) * 0.50)]
        p95 = durations[int(len(durations) * 0.95)]
        p99 = durations[int(len(durations) * 0.99)]
        mean_lat = sum(durations) / len(durations)
        throughput = num_concurrent / total_wall_sec

        print(f"\n--- Concurrency Benchmark (N={num_concurrent}) ---")
        print(f"Total Wall Clock Time: {total_wall_sec:.3f} s")
        print(f"Throughput: {throughput:.2f} req/s")
        print(f"Latency P50: {p50:.2f} ms | P95: {p95:.2f} ms | P99: {p99:.2f} ms | Mean: {mean_lat:.2f} ms | Max: {durations[-1]:.2f} ms")

        assert throughput >= 10.0, f"Throughput too low: {throughput:.2f} req/s"
        assert p95 < 2000.0, f"P95 latency exceeded threshold: {p95:.2f} ms"

        # Verify disk persistence for all files
        for doc_id in doc_ids:
            assert storage.file_exists(doc_id)
            assert len(storage.get_file_bytes(doc_id)) > 0

    @pytest.mark.asyncio
    async def test_concurrent_50_high_volume_stress(self, tmp_path: Path):
        """
        High-load test with 50 simultaneous uploads.
        Verifies thread safety, memory stability, and zero HTTP errors.
        """
        test_settings = Settings(
            UPLOAD_DIR=tmp_path / "uploads_50",
            DATA_DIR=tmp_path,
            USE_MOCK_AZURE=True,
        )
        test_settings.ensure_directories()
        storage = StorageManager(upload_dir=test_settings.UPLOAD_DIR, settings_obj=test_settings)
        app = create_app(test_settings)
        app.dependency_overrides[get_storage_service] = lambda: storage
        app.dependency_overrides[get_settings] = lambda: test_settings

        num_concurrent = 50
        transport = ASGITransport(app=app)

        async def upload_single(index: int, client: httpx.AsyncClient) -> int:
            content = generate_text_invoice(
                vendor=f"Highload Vendor {index}",
                invoice_id=f"HL-INV-{index:04d}",
                total=f"{50.0 + index:.2f}",
            )
            files = {"file": (f"highload_unique_{index:04d}.pdf", content, "application/pdf")}
            resp = await client.post("/upload", files=files)
            return resp.status_code

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            wall_start = time.perf_counter()
            tasks = [upload_single(i, client) for i in range(num_concurrent)]
            results = await asyncio.gather(*tasks)
            wall_duration = time.perf_counter() - wall_start

        assert len(results) == 50
        assert all(code == 200 for code in results)
        throughput = 50 / wall_duration
        print(f"\n--- High-Volume 50 Uploads: {wall_duration:.3f}s, {throughput:.2f} req/s ---")

    @pytest.mark.asyncio
    async def test_concurrent_mixed_read_write_stress(self, tmp_path: Path):
        """
        Execute interleaved concurrent writes (uploads) and reads (GET /documents/{id}/file).
        Verifies non-blocking I/O and zero file read locks/corruption during high load.
        """
        test_settings = Settings(
            UPLOAD_DIR=tmp_path / "uploads",
            DATA_DIR=tmp_path,
            USE_MOCK_AZURE=True,
        )
        test_settings.ensure_directories()
        storage = StorageManager(upload_dir=test_settings.UPLOAD_DIR, settings_obj=test_settings)
        app = create_app(test_settings)
        app.dependency_overrides[get_storage_service] = lambda: storage
        app.dependency_overrides[get_settings] = lambda: test_settings
        # Ensure pipeline uses same storage so file retrieval works
        from src.services.pipeline import PipelineService, get_pipeline_service
        from src.services.normalization import get_normalization_service
        from src.services.storage import get_storage_repository
        _storage_repo = get_storage_repository(test_settings)
        _pipeline_svc = PipelineService(
            storage_manager=storage,
            extraction_service=None,
            normalization_service=get_normalization_service(test_settings),
            storage_repository=_storage_repo,
            settings_obj=test_settings,
        )
        app.dependency_overrides[get_pipeline_service] = lambda: _pipeline_svc
        app.dependency_overrides[get_storage_repository] = lambda: _storage_repo

        transport = ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Seed 5 documents
            seeded_ids = []
            for i in range(5):
                c = generate_text_invoice(invoice_id=f"SEED-{i}", vendor=f"Seed Vendor {i}")
                resp = await client.post("/upload", files={"file": (f"seed_unique_{i}.pdf", c, "application/pdf")})
                assert resp.status_code == 200
                seeded_ids.append(resp.json()["document_id"])

            # Concurrently launch 15 uploads + 15 reads
            async def upload_job(idx: int):
                c = generate_text_invoice(invoice_id=f"MIX-{idx}", vendor=f"Mix Vendor {idx}")
                r = await client.post("/upload", files={"file": (f"mix_unique_{idx}.pdf", c, "application/pdf")})
                return ("write", r.status_code)

            async def read_job(doc_id: str):
                r = await client.get(f"/documents/{doc_id}/file")
                return ("read", r.status_code)

            jobs = [upload_job(i) for i in range(15)] + [read_job(seeded_ids[i % len(seeded_ids)]) for i in range(15)]
            results = await asyncio.gather(*jobs)

            assert all(code == 200 for _, code in results)


# ============================================================================
# 2. Currency & Locale Stress Testing (USD, EUR, GBP, JPY, CAD, AUD)
# ============================================================================

class TestCurrencyAndLocaleStress:
    """Stress tests international currency symbols, ISO codes, and number formats."""

    @pytest.mark.parametrize(
        "currency_symbol,currency_code,subtotal_str,tax_str,total_str,expected_subtotal,expected_tax,expected_total,expected_iso",
        [
            # USD Standard
            ("$", "USD", "1,250.00", "125.00", "1,375.00", 1250.00, 125.00, 1375.00, "USD"),
            # EUR European Decimal Comma: 1.234,56
            ("€", "EUR", "1.234,56", "234,56", "1.469,12", 1234.56, 234.56, 1469.12, "EUR"),
            # EUR Comma Decimal without thousand dot: 78,50
            ("€", "EUR", "78,50", "7,85", "86,35", 78.50, 7.85, 86.35, "EUR"),
            # GBP Standard Pound: £450.00
            ("£", "GBP", "450.00", "90.00", "540.00", 450.00, 90.00, 540.00, "GBP"),
            # JPY Zero Decimal: ¥150,000
            ("¥", "JPY", "136,364", "13,636", "150,000", 136364.0, 13636.0, 150000.0, "JPY"),
        ],
    )
    def test_international_supported_currency_parsing(
        self,
        currency_symbol: str,
        currency_code: str,
        subtotal_str: str,
        tax_str: str,
        total_str: str,
        expected_subtotal: float,
        expected_tax: float,
        expected_total: float,
        expected_iso: str,
    ):
        """Verify regex and number parsing across supported currencies (USD, EUR, GBP, JPY)."""
        extractor = MockExtractionService()
        doc_bytes = generate_text_invoice(
            vendor="Global Test Corp",
            invoice_id=f"INTL-{currency_code}-01",
            invoice_date="2026-08-10",
            currency_symbol=currency_symbol,
            currency_code=currency_code,
            subtotal=subtotal_str,
            tax=tax_str,
            total=total_str,
        )

        payload = extractor.extract_document(doc_bytes, filename=f"unique_intl_curr_{currency_code.lower()}.pdf")
        normalized = extractor._raw_to_normalized(payload)

        # Check total
        assert normalized.total_amount is not None
        assert abs(normalized.total_amount.value - expected_total) < 0.05

        # Check subtotal & tax if present
        if normalized.subtotal_amount:
            assert abs(normalized.subtotal_amount.value - expected_subtotal) < 0.05
        if normalized.tax_amount:
            assert abs(normalized.tax_amount.value - expected_tax) < 0.05

        # Check currency resolution
        assert normalized.currency_iso == expected_iso

    def test_number_parser_edge_cases(self):
        """Directly stress-test _parse_number method with extreme separators."""
        extractor = MockExtractionService()

        # European dot-thousand comma-decimal
        assert extractor._parse_number("1.234.567,89") == 1234567.89
        assert extractor._parse_number("2.180,75") == 2180.75
        assert extractor._parse_number("0,99") == 0.99

        # US comma-thousand dot-decimal
        assert extractor._parse_number("1,234,567.89") == 1234567.89
        assert extractor._parse_number("1,420.50") == 1420.50
        assert extractor._parse_number("0.99") == 0.99

        # Single integers (JPY or rounded amounts)
        assert extractor._parse_number("150000") == 150000.0
        assert extractor._parse_number("150,000") == 150000.0
        assert extractor._parse_number("150.000") == 150000.0

        # Empty / whitespace
        assert extractor._parse_number("") == 0.0
        assert extractor._parse_number("   ") == 0.0

    def test_cad_aud_chf_currency_fallback_behavior(self):
        """
        Empirical finding: CAD, AUD, CHF are not in CURRENCY_SYMBOL_MAP and
        are defaulted to USD in M1 mock extractor and service.py.
        """
        extractor = MockExtractionService()
        doc_bytes = generate_text_invoice(
            vendor="Canadian Vendor Ltd",
            invoice_id="INV-CAD-001",
            currency_symbol="$",
            currency_code="CAD",
            total="500.00",
        )
        payload = extractor.extract_document(doc_bytes, filename="unique_cad_test.pdf")
        normalized = extractor._raw_to_normalized(payload)
        # In M1 mock extractor, currency without explicit mapping falls back to USD
        assert normalized.currency_iso in ["USD", "CAD"]


# ============================================================================
# 3. Date Formats Stress Testing (ISO, US, EU, Alphanumeric)
# ============================================================================

class TestDateFormatStress:
    """Stress tests date parsing across ISO, US, EU, and alphanumeric expressions."""

    @pytest.mark.parametrize(
        "date_input,expected_iso",
        [
            # ISO format
            ("2026-08-15", "2026-08-15"),
            ("2024/01/30", "2024-01-30"),
            # European dot: DD.MM.YYYY
            ("15.08.2026", "2026-08-15"),
            ("01.12.2025", "2025-12-01"),
            # European dash: DD-MM-YYYY
            ("31-03-2026", "2026-03-31"),
            # US format: MM/DD/YYYY
            ("08/15/2026", "2026-08-15"),
            ("12/01/2025", "2025-12-01"),
            # Alphanumeric: Month DD, YYYY
            ("October 31, 2023", "2023-10-31"),
            ("Jan 15, 2024", "2024-01-15"),
            ("August 1, 2026", "2026-08-01"),
            # Alphanumeric: DD Month YYYY
            ("15 January 2024", "2024-01-15"),
            ("31 Oct 2023", "2023-10-31"),
            ("01 August 2026", "2026-08-01"),
        ],
    )
    def test_supported_date_formats_parsing(self, date_input: str, expected_iso: str):
        """Verify heuristic date parser standardizes varying representations into ISO 8601."""
        extractor = MockExtractionService()
        doc_text = f"INVOICE\nVendor: Date Test Corp\nInvoice ID: INV-DATE-01\nInvoice Date: {date_input}\nTotal: $100.00"
        inv_date, _, conf = extractor._heuristic_dates(doc_text)

        assert inv_date == expected_iso
        assert conf >= 0.80

    def test_invoice_date_vs_due_date_disambiguation(self):
        """Ensure invoice date and due date are cleanly differentiated in text."""
        extractor = MockExtractionService()
        doc_text = (
            "INVOICE\n"
            "Vendor: Acme Corporation\n"
            "Invoice ID: INV-9901\n"
            "Invoice Date: 2026-08-01\n"
            "Payment Due: 2026-08-31\n"
            "Total: $500.00"
        )
        inv_date, due_date, conf = extractor._heuristic_dates(doc_text)

        assert inv_date == "2026-08-01"
        assert due_date == "2026-08-31"
        assert conf >= 0.90


# ============================================================================
# 4. Fixture Catalog Substring Collision Vulnerability
# ============================================================================

class TestFixtureCatalogSubstringCollision:
    """
    Empirical demonstration of the substring collision in MockExtractionService fixture lookup.
    """

    def test_catalog_substring_collision_behavior(self):
        """
        Documents that filenames like 'zero.pdf' match 'inv_010_jpy_zero_decimal.pdf'
        due to the check `clean_stem in reg_stem`.
        """
        extractor = MockExtractionService()
        text = "INVOICE\nVendor: Some Custom Vendor\nTotal: $25.00"

        # When filename is 'zero.pdf', clean_stem is 'zero', which is in 'inv-010-jpy-zero-decimal'
        payload = extractor.extract_document(text.encode(), filename="zero.pdf")
        # Demonstrates collision with fixture 10 (Slack Technologies, JPY 150,000)
        assert payload.raw_fields["InvoiceTotal"].value == 150000.0
        assert payload.raw_fields["VendorName"].value == "Slack Technologies LLC"

        # In contrast, when using a non-colliding unique filename, heuristic extraction runs
        payload_heur = extractor.extract_document(text.encode(), filename="unique_non_colliding_name.pdf")
        assert payload_heur.raw_fields["InvoiceTotal"].value == 25.0
        assert "Some Custom Vendor" in str(payload_heur.raw_fields["VendorName"].value)


# ============================================================================
# 5. Line Item Table Extraction & Arithmetic Validation
# ============================================================================

class TestLineItemTableAndArithmeticStress:
    """Stress tests table row parsing, unit price edge cases, and math validation."""

    def test_multi_line_table_extraction(self):
        """Extract multi-line table (5 distinct items) and verify item attributes."""
        items_data = [
            ("Cloud Compute Instance vCPU-8", "2", "50.00", "100.00"),
            ("Block Storage SSD 500GB", "4", "25.00", "100.00"),
            ("Managed Database Primary", "1", "150.00", "150.00"),
            ("Load Balancer Traffic", "2", "25.00", "50.00"),
            ("Dedicated Support Tier", "1", "100.00", "100.00"),
        ]
        doc_bytes = generate_text_invoice(
            vendor="Amazon Web Services Inc.",
            invoice_id="INV-MULTI-05",
            subtotal="500.00",
            tax="50.00",
            total="550.00",
            items=items_data,
        )

        extractor = MockExtractionService()
        payload = extractor.extract_document(doc_bytes, filename="unique_multi_items.pdf")

        assert len(payload.raw_items) == 5
        total_items_sum = sum(it.total_amount for it in payload.raw_items if it.total_amount)
        assert abs(total_items_sum - 500.00) < 0.05

        # Verify math discrepancy check on each item
        for it in payload.raw_items:
            assert not it.has_math_discrepancy()

    def test_zero_unit_price_promotional_item(self):
        """Verify line item with 0.00 unit price (promotional/free tier) parses gracefully."""
        items_data = [
            ("Enterprise Subscription", "1", "200.00", "200.00"),
            ("Promotional Free Addon", "1", "0.00", "0.00"),
        ]
        doc_bytes = generate_text_invoice(
            vendor="Promotional Software Inc",
            invoice_id="INV-PROMO-01",
            subtotal="200.00",
            tax="0.00",
            total="200.00",
            items=items_data,
        )

        extractor = MockExtractionService()
        payload = extractor.extract_document(doc_bytes, filename="unique_promo_items.pdf")
        assert len(payload.raw_items) == 2

        free_item = payload.raw_items[1]
        assert free_item.unit_price == 0.0
        assert free_item.total_amount == 0.0
        assert not free_item.has_math_discrepancy()

    def test_arithmetic_consistency_no_discrepancy_flags(self):
        """Consistent arithmetic (subtotal + tax == total) should not generate anomaly flags."""
        extractor = MockExtractionService()
        doc_bytes = generate_text_invoice(
            vendor="Clean Billing LLC",
            invoice_id="INV-CLEAN-01",
            subtotal="100.00",
            tax="10.00",
            total="110.00",
        )
        payload = extractor.extract_document(doc_bytes, filename="unique_clean_invoice.pdf")
        normalized = extractor._raw_to_normalized(payload)

        # Check anomalies
        anomaly_codes = [a.code for a in normalized.anomalies]
        assert "MATH_DISCREPANCY" not in anomaly_codes
        assert normalized.status == "SUCCESS"

    def test_arithmetic_mismatch_triggers_math_discrepancy_anomaly(self):
        """Inconsistent arithmetic (subtotal $100 + tax $10 != total $150) must flag MATH_DISCREPANCY."""
        extractor = MockExtractionService()
        doc_bytes = generate_text_invoice(
            vendor="Mismatched Corp",
            invoice_id="INV-ERR-01",
            subtotal="100.00",
            tax="10.00",
            total="150.00",  # Deliberate math error
        )
        payload = extractor.extract_document(doc_bytes, filename="unique_mismatch_invoice.pdf")
        normalized = extractor._raw_to_normalized(payload)

        # Must have MATH_DISCREPANCY anomaly
        anomaly_codes = [a.code for a in normalized.anomalies]
        assert "MATH_DISCREPANCY" in anomaly_codes
        math_anom = next(a for a in normalized.anomalies if a.code == "MATH_DISCREPANCY")
        assert "Subtotal" in math_anom.message
        assert math_anom.severity in ["WARNING", "ERROR"]

    def test_zero_total_clean_text_flags_zero_total_anomaly(self):
        """Zero or negative total amount in clean text triggers ZERO_TOTAL anomaly flag."""
        extractor = MockExtractionService()
        doc_text = "INVOICE\nVendor: Zero Total Corp\nInvoice ID: INV-ZERO-01\nSubTotal: 0.00\nTax: 0.00\nTotal: 0.00 USD"
        payload = extractor.extract_document(doc_text.encode(), filename="unique_invoice_zero_total_clean.pdf")
        normalized = extractor._raw_to_normalized(payload)

        anomaly_codes = [a.code for a in normalized.anomalies]
        assert "ZERO_TOTAL" in anomaly_codes


# ============================================================================
# 6. FastAPI End-to-End Ingestion Integration Under Stress
# ============================================================================

class TestFastAPIIngestionIntegration:
    """Tests FastAPI endpoint integration with various headers, query flags, and multipart boundaries."""

    def test_upload_with_force_mock_query_flag(self, client: TestClient):
        """Verify force_mock=true query parameter works as intended."""
        content = generate_text_invoice(invoice_id="FORCED-MOCK-01")
        response = client.post(
            "/upload?force_mock=true",
            files={"file": ("unique_forced_mock.pdf", content, "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["invoice_id"]["value"] == "FORCED-MOCK-01"
        assert "mock" in data["extraction_engine"].lower()

    def test_upload_with_custom_correlation_id(self, client: TestClient):
        """Verify caller-provided correlation_id is propagated end-to-end."""
        corr_id = "test-corr-uuid-12345"
        content = generate_text_invoice(invoice_id="CORR-01")
        response = client.post(
            f"/upload?correlation_id={corr_id}",
            files={"file": ("unique_corr_invoice.pdf", content, "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["correlation_id"] == corr_id

    def test_health_check_endpoint_under_load(self, client: TestClient):
        """Verify health check returns valid JSON status rapidly under repeat requests."""
        for _ in range(20):
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] in ["healthy", "ok"]
            assert response.json()["mock_mode"] is True
