"""
tests/unit/test_tier1_features.py

Tier 1: Feature Coverage Test Suite.
Verifies all 9 core pipeline features with >= 5 dedicated tests per feature (50+ tests total):
- Feature 1: FastAPI Ingestion Validation
- Feature 2: Azure Document Intelligence & Mock Fallback Extraction
- Feature 3: Pydantic v2 Domain Models
- Feature 4: RapidFuzz Canonical Vendor Resolver
- Feature 5: 11-Category Spend Taxonomy Classifier
- Feature 6: ISO Date & Currency Parsing & Normalization
- Feature 7: Cosmos DB Dual-Storage Repository Interface
- Feature 8: 7-Day Sliding Window Duplicate Detection Engine
- Feature 9: Multi-Type Anomaly Detection Engine & Risk Scoring
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.core.models import (
    AnomalyFlag,
    AnomalySeverity,
    ConfidenceBreakdown,
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

# ============================================================================
# Feature 1: FastAPI Ingestion Validation (>= 6 tests)
# ============================================================================

class TestFeature1FastAPIIngestion:
    """Feature 1: FastAPI Ingestion Endpoints and Validation."""

    def test_ingest_standard_pdf_success(self, client: TestClient, sample_pdf_bytes: bytes) -> None:
        """Verify successful upload of a standard PDF document returns HTTP 200 and schema."""
        files = {"file": ("inv_001_aws.pdf", sample_pdf_bytes, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "document_id" in data
        assert "total_amount" in data
        assert data["filename"] == "inv_001_aws.pdf"

    def test_ingest_image_png_success(self, client: TestClient, sample_png_bytes: bytes) -> None:
        """Verify successful upload of a PNG receipt image with correct MIME handling."""
        files = {"file": ("receipt_uber.png", sample_png_bytes, "image/png")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "receipt_uber.png"
        assert data["status"] in ["SUCCESS", "PROCESSED", "NEEDS_REVIEW"]

    def test_ingest_image_jpg_success(self, client: TestClient, sample_jpg_bytes: bytes) -> None:
        """Verify successful upload of a JPEG image."""
        files = {"file": ("restaurant.jpg", sample_jpg_bytes, "image/jpeg")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "restaurant.jpg"

    def test_ingest_custom_correlation_id_propagates(self, client: TestClient, sample_pdf_bytes: bytes) -> None:
        """Verify custom correlation ID supplied in query param is preserved in the response."""
        custom_corr_id = f"trace-corr-{uuid.uuid4().hex[:12]}"
        files = {"file": ("test_invoice.pdf", sample_pdf_bytes, "application/pdf")}
        response = client.post(f"/upload?correlation_id={custom_corr_id}", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["correlation_id"] == custom_corr_id

    def test_health_check_endpoint_status_and_metadata(self, client: TestClient) -> None:
        """Verify /health endpoint returns status, mock mode indicator, and app version."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["mock_mode"] is True
        assert "version" in data
        assert data["storage_healthy"] is True

    def test_document_file_streaming_and_content_type(self, client: TestClient, sample_pdf_bytes: bytes) -> None:
        """Verify uploaded document can be retrieved and streamed via /documents/{id}/file."""
        files = {"file": ("stream_test.pdf", sample_pdf_bytes, "application/pdf")}
        upload_resp = client.post("/upload", files=files)
        assert upload_resp.status_code == 200
        doc_id = upload_resp.json()["document_id"]

        get_resp = client.get(f"/documents/{doc_id}/file")
        assert get_resp.status_code == 200
        assert get_resp.headers["content-type"] == "application/pdf"
        assert get_resp.content == sample_pdf_bytes


# ============================================================================
# Feature 2: Azure Extraction & Mock Fallback Parsing (>= 6 tests)
# ============================================================================

