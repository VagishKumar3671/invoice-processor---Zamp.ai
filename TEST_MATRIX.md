# Complete Test Execution Plan

## Pre-Test Setup (do this before EVERY test session)

```
1. Go to Dashboard → Danger Zone → Clear All History
2. Verify Quick Stats shows: Total=0, Approved=0, Rejected=0, Flagged=0
3. Verify Groq API key is set (process any 1 invoice to confirm)
```

---

## CSV Output Columns (for post-test validation)

After each test, export the CSV. These columns should exist:

| Column | What It Contains | How to Validate |
|--------|-----------------|-----------------|
| invoice_number | Extracted inv # or NOT_FOUND | Match against PDF |
| vendor_name | Extracted vendor or NOT_FOUND | Match against PDF |
| po_number | Matched PO or NOT_FOUND | Check against po_master.csv |
| invoice_amount | Extracted amount | Match PDF total |
| po_amount | PO value from master | Match po_master.csv |
| variance_dollar | invoice_amount - po_amount | Calculate manually |
| variance_percent | (variance/po) * 100 | Calculate manually |
| cumulative_invoiced | Running total for this PO | Sum previous non-rejected |
| status | Approved / Flagged for Review / Rejected | Compare to expected |
| remark | Pipe-separated check results | Read for correctness |
| suggested_action | One-line action summary | Should match scenario |
| confidence_score | 0-100 | Check deductions make sense |
| vendor_email | From vendor master | Match vendor_master.csv |
| contact_person | From vendor master | Match vendor_master.csv |
| file_name | Uploaded filename | Match upload |
| processed_date | Timestamp | Should be current |
| check_details | JSON array of all check results | Parse and verify each check |

---

## TEST ROUND 1: Happy Path Validation

### Setup
```
All validation checks: ON (defaults)
Stale Invoice Threshold: 1095 (slide to max)
All other settings: default values
```

### Test 1.1 — Perfect Match
```
Upload: invoice_1_happy_path.pdf
Expected status: Approved
Expected confidence: 100%
```
**CSV verification:**
- invoice_number = INV-2024-1001
- vendor_name = Acme Supplies Pvt Ltd
- po_number = PO-2024-001
- invoice_amount = 50000.0
- po_amount = 50000.0
- variance_percent = 0.0
- status = Approved
- remark contains "All checks passed" or no flag/reject text
- check_details JSON: all checks have status "pass" or "info"

### Test 1.2 — Within Tolerance (3% over)
```
Upload: invoice_2_within_tolerance.pdf
Expected status: Approved
Expected confidence: 100%
```
**CSV verification:**
- invoice_amount = 128750.0
- po_amount = 125000.0
- variance_percent = 3.0
- status = Approved
- remark contains "within 5% tolerance" or "Variance: +3.0%"

### Test 1.3 — Exact Tolerance Boundary (5%)
```
Upload: invoice_18_exact_tolerance.pdf
Expected status: Approved
Expected confidence: 100%
```
**CSV verification:**
- variance_percent = 5.0
- status = Approved (5.0% equals the threshold, so it passes)

### Test 1.4 — Vendor Name Typo
```
Upload: invoice_13_vendor_typo.pdf
Expected status: Approved
Expected confidence: 100%
```
**CSV verification:**
- vendor_name on PDF = "Acme Supplies" (without Pvt Ltd)
- Vendor check detail shows "Acme Supplies Pvt Ltd (100% match, approved)"
- token_set_ratio handles the abbreviation correctly

### Test 1.5 — Lump Sum Invoice
```
Upload: invoice_21_lump_sum.pdf
Expected status: Approved
```
**CSV verification:**
- line_items in check_details has 1 entry (bundled)
- Amount matches PO exactly

### Test 1.6 — No Tax Line
```
Upload: invoice_23_no_tax_line.pdf
Expected status: Approved
Expected confidence: 92% (tax_amount = NOT_FOUND, -8)
```

### Test 1.7 — Missing Due Date
```
Upload: invoice_25_no_due_date.pdf
Expected status: Approved
Expected confidence: 92% (due_date = NOT_FOUND, -8)
```

