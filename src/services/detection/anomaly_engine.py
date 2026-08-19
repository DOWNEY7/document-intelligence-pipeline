"""
src/services/detection/anomaly_engine.py

Multi-Rule Anomaly Detection Engine & Risk Scorer.

Detects 6 anomaly types:
1. EXTREME_AMOUNT     — invoice total is an outlier (IQR/Z-score)
2. UNRECOGNIZED_VENDOR — vendor not in known vendors catalog
3. CURRENCY_MISMATCH  — extracted currency doesn't match expected
4. LINE_ITEM_MATH     — line items don't sum to total
5. DATE_ANOMALY       — invoice date in far future or far past
6. MISSING_FIELDS     — required fields are absent or zero
7. DUPLICATE_SUBMISSION — already flagged by DuplicateDetectionEngine
"""

from __future__ import annotations

import logging
import statistics
from datetime import UTC, datetime

from src.core.models import AnomalyFlag, AnomalySeverity, NormalizedInvoice
from src.services.detection.duplicate_engine import DuplicateDetectionEngine

logger = logging.getLogger(__name__)


class AnomalyDetectionEngine:
    """
    Applies rule-based anomaly detection to a NormalizedInvoice,
    comparing it against a corpus of existing records for statistical outlier detection.
    """

    # Extreme amount thresholds (before statistical analysis)
    ABSOLUTE_EXTREME_THRESHOLD = 1_000_000.0   # > $1M always flagged
    ABSOLUTE_TRIVIAL_THRESHOLD = 0.01           # < $0.01 suspicious

    # Z-score threshold for extreme amounts (requires >= 10 records)
    Z_SCORE_THRESHOLD = 3.0

    # IQR multiplier for outlier detection (requires >= 5 records)
    IQR_MULTIPLIER = 2.5

    # Date anomaly window (days)
    FAR_FUTURE_DAYS = 90
    FAR_PAST_DAYS = 730

    # Known currencies
    KNOWN_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "SGD"}

    def __init__(self, existing_records: list[NormalizedInvoice] | None = None) -> None:
        self.existing_records = existing_records or []
        self._amounts: list[float] = [
            float(r.total_amount.value)
            for r in self.existing_records
            if r.total_amount and r.total_amount.value and float(r.total_amount.value) > 0
        ]

    def _check_extreme_amount(self, invoice: NormalizedInvoice) -> AnomalyFlag | None:
        """Detect extreme amount outliers using absolute thresholds and statistics."""
        amount = float(invoice.total_amount.value) if invoice.total_amount and invoice.total_amount.value else 0.0

        if amount <= 0:
            return None  # Handled by MISSING_FIELDS

        if amount >= self.ABSOLUTE_EXTREME_THRESHOLD:
            return AnomalyFlag(
                code="EXTREME_AMOUNT",
                message=f"Invoice total ${amount:,.2f} exceeds absolute extreme threshold (${self.ABSOLUTE_EXTREME_THRESHOLD:,.0f})",
                severity=AnomalySeverity.CRITICAL,
                field="total_amount",
                details={"amount": amount, "threshold": self.ABSOLUTE_EXTREME_THRESHOLD},
            )

        if amount < self.ABSOLUTE_TRIVIAL_THRESHOLD:
            return AnomalyFlag(
                code="EXTREME_AMOUNT",
                message=f"Invoice total ${amount:.4f} is suspiciously low (< ${self.ABSOLUTE_TRIVIAL_THRESHOLD})",
                severity=AnomalySeverity.WARNING,
                field="total_amount",
                details={"amount": amount, "threshold": self.ABSOLUTE_TRIVIAL_THRESHOLD},
            )

        # Statistical outlier detection
        if len(self._amounts) >= 5:
            try:
                sorted_amounts = sorted(self._amounts)
                q1 = statistics.quantiles(sorted_amounts, n=4)[0]
                q3 = statistics.quantiles(sorted_amounts, n=4)[2]
                iqr = q3 - q1
                upper_fence = q3 + self.IQR_MULTIPLIER * iqr
                lower_fence = max(0.0, q1 - self.IQR_MULTIPLIER * iqr)

                if amount > upper_fence or (lower_fence > 0 and amount < lower_fence):
                    return AnomalyFlag(
                        code="EXTREME_AMOUNT",
                        message=(
                            f"Invoice total ${amount:,.2f} is a statistical outlier "
                            f"(IQR fence: ${lower_fence:,.2f} – ${upper_fence:,.2f})"
                        ),
                        severity=AnomalySeverity.WARNING,
                        field="total_amount",
                        details={
                            "amount": amount,
                            "q1": q1,
                            "q3": q3,
                            "iqr": iqr,
                            "upper_fence": upper_fence,
                            "lower_fence": lower_fence,
                            "population_size": len(self._amounts),
                        },
                    )
            except statistics.StatisticsError:
                pass

        return None

    def _check_unrecognized_vendor(self, invoice: NormalizedInvoice) -> AnomalyFlag | None:
        """Flag invoices from vendors not in the canonical known-vendors table."""
        if not invoice.is_known_vendor:
            vendor_raw = invoice.vendor_raw or (
                str(invoice.vendor_name.value) if invoice.vendor_name else "Unknown"
            )
            score = invoice.vendor_match_score or 0.0
            return AnomalyFlag(
                code="UNRECOGNIZED_VENDOR",
                message=f"Vendor '{vendor_raw}' not found in canonical vendor catalog (match score: {score:.1f}/100)",
                severity=AnomalySeverity.WARNING,
                field="vendor_name",
                details={"raw_vendor": vendor_raw, "match_score": score},
            )
        return None

    def _check_currency_mismatch(self, invoice: NormalizedInvoice) -> AnomalyFlag | None:
        """Flag invoices with unrecognized or inconsistent currency codes."""
        currency_iso = invoice.currency_iso or "USD"
        if currency_iso not in self.KNOWN_CURRENCIES:
            return AnomalyFlag(
                code="CURRENCY_MISMATCH",
                message=f"Currency '{currency_iso}' is not a recognized ISO 4217 code",
                severity=AnomalySeverity.WARNING,
                field="currency",
                details={"currency_iso": currency_iso, "known_currencies": sorted(self.KNOWN_CURRENCIES)},
            )
        return None

    def _check_line_item_math(self, invoice: NormalizedInvoice) -> AnomalyFlag | None:
        """Detect line items that don't add up to the invoice total."""
        if not invoice.line_items:
            return None

        total_from_items = sum(
            float(item.total_amount)
            for item in invoice.line_items
            if item.total_amount is not None
        )

        if total_from_items == 0.0:
            return None  # Can't compute without item totals

        invoice_total = float(invoice.total_amount.value) if invoice.total_amount and invoice.total_amount.value else 0.0
        if invoice_total == 0.0:
            return None

        discrepancy = abs(total_from_items - invoice_total)
        tolerance = max(0.10, invoice_total * 0.005)  # 0.5% tolerance, min $0.10

        if discrepancy > tolerance:
            return AnomalyFlag(
                code="LINE_ITEM_MATH",
                message=(
                    f"Line items sum to ${total_from_items:,.2f} but invoice total is "
                    f"${invoice_total:,.2f} (discrepancy: ${discrepancy:,.2f})"
                ),
                severity=AnomalySeverity.WARNING,
                field="line_items",
                details={
                    "line_items_sum": total_from_items,
                    "invoice_total": invoice_total,
                    "discrepancy": discrepancy,
                    "tolerance": tolerance,
                    "item_count": len(invoice.line_items),
                },
            )
        return None

    def _check_date_anomaly(self, invoice: NormalizedInvoice) -> AnomalyFlag | None:
        """Flag invoices with dates far in the future or distant past."""
        if not invoice.invoice_date or not invoice.invoice_date.value:
            return None

        date_str = str(invoice.invoice_date.value)
        try:
            invoice_dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except ValueError:
            return AnomalyFlag(
                code="DATE_ANOMALY",
                message=f"Invoice date '{date_str}' could not be parsed as a valid date",
                severity=AnomalySeverity.ERROR,
                field="invoice_date",
                details={"raw_date": date_str},
            )

        now = datetime.now(UTC).replace(tzinfo=None)
        days_from_now = (invoice_dt - now).days

        if days_from_now > self.FAR_FUTURE_DAYS:
            return AnomalyFlag(
                code="DATE_ANOMALY",
                message=(
                    f"Invoice date {date_str} is {days_from_now} days in the future "
                    f"(threshold: {self.FAR_FUTURE_DAYS} days)"
                ),
                severity=AnomalySeverity.WARNING,
                field="invoice_date",
                details={"invoice_date": date_str, "days_from_now": days_from_now},
            )

        if days_from_now < -self.FAR_PAST_DAYS:
            return AnomalyFlag(
                code="DATE_ANOMALY",
                message=(
                    f"Invoice date {date_str} is {abs(days_from_now)} days in the past "
                    f"(threshold: {self.FAR_PAST_DAYS} days)"
                ),
                severity=AnomalySeverity.WARNING,
                field="invoice_date",
                details={"invoice_date": date_str, "days_from_now": days_from_now},
            )

        return None

    def _check_missing_fields(self, invoice: NormalizedInvoice) -> list[AnomalyFlag]:
        """Check for missing or zero required fields."""
        flags: list[AnomalyFlag] = []

        # Required: total_amount
        total = float(invoice.total_amount.value) if invoice.total_amount and invoice.total_amount.value is not None else None
        if total is None or total <= 0.0:
            flags.append(AnomalyFlag(
                code="MISSING_FIELDS",
                message="Invoice total amount is missing or zero",
                severity=AnomalySeverity.ERROR,
                field="total_amount",
            ))

        # Required: invoice_date
        if not invoice.invoice_date or not invoice.invoice_date.value:
            flags.append(AnomalyFlag(
                code="MISSING_FIELDS",
                message="Invoice date is missing",
                severity=AnomalySeverity.ERROR,
                field="invoice_date",
            ))

        # Required: vendor
        vendor_val = invoice.vendor_name.value if invoice.vendor_name else None
        if not vendor_val or str(vendor_val).strip() in ("", "Unknown Vendor", "unknown"):
            flags.append(AnomalyFlag(
                code="MISSING_FIELDS",
                message="Vendor name is missing or unrecognized",
                severity=AnomalySeverity.WARNING,
                field="vendor_name",
            ))

        return flags

    def detect(self, invoice: NormalizedInvoice) -> list[AnomalyFlag]:
        """
        Run all anomaly detection rules against the invoice.

        Returns list of AnomalyFlag objects (may be empty if all clear).
        """
        flags: list[AnomalyFlag] = []

        # 1. Extreme amount
        flag = self._check_extreme_amount(invoice)
        if flag:
            flags.append(flag)

        # 2. Unrecognized vendor
        flag = self._check_unrecognized_vendor(invoice)
        if flag:
            flags.append(flag)

        # 3. Currency mismatch
        flag = self._check_currency_mismatch(invoice)
        if flag:
            flags.append(flag)

        # 4. Line item math discrepancy
        flag = self._check_line_item_math(invoice)
        if flag:
            flags.append(flag)

        # 5. Date anomaly
        flag = self._check_date_anomaly(invoice)
        if flag:
            flags.append(flag)

        # 6. Missing required fields
        flags.extend(self._check_missing_fields(invoice))

        return flags

    @staticmethod
    def compute_risk_score(anomaly_flags: list[AnomalyFlag]) -> float:
        """
        Compute composite risk score from 0.0 (clean) to 1.0 (high risk).
        Severity weights: INFO=0.05, WARNING=0.15, ERROR=0.25, CRITICAL=0.40
        """
        if not anomaly_flags:
            return 0.0

        severity_weights = {
            AnomalySeverity.INFO: 0.05,
            AnomalySeverity.WARNING: 0.15,
            AnomalySeverity.ERROR: 0.25,
            AnomalySeverity.CRITICAL: 0.40,
        }

        total_weight = sum(
            severity_weights.get(f.severity, 0.15)  # type: ignore[arg-type]
            for f in anomaly_flags
        )
        return min(1.0, round(total_weight, 4))

    def enrich_with_anomaly_flags(self, invoice: NormalizedInvoice) -> NormalizedInvoice:
        """
        Detect anomalies and enrich the NormalizedInvoice in-place.

        Merges new anomaly flags with any existing ones (from normalization layer),
        computes risk_score, and sets has_anomalies flag.
        """
        new_flags = self.detect(invoice)

        # Merge: don't duplicate codes already present
        existing_codes = {f.code for f in invoice.anomalies}
        for flag in new_flags:
            if flag.code not in existing_codes:
                invoice.anomalies.append(flag)
                existing_codes.add(flag.code)

        invoice.has_anomalies = len(invoice.anomalies) > 0
        invoice.risk_score = self.compute_risk_score(invoice.anomalies)

        if invoice.has_anomalies and invoice.status == "SUCCESS":
            invoice.status = "NEEDS_REVIEW"

        return invoice


