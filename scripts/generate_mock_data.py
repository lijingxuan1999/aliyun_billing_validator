#!/usr/bin/env python3
"""Generate mock billing data for the Huazhong Machinery Group demo (Contract HZL-2026-003).

Outputs to staged_files/:
  HZL-2026-003-RateCard.csv      — standard rate card (8 service codes)
  HZL-INV-202610-001.pdf         — October Invoice 01  PASS  CNY 84,200.00
  HZL-INV-202610-002.pdf         — October Invoice 02  PASS  CNY 56,800.00
  HZL-INV-202610-003.pdf         — October Invoice 03  FAIL  WH-003 overcharged
"""

import csv
import subprocess
import sys
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fpdf2"])
    from fpdf import FPDF

STAGED = Path(__file__).parent.parent / "staged_files"
STAGED.mkdir(exist_ok=True)

# ── Parties ───────────────────────────────────────────────────────────────────

VENDOR_NAME    = "HUADONG LOGISTICS CO., LTD."
VENDOR_TAX     = "Tax ID: 9131000078787878XA"
CONSIGNEE_NAME = "HUAZHONG MACHINERY GROUP CO., LTD."
CONSIGNEE_ADDR = "No. 688 Industry Ave, Pudong, Shanghai 200120"
CONTRACT_NO    = "HZL-2026-003"

# ── Rate Card ─────────────────────────────────────────────────────────────────

RC_NAME  = f"Huadong Logistics - East China Heavy Industry ({CONTRACT_NO})"
RC_ITEMS = [
    # (serviceCode, serviceDesc, unit, unitPrice)
    ("BASIC_FREIGHT",  "Basic Freight",             "Ton",      200.00),
    ("FUEL_SURCHARGE", "Fuel Surcharge",             "Ton",       25.00),
    ("WH-003",         "Warehouse Management Fee",  "Ton·Day",   18.50),
    ("LOCAL_DEL",      "Local Delivery",             "Trip",    1200.00),
    ("LOADING",        "Loading & Unloading",        "Ton",       40.00),
    ("HANDLING",       "Handling Fee",               "Shipment",  800.00),
    ("INSURANCE",      "Cargo Insurance",            "Ton",        5.00),
    ("DOC_FEE",        "Documentation Fee",          "Shipment",  250.00),
]


def write_rate_card():
    path = STAGED / "HZL-2026-003-RateCard.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "rateCardName", "validFrom", "validTo", "status", "currency",
            "serviceCode", "serviceDesc", "unit", "unitPrice", "minQty", "notes",
        ])
        for code, desc, unit, price in RC_ITEMS:
            w.writerow([
                RC_NAME, "2026-01-01", "2026-12-31", "active", "CNY",
                code, desc, unit, price, 1, f"Contract {CONTRACT_NO}",
            ])
    print(f"  + {path.name}")


# ── Invoice data ──────────────────────────────────────────────────────────────
#
# Charge row: (description, qty, unit, unit_price, amount)
# Verification:
#   Invoice 01: 40000+5000+12950+12000+8000+4000+1000+1250 = 84,200  PASS
#   Invoice 02: 30000+3750+3700+8400+6000+3200+750+1000   = 56,800  PASS
#   Invoice 03: 36000+4500+12300+9600+7200+4000+900+1250  = 75,750
#               WH-003 billed @ 19.40 vs contract 18.50  => overcharged

