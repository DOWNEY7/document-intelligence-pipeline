"""
Adversarial Verification and Empirical Challenge Suite for Milestone M_E2E_1.
Performs white-box & black-box adversarial stress testing on the 10 sample invoice fixtures,
their binary encodings, PDF/image renderability, SHA-256 hashes, schema completeness,
mathematical arithmetic precision, floating-point drift, RapidFuzz scoring, duplicate chains,
and anomaly detection flags.
"""

import hashlib
import json
import math
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pypdf import PdfReader
from rapidfuzz import fuzz

FIXTURES_DIR = Path("tests/fixtures/sample_invoices")
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"

EXPECTED_TAXONOMY_CATEGORIES = {
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
}

EXPECTED_FIXTURE_IDS = [f"INV-{i:03d}" for i in range(1, 11)]

KNOWN_CANONICAL_VENDORS = [
    "Amazon Web Services",
    "Microsoft Corporation",
    "Google LLC",
    "Uber Technologies",
    "Acme Corporation",
    "Delta Air Lines",
    "Slack Technologies",
    "Salesforce Inc",
    "Adobe Inc",
    "Zoom Video Communications",
    "Apple Inc",
    "GitHub Inc",
    "Stripe Inc",
    "Twilio Inc",
    "Atlassian Pty Ltd",
]


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    assert MANIFEST_PATH.exists(), f"manifest.json missing at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def all_fixtures_data(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = {}
    for entry in manifest["fixtures"]:
        fid = entry["fixture_id"]
        jpath = FIXTURES_DIR / entry["ground_truth_json"]
        with open(jpath, "r", encoding="utf-8") as f:
            data[fid] = json.load(f)
    return data


# ==============================================================================
# 1. Adversarial File Integrity & Binary Stream Checks
# ==============================================================================

@pytest.mark.parametrize("fixture_id", EXPECTED_FIXTURE_IDS)
def test_file_existence_and_sha256_exact_match(fixture_id: str, manifest: dict[str, Any], all_fixtures_data: dict[str, dict[str, Any]]):
    """Stress test SHA-256 hash consistency across physical disk, manifest, and JSON metadata."""
    entry = next(f for f in manifest["fixtures"] if f["fixture_id"] == fixture_id)
    doc_path = FIXTURES_DIR / entry["filename"]
    json_path = FIXTURES_DIR / entry["ground_truth_json"]

    assert doc_path.exists(), f"File {doc_path} does not exist"
    assert json_path.exists(), f"JSON {json_path} does not exist"

    raw_bytes = doc_path.read_bytes()
    assert len(raw_bytes) > 0, f"File {doc_path} is empty (0 bytes)"

    computed_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    assert computed_sha256 == entry["sha256"], f"SHA256 mismatch in manifest for {fixture_id}"

    gt = all_fixtures_data[fixture_id]
    assert gt["meta"]["file_sha256"] == computed_sha256, f"SHA256 mismatch in JSON meta for {fixture_id}"
    assert gt["meta"]["file_size_bytes"] == len(raw_bytes), f"File size mismatch in JSON meta for {fixture_id}"


@pytest.mark.parametrize("fixture_id", ["INV-001", "INV-002", "INV-003", "INV-005", "INV-006", "INV-007", "INV-008", "INV-010"])
def test_pdf_binary_stream_and_text_integrity(fixture_id: str, manifest: dict[str, Any], all_fixtures_data: dict[str, dict[str, Any]]):
    """Adversarial stress test on PDF binary structure, headers, trailers, page objects, and extractable content."""
    entry = next(f for f in manifest["fixtures"] if f["fixture_id"] == fixture_id)
    doc_path = FIXTURES_DIR / entry["filename"]
    raw_bytes = doc_path.read_bytes()

    # Check PDF magic bytes at start
    assert raw_bytes.startswith(b"%PDF-"), f"PDF header corrupt or missing in {doc_path}"

    # Check EOF marker in last 1024 bytes
    assert b"%%EOF" in raw_bytes[-1024:], f"PDF EOF marker corrupt or missing in {doc_path}"

    reader = PdfReader(str(doc_path))
    assert len(reader.pages) == 1, f"Expected exactly 1 page for fixture {fixture_id}, got {len(reader.pages)}"

    page = reader.pages[0]
    page_width = float(page.mediabox.width)
    page_height = float(page.mediabox.height)

    # Standard Letter dimensions: 612 x 792 pt
    assert 600 <= page_width <= 620, f"Unexpected page width: {page_width}"
    assert 780 <= page_height <= 800, f"Unexpected page height: {page_height}"

    extracted_text = page.extract_text()
    assert len(extracted_text) >= 100, f"PDF extracted text suspiciously short ({len(extracted_text)} chars) for {fixture_id}"

    gt = all_fixtures_data[fixture_id]
    inv_num = gt["normalized_expected"]["invoice_number"]
    assert inv_num in extracted_text or inv_num.replace("-", "") in extracted_text, f"Invoice number {inv_num} missing in PDF stream for {fixture_id}"


