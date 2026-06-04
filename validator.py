"""
validator.py - Invoice Validation Engine (v3)

All checks driven by check_config dict (enable/disable + thresholds).
Each check respects its enabled flag. Thresholds are per-check.
"""

import pandas as pd
from fuzzywuzzy import fuzz
from datetime import datetime, timedelta
from extractor import parse_amount
import json
import copy

DEFAULT_CHECK_CONFIG = {
    "invoice_date": {"enabled": True, "label": "Invoice Date Sanity", "description": "Flag future-dated or stale invoices",
        "params": {"stale_days": {"value": 180, "min": 30, "max": 1095, "step": 30, "label": "Stale threshold (days)"}}},
    "critical_fields": {"enabled": True, "label": "Critical Fields Check", "description": "Ensure invoice #, vendor, amount present", "params": {}},
    "credit_note": {"enabled": True, "label": "Credit Note Detection", "description": "Detect credit notes (negative amounts, CN- prefix)", "params": {}},
    "duplicate": {"enabled": True, "label": "Duplicate Detection", "description": "Reject already-processed invoices",
        "params": {"similarity_threshold": {"value": 90, "min": 70, "max": 100, "step": 5, "label": "Vendor match % for dup"}}},
    "vendor": {"enabled": True, "label": "Vendor Verification", "description": "Verify vendor in master + approval status",
        "params": {"match_threshold": {"value": 85, "min": 60, "max": 100, "step": 5, "label": "Vendor fuzzy match %"}}},
    "po_match": {"enabled": True, "label": "PO Matching", "description": "Match invoice to PO (direct + fuzzy + closed)",
        "params": {"fuzzy_vendor_threshold": {"value": 80, "min": 60, "max": 100, "step": 5, "label": "Fuzzy PO vendor %"},
                   "fuzzy_amount_tolerance": {"value": 20, "min": 5, "max": 50, "step": 5, "label": "Fuzzy PO amount %"}}},
    "amount": {"enabled": True, "label": "Amount Comparison", "description": "Compare invoice vs PO amount within tolerance",
        "params": {"tolerance_pct": {"value": 5, "min": 1, "max": 15, "step": 1, "label": "Amount tolerance %"}}},
    "cumulative": {"enabled": True, "label": "Cumulative Invoicing", "description": "Track total invoiced per PO across runs",
        "params": {"tolerance_pct": {"value": 5, "min": 1, "max": 15, "step": 1, "label": "Cumulative tolerance %"}}},
    "tax_rate": {"enabled": True, "label": "Tax Rate Verification", "description": "Verify tax rate matches expected GST %",
        "params": {"expected_rate": {"value": 18, "min": 0, "max": 28, "step": 1, "label": "Expected tax rate %"},
                   "variance_pct": {"value": 2, "min": 1, "max": 10, "step": 1, "label": "Tax variance tolerance %"}}},
    "currency": {"enabled": True, "label": "Currency Validation", "description": "Verify invoice currency is in allowed list",
        "params": {}},
}

def get_default_config():
    return copy.deepcopy(DEFAULT_CHECK_CONFIG)

def _make_check(name, status, detail, data=None):
    return {"check": name, "status": status, "detail": detail, "data": data or {}}

def _get_param(cc, key, param, fallback):
    try: return cc[key]["params"][param]["value"]
    except: return fallback

def _is_enabled(cc, key):
    try: return cc[key]["enabled"]
    except: return True

def _format_amount(amount):
    if amount is None:
        return "N/A"
    sign = "-" if amount < 0 else ""
    return f"{sign}₹{abs(amount):,.2f}"

def _is_credit_note(extracted_data, invoice_amount):
    if invoice_amount is not None and invoice_amount < 0:
        return True
    inv_num = str(extracted_data.get("invoice_number", "")).upper().strip()
    if inv_num.startswith("CN-") or inv_num.startswith("CN/") or inv_num.startswith("CREDIT"):
        return True
    for li in extracted_data.get("line_items", []):
        d = str(li.get("description", "")).lower()
        a = li.get("amount")
        if "credit" in d or "refund" in d or "reversal" in d:
            return True
        if a is not None and isinstance(a, (int, float)) and a < 0:
            return True
    return False

def _normalize_credit_note_values(results):
    if results["invoice_amount"] is not None:
        results["invoice_amount"] = -abs(results["invoice_amount"])
    if results["tax_amount"] is not None:
        results["tax_amount"] = -abs(results["tax_amount"])
    for li in results.get("line_items", []):
        if isinstance(li.get("amount"), (int, float)):
            li["amount"] = -abs(li["amount"])

