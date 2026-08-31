"""Generator script for 3 distinct, realistic handwritten freight bill PDF test documents."""

import math
import random
from pathlib import Path
import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont, ImageEnhance


def generate_handwritten_pdf_1(out_path: Path):
    """PDF 1: Medium Cursive Handwriting (Segoe Script font)."""
    width, height = 1240, 1754
    image = Image.new("RGB", (width, height), "#FAF9F6")
    draw = ImageDraw.Draw(image)

    # Grid background
    for y in range(250, height - 100, 48):
        draw.line([(80, y), (width - 80, y)], fill="#E2E8F0", width=1)

    draw.rectangle([(60, 60), (width - 60, height - 60)], outline="#1E293B", width=3)
    draw.rectangle([(70, 70), (width - 70, 190)], fill="#F1F5F9", outline="#334155", width=2)

    try:
        font_title = ImageFont.truetype("arialbd.ttf", 30)
        font_label = ImageFont.truetype("arialbd.ttf", 17)
        font_hw = ImageFont.truetype("segoesc.ttf", 22)
    except IOError:
        font_title = font_label = font_hw = ImageFont.load_default()

    draw.text((90, 85), "SUMMIT LINE HAUL LOGISTICS", fill="#0F172A", font=font_title)
    draw.text((90, 135), "FREIGHT BILL & CARGO MANIFEST", fill="#475569", font=font_label)

    # Form boxes
    draw.rectangle([(70, 210), (600, 300)], outline="#475569", width=2)
    draw.rectangle([(620, 210), (width - 70, 300)], outline="#475569", width=2)
    draw.rectangle([(70, 315), (380, 405)], outline="#475569", width=2)
    draw.rectangle([(400, 315), (710, 405)], outline="#475569", width=2)
    draw.rectangle([(730, 315), (width - 70, 405)], outline="#475569", width=2)
    draw.rectangle([(70, 420), (600, 510)], outline="#475569", width=2)
    draw.rectangle([(620, 420), (width - 70, 510)], outline="#475569", width=2)
    draw.rectangle([(70, 525), (600, 615)], outline="#475569", width=2)
    draw.rectangle([(620, 525), (width - 70, 615)], outline="#475569", width=2)
    draw.rectangle([(70, 630), (600, 720)], outline="#475569", width=2)
    draw.rectangle([(620, 630), (width - 70, 720)], outline="#475569", width=2)
    draw.rectangle([(70, 735), (380, 825)], outline="#475569", width=2)
    draw.rectangle([(400, 735), (710, 825)], outline="#475569", width=2)
    draw.rectangle([(730, 735), (width - 70, 825)], outline="#475569", width=2)
    draw.rectangle([(620, 840), (width - 70, 970)], outline="#0F172A", width=2)
    draw.line([(620, 905), (width - 70, 905)], fill="#475569", width=1)
    draw.line([(850, 840), (850, 970)], fill="#0F172A", width=2)

    # Labels
    draw.text((80, 220), "CONSIGNOR (SHIPPER):", fill="#475569", font=font_label)
    draw.text((630, 220), "CONSIGNEE (RECEIVER):", fill="#475569", font=font_label)
    draw.text((80, 325), "BILL NO:", fill="#475569", font=font_label)
    draw.text((410, 325), "INVOICE NUMBER:", fill="#475569", font=font_label)
    draw.text((740, 325), "DATE:", fill="#475569", font=font_label)
    draw.text((80, 430), "ORIGIN:", fill="#475569", font=font_label)
    draw.text((630, 430), "DESTINATION:", fill="#475569", font=font_label)
    draw.text((80, 535), "VEHICLE NUMBER:", fill="#475569", font=font_label)
    draw.text((630, 535), "WEIGHT:", fill="#475569", font=font_label)
    draw.text((80, 640), "CARRIER:", fill="#475569", font=font_label)
    draw.text((630, 640), "COMMODITY DESCRIPTION:", fill="#475569", font=font_label)
    draw.text((80, 745), "QUANTITY:", fill="#475569", font=font_label)
    draw.text((410, 745), "DRIVER NAME:", fill="#475569", font=font_label)
    draw.text((740, 745), "PICKUP / DELIVERY TIME:", fill="#475569", font=font_label)
    draw.text((635, 860), "FREIGHT AMOUNT:", fill="#0F172A", font=font_label)
    draw.text((635, 925), "TOTAL AMOUNT:", fill="#0F172A", font=font_label)
    draw.text((80, 1000), "SPECIAL INSTRUCTIONS:", fill="#475569", font=font_label)

    # Handwritten values (Blue ink)
    ink = (15, 35, 110)
    draw.text((100, 255), "Westfield Components Inc.", fill=ink, font=font_hw)
    draw.text((640, 255), "Central Retail DC #8", fill=ink, font=font_hw)
    draw.text((100, 355), "FB-38164", fill=ink, font=font_hw)
    draw.text((430, 355), "INV-58321", fill=ink, font=font_hw)
    draw.text((760, 355), "08/27/2026", fill=ink, font=font_hw)
    draw.text((100, 460), "Dallas, TX", fill=ink, font=font_hw)
    draw.text((640, 460), "Oklahoma City, OK", fill=ink, font=font_hw)
    draw.text((100, 565), "TX-5842", fill=ink, font=font_hw)
    draw.text((640, 565), "18,760 lbs", fill=ink, font=font_hw)
    draw.text((100, 670), "Summit Line Haul LLC", fill=ink, font=font_hw)
    draw.text((640, 670), "Electrical Components", fill=ink, font=font_hw)
    draw.text((100, 775), "24 Pallets", fill=ink, font=font_hw)
    draw.text((430, 775), "Michael Carter", fill=ink, font=font_hw)
    draw.text((760, 775), "08:15 AM / 03:45 PM", fill=ink, font=font_hw)
    draw.text((870, 860), "$1,485.60", fill=ink, font=font_hw)
    draw.text((870, 925), "$1,572.35", fill=ink, font=font_hw)
    draw.text((100, 1035), "Call receiving before arrival", fill=ink, font=font_hw)

    # Save to pure image PDF
    temp_img = out_path.parent / "temp_p1.png"
    image.save(temp_img, format="PNG")
    img_doc = fitz.open(temp_img)
    pdf_doc = fitz.open("pdf", img_doc.convert_to_pdf())
    pdf_doc.save(str(out_path))
    pdf_doc.close()
    img_doc.close()
    if temp_img.exists():
        temp_img.unlink()
    print(f"Generated PDF 1 at '{out_path}'")


