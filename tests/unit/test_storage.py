"""
Comprehensive Unit Tests for Storage Manager and Services.
Document Intelligence Pipeline - Milestone 1
"""

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import UploadFile

from src.config import Settings
from src.core.storage import (
    StorageManager,
    StorageService,
    compute_sha256,
    generate_document_id,
    get_file_extension,
    get_storage_service,
    sanitize_filename,
)


class TestStorageComprehensive:
    def test_generate_document_id(self):
        doc_id = generate_document_id()
        assert isinstance(doc_id, str)
        assert len(doc_id) == 36

    def test_compute_sha256(self):
        data = b"hello document intelligence"
        h = compute_sha256(data)
        assert len(h) == 64
        assert h == "ada206e139d4a3c1735b6229942b7eac4ccbca1c7ca421458a1b7dc122f7f25f"

    def test_sanitize_filename_edge_cases(self):
        assert sanitize_filename("") == "unnamed_document.bin"
        assert sanitize_filename(None) == "unnamed_document.bin"
        assert sanitize_filename("simple.pdf") == "simple.pdf"
        assert sanitize_filename(r"C:\Users\Admin\invoice.pdf") == "invoice.pdf"
        assert sanitize_filename("/var/log/../../bad.png") == "bad.png"

    def test_get_file_extension(self):
        assert get_file_extension("invoice.PDF") == ".pdf"
        assert get_file_extension("file_without_ext") == ".bin"
        assert get_file_extension("image.jpeg") == ".jpeg"

    def test_validate_file_extensions_and_mimes(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)

        # Valid PDF
        valid, err = manager.validate_file("inv.pdf", content_type="application/pdf", file_size=1000)
        assert valid is True
        assert err is None

        # Unsupported extension
        valid, err = manager.validate_file("script.py", content_type="text/x-python", file_size=100)
        assert valid is False
        assert "Unsupported file extension" in err

        # File size exceeds limit
        valid, err = manager.validate_file("large.pdf", file_size=test_settings.MAX_UPLOAD_SIZE_BYTES + 100)
        assert valid is False
        assert "File size exceeds" in err

        # Unsupported MIME type
        valid, err = manager.validate_file("test.pdf", content_type="application/x-msdownload")
        assert valid is False
        assert "Unsupported MIME" in err

    def test_get_content_type(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)

        assert manager.get_content_type(Path("doc.pdf")) == "application/pdf"
        assert manager.get_content_type(Path("img.png")) == "image/png"
        assert manager.get_content_type(Path("img.jpg")) == "image/jpeg"
        assert manager.get_content_type(Path("img.jpeg")) == "image/jpeg"
        assert manager.get_content_type(Path("img.tiff")) == "image/tiff"
        assert manager.get_content_type(Path("img.bmp")) == "image/bmp"
        assert manager.get_content_type(Path("unknown.xyz")) == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_save_upload_file_async(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)

        content = b"Async upload file bytes content"
        file_obj = io.BytesIO(content)
        upload_file = UploadFile(file=file_obj, filename="async_inv.pdf")

        doc_id, path, file_hash, size = await manager.save_upload_file(upload_file)
        assert doc_id is not None
        assert path.exists()
        assert size == len(content)
        assert file_hash == compute_sha256(content)

    @pytest.mark.asyncio
    async def test_save_upload_file_empty_raises(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        empty_upload = UploadFile(file=io.BytesIO(b""), filename="empty.pdf")
        with pytest.raises(ValueError, match="empty"):
            await manager.save_upload_file(empty_upload)

    @pytest.mark.asyncio
    async def test_save_upload_file_oversized_raises(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        oversized = b"X" * (test_settings.MAX_UPLOAD_SIZE_BYTES + 1024)
        huge_upload = UploadFile(file=io.BytesIO(oversized), filename="huge.pdf")
        with pytest.raises(ValueError, match="maximum limit"):
            await manager.save_upload_file(huge_upload)

    def test_save_file_convenience_method(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        content = b"Convenience save file bytes"
        target_path = manager.save_file(content, "conv.pdf", document_id="doc-conv-01")
        assert target_path.exists()
        assert manager.get_file_path("doc-conv-01") == target_path

    def test_get_file_path_edge_cases(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        assert manager.get_file_path("") is None
        assert manager.get_file_path(None) is None
        assert manager.get_file_bytes("missing-doc-id") is None
        assert manager.get_file_stream("missing-doc-id") is None

    def test_delete_file_missing(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        assert manager.delete_file("non-existent-doc") is False

    def test_check_health(self, temp_storage_dir: Path, test_settings: Settings):
        manager = StorageManager(upload_dir=temp_storage_dir, settings_obj=test_settings)
        assert manager.check_health() is True

        with patch("pathlib.Path.write_text", side_effect=OSError("Read-only")):
            assert manager.check_health() is False

    def test_get_storage_service_factory(self):
        svc = get_storage_service()
        assert isinstance(svc, StorageManager)
        assert isinstance(svc, StorageService)