def run_all_checks(extracted_data, metadata, po_master_df, vendor_master_df, history_df, check_config=None):
    if check_config is None:
        check_config = get_default_config()

    tolerance_pct = _get_param(check_config, "amount", "tolerance_pct", 5.0)
    stale_days = _get_param(check_config, "invoice_date", "stale_days", 180)

    results = {
        "invoice_number": extracted_data.get("invoice_number", "NOT_FOUND"),
        "invoice_date": extracted_data.get("invoice_date", "NOT_FOUND"),
        "due_date": extracted_data.get("due_date", "NOT_FOUND"),
        "vendor_name": extracted_data.get("vendor_name", "NOT_FOUND"),
        "vendor_email": extracted_data.get("vendor_email", "NOT_FOUND"),
        "po_number": extracted_data.get("po_number", "NOT_FOUND"),
        "invoice_amount": parse_amount(extracted_data.get("total_amount")),
        "po_amount": None, "variance_dollar": None, "variance_percent": None,
        "cumulative_invoiced": None, "status": "Approved", "remark": "",
        "suggested_action": "No action needed", "confidence_score": 100,
        "confidence_label": "High", "confidence_breakdown": [],
        "vendor_email_resolved": None, "contact_person": None,
        "file_name": metadata.get("file_name", "unknown"),
        "document_id": metadata.get("document_id"),
        "document_type": metadata.get("document_type", "unknown"),
        "overall_extraction_confidence": metadata.get("overall_extraction_confidence"),
        "ocr_confidence": metadata.get("ocr_confidence"),
        "processed_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "extraction_method": metadata.get("extraction_method", "text"),
        "is_scanned": metadata.get("is_scanned", False),
        "line_items": extracted_data.get("line_items", []),
        "tax_amount": parse_amount(extracted_data.get("tax_amount")),
        "currency": extracted_data.get("currency", "NOT_FOUND"),
        "po_currency": None,
        "po_vendor_name": None,
        "po_date": None,
        "check_log": [],
        "active_checks": {k: v["enabled"] for k, v in check_config.items()},
    }

    all_remarks = []
    check_statuses = []
    currency_value = str(extracted_data.get("currency", "NOT_FOUND")).strip().upper()
    credit_note_auto_approve = (
        extracted_data.get("_learned_credit_note_action") == "approve"
        and _is_credit_note(extracted_data, results["invoice_amount"])
    )

    if metadata.get("extraction_error"):
        results["check_log"].append(_make_check("Extraction", "reject", metadata["extraction_error"]))
        results["status"] = "Flagged for Review"
        results["remark"] = metadata["extraction_error"]
        results["confidence_score"] = 10
        results["confidence_label"] = "Low"
        results["confidence_breakdown"] = [("Extraction failure", -90)]
        results["suggested_action"] = "Manual processing required"
        return results

    for learned_check in metadata.get("learned_rule_checks", []):
        results["check_log"].append(learned_check)

    if metadata.get("extraction_method") == "ocr" and metadata.get("ocr_confidence") is not None:
        c = check_ocr_quality(metadata.get("ocr_confidence"))
        results["check_log"].append(c)
        if c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])

    if metadata.get("overall_extraction_confidence") is not None:
        c = check_extraction_confidence(metadata.get("overall_extraction_confidence"))
        results["check_log"].append(c)
        if c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])

    # CHECK 0: Invoice date
    if _is_enabled(check_config, "invoice_date"):
        c = check_invoice_date(extracted_data.get("invoice_date"), stale_days=stale_days)
        if credit_note_auto_approve and c["status"] == "flag" and "days old" in c["detail"]:
            c = _make_check("Invoice Date Check", "skip", "Skipped stale-date flag by learned credit note policy.",
                            c.get("data", {}))
        results["check_log"].append(c)
        if c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
        elif c["status"] == "info": all_remarks.append(c["detail"])
    else:
        results["check_log"].append(_make_check("Invoice Date Check", "skip", "Disabled by user"))

    # CHECK 1: Critical fields
    if _is_enabled(check_config, "critical_fields"):
        c = check_critical_fields(extracted_data)
        results["check_log"].append(c)
        if c["status"] == "reject": check_statuses.append("Rejected"); all_remarks.append(c["detail"])
        elif c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
    else:
        results["check_log"].append(_make_check("Critical Fields", "skip", "Disabled by user"))

    # Credit note detection
    invoice_amount = results["invoice_amount"]
    if _is_enabled(check_config, "credit_note"):
        if _is_credit_note(extracted_data, invoice_amount):
            _normalize_credit_note_values(results)
            invoice_amount = results["invoice_amount"]
            ad = _format_amount(invoice_amount)
            if extracted_data.get("_learned_credit_note_action") == "approve" and "Rejected" not in check_statuses:
                reason = extracted_data.get("_learned_credit_note_reason") or "Reviewer-approved credit note policy"
                cn = _make_check("Credit Note Detection", "pass",
                                 f"Credit note auto-approved by learned rule ({ad}). {reason}",
                                 {"amount": invoice_amount, "learned_action": "approve"})
                results["check_log"].append(cn)
                results["status"] = "Approved"
                results["remark"] = cn["detail"]
                results = calculate_confidence(results, extracted_data, metadata, False); return results
            cn = _make_check("Credit Note Detection", "flag", f"Credit note detected ({ad}). Requires manual AP handling.",
                             {"amount": invoice_amount})
            results["check_log"].append(cn); check_statuses.append("Flagged"); all_remarks.append(cn["detail"])
            results["status"] = "Flagged for Review"; results["remark"] = " | ".join(all_remarks)
            results = calculate_confidence(results, extracted_data, metadata, False); return results
    else:
        results["check_log"].append(_make_check("Credit Note Detection", "skip", "Disabled by user"))

    # CHECK 2: Duplicate
    if _is_enabled(check_config, "duplicate"):
        dup_t = _get_param(check_config, "duplicate", "similarity_threshold", 90)
        if extracted_data.get("invoice_number") != "NOT_FOUND":
            c = check_duplicate(extracted_data.get("invoice_number"), extracted_data.get("vendor_name"), history_df, dup_t)
            results["check_log"].append(c)
            if c["status"] == "reject":
                check_statuses.append("Rejected"); all_remarks.append(c["detail"])
                results["status"] = "Rejected"; results["remark"] = " | ".join(all_remarks)
                results = calculate_confidence(results, extracted_data, metadata, False); return results
            elif c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
        else:
            results["check_log"].append(_make_check("Duplicate Detection", "skip", "No invoice number"))
    else:
        results["check_log"].append(_make_check("Duplicate Detection", "skip", "Disabled by user"))

    # CHECK 3: Vendor
    if _is_enabled(check_config, "vendor"):
        vt = _get_param(check_config, "vendor", "match_threshold", 85)
        if extracted_data.get("vendor_name") != "NOT_FOUND":
            c, vi = check_vendor(extracted_data.get("vendor_name"), vendor_master_df, vt)
            results["check_log"].append(c)
            if c["status"] == "reject": check_statuses.append("Rejected"); all_remarks.append(c["detail"])
            elif c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
            if vi: results["vendor_email_resolved"] = vi.get("vendor_email"); results["contact_person"] = vi.get("contact_person")
        else:
            results["check_log"].append(_make_check("Vendor Verification", "skip", "No vendor name"))
    else:
        results["check_log"].append(_make_check("Vendor Verification", "skip", "Disabled by user"))

    # CHECK 4: PO matching
    po_matched = False; po_matched_fuzzy = False; matched_po_number = None; matched_po_amount = None
    matched_po_vendor = None; matched_po_currency = None; matched_po_date = None
    if _is_enabled(check_config, "po_match"):
        fvt = _get_param(check_config, "po_match", "fuzzy_vendor_threshold", 80)
        fat = _get_param(check_config, "po_match", "fuzzy_amount_tolerance", 20)
        c, pmi = check_po_match(extracted_data.get("po_number"), extracted_data.get("vendor_name"),
                                parse_amount(extracted_data.get("total_amount")), po_master_df, fvt, fat)
        results["check_log"].append(c)
        if c["status"] == "reject": check_statuses.append("Rejected"); all_remarks.append(c["detail"])
        elif c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
        if pmi:
            po_matched = True; po_matched_fuzzy = pmi.get("fuzzy_matched", False)
            matched_po_number = pmi.get("po_number"); matched_po_amount = pmi.get("po_amount")
            matched_po_vendor = pmi.get("po_vendor_name"); matched_po_currency = pmi.get("po_currency"); matched_po_date = pmi.get("po_date")
            results["po_number"] = matched_po_number; results["po_amount"] = matched_po_amount
            results["po_vendor_name"] = matched_po_vendor; results["po_currency"] = matched_po_currency; results["po_date"] = matched_po_date
    else:
        results["check_log"].append(_make_check("PO Matching", "skip", "Disabled by user"))

    if po_matched and matched_po_vendor:
        c = check_vendor_po_match(extracted_data.get("vendor_name"), matched_po_vendor)
        results["check_log"].append(c)
        if c["status"] == "reject": check_statuses.append("Rejected"); all_remarks.append(c["detail"])
        elif c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
    else:
        results["check_log"].append(_make_check("Vendor-PO Match", "skip", "PO not matched or PO vendor unavailable"))

    if po_matched and matched_po_date:
        c = check_invoice_after_po_date(extracted_data.get("invoice_date"), matched_po_date)
        results["check_log"].append(c)
        if c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
    else:
        results["check_log"].append(_make_check("Invoice Date vs PO Date", "skip", "PO not matched or PO date unavailable"))

    # CHECK 5: Amount
    if _is_enabled(check_config, "amount"):
        if po_matched and invoice_amount is not None and matched_po_amount is not None:
            c, vi = check_amount(invoice_amount, matched_po_amount, tolerance_pct)
            results["check_log"].append(c)
            if c["status"] == "reject": check_statuses.append("Rejected"); all_remarks.append(c["detail"])
            elif c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
            elif c["detail"]: all_remarks.append(c["detail"])
            results["variance_dollar"] = vi.get("variance_dollar"); results["variance_percent"] = vi.get("variance_percent")
        else:
            results["check_log"].append(_make_check("Amount Comparison", "skip", "PO not matched or amount missing"))
    else:
        results["check_log"].append(_make_check("Amount Comparison", "skip", "Disabled by user"))

    # CHECK 6: Cumulative
    if _is_enabled(check_config, "cumulative"):
        ct = _get_param(check_config, "cumulative", "tolerance_pct", tolerance_pct)
        if po_matched and matched_po_number and invoice_amount is not None:
            c, ci = check_cumulative(matched_po_number, invoice_amount, matched_po_amount, history_df, ct)
            results["check_log"].append(c)
            if c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
            elif c["detail"]: all_remarks.append(c["detail"])
            results["cumulative_invoiced"] = ci.get("cumulative_total")
        else:
            results["check_log"].append(_make_check("Cumulative Invoicing", "skip", "PO not matched"))
    else:
        results["check_log"].append(_make_check("Cumulative Invoicing", "skip", "Disabled by user"))

    # CHECK 7: Currency Validation
    if _is_enabled(check_config, "currency"):
        allowed = check_config.get("currency", {}).get("_allowed_currencies", ALLOWED_CURRENCIES)
        c = check_currency(extracted_data.get("currency", "NOT_FOUND"), allowed)
        results["check_log"].append(c)
        if c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
        elif c["status"] == "reject": check_statuses.append("Rejected"); all_remarks.append(c["detail"])
    else:
        results["check_log"].append(_make_check("Currency Check", "skip", "Disabled by user"))

    if po_matched and matched_po_currency:
        c = check_currency_match(extracted_data.get("currency", "NOT_FOUND"), matched_po_currency)
        results["check_log"].append(c)
        if c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
    else:
        results["check_log"].append(_make_check("Currency Match", "skip", "PO not matched or PO currency unavailable"))

    # CHECK 8: Tax Rate Verification
    if _is_enabled(check_config, "tax_rate"):
        expected_rate = _get_param(check_config, "tax_rate", "expected_rate", 18)
        tax_variance = _get_param(check_config, "tax_rate", "variance_pct", 2)
        learned_skip_reason = extracted_data.get("_learned_skip_tax_rate_reason")
        if learned_skip_reason:
            c = _make_check("Tax Rate Check", "skip",
                            f"Skipped by learned rule: {learned_skip_reason}",
                            {"source": "learning_rule"})
        elif currency_value not in ("", "NOT_FOUND", "INR"):
            c = _make_check("Tax Rate Check", "skip",
                            f"Skipped GST check because invoice currency is {currency_value}.",
                            {"currency": currency_value})
        else:
            c = check_tax_rate(results.get("tax_amount"), invoice_amount, expected_rate, tax_variance)
        results["check_log"].append(c)
        if c["status"] == "flag": check_statuses.append("Flagged"); all_remarks.append(c["detail"])
        elif c["status"] == "reject": check_statuses.append("Rejected"); all_remarks.append(c["detail"])
    else:
        results["check_log"].append(_make_check("Tax Rate Check", "skip", "Disabled by user"))

    if "Rejected" in check_statuses: results["status"] = "Rejected"
    elif "Flagged" in check_statuses: results["status"] = "Flagged for Review"
    else: results["status"] = "Approved"
    results["remark"] = " | ".join(all_remarks) if all_remarks else "All checks passed."
    results = calculate_confidence(results, extracted_data, metadata, po_matched_fuzzy)
    return results

