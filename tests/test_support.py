"""
tests/test_support.py

Test harness domain support utilities for Document Intelligence Pipeline multi-tier testing.
Provides reference implementations and helpers for:
1. RapidFuzz Canonical Vendor Resolver & Known Vendors Table
2. 11-Category Spend Taxonomy Classifier
3. ISO Date & Currency Standardizer
4. 7-Day Sliding Window Duplicate Detection Engine
5. Multi-Type Anomaly Detection Engine & Risk Scorer
6. Dual-Storage Cosmos DB Mock Repository Abstraction
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from rapidfuzz import fuzz

from src.core.models import (
    AnomalyFlag,
    AnomalySeverity,
    NormalizedInvoice,
    RawInvoicePayload,
)

# ============================================================================
# 1. Known Vendors Reference Table & Vendor Matcher
# ============================================================================

KNOWN_VENDORS_TABLE = [
    {
        "vendor_id": "VEND-AWS-001",
        "canonical_name": "Amazon Web Services",
        "aliases": [
            "Amazon Web Services Inc.",
            "Amazon Web Services",
            "Amazon AWS",
            "AWS Direct Connect",
            "AWS Cloud Services",
        ],
        "default_category": "Cloud Services",
    },
    {
        "vendor_id": "VEND-MSFT-001",
        "canonical_name": "Microsoft Corporation",
        "aliases": [
            "Microsft Corp Ireland",
            "Microsoft Ireland Operations",
            "Microsoft Corporation",
            "Microsoft Corp",
            "Microsoft 365",
            "Microsoft",
        ],
        "default_category": "Software Subscriptions",
    },
    {
        "vendor_id": "VEND-GOOG-001",
        "canonical_name": "Google LLC",
        "aliases": [
            "Google Ireland Limited",
            "Google Cloud Platform",
            "Google LLC",
            "Google Workspace",
            "Google Inc",
        ],
        "default_category": "Cloud Services",
    },
    {
        "vendor_id": "VEND-UBER-001",
        "canonical_name": "Uber Technologies",
        "aliases": [
            "UBER *TRIP HELP.UBER",
            "Uber Technologies Inc",
            "Uber BV",
            "Uber Payments",
            "Uber",
        ],
        "default_category": "Travel & Transportation",
    },
    {
        "vendor_id": "VEND-ACME-001",
        "canonical_name": "Acme Corporation",
        "aliases": [
            "Acme Corp Ltd",
            "Acme Corporation LLC",
            "Acme Corporation",
            "Acme Corp",
            "Acme Industries",
        ],
        "default_category": "Office Supplies & Equipment",
    },
    {
        "vendor_id": "VEND-DAL-001",
        "canonical_name": "Delta Air Lines",
        "aliases": [
            "Delta Air Lines Inc",
            "Delta Airlines",
            "Delta Air Lines",
            "Delta Air",
        ],
        "default_category": "Travel & Transportation",
    },
    {
        "vendor_id": "VEND-SLACK-001",
        "canonical_name": "Slack Technologies",
        "aliases": [
            "Slack Technologies LLC",
            "Slack Technologies Inc",
            "Slack Technologies",
            "Slack",
        ],
        "default_category": "Software Subscriptions",
    },
    {
        "vendor_id": "VEND-FEDEX-001",
        "canonical_name": "FedEx Corporation",
        "aliases": ["FedEx", "Federal Express", "FedEx Ground"],
        "default_category": "Shipping & Logistics",
    },
    {
        "vendor_id": "VEND-CRM-001",
        "canonical_name": "Salesforce Inc.",
        "aliases": ["Salesforce", "Salesforce.com Inc", "Salesforce CRM"],
        "default_category": "Software Subscriptions",
    },
    {
        "vendor_id": "VEND-ADBE-001",
        "canonical_name": "Adobe Inc.",
        "aliases": ["Adobe Systems Inc", "Adobe Systems", "Adobe", "Adobe Creative Cloud"],
        "default_category": "Software Subscriptions",
    },
]


class VendorMatcherEngine:
    """Canonical vendor resolver using RapidFuzz token sorting and known vendor reference table."""

    def __init__(self, known_vendors: list[dict[str, Any]] | None = None) -> None:
        self.known_vendors = known_vendors or KNOWN_VENDORS_TABLE

    def match_vendor(self, raw_vendor_name: str | None) -> tuple[str, str | None, float, bool]:
        """
        Match a raw vendor string against known vendor records.

        Returns:
            Tuple of:
            - canonical_name: str (resolved canonical name or raw name if unknown)
            - vendor_id: Optional[str] (registered vendor ID or None)
            - match_score: float (0.0 to 100.0)
            - is_known_vendor: bool (True if score >= 70.0, else False)
        """
        if not raw_vendor_name or not str(raw_vendor_name).strip():
            return "Unknown Vendor", None, 0.0, False

        clean_query = self._normalize_vendor_string(raw_vendor_name)
        if not clean_query:
            return "Unknown Vendor", None, 0.0, False

        best_canonical: str = raw_vendor_name.strip()
        best_vendor_id: str | None = None
        best_score: float = 0.0

        for entry in self.known_vendors:
            canonical = entry["canonical_name"]
            vid = entry["vendor_id"]
            candidates = [canonical] + entry.get("aliases", [])

            for cand in candidates:
                clean_cand = self._normalize_vendor_string(cand)

                # Compute rapidfuzz score
                score_sort = fuzz.token_sort_ratio(clean_query, clean_cand)
                score_set = fuzz.token_set_ratio(clean_query, clean_cand)
                score = max(score_sort, score_set)

                # Direct substring bonus
                if clean_cand in clean_query or clean_query in clean_cand:
                    score = max(score, 88.0)

                if score > best_score:
                    best_score = score
                    best_canonical = canonical
                    best_vendor_id = vid

        # Evaluate threshold
        if best_score >= 70.0:
            return best_canonical, best_vendor_id, round(best_score, 1), True
        else:
            return raw_vendor_name.strip(), None, round(best_score, 1), False

    def _normalize_vendor_string(self, text: str) -> str:
        """Strip corporate entity suffixes and punctuation for fuzzy matching."""
        s = text.lower().strip()
        s = re.sub(r"[^\w\s]", " ", s)
        suffixes = [
            r"\binc\b", r"\bcorp\b", r"\bcorporation\b", r"\bllc\b", r"\bltd\b",
            r"\blimited\b", r"\bgmbh\b", r"\bs\.?a\.?\b", r"\bco\b", r"\bcompany\b",
            r"\boperations\b", r"\bhelp\b", r"\btrip\b", r"\bireland\b", r"\busa\b"
        ]
        for suf in suffixes:
            s = re.sub(suf, " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s


# ============================================================================
# 2. Spend Taxonomy Classifier
# ============================================================================

TAXONOMY_CATEGORIES = [
    "Cloud Services",
    "Software Subscriptions",
    "Travel & Transportation",
    "Office Supplies & Equipment",
    "Meals & Entertainment",
    "Professional Services",
    "Utilities",
    "Marketing & Advertising",
    "Hardware & Equipment",
    "Facilities",
    "Other / Miscellaneous",
]

CATEGORY_RULES: dict[str, list[str]] = {
    "Cloud Services": [
        "aws", "amazon web services", "cloud", "ec2", "s3", "rds", "compute", "azure", "gcp",
        "google cloud", "hosting", "direct connect", "data transfer", "kubernetes"
    ],
    "Software Subscriptions": [
        "microsoft", "office 365", "microsoft 365", "slack", "github", "jira", "zoom",
        "figma", "saas", "license", "subscription", "salesforce", "adobe", "creative cloud"
    ],
    "Travel & Transportation": [
        "uber", "lyft", "delta", "airline", "flight", "taxi", "rideshare", "train", "hotel",
        "airport", "car rental", "travel", "charter"
    ],
    "Office Supplies & Equipment": [
        "acme", "supplies", "paper", "stationery", "pens", "staples", "office depot",
        "furniture", "desk", "chair"
    ],
    "Meals & Entertainment": [
        "pizza", "restaurant", "catering", "dinner", "lunch", "breakfast", "coffee", "cafe",
        "food", "beverage", "luigi"
    ],
    "Professional Services": [
        "consulting", "legal", "advisory", "audit", "accounting", "retainer", "attorney",
        "professional services"
    ],
    "Utilities": [
        "electric", "water", "gas", "power", "telecom", "internet", "broadband", "verizon", "att"
    ],
    "Marketing & Advertising": [
        "google ads", "meta ads", "facebook ads", "advertising", "marketing", "campaign", "seo"
    ],
    "Hardware & Equipment": [
        "laptop", "macbook", "server", "dell", "lenovo", "monitor", "keyboard", "hardware"
    ],
    "Facilities": [
        "rent", "lease", "janitorial", "maintenance", "security guard", "facility", "building"
    ],
}


class SpendTaxonomyEngine:
    """11-category spend classification engine mapping line items and invoices."""

    @classmethod
    def classify(cls, vendor_name: str | None = "", description: str | None = "") -> str:
        """Determine spend category based on vendor and item descriptions."""
        combined = f"{vendor_name or ''} {description or ''}".lower()

        for category, keywords in CATEGORY_RULES.items():
            for kw in keywords:
                if kw in combined:
                    return category

        return "Other / Miscellaneous"

    @classmethod
    def all_categories(cls) -> list[str]:
        return list(TAXONOMY_CATEGORIES)


# ============================================================================
# 3. ISO Date & Currency Standardizer
# ============================================================================

class DateCurrencyStandardizer:
    """Standardizes date representations to ISO 8601 YYYY-MM-DD and currencies to ISO 4217."""

    MONTH_MAP = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "mai": 5, "juni": 6,
        "juli": 7, "oktober": 10, "dezember": 12,
    }

    CURRENCY_MAP = {
        "$": "USD",
        "USD": "USD",
        "US$": "USD",
        "€": "EUR",
        "EUR": "EUR",
        "£": "GBP",
        "GBP": "GBP",
        "¥": "JPY",
        "JPY": "JPY",
        "CAD": "CAD",
        "AUD": "AUD",
        "CHF": "CHF",
    }

    @classmethod
    def parse_iso_date(cls, raw_date_str: str | None) -> str | None:
        """Parse various date formats into standardized YYYY-MM-DD string."""
        if not raw_date_str or not str(raw_date_str).strip():
            return None

        s = str(raw_date_str).strip()

        # Format 1: ISO 8601 (YYYY-MM-DD)
        m_iso = re.search(r"\b(\d{4})[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b", s)
        if m_iso:
            y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
            if cls._is_valid_calendar_date(y, m, d):
                return f"{y:04d}-{m:02d}-{d:02d}"

        # Format 2: European Dot (DD.MM.YYYY or DD-MM-YYYY)
        m_eu = re.search(r"\b(0[1-9]|[12]\d|3[01])[.-](0[1-9]|1[0-2])[.-](\d{4})\b", s)
        if m_eu:
            d, m, y = int(m_eu.group(1)), int(m_eu.group(2)), int(m_eu.group(3))
            if cls._is_valid_calendar_date(y, m, d):
                return f"{y:04d}-{m:02d}-{d:02d}"

        # Format 3: Month Name DD, YYYY or DD. Month YYYY
        m_mon = re.search(r"\b([A-Za-zäöüÄÖÜ]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b", s)
        if m_mon:
            mon_str = m_mon.group(1).lower()
            if mon_str in cls.MONTH_MAP:
                m = cls.MONTH_MAP[mon_str]
                d, y = int(m_mon.group(2)), int(m_mon.group(3))
                if cls._is_valid_calendar_date(y, m, d):
                    return f"{y:04d}-{m:02d}-{d:02d}"

        m_mon_rev = re.search(r"\b(\d{1,2})\.?\s+([A-Za-zäöüÄÖÜ]{3,9})\s+(\d{4})\b", s)
        if m_mon_rev:
            mon_str = m_mon_rev.group(2).lower()
            if mon_str in cls.MONTH_MAP:
                m = cls.MONTH_MAP[mon_str]
                d, y = int(m_mon_rev.group(1)), int(m_mon_rev.group(3))
                if cls._is_valid_calendar_date(y, m, d):
                    return f"{y:04d}-{m:02d}-{d:02d}"

        # Format 4: US Slash (MM/DD/YYYY)
        m_us = re.search(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(\d{4})\b", s)
        if m_us:
            m, d, y = int(m_us.group(1)), int(m_us.group(2)), int(m_us.group(3))
            if cls._is_valid_calendar_date(y, m, d):
                return f"{y:04d}-{m:02d}-{d:02d}"

        return None

    @classmethod
    def _is_valid_calendar_date(cls, year: int, month: int, day: int) -> bool:
        """Validate calendar date including leap year rules."""
        try:
            date(year, month, day)
            return True
        except ValueError:
            return False

    @classmethod
    def standardize_currency(cls, currency_symbol_or_code: str | None) -> str:
        """Resolve currency symbol or text into ISO 4217 code."""
        if not currency_symbol_or_code:
            return "USD"
        cleaned = str(currency_symbol_or_code).strip().upper()
        return cls.CURRENCY_MAP.get(cleaned, cls.CURRENCY_MAP.get(str(currency_symbol_or_code).strip(), "USD"))

    @classmethod
    def parse_numeric_amount(cls, amount_str: str | float | int | None) -> float:
        """Parse currency number string handling US and European formatting."""
        if amount_str is None:
            return 0.0
        if isinstance(amount_str, (int, float)):
            return float(amount_str)

        s = str(amount_str).strip()
        for sym in ["$", "€", "£", "¥", "USD", "EUR", "GBP", "JPY"]:
            s = s.replace(sym, "")
        s = s.strip()

        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                # European 2.180,75 -> 2180.75
                s = s.replace(".", "").replace(",", ".")
            else:
                # US 1,420.50 -> 1420.50
                s = s.replace(",", "")
        elif "," in s:
            parts = s.split(",")
            if len(parts) == 2 and len(parts[-1]) <= 2:
                # 78,50 -> 78.50
                s = s.replace(",", ".")
            else:
                # 150,000 -> 150000
                s = s.replace(",", "")
        elif "." in s:
            parts = s.split(".")
            if len(parts) == 2 and len(parts[-1]) == 3:
                # European thousand dot 150.000 -> 150000
                s = s.replace(".", "")

        try:
            return float(s)
        except ValueError:
            return 0.0


# ============================================================================
# 4. 7-Day Sliding Window Duplicate Engine
# ============================================================================

class DuplicateDetectionEngine:
    """Identifies duplicate invoice submissions within +/- 7-day sliding window."""

    def __init__(self, window_days: int = 7, amount_tolerance: float = 0.01) -> None:
        self.window_days = window_days
        self.amount_tolerance = amount_tolerance

    def evaluate_duplicate(
        self,
        candidate: NormalizedInvoice,
        existing_invoices: list[NormalizedInvoice],
    ) -> tuple[bool, str | None, str | None, dict[str, Any]]:
        """
        Evaluate if candidate invoice matches an existing record.

        Rule:
        - Same canonical vendor (or exact raw vendor if unknown)
        - Identical total amount (within amount_tolerance)
        - Invoice dates within +/- window_days

        Returns:
            Tuple of:
            - is_duplicate: bool
            - duplicate_of_id: Optional[str]
            - duplicate_reason: Optional[str]
            - match_details: dict
        """
        cand_vendor = (candidate.vendor_canonical or candidate.vendor_raw or "").strip().lower()
        cand_amount = float(candidate.total_amount.value) if candidate.total_amount else 0.0
        cand_date_str = candidate.invoice_date.value if candidate.invoice_date else None

        if not cand_vendor or not cand_date_str:
            return False, None, None, {}

        try:
            cand_dt = datetime.strptime(cand_date_str, "%Y-%m-%d").date()
        except ValueError:
            return False, None, None, {}

        for record in existing_invoices:
            # Skip self
            if record.id == candidate.id or record.document_id == candidate.document_id:
                continue

            rec_vendor = (record.vendor_canonical or record.vendor_raw or "").strip().lower()
            rec_amount = float(record.total_amount.value) if record.total_amount else 0.0
            rec_date_str = record.invoice_date.value if record.invoice_date else None

            if not rec_vendor or not rec_date_str:
                continue

            try:
                rec_dt = datetime.strptime(rec_date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            # Check vendor match
            if cand_vendor != rec_vendor:
                continue

            # Check amount equality
            if abs(cand_amount - rec_amount) > self.amount_tolerance:
                continue

            # Check date window
            day_diff = abs((cand_dt - rec_dt).days)
            if day_diff <= self.window_days:
                reason = (
                    f"Duplicate identified: Same canonical vendor ('{candidate.vendor_canonical}') "
                    f"and identical amount (${cand_amount:.2f}) within {day_diff} days of invoice {record.id}."
                )
                details = {
                    "matched_invoice_id": record.id,
                    "matched_document_id": record.document_id,
                    "matched_vendor": record.vendor_canonical or record.vendor_raw,
                    "matched_amount": rec_amount,
                    "matched_date": rec_date_str,
                    "day_difference": day_diff,
                }
                return True, record.id, reason, details

        return False, None, None, {}


# ============================================================================
# 5. Multi-Type Anomaly Detection Engine
# ============================================================================

class AnomalyDetectionEngine:
    """Multi-rule anomaly detection engine and composite risk scorer."""

    def __init__(self, extreme_amount_threshold: float = 50000.0, math_tolerance: float = 0.05) -> None:
        self.extreme_amount_threshold = extreme_amount_threshold
        self.math_tolerance = math_tolerance

    def evaluate_anomalies(self, invoice: NormalizedInvoice) -> tuple[bool, list[AnomalyFlag], float]:
        """
        Evaluate invoice for anomalies and compute aggregated risk score.

        Returns:
            Tuple of:
            - has_anomalies: bool
            - anomaly_flags: list[AnomalyFlag]
            - risk_score: float (clamped in [0.0, 1.0])
        """
        flags: list[AnomalyFlag] = []
        risk_components: list[float] = []

        total = float(invoice.total_amount.value) if invoice.total_amount else 0.0
        subtotal = float(invoice.subtotal_amount.value) if invoice.subtotal_amount and invoice.subtotal_amount.value is not None else None
        tax = float(invoice.tax_amount.value) if invoice.tax_amount and invoice.tax_amount.value is not None else None

        # Rule 1: Extreme Amount Outlier
        if total > self.extreme_amount_threshold:
            flags.append(AnomalyFlag(
                code="EXTREME_AMOUNT",
                message=f"Invoice total ${total:,.2f} exceeds outlier threshold of ${self.extreme_amount_threshold:,.2f}.",
                severity=AnomalySeverity.CRITICAL,
                field="total_amount",
                details={"total_amount": total, "threshold": self.extreme_amount_threshold},
            ))
            risk_components.append(0.60)

        # Rule 2: Unrecognized Vendor
        if not invoice.is_known_vendor or (invoice.vendor_match_score is not None and invoice.vendor_match_score < 70.0):
            flags.append(AnomalyFlag(
                code="UNRECOGNIZED_VENDOR",
                message=f"Vendor '{invoice.vendor_raw}' was not found in known vendors reference table.",
                severity=AnomalySeverity.WARNING,
                field="vendor_name",
                details={"vendor_raw": invoice.vendor_raw, "match_score": invoice.vendor_match_score},
            ))
            risk_components.append(0.30)

        # Rule 3: Zero or Negative Total
        if total == 0.0:
            flags.append(AnomalyFlag(
                code="ZERO_TOTAL",
                message="Invoice total amount is exactly $0.00.",
                severity=AnomalySeverity.WARNING,
                field="total_amount",
            ))
            risk_components.append(0.25)
        elif total < 0.0:
            flags.append(AnomalyFlag(
                code="NEGATIVE_AMOUNT",
                message=f"Invoice total is negative (${total:,.2f}), indicating a credit note or refund.",
                severity=AnomalySeverity.INFO,
                field="total_amount",
            ))
            risk_components.append(0.15)

        # Rule 4: Subtotal + Tax Math Discrepancy
        if subtotal is not None and tax is not None:
            expected = round(subtotal + tax, 2)
            actual = round(total, 2)
            if abs(expected - actual) > self.math_tolerance:
                flags.append(AnomalyFlag(
                    code="MATH_DISCREPANCY",
                    message=f"Subtotal (${subtotal:.2f}) + Tax (${tax:.2f}) = ${expected:.2f}, does not equal Total (${actual:.2f}).",
                    severity=AnomalySeverity.WARNING,
                    field="total_amount",
                    details={"subtotal": subtotal, "tax": tax, "expected_total": expected, "actual_total": actual},
                ))
                risk_components.append(0.35)

        # Rule 5: Line item internal discrepancy
        for idx, item in enumerate(invoice.line_items):
            if item.has_math_discrepancy(self.math_tolerance):
                flags.append(AnomalyFlag(
                    code="LINE_ITEM_MATH_DISCREPANCY",
                    message=f"Line item {idx+1} ('{item.description}'): Quantity ({item.quantity}) * Unit Price ({item.unit_price}) != Line Total ({item.total_amount}).",
                    severity=AnomalySeverity.WARNING,
                    field=f"line_items[{idx}]",
                ))
                risk_components.append(0.20)
                break

        # Rule 6: Duplicate flag integration
        if invoice.is_duplicate:
            flags.append(AnomalyFlag(
                code="DUPLICATE_SUBMISSION",
                message=invoice.duplicate_reason or "Duplicate invoice detected.",
                severity=AnomalySeverity.ERROR,
                details=invoice.duplicate_match_details or {},
            ))
            risk_components.append(0.50)

        # Compute aggregate risk score
        if not risk_components:
            risk_score = 0.0
        else:
            # Multiplicative probabilistic combination 1 - prod(1 - r)
            prob_clean = 1.0
            for r in risk_components:
                prob_clean *= (1.0 - min(r, 0.9))
            risk_score = round(min(1.0, max(0.0, 1.0 - prob_clean)), 2)

        has_anomalies = len(flags) > 0
        return has_anomalies, flags, risk_score


# ============================================================================
# 6. Cosmos DB Dual-Storage Repository Mock
# ============================================================================

class DualStorageRepository:
    """
    High-fidelity dual-storage repository mimicking Cosmos DB containers:
    1. 'raw_extractions' container for immutable raw OCR payloads
    2. 'normalized_invoices' container for validated business records
    """

    def __init__(self) -> None:
        self.raw_container: dict[str, RawInvoicePayload] = {}
        self.normalized_container: dict[str, NormalizedInvoice] = {}

    def save_raw(self, payload: RawInvoicePayload) -> None:
        """Store raw extraction payload in raw_extractions container."""
        # Deep copy to ensure audit immutability
        self.raw_container[payload.document_id] = payload.model_copy(deep=True)

    def save_normalized(self, invoice: NormalizedInvoice) -> None:
        """Store normalized invoice in normalized_invoices container."""
        self.normalized_container[invoice.id] = invoice.model_copy(deep=True)

    def get_raw_by_document_id(self, document_id: str) -> RawInvoicePayload | None:
        """Retrieve raw extraction payload by document_id."""
        payload = self.raw_container.get(document_id)
        return payload.model_copy(deep=True) if payload else None

    def get_normalized_by_id(self, entity_id: str) -> NormalizedInvoice | None:
        """Retrieve normalized invoice by entity id."""
        invoice = self.normalized_container.get(entity_id)
        return invoice.model_copy(deep=True) if invoice else None

    def get_normalized_by_document_id(self, document_id: str) -> NormalizedInvoice | None:
        """Retrieve normalized invoice by document_id."""
        for inv in self.normalized_container.values():
            if inv.document_id == document_id:
                return inv.model_copy(deep=True)
        return None

    def get_by_correlation_id(self, correlation_id: str) -> tuple[list[RawInvoicePayload], list[NormalizedInvoice]]:
        """Query raw payloads and normalized records linked by correlation ID."""
        raws = [p.model_copy(deep=True) for p in self.raw_container.values() if p.correlation_id == correlation_id]
        norms = [i.model_copy(deep=True) for i in self.normalized_container.values() if i.correlation_id == correlation_id]
        return raws, norms

    def list_all_normalized(self) -> list[NormalizedInvoice]:
        """List all normalized records in storage."""
        return [inv.model_copy(deep=True) for inv in self.normalized_container.values()]

    def list_all_raw(self) -> list[RawInvoicePayload]:
        """List all raw extractions in storage."""
        return [p.model_copy(deep=True) for p in self.raw_container.values()]

    def delete(self, entity_id: str) -> bool:
        """Delete normalized record."""
        if entity_id in self.normalized_container:
            del self.normalized_container[entity_id]
            return True
        return False

    def clear(self) -> None:
        """Reset repository containers."""
        self.raw_container.clear()
        self.normalized_container.clear()