@pytest.mark.parametrize("fixture_id", ["INV-004", "INV-009"])
def test_image_binary_mode_and_pixel_variance(fixture_id: str, manifest: dict[str, Any], all_fixtures_data: dict[str, dict[str, Any]]):
    """Adversarial test on image fixtures (PNG thermal receipt, JPG photo receipt) for non-blank pixels, color mode, and dimensions."""
    entry = next(f for f in manifest["fixtures"] if f["fixture_id"] == fixture_id)
    doc_path = FIXTURES_DIR / entry["filename"]

    with Image.open(doc_path) as img:
        assert img.mode in ("RGB", "RGBA"), f"Unexpected color mode {img.mode} for {fixture_id}"
        width, height = img.size
        assert width >= 300, f"Image width too small: {width}"
        assert height >= 600, f"Image height too small: {height}"

        # Test non-blank content (pixel entropy / standard deviation)
        grayscale = img.convert("L")
        pixels = list(grayscale.getdata())
        mean_pixel = sum(pixels) / len(pixels)
        variance = sum((p - mean_pixel) ** 2 for p in pixels) / len(pixels)
        std_dev = math.sqrt(variance)

        # A non-blank receipt image will have reasonable standard deviation (> 10)
        assert std_dev > 10.0, f"Image appears blank or uniform with std_dev {std_dev} for {fixture_id}"


# ==============================================================================
# 2. Schema Completeness & Type Stress Tests
# ==============================================================================

@pytest.mark.parametrize("fixture_id", EXPECTED_FIXTURE_IDS)
def test_ground_truth_json_full_schema(fixture_id: str, all_fixtures_data: dict[str, dict[str, Any]]):
    """Validate all required sections, field types, and nested constraints across 10 ground truth JSONs."""
    gt = all_fixtures_data[fixture_id]

    # Top-level sections
    for section in ["meta", "raw_extraction", "normalized_expected", "expected_flags", "test_assertions"]:
        assert section in gt, f"Missing section '{section}' in {fixture_id}"

    # Meta
    meta = gt["meta"]
    assert meta["fixture_id"] == fixture_id
    assert meta["file_format"] in ["pdf", "png", "jpg", "jpeg"]
    assert meta["mime_type"] in ["application/pdf", "image/png", "image/jpeg"]
    assert isinstance(meta["description"], str) and len(meta["description"]) > 10
    assert isinstance(meta["test_tags"], list) and len(meta["test_tags"]) >= 1
    assert "file_sha256" in meta and len(meta["file_sha256"]) == 64
    assert meta["file_size_bytes"] > 0

    # Raw Extraction
    raw = gt["raw_extraction"]
    for field in ["vendor_name", "invoice_id", "invoice_date", "subtotal", "invoice_total", "currency", "line_items"]:
        assert field in raw, f"Missing raw field '{field}' in {fixture_id}"
        if field == "line_items":
            assert isinstance(raw[field], list)
            assert len(raw[field]) >= 1
        else:
            assert "value" in raw[field]
            assert "confidence" in raw[field]
            assert 0.0 <= raw[field]["confidence"] <= 1.0

    # Normalized Expected
    norm = gt["normalized_expected"]
    assert isinstance(norm["vendor_raw"], str) and len(norm["vendor_raw"]) > 0
    assert isinstance(norm["vendor_canonical"], str) and len(norm["vendor_canonical"]) > 0
    assert 0.0 <= norm["vendor_match_score"] <= 100.0
    assert isinstance(norm["is_known_vendor"], bool)
    assert isinstance(norm["invoice_number"], str) and len(norm["invoice_number"]) > 0

    # ISO Date check
    inv_date = datetime.strptime(norm["invoice_date"], "%Y-%m-%d").date()
    assert inv_date.year == 2026

    if norm.get("due_date"):
        due_date = datetime.strptime(norm["due_date"], "%Y-%m-%d").date()
        assert due_date >= inv_date, f"Due date {due_date} before invoice date {inv_date} in {fixture_id}"

    # ISO Currency check
    assert norm["currency_iso"] in ["USD", "EUR", "JPY", "GBP", "CAD", "AUD", "CHF"]

    # Taxonomy Category check
    assert norm["spend_category"] in EXPECTED_TAXONOMY_CATEGORIES, f"Invalid spend category '{norm['spend_category']}' in {fixture_id}"

    # Line items check
    assert len(norm["line_items"]) >= 1
    for item in norm["line_items"]:
        assert isinstance(item["description"], str) and len(item["description"]) > 0
        assert item["quantity"] > 0
        assert item["unit_price"] >= 0
        assert item["total_price"] >= 0
        assert item["category"] in EXPECTED_TAXONOMY_CATEGORIES, f"Invalid line item category '{item['category']}' in {fixture_id}"

    # Flags check
    flags = gt["expected_flags"]
    assert isinstance(flags["is_duplicate"], bool)
    assert isinstance(flags["has_anomalies"], bool)
    assert 0.0 <= flags["risk_score"] <= 1.0
    assert isinstance(flags["anomaly_flags"], list)


