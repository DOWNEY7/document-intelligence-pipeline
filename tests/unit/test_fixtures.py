"""
Unit and Schema Verification Tests for M_E2E_1 Sample Invoices & Ground Truth Dataset.
Validates physical file integrity (PDF & image parsing), SHA-256 hashes, and JSON schema compliance.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pypdf import PdfReader

from tests.fixtures.generate_fixtures import calculate_sha256

FIXTURES_DIR = Path("tests/fixtures/sample_invoices")
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"

EXPECTED_FIXTURE_IDS = [
    "INV-001",
    "INV-002",
    "INV-003",
    "INV-004",
    "INV-005",
    "INV-006",
    "INV-007",
    "INV-008",
    "INV-009",
    "INV-010",
]


@pytest.fixture(scope="module")
def manifest_data() -> dict[str, Any]:
    """Loads manifest.json."""
    assert MANIFEST_PATH.exists(), f"Manifest file missing at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def test_manifest_structure(manifest_data: dict[str, Any]) -> None:
    """Verifies manifest.json top-level fields and fixture count."""
    assert manifest_data["total_fixtures"] == 10
    assert "dataset_version" in manifest_data
    assert "generated_at" in manifest_data
    assert len(manifest_data["fixtures"]) == 10

    fixture_ids = [entry["fixture_id"] for entry in manifest_data["fixtures"]]
    assert fixture_ids == EXPECTED_FIXTURE_IDS


@pytest.mark.parametrize("fixture_id", EXPECTED_FIXTURE_IDS)
def test_fixture_files_exist_and_match_hash(fixture_id: str, manifest_data: dict[str, Any]) -> None:
    """Verifies that each document file and its ground truth JSON exist and match SHA-256."""
    entry = next(f for f in manifest_data["fixtures"] if f["fixture_id"] == fixture_id)

    doc_path = FIXTURES_DIR / entry["filename"]
    json_path = FIXTURES_DIR / entry["ground_truth_json"]

    assert doc_path.exists(), f"Document file missing: {doc_path}"
    assert json_path.exists(), f"Ground truth JSON missing: {json_path}"

    assert doc_path.stat().st_size > 0
    assert json_path.stat().st_size > 0

    computed_sha256 = calculate_sha256(doc_path)
    assert computed_sha256 == entry["sha256"], f"SHA256 mismatch for {doc_path}"

    # Load JSON and verify metadata matches
    with open(json_path, "r", encoding="utf-8") as jf:
        gt = json.load(jf)

    assert gt["meta"]["fixture_id"] == fixture_id
    assert gt["meta"]["file_sha256"] == computed_sha256
    assert gt["meta"]["file_size_bytes"] == doc_path.stat().st_size


@pytest.mark.parametrize("fixture_id", ["INV-001", "INV-002", "INV-003", "INV-005", "INV-006", "INV-007", "INV-008", "INV-010"])
def test_pdf_document_parsing(fixture_id: str, manifest_data: dict[str, Any]) -> None:
    """Verifies that all 8 PDF documents can be opened and parsed with pypdf."""
    entry = next(f for f in manifest_data["fixtures"] if f["fixture_id"] == fixture_id)
    doc_path = FIXTURES_DIR / entry["filename"]

    reader = PdfReader(str(doc_path))
    assert len(reader.pages) >= 1

    extracted_text = ""
    for page in reader.pages:
        extracted_text += page.extract_text() or ""

    assert len(extracted_text) > 20, f"PDF text extract too short for {fixture_id}"

    with open(FIXTURES_DIR / entry["ground_truth_json"], "r", encoding="utf-8") as jf:
        gt = json.load(jf)

    invoice_number = gt["normalized_expected"]["invoice_number"]
    # Check that invoice number is present in document text
    assert invoice_number in extracted_text or invoice_number.replace("-", "") in extracted_text


@pytest.mark.parametrize("fixture_id", ["INV-004", "INV-009"])
def test_image_document_parsing(fixture_id: str, manifest_data: dict[str, Any]) -> None:
    """Verifies that PNG and JPG receipts can be opened and have valid dimensions."""
    entry = next(f for f in manifest_data["fixtures"] if f["fixture_id"] == fixture_id)
    doc_path = FIXTURES_DIR / entry["filename"]

    with Image.open(doc_path) as img:
        assert img.width > 200
        assert img.height > 400
        if fixture_id == "INV-004":
            assert img.format == "PNG"
        elif fixture_id == "INV-009":
            assert img.format in ("JPEG", "JPG")


@pytest.mark.parametrize("fixture_id", EXPECTED_FIXTURE_IDS)
def test_ground_truth_schema_compliance(fixture_id: str, manifest_data: dict[str, Any]) -> None:
    """Verifies that every ground truth JSON strictly complies with expected keys and types."""
    entry = next(f for f in manifest_data["fixtures"] if f["fixture_id"] == fixture_id)
    json_path = FIXTURES_DIR / entry["ground_truth_json"]

    with open(json_path, "r", encoding="utf-8") as jf:
        gt = json.load(jf)

    required_sections = ["meta", "raw_extraction", "normalized_expected", "expected_flags", "test_assertions"]
    for section in required_sections:
        assert section in gt, f"Missing required section '{section}' in {json_path}"

    # Verify Normalized fields
    norm = gt["normalized_expected"]
    assert isinstance(norm["vendor_raw"], str)
    assert isinstance(norm["invoice_number"], str)
    assert len(norm["invoice_date"]) == 10  # YYYY-MM-DD
    assert len(norm["currency_iso"]) == 3   # USD, EUR, JPY
    assert norm["total_amount"] > 0
    assert len(norm["line_items"]) >= 1

    for item in norm["line_items"]:
        assert "description" in item
        assert "total_price" in item
        assert "category" in item

    # Verify Duplicate Flags
    dup = gt["expected_flags"]
    assert isinstance(dup["is_duplicate"], bool)
    assert isinstance(dup["has_anomalies"], bool)


def test_duplicate_chain_relationship() -> None:
    """Verifies duplicate logic across INV-005 (base), INV-006 (+3d, pos), INV-007 (+36d, neg)."""
    with open(FIXTURES_DIR / "inv_005_acme_dup_original.json", "r", encoding="utf-8") as f:
        inv5 = json.load(f)
    with open(FIXTURES_DIR / "inv_006_acme_dup_positive.json", "r", encoding="utf-8") as f:
        inv6 = json.load(f)
    with open(FIXTURES_DIR / "inv_007_acme_dup_negative.json", "r", encoding="utf-8") as f:
        inv7 = json.load(f)

    # All three share canonical vendor and amount
    assert inv5["normalized_expected"]["vendor_canonical"] == inv6["normalized_expected"]["vendor_canonical"]
    assert inv5["normalized_expected"]["vendor_canonical"] == inv7["normalized_expected"]["vendor_canonical"]
    assert inv5["normalized_expected"]["total_amount"] == inv6["normalized_expected"]["total_amount"] == inv7["normalized_expected"]["total_amount"]

    # INV-005 is not duplicate
    assert not inv5["expected_flags"]["is_duplicate"]

    # INV-006 is duplicate of INV-005
    assert inv6["expected_flags"]["is_duplicate"]
    assert inv6["expected_flags"]["duplicate_of_id"] == "INV-005"
    assert inv6["expected_flags"]["duplicate_match_details"]["days_difference"] == 3

    # INV-007 is NOT duplicate (outside 7-day window: 36 days)
    assert not inv7["expected_flags"]["is_duplicate"]


def test_anomaly_fixtures() -> None:
    """Verifies extreme amount and unrecognized vendor anomaly triggers."""
    with open(FIXTURES_DIR / "inv_008_extreme_anomaly.json", "r", encoding="utf-8") as f:
        inv8 = json.load(f)
    with open(FIXTURES_DIR / "inv_009_unrecognized_vendor.json", "r", encoding="utf-8") as f:
        inv9 = json.load(f)

    # INV-008: extreme amount
    assert inv8["expected_flags"]["has_anomalies"]
    flags8 = [fl["anomaly_type"] for fl in inv8["expected_flags"]["anomaly_flags"]]
    assert "extreme_amount" in flags8
    assert inv8["normalized_expected"]["total_amount"] == 1250000.00
    assert inv8["expected_flags"]["risk_score"] >= 0.80

    # INV-009: unrecognized vendor
    assert inv9["expected_flags"]["has_anomalies"]
    flags9 = [fl["anomaly_type"] for fl in inv9["expected_flags"]["anomaly_flags"]]
    assert "unrecognized_vendor" in flags9
    assert not inv9["normalized_expected"]["is_known_vendor"]
    assert inv9["normalized_expected"]["vendor_match_score"] < 70.0


def test_zero_decimal_jpy_fixture() -> None:
    """Verifies zero-decimal formatting in INV-010."""
    with open(FIXTURES_DIR / "inv_010_jpy_zero_decimal.json", "r", encoding="utf-8") as f:
        inv10 = json.load(f)

    assert inv10["normalized_expected"]["currency_iso"] == "JPY"
    assert inv10["normalized_expected"]["total_amount"] == 150000.0
    assert inv10["raw_extraction"]["currency"]["symbol"] == "¥"
