"""
src/services/extraction/azure_client.py

Azure Document Intelligence client integrating the prebuilt-invoice model.
Extracts key-value fields, line items, bounding polygons, and confidence scores.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.core.models import ExtractedField, LineItem, RawInvoicePayload

logger = logging.getLogger(__name__)

# SDK detection and dynamic imports
try:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
    from azure.core.credentials import AzureKeyCredential
    from azure.core.exceptions import (
        AzureError,
        ClientAuthenticationError,
        HttpResponseError,
    )
    AZURE_SDK_AVAILABLE = True
    SDK_FLAVOR = "documentintelligence"
except ImportError:
    try:
        from azure.ai.formrecognizer import DocumentAnalysisClient  # type: ignore
        from azure.core.credentials import AzureKeyCredential  # type: ignore
        from azure.core.exceptions import (  # type: ignore
            AzureError,
            ClientAuthenticationError,
            HttpResponseError,
        )
        AZURE_SDK_AVAILABLE = True
        SDK_FLAVOR = "formrecognizer"
    except ImportError:
        AZURE_SDK_AVAILABLE = False
        SDK_FLAVOR = None


class ExtractionError(Exception):
    """Base exception for all extraction failures."""


class AzureConfigurationError(ExtractionError):
    """Raised when Azure credentials or endpoint are missing or invalid."""


class AzureAuthenticationError(ExtractionError):
    """Raised when Azure authentication (API key) is rejected."""


class AzureAnalysisError(ExtractionError):
    """Raised when Azure Document Intelligence processing fails."""


class AzureDocumentIntelligenceClient:
    """Client for extracting invoice data via Azure Document Intelligence prebuilt-invoice model."""

    def __init__(
        self,
        endpoint: str | None = None,
        key: str | None = None,
        model_id: str = "prebuilt-invoice",
        timeout_seconds: int = 45,
    ) -> None:
        self.endpoint = endpoint
        self.key = key
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds
        self._client: Any | None = None

    def is_available(self) -> bool:
        """Check if SDK and credentials are configured."""
        return bool(
            AZURE_SDK_AVAILABLE
            and self.endpoint
            and self.key
            and str(self.endpoint).strip() != ""
            and str(self.key).strip() != ""
            and not str(self.endpoint).startswith("https://your-resource")
        )

    def _get_client(self) -> Any:
        """Lazily initialize and return the Azure SDK client."""
        if not AZURE_SDK_AVAILABLE:
            raise AzureConfigurationError(
                "azure-ai-documentintelligence (or azure-ai-formrecognizer) package is not installed."
            )
        if not self.endpoint or not self.key:
            raise AzureConfigurationError(
                "Azure Document Intelligence endpoint and key must be provided."
            )

        if self._client is None:
            credential = AzureKeyCredential(self.key)
            if SDK_FLAVOR == "documentintelligence":
                self._client = DocumentIntelligenceClient(
                    endpoint=self.endpoint,
                    credential=credential,
                )
            else:
                self._client = DocumentAnalysisClient(  # type: ignore
                    endpoint=self.endpoint,
                    credential=credential,
                )
        return self._client

    def analyze_document(
        self,
        file_bytes: bytes,
        filename: str = "document.pdf",
        content_type: str | None = None,
        document_id: str | None = None,
        correlation_id: str | None = None,
    ) -> RawInvoicePayload:
        """
        Analyze document bytes using the prebuilt-invoice model.

        Args:
            file_bytes: Raw binary content of the invoice (PDF, PNG, JPG).
            filename: Original document filename.
            content_type: MIME type of the document.
            document_id: Optional document UUID.
            correlation_id: Optional correlation tracking UUID.

        Returns:
            RawInvoicePayload containing structured extracted fields and line items.
        """
        doc_id = document_id or str(uuid.uuid4())
        corr_id = correlation_id or str(uuid.uuid4())

        client = self._get_client()

        try:
            logger.info(
                f"Submitting document {filename} ({len(file_bytes)} bytes) to Azure Doc Intelligence ({self.model_id})..."
            )

            if SDK_FLAVOR == "documentintelligence":
                poller = client.begin_analyze_document(
                    model_id=self.model_id,
                    analyze_request=AnalyzeDocumentRequest(bytes_source=file_bytes),
                    content_type=content_type or "application/octet-stream",
                )
            else:
                poller = client.begin_analyze_document(
                    model_id=self.model_id,
                    document=file_bytes,
                )

            result = poller.result()
            return self._parse_azure_result(result, doc_id, corr_id, filename)

        except ClientAuthenticationError as e:
            logger.error(f"Azure authentication failure: {e}")
            raise AzureAuthenticationError(f"Azure authentication rejected: {e}") from e
        except HttpResponseError as e:
            logger.error(f"Azure HTTP response error: {e.status_code} - {getattr(e, 'message', str(e))}")
            raise AzureAnalysisError(f"Azure analysis failed ({e.status_code}): {getattr(e, 'message', str(e))}") from e
        except AzureError as e:
            logger.error(f"Azure SDK error: {e}")
            raise AzureAnalysisError(f"Azure SDK error: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during Azure document analysis: {e}")
            raise AzureAnalysisError(f"Unexpected error: {e}") from e

    def _parse_azure_result(
        self,
        result: Any,
        document_id: str,
        correlation_id: str,
        filename: str,
    ) -> RawInvoicePayload:
        """Parse raw SDK result into RawInvoicePayload."""
        raw_fields: dict[str, ExtractedField[Any]] = {}
        raw_items: list[LineItem] = []
        confidence_scores: dict[str, float] = {}

        if not hasattr(result, "documents") or not result.documents:
            logger.warning("Azure result contained no extracted documents.")
            return RawInvoicePayload(
                document_id=document_id,
                correlation_id=correlation_id,
                filename=filename,
                raw_fields=raw_fields,
                raw_items=raw_items,
                confidence_scores=confidence_scores,
                extraction_engine="azure_prebuilt_invoice",
                raw_text=getattr(result, "content", ""),
            )

        doc = result.documents[0]
        fields = getattr(doc, "fields", {}) or {}

        # Standard field mapping list
        field_keys = [
            ("VendorName", "vendor_name", str),
            ("InvoiceId", "invoice_id", str),
            ("InvoiceDate", "invoice_date", str),
            ("DueDate", "due_date", str),
            ("InvoiceTotal", "total_amount", float),
            ("SubTotal", "subtotal_amount", float),
            ("TotalTax", "tax_amount", float),
            ("AmountDue", "amount_due", float),
            ("CustomerName", "customer_name", str),
            ("PurchaseOrder", "purchase_order", str),
            ("VendorAddress", "vendor_address", str),
            ("Currency", "currency", str),
        ]

        for azure_key, target_key, val_type in field_keys:
            if azure_key in fields and fields[azure_key] is not None:
                df = fields[azure_key]
                val = self._extract_value(df, val_type)
                conf = float(getattr(df, "confidence", 0.0) or 0.0)
                bbox = self._extract_bounding_box(df)
                page = self._extract_page_number(df)

                if val is not None:
                    raw_fields[azure_key] = ExtractedField(
                        value=val,
                        confidence=conf,
                        bounding_box=bbox,
                        page_number=page,
                    )
                    confidence_scores[target_key] = conf

        # Extract currency symbol if present on total
        if "InvoiceTotal" in fields and fields["InvoiceTotal"] is not None:
            df_tot = fields["InvoiceTotal"]
            curr_obj = getattr(df_tot, "value_currency", None)
            if curr_obj and hasattr(curr_obj, "currency_symbol") and curr_obj.currency_symbol:
                if "Currency" not in raw_fields:
                    raw_fields["Currency"] = ExtractedField(
                        value=curr_obj.currency_symbol,
                        confidence=getattr(df_tot, "confidence", 0.95),
                    )

        # Line items extraction
        if "Items" in fields and fields["Items"] is not None:
            items_field = fields["Items"]
            items_val = getattr(items_field, "value_array", None) or getattr(items_field, "value", [])
            for item in items_val:
                item_fields = getattr(item, "value_object", None) or getattr(item, "value", {})
                if isinstance(item_fields, dict):
                    desc = self._get_item_subfield_val(item_fields, "Description", str)
                    qty = self._get_item_subfield_val(item_fields, "Quantity", float)
                    unit_p = self._get_item_subfield_val(item_fields, "UnitPrice", float)
                    tot_amt = self._get_item_subfield_val(item_fields, "Amount", float)
                    tax_amt = self._get_item_subfield_val(item_fields, "Tax", float)
                    conf = float(getattr(item, "confidence", 1.0) or 1.0)
                    bbox = self._extract_bounding_box(item)
                    page = self._extract_page_number(item)

                    raw_items.append(LineItem(
                        description=desc,
                        quantity=qty,
                        unit_price=unit_p,
                        total_amount=tot_amt,
                        tax_amount=tax_amt,
                        confidence=conf,
                        page_number=page,
                        bounding_box=bbox,
                    ))

        return RawInvoicePayload(
            document_id=document_id,
            correlation_id=correlation_id,
            filename=filename,
            raw_fields=raw_fields,
            raw_items=raw_items,
            confidence_scores=confidence_scores,
            extraction_engine="azure_prebuilt_invoice",
            raw_text=getattr(result, "content", ""),
        )

    def _extract_value(self, field: Any, target_type: type) -> Any:
        """Extract typed value from DocumentField object."""
        if field is None:
            return None

        if target_type is str:
            # String / text fields
            str_obj = getattr(field, "value_string", None)
            if isinstance(str_obj, str):
                return str_obj
            date_obj = getattr(field, "value_date", None)
            if date_obj is not None and not hasattr(date_obj, "_mock_return_value"):
                return str(date_obj)
            content = getattr(field, "content", None)
            if isinstance(content, str):
                return content.strip()
            if hasattr(field, "value_string") and field.value_string is not None and not hasattr(field.value_string, "_mock_return_value"):
                return str(field.value_string)
            return None

        if target_type is float:
            # Currency types
            curr_obj = getattr(field, "value_currency", None)
            if curr_obj is not None:
                amt = getattr(curr_obj, "amount", None)
                if isinstance(amt, (int, float)):
                    return float(amt)
            # Number types
            num_obj = getattr(field, "value_number", None)
            if isinstance(num_obj, (int, float)):
                return float(num_obj)
            # Fallback to content parsing
            content = getattr(field, "content", None)
            if isinstance(content, str):
                try:
                    cleaned = content.replace("$", "").replace("€", "").replace("£", "").replace("¥", "").replace(",", "").strip()
                    return float(cleaned)
                except ValueError:
                    return None
            return None

        return getattr(field, "value", None)

    def _get_item_subfield_val(self, item_dict: dict[str, Any], key: str, target_type: type) -> Any:
        """Helper to extract line item subfield."""
        if key in item_dict and item_dict[key] is not None:
            return self._extract_value(item_dict[key], target_type)
        return None

    def _extract_bounding_box(self, field: Any) -> list[float] | None:
        """Extract normalized polygon coordinates."""
        regions = getattr(field, "bounding_regions", None)
        if regions and len(regions) > 0:
            polygon = getattr(regions[0], "polygon", None)
            if polygon:
                return [float(coord) for coord in polygon]
        return None

    def _extract_page_number(self, field: Any) -> int:
        """Extract page number from bounding region."""
        regions = getattr(field, "bounding_regions", None)
        if regions and len(regions) > 0:
            return int(getattr(regions[0], "page_number", 1) or 1)
        return 1
