"""
src/api/routes.py

FastAPI API Route Definitions for Document Intelligence Pipeline.
Includes document upload, extraction & normalization pipeline, dual-storage queries,
audit trail retrieval, document preview streaming, and health checks.
"""

from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from src.api.auth import verify_api_key
from src.config import Settings, get_settings
from src.core.models import HealthResponse, NormalizedInvoice, RawInvoicePayload
from src.core.storage import StorageManager, get_storage_service
from src.services.pipeline import PipelineService, get_pipeline_service
from src.services.storage import BaseStorageRepository, get_storage_repository

logger = logging.getLogger("document_intelligence.routes")
router = APIRouter()


# ============================================================================
# 1. Ingestion & Normalization Endpoints
# ============================================================================

@router.post(
    "/upload",
    response_model=NormalizedInvoice,
    status_code=status.HTTP_200_OK,
    summary="Upload, extract, normalize, and persist invoice document",
    description=(
        "Ingests a PDF, PNG, JPG, or TIFF invoice document, persists the source file "
        "to physical storage, executes OCR extraction (Azure Document Intelligence or mock fallback), "
        "persists the raw extraction to dual-storage, executes canonical normalization, "
        "and persists the normalized record to dual-storage."
    ),
)
async def upload_document(
    file: UploadFile = File(..., description="Invoice document file (PDF, PNG, JPG, TIFF)"),
    force_mock: bool = Query(default=False, description="Force offline mock extractor execution"),
    correlation_id: str | None = Query(default=None, description="Optional caller correlation ID"),
    settings: Settings = Depends(get_settings),
    pipeline_service: PipelineService = Depends(get_pipeline_service),
    _auth: str | None = Depends(verify_api_key),
) -> NormalizedInvoice:
    """
    Handle document upload, storage, extraction, normalization, and dual-persistence.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a valid filename.",
        )

    # Validate file extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file extension '{file_ext}'. "
                f"Allowed extensions: {', '.join(sorted(settings.ALLOWED_EXTENSIONS))}"
            ),
        )

    # Read file content into memory
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )

    # Check maximum file size limit
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum allowed limit of {settings.MAX_UPLOAD_SIZE_MB}MB.",
        )

    corr_id = correlation_id or str(uuid.uuid4())

    try:
        normalized_invoice = await pipeline_service.process_document(
            file_bytes=content,
            filename=file.filename,
            content_type=file.content_type,
            force_mock=force_mock,
            correlation_id=corr_id,
        )
        return normalized_invoice

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to process document %s: %s", file.filename, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process document: {exc!s}",
        )


# ============================================================================
# 2. Normalized Invoices Query Endpoints
# ============================================================================

@router.get(
    "/invoices",
    response_model=list[NormalizedInvoice],
    status_code=status.HTTP_200_OK,
    summary="List normalized invoices with optional filtering and pagination",
)
async def list_invoices(
    vendor: str | None = Query(default=None, description="Filter by vendor name substring"),
    category: str | None = Query(default=None, description="Filter by spend category"),
    is_duplicate: bool | None = Query(default=None, description="Filter by duplicate flag"),
    has_anomalies: bool | None = Query(default=None, description="Filter by anomaly flag"),
    start_date: str | None = Query(default=None, description="Filter invoices on or after YYYY-MM-DD"),
    end_date: str | None = Query(default=None, description="Filter invoices on or before YYYY-MM-DD"),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of items to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    storage_repo: BaseStorageRepository = Depends(get_storage_repository),
    _auth: str | None = Depends(verify_api_key),
) -> list[NormalizedInvoice]:
    """Retrieve normalized invoices from dual-storage repository."""
    return storage_repo.list_normalized(
        limit=limit,
        offset=offset,
        vendor=vendor,
        category=category,
        is_duplicate=is_duplicate,
        has_anomalies=has_anomalies,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/invoices/{id}",
    response_model=NormalizedInvoice,
    status_code=status.HTTP_200_OK,
    summary="Retrieve normalized invoice by entity UUID or document ID",
)
async def get_invoice(
    id: str,
    storage_repo: BaseStorageRepository = Depends(get_storage_repository),
    _auth: str | None = Depends(verify_api_key),
) -> NormalizedInvoice:
    """Retrieve a single normalized invoice by entity ID or document ID."""
    invoice = storage_repo.get_normalized(id)
    if not invoice:
        invoice = storage_repo.get_normalized_by_document_id(id)

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Normalized invoice with ID '{id}' was not found.",
        )
    return invoice


@router.get(
    "/invoices/correlation/{correlation_id}",
    status_code=status.HTTP_200_OK,
    summary="Retrieve all raw extractions and normalized invoices for a correlation ID",
)
async def get_by_correlation(
    correlation_id: str,
    storage_repo: BaseStorageRepository = Depends(get_storage_repository),
    _auth: str | None = Depends(verify_api_key),
) -> dict[str, Any]:
    """Retrieve all linked raw and normalized records by correlation ID."""
    raws, norms = storage_repo.get_by_correlation_id(correlation_id)
    return {
        "correlation_id": correlation_id,
        "raw_count": len(raws),
        "normalized_count": len(norms),
        "raw_extractions": [r.model_dump(mode="json") for r in raws],
        "normalized_invoices": [n.model_dump(mode="json") for n in norms],
    }


# ============================================================================
# 3. Raw Extraction Audit Endpoints
# ============================================================================

@router.get(
    "/raw/{document_id}",
    response_model=RawInvoicePayload,
    status_code=status.HTTP_200_OK,
    summary="Retrieve immutable raw extraction payload by document ID",
)
async def get_raw_extraction(
    document_id: str,
    storage_repo: BaseStorageRepository = Depends(get_storage_repository),
    _auth: str | None = Depends(verify_api_key),
) -> RawInvoicePayload:
    """Retrieve raw unnormalized extraction payload for auditing."""
    payload = storage_repo.get_raw(document_id)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Raw extraction payload for document ID '{document_id}' was not found.",
        )
    return payload


@router.get(
    "/documents/{document_id}/audit",
    status_code=status.HTTP_200_OK,
    summary="Retrieve full audit trail for document ID",
)
async def get_document_audit_trail(
    document_id: str,
    storage_repo: BaseStorageRepository = Depends(get_storage_repository),
    _auth: str | None = Depends(verify_api_key),
) -> dict[str, Any]:
    """Retrieve unified audit trail linking raw extraction and normalized record."""
    try:
        return storage_repo.get_audit_trail(document_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit trail not found for document ID '{document_id}': {exc!s}",
        )


# ============================================================================
# 4. Document File Streaming & Preview
# ============================================================================

@router.get(
    "/documents/{document_id}/file",
    response_class=FileResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve raw document file",
    description="Streams the raw uploaded document (PDF or image) for UI preview or inspection.",
)
async def get_document_file(
    document_id: str,
    storage_service: StorageManager = Depends(get_storage_service),
    _auth: str | None = Depends(verify_api_key),
) -> FileResponse:
    """Stream the raw file from storage by document_id."""
    file_path = storage_service.get_file_path(document_id)
    if not file_path or not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' was not found in storage.",
        )

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type is None:
        mime_type = storage_service.get_content_type(file_path)

    return FileResponse(
        path=file_path,
        media_type=mime_type,
        filename=file_path.name,
        headers={"Content-Disposition": f'inline; filename="{file_path.name}"'},
    )


# ============================================================================
# 5. Health Check Endpoint
# ============================================================================

@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health and status check",
    description="Returns service health status, mock fallback mode, and upload storage writeability.",
)
async def health_check(
    settings: Settings = Depends(get_settings),
    storage_service: StorageManager = Depends(get_storage_service),
    storage_repo: BaseStorageRepository = Depends(get_storage_repository),
) -> HealthResponse:
    """Perform health and environment readiness checks."""
    storage_ok = storage_service.check_health()
    repo_ok = storage_repo.check_health()
    azure_configured = settings.is_azure_configured

    return HealthResponse(
        status="healthy" if (storage_ok and repo_ok) else "degraded",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        mock_mode=settings.is_mock_azure,
        azure_configured=azure_configured,
        cosmos_configured=settings.is_cosmos_configured,
        storage_healthy=(storage_ok and repo_ok),
        upload_dir_status="ok" if storage_ok else "error",
        upload_dir_path=str(settings.UPLOAD_DIR.resolve()),
    )
