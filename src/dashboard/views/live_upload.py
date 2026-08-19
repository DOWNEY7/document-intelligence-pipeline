"""
src/dashboard/views/live_upload.py

Live Upload & Ingestion Lab View — Tab 4.

Provides:
- Drag-and-drop file uploader for PDF, PNG, JPG, JPEG documents
- Toggle for Force Mock Mode vs Live Azure Document Intelligence
- Real-time pipeline execution progress bar
- Instant JSON and formatted view of the extracted and normalized result
- Direct link to inspect the new record in Verification Queue
"""

from __future__ import annotations

import requests
import streamlit as st


def render_live_upload(api_base: str) -> None:
    """Render the Live Upload Lab view."""
    st.header("📤 Live Document Upload & Ingestion Lab")
    st.caption("Upload invoice or receipt documents (PDF, PNG, JPG) to execute the end-to-end extraction and normalization pipeline")

    col_upload, col_settings = st.columns([2, 1], gap="medium")

    with col_settings:
        st.subheader("⚙️ Processing Options")
        force_mock = st.checkbox(
            "Force Offline Mock Extractor",
            value=True,
            help="Bypass live Azure Document Intelligence calls and use deterministic offline heuristics / fixture catalog.",
        )
        custom_corr_id = st.text_input(
            "Correlation ID (Optional)",
            value="",
            placeholder="e.g. audit-corr-001",
            help="Custom correlation ID to trace this extraction across dual-storage.",
        )

    with col_upload:
        uploaded_files = st.file_uploader(
            "Upload Invoice / Receipt Documents",
            type=["pdf", "png", "jpg", "jpeg", "tiff"],
            accept_multiple_files=True,
            help="Select one or more PDF or image files to process.",
        )

    if uploaded_files:
        if st.button("🚀 Process Uploaded Documents", type="primary", use_container_width=True):
            progress_bar = st.progress(0)
            status_placeholder = st.empty()

            results = []
            for i, file in enumerate(uploaded_files):
                status_placeholder.info(f"Processing ({i+1}/{len(uploaded_files)}): **{file.name}**...")

                try:
                    files_payload = {"file": (file.name, file.getvalue(), file.type or "application/octet-stream")}
                    params = {"force_mock": str(force_mock).lower()}
                    if custom_corr_id.strip():
                        params["correlation_id"] = custom_corr_id.strip()

                    resp = requests.post(
                        f"{api_base}/api/v1/upload",
                        files=files_payload,
                        params=params,
                        timeout=30,
                    )

                    if resp.status_code == 200:
                        results.append({"filename": file.name, "status": "SUCCESS", "data": resp.json()})
                    else:
                        results.append({
                            "filename": file.name,
                            "status": "ERROR",
                            "error": resp.json().get("detail", resp.text),
                        })
                except Exception as exc:
                    results.append({"filename": file.name, "status": "ERROR", "error": str(exc)})

                progress_bar.progress((i + 1) / len(uploaded_files))

            status_placeholder.success(f"Processed {len(uploaded_files)} document(s) successfully!")

            # Render results
            for res in results:
                st.divider()
                if res["status"] == "SUCCESS":
                    data = res["data"]
                    vendor = data.get("vendor_canonical") or data.get("vendor_name", {}).get("value")
                    inv_id = data.get("invoice_id", {}).get("value")
                    total = data.get("total_amount", {}).get("value", 0)
                    currency = data.get("currency_iso", "USD")
                    category = data.get("spend_category")
                    doc_id = data.get("document_id")

                    st.markdown(f"### ✅ {res['filename']} `(Doc ID: {doc_id})`")
                    r_col1, r_col2, r_col3, r_col4 = st.columns(4)
                    with r_col1:
                        st.metric("Vendor", str(vendor))
                    with r_col2:
                        st.metric("Invoice ID", str(inv_id))
                    with r_col3:
                        st.metric("Total", f"{currency} {total:,.2f}")
                    with r_col4:
                        st.metric("Category", str(category))

                    if data.get("is_duplicate"):
                        st.warning(f"🔁 Duplicate Flag: {data.get('duplicate_reason')}")
                    if data.get("anomalies"):
                        for anom in data["anomalies"]:
                            st.info(f"⚠️ [{anom.get('code')}] {anom.get('message')}")

                    with st.expander("🔍 View Full Normalized JSON Payload"):
                        st.json(data)
                else:
                    st.error(f"❌ {res['filename']} failed: {res.get('error')}")
