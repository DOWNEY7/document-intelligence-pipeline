"""
src/services/normalization/taxonomy.py

11-Category Spend Taxonomy Classifier with rule/keyword classification,
alias/synonym mapping, and line-item categorization.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.models import LineItem, SpendCategory

logger = logging.getLogger(__name__)

# ============================================================================
# Canonical Categories & Synonyms
# ============================================================================

CANONICAL_CATEGORIES: list[str] = [
    SpendCategory.SOFTWARE_CLOUD.value,
    SpendCategory.HARDWARE_EQUIPMENT.value,
    SpendCategory.OFFICE_SUPPLIES.value,
    SpendCategory.TRAVEL_TRANSPORTATION.value,
    SpendCategory.MEALS_ENTERTAINMENT.value,
    SpendCategory.PROFESSIONAL_SERVICES.value,
    SpendCategory.MARKETING_ADVERTISING.value,
    SpendCategory.FACILITIES_REAL_ESTATE.value,
    SpendCategory.LOGISTICS_FREIGHT.value,
    SpendCategory.TELECOMMUNICATIONS.value,
    SpendCategory.MISCELLANEOUS_OTHER.value,
]

CATEGORY_SYNONYMS: dict[str, str] = {
    "cloud services": SpendCategory.SOFTWARE_CLOUD.value,
    "software subscriptions": SpendCategory.SOFTWARE_CLOUD.value,
    "software & cloud": SpendCategory.SOFTWARE_CLOUD.value,
    "saas": SpendCategory.SOFTWARE_CLOUD.value,
    "cloud": SpendCategory.SOFTWARE_CLOUD.value,
    "hardware & equipment": SpendCategory.HARDWARE_EQUIPMENT.value,
    "hardware": SpendCategory.HARDWARE_EQUIPMENT.value,
    "office supplies & equipment": SpendCategory.OFFICE_SUPPLIES.value,
    "office supplies": SpendCategory.OFFICE_SUPPLIES.value,
    "supplies": SpendCategory.OFFICE_SUPPLIES.value,
    "travel & transportation": SpendCategory.TRAVEL_TRANSPORTATION.value,
    "travel": SpendCategory.TRAVEL_TRANSPORTATION.value,
    "transportation": SpendCategory.TRAVEL_TRANSPORTATION.value,
    "meals & entertainment": SpendCategory.MEALS_ENTERTAINMENT.value,
    "meals": SpendCategory.MEALS_ENTERTAINMENT.value,
    "entertainment": SpendCategory.MEALS_ENTERTAINMENT.value,
    "dining": SpendCategory.MEALS_ENTERTAINMENT.value,
    "food": SpendCategory.MEALS_ENTERTAINMENT.value,
    "professional services": SpendCategory.PROFESSIONAL_SERVICES.value,
    "consulting": SpendCategory.PROFESSIONAL_SERVICES.value,
    "legal": SpendCategory.PROFESSIONAL_SERVICES.value,
    "marketing & advertising": SpendCategory.MARKETING_ADVERTISING.value,
    "marketing": SpendCategory.MARKETING_ADVERTISING.value,
    "advertising": SpendCategory.MARKETING_ADVERTISING.value,
    "facilities & real estate": SpendCategory.FACILITIES_REAL_ESTATE.value,
    "facilities": SpendCategory.FACILITIES_REAL_ESTATE.value,
    "real estate": SpendCategory.FACILITIES_REAL_ESTATE.value,
    "shipping & logistics": SpendCategory.LOGISTICS_FREIGHT.value,
    "logistics & freight": SpendCategory.LOGISTICS_FREIGHT.value,
    "logistics": SpendCategory.LOGISTICS_FREIGHT.value,
    "shipping": SpendCategory.LOGISTICS_FREIGHT.value,
    "freight": SpendCategory.LOGISTICS_FREIGHT.value,
    "telecommunications": SpendCategory.TELECOMMUNICATIONS.value,
    "telecom": SpendCategory.TELECOMMUNICATIONS.value,
    "utilities": SpendCategory.TELECOMMUNICATIONS.value,
    "other / miscellaneous": SpendCategory.MISCELLANEOUS_OTHER.value,
    "miscellaneous / other": SpendCategory.MISCELLANEOUS_OTHER.value,
    "other": SpendCategory.MISCELLANEOUS_OTHER.value,
    "miscellaneous": SpendCategory.MISCELLANEOUS_OTHER.value,
}

# ============================================================================
# Classification Keywords Rules
# ============================================================================

CATEGORY_RULES: dict[str, list[str]] = {
    SpendCategory.SOFTWARE_CLOUD.value: [
        "aws", "amazon web services", "cloud", "ec2", "s3", "rds", "compute",
        "azure", "gcp", "google cloud", "hosting", "direct connect", "data transfer",
        "kubernetes", "microsoft", "office 365", "microsoft 365", "slack", "github",
        "jira", "zoom", "figma", "saas", "license", "subscription", "salesforce",
        "adobe", "creative cloud", "digitalocean", "docker", "api", "serverless",
        "web hosting", "domain", "ssl certificate"
    ],
    SpendCategory.HARDWARE_EQUIPMENT.value: [
        "laptop", "macbook", "server", "dell", "lenovo", "hp", "monitor",
        "keyboard", "hardware", "cabling", "router", "switch", "mouse",
        "printer", "headset", "ram", "ssd", "hard drive", "equipment"
    ],
    SpendCategory.OFFICE_SUPPLIES.value: [
        "acme", "supplies", "paper", "stationery", "pens", "staples",
        "office depot", "furniture", "desk", "chair", "toner", "binder",
        "envelope", "post-it", "stapler"
    ],
    SpendCategory.TRAVEL_TRANSPORTATION.value: [
        "uber", "lyft", "delta", "airline", "flight", "taxi", "rideshare",
        "train", "hotel", "airport", "car rental", "travel", "charter",
        "amtrak", "hertz", "avis", "fuel", "mileage", "parking", "toll",
        "airfare"
    ],
    SpendCategory.MEALS_ENTERTAINMENT.value: [
        "pizza", "restaurant", "catering", "dinner", "lunch", "breakfast",
        "coffee", "cafe", "food", "beverage", "luigi", "starbucks",
        "doordash", "grubhub", "bar", "dining", "hilton"
    ],
    SpendCategory.PROFESSIONAL_SERVICES.value: [
        "consulting", "legal", "advisory", "audit", "accounting", "retainer",
        "attorney", "professional services", "recruiting", "staffing",
        "contractor", "law", "cpa", "tax preparation"
    ],
    SpendCategory.MARKETING_ADVERTISING.value: [
        "google ads", "meta ads", "facebook ads", "advertising", "marketing",
        "campaign", "seo", "sponsorship", "promotional", "billboard",
        "adwords", "linkedin ads", "ads", "pr agency"
    ],
    SpendCategory.FACILITIES_REAL_ESTATE.value: [
        "rent", "lease", "janitorial", "maintenance", "security guard",
        "facility", "building", "cleaning", "property", "hvac", "real estate",
        "office space", "repairs"
    ],
    SpendCategory.LOGISTICS_FREIGHT.value: [
        "fedex", "ups", "dhl", "usps", "shipping", "freight", "courier",
        "delivery", "postal", "logistics", "postage", "customs",
        "federal express", "parcel"
    ],
    SpendCategory.TELECOMMUNICATIONS.value: [
        "telecom", "internet", "broadband", "verizon", "att", "at&t",
        "t-mobile", "vodafone", "comcast", "voip", "cellular", "mobile",
        "phone", "electric", "water", "gas", "power", "utilities",
        "fiber", "sim card"
    ],
}


class SpendTaxonomyClassifier:
    """
    Spend category classifier mapping vendors, descriptions, and line items
    to standard spend categories.
    """

    def __init__(
        self,
        rules: dict[str, list[str]] | None = None,
        synonyms: dict[str, str] | None = None,
    ) -> None:
        self.rules = rules or CATEGORY_RULES
        self.synonyms = synonyms or CATEGORY_SYNONYMS

    def canonicalize_category(self, category_name: str | None) -> str:
        """
        Map category aliases or legacy strings to the canonical 11 categories.
        """
        if not category_name:
            return SpendCategory.MISCELLANEOUS_OTHER.value

        clean = category_name.strip().lower()
        if clean in self.synonyms:
            return self.synonyms[clean]

        for cat in CANONICAL_CATEGORIES:
            if clean == cat.lower():
                return cat

        return category_name.strip()

    def classify(
        self,
        vendor_name: str | None = "",
        description: str | None = "",
        default_vendor_category: str | None = None,
    ) -> str:
        """
        Determine spend category based on vendor and text description.
        """
        combined = f"{vendor_name or ''} {description or ''}".lower().strip()
        if not combined:
            return SpendCategory.MISCELLANEOUS_OTHER.value

        # First evaluate keyword rules across combined text
        for category, keywords in self.rules.items():
            for kw in keywords:
                if kw in combined:
                    return category

        # If default vendor category is provided, canonicalize and return
        if default_vendor_category:
            return self.canonicalize_category(default_vendor_category)

        return SpendCategory.MISCELLANEOUS_OTHER.value

    def classify_line_item(
        self,
        item: LineItem | Any,
        vendor_name: str | None = "",
        invoice_category: str | None = None,
    ) -> str:
        """
        Classify a single line item.
        """
        desc = getattr(item, "description", None) or ""
        cat = getattr(item, "category", None)
        if cat and cat.strip() and cat != SpendCategory.MISCELLANEOUS_OTHER.value:
            return self.canonicalize_category(cat)

        return self.classify(
            vendor_name=vendor_name,
            description=desc,
            default_vendor_category=invoice_category,
        )

    def all_categories(self) -> list[str]:
        """Return list of all 11 canonical spend categories."""
        return list(CANONICAL_CATEGORIES)


# Default singleton instance for convenience
spend_taxonomy = SpendTaxonomyClassifier()