class TestFeature2ExtractionAndMockFallback:
    """Feature 2: Azure Document Intelligence & Mock Fallback Extraction."""

    def test_azure_client_parse_result_mocked(self, mock_azure_response_loader: Any) -> None:
        """Verify Azure Document Intelligence client parses AnalyzeResult fields correctly."""
        mock_result = mock_azure_response_loader("inv_001_standard_aws")
        client = AzureDocumentIntelligenceClient()
        raw_payload = client._parse_azure_result(
            result=mock_result,
            document_id="doc-test-101",
            correlation_id="corr-test-101",
            filename="inv_001_standard_aws.pdf",
        )

        assert raw_payload.document_id == "doc-test-101"
        assert "VendorName" in raw_payload.raw_fields
        assert "Amazon Web Services" in str(raw_payload.raw_fields["VendorName"].value)
        assert "InvoiceTotal" in raw_payload.raw_fields
        assert raw_payload.raw_fields["InvoiceTotal"].value == 1420.50
        assert len(raw_payload.raw_items) >= 3

    def test_azure_client_line_items_extraction_fidelity(self, mock_azure_response_loader: Any) -> None:
        """Verify line items subfields (description, quantity, unit price, amount) are parsed."""
        mock_result = mock_azure_response_loader("inv_001_standard_aws")
        client = AzureDocumentIntelligenceClient()
        raw_payload = client._parse_azure_result(
            result=mock_result,
            document_id="doc-102",
            correlation_id="corr-102",
            filename="inv_001_standard_aws.pdf",
        )

        item0 = raw_payload.raw_items[0]
        assert "EC2" in item0.description
        assert item0.quantity == 1.0
        assert item0.unit_price == 850.0
        assert item0.total_amount == 850.0

    def test_mock_extractor_fixture_lookup_by_filename(self) -> None:
        """Verify MockExtractor correctly resolves benchmark fixtures by filename."""
        mock_service = MockExtractionService()
        raw_payload = mock_service.extract_document(
            file_bytes=b"%PDF-1.4 mock content",
            filename="inv_001_standard_aws.pdf",
        )
        assert raw_payload.raw_fields["VendorName"].value == "Amazon Web Services Inc."
        assert raw_payload.raw_fields["InvoiceTotal"].value == 1420.50
        assert raw_payload.extraction_engine == "mock_fixture_catalog"

    def test_mock_extractor_fixture_lookup_by_hash(self) -> None:
        """Verify MockExtractor matches fixtures by registered SHA-256 hash."""
        mock_service = MockExtractionService()
        dummy_bytes = b"custom-unique-invoice-bytes-999"
        import hashlib
        h = hashlib.sha256(dummy_bytes).hexdigest()

        mock_service.register_fixture_by_hash(h, {
            "vendor_name": "Custom Test Vendor LLC",
            "total_amount": 999.99,
            "currency": "USD",
            "invoice_date": "2026-08-19",
        })

        payload = mock_service.extract_document(file_bytes=dummy_bytes, filename="random_name.pdf")
        assert payload.raw_fields["VendorName"].value == "Custom Test Vendor LLC"
        assert payload.raw_fields["InvoiceTotal"].value == 999.99
        assert payload.extraction_engine == "mock_fixture_hash"

    def test_confidence_breakdown_structure_weights(self) -> None:
        """Verify confidence scoring structure and component breakdown."""
        cb = ConfidenceBreakdown(
            overall=0.96,
            vendor=0.98,
            invoice_id=0.95,
            date=0.99,
            total=0.97,
            line_items=0.92,
            field_scores={"VendorName": 0.98, "InvoiceTotal": 0.97},
        )
        assert cb.overall == 0.96
        assert cb.vendor == 0.98
        assert cb.field_scores["VendorName"] == 0.98

    def test_mock_heuristic_extractor_fallback(self) -> None:
        """Verify dynamic heuristic regex extractor parses text when no catalog match exists."""
        mock_service = MockExtractionService()
        text_content = (
            "From: Apex Digital Solutions LLC\n"
            "Invoice Number: APX-9941\n"
            "Date: 2026-08-18\n"
            "Due Date: 2026-09-17\n"
            "Subtotal: $2,000.00\n"
            "Tax: $200.00\n"
            "Total Amount: $2,200.00\n"
        )
        payload = mock_service.extract_document(
            file_bytes=text_content.encode("utf-8"),
            filename="unregistered_invoice.pdf",
        )
        assert "Apex Digital Solutions" in str(payload.raw_fields["VendorName"].value)
        assert payload.raw_fields["InvoiceTotal"].value == 2200.00
        assert payload.raw_fields["InvoiceDate"].value == "2026-08-18"


# ============================================================================
# Feature 3: Pydantic v2 Domain Models (>= 6 tests)
# ============================================================================

