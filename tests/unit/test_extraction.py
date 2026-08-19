"""
Unit Tests for Extraction Engine and Fallback Services.
Document Intelligence Pipeline - Milestone 1
"""

from unittest.mock import MagicMock

import pytest

from src.config import Settings
from src.core.models import ExtractedField, NormalizedInvoice, RawInvoicePayload
from src.services.extraction.azure_client import (
    AzureAnalysisError,
    AzureConfigurationError,
    AzureDocumentIntelligenceClient,
)
from src.services.extraction.mock_extractor import (
    FIXTURE_REGISTRY,
    MockExtractionService,
)
from src.services.extraction.service import ExtractionService


class TestMockExtractor:
    @pytest.mark.asyncio
    async def test_extract_from_pdf_bytes(self, sample_pdf_bytes: bytes):
        extractor = MockExtractionService()
        result = await extractor.extract(
            file_bytes=sample_pdf_bytes,
            filename="aws_invoice.pdf",
            document_id="doc-pdf-001",
            correlation_id="corr-001",
            storage_path="data/uploads/doc-pdf-001_aws_invoice.pdf",
        )
        assert result.document_id == "doc-pdf-001"
        assert result.vendor_name.value != ""
        assert result.total_amount.value > 0
        assert result.status in ["SUCCESS", "NEEDS_REVIEW"]
        assert 0.0 <= result.confidence_score <= 1.0

    @pytest.mark.asyncio
    async def test_extract_from_image_bytes(self, sample_png_bytes: bytes):
        extractor = MockExtractionService()
        result = await extractor.extract(
            file_bytes=sample_png_bytes,
            filename="receipt.png",
            document_id="doc-png-001",
            correlation_id="corr-002",
            storage_path="data/uploads/doc-png-001_receipt.png",
        )
        assert result.document_id == "doc-png-001"
        assert result.status in ["SUCCESS", "NEEDS_REVIEW"]
        assert result.confidence_score >= 0.0

    def test_fixture_catalog_all_ten_benchmarks(self):
        extractor = MockExtractionService()
        for fixture_name, expected_data in FIXTURE_REGISTRY.items():
            dummy_bytes = f"benchmark content for {fixture_name}".encode()
            raw = extractor.extract_document(
                file_bytes=dummy_bytes,
                filename=fixture_name,
            )
            assert raw.raw_fields["VendorName"].value == expected_data["vendor_name"]
            assert raw.raw_fields["InvoiceId"].value == expected_data["invoice_id"]
            assert raw.raw_fields["InvoiceDate"].value == expected_data["invoice_date"]
            assert raw.raw_fields["InvoiceTotal"].value == expected_data["total_amount"]
            assert len(raw.raw_items) == len(expected_data.get("line_items", []))

    def test_fixture_matching_by_hash(self):
        extractor = MockExtractionService()
        test_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        extractor.register_fixture_by_hash(
            test_hash,
            {
                "vendor_name": "Registered Hash Vendor Inc",
                "invoice_id": "HASH-9901",
                "invoice_date": "2026-08-10",
                "total_amount": 999.00,
            },
        )
        # Call with exact matching hash
        raw = extractor.extract_document(file_bytes=b"", filename="unknown.pdf")
        # Empty byte hash is e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        assert raw.raw_fields["VendorName"].value == "Registered Hash Vendor Inc"
        assert raw.raw_fields["InvoiceId"].value == "HASH-9901"
        assert raw.extraction_engine == "mock_fixture_hash"

    def test_heuristic_regex_parsing(self):
        extractor = MockExtractionService()
        text = (
            "Invoice from Acme Corporation\n"
            "Invoice #: INV-9988\n"
            "Date: 2026-08-10\n"
            "Payment Due: 2026-09-10\n"
            "Subtotal: $450.00\n"
            "Tax: $50.00\n"
            "Total Amount Due: $500.00\n"
        )
        fields = extractor._parse_heuristic_text(text)
        assert "Acme" in fields["vendor_name"].value
        assert fields["invoice_id"].value == "INV-9988"
        assert fields["invoice_date"].value == "2026-08-10"
        assert fields["due_date"].value == "2026-09-10"
        assert fields["total_amount"].value == 500.00
        assert fields["tax_amount"].value == 50.00
        assert fields["subtotal_amount"].value == 450.00

    def test_heuristic_european_currency_formatting(self):
        extractor = MockExtractionService()
        text = (
            "Google Ireland Limited\n"
            "Rechnung GOOG-EU-2026\n"
            "Datum: 05.08.2026\n"
            "Gesamtbetrag: 2.180,75 €\n"
        )
        fields = extractor._parse_heuristic_text(text)
        assert fields["total_amount"].value == 2180.75
        assert fields["currency"].value == "EUR"

    def test_heuristic_jpy_zero_decimal(self):
        extractor = MockExtractionService()
        text = (
            "Slack Technologies LLC\n"
            "Invoice Number: SLACK-JP-5541\n"
            "Invoice Date: August 15, 2026\n"
            "Total: ¥150,000\n"
        )
        fields = extractor._parse_heuristic_text(text)
        assert fields["total_amount"].value == 150000.0
        assert fields["currency"].value == "JPY"

    def test_heuristic_table_line_items(self):
        extractor = MockExtractionService()
        text = (
            "From: Acme Corp\n"
            "Invoice: INV-100\n"
            "Date: 2026-08-01\n"
            "Widget Alpha  2.0  $50.00  $100.00\n"
            "Widget Beta  1.0  $250.00  $250.00\n"
            "Total: $350.00\n"
        )
        raw = extractor.extract_document(file_bytes=text.encode("utf-8"), filename="custom.txt")
        assert len(raw.raw_items) >= 2
        assert raw.raw_fields["InvoiceTotal"].value == 350.00