INVOICES = [
    dict(
        inv_no="HZL-INV-202610-001",
        date="05-Oct-26", due="04-Dec-26",
        cargo="Steel Structural Components",
        origin="Shanghai Pudong Logistics Hub",
        dest="Suzhou Industrial Park, Jiangsu",
        weight="200 Ton",
        charges=[
            ("BASIC FREIGHT CHARGE",       200, "Ton",      200.00,  40_000.00),
            ("FUEL SURCHARGE",             200, "Ton",       25.00,   5_000.00),
            ("WAREHOUSE MANAGEMENT FEE",   700, "Ton·Day",   18.50,  12_950.00),
            ("LOCAL DELIVERY",              10, "Trip",    1_200.00,  12_000.00),
            ("LOADING & UNLOADING",        200, "Ton",       40.00,   8_000.00),
            ("HANDLING FEE",                 5, "Shipment",  800.00,   4_000.00),
            ("CARGO INSURANCE",            200, "Ton",        5.00,   1_000.00),
            ("DOCUMENTATION FEE",            5, "Shipment",  250.00,   1_250.00),
        ],
        total=84_200.00,
    ),
    dict(
        inv_no="HZL-INV-202610-002",
        date="12-Oct-26", due="11-Dec-26",
        cargo="Hydraulic Press Equipment",
        origin="Nanjing Manufacturing Centre, Jiangsu",
        dest="Wuxi Industrial Base, Jiangsu",
        weight="150 Ton",
        charges=[
            ("BASIC FREIGHT CHARGE",       150, "Ton",      200.00,  30_000.00),
            ("FUEL SURCHARGE",             150, "Ton",       25.00,   3_750.00),
            ("WAREHOUSE MANAGEMENT FEE",   200, "Ton·Day",   18.50,   3_700.00),
            ("LOCAL DELIVERY",               7, "Trip",    1_200.00,   8_400.00),
            ("LOADING & UNLOADING",        150, "Ton",       40.00,   6_000.00),
            ("HANDLING FEE",                 4, "Shipment",  800.00,   3_200.00),
            ("CARGO INSURANCE",            150, "Ton",        5.00,     750.00),
            ("DOCUMENTATION FEE",            4, "Shipment",  250.00,   1_000.00),
        ],
        total=56_800.00,
    ),
    dict(
        inv_no="HZL-INV-202610-003",
        date="20-Oct-26", due="19-Dec-26",
        cargo="CNC Machine Components",
        origin="Shanghai Minhang Warehouse",
        dest="Changzhou Factory Zone, Jiangsu",
        weight="180 Ton",
        charges=[
            ("BASIC FREIGHT CHARGE",       180, "Ton",      200.00,  36_000.00),
            ("FUEL SURCHARGE",             180, "Ton",       25.00,   4_500.00),
            # WH-003: billed at 19.40 instead of contract rate 18.50
            # 634 Ton·Day × 19.40 = 12,299.60 → rounded to 12,300.00 by vendor
            ("WAREHOUSE MANAGEMENT FEE",   634, "Ton·Day",   19.40,  12_300.00),
            ("LOCAL DELIVERY",               8, "Trip",    1_200.00,   9_600.00),
            ("LOADING & UNLOADING",        180, "Ton",       40.00,   7_200.00),
            ("HANDLING FEE",                 5, "Shipment",  800.00,   4_000.00),
            ("CARGO INSURANCE",            180, "Ton",        5.00,     900.00),
            ("DOCUMENTATION FEE",            5, "Shipment",  250.00,   1_250.00),
        ],
        total=75_750.00,
    ),
]

# ── PDF builder ───────────────────────────────────────────────────────────────

L_MARGIN, R_MARGIN, T_MARGIN = 18, 18, 15
PAGE_W = 210
USABLE_W = PAGE_W - L_MARGIN - R_MARGIN  # 174 mm

# Column widths for charges table (sum = 174)
CW = [80, 18, 24, 26, 26]  # desc | qty | unit | unit price | amount


class InvoicePDF(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5,
                  f"Mock document generated for demo purposes only.  "
                  f"Contract {CONTRACT_NO}.",
                  align="C")
        self.set_text_color(0, 0, 0)


def _section_title(pdf: InvoicePDF, title: str):
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, title, ln=True)
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.3)
    pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    pdf.ln(1.5)


def _kv(pdf: InvoicePDF, label: str, value: str, lw: float = 38):
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(lw, 5.5, label, ln=False)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5.5, value, ln=True)


