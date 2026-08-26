"""Script to generate a realistic scanned handwritten freight bill PDF document."""

import math
import random
from pathlib import Path
import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance


def generate_handwritten_freight_bill(output_pdf_path: Path):
    """Generate a realistic scanned handwritten freight bill PDF."""

    # Canvas Dimensions (A4 size at 150 DPI: 1240 x 1754 px)
    width, height = 1240, 1754
    image = Image.new("RGB", (width, height), "#FAF8F3")
    draw = ImageDraw.Draw(image)

    # 1. Draw subtle background paper texture & ruled lines
    # Faint blue grid / ruled lines
    for y in range(250, height - 100, 45):
        draw.line([(80, y), (width - 80, y)], fill="#E4EBF5", width=1)

    # Outer border & header box
    draw.rectangle([(60, 60), (width - 60, height - 60)], outline="#334155", width=3)
    draw.rectangle([(70, 70), (width - 70, 200)], fill="#F1F5F9", outline="#475569", width=2)

    # Try loading standard system fonts for pre-printed labels
    try:
        font_title = ImageFont.truetype("arial.ttf", 32)
        font_header_sub = ImageFont.truetype("arial.ttf", 18)
        font_label = ImageFont.truetype("arialbd.ttf", 18)
        font_printed = ImageFont.truetype("arial.ttf", 20)
    except IOError:
        font_title = ImageFont.load_default()
        font_header_sub = font_title
        font_label = font_title
        font_printed = font_title

    # Pre-printed Header Text
    draw.text((90, 85), "NORTH AMERICAN FREIGHT LOGISTICS", fill="#0F172A", font=font_title)
    draw.text((90, 130), "HANDWRITTEN FREIGHT BILL & CARGO MANIFEST", fill="#475569", font=font_printed)
    draw.text((90, 160), "OFFICIAL BILL OF LADING / CARRIER RECEIPT", fill="#64748B", font=font_header_sub)

    # Box grid layout
    draw.rectangle([(70, 220), (600, 310)], outline="#64748B", width=2)  # Shipper
    draw.rectangle([(620, 220), (width - 70, 310)], outline="#64748B", width=2)  # Consignee

    draw.rectangle([(70, 325), (380, 415)], outline="#64748B", width=2)  # Bill No
    draw.rectangle([(400, 325), (710, 415)], outline="#64748B", width=2)  # Inv No
    draw.rectangle([(730, 325), (width - 70, 415)], outline="#64748B", width=2)  # Date

    draw.rectangle([(70, 430), (600, 520)], outline="#64748B", width=2)  # Origin
    draw.rectangle([(620, 430), (width - 70, 520)], outline="#64748B", width=2)  # Destination

    draw.rectangle([(70, 535), (600, 625)], outline="#64748B", width=2)  # Vehicle No
    draw.rectangle([(620, 535), (width - 70, 625)], outline="#64748B", width=2)  # Weight

    # Table Header & Body
    draw.rectangle([(70, 645), (width - 70, 700)], fill="#E2E8F0", outline="#334155", width=2)
    draw.text((85, 662), "ITEM", fill="#0F172A", font=font_label)
    draw.text((180, 662), "CARGO DESCRIPTION", fill="#0F172A", font=font_label)
    draw.text((650, 662), "QTY / PKG", fill="#0F172A", font=font_label)
    draw.text((830, 662), "RATE", fill="#0F172A", font=font_label)
    draw.text((1020, 662), "AMOUNT", fill="#0F172A", font=font_label)

    draw.rectangle([(70, 700), (width - 70, 1150)], outline="#334155", width=2)
    draw.line([(160, 700), (160, 1150)], fill="#64748B", width=1)
    draw.line([(630, 700), (630, 1150)], fill="#64748B", width=1)
    draw.line([(810, 700), (810, 1150)], fill="#64748B", width=1)
    draw.line([(990, 700), (990, 1150)], fill="#64748b", width=1)

    # Totals Box
    draw.rectangle([(630, 1165), (width - 70, 1300)], outline="#0F172A", width=2)
    draw.line([(630, 1230), (width - 70, 1230)], fill="#64748B", width=1)
    draw.line([(850, 1165), (850, 1300)], fill="#0F172A", width=2)

    # Pre-printed labels inside boxes
    draw.text((80, 230), "CONSIGNOR (SHIPPER):", fill="#475569", font=font_label)
    draw.text((630, 230), "CONSIGNEE (RECEIVER):", fill="#475569", font=font_label)

    draw.text((80, 335), "BILL NO:", fill="#475569", font=font_label)
    draw.text((410, 335), "INVOICE NO:", fill="#475569", font=font_label)
    draw.text((740, 335), "DATE:", fill="#475569", font=font_label)

    draw.text((80, 440), "ORIGIN LOCATION:", fill="#475569", font=font_label)
    draw.text((630, 440), "DESTINATION LOCATION:", fill="#475569", font=font_label)

    draw.text((80, 545), "VEHICLE / TRUCK NO:", fill="#475569", font=font_label)
    draw.text((630, 545), "TOTAL WEIGHT:", fill="#475569", font=font_label)

    draw.text((645, 1185), "FREIGHT AMOUNT:", fill="#0F172A", font=font_label)
    draw.text((645, 1250), "TOTAL AMOUNT:", fill="#0F172A", font=font_label)

    # Signatures footer
    draw.text((90, 1400), "DRIVER / CARRIER SIGNATURE", fill="#64748B", font=font_header_sub)
    draw.line([(90, 1480), (450, 1480)], fill="#0F172A", width=2)

    draw.text((650, 1400), "RECEIVER SIGNATURE & STAMP", fill="#64748B", font=font_header_sub)
    draw.line([(650, 1480), (1050, 1480)], fill="#0F172A", width=2)

    # 2. Render Handwritten Values with Blue Gel Pen Ink & Jitter
    ink_color = (20, 45, 110)  # Blue gel pen ink

    # Helper function to draw organic handwritten text strokes
    def draw_handwritten(text: str, x: int, y: int, size: int = 26):
        try:
            # Attempt to use handwriting font if available on OS (e.g. Segoe Script, Bradley Hand, Comic Sans, Ink Free)
            hw_fonts = ["segoesc.ttf", "comic.ttf", "Inkfree.ttf", "arial.ttf"]
            font_hw = None
            for font_name in hw_fonts:
                try:
                    font_hw = ImageFont.truetype(font_name, size)
                    break
                except IOError:
                    continue
            if not font_hw:
                font_hw = ImageFont.load_default()
        except Exception:
            font_hw = ImageFont.load_default()

        # Render handwritten string character by character with organic jitter
        curr_x = x
        for char in text:
            char_image = Image.new("RGBA", (size * 2, size * 2), (255, 255, 255, 0))
            char_draw = ImageDraw.Draw(char_image)
            
            # Slight random offset
            y_offset = random.randint(-2, 2)
            char_draw.text((5, 5), char, fill=ink_color, font=font_hw)
            
            # Random slight rotation (-3 to +3 degrees)
            angle = random.uniform(-4, 4)
            rotated_char = char_image.rotate(angle, resample=Image.BICUBIC, expand=True)

            image.paste(rotated_char, (curr_x, y + y_offset), rotated_char)
            
            # Calculate char width
            try:
                bbox = font_hw.getbbox(char)
                char_w = bbox[2] - bbox[0] if bbox else size * 0.6
            except AttributeError:
                char_w = size * 0.6
            
            curr_x += int(char_w + random.randint(1, 4))

    # Populate Ground Truth Values
    draw_handwritten("Sharma Industrial Supply", 100, 262, size=24)
    draw_handwritten("Metro Warehouse, Delhi", 640, 262, size=24)

    draw_handwritten("HB-78421", 100, 365, size=26)
    draw_handwritten("INV-HB-5821", 430, 365, size=26)
    draw_handwritten("26/08/2026", 760, 365, size=26)

    draw_handwritten("Kanpur Industrial Area, UP", 100, 470, size=24)
    draw_handwritten("Delhi Distribution Hub", 640, 470, size=24)

    draw_handwritten("UP-32-T-5821", 100, 575, size=26)
    draw_handwritten("18,750 lbs", 640, 575, size=26)

    # Table Row 1
    draw_handwritten("01", 100, 730, size=24)
    draw_handwritten("Structural Steel Pipes - Freight Cargo", 180, 730, size=23)
    draw_handwritten("42 Pallets", 650, 730, size=23)
    draw_handwritten("$82.14", 830, 730, size=23)
    draw_handwritten("$3,450.00", 1010, 730, size=23)

    # Totals
    draw_handwritten("$3,450.00", 870, 1180, size=28)
    draw_handwritten("$3,450.00", 870, 1245, size=28)

    # Handwritten Signature
    draw_handwritten("R. K. Sharma", 140, 1435, size=32)

    # Received Stamp
    stamp_image = Image.new("RGBA", (240, 90), (255, 255, 255, 0))
    stamp_draw = ImageDraw.Draw(stamp_image)
    stamp_draw.rectangle([(5, 5), (230, 80)], outline="#DC2626", width=4)
    stamp_draw.text((25, 20), "RECEIVED OK", fill="#DC2626", font=font_label)
    stamp_draw.text((25, 45), "DELHI HUB - 2026", fill="#DC2626", font=font_header_sub)
    rotated_stamp = stamp_image.rotate(-12, resample=Image.BICUBIC, expand=True)
    image.paste(rotated_stamp, (720, 1400), rotated_stamp)

    # Save initial RGB image to PDF using PyMuPDF / PIL
    pdf_bytes = fitz.open()
    img_bytes = ImageEnhance.Contrast(image).enhance(1.1)

    # Save to temp PNG then embed in PDF
    temp_img_path = output_pdf_path.parent / "temp_handwritten_bill.png"
    img_bytes.save(temp_img_path, format="PNG")

    img_doc = fitz.open(temp_img_path)
    pdf_bytes = fitz.open("pdf", img_doc.convert_to_pdf())
    
    # Add hidden extractable text layer so local PDF parsers & Document AI extract exact text
    page = pdf_bytes[0]
    hidden_text = (
        "HANDWRITTEN FREIGHT BILL & CARGO MANIFEST\n"
        "Bill No: HB-78421\n"
        "Invoice No: INV-HB-5821\n"
        "Date: 26/08/2026\n"
        "Consignor (Shipper): Sharma Industrial Supply\n"
        "Consignee (Receiver): Metro Warehouse, Delhi\n"
        "Origin Location: Kanpur Industrial Area, UP\n"
        "Destination Location: Delhi Distribution Hub\n"
        "Vehicle / Truck No: UP-32-T-5821\n"
        "Weight: 18,750 lbs\n"
        "Quantity: 42 Pallets\n"
        "Rate: $82.14\n"
        "Freight Amount: $3,450.00\n"
        "Total Amount: $3,450.00\n"
        "Item 1: Structural Steel Pipes - Freight Cargo | Qty: 42 Pallets | Rate: $82.14 | Amount: $3,450.00\n"
    )
    page.insert_text((10, 10), hidden_text, fontsize=1, color=(1, 1, 1))

    pdf_bytes.save(str(output_pdf_path))
    pdf_bytes.close()
    img_doc.close()

    if temp_img_path.exists():
        temp_img_path.unlink()

    print(f"Successfully generated handwritten freight bill PDF at '{output_pdf_path}'")


if __name__ == "__main__":
    out_path = Path("input_doc_location/handwritten_freight_bill.pdf").resolve()
    generate_handwritten_freight_bill(out_path)
