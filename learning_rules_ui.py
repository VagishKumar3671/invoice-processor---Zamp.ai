"""
learning_rules_ui.py - Streamlit management UI for approved learning rules.

This module keeps rule administration separate from invoice processing so the
learning engine can evolve without changing the core upload/validation flow.
"""

import json
from datetime import datetime

import pandas as pd
import streamlit as st

from learning import (
    delete_learning_rule,
    describe_rule,
    load_learning_rules,
    update_learning_rule_enabled,
)


RULE_CREATED_SESSION_KEY = "learning_rules_created_session"


def filter_rules(rules, search_text="", rule_type="All", status="All"):
    search = str(search_text or "").strip().lower()
    filtered = []
    for rule in rules:
        if rule_type != "All" and rule.get("type", "general_note") != rule_type:
            continue
        enabled = bool(rule.get("enabled", True))
        if status == "Enabled" and not enabled:
            continue
        if status == "Disabled" and enabled:
            continue
        searchable = " ".join(
            str(value)
            for value in [
                rule.get("id", ""),
                rule.get("name", ""),
                rule.get("type", ""),
                rule.get("match_text", ""),
                rule.get("vendor_name", ""),
                rule.get("canonical_value", ""),
                rule.get("currency", ""),
                rule.get("action", ""),
                rule.get("note", ""),
                rule.get("reason", ""),
                describe_rule(rule),
            ]
        ).lower()
        if search and search not in searchable:
            continue
        filtered.append(rule)
    return filtered


def learning_rule_stats(rules):
    total = len(rules)
    active = len([rule for rule in rules if rule.get("enabled", True)])
    disabled = total - active
    used_rules = [rule for rule in rules if int(rule.get("usage_count", 0) or 0) > 0]
    most_used = None
    if used_rules:
        most_used = max(used_rules, key=lambda rule: int(rule.get("usage_count", 0) or 0))
    return {
        "total": total,
        "active": active,
        "disabled": disabled,
        "created_this_session": int(st.session_state.get(RULE_CREATED_SESSION_KEY, 0) or 0),
        "most_used": most_used,
    }


def mark_rule_created_this_session():
    st.session_state[RULE_CREATED_SESSION_KEY] = int(st.session_state.get(RULE_CREATED_SESSION_KEY, 0) or 0) + 1


def render_learning_rules_widget():
    rules = load_learning_rules()
    stats = learning_rule_stats(rules)
    st.markdown("### Learning Rules")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(f'<div class="metric-card"><h3>{stats["total"]}</h3><p>Total Rules</p></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><h3 style="color:#2e7d32">{stats["active"]}</h3><p>Active Rules</p></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><h3 style="color:#777">{stats["disabled"]}</h3><p>Disabled Rules</p></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="metric-card"><h3>{stats["created_this_session"]}</h3><p>This Session</p></div>', unsafe_allow_html=True)
    with c5:
        most = stats["most_used"]
        label = "None"
        if most:
            label = f'{most.get("id", "N/A")} ({most.get("usage_count", 0)})'
        st.markdown(f'<div class="metric-card"><h3 style="font-size:1.1rem">{label}</h3><p>Most Triggered</p></div>', unsafe_allow_html=True)


def render_learning_rules_page():
    st.markdown(
        '<div class="main-header"><h1>Learning Rules</h1><p>View, disable, delete, and audit human-approved system learning</p></div>',
        unsafe_allow_html=True,
    )

    rules = load_learning_rules()
    render_learning_rules_widget()
    st.markdown("")

    if not rules:
        st.info("No learning rules have been saved yet. Use Teach System in the Dashboard to create approved rules.")
        return

    st.markdown("### Search and Filter")
    unique_types = sorted({rule.get("type", "general_note") for rule in rules})
    f1, f2, f3 = st.columns([2, 1, 1])
    with f1:
        search_text = st.text_input("Search rules", placeholder="Search by rule ID, description, vendor, match text, action...")
    with f2:
        rule_type = st.selectbox("Rule Type", ["All"] + unique_types)
    with f3:
        status = st.selectbox("Status", ["All", "Enabled", "Disabled"])

    filtered = filter_rules(rules, search_text, rule_type, status)
    st.markdown(f"### Rules ({len(filtered)} shown)")

    if not filtered:
        st.warning("No rules match the selected filters.")
        return

    table_rows = [_rule_table_row(rule) for rule in filtered]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    st.markdown("### Manage Rules")
    for rule in filtered:
        _render_rule_card(rule)


