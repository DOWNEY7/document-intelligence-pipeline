"""
src/dashboard/views/executive_kpis.py

Executive KPI Summary View — Tab 1.

Displays:
- Total spend (sum of all invoice totals)
- Total invoice count
- Duplicate count
- Anomaly / flagged count
- Extraction engine breakdown (Azure vs Mock)
- Top 3 vendors by spend
"""

from __future__ import annotations

import requests
import streamlit as st


def _fetch_invoices(api_base: str, limit: int = 1000) -> list[dict]:
    """Fetch all invoices from the API."""
    try:
        resp = requests.get(f"{api_base}/api/v1/invoices", params={"limit": limit}, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        st.error(f"Failed to connect to API at {api_base}: {exc}")
    return []


def render_executive_kpis(api_base: str) -> None:
    """Render Executive KPI tab."""
    st.header("📊 Executive Dashboard")
    st.caption("Real-time spend intelligence across all processed invoices")

    with st.spinner("Loading invoice data..."):
        invoices = _fetch_invoices(api_base)

    if not invoices:
        st.warning(
            "No invoices found. Upload documents using the **📤 Live Upload** tab "
            "or connect the API at the correct base URL."
        )
        st.info(f"API: `{api_base}/api/v1/invoices`")
        return

    # ── Compute KPIs ──────────────────────────────────────────────────────────
    total_invoices = len(invoices)
    total_spend = sum(
        float(inv.get("total_amount", {}).get("value", 0) or 0)
        for inv in invoices
        if inv.get("total_amount")
    )
    duplicates = sum(1 for inv in invoices if inv.get("is_duplicate", False))
    anomalies = sum(1 for inv in invoices if inv.get("has_anomalies", False))
    azure_extracted = sum(
        1 for inv in invoices
        if inv.get("extraction_engine", "").startswith("azure")
    )
    mock_extracted = total_invoices - azure_extracted

    currencies: dict[str, float] = {}
    for inv in invoices:
        currency = inv.get("currency_iso", "USD") or "USD"
        amount = float(inv.get("total_amount", {}).get("value", 0) or 0)
        currencies[currency] = currencies.get(currency, 0.0) + amount

    # ── KPI Metric Row ─────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        primary_currency = max(currencies, key=currencies.get) if currencies else "USD"
        st.metric(
            "💰 Total Spend",
            f"{primary_currency} {total_spend:,.2f}",
            help="Sum of all normalized invoice totals",
        )
    with col2:
        st.metric("📄 Invoices Processed", f"{total_invoices:,}")
    with col3:
        dup_pct = f"{duplicates / total_invoices * 100:.1f}%" if total_invoices else "0%"
        st.metric(
            "🔁 Duplicates",
            str(duplicates),
            delta=f"{dup_pct} of total" if duplicates else None,
            delta_color="inverse",
        )
    with col4:
        anom_pct = f"{anomalies / total_invoices * 100:.1f}%" if total_invoices else "0%"
        st.metric(
            "⚠️ Anomaly Flags",
            str(anomalies),
            delta=f"{anom_pct} of total" if anomalies else None,
            delta_color="inverse",
        )

    st.divider()

    # ── Secondary Metrics ─────────────────────────────────────────────────────
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("🤖 Azure Extracted", str(azure_extracted))
    with col_b:
        st.metric("🧪 Mock Extracted", str(mock_extracted))
    with col_c:
        clean = total_invoices - duplicates - anomalies
        clean = max(0, clean)
        st.metric("✅ Clean Invoices", str(clean))

    st.divider()

    # ── Top Vendors Table ─────────────────────────────────────────────────────
    st.subheader("🏢 Top Vendors by Spend")

    vendor_spend: dict[str, float] = {}
    for inv in invoices:
        vendor = inv.get("vendor_canonical") or (
            inv.get("vendor_name", {}).get("value") if inv.get("vendor_name") else "Unknown"
        )
        vendor = str(vendor or "Unknown")
        amount = float(inv.get("total_amount", {}).get("value", 0) or 0)
        vendor_spend[vendor] = vendor_spend.get(vendor, 0.0) + amount

    top_vendors = sorted(vendor_spend.items(), key=lambda x: x[1], reverse=True)[:10]

    if top_vendors:
        import pandas as pd
        df_vendors = pd.DataFrame(top_vendors, columns=["Vendor", "Total Spend"])
        df_vendors["Total Spend"] = df_vendors["Total Spend"].map(lambda x: f"{primary_currency} {x:,.2f}")
        df_vendors.index = range(1, len(df_vendors) + 1)
        st.dataframe(df_vendors, use_container_width=True)

    # ── Status Distribution ───────────────────────────────────────────────────
    st.subheader("📋 Invoice Status Distribution")
    status_counts: dict[str, int] = {}
    for inv in invoices:
        s = inv.get("status", "UNKNOWN")
        status_counts[s] = status_counts.get(s, 0) + 1

    if status_counts:
        import pandas as pd
        df_status = pd.DataFrame(list(status_counts.items()), columns=["Status", "Count"])
        df_status = df_status.sort_values("Count", ascending=False)
        df_status.index = range(1, len(df_status) + 1)
        st.dataframe(df_status, use_container_width=True)