def generate_handwritten_pdf_2(out_path: Path):
    """PDF 2: Hard Slanted Handwriting (Ink Free font with extra financial breakdown)."""
    width, height = 1240, 1754
    image = Image.new("RGB", (width, height), "#FFFDF9")
    draw = ImageDraw.Draw(image)

    for y in range(250, height - 100, 50):
        draw.line([(80, y), (width - 80, y)], fill="#E2E8F0", width=1)

    draw.rectangle([(60, 60), (width - 60, height - 60)], outline="#0F172A", width=3)
    draw.rectangle([(70, 70), (width - 70, 190)], fill="#F8FAFC", outline="#334155", width=2)

    try:
        font_title = ImageFont.truetype("arialbd.ttf", 30)
        font_label = ImageFont.truetype("arialbd.ttf", 17)
        font_hw = ImageFont.truetype("Inkfree.ttf", 26)
    except IOError:
        font_title = font_label = font_hw = ImageFont.load_default()

    draw.text((90, 85), "APEX FREIGHT CARRIERS", fill="#0F172A", font=font_title)
    draw.text((90, 135), "BILL OF LADING & RECEIPT", fill="#475569", font=font_label)

    # Layout boxes
    draw.rectangle([(70, 210), (600, 300)], outline="#475569", width=2)
    draw.rectangle([(620, 210), (width - 70, 300)], outline="#475569", width=2)
    draw.rectangle([(70, 315), (380, 405)], outline="#475569", width=2)
    draw.rectangle([(400, 315), (710, 405)], outline="#475569", width=2)
    draw.rectangle([(730, 315), (width - 70, 405)], outline="#475569", width=2)
    draw.rectangle([(70, 420), (600, 510)], outline="#475569", width=2)
    draw.rectangle([(620, 420), (width - 70, 510)], outline="#475569", width=2)
    draw.rectangle([(70, 525), (600, 615)], outline="#475569", width=2)
    draw.rectangle([(620, 525), (width - 70, 615)], outline="#475569", width=2)
    draw.rectangle([(70, 630), (600, 720)], outline="#475569", width=2)
    draw.rectangle([(620, 630), (width - 70, 720)], outline="#475569", width=2)
    draw.rectangle([(70, 735), (380, 825)], outline="#475569", width=2)
    draw.rectangle([(400, 735), (710, 825)], outline="#475569", width=2)
    draw.rectangle([(730, 735), (width - 70, 825)], outline="#475569", width=2)

    # Financial Breakdown Box
    draw.rectangle([(620, 840), (width - 70, 1030)], outline="#0F172A", width=2)
    draw.line([(620, 885), (width - 70, 885)], fill="#475569", width=1)
    draw.line([(620, 930), (width - 70, 930)], fill="#475569", width=1)
    draw.line([(620, 975), (width - 70, 975)], fill="#475569", width=1)
    draw.line([(850, 840), (850, 1030)], fill="#0F172A", width=2)

    # Labels
    draw.text((80, 220), "CONSIGNOR (SHIPPER):", fill="#475569", font=font_label)
    draw.text((630, 220), "CONSIGNEE (RECEIVER):", fill="#475569", font=font_label)
    draw.text((80, 325), "BILL NO:", fill="#475569", font=font_label)
    draw.text((410, 325), "INVOICE NUMBER:", fill="#475569", font=font_label)
    draw.text((740, 325), "DATE:", fill="#475569", font=font_label)
    draw.text((80, 430), "ORIGIN:", fill="#475569", font=font_label)
    draw.text((630, 430), "DESTINATION:", fill="#475569", font=font_label)
    draw.text((80, 535), "VEHICLE NUMBER:", fill="#475569", font=font_label)
    draw.text((630, 535), "WEIGHT:", fill="#475569", font=font_label)
    draw.text((80, 640), "CARRIER:", fill="#475569", font=font_label)
    draw.text((630, 640), "COMMODITY DESCRIPTION:", fill="#475569", font=font_label)
    draw.text((80, 745), "QUANTITY:", fill="#475569", font=font_label)
    draw.text((410, 745), "DRIVER NAME:", fill="#475569", font=font_label)
    draw.text((740, 745), "PICKUP / DELIVERY TIME:", fill="#475569", font=font_label)

    draw.text((635, 855), "FREIGHT AMOUNT:", fill="#0F172A", font=font_label)
    draw.text((635, 900), "FUEL SURCHARGE:", fill="#0F172A", font=font_label)
    draw.text((635, 945), "HANDLING CHARGE:", fill="#0F172A", font=font_label)
    draw.text((635, 990), "TOTAL AMOUNT:", fill="#0F172A", font=font_label)
    draw.text((80, 1060), "SPECIAL INSTRUCTIONS:", fill="#475569", font=font_label)

    # Handwritten Values (Dark Slate Ink)
    ink = (20, 30, 70)
    draw.text((100, 255), "Pinnacle Metals Corp", fill=ink, font=font_hw)
    draw.text((640, 255), "Vanguard Distribution Hub", fill=ink, font=font_hw)
    draw.text((100, 355), "HB-73184", fill=ink, font=font_hw)
    draw.text((430, 355), "INV-HB-73148", fill=ink, font=font_hw)
    draw.text((760, 355), "08/29/2026", fill=ink, font=font_hw)
    draw.text((100, 460), "Atlanta, GA", fill=ink, font=font_hw)
    draw.text((640, 460), "Charlotte, NC", fill=ink, font=font_hw)
    draw.text((100, 565), "GA-9104", fill=ink, font=font_hw)
    draw.text((640, 565), "32,450 lbs", fill=ink, font=font_hw)
    draw.text((100, 670), "Apex Freight Carriers", fill=ink, font=font_hw)
    draw.text((640, 670), "Industrial Aluminum Tubing", fill=ink, font=font_hw)
    draw.text((100, 775), "15 Bundles", fill=ink, font=font_hw)
    draw.text((430, 775), "David Reynolds", fill=ink, font=font_hw)
    draw.text((760, 775), "09:30 AM / 04:15 PM", fill=ink, font=font_hw)

    draw.text((870, 855), "$1,276.40", fill=ink, font=font_hw)
    draw.text((870, 900), "$102.11", fill=ink, font=font_hw)
    draw.text((870, 945), "$38.50", fill=ink, font=font_hw)
    draw.text((870, 990), "$1,417.01", fill=ink, font=font_hw)

    draw.text((100, 1095), "Liftgate required at destination", fill=ink, font=font_hw)

    # Save to pure image PDF
    temp_img = out_path.parent / "temp_p2.png"
    image.save(temp_img, format="PNG")
    img_doc = fitz.open(temp_img)
    pdf_doc = fitz.open("pdf", img_doc.convert_to_pdf())
    pdf_doc.save(str(out_path))
    pdf_doc.close()
    img_doc.close()
    if temp_img.exists():
        temp_img.unlink()
    print(f"Generated PDF 2 at '{out_path}'")