**Pass criteria for Round 1:** All 7 invoices show "Approved". Export CSV, verify all statuses.

---

## TEST ROUND 2: Rejection Scenarios

### Setup
```
Clear history first
Stale Invoice Threshold: 1095
All checks: ON (defaults)
```

### Test 2.1 — Amount Over Tolerance (15%)
```
Upload: invoice_3_over_tolerance.pdf
Expected status: Rejected
```
**CSV verification:**
- variance_percent = 15.0
- Amount Comparison check = "reject"
- remark contains "significantly exceeds PO"
- suggested_action contains "amount variance" or "amount discrepancy"

### Test 2.2 — Unknown Vendor
```
Upload: invoice_8_unknown_vendor.pdf
Expected status: Rejected
```
**CSV verification:**
- Vendor check = "reject"
- Detail contains "not found in approved vendor database"
- Closest match shows Gamma Services at ~31% (way below 85%)
- suggested_action = "Escalate to procurement"

### Test 2.3 — Unapproved Vendor
```
Upload: invoice_12_unapproved_vendor.pdf
Expected status: Rejected
```
**CSV verification:**
- Vendor check = "reject"
- Detail contains "not approved"
- Omega Corp matched at 100% but approved=No

**Pass criteria for Round 2:** All 3 invoices show "Rejected". Correct rejection reasons in check_details.

---

## TEST ROUND 3: Flag Scenarios

### Setup
```
Clear history
Stale threshold: 1095
All checks: ON (defaults)
```

### Test 3.1 — No PO Reference
```
Upload: invoice_5_no_po.pdf
Expected status: Flagged for Review
```
**CSV verification:**
- PO Matching check = "flag"
- Detail contains "Inferred" and "PO-2024-004"
- confidence = 82 (fuzzy PO match = -10, plus possible missing fields)

### Test 3.2 — Credit Note
```
Upload: invoice_10_credit_note.pdf
Expected status: Flagged for Review
```
**CSV verification:**
- Credit Note Detection check = "flag"
- Detail contains "Credit note detected"
- Remaining checks (vendor, PO, amount, cumulative) should NOT appear in check_details
- suggested_action contains "credit note" or "AP team"

### Test 3.3 — Closed PO
```
Upload: invoice_11_closed_po.pdf
Expected status: Flagged for Review
```
**CSV verification:**
- PO Matching check = "flag"
- Detail contains "Closed" and "manager approval"

### Test 3.4 — Future Date
```
Upload: invoice_16_future_date.pdf
Expected status: Flagged for Review
```
**CSV verification:**
- Invoice Date Check = "flag"
- Detail contains "future"

### Test 3.5 — Just Over Tolerance (7.2%)
```
Upload: invoice_19_just_over_tolerance.pdf
Expected status: Flagged for Review
```
**CSV verification:**
- variance_percent = 7.2
- Amount Comparison check = "flag" (not reject — 7.2% is between 5-10%)

### Test 3.6 — PO Not Found
```
Upload: invoice_20_po_not_found.pdf
Expected status: Flagged for Review
```
**CSV verification:**
- PO Matching check = "flag"
- Detail contains "PO-2024-777 not found"

### Test 3.7 — Missing Invoice Number
```
Upload: invoice_14_no_invoice_number.pdf
Expected status: Flagged for Review
```
**CSV verification:**
- invoice_number = NOT_FOUND
- Critical Fields check = "flag" with "Missing: invoice number"
- Duplicate Detection check = "skip" (no invoice number to match)

### Test 3.8 — Blank PDF
```
Upload: invoice_24_blank.pdf
Expected status: Flagged for Review
Expected confidence: 10%
```
**CSV verification:**
- All extracted fields = NOT_FOUND
- Extraction check = "reject"
- suggested_action = "Manual processing required"

**Pass criteria for Round 3:** All 8 invoices show "Flagged for Review". Correct flag reasons.

---

## TEST ROUND 4: Sequence-Dependent Tests