# =========================================================
# INDIVIDUAL CHECKS
# =========================================================
def check_invoice_date(invoice_date_str, stale_days=180):
    if invoice_date_str == "NOT_FOUND" or not invoice_date_str:
        return _make_check("Invoice Date Check", "skip", "No invoice date extracted")
    try: inv_date = datetime.strptime(invoice_date_str, "%Y-%m-%d")
    except ValueError: return _make_check("Invoice Date Check", "info", f"Could not parse date '{invoice_date_str}'.")
    today = datetime.now()
    if inv_date > today + timedelta(days=1):
        return _make_check("Invoice Date Check", "flag", f"Invoice date ({invoice_date_str}) is in the future.",
                           {"days_ahead": (inv_date - today).days})
    days_old = (today - inv_date).days
    if days_old > stale_days:
        return _make_check("Invoice Date Check", "flag",
                           f"Invoice is {days_old} days old. Exceeds {stale_days}-day threshold.",
                           {"days_old": days_old, "threshold": stale_days})
    if days_old > 60:
        return _make_check("Invoice Date Check", "info", f"Invoice is {days_old} days old.", {"days_old": days_old})
    return _make_check("Invoice Date Check", "pass", f"Invoice dated {invoice_date_str} ({days_old} days ago)")

def check_ocr_quality(ocr_confidence, threshold=0.65):
    try:
        score = float(ocr_confidence)
    except (TypeError, ValueError):
        return _make_check("OCR Quality", "flag", "OCR confidence unavailable. Manual review required.",
                           {"error_code": "LOW_OCR_CONFIDENCE", "validation_type": "ocr_quality"})
    if score < threshold:
        return _make_check("OCR Quality", "flag", f"OCR confidence {score:.2f} below {threshold:.2f}. Manual review required.",
                           {"error_code": "LOW_OCR_CONFIDENCE", "validation_type": "ocr_quality", "score": score})
    return _make_check("OCR Quality", "pass", f"OCR confidence {score:.2f} is acceptable.", {"score": score})

