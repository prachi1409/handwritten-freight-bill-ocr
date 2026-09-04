"""Unit test suite verifying carrier, delivery time, fuel/handling charges, weight, location, and status logic."""

import pytest
from app.db.models import DocumentStatus
from app.ocr.field_extractor import extract_fields_from_raw_text
from app.ocr.normalizer import (
    normalize_currency,
    normalize_freight_data,
    normalize_location,
    normalize_weight,
    validate_extraction_data,
)


def test_mashed_scale_ticket_row_splits_weight_and_times():
    """Glued scale rows should not keep clock times inside weight."""
    assert normalize_weight("27.0215:20 5:27") == "27.02"
    text = """
    CALIFORNIA MATERIALS
    Shipper
    Granite Vernalis
    Consignee
    A&A Concrete
    Point of Origin
    ADDRESS
    123 Vernalis Rd
    Point of Destination
    STREET AND CITY
    Tracy, CA
    SUB-HAUL#
    1 x 4 Rock 884120 27.02 5:20 5:27
    """
    fields = extract_fields_from_raw_text(text)
    assert "Granite" in (fields.get("consignor") or "")
    assert "A&A" in (fields.get("consignee") or "")
    origin = fields.get("origin") or ""
    assert "ADDRESS" not in origin.upper()
    assert "Vernalis" in origin
    dest = fields.get("destination") or ""
    assert "POINT OF DESTINATION" not in dest.upper()
    assert "Tracy" in dest
    assert fields.get("weight") == "27.02"
    assert "1 x 4 Rock" in (fields.get("commodity_description") or "")
    assert fields.get("pickup_time") == "5:20"
    assert fields.get("delivery_time") == "5:27"

    norm = normalize_freight_data(fields, raw_text=text, base_confidence=0.50)
    assert "Granite" in (norm.get("consignor") or "")
    assert norm.get("origin") and "ADDRESS" not in str(norm.get("origin")).upper()
    assert "Vernalis" in (norm.get("origin") or "")
    assert norm.get("weight") == "27.02"
    assert norm.get("bill_date") is None
    assert (norm.get("field_confidence") or {}).get("bill_date", 0) == 0.0


def test_glued_rapidocr_scale_ticket_layout():
    """RapidOCR often concatenates labels; still recover shipper, route, weight, times."""
    from app.ocr.field_extractor import pick_extracted_value

    text = """
CALIFORNIAMATERIALS,INC.
CMAT
No. 16740-1
SHIPPER
GraniteVernalis
CONSIGNEE
BILLTO
AAConcrete
ADDRESS
POINTOFORIGIN
POINTOFDESTINATION(Street&City)
DATE
SBird Bd Tray
WLinne
Bd
Tay
YR.26
MO. 2
DAY 2
LOADING
x4bocK4457600q
27.0215:20 5:27
"""
    fields = extract_fields_from_raw_text(text)
    assert "Granite" in (fields.get("consignor") or "")
    assert "AAConcrete" in (fields.get("consignee") or "")
    assert "MATERIALS" in (fields.get("carrier") or "").upper()
    assert "Bird" in (fields.get("origin") or "")
    assert "WLinne" in (fields.get("destination") or "")
    assert "Bd" in (fields.get("destination") or "") or "Rd" in (fields.get("destination") or "")
    assert fields.get("weight") == "27.02"
    assert fields.get("pickup_time") == "5:20"
    assert fields.get("delivery_time") == "5:27"
    assert fields.get("bill_number") == "16740-1"
    assert fields.get("quantity") == "1"
    assert "Rock" in (fields.get("commodity_description") or "")
    assert "445760" not in (fields.get("commodity_description") or "")
    assert pick_extracted_value("consignor", "CMa+", "GraniteVernalis") == "GraniteVernalis"
    assert pick_extracted_value("origin", "POINTOFDESTINATION(Street&City)", "SBird Bd Tray") == "SBird Bd Tray"
    assert pick_extracted_value("destination", "WLinne", "WLinne Bd Tay") == "WLinne Bd Tay"


def test_compact_times_and_duplicate_party_junk():
    from app.ocr.field_extractor import extract_fields_from_raw_text
    from app.ocr.normalizer import looks_like_ocr_junk, normalize_clock_time, normalize_freight_data

    assert normalize_clock_time("930") == "9:30"
    assert normalize_clock_time("1020") == "10:20"
    assert looks_like_ocr_junk("Qee") is True
    assert looks_like_ocr_junk("RN Alo YRZ") is True
    assert looks_like_ocr_junk("BElIm Ae ME") is True
    assert looks_like_ocr_junk("Sharma Industrial Supply") is False
    assert looks_like_ocr_junk("A&A Concrete") is False

    text = """
    CALIFORNIAMATERIALS,INC.
    No. 16766-1
    SHIPPER
    BELL MARINE
    CONSIGNEE
    BELL MARINE
    WEIGHT
    12.85 930 1020 1025 1030
    """
    fields = extract_fields_from_raw_text(text)
    assert fields.get("bill_number") == "16766-1"
    assert fields.get("invoice_number") in (None, "")
    assert fields.get("pickup_time") == "9:30"
    assert fields.get("delivery_time") == "10:30"
    assert fields.get("weight") == "12.85"
    items = fields.get("line_items") or []
    assert items
    assert items[0].get("unload_depart") == "10:30"

    norm = normalize_freight_data({
        "consignor": "BElIm Ae ME",
        "consignee": "BElIm Ae ME",
        "origin": "RN Alo YRZ",
        "commodity_description": "Qee",
        "bill_number": "16766-1",
        "pickup_time": "930",
        "delivery_time": "1030",
    }, raw_text=text)
    assert norm.get("consignor") is None
    assert norm.get("consignee") is None
    assert norm.get("origin") is None
    assert norm.get("commodity_description") is None
    assert norm.get("pickup_time") == "9:30"
    assert norm.get("delivery_time") == "10:30"

    footer = """
SIGNATURE
DRIVER
PAYROLL#
CONSIGNEE
SamveI M
HOURS
639
"""
    footer_fields = extract_fields_from_raw_text(footer)
    assert "Samve" in (footer_fields.get("driver_name") or "")
    assert "Samve" in (footer_fields.get("driver_signature") or "")

    norm = normalize_freight_data(fields, raw_text=text)
    assert "BELL" in (norm.get("consignor") or "").upper()
    assert " " in (norm.get("consignor") or "")
    assert norm.get("consignee") in (None, "")
    assert "MATERIALS" in (norm.get("carrier") or "").upper()
    assert "," in (norm.get("carrier") or "")
    assert norm.get("weight") == "12.85"
    assert norm.get("pickup_time") == "9:30"
    assert norm.get("delivery_time") == "10:30"
    assert norm.get("bill_number") == "16766-1"


