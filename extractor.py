"""
extractor.py - Invoice Data Extraction Engine (v2)

Changes from v1:
- Added step-level audit log (pipeline_steps) so the UI can show each stage
- Added timing per step
- Better error messages with context
- Handles edge case where Groq returns amounts as strings
- Added retry with exponential backoff for 429 rate limit errors
- Added model fallback chain for rate limit resilience
"""

import json
import os
import re
import time
import fitz  # PyMuPDF
from groq import Groq
from groq import RateLimitError
from document_intake import classify_document_type, create_document_metadata

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

MIN_TEXT_LENGTH = 50

EXTRACTION_PROMPT = """You are an invoice data extraction system. You will receive raw text extracted from an invoice PDF.

Extract the following fields and return ONLY valid JSON with no other text, no markdown backticks, no explanation.

Required JSON structure:
{
    "invoice_number": "string or NOT_FOUND",
    "invoice_date": "string (YYYY-MM-DD format) or NOT_FOUND",
    "due_date": "string (YYYY-MM-DD format) or NOT_FOUND",
    "vendor_name": "string or NOT_FOUND",
    "vendor_email": "string or NOT_FOUND",
    "po_number": "string or NOT_FOUND",
    "line_items": [
        {
            "description": "string",
            "quantity": "number or null",
            "unit_price": "number or null",
            "amount": "number"
        }
    ],
    "tax_amount": "number or NOT_FOUND",
    "total_amount": "number or NOT_FOUND",
    "currency": "string (e.g. INR, USD) or NOT_FOUND"
}

Rules:
- Extract EXACTLY what is in the invoice. Do not guess or make up values.
- If a field is not present in the text, set it to "NOT_FOUND".
- For amounts, extract as numbers without currency symbols (e.g. 50000.00 not ₹50,000.00).
- For line_items, if items are bundled as lump sum, create one entry.
- If the invoice text is garbled or unreadable, set all fields to "NOT_FOUND".
- Return ONLY the JSON object. No other text before or after it.

Invoice text to extract from:
"""


def _make_step(name, status, detail="", duration_ms=0):
    """Create a pipeline step record for the audit log."""
    return {
        "step": name,
        "status": status,  # "success", "warning", "error", "skipped"
        "detail": detail,
        "duration_ms": round(duration_ms, 1),
    }


def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        text = ""
        page_count = len(doc)
        for page in doc:
            text += page.get_text()
        doc.close()
        cleaned_text = text.strip()
        is_scanned = len(cleaned_text) < MIN_TEXT_LENGTH
        return cleaned_text, is_scanned, page_count
    except Exception as e:
        return "", True, 0


def extract_text_with_ocr(pdf_path):
    if not OCR_AVAILABLE:
        return "", "OCR libraries not installed (pytesseract/Pillow)", 0.0
    try:
        doc = fitz.open(pdf_path)
        text = ""
        confidences = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            page_text = pytesseract.image_to_string(img)
            text += page_text + "\n"
            try:
                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                for conf in data.get("conf", []):
                    try:
                        val = float(conf)
                        if val >= 0:
                            confidences.append(val / 100)
                    except (TypeError, ValueError):
                        continue
            except Exception:
                pass
        doc.close()
        avg_confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
        return text.strip(), "", avg_confidence
    except Exception as e:
        return "", str(e), 0.0


# Model fallback chain: highest quality first, progressively smaller.
# qwen3-32b sits between 70B and 8B in quality, and has 60 RPM (vs 30 for 70B).
MODEL_FALLBACK_CHAIN = [
    "llama-3.3-70b-versatile",      # Best quality, 30 RPM, 1K req/day
    "qwen/qwen3-32b",               # Strong mid-tier, 60 RPM, higher daily limit
    "llama-3.1-8b-instant",          # Fast fallback, 60 RPM, 14.4K req/day
]


def _clean_response(text):
    """Strip markdown code fences from LLM response."""
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()


def _call_model_with_retry(client, messages, model, max_retries=3):
    """
    Call Groq API with exponential backoff on 429 Rate Limit errors.
    Returns (response_text, error_str). error_str is empty on success.
    """
    delay = 5  # seconds — start conservative
    for attempt in range(max_retries):
        try:
            chat_completion = client.chat.completions.create(
                messages=messages,
                model=model,
                temperature=0,
                max_tokens=2000,
                timeout=30,
            )
            return chat_completion.choices[0].message.content.strip(), ""
        except RateLimitError as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2  # exponential backoff: 5s → 10s → 20s
            else:
                return "", f"Rate limit (429) after {max_retries} retries on {model}: {str(e)[:80]}"
        except Exception as e:
            return "", f"API call failed: {str(e)[:100]}"
    return "", "Unknown error in retry loop"