def check_extraction_confidence(overall_confidence, threshold=0.70):
    try:
        score = float(overall_confidence)
    except (TypeError, ValueError):
        return _make_check("Extraction Confidence", "flag", "Extraction confidence unavailable. Manual review required.",
                           {"error_code": "LOW_EXTRACTION_CONFIDENCE", "validation_type": "extraction_confidence"})
    if score < threshold:
        return _make_check("Extraction Confidence", "flag", f"Extraction confidence {score:.2f} below {threshold:.2f}. Manual review required.",
                           {"error_code": "LOW_EXTRACTION_CONFIDENCE", "validation_type": "extraction_confidence", "score": score})
    return _make_check("Extraction Confidence", "pass", f"Extraction confidence {score:.2f} is acceptable.", {"score": score})

def check_critical_fields(extracted_data):
    missing = []
    if extracted_data.get("invoice_number") == "NOT_FOUND": missing.append("invoice number")
    if extracted_data.get("vendor_name") == "NOT_FOUND": missing.append("vendor name")
    if extracted_data.get("total_amount") == "NOT_FOUND" or parse_amount(extracted_data.get("total_amount")) is None: missing.append("total amount")
    if not missing: return _make_check("Critical Fields", "pass", "All critical fields present")
    if "total amount" in missing:
        return _make_check("Critical Fields", "reject", f"Missing: {', '.join(missing)}. Cannot process.", {"missing": missing})
    return _make_check("Critical Fields", "flag", f"Missing: {', '.join(missing)}.", {"missing": missing})

