"""
Document Storage Utility.

Manages physical file persistence to data/uploads/, safe filename generation,
SHA-256 hash calculation, MIME type resolution, file validation, and chunked streaming.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from src.config import Settings, get_settings


def generate_document_id() -> str:
    """Generate a clean UUIDv4 document identifier string."""
    return str(uuid.uuid4())


def compute_sha256(data: bytes) -> str:
    """Calculate SHA-256 hex digest for a given bytes payload."""
    hasher = hashlib.sha256()
    hasher.update(data)
    return hasher.hexdigest()


def sanitize_filename(filename: str) -> str:
    """
    Sanitize uploaded filename to prevent directory traversal and invalid characters.
    Preserves original extension in lowercase.
    """
    if not filename:
        return "unnamed_document.bin"

    # Strip path separators
    basename = os.path.basename(filename.replace("\\", "/"))
    # Replace dangerous or weird characters with underscores
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', basename)
    # Collapse consecutive dots to single dot to prevent .. traversal
    sanitized = re.sub(r'\.{2,}', '.', sanitized)
    # Collapse consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    return sanitized if sanitized else "document.bin"


def get_file_extension(filename: str) -> str:
    """Extract lowercase file extension with leading dot."""
    ext = Path(filename).suffix.lower()
    return ext if ext else ".bin"


class StorageManager:
    """
    Thread-safe storage manager handling document persistence and retrieval.
    """

    def __init__(self, upload_dir: Path | None = None, settings_obj: Settings | None = None):
        self.settings = settings_obj or get_settings()
        self.upload_dir = upload_dir or self.settings.UPLOAD_DIR
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def validate_file(
        self,
        filename: str,
        content_type: str | None = None,
        file_size: int | None = None,
    ) -> tuple[bool, str | None]:
        """
        Validate file extension, MIME type, and size against configured limits.

        Returns:
            Tuple of (is_valid: bool, error_message: Optional[str])
        """
        ext = get_file_extension(filename)
        if ext not in self.settings.ALLOWED_EXTENSIONS:
            return (
                False,
                f"Unsupported file extension '{ext}'. Allowed extensions: {', '.join(sorted(self.settings.ALLOWED_EXTENSIONS))}",
            )

        if file_size is not None and file_size > self.settings.MAX_UPLOAD_SIZE_BYTES:
            max_mb = self.settings.MAX_UPLOAD_SIZE_BYTES / (1024 * 1024)
            return False, f"File size exceeds maximum permitted limit of {max_mb:.1f} MB."

        if content_type and content_type.lower() not in self.settings.ALLOWED_MIME_TYPES:
            if content_type.lower() in ["application/octet-stream", "binary/octet-stream"]:
                # Fall back to extension-based mime check if client provided generic octet-stream
                guessed_mime, _ = mimetypes.guess_type(filename)
                if not (guessed_mime and guessed_mime in self.settings.ALLOWED_MIME_TYPES):
                    return False, f"Unsupported MIME content type '{content_type}'."
            else:
                return False, f"Unsupported MIME content type '{content_type}'."

        return True, None

    def save_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        document_id: str | None = None,
    ) -> tuple[str, Path, str, int]:
        """
        Persist raw bytes to disk.

        Args:
            file_bytes: Raw bytes of the document.
            filename: Original filename.
            document_id: Optional existing document ID, generates new UUIDv4 if None.

        Returns:
            Tuple of (document_id, file_path, sha256_hash, file_size)
        """
        if not file_bytes:
            raise ValueError("Cannot save empty file (0 bytes).")

        doc_id = document_id or generate_document_id()
        get_file_extension(filename)
        safe_name = sanitize_filename(filename)
        target_filename = f"{doc_id}_{safe_name}"
        target_path = self.upload_dir / target_filename

        sha256_hash = compute_sha256(file_bytes)
        file_size = len(file_bytes)

        # Atomic write via temporary file
        temp_path = self.upload_dir / f"{doc_id}.tmp"
        with open(temp_path, "wb") as f:
            f.write(file_bytes)

        if target_path.exists():
            target_path.unlink()
        temp_path.rename(target_path)

        return doc_id, target_path, sha256_hash, file_size

    def save_file(
        self,
        file_bytes: bytes,
        filename: str,
        document_id: str | None = None,
    ) -> Path:
        """
        Convenience method persisting bytes and returning target file path.
        """
        _, target_path, _, _ = self.save_bytes(file_bytes, filename, document_id)
        return target_path

    async def save_upload_file(
        self,
        upload_file: UploadFile,
        document_id: str | None = None,
    ) -> tuple[str, Path, str, int]:
        """
        Save an incoming FastAPI UploadFile asynchronously with chunked hashing.

        Args:
            upload_file: FastAPI multipart UploadFile.
            document_id: Optional existing document ID.

        Returns:
            Tuple of (document_id, file_path, sha256_hash, file_size)
        """
        doc_id = document_id or generate_document_id()
        orig_name = upload_file.filename or "document.bin"
        safe_name = sanitize_filename(orig_name)
        target_filename = f"{doc_id}_{safe_name}"
        target_path = self.upload_dir / target_filename
        temp_path = self.upload_dir / f"{doc_id}.tmp"

        hasher = hashlib.sha256()
        total_bytes = 0
        chunk_size = 64 * 1024  # 64 KB chunks

        # Reset upload file pointer to beginning
        await upload_file.seek(0)

        oversized = False
        with open(temp_path, "wb") as f:
            while chunk := await upload_file.read(chunk_size):
                total_bytes += len(chunk)
                if total_bytes > self.settings.MAX_UPLOAD_SIZE_BYTES:
                    oversized = True
                    break
                hasher.update(chunk)
                f.write(chunk)

        if oversized:
            temp_path.unlink(missing_ok=True)
            raise ValueError(
                f"File size exceeded maximum limit of {self.settings.MAX_UPLOAD_SIZE_BYTES} bytes."
            )

        if total_bytes == 0:
            temp_path.unlink(missing_ok=True)
            raise ValueError("Uploaded file is empty (0 bytes).")

        if target_path.exists():
            target_path.unlink()
        temp_path.rename(target_path)

        sha256_hash = hasher.hexdigest()
        return doc_id, target_path, sha256_hash, total_bytes

    def get_file_path(self, document_id: str) -> Path | None:
        """
        Locate the stored document path for a given document_id.
        Searches for exact match or prefix '{document_id}*'
        """
        if not document_id:
            return None

        # Check direct exact name
        direct_path = self.upload_dir / document_id
        if direct_path.exists() and direct_path.is_file():
            return direct_path

        # Check matching files starting with document_id
        for match in self.upload_dir.glob(f"{document_id}*"):
            if match.is_file() and not match.name.endswith(".tmp"):
                return match

        return None

    def get_file_bytes(self, document_id: str) -> bytes | None:
        """Read and return full byte contents of stored document."""
        file_path = self.get_file_path(document_id)
        if file_path and file_path.exists():
            return file_path.read_bytes()
        return None

    def get_file_stream(self, document_id: str, chunk_size: int = 65536) -> Generator[bytes, None, None] | None:
        """
        Return a generator yielding chunks of the file for memory-efficient streaming responses.
        """
        file_path = self.get_file_path(document_id)
        if not file_path or not file_path.exists():
            return None

        def stream_generator() -> Generator[bytes, None, None]:
            with open(file_path, "rb") as f:
                while chunk := f.read(chunk_size):
                    yield chunk

        return stream_generator()

    def get_content_type(self, file_path_or_id: str | Path) -> str:
        """Resolve standard MIME content-type for a file path or document ID."""
        if isinstance(file_path_or_id, str):
            path = self.get_file_path(file_path_or_id)
            if not path:
                path = Path(file_path_or_id)
        else:
            path = file_path_or_id

        mime_type, _ = mimetypes.guess_type(str(path))
        if mime_type:
            return mime_type

        ext = path.suffix.lower()
        mapping = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
            ".bmp": "image/bmp",
        }
        return mapping.get(ext, "application/octet-stream")

    def file_exists(self, document_id: str) -> bool:
        """Check whether a document exists in storage."""
        return self.get_file_path(document_id) is not None

    def delete_file(self, document_id: str) -> bool:
        """Delete stored document from uploads directory."""
        file_path = self.get_file_path(document_id)
        if file_path and file_path.exists():
            file_path.unlink()
            return True
        return False

    def list_files(self) -> list[dict[str, Any]]:
        """List all stored documents with basic metadata."""
        results = []
        for path in self.upload_dir.iterdir():
            if path.is_file() and not path.name.endswith(".tmp"):
                stat = path.stat()
                doc_id = path.stem.split("_")[0] if "_" in path.stem else path.stem
                results.append({
                    "document_id": doc_id,
                    "filename": path.name,
                    "file_path": str(path),
                    "size_bytes": stat.st_size,
                    "content_type": self.get_content_type(path),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                })
        return results

    def check_health(self) -> bool:
        """Verify storage directory writeability."""
        try:
            test_file = self.upload_dir / f".health_check_probe_{uuid.uuid4().hex[:8]}"
            test_file.write_text("probe")
            test_file.unlink(missing_ok=True)
            return True
        except Exception:
            return False


# Aliases for compatibility
StorageService = StorageManager


def get_storage_service(settings_obj: Settings | None = None) -> StorageManager:
    """Factory for dependency injection."""
    return StorageManager(settings_obj=settings_obj or get_settings())


# Default module-level storage manager singleton
storage_manager = StorageManager()
