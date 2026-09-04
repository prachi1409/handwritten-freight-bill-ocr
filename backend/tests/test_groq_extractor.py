"""Tests for Groq JSON mapping and Spanish regex fallback."""

from app.ocr.field_extractor import extract_fields_from_raw_text
from app.ocr.groq_extractor import apply_llm_fields, parse_llm_fields, translate_fields_for_display, _extract_json_object


def test_parse_groq_json_from_fenced_response():
    payload = _extract_json_object('```json\n{"bill_number": "CP-12", "consignor": "Acme"}\n```')
    assert payload["bill_number"] == "CP-12"


def test_parse_groq_json_from_thinking_wrapper():
    payload = _extract_json_object(
        '<think>need json</think>\nHere:\n{"consignor": "BELL MARINE", "weight": "17.85"}\n'
    )
    assert payload["consignor"] == "BELL MARINE"
    assert payload["weight"] == "17.85"


def test_parse_llm_fields_keeps_schema():
    parsed = parse_llm_fields({
        "bill_number": "CP-9",
        "extra": "ignore",
        "line_items": [{"description": "acero", "amount": "10"}],
    })
    assert parsed["bill_number"] == "CP-9"
    assert parsed["consignor"] == ""
    assert parsed["line_items"][0]["description"] == "acero"
    assert "extra" not in parsed


def test_apply_llm_prefers_groq_then_regex():
    base = {"bill_number": "HB-REGEX", "consignor": "Acme"}
    llm = {"bill_number": "HB-LLM", "consignor": "", "destination": "Dallas"}
    merged = apply_llm_fields(base, llm)
    assert merged["bill_number"] == "HB-LLM"
    assert merged["consignor"] == "Acme"
    assert merged["destination"] == "Dallas"


def test_apply_llm_ignores_placeholder_values():
    base = {"freight_amount": "564.90", "driver_name": "Mike Donovan"}
    llm = {"freight_amount": "N/A", "driver_name": "unknown", "vehicle_number": "197"}
    merged = apply_llm_fields(base, llm)
    assert merged["freight_amount"] == "564.90"
    assert merged["driver_name"] == "Mike Donovan"
    assert merged["vehicle_number"] == "197"


def test_apply_llm_skips_ocr_junk_and_duplicate_parties():
    base = {"consignor": "Bell Marine", "consignee": ""}
    llm = {"consignor": "BElIm Ae ME", "consignee": "Bell Marine", "commodity_description": "Qee"}
    merged = apply_llm_fields(base, llm)
    assert merged["consignor"] == "Bell Marine"
    assert merged.get("consignee") != "Bell Marine" or merged.get("consignee") in (None, "")
    assert merged.get("commodity_description") in (None, "", [])


def test_apply_llm_skips_form_header_labels():
    base = {"origin": "123 Vernalis Rd", "consignor": "Granite Vernalis"}
    llm = {"origin": "ADDRESS", "consignor": "SHIPPER", "destination": "Tracy, CA"}
    merged = apply_llm_fields(base, llm)
    assert merged["origin"] == "123 Vernalis Rd"
    assert merged["consignor"] == "Granite Vernalis"
    assert merged["destination"] == "Tracy, CA"


def test_spanish_factura_de_flete_does_not_steal_invoice():
    text = (
        "FACTURA DE FLETE / CONOCIMIENTO DE EMBARQUE\n"
        "N.º de factura: FB-10247\n"
        "Transportista: Midwest Hauling LLC\n"
        "Fecha: 25/08/26\n"
        "Número de factura: INV-30931\n"
        "Remitente: Acme Steel Corp\n"
        "Destinatario: Costco Wholesale #221\n"
        "Origen: Chicago, IL\n"
        "Destino: Indianapolis, IN\n"
    )
    fields = extract_fields_from_raw_text(text)
    assert fields.get("bill_number") == "FB-10247"
    assert fields.get("invoice_number") == "INV-30931"
    assert fields.get("invoice_number") != "DE"
    assert "Acme" in (fields.get("consignor") or "")
    assert "Midwest" in (fields.get("carrier") or "")


def test_spanish_multiline_amounts_and_logistics_fields():
    text = """
FACTURA DE FLETE / CONOCIMIENTO DE EMBARQUE
N.º de factura:
FB-10247
Número de factura:
INV-30931
Cantidad:
49
Peso (lb):
24,126
Importe del flete ($):
564.90
Importe total ($):
610.35
Número de vehículo:
#197
Nombre del conductor:
Mike Donovan
Hora de recogida:
7:10 a. m.
Hora de entrega:
5:20 p. m.
Instrucciones especiales:
Se requiere plataforma elevadora
Firma del conductor:
MUESTRA / NO VALIDA
Firma del destinatario
(prueba de entrega):
MUESTRA / NO VALIDA
Fecha/hora de
recepción:
28/08/26 10:40 a. m.
"""
    fields = extract_fields_from_raw_text(text)
    assert fields.get("bill_number") == "FB-10247"
    assert fields.get("invoice_number") == "INV-30931"
    assert fields.get("quantity") == "49"
    assert fields.get("weight") == "24,126"
    assert "564.90" in (fields.get("freight_amount") or "")
    assert "610.35" in (fields.get("total_amount") or "")
    assert fields.get("vehicle_number") == "197"
    assert "Mike Donovan" in (fields.get("driver_name") or "")
    assert "7:10" in (fields.get("pickup_time") or "")
    assert "5:20" in (fields.get("delivery_time") or "")
    assert "plataforma" in (fields.get("special_instructions") or "").lower()
    assert fields.get("received_datetime")
    assert "MUESTRA" in (fields.get("driver_signature") or "")
    assert "MUESTRA" in (fields.get("consignee_signature") or "")

    text = (
        "Carta de porte: CP-4412\n"
        "Remitente: Acme Logistica\n"
        "Destinatario: Beta SA\n"
        "Origen: Houston\n"
        "Destino: Dallas\n"
        "Importe total: $120.00\n"
    )
    fields = extract_fields_from_raw_text(text)
    assert fields.get("bill_number") == "CP-4412"
    assert "Acme" in (fields.get("consignor") or "")
    assert "Beta" in (fields.get("consignee") or "")
    assert "Houston" in (fields.get("origin") or "")
    assert "Dallas" in (fields.get("destination") or "")
    assert "120" in (fields.get("total_amount") or "")


