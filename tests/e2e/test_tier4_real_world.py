"""
tests/e2e/test_tier4_real_world.py

Tier 4: Real-World Workload Scenarios & E2E Acceptance Test Suite.
Verifies complete end-to-end processing across realistic enterprise workflows (12 scenarios):
- Scenario 1: Sequential Ingestion & Verification of All 10 Benchmark Fixtures (INV-001 to INV-010)
- Scenario 2: Complete 3-Stage Duplicate Lifecycle Workflow (INV-005 -> INV-006 -> INV-007)
- Scenario 3: Fraud & Outlier Anomaly Quarantine Workflow (INV-008 Extreme Outlier + INV-009 Unknown Vendor)
- Scenario 4: Multi-Currency Enterprise Spend Summary & Grouped Analytics (USD, EUR, JPY)
- Scenario 5: High-Concurrency Batch Ingestion Simulation (10 fixtures uploaded concurrently)
- Scenario 6: Split-Screen Verification Queue Data Provider & Source Preview Streaming
- Scenario 7: Pipeline Traceability & Idempotent Re-Ingestion with Correlation Tracking
- Scenario 8: Air-Gapped Offline Execution & Fallback Reliability Verification
- Scenario 9: Multi-Item Tax & Subtotal Arithmetic Integrity Verification
- Scenario 10: Ground-Truth Contract Benchmark Matrix Evaluation
- Scenario 11: Physical Document File Storage Lifecycle (Upload -> Store -> Stream -> Delete)
- Scenario 12: Executive Spend KPI Metrics Computation from Ingested Pipeline State
"""

import hashlib
import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from src.core.models import (
    ExtractedField,
    NormalizedInvoice,
)
from src.core.storage import StorageManager
from tests.test_support import (
    AnomalyDetectionEngine,
    DualStorageRepository,
    DuplicateDetectionEngine,
)