def generate_handwritten_pdf_3(out_path: Path):
    """PDF 3: Very Hard Mixed Quality Handwriting (Comic Sans font)."""
    width, height = 1240, 1754
    image = Image.new("RGB", (width, height), "#FAFAF5")
    draw = ImageDraw.Draw(image)

    for y in range(250, height - 100, 50):
        draw.line([(80, y), (width - 80, y)], fill="#CBD5E1", width=1)

    draw.rectangle([(60, 60), (width - 60, height - 60)], outline="#334155", width=3)
    draw.rectangle([(70, 70), (width - 70, 190)], fill="#F1F5F9", outline="#475569", width=2)

    try:
        font_title = ImageFont.truetype("arialbd.ttf", 30)
        font_label = ImageFont.truetype("arialbd.ttf", 17)
        font_hw = ImageFont.truetype("comic.ttf", 23)
    except IOError:
        font_title = font_label = font_hw = ImageFont.load_default()

    draw.text((90, 85), "TITAN GLOBAL LOGISTICS", fill="#0F172A", font=font_title)
    draw.text((90, 135), "FREIGHT MANIFEST & CARRIER BILL", fill="#475569", font=font_label)

    # Layout boxes
    draw.rectangle([(70, 210), (600, 300)], outline="#475569", width=2)
    draw.rectangle([(620, 210), (width - 70, 300)], outline="#475569", width=2)
    draw.rectangle([(70, 315), (380, 405)], outline="#475569", width=2)
    draw.rectangle([(400, 315), (710, 405)], outline="#475569", width=2)
    draw.rectangle([(730, 315), (width - 70, 405)], outline="#475569", width=2)
    draw.rectangle([(70, 420), (600, 510)], outline="#475569", width=2)
    draw.rectangle([(620, 420), (width - 70, 510)], outline="#475569", width=2)
    draw.rectangle([(70, 525), (600, 615)], outline="#475569", width=2)
    draw.rectangle([(620, 525), (width - 70, 615)], outline="#475569", width=2)
    draw.rectangle([(70, 630), (600, 720)], outline="#475569", width=2)
    draw.rectangle([(620, 630), (width - 70, 720)], outline="#475569", width=2)
    draw.rectangle([(70, 735), (380, 825)], outline="#475569", width=2)
    draw.rectangle([(400, 735), (710, 825)], outline="#475569", width=2)
    draw.rectangle([(730, 735), (width - 70, 825)], outline="#475569", width=2)

    draw.rectangle([(620, 840), (width - 70, 970)], outline="#0F172A", width=2)
    draw.line([(620, 905), (width - 70, 905)], fill="#475569", width=1)
    draw.line([(850, 840), (850, 970)], fill="#0F172A", width=2)

    # Labels
    draw.text((80, 220), "CONSIGNOR (SHIPPER):", fill="#475569", font=font_label)
    draw.text((630, 220), "CONSIGNEE (RECEIVER):", fill="#475569", font=font_label)
    draw.text((80, 325), "BILL NO:", fill="#475569", font=font_label)
    draw.text((410, 325), "INVOICE NUMBER:", fill="#475569", font=font_label)
    draw.text((740, 325), "DATE:", fill="#475569", font=font_label)
    draw.text((80, 430), "ORIGIN:", fill="#475569", font=font_label)
    draw.text((630, 430), "DESTINATION:", fill="#475569", font=font_label)
    draw.text((80, 535), "VEHICLE NUMBER:", fill="#475569", font=font_label)
    draw.text((630, 535), "WEIGHT:", fill="#475569", font=font_label)
    draw.text((80, 640), "CARRIER:", fill="#475569", font=font_label)
    draw.text((630, 640), "COMMODITY DESCRIPTION:", fill="#475569", font=font_label)
    draw.text((80, 745), "QUANTITY:", fill="#475569", font=font_label)
    draw.text((410, 745), "DRIVER NAME:", fill="#475569", font=font_label)
    draw.text((740, 745), "PICKUP / DELIVERY TIME:", fill="#475569", font=font_label)

    draw.text((635, 860), "FREIGHT AMOUNT:", fill="#0F172A", font=font_label)
    draw.text((635, 925), "TOTAL AMOUNT:", fill="#0F172A", font=font_label)
    draw.text((80, 1000), "SPECIAL INSTRUCTIONS:", fill="#475569", font=font_label)

    # Handwritten values (Dark Charcoal Ink)
    ink = (30, 35, 45)
    draw.text((100, 255), "Starlight Chemical Labs", fill=ink, font=font_hw)
    draw.text((640, 255), "Midwest Pharma Storage", fill=ink, font=font_hw)
    draw.text((100, 355), "FB-92041", fill=ink, font=font_hw)
    draw.text((430, 355), "INV-92041-B", fill=ink, font=font_hw)
    draw.text((760, 355), "08/30/2026", fill=ink, font=font_hw)
    draw.text((100, 460), "Indianapolis, IN", fill=ink, font=font_hw)
    draw.text((640, 460), "Columbus, OH", fill=ink, font=font_hw)
    draw.text((100, 565), "IN-4421", fill=ink, font=font_hw)
    draw.text((640, 565), "14,920 lbs", fill=ink, font=font_hw)
    draw.text((100, 670), "Titan Global Logistics", fill=ink, font=font_hw)
    draw.text((640, 670), "Non-Hazardous Lab Supplies", fill=ink, font=font_hw)
    draw.text((100, 775), "38 Crates", fill=ink, font=font_hw)
    draw.text((430, 775), "Marcus Vance", fill=ink, font=font_hw)
    draw.text((760, 775), "07:45 AM / 01:30 PM", fill=ink, font=font_hw)

    draw.text((870, 860), "$2,140.00", fill=ink, font=font_hw)
    draw.text((870, 925), "$2,315.50", fill=ink, font=font_hw)

    draw.text((100, 1035), "Keep dry - temperature sensitive", fill=ink, font=font_hw)

    # Save to pure image PDF
    temp_img = out_path.parent / "temp_p3.png"
    image.save(temp_img, format="PNG")
    img_doc = fitz.open(temp_img)
    pdf_doc = fitz.open("pdf", img_doc.convert_to_pdf())
    pdf_doc.save(str(out_path))
    pdf_doc.close()
    img_doc.close()
    if temp_img.exists():
        temp_img.unlink()
    print(f"Generated PDF 3 at '{out_path}'")


if __name__ == "__main__":
    target_dir = Path(r"c:\Users\Prachi\OneDrive\Desktop\bill-ocr\backend\input_doc_location").resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    generate_handwritten_pdf_1(target_dir / "handwritten_test_medium_01.pdf")
    generate_handwritten_pdf_2(target_dir / "handwritten_test_hard_02.pdf")
    generate_handwritten_pdf_3(target_dir / "handwritten_test_hard_03.pdf")