def check_duplicate(invoice_number, vendor_name, history_df, similarity_threshold=90):
    if history_df.empty or invoice_number == "NOT_FOUND":
        return _make_check("Duplicate Detection", "pass", "No duplicates found")
    for _, row in history_df.iterrows():
        if str(row.get("invoice_number", "")).strip().upper() == str(invoice_number).strip().upper():
            if vendor_name != "NOT_FOUND" and row.get("vendor_name"):
                sim = fuzz.ratio(str(vendor_name).lower().strip(), str(row["vendor_name"]).lower().strip())
                if sim >= similarity_threshold:
                    return _make_check("Duplicate Detection", "reject",
                        f"Duplicate: {invoice_number} from {vendor_name} processed on {row.get('processed_date', '?')} ({row.get('status', '?')}).",
                        {"match_similarity": sim, "prev_date": row.get("processed_date", "")})
            elif vendor_name == "NOT_FOUND":
                return _make_check("Duplicate Detection", "flag", f"Possible duplicate: {invoice_number} matches history.")
    return _make_check("Duplicate Detection", "pass", "No duplicates found")

def check_vendor(vendor_name, vendor_master_df, match_threshold=85):
    if vendor_name == "NOT_FOUND": return _make_check("Vendor Verification", "flag", "No vendor name."), None
    best_match, best_score = None, 0
    for _, row in vendor_master_df.iterrows():
        s = fuzz.token_set_ratio(vendor_name.lower().strip(), str(row["vendor_name"]).lower().strip())
        if s > best_score: best_score = s; best_match = row
    if best_score < match_threshold:
        bn = best_match['vendor_name'] if best_match is not None else 'none'
        return _make_check("Vendor Verification", "reject", f"Vendor '{vendor_name}' not found (closest: {bn} at {best_score}%).",
                           {"best_match": bn, "similarity": best_score}), None
    if str(best_match.get("approved", "")).strip().lower() != "yes":
        vi = {"vendor_email": best_match.get("vendor_email", ""), "contact_person": best_match.get("contact_person", "")}
        return _make_check("Vendor Verification", "reject", f"Vendor '{best_match['vendor_name']}' not approved.",
                           {"matched_name": best_match['vendor_name'], "similarity": best_score}), vi
    vi = {"vendor_email": best_match.get("vendor_email", ""), "contact_person": best_match.get("contact_person", "")}
    return _make_check("Vendor Verification", "pass", f"Verified: {best_match['vendor_name']} ({best_score}% match, approved)",
                       {"matched_name": best_match['vendor_name'], "similarity": best_score}), vi

