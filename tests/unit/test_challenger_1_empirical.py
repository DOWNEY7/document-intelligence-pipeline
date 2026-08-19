"""
tests/unit/test_challenger_1_empirical.py

Empirical Challenger 1 Adversarial & Boundary Stress Test Suite.
Adversarially probes:
1. Security & Path Traversal Fuzzing
2. File Upload Payload, Size & Extension Validation
3. Corrupted Streams & Header Fuzzing (PDF, PNG, JPG, TIFF)
4. Malformed API Requests & Boundary Invariants
5. Dynamic Heuristic Extraction & Arithmetic Precision
6. Storage Manager Resilience & Filename Boundary Conditions
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config import Settings
from src.core.storage import StorageManager, sanitize_filename
from src.services.extraction.azure_client import AzureDocumentIntelligenceClient
from src.services.extraction.mock_extractor import MockExtractionService
from src.services.extraction.service import ExtractionService

# ============================================================================
# Section 1: Security & Path Traversal Fuzzing
# ============================================================================

class TestSecurityAndPathTraversal:
    """Security tests against directory traversal, injection payloads, and reserved filenames."""

    @pytest.mark.parametrize(
        "malicious_name",
        [
            "../../etc/passwd",
            "..\\..\\windows\\win.ini",
            "....//....//boot.ini",
            "%2e%2e%2f%2e%2e%2fsecret.pdf",
            "invoice/../../../etc/shadow.pdf",
            "C:\\Windows\\System32\\drivers\\etc\\hosts.pdf",
            "CON.pdf",
            "PRN.png",
            "NUL.jpg",
            "AUX.pdf",
            "COM1.pdf",
            "<script>alert('xss')</script>.pdf",
            "invoice'; DROP TABLE invoices;--.pdf",
            "invoice\x00nullbyte.pdf",
            "invoice\r\nnewline.pdf",
            "   leading_trailing_spaces.pdf   ",
            "..",
            ".",
            "",
        ],
    )
    def test_filename_sanitization_invariants(self, malicious_name: str):
        """Sanitized filenames must never contain directory traversal sequences or control characters."""
        cleaned = sanitize_filename(malicious_name)
        assert "/" not in cleaned
        assert "\\" not in cleaned
        assert ".." not in cleaned
        assert "\x00" not in cleaned
        assert "\r" not in cleaned and "\n" not in cleaned
        assert len(cleaned) > 0

    @pytest.mark.parametrize(
        "traversal_payload",
        [
            "../../etc/passwd.pdf",
            "..\\..\\windows\\win.ini.pdf",
            "....//....//boot.ini.pdf",
            "/etc/shadow.pdf",
        ],
    )
    def test_upload_directory_traversal_api_isolation(
        self, client: TestClient, traversal_payload: str, temp_storage_dir: Path, test_settings: Settings
    ):
        """Verify multipart upload containing path traversal payload stores file strictly within target directory."""
        file_bytes = b"%PDF-1.4 Minimal content\nVendor: Safe Corp\nInvoice ID: INV-TRAV-01\nTotal: $100.00"
        files = {"file": (traversal_payload, file_bytes, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        doc_id = data["document_id"]

        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        found = manager.get_file_path(doc_id)
        assert found is not None
        assert str(temp_storage_dir.resolve()) in str(found.resolve())

    @pytest.mark.parametrize(
        "bad_doc_id",
        [
            "../../etc/passwd",
            "..\\..\\windows\\win.ini",
            "../uploads",
            "non-existent-uuid-99999",
            "invalid_id_12345",
            "%2e%2e%2fetc%2fpasswd",
        ],
    )
    def test_get_document_file_traversal_returns_404(self, client: TestClient, bad_doc_id: str):
        """GET /documents/{doc_id}/file with traversal IDs must return 404 Not Found."""
        response = client.get(f"/documents/{bad_doc_id}/file")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# ============================================================================
# Section 2: File Upload Payload, Size & Extension Validation
# ============================================================================

class TestUploadPayloadValidation:
    """Boundary testing on file sizes, MIME types, extensions, and empty payloads."""

    def test_zero_byte_upload_rejected_with_400(self, client: TestClient):
        """Zero-byte file upload must be rejected with HTTP 400 Bad Request."""
        files = {"file": ("empty.pdf", b"", "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_single_byte_upload_accepted(self, client: TestClient):
        """Single-byte non-empty file must be accepted and processed without crashing."""
        files = {"file": ("single_byte.pdf", b"X", "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        assert "document_id" in response.json()

    def test_oversized_upload_rejected(self, client: TestClient, test_settings: Settings):
        """File larger than MAX_UPLOAD_SIZE_BYTES must be rejected with HTTP 400 or HTTP 413."""
        oversized = b"X" * (test_settings.MAX_UPLOAD_SIZE_BYTES + 1024)
        files = {"file": ("oversized.pdf", oversized, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code in [400, 413]

    @pytest.mark.parametrize(
        "forbidden_filename,mime_type",
        [
            ("malicious.exe", "application/x-msdownload"),
            ("exploit.sh", "application/x-sh"),
            ("payload.py", "text/x-python"),
            ("script.js", "application/javascript"),
            ("page.html", "text/html"),
            ("vector.svg", "image/svg+xml"),
            ("archive.tar.gz", "application/gzip"),
            ("document.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("spreadsheet.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("no_extension", "application/pdf"),
            (".hidden_no_stem", "application/pdf"),
        ],
    )
    def test_forbidden_file_extensions_rejected_with_400(
        self, client: TestClient, forbidden_filename: str, mime_type: str
    ):
        """Strict whitelist validation must reject forbidden extensions with HTTP 400."""
        files = {"file": (forbidden_filename, b"content", mime_type)}
        response = client.post("/upload", files=files)
        assert response.status_code == 400
        assert "unsupported file extension" in response.json()["detail"].lower()

    @pytest.mark.parametrize(
        "allowed_case_variant",
        [
            "invoice.PDF",
            "invoice.Pdf",
            "image.PNG",
            "image.Png",
            "receipt.JPG",
            "receipt.Jpeg",
            "scan.TIFF",
            "scan.Tif",
            "bitmap.BMP",
        ],
    )
    def test_allowed_extensions_case_insensitivity(self, client: TestClient, allowed_case_variant: str):
        """All case variations of allowed extensions (.PDF, .PNG, .TIFF) must be accepted."""
        content = b"%PDF-1.4\nVendor: Case Corp\nInvoice ID: INV-CASE-01\nTotal: $100.00"
        files = {"file": (allowed_case_variant, content, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        assert "document_id" in response.json()


# ============================================================================
# Section 3: Corrupted Streams & Header Fuzzing
# ============================================================================

class TestCorruptedStreamsAndHeaderFuzzing:
    """Stress tests corrupted headers, truncated bodies, and binary noise."""

    def test_truncated_pdf_header_only(self, client: TestClient):
        """PDF containing only `%PDF-1.7` with no body or EOF marker must extract gracefully."""
        corrupt = b"%PDF-1.7"
        files = {"file": ("corrupt_header.pdf", corrupt, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        assert "document_id" in data
        assert data["status"] in ["SUCCESS", "NEEDS_REVIEW"]

    def test_random_binary_garbage_stream(self, client: TestClient):
        """Pure random bytes (os.urandom) named .pdf must not raise unhandled exceptions."""
        noise = os.urandom(2048)
        files = {"file": ("noise.pdf", noise, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        assert "document_id" in response.json()

    def test_truncated_png_magic_only(self, client: TestClient):
        """PNG file containing only 8 magic bytes `\x89PNG\r\n\x1a\n` must be handled safely."""
        png_magic = b"\x89PNG\r\n\x1a\n"
        files = {"file": ("truncated.png", png_magic, "image/png")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        assert "document_id" in response.json()

    def test_truncated_jpeg_soi_only(self, client: TestClient):
        """JPEG file containing only SOI marker `\xFF\xD8\xFF` must be handled safely."""
        jpg_magic = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        files = {"file": ("truncated.jpg", jpg_magic, "image/jpeg")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        assert "document_id" in response.json()


# ============================================================================
# Section 4: Malformed API Requests & Boundary Invariants
# ============================================================================

class TestMalformedApiRequests:
    """Probes endpoint resilience to missing fields, wrong HTTP methods, and invalid types."""

    def test_upload_missing_file_body_returns_422(self, client: TestClient):
        """POST /upload without multipart file must return 422 Unprocessable Entity."""
        response = client.post("/upload", data={"force_mock": "true"})
        assert response.status_code == 422
        assert response.json()["error_type"] == "ValidationError"

    def test_upload_json_body_instead_of_multipart_returns_422(self, client: TestClient):
        """POST /upload with raw JSON body must return 422."""
        response = client.post("/upload", json={"file": "test.pdf"})
        assert response.status_code == 422

    def test_upload_disallowed_http_verbs_return_405(self, client: TestClient):
        """GET, PUT, DELETE requests on /upload must return 405 Method Not Allowed."""
        assert client.get("/upload").status_code == 405
        assert client.put("/upload").status_code == 405
        assert client.delete("/upload").status_code == 405

    def test_health_check_endpoint_contract(self, client: TestClient):
        """GET /health and GET /api/v1/health must return healthy status contract."""
        for endpoint in ["/health", "/api/v1/health"]:
            res = client.get(endpoint)
            assert res.status_code == 200
            data = res.json()
            assert data["status"] in ["healthy", "ok", "degraded"]
            assert "app_name" in data
            assert "version" in data
            assert "mock_mode" in data
            assert "storage_healthy" in data


# ============================================================================
# Section 5: Dynamic Heuristic Extraction & Arithmetic Precision
# ============================================================================

class TestDynamicExtractionAndArithmetic:
    """Stress tests dynamic heuristic parser, multi-item tables, and floating point math."""

    def test_invoice_with_missing_totals(self):
        """Invoice with no explicit Total header extracts zero total and flags ZERO_TOTAL."""
        text = "INVOICE\nVendor: No Total Services Inc\nInvoice ID: INV-NOTOT-01\nInvoice Date: 2026-08-01\nLine description"
        extractor = MockExtractionService()
        raw = extractor._extract_heuristically(text, "doc-1", "corr-1", "no_total.pdf")
        normalized = extractor._raw_to_normalized(raw)

        assert normalized.total_amount.value == 0.0
        assert any(a.code == "ZERO_TOTAL" for a in normalized.anomalies)

    def test_invoice_with_50_line_items_table(self):
        """Verify parser scales to 50 structured table line items."""
        lines = [
            "INVOICE",
            "Vendor: Enterprise Multi-Item Vendor Inc",
            "Invoice ID: INV-50-ITEMS",
            "Invoice Date: 2026-08-01",
            "Description Qty UnitPrice Total",
            "-" * 50,
        ]
        for i in range(1, 51):
            lines.append(f"Cloud Resource SKU-{i:03d} 1.0 10.00 10.00")
        lines.append("-" * 50)
        lines.append("SubTotal: $500.00")
        lines.append("Tax: $50.00")
        lines.append("Total: $550.00")

        text = "\n".join(lines)
        extractor = MockExtractionService()
        raw = extractor._extract_heuristically(text, "doc-4", "corr-4", "large_table.pdf")
        normalized = extractor._raw_to_normalized(raw)

        assert len(normalized.line_items) == 50
        assert normalized.total_amount.value == 550.00
        assert normalized.status == "SUCCESS"

    def test_arithmetic_tolerance_exact_boundaries(self):
        """Diff of $0.04 (within $0.05 tolerance) passes; diff of $0.06 flags MATH_DISCREPANCY."""
        extractor = MockExtractionService()

        # Within tolerance: Subtotal 100.00 + Tax 10.00 vs Total 110.04 (diff = 0.04 <= 0.05)
        text_ok = "INVOICE\nVendor: Tol Corp\nInvoice ID: INV-TOL-01\nInvoice Date: 2026-08-01\nSubTotal: $100.00\nTax: $10.00\nTotal: $110.04"
        raw_ok = extractor._extract_heuristically(text_ok, "d1", "c1", "tol_ok.pdf")
        norm_ok = extractor._raw_to_normalized(raw_ok)
        assert not any(a.code == "MATH_DISCREPANCY" for a in norm_ok.anomalies)

        # Outside tolerance: Subtotal 100.00 + Tax 10.00 vs Total 110.06 (diff = 0.06 > 0.05)
        text_bad = "INVOICE\nVendor: Tol Corp\nInvoice ID: INV-TOL-02\nInvoice Date: 2026-08-01\nSubTotal: $100.00\nTax: $10.00\nTotal: $110.06"
        raw_bad = extractor._extract_heuristically(text_bad, "d2", "c2", "tol_bad.pdf")
        norm_bad = extractor._raw_to_normalized(raw_bad)
        assert any(a.code == "MATH_DISCREPANCY" for a in norm_bad.anomalies)

    def test_azure_client_unconfigured_availability_and_fallback(self):
        """Azure client reports is_available == False for dummy keys and activates MockExtractor fallback."""
        client = AzureDocumentIntelligenceClient(
            endpoint="https://your-resource.cognitiveservices.azure.com/",
            key="dummy_key",
        )
        assert client.is_available() is False

        service = ExtractionService(azure_client=client)
        assert service.should_use_mock() is True

        payload = service.extract_raw(
            file_bytes=b"%PDF-1.4 Sample\nVendor: Acme Corp\nInvoice ID: INV-FALLBACK-01\nTotal: $100.00",
            filename="fallback.pdf",
        )
        assert payload is not None
        assert payload.document_id is not None