class TestAzureClient:
    def test_azure_client_availability(self):
        client_no_creds = AzureDocumentIntelligenceClient(endpoint=None, key=None)
        assert client_no_creds.is_available() is False

        client_dummy = AzureDocumentIntelligenceClient(
            endpoint="https://test.cognitiveservices.azure.com/",
            key="secret-key-12345",
        )
        # Will be True if SDK installed, False if not
        # Either way is_available() does not throw exception
        assert isinstance(client_dummy.is_available(), bool)

    def test_azure_client_missing_config_raises(self):
        client = AzureDocumentIntelligenceClient(endpoint=None, key=None)
        with pytest.raises(AzureConfigurationError):
            client._get_client()

    def test_parse_azure_result_mocked(self):
        client = AzureDocumentIntelligenceClient(
            endpoint="https://test.cognitiveservices.azure.com/",
            key="secret-key",
        )

        # Build mock SDK AnalyzeResult
        mock_result = MagicMock()
        mock_doc = MagicMock()

        # Mock field objects
        vendor_field = MagicMock()
        vendor_field.value_string = "Amazon Web Services Inc."
        vendor_field.confidence = 0.98
        vendor_field.bounding_regions = [MagicMock(polygon=[0.1, 0.1, 0.5, 0.1, 0.5, 0.3, 0.1, 0.3], page_number=1)]

        total_field = MagicMock()
        total_field.value_currency = MagicMock(amount=1420.50, currency_symbol="$")
        total_field.confidence = 0.99
        total_field.bounding_regions = []

        inv_id_field = MagicMock()
        inv_id_field.value_string = "INV-2026-001"
        inv_id_field.confidence = 0.95
        inv_id_field.bounding_regions = []

        date_field = MagicMock()
        date_field.value_date = "2026-08-01"
        date_field.confidence = 0.97
        date_field.bounding_regions = []

        # Mock line item
        item_obj = MagicMock()
        item_obj.confidence = 0.95
        item_obj.value_object = {
            "Description": MagicMock(value_string="Cloud Compute"),
            "Quantity": MagicMock(value_number=2.0),
            "UnitPrice": MagicMock(value_currency=MagicMock(amount=50.0)),
            "Amount": MagicMock(value_currency=MagicMock(amount=100.0)),
        }
        item_obj.bounding_regions = []

        items_field = MagicMock()
        items_field.value_array = [item_obj]

        mock_doc.fields = {
            "VendorName": vendor_field,
            "InvoiceTotal": total_field,
            "InvoiceId": inv_id_field,
            "InvoiceDate": date_field,
            "Items": items_field,
        }
        mock_result.documents = [mock_doc]
        mock_result.content = "Sample raw document text"

        parsed = client._parse_azure_result(
            mock_result, "doc-123", "corr-456", "aws.pdf"
        )
        assert parsed.document_id == "doc-123"
        assert parsed.raw_fields["VendorName"].value == "Amazon Web Services Inc."
        assert parsed.raw_fields["VendorName"].confidence == 0.98
        assert parsed.raw_fields["InvoiceTotal"].value == 1420.50
        assert len(parsed.raw_items) == 1
        assert parsed.raw_items[0].description == "Cloud Compute"
        assert parsed.raw_items[0].total_amount == 100.0


