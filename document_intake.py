"""
document_intake.py - Lightweight document intake metadata.

This layer is intentionally small: it records stable file metadata before the
existing extraction pipeline decides whether to use text extraction or OCR.
"""

import mimetypes
import os
import uuid
from datetime import datetime


def create_document_metadata(file_path):
    file_type = _detect_file_type(file_path)
    return {
        "document_id": str(uuid.uuid4())[:8],
        "file_type": file_type,
        "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "ready_for_processing",
    }


def classify_document_type(extracted_text, threshold=50):
    if len((extracted_text or "").strip()) > threshold:
        return "text_pdf"
    return "scanned_pdf"


def _detect_file_type(file_path):
    guessed_type, _ = mimetypes.guess_type(file_path)
    if guessed_type == "application/pdf" or str(file_path).lower().endswith(".pdf"):
        return "pdf"
    return os.path.splitext(file_path)[1].lstrip(".").lower() or "unknown"
