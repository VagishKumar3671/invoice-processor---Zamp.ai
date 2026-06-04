"""
Generate 9 test invoice PDFs for the Invoice Processing Automation demo.
Each invoice tests a specific scenario/edge case.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from PIL import Image
import os
import io

OUTPUT_DIR = "test_invoices"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Colors
PRIMARY = HexColor("#1a1a2e")
ACCENT = HexColor("#16213e")
LIGHT_GRAY = HexColor("#f0f0f0")
BORDER = HexColor("#cccccc")
GREEN = HexColor("#2d6a4f")
RED = HexColor("#d62828")


def draw_invoice(c, width, height, data):
    """Draw a professional invoice on the canvas."""
    
    # --- Header band ---
    c.setFillColor(PRIMARY)
    c.rect(0, height - 100, width, 100, fill=True, stroke=False)
    
    # Company name
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(40, height - 50, data["vendor_name"] or "[Vendor Name Missing]")
    
    # Company tagline / address
    c.setFont("Helvetica", 9)
    c.drawString(40, height - 68, data.get("vendor_address", "123 Business Park, Mumbai, Maharashtra 400001"))
    c.drawString(40, height - 80, f"Email: {data.get('vendor_email', 'info@vendor.com')}  |  Phone: {data.get('vendor_phone', '+91 22 1234 5678')}")
    
    # INVOICE label on right
    c.setFont("Helvetica-Bold", 28)
    c.drawRightString(width - 40, height - 55, "INVOICE")
    
    # --- Invoice details section ---
    y = height - 130
    
    # Left column: Bill To
    c.setFillColor(PRIMARY)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "BILL TO:")
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(40, y - 18, "TechVentures India Pvt Ltd")
    c.drawString(40, y - 33, "456 Corporate Avenue, BKC")
    c.drawString(40, y - 48, "Mumbai, Maharashtra 400051")
    c.drawString(40, y - 63, "accounts@techventures.in")
    
    # Right column: Invoice details
    detail_x = width - 200
    c.setFillColor(PRIMARY)
    c.setFont("Helvetica-Bold", 10)
    
    details = []
    if data.get("invoice_number"):
        details.append(("Invoice No:", data["invoice_number"]))
    if data.get("invoice_date"):
        details.append(("Date:", data["invoice_date"]))
    if data.get("due_date"):
        details.append(("Due Date:", data["due_date"]))
    if data.get("po_number"):
        details.append(("PO Reference:", data["po_number"]))
    
    for i, (label, value) in enumerate(details):
        cy = y - (i * 18)
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(ACCENT)
        c.drawString(detail_x, cy, label)
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.black)
        c.drawString(detail_x + 90, cy, str(value))
    
    # --- Line items table ---
    table_top = y - 100
    
    # Table header
    c.setFillColor(PRIMARY)
    c.rect(35, table_top - 5, width - 70, 22, fill=True, stroke=False)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(45, table_top + 2, "#")
    c.drawString(65, table_top + 2, "Description")
    c.drawString(320, table_top + 2, "Qty")
    c.drawString(380, table_top + 2, "Unit Price")
    c.drawString(470, table_top + 2, "Amount")
    
    # Table rows
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    row_y = table_top - 22
    
    for i, item in enumerate(data["line_items"]):
        if i % 2 == 0:
            c.setFillColor(LIGHT_GRAY)
            c.rect(35, row_y - 5, width - 70, 20, fill=True, stroke=False)
        
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 9)
        c.drawString(45, row_y + 2, str(i + 1))
        c.drawString(65, row_y + 2, item["description"])
        c.drawString(320, row_y + 2, str(item.get("qty", "-")))
        c.drawString(380, row_y + 2, f"₹{item.get('unit_price', '-'):,.2f}" if isinstance(item.get('unit_price'), (int, float)) else str(item.get('unit_price', '-')))
        c.drawString(470, row_y + 2, f"₹{item['amount']:,.2f}")
        row_y -= 22
    
    # --- Totals section ---
    totals_y = row_y - 15
    
    # Divider line
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(350, totals_y + 10, width - 35, totals_y + 10)
    
    # Subtotal
    subtotal = sum(item["amount"] for item in data["line_items"])
    c.setFont("Helvetica", 10)
    c.drawString(370, totals_y - 5, "Subtotal:")
    c.drawRightString(width - 45, totals_y - 5, f"₹{subtotal:,.2f}")
    
    # Tax
    if data.get("tax_amount") is not None:
        tax = data["tax_amount"]
        tax_label = data.get("tax_label", "GST (18%)")
        c.drawString(370, totals_y - 25, f"{tax_label}:")
        c.drawRightString(width - 45, totals_y - 25, f"₹{tax:,.2f}")
        total_y_offset = 45
    else:
        total_y_offset = 25
    
    # Total
    c.setFillColor(PRIMARY)
    c.rect(350, totals_y - total_y_offset - 10, width - 385, 25, fill=True, stroke=False)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(370, totals_y - total_y_offset - 2, "TOTAL:")
    total = data.get("total_amount", subtotal + data.get("tax_amount", 0))
    c.drawRightString(width - 45, totals_y - total_y_offset - 2, f"₹{total:,.2f}")
    
    # --- Footer ---
    footer_y = 80
    c.setFillColor(BORDER)
    c.line(40, footer_y + 20, width - 40, footer_y + 20)
    
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 8)
    c.drawString(40, footer_y, "Payment Terms: Net 30 days from invoice date")
    c.drawString(40, footer_y - 14, f"Bank: HDFC Bank | Account: 1234567890 | IFSC: HDFC0001234")
    
    if data.get("notes"):
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(40, footer_y - 30, f"Note: {data['notes']}")
    
    c.setFont("Helvetica", 7)
    c.setFillColor(HexColor("#888888"))
    c.drawCentredString(width / 2, 30, "This is a computer-generated invoice and does not require a physical signature.")


def create_invoice_pdf(filename, data):
    """Create a single invoice PDF."""
    filepath = os.path.join(OUTPUT_DIR, filename)
    width, height = A4
    c = canvas.Canvas(filepath, pagesize=A4)
    draw_invoice(c, width, height, data)
    c.save()
    print(f"Created: {filepath}")
    return filepath


def create_scanned_invoice_pdf(filename, data):
    """Create a PDF that looks like a scanned image (for OCR testing)."""
    # First create a normal invoice as a temporary PDF
    temp_path = os.path.join(OUTPUT_DIR, "temp_scan.pdf")
    width, height = A4
    c = canvas.Canvas(temp_path, pagesize=A4)
    draw_invoice(c, width, height, data)
    c.save()
    
    # Convert PDF page to image using reportlab's renderPM is not available,
    # so we'll create the invoice directly as an image then embed it
    # Alternative approach: create invoice content as image using PIL
    
    import subprocess
    # Use a different approach: create a PDF with the invoice drawn as an image
    # We'll use the canvas to draw the invoice, save as PDF, then re-embed as image
    
    # Simple approach: create the invoice visually using PIL
    from PIL import Image, ImageDraw, ImageFont
    
    img_width, img_height = 595, 842  # A4 at 72 DPI
    img = Image.new('RGB', (img_width, img_height), 'white')
    draw = ImageDraw.Draw(img)
    
    # Add some noise/grain to simulate scan
    import random
    for _ in range(3000):
        x = random.randint(0, img_width - 1)
        y = random.randint(0, img_height - 1)
        gray = random.randint(200, 240)
        draw.point((x, y), fill=(gray, gray, gray))
    
    # Draw header
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_bold = ImageFont.load_default()
    
    # Header bar
    draw.rectangle([0, 0, img_width, 80], fill=(26, 26, 46))
    draw.text((30, 20), data["vendor_name"], fill="white", font=font_large)
    draw.text((30, 50), f"Email: {data.get('vendor_email', '')}", fill="white", font=font_small)
    draw.text((400, 25), "INVOICE", fill="white", font=font_large)
    
    # Invoice details
    y = 110
    draw.text((30, y), "BILL TO: TechVentures India Pvt Ltd", fill="black", font=font_bold)
    y += 20
    draw.text((30, y), "456 Corporate Avenue, BKC, Mumbai", fill="black", font=font_small)
    
    # Right side details
    if data.get("invoice_number"):
        draw.text((370, 110), f"Invoice No: {data['invoice_number']}", fill="black", font=font_small)
    if data.get("invoice_date"):
        draw.text((370, 128), f"Date: {data['invoice_date']}", fill="black", font=font_small)
    if data.get("po_number"):
        draw.text((370, 146), f"PO Ref: {data['po_number']}", fill="black", font=font_small)
    
    # Line items
    y = 200
    draw.rectangle([25, y, img_width - 25, y + 22], fill=(26, 26, 46))
    draw.text((35, y + 3), "#   Description                          Qty    Unit Price    Amount", fill="white", font=font_small)
    y += 30
    
    for i, item in enumerate(data["line_items"]):
        text = f"{i+1}   {item['description']:<38} {item.get('qty', '-'):<6} Rs.{item.get('unit_price', 0):>10,.2f}    Rs.{item['amount']:>10,.2f}"
        draw.text((35, y), text, fill="black", font=font_small)
        y += 22
    
    # Totals
    y += 15
    draw.line([(350, y), (img_width - 30, y)], fill="gray")
    y += 10
    subtotal = sum(item["amount"] for item in data["line_items"])
    draw.text((370, y), f"Subtotal: Rs.{subtotal:,.2f}", fill="black", font=font_small)
    y += 20
    if data.get("tax_amount"):
        draw.text((370, y), f"GST (18%): Rs.{data['tax_amount']:,.2f}", fill="black", font=font_small)
        y += 20
    total = data.get("total_amount", subtotal + data.get("tax_amount", 0))
    draw.rectangle([350, y, img_width - 30, y + 22], fill=(26, 26, 46))
    draw.text((370, y + 3), f"TOTAL: Rs.{total:,.2f}", fill="white", font=font_bold)
    
    # Slight rotation to simulate scan misalignment
    img = img.rotate(0.5, fillcolor='white', expand=False)
    
    # Save as image
    img_path = os.path.join(OUTPUT_DIR, "temp_scan.png")
    img.save(img_path, 'PNG')
    
    # Create PDF with just the image (no selectable text)
    filepath = os.path.join(OUTPUT_DIR, filename)
    c = canvas.Canvas(filepath, pagesize=A4)
    c.drawImage(img_path, 0, 0, width=A4[0], height=A4[1])
    c.save()
    
    # Cleanup
    os.remove(img_path)
    if os.path.exists(temp_path):
        os.remove(temp_path)
    
    print(f"Created (scanned): {filepath}")
    return filepath


# ============================================================
# INVOICE 1: Happy Path - Perfect Match
# PO-2024-001, Acme Supplies, PO amount = 50,000
# ============================================================
create_invoice_pdf("invoice_1_happy_path.pdf", {
    "vendor_name": "Acme Supplies Pvt Ltd",
    "vendor_email": "billing@acmesupplies.com",
    "vendor_phone": "+91 22 2345 6789",
    "vendor_address": "78 Industrial Estate, Andheri East, Mumbai 400069",
    "invoice_number": "INV-2024-1001",
    "invoice_date": "2024-03-15",
    "due_date": "2024-04-15",
    "po_number": "PO-2024-001",
    "line_items": [
        {"description": "Ergonomic Office Chairs (Model X200)", "qty": 10, "unit_price": 2500.00, "amount": 25000.00},
        {"description": "Standing Desks (Adjustable)", "qty": 5, "unit_price": 3000.00, "amount": 15000.00},
        {"description": "Monitor Arms (Dual Mount)", "qty": 10, "unit_price": 237.29, "amount": 2372.88},
    ],
    "tax_amount": 7627.12,
    "tax_label": "GST (18%)",
    "total_amount": 50000.00,
})

# ============================================================
# INVOICE 2: Amount Within Tolerance (3% over)
# PO-2024-002, Beta Technologies, PO amount = 125,000
# Invoice = 128,750 (3% over)
# ============================================================
create_invoice_pdf("invoice_2_within_tolerance.pdf", {
    "vendor_name": "Beta Technologies",
    "vendor_email": "accounts@betatech.com",
    "vendor_phone": "+91 80 4567 8901",
    "vendor_address": "22 Tech Park, Whitefield, Bangalore 560066",
    "invoice_number": "INV-2024-1002",
    "invoice_date": "2024-03-20",
    "due_date": "2024-04-20",
    "po_number": "PO-2024-002",
    "line_items": [
        {"description": "Enterprise Software License (Annual)", "qty": 1, "unit_price": 85000.00, "amount": 85000.00},
        {"description": "Premium Support Package", "qty": 1, "unit_price": 24110.17, "amount": 24110.17},
    ],
    "tax_amount": 19639.83,
    "tax_label": "GST (18%)",
    "total_amount": 128750.00,
    "notes": "License renewed for FY 2024-25. Support includes 24/7 coverage.",
})

# ============================================================
# INVOICE 3: Amount Outside Tolerance (15% over)
# PO-2024-003, Gamma Services, PO amount = 30,000
# Invoice = 34,500 (15% over)
# ============================================================
create_invoice_pdf("invoice_3_over_tolerance.pdf", {
    "vendor_name": "Gamma Services",
    "vendor_email": "finance@gammaservices.com",
    "vendor_phone": "+91 11 6789 0123",
    "vendor_address": "15 Consulting Plaza, Connaught Place, New Delhi 110001",
    "invoice_number": "INV-2024-1003",
    "invoice_date": "2024-03-25",
    "due_date": "2024-04-25",
    "po_number": "PO-2024-003",
    "line_items": [
        {"description": "Strategy Consulting - Phase 1", "qty": 1, "unit_price": 20000.00, "amount": 20000.00},
        {"description": "Market Research Report", "qty": 1, "unit_price": 9237.29, "amount": 9237.29},
    ],
    "tax_amount": 5262.71,
    "tax_label": "GST (18%)",
    "total_amount": 34500.00,
    "notes": "Additional research scope added per email discussion dated 15-Mar-2024.",
})

# ============================================================
# INVOICE 4: Duplicate of Invoice 1
# Same invoice number, same vendor, same amount
# ============================================================
create_invoice_pdf("invoice_4_duplicate.pdf", {
    "vendor_name": "Acme Supplies Pvt Ltd",
    "vendor_email": "billing@acmesupplies.com",
    "vendor_phone": "+91 22 2345 6789",
    "vendor_address": "78 Industrial Estate, Andheri East, Mumbai 400069",
    "invoice_number": "INV-2024-1001",
    "invoice_date": "2024-03-15",
    "due_date": "2024-04-15",
    "po_number": "PO-2024-001",
    "line_items": [
        {"description": "Ergonomic Office Chairs (Model X200)", "qty": 10, "unit_price": 2500.00, "amount": 25000.00},
        {"description": "Standing Desks (Adjustable)", "qty": 5, "unit_price": 3000.00, "amount": 15000.00},
        {"description": "Monitor Arms (Dual Mount)", "qty": 10, "unit_price": 237.29, "amount": 2372.88},
    ],
    "tax_amount": 7627.12,
    "tax_label": "GST (18%)",
    "total_amount": 50000.00,
})

# ============================================================
# INVOICE 5: No PO Reference
# Delta Logistics, Amount = 74,000 (close to PO-2024-004 = 75,000)
# PO number deliberately NOT included
# ============================================================
create_invoice_pdf("invoice_5_no_po.pdf", {
    "vendor_name": "Delta Logistics",
    "vendor_email": "invoices@deltalogistics.com",
    "vendor_phone": "+91 44 7890 1234",
    "vendor_address": "99 Warehouse Road, Guindy, Chennai 600032",
    "invoice_number": "INV-2024-1005",
    "invoice_date": "2024-04-01",
    "due_date": "2024-05-01",
    # NO po_number field - this is the edge case
    "line_items": [
        {"description": "Freight Charges - Mumbai to Delhi", "qty": 3, "unit_price": 12000.00, "amount": 36000.00},
        {"description": "Warehousing Fee - March 2024", "qty": 1, "unit_price": 15000.00, "amount": 15000.00},
        {"description": "Packaging and Handling", "qty": 1, "unit_price": 11711.86, "amount": 11711.86},
    ],
    "tax_amount": 11288.14,
    "tax_label": "GST (18%)",
    "total_amount": 74000.00,
})

# ============================================================
# INVOICE 6: Partial Invoice (First) against PO-2024-005
# Acme Supplies, PO = 20,000, Invoice = 12,000
# ============================================================
create_invoice_pdf("invoice_6_partial_first.pdf", {
    "vendor_name": "Acme Supplies Pvt Ltd",
    "vendor_email": "billing@acmesupplies.com",
    "vendor_phone": "+91 22 2345 6789",
    "vendor_address": "78 Industrial Estate, Andheri East, Mumbai 400069",
    "invoice_number": "INV-2024-1006",
    "invoice_date": "2024-04-05",
    "due_date": "2024-05-05",
    "po_number": "PO-2024-005",
    "line_items": [
        {"description": "HP LaserJet Toner Cartridge (Black)", "qty": 15, "unit_price": 550.00, "amount": 8250.00},
        {"description": "A4 Printer Paper (500 sheets/ream)", "qty": 10, "unit_price": 191.53, "amount": 1915.25},
    ],
    "tax_amount": 1834.75,
    "tax_label": "GST (18%)",
    "total_amount": 12000.00,
    "notes": "Partial delivery. Remaining items to follow in next shipment.",
})

# ============================================================
# INVOICE 7: Partial Invoice (Second - pushes cumulative over PO)
# Same PO-2024-005, PO = 20,000, This invoice = 12,000
# Cumulative would be 24,000 (20% over PO)
# ============================================================
create_invoice_pdf("invoice_7_partial_over.pdf", {
    "vendor_name": "Acme Supplies Pvt Ltd",
    "vendor_email": "billing@acmesupplies.com",
    "vendor_phone": "+91 22 2345 6789",
    "vendor_address": "78 Industrial Estate, Andheri East, Mumbai 400069",
    "invoice_number": "INV-2024-1007",
    "invoice_date": "2024-04-15",
    "due_date": "2024-05-15",
    "po_number": "PO-2024-005",
    "line_items": [
        {"description": "HP LaserJet Toner Cartridge (Color Set)", "qty": 10, "unit_price": 750.00, "amount": 7500.00},
        {"description": "Printer Drum Unit", "qty": 2, "unit_price": 1271.19, "amount": 2542.37},
    ],
    "tax_amount": 1957.63,
    "tax_label": "GST (18%)",
    "total_amount": 12000.00,
    "notes": "Final delivery against PO-2024-005.",
})

# ============================================================
# INVOICE 8: Unknown Vendor
# Phantom Industries - not in vendor master at all
# ============================================================
create_invoice_pdf("invoice_8_unknown_vendor.pdf", {
    "vendor_name": "Phantom Industries",
    "vendor_email": "accounts@phantomindustries.com",
    "vendor_phone": "+91 33 4567 8900",
    "vendor_address": "42 Shadow Lane, Salt Lake City, Kolkata 700091",
    "invoice_number": "INV-2024-1008",
    "invoice_date": "2024-04-10",
    "due_date": "2024-05-10",
    "po_number": "PO-2024-099",
    "line_items": [
        {"description": "Industrial Cleaning Supplies", "qty": 50, "unit_price": 500.00, "amount": 25000.00},
        {"description": "Safety Equipment (PPE Kits)", "qty": 20, "unit_price": 635.59, "amount": 12711.86},
    ],
    "tax_amount": 7288.14,
    "tax_label": "GST (18%)",
    "total_amount": 45000.00,
})

# ============================================================
# INVOICE 9: Scanned/Image PDF (for OCR testing)
# Beta Technologies, same as PO-2024-002
# ============================================================
create_scanned_invoice_pdf("invoice_9_scanned.pdf", {
    "vendor_name": "Beta Technologies",
    "vendor_email": "accounts@betatech.com",
    "vendor_phone": "+91 80 4567 8901",
    "vendor_address": "22 Tech Park, Whitefield, Bangalore 560066",
    "invoice_number": "INV-2024-1009",
    "invoice_date": "2024-04-12",
    "due_date": "2024-05-12",
    "po_number": "PO-2024-002",
    "line_items": [
        {"description": "Software License Renewal", "qty": 1, "unit_price": 90000.00, "amount": 90000.00},
        {"description": "Implementation Support", "qty": 1, "unit_price": 15889.83, "amount": 15889.83},
    ],
    "tax_amount": 19110.17,
    "tax_label": "GST (18%)",
    "total_amount": 125000.00,
})

# ============================================================
# INVOICE 10: Credit Note (Negative Amount)
# Gamma Services issues a credit note for ₹-5,000
# ============================================================
create_invoice_pdf("invoice_10_credit_note.pdf", {
    "vendor_name": "Gamma Services",
    "vendor_email": "finance@gammaservices.com",
    "vendor_phone": "+91 22 3456 7890",
    "vendor_address": "55 Service Road, Powai, Mumbai 400076",
    "invoice_number": "CN-2024-0042",
    "invoice_date": "2024-04-18",
    "due_date": "",
    "po_number": "PO-2024-003",
    "line_items": [
        {"description": "Credit: Overcharge on Q1 consulting hours", "qty": 1, "unit_price": -4237.29, "amount": -4237.29},
    ],
    "tax_amount": -762.71,
    "tax_label": "GST (18%)",
    "total_amount": -5000.00,
    "notes": "Credit note against original INV-2024-0888. Please adjust in next payment cycle.",
})

# ============================================================
# INVOICE 11: Invoice Against Closed PO
# Beta Technologies invoices against PO-2024-006 which is Closed
# ============================================================
create_invoice_pdf("invoice_11_closed_po.pdf", {
    "vendor_name": "Beta Technologies",
    "vendor_email": "accounts@betatech.com",
    "vendor_phone": "+91 80 4567 8901",
    "vendor_address": "22 Tech Park, Whitefield, Bangalore 560066",
    "invoice_number": "INV-2024-1011",
    "invoice_date": "2024-04-20",
    "due_date": "2024-05-20",
    "po_number": "PO-2024-006",
    "line_items": [
        {"description": "Cloud Infrastructure Setup - Phase 2", "qty": 1, "unit_price": 42372.88, "amount": 42372.88},
        {"description": "Configuration & Testing", "qty": 1, "unit_price": 8474.58, "amount": 8474.58},
    ],
    "tax_amount": 9152.54,
    "tax_label": "GST (18%)",
    "total_amount": 60000.00,
    "notes": "Phase 2 delivery as discussed with project team.",
})

# ============================================================
# INVOICE 12: Unapproved Vendor
# Omega Corp exists in vendor master but approved=No
# ============================================================
create_invoice_pdf("invoice_12_unapproved_vendor.pdf", {
    "vendor_name": "Omega Corp",
    "vendor_email": "billing@omegacorp.com",
    "vendor_phone": "+91 40 5678 9012",
    "vendor_address": "8 Enterprise Hub, HITEC City, Hyderabad 500081",
    "invoice_number": "INV-2024-1012",
    "invoice_date": "2024-04-22",
    "due_date": "2024-05-22",
    "po_number": "PO-2024-001",
    "line_items": [
        {"description": "Office Renovation Materials", "qty": 1, "unit_price": 33898.31, "amount": 33898.31},
        {"description": "Labour Charges", "qty": 1, "unit_price": 8474.58, "amount": 8474.58},
    ],
    "tax_amount": 7627.11,
    "tax_label": "GST (18%)",
    "total_amount": 50000.00,
})

# ============================================================
# INVOICE 13: Vendor Name Typo / Abbreviation
# "Acme Supplies" instead of "Acme Supplies Pvt Ltd"
# Tests fuzzy matching at 85%+
# ============================================================
create_invoice_pdf("invoice_13_vendor_typo.pdf", {
    "vendor_name": "Acme Supplies",
    "vendor_email": "billing@acmesupplies.com",
    "vendor_phone": "+91 22 2345 6789",
    "vendor_address": "78 Industrial Estate, Andheri East, Mumbai 400069",
    "invoice_number": "INV-2024-1013",
    "invoice_date": "2024-04-25",
    "due_date": "2024-05-25",
    "po_number": "PO-2024-001",
    "line_items": [
        {"description": "Cable Management Kit", "qty": 20, "unit_price": 2118.64, "amount": 42372.88},
    ],
    "tax_amount": 7627.12,
    "tax_label": "GST (18%)",
    "total_amount": 50000.00,
    "notes": "Replacement order for damaged items from first delivery.",
})

# ============================================================
# INVOICE 14: Missing Invoice Number
# All other fields present. Tests critical field check.
# ============================================================
create_invoice_pdf("invoice_14_no_invoice_number.pdf", {
    "vendor_name": "Gamma Services",
    "vendor_email": "finance@gammaservices.com",
    "vendor_phone": "+91 11 6789 0123",
    "vendor_address": "15 Consulting Plaza, Connaught Place, New Delhi 110001",
    # NO invoice_number
    "invoice_date": "2024-04-28",
    "due_date": "2024-05-28",
    "po_number": "PO-2024-003",
    "line_items": [
        {"description": "Advisory Services - April 2024", "qty": 40, "unit_price": 635.59, "amount": 25423.73},
    ],
    "tax_amount": 4576.27,
    "tax_label": "GST (18%)",
    "total_amount": 30000.00,
})

# ============================================================
# INVOICE 15: Missing Vendor Name
# Invoice has no vendor name. Tests critical field check.
# ============================================================
create_invoice_pdf("invoice_15_no_vendor_name.pdf", {
    "vendor_name": "",  # empty
    "vendor_email": "unknown@company.com",
    "vendor_phone": "+91 22 0000 0000",
    "invoice_number": "INV-2024-1015",
    "invoice_date": "2024-04-29",
    "due_date": "2024-05-29",
    "po_number": "PO-2024-004",
    "line_items": [
        {"description": "Shipping Services", "qty": 1, "unit_price": 63559.32, "amount": 63559.32},
    ],
    "tax_amount": 11440.68,
    "tax_label": "GST (18%)",
    "total_amount": 75000.00,
})

# ============================================================
# INVOICE 16: Future-Dated Invoice
# Invoice date is 2027. Tests date sanity check.
# ============================================================
create_invoice_pdf("invoice_16_future_date.pdf", {
    "vendor_name": "Delta Logistics",
    "vendor_email": "invoices@deltalogistics.com",
    "vendor_phone": "+91 44 7890 1234",
    "vendor_address": "99 Warehouse Road, Guindy, Chennai 600032",
    "invoice_number": "INV-2024-1016",
    "invoice_date": "2027-06-15",
    "due_date": "2027-07-15",
    "po_number": "PO-2024-004",
    "line_items": [
        {"description": "Advance Booking - Warehouse Space H2 2027", "qty": 1, "unit_price": 63559.32, "amount": 63559.32},
    ],
    "tax_amount": 11440.68,
    "tax_label": "GST (18%)",
    "total_amount": 75000.00,
})

# ============================================================
# INVOICE 17: Stale Invoice (>180 days old)
# Invoice from 2023. Tests date sanity check.
# ============================================================
create_invoice_pdf("invoice_17_stale_invoice.pdf", {
    "vendor_name": "Gamma Services",
    "vendor_email": "finance@gammaservices.com",
    "vendor_phone": "+91 11 6789 0123",
    "vendor_address": "15 Consulting Plaza, Connaught Place, New Delhi 110001",
    "invoice_number": "INV-2023-0555",
    "invoice_date": "2023-06-10",
    "due_date": "2023-07-10",
    "po_number": "PO-2024-003",
    "line_items": [
        {"description": "Consulting Services - Q2 2023", "qty": 1, "unit_price": 25423.73, "amount": 25423.73},
    ],
    "tax_amount": 4576.27,
    "tax_label": "GST (18%)",
    "total_amount": 30000.00,
    "notes": "Late submission. Originally misplaced in vendor's filing system.",
})

# ============================================================
# INVOICE 18: Exact Tolerance Boundary (5.0% over)
# PO-2024-003 = 30,000. Invoice = 31,500 (exactly 5%)
# Should PASS at default 5% tolerance
# ============================================================
create_invoice_pdf("invoice_18_exact_tolerance.pdf", {
    "vendor_name": "Gamma Services",
    "vendor_email": "finance@gammaservices.com",
    "vendor_phone": "+91 11 6789 0123",
    "vendor_address": "15 Consulting Plaza, Connaught Place, New Delhi 110001",
    "invoice_number": "INV-2024-1018",
    "invoice_date": "2024-05-01",
    "due_date": "2024-06-01",
    "po_number": "PO-2024-003",
    "line_items": [
        {"description": "Process Optimization Consulting", "qty": 1, "unit_price": 26694.92, "amount": 26694.92},
    ],
    "tax_amount": 4805.08,
    "tax_label": "GST (18%)",
    "total_amount": 31500.00,
    "notes": "Includes agreed scope adjustment per Change Request CR-042.",
})

# ============================================================
# INVOICE 19: Just Over Tolerance (7.2% over)
# PO-2024-004 = 75,000. Invoice = 80,400 (7.2%)
# Should be FLAGGED (5-10% range)
# ============================================================
create_invoice_pdf("invoice_19_just_over_tolerance.pdf", {
    "vendor_name": "Delta Logistics",
    "vendor_email": "invoices@deltalogistics.com",
    "vendor_phone": "+91 44 7890 1234",
    "vendor_address": "99 Warehouse Road, Guindy, Chennai 600032",
    "invoice_number": "INV-2024-1019",
    "invoice_date": "2024-05-05",
    "due_date": "2024-06-05",
    "po_number": "PO-2024-004",
    "line_items": [
        {"description": "Freight Charges - Emergency Shipment", "qty": 5, "unit_price": 10000.00, "amount": 50000.00},
        {"description": "Express Surcharge", "qty": 1, "unit_price": 18135.59, "amount": 18135.59},
    ],
    "tax_amount": 12264.41,
    "tax_label": "GST (18%)",
    "total_amount": 80400.00,
    "notes": "Express surcharge applied due to urgent delivery request.",
})

# ============================================================
# INVOICE 20: PO Number Not Found in System
# References a PO that doesn't exist at all
# ============================================================
create_invoice_pdf("invoice_20_po_not_found.pdf", {
    "vendor_name": "Acme Supplies Pvt Ltd",
    "vendor_email": "billing@acmesupplies.com",
    "vendor_phone": "+91 22 2345 6789",
    "vendor_address": "78 Industrial Estate, Andheri East, Mumbai 400069",
    "invoice_number": "INV-2024-1020",
    "invoice_date": "2024-05-08",
    "due_date": "2024-06-08",
    "po_number": "PO-2024-777",
    "line_items": [
        {"description": "Office Supplies - Miscellaneous", "qty": 1, "unit_price": 12711.86, "amount": 12711.86},
    ],
    "tax_amount": 2288.14,
    "tax_label": "GST (18%)",
    "total_amount": 15000.00,
})

# ============================================================
# INVOICE 21: Lump Sum / Bundled (Single Line Item)
# Tests AI extraction when items are bundled as one entry
# ============================================================
create_invoice_pdf("invoice_21_lump_sum.pdf", {
    "vendor_name": "Beta Technologies",
    "vendor_email": "accounts@betatech.com",
    "vendor_phone": "+91 80 4567 8901",
    "vendor_address": "22 Tech Park, Whitefield, Bangalore 560066",
    "invoice_number": "INV-2024-1021",
    "invoice_date": "2024-05-10",
    "due_date": "2024-06-10",
    "po_number": "PO-2024-002",
    "line_items": [
        {"description": "Annual Software License + Premium Support + Implementation (Bundle)", "qty": 1, "unit_price": 105932.20, "amount": 105932.20},
    ],
    "tax_amount": 19067.80,
    "tax_label": "GST (18%)",
    "total_amount": 125000.00,
})

# ============================================================
# INVOICE 22: Many Line Items (stress test)
# Tests extraction with 8 line items
# ============================================================
create_invoice_pdf("invoice_22_many_line_items.pdf", {
    "vendor_name": "Acme Supplies Pvt Ltd",
    "vendor_email": "billing@acmesupplies.com",
    "vendor_phone": "+91 22 2345 6789",
    "vendor_address": "78 Industrial Estate, Andheri East, Mumbai 400069",
    "invoice_number": "INV-2024-1022",
    "invoice_date": "2024-05-12",
    "due_date": "2024-06-12",
    "po_number": "PO-2024-001",
    "line_items": [
        {"description": "Whiteboard Markers (Box of 12)", "qty": 10, "unit_price": 350.00, "amount": 3500.00},
        {"description": "A4 Notebooks (100 pages)", "qty": 50, "unit_price": 80.00, "amount": 4000.00},
        {"description": "Sticky Notes (Pack of 6)", "qty": 30, "unit_price": 120.00, "amount": 3600.00},
        {"description": "Ball Pens (Box of 20)", "qty": 15, "unit_price": 200.00, "amount": 3000.00},
        {"description": "File Folders (Pack of 10)", "qty": 20, "unit_price": 180.00, "amount": 3600.00},
        {"description": "Paper Clips (Box of 100)", "qty": 10, "unit_price": 50.00, "amount": 500.00},
        {"description": "Stapler + Pins Kit", "qty": 10, "unit_price": 350.00, "amount": 3500.00},
        {"description": "Desk Organiser", "qty": 10, "unit_price": 2067.37, "amount": 20673.73},
    ],
    "tax_amount": 7626.27,
    "tax_label": "GST (18%)",
    "total_amount": 50000.00,
})

# ============================================================
# INVOICE 23: No Tax Line (tax embedded in total)
# Tests edge case where there's no separate tax amount
# ============================================================
create_invoice_pdf("invoice_23_no_tax_line.pdf", {
    "vendor_name": "Gamma Services",
    "vendor_email": "finance@gammaservices.com",
    "vendor_phone": "+91 11 6789 0123",
    "vendor_address": "15 Consulting Plaza, Connaught Place, New Delhi 110001",
    "invoice_number": "INV-2024-1023",
    "invoice_date": "2024-05-15",
    "due_date": "2024-06-15",
    "po_number": "PO-2024-003",
    "line_items": [
        {"description": "Management Consulting (All-Inclusive)", "qty": 1, "unit_price": 30000.00, "amount": 30000.00},
    ],
    # NO tax_amount - taxes included in total
    "total_amount": 30000.00,
    "notes": "All prices inclusive of applicable taxes. No separate GST line.",
})

# ============================================================
# INVOICE 24: Blank/Corrupted PDF
# Creates a PDF with no extractable content
# ============================================================
def create_blank_pdf(filename):
    """Create a completely blank PDF (corrupted/empty invoice)."""
    filepath = os.path.join(OUTPUT_DIR, filename)
    c_obj = canvas.Canvas(filepath, pagesize=A4)
    c_obj.setFont("Helvetica", 6)
    c_obj.setFillColor(HexColor("#f0f0f0"))
    c_obj.drawString(10, 10, ".")  # minimal content so it's a valid PDF
    c_obj.save()
    print(f"Created (blank): {filepath}")
    return filepath

create_blank_pdf("invoice_24_blank.pdf")

# ============================================================
# INVOICE 25: Missing Due Date Only (minor missing field)
# Tests that missing non-critical fields still work
# ============================================================
create_invoice_pdf("invoice_25_no_due_date.pdf", {
    "vendor_name": "Delta Logistics",
    "vendor_email": "invoices@deltalogistics.com",
    "vendor_phone": "+91 44 7890 1234",
    "vendor_address": "99 Warehouse Road, Guindy, Chennai 600032",
    "invoice_number": "INV-2024-1025",
    "invoice_date": "2024-05-18",
    # NO due_date
    "po_number": "PO-2024-004",
    "line_items": [
        {"description": "Local Delivery Services - May 2024", "qty": 10, "unit_price": 6355.93, "amount": 63559.32},
    ],
    "tax_amount": 11440.68,
    "tax_label": "GST (18%)",
    "total_amount": 75000.00,
})


print("\n" + "=" * 60)
print("✅ All 25 test invoices created successfully!")
print(f"Location: {os.path.abspath(OUTPUT_DIR)}/")
print("=" * 60)
print("""
DEMO ORDER AND EXPECTED RESULTS:
═══════════════════════════════════════════════════════════
#   File                              Expected Status
─── ────────────────────────────────  ────────────────────
 1  invoice_1_happy_path.pdf          ✅ Approved
 2  invoice_2_within_tolerance.pdf    ✅ Approved (3% note)
 3  invoice_3_over_tolerance.pdf      🔴 Rejected (15% over)
 4  invoice_4_duplicate.pdf           🔴 Rejected (dup of #1) ← RUN AFTER #1
 5  invoice_5_no_po.pdf               🟡 Flagged (fuzzy PO)
 6  invoice_6_partial_first.pdf       ✅ Approved (partial)
 7  invoice_7_partial_over.pdf        🟡 Flagged (cumul.) ← RUN AFTER #6
 8  invoice_8_unknown_vendor.pdf      🔴 Rejected (unknown)
 9  invoice_9_scanned.pdf             🟡 Flagged (OCR)
10  invoice_10_credit_note.pdf        🟡 Flagged (credit note)
11  invoice_11_closed_po.pdf          🟡 Flagged (closed PO)
12  invoice_12_unapproved_vendor.pdf  🔴 Rejected (not approved)
13  invoice_13_vendor_typo.pdf        ✅ Approved (fuzzy vendor)
14  invoice_14_no_invoice_number.pdf  🟡 Flagged (missing inv #)
15  invoice_15_no_vendor_name.pdf     🟡 Flagged (missing vendor)
16  invoice_16_future_date.pdf        🟡 Flagged (future date)
17  invoice_17_stale_invoice.pdf      🟡 Flagged (>180 days old)
18  invoice_18_exact_tolerance.pdf    ✅ Approved (exactly 5%)
19  invoice_19_just_over_tolerance.pdf 🟡 Flagged (7.2% over)
20  invoice_20_po_not_found.pdf       🟡 Flagged (PO-777 missing)
21  invoice_21_lump_sum.pdf           ✅ Approved (bundled)
22  invoice_22_many_line_items.pdf    ✅ Approved (8 items) *dup of #1
23  invoice_23_no_tax_line.pdf        ✅ Approved (no tax)
24  invoice_24_blank.pdf              🟡 Flagged (extraction fail)
25  invoice_25_no_due_date.pdf        ✅ Approved (minor missing)

BATCH TEST GROUPS:
═══════════════════════════════════════════════════════════
Batch A (Happy Path):        1, 2, 18, 21, 23, 25
Batch B (Rejection Suite):   3, 8, 12
Batch C (Flag Suite):        5, 10, 11, 16, 17, 19, 20
Batch D (Sequence: Dup):     Run #1 first, then #4
Batch E (Sequence: Cumul):   Run #6 first, then #7
Batch F (Missing Fields):    14, 15, 24
Batch G (Vendor Tests):      8, 12, 13
Batch H (Tolerance Range):   2, 18, 19, 3
Batch I (Tax/Currency):      26, 27, 28, 29
""")

# ============================================================
# INVOICE 26: Wrong Tax Rate (12% instead of 18%)
# Gamma Services, PO-2024-003 = 30,000
# Subtotal = 26,785.71, Tax at 12% = 3,214.29, Total = 30,000
# ============================================================
create_invoice_pdf("invoice_26_tax_12pct.pdf", {
    "vendor_name": "Gamma Services",
    "vendor_email": "finance@gammaservices.com",
    "vendor_phone": "+91 11 6789 0123",
    "vendor_address": "15 Consulting Plaza, Connaught Place, New Delhi 110001",
    "invoice_number": "INV-2024-1026",
    "invoice_date": "2024-05-20",
    "due_date": "2024-06-20",
    "po_number": "PO-2024-003",
    "line_items": [
        {"description": "Consulting Services - Special Rate", "qty": 1, "unit_price": 26785.71, "amount": 26785.71},
    ],
    "tax_amount": 3214.29,
    "tax_label": "GST (12%)",
    "total_amount": 30000.00,
    "notes": "GST at 12% applied as per exempted service category.",
})

# ============================================================
# INVOICE 27: Zero Tax / Tax Missing
# Acme Supplies, PO-2024-001 = 50,000
# No tax at all - entire amount is line items
# ============================================================
create_invoice_pdf("invoice_27_zero_tax.pdf", {
    "vendor_name": "Acme Supplies Pvt Ltd",
    "vendor_email": "billing@acmesupplies.com",
    "vendor_phone": "+91 22 2345 6789",
    "vendor_address": "78 Industrial Estate, Andheri East, Mumbai 400069",
    "invoice_number": "INV-2024-1027",
    "invoice_date": "2024-05-22",
    "due_date": "2024-06-22",
    "po_number": "PO-2024-001",
    "line_items": [
        {"description": "Office Supplies (Tax Exempt)", "qty": 1, "unit_price": 50000.00, "amount": 50000.00},
    ],
    "total_amount": 50000.00,
    "notes": "Tax exempt supply under GST Schedule. No GST applicable.",
})

# ============================================================
# INVOICE 28: EUR Currency (not in allowed list)
# Delta Logistics, PO-2024-004
# Amount in EUR instead of INR
# ============================================================
create_invoice_pdf("invoice_28_eur_currency.pdf", {
    "vendor_name": "Delta Logistics",
    "vendor_email": "invoices@deltalogistics.com",
    "vendor_phone": "+49 30 1234 5678",
    "vendor_address": "42 Logistik Strasse, Berlin, Germany 10115",
    "invoice_number": "INV-2024-1028",
    "invoice_date": "2024-05-25",
    "due_date": "2024-06-25",
    "po_number": "PO-2024-004",
    "line_items": [
        {"description": "International Freight - Berlin to Mumbai", "qty": 1, "unit_price": 635.59, "amount": 635.59},
        {"description": "Customs Documentation Fee", "qty": 1, "unit_price": 114.41, "amount": 114.41},
    ],
    "tax_amount": 0,
    "tax_label": "VAT (0% - Export)",
    "total_amount": 750.00,
    "notes": "Amount in EUR. VAT zero-rated for export services.",
})

# ============================================================
# INVOICE 29: USD Currency (in allowed list)
# Beta Technologies, PO-2024-002
# Amount in USD
# ============================================================
create_invoice_pdf("invoice_29_usd_currency.pdf", {
    "vendor_name": "Beta Technologies",
    "vendor_email": "accounts@betatech.com",
    "vendor_phone": "+1 415 555 0123",
    "vendor_address": "100 Tech Boulevard, San Francisco, CA 94105, USA",
    "invoice_number": "INV-2024-1029",
    "invoice_date": "2024-05-28",
    "due_date": "2024-06-28",
    "po_number": "PO-2024-002",
    "line_items": [
        {"description": "Cloud SaaS License (Annual - USD)", "qty": 1, "unit_price": 1271.19, "amount": 1271.19},
        {"description": "Premium Support (USD)", "qty": 1, "unit_price": 228.81, "amount": 228.81},
    ],
    "tax_amount": 0,
    "tax_label": "Sales Tax (0%)",
    "total_amount": 1500.00,
    "notes": "Billed in USD. No Indian GST applicable for overseas services.",
})

print("\nAdditional invoices 26-29 created for tax/currency testing.")