def test_carrier_banner_header_exclusion():
    """Verify carrier extraction ignores form banner titles like FREIGHT MANIFEST & BILL OF LADING."""
    text = """
    FREIGHT MANIFEST & BILL OF LADING
    CARRIER: Summit Line Haul LLC
    CONSIGNOR: Westfield Components
    """
    fields = extract_fields_from_raw_text(text)
    assert fields.get("carrier") == "Summit Line Haul LLC"
    assert "MANIFEST" not in fields.get("carrier", "")


def test_paired_pickup_delivery_time_extraction():
    """Verify time pairs like 08:15 AM / 03:45 PM extract into pickup_time and delivery_time."""
    text = """
    Bill No: FB-10238
    Pickup / Delivery Time: 08:15 AM / 03:45 PM
    Freight Amount: $1,485.60
    """
    fields = extract_fields_from_raw_text(text)
    assert fields.get("pickup_time") == "08:15 AM"
    assert fields.get("delivery_time") == "03:45 PM"


def test_fuel_and_handling_charge_extraction():
    """Verify fuel surcharge and handling charge extractions from text."""
    text = """
    Freight Amount: $1,276.40
    Fuel Surcharge: $102.11
    Handling Charge: $38.50
    Total Amount: $1,417.01
    """
    fields = extract_fields_from_raw_text(text)
    assert fields.get("fuel_surcharge") == "$102.11"
    assert fields.get("handling_charge") == "$38.50"


def test_weight_unit_normalization():
    """Verify weight unit OCR noise is normalized to standard 'lbs' format."""
    assert normalize_weight("32,450los") == "32,450 lbs"
    assert normalize_weight("14.920lbs") == "14,920 lbs"
    assert normalize_weight("18,760 Ibs") == "18,760 lbs"
    assert normalize_weight("22,100 LBS") == "22,100 lbs"


def test_location_spacing_normalization():
    """Verify city/state spacing and capitalization normalization."""
    assert normalize_location("Columbus,OH") == "Columbus, OH"
    assert normalize_location("Dallas,Tx") == "Dallas, Tx"
    assert normalize_location("Chicago,IL") == "Chicago, IL"


def test_strict_status_logic_flags_missing_critical_fields():
    """Verify DocumentStatus.REVIEW is assigned if critical fields are missing."""
    incomplete_data = {
        "bill_number": "FB-10238",
        "consignor": "Acme Corp",
        # Missing consignee and total_amount
    }
    status, warnings, conf = validate_extraction_data(incomplete_data)
    assert status == DocumentStatus.REVIEW
    assert any("Missing critical field" in w for w in warnings)


def test_strict_status_logic_completes_when_valid():
    """Verify DocumentStatus.COMPLETED is assigned when all required critical fields exist."""
    valid_data = {
        "bill_number": "FB-10238",
        "invoice_number": "INV-10238",
        "consignor": "Acme Steel Corp",
        "consignee": "Costco Wholesale",
        "origin": "Chicago, IL",
        "destination": "Memphis, TN",
        "freight_amount": "$848.89",
        "total_amount": "$916.80",
        "field_confidence": {
            "bill_number": 0.95,
            "invoice_number": 0.95,
            "consignor": 0.90,
            "consignee": 0.90,
            "origin": 0.90,
            "destination": 0.90,
            "freight_amount": 0.95,
            "total_amount": 0.95
        }
    }
    status, warnings, conf = validate_extraction_data(valid_data)
    assert status == DocumentStatus.COMPLETED
    assert len(warnings) == 0


def test_scale_ticket_column_headers_are_not_field_values():
    """Printed MILES / HOURS / AB must not become vehicle, driver, or remarks."""
    text = """
    TRUCK NO
    90
    MILES
    DRIVER
    ISAAC CORDERO
    MHOURS
    WEIGHT
    17.85
    SPECIAL INSTRUCTIONS
    AB
    """
    fields = extract_fields_from_raw_text(text)
    assert fields.get("vehicle_number") != "MILES"
    assert "90" in str(fields.get("vehicle_number") or "")
    assert "ISAAC" in (fields.get("driver_name") or "").upper()
    assert "HOUR" not in (fields.get("driver_name") or "").upper()
    assert fields.get("special_instructions") not in ("AB", "Ab")
    assert fields.get("weight") == "17.85"

    from app.ocr.normalizer import normalize_freight_data
    norm = normalize_freight_data({
        "vehicle_number": "MILES",
        "driver_name": "MHOURS",
        "special_instructions": "AB",
        "weight": "17.85",
    })
    assert norm.get("vehicle_number") is None
    assert norm.get("driver_name") is None
    assert norm.get("special_instructions") is None
    assert norm.get("weight") == "17.85"