def check_po_match(po_number, vendor_name, invoice_amount, po_master_df, fuzzy_vendor_threshold=80, fuzzy_amount_tolerance=20):
    if po_number and po_number != "NOT_FOUND":
        match = po_master_df[po_master_df["po_number"].str.strip().str.upper() == str(po_number).strip().upper()]
        if not match.empty:
            row = match.iloc[0]
            if str(row.get("status", "Open")).strip().lower() == "closed":
                return _make_check("PO Matching", "flag", f"PO {po_number} found but Closed. Manager approval required.",
                                   {"po_status": "Closed"}), _po_info(row, False)
            return _make_check("PO Matching", "pass", f"PO {po_number} matched. Amount: ₹{float(row['po_amount']):,.2f}",
                               {"match_type": "direct"}), _po_info(row, False)
        return _make_check("PO Matching", "flag", f"PO {po_number} not found.", {"match_type": "not_found"}), None
    if vendor_name == "NOT_FOUND" or invoice_amount is None:
        return _make_check("PO Matching", "flag", "No PO reference. Cannot infer."), None
    candidates = []
    for _, row in po_master_df.iterrows():
        if str(row.get("status", "Open")).strip().lower() != "open": continue
        vs = fuzz.ratio(vendor_name.lower().strip(), str(row["vendor_name"]).lower().strip())
        pa = float(row["po_amount"])
        if vs >= fuzzy_vendor_threshold and pa > 0:
            diff = abs(invoice_amount - pa) / pa * 100
            if diff <= fuzzy_amount_tolerance:
                candidates.append({"po_number": row["po_number"], "po_amount": pa, "vendor_name": row["vendor_name"],
                                   "vendor_score": vs, "amount_diff_pct": diff, "fuzzy_matched": True,
                                   "po_vendor_name": row.get("vendor_name"), "po_currency": row.get("currency"), "po_date": row.get("po_date")})
    if not candidates: return _make_check("PO Matching", "flag", "No PO reference. No match inferred."), None
    best = min(candidates, key=lambda x: x["amount_diff_pct"])
    if len(candidates) == 1:
        return _make_check("PO Matching", "flag",
            f"Inferred: {best['po_number']} ({best['vendor_name']}, ₹{best['po_amount']:,.2f}, {best['amount_diff_pct']:.1f}% diff). Verify.",
            {"match_type": "fuzzy_single"}), best
    cs = ", ".join([f"{c['po_number']}" for c in candidates])
    return _make_check("PO Matching", "flag", f"Multiple matches: {cs}. Best: {best['po_number']}.",
                       {"match_type": "fuzzy_multiple"}), best

def _po_info(row, fuzzy_matched):
    return {
        "po_number": row["po_number"],
        "po_amount": float(row["po_amount"]),
        "po_vendor_name": row.get("vendor_name"),
        "po_currency": row.get("currency"),
        "po_date": row.get("po_date"),
        "fuzzy_matched": fuzzy_matched,
    }

