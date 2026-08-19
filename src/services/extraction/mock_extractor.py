"""
src/services/extraction/mock_extractor.py

Offline Mock & Heuristic Extraction Engine.
Provides 100% offline document parsing via:
1. Ground-truth fixture registry (hash & filename matching for INV-001 to INV-010)
2. Pure Python multi-format text extraction (PDF stream decompressor, UTF-8, binary)
3. Rule-based regex heuristics for vendor, dates, currency, totals, and line items.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import uuid
import zlib
from datetime import UTC, datetime
from typing import Any

from src.core.models import (
    AnomalyFlag,
    ExtractedField,
    LineItem,
    NormalizedInvoice,
    RawInvoicePayload,
)

logger = logging.getLogger(__name__)

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

CURRENCY_SYMBOL_MAP = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "USD": "USD",
    "EUR": "EUR",
    "GBP": "GBP",
    "JPY": "JPY",
}

FIXTURE_REGISTRY: dict[str, dict[str, Any]] = {
    "inv_001_standard_aws.pdf": {
        "vendor_name": "Amazon Web Services Inc.",
        "invoice_id": "INV-2026-AWS-001",
        "invoice_date": "2026-08-01",
        "due_date": "2026-08-31",
        "subtotal_amount": 1291.36,
        "tax_amount": 129.14,
        "total_amount": 1420.50,
        "currency": "USD",
        "line_items": [
            {"description": "Amazon Elastic Compute Cloud (EC2)", "quantity": 10.0, "unit_price": 85.00, "total_amount": 850.00, "confidence": 0.99},
            {"description": "Amazon Simple Storage Service (S3)", "quantity": 5.0, "unit_price": 45.00, "total_amount": 225.00, "confidence": 0.99},
            {"description": "Amazon Relational Database Service (RDS)", "quantity": 1.0, "unit_price": 216.36, "total_amount": 216.36, "confidence": 0.98},
        ],
        "confidence_score": 0.98,
    },
    "inv_002_typo_vendor_msft.pdf": {
        "vendor_name": "Microsft Corp Ireland",
        "invoice_id": "MS-8839201",
        "invoice_date": "2026-08-03",
        "due_date": "2026-09-02",
        "subtotal_amount": 350.00,
        "tax_amount": 0.00,
        "total_amount": 350.00,
        "currency": "USD",
        "line_items": [
            {"description": "Microsoft 365 Business Standard (10 Users)", "quantity": 10.0, "unit_price": 35.00, "total_amount": 350.00, "confidence": 0.95},
        ],
        "confidence_score": 0.95,
    },
    "inv_003_multicurrency_eur.pdf": {
        "vendor_name": "Google Ireland Limited",
        "invoice_id": "GOOG-EU-2026-08",
        "invoice_date": "2026-08-05",
        "due_date": "2026-09-04",
        "subtotal_amount": 1802.27,
        "tax_amount": 378.48,
        "total_amount": 2180.75,
        "currency": "EUR",
        "line_items": [
            {"description": "Google Workspace Enterprise Plus", "quantity": 50.0, "unit_price": 30.00, "total_amount": 1500.00, "confidence": 0.97},
            {"description": "Google Cloud Platform - Compute Engine", "quantity": 1.0, "unit_price": 302.27, "total_amount": 302.27, "confidence": 0.96},
        ],
        "confidence_score": 0.97,
    },
    "inv_004_thermal_receipt_uber.png": {
        "vendor_name": "UBER *TRIP HELP.UBER",
        "invoice_id": "UBER-TRIP-99231",
        "invoice_date": "2026-08-07",
        "due_date": None,
        "subtotal_amount": 38.00,
        "tax_amount": 4.80,
        "total_amount": 42.80,
        "currency": "USD",
        "line_items": [
            {"description": "UberX Airport Transfer Trip", "quantity": 1.0, "unit_price": 42.80, "total_amount": 42.80, "confidence": 0.92},
        ],
        "confidence_score": 0.92,
    },
    "inv_005_acme_dup_original.pdf": {
        "vendor_name": "Acme Corp Ltd",
        "invoice_id": "ACME-2026-101",
        "invoice_date": "2026-08-10",
        "due_date": "2026-09-09",
        "subtotal_amount": 500.00,
        "tax_amount": 0.00,
        "total_amount": 500.00,
        "currency": "USD",
        "line_items": [
            {"description": "Professional Consulting Services - Stage 1", "quantity": 1.0, "unit_price": 500.00, "total_amount": 500.00, "confidence": 0.98},
        ],
        "confidence_score": 0.98,
    },
    "inv_006_acme_dup_positive.pdf": {
        "vendor_name": "Acme Corporation LLC",
        "invoice_id": "ACME-2026-102",
        "invoice_date": "2026-08-13",
        "due_date": "2026-09-12",
        "subtotal_amount": 500.00,
        "tax_amount": 0.00,
        "total_amount": 500.00,
        "currency": "USD",
        "line_items": [
            {"description": "Professional Consulting Services - Stage 2", "quantity": 1.0, "unit_price": 500.00, "total_amount": 500.00, "confidence": 0.98},
        ],
        "confidence_score": 0.98,
    },
    "inv_007_acme_dup_negative.pdf": {
        "vendor_name": "Acme Corporation",
        "invoice_id": "ACME-2026-103",
        "invoice_date": "2026-09-15",
        "due_date": "2026-10-15",
        "subtotal_amount": 500.00,
        "tax_amount": 0.00,
        "total_amount": 500.00,
        "currency": "USD",
        "line_items": [
            {"description": "Monthly Retainer Services", "quantity": 1.0, "unit_price": 500.00, "total_amount": 500.00, "confidence": 0.98},
        ],
        "confidence_score": 0.98,
    },
    "inv_008_extreme_anomaly.pdf": {
        "vendor_name": "Delta Air Lines Inc",
        "invoice_id": "DAL-773829",
        "invoice_date": "2026-08-12",
        "due_date": "2026-09-11",
        "subtotal_amount": 1200000.00,
        "tax_amount": 50000.00,
        "total_amount": 1250000.00,
        "currency": "USD",
        "line_items": [
            {"description": "Corporate Fleet Charter & Maintenance Package", "quantity": 1.0, "unit_price": 1250000.00, "total_amount": 1250000.00, "confidence": 0.99},
        ],
        "confidence_score": 0.99,
    },
    "inv_009_unrecognized_vendor.jpg": {
        "vendor_name": "Luigi's Pizza & Catering",
        "invoice_id": "LPC-4029",
        "invoice_date": "2026-08-14",
        "due_date": None,
        "subtotal_amount": 78.00,
        "tax_amount": 7.50,
        "total_amount": 85.50,
        "currency": "USD",
        "line_items": [
            {"description": "Large Gourmet Pepperoni Pizza", "quantity": 2.0, "unit_price": 25.00, "total_amount": 50.00, "confidence": 0.94},
            {"description": "Beverage & Catering Assortment", "quantity": 1.0, "unit_price": 28.00, "total_amount": 28.00, "confidence": 0.94},
        ],
        "confidence_score": 0.94,
    },
    "inv_010_jpy_zero_decimal.pdf": {
        "vendor_name": "Slack Technologies LLC",
        "invoice_id": "SLACK-JP-5541",
        "invoice_date": "2026-08-15",
        "due_date": "2026-09-14",
        "subtotal_amount": 136364.00,
        "tax_amount": 13636.00,
        "total_amount": 150000.00,
        "currency": "JPY",
        "line_items": [
            {"description": "Slack Enterprise Grid Annual Subscription", "quantity": 1.0, "unit_price": 150000.00, "total_amount": 150000.00, "confidence": 0.98},
        ],
        "confidence_score": 0.98,
    },
}


class MockExtractionService:
    """Offline mock and heuristic extraction engine for invoice processing."""

    def __init__(self, custom_fixtures: dict[str, dict[str, Any]] | None = None) -> None:
        self.fixtures: dict[str, dict[str, Any]] = dict(FIXTURE_REGISTRY)
        if custom_fixtures:
            self.fixtures.update(custom_fixtures)
        self._hash_registry: dict[str, dict[str, Any]] = {}

    def register_fixture_by_hash(self, file_hash: str, fixture_data: dict[str, Any]) -> None:
        """Register a fixture payload by SHA-256 hash."""
        self._hash_registry[file_hash.lower()] = fixture_data

    def register_fixture_by_filename(self, filename: str, fixture_data: dict[str, Any]) -> None:
        """Register a fixture payload by filename."""
        self.fixtures[filename.lower()] = fixture_data

    def extract_document(
        self,
        file_bytes: bytes,
        filename: str = "invoice.pdf",
        document_id: str | None = None,
        correlation_id: str | None = None,
    ) -> RawInvoicePayload:
        """
        Extract invoice data using offline fixture lookup or dynamic heuristics.

        Args:
            file_bytes: Raw bytes of the document.
            filename: Name of the uploaded file.
            document_id: Optional document ID.
            correlation_id: Optional correlation tracking ID.

        Returns:
            RawInvoicePayload with extracted fields and confidence scores.
        """
        doc_id = document_id or str(uuid.uuid4())
        corr_id = correlation_id or str(uuid.uuid4())
        file_hash = hashlib.sha256(file_bytes).hexdigest().lower()
        clean_name = filename.lower().strip()

        # Strategy 1: Check Hash Registry
        if file_hash in self._hash_registry:
            logger.info(f"MockExtractor: Matched fixture by SHA-256 hash ({file_hash[:8]}...)")
            return self._build_payload_from_dict(
                self._hash_registry[file_hash], doc_id, corr_id, filename, "mock_fixture_hash"
            )

        # Strategy 1: Check Filename Registry
        for reg_name, data in self.fixtures.items():
            # Check full match, partial match, or index-based match (e.g. inv_001 vs inv-001)
            reg_stem = reg_name.split(".")[0].replace("_", "-")
            clean_stem = clean_name.split(".")[0].replace("_", "-")
            if reg_name in clean_name or clean_name in reg_name or reg_stem in clean_stem or clean_stem in reg_stem:
                logger.info(f"MockExtractor: Matched fixture by filename ({reg_name})")
                return self._build_payload_from_dict(
                    data, doc_id, corr_id, filename, "mock_fixture_catalog"
                )

        # Strategy 2: Dynamic Multi-Modal Heuristic Extraction
        logger.info(f"MockExtractor: Executing dynamic heuristic extraction for {filename}")
        raw_text = self._extract_text_from_bytes(file_bytes, filename)
        return self._extract_heuristically(raw_text, doc_id, corr_id, filename)

    async def extract(
        self,
        file_bytes: bytes,
        filename: str = "invoice.pdf",
        document_id: str | None = None,
        correlation_id: str | None = None,
        storage_path: str | None = None,
    ) -> NormalizedInvoice:
        """
        Async convenience method extracting document and returning NormalizedInvoice.
        """
        raw_payload = self.extract_document(
            file_bytes=file_bytes,
            filename=filename,
            document_id=document_id,
            correlation_id=correlation_id,
        )
        if storage_path:
            raw_payload.storage_path = storage_path
        return self._raw_to_normalized(raw_payload)

    def _extract_text_from_bytes(self, file_bytes: bytes, filename: str) -> str:
        """Extract plain text from PDF bytes or raw text buffer."""
        # Check for PDF header
        if file_bytes.startswith(b"%PDF"):
            # Try pypdf if installed
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                pages_text = [page.extract_text() or "" for page in reader.pages]
                full_text = "\n".join(pages_text).strip()
                if full_text:
                    return full_text
            except Exception:
                pass

            # Pure Python PDF stream decompressor fallback
            chunks: list[str] = []
            for match in re.finditer(rb"stream[\r\n]+([\s\S]*?)[\r\n]+endstream", file_bytes):
                stream_data = match.group(1)
                try:
                    decompressed = zlib.decompress(stream_data)
                    stream_data = decompressed
                except Exception:
                    pass

                # Extract text in parentheses (Tj operator)
                for tj in re.findall(rb"\(((?:[^()\\]|\\.)*)\)\s*Tj", stream_data):
                    chunks.append(tj.decode("latin-1", errors="ignore"))
                # Extract text in TJ array operator
                for tj_array in re.findall(rb"\[([\s\S]*?)\]\s*TJ", stream_data):
                    for tj in re.findall(rb"\(((?:[^()\\]|\\.)*)\)", tj_array):
                        chunks.append(tj.decode("latin-1", errors="ignore"))

            extracted = "\n".join(chunks).strip()
            if extracted:
                return extracted

        # Try direct text decoding
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return file_bytes.decode("latin-1")
            except Exception:
                # String extract from binary
                chars = [chr(b) if 32 <= b <= 126 or b in (10, 13) else " " for b in file_bytes]
                return "".join(chars)

    def _parse_heuristic_text(self, text: str) -> dict[str, ExtractedField[Any]]:
        """Direct text parser exposing heuristic fields for unit testing."""
        raw_fields: dict[str, ExtractedField[Any]] = {}
        vendor, vendor_conf = self._heuristic_vendor(text, "document.pdf")
        raw_fields["vendor_name"] = ExtractedField(value=vendor, confidence=vendor_conf)
        raw_fields["VendorName"] = ExtractedField(value=vendor, confidence=vendor_conf)

        inv_id, inv_conf = self._heuristic_invoice_id(text, "document.pdf")
        raw_fields["invoice_id"] = ExtractedField(value=inv_id, confidence=inv_conf)
        raw_fields["InvoiceId"] = ExtractedField(value=inv_id, confidence=inv_conf)

        inv_date, due_date, date_conf = self._heuristic_dates(text)
        raw_fields["invoice_date"] = ExtractedField(value=inv_date, confidence=date_conf)
        raw_fields["InvoiceDate"] = ExtractedField(value=inv_date, confidence=date_conf)
        if due_date:
            raw_fields["due_date"] = ExtractedField(value=due_date, confidence=date_conf * 0.95)
            raw_fields["DueDate"] = ExtractedField(value=due_date, confidence=date_conf * 0.95)

        currency, total, subtotal, tax, amt_conf = self._heuristic_amounts(text)
        raw_fields["total_amount"] = ExtractedField(value=total, confidence=amt_conf)
        raw_fields["InvoiceTotal"] = ExtractedField(value=total, confidence=amt_conf)
        if subtotal is not None:
            raw_fields["subtotal_amount"] = ExtractedField(value=subtotal, confidence=amt_conf)
            raw_fields["SubTotal"] = ExtractedField(value=subtotal, confidence=amt_conf)
        if tax is not None:
            raw_fields["tax_amount"] = ExtractedField(value=tax, confidence=amt_conf)
            raw_fields["TotalTax"] = ExtractedField(value=tax, confidence=amt_conf)
        raw_fields["currency"] = ExtractedField(value=currency, confidence=amt_conf)
        raw_fields["Currency"] = ExtractedField(value=currency, confidence=amt_conf)

        return raw_fields

    def _extract_heuristically(
        self,
        text: str,
        document_id: str,
        correlation_id: str,
        filename: str,
    ) -> RawInvoicePayload:
        """Apply regex heuristics to extract fields and line items."""
        raw_fields: dict[str, ExtractedField[Any]] = {}
        confidence_scores: dict[str, float] = {}

        # 1. Vendor Name Heuristic
        vendor, vendor_conf = self._heuristic_vendor(text, filename)
        raw_fields["VendorName"] = ExtractedField(value=vendor, confidence=vendor_conf)
        confidence_scores["vendor_name"] = vendor_conf

        # 2. Invoice ID Heuristic
        inv_id, inv_conf = self._heuristic_invoice_id(text, filename)
        raw_fields["InvoiceId"] = ExtractedField(value=inv_id, confidence=inv_conf)
        confidence_scores["invoice_id"] = inv_conf

        # 3. Dates Heuristic (Invoice Date & Due Date)
        inv_date, due_date, date_conf = self._heuristic_dates(text)
        raw_fields["InvoiceDate"] = ExtractedField(value=inv_date, confidence=date_conf)
        confidence_scores["invoice_date"] = date_conf
        if due_date:
            raw_fields["DueDate"] = ExtractedField(value=due_date, confidence=date_conf * 0.95)
            confidence_scores["due_date"] = date_conf * 0.95

        # 4. Currency & Amounts Heuristic
        currency, total, subtotal, tax, amt_conf = self._heuristic_amounts(text)
        raw_fields["InvoiceTotal"] = ExtractedField(value=total, confidence=amt_conf)
        confidence_scores["total_amount"] = amt_conf
        if subtotal is not None:
            raw_fields["SubTotal"] = ExtractedField(value=subtotal, confidence=amt_conf)
            confidence_scores["subtotal_amount"] = amt_conf
        if tax is not None:
            raw_fields["TotalTax"] = ExtractedField(value=tax, confidence=amt_conf)
            confidence_scores["tax_amount"] = amt_conf

        raw_fields["Currency"] = ExtractedField(value=currency, confidence=amt_conf)
        confidence_scores["currency"] = amt_conf

        # 5. Line Items Heuristic
        raw_items = self._heuristic_line_items(text, total)

        # 6. Arithmetic Validation Confidence Boost
        if subtotal is not None and tax is not None:
            if abs((subtotal + tax) - total) < 0.05:
                confidence_scores["total_amount"] = min(1.0, confidence_scores["total_amount"] + 0.05)
                raw_fields["InvoiceTotal"].confidence = confidence_scores["total_amount"]

        return RawInvoicePayload(
            document_id=document_id,
            correlation_id=correlation_id,
            filename=filename,
            raw_fields=raw_fields,
            raw_items=raw_items,
            confidence_scores=confidence_scores,
            extraction_engine="mock_heuristic_extractor",
            raw_text=text,
        )

    def _heuristic_vendor(self, text: str, filename: str) -> tuple[str, float]:
        """Extract vendor name from text or cues."""
        # Check header cues
        m = re.search(r"(?i)(?:From|Vendor|Merchant|Supplier|Billed By|Company)[\s:]*([A-Za-z0-9\s&'.,-]+)", text)
        if m:
            candidate = m.group(1).split("\n")[0].strip()
            if len(candidate) > 2:
                return candidate, 0.92

        # Check known vendor signatures
        known_vendors = [
            "Amazon Web Services Inc.", "Amazon Web Services", "Microsoft Corporation",
            "Microsft Corp Ireland", "Google Ireland Limited", "Google LLC",
            "UBER *TRIP HELP.UBER", "Uber Technologies", "Acme Corporation LLC",
            "Acme Corp Ltd", "Acme Corporation", "Delta Air Lines Inc", "Delta Air Lines",
            "Luigi's Pizza & Catering", "Slack Technologies LLC", "Slack Technologies",
        ]
        for kv in known_vendors:
            if re.search(r"\b" + re.escape(kv) + r"\b", text, re.IGNORECASE):
                return kv, 0.95

        # Check corporate suffixes
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines[:10]:
            if re.search(r"\b(Inc|Corp|LLC|Ltd|Limited|Technologies|Services|Airlines|Catering)\b", line, re.IGNORECASE):
                return line, 0.88

        # Fallback to first non-empty line
        if lines:
            return lines[0][:50], 0.70
        return "Unknown Vendor", 0.50

    def _heuristic_invoice_id(self, text: str, filename: str) -> tuple[str, float]:
        """Extract invoice number."""
        m = re.search(r"(?i)(?:Invoice\s*(?:#|No\.?|Number|ID)|INV\b|Receipt\s*(?:#|No\.?))[\s:]*([A-Za-z0-9\-_/]+)", text)
        if m:
            return m.group(1).strip(), 0.94

        m_code = re.search(r"\b([A-Z]{2,4}-\d{4,8}|INV-\d{3,8})\b", text)
        if m_code:
            return m_code.group(1).strip(), 0.90

        return f"INV-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}", 0.60

    def _heuristic_dates(self, text: str) -> tuple[str, str | None, float]:
        """Extract invoice date and optional due date."""
        inv_date = datetime.now(UTC).strftime("%Y-%m-%d")
        due_date: str | None = None
        conf = 0.70
        found_explicit_inv_date = False

        # Find all dates in text: (pre_context, iso_date)
        date_matches: list[tuple[str, str]] = []

        # Pattern 1: ISO YYYY-MM-DD or YYYY/MM/DD
        for m in re.finditer(r"\b(20\d\d)[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b", text):
            iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            pre_ctx = text[max(0, m.start() - 30):m.start()].lower()
            date_matches.append((pre_ctx, iso))

        # Pattern 2: European dot DD.MM.YYYY or DD-MM-YYYY
        for m in re.finditer(r"\b(0[1-9]|[12]\d|3[01])[.-](0[1-9]|1[0-2])[.-](20\d\d)\b", text):
            iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            pre_ctx = text[max(0, m.start() - 30):m.start()].lower()
            date_matches.append((pre_ctx, iso))

        # Pattern 3: Month DD, YYYY or DD Month YYYY
        for m in re.finditer(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(20\d\d)\b", text):
            mon = m.group(1).lower()
            if mon in MONTH_MAP:
                iso = f"{int(m.group(3)):04d}-{MONTH_MAP[mon]:02d}-{int(m.group(2)):02d}"
                pre_ctx = text[max(0, m.start() - 30):m.start()].lower()
                date_matches.append((pre_ctx, iso))

        for m in re.finditer(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d\d)\b", text):
            mon = m.group(2).lower()
            if mon in MONTH_MAP:
                iso = f"{int(m.group(3)):04d}-{MONTH_MAP[mon]:02d}-{int(m.group(1)):02d}"
                pre_ctx = text[max(0, m.start() - 30):m.start()].lower()
                date_matches.append((pre_ctx, iso))

        # Pattern 4: US MM/DD/YYYY
        for m in re.finditer(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(20\d\d)\b", text):
            iso = f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            pre_ctx = text[max(0, m.start() - 30):m.start()].lower()
            date_matches.append((pre_ctx, iso))

        if date_matches:
            for pre_ctx, d in date_matches:
                if any(k in pre_ctx for k in ["due", "payment due", "terms", "net", "fällig", "zahlbar"]):
                    due_date = d
                elif any(k in pre_ctx for k in ["invoice", "date", "datum", "rechnung", "bill", "billing", "issued"]):
                    inv_date = d
                    conf = 0.95
                    found_explicit_inv_date = True
                elif not found_explicit_inv_date:
                    inv_date = d
                    conf = 0.85
                    found_explicit_inv_date = True

        return inv_date, due_date, conf

    def _heuristic_amounts(self, text: str) -> tuple[str, float, float | None, float | None, float]:
        """Extract currency, total, subtotal, and tax amounts."""
        currency = "USD"
        total = 0.0
        subtotal: float | None = None
        tax: float | None = None
        conf = 0.70

        # Detect currency
        for sym, curr in CURRENCY_SYMBOL_MAP.items():
            if sym in text:
                currency = curr
                break

        # Total amount pattern (ensure not preceded by 'sub' or 'net')
        m_total = re.search(
            r"(?i)\b(?<!sub)(?<!sub-)(?<!sub )(?:total|amount due|balance due|grand total|total amount|gesamtbetrag|gesamt|betrag|montant|summe|endbetrag)[\s:]*([$€£¥]|USD|EUR|GBP|JPY)?\s*([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?|[0-9]+(?:[.,][0-9]+)?)\s*([$€£¥]|USD|EUR|GBP|JPY)?",
            text,
        )
        if m_total:
            c1, amt_str, c2 = m_total.group(1), m_total.group(2), m_total.group(3)
            sym = c1 or c2
            if sym and sym in CURRENCY_SYMBOL_MAP:
                currency = CURRENCY_SYMBOL_MAP[sym]
            total = self._parse_number(amt_str)
            conf = 0.94

        # Subtotal pattern
        m_sub = re.search(
            r"(?i)\b(?:subtotal|sub total|net amount|sub-total|nettobetrag|netto|zwischensumme)[\s:]*([$€£¥]|USD|EUR|GBP|JPY)?\s*([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?|[0-9]+(?:[.,][0-9]+)?)\s*([$€£¥]|USD|EUR|GBP|JPY)?",
            text,
        )
        if m_sub:
            subtotal = self._parse_number(m_sub.group(2))

        # Tax pattern
        m_tax = re.search(
            r"(?i)\b(?:tax|vat|sales tax|gst|mwst|ust|steuern|mehrwertsteuer)[\s:]*([$€£¥]|USD|EUR|GBP|JPY)?\s*([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?|[0-9]+(?:[.,][0-9]+)?)\s*([$€£¥]|USD|EUR|GBP|JPY)?",
            text,
        )
        if m_tax:
            tax = self._parse_number(m_tax.group(2))

        # Fallback if no total found: find largest monetary number
        if total == 0.0:
            numbers = []
            for m in re.finditer(r"(?:[$€£¥]|USD|EUR|GBP|JPY)\s*([0-9.,]+)|([0-9.,]+)\s*(?:[$€£¥]|USD|EUR|GBP|JPY)", text):
                val_str = m.group(1) or m.group(2)
                if val_str:
                    numbers.append(self._parse_number(val_str))
            if numbers:
                total = max(numbers)
                conf = 0.75

        return currency, total, subtotal, tax, conf

    def _parse_number(self, num_str: str) -> float:
        """Parse currency number string handling US, EU, and thousands separators."""
        s = num_str.strip().replace(" ", "")
        if not s:
            return 0.0

        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                # European decimal comma: 2.180,75 -> 2180.75
                s = s.replace(".", "").replace(",", ".")
            else:
                # US decimal dot: 1,420.50 -> 1420.50
                s = s.replace(",", "")
        elif "," in s:
            parts = s.split(",")
            if len(parts) == 2 and len(parts[-1]) <= 2:
                # Decimal comma: 78,50 -> 78.50
                s = s.replace(",", ".")
            else:
                # Thousand separator: 150,000 -> 150000
                s = s.replace(",", "")
        elif "." in s:
            parts = s.split(".")
            if len(parts) == 2 and len(parts[-1]) == 3:
                # European thousand dot: 150.000 -> 150000
                s = s.replace(".", "")

        try:
            return float(s)
        except ValueError:
            return 0.0

    def _heuristic_line_items(self, text: str, total_amount: float) -> list[LineItem]:
        """Extract line items from invoice table rows."""
        items: list[LineItem] = []
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        row_pattern = r"^(.+?)\s+(\d+(?:\.\d+)?)\s+([$€£¥]?[0-9,.]+(?:\.\d{2})?)\s+([$€£¥]?[0-9,.]+(?:\.\d{2})?)$"

        for line in lines:
            # Skip header or total summary lines
            if re.search(r"(?i)(description|qty|unit price|subtotal|tax|total|invoice|date|vendor|billed to)", line):
                if not re.match(r"(?i)^(amazon|microsoft|google|slack|uber|delta|luigi|item|product|consulting|large|trip)", line):
                    continue
            m = re.match(row_pattern, line)
            if m:
                desc = m.group(1).strip()
                qty = float(m.group(2))
                unit_p = self._parse_number(m.group(3))
                tot_p = self._parse_number(m.group(4))
                items.append(LineItem(
                    description=desc,
                    quantity=qty,
                    unit_price=unit_p,
                    total_amount=tot_p,
                    confidence=0.92,
                ))

        # Fallback if no table items extracted: create single consolidated line item
        if not items and total_amount > 0:
            items.append(LineItem(
                description="Invoice Item Total",
                quantity=1.0,
                unit_price=total_amount,
                total_amount=total_amount,
                confidence=0.85,
            ))

        return items

    def _build_payload_from_dict(
        self,
        data: dict[str, Any],
        document_id: str,
        correlation_id: str,
        filename: str,
        engine_tag: str,
    ) -> RawInvoicePayload:
        """Convert a fixture dictionary into RawInvoicePayload."""
        raw_fields: dict[str, ExtractedField[Any]] = {}
        confidence_scores: dict[str, float] = {}

        field_map = [
            ("VendorName", "vendor_name", str),
            ("InvoiceId", "invoice_id", str),
            ("InvoiceDate", "invoice_date", str),
            ("DueDate", "due_date", str),
            ("InvoiceTotal", "total_amount", float),
            ("SubTotal", "subtotal_amount", float),
            ("TotalTax", "tax_amount", float),
            ("Currency", "currency", str),
        ]

        for azure_key, target_key, _ in field_map:
            if target_key in data and data[target_key] is not None:
                val = data[target_key]
                conf = float(data.get("confidence_score", 0.98))
                raw_fields[azure_key] = ExtractedField(value=val, confidence=conf)
                confidence_scores[target_key] = conf

        raw_items: list[LineItem] = []
        for item in data.get("line_items", []):
            raw_items.append(LineItem(
                description=item.get("description"),
                quantity=item.get("quantity"),
                unit_price=item.get("unit_price"),
                total_amount=item.get("total_amount"),
                confidence=item.get("confidence", 0.95),
            ))

        return RawInvoicePayload(
            document_id=document_id,
            correlation_id=correlation_id,
            filename=filename,
            raw_fields=raw_fields,
            raw_items=raw_items,
            confidence_scores=confidence_scores,
            extraction_engine=engine_tag,
            raw_text=str(data),
        )

    def _raw_to_normalized(self, raw: RawInvoicePayload) -> NormalizedInvoice:
        """Helper to convert RawInvoicePayload to NormalizedInvoice."""
        fields = raw.raw_fields

        vendor_field = fields.get("VendorName") or ExtractedField(value="Unknown Vendor", confidence=0.0)
        invoice_id_field = fields.get("InvoiceId") or ExtractedField(value=f"INV-{raw.document_id[:8].upper()}", confidence=0.0)
        invoice_date_field = fields.get("InvoiceDate") or ExtractedField(
            value=datetime.now(UTC).strftime("%Y-%m-%d"), confidence=0.5
        )
        due_date_field = fields.get("DueDate")
        total_field = fields.get("InvoiceTotal") or ExtractedField(value=0.0, confidence=0.0)
        subtotal_field = fields.get("SubTotal")
        tax_field = fields.get("TotalTax")
        currency_field = fields.get("Currency") or ExtractedField(value="USD", confidence=0.8)

        line_items = raw.raw_items

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

        if subtotal_field and tax_field:
            expected_total = round(subtotal_field.value + tax_field.value, 2)
            if abs(expected_total - total_field.value) > 0.05:
                anomalies.append(AnomalyFlag(
                    code="MATH_DISCREPANCY",
                    message=f"Subtotal ({subtotal_field.value}) + Tax ({tax_field.value}) != Total ({total_field.value})",
                    severity="WARNING",
                    field="total_amount",
                ))

        return NormalizedInvoice(
            document_id=raw.document_id,
            correlation_id=raw.correlation_id,
            filename=raw.filename,
            storage_path=raw.storage_path,
            vendor_name=vendor_field,
            invoice_id=invoice_id_field,
            invoice_date=invoice_date_field,
            due_date=due_date_field,
            total_amount=total_field,
            tax_amount=tax_field,
            subtotal_amount=subtotal_field,
            currency=currency_field,
            currency_iso=str(currency_field.value).upper() if str(currency_field.value).upper() in ["USD", "EUR", "GBP", "JPY"] else "USD",
            line_items=line_items,
            confidence_score=overall_confidence,
            status=status,
            anomalies=anomalies,
            extraction_engine=raw.extraction_engine,
            created_at=datetime.now(UTC).isoformat(),
        )
