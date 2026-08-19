"""
Fixture Generator Script: Document Intelligence Pipeline (Milestone M_E2E_1)
Generates 10 realistic invoice documents (PDFs, PNG thermal receipt, JPG photo receipt),
10 ground-truth JSON schema files, and a SHA-256 indexing manifest.json.

Usage:
    uv run python tests/fixtures/generate_fixtures.py
    # or with custom output directory:
    uv run python tests/fixtures/generate_fixtures.py --output-dir tests/fixtures/sample_invoices
"""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Pillow imports for image generation
from PIL import Image, ImageDraw, ImageFont

# ReportLab imports for PDF generation
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# ==============================================================================
# 1. ReportLab PDF Generation Helper
# ==============================================================================

def create_styled_pdf_invoice(
    output_path: Path,
    vendor_name: str,
    vendor_address: list[str],
    invoice_id: str,
    invoice_date: str,
    due_date: str,
    customer_name: str,
    customer_address: list[str],
    currency_symbol: str,
    line_items: list[dict[str, Any]],
    subtotal: float,
    tax_amount: float,
    total_amount: float,
    tax_label: str = "Tax",
    notes: str | None = None,
    po_number: str | None = None,
    is_zero_decimal: bool = False,
    is_european_format: bool = False,
    watermark_text: str | None = None,
    theme_color_hex: str = "#1E293B",
) -> None:
    """Generates a professional vector PDF invoice using ReportLab."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    primary_color = colors.HexColor(theme_color_hex)
    accent_bg = colors.HexColor("#F8FAFC")
    border_color = colors.HexColor("#CBD5E1")
    text_dark = colors.HexColor("#0F172A")
    text_muted = colors.HexColor("#64748B")

    meta_style = ParagraphStyle(
        "MetaLeft",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=text_dark,
    )

    meta_right_style = ParagraphStyle(
        "MetaRight",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        alignment=TA_RIGHT,
        textColor=text_dark,
    )

    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=colors.white,
    )

    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=text_dark,
    )

    table_cell_right = ParagraphStyle(
        "TableCellRight",
        parent=table_cell_style,
        alignment=TA_RIGHT,
    )

    def fmt_amt(val: float) -> str:
        if is_zero_decimal:
            return f"{currency_symbol}{int(round(val)):,}"
        if is_european_format:
            formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"{formatted} {currency_symbol}"
        return f"{currency_symbol}{val:,.2f}"

    elements: list[Any] = []

    # Watermark / Notice Banner (e.g. for reprint duplicate)
    if watermark_text:
        banner_style = ParagraphStyle(
            "BannerNotice",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#991B1B"),
        )
        banner_table = Table([[Paragraph(f"⚠️ {watermark_text}", banner_style)]], colWidths=[540])
        banner_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEE2E2")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#F87171")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        )
        elements.append(banner_table)
        elements.append(Spacer(1, 10))

    # 1. Header Block: Vendor details (left) & Invoice Title/ID/Dates (right)
    vendor_lines = "<br/>".join([f"<b><font size='11'>{vendor_name}</font></b>"] + vendor_address)
    header_left = Paragraph(vendor_lines, meta_style)

    header_right_lines = [
        f"<b><font size='16' color='{theme_color_hex}'>INVOICE</font></b><br/>",
        f"<font color='{text_muted.hexval()}'>Invoice Number:</font> <b>{invoice_id}</b><br/>",
        f"<font color='{text_muted.hexval()}'>Invoice Date:</font> {invoice_date}<br/>",
        f"<font color='{text_muted.hexval()}'>Payment Due:</font> {due_date}",
    ]
    if po_number:
        header_right_lines.append(f"<br/><font color='{text_muted.hexval()}'>PO Number:</font> {po_number}")

    header_right = Paragraph("".join(header_right_lines), meta_right_style)

    header_table = Table([[header_left, header_right]], colWidths=[310, 230])
    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    elements.append(header_table)
    elements.append(Spacer(1, 14))

    # 2. Bill To Block
    customer_lines = "<br/>".join(
        [f"<b><font color='{theme_color_hex}'>BILL TO:</font></b>", f"<b>{customer_name}</b>"] + customer_address
    )
    bill_to_para = Paragraph(customer_lines, meta_style)
    bill_to_table = Table([[bill_to_para]], colWidths=[540])
    bill_to_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), accent_bg),
            ("BOX", (0, 0), (-1, -1), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    elements.append(bill_to_table)
    elements.append(Spacer(1, 14))

    # 3. Line Items Table
    table_data = [[
        Paragraph("Description", table_header_style),
        Paragraph("Qty", ParagraphStyle("THC", parent=table_header_style, alignment=TA_CENTER)),
        Paragraph("Unit Price", ParagraphStyle("THR", parent=table_header_style, alignment=TA_RIGHT)),
        Paragraph("Amount", ParagraphStyle("THR2", parent=table_header_style, alignment=TA_RIGHT)),
    ]]

    for item in line_items:
        desc = item.get("description", "")
        qty = item.get("quantity", 1.0)
        price = item.get("unit_price", 0.0)
        total = item.get("amount", item.get("total_amount", qty * price))

        qty_str = f"{int(qty)}" if qty == int(qty) else f"{qty:.1f}"

        table_data.append([
            Paragraph(desc, table_cell_style),
            Paragraph(qty_str, ParagraphStyle("TCC", parent=table_cell_style, alignment=TA_CENTER)),
            Paragraph(fmt_amt(price), table_cell_right),
            Paragraph(fmt_amt(total), table_cell_right),
        ])

    items_table = Table(table_data, colWidths=[280, 50, 105, 105])
    items_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), primary_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, accent_bg]),
            ("GRID", (0, 0), (-1, -1), 0.5, border_color),
        ])
    )
    elements.append(items_table)
    elements.append(Spacer(1, 10))

    # 4. Totals Summary Table
    totals_data = [
        [Paragraph("Subtotal:", table_cell_right), Paragraph(fmt_amt(subtotal), table_cell_right)],
        [Paragraph(f"{tax_label}:", table_cell_right), Paragraph(fmt_amt(tax_amount), table_cell_right)],
        [
            Paragraph(
                "<b>TOTAL DUE:</b>",
                ParagraphStyle("TB", parent=table_cell_right, fontSize=10, fontName="Helvetica-Bold"),
            ),
            Paragraph(
                f"<b>{fmt_amt(total_amount)}</b>",
                ParagraphStyle(
                    "TB2",
                    parent=table_cell_right,
                    fontSize=10,
                    fontName="Helvetica-Bold",
                    textColor=primary_color,
                ),
            ),
        ],
    ]
    totals_table = Table(totals_data, colWidths=[410, 130])
    totals_table.setStyle(
        TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEABOVE", (0, 2), (1, 2), 1, primary_color),
            ("LINEBELOW", (0, 2), (1, 2), 2, primary_color),
        ])
    )
    elements.append(totals_table)

    # 5. Notes & Footer
    if notes:
        elements.append(Spacer(1, 16))
        notes_para = Paragraph(f"<b>Notes & Payment Details:</b><br/>{notes}", meta_style)
        elements.append(notes_para)

    doc.build(elements)


# ==============================================================================
# 2. Pillow Image Generation Helpers
# ==============================================================================

def create_thermal_receipt_png(
    output_path: Path,
    vendor_header: str,
    vendor_sub: str,
    receipt_id: str,
    date_str: str,
    rider_name: str,
    line_items: list[dict[str, Any]],
    subtotal: float,
    tax_amount: float,
    total_amount: float,
) -> None:
    """Generates an authentic 400x720 thermal POS ride-share receipt PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 400, 720
    bg_color = (248, 248, 244)
    text_color = (20, 20, 20)
    muted_color = (90, 90, 90)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    font_title = ImageFont.load_default()
    font_body = ImageFont.load_default()
    font_bold = ImageFont.load_default()

    y = 25
    # Header
    draw.text((width // 2, y), vendor_header, fill=text_color, font=font_title, anchor="mm")
    y += 18
    draw.text((width // 2, y), vendor_sub, fill=muted_color, font=font_body, anchor="mm")
    y += 16
    draw.text((width // 2, y), f"Trip Receipt: {receipt_id}", fill=muted_color, font=font_body, anchor="mm")
    y += 16
    draw.text((width // 2, y), f"Date: {date_str}", fill=muted_color, font=font_body, anchor="mm")
    y += 16
    draw.text((width // 2, y), f"Rider: {rider_name}", fill=muted_color, font=font_body, anchor="mm")
    y += 20

    # Dashed divider
    for x in range(20, width - 20, 10):
        draw.line([(x, y), (x + 5, y)], fill=muted_color, width=1)
    y += 16

    # Line Items
    draw.text((25, y), "TRIP BREAKDOWN", fill=text_color, font=font_bold)
    y += 22

    for item in line_items:
        desc = item["description"]
        amt = item.get("amount", item.get("total_amount", 0.0))
        # Wrap long description if needed
        if len(desc) > 30:
            part1 = desc[:30]
            part2 = desc[30:]
            draw.text((25, y), part1, fill=text_color, font=font_body)
            draw.text((width - 25, y), f"${amt:.2f}", fill=text_color, font=font_body, anchor="ra")
            y += 16
            draw.text((35, y), part2, fill=text_color, font=font_body)
            y += 20
        else:
            draw.text((25, y), desc, fill=text_color, font=font_body)
            draw.text((width - 25, y), f"${amt:.2f}", fill=text_color, font=font_body, anchor="ra")
            y += 20

    y += 5
    for x in range(20, width - 20, 10):
        draw.line([(x, y), (x + 5, y)], fill=muted_color, width=1)
    y += 16

    # Subtotal & Tax & Total
    draw.text((25, y), "Subtotal:", fill=text_color, font=font_body)
    draw.text((width - 25, y), f"${subtotal:.2f}", fill=text_color, font=font_body, anchor="ra")
    y += 18

    if tax_amount > 0:
        draw.text((25, y), "Tax & Surcharges:", fill=text_color, font=font_body)
        draw.text((width - 25, y), f"${tax_amount:.2f}", fill=text_color, font=font_body, anchor="ra")
        y += 18

    draw.line([(20, y), (width - 20, y)], fill=text_color, width=2)
    y += 12

    draw.text((25, y), "TOTAL CHARGED (USD):", fill=text_color, font=font_bold)
    draw.text((width - 25, y), f"${total_amount:.2f}", fill=text_color, font=font_bold, anchor="ra")
    y += 30

    # Payment method & Barcode imitation
    draw.text((width // 2, y), "Paid via Corporate Visa (*4481)", fill=muted_color, font=font_body, anchor="mm")
    y += 22

    # Draw barcode bars
    barcode_x = 70
    barcode_y = y
    barcode_w = 260
    barcode_h = 35
    for bx in range(barcode_x, barcode_x + barcode_w, 4):
        if (bx % 7) in (0, 1, 3, 5):
            draw.line([(bx, barcode_y), (bx, barcode_y + barcode_h)], fill=(40, 40, 40), width=2)
    y += 45

    draw.text((width // 2, y), "Thank you for riding with Uber!", fill=muted_color, font=font_body, anchor="mm")

    img.save(output_path, "PNG")


def create_restaurant_receipt_jpg(
    output_path: Path,
    restaurant_name: str,
    address_lines: list[str],
    order_id: str,
    table_no: str,
    server_name: str,
    date_time_str: str,
    line_items: list[dict[str, Any]],
    subtotal: float,
    tax: float,
    total: float,
) -> None:
    """Generates an authentic 440x780 restaurant guest check JPG receipt."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 440, 780
    bg_color = (252, 250, 242)  # Warm paper parchment
    text_color = (25, 25, 25)
    muted_color = (100, 100, 100)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    font_title = ImageFont.load_default()
    font_body = ImageFont.load_default()
    font_bold = ImageFont.load_default()

    y = 30
    draw.text((width // 2, y), restaurant_name.upper(), fill=text_color, font=font_title, anchor="mm")
    y += 20
    for addr in address_lines:
        draw.text((width // 2, y), addr, fill=muted_color, font=font_body, anchor="mm")
        y += 15

    y += 8
    draw.line([(25, y), (width - 25, y)], fill=muted_color, width=1)
    y += 14

    # Check details
    draw.text((30, y), f"Check #: {order_id}", fill=text_color, font=font_body)
    draw.text((width - 30, y), f"Table: {table_no}", fill=text_color, font=font_body, anchor="ra")
    y += 16
    draw.text((30, y), f"Server: {server_name}", fill=text_color, font=font_body)
    draw.text((width - 30, y), date_time_str, fill=text_color, font=font_body, anchor="ra")
    y += 18

    draw.line([(25, y), (width - 25, y)], fill=muted_color, width=1)
    y += 16

    # Items
    draw.text((30, y), "QTY  ITEM DESCRIPTION", fill=text_color, font=font_bold)
    draw.text((width - 30, y), "AMOUNT", fill=text_color, font=font_bold, anchor="ra")
    y += 20

    for item in line_items:
        desc = item["description"]
        qty = item.get("quantity", 1)
        tot = item.get("amount", item.get("total_amount", 0.0))
        qty_str = f"{int(qty)}x" if qty == int(qty) else f"{qty}x"

        draw.text((30, y), f"{qty_str:<4} {desc}", fill=text_color, font=font_body)
        draw.text((width - 30, y), f"${tot:.2f}", fill=text_color, font=font_body, anchor="ra")
        y += 20

    y += 8
    draw.line([(25, y), (width - 25, y)], fill=muted_color, width=1)
    y += 16

    # Totals
    draw.text((30, y), "Subtotal:", fill=text_color, font=font_body)
    draw.text((width - 30, y), f"${subtotal:.2f}", fill=text_color, font=font_body, anchor="ra")
    y += 18
    draw.text((30, y), "NY Sales Tax (9.62%):", fill=text_color, font=font_body)
    draw.text((width - 30, y), f"${tax:.2f}", fill=text_color, font=font_body, anchor="ra")
    y += 22

    draw.line([(25, y), (width - 25, y)], fill=text_color, width=2)
    y += 12
    draw.text((30, y), "TOTAL BALANCE:", fill=text_color, font=font_bold)
    draw.text((width - 30, y), f"${total:.2f}", fill=text_color, font=font_bold, anchor="ra")
    y += 35

    # Tip box
    draw.rectangle([(30, y), (width - 30, y + 60)], outline=muted_color, width=1)
    draw.text(
        (width // 2, y + 18),
        "Suggested Tip: 15%=$11.93 | 18%=$14.31 | 20%=$15.90",
        fill=muted_color,
        font=font_body,
        anchor="mm",
    )
    draw.text(
        (width // 2, y + 42),
        "THANK YOU FOR YOUR PATRONAGE!",
        fill=text_color,
        font=font_bold,
        anchor="mm",
    )

    img.save(output_path, "JPEG", quality=92)


# ==============================================================================
# 3. Ground-Truth Data Definitions for All 10 Fixtures
# ==============================================================================

FIXTURES_CONFIG: dict[str, dict[str, Any]] = {
    "INV-001": {
        "stem": "inv_001_standard_aws",
        "file_ext": ".pdf",
        "doc_type_builder": "pdf",
        "pdf_params": {
            "vendor_name": "Amazon Web Services Inc.",
            "vendor_address": ["410 Terry Ave N", "Seattle, WA 98109, USA", "Tax ID: US-91-1234567"],
            "invoice_id": "INV-AWS-2026-0881",
            "invoice_date": "2026-08-01",
            "due_date": "2026-08-31",
            "customer_name": "Contoso Global Enterprises",
            "customer_address": ["100 Enterprise Way, Suite 400", "Austin, TX 78701, USA", "Account ID: 1049-8812-9901"],
            "currency_symbol": "$",
            "line_items": [
                {
                    "description": "Amazon Elastic Compute Cloud (EC2) - Production Instances",
                    "quantity": 1.0,
                    "unit_price": 850.00,
                    "amount": 850.00,
                },
                {
                    "description": "Amazon Simple Storage Service (S3) - Standard Storage",
                    "quantity": 1.0,
                    "unit_price": 220.50,
                    "amount": 220.50,
                },
                {
                    "description": "AWS Direct Connect & Regional Data Transfer",
                    "quantity": 1.0,
                    "unit_price": 250.00,
                    "amount": 250.00,
                },
            ],
            "subtotal": 1320.50,
            "tax_amount": 100.00,
            "total_amount": 1420.50,
            "tax_label": "State Sales Tax (7.57%)",
            "notes": "Thank you for using AWS. Automatic charge to Corporate Credit Card ending in 1092.",
            "po_number": "PO-99120",
            "theme_color_hex": "#1E293B",
        },
        "ground_truth": {
            "meta": {
                "fixture_id": "INV-001",
                "filename": "inv_001_standard_aws.pdf",
                "file_format": "pdf",
                "mime_type": "application/pdf",
                "document_type": "invoice",
                "description": "Clean standard multi-item cloud hosting invoice with tax & subtotal",
                "test_tags": ["standard", "cloud_hosting", "multi_item", "tax_subtotal", "tier1", "tier4"],
            },
            "raw_extraction": {
                "vendor_name": {"value": "Amazon Web Services Inc.", "confidence": 0.99, "raw_text": "Amazon Web Services Inc."},
                "vendor_address": {"value": "410 Terry Ave N, Seattle, WA 98109, USA", "confidence": 0.95, "raw_text": "410 Terry Ave N, Seattle, WA 98109, USA"},
                "customer_name": {"value": "Contoso Global Enterprises", "confidence": 0.96, "raw_text": "Contoso Global Enterprises"},
                "invoice_id": {"value": "INV-AWS-2026-0881", "confidence": 0.98, "raw_text": "INV-AWS-2026-0881"},
                "invoice_date": {"value": "2026-08-01", "confidence": 0.99, "raw_text": "2026-08-01"},
                "due_date": {"value": "2026-08-31", "confidence": 0.97, "raw_text": "2026-08-31"},
                "currency": {"value": "USD", "symbol": "$", "confidence": 0.99, "raw_text": "$"},
                "subtotal": {"value": 1320.50, "confidence": 0.98, "raw_text": "$1,320.50"},
                "total_tax": {"value": 100.00, "confidence": 0.98, "raw_text": "$100.00"},
                "invoice_total": {"value": 1420.50, "confidence": 0.99, "raw_text": "$1,420.50"},
                "amount_due": {"value": 1420.50, "confidence": 0.98, "raw_text": "$1,420.50"},
                "line_items": [
                    {
                        "description": "Amazon Elastic Compute Cloud (EC2) - Production Instances",
                        "quantity": 1.0,
                        "unit_price": 850.00,
                        "amount": 850.00,
                        "confidence": 0.98,
                    },
                    {
                        "description": "Amazon Simple Storage Service (S3) - Standard Storage",
                        "quantity": 1.0,
                        "unit_price": 220.50,
                        "amount": 220.50,
                        "confidence": 0.97,
                    },
                    {
                        "description": "AWS Direct Connect & Regional Data Transfer",
                        "quantity": 1.0,
                        "unit_price": 250.00,
                        "amount": 250.00,
                        "confidence": 0.98,
                    },
                ],
            },
            "normalized_expected": {
                "vendor_raw": "Amazon Web Services Inc.",
                "vendor_canonical": "Amazon Web Services",
                "vendor_id": "VEND-AWS-001",
                "vendor_match_score": 95.0,
                "is_known_vendor": True,
                "invoice_number": "INV-AWS-2026-0881",
                "invoice_date": "2026-08-01",
                "due_date": "2026-08-31",
                "currency_raw": "$",
                "currency_iso": "USD",
                "subtotal": 1320.50,
                "tax_amount": 100.00,
                "total_amount": 1420.50,
                "amount_due": 1420.50,
                "spend_category": "Cloud Services",
                "line_items": [
                    {
                        "item_id": "item_1",
                        "description": "Amazon Elastic Compute Cloud (EC2) - Production Instances",
                        "quantity": 1.0,
                        "unit_price": 850.00,
                        "total_price": 850.00,
                        "category": "Cloud Services",
                    },
                    {
                        "item_id": "item_2",
                        "description": "Amazon Simple Storage Service (S3) - Standard Storage",
                        "quantity": 1.0,
                        "unit_price": 220.50,
                        "total_price": 220.50,
                        "category": "Cloud Services",
                    },
                    {
                        "item_id": "item_3",
                        "description": "AWS Direct Connect & Regional Data Transfer",
                        "quantity": 1.0,
                        "unit_price": 250.00,
                        "total_price": 250.00,
                        "category": "Cloud Services",
                    },
                ],
            },
            "expected_flags": {
                "is_duplicate": False,
                "duplicate_of_id": None,
                "duplicate_reason": None,
                "duplicate_match_details": None,
                "has_anomalies": False,
                "anomaly_flags": [],
                "risk_score": 0.0,
            },
            "test_assertions": {
                "min_vendor_match_score": 85.0,
                "exact_canonical_vendor": "Amazon Web Services",
                "exact_currency_iso": "USD",
                "exact_invoice_date": "2026-08-01",
                "exact_total_amount": 1420.50,
                "exact_spend_category": "Cloud Services",
                "min_line_items_count": 3,
                "is_duplicate": False,
                "has_anomalies": False,
                "expected_anomaly_types": [],
            },
        },
    },

    "INV-002": {
        "stem": "inv_002_typo_vendor_msft",
        "file_ext": ".pdf",
        "doc_type_builder": "pdf",
        "pdf_params": {
            "vendor_name": "Microsft Corp Ireland",
            "vendor_address": ["One Microsoft Place", "South County Business Park, Leopardstown", "Dublin 18, Ireland", "VAT Reg: IE9578122K"],
            "invoice_id": "MSFT-9842103",
            "invoice_date": "2026-08-03",
            "due_date": "2026-09-02",
            "customer_name": "Contoso Global Enterprises",
            "customer_address": ["100 Enterprise Way, Suite 400", "Austin, TX 78701, USA"],
            "currency_symbol": "$",
            "line_items": [
                {
                    "description": "Microsoft 365 E5 Enterprise License (Monthly Subscription)",
                    "quantity": 10.0,
                    "unit_price": 35.00,
                    "amount": 350.00,
                },
            ],
            "subtotal": 350.00,
            "tax_amount": 0.00,
            "total_amount": 350.00,
            "tax_label": "VAT / Sales Tax",
            "notes": "Payment received via Enterprise Direct Debit agreement.",
            "po_number": "PO-99144",
            "theme_color_hex": "#0078D4",
        },
        "ground_truth": {
            "meta": {
                "fixture_id": "INV-002",
                "filename": "inv_002_typo_vendor_msft.pdf",
                "file_format": "pdf",
                "mime_type": "application/pdf",
                "document_type": "invoice",
                "description": "Noisy vendor string with typo & regional entity variation",
                "test_tags": ["fuzzy_vendor", "typo", "saas", "tier1", "tier3"],
            },
            "raw_extraction": {
                "vendor_name": {"value": "Microsft Corp Ireland", "confidence": 0.92, "raw_text": "Microsft Corp Ireland"},
                "vendor_address": {"value": "One Microsoft Place, Leopardstown, Dublin 18, Ireland", "confidence": 0.93, "raw_text": "One Microsoft Place, Leopardstown, Dublin 18, Ireland"},
                "customer_name": {"value": "Contoso Global Enterprises", "confidence": 0.95, "raw_text": "Contoso Global Enterprises"},
                "invoice_id": {"value": "MSFT-9842103", "confidence": 0.97, "raw_text": "MSFT-9842103"},
                "invoice_date": {"value": "2026-08-03", "confidence": 0.96, "raw_text": "2026-08-03"},
                "due_date": {"value": "2026-09-02", "confidence": 0.95, "raw_text": "2026-09-02"},
                "currency": {"value": "USD", "symbol": "$", "confidence": 0.98, "raw_text": "$"},
                "subtotal": {"value": 350.00, "confidence": 0.97, "raw_text": "$350.00"},
                "total_tax": {"value": 0.00, "confidence": 0.95, "raw_text": "$0.00"},
                "invoice_total": {"value": 350.00, "confidence": 0.98, "raw_text": "$350.00"},
                "amount_due": {"value": 350.00, "confidence": 0.97, "raw_text": "$350.00"},
                "line_items": [
                    {
                        "description": "Microsoft 365 E5 Enterprise License (Monthly Subscription)",
                        "quantity": 10.0,
                        "unit_price": 35.00,
                        "amount": 350.00,
                        "confidence": 0.96,
                    }
                ],
            },
            "normalized_expected": {
                "vendor_raw": "Microsft Corp Ireland",
                "vendor_canonical": "Microsoft Corporation",
                "vendor_id": "VEND-MSFT-001",
                "vendor_match_score": 86.5,
                "is_known_vendor": True,
                "invoice_number": "MSFT-9842103",
                "invoice_date": "2026-08-03",
                "due_date": "2026-09-02",
                "currency_raw": "$",
                "currency_iso": "USD",
                "subtotal": 350.00,
                "tax_amount": 0.00,
                "total_amount": 350.00,
                "amount_due": 350.00,
                "spend_category": "Software Subscriptions",
                "line_items": [
                    {
                        "item_id": "item_1",
                        "description": "Microsoft 365 E5 Enterprise License (Monthly Subscription)",
                        "quantity": 10.0,
                        "unit_price": 35.00,
                        "total_price": 350.00,
                        "category": "Software Subscriptions",
                    }
                ],
            },
            "expected_flags": {
                "is_duplicate": False,
                "duplicate_of_id": None,
                "duplicate_reason": None,
                "duplicate_match_details": None,
                "has_anomalies": False,
                "anomaly_flags": [],
                "risk_score": 0.0,
            },
            "test_assertions": {
                "min_vendor_match_score": 85.0,
                "exact_canonical_vendor": "Microsoft Corporation",
                "exact_currency_iso": "USD",
                "exact_invoice_date": "2026-08-03",
                "exact_total_amount": 350.00,
                "exact_spend_category": "Software Subscriptions",
                "min_line_items_count": 1,
                "is_duplicate": False,
                "has_anomalies": False,
                "expected_anomaly_types": [],
            },
        },
    },

    "INV-003": {
        "stem": "inv_003_multicurrency_eur",
        "file_ext": ".pdf",
        "doc_type_builder": "pdf",
        "pdf_params": {
            "vendor_name": "Google Ireland Limited",
            "vendor_address": ["Gordon House, Barrow Street", "Dublin 4, Ireland", "VAT: IE6388047V"],
            "invoice_id": "GCP-EU-2026-771",
            "invoice_date": "05/08/2026",
            "due_date": "04/09/2026",
            "customer_name": "Contoso European Branch B.V.",
            "customer_address": ["Keizersgracht 421", "1016 EK Amsterdam, Netherlands", "VAT: NL884210944B01"],
            "currency_symbol": "€",
            "line_items": [
                {
                    "description": "Google Cloud Platform - Compute Engine n2-standard-8",
                    "quantity": 1.0,
                    "unit_price": 1800.00,
                    "amount": 1800.00,
                },
                {
                    "description": "Google Cloud Storage - Multi-Regional EU",
                    "quantity": 1.0,
                    "unit_price": 180.75,
                    "amount": 180.75,
                },
            ],
            "subtotal": 1980.75,
            "tax_amount": 200.00,
            "total_amount": 2180.75,
            "tax_label": "BTW / VAT (10.10%)",
            "notes": "IBAN: IE29AIBK93115212345678 | BIC: AIBKIE2D | Reverse charge mechanism applies where indicated.",
            "po_number": "PO-EU-8812",
            "is_european_format": True,
            "theme_color_hex": "#4285F4",
        },
        "ground_truth": {
            "meta": {
                "fixture_id": "INV-003",
                "filename": "inv_003_multicurrency_eur.pdf",
                "file_format": "pdf",
                "mime_type": "application/pdf",
                "document_type": "invoice",
                "description": "European formatting (comma decimal, EUR currency symbol)",
                "test_tags": ["multicurrency", "eur", "comma_decimal", "vat", "tier1", "tier2"],
            },
            "raw_extraction": {
                "vendor_name": {"value": "Google Ireland Limited", "confidence": 0.98, "raw_text": "Google Ireland Limited"},
                "vendor_address": {"value": "Gordon House, Barrow Street, Dublin 4, Ireland", "confidence": 0.95, "raw_text": "Gordon House, Barrow Street, Dublin 4, Ireland"},
                "customer_name": {"value": "Contoso European Branch B.V.", "confidence": 0.96, "raw_text": "Contoso European Branch B.V."},
                "invoice_id": {"value": "GCP-EU-2026-771", "confidence": 0.98, "raw_text": "GCP-EU-2026-771"},
                "invoice_date": {"value": "2026-08-05", "confidence": 0.97, "raw_text": "05/08/2026"},
                "due_date": {"value": "2026-09-04", "confidence": 0.96, "raw_text": "04/09/2026"},
                "currency": {"value": "EUR", "symbol": "€", "confidence": 0.99, "raw_text": "€"},
                "subtotal": {"value": 1980.75, "confidence": 0.97, "raw_text": "1.980,75 €"},
                "total_tax": {"value": 200.00, "confidence": 0.96, "raw_text": "200,00 €"},
                "invoice_total": {"value": 2180.75, "confidence": 0.98, "raw_text": "2.180,75 €"},
                "amount_due": {"value": 2180.75, "confidence": 0.97, "raw_text": "2.180,75 €"},
                "line_items": [
                    {
                        "description": "Google Cloud Platform - Compute Engine n2-standard-8",
                        "quantity": 1.0,
                        "unit_price": 1800.00,
                        "amount": 1800.00,
                        "confidence": 0.97,
                    },
                    {
                        "description": "Google Cloud Storage - Multi-Regional EU",
                        "quantity": 1.0,
                        "unit_price": 180.75,
                        "amount": 180.75,
                        "confidence": 0.96,
                    },
                ],
            },
            "normalized_expected": {
                "vendor_raw": "Google Ireland Limited",
                "vendor_canonical": "Google LLC",
                "vendor_id": "VEND-GOOG-001",
                "vendor_match_score": 88.0,
                "is_known_vendor": True,
                "invoice_number": "GCP-EU-2026-771",
                "invoice_date": "2026-08-05",
                "due_date": "2026-09-04",
                "currency_raw": "€",
                "currency_iso": "EUR",
                "subtotal": 1980.75,
                "tax_amount": 200.00,
                "total_amount": 2180.75,
                "amount_due": 2180.75,
                "spend_category": "Cloud Services",
                "line_items": [
                    {
                        "item_id": "item_1",
                        "description": "Google Cloud Platform - Compute Engine n2-standard-8",
                        "quantity": 1.0,
                        "unit_price": 1800.00,
                        "total_price": 1800.00,
                        "category": "Cloud Services",
                    },
                    {
                        "item_id": "item_2",
                        "description": "Google Cloud Storage - Multi-Regional EU",
                        "quantity": 1.0,
                        "unit_price": 180.75,
                        "total_price": 180.75,
                        "category": "Cloud Services",
                    },
                ],
            },
            "expected_flags": {
                "is_duplicate": False,
                "duplicate_of_id": None,
                "duplicate_reason": None,
                "duplicate_match_details": None,
                "has_anomalies": False,
                "anomaly_flags": [],
                "risk_score": 0.0,
            },
            "test_assertions": {
                "min_vendor_match_score": 85.0,
                "exact_canonical_vendor": "Google LLC",
                "exact_currency_iso": "EUR",
                "exact_invoice_date": "2026-08-05",
                "exact_total_amount": 2180.75,
                "exact_spend_category": "Cloud Services",
                "min_line_items_count": 2,
                "is_duplicate": False,
                "has_anomalies": False,
                "expected_anomaly_types": [],
            },
        },
    },

    "INV-004": {
        "stem": "inv_004_thermal_receipt_uber",
        "file_ext": ".png",
        "doc_type_builder": "png_thermal",
        "png_params": {
            "vendor_header": "UBER *TRIP HELP.UBER",
            "vendor_sub": "Uber Technologies, Inc. - San Francisco, CA",
            "receipt_id": "UBER-TRIP-883921",
            "date_str": "2026-08-07 14:23 PST",
            "rider_name": "Contoso Employee (Alex M.)",
            "line_items": [
                {
                    "description": "UberX Trip - SFO Airport to Downtown Hotel",
                    "quantity": 1.0,
                    "unit_price": 35.00,
                    "amount": 35.00,
                },
                {
                    "description": "Airport Surcharge & Local Regulatory Fee",
                    "quantity": 1.0,
                    "unit_price": 2.80,
                    "amount": 2.80,
                },
                {
                    "description": "Driver Gratuity / Tip",
                    "quantity": 1.0,
                    "unit_price": 5.00,
                    "amount": 5.00,
                },
            ],
            "subtotal": 37.80,
            "tax_amount": 0.00,
            "total_amount": 42.80,
        },
        "ground_truth": {
            "meta": {
                "fixture_id": "INV-004",
                "filename": "inv_004_thermal_receipt_uber.png",
                "file_format": "png",
                "mime_type": "image/png",
                "document_type": "receipt",
                "description": "PNG thermal receipt image, ride-share category, informal layout",
                "test_tags": ["receipt", "png_image", "rideshare", "thermal_layout", "tier1", "tier3"],
            },
            "raw_extraction": {
                "vendor_name": {"value": "UBER *TRIP HELP.UBER", "confidence": 0.94, "raw_text": "UBER *TRIP HELP.UBER"},
                "vendor_address": {"value": "1515 3rd St, San Francisco, CA 94158", "confidence": 0.91, "raw_text": "1515 3rd St, San Francisco, CA 94158"},
                "customer_name": {"value": "Contoso Employee", "confidence": 0.90, "raw_text": "Contoso Employee"},
                "invoice_id": {"value": "UBER-TRIP-883921", "confidence": 0.96, "raw_text": "UBER-TRIP-883921"},
                "invoice_date": {"value": "2026-08-07", "confidence": 0.97, "raw_text": "2026-08-07 14:23 PST"},
                "due_date": {"value": "2026-08-07", "confidence": 0.95, "raw_text": "2026-08-07"},
                "currency": {"value": "USD", "symbol": "$", "confidence": 0.98, "raw_text": "$"},
                "subtotal": {"value": 37.80, "confidence": 0.95, "raw_text": "$37.80"},
                "total_tax": {"value": 0.00, "confidence": 0.92, "raw_text": "$0.00"},
                "invoice_total": {"value": 42.80, "confidence": 0.98, "raw_text": "$42.80"},
                "amount_due": {"value": 42.80, "confidence": 0.97, "raw_text": "$42.80"},
                "line_items": [
                    {
                        "description": "UberX Trip - SFO Airport to Downtown Hotel",
                        "quantity": 1.0,
                        "unit_price": 35.00,
                        "amount": 35.00,
                        "confidence": 0.95,
                    },
                    {
                        "description": "Airport Surcharge & Local Regulatory Fee",
                        "quantity": 1.0,
                        "unit_price": 2.80,
                        "amount": 2.80,
                        "confidence": 0.94,
                    },
                    {
                        "description": "Driver Gratuity / Tip",
                        "quantity": 1.0,
                        "unit_price": 5.00,
                        "amount": 5.00,
                        "confidence": 0.93,
                    },
                ],
            },
            "normalized_expected": {
                "vendor_raw": "UBER *TRIP HELP.UBER",
                "vendor_canonical": "Uber Technologies",
                "vendor_id": "VEND-UBER-001",
                "vendor_match_score": 78.5,
                "is_known_vendor": True,
                "invoice_number": "UBER-TRIP-883921",
                "invoice_date": "2026-08-07",
                "due_date": "2026-08-07",
                "currency_raw": "$",
                "currency_iso": "USD",
                "subtotal": 37.80,
                "tax_amount": 0.00,
                "total_amount": 42.80,
                "amount_due": 42.80,
                "spend_category": "Travel & Transportation",
                "line_items": [
                    {
                        "item_id": "item_1",
                        "description": "UberX Trip - SFO Airport to Downtown Hotel",
                        "quantity": 1.0,
                        "unit_price": 35.00,
                        "total_price": 35.00,
                        "category": "Travel & Transportation",
                    },
                    {
                        "item_id": "item_2",
                        "description": "Airport Surcharge & Local Regulatory Fee",
                        "quantity": 1.0,
                        "unit_price": 2.80,
                        "total_price": 2.80,
                        "category": "Travel & Transportation",
                    },
                    {
                        "item_id": "item_3",
                        "description": "Driver Gratuity / Tip",
                        "quantity": 1.0,
                        "unit_price": 5.00,
                        "total_price": 5.00,
                        "category": "Travel & Transportation",
                    },
                ],
            },
            "expected_flags": {
                "is_duplicate": False,
                "duplicate_of_id": None,
                "duplicate_reason": None,
                "duplicate_match_details": None,
                "has_anomalies": False,
                "anomaly_flags": [],
                "risk_score": 0.0,
            },
            "test_assertions": {
                "min_vendor_match_score": 75.0,
                "exact_canonical_vendor": "Uber Technologies",
                "exact_currency_iso": "USD",
                "exact_invoice_date": "2026-08-07",
                "exact_total_amount": 42.80,
                "exact_spend_category": "Travel & Transportation",
                "min_line_items_count": 3,
                "is_duplicate": False,
                "has_anomalies": False,
                "expected_anomaly_types": [],
            },
        },
    },

    "INV-005": {
        "stem": "inv_005_acme_dup_original",
        "file_ext": ".pdf",
        "doc_type_builder": "pdf",
        "pdf_params": {
            "vendor_name": "Acme Corp Ltd",
            "vendor_address": ["123 Industrial Parkway", "Springfield, IL 62701, USA", "Tax ID: US-93-8819201"],
            "invoice_id": "ACM-2026-0501",
            "invoice_date": "2026-08-10",
            "due_date": "2026-09-09",
            "customer_name": "Contoso Global Enterprises",
            "customer_address": ["100 Enterprise Way, Suite 400", "Austin, TX 78701, USA"],
            "currency_symbol": "$",
            "line_items": [
                {
                    "description": "Industrial Precision Heavy-Duty Widget Model A",
                    "quantity": 5.0,
                    "unit_price": 100.00,
                    "amount": 500.00,
                },
            ],
            "subtotal": 500.00,
            "tax_amount": 0.00,
            "total_amount": 500.00,
            "tax_label": "Tax",
            "notes": "Terms: Net 30 days. Remit payment to Acme Corp Operating Account.",
            "po_number": "PO-99201",
            "theme_color_hex": "#800000",
        },
        "ground_truth": {
            "meta": {
                "fixture_id": "INV-005",
                "filename": "inv_005_acme_dup_original.pdf",
                "file_format": "pdf",
                "mime_type": "application/pdf",
                "document_type": "invoice",
                "description": "Base original invoice for duplicate pair testing",
                "test_tags": ["duplicate_base", "acme", "office_supplies", "tier1", "tier2"],
            },
            "raw_extraction": {
                "vendor_name": {"value": "Acme Corp Ltd", "confidence": 0.98, "raw_text": "Acme Corp Ltd"},
                "vendor_address": {"value": "123 Industrial Parkway, Springfield, IL 62701", "confidence": 0.94, "raw_text": "123 Industrial Parkway, Springfield, IL 62701"},
                "customer_name": {"value": "Contoso Global Enterprises", "confidence": 0.96, "raw_text": "Contoso Global Enterprises"},
                "invoice_id": {"value": "ACM-2026-0501", "confidence": 0.98, "raw_text": "ACM-2026-0501"},
                "invoice_date": {"value": "2026-08-10", "confidence": 0.99, "raw_text": "2026-08-10"},
                "due_date": {"value": "2026-09-09", "confidence": 0.97, "raw_text": "2026-09-09"},
                "currency": {"value": "USD", "symbol": "$", "confidence": 0.99, "raw_text": "$"},
                "subtotal": {"value": 500.00, "confidence": 0.98, "raw_text": "$500.00"},
                "total_tax": {"value": 0.00, "confidence": 0.95, "raw_text": "$0.00"},
                "invoice_total": {"value": 500.00, "confidence": 0.99, "raw_text": "$500.00"},
                "amount_due": {"value": 500.00, "confidence": 0.98, "raw_text": "$500.00"},
                "line_items": [
                    {
                        "description": "Industrial Precision Heavy-Duty Widget Model A",
                        "quantity": 5.0,
                        "unit_price": 100.00,
                        "amount": 500.00,
                        "confidence": 0.98,
                    }
                ],
            },
            "normalized_expected": {
                "vendor_raw": "Acme Corp Ltd",
                "vendor_canonical": "Acme Corporation",
                "vendor_id": "VEND-ACME-001",
                "vendor_match_score": 91.0,
                "is_known_vendor": True,
                "invoice_number": "ACM-2026-0501",
                "invoice_date": "2026-08-10",
                "due_date": "2026-09-09",
                "currency_raw": "$",
                "currency_iso": "USD",
                "subtotal": 500.00,
                "tax_amount": 0.00,
                "total_amount": 500.00,
                "amount_due": 500.00,
                "spend_category": "Office Supplies & Equipment",
                "line_items": [
                    {
                        "item_id": "item_1",
                        "description": "Industrial Precision Heavy-Duty Widget Model A",
                        "quantity": 5.0,
                        "unit_price": 100.00,
                        "total_price": 500.00,
                        "category": "Office Supplies & Equipment",
                    }
                ],
            },
            "expected_flags": {
                "is_duplicate": False,
                "duplicate_of_id": None,
                "duplicate_reason": None,
                "duplicate_match_details": None,
                "has_anomalies": False,
                "anomaly_flags": [],
                "risk_score": 0.0,
            },
            "test_assertions": {
                "min_vendor_match_score": 85.0,
                "exact_canonical_vendor": "Acme Corporation",
                "exact_currency_iso": "USD",
                "exact_invoice_date": "2026-08-10",
                "exact_total_amount": 500.00,
                "exact_spend_category": "Office Supplies & Equipment",
                "min_line_items_count": 1,
                "is_duplicate": False,
                "has_anomalies": False,
                "expected_anomaly_types": [],
            },
        },
    },

    "INV-006": {
        "stem": "inv_006_acme_dup_positive",
        "file_ext": ".pdf",
        "doc_type_builder": "pdf",
        "pdf_params": {
            "vendor_name": "Acme Corporation LLC",
            "vendor_address": ["123 Industrial Parkway", "Springfield, IL 62701, USA", "Tax ID: US-93-8819201"],
            "invoice_id": "ACM-2026-0501-DUP",
            "invoice_date": "2026-08-13",
            "due_date": "2026-09-12",
            "customer_name": "Contoso Global Enterprises",
            "customer_address": ["100 Enterprise Way, Suite 400", "Austin, TX 78701, USA"],
            "currency_symbol": "$",
            "line_items": [
                {
                    "description": "Industrial Precision Heavy-Duty Widget Model A (Replacement Delivery)",
                    "quantity": 5.0,
                    "unit_price": 100.00,
                    "amount": 500.00,
                },
            ],
            "subtotal": 500.00,
            "tax_amount": 0.00,
            "total_amount": 500.00,
            "tax_label": "Tax",
            "notes": "DUPLICATE REPRINT / COPY - Original issued 2026-08-10.",
            "po_number": "PO-99201",
            "watermark_text": "DUPLICATE COPY / REPRINT",
            "theme_color_hex": "#800000",
        },
        "ground_truth": {
            "meta": {
                "fixture_id": "INV-006",
                "filename": "inv_006_acme_dup_positive.pdf",
                "file_format": "pdf",
                "mime_type": "application/pdf",
                "document_type": "invoice",
                "description": "Positive duplicate (+3 days from INV-005, same canonical vendor & amount)",
                "test_tags": ["duplicate_positive", "acme", "sliding_window_3d", "tier1", "tier2", "tier4"],
            },
            "raw_extraction": {
                "vendor_name": {"value": "Acme Corporation LLC", "confidence": 0.98, "raw_text": "Acme Corporation LLC"},
                "vendor_address": {"value": "123 Industrial Parkway, Springfield, IL 62701", "confidence": 0.94, "raw_text": "123 Industrial Parkway, Springfield, IL 62701"},
                "customer_name": {"value": "Contoso Global Enterprises", "confidence": 0.96, "raw_text": "Contoso Global Enterprises"},
                "invoice_id": {"value": "ACM-2026-0501-DUP", "confidence": 0.98, "raw_text": "ACM-2026-0501-DUP"},
                "invoice_date": {"value": "2026-08-13", "confidence": 0.99, "raw_text": "2026-08-13"},
                "due_date": {"value": "2026-09-12", "confidence": 0.97, "raw_text": "2026-09-12"},
                "currency": {"value": "USD", "symbol": "$", "confidence": 0.99, "raw_text": "$"},
                "subtotal": {"value": 500.00, "confidence": 0.98, "raw_text": "$500.00"},
                "total_tax": {"value": 0.00, "confidence": 0.95, "raw_text": "$0.00"},
                "invoice_total": {"value": 500.00, "confidence": 0.99, "raw_text": "$500.00"},
                "amount_due": {"value": 500.00, "confidence": 0.98, "raw_text": "$500.00"},
                "line_items": [
                    {
                        "description": "Industrial Precision Heavy-Duty Widget Model A (Replacement Delivery)",
                        "quantity": 5.0,
                        "unit_price": 100.00,
                        "amount": 500.00,
                        "confidence": 0.98,
                    }
                ],
            },
            "normalized_expected": {
                "vendor_raw": "Acme Corporation LLC",
                "vendor_canonical": "Acme Corporation",
                "vendor_id": "VEND-ACME-001",
                "vendor_match_score": 96.0,
                "is_known_vendor": True,
                "invoice_number": "ACM-2026-0501-DUP",
                "invoice_date": "2026-08-13",
                "due_date": "2026-09-12",
                "currency_raw": "$",
                "currency_iso": "USD",
                "subtotal": 500.00,
                "tax_amount": 0.00,
                "total_amount": 500.00,
                "amount_due": 500.00,
                "spend_category": "Office Supplies & Equipment",
                "line_items": [
                    {
                        "item_id": "item_1",
                        "description": "Industrial Precision Heavy-Duty Widget Model A (Replacement Delivery)",
                        "quantity": 5.0,
                        "unit_price": 100.00,
                        "total_price": 500.00,
                        "category": "Office Supplies & Equipment",
                    }
                ],
            },
            "expected_flags": {
                "is_duplicate": True,
                "duplicate_of_id": "INV-005",
                "duplicate_reason": "Duplicate detected: Matches existing invoice INV-005 with identical canonical vendor ('Acme Corporation') and amount ($500.00) within 7 days (date delta: 3 days).",
                "duplicate_match_details": {
                    "original_invoice_id": "INV-005",
                    "original_date": "2026-08-10",
                    "days_difference": 3,
                    "vendor_matched": "Acme Corporation",
                    "amount_matched": 500.00,
                },
                "has_anomalies": False,
                "anomaly_flags": [],
                "risk_score": 0.85,
            },
            "test_assertions": {
                "min_vendor_match_score": 85.0,
                "exact_canonical_vendor": "Acme Corporation",
                "exact_currency_iso": "USD",
                "exact_invoice_date": "2026-08-13",
                "exact_total_amount": 500.00,
                "exact_spend_category": "Office Supplies & Equipment",
                "min_line_items_count": 1,
                "is_duplicate": True,
                "has_anomalies": False,
                "expected_anomaly_types": [],
            },
        },
    },

    "INV-007": {
        "stem": "inv_007_acme_dup_negative",
        "file_ext": ".pdf",
        "doc_type_builder": "pdf",
        "pdf_params": {
            "vendor_name": "Acme Corporation",
            "vendor_address": ["123 Industrial Parkway", "Springfield, IL 62701, USA", "Tax ID: US-93-8819201"],
            "invoice_id": "ACM-2026-0618",
            "invoice_date": "2026-09-15",
            "due_date": "2026-10-15",
            "customer_name": "Contoso Global Enterprises",
            "customer_address": ["100 Enterprise Way, Suite 400", "Austin, TX 78701, USA"],
            "currency_symbol": "$",
            "line_items": [
                {
                    "description": "Industrial Precision Heavy-Duty Widget Model A (Monthly Standard Restock)",
                    "quantity": 5.0,
                    "unit_price": 100.00,
                    "amount": 500.00,
                },
            ],
            "subtotal": 500.00,
            "tax_amount": 0.00,
            "total_amount": 500.00,
            "tax_label": "Tax",
            "notes": "Regular monthly restock order for September 2026. Standard Net 30 terms.",
            "po_number": "PO-99380",
            "theme_color_hex": "#800000",
        },
        "ground_truth": {
            "meta": {
                "fixture_id": "INV-007",
                "filename": "inv_007_acme_dup_negative.pdf",
                "file_format": "pdf",
                "mime_type": "application/pdf",
                "document_type": "invoice",
                "description": "Negative duplicate (+36 days from INV-005, outside 7-day window)",
                "test_tags": ["duplicate_negative", "acme", "outside_window_36d", "tier1", "tier2"],
            },
            "raw_extraction": {
                "vendor_name": {"value": "Acme Corporation", "confidence": 0.99, "raw_text": "Acme Corporation"},
                "vendor_address": {"value": "123 Industrial Parkway, Springfield, IL 62701", "confidence": 0.95, "raw_text": "123 Industrial Parkway, Springfield, IL 62701"},
                "customer_name": {"value": "Contoso Global Enterprises", "confidence": 0.97, "raw_text": "Contoso Global Enterprises"},
                "invoice_id": {"value": "ACM-2026-0618", "confidence": 0.98, "raw_text": "ACM-2026-0618"},
                "invoice_date": {"value": "2026-09-15", "confidence": 0.99, "raw_text": "2026-09-15"},
                "due_date": {"value": "2026-10-15", "confidence": 0.97, "raw_text": "2026-10-15"},
                "currency": {"value": "USD", "symbol": "$", "confidence": 0.99, "raw_text": "$"},
                "subtotal": {"value": 500.00, "confidence": 0.98, "raw_text": "$500.00"},
                "total_tax": {"value": 0.00, "confidence": 0.95, "raw_text": "$0.00"},
                "invoice_total": {"value": 500.00, "confidence": 0.99, "raw_text": "$500.00"},
                "amount_due": {"value": 500.00, "confidence": 0.98, "raw_text": "$500.00"},
                "line_items": [
                    {
                        "description": "Industrial Precision Heavy-Duty Widget Model A (Monthly Standard Restock)",
                        "quantity": 5.0,
                        "unit_price": 100.00,
                        "amount": 500.00,
                        "confidence": 0.98,
                    }
                ],
            },
            "normalized_expected": {
                "vendor_raw": "Acme Corporation",
                "vendor_canonical": "Acme Corporation",
                "vendor_id": "VEND-ACME-001",
                "vendor_match_score": 100.0,
                "is_known_vendor": True,
                "invoice_number": "ACM-2026-0618",
                "invoice_date": "2026-09-15",
                "due_date": "2026-10-15",
                "currency_raw": "$",
                "currency_iso": "USD",
                "subtotal": 500.00,
                "tax_amount": 0.00,
                "total_amount": 500.00,
                "amount_due": 500.00,
                "spend_category": "Office Supplies & Equipment",
                "line_items": [
                    {
                        "item_id": "item_1",
                        "description": "Industrial Precision Heavy-Duty Widget Model A (Monthly Standard Restock)",
                        "quantity": 5.0,
                        "unit_price": 100.00,
                        "total_price": 500.00,
                        "category": "Office Supplies & Equipment",
                    }
                ],
            },
            "expected_flags": {
                "is_duplicate": False,
                "duplicate_of_id": None,
                "duplicate_reason": None,
                "duplicate_match_details": None,
                "has_anomalies": False,
                "anomaly_flags": [],
                "risk_score": 0.0,
            },
            "test_assertions": {
                "min_vendor_match_score": 85.0,
                "exact_canonical_vendor": "Acme Corporation",
                "exact_currency_iso": "USD",
                "exact_invoice_date": "2026-09-15",
                "exact_total_amount": 500.00,
                "exact_spend_category": "Office Supplies & Equipment",
                "min_line_items_count": 1,
                "is_duplicate": False,
                "has_anomalies": False,
                "expected_anomaly_types": [],
            },
        },
    },

    "INV-008": {
        "stem": "inv_008_extreme_anomaly",
        "file_ext": ".pdf",
        "doc_type_builder": "pdf",
        "pdf_params": {
            "vendor_name": "Delta Air Lines Inc",
            "vendor_address": ["1030 Delta Blvd", "Atlanta, GA 30354, USA", "Corporate Contract Division"],
            "invoice_id": "DAL-CHARTER-99012",
            "invoice_date": "2026-08-12",
            "due_date": "2026-08-26",
            "customer_name": "Contoso Global Enterprises",
            "customer_address": ["100 Enterprise Way, Suite 400", "Austin, TX 78701, USA"],
            "currency_symbol": "$",
            "line_items": [
                {
                    "description": "Annual Corporate Executive Jet Fleet Charter Agreement (Global Operations)",
                    "quantity": 1.0,
                    "unit_price": 1200000.00,
                    "amount": 1200000.00,
                },
            ],
            "subtotal": 1200000.00,
            "tax_amount": 50000.00,
            "total_amount": 1250000.00,
            "tax_label": "Federal Aviation & Transportation Taxes",
            "notes": "Master Aviation Services Agreement Ref: DAL-EXEC-2026. Electronic Wire Transfer Required.",
            "po_number": "PO-EXEC-001",
            "theme_color_hex": "#002244",
        },
        "ground_truth": {
            "meta": {
                "fixture_id": "INV-008",
                "filename": "inv_008_extreme_anomaly.pdf",
                "file_format": "pdf",
                "mime_type": "application/pdf",
                "document_type": "invoice",
                "description": "Extreme amount anomaly (> $50,000 statistical outlier threshold)",
                "test_tags": ["anomaly", "extreme_amount", "outlier", "critical_risk", "tier1", "tier2", "tier3"],
            },
            "raw_extraction": {
                "vendor_name": {"value": "Delta Air Lines Inc", "confidence": 0.98, "raw_text": "Delta Air Lines Inc"},
                "vendor_address": {"value": "1030 Delta Blvd, Atlanta, GA 30354", "confidence": 0.95, "raw_text": "1030 Delta Blvd, Atlanta, GA 30354"},
                "customer_name": {"value": "Contoso Global Enterprises", "confidence": 0.97, "raw_text": "Contoso Global Enterprises"},
                "invoice_id": {"value": "DAL-CHARTER-99012", "confidence": 0.98, "raw_text": "DAL-CHARTER-99012"},
                "invoice_date": {"value": "2026-08-12", "confidence": 0.99, "raw_text": "2026-08-12"},
                "due_date": {"value": "2026-08-26", "confidence": 0.96, "raw_text": "2026-08-26"},
                "currency": {"value": "USD", "symbol": "$", "confidence": 0.99, "raw_text": "$"},
                "subtotal": {"value": 1200000.00, "confidence": 0.98, "raw_text": "$1,200,000.00"},
                "total_tax": {"value": 50000.00, "confidence": 0.97, "raw_text": "$50,000.00"},
                "invoice_total": {"value": 1250000.00, "confidence": 0.99, "raw_text": "$1,250,000.00"},
                "amount_due": {"value": 1250000.00, "confidence": 0.98, "raw_text": "$1,250,000.00"},
                "line_items": [
                    {
                        "description": "Annual Corporate Executive Jet Fleet Charter Agreement (Global Operations)",
                        "quantity": 1.0,
                        "unit_price": 1200000.00,
                        "amount": 1200000.00,
                        "confidence": 0.98,
                    }
                ],
            },
            "normalized_expected": {
                "vendor_raw": "Delta Air Lines Inc",
                "vendor_canonical": "Delta Air Lines",
                "vendor_id": "VEND-DAL-001",
                "vendor_match_score": 95.0,
                "is_known_vendor": True,
                "invoice_number": "DAL-CHARTER-99012",
                "invoice_date": "2026-08-12",
                "due_date": "2026-08-26",
                "currency_raw": "$",
                "currency_iso": "USD",
                "subtotal": 1200000.00,
                "tax_amount": 50000.00,
                "total_amount": 1250000.00,
                "amount_due": 1250000.00,
                "spend_category": "Travel & Transportation",
                "line_items": [
                    {
                        "item_id": "item_1",
                        "description": "Annual Corporate Executive Jet Fleet Charter Agreement (Global Operations)",
                        "quantity": 1.0,
                        "unit_price": 1200000.00,
                        "total_price": 1200000.00,
                        "category": "Travel & Transportation",
                    }
                ],
            },
            "expected_flags": {
                "is_duplicate": False,
                "duplicate_of_id": None,
                "duplicate_reason": None,
                "duplicate_match_details": None,
                "has_anomalies": True,
                "anomaly_flags": [
                    {
                        "anomaly_type": "extreme_amount",
                        "severity": "CRITICAL",
                        "description": "Total invoice amount $1,250,000.00 exceeds the statistical outlier limit of $50,000.00.",
                        "details": {
                            "threshold": 50000.00,
                            "total_amount": 1250000.00,
                            "ratio_to_threshold": 25.0,
                        },
                    }
                ],
                "risk_score": 0.95,
            },
            "test_assertions": {
                "min_vendor_match_score": 85.0,
                "exact_canonical_vendor": "Delta Air Lines",
                "exact_currency_iso": "USD",
                "exact_invoice_date": "2026-08-12",
                "exact_total_amount": 1250000.00,
                "exact_spend_category": "Travel & Transportation",
                "min_line_items_count": 1,
                "is_duplicate": False,
                "has_anomalies": True,
                "expected_anomaly_types": ["extreme_amount"],
            },
        },
    },

    "INV-009": {
        "stem": "inv_009_unrecognized_vendor",
        "file_ext": ".jpg",
        "doc_type_builder": "jpg_diner",
        "jpg_params": {
            "restaurant_name": "Luigi's Pizza & Catering",
            "address_lines": ["88 Little Italy Way", "New York, NY 10013", "Tel: (212) 555-0199"],
            "order_id": "REC-LUI-44810",
            "table_no": "14",
            "server_name": "Sarah J.",
            "date_time_str": "08/14/2026 19:45",
            "line_items": [
                {
                    "description": "Catering Large Specialty Pizzas (3x Assorted)",
                    "quantity": 3.0,
                    "unit_price": 23.00,
                    "amount": 69.00,
                },
                {
                    "description": "Beverages - 2L Soda Bottles & Sparkling Water",
                    "quantity": 3.0,
                    "unit_price": 3.50,
                    "amount": 10.50,
                },
            ],
            "subtotal": 79.50,
            "tax": 6.00,
            "total": 85.50,
        },
        "ground_truth": {
            "meta": {
                "fixture_id": "INV-009",
                "filename": "inv_009_unrecognized_vendor.jpg",
                "file_format": "jpg",
                "mime_type": "image/jpeg",
                "document_type": "receipt",
                "description": "JPG photo receipt from unknown vendor (< 70% fuzzy match threshold)",
                "test_tags": ["anomaly", "unrecognized_vendor", "catering", "jpg_image", "tier1", "tier3"],
            },
            "raw_extraction": {
                "vendor_name": {"value": "Luigi's Pizza & Catering", "confidence": 0.91, "raw_text": "Luigi's Pizza & Catering"},
                "vendor_address": {"value": "88 Little Italy Way, New York, NY 10013", "confidence": 0.89, "raw_text": "88 Little Italy Way, New York, NY 10013"},
                "customer_name": {"value": "Contoso Engineering Team", "confidence": 0.92, "raw_text": "Contoso Engineering Team"},
                "invoice_id": {"value": "REC-LUI-44810", "confidence": 0.95, "raw_text": "REC-LUI-44810"},
                "invoice_date": {"value": "2026-08-14", "confidence": 0.96, "raw_text": "2026-08-14"},
                "due_date": {"value": "2026-08-14", "confidence": 0.95, "raw_text": "2026-08-14"},
                "currency": {"value": "USD", "symbol": "$", "confidence": 0.98, "raw_text": "$"},
                "subtotal": {"value": 79.50, "confidence": 0.94, "raw_text": "$79.50"},
                "total_tax": {"value": 6.00, "confidence": 0.93, "raw_text": "$6.00"},
                "invoice_total": {"value": 85.50, "confidence": 0.97, "raw_text": "$85.50"},
                "amount_due": {"value": 85.50, "confidence": 0.96, "raw_text": "$85.50"},
                "line_items": [
                    {
                        "description": "Catering Large Specialty Pizzas (3x Assorted)",
                        "quantity": 3.0,
                        "unit_price": 23.00,
                        "amount": 69.00,
                        "confidence": 0.93,
                    },
                    {
                        "description": "Beverages - 2L Soda Bottles & Sparkling Water",
                        "quantity": 3.0,
                        "unit_price": 3.50,
                        "amount": 10.50,
                        "confidence": 0.92,
                    },
                ],
            },
            "normalized_expected": {
                "vendor_raw": "Luigi's Pizza & Catering",
                "vendor_canonical": "Luigi's Pizza & Catering",
                "vendor_id": None,
                "vendor_match_score": 32.5,
                "is_known_vendor": False,
                "invoice_number": "REC-LUI-44810",
                "invoice_date": "2026-08-14",
                "due_date": "2026-08-14",
                "currency_raw": "$",
                "currency_iso": "USD",
                "subtotal": 79.50,
                "tax_amount": 6.00,
                "total_amount": 85.50,
                "amount_due": 85.50,
                "spend_category": "Meals & Entertainment",
                "line_items": [
                    {
                        "item_id": "item_1",
                        "description": "Catering Large Specialty Pizzas (3x Assorted)",
                        "quantity": 3.0,
                        "unit_price": 23.00,
                        "total_price": 69.00,
                        "category": "Meals & Entertainment",
                    },
                    {
                        "item_id": "item_2",
                        "description": "Beverages - 2L Soda Bottles & Sparkling Water",
                        "quantity": 3.0,
                        "unit_price": 3.50,
                        "total_price": 10.50,
                        "category": "Meals & Entertainment",
                    },
                ],
            },
            "expected_flags": {
                "is_duplicate": False,
                "duplicate_of_id": None,
                "duplicate_reason": None,
                "duplicate_match_details": None,
                "has_anomalies": True,
                "anomaly_flags": [
                    {
                        "anomaly_type": "unrecognized_vendor",
                        "severity": "WARNING",
                        "description": "Vendor 'Luigi's Pizza & Catering' does not match any approved vendor in the known vendors database (best match score: 32.5% < 70.0%).",
                        "details": {
                            "vendor_raw": "Luigi's Pizza & Catering",
                            "best_match": None,
                            "match_score": 32.5,
                            "threshold": 70.0,
                        },
                    }
                ],
                "risk_score": 0.50,
            },
            "test_assertions": {
                "min_vendor_match_score": 0.0,
                "exact_canonical_vendor": "Luigi's Pizza & Catering",
                "exact_currency_iso": "USD",
                "exact_invoice_date": "2026-08-14",
                "exact_total_amount": 85.50,
                "exact_spend_category": "Meals & Entertainment",
                "min_line_items_count": 2,
                "is_duplicate": False,
                "has_anomalies": True,
                "expected_anomaly_types": ["unrecognized_vendor"],
            },
        },
    },

    "INV-010": {
        "stem": "inv_010_jpy_zero_decimal",
        "file_ext": ".pdf",
        "doc_type_builder": "pdf",
        "pdf_params": {
            "vendor_name": "Slack Technologies LLC",
            "vendor_address": ["500 Howard St, San Francisco, CA 94105, USA", "Tokyo Branch: Roppongi Hills Mori Tower 18F", "Minato-ku, Tokyo 106-6118, Japan"],
            "invoice_id": "SLACK-INV-2026-904",
            "invoice_date": "2026-08-15",
            "due_date": "2026-09-14",
            "customer_name": "Contoso Japan K.K.",
            "customer_address": ["Roppongi Hills Mori Tower 28F", "Minato-ku, Tokyo 106-6128, Japan"],
            "currency_symbol": "¥",
            "line_items": [
                {
                    "description": "Slack Enterprise Grid Subscription (10 user seats @ ¥15,000/seat)",
                    "quantity": 10.0,
                    "unit_price": 15000.0,
                    "amount": 150000.0,
                },
            ],
            "subtotal": 150000.0,
            "tax_amount": 0.0,
            "total_amount": 150000.0,
            "tax_label": "Japanese Consumption Tax (JCT)",
            "notes": "Bank Transfer: Mitsubishi UFJ Bank, Roppongi Branch, Account: 7781029.",
            "po_number": "PO-JP-881",
            "is_zero_decimal": True,
            "theme_color_hex": "#4A154B",
        },
        "ground_truth": {
            "meta": {
                "fixture_id": "INV-010",
                "filename": "inv_010_jpy_zero_decimal.pdf",
                "file_format": "pdf",
                "mime_type": "application/pdf",
                "document_type": "invoice",
                "description": "Zero-decimal currency formatting (JPY), line items with software subscription",
                "test_tags": ["zero_decimal", "jpy", "software_subscription", "tier1", "tier2"],
            },
            "raw_extraction": {
                "vendor_name": {"value": "Slack Technologies LLC", "confidence": 0.98, "raw_text": "Slack Technologies LLC"},
                "vendor_address": {"value": "500 Howard St, San Francisco, CA 94105", "confidence": 0.95, "raw_text": "500 Howard St, San Francisco, CA 94105"},
                "customer_name": {"value": "Contoso Japan K.K.", "confidence": 0.96, "raw_text": "Contoso Japan K.K."},
                "invoice_id": {"value": "SLACK-INV-2026-904", "confidence": 0.98, "raw_text": "SLACK-INV-2026-904"},
                "invoice_date": {"value": "2026-08-15", "confidence": 0.99, "raw_text": "2026-08-15"},
                "due_date": {"value": "2026-09-14", "confidence": 0.97, "raw_text": "2026-09-14"},
                "currency": {"value": "JPY", "symbol": "¥", "confidence": 0.99, "raw_text": "¥"},
                "subtotal": {"value": 150000.0, "confidence": 0.98, "raw_text": "¥150,000"},
                "total_tax": {"value": 0.0, "confidence": 0.95, "raw_text": "¥0"},
                "invoice_total": {"value": 150000.0, "confidence": 0.99, "raw_text": "¥150,000"},
                "amount_due": {"value": 150000.0, "confidence": 0.98, "raw_text": "¥150,000"},
                "line_items": [
                    {
                        "description": "Slack Enterprise Grid Subscription (10 user seats @ ¥15,000/seat)",
                        "quantity": 10.0,
                        "unit_price": 15000.0,
                        "amount": 150000.0,
                        "confidence": 0.98,
                    }
                ],
            },
            "normalized_expected": {
                "vendor_raw": "Slack Technologies LLC",
                "vendor_canonical": "Slack Technologies",
                "vendor_id": "VEND-SLACK-001",
                "vendor_match_score": 95.0,
                "is_known_vendor": True,
                "invoice_number": "SLACK-INV-2026-904",
                "invoice_date": "2026-08-15",
                "due_date": "2026-09-14",
                "currency_raw": "¥",
                "currency_iso": "JPY",
                "subtotal": 150000.0,
                "tax_amount": 0.0,
                "total_amount": 150000.0,
                "amount_due": 150000.0,
                "spend_category": "Software Subscriptions",
                "line_items": [
                    {
                        "item_id": "item_1",
                        "description": "Slack Enterprise Grid Subscription (10 user seats @ ¥15,000/seat)",
                        "quantity": 10.0,
                        "unit_price": 15000.0,
                        "total_price": 150000.0,
                        "category": "Software Subscriptions",
                    }
                ],
            },
            "expected_flags": {
                "is_duplicate": False,
                "duplicate_of_id": None,
                "duplicate_reason": None,
                "duplicate_match_details": None,
                "has_anomalies": False,
                "anomaly_flags": [],
                "risk_score": 0.0,
            },
            "test_assertions": {
                "min_vendor_match_score": 85.0,
                "exact_canonical_vendor": "Slack Technologies",
                "exact_currency_iso": "JPY",
                "exact_invoice_date": "2026-08-15",
                "exact_total_amount": 150000.0,
                "exact_spend_category": "Software Subscriptions",
                "min_line_items_count": 1,
                "is_duplicate": False,
                "has_anomalies": False,
                "expected_anomaly_types": [],
            },
        },
    },
}


# ==============================================================================
# 4. Master Generator & Manifest Compiler
# ==============================================================================

def calculate_sha256(file_path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def generate_all_fixtures(output_dir: Path) -> dict[str, Any]:
    """Generates all 10 document files, 10 ground-truth JSONs, and manifest.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, Any]] = []

    print("\n========================================================")
    print("  Generating Document Intelligence Fixtures & Ground Truth")
    print(f"  Target Output Directory: {output_dir.resolve()}")
    print("========================================================\n")

    for fixture_id, config in FIXTURES_CONFIG.items():
        stem = config["stem"]
        ext = config["file_ext"]
        doc_filename = f"{stem}{ext}"
        json_filename = f"{stem}.json"

        doc_path = output_dir / doc_filename
        json_path = output_dir / json_filename

        # 1. Build Physical Document
        builder_type = config["doc_type_builder"]
        if builder_type == "pdf":
            create_styled_pdf_invoice(output_path=doc_path, **config["pdf_params"])
        elif builder_type == "png_thermal":
            create_thermal_receipt_png(output_path=doc_path, **config["png_params"])
        elif builder_type == "jpg_diner":
            create_restaurant_receipt_jpg(output_path=doc_path, **config["jpg_params"])
        else:
            raise ValueError(f"Unknown builder type: {builder_type}")

        # 2. Compute Hashes & Size
        file_sha256 = calculate_sha256(doc_path)
        file_size = os.path.getsize(doc_path)

        # 3. Write Ground Truth JSON (with file_sha256 included in meta)
        gt_data = config["ground_truth"].copy()
        gt_data["meta"]["file_sha256"] = file_sha256
        gt_data["meta"]["file_size_bytes"] = file_size

        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(gt_data, jf, indent=2, ensure_ascii=False)

        # 4. Add Manifest Entry
        manifest_entries.append({
            "fixture_id": fixture_id,
            "filename": doc_filename,
            "ground_truth_json": json_filename,
            "file_format": config["file_ext"].lstrip("."),
            "mime_type": gt_data["meta"]["mime_type"],
            "sha256": file_sha256,
            "size_bytes": file_size,
            "raw_vendor": gt_data["normalized_expected"]["vendor_raw"],
            "canonical_vendor": gt_data["normalized_expected"]["vendor_canonical"],
            "total_amount": gt_data["normalized_expected"]["total_amount"],
            "currency": gt_data["normalized_expected"]["currency_iso"],
            "invoice_date": gt_data["normalized_expected"]["invoice_date"],
            "spend_category": gt_data["normalized_expected"]["spend_category"],
            "test_purpose": gt_data["meta"]["description"],
            "is_duplicate": gt_data["expected_flags"]["is_duplicate"],
            "duplicate_of_id": gt_data["expected_flags"]["duplicate_of_id"],
            "has_anomalies": gt_data["expected_flags"]["has_anomalies"],
            "anomaly_types": [flag["anomaly_type"] for flag in gt_data["expected_flags"]["anomaly_flags"]],
        })

        print(f"[{fixture_id}] -> Generated {doc_filename} ({file_size:,} bytes) & {json_filename}")

    # 5. Write Master Manifest
    manifest_data = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_fixtures": len(manifest_entries),
        "dataset_version": "1.0.0",
        "description": "Document Intelligence Pipeline ground-truth dataset and fixture index for M_E2E_1",
        "fixtures": manifest_entries,
    }

    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as mf:
        json.dump(manifest_data, mf, indent=2, ensure_ascii=False)

    print(f"\n[MANIFEST] -> Generated manifest.json ({os.path.getsize(manifest_path):,} bytes)")
    print("\n========================================================")
    print("  Successfully Generated All 10 Fixtures, JSONs, & Manifest")
    print("========================================================\n")

    return manifest_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Document Intelligence test fixtures.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tests/fixtures/sample_invoices"),
        help="Directory where sample invoices and ground-truth JSONs are written.",
    )
    args = parser.parse_args()
    generate_all_fixtures(args.output_dir)


if __name__ == "__main__":
    main()