def check_vendor_po_match(invoice_vendor, po_vendor, threshold=85):
    if not invoice_vendor or invoice_vendor == "NOT_FOUND" or not po_vendor:
        return _make_check("Vendor-PO Match", "skip", "Invoice vendor or PO vendor unavailable")
    score = fuzz.token_set_ratio(str(invoice_vendor).lower().strip(), str(po_vendor).lower().strip())
    if score < threshold:
        return _make_check("Vendor-PO Match", "reject",
                           f"Vendor-PO mismatch. PO expects '{po_vendor}', invoice has '{invoice_vendor}'.",
                           {"error_code": "VENDOR_PO_MISMATCH", "validation_type": "vendor_po_match",
                            "expected": po_vendor, "found": invoice_vendor, "similarity": score})
    return _make_check("Vendor-PO Match", "pass", f"Invoice vendor matches PO vendor ({score}% match).",
                       {"similarity": score})

def check_currency_match(invoice_currency, po_currency):
    if not invoice_currency or invoice_currency == "NOT_FOUND" or not po_currency:
        return _make_check("Currency Match", "skip", "Invoice currency or PO currency unavailable")
    invoice_currency = str(invoice_currency).strip().upper()
    po_currency = str(po_currency).strip().upper()
    if invoice_currency != po_currency:
        return _make_check("Currency Match", "flag",
                           f"Currency mismatch. Invoice {invoice_currency}, PO {po_currency}.",
                           {"error_code": "CURRENCY_MISMATCH", "validation_type": "currency_mismatch",
                            "invoice_currency": invoice_currency, "po_currency": po_currency})
    return _make_check("Currency Match", "pass", f"Invoice currency matches PO currency ({invoice_currency}).")

def check_invoice_after_po_date(invoice_date_str, po_date_str):
    if not invoice_date_str or invoice_date_str == "NOT_FOUND" or not po_date_str:
        return _make_check("Invoice Date vs PO Date", "skip", "Invoice date or PO date unavailable")
    try:
        invoice_date = datetime.strptime(str(invoice_date_str), "%Y-%m-%d")
        po_date = datetime.strptime(str(po_date_str), "%Y-%m-%d")
    except ValueError:
        return _make_check("Invoice Date vs PO Date", "info", "Could not parse invoice date or PO date")
    if invoice_date < po_date:
        return _make_check("Invoice Date vs PO Date", "flag",
                           f"Invoice date {invoice_date_str} is before PO date {po_date_str}.",
                           {"error_code": "INVALID_DOCUMENT_TIMELINE", "validation_type": "invoice_date_after_po",
                            "invoice_date": invoice_date_str, "po_date": po_date_str})
    return _make_check("Invoice Date vs PO Date", "pass", f"Invoice date {invoice_date_str} is on/after PO date {po_date_str}.")

def check_amount(invoice_amount, po_amount, tolerance_pct=5.0):
    if po_amount == 0: return _make_check("Amount Comparison", "flag", "PO amount is zero.", {"variance_dollar": invoice_amount, "variance_percent": None}), {"variance_dollar": invoice_amount, "variance_percent": None}
    vd = invoice_amount - po_amount; vp = (vd / po_amount) * 100
    vi = {"variance_dollar": round(vd, 2), "variance_percent": round(vp, 2)}
    if vp < 0: return _make_check("Amount Comparison", "pass", f"Partial invoice. ₹{invoice_amount:,.2f} is {abs(vp):.1f}% below PO ₹{po_amount:,.2f}.", vi), vi
    if vp <= tolerance_pct:
        d = f"Within {tolerance_pct}% tolerance. Variance: ₹{vd:,.2f} ({vp:+.1f}%)." if vp > 0.01 else f"Exact match. ₹{invoice_amount:,.2f} = PO ₹{po_amount:,.2f}."
        return _make_check("Amount Comparison", "pass", d, vi), vi
    if vp <= 10: return _make_check("Amount Comparison", "flag", f"Variance {vp:+.1f}% exceeds {tolerance_pct}% tolerance. ₹{invoice_amount:,.2f} vs PO ₹{po_amount:,.2f}.", vi), vi
    return _make_check("Amount Comparison", "reject", f"Variance {vp:+.1f}% significantly exceeds PO. ₹{invoice_amount:,.2f} vs PO ₹{po_amount:,.2f}.", vi), vi

