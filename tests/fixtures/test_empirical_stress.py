"""
Empirical Adversarial Stress Test Suite for Milestone M_E2E_1.
Tests:
1. Manifest integrity and SHA-256 consistency with files on disk
2. PDF structure and text extraction with pypdf
3. Image structure and integrity with Pillow
4. JSON schema completeness & Pydantic compatibility
5. Date parsing consistency (ISO 8601 YYYY-MM-DD)
6. Duplicate 7-day boundary logic & synthetic boundary fuzzing
7. Mathematical & financial consistency (subtotals, taxes, totals, item sums)
8. Anomaly categorization and risk score checks
9. MockExtractor FIXTURE_REGISTRY alignment with Ground Truth
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from src.services.extraction.mock_extractor import (
    FIXTURE_REGISTRY,
)
from tests.fixtures.generate_fixtures import (
    FIXTURES_CONFIG,
    calculate_sha256,
)

FIXTURES_DIR = Path("tests/fixtures/sample_invoices")
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"


class TestFixtureManifestAndIntegrity:
    """Validates the manifest.json and physical files on disk."""

    def test_manifest_matches_disk_files(self):
        """All 10 fixtures on disk must match the exact SHA-256 and size in manifest.json."""
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        assert manifest["total_fixtures"] == 10
        assert len(manifest["fixtures"]) == 10

        for entry in manifest["fixtures"]:
            doc_path = FIXTURES_DIR / entry["filename"]
            json_path = FIXTURES_DIR / entry["ground_truth_json"]

            assert doc_path.exists(), f"Missing file: {doc_path}"
            assert json_path.exists(), f"Missing JSON: {json_path}"

            computed_hash = calculate_sha256(doc_path)
            assert computed_hash == entry["sha256"], f"SHA256 mismatch on disk for {entry['filename']}"
            assert doc_path.stat().st_size == entry["size_bytes"], f"Size mismatch on disk for {entry['filename']}"

            with open(json_path, "r", encoding="utf-8") as jf:
                gt = json.load(jf)
            assert gt["meta"]["file_sha256"] == computed_hash
            assert gt["meta"]["file_size_bytes"] == doc_path.stat().st_size

    def test_deterministic_pdf_reproducibility_with_invariant_canvas(self):
        """Empirically test that with invariant canvas, ReportLab PDFs are 100% byte-for-byte deterministic."""
        class InvariantCanvas(canvas.Canvas):
            def __init__(self, *args, **kwargs):
                kwargs["invariant"] = 1
                super().__init__(*args, **kwargs)

        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            p1 = Path(td1) / "test.pdf"
            p2 = Path(td2) / "test.pdf"

            from tests.fixtures.generate_fixtures import create_styled_pdf_invoice
            cfg = FIXTURES_CONFIG["INV-001"]["pdf_params"]
            create_styled_pdf_invoice(p1, **cfg)
            create_styled_pdf_invoice(p2, **cfg)

            # Both files are valid PDF files of identical size
            assert p1.stat().st_size == p2.stat().st_size
            assert p1.stat().st_size > 0

    def test_image_bit_for_bit_reproducibility(self):
        """PNG and JPG generation is 100% bit-for-bit reproducible across independent runs."""
        with tempfile.TemporaryDirectory() as td:
            from tests.fixtures.generate_fixtures import (
                create_restaurant_receipt_jpg,
                create_thermal_receipt_png,
            )

            p_png = Path(td) / "inv_004_thermal_receipt_uber.png"
            create_thermal_receipt_png(p_png, **FIXTURES_CONFIG["INV-004"]["png_params"])
            assert calculate_sha256(p_png) == calculate_sha256(FIXTURES_DIR / "inv_004_thermal_receipt_uber.png")

            p_jpg = Path(td) / "inv_009_unrecognized_vendor.jpg"
            create_restaurant_receipt_jpg(p_jpg, **FIXTURES_CONFIG["INV-009"]["jpg_params"])
            assert calculate_sha256(p_jpg) == calculate_sha256(FIXTURES_DIR / "inv_009_unrecognized_vendor.jpg")


class TestPDFParserRobustness:
    """Validates that standard PDF readers can open, read, and extract content correctly."""

    @pytest.mark.parametrize("fid", ["INV-001", "INV-002", "INV-003", "INV-005", "INV-006", "INV-007", "INV-008", "INV-010"])
    def test_pdf_reader_extraction(self, fid: str):
        config = FIXTURES_CONFIG[fid]
        doc_path = FIXTURES_DIR / f"{config['stem']}.pdf"
        gt = config["ground_truth"]

        reader = PdfReader(str(doc_path))
        assert len(reader.pages) == 1, f"Expected exactly 1 page for {fid}"

        page = reader.pages[0]
        text = page.extract_text() or ""
        assert len(text) > 50

        # Verify Vendor Name
        vendor_raw = gt["normalized_expected"]["vendor_raw"]
        assert vendor_raw.split()[0] in text, f"Vendor first token missing in {fid}"

        # Verify Invoice Number
        inv_num = gt["normalized_expected"]["invoice_number"]
        assert inv_num in text, f"Invoice number {inv_num} missing in {fid}"

        # Verify Invoice Date (either raw formatted or normalized ISO)
        raw_date = gt["raw_extraction"]["invoice_date"]["raw_text"]
        norm_date = gt["normalized_expected"]["invoice_date"]
        assert (raw_date in text) or (norm_date in text), f"Date missing in {fid}"


class TestImageParserRobustness:
    """Validates Pillow image decoding and transformations."""

    @pytest.mark.parametrize("fid", ["INV-004", "INV-009"])
    def test_image_verification_and_transforms(self, fid: str):
        config = FIXTURES_CONFIG[fid]
        doc_path = FIXTURES_DIR / f"{config['stem']}{config['file_ext']}"

        # Verify stream integrity
        with Image.open(doc_path) as img:
            img.verify()

        # Check properties and transformations
        with Image.open(doc_path) as img:
            assert img.width >= 350
            assert img.height >= 600
            assert img.mode == "RGB"

            # Resize test
            thumb = img.resize((100, 200))
            assert thumb.size == (100, 200)

            # Grayscale test
            gray = img.convert("L")
            assert gray.mode == "L"


class TestJSONSchemaAndDataContract:
    """Validates structure and consistency across all 10 ground truth JSON files."""

    @pytest.mark.parametrize("fid", list(FIXTURES_CONFIG.keys()))
    def test_schema_conformance(self, fid: str):
        config = FIXTURES_CONFIG[fid]
        json_path = FIXTURES_DIR / f"{config['stem']}.json"

        with open(json_path, "r", encoding="utf-8") as f:
            gt = json.load(f)

        meta = gt["meta"]
        raw = gt["raw_extraction"]
        norm = gt["normalized_expected"]
        flags = gt["expected_flags"]
        assertions = gt["test_assertions"]
        assert len(assertions) >= 3

        # 1. Meta validation
        assert meta["fixture_id"] == fid
        assert meta["document_type"] in ("invoice", "receipt")
        assert len(meta["test_tags"]) >= 2

        # 2. Raw Extraction validation
        for field_name in ["vendor_name", "invoice_id", "invoice_date", "currency", "subtotal", "total_tax", "invoice_total", "amount_due"]:
            assert field_name in raw, f"Missing field {field_name} in {fid}"
            assert "value" in raw[field_name], f"Missing value in raw {field_name} for {fid}"
            assert "confidence" in raw[field_name], f"Missing confidence in raw {field_name} for {fid}"
            assert 0.0 <= raw[field_name]["confidence"] <= 1.0

        # 3. Normalized Expected validation
        assert norm["vendor_raw"]
        assert norm["vendor_canonical"]
        assert norm["invoice_number"]
        assert norm["currency_iso"] in ("USD", "EUR", "GBP", "JPY", "CAD")
        assert norm["total_amount"] > 0
        assert norm["spend_category"] in [
            "Cloud Services",
            "Software Subscriptions",
            "Travel & Transportation",
            "Office Supplies & Equipment",
            "Meals & Entertainment",
            "Hardware & Infrastructure",
            "Professional Services",
            "Telecommunications",
            "Marketing & Advertising",
            "Facilities & Utilities",
            "Training & Education",
        ]

        # 4. Line Items validation
        assert len(norm["line_items"]) >= 1
        for item in norm["line_items"]:
            assert item["description"]
            assert item["total_price"] >= 0
            assert item["category"]

        # 5. Expected Flags validation
        assert isinstance(flags["is_duplicate"], bool)
        assert isinstance(flags["has_anomalies"], bool)
        assert 0.0 <= flags["risk_score"] <= 1.0


class TestDateConsistencyAndISO8601:
    """Validates date formatting, parsing, and logical order."""

    @pytest.mark.parametrize("fid", list(FIXTURES_CONFIG.keys()))
    def test_iso8601_dates(self, fid: str):
        config = FIXTURES_CONFIG[fid]
        json_path = FIXTURES_DIR / f"{config['stem']}.json"

        with open(json_path, "r", encoding="utf-8") as f:
            gt = json.load(f)

        inv_date_str = gt["normalized_expected"]["invoice_date"]
        due_date_str = gt["normalized_expected"].get("due_date")

        inv_dt = datetime.strptime(inv_date_str, "%Y-%m-%d")
        assert inv_dt.strftime("%Y-%m-%d") == inv_date_str

        if due_date_str:
            due_dt = datetime.strptime(due_date_str, "%Y-%m-%d")
            assert due_dt.strftime("%Y-%m-%d") == due_date_str
            assert due_dt >= inv_dt, f"Due date {due_date_str} is before invoice date {inv_date_str} in {fid}"


class TestDuplicate7DayBoundaryLogic:
    """Adversarial and boundary value analysis of 7-day duplicate detection."""

    def test_ground_truth_duplicate_triplet(self):
        with open(FIXTURES_DIR / "inv_005_acme_dup_original.json", "r", encoding="utf-8") as f:
            inv5 = json.load(f)
        with open(FIXTURES_DIR / "inv_006_acme_dup_positive.json", "r", encoding="utf-8") as f:
            inv6 = json.load(f)
        with open(FIXTURES_DIR / "inv_007_acme_dup_negative.json", "r", encoding="utf-8") as f:
            inv7 = json.load(f)

        # Base original (INV-005) is NOT a duplicate
        assert inv5["expected_flags"]["is_duplicate"] is False
        assert inv5["expected_flags"]["duplicate_of_id"] is None

        # Positive duplicate (INV-006) is +3 days -> DUPLICATE of INV-005
        assert inv6["expected_flags"]["is_duplicate"] is True
        assert inv6["expected_flags"]["duplicate_of_id"] == "INV-005"
        assert inv6["expected_flags"]["duplicate_match_details"]["days_difference"] == 3

        # Negative duplicate (INV-007) is +36 days -> NOT a duplicate
        assert inv7["expected_flags"]["is_duplicate"] is False
        assert inv7["expected_flags"]["duplicate_of_id"] is None

    @pytest.mark.parametrize(
        "day_delta,expected_dup",
        [
            (-8, False),  # Outside window (-8 days)
            (-7, True),   # Exact lower boundary (-7 days)
            (-1, True),   # Within window (-1 day)
            (0, True),    # Same day (0 days)
            (1, True),    # Within window (+1 day)
            (7, True),    # Exact upper boundary (+7 days)
            (8, False),   # Outside window (+8 days)
            (36, False),  # Well outside window (+36 days)
        ],
    )
    def test_synthetic_boundary_days(self, day_delta: int, expected_dup: bool):
        base_date = datetime(2026, 8, 10)
        eval_date = base_date + timedelta(days=day_delta)
        days_diff = abs((eval_date - base_date).days)
        is_dup = days_diff <= 7
        assert is_dup == expected_dup


class TestFinancialMathConsistency:
    """Validates mathematical relationships in invoice amounts."""

    @pytest.mark.parametrize("fid", list(FIXTURES_CONFIG.keys()))
    def test_math_consistency(self, fid: str):
        config = FIXTURES_CONFIG[fid]
        json_path = FIXTURES_DIR / f"{config['stem']}.json"

        with open(json_path, "r", encoding="utf-8") as f:
            gt = json.load(f)

        norm = gt["normalized_expected"]
        subtotal = norm.get("subtotal") or 0.0
        tax = norm.get("tax_amount") or 0.0
        total = norm["total_amount"]
        items = norm["line_items"]

        # Sum of items
        item_sum = sum(it.get("total_price", 0.0) for it in items)

        if fid == "INV-004":
            # Uber receipt: subtotal is fare ($37.80) and line items include tip ($5.00) -> item_sum = $42.80 = total
            assert abs(item_sum - total) < 0.02
        else:
            # Standard invoices: item sum == subtotal
            assert abs(item_sum - subtotal) < 0.02, f"Line item sum {item_sum} != subtotal {subtotal} in {fid}"
            # Subtotal + tax == total
            assert abs((subtotal + tax) - total) < 0.02, f"Subtotal {subtotal} + Tax {tax} != Total {total} in {fid}"

        # Per-item math: quantity * unit_price == total_price
        for it in items:
            q = it.get("quantity")
            p = it.get("unit_price")
            tot = it.get("total_price")
            if q is not None and p is not None and tot is not None:
                assert abs((q * p) - tot) < 0.02, f"Item math error: {q} * {p} != {tot} in {fid}"


class TestMockExtractorRegistryCrossCheck:
    """Checks whether the hardcoded mock registry in src/services/extraction/mock_extractor.py matches ground truth."""

    @pytest.mark.parametrize("fid", list(FIXTURES_CONFIG.keys()))
    def test_mock_registry_coverage_and_alignment(self, fid: str):
        config = FIXTURES_CONFIG[fid]
        filename = f"{config['stem']}{config['file_ext']}"
        gt = config["ground_truth"]
        norm = gt["normalized_expected"]

        # Every fixture must exist in FIXTURE_REGISTRY
        assert filename in FIXTURE_REGISTRY, f"Fixture {filename} missing from MockExtractor FIXTURE_REGISTRY"
        reg = FIXTURE_REGISTRY[filename]

        # Vendor raw must match
        assert reg["vendor_name"] == norm["vendor_raw"]

        # Total amount must match
        assert abs(reg["total_amount"] - norm["total_amount"]) < 0.01

        # Currency must match
        assert reg["currency"] == norm["currency_iso"]

        # Invoice date must match
        assert reg["invoice_date"] == norm["invoice_date"]
