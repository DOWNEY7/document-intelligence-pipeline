"""
Unit Tests for FastAPI Ingestion API Endpoints and Storage Manager.
Document Intelligence Pipeline - Milestone 1
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config import Settings
from src.core.storage import StorageManager, sanitize_filename


class TestStorageManager:
    def test_storage_save_and_retrieve_bytes(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        content = b"PDF dummy content for storage testing"
        doc_id, path, file_hash, size = manager.save_bytes(content, "test_invoice.pdf")

        assert doc_id is not None
        assert path.exists()
        assert size == len(content)
        assert manager.file_exists(doc_id) is True

        retrieved = manager.get_file_bytes(doc_id)
        assert retrieved == content

        # Check path lookup
        found_path = manager.get_file_path(doc_id)
        assert found_path == path

    def test_storage_filename_sanitization(self):
        dirty = "../../etc/passwd/malicious...invoice?.pdf"
        clean = sanitize_filename(dirty)
        assert "/" not in clean
        assert "\\" not in clean
        assert ".." not in clean
        assert clean.endswith(".pdf")

    def test_storage_file_stream(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        content = b"Stream chunk test byte data" * 100
        doc_id, path, _, _ = manager.save_bytes(content, "stream_test.pdf")

        stream_gen = manager.get_file_stream(doc_id, chunk_size=64)
        assert stream_gen is not None
        collected = b"".join(list(stream_gen))
        assert collected == content

    def test_storage_delete_file(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        doc_id, path, _, _ = manager.save_bytes(b"data to delete", "delete_me.pdf")
        assert manager.file_exists(doc_id) is True

        deleted = manager.delete_file(doc_id)
        assert deleted is True
        assert manager.file_exists(doc_id) is False

    def test_storage_list_files(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        doc_id, _, _, _ = manager.save_bytes(b"some content", "list_item.pdf")
        files = manager.list_files()
        assert any(f["document_id"] == doc_id for f in files)

    def test_storage_empty_file_rejected(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        with pytest.raises(ValueError, match="empty file"):
            manager.save_bytes(b"", "empty.pdf")


class TestApiEndpoints:
    def test_health_check_endpoint(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["mock_mode"] is True

        response_v1 = client.get("/api/v1/health")
        assert response_v1.status_code == 200
        data_v1 = response_v1.json()
        assert data_v1["status"] == "healthy"

    def test_upload_pdf_document_root(self, client: TestClient, sample_pdf_bytes: bytes):
        files = {"file": ("inv_001_standard_aws.pdf", sample_pdf_bytes, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        data = response.json()

        assert "document_id" in data
        assert data["vendor_name"]["value"] == "Amazon Web Services Inc."
        assert data["total_amount"]["value"] == 1420.50
        assert data["status"] in ["SUCCESS", "NEEDS_REVIEW"]
        assert len(data["line_items"]) > 0

    def test_upload_pdf_document_v1(self, client: TestClient, sample_pdf_bytes: bytes):
        files = {"file": ("aws_invoice.pdf", sample_pdf_bytes, "application/pdf")}
        response = client.post("/api/v1/upload?force_mock=true", files=files)
        assert response.status_code == 200
        data = response.json()
        assert "document_id" in data
        assert data["total_amount"]["value"] > 0

    def test_upload_png_image(self, client: TestClient, sample_png_bytes: bytes):
        files = {"file": ("receipt.png", sample_png_bytes, "image/png")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        assert "document_id" in data
        assert data["status"] in ["SUCCESS", "NEEDS_REVIEW"]

    def test_upload_jpg_image(self, client: TestClient, sample_jpg_bytes: bytes):
        files = {"file": ("receipt.jpg", sample_jpg_bytes, "image/jpeg")}
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        assert "document_id" in data

    def test_upload_invalid_extension_rejected(self, client: TestClient):
        files = {"file": ("malicious_script.exe", b"binary content", "application/octet-stream")}
        response = client.post("/upload", files=files)
        assert response.status_code == 400
        assert "Unsupported file extension" in response.json()["detail"]

    def test_upload_empty_file_rejected(self, client: TestClient):
        files = {"file": ("empty_invoice.pdf", b"", "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_upload_oversized_file_rejected(self, client: TestClient, test_settings: Settings):
        oversized = b"A" * (test_settings.MAX_UPLOAD_SIZE_BYTES + 1024)
        files = {"file": ("huge_invoice.pdf", oversized, "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code in [400, 413]

    def test_document_file_retrieval(self, client: TestClient, sample_pdf_bytes: bytes):
        # 1. Upload a file
        files = {"file": ("test_preview.pdf", sample_pdf_bytes, "application/pdf")}
        upload_resp = client.post("/upload", files=files)
        assert upload_resp.status_code == 200
        doc_id = upload_resp.json()["document_id"]

        # 2. Retrieve the file
        get_resp = client.get(f"/documents/{doc_id}/file")
        assert get_resp.status_code == 200
        assert get_resp.content == sample_pdf_bytes
        assert "inline" in get_resp.headers.get("content-disposition", "").lower()

        # 3. Retrieve via v1 prefix
        get_v1_resp = client.get(f"/api/v1/documents/{doc_id}/file")
        assert get_v1_resp.status_code == 200
        assert get_v1_resp.content == sample_pdf_bytes

    def test_document_file_not_found(self, client: TestClient):
        response = client.get("/documents/non-existent-doc-id/file")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