def check_cumulative(po_number, current_amount, po_amount, history_df, tolerance_pct=5.0):
    prev = 0.0
    if not history_df.empty:
        ph = history_df[(history_df["po_number"].astype(str).str.strip().str.upper() == str(po_number).strip().upper()) & (history_df["status"] != "Rejected")]
        if not ph.empty: prev = pd.to_numeric(ph["invoice_amount"], errors="coerce").fillna(0).sum()
    cum = prev + current_amount; ci = {"previously_invoiced": round(prev, 2), "cumulative_total": round(cum, 2)}
    if po_amount and po_amount > 0:
        op = ((cum - po_amount) / po_amount) * 100
        if op > tolerance_pct:
            return _make_check("Cumulative Invoicing", "flag", f"Cumulative ₹{cum:,.2f} exceeds PO ₹{po_amount:,.2f} by {op:.1f}%. Previously: ₹{prev:,.2f}.", ci), ci
        if prev > 0:
            return _make_check("Cumulative Invoicing", "pass", f"Partial. Cumulative: ₹{cum:,.2f} of ₹{po_amount:,.2f} ({cum/po_amount*100:.0f}%).", ci), ci
    return _make_check("Cumulative Invoicing", "pass", "No previous invoices against this PO.", ci), ci

def check_tax_rate(tax_amount, total_amount, expected_rate=18, variance_pct=2):
    """Verify that the effective tax rate matches the expected rate."""
    if tax_amount is None or total_amount is None:
        return _make_check("Tax Rate Check", "skip", "Tax amount or total not available")
    if total_amount == 0:
        return _make_check("Tax Rate Check", "skip", "Total amount is zero")
    # Calculate pre-tax amount and effective tax rate
    pre_tax = total_amount - tax_amount
    if pre_tax <= 0:
        return _make_check("Tax Rate Check", "flag", f"Pre-tax amount is ₹{pre_tax:,.2f}. Tax may exceed invoice total.",
                           {"tax_amount": tax_amount, "total": total_amount})
    effective_rate = (tax_amount / pre_tax) * 100
    diff = abs(effective_rate - expected_rate)
    if diff <= variance_pct:
        return _make_check("Tax Rate Check", "pass",
                           f"Tax rate {effective_rate:.1f}% matches expected {expected_rate}% (within {variance_pct}% tolerance).",
                           {"effective_rate": round(effective_rate, 2), "expected": expected_rate})
    return _make_check("Tax Rate Check", "flag",
                       f"Tax rate mismatch. Effective: {effective_rate:.1f}%, expected: {expected_rate}%. Difference: {diff:.1f}%.",
                       {"effective_rate": round(effective_rate, 2), "expected": expected_rate, "diff": round(diff, 2)})

ALLOWED_CURRENCIES = ["INR", "USD"]

def check_currency(currency_str, allowed_currencies=None):
    """Verify the invoice currency is in the allowed list."""
    if allowed_currencies is None:
        allowed_currencies = ALLOWED_CURRENCIES
    if currency_str == "NOT_FOUND" or not currency_str:
        return _make_check("Currency Check", "skip", "Currency not extracted")
    currency_upper = str(currency_str).strip().upper()
    if currency_upper in [c.upper() for c in allowed_currencies]:
        return _make_check("Currency Check", "pass", f"Currency {currency_upper} is allowed.",
                           {"currency": currency_upper})
    return _make_check("Currency Check", "flag",
                       f"Currency '{currency_upper}' not in allowed list ({', '.join(allowed_currencies)}).",
                       {"currency": currency_upper, "allowed": allowed_currencies})

def calculate_confidence(results, extracted_data, metadata, po_matched_fuzzy):
    s = 100; bd = []
    for f in ["invoice_number","invoice_date","due_date","vendor_name","vendor_email","po_number","total_amount","tax_amount"]:
        if extracted_data.get(f) == "NOT_FOUND": s -= 8; bd.append((f"Missing: {f.replace('_',' ')}", -8))
    if results.get("active_checks", {}).get("currency") and extracted_data.get("currency") == "NOT_FOUND":
        s -= 5; bd.append(("Missing: currency", -5))
    if po_matched_fuzzy: s -= 10; bd.append(("Fuzzy PO match", -10))
    if metadata.get("extraction_method") == "ocr": s -= 20; bd.append(("OCR extraction", -20))
    if metadata.get("extraction_error"): s = max(s-30, 0); bd.append(("Extraction error", -30))
    s = max(0, min(100, s)); l = "High" if s >= 80 else ("Medium" if s >= 50 else "Low")
    results["confidence_score"] = s; results["confidence_label"] = l; results["confidence_breakdown"] = bd
    return results