def make_invoice(inv: dict):
    pdf = InvoicePDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(L_MARGIN, T_MARGIN, R_MARGIN)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()

    # ── Title ─────────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(0, 10, "ORIGINAL INVOICE", ln=True)
    pdf.set_line_width(0.6)
    pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(3)

    # ── Header meta ───────────────────────────────────────────────────────────
    _kv(pdf, "Invoice No.", inv["inv_no"])
    _kv(pdf, "Date",        inv["date"])
    _kv(pdf, "Due On",      inv["due"])
    _kv(pdf, "Terms",       "60 days from Invoice Date")
    _kv(pdf, "Contract No.", CONTRACT_NO)
    pdf.ln(4)

    # ── Vendor / Consignee ────────────────────────────────────────────────────
    half = USABLE_W / 2
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(half, 5.5, "VENDOR", ln=False)
    pdf.cell(half, 5.5, "CONSIGNEE", ln=True)
    pdf.set_font("Helvetica", "", 9)
    for vl, cl in [(VENDOR_NAME, CONSIGNEE_NAME), (VENDOR_TAX, CONSIGNEE_ADDR)]:
        pdf.cell(half, 5.5, vl, ln=False)
        pdf.cell(half, 5.5, cl, ln=True)
    pdf.ln(5)

    # ── Service Details ───────────────────────────────────────────────────────
    _section_title(pdf, "SERVICE DETAILS")
    _kv(pdf, "Service Period", "October 2026",            lw=40)
    _kv(pdf, "Contract No.",   CONTRACT_NO,               lw=40)
    _kv(pdf, "Service Region", "East China",              lw=40)
    _kv(pdf, "Cargo",          inv["cargo"],              lw=40)
    _kv(pdf, "Origin",         inv["origin"],             lw=40)
    _kv(pdf, "Destination",    inv["dest"],               lw=40)
    _kv(pdf, "Total Weight",   inv["weight"],             lw=40)
    pdf.ln(5)

    # ── Charges table ─────────────────────────────────────────────────────────
    _section_title(pdf, "CHARGES")

    # Header row
    pdf.set_fill_color(235, 235, 235)
    pdf.set_font("Helvetica", "B", 8)
    headers = ["DESCRIPTION", "QTY", "UNIT", "UNIT PRICE", "AMOUNT (CNY)"]
    aligns  = ["L", "R", "R", "R", "R"]
    for txt, w, a in zip(headers, CW, aligns):
        pdf.cell(w, 7, f" {txt}" if a == "L" else txt,
                 border=1, align=a, fill=True)
    pdf.ln()

    # Data rows
    pdf.set_font("Helvetica", "", 8.5)
    for desc, qty, unit, price, amount in inv["charges"]:
        pdf.cell(CW[0], 6, f"  {desc}",          border="LR", align="L")
        pdf.cell(CW[1], 6, f"{qty:,}",            border="LR", align="R")
        pdf.cell(CW[2], 6, unit,                  border="LR", align="R")
        pdf.cell(CW[3], 6, f"{price:,.2f}",       border="LR", align="R")
        pdf.cell(CW[4], 6, f"{amount:,.2f}",      border="LR", align="R")
        pdf.ln()

    # Close bottom border
    pdf.set_line_width(0.4)
    pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(1)

    # Total row
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(220, 230, 245)
    label_w = sum(CW[:4])
    pdf.cell(label_w, 7.5, "TOTAL", border=1, align="R", fill=True)
    pdf.cell(CW[4],   7.5, f"CNY {inv['total']:,.2f}", border=1, align="R", fill=True)
    pdf.ln(10)

    # ── Payment note ──────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(
        0, 5,
        f"Please remit payment to Huadong Logistics Co., Ltd.  "
        f"Bank: Bank of China Shanghai Branch  |  "
        f"Account: 4223 8801 0200 6789  |  "
        f"Reference: {inv['inv_no']}",
        align="L",
    )
    pdf.set_text_color(0, 0, 0)

    out = STAGED / f"{inv['inv_no']}.pdf"
    pdf.output(str(out))
    print(f"  + {out.name}  (total CNY {inv['total']:,.2f})")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Generating mock data for HZL-2026-003 demo...")
    write_rate_card()
    for inv in INVOICES:
        make_invoice(inv)
    print("\nDone. Files written to staged_files/")
