"""
learning.py - Human-approved learning rules for the invoice processor.

The LLM may suggest a rule from reviewer feedback, but saved rules execute as
deterministic, auditable corrections before validation runs.
"""

import copy
import json
import os
import re
import uuid
from datetime import datetime

try:
    from groq import Groq
except ImportError:
    Groq = None

LEARNING_RULES_PATH = os.path.join("data", "learning_rules.json")
LEARNING_SUGGESTION_MODEL = "openai/gpt-oss-120b"

SUPPORTED_RULE_TYPES = {
    "vendor_alias",
    "po_mapping",
    "credit_pattern",
    "credit_note_policy",
    "tax_currency_exception",
    "general_note",
}


RULE_SUGGESTION_PROMPT = """You convert AP reviewer feedback into one deterministic learning rule.

Return ONLY valid JSON. Do not include markdown.

Supported rule types:
1. vendor_alias
   fields: match_text, canonical_value
2. po_mapping
   fields: match_text, canonical_value
3. credit_pattern
   fields: match_text
4. credit_note_policy
   fields: vendor_name, action, reason
   allowed action: approve
5. tax_currency_exception
   fields: currency, vendor_name, reason
6. general_note
   fields: note

Rules:
- Choose one rule type only.
- Use invoice context when helpful.
- If feedback is unclear, return type general_note.
- Keep conditions narrow and auditable.
- If feedback says a vendor's credit notes should be approved or not flagged, use credit_note_policy with action approve.

Invoice context:
{context_json}

Reviewer feedback:
{feedback}
"""


def load_learning_rules(path=LEARNING_RULES_PATH):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        return []
    return []


def save_learning_rule(rule, path=LEARNING_RULES_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rules = load_learning_rules(path)
    clean = normalize_rule(rule)
    clean["id"] = clean.get("id") or str(uuid.uuid4())[:8]
    clean["created_at"] = clean.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean["enabled"] = bool(clean.get("enabled", True))
    rules.append(clean)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2)
    return clean


def save_learning_rules(rules, path=LEARNING_RULES_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not isinstance(rules, list):
        rules = []
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2)
    return rules


def update_learning_rule_enabled(rule_id, enabled, path=LEARNING_RULES_PATH):
    rules = load_learning_rules(path)
    updated_rule = None
    for rule in rules:
        if str(rule.get("id")) == str(rule_id):
            rule["enabled"] = bool(enabled)
            updated_rule = rule
            break
    if updated_rule is not None:
        save_learning_rules(rules, path)
    return updated_rule


def delete_learning_rule(rule_id, path=LEARNING_RULES_PATH):
    rules = load_learning_rules(path)
    remaining = [rule for rule in rules if str(rule.get("id")) != str(rule_id)]
    deleted = len(remaining) != len(rules)
    if deleted:
        save_learning_rules(remaining, path)
    return deleted


