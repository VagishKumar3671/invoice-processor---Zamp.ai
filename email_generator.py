"""
email_generator.py - Draft Email Generator (v2)

Generates context-specific draft emails for Flagged and Rejected invoices.
6 email types based on the reason for the flag/rejection.
Added: closed PO email, credit note email.
"""


def generate_email(results):
    status = results.get("status", "")
    remark = results.get("remark", "").lower()
    failed_checks = [c for c in results.get("check_log", []) if c.get("status") in ("flag", "reject")]

    invoice_number = results.get("invoice_number", "N/A")
    vendor_name = results.get("vendor_name", "N/A")
    invoice_amount = results.get("invoice_amount")
    po_number = results.get("po_number", "N/A")
    po_amount = results.get("po_amount")
    variance_percent = results.get("variance_percent")
    cumulative_invoiced = results.get("cumulative_invoiced")
    contact_person = results.get("contact_person", "Sir/Madam")
    vendor_email = results.get("vendor_email_resolved") or results.get("vendor_email", "")
    invoice_date = results.get("invoice_date", "N/A")

    inv_amt_str = f"₹{invoice_amount:,.2f}" if invoice_amount is not None else "N/A"
    po_amt_str = f"₹{po_amount:,.2f}" if po_amount else "N/A"

    if status == "Approved":
        return {"to_email": "", "subject": "", "body": "", "email_type": "none",
                "action_summary": "No action needed. Invoice approved."}

    # Route by business priority, not by whichever phrase appears first in the remark.
    if _has_check(failed_checks, "Extraction"):
        return {
            "to_email": "ap-team@techventures.in",
            "subject": f"Manual Processing Required - Invoice from {vendor_name}",
            "body": f"Dear AP Team,\n\nAn invoice from {vendor_name} (Invoice #{invoice_number}) could not be automatically processed due to extraction issues.\n\nPlease process this invoice manually and verify all details.\n\nRegards,\nInvoice Processing System",
            "email_type": "extraction_failure",
            "action_summary": "Route to AP team for manual processing",
        }

    if _has_check(failed_checks, "Credit Note Detection") or "credit note" in remark:
        return _email_credit_note(invoice_number, vendor_name, inv_amt_str)

    if _has_check(failed_checks, "Duplicate Detection") or "duplicate" in remark:
        return _email_duplicate(invoice_number, vendor_name, contact_person, vendor_email, remark)

    vendor_failure = _get_check(failed_checks, "Vendor Verification")
    if vendor_failure and "not approved" in vendor_failure.get("detail", "").lower():
        return _email_unapproved_vendor(invoice_number, vendor_name, inv_amt_str, po_number)

    if vendor_failure or ("not found" in remark and "vendor" in remark.lower()) or "not approved" in remark:
        return _email_unknown_vendor(invoice_number, vendor_name, inv_amt_str, po_number)

    currency_failure = _get_check(failed_checks, "Currency Check")
    if currency_failure or "not in allowed list" in remark:
        return _email_currency_mismatch(invoice_number, vendor_name, remark)

    po_failure = _get_check(failed_checks, "PO Matching")
    if (po_failure and "closed" in po_failure.get("detail", "").lower()) or ("closed" in remark and "po" in remark):
        return _email_closed_po(invoice_number, vendor_name, contact_person, vendor_email, inv_amt_str, po_number)

    if po_failure or ("no po" in remark and ("reference" in remark or "on invoice" in remark)) or ("po" in remark and "not found" in remark):
        return _email_missing_po(invoice_number, vendor_name, contact_person, vendor_email, inv_amt_str, invoice_date)

    if _has_check(failed_checks, "Amount Comparison") or "variance" in remark or "significantly exceeds" in remark:
        return _email_amount_mismatch(invoice_number, vendor_name, contact_person, vendor_email, inv_amt_str, po_number, po_amt_str, variance_percent)

    if _has_check(failed_checks, "Cumulative Invoicing") or "cumulative" in remark:
        return _email_cumulative(invoice_number, vendor_name, contact_person, vendor_email, inv_amt_str, po_number, po_amt_str, cumulative_invoiced)

    if _has_check(failed_checks, "Tax Rate Check") or "tax rate mismatch" in remark:
        return {
            "to_email": "ap-team@techventures.in",
            "subject": f"Tax Rate Verification Required - {invoice_number}",
            "body": f"Dear AP Team,\n\nInvoice #{invoice_number} from {vendor_name} for {inv_amt_str} has a tax rate that differs from the expected rate.\n\nDetails: {remark}\n\nPlease verify the tax calculation and applicable GST rate before processing payment.\n\nRegards,\nInvoice Processing System",
            "email_type": "tax_mismatch",
            "action_summary": "Verify tax rate with vendor or tax team",
        }

    return {
        "to_email": vendor_email if vendor_email and vendor_email != "NOT_FOUND" else "ap-team@techventures.in",
        "subject": f"Invoice Review Required - {invoice_number}",
        "body": f"Dear {contact_person},\n\nInvoice #{invoice_number} from {vendor_name} requires review.\n\nReason: {results.get('remark', 'See details.')}\n\nRegards,\nAccounts Payable Team\nTechVentures India Pvt Ltd",
        "email_type": "general",
        "action_summary": "Review required - see remarks",
    }