class TestFeature3PydanticDomainModels:
    """Feature 3: Pydantic v2 Domain Models and Validation."""

    def test_extracted_field_generic_typing_and_bounds(self) -> None:
        """Verify ExtractedField enforces confidence in [0, 1] and generic types."""
        f_str = ExtractedField[str](value="Test Vendor", confidence=0.95, raw_text="Test Vendor Inc")
        assert f_str.value == "Test Vendor"
        assert f_str.is_confident(0.90) is True
        assert f_str.is_confident(0.98) is False

        with pytest.raises(Exception):
            ExtractedField[float](value=100.0, confidence=1.5)  # Out of bounds

    def test_line_item_math_discrepancy_method(self) -> None:
        """Verify LineItem.has_math_discrepancy detects calculation mismatches."""
        item_correct = LineItem(description="Item 1", quantity=2.0, unit_price=50.0, total_amount=100.0)
        assert item_correct.has_math_discrepancy() is False

        item_wrong = LineItem(description="Item 2", quantity=2.0, unit_price=50.0, total_amount=120.0)
        assert item_wrong.has_math_discrepancy() is True

    def test_anomaly_flag_model_severity_validation(self) -> None:
        """Verify AnomalyFlag model correctly validates severity enums."""
        flag = AnomalyFlag(
            code="EXTREME_AMOUNT",
            message="Amount exceeds threshold",
            severity=AnomalySeverity.CRITICAL,
            details={"threshold": 50000.0},
        )
        assert flag.code == "EXTREME_AMOUNT"
        assert flag.severity == AnomalySeverity.CRITICAL

    def test_normalized_invoice_serialization_roundtrip(self, sample_normalized_invoice: NormalizedInvoice) -> None:
        """Verify NormalizedInvoice serializes to JSON and deserializes without data loss."""
        json_data = sample_normalized_invoice.model_dump_json()
        assert isinstance(json_data, str)

        parsed = NormalizedInvoice.model_validate_json(json_data)
        assert parsed.document_id == sample_normalized_invoice.document_id
        assert parsed.total_amount.value == sample_normalized_invoice.total_amount.value
        assert parsed.currency_iso == "USD"

    def test_normalized_invoice_validator_helper_sync(self) -> None:
        """Verify validator automatically populates vendor_raw, vendor_canonical, and currency_iso."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Google LLC"),
            invoice_id=ExtractedField[str](value="INV-100"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=500.0),
            currency=ExtractedField[str](value="€"),
        )
        assert inv.vendor_raw == "Google LLC"
        assert inv.vendor_canonical == "Google LLC"
        assert inv.currency_iso == "EUR"

    def test_raw_invoice_payload_creation_and_fields(self) -> None:
        """Verify RawInvoicePayload creates audit payload with correlation ID and confidence scores."""
        raw = RawInvoicePayload(
            filename="test.pdf",
            raw_fields={
                "VendorName": ExtractedField[str](value="Acme Corp", confidence=0.99),
                "InvoiceTotal": ExtractedField[float](value=250.0, confidence=0.98),
            },
            confidence_scores={"vendor_name": 0.99, "total_amount": 0.98},
        )
        assert raw.filename == "test.pdf"
        assert len(raw.raw_fields) == 2
        assert raw.confidence_scores["vendor_name"] == 0.99


# ============================================================================
# Feature 4: RapidFuzz Canonical Vendor Resolver (>= 6 tests)
# ============================================================================

class TestFeature4VendorMatcher:
    """Feature 4: RapidFuzz Canonical Vendor Matching Rules."""

    @pytest.fixture
    def matcher(self) -> VendorMatcherEngine:
        return VendorMatcherEngine()

    def test_vendor_match_exact_high_confidence(self, matcher: VendorMatcherEngine) -> None:
        """Verify exact/near-exact vendor strings match with score >= 85.0%."""
        canonical, vid, score, is_known = matcher.match_vendor("Amazon Web Services Inc.")
        assert canonical == "Amazon Web Services"
        assert vid == "VEND-AWS-001"
        assert score >= 85.0
        assert is_known is True

    def test_vendor_match_typo_resolution(self, matcher: VendorMatcherEngine) -> None:
        """Verify typo vendor string ('Microsft Corp Ireland') resolves to 'Microsoft Corporation'."""
        canonical, vid, score, is_known = matcher.match_vendor("Microsft Corp Ireland")
        assert canonical == "Microsoft Corporation"
        assert vid == "VEND-MSFT-001"
        assert score >= 75.0
        assert is_known is True

    def test_vendor_match_corporate_suffix_normalization(self, matcher: VendorMatcherEngine) -> None:
        """Verify corporate suffixes (Ltd, LLC, Corporation) resolve to canonical entry."""
        canonical, vid, score, is_known = matcher.match_vendor("Acme Corp Ltd")
        assert canonical == "Acme Corporation"
        assert is_known is True

        canonical2, _, _, _ = matcher.match_vendor("Acme Corporation LLC")
        assert canonical2 == "Acme Corporation"

    def test_vendor_match_thermal_receipt_alias(self, matcher: VendorMatcherEngine) -> None:
        """Verify noisy receipt string ('UBER *TRIP HELP.UBER') resolves to 'Uber Technologies'."""
        canonical, vid, score, is_known = matcher.match_vendor("UBER *TRIP HELP.UBER")
        assert canonical == "Uber Technologies"
        assert vid == "VEND-UBER-001"
        assert is_known is True

    def test_vendor_match_unrecognized_vendor_rejection(self, matcher: VendorMatcherEngine) -> None:
        """Verify unknown vendor (<70.0 score) is marked unrecognized with is_known=False."""
        canonical, vid, score, is_known = matcher.match_vendor("Luigi's Pizza & Catering")
        assert canonical == "Luigi's Pizza & Catering"
        assert vid is None
        assert score < 70.0
        assert is_known is False

    def test_vendor_match_empty_and_whitespace_handling(self, matcher: VendorMatcherEngine) -> None:
        """Verify empty and whitespace strings return 'Unknown Vendor' and score 0.0."""
        canonical, vid, score, is_known = matcher.match_vendor("")
        assert canonical == "Unknown Vendor"
        assert score == 0.0
        assert is_known is False

        canonical2, _, score2, _ = matcher.match_vendor("   ")
        assert canonical2 == "Unknown Vendor"
        assert score2 == 0.0


# ============================================================================
# Feature 5: 11-Category Spend Taxonomy Classifier (>= 6 tests)
# ============================================================================

class TestFeature5SpendTaxonomy:
    """Feature 5: 11-Category Spend Taxonomy Classification."""

    def test_category_cloud_services_classification(self) -> None:
        """Verify cloud hosting keywords classify as 'Cloud Services'."""
        cat1 = SpendTaxonomyEngine.classify(vendor_name="Amazon Web Services", description="EC2 Compute Instances")
        assert cat1 == "Cloud Services"

        cat2 = SpendTaxonomyEngine.classify(vendor_name="Google Cloud Platform", description="Cloud Storage Bucket")
        assert cat2 == "Cloud Services"

    def test_category_software_subscriptions(self) -> None:
        """Verify SaaS and software tools classify as 'Software Subscriptions'."""
        cat1 = SpendTaxonomyEngine.classify(vendor_name="Microsoft Corporation", description="Microsoft 365 Business Standard")
        assert cat1 == "Software Subscriptions"

        cat2 = SpendTaxonomyEngine.classify(vendor_name="Slack Technologies", description="Enterprise Grid Annual Subscription")
        assert cat2 == "Software Subscriptions"

    def test_category_travel_transportation(self) -> None:
        """Verify airline and ride-share services classify as 'Travel & Transportation'."""
        cat1 = SpendTaxonomyEngine.classify(vendor_name="Uber Technologies", description="UberX Trip Downtown")
        assert cat1 == "Travel & Transportation"

        cat2 = SpendTaxonomyEngine.classify(vendor_name="Delta Air Lines", description="Flight Charter")
        assert cat2 == "Travel & Transportation"

    def test_category_office_supplies(self) -> None:
        """Verify office furniture and stationery classify as 'Office Supplies & Equipment'."""
        cat = SpendTaxonomyEngine.classify(vendor_name="Acme Corporation", description="Office paper and stationery")
        assert cat == "Office Supplies & Equipment"

    def test_category_meals_entertainment(self) -> None:
        """Verify food, catering, and dining classify as 'Meals & Entertainment'."""
        cat = SpendTaxonomyEngine.classify(vendor_name="Luigi's Pizza & Catering", description="Team Lunch Assortment")
        assert cat == "Meals & Entertainment"

    def test_category_taxonomy_completeness_11_categories(self) -> None:
        """Verify all 11 canonical categories are defined in taxonomy."""
        all_cats = SpendTaxonomyEngine.all_categories()
        assert len(all_cats) == 11
        expected = [
            "Cloud Services", "Software Subscriptions", "Travel & Transportation",
            "Office Supplies & Equipment", "Meals & Entertainment", "Professional Services",
            "Utilities", "Marketing & Advertising", "Hardware & Equipment", "Facilities",
            "Other / Miscellaneous"
        ]
        for exp in expected:
            assert exp in all_cats


# ============================================================================
# Feature 6: ISO Date & Currency Parsing & Normalization (>= 6 tests)
# ============================================================================

class TestFeature6DateAndCurrencyParsing:
    """Feature 6: ISO Date (YYYY-MM-DD) and Currency (ISO 4217) Normalization."""

    def test_iso_date_parsing_standard_iso8601(self) -> None:
        """Verify standard ISO 8601 string parsing."""
        assert DateCurrencyStandardizer.parse_iso_date("2026-08-01") == "2026-08-01"
        assert DateCurrencyStandardizer.parse_iso_date("2026/08/15") == "2026-08-15"

    def test_iso_date_parsing_european_format(self) -> None:
        """Verify European dot DD.MM.YYYY format parsing."""
        assert DateCurrencyStandardizer.parse_iso_date("15.08.2026") == "2026-08-15"
        assert DateCurrencyStandardizer.parse_iso_date("01-09-2026") == "2026-09-01"

    def test_iso_date_parsing_us_format(self) -> None:
        """Verify US slash MM/DD/YYYY format parsing."""
        assert DateCurrencyStandardizer.parse_iso_date("08/15/2026") == "2026-08-15"

    def test_iso_date_parsing_alphanumeric_month(self) -> None:
        """Verify alphanumeric month date parsing (e.g. August 15, 2026)."""
        assert DateCurrencyStandardizer.parse_iso_date("August 15, 2026") == "2026-08-15"
        assert DateCurrencyStandardizer.parse_iso_date("15 August 2026") == "2026-08-15"

    def test_iso_currency_code_conversion(self) -> None:
        """Verify currency symbols and text convert to ISO 4217 codes."""
        assert DateCurrencyStandardizer.standardize_currency("$") == "USD"
        assert DateCurrencyStandardizer.standardize_currency("€") == "EUR"
        assert DateCurrencyStandardizer.standardize_currency("£") == "GBP"
        assert DateCurrencyStandardizer.standardize_currency("¥") == "JPY"
        assert DateCurrencyStandardizer.standardize_currency("EUR") == "EUR"

    def test_european_number_decimal_comma_normalization(self) -> None:
        """Verify European comma decimals (2.180,75) parse to standard float (2180.75)."""
        assert DateCurrencyStandardizer.parse_numeric_amount("€2.180,75") == 2180.75
        assert DateCurrencyStandardizer.parse_numeric_amount("150,000") == 150000.0
        assert DateCurrencyStandardizer.parse_numeric_amount("$1,420.50") == 1420.50


# ============================================================================
# Feature 7: Cosmos DB Dual-Storage Repository Interface (>= 5 tests)
# ============================================================================

class TestFeature7DualStorageRepository:
    """Feature 7: Cosmos DB Dual-Storage Architecture (raw_extractions vs normalized_invoices)."""

    @pytest.fixture
    def repo(self) -> DualStorageRepository:
        return DualStorageRepository()

    def test_dual_storage_persist_raw_extraction(self, repo: DualStorageRepository) -> None:
        """Verify raw extraction payload is stored in raw_extractions container."""
        payload = RawInvoicePayload(
            document_id="doc-raw-001",
            correlation_id="corr-raw-001",
            filename="invoice.pdf",
            raw_fields={"VendorName": ExtractedField[str](value="Test Vendor")},
        )
        repo.save_raw(payload)
        retrieved = repo.get_raw_by_document_id("doc-raw-001")
        assert retrieved is not None
        assert retrieved.document_id == "doc-raw-001"
        assert retrieved.filename == "invoice.pdf"

    def test_dual_storage_persist_normalized_invoice(self, repo: DualStorageRepository) -> None:
        """Verify normalized invoice is stored in normalized_invoices container."""
        invoice = NormalizedInvoice(
            id="inv-norm-001",
            document_id="doc-norm-001",
            correlation_id="corr-norm-001",
            vendor_name=ExtractedField[str](value="Acme Corp"),
            invoice_id=ExtractedField[str](value="INV-100"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=500.0),
        )
        repo.save_normalized(invoice)
        retrieved = repo.get_normalized_by_id("inv-norm-001")
        assert retrieved is not None
        assert retrieved.id == "inv-norm-001"
        assert retrieved.total_amount.value == 500.0

    def test_dual_storage_correlation_id_query_linkage(self, repo: DualStorageRepository) -> None:
        """Verify querying by correlation_id returns both raw and normalized records."""
        shared_corr = "corr-shared-123"
        raw = RawInvoicePayload(document_id="doc-001", correlation_id=shared_corr, filename="a.pdf")
        norm = NormalizedInvoice(
            id="inv-001", document_id="doc-001", correlation_id=shared_corr,
            vendor_name=ExtractedField[str](value="Acme"),
            invoice_id=ExtractedField[str](value="INV-1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=100.0),
        )
        repo.save_raw(raw)
        repo.save_normalized(norm)

        raws, norms = repo.get_by_correlation_id(shared_corr)
        assert len(raws) == 1
        assert len(norms) == 1
        assert raws[0].document_id == "doc-001"
        assert norms[0].id == "inv-001"

    def test_dual_storage_audit_immutability_isolation(self, repo: DualStorageRepository) -> None:
        """Verify modifying normalized record does not alter raw extraction in storage."""
        raw = RawInvoicePayload(
            document_id="doc-imm-001",
            filename="orig.pdf",
            raw_fields={"VendorName": ExtractedField[str](value="Original Raw Vendor")},
        )
        repo.save_raw(raw)

        norm = NormalizedInvoice(
            id="norm-imm-001",
            document_id="doc-imm-001",
            vendor_name=ExtractedField[str](value="Canonical Normalized Vendor"),
            invoice_id=ExtractedField[str](value="INV-1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=100.0),
        )
        repo.save_normalized(norm)

        # Mutate normalized
        norm.vendor_canonical = "Modified Vendor"
        repo.save_normalized(norm)

        raw_retrieved = repo.get_raw_by_document_id("doc-imm-001")
        assert raw_retrieved.raw_fields["VendorName"].value == "Original Raw Vendor"

    def test_dual_storage_delete_and_listing(self, repo: DualStorageRepository) -> None:
        """Verify listing and deleting records in repository."""
        inv1 = NormalizedInvoice(
            id="inv-del-1", document_id="doc-1",
            vendor_name=ExtractedField[str](value="V1"),
            invoice_id=ExtractedField[str](value="I1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=10.0),
        )
        repo.save_normalized(inv1)
        assert len(repo.list_all_normalized()) == 1

        deleted = repo.delete("inv-del-1")
        assert deleted is True
        assert len(repo.list_all_normalized()) == 0


# ============================================================================
# Feature 8: 7-Day Sliding Window Duplicate Detection Rules (>= 6 tests)
# ============================================================================

class TestFeature8DuplicateEngine:
    """Feature 8: 7-Day Sliding Window Duplicate Detection Engine."""

    @pytest.fixture
    def engine(self) -> DuplicateDetectionEngine:
        return DuplicateDetectionEngine(window_days=7)

    @pytest.fixture
    def base_invoice(self) -> NormalizedInvoice:
        return NormalizedInvoice(
            id="inv-base-005",
            document_id="doc-base-005",
            vendor_name=ExtractedField[str](value="Acme Corp Ltd"),
            vendor_raw="Acme Corp Ltd",
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-101"),
            invoice_date=ExtractedField[str](value="2026-08-10"),
            total_amount=ExtractedField[float](value=500.00),
            currency_iso="USD",
        )

    def test_duplicate_exact_same_day(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Verify same vendor + identical amount on Day 0 is flagged as duplicate."""
        candidate = NormalizedInvoice(
            id="inv-cand-day0",
            document_id="doc-cand-day0",
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-101-DUP"),
            invoice_date=ExtractedField[str](value="2026-08-10"),  # T + 0d
            total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, dup_id, reason, _ = engine.evaluate_duplicate(candidate, [base_invoice])
        assert is_dup is True
        assert dup_id == "inv-base-005"
        assert "Duplicate identified" in reason

    def test_duplicate_sliding_window_positive_3_days(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Verify submission 3 days later (within 7 days) is flagged as duplicate (INV-006 scenario)."""
        candidate = NormalizedInvoice(
            id="inv-cand-day3",
            document_id="doc-cand-day3",
            vendor_name=ExtractedField[str](value="Acme Corporation LLC"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-102"),
            invoice_date=ExtractedField[str](value="2026-08-13"),  # T + 3d
            total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, dup_id, _, details = engine.evaluate_duplicate(candidate, [base_invoice])
        assert is_dup is True
        assert dup_id == "inv-base-005"
        assert details["day_difference"] == 3

    def test_duplicate_sliding_window_negative_36_days(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Verify submission 36 days later (outside 7 days) is NOT duplicate (INV-007 scenario)."""
        candidate = NormalizedInvoice(
            id="inv-cand-day36",
            document_id="doc-cand-day36",
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-103"),
            invoice_date=ExtractedField[str](value="2026-09-15"),  # T + 36d
            total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, dup_id, _, _ = engine.evaluate_duplicate(candidate, [base_invoice])
        assert is_dup is False
        assert dup_id is None

    def test_duplicate_immunity_different_amounts(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Verify different amounts from same vendor are NOT flagged as duplicates."""
        candidate = NormalizedInvoice(
            id="inv-cand-diff-amt",
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-104"),
            invoice_date=ExtractedField[str](value="2026-08-12"),  # T + 2d
            total_amount=ExtractedField[float](value=550.00),  # Different amount
        )
        is_dup, _, _, _ = engine.evaluate_duplicate(candidate, [base_invoice])
        assert is_dup is False

    def test_duplicate_immunity_different_vendors(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Verify identical amounts from different vendors are NOT flagged as duplicates."""
        candidate = NormalizedInvoice(
            id="inv-cand-diff-vend",
            vendor_name=ExtractedField[str](value="Amazon Web Services"),
            vendor_canonical="Amazon Web Services",
            invoice_id=ExtractedField[str](value="AWS-999"),
            invoice_date=ExtractedField[str](value="2026-08-10"),
            total_amount=ExtractedField[float](value=500.00),  # Same amount, diff vendor
        )
        is_dup, _, _, _ = engine.evaluate_duplicate(candidate, [base_invoice])
        assert is_dup is False

    def test_duplicate_enrichment_fields(self, engine: DuplicateDetectionEngine, base_invoice: NormalizedInvoice) -> None:
        """Verify duplicate detection outputs rich diagnostic metadata."""
        candidate = NormalizedInvoice(
            id="inv-cand-enrich",
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-105"),
            invoice_date=ExtractedField[str](value="2026-08-14"),
            total_amount=ExtractedField[float](value=500.00),
        )
        is_dup, dup_id, reason, details = engine.evaluate_duplicate(candidate, [base_invoice])
        assert is_dup is True
        assert details["matched_vendor"] == "Acme Corporation"
        assert details["matched_amount"] == 500.00
        assert details["day_difference"] == 4


# ============================================================================
# Feature 9: Multi-Type Anomaly Detection Engine (>= 6 tests)
# ============================================================================

class TestFeature9AnomalyEngine:
    """Feature 9: Multi-Type Anomaly Detection Rules and Risk Scoring."""

    @pytest.fixture
    def anomaly_engine(self) -> AnomalyDetectionEngine:
        return AnomalyDetectionEngine(extreme_amount_threshold=50000.0)

    def test_anomaly_extreme_amount_outlier(self, anomaly_engine: AnomalyDetectionEngine) -> None:
        """Verify extreme amount outlier (e.g. $1.25M) raises CRITICAL EXTREME_AMOUNT anomaly."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Delta Air Lines Inc"),
            vendor_canonical="Delta Air Lines",
            invoice_id=ExtractedField[str](value="DAL-001"),
            invoice_date=ExtractedField[str](value="2026-08-12"),
            total_amount=ExtractedField[float](value=1250000.00),  # Outlier
        )
        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv)
        assert has_anom is True
        assert any(f.code == "EXTREME_AMOUNT" for f in flags)
        assert any(f.severity == AnomalySeverity.CRITICAL for f in flags)
        assert risk >= 0.60

    def test_anomaly_unrecognized_vendor(self, anomaly_engine: AnomalyDetectionEngine) -> None:
        """Verify unregistered vendor (<70% score) raises WARNING UNRECOGNIZED_VENDOR anomaly."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Luigi's Pizza & Catering"),
            vendor_raw="Luigi's Pizza & Catering",
            vendor_canonical="Luigi's Pizza & Catering",
            is_known_vendor=False,
            vendor_match_score=45.0,
            invoice_id=ExtractedField[str](value="LPC-101"),
            invoice_date=ExtractedField[str](value="2026-08-14"),
            total_amount=ExtractedField[float](value=85.50),
        )
        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv)
        assert has_anom is True
        assert any(f.code == "UNRECOGNIZED_VENDOR" for f in flags)
        assert risk >= 0.25

    def test_anomaly_subtotal_tax_math_discrepancy(self, anomaly_engine: AnomalyDetectionEngine) -> None:
        """Verify subtotal + tax != total raises MATH_DISCREPANCY anomaly."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-MATH"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            subtotal_amount=ExtractedField[float](value=100.00),
            tax_amount=ExtractedField[float](value=10.00),
            total_amount=ExtractedField[float](value=150.00),  # Expected 110.00, actual 150.00
        )
        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv)
        assert has_anom is True
        assert any(f.code == "MATH_DISCREPANCY" for f in flags)

    def test_anomaly_line_item_math_discrepancy(self, anomaly_engine: AnomalyDetectionEngine) -> None:
        """Verify line item qty * unit_price != total_amount raises LINE_ITEM_MATH_DISCREPANCY."""
        inv = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ACME-ITEM"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=100.00),
            line_items=[
                LineItem(description="Item A", quantity=2.0, unit_price=40.0, total_amount=100.0)  # 2*40 != 100
            ],
        )
        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv)
        assert has_anom is True
        assert any(f.code == "LINE_ITEM_MATH_DISCREPANCY" for f in flags)

    def test_anomaly_zero_and_negative_amounts(self, anomaly_engine: AnomalyDetectionEngine) -> None:
        """Verify zero total and negative credit notes trigger corresponding anomaly flags."""
        inv_zero = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="ZERO-1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=0.00),
        )
        has_anom_z, flags_z, _ = anomaly_engine.evaluate_anomalies(inv_zero)
        assert has_anom_z is True
        assert any(f.code == "ZERO_TOTAL" for f in flags_z)

        inv_neg = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Acme Corporation"),
            vendor_canonical="Acme Corporation",
            invoice_id=ExtractedField[str](value="NEG-1"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            total_amount=ExtractedField[float](value=-50.00),
        )
        has_anom_n, flags_n, _ = anomaly_engine.evaluate_anomalies(inv_neg)
        assert has_anom_n is True
        assert any(f.code == "NEGATIVE_AMOUNT" for f in flags_n)

    def test_anomaly_composite_risk_score_clamping(self, anomaly_engine: AnomalyDetectionEngine) -> None:
        """Verify composite risk score combines multiple risk factors and clamps to [0.0, 1.0]."""
        inv_multi = NormalizedInvoice(
            vendor_name=ExtractedField[str](value="Unknown Shady Supplier"),
            vendor_raw="Unknown Shady Supplier",
            is_known_vendor=False,
            vendor_match_score=20.0,
            invoice_id=ExtractedField[str](value="RISK-99"),
            invoice_date=ExtractedField[str](value="2026-08-01"),
            subtotal_amount=ExtractedField[float](value=100000.0),
            tax_amount=ExtractedField[float](value=10000.0),
            total_amount=ExtractedField[float](value=2000000.0),  # Extreme + math error + unknown vendor
            is_duplicate=True,
            duplicate_reason="Repeated identical submission",
        )
        has_anom, flags, risk = anomaly_engine.evaluate_anomalies(inv_multi)
        assert has_anom is True
        assert len(flags) >= 3
        assert 0.0 <= risk <= 1.0
        assert risk >= 0.85
