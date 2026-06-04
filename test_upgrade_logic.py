import unittest

import pandas as pd

from document_intake import classify_document_type, create_document_metadata
from validator import run_all_checks


PO_MASTER = pd.DataFrame([
    {
        "po_number": "PO-1001",
        "vendor_name": "Acme Supplies Pvt Ltd",
        "po_amount": 1000,
        "currency": "INR",
        "po_date": "2026-01-10",
        "status": "Open",
    }
])

VENDOR_MASTER = pd.DataFrame([
    {
        "vendor_name": "Acme Supplies Pvt Ltd",
        "vendor_email": "billing@acme.test",
        "contact_person": "Raj",
        "approved": "Yes",
    },
    {
        "vendor_name": "Wrong Vendor Pvt Ltd",
        "vendor_email": "billing@wrong.test",
        "contact_person": "Asha",
        "approved": "Yes",
    },
])

EMPTY_HISTORY = pd.DataFrame()


def base_invoice(**overrides):
    data = {
        "invoice_number": "INV-1001",
        "invoice_date": "2026-01-15",
        "due_date": "2026-02-15",
        "vendor_name": "Acme Supplies Pvt Ltd",
        "vendor_email": "billing@acme.test",
        "po_number": "PO-1001",
        "line_items": [{"description": "Office supplies", "amount": 847.46}],
        "tax_amount": 152.54,
        "total_amount": 1000,
        "currency": "INR",
    }
    data.update(overrides)
    return data


def base_metadata(**overrides):
    data = {
        "file_name": "test.pdf",
        "document_id": "doc-test",
        "document_type": "text_pdf",
        "extraction_method": "text",
        "is_scanned": False,
        "ocr_confidence": None,
        "overall_extraction_confidence": 0.94,
    }
    data.update(overrides)
    return data


def check_status(result, check_name):
    for check in result["check_log"]:
        if check["check"] == check_name:
            return check["status"], check["detail"], check.get("data", {})
    raise AssertionError(f"Missing check {check_name}")


class UpgradeValidationTests(unittest.TestCase):
    def test_document_type_detection(self):
        self.assertEqual(classify_document_type("invoice text" * 10, 50), "text_pdf")
        self.assertEqual(classify_document_type("", 50), "scanned_pdf")
        self.assertEqual(create_document_metadata("sample.pdf")["file_type"], "pdf")

    def test_happy_path_approval(self):
        result = run_all_checks(base_invoice(), base_metadata(), PO_MASTER, VENDOR_MASTER, EMPTY_HISTORY)
        self.assertEqual(result["status"], "Approved")
        self.assertEqual(check_status(result, "Vendor-PO Match")[0], "pass")
        self.assertEqual(check_status(result, "Currency Match")[0], "pass")
        self.assertEqual(check_status(result, "Invoice Date vs PO Date")[0], "pass")

    def test_low_ocr_confidence_routes_review(self):
        result = run_all_checks(
            base_invoice(),
            base_metadata(document_type="scanned_pdf", extraction_method="ocr", is_scanned=True, ocr_confidence=0.52),
            PO_MASTER,
            VENDOR_MASTER,
            EMPTY_HISTORY,
        )
        self.assertEqual(result["status"], "Flagged for Review")
        self.assertEqual(check_status(result, "OCR Quality")[0], "flag")

    def test_low_extraction_confidence_routes_review(self):
        result = run_all_checks(
            base_invoice(),
            base_metadata(overall_extraction_confidence=0.58),
            PO_MASTER,
            VENDOR_MASTER,
            EMPTY_HISTORY,
        )
        self.assertEqual(result["status"], "Flagged for Review")
        self.assertEqual(check_status(result, "Extraction Confidence")[0], "flag")

    def test_vendor_po_mismatch_rejects(self):
        result = run_all_checks(
            base_invoice(vendor_name="Wrong Vendor Pvt Ltd"),
            base_metadata(),
            PO_MASTER,
            VENDOR_MASTER,
            EMPTY_HISTORY,
        )
        self.assertEqual(result["status"], "Rejected")
        status, _, data = check_status(result, "Vendor-PO Match")
        self.assertEqual(status, "reject")
        self.assertEqual(data["error_code"], "VENDOR_PO_MISMATCH")

    def test_currency_mismatch_routes_review(self):
        result = run_all_checks(
            base_invoice(currency="USD"),
            base_metadata(),
            PO_MASTER,
            VENDOR_MASTER,
            EMPTY_HISTORY,
        )
        self.assertEqual(result["status"], "Flagged for Review")
        status, _, data = check_status(result, "Currency Match")
        self.assertEqual(status, "flag")
        self.assertEqual(data["error_code"], "CURRENCY_MISMATCH")

    def test_invoice_before_po_routes_review(self):
        result = run_all_checks(
            base_invoice(invoice_date="2026-01-05"),
            base_metadata(),
            PO_MASTER,
            VENDOR_MASTER,
            EMPTY_HISTORY,
        )
        self.assertEqual(result["status"], "Flagged for Review")
        status, _, data = check_status(result, "Invoice Date vs PO Date")
        self.assertEqual(status, "flag")
        self.assertEqual(data["error_code"], "INVALID_DOCUMENT_TIMELINE")


if __name__ == "__main__":
    unittest.main()