class DetectionService:
    """
    High-level service facade combining duplicate and anomaly detection.
    Designed for injection into the pipeline.
    """

    def __init__(
        self,
        duplicate_engine: DuplicateDetectionEngine | None = None,
        anomaly_engine: AnomalyDetectionEngine | None = None,
    ) -> None:
        self.duplicate_engine = duplicate_engine or DuplicateDetectionEngine()
        # AnomalyDetectionEngine is instantiated per-call with current records
        self._anomaly_engine_factory = anomaly_engine

    def run_detection(
        self,
        invoice: NormalizedInvoice,
        existing_records: list[NormalizedInvoice],
    ) -> NormalizedInvoice:
        """
        Run both duplicate and anomaly detection, enriching the invoice in-place.

        Args:
            invoice: The normalized invoice to check.
            existing_records: All previously processed normalized invoices for comparison.

        Returns:
            Enriched NormalizedInvoice with detection fields populated.
        """
        # Step 1: Duplicate detection
        invoice = self.duplicate_engine.enrich_with_duplicate_flags(invoice, existing_records)

        # Step 2: Anomaly detection with population context
        anomaly_engine = self._anomaly_engine_factory or AnomalyDetectionEngine(existing_records)
        invoice = anomaly_engine.enrich_with_anomaly_flags(invoice)

        logger.info(
            "Detection complete for invoice %s: is_duplicate=%s, has_anomalies=%s, risk_score=%.2f",
            invoice.id,
            invoice.is_duplicate,
            invoice.has_anomalies,
            invoice.risk_score,
        )
        return invoice


def get_detection_service() -> DetectionService:
    """Factory for dependency injection."""
    return DetectionService()
