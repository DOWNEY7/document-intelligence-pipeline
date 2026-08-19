"""
Shared Pytest Fixtures for Document Intelligence Pipeline Test Suites.
Provides TestClient, temporary storage, PDF/Image byte generators, mock Azure response loaders,
MockAnalyzeResultBuilder, ground truth dataset fixtures, and comparison assertion helpers.
"""

import io
import json
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from src.api.app import create_app
from src.config import Settings, get_settings
from src.core.models import (
    ConfidenceBreakdown,
    ExtractedField,
    LineItem,
    NormalizedInvoice,
)
from src.core.storage import StorageManager, get_storage_service
from src.services.extraction.service import ExtractionService, get_extraction_service

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = WORKSPACE_ROOT / "tests" / "fixtures"
SAMPLE_INVOICES_DIR = FIXTURES_DIR / "sample_invoices"
MOCK_AZURE_DIR = FIXTURES_DIR / "mock_azure_responses"


# ============================================================================
# Core Storage & Settings Fixtures
# ============================================================================

@pytest.fixture
def temp_storage_dir(tmp_path: Path) -> Path:
    """Creates an isolated temporary directory for file uploads."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


@pytest.fixture
def test_settings(temp_storage_dir: Path) -> Settings:
    """Provides test application settings with mock mode forced and temp storage."""
    return Settings(
        APP_NAME="Test Document Intelligence Pipeline",
        APP_VERSION="0.1.0-test",
        DEBUG=True,
        USE_MOCK_AZURE=True,
        AZURE_FORM_RECOGNIZER_ENDPOINT="https://mock-endpoint.cognitiveservices.azure.com/",
        AZURE_FORM_RECOGNIZER_KEY="mock-secret-key-12345",
        DATA_DIR=temp_storage_dir.parent,
        UPLOAD_DIR=temp_storage_dir,
        STORE_DIR=temp_storage_dir.parent / "store",
        MAX_UPLOAD_SIZE_MB=5,
        MAX_UPLOAD_SIZE_BYTES=5 * 1024 * 1024,
    )


@pytest.fixture
def client(test_settings: Settings) -> Generator[TestClient, None, None]:
    """Provides a FastAPI TestClient instance configured with test settings."""
    from src.services.pipeline import PipelineService, get_pipeline_service
    from src.services.normalization import get_normalization_service
    from src.services.storage import get_storage_repository

    app = create_app(settings=test_settings)

    # Override settings dependency
    app.dependency_overrides[get_settings] = lambda: test_settings
    storage = StorageManager(upload_dir=test_settings.UPLOAD_DIR, settings_obj=test_settings)
    extraction_svc = ExtractionService(settings_obj=test_settings)
    normalization_svc = get_normalization_service(test_settings)
    storage_repo = get_storage_repository(test_settings)
    pipeline_svc = PipelineService(
        storage_manager=storage,
        extraction_service=extraction_svc,
        normalization_service=normalization_svc,
        storage_repository=storage_repo,
        settings_obj=test_settings,
    )

    app.dependency_overrides[get_storage_service] = lambda: storage
    app.dependency_overrides[get_extraction_service] = lambda: extraction_svc
    app.dependency_overrides[get_pipeline_service] = lambda: pipeline_svc
    app.dependency_overrides[get_storage_repository] = lambda: storage_repo

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# ============================================================================
# Synthetic Document Byte Generators
# ============================================================================

@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Generates valid PDF bytes containing invoice text using ReportLab."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.drawString(100, 750, "INVOICE")
    c.drawString(100, 720, "Vendor: Amazon Web Services Inc.")
    c.drawString(100, 700, "Invoice Number: INV-2026-001")
    c.drawString(100, 680, "Invoice Date: 2026-08-01")
    c.drawString(100, 660, "Due Date: 2026-08-31")
    c.drawString(100, 620, "Description: Cloud Compute EC2")
    c.drawString(100, 600, "Subtotal: $1,200.00")
    c.drawString(100, 580, "Tax: $220.50")
    c.drawString(100, 560, "Total: $1,420.50")
    c.save()
    return buffer.getvalue()


@pytest.fixture
def sample_png_bytes() -> bytes:
    """Generates a valid PNG image byte stream using Pillow."""
    buffer = io.BytesIO()
    img = Image.new("RGB", (200, 200), color=(240, 240, 240))
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def sample_jpg_bytes() -> bytes:
    """Generates a valid JPEG image byte stream using Pillow."""
    buffer = io.BytesIO()
    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    img.save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def sample_normalized_invoice() -> NormalizedInvoice:
    """Provides a sample NormalizedInvoice model for unit testing."""
    return NormalizedInvoice(
        document_id="test-doc-uuid-1234",
        correlation_id="test-corr-uuid-5678",
        filename="sample_invoice.pdf",
        storage_path="data/uploads/test-doc-uuid-1234_sample_invoice.pdf",
        vendor_name=ExtractedField[str](value="Amazon Web Services Inc.", confidence=0.98),
        invoice_id=ExtractedField[str](value="INV-2026-001", confidence=0.95),
        invoice_date=ExtractedField[str](value="2026-08-01", confidence=0.99),
        due_date=ExtractedField[str](value="2026-08-31", confidence=0.92),
        total_amount=ExtractedField[float](value=1420.50, confidence=0.97),
        tax_amount=ExtractedField[float](value=220.50, confidence=0.90),
        subtotal_amount=ExtractedField[float](value=1200.00, confidence=0.95),
        currency=ExtractedField[str](value="USD", confidence=1.0),
        currency_raw="$",
        currency_iso="USD",
        line_items=[
            LineItem(
                description="Cloud Compute EC2 Instances",
                quantity=1.0,
                unit_price=1200.00,
                total_amount=1200.00,
                confidence=0.95,
            )
        ],
        confidence_score=0.96,
        confidence_breakdown=ConfidenceBreakdown(
            overall=0.96,
            vendor=0.98,
            invoice_id=0.95,
            date=0.99,
            total=0.97,
            line_items=0.95,
            field_scores={"vendor_name": 0.98, "total_amount": 0.97},
        ),
        status="SUCCESS",
        anomalies=[],
        extraction_engine="mock_fallback",
        created_at=datetime.now(UTC).isoformat(),
    )


# ============================================================================
# Mock Azure Document Intelligence Objects & Builder
# ============================================================================

class MockAnalyzeResultBuilder:
    """Constructs dynamic mock SDK AnalyzeResult objects from mock Azure JSON files."""

    @staticmethod
    def from_json_dict(data: dict[str, Any]) -> MagicMock:
        """Parse raw JSON dict into mock Azure SDK DocumentIntelligence AnalyzeResult."""
        mock_result = MagicMock()
        mock_result.content = data.get("content", "")
        mock_result.documents = []

        for doc_dict in data.get("documents", []):
            mock_doc = MagicMock()
            mock_doc.doc_type = doc_dict.get("docType", "invoice")
            mock_doc.confidence = doc_dict.get("confidence", 0.98)
            mock_doc.fields = {}

            for field_name, f_val in doc_dict.get("fields", {}).items():
                mock_field = MagicMock()
                mock_field.confidence = f_val.get("confidence", 0.98)
                mock_field.content = f_val.get("content", "")

                # Bounding regions
                b_regions = []
                for br in f_val.get("boundingRegions", []):
                    reg_mock = MagicMock()
                    reg_mock.page_number = br.get("pageNumber", 1)
                    reg_mock.polygon = br.get("polygon", [])
                    b_regions.append(reg_mock)
                mock_field.bounding_regions = b_regions

                f_type = f_val.get("type")
                if f_type == "string":
                    mock_field.value_string = f_val.get("valueString")
                elif f_type == "date":
                    mock_field.value_date = f_val.get("valueDate")
                elif f_type == "currency":
                    curr_info = f_val.get("valueCurrency", {})
                    curr_mock = MagicMock()
                    curr_mock.amount = curr_info.get("amount")
                    curr_mock.currency_symbol = curr_info.get("currencySymbol", "$")
                    mock_field.value_currency = curr_mock
                elif f_type == "number":
                    mock_field.value_number = f_val.get("valueNumber")
                elif f_type == "array" and field_name == "Items":
                    mock_items = []
                    for item_elem in f_val.get("valueArray", []):
                        mock_item = MagicMock()
                        mock_item.confidence = item_elem.get("confidence", 0.95)
                        obj_dict = item_elem.get("valueObject", {})
                        mock_item.value_object = {}
                        for sub_k, sub_v in obj_dict.items():
                            sub_mock = MagicMock()
                            sub_mock.confidence = sub_v.get("confidence", 0.95)
                            sub_mock.content = sub_v.get("content", "")
                            sub_mock.bounding_regions = []
                            if sub_v.get("type") == "string":
                                sub_mock.value_string = sub_v.get("valueString")
                            elif sub_v.get("type") == "number":
                                sub_mock.value_number = sub_v.get("valueNumber")
                            elif sub_v.get("type") == "currency":
                                c_info = sub_v.get("valueCurrency", {})
                                c_m = MagicMock()
                                c_m.amount = c_info.get("amount")
                                c_m.currency_symbol = c_info.get("currencySymbol", "$")
                                sub_mock.value_currency = c_m
                            mock_item.value_object[sub_k] = sub_mock
                        mock_items.append(mock_item)
                    mock_field.value_array = mock_items

                mock_doc.fields[field_name] = mock_field
            mock_result.documents.append(mock_doc)

        return mock_result


@pytest.fixture
def mock_azure_response_loader() -> Callable[[str], MagicMock]:
    """Fixture providing a function to load mock Azure AnalyzeResult objects by fixture name or ID."""
    def _loader(fixture_name_or_id: str) -> MagicMock:
        clean_name = fixture_name_or_id.replace("-", "_").lower()
        target_file = None
        for path in MOCK_AZURE_DIR.glob("*.json"):
            if clean_name in path.name.lower():
                target_file = path
                break
        if not target_file:
            raise FileNotFoundError(f"Mock Azure response for '{fixture_name_or_id}' not found in {MOCK_AZURE_DIR}")
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return MockAnalyzeResultBuilder.from_json_dict(data)
    return _loader


# ============================================================================
# Ground Truth Dataset & Fixtures Directory Helpers
# ============================================================================

@pytest.fixture
def sample_fixtures_dir() -> Path:
    """Returns Path to tests/fixtures/sample_invoices/."""
    return SAMPLE_INVOICES_DIR


@pytest.fixture
def mock_azure_responses_dir() -> Path:
    """Returns Path to tests/fixtures/mock_azure_responses/."""
    return MOCK_AZURE_DIR


@pytest.fixture
def sample_manifest() -> dict[str, Any]:
    """Loads manifest.json describing all 10 sample fixtures."""
    manifest_path = SAMPLE_INVOICES_DIR / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def load_ground_truth() -> Callable[[str], dict[str, Any]]:
    """Fixture providing a function to load ground truth JSON for a fixture ID or name."""
    def _loader(fixture_name_or_id: str) -> dict[str, Any]:
        clean_name = fixture_name_or_id.replace("-", "_").lower()
        target_file = None
        for path in SAMPLE_INVOICES_DIR.glob("*.json"):
            if clean_name in path.name.lower() and path.name != "manifest.json":
                target_file = path
                break
        if not target_file:
            raise FileNotFoundError(f"Ground truth JSON for '{fixture_name_or_id}' not found in {SAMPLE_INVOICES_DIR}")
        with open(target_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return _loader


@pytest.fixture
def sample_invoice_paths(sample_manifest: dict[str, Any]) -> dict[str, dict[str, Path]]:
    """
    Returns a dictionary mapping fixture_id (e.g. 'INV-001') to a dictionary of:
    - 'file': Path to physical file (PDF/PNG/JPG)
    - 'gt_json': Path to ground truth JSON
    - 'mock_azure_json': Path to mock Azure response JSON
    """
    catalog = {}
    for entry in sample_manifest.get("fixtures", []):
        fid = entry["fixture_id"]
        fname = entry["filename"]
        gt_name = entry["ground_truth_json"]
        catalog[fid] = {
            "file": SAMPLE_INVOICES_DIR / fname,
            "gt_json": SAMPLE_INVOICES_DIR / gt_name,
            "mock_azure_json": MOCK_AZURE_DIR / gt_name,
        }
    return catalog


# ============================================================================
# Domain Engine Fixtures
# ============================================================================

@pytest.fixture
def vendor_matcher() -> Any:
    """Provides VendorMatcherEngine instance."""
    from tests.test_support import VendorMatcherEngine
    return VendorMatcherEngine()


@pytest.fixture
def taxonomy_engine() -> Any:
    """Provides SpendTaxonomyEngine instance."""
    from tests.test_support import SpendTaxonomyEngine
    return SpendTaxonomyEngine()


@pytest.fixture
def duplicate_engine() -> Any:
    """Provides DuplicateDetectionEngine instance."""
    from tests.test_support import DuplicateDetectionEngine
    return DuplicateDetectionEngine(window_days=7)


@pytest.fixture
def anomaly_engine() -> Any:
    """Provides AnomalyDetectionEngine instance."""
    from tests.test_support import AnomalyDetectionEngine
    return AnomalyDetectionEngine(extreme_amount_threshold=50000.0)


@pytest.fixture
def dual_storage() -> Any:
    """Provides DualStorageRepository instance."""
    from tests.test_support import DualStorageRepository
    return DualStorageRepository()
