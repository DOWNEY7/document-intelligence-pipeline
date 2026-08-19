"""
src/dashboard/views/invoice_explorer.py

Invoice Explorer View — Tab 5.

Provides:
- Searchable, sortable, filterable table of all processed invoices
- Download data as CSV / JSON
- Drill-down inspector for single invoices (line items, raw JSON, audit trail)
"""

from __future__ import annotations

import requests
import streamlit as st


def _fetch_all_invoices(api_base: str, limit: int = 1000) -> list[dict]:
    try:
        resp = requests.get(f"{api_base}/api/v1/invoices", params={"limit": limit}, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        st.error(f"Failed to fetch invoices from {api_base}: {exc}")
    return []


def render_invoice_explorer(api_base: str) -> None:
    """Render the full Invoice Explorer tab."""
    st.header("📋 Invoice Explorer")
    st.caption("Browse, filter, inspect, and export all stored invoices and raw extraction records")

    invoices = _fetch_all_invoices(api_base)

    if not invoices:
        st.info("No invoices found in database. Process sample files or use the Live Upload tab.")
        return

    import pandas as pd

    # Flatten for table
    table_rows = []
    for inv in invoices:
        v_name = inv.get("vendor_canonical") or (
            inv.get("vendor_name", {}).get("value") if isinstance(inv.get("vendor_name"), dict) else inv.get("vendor_name")
        )
        inv_id_val = inv.get("invoice_id", {}).get("value") if isinstance(inv.get("invoice_id"), dict) else inv.get("invoice_id")
        date_val = inv.get("invoice_date", {}).get("value") if isinstance(inv.get("invoice_date"), dict) else inv.get("invoice_date")
        total_val = inv.get("total_amount", {}).get("value", 0) if isinstance(inv.get("total_amount"), dict) else inv.get("total_amount", 0)

        table_rows.append({
            "ID": inv.get("id", "")[:8],
            "Document ID": inv.get("document_id", "")[:8],
            "Vendor": str(v_name or "Unknown"),
            "Invoice #": str(inv_id_val or "N/A"),
            "Date": str(date_val or "N/A"),
            "Total": float(total_val or 0),
            "Currency": inv.get("currency_iso", "USD"),
            "Category": str(inv.get("spend_category") or "N/A"),
            "Status": inv.get("status", "SUCCESS"),
            "Duplicate": "🔁 Yes" if inv.get("is_duplicate") else "No",
            "Anomalies": f"⚠️ ({len(inv.get('anomalies', []))})" if inv.get("anomalies") else "None",
            "_full_record": inv,
        })

    df = pd.DataFrame(table_rows)

    # ── Search & Filter Controls ──
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        search_query = st.text_input("🔍 Search Vendor or Invoice #", value="")
    with f_col2:
        status_filter = st.selectbox("Status Filter", ["All"] + sorted(list(set(df["Status"]))))
    with f_col3:
        dup_filter = st.selectbox("Duplicate Filter", ["All", "Duplicates Only", "Non-Duplicates Only"])

    filtered_df = df.copy()
    if search_query.strip():
        q = search_query.strip().lower()
        filtered_df = filtered_df[
            filtered_df["Vendor"].str.lower().str.contains(q)
            | filtered_df["Invoice #"].str.lower().str.contains(q)
        ]
    if status_filter != "All":
        filtered_df = filtered_df[filtered_df["Status"] == status_filter]
    if dup_filter == "Duplicates Only":
        filtered_df = filtered_df[filtered_df["Duplicate"] == "🔁 Yes"]
    elif dup_filter == "Non-Duplicates Only":
        filtered_df = filtered_df[filtered_df["Duplicate"] == "No"]

    st.markdown(f"**Showing {len(filtered_df)} of {len(df)} records**")

    # Display table without the internal _full_record column
    display_df = filtered_df.drop(columns=["_full_record"])
    st.dataframe(display_df, use_container_width=True)

    # ── Export ──
    csv_data = display_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 Export Filtered Table as CSV",
        data=csv_data,
        file_name="invoices_export.csv",
        mime="text/csv",
    )

    # ── Drill-down Record Details ──
    st.divider()
    st.subheader("🔍 Inspect Single Record")
    if not filtered_df.empty:
        record_idx = st.selectbox(
            "Select Record to Inspect",
            range(len(filtered_df)),
            format_func=lambda i: f"{filtered_df.iloc[i]['Vendor']} — {filtered_df.iloc[i]['Invoice #']} ({filtered_df.iloc[i]['Currency']} {filtered_df.iloc[i]['Total']:,.2f})",
        )
        selected_record = filtered_df.iloc[record_idx]["_full_record"]
        st.json(selected_record)
