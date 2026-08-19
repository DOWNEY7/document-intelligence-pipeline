"""
src/services/detection/duplicate_engine.py

7-Day Sliding Window Duplicate Detection Engine.

Identifies duplicate invoice submissions by matching:
- Canonical vendor name (exact match after normalisation)
- Total amount (within 1% tolerance for floating point)
- Invoice date within a ±7 day sliding window

A secondary fingerprint match (invoice_id) is used for high-confidence detection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from src.core.models import AnomalyFlag, AnomalySeverity, NormalizedInvoice

logger = logging.getLogger(__name__)


class DuplicateDetectionEngine:
    """
    Identifies duplicate invoice submissions using a 7-day sliding window rule.

    Match criteria (ALL must be satisfied):
        1. Canonical vendor name matches exactly (case-insensitive)
        2. Total amount matches within tolerance (default 1%)
        3. Invoice dates are within ±7 calendar days

    Secondary high-confidence criterion (either triggers CERTAIN duplicate):
        - Same invoice_id (invoice number) from same vendor
    """

    DEFAULT_WINDOW_DAYS = 7
    DEFAULT_AMOUNT_TOLERANCE = 0.01  # 1%

    def __init__(
        self,
        window_days: int = DEFAULT_WINDOW_DAYS,
        amount_tolerance_pct: float = DEFAULT_AMOUNT_TOLERANCE,
    ) -> None:
        self.window_days = window_days
        self.amount_tolerance_pct = amount_tolerance_pct

    def _parse_date(self, date_str: str | None) -> datetime | None:
        """Parse ISO 8601 YYYY-MM-DD date string to datetime object."""
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(date_str[:10], "%Y-%m-%d")
            except ValueError:
                continue
        return None

    def _get_invoice_date(self, invoice: NormalizedInvoice) -> datetime | None:
        """Extract invoice date from NormalizedInvoice."""
        if invoice.invoice_date and invoice.invoice_date.value:
            return self._parse_date(str(invoice.invoice_date.value))
        return None

    def _get_vendor_canonical(self, invoice: NormalizedInvoice) -> str:
        """Get the canonical vendor name for comparison."""
        if invoice.vendor_canonical:
            return invoice.vendor_canonical.strip().lower()
        if invoice.vendor_name and invoice.vendor_name.value:
            return str(invoice.vendor_name.value).strip().lower()
        return ""

    def _get_total_amount(self, invoice: NormalizedInvoice) -> float:
        """Get total amount from NormalizedInvoice."""
        if invoice.total_amount and invoice.total_amount.value is not None:
            return float(invoice.total_amount.value)
        return 0.0

    def _get_invoice_id(self, invoice: NormalizedInvoice) -> str:
        """Get invoice ID string for secondary comparison."""
        if invoice.invoice_id and invoice.invoice_id.value:
            return str(invoice.invoice_id.value).strip().upper()
        return ""

    def _amounts_match(self, amount_a: float, amount_b: float) -> bool:
        """Check if two amounts match within the configured tolerance."""
        if amount_a == 0.0 and amount_b == 0.0:
            return True
        if amount_a == 0.0 or amount_b == 0.0:
            return False
        relative_diff = abs(amount_a - amount_b) / max(abs(amount_a), abs(amount_b))
        return relative_diff <= self.amount_tolerance_pct

    def _dates_within_window(self, date_a: datetime | None, date_b: datetime | None) -> bool:
        """Check if two dates are within the configured window."""
        if date_a is None or date_b is None:
            # If date is missing, fall back to lenient match (might be same doc)
            return True
        return abs((date_a - date_b).days) <= self.window_days

    def check_duplicate(
        self,
        candidate: NormalizedInvoice,
        existing_records: list[NormalizedInvoice],
    ) -> tuple[bool, str | None, dict[str, Any] | None]:
        """
        Check if candidate invoice is a duplicate of any existing records.

        Returns:
            Tuple of (is_duplicate, duplicate_of_id, match_details)
        """
        if not existing_records:
            return False, None, None

        candidate_vendor = self._get_vendor_canonical(candidate)
        candidate_amount = self._get_total_amount(candidate)
        candidate_date = self._get_invoice_date(candidate)
        candidate_invoice_id = self._get_invoice_id(candidate)

        for existing in existing_records:
            # Skip self-comparison
            if existing.id == candidate.id or existing.document_id == candidate.document_id:
                continue

            existing_vendor = self._get_vendor_canonical(existing)
            existing_amount = self._get_total_amount(existing)
            existing_date = self._get_invoice_date(existing)
            existing_invoice_id = self._get_invoice_id(existing)

            # Skip if vendor doesn't match
            if candidate_vendor != existing_vendor and candidate_vendor and existing_vendor:
                continue

            # High-confidence: same vendor + same invoice_id
            if (
                candidate_invoice_id
                and existing_invoice_id
                and candidate_invoice_id == existing_invoice_id
                and candidate_vendor == existing_vendor
                and candidate_vendor not in ("", "unknown", "unknown vendor")
            ):
                return True, existing.id, {
                    "match_type": "exact_invoice_id",
                    "confidence": 1.0,
                    "matching_vendor": existing_vendor,
                    "matching_invoice_id": candidate_invoice_id,
                    "existing_amount": existing_amount,
                    "candidate_amount": candidate_amount,
                    "existing_date": str(existing_date.date()) if existing_date else None,
                    "candidate_date": str(candidate_date.date()) if candidate_date else None,
                }

            # Standard: same known vendor + non-zero amount within tolerance + date within window
            if (
                candidate_vendor
                and candidate_vendor not in ("", "unknown", "unknown vendor")
                and candidate_amount > 0.0
                and existing_amount > 0.0
                and self._amounts_match(candidate_amount, existing_amount)
                and self._dates_within_window(candidate_date, existing_date)
            ):
                date_diff_days = (
                    abs((candidate_date - existing_date).days)
                    if candidate_date and existing_date
                    else None
                )
                amount_diff_pct = (
                    abs(candidate_amount - existing_amount) / max(abs(candidate_amount), 1.0) * 100
                    if candidate_amount
                    else None
                )
                return True, existing.id, {
                    "match_type": "vendor_amount_date_window",
                    "confidence": 0.85,
                    "matching_vendor": existing_vendor,
                    "existing_amount": existing_amount,
                    "candidate_amount": candidate_amount,
                    "amount_diff_pct": round(amount_diff_pct, 4) if amount_diff_pct is not None else None,
                    "existing_date": str(existing_date.date()) if existing_date else None,
                    "candidate_date": str(candidate_date.date()) if candidate_date else None,
                    "date_diff_days": date_diff_days,
                    "window_days": self.window_days,
                }

        return False, None, None

    def enrich_with_duplicate_flags(
        self,
        invoice: NormalizedInvoice,
        existing_records: list[NormalizedInvoice],
    ) -> NormalizedInvoice:
        """
        Enrich NormalizedInvoice with duplicate detection results in-place.

        Returns the same invoice object with is_duplicate / duplicate_of_id
        / duplicate_reason / duplicate_match_details fields populated.
        """
        is_dup, dup_of_id, match_details = self.check_duplicate(invoice, existing_records)

        invoice.is_duplicate = is_dup
        invoice.duplicate_of_id = dup_of_id

        if is_dup and match_details:
            match_type = match_details.get("match_type", "unknown")
            vendor = match_details.get("matching_vendor", "")
            amount = match_details.get("existing_amount", 0.0)

            if match_type == "exact_invoice_id":
                invoice.duplicate_reason = (
                    f"Exact duplicate: invoice ID '{match_details.get('matching_invoice_id')}' "
                    f"already exists for vendor '{vendor}'"
                )
            else:
                days = match_details.get("date_diff_days")
                invoice.duplicate_reason = (
                    f"Likely duplicate: same vendor '{vendor}', amount ${amount:.2f}, "
                    f"submitted within {days or self.window_days}-day window"
                )
            invoice.duplicate_match_details = match_details

            # Add anomaly flag for duplicate
            dup_flag = AnomalyFlag(
                code="DUPLICATE_SUBMISSION",
                message=invoice.duplicate_reason,
                severity=AnomalySeverity.WARNING,
                details=match_details,
            )
            if not any(f.code == "DUPLICATE_SUBMISSION" for f in invoice.anomalies):
                invoice.anomalies.append(dup_flag)
                invoice.has_anomalies = True

            # Mark invoice status as NEEDS_REVIEW
            invoice.status = "NEEDS_REVIEW"

        logger.info(
            "Duplicate check for invoice %s: is_duplicate=%s, duplicate_of=%s",
            invoice.id,
            is_dup,
            dup_of_id,
        )
        return invoice