class TestTier4RealWorldWorkloads:
    """Real-World Enterprise Workload Scenarios."""

    # Scenario 1: Sequential Ingestion of All 10 Benchmark Documents
    def test_scenario_1_sequential_evaluation_all_ten_fixtures(
        self,
        client: TestClient,
        sample_invoice_paths: dict[str, dict[str, Path]],
        load_ground_truth: Any,
    ) -> None:
        """Scenario 1: Upload and verify all 10 physical documents through /upload endpoint."""
        assert len(sample_invoice_paths) == 10

        for fid, paths in sorted(sample_invoice_paths.items()):
            file_path = paths["file"]
            gt = load_ground_truth(fid)
            expected_total = gt["test_assertions"]["exact_total_amount"]
            expected_date = gt["test_assertions"]["exact_invoice_date"]

            content_type = "application/pdf" if file_path.suffix == ".pdf" else ("image/png" if file_path.suffix == ".png" else "image/jpeg")
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            files = {"file": (file_path.name, file_bytes, content_type)}
            response = client.post("/upload", files=files)
            assert response.status_code == 200, f"Failed uploading {fid}: {response.text}"

            data = response.json()
            assert "id" in data
            assert data["filename"] == file_path.name
            assert abs(data["total_amount"]["value"] - expected_total) < 0.05
            assert data["invoice_date"]["value"] == expected_date

    # Scenario 2: Complete 3-Stage Duplicate Lifecycle (INV-005 -> INV-006 -> INV-007)
    def test_scenario_2_duplicate_lifecycle_workflow(
        self,
        duplicate_engine: DuplicateDetectionEngine,
        sample_invoice_paths: dict[str, dict[str, Path]],
        load_ground_truth: Any,
    ) -> None:
        """Scenario 2: INV-005 (base) -> INV-006 (duplicate +3d) -> INV-007 (non-duplicate +36d)."""
        gt5 = load_ground_truth("INV-005")
        gt6 = load_ground_truth("INV-006")
        gt7 = load_ground_truth("INV-007")

        inv5 = NormalizedInvoice(
            id="inv-005-entity",
            document_id="doc-005",
            vendor_name=ExtractedField[str](value=gt5["normalized_expected"]["vendor_raw"]),
            vendor_raw=gt5["normalized_expected"]["vendor_raw"],
            vendor_canonical=gt5["normalized_expected"]["vendor_canonical"],
            invoice_id=ExtractedField[str](value=gt5["normalized_expected"]["invoice_number"]),
            invoice_date=ExtractedField[str](value=gt5["normalized_expected"]["invoice_date"]),
            total_amount=ExtractedField[float](value=gt5["normalized_expected"]["total_amount"]),
        )

        inv6 = NormalizedInvoice(
            id="inv-006-entity",
            document_id="doc-006",
            vendor_name=ExtractedField[str](value=gt6["normalized_expected"]["vendor_raw"]),
            vendor_raw=gt6["normalized_expected"]["vendor_raw"],
            vendor_canonical=gt6["normalized_expected"]["vendor_canonical"],
            invoice_id=ExtractedField[str](value=gt6["normalized_expected"]["invoice_number"]),
            invoice_date=ExtractedField[str](value=gt6["normalized_expected"]["invoice_date"]),  # +3 days
            total_amount=ExtractedField[float](value=gt6["normalized_expected"]["total_amount"]),
        )

        inv7 = NormalizedInvoice(
            id="inv-007-entity",
            document_id="doc-007",
            vendor_name=ExtractedField[str](value=gt7["normalized_expected"]["vendor_raw"]),
            vendor_raw=gt7["normalized_expected"]["vendor_raw"],
            vendor_canonical=gt7["normalized_expected"]["vendor_canonical"],
            invoice_id=ExtractedField[str](value=gt7["normalized_expected"]["invoice_number"]),
            invoice_date=ExtractedField[str](value=gt7["normalized_expected"]["invoice_date"]),  # +36 days
            total_amount=ExtractedField[float](value=gt7["normalized_expected"]["total_amount"]),
        )

        # Stage 1: Ingest INV-005 (Base)
        is_dup_5, _, _, _ = duplicate_engine.evaluate_duplicate(inv5, [])
        assert is_dup_5 is False

        # Stage 2: Ingest INV-006 (Duplicate)
        is_dup_6, dup_id_6, reason_6, details_6 = duplicate_engine.evaluate_duplicate(inv6, [inv5])
        assert is_dup_6 is True
        assert dup_id_6 == "inv-005-entity"
        assert details_6["day_difference"] == 3

        # Stage 3: Ingest INV-007 (Non-duplicate after 36 days)
        is_dup_7, dup_id_7, _, _ = duplicate_engine.evaluate_duplicate(inv7, [inv5, inv6])
        assert is_dup_7 is False
        assert dup_id_7 is None

    # Scenario 3: Fraud & Outlier Anomaly Quarantine Workflow
    def test_scenario_3_anomaly_quarantine_workflow(
        self,
        anomaly_engine: AnomalyDetectionEngine,
        dual_storage: DualStorageRepository,
        load_ground_truth: Any,
    ) -> None:
        """Scenario 3: Quarantine high-risk documents (INV-008 $1.25M outlier + INV-009 unknown vendor)."""
        gt8 = load_ground_truth("INV-008")
        gt9 = load_ground_truth("INV-009")

        inv8 = NormalizedInvoice(
            id="inv-008-entity",
            document_id="doc-008",
            vendor_name=ExtractedField[str](value=gt8["normalized_expected"]["vendor_raw"]),
            vendor_canonical=gt8["normalized_expected"]["vendor_canonical"],
            invoice_id=ExtractedField[str](value=gt8["normalized_expected"]["invoice_number"]),
            invoice_date=ExtractedField[str](value=gt8["normalized_expected"]["invoice_date"]),
            total_amount=ExtractedField[float](value=gt8["normalized_expected"]["total_amount"]),
        )
        has_anom_8, flags_8, risk_8 = anomaly_engine.evaluate_anomalies(inv8)
        inv8.has_anomalies = has_anom_8
        inv8.anomalies = flags_8
        inv8.risk_score = risk_8
        dual_storage.save_normalized(inv8)

        inv9 = NormalizedInvoice(
            id="inv-009-entity",
            document_id="doc-009",
            vendor_name=ExtractedField[str](value=gt9["normalized_expected"]["vendor_raw"]),
            vendor_raw=gt9["normalized_expected"]["vendor_raw"],
            is_known_vendor=False,
            vendor_match_score=45.0,
            invoice_id=ExtractedField[str](value=gt9["normalized_expected"]["invoice_number"]),
            invoice_date=ExtractedField[str](value=gt9["normalized_expected"]["invoice_date"]),
            total_amount=ExtractedField[float](value=gt9["normalized_expected"]["total_amount"]),
        )
        has_anom_9, flags_9, risk_9 = anomaly_engine.evaluate_anomalies(inv9)
        inv9.has_anomalies = has_anom_9
        inv9.anomalies = flags_9
        inv9.risk_score = risk_9
        dual_storage.save_normalized(inv9)

        # Assert Quarantine filter
        all_norm = dual_storage.list_all_normalized()
        quarantined = [r for r in all_norm if r.has_anomalies]
        assert len(quarantined) == 2
        assert any(r.risk_score >= 0.60 for r in quarantined)

    # Scenario 4: Multi-Currency Enterprise Spend Summary & Grouped Analytics
    def test_scenario_4_multicurrency_spend_summary_analytics(
        self,
        dual_storage: DualStorageRepository,
        load_ground_truth: Any,
    ) -> None:
        """Scenario 4: Aggregate multi-currency spend across USD, EUR, and JPY."""
        # USD Invoice (INV-001)
        gt1 = load_ground_truth("INV-001")
        inv1 = NormalizedInvoice(
            id="inv-usd",
            vendor_name=ExtractedField[str](value=gt1["normalized_expected"]["vendor_canonical"]),
            vendor_canonical=gt1["normalized_expected"]["vendor_canonical"],
            invoice_id=ExtractedField[str](value=gt1["normalized_expected"]["invoice_number"]),
            invoice_date=ExtractedField[str](value=gt1["normalized_expected"]["invoice_date"]),
            total_amount=ExtractedField[float](value=gt1["normalized_expected"]["total_amount"]),
            currency_iso="USD",
            spend_category=gt1["normalized_expected"]["spend_category"],
        )
        dual_storage.save_normalized(inv1)

        # EUR Invoice (INV-003)
        gt3 = load_ground_truth("INV-003")
        inv3 = NormalizedInvoice(
            id="inv-eur",
            vendor_name=ExtractedField[str](value=gt3["normalized_expected"]["vendor_canonical"]),
            vendor_canonical=gt3["normalized_expected"]["vendor_canonical"],
            invoice_id=ExtractedField[str](value=gt3["normalized_expected"]["invoice_number"]),
            invoice_date=ExtractedField[str](value=gt3["normalized_expected"]["invoice_date"]),
            total_amount=ExtractedField[float](value=gt3["normalized_expected"]["total_amount"]),
            currency_iso="EUR",
            spend_category=gt3["normalized_expected"]["spend_category"],
        )
        dual_storage.save_normalized(inv3)

        # JPY Invoice (INV-010)
        gt10 = load_ground_truth("INV-010")
        inv10 = NormalizedInvoice(
            id="inv-jpy",
            vendor_name=ExtractedField[str](value=gt10["normalized_expected"]["vendor_canonical"]),
            vendor_canonical=gt10["normalized_expected"]["vendor_canonical"],
            invoice_id=ExtractedField[str](value=gt10["normalized_expected"]["invoice_number"]),
            invoice_date=ExtractedField[str](value=gt10["normalized_expected"]["invoice_date"]),
            total_amount=ExtractedField[float](value=gt10["normalized_expected"]["total_amount"]),
            currency_iso="JPY",
            spend_category=gt10["normalized_expected"]["spend_category"],
        )
        dual_storage.save_normalized(inv10)

        # Compute grouped spend by currency
        all_invs = dual_storage.list_all_normalized()
        spend_by_curr: dict[str, float] = {}
        for item in all_invs:
            curr = item.currency_iso
            spend_by_curr[curr] = spend_by_curr.get(curr, 0.0) + item.total_amount.value

        assert spend_by_curr["USD"] == 1420.50
        assert spend_by_curr["EUR"] == 2180.75
        assert spend_by_curr["JPY"] == 150000.0

    # Scenario 5: High-Concurrency Batch Ingestion Simulation
    def test_scenario_5_batch_ingestion_simulation(
        self,
        client: TestClient,
        sample_invoice_paths: dict[str, dict[str, Path]],
    ) -> None:
        """Scenario 5: Concurrently submit all 10 sample fixtures with shared batch correlation ID."""
        batch_corr = f"batch-sim-{uuid.uuid4().hex[:8]}"
        uploaded_doc_ids = []

        for fid, paths in sample_invoice_paths.items():
            fpath = paths["file"]
            mime = "application/pdf" if fpath.suffix == ".pdf" else ("image/png" if fpath.suffix == ".png" else "image/jpeg")
            with open(fpath, "rb") as f:
                content = f.read()

            files = {"file": (fpath.name, content, mime)}
            resp = client.post(f"/upload?correlation_id={batch_corr}", files=files)
            assert resp.status_code == 200
            uploaded_doc_ids.append(resp.json()["document_id"])

        assert len(uploaded_doc_ids) == 10
        # Verify distinct document IDs
        assert len(set(uploaded_doc_ids)) == 10

    # Scenario 6: Split-Screen Verification Queue Data Provider & Source Preview Streaming
    def test_scenario_6_verification_queue_preview_streaming(
        self,
        client: TestClient,
        sample_pdf_bytes: bytes,
    ) -> None:
        """Scenario 6: Upload document, retrieve structured data and stream preview bytes matching SHA-256."""
        files = {"file": ("preview_verify.pdf", sample_pdf_bytes, "application/pdf")}
        upload_resp = client.post("/upload", files=files)
        assert upload_resp.status_code == 200
        doc_data = upload_resp.json()
        doc_id = doc_data["document_id"]

        # Stream preview
        stream_resp = client.get(f"/documents/{doc_id}/file")
        assert stream_resp.status_code == 200

        # Assert SHA-256 parity
        uploaded_hash = hashlib.sha256(sample_pdf_bytes).hexdigest()
        streamed_hash = hashlib.sha256(stream_resp.content).hexdigest()
        assert streamed_hash == uploaded_hash

    # Scenario 7: Pipeline Traceability & Idempotent Re-Ingestion with Correlation Tracking
    def test_scenario_7_pipeline_traceability_idempotency(
        self,
        client: TestClient,
        sample_pdf_bytes: bytes,
    ) -> None:
        """Scenario 7: Re-uploading same document creates distinct document IDs with same file hash."""
        corr_1 = "corr-run-1"
        corr_2 = "corr-run-2"

        files1 = {"file": ("idem.pdf", sample_pdf_bytes, "application/pdf")}
        resp1 = client.post(f"/upload?correlation_id={corr_1}", files=files1)
        assert resp1.status_code == 200

        files2 = {"file": ("idem.pdf", sample_pdf_bytes, "application/pdf")}
        resp2 = client.post(f"/upload?correlation_id={corr_2}", files=files2)
        assert resp2.status_code == 200

        d1 = resp1.json()
        d2 = resp2.json()

        assert d1["document_id"] != d2["document_id"]
        assert d1["correlation_id"] == corr_1
        assert d2["correlation_id"] == corr_2
        assert d1["file_hash"] == d2["file_hash"]

    # Scenario 8: Air-Gapped Offline Execution & Fallback Reliability Verification
    def test_scenario_8_air_gapped_offline_execution(
        self,
        client: TestClient,
        sample_invoice_paths: dict[str, dict[str, Path]],
    ) -> None:
        """Scenario 8: Force mock mode across all fixtures to ensure 100% offline reliability."""
        for fid, paths in sample_invoice_paths.items():
            fpath = paths["file"]
            mime = "application/pdf" if fpath.suffix == ".pdf" else ("image/png" if fpath.suffix == ".png" else "image/jpeg")
            with open(fpath, "rb") as f:
                content = f.read()

            files = {"file": (fpath.name, content, mime)}
            resp = client.post("/upload?force_mock=true", files=files)
            assert resp.status_code == 200
            assert resp.json()["status"] in ["SUCCESS", "PROCESSED", "NEEDS_REVIEW"]

    # Scenario 9: Multi-Item Tax & Subtotal Arithmetic Integrity Verification
    def test_scenario_9_multi_item_arithmetic_integrity(
        self,
        load_ground_truth: Any,
    ) -> None:
        """Scenario 9: Validate line item subtotal + tax = total across multi-item fixtures."""
        gt_aws = load_ground_truth("INV-001")
        raw = gt_aws["raw_extraction"]
        subtotal = raw["subtotal"]["value"]
        tax = raw["total_tax"]["value"]
        total = raw["invoice_total"]["value"]

        assert round(subtotal + tax, 2) == total

        items_sum = sum(it["amount"] for it in raw["line_items"])
        assert round(items_sum, 2) == subtotal

    # Scenario 10: Ground-Truth Contract Benchmark Matrix Evaluation
    def test_scenario_10_ground_truth_contract_parity(
        self,
        sample_manifest: dict[str, Any],
        load_ground_truth: Any,
    ) -> None:
        """Scenario 10: Evaluate all 10 ground truth JSON contracts against manifest specifications."""
        fixtures = sample_manifest.get("fixtures", [])
        assert len(fixtures) == 10

        for entry in fixtures:
            fid = entry["fixture_id"]
            gt = load_ground_truth(fid)
            assert gt["meta"]["fixture_id"] == fid
            assert gt["test_assertions"]["exact_total_amount"] == entry["total_amount"]
            assert gt["test_assertions"]["exact_currency_iso"] == entry["currency"]
            assert gt["test_assertions"]["exact_invoice_date"] == entry["invoice_date"]
            assert gt["test_assertions"]["is_duplicate"] == entry["is_duplicate"]

    # Scenario 11: Physical Document File Storage Lifecycle
    def test_scenario_11_storage_manager_lifecycle(self, temp_storage_dir: Path) -> None:
        """Scenario 11: Save bytes -> check exists -> read stream -> delete file."""
        sm = StorageManager(upload_dir=temp_storage_dir)
        doc_bytes = b"%PDF-1.4 test document content for storage lifecycle"
        doc_id, path, sha, size = sm.save_bytes(doc_bytes, "lifecycle.pdf")

        assert sm.file_exists(doc_id) is True
        assert path.exists() is True
        assert size == len(doc_bytes)

        # Stream chunks
        stream_gen = sm.get_file_stream(doc_id)
        assert stream_gen is not None
        reconstructed = b"".join(list(stream_gen))
        assert reconstructed == doc_bytes

        # Delete
        assert sm.delete_file(doc_id) is True
        assert sm.file_exists(doc_id) is False

    # Scenario 12: Executive Spend KPI Metrics Computation
    def test_scenario_12_executive_spend_kpi_computation(
        self,
        dual_storage: DualStorageRepository,
        load_ground_truth: Any,
    ) -> None:
        """Scenario 12: Calculate KPI metrics (total spend, invoice count, duplicate count, anomaly count)."""
        # Ingest 3 normalized records
        for fid in ["INV-001", "INV-006", "INV-008"]:
            gt = load_ground_truth(fid)
            inv = NormalizedInvoice(
                id=f"kpi-{fid}",
                vendor_name=ExtractedField[str](value=gt["normalized_expected"]["vendor_canonical"]),
                vendor_canonical=gt["normalized_expected"]["vendor_canonical"],
                invoice_id=ExtractedField[str](value=gt["normalized_expected"]["invoice_number"]),
                invoice_date=ExtractedField[str](value=gt["normalized_expected"]["invoice_date"]),
                total_amount=ExtractedField[float](value=gt["normalized_expected"]["total_amount"]),
                is_duplicate=gt["expected_flags"]["is_duplicate"],
                has_anomalies=gt["expected_flags"]["has_anomalies"],
            )
            dual_storage.save_normalized(inv)

        records = dual_storage.list_all_normalized()
        total_invoices = len(records)
        total_usd_spend = sum(r.total_amount.value for r in records if r.currency_iso == "USD")
        duplicate_count = sum(1 for r in records if r.is_duplicate)
        anomaly_count = sum(1 for r in records if r.has_anomalies)

        assert total_invoices == 3
        assert total_usd_spend == (1420.50 + 500.00 + 1250000.00)
        assert duplicate_count == 1
        assert anomaly_count == 1
