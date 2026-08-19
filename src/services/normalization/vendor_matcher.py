"""
src/services/normalization/vendor_matcher.py

Canonical Vendor Matcher using RapidFuzz multi-strategy token scoring,
pre-sanitization, legal suffix stripping, and 3-tier confidence classification.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rapidfuzz import fuzz

from src.core.models import ConfidenceTier, SpendCategory, VendorMatchResult

logger = logging.getLogger(__name__)

# ============================================================================
# Canonical Vendor Catalog (16 reference vendors)
# ============================================================================

CANONICAL_VENDORS_CATALOG: list[dict[str, Any]] = [
    {
        "vendor_id": "VEND-AWS-001",
        "canonical_name": "Amazon Web Services",
        "aliases": [
            "AWS",
            "Amazon Web Services Inc",
            "Amazon Web Services Inc.",
            "Amazon Web Services",
            "Amazon AWS",
            "AWS Direct Connect",
            "AWS Cloud Services",
            "AWS Cloud",
        ],
        "default_category": SpendCategory.SOFTWARE_CLOUD.value,
    },
    {
        "vendor_id": "VEND-MSFT-001",
        "canonical_name": "Microsoft Corporation",
        "aliases": [
            "Microsoft",
            "MSFT",
            "MSFT Azure",
            "Microsoft Ireland",
            "Microsft Corp Ireland",
            "Microsoft Ireland Operations",
            "Microsoft Corporation",
            "Microsoft Corp",
            "Microsoft 365",
            "Office 365",
        ],
        "default_category": SpendCategory.SOFTWARE_CLOUD.value,
    },
    {
        "vendor_id": "VEND-GOOG-001",
        "canonical_name": "Google LLC",
        "aliases": [
            "Google",
            "Google Cloud",
            "GCP",
            "Google Ireland Ltd",
            "Google Ireland Limited",
            "Google Cloud Platform",
            "Google LLC",
            "Google Workspace",
            "Google Inc",
            "Alphabet",
        ],
        "default_category": SpendCategory.SOFTWARE_CLOUD.value,
    },
    {
        "vendor_id": "VEND-ACME-001",
        "canonical_name": "Acme Corporation",
        "aliases": [
            "Acme",
            "Acme Corp",
            "Acme Corp Ltd",
            "Acme Corporation LLC",
            "Acme Corporation",
            "Acme Industries",
            "Acme Co Ltd",
            "Acme Co",
        ],
        "default_category": SpendCategory.OFFICE_SUPPLIES.value,
    },
    {
        "vendor_id": "VEND-UBER-001",
        "canonical_name": "Uber Technologies",
        "aliases": [
            "Uber",
            "Uber BV",
            "Uber Eats",
            "Uber Rides",
            "UBER *TRIP HELP.UBER",
            "Uber Technologies Inc",
            "Uber Payments",
            "Uber Technologies",
        ],
        "default_category": SpendCategory.TRAVEL_TRANSPORTATION.value,
    },
    {
        "vendor_id": "VEND-DAL-001",
        "canonical_name": "Delta Air Lines",
        "aliases": [
            "Delta",
            "Delta Airlines",
            "Delta Air Lines",
            "Delta Air Lines Inc",
            "Delta Air",
            "DAL",
        ],
        "default_category": SpendCategory.TRAVEL_TRANSPORTATION.value,
    },
    {
        "vendor_id": "VEND-STAPLES-001",
        "canonical_name": "Staples Inc.",
        "aliases": [
            "Staples",
            "Staples Advantage",
            "Staples Office",
            "Staples Inc",
            "Staples Inc.",
        ],
        "default_category": SpendCategory.OFFICE_SUPPLIES.value,
    },
    {
        "vendor_id": "VEND-CRM-001",
        "canonical_name": "Salesforce Inc.",
        "aliases": [
            "Salesforce",
            "SFDC",
            "Salesforce.com",
            "Salesforce.com Inc",
            "Salesforce CRM",
            "Salesforce Inc",
            "Salesforce Inc.",
        ],
        "default_category": SpendCategory.SOFTWARE_CLOUD.value,
    },
    {
        "vendor_id": "VEND-SLACK-001",
        "canonical_name": "Slack Technologies",
        "aliases": [
            "Slack",
            "Slack Inc",
            "Slack HQ",
            "Slack Technologies LLC",
            "Slack Technologies Inc",
            "Slack Technologies",
        ],
        "default_category": SpendCategory.SOFTWARE_CLOUD.value,
    },
    {
        "vendor_id": "VEND-GH-001",
        "canonical_name": "GitHub Inc.",
        "aliases": [
            "GitHub",
            "Github",
            "GitHub Inc",
            "GitHub Inc.",
            "GitHub LLC",
            "Github.com",
        ],
        "default_category": SpendCategory.SOFTWARE_CLOUD.value,
    },
    {
        "vendor_id": "VEND-HILTON-001",
        "canonical_name": "Hilton Hotels & Resorts",
        "aliases": [
            "Hilton",
            "Hilton Worldwide",
            "Hampton by Hilton",
            "Hilton Hotels",
            "Hilton Garden Inn",
            "Hilton Hotel",
        ],
        "default_category": SpendCategory.MEALS_ENTERTAINMENT.value,
    },
    {
        "vendor_id": "VEND-FEDEX-001",
        "canonical_name": "FedEx Corporation",
        "aliases": [
            "FedEx",
            "Federal Express",
            "FedEx Express",
            "FedEx Ground",
            "FedEx Freight",
            "FedEx Corporation",
        ],
        "default_category": SpendCategory.LOGISTICS_FREIGHT.value,
    },
    {
        "vendor_id": "VEND-ZOOM-001",
        "canonical_name": "Zoom Video Communications",
        "aliases": [
            "Zoom",
            "Zoom Video",
            "Zoom.us",
            "Zoom Video Communications",
            "Zoom Video Communications Inc",
        ],
        "default_category": SpendCategory.TELECOMMUNICATIONS.value,
    },
    {
        "vendor_id": "VEND-DO-001",
        "canonical_name": "DigitalOcean LLC",
        "aliases": [
            "DigitalOcean",
            "Digital Ocean",
            "DigitalOcean Inc",
            "Digital Ocean Inc",
            "DigitalOcean LLC",
        ],
        "default_category": SpendCategory.SOFTWARE_CLOUD.value,
    },
    {
        "vendor_id": "VEND-LYFT-001",
        "canonical_name": "Lyft Inc.",
        "aliases": [
            "Lyft",
            "Lyft Rides",
            "Lyft Inc",
            "Lyft Inc.",
            "Lyft Driver",
        ],
        "default_category": SpendCategory.TRAVEL_TRANSPORTATION.value,
    },
    {
        "vendor_id": "VEND-ADBE-001",
        "canonical_name": "Adobe Inc.",
        "aliases": [
            "Adobe Systems Inc",
            "Adobe Systems",
            "Adobe",
            "Adobe Creative Cloud",
            "Adobe Inc",
            "Adobe Inc.",
        ],
        "default_category": SpendCategory.SOFTWARE_CLOUD.value,
    },
]


class VendorMatcher:
    """
    Canonical vendor resolver utilizing RapidFuzz scoring and reference catalog.
    """

    LEGAL_SUFFIXES_REGEX = re.compile(
        r"\b(inc|corp|corporation|llc|ltd|limited|gmbh|bv|sarl|co|company|plc|sa|operations|technologies|services|help|trip|ireland|usa|ag|pty|holdings)\b",
        re.IGNORECASE,
    )

    def __init__(self, catalog: list[dict[str, Any]] | None = None) -> None:
        self.catalog = catalog or CANONICAL_VENDORS_CATALOG
        self._compiled_cache: dict[str, Any] = {}

    def normalize_vendor_string(self, text: str | None) -> str:
        """
        Pre-sanitize vendor string: lowercasing, punctuation stripping,
        corporate legal entity stripping, and whitespace collapsing.
        """
        if not text:
            return ""
        s = text.lower().strip()
        # Replace punctuation and special characters with spaces
        s = re.sub(r"[^\w\s]", " ", s)
        # Strip corporate suffixes
        s = self.LEGAL_SUFFIXES_REGEX.sub(" ", s)
        # Collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def match_vendor(self, raw_vendor_name: str | None) -> VendorMatchResult:
        """
        Match a raw vendor string against the known vendor catalog.

        Returns:
            VendorMatchResult with canonical name, vendor ID, match score,
            is_known_vendor flag, confidence tier, and default category.
        """
        if not raw_vendor_name or not str(raw_vendor_name).strip():
            return VendorMatchResult(
                canonical_name="Unknown Vendor",
                vendor_id=None,
                match_score=0.0,
                is_known_vendor=False,
                confidence_tier=ConfidenceTier.UNKNOWN,
                default_category=SpendCategory.MISCELLANEOUS_OTHER.value,
                raw_vendor=raw_vendor_name or "",
            )

        raw_clean = str(raw_vendor_name).strip()
        clean_query = self.normalize_vendor_string(raw_clean)

        if not clean_query:
            return VendorMatchResult(
                canonical_name="Unknown Vendor",
                vendor_id=None,
                match_score=0.0,
                is_known_vendor=False,
                confidence_tier=ConfidenceTier.UNKNOWN,
                default_category=SpendCategory.MISCELLANEOUS_OTHER.value,
                raw_vendor=raw_clean,
            )

        best_canonical: str = raw_clean
        best_vendor_id: str | None = None
        best_category: str | None = None
        best_score: float = 0.0

        for entry in self.catalog:
            canonical = entry["canonical_name"]
            vid = entry["vendor_id"]
            cat = entry.get("default_category", SpendCategory.MISCELLANEOUS_OTHER.value)
            candidates = [canonical] + entry.get("aliases", [])

            for cand in candidates:
                # Check exact normalized candidate string match
                if cand.strip().lower() == raw_clean.lower():
                    score = 100.0
                else:
                    clean_cand = self.normalize_vendor_string(cand)
                    if not clean_cand:
                        continue

                    if clean_cand == clean_query:
                        score = 100.0
                    else:
                        score_sort = fuzz.token_sort_ratio(clean_query, clean_cand)
                        score_set = fuzz.token_set_ratio(clean_query, clean_cand)
                        score_wratio = fuzz.WRatio(clean_query, clean_cand)
                        score = max(score_sort, score_set, score_wratio)

                        # Substring bonus for recognizable stems (>= 3 chars)
                        if (len(clean_cand) >= 3 and clean_cand in clean_query) or (
                            len(clean_query) >= 3 and clean_query in clean_cand
                        ):
                            score = max(score, 88.0)

                if score > best_score:
                    best_score = score
                    best_canonical = canonical
                    best_vendor_id = vid
                    best_category = cat

        rounded_score = round(best_score, 1)

        # Evaluate 3-tier thresholds
        if rounded_score >= 85.0:
            tier = ConfidenceTier.HIGH
            is_known = True
            canonical_name = best_canonical
            vendor_id = best_vendor_id
            category = best_category
        elif rounded_score >= 70.0:
            tier = ConfidenceTier.MODERATE
            is_known = True
            canonical_name = best_canonical
            vendor_id = best_vendor_id
            category = best_category
        else:
            tier = ConfidenceTier.UNKNOWN
            is_known = False
            canonical_name = raw_clean
            vendor_id = None
            category = SpendCategory.MISCELLANEOUS_OTHER.value

        return VendorMatchResult(
            canonical_name=canonical_name,
            vendor_id=vendor_id,
            match_score=rounded_score,
            is_known_vendor=is_known,
            confidence_tier=tier,
            default_category=category,
            raw_vendor=raw_clean,
        )
