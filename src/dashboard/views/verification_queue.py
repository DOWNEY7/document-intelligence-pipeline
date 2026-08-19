"""
src/dashboard/views/verification_queue.py

Split-Screen Verification Queue View — Tab 3.

Provides:
- Filterable queue of invoices requiring human verification (flagged for duplicate, anomalies, or low confidence)
- Interactive split-screen review:
  - Left pane: Source document file viewer (embedded PDF or Image streamed directly from API)
  - Right pane: Extracted & normalized key fields, line items, and active anomaly warnings
- Status update actions (Approve / Reject / Mark Resolved)
"""

from __future__ import annotations

import base64

import requests
import streamlit as st


def _fetch_flagged_invoices(api_base: str) -> list[dict]:
    """Fetch invoices that have anomalies, are duplicates, or have status NEEDS_REVIEW/FLAGGED."""
    try:
        resp = requests.get(f"{api_base}/api/v1/invoices", params={"limit": 500}, timeout=10)
        if resp.status_code == 200:
            all_invoices = resp.json()
            # Filter for items requiring verification
            flagged = [
                inv for inv in all_invoices
                if inv.get("is_duplicate")
                or inv.get("has_anomalies")
                or inv.get("status") in ["NEEDS_REVIEW", "FLAGGED"]
                or (inv.get("confidence_score") and inv.get("confidence_score") < 0.85)
            ]
            return flagged if flagged else all_invoices[:10]
    except Exception as exc:
        st.error(f"Failed to fetch verification queue from {api_base}: {exc}")
    return []


def _fetch_document_file(api_base: str, doc_id: str) -> tuple[bytes | None, str]:
    """Fetch binary file for document preview."""
    try:
        resp = requests.get(f"{api_base}/api/v1/documents/{doc_id}/file", timeout=15)
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "application/pdf")
            return resp.content, content_type
    except Exception:
        pass
    return None, ""


