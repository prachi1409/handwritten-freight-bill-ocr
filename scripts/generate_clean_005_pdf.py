"""Script to generate freight_bill_clean_005.pdf document."""

import math
import random
from pathlib import Path
import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont, ImageEnhance


def generate_clean_005_pdf(output_pdf_path: Path):
    """Generate realistic scanned handwritten/printed freight bill PDF for clean_005 test."""

    width, height = 1240, 1754
    image = Image.new("RGB", (width, height), "#FAFAFA")
    draw = ImageDraw.Draw(image)

    # Background grid lines
    for y in range(250, height - 100, 50):
        draw.line([(80, y), (width - 80, y)], fill="#E2E8F0", width=1)

    # Outer border & header box
    draw.rectangle([(60, 60), (width - 60, height - 60)], outline="#1E293B", width=3)
    draw.rectangle([(70, 70), (width - 70, 190)], fill="#F8FAFC", outline="#334155", width=2)

    try:
        font_title = ImageFont.truetype("arial.ttf", 30)
        font_label = ImageFont.truetype("arialbd.ttf", 18)
        font_printed = ImageFont.truetype("arial.ttf", 20)
    except IOError:
        font_title = ImageFont.load_default()
        font_label = font_title
        font_printed = font_title

    # Header
    draw.text((90, 85), "MIDWEST HAULING FREIGHT LOGISTICS", fill="#0F172A", font=font_title)
    draw.text((90, 130), "FREIGHT BILL & MANIFEST", fill="#475569", font=font_printed)

    # Layout boxes
    draw.rectangle([(70, 210), (600, 300)], outline="#475569", width=2)  # Shipper
    draw.rectangle([(620, 210), (width - 70, 300)], outline="#475569", width=2)  # Consignee

    draw.rectangle([(70, 315), (380, 405)], outline="#475569", width=2)  # Bill No
    draw.rectangle([(400, 315), (710, 405)], outline="#475569", width=2)  # Inv No
    draw.rectangle([(730, 315), (width - 70, 405)], outline="#475569", width=2)  # Date

    draw.rectangle([(70, 420), (600, 510)], outline="#475569", width=2)  # Origin
    draw.rectangle([(620, 420), (width - 70, 510)], outline="#475569", width=2)  # Destination

    draw.rectangle([(70, 525), (600, 615)], outline="#475569", width=2)  # Vehicle No
    draw.rectangle([(620, 525), (width - 70, 615)], outline="#475569", width=2)  # Weight

    draw.rectangle([(70, 630), (600, 720)], outline="#475569", width=2)  # Carrier
    draw.rectangle([(620, 630), (width - 70, 720)], outline="#475569", width=2)  # Commodity

    draw.rectangle([(70, 735), (380, 825)], outline="#475569", width=2)  # Qty
    draw.rectangle([(400, 735), (710, 825)], outline="#475569", width=2)  # Driver
    draw.rectangle([(730, 735), (width - 70, 825)], outline="#475569", width=2)  # Pickup / Delivery Time

    # Amounts box
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

    # Render Document Values
    def draw_text_val(text: str, x: int, y: int, size: int = 24):
        try:
            font_v = ImageFont.truetype("arialbd.ttf", size)
        except IOError:
            font_v = ImageFont.load_default()
        draw.text((x, y), text, fill="#0F172A", font=font_v)

    draw_text_val("Acme Steel Corp", 100, 255)
    draw_text_val("Costco Wholesale #221", 640, 255)

    draw_text_val("FB-10238", 100, 355)
    draw_text_val("INV-87924", 430, 355)
    draw_text_val("8/24/26", 760, 355)

    draw_text_val("Chicago, IL", 100, 460)
    draw_text_val("Memphis, TN", 640, 460)

    draw_text_val("#261", 100, 565)
    draw_text_val("43,533 lbs", 640, 565)

    draw_text_val("Midwest Hauling LLC", 100, 670)
    draw_text_val("Building Materials", 640, 670)

    draw_text_val("21", 100, 775)
    draw_text_val("Roberto Nunez", 430, 775)
    draw_text_val("10:00 AM / 2:00 PM", 760, 775)

    draw_text_val("$848.89", 870, 860)
    draw_text_val("$916.80", 870, 925)

    draw_text_val("Call on arrival", 100, 1035)

    # Save to PNG then convert to pure image PDF (no text layer)
    temp_img_path = output_pdf_path.parent / "temp_clean_005.png"
    image.save(temp_img_path, format="PNG")

    img_doc = fitz.open(temp_img_path)
    pdf_bytes = fitz.open("pdf", img_doc.convert_to_pdf())
    pdf_bytes.save(str(output_pdf_path))
    pdf_bytes.close()
    img_doc.close()

    if temp_img_path.exists():
        temp_img_path.unlink()

    print(f"Generated scanned image PDF at '{output_pdf_path}'")


if __name__ == "__main__":
    out_1 = Path("input_doc_location/clean_005.pdf").resolve()
    out_2 = Path("input_doc_location/freight_bill_clean_005.pdf").resolve()
    generate_clean_005_pdf(out_1)
    generate_clean_005_pdf(out_2)

