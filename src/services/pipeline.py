"""
src/services/pipeline.py

End-to-End Document Intelligence Pipeline Orchestrator.
Coordinates:
1. Physical document upload & hash validation (StorageManager)
2. Raw key-value extraction (ExtractionService)
3. Dual-storage persistence of raw payload (BaseStorageRepository.save_raw)
4. Canonical normalization, vendor matching & spend classification (NormalizationService)
5. Dual-storage persistence of normalized domain model (BaseStorageRepository.save_normalized)
"""

from __future__ import annotations

import logging
import uuid

from src.config import Settings, get_settings
from src.core.models import NormalizedInvoice
from src.core.storage import StorageManager, get_storage_service
from src.services.detection import DetectionService, get_detection_service
from src.services.extraction.service import ExtractionService, get_extraction_service
from src.services.normalization import NormalizationService, get_normalization_service
from src.services.storage import BaseStorageRepository, get_storage_repository

logger = logging.getLogger(__name__)


class PipelineService:
    """
    Unified Document Intelligence Pipeline executing physical persistence,
    raw OCR extraction, audit persistence, canonical normalization, duplicate/anomaly detection,
    and dual-container storage.
    """

    def __init__(
        self,
        storage_manager: StorageManager | None = None,
        extraction_service: ExtractionService | None = None,
        normalization_service: NormalizationService | None = None,
        storage_repository: BaseStorageRepository | None = None,
        detection_service: DetectionService | None = None,
        settings_obj: Settings | None = None,
    ) -> None:
        self.settings = settings_obj or get_settings()
        self.storage_manager = storage_manager or get_storage_service(self.settings)
        self.extraction_service = extraction_service or get_extraction_service(self.settings)
        self.normalization_service = normalization_service or get_normalization_service(self.settings)
        self.storage_repository = storage_repository or get_storage_repository(self.settings)
        self.detection_service = detection_service or get_detection_service()

    async def process_document(
        self,
        file_bytes: bytes,
        filename: str = "document.pdf",
        content_type: str | None = None,
        force_mock: bool = False,
        correlation_id: str | None = None,
    ) -> NormalizedInvoice:
        """
        Execute full end-to-end processing pipeline on an uploaded invoice document.
        """
        doc_id = str(uuid.uuid4())
        corr_id = correlation_id or str(uuid.uuid4())

        # 1. Physical document persistence
        _, storage_path, file_hash, file_size = self.storage_manager.save_bytes(
            file_bytes=file_bytes,
            filename=filename,
            document_id=doc_id,
        )

        # 2. Extract raw OCR payload
        raw_payload = self.extraction_service.extract_raw(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            force_mock=force_mock,
            document_id=doc_id,
            correlation_id=corr_id,
            storage_path=str(storage_path),
        )
        raw_payload.file_hash = file_hash
        raw_payload.file_size = file_size

        # 3. Persist raw extraction for regulatory & audit immutability
        self.storage_repository.save_raw(raw_payload)
        logger.info("Persisted raw extraction for document %s (corr: %s)", doc_id, corr_id)

        # 4. Canonical normalization
        normalized_invoice = self.normalization_service.normalize_invoice(raw_payload)
        normalized_invoice.file_hash = file_hash
        normalized_invoice.file_size = file_size
        normalized_invoice.storage_path = str(storage_path)

        # 4.5 Duplicate & Anomaly Detection
        existing_records = self.storage_repository.list_normalized(limit=1000)
        normalized_invoice = self.detection_service.run_detection(normalized_invoice, existing_records)

        # 5. Persist normalized record in dual storage
        self.storage_repository.save_normalized(normalized_invoice)
        logger.info("Persisted normalized invoice %s for document %s", normalized_invoice.id, doc_id)

        return normalized_invoice

    def process_document_sync(
        self,
        file_bytes: bytes,
        filename: str = "document.pdf",
        content_type: str | None = None,
        force_mock: bool = False,
        correlation_id: str | None = None,
    ) -> NormalizedInvoice:
        """Synchronous version of document processing."""
        doc_id = str(uuid.uuid4())
        corr_id = correlation_id or str(uuid.uuid4())

        # 1. Physical document persistence
        _, storage_path, file_hash, file_size = self.storage_manager.save_bytes(
            file_bytes=file_bytes,
            filename=filename,
            document_id=doc_id,
        )

        # 2. Extract raw OCR payload
        raw_payload = self.extraction_service.extract_raw(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            force_mock=force_mock,
            document_id=doc_id,
            correlation_id=corr_id,
            storage_path=str(storage_path),
        )
        raw_payload.file_hash = file_hash
        raw_payload.file_size = file_size

        # 3. Persist raw extraction
        self.storage_repository.save_raw(raw_payload)

        # 4. Canonical normalization
        normalized_invoice = self.normalization_service.normalize_invoice(raw_payload)
        normalized_invoice.file_hash = file_hash
        normalized_invoice.file_size = file_size
        normalized_invoice.storage_path = str(storage_path)

        # 4.5 Duplicate & Anomaly Detection
        existing_records = self.storage_repository.list_normalized(limit=1000)
        normalized_invoice = self.detection_service.run_detection(normalized_invoice, existing_records)

        # 5. Persist normalized record
        self.storage_repository.save_normalized(normalized_invoice)

        return normalized_invoice


# Alias for backward compatibility
DocumentPipeline = PipelineService


def get_pipeline_service() -> PipelineService:
    """Factory creating PipelineService with injected dependencies."""
    settings = get_settings()
    return PipelineService(
        storage_manager=get_storage_service(settings),
        extraction_service=get_extraction_service(settings),
        normalization_service=get_normalization_service(settings),
        storage_repository=get_storage_repository(settings),
        detection_service=get_detection_service(),
        settings_obj=settings,
    )