def call_groq_api(text, api_key):
    """Returns (extracted_data, success, detail_str, model_used, fallback_level)"""
    client = Groq(api_key=api_key)
    last_error = "No models available"

    for idx, model in enumerate(MODEL_FALLBACK_CHAIN):
        messages = [
            {"role": "system", "content": "You are a precise data extraction system. Return only valid JSON."},
            {"role": "user", "content": EXTRACTION_PROMPT + text},
        ]

        response_text, error = _call_model_with_retry(client, messages, model)

        if error:
            if "Rate limit" in error or "429" in error:
                last_error = error
                continue
            return get_empty_extraction(), False, error, model, idx

        response_text = _clean_response(response_text)

        try:
            extracted = json.loads(response_text)
            note = f"via {model}" if idx > 0 else ""
            return extracted, True, note, model, idx
        except json.JSONDecodeError:
            strict_messages = [
                {"role": "system", "content": "Return ONLY a valid JSON object. No text before or after. No markdown."},
                {"role": "user", "content": EXTRACTION_PROMPT + text},
            ]
            response_text2, error2 = _call_model_with_retry(client, strict_messages, model, max_retries=1)
            if error2:
                last_error = error2
                continue
            response_text2 = _clean_response(response_text2)
            try:
                extracted = json.loads(response_text2)
                note = f"Retry succeeded via {model}"
                return extracted, True, note, model, idx
            except Exception as e2:
                last_error = f"JSON parse failed on {model}: {str(e2)[:80]}"
                continue

    return get_empty_extraction(), False, last_error, "none", len(MODEL_FALLBACK_CHAIN)


def get_empty_extraction():
    return {
        "invoice_number": "NOT_FOUND",
        "invoice_date": "NOT_FOUND",
        "due_date": "NOT_FOUND",
        "vendor_name": "NOT_FOUND",
        "vendor_email": "NOT_FOUND",
        "po_number": "NOT_FOUND",
        "line_items": [],
        "tax_amount": "NOT_FOUND",
        "total_amount": "NOT_FOUND",
        "currency": "NOT_FOUND",
    }


