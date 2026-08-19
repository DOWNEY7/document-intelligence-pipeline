# E2E Test Infra: Document Intelligence Pipeline

## Test Philosophy
- **Opaque-Box & Requirement-Driven**: Tests interact with the pipeline via public APIs, CLI entry points, and normalized data contracts without relying on internal private implementations.
- **Methodology**: 4-Tier Test Suite design following Category-Partition, Boundary Value Analysis (BVA), Pairwise Combinatorial Testing, and Real-World Workload Testing + Tier 5 Adversarial Coverage Hardening.

## 10 Sample Invoice Fixture Specifications (R5 Matrix)
| ID | Filename | Vendor (Raw / Canonical) | Amount | Currency | Invoice Date | Characteristics / Test Purpose |
|----|----------|--------------------------|--------|----------|--------------|--------------------------------|
| `INV-001` | `inv_001_standard_aws.pdf` | `Amazon Web Services Inc.` / `Amazon Web Services` | `$1,420.50` | `USD` | `2026-08-01` | Clean standard multi-item cloud hosting invoice with tax & subtotal |
| `INV-002` | `inv_002_typo_vendor_msft.pdf` | `Microsft Corp Ireland` / `Microsoft Corporation` | `$350.00` | `USD` | `2026-08-03` | Noisy vendor string with typo & regional entity variation |
| `INV-003` | `inv_003_multicurrency_eur.pdf` | `Google Ireland Limited` / `Google LLC` | `€2,180.75` | `EUR` | `2026-08-05` | European formatting (comma decimal, EUR currency symbol) |
| `INV-004` | `inv_004_thermal_receipt_uber.png` | `UBER *TRIP HELP.UBER` / `Uber Technologies` | `$42.80` | `USD` | `2026-08-07` | PNG thermal receipt image, ride-share category, informal layout |
| `INV-005` | `inv_005_acme_dup_original.pdf` | `Acme Corp Ltd` / `Acme Corporation` | `$500.00` | `USD` | `2026-08-10` | Base original invoice for duplicate pair testing |
| `INV-006` | `inv_006_acme_dup_positive.pdf` | `Acme Corporation LLC` / `Acme Corporation` | `$500.00` | `USD` | `2026-08-13` | Positive duplicate (+3 days from INV-005, same canonical vendor & amount) |
| `INV-007` | `inv_007_acme_dup_negative.pdf` | `Acme Corporation` / `Acme Corporation` | `$500.00` | `USD` | `2026-09-15` | Negative duplicate (+36 days from INV-005, outside 7-day window) |
| `INV-008` | `inv_008_extreme_anomaly.pdf` | `Delta Air Lines Inc` / `Delta Air Lines` | `$1,250,000.00` | `USD` | `2026-08-12` | Extreme amount anomaly (> $50,000 statistical outlier threshold) |
| `INV-009` | `inv_009_unrecognized_vendor.jpg` | `Luigi's Pizza & Catering` / `Luigi's Pizza & Catering` | `$85.50` | `USD` | `2026-08-14` | JPG photo receipt from unknown vendor (< 70% fuzzy match threshold) |
| `INV-010` | `inv_010_jpy_zero_decimal.pdf` | `Slack Technologies LLC` / `Slack Technologies` | `¥150,000` | `JPY` | `2026-08-15` | Zero-decimal currency formatting (JPY), line items with software subscription |

## Test Tier Architecture
- **Tier 1: Feature Coverage (>= 5 per feature, 100+ cases)**:
  - Ingestion validation (MIME, size, error responses).
  - Field extraction completeness (dates, amounts, vendor, items).
  - Pydantic schema validation.
  - RapidFuzz threshold behaviors (>=85 exact/high, 70-84 moderate, <70 unknown).
  - Spend classification mapping across all 11 taxonomy categories.
- **Tier 2: Boundary & Corner Cases (>= 5 per feature, 50+ cases)**:
  - Empty files, corrupted headers, max file size limit.
  - Zero-decimal currencies (JPY), multi-symbol currencies.
  - Floating point equality (e.g. 500.0001 vs 500.00).
  - Exactly 7-day window boundary (Day 0, Day 7, Day 8).
  - Negative amounts, zero totals, missing vendor lines.
- **Tier 3: Cross-Feature Combinations (Pairwise Coverage, 25+ cases)**:
  - Multi-currency + extreme anomaly.
  - Unrecognized vendor + 7-day duplicate detection.
  - Messy vendor typo + missing line item subtotal.
  - Thermal receipt image + dual-storage query.
- **Tier 4: Real-World Application Workloads (10+ scenarios)**:
  - End-to-end processing of all 10 fixtures in sequence.
  - Bulk batch upload scenario with mixed anomalies and duplicates.
  - Streamlit dashboard data provider integration test.
- **Tier 5: Adversarial Hardening (Challenger-Driven)**:
  - Synthetic stress test generation with random noise, corrupted payloads, and boundary fuzzing.

## Coverage Thresholds
- Target: **100% passing rate** on all pytest test suites.
- Code coverage target: **>= 90% statement coverage** across `src/`.
- Offline execution: All tests must run cleanly without active internet access or external Azure resources.