### Test 4.1 — Duplicate Detection
```
Clear history
Stale threshold: 1095

Step 1: Upload invoice_1_happy_path.pdf
Expected: Approved

Step 2: Upload invoice_4_duplicate.pdf (same invoice number as #1)
Expected: Rejected
```
**CSV verification (after both):**
- Row 1: INV-2024-1001, Approved
- Row 2: INV-2024-1001, Rejected
- Row 2 remark contains "Duplicate"
- Row 2 Duplicate Detection check = "reject"

### Test 4.2 — Cumulative Invoicing
```
Clear history
Stale threshold: 1095

Step 1: Upload invoice_6_partial_first.pdf
Expected: Approved (₹12K against ₹20K PO-2024-005)

Step 2: Upload invoice_7_partial_over.pdf
Expected: Flagged (cumulative ₹24K exceeds ₹20K PO)
```
**CSV verification:**
- Row 1: invoice_amount=12000, status=Approved, cumulative=12000
- Row 2: invoice_amount=12000, status=Flagged, cumulative=24000
- Row 2 Cumulative check = "flag" with "exceeds PO"

---

## TEST ROUND 5: Configuration Toggle Tests

### Test 5.1 — Disable Amount Check
```
Clear history. Stale threshold: 1095.
Amount Comparison: OFF (toggle off in sidebar)
All other checks: ON

Upload: invoice_3_over_tolerance.pdf (normally rejected at 15%)
Expected: Approved (amount check disabled, all other checks pass)
```
**CSV verification:**
- status = Approved
- check_details shows Amount Comparison = "skip", "Disabled by user"

### Test 5.2 — Disable Vendor Check
```
Clear history. Stale threshold: 1095.
Vendor Verification: OFF
All other checks: ON

Upload: invoice_8_unknown_vendor.pdf (normally rejected)
Expected: Flagged for Review (PO check still flags PO-2024-099 not found)
```
**CSV verification:**
- status = Flagged for Review (NOT Rejected)
- Vendor Verification = "skip", "Disabled by user"
- PO Matching = "flag", "not found"

### Test 5.3 — Disable Cumulative Check
```
Clear history. Stale threshold: 1095.
Cumulative Invoicing: OFF
All other checks: ON

Step 1: Upload invoice_6_partial_first.pdf → Approved
Step 2: Upload invoice_7_partial_over.pdf → Expected: Approved (cumulative disabled)
```
**CSV verification:**
- Row 2 status = Approved
- Cumulative Invoicing = "skip", "Disabled by user"

### Test 5.4 — Change Amount Tolerance to 10%
```
Clear history. Stale threshold: 1095.
Amount Comparison: ON
Amount tolerance: change slider to 10%

Upload: invoice_19_just_over_tolerance.pdf (7.2% over)
Expected: Approved (7.2% within 10% tolerance)
```
**CSV verification:**
- status = Approved
- Amount Comparison detail shows "Within 10% tolerance"

### Test 5.5 — Change Stale Threshold to 180
```
Clear history.
Stale threshold: 180 (default)

Upload: invoice_1_happy_path.pdf (dated 2024-03-15, ~790 days old)
Expected: Flagged for Review (stale date flag)
```
**CSV verification:**
- status = Flagged for Review
- Invoice Date Check = "flag"
- Detail contains "Exceeds 180-day threshold"

### Test 5.6 — Disable All Optional Checks
```
Clear history. Stale threshold: 1095.
Disable: Invoice Date, Credit Note, Duplicate, Vendor, PO, Amount, Cumulative
Keep only: Critical Fields (ON)

Upload: invoice_8_unknown_vendor.pdf
Expected: Approved (only critical fields checked, and they all exist)
```
**CSV verification:**
- status = Approved
- 7 checks show "skip", "Disabled by user"
- Only Critical Fields = "pass"

---

## TEST ROUND 6: Extraction Quality

### Test 6.1 — Many Line Items
```
Upload: invoice_22_many_line_items.pdf (8 items)
Verify: check_details → line_items array has 8 entries
```

### Test 6.2 — Scanned PDF
```
Upload: invoice_9_scanned.pdf
Verify:
- Pipeline shows OCR Fallback step with "success" or "warning"
- Some fields may be garbled (e.g. PO number as "PO-7024-002")
- Confidence = 72% or lower (OCR penalty = -20)
```