def record_learning_rule_usage(rule_ids, path=LEARNING_RULES_PATH):
    if not rule_ids:
        return []
    wanted = {str(rule_id) for rule_id in rule_ids if rule_id}
    if not wanted:
        return []
    rules = load_learning_rules(path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    touched = []
    for rule in rules:
        if str(rule.get("id")) in wanted:
            rule["usage_count"] = int(rule.get("usage_count", 0) or 0) + 1
            rule["last_used_at"] = now
            touched.append(rule)
    if touched:
        save_learning_rules(rules, path)
    return touched


def normalize_rule(rule):
    if not isinstance(rule, dict):
        rule = {}
    rule_type = str(rule.get("type", "general_note")).strip().lower()
    if rule_type not in SUPPORTED_RULE_TYPES:
        rule_type = "general_note"
    normalized = {
        "type": rule_type,
        "enabled": bool(rule.get("enabled", True)),
        "source": rule.get("source", "reviewer_feedback"),
    }
    for key in ["match_text", "canonical_value", "currency", "vendor_name", "reason", "note", "action"]:
        value = rule.get(key)
        if value is not None:
            normalized[key] = str(value).strip()
    if rule_type == "credit_note_policy" and normalized.get("action") != "approve":
        normalized["action"] = "approve"
    if "note" not in normalized:
        normalized["note"] = describe_rule(normalized)
    return normalized


def apply_learning_rules(extracted_data, rules=None):
    updated = copy.deepcopy(extracted_data)
    applied = []
    applied_rule_ids = []
    for rule in rules if rules is not None else load_learning_rules():
        if not rule.get("enabled", True):
            continue
        rule_type = rule.get("type")
        if rule_type == "vendor_alias":
            if _contains(updated.get("vendor_name"), rule.get("match_text")):
                old = updated.get("vendor_name", "NOT_FOUND")
                updated["vendor_name"] = rule.get("canonical_value", old)
                applied.append(_applied_check(rule, f"Vendor alias: '{old}' -> '{updated['vendor_name']}'"))
                applied_rule_ids.append(rule.get("id"))
        elif rule_type == "po_mapping":
            if _contains(updated.get("po_number"), rule.get("match_text")):
                old = updated.get("po_number", "NOT_FOUND")
                updated["po_number"] = rule.get("canonical_value", old)
                applied.append(_applied_check(rule, f"PO mapping: '{old}' -> '{updated['po_number']}'"))
                applied_rule_ids.append(rule.get("id"))
        elif rule_type == "credit_pattern":
            if _matches_credit_pattern(updated, rule.get("match_text")):
                _force_negative_amounts(updated)
                applied.append(_applied_check(rule, f"Credit pattern applied: {rule.get('match_text')}"))
                applied_rule_ids.append(rule.get("id"))
        elif rule_type == "credit_note_policy":
            if _matches_credit_note_policy(updated, rule):
                reason = rule.get("reason") or "Reviewer-approved credit note policy"
                updated["_learned_credit_note_action"] = rule.get("action", "approve")
                updated["_learned_credit_note_reason"] = reason
                applied.append(_applied_check(rule, f"Credit note policy: {reason}"))
                applied_rule_ids.append(rule.get("id"))
        elif rule_type == "tax_currency_exception":
            if _matches_tax_currency_exception(updated, rule):
                reason = rule.get("reason") or "Reviewer-approved tax/currency exception"
                updated["_learned_skip_tax_rate_reason"] = reason
                applied.append(_applied_check(rule, f"Tax/currency exception: {reason}"))
                applied_rule_ids.append(rule.get("id"))
        elif rule_type == "general_note":
            if _general_note_is_credit_note_policy(updated, rule):
                reason = rule.get("note") or "Reviewer-approved credit note policy"
                updated["_learned_credit_note_action"] = "approve"
                updated["_learned_credit_note_reason"] = reason
                applied.append(_applied_check(rule, f"Credit note policy from note: {reason}"))
                applied_rule_ids.append(rule.get("id"))
    if rules is None:
        record_learning_rule_usage(applied_rule_ids)
    return updated, applied


def suggest_learning_rule(feedback, invoice_context, api_key=None):
    if not str(feedback or "").strip():
        return normalize_rule({"type": "general_note", "note": "No reviewer feedback provided"})
    if api_key:
        llm_rule = _suggest_with_llm(feedback, invoice_context, api_key)
        if llm_rule:
            llm_rule["source"] = "llm_suggestion"
            return normalize_rule(llm_rule)
    return _suggest_with_heuristics(feedback, invoice_context)


def describe_rule(rule):
    rule_type = rule.get("type")
    if rule_type == "vendor_alias":
        return f"Treat '{rule.get('match_text', '')}' as vendor '{rule.get('canonical_value', '')}'."
    if rule_type == "po_mapping":
        return f"Map PO '{rule.get('match_text', '')}' to '{rule.get('canonical_value', '')}'."
    if rule_type == "credit_pattern":
        return f"Treat invoices containing '{rule.get('match_text', '')}' as credit notes."
    if rule_type == "credit_note_policy":
        vendor = rule.get("vendor_name") or "matching vendors"
        return f"Approve credit notes for {vendor} without routing to manual review."
    if rule_type == "tax_currency_exception":
        vendor = rule.get("vendor_name") or "matching vendors"
        currency = rule.get("currency") or "matching currencies"
        return f"Skip GST tax validation for {vendor} invoices in {currency}."
    return rule.get("note") or "Store reviewer note for audit context."


def _suggest_with_llm(feedback, invoice_context, api_key):
    if Groq is None:
        return None
    try:
        client = Groq(api_key=api_key)
        context_json = json.dumps(invoice_context, default=str)[:3000]
        prompt = RULE_SUGGESTION_PROMPT.format(context_json=context_json, feedback=feedback)
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You return only strict JSON learning rules."},
                {"role": "user", "content": prompt},
            ],
            model=LEARNING_SUGGESTION_MODEL,
            temperature=0,
            max_tokens=500,
            timeout=30,
        )
        text = _clean_json_text(response.choices[0].message.content)
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def _suggest_with_heuristics(feedback, invoice_context):
    text = str(feedback).strip()
    lower = text.lower()
    vendor = str(invoice_context.get("vendor_name", "")).strip()
    po_number = str(invoice_context.get("po_number", "")).strip()
    currency = str(invoice_context.get("currency", "")).strip().upper()
    if ("credit" in lower or "refund" in lower) and ("approve" in lower or "without flag" in lower or "not flag" in lower):
        return normalize_rule({
            "type": "credit_note_policy",
            "vendor_name": vendor,
            "action": "approve",
            "reason": text,
            "source": "heuristic",
        })
    if "credit" in lower or "refund" in lower or "negative" in lower:
        return normalize_rule({"type": "credit_pattern", "match_text": _quoted_or_default(text, "credit"), "source": "heuristic"})
    if "currency" in lower or "eur" in lower or "usd" in lower or "vat" in lower or "gst" in lower:
        return normalize_rule({
            "type": "tax_currency_exception",
            "currency": currency if currency and currency != "NOT_FOUND" else _currency_from_text(text),
            "vendor_name": vendor,
            "reason": text,
            "source": "heuristic",
        })
    if "po" in lower and po_number:
        return normalize_rule({"type": "po_mapping", "match_text": po_number, "canonical_value": _quoted_or_default(text, po_number), "source": "heuristic"})
    if "vendor" in lower or "treat" in lower or "map" in lower:
        return normalize_rule({"type": "vendor_alias", "match_text": vendor, "canonical_value": _quoted_or_default(text, vendor), "source": "heuristic"})
    return normalize_rule({"type": "general_note", "note": text, "source": "heuristic"})


