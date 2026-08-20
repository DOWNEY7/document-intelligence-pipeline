# Document Intelligence Pipeline (Enterprise FDE Edition)

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-009688.svg)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.31%2B-FF4B4B.svg)](https://streamlit.io)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-E92063.svg)](https://docs.pydantic.dev)
[![Tests](https://img.shields.io/badge/Tests-303%20Passing-brightgreen.svg)]()

An enterprise-grade, end-to-end Document Intelligence & Spend Intelligence Pipeline designed for automated invoice, receipt, and financial document ingestion, structured OCR extraction via Azure Document Intelligence (`prebuilt-invoice`), AI/heuristic canonical normalization with Pydantic validation, dual-storage auditing in Cosmos DB, real-time duplicate & anomaly detection, and an executive Streamlit verification dashboard.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph Ingestion["1. Document Ingestion Layer"]
        UI["Streamlit / Client Upload"] -->|Upload Documents| API["FastAPI Ingestion Endpoint"]
        API --> StorageMgr["StorageManager File Persistence"]
        StorageMgr --> S1[("Local File Storage")]
    end

    subgraph Extraction["2. Extraction Engine"]
        API --> DocCheck{"Azure Configured?"}
        DocCheck -->|Yes| AzureClient["Azure Document Intelligence<br/>prebuilt-invoice Model"]
        DocCheck -->|No| MockExtractor["Offline Mock Extractor<br/>Multi-Modal Heuristics"]
        AzureClient --> RawPayload["Raw Extraction Payload"]
        MockExtractor --> RawPayload
    end

    subgraph Persistence1["3. Raw Audit Storage"]
        RawPayload -->|Immutable Audit Copy| RawDB[("Cosmos DB: Raw Extractions")]
    end

    subgraph Normalization["4. Normalization Layer"]
        RawPayload --> NormService["Normalization Engine"]
        NormService --> RapidFuzz["RapidFuzz Canonical Vendor Matcher<br/>16 Plus Registered Vendors"]
        NormService --> Taxonomy["11-Category Spend Taxonomy"]
        NormService --> ISOParsers["ISO Date and Currency Standardizer"]
        NormService --> PydanticVal["Pydantic v2 Schema Validator"]
        PydanticVal --> NormModel["Normalized Invoice Model"]
    end

    subgraph Detection["5. Duplicate and Anomaly Engine"]
        NormModel --> DupEngine["7-Day Duplicate Detection Engine<br/>Sliding Window Matching"]
        DupEngine --> AnomEngine["Multi-Rule Anomaly and Risk Engine<br/>Outliers and Math Validation"]
        AnomEngine --> EnrichedModel["Enriched Normalized Record"]
    end

    subgraph Persistence2["6. Normalized Persistence"]
        EnrichedModel --> NormDB[("Cosmos DB: Normalized Invoices")]
    end

    subgraph AnalyticsUI["7. Streamlit Executive Dashboard"]
        NormDB --> DashKPI["Tab 1: Executive KPI Metrics"]
        NormDB --> DashSpend["Tab 2: Spend Analytics Charts"]
        NormDB --> DashVerify["Tab 3: Verification Queue<br/>Side-by-Side Review"]
        S1 --> DashVerify
        API --> DashUpload["Tab 4: Live Ingestion Lab"]
        NormDB --> DashExplorer["Tab 5: Searchable Explorer"]
    end
```

---

## 🌟 Key Features

1. **Multi-Format Ingestion**: Accepts PDF, PNG, JPG, JPEG, and TIFF documents with strict MIME validation, file sanitization, and SHA-256 deduplication.
2. **Azure Document Intelligence + Robust Mock Fallback**: Seamless integration with Azure `prebuilt-invoice` model with 100% offline fallback executing heuristic regex parsing or catalog lookups when running locally or in CI.
3. **Dual-Storage Auditability**: Every document persists raw extraction telemetry (`raw_extractions`) and validated records (`normalized_invoices`) linked by correlation IDs for strict financial compliance.
4. **Canonical Vendor Resolution**: RapidFuzz fuzzy matching with legal suffix normalization resolving noisy vendor strings (e.g., `"Microsft Corp Ireland"` $\to$ `"Microsoft Corporation"`).
5. **Spend Taxonomy**: 11-category spend classification mapping line items and invoices to standard accounting buckets.
6. **7-Day Window Duplicate Detection**: Flags duplicate submissions matching canonical vendor and total amount within a 7-day sliding window, plus invoice number fingerprinting.
7. **Multi-Rule Anomaly & Risk Scoring**: Flags statistical outliers (IQR / Z-score), arithmetic discrepancies (line items vs total), currency anomalies, and date issues.
8. **Interactive Split-Screen Verification Queue**: Side-by-side verification interface embedding the original source PDF/image document stream alongside extracted key-value fields.
9. **API Security & CORS Protection**: API Key authentication (`X-API-Key` & Bearer token) and secure, strict CORS configuration preventing wildcard credential exposure.

---

## 📊 Benchmark & Accuracy Report (10 Diverse Test Documents)

The pipeline is benchmarked against a matrix of 10 diverse test fixtures covering real-world invoice scenarios:

| Fixture ID | Filename | Document Type | Expected Vendor | Canonical Resolved | Total Amount | Cur. | Key Challenge Tested | Accuracy / Result |
|:---|:---|:---|:---|:---|:---|:---|:---|:---|
| **INV-001** | `inv_001_standard_aws.pdf` | PDF | Amazon Web Services Inc. | Amazon Web Services | $1,420.50 | USD | Standard multi-item cloud hosting invoice with tax & subtotal | **100% Match** ✅ |
| **INV-002** | `inv_002_typo_vendor_msft.pdf` | PDF | Microsft Corp Ireland | Microsoft Corporation | $350.00 | USD | Severe vendor typo & regional entity alias resolution | **100% Match** ✅ |
| **INV-003** | `inv_003_multicurrency_eur.pdf` | PDF | Google Ireland Limited | Google LLC | €2,180.75 | EUR | European currency formatting (comma decimal `2.180,75 €`) | **100% Match** ✅ |
| **INV-004** | `inv_004_thermal_receipt_uber.png` | PNG Image | UBER *TRIP HELP.UBER | Uber Technologies | $42.80 | USD | Thermal receipt image, ride-share informal layout | **100% Match** ✅ |
| **INV-005** | `inv_005_acme_dup_original.pdf` | PDF | Acme Corp Ltd | Acme Corporation | $500.00 | USD | Base original invoice for duplicate pair testing | **100% Match** ✅ |
| **INV-006** | `inv_006_acme_dup_positive.pdf` | PDF | Acme Corporation LLC | Acme Corporation | $500.00 | USD | Positive duplicate (+3 days from INV-005, same vendor & amount) | **Flagged Duplicate** 🔁 |
| **INV-007** | `inv_007_acme_dup_negative.pdf` | PDF | Acme Corporation | Acme Corporation | $500.00 | USD | Negative duplicate (+36 days from INV-005, outside 7-day window) | **Clean Passed** ✅ |
| **INV-008** | `inv_008_extreme_anomaly.pdf` | PDF | Delta Air Lines Inc | Delta Air Lines | $1,250,000.00 | USD | Extreme amount anomaly (> $50,000 statistical outlier) | **Flagged Anomaly** ⚠️ |
| **INV-009** | `inv_009_unrecognized_vendor.jpg` | JPG Image | Luigi's Pizza & Catering | Luigi's Pizza & Catering | $85.50 | USD | Photo receipt from unknown vendor (< 70% match threshold) | **Flagged Unknown** ⚠️ |
| **INV-010** | `inv_010_jpy_zero_decimal.pdf` | PDF | Slack Technologies LLC | Slack Technologies | ¥150,000 | JPY | Zero-decimal currency formatting (Japanese Yen) | **100% Match** ✅ |

---

## 🚀 Quickstart & Installation

### 1. Prerequisites
- Python 3.10+
- (Optional) Azure Document Intelligence API key & endpoint
- (Optional) Azure Cosmos DB endpoint & key

### 2. Environment Setup
```bash
# Clone the repository
git clone https://github.com/DOWNEY7/document-intelligence-pipeline.git
cd document-intelligence-pipeline

# Create and activate virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows:
.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies in editable mode with development tools
pip install -e ".[dev]"
```

### 3. Environment Variables (Optional)
Create a `.env` file in the root directory (defaults to 100% offline mock mode if omitted):
```env
# Server
DEBUG=true
PORT=8000

# Azure Document Intelligence (leave blank for offline mock mode)
AZURE_FORM_RECOGNIZER_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/
AZURE_FORM_RECOGNIZER_KEY=<your-key>
USE_MOCK_AZURE=false

# Azure Cosmos DB (leave blank for local SQLite/JSON repository)
AZURE_COSMOS_ENDPOINT=https://<your-account>.documents.azure.com:443/
AZURE_COSMOS_KEY=<your-key>
USE_MOCK_COSMOS=false
```

---

## 🏃 Running the Services

### Start the FastAPI Backend
```bash
python -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
```
Interactive OpenAPI documentation available at: `http://localhost:8000/docs`

### Start the Streamlit Executive Dashboard
```bash
streamlit run src.dashboard.app.py --server.port 8501
```
Access the dashboard at: `http://localhost:8501`

---

## 🧪 Testing & Validation

Run the complete multi-tier pytest suite (303 tests):
```bash
pytest
```

Run test suite with detailed coverage report:
```bash
pytest --cov=src --cov-report=term-missing
```

Run specific test tiers:
```bash
pytest tests/unit/             # Unit tests (extraction, normalization, detection, storage)
pytest tests/integration/      # Integration tests (API endpoints, dual-storage)
pytest tests/e2e/              # End-to-end multi-fixture workflows
```

---

## 📡 API Reference Summary

| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/upload` or `/api/v1/upload` | Ingest, extract, normalize, and persist invoice document |
| `GET` | `/invoices` or `/api/v1/invoices` | List normalized invoices with filtering (vendor, category, anomalies, dates) |
| `GET` | `/invoices/{id}` | Retrieve single normalized invoice by entity ID or document ID |
| `GET` | `/invoices/correlation/{correlation_id}` | Retrieve all linked raw extractions and normalized records by trace ID |
| `GET` | `/raw/{document_id}` | Retrieve immutable raw extraction payload for auditing |
| `GET` | `/documents/{document_id}/audit` | Retrieve complete audit trail linking raw & normalized models |
| `GET` | `/documents/{document_id}/file` | Stream raw source document (PDF/Image) for UI preview |
| `GET` | `/health` or `/api/v1/health` | Service health status and mock fallback configuration |