def _get_check(checks, check_name):
    for check in checks:
        if check.get("check") == check_name:
            return check
    return None


def _has_check(checks, check_name):
    return _get_check(checks, check_name) is not None


def _email_credit_note(invoice_number, vendor_name, inv_amt_str):
    return {
        "to_email": "ap-team@techventures.in",
        "subject": f"Credit Note Received - {invoice_number} from {vendor_name}",
        "body": f"Dear AP Team,\n\nA credit note (Invoice #{invoice_number}) has been received from {vendor_name} for {inv_amt_str}.\n\nCredit notes require manual processing to apply against the correct original invoice. Please review and process accordingly.\n\nRegards,\nInvoice Processing System",
        "email_type": "credit_note",
        "action_summary": "Route to AP team - credit note requires manual application",
    }


def _email_closed_po(invoice_number, vendor_name, contact_person, vendor_email, inv_amt_str, po_number):
    return {
        "to_email": vendor_email if vendor_email and vendor_email != "NOT_FOUND" else "ap-team@techventures.in",
        "subject": f"Invoice Against Closed PO - {invoice_number}",
        "body": f"Dear {contact_person},\n\nWe received Invoice #{invoice_number} from {vendor_name} for {inv_amt_str} referencing PO #{po_number}.\n\nHowever, this purchase order has been marked as Closed in our system. We are unable to process invoices against closed POs without manager approval.\n\nCould you please confirm whether this PO should be reopened, or provide an alternative PO reference?\n\nRegards,\nAccounts Payable Team\nTechVentures India Pvt Ltd",
        "email_type": "closed_po",
        "action_summary": f"Contact vendor about closed PO {po_number}",
    }


def _email_duplicate(invoice_number, vendor_name, contact_person, vendor_email, remark):
    return {
        "to_email": vendor_email if vendor_email and vendor_email != "NOT_FOUND" else "",
        "subject": f"Duplicate Invoice Notice - {invoice_number}",
        "body": f"Dear {contact_person},\n\nWe received Invoice #{invoice_number} from {vendor_name}. However, our records indicate that this invoice has been previously submitted and processed.\n\nCould you please verify whether this is a resubmission or if the original invoice should be disregarded? If this is a revised invoice, kindly resubmit with a new invoice number and mark it as a revision.\n\nWe are unable to process duplicate invoices to prevent double payment.\n\nRegards,\nAccounts Payable Team\nTechVentures India Pvt Ltd",
        "email_type": "duplicate",
        "action_summary": "Notify vendor of duplicate submission",
    }


def _email_unknown_vendor(invoice_number, vendor_name, inv_amt_str, po_number):
    return {
        "to_email": "procurement@techventures.in",
        "subject": f"Unknown Vendor Alert - {vendor_name}",
        "body": f"Dear Procurement Team,\n\nAn invoice has been received from a vendor that is not in our approved vendor database.\n\nDetails:\n- Vendor: {vendor_name}\n- Invoice Number: {invoice_number}\n- Amount: {inv_amt_str}\n- PO Reference: {po_number}\n\nPlease verify this vendor and advise whether they should be onboarded. The invoice is on hold pending your confirmation.\n\nRegards,\nAccounts Payable Team\nTechVentures India Pvt Ltd",
        "email_type": "unknown_vendor",
        "action_summary": "Escalate to procurement - unknown vendor",
    }


