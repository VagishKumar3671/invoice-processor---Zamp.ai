# Edge Case Documentation

## Category A: PDF-Defined Edge Cases
*Scenarios explicitly described in the PS-1 case study requirements*

| ID | Scenario | What the PDF Says | How We Handle It | Test Invoice |
|----|----------|-------------------|------------------|-------------|
| A1 | Different vendor formats | "Different vendors format them differently" | Fuzzy matching via token_set_ratio at configurable threshold (default 85%) | #13 (vendor typo) |
| A2 | Line items itemized vs bundled | "Line items might be itemised or bundled" | AI extraction handles both; single or multi-row line_items array | #21 (lump sum), #22 (8 items) |
| A3 | Tax embedded vs separated | "Tax might be embedded or separated" | Match on total_amount, not subtotal. tax_amount is informational | #23 (no tax line) |
| A4 | PO explicit vs implied | "PO references might be explicit or implied" | Direct PO lookup → fuzzy inference (vendor+amount match) | #5 (no PO), #1 (explicit PO) |
| A5 | Missing critical fields | "Sometimes critical information is just missing" | Flag missing invoice #/vendor. Reject if total_amount missing | #14 (no inv#), #15 (no vendor) |
| A6 | Duplicate detection | "Duplicate detection rules" | Invoice # + vendor fuzzy match against processing history | #4 (duplicate of #1) |
| A7 | Split invoicing / cumulative | "A vendor might split a single PO into multiple invoices" | Track running total per PO across all non-rejected invoices | #6 then #7 (cumulative pair) |
| A8 | Approximate amounts | "Amounts might be close but not exact" | Configurable tolerance threshold (default 5%) | #2 (3%), #18 (5%), #19 (7.2%) |
| A9 | Scanned/image PDFs | "Some are scanned images" | OCR fallback via Tesseract when PyMuPDF text < 50 chars | #9 (scanned) |

## Category B: Custom-Created Edge Cases
*Additional scenarios we designed to show business understanding*

| ID | Scenario | Business Rationale | How We Handle It | Test Invoice |
|----|----------|-------------------|------------------|-------------|
| B1 | Unknown vendor | Vendor not in master database at all | Reject with "escalate to procurement" email | #8 |
| B2 | Unapproved vendor | Vendor exists but approved=No | Reject with vendor compliance flag | #12 |
| B3 | Credit note (negative amount) | Vendor issues credit memo, not a standard invoice | Detect via negative amount OR CN- prefix OR "credit" keywords. Short-circuit remaining checks, route to AP | #10 |
| B4 | Closed PO | PO exists but status=Closed | Flag, require manager approval | #11 |
| B5 | Future-dated invoice | Invoice date is in the future | Flag as possible data entry error | #16 |
| B6 | Stale invoice (>N days) | Old invoice submitted late | Flag with configurable day threshold | #17 |
| B7 | AI extraction failure | PDF is blank, corrupted, or unreadable | Graceful degradation: 10% confidence, route to manual processing | #24 |
| B8 | PO number not found | PO reference exists but doesn't match any record | Flag (different from "no PO at all") | #20 |
| B9 | Missing due date only | Non-critical field missing | Proceed with minor confidence deduction | #25 |

## Category C: Validation / Tolerance Scenarios
*Boundary testing for configurable thresholds*

| ID | Scenario | Test Condition | Expected at Default | Test Invoice |
|----|----------|---------------|-------------------|-------------|
| C1 | Exact match | 0% variance | Approved | #1 |
| C2 | Within tolerance | 3% over | Approved | #2 |
| C3 | Exact boundary | 5.0% over (equals threshold) | Approved | #18 |
| C4 | Just over tolerance | 7.2% over | Flagged | #19 |
| C5 | Far over tolerance | 15% over | Rejected | #3 |
| C6 | Partial invoice (under PO) | 40% below PO | Approved (partial delivery) | #6 |
| C7 | Cumulative exceeds PO | Two partials sum > PO | Flagged | #6 then #7 |

