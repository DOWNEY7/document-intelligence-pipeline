"""
src/services/extraction/service.py

Unified Extraction Service orchestrator.
Seamlessly routes extraction requests to Azure Document Intelligence or MockExtractor.
Converts raw extraction payloads into NormalizedInvoice domain models.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from src.config import Settings, get_settings
from src.core.models import (
    AnomalyFlag,
    ConfidenceBreakdown,
    ExtractedField,
    NormalizedInvoice,
    RawInvoicePayload,
)
from src.services.extraction.azure_client import (
    AzureDocumentIntelligenceClient,
    ExtractionError,
)
from src.services.extraction.mock_extractor import MockExtractionService

UTC = timezone.utc
logger = logging.getLogger(__name__)


class ExtractionService:
    """Unified document extraction orchestrator."""

    def __init__(
        self,
        azure_client: AzureDocumentIntelligenceClient | None = None,
        mock_extractor: MockExtractionService | None = None,
        settings_obj: Settings | None = None,
    ) -> None:
        self.settings = settings_obj or get_settings()
        self.azure_client = azure_client or AzureDocumentIntelligenceClient(
            endpoint=self.settings.AZURE_FORM_RECOGNIZER_ENDPOINT,
            key=self.settings.AZURE_FORM_RECOGNIZER_KEY,
        )
        self.mock_extractor = mock_extractor or MockExtractionService()

    def should_use_mock(self, force_mock: bool = False) -> bool:
        """Evaluate if extraction should run via mock fallback."""
        if force_mock:
            return True
        if self.settings.USE_MOCK_AZURE:
            return True
        if not self.azure_client.is_available():
            return True
        return False

    def extract_raw(
        self,
        file_bytes: bytes,
        filename: str = "document.pdf",
        content_type: str | None = None,
        force_mock: bool = False,
        document_id: str | None = None,
        correlation_id: str | None = None,
        storage_path: str | None = None,
    ) -> RawInvoicePayload:
        """
        Extract raw invoice data from file bytes.

        Args:
            file_bytes: Binary document content.
            filename: Document file name.
            content_type: MIME type.
            force_mock: If True, bypasses Azure and uses MockExtractor.
            document_id: Optional unique document identifier.
            correlation_id: Optional tracking correlation ID.
            storage_path: Optional path to stored source file.

        Returns:
            RawInvoicePayload containing structured extracted fields and line items.
        """
        doc_id = document_id or str(uuid.uuid4())
        corr_id = correlation_id or str(uuid.uuid4())

        if self.should_use_mock(force_mock=force_mock):
            logger.info(f"ExtractionService: Using MockExtractor for {filename}")
            payload = self.mock_extractor.extract_document(
                file_bytes=file_bytes,
                filename=filename,
                document_id=doc_id,
                correlation_id=corr_id,
            )
            if storage_path:
                payload.storage_path = storage_path
            return payload

        try:
            logger.info(f"ExtractionService: Using Azure Document Intelligence for {filename}")
            payload = self.azure_client.analyze_document(
                file_bytes=file_bytes,
                filename=filename,
                content_type=content_type,
                document_id=doc_id,
                correlation_id=corr_id,
            )
            if storage_path:
                payload.storage_path = storage_path
            return payload
        except ExtractionError as e:
            logger.warning(
                f"Azure extraction failed ({e}). Automatically falling back to MockExtractor."
            )
            fallback_payload = self.mock_extractor.extract_document(
                file_bytes=file_bytes,
                filename=filename,
                document_id=doc_id,
                correlation_id=corr_id,
            )
            fallback_payload.extraction_engine = "mock_fallback_on_azure_error"
            if storage_path:
                fallback_payload.storage_path = storage_path
            return fallback_payload

    async def extract_invoice(
        self,
        file_bytes: bytes,
        filename: str = "document.pdf",
        content_type: str | None = None,
        force_mock: bool = False,
        document_id: str | None = None,
        correlation_id: str | None = None,
        storage_path: str | None = None,
    ) -> NormalizedInvoice:
        """
        Async extraction method transforming input into NormalizedInvoice model.
        """
        raw_payload = self.extract_raw(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            force_mock=force_mock,
            document_id=document_id,
            correlation_id=correlation_id,
            storage_path=storage_path,
        )
        return self._raw_to_normalized(raw_payload)

    def extract_invoice_sync(
        self,
        file_bytes: bytes,
        filename: str = "document.pdf",
        content_type: str | None = None,
        force_mock: bool = False,
        document_id: str | None = None,
        correlation_id: str | None = None,
        storage_path: str | None = None,
    ) -> NormalizedInvoice:
        """
        Synchronous extraction method.
        """
        raw_payload = self.extract_raw(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            force_mock=force_mock,
            document_id=document_id,
            correlation_id=correlation_id,
            storage_path=storage_path,
        )
        return self._raw_to_normalized(raw_payload)

    def _raw_to_normalized(self, raw: RawInvoicePayload) -> NormalizedInvoice:
        """Transform RawInvoicePayload into NormalizedInvoice for Milestone 1."""
        fields = raw.raw_fields

        # Vendor Name
        vendor_field = fields.get("VendorName") or ExtractedField(value="Unknown Vendor", confidence=0.0)

        # Invoice ID
        invoice_id_field = fields.get("InvoiceId") or ExtractedField(value=f"INV-{raw.document_id[:8].upper()}", confidence=0.0)

        # Invoice Date
        invoice_date_field = fields.get("InvoiceDate") or ExtractedField(
            value=datetime.now(UTC).strftime("%Y-%m-%d"), confidence=0.5
        )

        # Due Date
        due_date_field = fields.get("DueDate")

        # Amounts
        total_field = fields.get("InvoiceTotal") or ExtractedField(value=0.0, confidence=0.0)
        subtotal_field = fields.get("SubTotal")
        tax_field = fields.get("TotalTax")
        amount_due_field = fields.get("AmountDue")
        customer_name_field = fields.get("CustomerName")
        purchase_order_field = fields.get("PurchaseOrder")
        currency_field = fields.get("Currency") or ExtractedField(value="USD", confidence=0.8)

        # Line Items
        line_items = raw.raw_items

        # Calculate weighted confidence score
        confidence_values = [
            vendor_field.confidence * 0.25,
            invoice_id_field.confidence * 0.20,
            invoice_date_field.confidence * 0.20,
            total_field.confidence * 0.25,
        ]
        if line_items:
            item_confs = [it.confidence for it in line_items]
            avg_item_conf = sum(item_confs) / len(item_confs)
            confidence_values.append(avg_item_conf * 0.10)

        overall_confidence = round(sum(confidence_values), 4)

        # Initial Status and Anomaly Checks
        anomalies: list[AnomalyFlag] = []
        status = "SUCCESS"

        if overall_confidence < 0.70:
            status = "NEEDS_REVIEW"
            anomalies.append(AnomalyFlag(
                code="LOW_CONFIDENCE",
                message=f"Extraction confidence ({overall_confidence:.2f}) is below threshold (0.70)",
                severity="WARNING",
            ))

        if total_field.value <= 0.0:
            anomalies.append(AnomalyFlag(
                code="ZERO_TOTAL",
                message="Extracted invoice total is zero or negative",
                severity="WARNING",
                field="total_amount",
            ))

        # Check line item math consistency
        if subtotal_field and tax_field:
            expected_total = round(subtotal_field.value + tax_field.value, 2)
            if abs(expected_total - total_field.value) > 0.05:
                anomalies.append(AnomalyFlag(
                    code="MATH_DISCREPANCY",
                    message=f"Subtotal ({subtotal_field.value}) + Tax ({tax_field.value}) != Total ({total_field.value})",
                    severity="WARNING",
                    field="total_amount",
                ))

        breakdown = ConfidenceBreakdown(
            overall=overall_confidence,
            vendor=vendor_field.confidence,
            invoice_id=invoice_id_field.confidence,
            date=invoice_date_field.confidence,
            total=total_field.confidence,
            line_items=sum(it.confidence for it in line_items) / len(line_items) if line_items else 1.0,
            field_scores=raw.confidence_scores,
        )

        # Determine currency ISO
        raw_curr = str(currency_field.value).strip() if currency_field and currency_field.value else "$"
        curr_iso = "USD"
        if raw_curr in ["EUR", "€"]:
            curr_iso = "EUR"
        elif raw_curr in ["GBP", "£"]:
            curr_iso = "GBP"
        elif raw_curr in ["JPY", "¥"]:
            curr_iso = "JPY"
        elif raw_curr in ["USD", "$"]:
            curr_iso = "USD"

        return NormalizedInvoice(
            document_id=raw.document_id,
            correlation_id=raw.correlation_id,
            filename=raw.filename,
            storage_path=raw.storage_path,
            file_hash=raw.file_hash,
            file_size=raw.file_size,
            vendor_name=vendor_field,
            invoice_id=invoice_id_field,
            invoice_date=invoice_date_field,
            due_date=due_date_field,
            total_amount=total_field,
            tax_amount=tax_field,
            subtotal_amount=subtotal_field,
            amount_due=amount_due_field,
            customer_name=customer_name_field,
            purchase_order=purchase_order_field,
            currency=currency_field,
            currency_raw=raw_curr,
            currency_iso=curr_iso,
            line_items=line_items,
            confidence_score=overall_confidence,
            confidence_breakdown=breakdown,
            status=status,
            anomalies=anomalies,
            extraction_engine=raw.extraction_engine,
            created_at=datetime.now(UTC).isoformat(),
        )


def get_extraction_service(settings_obj: Settings | None = None) -> ExtractionService:
    """Factory for dependency injection."""
    return ExtractionService(settings_obj=settings_obj or get_settings())
