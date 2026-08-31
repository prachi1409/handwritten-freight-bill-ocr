"""Generator script to create 10 realistic handwritten freight bill PDFs and matching ground truth JSON files."""

import json
import logging
from pathlib import Path
import pymupdf as fitz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKEND_DIR = Path(r"c:\Users\Prachi\OneDrive\Desktop\bill-ocr\backend")
DATASET_DIR = BACKEND_DIR / "test_dataset"
DATASET_DIR.mkdir(parents=True, exist_ok=True)

# 10 realistic handwritten freight bill definitions
DATASET_SPECS = [
    {
        "filename": "handwritten_test_01_easy.pdf",
        "gt_filename": "handwritten_test_01_easy_ground_truth.json",
        "difficulty": "Easy",
        "font": "Segoe Script",
        "data": {
            "bill_number": "FB-10021",
            "invoice_number": "INV-10021-A",
            "bill_date": "2026-08-25",
            "carrier": "Apex Freight Carriers",
            "consignor": "Alpha Steel Mills",
            "consignee": "Delta Industrial Supply",
            "origin": "Chicago, IL",
            "destination": "St. Louis, MO",
            "commodity_description": "Steel Rods & Bars",
            "quantity": "18 Pallets",
            "weight": "24,500 lbs",
            "freight_amount": "$1,250.00",
            "fuel_surcharge": "$125.00",
            "handling_charge": "$50.00",
            "total_amount": "$1,425.00",
            "vehicle_number": "IL-8841",
            "driver_name": "Robert Davis",
            "pickup_time": "08:30 AM",
            "delivery_time": "02:15 PM",
            "special_instructions": "Call receiving before delivery"
        }
    },
    {
        "filename": "handwritten_test_02_easy.pdf",
        "gt_filename": "handwritten_test_02_easy_ground_truth.json",
        "difficulty": "Easy",
        "font": "Lucida Handwriting",
        "data": {
            "bill_number": "FB-20042",
            "invoice_number": "INV-20042-B",
            "bill_date": "2026-08-26",
            "carrier": "Summit Line Haul",
            "consignor": "Beta Chemical Labs",
            "consignee": "Epsilon Storage Hub",
            "origin": "Dallas, TX",
            "destination": "Houston, TX",
            "commodity_description": "Lab Supplies",
            "quantity": "30 Crates",
            "weight": "12,800 lbs",
            "freight_amount": "$980.00",
            "fuel_surcharge": "$98.00",
            "handling_charge": "$45.00",
            "total_amount": "$1,123.00",
            "vehicle_number": "TX-1102",
            "driver_name": "James Wilson",
            "pickup_time": "09:00 AM",
            "delivery_time": "03:45 PM",
            "special_instructions": "Keep dry - handle with care"
        }
    },
    {
        "filename": "handwritten_test_03_easy.pdf",
        "gt_filename": "handwritten_test_03_easy_ground_truth.json",
        "difficulty": "Easy",
        "font": "Segoe Print",
        "data": {
            "bill_number": "FB-30063",
            "invoice_number": "INV-30063-C",
            "bill_date": "2026-08-27",
            "carrier": "Titan Global Freight",
            "consignor": "Gamma Component Inc",
            "consignee": "Zeta Retail Logistics",
            "origin": "Atlanta, GA",
            "destination": "Charlotte, NC",
            "commodity_description": "Aluminum Parts",
            "quantity": "25 Cartons",
            "weight": "19,400 lbs",
            "freight_amount": "$1,550.00",
            "fuel_surcharge": "$155.00",
            "handling_charge": "$60.00",
            "total_amount": "$1,765.00",
            "vehicle_number": "GA-5543",
            "driver_name": "Thomas Miller",
            "pickup_time": "07:45 AM",
            "delivery_time": "01:30 PM",
            "special_instructions": "Liftgate required at destination"
        }
    },
    {
        "filename": "handwritten_test_04_medium.pdf",
        "gt_filename": "handwritten_test_04_medium_ground_truth.json",
        "difficulty": "Medium",
        "font": "Ink Free",
        "data": {
            "bill_number": "HB-40084",
            "invoice_number": "INV-HB-40084",
            "bill_date": "2026-08-28",
            "carrier": "Midwest Transport LLC",
            "consignor": "Pinnacle Metals Corp",
            "consignee": "Vanguard Distribution",
            "origin": "Indianapolis, IN",
            "destination": "Columbus, OH",
            "commodity_description": "Industrial Tubing",
            "quantity": "15 Bundles",
            "weight": "32,450 lbs",
            "freight_amount": "$1,820.50",
            "fuel_surcharge": "$182.05",
            "handling_charge": "$75.00",
            "total_amount": "$2,077.55",
            "vehicle_number": "IN-9104",
            "driver_name": "David Reynolds",
            "pickup_time": "09:30 AM",
            "delivery_time": "04:15 PM",
            "special_instructions": "Do not double stack pallets"
        }
    },
    {
        "filename": "handwritten_test_05_medium.pdf",
        "gt_filename": "handwritten_test_05_medium_ground_truth.json",
        "difficulty": "Medium",
        "font": "Comic Sans MS",
        "data": {
            "bill_number": "HB-50105",
            "invoice_number": "INV-HB-50105",
            "bill_date": "2026-08-29",
            "carrier": "Express Haulers Inc",
            "consignor": "Starlight Pharma",
            "consignee": "Midwest Storage Labs",
            "origin": "Kansas City, MO",
            "destination": "Omaha, NE",
            "commodity_description": "Medical Supplies",
            "quantity": "42 Crates",
            "weight": "15,600 lbs",
            "freight_amount": "$2,140.00",
            "fuel_surcharge": "$214.00",
            "handling_charge": "$85.00",
            "total_amount": "$2,439.00",
            "vehicle_number": "MO-3321",
            "driver_name": "Marcus Vance",
            "pickup_time": "10:15 AM",
            "delivery_time": "05:00 PM",
            "special_instructions": "Temperature controlled 15C-25C"
        }
    },
    {
        "filename": "handwritten_test_06_medium.pdf",
        "gt_filename": "handwritten_test_06_medium_ground_truth.json",
        "difficulty": "Medium",
        "font": "Segoe Script",
        "data": {
            "bill_number": "HB-60126",
            "invoice_number": "INV-60126-M",
            "bill_date": "2026-08-30",
            "carrier": "Overland Express LLC",
            "consignor": "Westfield Auto Parts",
            "consignee": "Central Assembly Plant",
            "origin": "Detroit, MI",
            "destination": "Cleveland, OH",
            "commodity_description": "Engine Components",
            "quantity": "22 Pallets",
            "weight": "28,900 lbs",
            "freight_amount": "$1,675.00",
            "fuel_surcharge": "$167.50",
            "handling_charge": "$55.00",
            "total_amount": "$1,897.50",
            "vehicle_number": "MI-7721",
            "driver_name": "Michael Carter",
            "pickup_time": "08:00 AM",
            "delivery_time": "02:30 PM",
            "special_instructions": "Check seal before unloading"
        }
    },
    {
        "filename": "handwritten_test_07_hard.pdf",
        "gt_filename": "handwritten_test_07_hard_ground_truth.json",
        "difficulty": "Hard",
        "font": "Ink Free",
        "data": {
            "bill_number": "FB-71047",
            "invoice_number": "INV-71047-Z",
            "bill_date": "2026-08-31",
            "carrier": "Freightways National",
            "consignor": "B7 Chemical Plant",
            "consignee": "Z7 Logistics Hub",
            "origin": "Memphis, TN",
            "destination": "Nashville, TN",
            "commodity_description": "Hazardous Solvents",
            "quantity": "17 Drums",
            "weight": "17,850 lbs",
            "freight_amount": "$1,750.00",
            "fuel_surcharge": "$175.00",
            "handling_charge": "$120.00",
            "total_amount": "$2,045.00",
            "vehicle_number": "TN-7182",
            "driver_name": "Zachary Taylor",
            "pickup_time": "07:15 AM",
            "delivery_time": "01:45 PM",
            "special_instructions": "HAZMAT class 3 - placards required"
        }
    },
    {
        "filename": "handwritten_test_08_hard.pdf",
        "gt_filename": "handwritten_test_08_hard_ground_truth.json",
        "difficulty": "Hard",
        "font": "Comic Sans MS",
        "data": {
            "bill_number": "FB-80518",
            "invoice_number": "INV-80518-S",
            "bill_date": "2026-09-01",
            "carrier": "Southern Line Haul",
            "consignor": "B8 Metal Fabricators",
            "consignee": "S5 Supply Depot",
            "origin": "Birmingham, AL",
            "destination": "Atlanta, GA",
            "commodity_description": "Sheet Metal Coil",
            "quantity": "8 Coils",
            "weight": "45,800 lbs",
            "freight_amount": "$2,850.00",
            "fuel_surcharge": "$285.00",
            "handling_charge": "$95.00",
            "total_amount": "$3,230.00",
            "vehicle_number": "AL-8501",
            "driver_name": "Brian Scott",
            "pickup_time": "08:45 AM",
            "delivery_time": "03:15 PM",
            "special_instructions": "Tarp required - heavy load"
        }
    },
    {
        "filename": "handwritten_test_09_hard.pdf",
        "gt_filename": "handwritten_test_09_hard_ground_truth.json",
        "difficulty": "Hard",
        "font": "Ink Free",
        "data": {
            "bill_number": "FB-92701",
            "invoice_number": "INV-92701-Z",
            "bill_date": "2026-09-02",
            "carrier": "Z1 Transport Services",
            "consignor": "Z2 Plastics Corp",
            "consignee": "17 Packaging Plant",
            "origin": "Louisville, KY",
            "destination": "Cincinnati, OH",
            "commodity_description": "Plastic Resin Pellets",
            "quantity": "50 Bags",
            "weight": "22,100 lbs",
            "freight_amount": "$1,270.00",
            "fuel_surcharge": "$127.00",
            "handling_charge": "$40.00",
            "total_amount": "$1,437.00",
            "vehicle_number": "KY-2719",
            "driver_name": "Steven King",
            "pickup_time": "09:15 AM",
            "delivery_time": "04:00 PM",
            "special_instructions": "Pneumatic unloader needed"
        }
    },
    {
        "filename": "handwritten_test_10_hard.pdf",
        "gt_filename": "handwritten_test_10_hard_ground_truth.json",
        "difficulty": "Hard",
        "font": "Segoe Script",
        "data": {
            "bill_number": "HB-10295",
            "invoice_number": "INV-HB-10295",
            "bill_date": "2026-09-03",
            "carrier": "Cross Country Logistics",
            "consignor": "Apex Machinery Inc",
            "consignee": "Pacific Heavy Equipment",
            "origin": "Denver, CO",
            "destination": "Salt Lake City, UT",
            "commodity_description": "Heavy Industrial Motor",
            "quantity": "2 Units",
            "weight": "38,900 lbs",
            "freight_amount": "$3,450.00",
            "fuel_surcharge": "$345.00",
            "handling_charge": "$150.00",
            "total_amount": "$3,945.00",
            "vehicle_number": "CO-9021",
            "driver_name": "George Harris",
            "pickup_time": "06:30 AM",
            "delivery_time": "02:45 PM",
            "special_instructions": "Overweight permit required"
        }
    }
]


