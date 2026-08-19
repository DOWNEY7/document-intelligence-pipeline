# E2E Test Suite Ready

## Test Runner
- **Command**: `uv run pytest tests/ -v`
- **Execution Time**: ~17s – 23s
- **Pass Criteria**: 100% pass on all test tiers (0 failures, 0 errors)
- **Air-Gapped Status**: 100% offline executable with zero live Azure credentials required.

## Coverage Summary
| Tier | Test Count | Description |
|------|-----------:|-------------|
| **Tier 1: Feature Coverage** | 50 | Comprehensive coverage across all 9 pipeline features (FastAPI ingestion, Azure extraction parsing, Pydantic schemas, RapidFuzz vendor matching, 11-category spend classification, ISO date/currency parsing, Cosmos DB dual-storage, 7-day duplicate detection, multi-type anomaly detection) |
| **Tier 2: Boundary & Corner Cases** | 52 | Boundary Value Analysis (BVA) covering upload size limits (0B, 1B, 5MB, 5MB+1B), zero-decimal JPY currency, extreme amounts ($1.25M, $100M, $0, -$50), calendar leap years, exact 7-day sliding window edges (Days 0, +1, +7, -7 positive; Days +8, -8 negative), RapidFuzz score thresholds (85%, 70%), and floating-point math tolerances |
| **Tier 3: Cross-Feature Combinations** | 28 | Pairwise combinatorial interactions (e.g. Typo vendor + extreme anomaly, unknown vendor + duplicate check, multi-currency + storage lookup, thermal receipt + live upload) |
| **Tier 4: Real-World Application Scenarios** | 12 | Realistic end-to-end workload lifecycles (all 10 sample fixtures, 3-stage duplicate lifecycle, fraud quarantine, multi-currency spend aggregation, concurrent batch ingestion, preview streaming, idempotency) |
| **Baseline & Fixture Verification** | 354 | Empirical stress tests, adversarial binary checks, PDF/image parsing, and model validation |
| **Total Test Suite** | **496** | **100% Pass Rate (496 / 496 passing)** |

## Feature Checklist Matrix
| Feature | Tier 1 | Tier 2 | Tier 3 | Tier 4 | Status |
|---------|:------:|:------:|:------:|:------:|:------:|
| 1. FastAPI Ingestion Service (`/upload`, `/api/v1/upload`) | 5 | 6 | 3 | 2 | Verified |
| 2. Azure Doc Intelligence & Mock Fallback Extractor | 6 | 5 | 3 | 2 | Verified |
| 3. Source Document Storage & Streaming Preview | 5 | 5 | 3 | 2 | Verified |
| 4. Pydantic v2 Strict Domain Models | 6 | 6 | 3 | 1 | Verified |
| 5. Canonical Vendor Fuzzy Matcher (RapidFuzz) | 6 | 6 | 4 | 1 | Verified |
| 6. Spend Categorization (11-Category Taxonomy) | 6 | 5 | 3 | 1 | Verified |
| 7. ISO Date & Currency Standardizer (ISO 8601 & 4217) | 5 | 6 | 3 | 1 | Verified |
| 8. Dual-Storage Cosmos DB Repository | 5 | 6 | 3 | 1 | Verified |
| 9. 7-Day Window Duplicate & Multi-Type Anomaly Engine | 6 | 7 | 3 | 1 | Verified |

## 10 Sample Fixtures Inventory (`tests/fixtures/sample_invoices/`)
| ID | Document Filename | Format | Vendor (Raw / Canonical) | Amount | Currency | Invoice Date | Ground Truth Characteristics & Test Purpose |
|---|-------------------|--------|--------------------------|--------|----------|--------------|---------------------------------------------|
| `INV-001` | `inv_001_standard_aws.pdf` | Vector PDF | `Amazon Web Services Inc.` / `Amazon Web Services` | `$1,420.50` | `USD` | `2026-08-01` | Standard multi-item cloud hosting invoice with tax & subtotal |
| `INV-002` | `inv_002_typo_vendor_msft.pdf` | Vector PDF | `Microsft Corp Ireland` / `Microsoft Corporation` | `$350.00` | `USD` | `2026-08-03` | Noisy vendor string with typo & regional entity variation |
| `INV-003` | `inv_003_multicurrency_eur.pdf` | Vector PDF | `Google Ireland Limited` / `Google LLC` | `€2,180.75` | `EUR` | `2026-08-05` | European formatting (comma decimal `2.180,75 €`, EU VAT, EUR currency) |
| `INV-004` | `inv_004_thermal_receipt_uber.png` | Raster PNG | `UBER *TRIP HELP.UBER` / `Uber Technologies` | `$42.80` | `USD` | `2026-08-07` | 400x720 PNG thermal receipt image, ride-share category, barcode raster |
| `INV-005` | `inv_005_acme_dup_original.pdf` | Vector PDF | `Acme Corp Ltd` / `Acme Corporation` | `$500.00` | `USD` | `2026-08-10` | Base original invoice for 7-day duplicate window testing |
| `INV-006` | `inv_006_acme_dup_positive.pdf` | Vector PDF | `Acme Corporation LLC` / `Acme Corporation` | `$500.00` | `USD` | `2026-08-13` | Positive duplicate (+3 days from INV-005, same canonical vendor & amount) |
| `INV-007` | `inv_007_acme_dup_negative.pdf` | Vector PDF | `Acme Corporation` / `Acme Corporation` | `$500.00` | `USD` | `2026-09-15` | Negative duplicate (+36 days from INV-005, outside 7-day window) |
| `INV-008` | `inv_008_extreme_anomaly.pdf` | Vector PDF | `Delta Air Lines Inc` / `Delta Air Lines` | `$1,250,000.00` | `USD` | `2026-08-12` | Extreme amount anomaly (> $50,000 statistical outlier threshold) |
| `INV-009` | `inv_009_unrecognized_vendor.jpg` | Raster JPG | `Luigi's Pizza & Catering` / `Luigi's Pizza & Catering` | `$85.50` | `USD` | `2026-08-14` | 440x780 JPG diner check receipt from unknown vendor (< 70% fuzzy match) |
| `INV-010` | `inv_010_jpy_zero_decimal.pdf` | Vector PDF | `Slack Technologies LLC` / `Slack Technologies` | `¥150,000` | `JPY` | `2026-08-15` | Zero-decimal currency formatting (JPY), line items with software subscription |