def test_hindi_devanagari_bill_and_invoice_ids():
    text = (
        "FREIGHT BILL / BILL OF LADING\n"
        "Bill No.: एफबी-१०२३६\n"
        "Invoice Number: आईएनवी-६२१\n"
        "Carrier: प्रेयरी स्टेट ट्रकिंग\n"
    )
    fields = extract_fields_from_raw_text(text)
    assert fields.get("bill_number") == "एफबी-१०२३६"
    assert fields.get("invoice_number") == "आईएनवी-६२१"


def test_translate_fields_for_display_converts_digits_without_saving():
    result = translate_fields_for_display({
        "quantity": "३६",
        "weight": "४३,२९०",
        "carrier": "प्रेयरी स्टेट ट्रकिंग",
        "bill_number": "FB-10236",
        "total_amount": "$989.95",
    })
    assert result["translations"]["quantity"] == "36"
    assert result["translations"]["weight"] == "43,290"
    assert "bill_number" not in result["translations"]
    assert "total_amount" not in result["translations"]
    assert "carrier" not in result["translations"]


def test_looks_like_permit_number():
    from app.ocr.groq_extractor import looks_like_permit_number

    assert looks_like_permit_number("CA0385520") is True
    assert looks_like_permit_number("CA 0385520") is True
    assert looks_like_permit_number("INV-30931") is False


def test_encode_images_for_groq_vision_makes_jpeg_data_url():
    from PIL import Image
    from app.ocr.groq_extractor import encode_images_for_groq_vision

    img = Image.new("RGB", (2200, 1600), "white")
    urls = encode_images_for_groq_vision([img], max_pages=1, max_edge=800)
    assert len(urls) == 1
    assert urls[0].startswith("data:image/jpeg;base64,")
    assert len(urls[0]) < 200_000


def test_apply_vision_fields_reads_handwriting_and_drops_permit_invoice():
    from app.ocr.groq_extractor import apply_vision_fields

    base = {
        "consignor": "CALIFORNIA MATERIALS, INC.",
        "consignee": "",
        "carrier": "AGGREGATES•TRUCKING",
        "invoice_number": "CA0385520",
        "origin": "MARINE",
        "destination": "",
    }
    vision = {
        "consignor": "BELL MARINE",
        "consignee": "CORONE & CO",
        "carrier": "CALIFORNIA MATERIALS, INC.",
        "invoice_number": "",
        "origin": "",
        "destination": "CANNON LANDFILL",
        "bill_number": "16766-1",
        "pickup_time": "9:30",
        "weight": "12.85",
        "line_items": [{"tag": "4124", "weight": "12.85", "load_arrive": "9:30", "load_depart": "10:20"}],
    }
    merged = apply_vision_fields(base, vision)
    assert merged["consignor"] == "BELL MARINE"
    assert merged["consignee"] == "CORONE & CO"
    assert merged["carrier"] == "CALIFORNIA MATERIALS, INC."
    assert merged.get("invoice_number") in (None, "")
    assert merged["destination"] == "CANNON LANDFILL"
    assert merged.get("origin") in (None, "")
    assert merged["bill_number"] == "16766-1"
    assert merged["line_items"][0]["tag"] == "4124"


def test_extract_fields_with_groq_vision_sends_image_url(monkeypatch):
    from PIL import Image
    from app.ocr import groq_extractor as ge

    monkeypatch.setattr(ge.settings, "TESTING", False)
    monkeypatch.setattr(ge.settings, "ENABLE_GROQ", True)
    monkeypatch.setattr(ge.settings, "ENABLE_GROQ_VISION", True)
    monkeypatch.setattr(ge.settings, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(ge.settings, "GROQ_VISION_MODEL", "qwen/qwen3.6-27b")

    captured = {}

    def fake_parse(messages, model, timeout=90.0, vision=False):
        captured["messages"] = messages
        captured["model"] = model
        captured["vision"] = vision
        return {"consignor": "BELL MARINE", "consignee": "CORONE & CO", "bill_number": "16766-1"}

    monkeypatch.setattr(ge, "_groq_chat_parse", fake_parse)
    img = Image.new("RGB", (100, 80), "white")
    fields = ge.extract_fields_with_groq_vision([img])
    assert fields["consignor"] == "BELL MARINE"
    assert fields["consignee"] == "CORONE & CO"
    user = captured["messages"][1]["content"]
    assert user[0]["type"] == "text"
    assert user[1]["type"] == "image_url"
    assert user[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert captured["model"] == "qwen/qwen3.6-27b"
    assert captured["vision"] is True