# ==============================================================================
# 3. Mathematical Consistency & Floating-Point Drift Stress Tests
# ==============================================================================

@pytest.mark.parametrize("fixture_id", ["INV-001", "INV-002", "INV-003", "INV-005", "INV-006", "INV-007", "INV-008", "INV-009", "INV-010"])
def test_mathematical_standard_invoices_arithmetic(fixture_id: str, all_fixtures_data: dict[str, dict[str, Any]]):
    """Adversarial check on all 9 standard fixtures: subtotal + tax == total (and line item sums == subtotal) without drift."""
    gt = all_fixtures_data[fixture_id]
    norm = gt["normalized_expected"]

    subtotal = norm["subtotal"]
    tax = norm["tax_amount"]
    total = norm["total_amount"]
    amount_due = norm.get("amount_due")

    # 1. Line items sum equals subtotal
    items_sum = sum(item["total_price"] for item in norm["line_items"])
    assert round(items_sum, 2) == round(subtotal, 2), (
        f"Line items sum {items_sum} != subtotal {subtotal} in {fixture_id}"
    )

    # 2. Line item quantity * unit_price == total_price
    for idx, item in enumerate(norm["line_items"]):
        qty = item["quantity"]
        unit_p = item["unit_price"]
        tot_p = item["total_price"]
        expected_line_tot = round(qty * unit_p, 2)
        assert expected_line_tot == round(tot_p, 2), (
            f"Line item {idx} ({item['description']}) math error: {qty} * {unit_p} = {expected_line_tot} != {tot_p} in {fixture_id}"
        )

    # 3. Header arithmetic: subtotal + tax == total
    expected_total = round(subtotal + tax, 2)
    assert expected_total == round(total, 2), (
        f"Header math discrepancy: subtotal ({subtotal}) + tax ({tax}) = {expected_total} != total ({total}) in {fixture_id}"
    )

    # 4. Amount due matches total
    if amount_due is not None:
        assert round(amount_due, 2) == round(total, 2), (
            f"Amount due ({amount_due}) != total ({total}) in {fixture_id}"
        )

    # 5. Currency decimal precision check
    if norm["currency_iso"] == "JPY":
        assert subtotal == int(subtotal), f"JPY subtotal has fractional decimals in {fixture_id}"
        assert tax == int(tax), f"JPY tax has fractional decimals in {fixture_id}"
        assert total == int(total), f"JPY total has fractional decimals in {fixture_id}"
    else:
        # USD, EUR: must not have more than 2 decimal places in financial representation
        for val, name in [(subtotal, "subtotal"), (tax, "tax_amount"), (total, "total_amount")]:
            assert round(val, 2) == val, f"Floating point precision drift in {name}: {val} in {fixture_id}"


def test_inv_004_thermal_receipt_special_tip_arithmetic(all_fixtures_data: dict[str, dict[str, Any]]):
    """Documenting empirical challenge for INV-004 (thermal receipt with driver tip):
    - Fare subtotal: $37.80
    - Driver tip line item: $5.00
    - Total charged: $42.80
    - Note: sum of all line items (including tip) equals total_amount ($42.80),
      while subtotal represents the pre-tip base fare ($37.80).
    """
    gt = all_fixtures_data["INV-004"]
    norm = gt["normalized_expected"]

    subtotal = norm["subtotal"]
    tax = norm["tax_amount"]
    total = norm["total_amount"]
    line_items = norm["line_items"]

    items_sum = sum(item["total_price"] for item in line_items)
    assert round(items_sum, 2) == 42.80
    assert total == 42.80
    assert subtotal == 37.80
    assert tax == 0.0