class TestExtractionService:
    def test_service_routing_mock_forced(self, test_settings: Settings):
        service = ExtractionService(settings_obj=test_settings)
        assert service.should_use_mock(force_mock=False) is True
        assert service.should_use_mock(force_mock=True) is True

    def test_service_sync_extraction(self, test_settings: Settings, sample_pdf_bytes: bytes):
        service = ExtractionService(settings_obj=test_settings)
        invoice = service.extract_invoice_sync(
            file_bytes=sample_pdf_bytes,
            filename="inv_001_standard_aws.pdf",
            document_id="doc-sync-01",
        )
        assert isinstance(invoice, NormalizedInvoice)
        assert invoice.document_id == "doc-sync-01"
        assert invoice.vendor_name.value == "Amazon Web Services Inc."
        assert invoice.total_amount.value == 1420.50

    @pytest.mark.asyncio
    async def test_service_async_extraction(self, test_settings: Settings, sample_pdf_bytes: bytes):
        service = ExtractionService(settings_obj=test_settings)
        invoice = await service.extract_invoice(
            file_bytes=sample_pdf_bytes,
            filename="inv_001_standard_aws.pdf",
            document_id="doc-async-01",
        )
        assert isinstance(invoice, NormalizedInvoice)
        assert invoice.document_id == "doc-async-01"
        assert invoice.status in ["SUCCESS", "NEEDS_REVIEW"]

    def test_service_failover_on_azure_error(self, test_settings: Settings, sample_pdf_bytes: bytes):
        mock_azure = MagicMock()
        mock_azure.is_available.return_value = True
        mock_azure.analyze_document.side_effect = AzureAnalysisError("Azure service temporary failure")

        settings_live = Settings(
            USE_MOCK_AZURE=False,
            AZURE_FORM_RECOGNIZER_ENDPOINT="https://live-endpoint.cognitiveservices.azure.com/",
            AZURE_FORM_RECOGNIZER_KEY="valid-key",
        )

        service = ExtractionService(
            azure_client=mock_azure,
            settings_obj=settings_live,
        )

        # Extraction should not raise, but gracefully fallback to Mock
        raw = service.extract_raw(
            file_bytes=sample_pdf_bytes,
            filename="inv_001_standard_aws.pdf",
            force_mock=False,
            storage_path="data/uploads/test.pdf",
        )
        assert raw.raw_fields["VendorName"].value == "Amazon Web Services Inc."
        assert "mock" in raw.extraction_engine
        assert raw.storage_path == "data/uploads/test.pdf"

    def test_service_live_azure_success(self, sample_pdf_bytes: bytes):
        mock_azure = MagicMock()
        mock_azure.is_available.return_value = True
        mock_payload = RawInvoicePayload(
            document_id="doc-live-1",
            correlation_id="corr-live-1",
            filename="invoice.pdf",
            raw_fields={
                "VendorName": ExtractedField[str](value="Live Azure Vendor", confidence=0.99),
                "InvoiceId": ExtractedField[str](value="AZ-100", confidence=0.95),
                "InvoiceTotal": ExtractedField[float](value=500.0, confidence=0.98),
            },
            extraction_engine="azure_prebuilt_invoice",
        )
        mock_azure.analyze_document.return_value = mock_payload

        settings_live = Settings(
            USE_MOCK_AZURE=False,
            AZURE_FORM_RECOGNIZER_ENDPOINT="https://live.cognitiveservices.azure.com/",
            AZURE_FORM_RECOGNIZER_KEY="valid-key",
        )

        service = ExtractionService(
            azure_client=mock_azure,
            settings_obj=settings_live,
        )

        assert service.should_use_mock(force_mock=False) is False
        norm = service.extract_invoice_sync(
            file_bytes=sample_pdf_bytes,
            filename="invoice.pdf",
            document_id="doc-live-1",
        )
        assert norm.vendor_name.value == "Live Azure Vendor"
        assert norm.total_amount.value == 500.0

    def test_service_anomalies_generation(self):
        service = ExtractionService()
        raw_zero = RawInvoicePayload(
            document_id="doc-zero",
            correlation_id="corr-zero",
            filename="zero.pdf",
            raw_fields={
                "VendorName": ExtractedField[str](value="Vendor Zero", confidence=0.5),
                "InvoiceId": ExtractedField[str](value="INV-0", confidence=0.5),
                "InvoiceTotal": ExtractedField[float](value=0.0, confidence=0.5),
                "SubTotal": ExtractedField[float](value=100.0, confidence=0.5),
                "TotalTax": ExtractedField[float](value=20.0, confidence=0.5),
            },
        )
        norm = service._raw_to_normalized(raw_zero)
        assert norm.status == "NEEDS_REVIEW"
        codes = [a.code for a in norm.anomalies]
        assert "LOW_CONFIDENCE" in codes
        assert "ZERO_TOTAL" in codes
        assert "MATH_DISCREPANCY" in codes