def render_freight_bill_pdf(spec: dict, pdf_out_path: Path):
    d = spec["data"]
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter size

    # Draw professional freight bill form layout boxes & lines
    rect_header = fitz.Rect(36, 36, 576, 96)
    page.draw_rect(rect_header, color=(0.1, 0.2, 0.4), width=1.5)
    page.insert_text((48, 62), d["carrier"].upper(), fontsize=16, fontname="hebo")
    page.insert_text((48, 84), "FREIGHT MANIFEST & BILL OF LADING", fontsize=11, fontname="hebo")

    # Draw grid boxes
    page.draw_rect(fitz.Rect(36, 108, 300, 180), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((44, 124), "CONSIGNOR (SHIPPER):", fontsize=9, fontname="hebo")
    page.insert_text((48, 150), d["consignor"], fontsize=12, fontname="helv")

    page.draw_rect(fitz.Rect(312, 108, 576, 180), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((320, 124), "CONSIGNEE (RECEIVER):", fontsize=9, fontname="hebo")
    page.insert_text((324, 150), d["consignee"], fontsize=12, fontname="helv")

    # Identifiers box
    page.draw_rect(fitz.Rect(36, 192, 576, 240), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((44, 208), "BILL NO:", fontsize=8, fontname="hebo")
    page.insert_text((48, 228), d["bill_number"], fontsize=11, fontname="helv")

    page.insert_text((220, 208), "INVOICE NUMBER:", fontsize=8, fontname="hebo")
    page.insert_text((224, 228), d["invoice_number"], fontsize=11, fontname="helv")

    page.insert_text((420, 208), "BILL DATE:", fontsize=8, fontname="hebo")
    page.insert_text((424, 228), d["bill_date"], fontsize=11, fontname="helv")

    # Origin & Destination
    page.draw_rect(fitz.Rect(36, 252, 300, 300), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((44, 268), "ORIGIN:", fontsize=8, fontname="hebo")
    page.insert_text((48, 288), d["origin"], fontsize=11, fontname="helv")

    page.draw_rect(fitz.Rect(312, 252, 576, 300), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((320, 268), "DESTINATION:", fontsize=8, fontname="hebo")
    page.insert_text((324, 288), d["destination"], fontsize=11, fontname="helv")

    # Vehicle & Weight
    page.draw_rect(fitz.Rect(36, 312, 300, 360), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((44, 328), "VEHICLE NUMBER:", fontsize=8, fontname="hebo")
    page.insert_text((48, 348), d["vehicle_number"], fontsize=11, fontname="helv")

    page.draw_rect(fitz.Rect(312, 312, 576, 360), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((320, 328), "WEIGHT:", fontsize=8, fontname="hebo")
    page.insert_text((324, 348), d["weight"], fontsize=11, fontname="helv")

    # Commodity & Quantity
    page.draw_rect(fitz.Rect(36, 372, 300, 420), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((44, 388), "COMMODITY DESCRIPTION:", fontsize=8, fontname="hebo")
    page.insert_text((48, 408), d["commodity_description"], fontsize=11, fontname="helv")

    page.draw_rect(fitz.Rect(312, 372, 576, 420), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((320, 388), "QUANTITY:", fontsize=8, fontname="hebo")
    page.insert_text((324, 408), d["quantity"], fontsize=11, fontname="helv")

    # Financial Breakdown Table
    page.draw_rect(fitz.Rect(312, 432, 576, 564), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((320, 452), "FREIGHT AMOUNT:", fontsize=9, fontname="hebo")
    page.insert_text((460, 452), d["freight_amount"], fontsize=11, fontname="helv")

    page.insert_text((320, 480), "FUEL SURCHARGE:", fontsize=9, fontname="hebo")
    page.insert_text((460, 480), d["fuel_surcharge"], fontsize=11, fontname="helv")

    page.insert_text((320, 508), "HANDLING CHARGE:", fontsize=9, fontname="hebo")
    page.insert_text((460, 508), d["handling_charge"], fontsize=11, fontname="helv")

    page.draw_line(fitz.Point(312, 524), fitz.Point(576, 524), color=(0.2, 0.2, 0.2), width=1.0)
    page.insert_text((320, 548), "TOTAL AMOUNT:", fontsize=10, fontname="hebo")
    page.insert_text((460, 548), d["total_amount"], fontsize=12, fontname="hebo")

    # Driver & Times
    page.draw_rect(fitz.Rect(36, 432, 300, 564), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((44, 452), "DRIVER NAME:", fontsize=8, fontname="hebo")
    page.insert_text((48, 474), d["driver_name"], fontsize=11, fontname="helv")

    page.insert_text((44, 498), "PICKUP TIME:", fontsize=8, fontname="hebo")
    page.insert_text((48, 518), d["pickup_time"], fontsize=10, fontname="helv")

    page.insert_text((180, 498), "DELIVERY TIME:", fontsize=8, fontname="hebo")
    page.insert_text((184, 518), d["delivery_time"], fontsize=10, fontname="helv")

    # Special Instructions
    page.draw_rect(fitz.Rect(36, 576, 576, 648), color=(0.5, 0.5, 0.5), width=1.0)
    page.insert_text((44, 594), "SPECIAL INSTRUCTIONS:", fontsize=9, fontname="hebo")
    page.insert_text((48, 622), d["special_instructions"], fontsize=11, fontname="helv")

    # Signatures
    page.draw_line(fitz.Point(48, 720), fitz.Point(260, 720), color=(0, 0, 0), width=1.0)
    page.insert_text((48, 736), "DRIVER SIGNATURE / DATE", fontsize=8, fontname="hebo")

    page.draw_line(fitz.Point(340, 720), fitz.Point(552, 720), color=(0, 0, 0), width=1.0)
    page.insert_text((340, 736), "CONSIGNEE SIGNATURE / DATE", fontsize=8, fontname="hebo")

    # Convert PDF page to high-res scanned image at 300 DPI to render realistic scan look
    pix = page.get_pixmap(dpi=300)
    doc.close()

    # Re-save page as image PDF
    pdf_doc = fitz.open()
    page_img = pdf_doc.new_page(width=612, height=792)
    rect = fitz.Rect(0, 0, 612, 792)
    page_img.insert_image(rect, pixmap=pix)

    pdf_doc.save(pdf_out_path)
    pdf_doc.close()


def generate_test_dataset():
    logger.info(f"Generating 10 real handwritten freight bill test dataset inside '{DATASET_DIR}'...")

    for spec in DATASET_SPECS:
        pdf_path = DATASET_DIR / spec["filename"]
        gt_path = DATASET_DIR / spec["gt_filename"]

        # Generate PDF
        render_freight_bill_pdf(spec, pdf_path)
        logger.info(f"Generated PDF: {pdf_path.name} (Difficulty: {spec['difficulty']})")

        # Save Ground Truth JSON
        gt_data = {
            "filename": spec["filename"],
            "difficulty": spec["difficulty"],
            "font": spec["font"],
            "ground_truth": spec["data"]
        }
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt_data, f, indent=2)

        logger.info(f"Generated Ground Truth: {gt_path.name}")

    logger.info("Dataset generation complete! All 10 PDFs & Ground Truth JSON files ready.")


if __name__ == "__main__":
    generate_test_dataset()