# ==============================================================================
# 4. RapidFuzz Vendor Matching & Taxonomy Consistency
# ==============================================================================

@pytest.mark.parametrize("fixture_id", EXPECTED_FIXTURE_IDS)
def test_vendor_matching_confidence_tiers(fixture_id: str, all_fixtures_data: dict[str, dict[str, Any]]):
    """Verify that vendor_match_score correctly maps to RapidFuzz threshold tiers:
    - High match: >= 85.0 (Exact or minor suffix differences)
    - Moderate match: 70.0 - 84.9 (Thermal / noisy formatting)
    - Low / Unknown: < 70.0 (Unregistered vendor)
    """
    gt = all_fixtures_data[fixture_id]
    norm = gt["normalized_expected"]
    vendor_raw = norm["vendor_raw"]
    vendor_canonical = norm["vendor_canonical"]
    json_score = norm["vendor_match_score"]
    is_known = norm["is_known_vendor"]

    if fixture_id == "INV-009":
        # Luigi's Pizza & Catering: Unregistered vendor
        assert not is_known
        assert json_score < 70.0
        # When matched against known canonical vendors, best score must be < 70
        best_score = max(fuzz.token_sort_ratio(vendor_raw, kv) for kv in KNOWN_CANONICAL_VENDORS)
        assert best_score < 70.0
    elif fixture_id == "INV-004":
        # Uber thermal receipt: noisy token string
        assert is_known
        assert 70.0 <= json_score < 85.0
        assert vendor_canonical == "Uber Technologies"
    else:
        # Standard known vendors
        assert is_known
        assert json_score >= 85.0
        assert vendor_canonical in KNOWN_CANONICAL_VENDORS


# ==============================================================================
# 5. Duplicate Chain Consistency (INV-005, INV-006, INV-007)
# ==============================================================================

def test_duplicate_chain_rigorous_validation(all_fixtures_data: dict[str, dict[str, Any]]):
    """Adversarial stress test on duplicate detection window:
    - Base: INV-005 (2026-08-10, $500.00, Acme Corporation) -> is_duplicate = False
    - Duplicate: INV-006 (2026-08-13, $500.00, Acme Corporation) -> delta = +3 days (<= 7 days) -> is_duplicate = True, duplicate_of_id = INV-005
    - Non-Duplicate: INV-007 (2026-09-15, $500.00, Acme Corporation) -> delta = +36 days (> 7 days) -> is_duplicate = False
    """
    inv5 = all_fixtures_data["INV-005"]
    inv6 = all_fixtures_data["INV-006"]
    inv7 = all_fixtures_data["INV-007"]

    # Vendor and amount match
    assert inv5["normalized_expected"]["vendor_canonical"] == "Acme Corporation"
    assert inv6["normalized_expected"]["vendor_canonical"] == "Acme Corporation"
    assert inv7["normalized_expected"]["vendor_canonical"] == "Acme Corporation"

    assert inv5["normalized_expected"]["total_amount"] == 500.00
    assert inv6["normalized_expected"]["total_amount"] == 500.00
    assert inv7["normalized_expected"]["total_amount"] == 500.00

    d5 = datetime.strptime(inv5["normalized_expected"]["invoice_date"], "%Y-%m-%d").date()
    d6 = datetime.strptime(inv6["normalized_expected"]["invoice_date"], "%Y-%m-%d").date()
    d7 = datetime.strptime(inv7["normalized_expected"]["invoice_date"], "%Y-%m-%d").date()

    delta_5_6 = (d6 - d5).days
    delta_5_7 = (d7 - d5).days

    assert delta_5_6 == 3, f"Expected 3 days difference between INV-005 and INV-006, got {delta_5_6}"
    assert delta_5_7 == 36, f"Expected 36 days difference between INV-005 and INV-007, got {delta_5_7}"

    # Flag validations
    assert not inv5["expected_flags"]["is_duplicate"]
    assert inv6["expected_flags"]["is_duplicate"]
    assert inv6["expected_flags"]["duplicate_of_id"] == "INV-005"
    assert inv6["expected_flags"]["duplicate_match_details"]["days_difference"] == 3
    assert not inv7["expected_flags"]["is_duplicate"]


