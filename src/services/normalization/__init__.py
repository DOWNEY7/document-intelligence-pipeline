"""
src/services/normalization package.

Export normalization services, vendor matching, taxonomy classification,
and standardizers.
"""

from src.services.normalization.normalizer import (
    CurrencyStandardizer,
    DateStandardizer,
    LLMNormalizer,
    NormalizationService,
    RuleBasedNormalizer,
    get_normalization_service,
)
from src.services.normalization.taxonomy import (
    CANONICAL_CATEGORIES,
    CATEGORY_SYNONYMS,
    SpendTaxonomyClassifier,
    spend_taxonomy,
)
from src.services.normalization.vendor_matcher import (
    CANONICAL_VENDORS_CATALOG,
    VendorMatcher,
)

__all__ = [
    "CANONICAL_CATEGORIES",
    "CANONICAL_VENDORS_CATALOG",
    "CATEGORY_SYNONYMS",
    "CurrencyStandardizer",
    "DateStandardizer",
    "LLMNormalizer",
    "NormalizationService",
    "RuleBasedNormalizer",
    "SpendTaxonomyClassifier",
    "VendorMatcher",
    "get_normalization_service",
    "spend_taxonomy",
]