def _email_unapproved_vendor(invoice_number, vendor_name, inv_amt_str, po_number):
    return {
        "to_email": "procurement@techventures.in",
        "subject": f"Unapproved Vendor Alert - {vendor_name}",
        "body": f"Dear Procurement Team,\n\nAn invoice has been received from a vendor that exists in our database but is not approved for payment.\n\nDetails:\n- Vendor: {vendor_name}\n- Invoice Number: {invoice_number}\n- Amount: {inv_amt_str}\n- PO Reference: {po_number}\n\nPlease confirm whether this vendor should be approved before AP proceeds.\n\nRegards,\nAccounts Payable Team\nTechVentures India Pvt Ltd",
        "email_type": "unapproved_vendor",
        "action_summary": "Escalate to procurement - vendor not approved",
    }


def _email_missing_po(invoice_number, vendor_name, contact_person, vendor_email, inv_amt_str, invoice_date):
    return {
        "to_email": vendor_email if vendor_email and vendor_email != "NOT_FOUND" else "",
        "subject": f"Purchase Order Reference Required - Invoice {invoice_number}",
        "body": f"Dear {contact_person},\n\nWe received Invoice #{invoice_number} dated {invoice_date} for {inv_amt_str} from {vendor_name}.\n\nHowever, the invoice does not contain a Purchase Order (PO) reference number. We require a valid PO number to process your invoice.\n\nCould you please reply with the correct PO number?\n\nRegards,\nAccounts Payable Team\nTechVentures India Pvt Ltd",
        "email_type": "missing_po",
        "action_summary": "Request PO number from vendor",
    }


def _email_currency_mismatch(invoice_number, vendor_name, remark):
    return {
        "to_email": "ap-team@techventures.in",
        "subject": f"Currency Review Required - {invoice_number}",
        "body": f"Dear AP Team,\n\nInvoice #{invoice_number} from {vendor_name} is denominated in a currency that is not in our approved list.\n\nDetails: {remark}\n\nPlease verify the currency and coordinate with the vendor for a corrected invoice if necessary.\n\nRegards,\nInvoice Processing System",
        "email_type": "currency_mismatch",
        "action_summary": "Review unsupported currency / PO mapping",
    }


def _email_amount_mismatch(invoice_number, vendor_name, contact_person, vendor_email, inv_amt_str, po_number, po_amt_str, variance_percent):
    var_str = f"{variance_percent:+.1f}%" if variance_percent else "N/A"
    return {
        "to_email": vendor_email if vendor_email and vendor_email != "NOT_FOUND" else "",
        "subject": f"Clarification Required - Invoice {invoice_number} Amount Discrepancy",
        "body": f"Dear {contact_person},\n\nWe received Invoice #{invoice_number} from {vendor_name} for {inv_amt_str}. However, our PO #{po_number} was for {po_amt_str}.\n\nThis represents a variance of {var_str}. Our policy requires invoices within the agreed tolerance.\n\nCould you please clarify the discrepancy?\n\nRegards,\nAccounts Payable Team\nTechVentures India Pvt Ltd",
        "email_type": "amount_mismatch",
        "action_summary": f"Contact vendor about {var_str} amount variance",
    }


def _email_cumulative(invoice_number, vendor_name, contact_person, vendor_email, inv_amt_str, po_number, po_amt_str, cumulative_total):
    cum_str = f"₹{cumulative_total:,.2f}" if cumulative_total else "N/A"
    return {
        "to_email": vendor_email if vendor_email and vendor_email != "NOT_FOUND" else "",
        "subject": f"Invoice Review - PO {po_number} Cumulative Amount Exceeded",
        "body": f"Dear {contact_person},\n\nWe received Invoice #{invoice_number} from {vendor_name} for {inv_amt_str} against PO #{po_number} (value: {po_amt_str}).\n\nWith this invoice, the total invoiced against this PO would be {cum_str}, exceeding the original PO value.\n\nPlease confirm whether the PO should be amended or the invoice adjusted.\n\nRegards,\nAccounts Payable Team\nTechVentures India Pvt Ltd",
        "email_type": "cumulative_exceeded",
        "action_summary": f"Contact vendor - cumulative exceeds PO {po_number}",
    }