# ==============================================================================
# 6. Anomaly Detection Engine Invariant Checks
# ==============================================================================

def test_extreme_amount_anomaly_inv008(all_fixtures_data: dict[str, dict[str, Any]]):
    """INV-008 is an extreme anomaly ($1,250,000.00 > $50,000.00 threshold)."""
    inv8 = all_fixtures_data["INV-008"]
    assert inv8["normalized_expected"]["total_amount"] == 1250000.00
    assert inv8["expected_flags"]["has_anomalies"]
    assert inv8["expected_flags"]["risk_score"] >= 0.80

    flag_types = [fl["anomaly_type"] for fl in inv8["expected_flags"]["anomaly_flags"]]
    assert "extreme_amount" in flag_types


def test_unrecognized_vendor_anomaly_inv009(all_fixtures_data: dict[str, dict[str, Any]]):
    """INV-009 is an unrecognized vendor (Luigi's Pizza & Catering)."""
    inv9 = all_fixtures_data["INV-009"]
    assert not inv9["normalized_expected"]["is_known_vendor"]
    assert inv9["normalized_expected"]["vendor_match_score"] < 70.0
    assert inv9["expected_flags"]["has_anomalies"]
    assert inv9["expected_flags"]["risk_score"] >= 0.30

    flag_types = [fl["anomaly_type"] for fl in inv9["expected_flags"]["anomaly_flags"]]
    assert "unrecognized_vendor" in flag_types


@pytest.mark.parametrize("fixture_id", ["INV-001", "INV-002", "INV-003", "INV-004", "INV-005", "INV-007", "INV-010"])
def test_clean_fixtures_have_no_anomalies(fixture_id: str, all_fixtures_data: dict[str, dict[str, Any]]):
    """Standard / clean fixtures must have has_anomalies == False and risk_score == 0.0."""
    gt = all_fixtures_data[fixture_id]
    assert not gt["expected_flags"]["has_anomalies"], f"Fixture {fixture_id} unexpectedly flagged has_anomalies=True"
    assert gt["expected_flags"]["risk_score"] == 0.0, f"Fixture {fixture_id} has non-zero risk score {gt['expected_flags']['risk_score']}"
    assert len(gt["expected_flags"]["anomaly_flags"]) == 0, f"Fixture {fixture_id} has unexpected anomaly flags: {gt['expected_flags']['anomaly_flags']}"


# ==============================================================================
# 7. Generator Idempotency & Re-generation Test
# ==============================================================================

