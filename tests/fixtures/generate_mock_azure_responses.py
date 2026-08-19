"""
tests/fixtures/generate_mock_azure_responses.py

Deterministic generator that transforms ground-truth JSON fixtures in
tests/fixtures/sample_invoices/ into Azure Document Intelligence AnalyzeResult
JSON payloads in tests/fixtures/mock_azure_responses/.
"""

import json
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_INVOICES_DIR = WORKSPACE_ROOT / "tests" / "fixtures" / "sample_invoices"
MOCK_AZURE_DIR = WORKSPACE_ROOT / "tests" / "fixtures" / "mock_azure_responses"


def generate_mock_azure_response(ground_truth_path: Path) -> dict[str, Any]:
    """Transform ground-truth JSON fixture into Azure prebuilt-invoice AnalyzeResult structure."""
    with open(ground_truth_path, "r", encoding="utf-8") as f:
        gt = json.load(f)

    meta = gt.get("meta", {})
    raw = gt.get("raw_extraction", {})
    filename = meta.get("filename", "invoice.pdf")
    fixture_id = meta.get("fixture_id", "INV-000")

    # Build fields dictionary
    fields: dict[str, Any] = {}

    if "vendor_name" in raw and raw["vendor_name"].get("value"):
        v = raw["vendor_name"]
        fields["VendorName"] = {
            "type": "string",
            "valueString": v["value"],
            "content": v.get("raw_text", v["value"]),
            "confidence": v.get("confidence", 0.98),
            "boundingRegions": [{"pageNumber": 1, "polygon": [0.5, 1.0, 3.5, 1.0, 3.5, 1.3, 0.5, 1.3]}],
        }

    if "vendor_address" in raw and raw["vendor_address"].get("value"):
        va = raw["vendor_address"]
        fields["VendorAddress"] = {
            "type": "string",
            "valueString": va["value"],
            "content": va.get("raw_text", va["value"]),
            "confidence": va.get("confidence", 0.95),
            "boundingRegions": [{"pageNumber": 1, "polygon": [0.5, 1.4, 4.0, 1.4, 4.0, 1.7, 0.5, 1.7]}],
        }

    if "customer_name" in raw and raw["customer_name"].get("value"):
        cn = raw["customer_name"]
        fields["CustomerName"] = {
            "type": "string",
            "valueString": cn["value"],
            "content": cn.get("raw_text", cn["value"]),
            "confidence": cn.get("confidence", 0.96),
            "boundingRegions": [{"pageNumber": 1, "polygon": [5.0, 1.0, 8.0, 1.0, 8.0, 1.3, 5.0, 1.3]}],
        }

    if "invoice_id" in raw and raw["invoice_id"].get("value"):
        inv = raw["invoice_id"]
        fields["InvoiceId"] = {
            "type": "string",
            "valueString": inv["value"],
            "content": inv.get("raw_text", inv["value"]),
            "confidence": inv.get("confidence", 0.98),
            "boundingRegions": [{"pageNumber": 1, "polygon": [5.0, 1.4, 7.5, 1.4, 7.5, 1.7, 5.0, 1.7]}],
        }

    if "invoice_date" in raw and raw["invoice_date"].get("value"):
        idate = raw["invoice_date"]
        fields["InvoiceDate"] = {
            "type": "date",
            "valueDate": idate["value"],
            "content": idate.get("raw_text", idate["value"]),
            "confidence": idate.get("confidence", 0.99),
            "boundingRegions": [{"pageNumber": 1, "polygon": [5.0, 1.8, 7.0, 1.8, 7.0, 2.0, 5.0, 2.0]}],
        }

    if "due_date" in raw and raw["due_date"].get("value"):
        ddate = raw["due_date"]
        fields["DueDate"] = {
            "type": "date",
            "valueDate": ddate["value"],
            "content": ddate.get("raw_text", ddate["value"]),
            "confidence": ddate.get("confidence", 0.97),
            "boundingRegions": [{"pageNumber": 1, "polygon": [5.0, 2.1, 7.0, 2.1, 7.0, 2.3, 5.0, 2.3]}],
        }

    currency_code = raw.get("currency", {}).get("value", "USD")
    currency_symbol = raw.get("currency", {}).get("symbol", "$")

    if "subtotal" in raw and raw["subtotal"].get("value") is not None:
        sub = raw["subtotal"]
        fields["SubTotal"] = {
            "type": "currency",
            "valueCurrency": {
                "amount": float(sub["value"]),
                "currencySymbol": currency_symbol,
                "currencyCode": currency_code,
            },
            "content": sub.get("raw_text", f"{currency_symbol}{sub['value']}"),
            "confidence": sub.get("confidence", 0.98),
            "boundingRegions": [{"pageNumber": 1, "polygon": [6.0, 7.0, 7.8, 7.0, 7.8, 7.3, 6.0, 7.3]}],
        }

    if "total_tax" in raw and raw["total_tax"].get("value") is not None:
        tax = raw["total_tax"]
        fields["TotalTax"] = {
            "type": "currency",
            "valueCurrency": {
                "amount": float(tax["value"]),
                "currencySymbol": currency_symbol,
                "currencyCode": currency_code,
            },
            "content": tax.get("raw_text", f"{currency_symbol}{tax['value']}"),
            "confidence": tax.get("confidence", 0.98),
            "boundingRegions": [{"pageNumber": 1, "polygon": [6.0, 7.4, 7.8, 7.4, 7.8, 7.7, 6.0, 7.7]}],
        }

    if "invoice_total" in raw and raw["invoice_total"].get("value") is not None:
        tot = raw["invoice_total"]
        fields["InvoiceTotal"] = {
            "type": "currency",
            "valueCurrency": {
                "amount": float(tot["value"]),
                "currencySymbol": currency_symbol,
                "currencyCode": currency_code,
            },
            "content": tot.get("raw_text", f"{currency_symbol}{tot['value']}"),
            "confidence": tot.get("confidence", 0.99),
            "boundingRegions": [{"pageNumber": 1, "polygon": [6.0, 7.8, 7.8, 7.8, 7.8, 8.2, 6.0, 8.2]}],
        }

    if "amount_due" in raw and raw["amount_due"].get("value") is not None:
        due = raw["amount_due"]
        fields["AmountDue"] = {
            "type": "currency",
            "valueCurrency": {
                "amount": float(due["value"]),
                "currencySymbol": currency_symbol,
                "currencyCode": currency_code,
            },
            "content": due.get("raw_text", f"{currency_symbol}{due['value']}"),
            "confidence": due.get("confidence", 0.98),
            "boundingRegions": [{"pageNumber": 1, "polygon": [6.0, 8.3, 7.8, 8.3, 7.8, 8.6, 6.0, 8.6]}],
        }

    # Line items
    if "line_items" in raw and raw["line_items"]:
        items_array = []
        for it in raw["line_items"]:
            item_obj = {
                "Description": {
                    "type": "string",
                    "valueString": it.get("description", ""),
                    "content": it.get("description", ""),
                    "confidence": it.get("confidence", 0.95),
                },
                "Quantity": {
                    "type": "number",
                    "valueNumber": float(it.get("quantity", 1.0)),
                    "content": str(it.get("quantity", 1.0)),
                    "confidence": it.get("confidence", 0.95),
                },
                "UnitPrice": {
                    "type": "currency",
                    "valueCurrency": {
                        "amount": float(it.get("unit_price", 0.0)),
                        "currencySymbol": currency_symbol,
                        "currencyCode": currency_code,
                    },
                    "content": f"{currency_symbol}{it.get('unit_price', 0.0)}",
                    "confidence": it.get("confidence", 0.95),
                },
                "Amount": {
                    "type": "currency",
                    "valueCurrency": {
                        "amount": float(it.get("amount", 0.0)),
                        "currencySymbol": currency_symbol,
                        "currencyCode": currency_code,
                    },
                    "content": f"{currency_symbol}{it.get('amount', 0.0)}",
                    "confidence": it.get("confidence", 0.95),
                },
            }
            items_array.append({
                "type": "object",
                "valueObject": item_obj,
                "confidence": it.get("confidence", 0.95),
            })
        fields["Items"] = {
            "type": "array",
            "valueArray": items_array,
            "confidence": 0.98,
        }

    vendor_text = fields.get("VendorName", {}).get("valueString", "")
    total_text = fields.get("InvoiceTotal", {}).get("content", "")
    inv_id_text = fields.get("InvoiceId", {}).get("valueString", "")
    date_text = fields.get("InvoiceDate", {}).get("valueDate", "")

    full_content = (
        f"INVOICE\n"
        f"Vendor: {vendor_text}\n"
        f"Invoice Number: {inv_id_text}\n"
        f"Invoice Date: {date_text}\n"
        f"Total Amount: {total_text}\n"
        f"Document: {filename} ({fixture_id})\n"
    )

    return {
        "apiVersion": "2024-02-29-preview",
        "modelId": "prebuilt-invoice",
        "stringIndexType": "textElements",
        "content": full_content,
        "pages": [
            {
                "pageNumber": 1,
                "angle": 0.0,
                "width": 8.5,
                "height": 11.0,
                "unit": "inch",
                "spans": [{"offset": 0, "length": len(full_content)}],
            }
        ],
        "tables": [],
        "documents": [
            {
                "docType": "invoice",
                "boundingRegions": [{"pageNumber": 1, "polygon": [0.5, 0.5, 8.0, 0.5, 8.0, 10.5, 0.5, 10.5]}],
                "confidence": 0.98,
                "spans": [{"offset": 0, "length": len(full_content)}],
                "fields": fields,
            }
        ],
    }


def main() -> None:
    MOCK_AZURE_DIR.mkdir(parents=True, exist_ok=True)
    gt_files = sorted(SAMPLE_INVOICES_DIR.glob("inv_*.json"))
    print(f"Generating {len(gt_files)} mock Azure response JSON files in {MOCK_AZURE_DIR}...")

    for gt_path in gt_files:
        payload = generate_mock_azure_response(gt_path)
        out_path = MOCK_AZURE_DIR / gt_path.name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"  [OK] Generated {out_path.name}")


if __name__ == "__main__":
    main()