def extract_invoice_data(pdf_path, api_key):
    """
    Main extraction function. Returns extracted data + metadata + pipeline_steps audit log.
    """
    pipeline_steps = []
    total_start = time.time()
    intake_metadata = create_document_metadata(pdf_path)

    result = {
        "extracted_data": get_empty_extraction(),
        "metadata": {
            **intake_metadata,
            "is_scanned": False,
            "document_type": "unknown",
            "extraction_method": "text",
            "raw_confidence": "high",
            "ocr_confidence": None,
            "field_confidences": {},
            "overall_extraction_confidence": 0.0,
            "extraction_error": None,
            "file_name": os.path.basename(pdf_path),
            "total_time_ms": 0,
            "model_used": None,
            "fallback_level": 0,
        },
        "pipeline_steps": pipeline_steps,
    }

    # Step 1: PDF text extraction
    pipeline_steps.append(_make_step(
        "Document Intake",
        "success",
        f"{intake_metadata['file_type'].upper()} received as {intake_metadata['document_id']}",
        0,
    ))
    t0 = time.time()
    text, is_scanned, page_count = extract_text_from_pdf(pdf_path)
    t1 = time.time()
    result["metadata"]["document_type"] = classify_document_type(text, MIN_TEXT_LENGTH)
    result["metadata"]["is_scanned"] = is_scanned

    if not is_scanned:
        pipeline_steps.append(_make_step(
            "PDF Text Extraction",
            "success",
            f"PyMuPDF extracted {len(text)} chars from {page_count} page(s)",
            (t1 - t0) * 1000,
        ))
    else:
        pipeline_steps.append(_make_step(
            "PDF Text Extraction",
            "warning",
            f"Only {len(text)} chars found ({page_count} pages). Likely scanned document.",
            (t1 - t0) * 1000,
        ))

    # Step 2: OCR fallback
    if is_scanned:
        result["metadata"]["extraction_method"] = "ocr"
        result["metadata"]["raw_confidence"] = "medium"

        t0 = time.time()
        ocr_text, ocr_error, ocr_confidence = extract_text_with_ocr(pdf_path)
        t1 = time.time()
        result["metadata"]["ocr_confidence"] = ocr_confidence

        if len(ocr_text.strip()) < MIN_TEXT_LENGTH:
            detail = ocr_error if ocr_error else "OCR returned insufficient text"
            pipeline_steps.append(_make_step("OCR Fallback", "error", detail, (t1 - t0) * 1000))
            result["metadata"]["raw_confidence"] = "low"
            result["metadata"]["extraction_error"] = f"Scanned invoice detected. {detail}. Manual processing required."
            result["metadata"]["total_time_ms"] = round((time.time() - total_start) * 1000, 1)
            return result

        pipeline_steps.append(_make_step(
            "OCR Fallback",
            "success" if ocr_confidence >= 0.65 else "warning",
            f"Tesseract extracted {len(ocr_text)} chars (confidence {ocr_confidence:.2f})",
            (t1 - t0) * 1000,
        ))
        text = ocr_text
    else:
        pipeline_steps.append(_make_step("OCR Fallback", "skipped", "Not needed, text PDF detected", 0))

    # Step 3: AI extraction
    if not text or len(text.strip()) < MIN_TEXT_LENGTH:
        pipeline_steps.append(_make_step("AI Extraction", "error", "No readable text to process", 0))
        result["metadata"]["raw_confidence"] = "low"
        result["metadata"]["extraction_error"] = "Could not extract readable text from PDF."
        result["metadata"]["total_time_ms"] = round((time.time() - total_start) * 1000, 1)
        return result

    t0 = time.time()
    extracted, success, api_detail, model_used, fallback_level = call_groq_api(text, api_key)
    t1 = time.time()

    result["metadata"]["model_used"] = model_used
    result["metadata"]["fallback_level"] = fallback_level

    if not success:
        pipeline_steps.append(_make_step("AI Extraction", "error", api_detail, (t1 - t0) * 1000))
        result["metadata"]["raw_confidence"] = "low"
        result["metadata"]["extraction_error"] = f"AI extraction failed. {api_detail}. Manual processing required."
        result["metadata"]["total_time_ms"] = round((time.time() - total_start) * 1000, 1)
        return result

    # Count extracted vs missing fields
    field_keys = [k for k in extracted.keys() if k != "line_items"]
    found_count = sum(1 for k in field_keys if extracted.get(k) != "NOT_FOUND")
    not_found_count = len(field_keys) - found_count
    line_item_count = len(extracted.get("line_items", []))

    detail = f"Extracted {found_count}/{len(field_keys)} fields, {line_item_count} line items"
    if fallback_level > 0:
        detail += f" (fallback to {model_used})"
    elif api_detail:
        detail += f" ({api_detail})"

    pipeline_steps.append(_make_step(
        "AI Extraction",
        "success" if not_found_count <= 2 else "warning",
        detail,
        (t1 - t0) * 1000,
    ))

    result["extracted_data"] = extracted
    field_confidences, overall_confidence = assess_extraction_confidence(extracted, result["metadata"])
    result["metadata"]["field_confidences"] = field_confidences
    result["metadata"]["overall_extraction_confidence"] = overall_confidence

    if not_found_count > len(field_keys) * 0.6:
        if result["metadata"]["extraction_method"] == "ocr":
            result["metadata"]["raw_confidence"] = "low"
        else:
            result["metadata"]["raw_confidence"] = "medium"

    result["metadata"]["total_time_ms"] = round((time.time() - total_start) * 1000, 1)
    return result


def assess_extraction_confidence(extracted, metadata):
    required_fields = ["invoice_number", "invoice_date", "vendor_name", "po_number", "total_amount", "tax_amount", "currency"]
    base_found = 0.82 if metadata.get("extraction_method") == "ocr" else 0.94
    if metadata.get("fallback_level", 0) > 0:
        base_found -= min(metadata.get("fallback_level", 0) * 0.05, 0.15)
    ocr_conf = metadata.get("ocr_confidence")
    if ocr_conf is not None:
        base_found = min(base_found, max(float(ocr_conf), 0.0))
    confidences = {}
    weights = {
        "invoice_number": 1.2,
        "vendor_name": 1.2,
        "po_number": 1.1,
        "total_amount": 1.3,
    }
    weighted_total = 0
    weight_sum = 0
    for field in required_fields:
        value = extracted.get(field, "NOT_FOUND")
        confidence = 0.0 if value == "NOT_FOUND" else round(max(min(base_found, 1.0), 0.0), 2)
        confidences[field] = {"value": value, "confidence": confidence}
        weight = weights.get(field, 1.0)
        weighted_total += confidence * weight
        weight_sum += weight
    overall = round(weighted_total / weight_sum, 2) if weight_sum else 0.0
    return confidences, overall


def parse_amount(value):
    if value == "NOT_FOUND" or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r'[₹$€£,\s]', '', value)
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None