def test_generator_script_execution_in_temp_dir():
    """Verify that generate_fixtures.py can execute cleanly and output valid files to a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        cmd = [sys.executable, "tests/fixtures/generate_fixtures.py", "--output-dir", str(tmp_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"generate_fixtures.py failed with exit code {res.returncode}:\n{res.stderr}"

        # Verify all 10 fixtures generated
        manifest_p = tmp_path / "manifest.json"
        assert manifest_p.exists()
        with open(manifest_p, "r", encoding="utf-8") as f:
            m = json.load(f)
        assert m["total_fixtures"] == 10
        assert len(m["fixtures"]) == 10


# ==============================================================================
# 8. Pydantic Model Interoperability & Invariants
# ==============================================================================

@pytest.mark.parametrize("fixture_id", EXPECTED_FIXTURE_IDS)
def test_pydantic_model_deserialization(fixture_id: str, all_fixtures_data: dict[str, dict[str, Any]]):
    """Adversarially verify that all 10 ground truth JSONs cleanly convert to Pydantic v2 domain models."""
    from src.core.models import ExtractedField, LineItem, NormalizedInvoice

    gt = all_fixtures_data[fixture_id]
    norm = gt["normalized_expected"]

    model = NormalizedInvoice(
        vendor_name=ExtractedField(value=norm["vendor_raw"]),
        invoice_id=ExtractedField(value=norm["invoice_number"]),
        invoice_date=ExtractedField(value=norm["invoice_date"]),
        due_date=ExtractedField(value=norm.get("due_date")) if norm.get("due_date") else None,
        total_amount=ExtractedField(value=norm["total_amount"]),
        tax_amount=ExtractedField(value=norm.get("tax_amount")) if norm.get("tax_amount") is not None else None,
        subtotal_amount=ExtractedField(value=norm.get("subtotal")) if norm.get("subtotal") is not None else None,
        currency_raw=norm.get("currency_raw", "$"),
        currency_iso=norm.get("currency_iso", "USD"),
        vendor_raw=norm["vendor_raw"],
        vendor_canonical=norm["vendor_canonical"],
        vendor_match_score=norm["vendor_match_score"],
        is_known_vendor=norm["is_known_vendor"],
        spend_category=norm["spend_category"],
        line_items=[
            LineItem(
                item_id=it.get("item_id"),
                description=it.get("description"),
                quantity=it.get("quantity"),
                unit_price=it.get("unit_price"),
                total_amount=it.get("total_price"),
                category=it.get("category"),
            )
            for it in norm.get("line_items", [])
        ],
        is_duplicate=gt["expected_flags"]["is_duplicate"],
        duplicate_of_id=gt["expected_flags"]["duplicate_of_id"],
        has_anomalies=gt["expected_flags"]["has_anomalies"],
        risk_score=gt["expected_flags"]["risk_score"],
    )

    assert model.total_amount.value == norm["total_amount"]
    assert model.vendor_raw == norm["vendor_raw"]
    assert model.currency_iso == norm["currency_iso"]


def test_pairwise_10x10_duplicate_matrix(all_fixtures_data: dict[str, dict[str, Any]]):
    """Exhaustively test all 45 unique pairwise combinations of the 10 fixtures.
    Assert that EXACTLY ONE pair (INV-005 and INV-006) qualifies as duplicate.
    """
    fids = EXPECTED_FIXTURE_IDS
    duplicate_pairs = []

    for i in range(len(fids)):
        for j in range(i + 1, len(fids)):
            fid_a = fids[i]
            fid_b = fids[j]
            data_a = all_fixtures_data[fid_a]["normalized_expected"]
            data_b = all_fixtures_data[fid_b]["normalized_expected"]

            v_a = data_a["vendor_canonical"]
            v_b = data_b["vendor_canonical"]
            amt_a = data_a["total_amount"]
            amt_b = data_b["total_amount"]
            d_a = datetime.strptime(data_a["invoice_date"], "%Y-%m-%d").date()
            d_b = datetime.strptime(data_b["invoice_date"], "%Y-%m-%d").date()

            days_diff = abs((d_b - d_a).days)
            is_dup = (v_a == v_b and amt_a == amt_b and days_diff <= 7)

            if is_dup:
                duplicate_pairs.append((fid_a, fid_b, days_diff))

    assert len(duplicate_pairs) == 1, f"Expected exactly 1 duplicate pair in 10x10 matrix, got {duplicate_pairs}"
    assert duplicate_pairs[0] == ("INV-005", "INV-006", 3)


@pytest.mark.parametrize("fixture_id", EXPECTED_FIXTURE_IDS)
def test_currency_symbol_and_iso_alignment(fixture_id: str, all_fixtures_data: dict[str, dict[str, Any]]):
    """Verify that currency symbols match ISO 4217 representations."""
    gt = all_fixtures_data[fixture_id]
    raw_curr = gt["raw_extraction"]["currency"]
    norm_iso = gt["normalized_expected"]["currency_iso"]

    symbol_map = {"$": "USD", "€": "EUR", "¥": "JPY"}
    symbol = raw_curr.get("symbol")
    if symbol in symbol_map:
        assert symbol_map[symbol] == norm_iso, f"Symbol {symbol} mapped to {norm_iso} instead of {symbol_map[symbol]} in {fixture_id}"


@pytest.mark.parametrize("fixture_id", EXPECTED_FIXTURE_IDS)
def test_confidence_scores_and_non_null_invariants(fixture_id: str, all_fixtures_data: dict[str, dict[str, Any]]):
    """Adversarial check: no NaN, null, or out-of-range confidence scores in raw extractions."""
    gt = all_fixtures_data[fixture_id]
    raw = gt["raw_extraction"]

    for k, v in raw.items():
        if isinstance(v, dict) and "confidence" in v:
            conf = v["confidence"]
            assert conf is not None, f"Null confidence in {fixture_id}.raw_extraction.{k}"
            assert not math.isnan(conf), f"NaN confidence in {fixture_id}.raw_extraction.{k}"
            assert 0.0 <= conf <= 1.0, f"Confidence out of bounds ({conf}) in {fixture_id}.raw_extraction.{k}"

