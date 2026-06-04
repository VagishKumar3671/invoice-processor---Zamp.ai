import os
import tempfile
import unittest

from learning import (
    apply_learning_rules,
    delete_learning_rule,
    load_learning_rules,
    save_learning_rules,
    update_learning_rule_enabled,
)
from learning_rules_ui import filter_rules


class LearningRulesManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "learning_rules.json")
        self.rules = [
            {
                "id": "R001",
                "type": "credit_pattern",
                "match_text": "credit service",
                "enabled": True,
                "source": "reviewer_feedback",
                "created_at": "2026-06-01 10:00:00",
            },
            {
                "id": "R002",
                "type": "vendor_alias",
                "match_text": "Gamma",
                "canonical_value": "Gamma Services",
                "enabled": False,
                "source": "llm_suggestion",
                "created_at": "2026-06-01 10:05:00",
            },
        ]
        save_learning_rules(self.rules, self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_toggle_enabled_persists(self):
        updated = update_learning_rule_enabled("R001", False, self.path)
        self.assertIsNotNone(updated)
        rules = load_learning_rules(self.path)
        self.assertFalse(rules[0]["enabled"])

    def test_delete_rule_persists(self):
        self.assertTrue(delete_learning_rule("R002", self.path))
        rules = load_learning_rules(self.path)
        self.assertEqual([rule["id"] for rule in rules], ["R001"])

    def test_disabled_rule_is_not_applied(self):
        invoice = {"vendor_name": "Gamma", "po_number": "PO-1", "invoice_number": "INV-1", "line_items": []}
        updated, applied = apply_learning_rules(invoice, load_learning_rules(self.path))
        self.assertEqual(updated["vendor_name"], "Gamma")
        self.assertEqual(applied, [])

    def test_enabled_rule_continues_working(self):
        invoice = {
            "vendor_name": "Any Vendor",
            "po_number": "PO-1",
            "invoice_number": "INV-1",
            "total_amount": 500,
            "tax_amount": 90,
            "line_items": [{"description": "credit service", "amount": 500}],
        }
        updated, applied = apply_learning_rules(invoice, load_learning_rules(self.path))
        self.assertEqual(updated["total_amount"], -500)
        self.assertEqual(updated["tax_amount"], -90)
        self.assertEqual(len(applied), 1)

    def test_search_and_filter(self):
        rules = load_learning_rules(self.path)
        self.assertEqual(len(filter_rules(rules, search_text="Gamma")), 1)
        self.assertEqual(len(filter_rules(rules, rule_type="credit_pattern")), 1)
        self.assertEqual(len(filter_rules(rules, status="Enabled")), 1)
        self.assertEqual(len(filter_rules(rules, status="Disabled")), 1)


if __name__ == "__main__":
    unittest.main()