class TestMockExtractorEdgeCases:
    def test_flatedecode_stream_decompression(self):
        extractor = MockExtractionService()
        import zlib
        stream_content = b"BT /F1 12 Tf (Invoice from Stream Corp) Tj (Total: $750.00) Tj ET"
        compressed = zlib.compress(stream_content)
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Length " + str(len(compressed)).encode() + b" >>\nstream\n" + compressed + b"\nendstream\nendobj\n%%EOF"

        raw = extractor.extract_document(file_bytes=pdf_bytes, filename="stream_decompressed.pdf")
        assert "Stream" in raw.raw_fields["VendorName"].value or raw.raw_fields["InvoiceTotal"].value == 750.0

    def test_binary_string_extraction(self):
        extractor = MockExtractionService()
        binary_data = b"\x00\x01\x02Vendor: Binary Systems Inc\x00\x00Total: $120.00\xff\xfe"
        raw = extractor.extract_document(file_bytes=binary_data, filename="binary.bin")
        assert raw.raw_fields["VendorName"].value != ""
        assert raw.raw_fields["InvoiceTotal"].value > 0

    def test_spelled_out_and_slash_dates(self):
        extractor = MockExtractionService()
        text_dates = "Vendor: Corp A\nInvoice Date: 12 August 2026\nPayment Due: 09/15/2026\nTotal: $100.00\n"
        fields = extractor._parse_heuristic_text(text_dates)
        assert fields["invoice_date"].value == "2026-08-12"
        assert fields["due_date"].value == "2026-09-15"


class TestAzureClientErrorHandling:
    def test_azure_client_empty_result(self):
        client = AzureDocumentIntelligenceClient(endpoint="https://test.cognitiveservices.azure.com/", key="key")
        mock_result = MagicMock()
        mock_result.documents = []
        mock_result.content = "Empty content"

        raw = client._parse_azure_result(mock_result, "doc-empty", "corr-empty", "empty.pdf")
        assert raw.document_id == "doc-empty"
        assert len(raw.raw_fields) == 0

    def test_azure_client_extract_value_branches(self):
        client = AzureDocumentIntelligenceClient(endpoint="https://test.cognitiveservices.azure.com/", key="key")

        # Test float from content string
        mock_content_field = MagicMock(spec=[])
        mock_content_field.content = "$1,500.75"
        val = client._extract_value(mock_content_field, float)
        assert val == 1500.75

        # Test invalid content string
        mock_bad_content = MagicMock(spec=[])
        mock_bad_content.content = "Not a number"
        assert client._extract_value(mock_bad_content, float) is None

        # Test None field
        assert client._extract_value(None, str) is None

