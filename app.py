"""
app.py - Invoice Processing Automation (v2)
Pages: Invoice Processor + Dashboard + Learning Rules

Key improvements over v1:
- Live pipeline visualization showing each stage as it executes
- Per-check audit trail with pass/fail icons and detailed reasoning
- Confidence score breakdown (itemized deductions)
- Processing time per invoice
- Clean action summary separate from email body
- Better error handling for None/missing amounts
"""

import streamlit as st
import pandas as pd
import os
import time
import json
from datetime import datetime

from extractor import extract_invoice_data, parse_amount
from validator import run_all_checks, get_default_config
from email_generator import generate_email
from learning import (
    apply_learning_rules,
    describe_rule,
    load_learning_rules,
    save_learning_rule,
    suggest_learning_rule,
)
from learning_rules_ui import (
    mark_rule_created_this_session,
    render_learning_rules_page,
    render_learning_rules_widget,
)

# =========================================================
# CONFIG
# =========================================================
DATA_DIR = "data"
PO_MASTER_PATH = os.path.join(DATA_DIR, "po_master.csv")
VENDOR_MASTER_PATH = os.path.join(DATA_DIR, "vendor_master.csv")
HISTORY_PATH = os.path.join(DATA_DIR, "processing_history.csv")

st.set_page_config(
    page_title="Zamp Invoice Processor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# CSS
# =========================================================
st.markdown("""
<style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem; color: white;
    }
    .main-header h1 { color: white; margin: 0; font-size: 1.8rem; font-weight: 700; }
    .main-header p { color: #b8c6db; margin: 0.3rem 0 0 0; font-size: 0.95rem; }

    .status-approved { background:#d4edda; color:#155724; padding:4px 12px; border-radius:20px; font-weight:600; font-size:0.85rem; display:inline-block; }
    .status-flagged { background:#fff3cd; color:#856404; padding:4px 12px; border-radius:20px; font-weight:600; font-size:0.85rem; display:inline-block; }
    .status-rejected { background:#f8d7da; color:#721c24; padding:4px 12px; border-radius:20px; font-weight:600; font-size:0.85rem; display:inline-block; }

    .metric-card { background:white; border:1px solid #e0e0e0; border-radius:10px; padding:1.2rem; text-align:center; box-shadow:0 2px 4px rgba(0,0,0,0.05); }
    .metric-card h3 { margin:0; font-size:2rem; font-weight:700; }
    .metric-card p { margin:0.3rem 0 0 0; color:#666; font-size:0.85rem; }

    .pipeline-step { padding:0.4rem 0.8rem; margin:0.2rem 0; border-radius:6px; font-size:0.85rem; display:flex; align-items:center; gap:0.5rem; }
    .pipe-success { background:#e8f5e9; border-left:3px solid #2e7d32; color:#2e7d32; }
    .pipe-warning { background:#fff8e1; border-left:3px solid #f57f17; color:#795548; }
    .pipe-error { background:#ffebee; border-left:3px solid #c62828; color:#c62828; }
    .pipe-skip { background:#f5f5f5; border-left:3px solid #bdbdbd; color:#9e9e9e; }
    .pipe-active { background:#e3f2fd; border-left:3px solid #1976d2; color:#1565c0; }
    .pipe-time { font-size:0.75rem; color:#888; margin-left:auto; }

    .check-row { padding:0.35rem 0.7rem; margin:0.15rem 0; border-radius:4px; font-size:0.82rem; }
    .check-pass { background:#f1f8e9; }
    .check-flag { background:#fff8e1; }
    .check-reject { background:#fce4ec; }
    .check-skip { background:#fafafa; color:#999; }
    .check-info { background:#e8eaf6; }

    .conf-high { color:#2e7d32; font-weight:600; }
    .conf-medium { color:#f57f17; font-weight:600; }
    .conf-low { color:#c62828; font-weight:600; }

    .email-draft { background:#f8f9fa; border:1px solid #dee2e6; border-radius:8px; padding:1rem; font-size:0.82rem; white-space:pre-wrap; }

    #MainMenu {visibility:hidden;} footer {visibility:hidden;}
</style>
""", unsafe_allow_html=True)


# =========================================================
# DATA
# =========================================================
@st.cache_data
def load_po_master():
    return pd.read_csv(PO_MASTER_PATH)

@st.cache_data
def load_vendor_master():
    return pd.read_csv(VENDOR_MASTER_PATH)

def load_history():
    if os.path.exists(HISTORY_PATH):
        df = pd.read_csv(HISTORY_PATH)
        if df.empty or len(df.columns) <= 1:
            return pd.DataFrame()
        return df
    return pd.DataFrame()

def save_to_history(results_list):
    history_df = load_history()
    new_rows = []
    for r in results_list:
        # Serialize check_log as JSON string for storage
        check_details = json.dumps(r.get("check_log", []), default=str)
        new_rows.append({
            "document_id": r.get("document_id", ""),
            "document_type": r.get("document_type", ""),
            "invoice_number": r.get("invoice_number", ""),
            "vendor_name": r.get("vendor_name", ""),
            "po_number": r.get("po_number", ""),
            "invoice_amount": r.get("invoice_amount", ""),
            "tax_amount": r.get("tax_amount", ""),
            "currency": r.get("currency", ""),
            "po_currency": r.get("po_currency", ""),
            "po_vendor_name": r.get("po_vendor_name", ""),
            "po_date": r.get("po_date", ""),
            "po_amount": r.get("po_amount", ""),
            "variance_dollar": r.get("variance_dollar", ""),
            "variance_percent": r.get("variance_percent", ""),
            "cumulative_invoiced": r.get("cumulative_invoiced", ""),
            "status": r.get("status", ""),
            "remark": r.get("remark", ""),
            "suggested_action": r.get("action_summary", ""),
            "confidence_score": r.get("confidence_score", ""),
            "overall_extraction_confidence": r.get("overall_extraction_confidence", ""),
            "ocr_confidence": r.get("ocr_confidence", ""),
            "vendor_email": r.get("vendor_email_resolved", r.get("vendor_email", "")),
            "contact_person": r.get("contact_person", ""),
            "file_name": r.get("file_name", ""),
            "processed_date": r.get("processed_date", ""),
            "check_details": check_details,
        })
    new_df = pd.DataFrame(new_rows)
    combined = pd.concat([history_df, new_df], ignore_index=True) if not history_df.empty else new_df
    combined.to_csv(HISTORY_PATH, index=False)

def build_invoice_context(row, checks=None):
    return {
        "invoice_number": row.get("invoice_number", ""),
        "document_type": row.get("document_type", ""),
        "vendor_name": row.get("vendor_name", ""),
        "po_number": row.get("po_number", ""),
        "invoice_amount": row.get("invoice_amount", ""),
        "po_amount": row.get("po_amount", ""),
        "variance_percent": row.get("variance_percent", ""),
        "status": row.get("status", ""),
        "remark": row.get("remark", ""),
        "suggested_action": row.get("suggested_action", ""),
        "currency": row.get("currency", ""),
        "failed_checks": [
            {"check": c.get("check"), "detail": c.get("detail")}
            for c in (checks or [])
            if c.get("status") in ("flag", "reject")
        ],
    }


def fmt_amount(val):
    if val is None: return "N/A"
    try: return f"₹{float(val):,.2f}"
    except: return str(val)

def get_status_badge(status):
    if status == "Approved": return '<span class="status-approved">✓ Approved</span>'
    elif "Flagged" in str(status): return '<span class="status-flagged">⚠ Flagged for Review</span>'
    elif status == "Rejected": return '<span class="status-rejected">✗ Rejected</span>'
    return str(status)

def get_status_icon(status):
    if status == "Approved": return "🟢"
    elif "Flagged" in str(status): return "🟡"
    return "🔴"

def render_check_log(check_log):
    """Render the per-check audit trail."""
    icons = {"pass": "✅", "flag": "⚠️", "reject": "❌", "skip": "⏭️", "info": "ℹ️"}
    css = {"pass": "check-pass", "flag": "check-flag", "reject": "check-reject", "skip": "check-skip", "info": "check-info"}
    for c in check_log:
        s = c.get("status", "info")
        icon = icons.get(s, "•")
        cls = css.get(s, "check-info")
        st.markdown(f'<div class="check-row {cls}">{icon} <strong>{c["check"]}</strong>: {c["detail"]}</div>', unsafe_allow_html=True)

def render_pipeline_steps(steps):
    """Render extraction pipeline steps."""
    icons = {"success": "✅", "warning": "⚠️", "error": "❌", "skipped": "⏭️"}
    css = {"success": "pipe-success", "warning": "pipe-warning", "error": "pipe-error", "skipped": "pipe-skip"}
    for s in steps:
        icon = icons.get(s["status"], "•")
        cls = css.get(s["status"], "pipe-skip")
        time_str = f'{s["duration_ms"]:.0f}ms' if s["duration_ms"] > 0 else ""
        st.markdown(
            f'<div class="pipeline-step {cls}">{icon} <strong>{s["step"]}</strong> — {s["detail"]}'
            f'<span class="pipe-time">{time_str}</span></div>',
            unsafe_allow_html=True
        )


# =========================================================
# SIDEBAR
# =========================================================

check_config = get_default_config()

with st.sidebar:
    st.image("assets/zamp_logo.png", width=60)
    st.markdown("#### Zamp Invoice Processor")
    page = st.radio("Go to", ["Invoice Processor", "Dashboard", "Learning Rules"], label_visibility="collapsed")
    st.markdown("---")

    st.markdown("### ⚙️ Validation Rules")

    # Status indicator showing active/total checks
    active_count = 0

    for check_key, check_def in check_config.items():
        label = check_def["label"]
        desc = check_def["description"]
        params = check_def["params"]

        # Each check gets an expander with toggle inside
        with st.expander(f"{'🟢' if check_def['enabled'] else '⚪'} {label}", expanded=False):
            st.caption(desc)

            enabled = st.toggle("Enabled", value=check_def["enabled"], key=f"chk_{check_key}")
            check_config[check_key]["enabled"] = enabled
            if enabled:
                active_count += 1

            if enabled and params:
                st.markdown("**Configuration**")
                for param_key, param_def in params.items():
                    default_val = param_def["value"]
                    st.caption(f"Default: {default_val}")
                    val = st.slider(
                        param_def["label"],
                        min_value=param_def["min"],
                        max_value=param_def["max"],
                        value=default_val,
                        step=param_def["step"],
                        key=f"param_{check_key}_{param_key}",
                    )
                    check_config[check_key]["params"][param_key]["value"] = val
                    if val != default_val:
                        st.caption(f"⚠️ Custom: {val} (default: {default_val})")

            # Special: currency check gets a text input for allowed currencies
            if enabled and check_key == "currency":
                st.markdown("**Configuration**")
                currencies_str = st.text_input("Allowed currencies (comma-separated)", value="INR, USD", key="currency_allowed")
                parsed = [c.strip().upper() for c in currencies_str.split(",") if c.strip()]
                st.caption(f"Active: {', '.join(parsed)}")
                # Store in session for the validator to use
                st.session_state["allowed_currencies"] = parsed

            elif not enabled:
                st.caption("This check is disabled and will be skipped during validation.")

    st.markdown(f"<div style='text-align:center;padding:0.5rem;background:#f0f2f6;border-radius:8px;margin:0.5rem 0;'>"
                f"<strong>{active_count}/{len(check_config)}</strong> checks active</div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📊 Quick Stats")
    history = load_history()
    if not history.empty:
        total = len(history)
        approved = len(history[history["status"] == "Approved"])
        flagged = len(history[history["status"].str.contains("Flagged", na=False)])
        rejected = len(history[history["status"] == "Rejected"])
        st.metric("Total Processed", total)
        col_a, col_b = st.columns(2)
        col_a.metric("Approved", approved)
        col_b.metric("Rejected", rejected)
        st.metric("Flagged", flagged)
    else:
        st.info("No invoices processed yet")
    st.markdown("---")
    st.markdown("<div style='text-align:center;color:#888;font-size:0.75rem;'>Zamp Invoice Processor v3.0<br>AI Solutions Associate Case Study</div>", unsafe_allow_html=True)


# =========================================================
# PAGE 1: INVOICE PROCESSOR
# =========================================================
if page == "Invoice Processor":
    st.markdown('<div class="main-header"><h1>⚡ Zamp Invoice Processor</h1><p>Automated invoice extraction, validation, and decision engine</p></div>', unsafe_allow_html=True)

    api_key = st.secrets.get("GROQ_API_KEY", "")
    if not api_key or api_key == "your-groq-api-key-here":
        st.error("Groq API key not configured. Add your key to `.streamlit/secrets.toml`")
        st.code('GROQ_API_KEY = "gsk_your_actual_key_here"', language="toml")
        st.stop()

    st.markdown("### Upload Invoices")
    uploaded_files = st.file_uploader("Drag and drop invoice PDFs", type=["pdf"], accept_multiple_files=True)

    col1, col2 = st.columns([1, 4])
    with col1:
        process_btn = st.button("🚀 Process Invoices", type="primary", use_container_width=True, disabled=not uploaded_files)
    with col2:
        if uploaded_files:
            amt_t = check_config["amount"]["params"]["tolerance_pct"]["value"]
            stale_t = check_config["invoice_date"]["params"]["stale_days"]["value"]
            enabled_count = sum(1 for v in check_config.values() if v["enabled"])
            st.markdown(f"<span style='color:#666;line-height:2.5;'>{len(uploaded_files)} file(s) | {enabled_count}/{len(check_config)} checks active</span>", unsafe_allow_html=True)

    if process_btn and uploaded_files:
        po_master_df = load_po_master()
        vendor_master_df = load_vendor_master()
        all_results = []
        batch_start = time.time()

        st.markdown("---")
        st.markdown("### Processing Pipeline")

        for i, uploaded_file in enumerate(uploaded_files):
            file_name = uploaded_file.name
            st.markdown(f"**📄 {file_name}** ({i+1}/{len(uploaded_files)})")

            # Save temp file
            temp_path = os.path.join("data", f"temp_{file_name}")
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            try:
                # ---- EXTRACTION ----
                with st.spinner(f"Extracting data from {file_name}..."):
                    extraction_result = extract_invoice_data(temp_path, api_key)

                # Show extraction pipeline steps
                render_pipeline_steps(extraction_result.get("pipeline_steps", []))

                learned_data, learned_checks = apply_learning_rules(extraction_result["extracted_data"])
                extraction_result["extracted_data"] = learned_data
                extraction_result["metadata"]["learned_rule_checks"] = learned_checks

                # ---- VALIDATION ----
                current_history = load_history()
                if all_results:
                    batch_df = pd.DataFrame([{
                        "invoice_number": r.get("invoice_number", ""),
                        "vendor_name": r.get("vendor_name", ""),
                        "po_number": r.get("po_number", ""),
                        "invoice_amount": r.get("invoice_amount", ""),
                        "po_amount": r.get("po_amount", ""),
                        "status": r.get("status", ""),
                        "remark": r.get("remark", ""),
                        "processed_date": r.get("processed_date", ""),
                        "file_name": r.get("file_name", ""),
                    } for r in all_results])
                    combined_history = pd.concat([current_history, batch_df], ignore_index=True) if not current_history.empty else batch_df
                else:
                    combined_history = current_history

                # Pass allowed currencies from sidebar into check_config
                if "allowed_currencies" in st.session_state:
                    check_config["currency"]["_allowed_currencies"] = st.session_state["allowed_currencies"]

                validation_result = run_all_checks(
                    extraction_result["extracted_data"],
                    extraction_result["metadata"],
                    po_master_df, vendor_master_df, combined_history,
                    check_config=check_config,
                )

                # ---- EMAIL ----
                email_draft = generate_email(validation_result)
                validation_result["action_summary"] = email_draft.get("action_summary", "No action needed")
                validation_result["email_to"] = email_draft.get("to_email", "")
                validation_result["email_subject"] = email_draft.get("subject", "")
                validation_result["email_body"] = email_draft.get("body", "")
                validation_result["email_type"] = email_draft.get("email_type", "none")
                validation_result["total_time_ms"] = extraction_result["metadata"].get("total_time_ms", 0)
                validation_result["model_used"] = extraction_result["metadata"].get("model_used", "N/A")
                validation_result["fallback_level"] = extraction_result["metadata"].get("fallback_level", 0)
                validation_result["pipeline_steps"] = extraction_result.get("pipeline_steps", [])

                all_results.append(validation_result)

                # Show validation check log inline
                render_check_log(validation_result.get("check_log", []))

                # Show decision
                status = validation_result["status"]
                badge = get_status_badge(status)
                time_ms = validation_result.get("total_time_ms", 0)
                st.markdown(f"**Decision:** {badge} &nbsp; <span style='color:#888;font-size:0.8rem;'>({time_ms:.0f}ms)</span>", unsafe_allow_html=True)
                st.markdown("---")

            except Exception as e:
                st.error(f"Error processing {file_name}: {str(e)}")
                st.markdown("---")
            finally:
                # Store PDF bytes in session state for Dashboard preview (no disk save)
                if "pdf_cache" not in st.session_state:
                    st.session_state["pdf_cache"] = {}
                if os.path.exists(temp_path):
                    with open(temp_path, "rb") as pf:
                        st.session_state["pdf_cache"][f"temp_{file_name}"] = pf.read()
                    os.remove(temp_path)

        batch_time = round((time.time() - batch_start) * 1000, 0)

        # Save to history
        save_to_history(all_results)
        load_po_master.clear()
        load_vendor_master.clear()

        # =========================================================
        # RESULTS SUMMARY
        # =========================================================
        st.markdown("### Results Summary")

        total = len(all_results)
        approved = sum(1 for r in all_results if r["status"] == "Approved")
        flagged = sum(1 for r in all_results if "Flagged" in r["status"])
        rejected = sum(1 for r in all_results if r["status"] == "Rejected")

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.markdown(f'<div class="metric-card"><h3>{total}</h3><p>Processed</p></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-card"><h3 style="color:#2e7d32">{approved}</h3><p>Approved</p></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="metric-card"><h3 style="color:#f57f17">{flagged}</h3><p>Flagged</p></div>', unsafe_allow_html=True)
        with c4:
            st.markdown(f'<div class="metric-card"><h3 style="color:#c62828">{rejected}</h3><p>Rejected</p></div>', unsafe_allow_html=True)
        with c5:
            st.markdown(f'<div class="metric-card"><h3 style="font-size:1.4rem">{batch_time/1000:.1f}s</h3><p>Total Time</p></div>', unsafe_allow_html=True)

        st.markdown("")

        # Sort: Rejected first, then Flagged, then Approved
        sort_order = {"Rejected": 0, "Flagged for Review": 1, "Approved": 2}
        sorted_results = sorted(all_results, key=lambda x: sort_order.get(x["status"], 3))

        st.markdown("### Detailed Results")

        # Status filter using radio (maintains state across rerenders)
        filter_options = [
            f"All ({total})",
            f"✅ Approved ({approved})",
            f"⚠️ Flagged ({flagged})",
            f"❌ Rejected ({rejected})",
        ]
        selected_filter = st.radio(
            "Filter by status",
            filter_options,
            index=0,
            horizontal=True,
            label_visibility="collapsed",
            key="result_status_filter",
        )

        # Apply filter
        if "Approved" in selected_filter:
            filtered_results = [r for r in sorted_results if r["status"] == "Approved"]
            filter_label = "approved"
        elif "Flagged" in selected_filter:
            filtered_results = [r for r in sorted_results if "Flagged" in r["status"]]
            filter_label = "flagged"
        elif "Rejected" in selected_filter:
            filtered_results = [r for r in sorted_results if r["status"] == "Rejected"]
            filter_label = "rejected"
        else:
            filtered_results = sorted_results
            filter_label = "all"

        if not filtered_results:
            st.info(f"No {filter_label} invoices in this batch.")

        for r in filtered_results:
            status = r["status"]
            icon = get_status_icon(status)
            badge = get_status_badge(status)
            time_ms = r.get("total_time_ms", 0)

            with st.expander(f"{icon} {r['file_name']} — {r['vendor_name']} — {r['invoice_number']} — {status}", expanded=(status != "Approved")):

                # Status + confidence + time
                conf_score = r["confidence_score"]
                conf_label = r["confidence_label"]
                conf_cls = "conf-high" if conf_label == "High" else ("conf-medium" if conf_label == "Medium" else "conf-low")
                st.markdown(
                    f"**Status:** {badge} &nbsp;&nbsp; **Confidence:** <span class='{conf_cls}'>{conf_score}% ({conf_label})</span>"
                    f" &nbsp;&nbsp; **Time:** {time_ms:.0f}ms",
                    unsafe_allow_html=True
                )

                # Action summary
                action = r.get("action_summary", "")
                if status == "Approved":
                    st.success("**Action:** No action needed. Invoice approved.")
                elif action and action != "No action needed":
                    st.info(f"**Suggested Action:** {action}")

                # PDF preview + Details side by side
                pdf_col, detail_col = st.columns([1, 2])

                with pdf_col:
                    st.markdown("**📄 Invoice Preview**")
                    # Try to render page 1 of the uploaded PDF as image
                    pdf_file_name = r.get("file_name", "")
                    # Check if the uploaded file is still available in the batch
                    pdf_rendered = False
                    for uf in uploaded_files:
                        if uf.name == pdf_file_name.replace("temp_", ""):
                            try:
                                import fitz as fitz_preview
                                uf.seek(0)
                                pdf_bytes = uf.read()
                                doc = fitz_preview.open(stream=pdf_bytes, filetype="pdf")
                                if len(doc) > 0:
                                    page = doc[0]
                                    pix = page.get_pixmap(dpi=120)
                                    img_bytes = pix.tobytes("png")
                                    st.image(img_bytes, use_container_width=True)
                                    pdf_rendered = True
                                doc.close()
                            except Exception:
                                pass
                            break
                    if not pdf_rendered:
                        st.caption("Preview not available")

                with detail_col:
                    # Details grid
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Invoice Details**")
                        st.text(f"Invoice #:    {r.get('invoice_number', 'N/A')}")
                        st.text(f"Date:         {r.get('invoice_date', 'N/A')}")
                        st.text(f"Due Date:     {r.get('due_date', 'N/A')}")
                        st.text(f"Amount:       {fmt_amount(r.get('invoice_amount'))}")
                        st.text(f"Tax:          {fmt_amount(r.get('tax_amount'))}")
                        st.text(f"Currency:     {r.get('currency', 'N/A')}")
                    with col2:
                        st.markdown("**Matching & Telemetry**")
                        st.text(f"PO #:         {r.get('po_number', 'N/A')}")
                        st.text(f"PO Amount:    {fmt_amount(r.get('po_amount'))}")
                        vd = r.get('variance_dollar')
                        vp = r.get('variance_percent')
                        st.text(f"Variance:     {fmt_amount(vd)} ({vp:+.1f}%)" if vd is not None and vp is not None else "Variance:     N/A")
                        st.text(f"Vendor:       {r.get('vendor_name', 'N/A')}")
                        st.text(f"Model:        {r.get('model_used', 'N/A')}")
                        st.text(f"Fallback:     Level {r.get('fallback_level', 0)}")

                # Validation audit trail
                st.markdown("**Validation Checks:**")
                render_check_log(r.get("check_log", []))

                # Failed checks summary for flagged/rejected
                if status != "Approved":
                    failed_checks = [c for c in r.get("check_log", []) if c.get("status") in ("flag", "reject")]
                    if failed_checks:
                        st.markdown("**❌ Failed Checks:**")
                        for fc in failed_checks:
                            ficon = "🔴" if fc["status"] == "reject" else "🟡"
                            st.markdown(f"{ficon} **{fc['check']}**: {fc['detail']}")

                # Confidence breakdown
                breakdown = r.get("confidence_breakdown", [])
                if breakdown:
                    st.markdown("**Confidence Breakdown:**")
                    parts = ["Base: 100"]
                    for label, delta in breakdown:
                        parts.append(f"{delta:+d} ({label})")
                    parts.append(f"= **{conf_score}%**")
                    st.markdown(" → ".join(parts))

                # Line items
                if r.get("line_items"):
                    st.markdown("**Line Items:**")
                    li_data = []
                    for li in r["line_items"]:
                        li_data.append({
                            "Description": li.get("description", ""),
                            "Qty": li.get("quantity", li.get("qty", "-")),
                            "Unit Price": fmt_amount(li.get("unit_price")),
                            "Amount": fmt_amount(li.get("amount")),
                        })
                    if li_data:
                        st.dataframe(pd.DataFrame(li_data), use_container_width=True, hide_index=True)

                # Email draft
                if r.get("email_type", "none") != "none" and status != "Approved" and r.get("email_body"):
                    st.markdown("**📧 Draft Email:**")
                    st.markdown(f"**To:** {r.get('email_to', 'N/A')} &nbsp; | &nbsp; **Subject:** {r.get('email_subject', 'N/A')}")
                    st.markdown(f'<div class="email-draft">{r.get("email_body", "")}</div>', unsafe_allow_html=True)

        # Export
        st.markdown("---")
        export_data = []
        for r in sorted_results:
            export_data.append({
                "File Name": r.get("file_name", ""),
                "Invoice #": r.get("invoice_number", ""),
                "Invoice Date": r.get("invoice_date", ""),
                "Due Date": r.get("due_date", ""),
                "Vendor Name": r.get("vendor_name", ""),
                "PO Number": r.get("po_number", ""),
                "Invoice Amount": r.get("invoice_amount", ""),
                "PO Amount": r.get("po_amount", ""),
                "Variance (%)": r.get("variance_percent", ""),
                "Status": r.get("status", ""),
                "Action": r.get("action_summary", ""),
                "Confidence": r.get("confidence_score", ""),
                "Processed At": r.get("processed_date", ""),
            })
        export_df = pd.DataFrame(export_data)
        csv = export_df.to_csv(index=False)
        st.download_button("📥 Export Results to CSV", csv,
                           file_name=f"invoice_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                           mime="text/csv")


# =========================================================
# PAGE 2: DASHBOARD
# =========================================================
elif page == "Dashboard":
    st.markdown('<div class="main-header"><h1>📊 Processing Dashboard</h1><p>History, audit trails, and data export</p></div>', unsafe_allow_html=True)

    history_df = load_history()
    render_learning_rules_widget()
    st.markdown("")
    if history_df.empty:
        st.info("No invoices processed yet. Go to Invoice Processor to get started.")
        st.stop()

    total = len(history_df)
    approved = len(history_df[history_df["status"] == "Approved"])
    flagged = len(history_df[history_df["status"].str.contains("Flagged", na=False)])
    rejected = len(history_df[history_df["status"] == "Rejected"])

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div class="metric-card"><h3>{total}</h3><p>Total Processed</p></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><h3 style="color:#2e7d32">{approved}</h3><p>Approved ({approved/total*100:.0f}%)</p></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><h3 style="color:#f57f17">{flagged}</h3><p>Flagged ({flagged/total*100:.0f}%)</p></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="metric-card"><h3 style="color:#c62828">{rejected}</h3><p>Rejected ({rejected/total*100:.0f}%)</p></div>', unsafe_allow_html=True)

    st.markdown("")
    st.markdown("### Filters")
    rule_count = len([r for r in load_learning_rules() if r.get("enabled", True)])
    st.caption(f"{rule_count} approved learning rule(s) active")
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        status_filter = st.selectbox("Status", ["All", "Approved", "Flagged for Review", "Rejected"])
    with fc2:
        vendor_names = ["All"] + sorted(history_df["vendor_name"].dropna().unique().tolist())
        vendor_filter = st.selectbox("Vendor", vendor_names)
    with fc3:
        sort_order = st.selectbox("Sort by", ["Newest First", "Oldest First", "Status (Critical First)"])

    filtered_df = history_df.copy()
    if status_filter != "All":
        if status_filter == "Flagged for Review":
            filtered_df = filtered_df[filtered_df["status"].str.contains("Flagged", na=False)]
        else:
            filtered_df = filtered_df[filtered_df["status"] == status_filter]
    if vendor_filter != "All":
        filtered_df = filtered_df[filtered_df["vendor_name"] == vendor_filter]

    if sort_order == "Newest First":
        filtered_df = filtered_df.sort_index(ascending=False)
    elif sort_order == "Oldest First":
        filtered_df = filtered_df.sort_index(ascending=True)
    elif sort_order == "Status (Critical First)":
        smap = {"Rejected": 0, "Flagged for Review": 1, "Approved": 2}
        filtered_df["_s"] = filtered_df["status"].map(smap).fillna(3)
        filtered_df = filtered_df.sort_values("_s").drop(columns=["_s"])

    st.markdown(f"### Results ({len(filtered_df)} records)")

    display_cols = ["file_name", "document_type", "invoice_number", "vendor_name", "po_number",
                    "invoice_amount", "po_amount", "variance_percent",
                    "status", "suggested_action", "confidence_score", "processed_date"]
    available_cols = [c for c in display_cols if c in filtered_df.columns]

    if available_cols:
        display_df = filtered_df[available_cols].copy()
        rename_map = {"file_name": "File", "invoice_number": "Invoice #", "vendor_name": "Vendor",
                      "document_type": "Doc Type", "po_number": "PO #", "invoice_amount": "Invoice Amt", "po_amount": "PO Amt",
                      "variance_percent": "Variance %", "status": "Status", "suggested_action": "Action",
                      "confidence_score": "Confidence", "processed_date": "Processed"}
        display_df = display_df.rename(columns=rename_map)
        st.dataframe(display_df, use_container_width=True, hide_index=True,
                     column_config={
                         "Invoice Amt": st.column_config.NumberColumn(format="₹%.2f"),
                         "PO Amt": st.column_config.NumberColumn(format="₹%.2f"),
                         "Variance %": st.column_config.NumberColumn(format="%.1f%%"),
                         "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
                     })

    # Audit detail view
    if "check_details" in filtered_df.columns:
        st.markdown("### Invoice Detail View")
        st.caption("Expand any invoice to see full validation audit trail, failed checks, and suggested actions.")
        for idx, row in filtered_df.iterrows():
            inv_status = row.get('status', '')
            label = f"{row.get('file_name', '')} — {row.get('invoice_number', '')} — {inv_status}"
            with st.expander(f"{get_status_icon(inv_status)} {label}"):

                # Status badge
                st.markdown(f"**Status:** {get_status_badge(inv_status)} &nbsp;&nbsp; **Confidence:** {row.get('confidence_score', 'N/A')}%", unsafe_allow_html=True)

                # PDF preview + Invoice details side by side
                pdf_col_d, details_col_d = st.columns([1, 2])

                with pdf_col_d:
                    st.markdown("**📄 Invoice Preview**")
                    pdf_file = row.get('file_name', '')
                    pdf_shown = False
                    pdf_bytes_d = None

                    # Try session state cache first
                    if "pdf_cache" in st.session_state and pdf_file in st.session_state["pdf_cache"]:
                        pdf_bytes_d = st.session_state["pdf_cache"][pdf_file]

                    if pdf_bytes_d:
                        try:
                            import fitz as fitz_dash
                            doc = fitz_dash.open(stream=pdf_bytes_d, filetype="pdf")
                            if len(doc) > 0:
                                page = doc[0]
                                pix = page.get_pixmap(dpi=120)
                                img_bytes = pix.tobytes("png")
                                st.image(img_bytes, use_container_width=True)
                                pdf_shown = True
                            doc.close()
                        except Exception:
                            pass

                    if not pdf_shown:
                        st.caption("PDF preview available after processing invoices in this session.")

                    # Download button
                    if pdf_bytes_d:
                        st.download_button("📥 Download PDF", pdf_bytes_d,
                                           file_name=pdf_file.replace("temp_", ""),
                                           mime="application/pdf",
                                           key=f"dl_pdf_{idx}")

                with details_col_d:
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        st.markdown("**Invoice Details**")
                        st.text(f"Invoice #:    {row.get('invoice_number', 'N/A')}")
                        st.text(f"Vendor:       {row.get('vendor_name', 'N/A')}")
                        st.text(f"Amount:       {fmt_amount(row.get('invoice_amount'))}")
                        if "document_type" in row:
                            st.text(f"Doc Type:     {row.get('document_type', 'N/A')}")
                    with dc2:
                        st.markdown("**PO Details**")
                        st.text(f"PO #:         {row.get('po_number', 'N/A')}")
                        st.text(f"PO Amount:    {fmt_amount(row.get('po_amount'))}")
                        if "po_currency" in row:
                            st.text(f"PO Currency:  {row.get('po_currency', 'N/A')}")
                        vp = row.get('variance_percent')
                        st.text(f"Variance:     {vp}%" if vp and str(vp) != '' else "Variance:     N/A")

                # Validation checks
                st.markdown("**Validation Checks:**")
                checks = []
                try:
                    checks = json.loads(row.get("check_details", "[]"))
                    if checks:
                        render_check_log(checks)

                        # Show failed checks summary for flagged/rejected
                        if inv_status != "Approved":
                            failed = [c for c in checks if c.get("status") in ("flag", "reject")]
                            if failed:
                                st.markdown("**❌ Failed Checks:**")
                                for fc in failed:
                                    icon = "🔴" if fc["status"] == "reject" else "🟡"
                                    st.markdown(f"{icon} **{fc['check']}**: {fc['detail']}")
                    else:
                        st.caption("No detailed check data available.")
                except:
                    st.caption("Could not parse check details.")

                # Remark + Action
                st.markdown(f"**Remark:** {row.get('remark', 'N/A')}")
                action = row.get('suggested_action', 'N/A')
                if action and action != "No action needed. Invoice approved.":
                    st.info(f"**Suggested Action:** {action}")
                else:
                    st.success("**Action:** No action needed. Invoice approved.")

                st.markdown("---")
                with st.container():
                    st.markdown("**Teach System**")
                    st.caption("Reviewer feedback is converted into a suggested rule. Save only rules you want applied to future invoices.")
                    feedback_key = f"learn_feedback_{idx}"
                    suggestion_key = f"learn_suggestion_{idx}"
                    feedback = st.text_area(
                        "What should the system learn from this invoice?",
                        key=feedback_key,
                        placeholder="Example: Delta Logistics Pvt should be treated as Delta Logistics.",
                    )
                    learn_col1, learn_col2 = st.columns([1, 1])
                    with learn_col1:
                        if st.button("Suggest Rule", key=f"suggest_rule_{idx}", disabled=not feedback.strip()):
                            api_key_dash = st.secrets.get("GROQ_API_KEY", "")
                            invoice_context = build_invoice_context(row, checks)
                            st.session_state[suggestion_key] = suggest_learning_rule(feedback, invoice_context, api_key_dash)
                    with learn_col2:
                        if st.button("Clear Suggestion", key=f"clear_rule_{idx}"):
                            st.session_state.pop(suggestion_key, None)

                    if suggestion_key in st.session_state:
                        suggested_rule = st.session_state[suggestion_key]
                        st.markdown("**Suggested Rule**")
                        st.info(describe_rule(suggested_rule))
                        rule_json = st.text_area(
                            "Review/edit rule JSON before saving",
                            value=json.dumps(suggested_rule, indent=2),
                            key=f"rule_json_{idx}",
                            height=180,
                        )
                        if st.button("Save Approved Rule", key=f"save_rule_{idx}", type="primary"):
                            try:
                                saved = save_learning_rule(json.loads(rule_json))
                                mark_rule_created_this_session()
                                st.success(f"Saved learning rule {saved['id']}: {describe_rule(saved)}")
                                st.session_state.pop(suggestion_key, None)
                            except json.JSONDecodeError:
                                st.error("Rule JSON is not valid. Fix the JSON before saving.")

                # Email draft for flagged/rejected
                if inv_status != "Approved":
                    vendor = row.get('vendor_name', 'Vendor')
                    inv_num = row.get('invoice_number', 'N/A')
                    vendor_email = row.get('vendor_email', '')
                    remark_text = row.get('remark', '')

                    # Generate contextual email
                    subject = f"Invoice Review Required - {inv_num}"
                    if "duplicate" in str(remark_text).lower():
                        subject = f"Duplicate Invoice Notice - {inv_num}"
                    elif "not found" in str(remark_text).lower() and "vendor" in str(remark_text).lower():
                        subject = f"Unknown Vendor Alert - {vendor}"
                    elif "not approved" in str(remark_text).lower():
                        subject = f"Unapproved Vendor - {vendor}"
                    elif "variance" in str(remark_text).lower() or "exceeds" in str(remark_text).lower():
                        subject = f"Amount Discrepancy - {inv_num}"
                    elif "closed" in str(remark_text).lower():
                        subject = f"Invoice Against Closed PO - {inv_num}"
                    elif "credit" in str(remark_text).lower():
                        subject = f"Credit Note Received - {inv_num}"

                    email_body = f"Hello,\n\nInvoice #{inv_num} from {vendor} has been {inv_status.lower()} during automated processing.\n\nReason: {remark_text}\n\nPlease review and take the necessary action.\n\nRegards,\nAccounts Payable Team"

                    st.markdown("**📧 Suggested Email:**")
                    to_addr = vendor_email if vendor_email and str(vendor_email) != 'nan' and vendor_email != '' else "ap-team@company.com"
                    st.markdown(f"**To:** {to_addr} &nbsp; | &nbsp; **Subject:** {subject}")
                    st.markdown(f'<div class="email-draft">{email_body}</div>', unsafe_allow_html=True)

    st.markdown("---")
    csv = filtered_df.to_csv(index=False)
    st.download_button("📥 Export to CSV", csv,
                       file_name=f"invoice_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                       mime="text/csv")

    st.markdown("---")
    with st.expander("⚠️ Danger Zone"):
        st.warning("This will permanently delete all processing history.")
        if st.button("🗑️ Clear All History", type="secondary"):
            pd.DataFrame(columns=[
                "invoice_number", "vendor_name", "po_number", "invoice_amount",
                "document_id", "document_type", "tax_amount", "currency", "po_currency", "po_vendor_name", "po_date",
                "po_amount", "variance_dollar", "variance_percent", "cumulative_invoiced",
                "status", "remark", "suggested_action", "confidence_score",
                "overall_extraction_confidence", "ocr_confidence",
                "vendor_email", "contact_person", "file_name", "processed_date", "check_details"
            ]).to_csv(HISTORY_PATH, index=False)
            st.success("History cleared. Refresh the page.")
            st.rerun()


# =========================================================
# PAGE 3: LEARNING RULES
# =========================================================
elif page == "Learning Rules":
    render_learning_rules_page()