def _clean_json_text(text):
    text = str(text).strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _quoted_or_default(text, default):
    match = re.search(r"['\"]([^'\"]+)['\"]", text)
    if match:
        return match.group(1).strip()
    return default


def _currency_from_text(text):
    for code in ["INR", "USD", "EUR", "GBP"]:
        if code.lower() in str(text).lower():
            return code
    return ""


def _contains(value, needle):
    if not value or not needle:
        return False
    return str(needle).lower().strip() in str(value).lower().strip()


def _matches_credit_pattern(extracted_data, match_text):
    if not match_text:
        return False
    haystack = [
        extracted_data.get("invoice_number", ""),
        extracted_data.get("po_number", ""),
    ]
    haystack.extend([item.get("description", "") for item in extracted_data.get("line_items", [])])
    return any(_contains(value, match_text) for value in haystack)


def _matches_credit_note_policy(extracted_data, rule):
    vendor = str(rule.get("vendor_name", "")).strip().lower()
    data_vendor = str(extracted_data.get("vendor_name", "")).strip().lower()
    vendor_ok = not vendor or vendor in data_vendor
    return vendor_ok and _looks_like_credit_note(extracted_data)


def _general_note_is_credit_note_policy(extracted_data, rule):
    note = str(rule.get("note", "")).lower()
    if "credit note" not in note or "approve" not in note:
        return False
    vendor = str(extracted_data.get("vendor_name", "")).strip().lower()
    return bool(vendor and vendor in note and _looks_like_credit_note(extracted_data))


def _looks_like_credit_note(extracted_data):
    invoice_number = str(extracted_data.get("invoice_number", "")).upper().strip()
    if invoice_number.startswith(("CN-", "CN/", "CREDIT")):
        return True
    total = _parse_amount(extracted_data.get("total_amount"))
    tax = _parse_amount(extracted_data.get("tax_amount"))
    if total is not None and total < 0:
        return True
    if tax is not None and tax < 0:
        return True
    for item in extracted_data.get("line_items", []):
        description = str(item.get("description", "")).lower()
        amount = _parse_amount(item.get("amount"))
        if "credit" in description or "refund" in description or "reversal" in description:
            return True
        if amount is not None and amount < 0:
            return True
    return False


def _matches_tax_currency_exception(extracted_data, rule):
    currency = str(rule.get("currency", "")).strip().upper()
    vendor = str(rule.get("vendor_name", "")).strip().lower()
    data_currency = str(extracted_data.get("currency", "")).strip().upper()
    data_vendor = str(extracted_data.get("vendor_name", "")).strip().lower()
    currency_ok = not currency or currency == data_currency
    vendor_ok = not vendor or vendor in data_vendor
    return currency_ok and vendor_ok


def _force_negative_amounts(extracted_data):
    for key in ["total_amount", "tax_amount"]:
        value = extracted_data.get(key)
        amount = _parse_amount(value)
        if amount is not None:
            extracted_data[key] = -abs(amount)
    for item in extracted_data.get("line_items", []):
        amount = _parse_amount(item.get("amount"))
        if amount is not None:
            item["amount"] = -abs(amount)


def _parse_amount(value):
    if value in (None, "NOT_FOUND"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[₹$€£,\s]", "", str(value))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _applied_check(rule, detail):
    return {
        "check": "Learned Rule Applied",
        "status": "info",
        "detail": detail,
        "data": {"rule_id": rule.get("id"), "rule_type": rule.get("type")},
    }