## Validation Check Reference

| Check | What It Does | Configurable Params | Default |
|-------|-------------|-------------------|---------|
| Invoice Date Sanity | Flags future or stale invoices | Stale threshold (days) | 180 |
| Critical Fields | Ensures invoice #, vendor, amount present | None | Always on |
| Credit Note Detection | Catches credit memos via amount/prefix/keywords | None | Always on |
| Duplicate Detection | Rejects already-processed invoices | Vendor match % | 90% |
| Vendor Verification | Fuzzy-matches vendor name against master | Match threshold % | 85% |
| PO Matching | Matches invoice to PO (direct + fuzzy + closed) | Fuzzy vendor %, amount tolerance % | 80%, 20% |
| Amount Comparison | Compares invoice vs PO amount | Tolerance % | 5% |
| Cumulative Invoicing | Tracks total invoiced per PO | Tolerance % | 5% |

## Test Batch Groups

| Batch | Purpose | Invoices | Notes |
|-------|---------|----------|-------|
| A | Happy Path | 1, 2, 18, 21, 23, 25 | All should Approve |
| B | Rejections | 3, 8, 12 | All should Reject |
| C | Flags | 5, 10, 11, 16, 17, 19, 20 | All should Flag |
| D | Duplicate Sequence | 1 then 4 | Must run in order |
| E | Cumulative Sequence | 6 then 7 | Must run in order |
| F | Missing Fields | 14, 15, 24 | Various flag types |
| G | Vendor Tests | 8, 12, 13 | Reject, Reject, Approve |
| H | Tolerance Range | 2, 18, 19, 3 | Approve, Approve, Flag, Reject |

## Demo Order for Interview

1. Clear history
2. Set stale threshold to 1095 (max)
3. Batch A (happy path) → show 6 approvals
4. Invoice 3 → show rejection with reasoning
5. Invoice 10 → show credit note detection
6. Invoice 1 again → show duplicate rejection
7. Toggle tolerance slider to 3% → re-run Invoice 18 → now flags instead of approves
8. Disable cumulative check → show how it changes results

---

## Category D: Considered but Not Implemented

These edge cases were discussed but deliberately excluded. Here's why and whether to add them later.

| Edge Case | Why Not Implemented | Should It Be Added? | Recommendation |
|-----------|-------------------|--------------------|----|
| Tax Mismatch | All 25 test invoices use 18% GST. A tax check would never fire during the demo, making it look like dead code. No test data to exercise it. | Add in production when real multi-tax invoices exist | Skip for case study, mention as "what I'd build next" |
| Currency Mismatch | All invoices are INR. Same problem — a currency check with no USD/EUR test data can't be demonstrated. | Add when multi-currency POs exist in the dataset | Skip for case study, mention in interview |
| OCR Confidence Threshold | Tesseract's page-level confidence is unreliable. The current approach (flag if extracted text < 50 chars) is more practical than a numeric threshold. | Replace with a better OCR engine (Google Vision, AWS Textract) that returns reliable confidence | Current approach is correct for Tesseract |
| Multi-stage Extraction | Splitting extraction into 3 LLM calls would triple API usage. Groq free tier already hits rate limits on 25 invoices. Would break during demo. | Consider for production with paid API tier | Definitely skip for case study |
| Round Number Anomaly | Flagging suspiciously round amounts (e.g. exactly ₹100,000 with no tax) as potential fraud. Interesting but no test invoice exercises it. | Add if fraud detection becomes a focus | Low priority |
| Late Payment Risk | Checking if vendor has been waiting >60 days. Would need payment terms data we don't have. | Add with real AP data | Good interview talking point |

**Interview answer:** "I considered these but deliberately excluded them because I couldn't demonstrate them with test data. A check that never fires during a demo is worse than no check — it looks broken. In production, I'd add tax and currency validation once the system handles real multi-currency invoices."
