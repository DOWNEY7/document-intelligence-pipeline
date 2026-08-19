"""
src/dashboard/app.py

Streamlit Analytics Dashboard — Entry Point.

Tabs:
1. 📊 Executive KPIs          — Total spend, invoice count, anomaly summary
2. 📈 Spend Analytics         — Monthly, vendor, category Plotly charts
3. 🔍 Verification Queue      — Flagged invoices with source document preview
4. 📤 Live Upload Lab         — Interactive upload with real-time pipeline execution
5. 📋 Invoice Explorer        — Searchable/filterable full invoice table

Run:
    streamlit run src/dashboard/app.py
    # OR
    python -m streamlit run src/dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path when running as a script
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

# Configure page
st.set_page_config(
    page_title="Document Intelligence Pipeline",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "# Document Intelligence Pipeline\nEnterprise invoice processing powered by Azure AI.",
    },
)

from src.dashboard.views.executive_kpis import render_executive_kpis
from src.dashboard.views.spend_analytics import render_spend_analytics
from src.dashboard.views.verification_queue import render_verification_queue
from src.dashboard.views.live_upload import render_live_upload
from src.dashboard.views.invoice_explorer import render_invoice_explorer


def main() -> None:
    """Main Streamlit dashboard entry point."""

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("🧾 Document Intelligence")
        st.caption("Azure AI · FastAPI · Streamlit")
        st.divider()

        api_base = st.text_input(
            "API Base URL",
            value="http://localhost:8000",
            help="FastAPI backend URL",
        )

        st.divider()
        st.caption("© 2026 Document Intelligence Pipeline")

    # ── Tabs ───────────────────────────────────────────────────────────────────
    tab_kpi, tab_analytics, tab_verify, tab_upload, tab_explorer = st.tabs([
        "📊 Executive KPIs",
        "📈 Spend Analytics",
        "🔍 Verification Queue",
        "📤 Live Upload",
        "📋 Invoice Explorer",
    ])

    with tab_kpi:
        render_executive_kpis(api_base)

    with tab_analytics:
        render_spend_analytics(api_base)

    with tab_verify:
        render_verification_queue(api_base)

    with tab_upload:
        render_live_upload(api_base)

    with tab_explorer:
        render_invoice_explorer(api_base)


if __name__ == "__main__":
    main()