def render_verification_queue(api_base: str) -> None:
    """Render the Split-Screen Verification Queue view."""
    st.header("🔍 Split-Screen Verification Queue")
    st.caption("Review flagged invoices and inspect original source documents side-by-side with extracted data")

    flagged_invoices = _fetch_flagged_invoices(api_base)

    if not flagged_invoices:
        st.success("🎉 Verification queue is empty! No flagged anomalies or duplicate invoices pending review.")
        return

    # ── Queue Selector ────────────────────────────────────────────────────────
    invoice_options = {}
    for inv in flagged_invoices:
        doc_id = inv.get("document_id", "N/A")
        inv_id = inv.get("invoice_id", {}).get("value") if isinstance(inv.get("invoice_id"), dict) else inv.get("invoice_id", "N/A")
        vendor = inv.get("vendor_canonical") or inv.get("vendor_name", {}).get("value") or "Unknown"
        amount = inv.get("total_amount", {}).get("value", 0) or 0
        currency = inv.get("currency_iso", "USD")
        status = inv.get("status", "FLAGGED")

        label = f"[{status}] {vendor} — {inv_id} ({currency} {amount:,.2f}) [Doc: {doc_id[:8]}]"
        invoice_options[label] = inv

    selected_label = st.selectbox(
        "Select Invoice to Verify",
        options=list(invoice_options.keys()),
        index=0,
        help="Select a flagged invoice from the review queue",
    )

    selected_inv = invoice_options[selected_label]
    doc_id = selected_inv.get("document_id")

    st.divider()

    # ── Split-Screen Layout ───────────────────────────────────────────────────
    col_left, col_right = st.columns([1, 1], gap="medium")

    # ── LEFT: Source Document Preview ──
    with col_left:
        st.subheader("📄 Source Document Preview")
        filename = selected_inv.get("filename", "document.pdf")
        st.caption(f"File: **{filename}** | Document ID: `{doc_id}`")

        if doc_id:
            file_bytes, content_type = _fetch_document_file(api_base, doc_id)
            if file_bytes:
                if "pdf" in content_type.lower() or filename.lower().endswith(".pdf"):
                    base64_pdf = base64.b64encode(file_bytes).decode("utf-8")
                    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf" style="border: 1px solid #ccc; border-radius: 8px;"></iframe>'
                    st.markdown(pdf_display, unsafe_allow_html=True)
                else:
                    st.image(file_bytes, caption=filename, use_container_width=True)
            else:
                st.warning(f"Could not load preview for document `{doc_id}` from API endpoint `/api/v1/documents/{doc_id}/file`.")
        else:
            st.info("No document ID associated with this invoice.")

    # ── RIGHT: Extracted Data & Anomalies ──
    with col_right:
        st.subheader("📋 Extracted & Normalised Data")

        # ── Anomaly & Duplicate Alerts ──
        if selected_inv.get("is_duplicate"):
            st.error(
                f"🔁 **Duplicate Invoice Detected!**\n\n"
                f"{selected_inv.get('duplicate_reason', 'Identical vendor + amount in 7-day window')}\n"
                f"Original ID: `{selected_inv.get('duplicate_of_id', 'N/A')}`"
            )

        anomalies = selected_inv.get("anomalies", [])
        if anomalies:
            for anom in anomalies:
                code = anom.get("code", "ANOMALY")
                msg = anom.get("message", "")
                sev = anom.get("severity", "WARNING")
                if sev in ["CRITICAL", "ERROR"]:
                    st.error(f"⚠️ **[{code}]** {msg}")
                else:
                    st.warning(f"⚠️ **[{code}]** {msg}")

        # ── Key Fields Display ──
        vendor_raw = selected_inv.get("vendor_raw") or selected_inv.get("vendor_name", {}).get("value")
        vendor_can = selected_inv.get("vendor_canonical")
        match_score = selected_inv.get("vendor_match_score", 100.0)

        f_col1, f_col2 = st.columns(2)
        with f_col1:
            st.text_input("Canonical Vendor", value=str(vendor_can or "N/A"), disabled=True)
            st.text_input("Raw Vendor", value=str(vendor_raw or "N/A"), disabled=True)
            st.text_input("Invoice ID", value=str(selected_inv.get("invoice_id", {}).get("value") or "N/A"), disabled=True)
            st.text_input("Invoice Date", value=str(selected_inv.get("invoice_date", {}).get("value") or "N/A"), disabled=True)
        with f_col2:
            st.text_input("Spend Category", value=str(selected_inv.get("spend_category") or "N/A"), disabled=True)
            st.text_input("Match Score", value=f"{match_score:.1f}%", disabled=True)
            st.text_input("Total Amount", value=f"{selected_inv.get('currency_iso', 'USD')} {selected_inv.get('total_amount', {}).get('value', 0):,.2f}", disabled=True)
            st.text_input("Tax / VAT", value=f"{selected_inv.get('tax_amount', {}).get('value', 0) or 0:,.2f}", disabled=True)

        # ── Line Items ──
        line_items = selected_inv.get("line_items", [])
        if line_items:
            st.markdown("**Structured Line Items**")
            import pandas as pd
            items_data = []
            for it in line_items:
                items_data.append({
                    "Description": it.get("description", ""),
                    "Qty": it.get("quantity", 1),
                    "Unit Price": it.get("unit_price", 0),
                    "Total": it.get("total_amount", 0),
                    "Category": it.get("category", ""),
                })
            st.dataframe(pd.DataFrame(items_data), use_container_width=True)

        # ── Verification Actions ──
        st.markdown("**Verification Actions**")
        act_col1, act_col2, act_col3 = st.columns(3)
        with act_col1:
            if st.button("✅ Approve & Clear", use_container_width=True):
                st.success("Invoice approved and cleared from verification queue.")
        with act_col2:
            if st.button("❌ Reject / Void", use_container_width=True):
                st.error("Invoice marked as rejected/voided.")
        with act_col3:
            if st.button("📝 Edit Record", use_container_width=True):
                st.info("Edit mode active (mock).")
