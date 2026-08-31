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