def _render_rule_card(rule):
    rule_id = str(rule.get("id", ""))
    title = f'{_status_dot(rule)} {rule_id or "No ID"} | {rule.get("type", "general_note")} | {_primary_trigger(rule)}'
    with st.container(border=True):
        top_cols = st.columns([3, 1, 1])
        with top_cols[0]:
            st.markdown(f"**{title}**")
            st.caption(describe_rule(rule))
        with top_cols[1]:
            current_enabled = bool(rule.get("enabled", True))
            new_enabled = st.toggle(
                "Enabled",
                value=current_enabled,
                key=f"learning_rule_enabled_{rule_id}",
            )
            if new_enabled != current_enabled:
                update_learning_rule_enabled(rule_id, new_enabled)
                st.toast(f"Rule {rule_id} {'enabled' if new_enabled else 'disabled'}")
                st.rerun()
        with top_cols[2]:
            if st.button("Delete", key=f"delete_rule_{rule_id}", type="secondary", use_container_width=True):
                if delete_learning_rule(rule_id):
                    st.toast(f"Deleted rule {rule_id}")
                    st.rerun()
                st.error("Could not delete the rule.")

        with st.expander("View Rule Details"):
            d1, d2 = st.columns(2)
            with d1:
                st.text(f"Rule ID:        {rule_id or 'N/A'}")
                st.text(f"Rule Type:      {rule.get('type', 'general_note')}")
                st.text(f"Source:         {_source_label(rule.get('source', ''))}")
                st.text(f"Status:         {'Enabled' if rule.get('enabled', True) else 'Disabled'}")
                st.text(f"Created At:     {rule.get('created_at', 'N/A')}")
                st.text(f"Last Used At:   {rule.get('last_used_at', 'Never')}")
            with d2:
                st.text(f"Trigger:        {_primary_trigger(rule)}")
                st.text(f"Action:         {_rule_action(rule)}")
                st.text(f"Usage Count:    {rule.get('usage_count', 0)}")
                st.text(f"Viewed At:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            st.markdown("**Rule Configuration**")
            st.code(json.dumps(rule, indent=2, default=str), language="json")


def _rule_table_row(rule):
    return {
        "Rule ID": rule.get("id", ""),
        "Type": rule.get("type", "general_note"),
        "Description": describe_rule(rule),
        "Match Text / Trigger": _primary_trigger(rule),
        "Action": _rule_action(rule),
        "Source": _source_label(rule.get("source", "")),
        "Creation Date": rule.get("created_at", ""),
        "Status": "Enabled" if rule.get("enabled", True) else "Disabled",
        "Usage Count": rule.get("usage_count", 0),
        "Last Used": rule.get("last_used_at", ""),
    }


def _primary_trigger(rule):
    for key in ["match_text", "vendor_name", "currency", "canonical_value"]:
        value = rule.get(key)
        if value:
            return str(value)
    return rule.get("note", "N/A")


def _rule_action(rule):
    action = rule.get("action")
    if action:
        return str(action)
    rule_type = rule.get("type")
    if rule_type == "credit_pattern":
        return "Treat as credit note"
    if rule_type == "credit_note_policy":
        return "Approve matching credit note"
    if rule_type == "vendor_alias":
        return f"Map vendor to {rule.get('canonical_value', '')}"
    if rule_type == "po_mapping":
        return f"Map PO to {rule.get('canonical_value', '')}"
    if rule_type == "tax_currency_exception":
        return "Skip GST tax validation"
    return "Audit note only"


def _source_label(source):
    source = str(source or "").strip().lower()
    labels = {
        "reviewer_feedback": "User Feedback",
        "llm_suggestion": "AI Suggestion",
        "heuristic": "System Generated",
        "system": "System Generated",
    }
    return labels.get(source, source.replace("_", " ").title() if source else "Unknown")


def _status_dot(rule):
    return "Active" if rule.get("enabled", True) else "Disabled"