### Test 6.3 — Telemetry Check
```
Upload any invoice.
In detailed results, verify:
- Model: shows "llama-3.3-70b-versatile" (or fallback model)
- Fallback: shows "Level 0" (or higher if fallback occurred)
```

---

## TEST ROUND 7: UI Verification

| Check | How to Verify | Pass |
|-------|--------------|------|
| Zamp logo | Sidebar shows Zamp logo at top | ✅ |
| Header branding | Main page shows "Zamp Invoice Processor" | ✅ |
| Pipeline steps | Upload 1 invoice, see 3 steps render with icons + timing | ✅ |
| Check audit trail | Expand results, see 7+ individual check rows | ✅ |
| Confidence breakdown | Shows "Base: 100 → -8 (missing field) → = 92%" format | ✅ |
| Email draft | Flagged/rejected invoice shows draft email | ✅ |
| Config expanders | Sidebar has 8 expandable check cards | ✅ |
| Toggle behavior | Disable a check → shows "Disabled by user" in audit | ✅ |
| Custom value warning | Change a slider → shows "Custom: X (default: Y)" | ✅ |
| Active count | Bottom of sidebar shows "N/8 checks active" | ✅ |
| Dashboard filters | Status/Vendor/Sort dropdowns work | ✅ |
| CSV export | Download button produces valid file | ✅ |
| Clear history | Danger Zone clears all records | ✅ |

---

## Post-Test CSV Evaluation

After running all tests, download the final CSV. Add these manual evaluation columns:

| Column to Add | Purpose |
|--------------|---------|
| expected_status | What you expected (Approved/Flagged/Rejected) |
| pass_fail | Does actual match expected? (PASS/FAIL) |
| extraction_correct | Were extracted fields accurate? (YES/NO/PARTIAL) |
| edge_case_id | Which edge case was tested (A1, B3, C5, etc from EDGE_CASES.md) |
| notes | Any observations |

This gives you a validation spreadsheet you can reference during the interview.

---

## What an Interviewer Will Test

Ranked by likelihood:

1. **"Run the happy path"** → Upload 1 clean invoice, show the full pipeline
2. **"Show me an edge case"** → Credit note (#10) or Unknown vendor (#8)
3. **"What happens if I change this setting?"** → Toggle a check, change tolerance
4. **"How does it handle bad data?"** → Blank PDF (#24) or missing fields (#14)
5. **"Show me the dashboard"** → Historical data, filters, audit trail
6. **"What would you improve?"** → Multi-currency, email integration, ERP, ML anomaly detection

---

## What Will Fail (and how to handle it)

| Risk | How to Handle |
|------|--------------|
| Groq rate limit | Process max 5-8 invoices per batch. Wait 30s between batches. |
| Extraction varies between runs | LLM output is non-deterministic. Acknowledge this. Say "we use temperature=0 to minimize variance." |
| Scanned invoice garbled | Expected behavior. Say "in production, we'd add a human review step for low-confidence OCR." |
| Cumulative numbers wrong | Always clear history before demo. Run sequence tests individually. |
| Stale dates flagging everything | Set slider to 1095 first. Explain the configurability. |

---

## Demo Script (5 minutes)

**0:00-0:30** — "This is Zamp Invoice Processor, an AI-powered system that automates invoice validation for accounts payable teams." Show the sidebar with configurable checks.

**0:30-1:30** — Happy path: Upload invoice 1. Show pipeline steps, all checks passing, "Approved" with 100% confidence.

**1:30-2:30** — Edge case: Upload invoice 10 (credit note). Show CN- prefix detection, remaining checks skipped. Explain "in production, credit notes follow a different AP workflow."

**2:30-3:30** — Rejection: Upload invoice 3 (15% over). Show amount check rejection. Show draft email. Then toggle amount tolerance to 20% and explain "the threshold is configurable per business."

**3:30-4:15** — Configuration: Disable duplicate detection. Explain "each check is independently toggleable with its own thresholds."

**4:15-5:00** — Dashboard: Show history, expand a row to see audit trail, export CSV. Close with "what I'd build next: ERP integration, multi-currency support, ML anomaly detection."
