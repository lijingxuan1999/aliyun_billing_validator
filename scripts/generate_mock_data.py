#!/usr/bin/env python3
"""Generate mock billing data for the Huazhong Machinery Group demo (Contract HZL-2026-003).

Outputs to staged_files/:
  HZL-2026-003-RateCard.csv      — 7-item CNY rate card (WH-001..WH-008, WH-003 removed)
  HDLS-INV-202610-001.pdf        — October Invoice 01  PASS  CNY 69,400.00
  HDLS-INV-202610-002.pdf        — October Invoice 02  PASS  CNY 49,400.00
  HDLS-INV-202610-003.pdf        — October Invoice 03  FAIL  WH-002 Fuel Surcharge overcharged

Demo script:
  - Contract: HZL-2026-003 (Huazhong Machinery Group ↔ Huadong Logistics)
  - Invoice 03 failure: WH-002 billed @ 28.50/Ton vs contract rate 25.00/Ton
    → 180 Ton × (28.50 - 25.00) = CNY 630.00 overcharge
  - Rejection approval flow: PR-20261028-007

PDF schema compliance (SAP Document Intelligence):
  Header fields : INVOICE, SHIPPER, CONSIGNEE, ORIGIN, DESTINATION,
                  DESCRIPTION, PACKAGES, WEIGHT, VOLUME, CHARGEABLE
  Line item cols: DESCRIPTION, CUR, AMOUNT
  Qty/unit info is embedded inside DESCRIPTION (e.g. "Basic Freight - 200 Ton @ 200.00/Ton")
  No extra labeled fields outside the schema.
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

STAGED = Path(__file__).parent.parent / "agent" / "staged_files"
STAGED.mkdir(exist_ok=True)

# ── Parties ───────────────────────────────────────────────────────────────────

VENDOR_NAME    = "HUADONG LOGISTICS CO., LTD."
VENDOR_TAX     = "Tax ID: 9131000078787878XA"
CONSIGNEE_NAME = "HUAZHONG MACHINERY GROUP CO., LTD."
CONSIGNEE_ADDR = "No. 688 Industry Ave, Pudong, Shanghai 200120"
CONTRACT_NO    = "HZL-2026-003"

# ── Rate Card (7 items — WH-003 removed) ──────────────────────────────────────

RC_NAME  = f"Huadong Logistics - East China Heavy Industry ({CONTRACT_NO})"

RC_ITEMS = [
    ("WH-001", "Basic Freight",                 "Ton",       100.00),
    ("WH-002", "Fuel Surcharge",                "Ton",        25.00),
    # WH-003 (Warehouse Management Fee, Ton·Day) removed — unit too complex for OCR demo
    ("WH-004", "Origin Handling Fee",           "Ton",        50.00),
    ("WH-005", "Pickup & Collection",           "Shipment",  800.00),
    ("WH-006", "Oversized Cargo Permit Fee",    "Shipment",  400.00),
    ("WH-007", "Documentation Fee",             "Shipment",  400.00),
    ("WH-008", "On-Carriage at Destination",    "Ton",        25.00),
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
# Line item tuple: (description, cur, amount)
#
# Per-ton items (WH-001/002/004/008): description = "Service - Qty Ton @ Rate/Ton"
# Flat items (WH-005/006/007):        description = service name only
#
# Per-ton combined rate: 100+25+50+25 = 200/Ton
# Flat fees total: 800+400+400 = 1,600 per invoice
#
# Invoice 01: 413 Ton  →  413×200 + 1,600 = CNY 84,200  (Basic Freight = 49%)
# Invoice 02: 276 Ton  →  276×200 + 1,600 = CNY 56,800
# Invoice 03: 180 Ton, WH-002 billed @ 28.50/Ton (contract 25.00/Ton)
#             180×28.50=5,130 vs correct 4,500 → overcharge CNY 630
#             total: 180×203.50 + 1,600 = CNY 38,230

INVOICES = [
    dict(
        inv_no="HDLS-INV-202610-001",
        date="05-Oct-26", due="04-Dec-26",
        cargo="Steel Structural Components",
        origin="Shanghai Pudong Logistics Hub",
        dest="Suzhou Industrial Park, Jiangsu",
        packages="21 PLT", weight="413.00 TON", volume="600.0 M3", chargeable="413.00 TON",
        charges=[
            ("Basic Freight - 413 Ton @ 100.00/Ton",             "CNY", 41_300.00),
            ("Fuel Surcharge - 413 Ton @ 25.00/Ton",             "CNY", 10_325.00),
            ("Origin Handling Fee - 413 Ton @ 50.00/Ton",        "CNY", 20_650.00),
            ("Pickup & Collection",                               "CNY",    800.00),
            ("Oversized Cargo Permit Fee",                        "CNY",    400.00),
            ("Documentation Fee",                                 "CNY",    400.00),
            ("On-Carriage at Destination - 413 Ton @ 25.00/Ton", "CNY", 10_325.00),
        ],
        total=84_200.00,
    ),
    dict(
        inv_no="HDLS-INV-202610-002",
        date="12-Oct-26", due="11-Dec-26",
        cargo="Hydraulic Press Equipment",
        origin="Nanjing Manufacturing Centre, Jiangsu",
        dest="Wuxi Industrial Base, Jiangsu",
        packages="14 PLT", weight="276.00 TON", volume="400.0 M3", chargeable="276.00 TON",
        charges=[
            ("Basic Freight - 276 Ton @ 100.00/Ton",             "CNY", 27_600.00),
            ("Fuel Surcharge - 276 Ton @ 25.00/Ton",             "CNY",  6_900.00),
            ("Origin Handling Fee - 276 Ton @ 50.00/Ton",        "CNY", 13_800.00),
            ("Pickup & Collection",                               "CNY",    800.00),
            ("Oversized Cargo Permit Fee",                        "CNY",    400.00),
            ("Documentation Fee",                                 "CNY",    400.00),
            ("On-Carriage at Destination - 276 Ton @ 25.00/Ton", "CNY",  6_900.00),
        ],
        total=56_800.00,
    ),
    dict(
        inv_no="HDLS-INV-202610-003",
        date="20-Oct-26", due="19-Dec-26",
        cargo="CNC Machine Components",
        origin="Shanghai Minhang Warehouse",
        dest="Changzhou Factory Zone, Jiangsu",
        packages="9 PLT", weight="180.00 TON", volume="260.0 M3", chargeable="180.00 TON",
        charges=[
            ("Basic Freight - 180 Ton @ 100.00/Ton",             "CNY", 18_000.00),
            # WH-002: vendor billed 28.50/Ton instead of contract rate 25.00/Ton
            # 180 × 28.50 = 5,130  (correct: 4,500, overcharge: CNY 630)
            ("Fuel Surcharge - 180 Ton @ 28.50/Ton",             "CNY",  5_130.00),
            ("Origin Handling Fee - 180 Ton @ 50.00/Ton",        "CNY",  9_000.00),
            ("Pickup & Collection",                               "CNY",    800.00),
            ("Oversized Cargo Permit Fee",                        "CNY",    400.00),
            ("Documentation Fee",                                 "CNY",    400.00),
            ("On-Carriage at Destination - 180 Ton @ 25.00/Ton", "CNY",  4_500.00),
        ],
        total=38_230.00,
    ),
]

# ── PDF layout constants ───────────────────────────────────────────────────────

L_MARGIN, R_MARGIN, T_MARGIN = 18, 18, 15
PAGE_W   = 210
USABLE_W = PAGE_W - L_MARGIN - R_MARGIN  # 174 mm

# Line-item columns: DESCRIPTION | CUR | AMOUNT
CW = [112, 18, 44]


class InvoicePDF(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5,
                  f"Mock document generated for demo purposes only.  Contract {CONTRACT_NO}.",
                  align="C")
        self.set_text_color(0, 0, 0)


def _rule(pdf, lw=0.3):
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(lw)
    pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)


def _cell(pdf, w, h, txt, border="", align="L", fill=False):
    from fpdf.enums import XPos, YPos
    pdf.cell(w, h, txt, border=border, align=align, fill=fill,
             new_x=XPos.RIGHT, new_y=YPos.TOP)


def _cell_nl(pdf, w, h, txt, border="", align="L", fill=False):
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
    pdf.cell(0, 10, "ORIGINAL INVOICE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_line_width(0.6)
    pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(3)

    # ── INVOICE field ─────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(35, 5.5, "INVOICE", new_x="RIGHT", new_y="TOP")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5.5, inv["inv_no"], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(35, 5, "Date", new_x="RIGHT", new_y="TOP")
    pdf.cell(0, 5, inv["date"], new_x="LMARGIN", new_y="NEXT")
    pdf.cell(35, 5, "Due", new_x="RIGHT", new_y="TOP")
    pdf.cell(0, 5, inv["due"], new_x="LMARGIN", new_y="NEXT")
    pdf.cell(35, 5, "Contract", new_x="RIGHT", new_y="TOP")
    pdf.cell(0, 5, CONTRACT_NO, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # ── SHIPPER | CONSIGNEE ───────────────────────────────────────────────────
    half = USABLE_W / 2
    pdf.set_font("Helvetica", "B", 8)
    _rule(pdf)
    pdf.ln(1.5)
    _cell(pdf, half, 5, "SHIPPER")
    _cell_nl(pdf, half, 5, "CONSIGNEE")
    pdf.set_font("Helvetica", "B", 9)
    _cell(pdf, half, 5.5, VENDOR_NAME)
    _cell_nl(pdf, half, 5.5, CONSIGNEE_NAME)
    pdf.set_font("Helvetica", "", 8.5)
    _cell(pdf, half, 5, VENDOR_TAX)
    _cell_nl(pdf, half, 5, CONSIGNEE_ADDR)
    pdf.ln(3)

    # ── ORIGIN | DESTINATION ──────────────────────────────────────────────────
    _rule(pdf)
    pdf.ln(1.5)
    pdf.set_font("Helvetica", "B", 8)
    _cell(pdf, half, 5, "ORIGIN")
    _cell_nl(pdf, half, 5, "DESTINATION")
    pdf.set_font("Helvetica", "", 9)
    _cell(pdf, half, 5.5, inv["origin"])
    _cell_nl(pdf, half, 5.5, inv["dest"])
    pdf.ln(3)

    # ── DESCRIPTION / PACKAGES / WEIGHT / VOLUME / CHARGEABLE ────────────────
    _rule(pdf)
    pdf.ln(1.5)
    desc_w  = USABLE_W - 4 * 28  # 62 mm for description
    col_w   = 28
    pdf.set_font("Helvetica", "B", 8)
    _cell(pdf, desc_w, 5, "DESCRIPTION")
    _cell(pdf, col_w,  5, "PACKAGES",   align="C")
    _cell(pdf, col_w,  5, "WEIGHT",     align="C")
    _cell(pdf, col_w,  5, "VOLUME",     align="C")
    _cell_nl(pdf, col_w, 5, "CHARGEABLE", align="C")
    pdf.set_font("Helvetica", "", 9)
    _cell(pdf, desc_w, 6, inv["cargo"])
    _cell(pdf, col_w,  6, inv["packages"],   align="C")
    _cell(pdf, col_w,  6, inv["weight"],     align="C")
    _cell(pdf, col_w,  6, inv["volume"],     align="C")
    _cell_nl(pdf, col_w, 6, inv["chargeable"], align="C")
    pdf.ln(5)

    # ── Charges table ─────────────────────────────────────────────────────────
    _rule(pdf, lw=0.6)
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "CHARGES", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    # Header row
    pdf.set_fill_color(235, 235, 235)
    pdf.set_font("Helvetica", "B", 8)
    headers = ["DESCRIPTION", "CUR", "AMOUNT"]
    aligns  = ["L", "C", "R"]
    for i, (txt, w, a) in enumerate(zip(headers, CW, aligns)):
        fn = _cell_nl if i == len(CW) - 1 else _cell
        fn(pdf, w, 7, f"  {txt}" if a == "L" else txt,
           border=1, align=a, fill=True)

    # Data rows
    pdf.set_font("Helvetica", "", 8.5)
    for desc, cur, amount in inv["charges"]:
        _cell(pdf,    CW[0], 6, f"  {desc}",          border="LR", align="L")
        _cell(pdf,    CW[1], 6, cur,                   border="LR", align="C")
        _cell_nl(pdf, CW[2], 6, f"{amount:,.2f}",      border="LR", align="R")

    # Bottom rule + total
    pdf.set_line_width(0.4)
    pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(1)

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(220, 230, 245)
    label_w = CW[0] + CW[1]
    _cell(pdf,    label_w, 7.5, "TOTAL",
          border=1, align="R", fill=True)
    _cell_nl(pdf, CW[2],   7.5, f"CNY {inv['total']:,.2f}",
             border=1, align="R", fill=True)

    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(
        0, 5,
        f"Please remit payment to Huadong Logistics Co., Ltd.  "
        f"Bank: Bank of China Shanghai Branch  |  "
        f"Account: 4223 8801 0200 6789  |  Reference: {inv['inv_no']}",
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
    print("\nInvoice 03 discrepancy:")
    print("  WH-002 Fuel Surcharge billed @ 28.50/Ton (contract: 25.00/Ton)")
    print("  180 Ton × (28.50 - 25.00) = CNY 630.00 overcharge")
