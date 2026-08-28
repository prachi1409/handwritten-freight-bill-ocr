"""Tests for image preprocessing and deskew."""

from PIL import Image, ImageDraw

from app.ocr.local_processor import LocalOCRProcessor, _choose_ocr_text, _text_is_sparse
from app.ocr.preprocessor import deskew_image, preprocess_pdf_pages


def test_preprocess_pdf_pages_renders_images(create_pdf):
    pdf_path = create_pdf("preproc_test.pdf", "Sample PDF Text for Preprocessing")
    images = preprocess_pdf_pages(pdf_path)
    assert len(images) == 1
    assert images[0].width > 0
    assert images[0].height > 0
    assert images[0].mode == "RGB"


def test_deskew_image_corrects_rotated_lines():
    img = Image.new("L", (400, 200), 255)
    draw = ImageDraw.Draw(img)
    for y in range(40, 180, 20):
        draw.line([(20, y), (380, y)], fill=0, width=3)
    skewed = img.rotate(8, expand=True, fillcolor=255)

    corrected, angle = deskew_image(skewed, max_angle=12.0)
    assert corrected.size[0] > 0
    assert abs(angle) >= 0.5


def test_choose_ocr_text_prefers_rich_pdf_layer():
    native = "Bill No: HB-1\nConsignor: Acme\n" * 5
    image = "noisy scan fragments"
    text, source = _choose_ocr_text(native, image)
    assert source == "pdf_text"
    assert "HB-1" in text


def test_choose_ocr_text_uses_image_when_pdf_empty():
    image = "Bill No: FB-99\nShipper: Steel Co\nOrigin: Houston\nDestination: Dallas\n"
    text, source = _choose_ocr_text("", image)
    assert source == "preprocessed_image"
    assert "FB-99" in text


def test_text_is_sparse():
    assert _text_is_sparse("")
    assert _text_is_sparse("...")
    assert not _text_is_sparse("Bill No HB78421 Consignor Acme Logistics Origin Houston")


def test_local_processor_records_preprocessing_metadata(create_pdf):
    pdf_path = create_pdf(
        "meta_bill.pdf",
        "Bill No: HB-1\nInvoice No: INV-1\nDate: 01/01/2026\n"
        "Consignor: A\nConsignee: B\nOrigin: X\nDestination: Y\nTotal Amount: $10.00\n",
    )
    result = LocalOCRProcessor().process_document(pdf_path)
    assert result.raw_ocr["ocr_text_source"] == "pdf_text"
    assert "preprocessing" in result.raw_ocr
    assert result.raw_ocr["preprocessing"]["dpi"] >= 150
    assert isinstance(result.raw_ocr["preprocessing"]["deskew_angles"], list)
