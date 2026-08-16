#!/usr/bin/env python3
"""Generate mock billing data for the Huazhong Machinery Group demo (Contract HZL-2026-003).

Outputs to staged_files/:
  HZL-2026-003-RateCard.csv      — 8-item CNY rate card (WH-001 … WH-008)
  HZL-INV-202610-001.pdf         — October Invoice 01  PASS  CNY 84,200.00
  HZL-INV-202610-002.pdf         — October Invoice 02  PASS  CNY 56,800.00
  HZL-INV-202610-003.pdf         — October Invoice 03  FAIL  WH-003 overcharged

Rate card derivation from reference (CEVA HKG-TPE, 9 items):
  - THC_DEST removed   → replaced by WH-003 (Warehouse Management Fee)
  - CUSTOMS_DEST removed (domestic logistics, no destination clearance)
  - All service codes unified to WH-00X format
  - Units adapted from KG/Shipment to Ton/Ton·Day/Trip for heavy industry
  - Currency converted from USD to CNY
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

# (serviceCode, serviceDesc, unit, unitPrice)
# WH-003 = Warehouse Management Fee is fixed by contract reference in the script
RC_ITEMS = [
    ("WH-001", "Basic Freight",                    "Ton",      200.00),
    ("WH-002", "Fuel Surcharge",                   "Ton",       25.00),
    ("WH-003", "Warehouse Management Fee",         "Ton·Day",   18.50),
    ("WH-004", "Origin Handling Fee",              "Shipment", 1200.00),
    ("WH-005", "Pickup & Collection",              "Trip",      800.00),
    ("WH-006", "Oversized Cargo Permit Fee",        "Shipment",  350.00),
    ("WH-007", "Documentation Fee",                "Shipment",  250.00),
    ("WH-008", "On-Carriage at Destination",       "Trip",      900.00),
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
    print(f"  + {path.name}  ({len(RC_ITEMS)} service codes)")


# ── Invoice data ──────────────────────────────────────────────────────────────
#
# Charge row: (serviceCode, description, qty, unit, unit_price, amount)
#
# Verification:
#   Invoice 01: 40000+5000+14800+6000+6400+2800+2000+7200 = 84,200  PASS
#   Invoice 02: 30000+3750+7400+3600+4800+350+1500+5400   = 56,800  PASS
#   Invoice 03: WH-003 billed @ 19.40 vs contract 18.50  => FAIL
#               634 Ton·Day × 19.40 = 12,299.60 ≈ 12,300 (vendor rounded up)

INVOICES = [
    dict(
        inv_no="HZL-INV-202610-001",
        date="05-Oct-26", due="04-Dec-26",
        cargo="Steel Structural Components",
        origin="Shanghai Pudong Logistics Hub",
        dest="Suzhou Industrial Park, Jiangsu",
        weight="200 Ton",
        charges=[
            ("WH-001", "Basic Freight",                  200, "Ton",      200.00,  40_000.00),
            ("WH-002", "Fuel Surcharge",                 200, "Ton",       25.00,   5_000.00),
            ("WH-003", "Warehouse Management Fee",       800, "Ton·Day",   18.50,  14_800.00),
            ("WH-004", "Origin Handling Fee",              5, "Shipment", 1_200.00,  6_000.00),
            ("WH-005", "Pickup & Collection",              8, "Trip",      800.00,   6_400.00),
            ("WH-006", "Oversized Cargo Permit Fee",        8, "Shipment",  350.00,   2_800.00),
            ("WH-007", "Documentation Fee",                8, "Shipment",  250.00,   2_000.00),
            ("WH-008", "On-Carriage at Destination",       8, "Trip",      900.00,   7_200.00),
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
            ("WH-001", "Basic Freight",                  150, "Ton",      200.00,  30_000.00),
            ("WH-002", "Fuel Surcharge",                 150, "Ton",       25.00,   3_750.00),
            ("WH-003", "Warehouse Management Fee",       400, "Ton·Day",   18.50,   7_400.00),
            ("WH-004", "Origin Handling Fee",              3, "Shipment", 1_200.00,  3_600.00),
            ("WH-005", "Pickup & Collection",              6, "Trip",      800.00,   4_800.00),
            ("WH-006", "Oversized Cargo Permit Fee",        1, "Shipment",  350.00,     350.00),
            ("WH-007", "Documentation Fee",                6, "Shipment",  250.00,   1_500.00),
            ("WH-008", "On-Carriage at Destination",       6, "Trip",      900.00,   5_400.00),
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
            ("WH-001", "Basic Freight",                  180, "Ton",      200.00,  36_000.00),
            ("WH-002", "Fuel Surcharge",                 180, "Ton",       25.00,   4_500.00),
            # WH-003: vendor billed 19.40 instead of contract rate 18.50
            # 634 Ton·Day × 19.40 = 12,299.60; vendor rounded up to 12,300.00
            ("WH-003", "Warehouse Management Fee",       634, "Ton·Day",   19.40,  12_300.00),
            ("WH-004", "Origin Handling Fee",              5, "Shipment", 1_200.00,  6_000.00),
            ("WH-005", "Pickup & Collection",              8, "Trip",      800.00,   6_400.00),
            ("WH-006", "Oversized Cargo Permit Fee",        3, "Shipment",  350.00,   1_050.00),
            ("WH-007", "Documentation Fee",                5, "Shipment",  250.00,   1_250.00),
            ("WH-008", "On-Carriage at Destination",       8, "Trip",      900.00,   7_200.00),
        ],
        total=74_700.00,
    ),
]

# ── PDF builder ───────────────────────────────────────────────────────────────

L_MARGIN, R_MARGIN, T_MARGIN = 18, 18, 15
PAGE_W   = 210
USABLE_W = PAGE_W - L_MARGIN - R_MARGIN  # 174 mm

# Column widths: CODE | DESCRIPTION | QTY | UNIT | UNIT PRICE | AMOUNT  = 174
CW = [24, 54, 12, 20, 28, 36]


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
    pdf.cell(0, 5, title,
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.3)
    pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    pdf.ln(1.5)


def _kv(pdf: InvoicePDF, label: str, value: str, lw: float = 40):
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(lw, 5.5, label, new_x="RIGHT", new_y="TOP")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5.5, value, new_x="LMARGIN", new_y="NEXT")


def _cell(pdf, w, h, txt, border="", align="L", fill=False):
    """Wrapper using new fpdf2 API."""
    from fpdf.enums import XPos, YPos
    pdf.cell(w, h, txt, border=border, align=align, fill=fill,
             new_x=XPos.RIGHT, new_y=YPos.TOP)


def _cell_nl(pdf, w, h, txt, border="", align="L", fill=False):
    """Cell that moves to next line (last cell in a row)."""
    from fpdf.enums import XPos, YPos
    pdf.cell(w, h, txt, border=border, align=align, fill=fill,
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def make_invoice(inv: dict):
    pdf = InvoicePDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(L_MARGIN, T_MARGIN, R_MARGIN)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()

    # ── Title ─────────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(0, 10, "ORIGINAL INVOICE",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_line_width(0.6)
    pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(3)

    # ── Header meta ───────────────────────────────────────────────────────────
    _kv(pdf, "Invoice No.",  inv["inv_no"])
    _kv(pdf, "Date",         inv["date"])
    _kv(pdf, "Due On",       inv["due"])
    _kv(pdf, "Terms",        "60 days from Invoice Date")
    _kv(pdf, "Contract No.", CONTRACT_NO)
    pdf.ln(4)

    # ── Vendor / Consignee ────────────────────────────────────────────────────
    half = USABLE_W / 2
    pdf.set_font("Helvetica", "B", 9)
    _cell(pdf, half, 5.5, "VENDOR")
    _cell_nl(pdf, half, 5.5, "CONSIGNEE")
    pdf.set_font("Helvetica", "", 9)
    for vl, cl in [(VENDOR_NAME, CONSIGNEE_NAME), (VENDOR_TAX, CONSIGNEE_ADDR)]:
        _cell(pdf, half, 5.5, vl)
        _cell_nl(pdf, half, 5.5, cl)
    pdf.ln(5)

    # ── Service Details ───────────────────────────────────────────────────────
    _section_title(pdf, "SERVICE DETAILS")
    _kv(pdf, "Service Period", "October 2026")
    _kv(pdf, "Contract No.",   CONTRACT_NO)
    _kv(pdf, "Service Region", "East China")
    _kv(pdf, "Cargo",          inv["cargo"])
    _kv(pdf, "Origin",         inv["origin"])
    _kv(pdf, "Destination",    inv["dest"])
    _kv(pdf, "Total Weight",   inv["weight"])
    pdf.ln(5)

    # ── Charges table ─────────────────────────────────────────────────────────
    _section_title(pdf, "CHARGES")

    # Header row
    pdf.set_fill_color(235, 235, 235)
    pdf.set_font("Helvetica", "B", 8)
    headers = ["SERVICE CODE", "DESCRIPTION", "QTY", "UNIT", "UNIT PRICE", "AMOUNT (CNY)"]
    aligns  = ["C", "L", "R", "R", "R", "R"]
    for i, (txt, w, a) in enumerate(zip(headers, CW, aligns)):
        if i < len(CW) - 1:
            _cell(pdf, w, 7, txt, border=1, align=a, fill=True)
        else:
            _cell_nl(pdf, w, 7, txt, border=1, align=a, fill=True)

    # Data rows
    pdf.set_font("Helvetica", "", 8.5)
    for row in inv["charges"]:
        code, desc, qty, unit, price, amount = row
        _cell(pdf,    CW[0], 6, code,              border="LR", align="C")
        _cell(pdf,    CW[1], 6, f"  {desc}",       border="LR", align="L")
        _cell(pdf,    CW[2], 6, f"{qty:,}",        border="LR", align="R")
        _cell(pdf,    CW[3], 6, unit,              border="LR", align="R")
        _cell(pdf,    CW[4], 6, f"{price:,.2f}",   border="LR", align="R")
        _cell_nl(pdf, CW[5], 6, f"{amount:,.2f}",  border="LR", align="R")

    # Bottom rule
    pdf.set_line_width(0.4)
    pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(1)

    # Total row
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(220, 230, 245)
    label_w = sum(CW[:-1])
    _cell(pdf,    label_w, 7.5, "TOTAL",
          border=1, align="R", fill=True)
    _cell_nl(pdf, CW[-1],  7.5, f"CNY {inv['total']:,.2f}",
             border=1, align="R", fill=True)
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
