"""
src/dashboard/views/spend_analytics.py

Spend Analytics View — Tab 2.

Interactive Plotly charts:
- Monthly spend trend (line/bar)
- Spend by vendor (bar chart)
- Spend by category (pie/donut)
- Currency breakdown
"""

from __future__ import annotations

import requests
import streamlit as st


def _fetch_invoices(api_base: str, limit: int = 1000, api_key: str | None = None) -> list[dict]:
    try:
        headers = {"X-API-Key": api_key} if api_key else None
        resp = requests.get(
            f"{api_base}/api/v1/invoices",
            params={"limit": limit},
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def render_spend_analytics(api_base: str, api_key: str | None = None) -> None:
    """Render Spend Analytics tab with interactive charts."""
    st.header("📈 Spend Analytics")

    try:
        import pandas as pd
        import plotly.express as px
    except ImportError:
        st.error("Install plotly: `pip install plotly`")
        return

    with st.spinner("Loading analytics data..."):
        invoices = _fetch_invoices(api_base, api_key=api_key)

    if not invoices:
        st.info("No invoice data available. Upload documents via the Live Upload tab.")
        return

    # Build flat DataFrame
    rows = []
    for inv in invoices:
        total = float(inv.get("total_amount", {}).get("value", 0) or 0)
        if total <= 0:
            continue

        date_val = inv.get("invoice_date", {})
        date_str = date_val.get("value", "") if isinstance(date_val, dict) else str(date_val or "")
        month = date_str[:7] if len(date_str) >= 7 else "Unknown"

        vendor = inv.get("vendor_canonical") or (
            inv.get("vendor_name", {}).get("value") if isinstance(inv.get("vendor_name"), dict) else "Unknown"
        )
        category = inv.get("spend_category") or "Miscellaneous / Other"
        currency = inv.get("currency_iso", "USD") or "USD"

        rows.append({
            "month": month,
            "vendor": str(vendor or "Unknown"),
            "category": str(category),
            "currency": currency,
            "amount": total,
            "is_duplicate": inv.get("is_duplicate", False),
            "has_anomalies": inv.get("has_anomalies", False),
        })

    if not rows:
        st.info("No invoices with valid amounts found.")
        return

    df = pd.DataFrame(rows)

    # ── Filters ───────────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        all_vendors = ["All"] + sorted(df["vendor"].unique().tolist())
        selected_vendor = st.selectbox("Filter by Vendor", all_vendors)
    with col_f2:
        all_categories = ["All"] + sorted(df["category"].unique().tolist())
        selected_category = st.selectbox("Filter by Category", all_categories)
    with col_f3:
        exclude_duplicates = st.checkbox("Exclude Duplicates", value=False)

    # Apply filters
    filtered_df = df.copy()
    if selected_vendor != "All":
        filtered_df = filtered_df[filtered_df["vendor"] == selected_vendor]
    if selected_category != "All":
        filtered_df = filtered_df[filtered_df["category"] == selected_category]
    if exclude_duplicates:
        filtered_df = filtered_df[~filtered_df["is_duplicate"]]

    if filtered_df.empty:
        st.warning("No data matches the selected filters.")
        return

    primary_currency = filtered_df["currency"].mode()[0] if not filtered_df.empty else "USD"

    # ── Monthly Spend Trend ────────────────────────────────────────────────────
    st.subheader("📅 Monthly Spend Trend")
    monthly = filtered_df.groupby("month")["amount"].sum().reset_index()
    monthly = monthly.sort_values("month")

    if not monthly.empty:
        fig_monthly = px.bar(
            monthly,
            x="month",
            y="amount",
            labels={"month": "Month", "amount": f"Spend ({primary_currency})"},
            title="Total Spend by Month",
            color_discrete_sequence=["#4361EE"],
        )
        fig_monthly.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig_monthly, use_container_width=True)

    # ── Vendor vs Category Charts ─────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("🏢 Spend by Vendor")
        vendor_spend = filtered_df.groupby("vendor")["amount"].sum().reset_index()
        vendor_spend = vendor_spend.sort_values("amount", ascending=False).head(15)

        if not vendor_spend.empty:
            fig_vendor = px.bar(
                vendor_spend,
                x="amount",
                y="vendor",
                orientation="h",
                labels={"amount": f"Spend ({primary_currency})", "vendor": "Vendor"},
                title="Top Vendors by Spend",
                color="amount",
                color_continuous_scale="Blues",
            )
            fig_vendor.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig_vendor, use_container_width=True)

    with col_right:
        st.subheader("🗂️ Spend by Category")
        cat_spend = filtered_df.groupby("category")["amount"].sum().reset_index()

        if not cat_spend.empty:
            fig_cat = px.pie(
                cat_spend,
                values="amount",
                names="category",
                title="Spend by Category",
                hole=0.4,
            )
            fig_cat.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig_cat, use_container_width=True)

    # ── Currency Breakdown ────────────────────────────────────────────────────
    st.subheader("💱 Currency Distribution")
    currency_spend = filtered_df.groupby("currency")["amount"].sum().reset_index()
    if len(currency_spend) > 1:
        fig_curr = px.pie(
            currency_spend,
            values="amount",
            names="currency",
            title="Spend by Currency",
        )
        st.plotly_chart(fig_curr, use_container_width=True)
    else:
        st.info(f"All invoices in {primary_currency}")

    # ── Anomaly Overlay ───────────────────────────────────────────────────────
    anomaly_count = filtered_df["has_anomalies"].sum()
    dup_count = filtered_df["is_duplicate"].sum()
    if anomaly_count > 0 or dup_count > 0:
        st.subheader("⚠️ Anomaly & Duplicate Summary")
        colx, coly = st.columns(2)
        with colx:
            st.metric("Invoices with Anomalies", str(int(anomaly_count)))
        with coly:
            st.metric("Duplicate Invoices", str(int(dup_count)))
