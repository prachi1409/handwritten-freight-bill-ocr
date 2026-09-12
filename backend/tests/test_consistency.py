"""Point 5 bill-level consistency/anomaly checks."""

from app.db.models import DocumentStatus
from app.ocr.consistency import (
    CODE_CONSIGNOR_EQUALS_CONSIGNEE,
    CODE_DESTINATION_COPIED_FROM_ORIGIN,
    CODE_FREIGHT_EXCEEDS_TOTAL,
    CODE_HISTORICAL_CONFLICT,
    CODE_LINE_ITEM_ARITHMETIC,
    CODE_LINE_ITEM_SUM_MISMATCH,
    CODE_NEGATIVE_VALUE,
    attach_consistency_checks,
    check_bill_consistency,
)
from app.ocr.normalizer import validate_extraction_status
from app.ocr.priors import empty_priors, observe_reviewed_ticket


def _codes(payload):
    return [row["code"] for row in payload.get("checks") or []]


def test_consignor_equals_consignee_is_flagged():
    payload = check_bill_consistency(
        {"consignor": "Clean Planet", "consignee": "clean planet"},
        priors=empty_priors(),
    )
    assert CODE_CONSIGNOR_EQUALS_CONSIGNEE in _codes(payload)
    assert payload["checks"][0]["severity"] == "error"


def test_different_parties_do_not_trigger_equality():
    payload = check_bill_consistency(
        {"consignor": "Clean Planet", "consignee": "Aquamarine Contractors Inc."},
        priors=empty_priors(),
    )
    assert CODE_CONSIGNOR_EQUALS_CONSIGNEE not in _codes(payload)


def test_destination_copied_from_origin_is_flagged():
    payload = check_bill_consistency(
        {"origin": "North Hooper", "destination": "Stockton"},
        priors=empty_priors(),
    )
    assert CODE_DESTINATION_COPIED_FROM_ORIGIN in _codes(payload)
    ok = check_bill_consistency(
        {"origin": "North Hooper", "destination": "Discovery Bay"},
        priors=empty_priors(),
    )
    assert CODE_DESTINATION_COPIED_FROM_ORIGIN not in _codes(ok)


def test_freight_exceeds_total_is_detected():
    payload = check_bill_consistency(
        {"freight_amount": "$1,200.00", "total_amount": "$950.00"},
        priors=empty_priors(),
    )
    assert CODE_FREIGHT_EXCEEDS_TOTAL in _codes(payload)
    row = next(item for item in payload["checks"] if item["code"] == CODE_FREIGHT_EXCEEDS_TOTAL)
    assert row["severity"] == "error"
    assert row["observed_values"]["freight_amount"] == 1200.0


def test_freight_at_or_below_total_is_ok():
    equal = check_bill_consistency(
        {"freight_amount": "$950.00", "total_amount": "$950.00"},
        priors=empty_priors(),
    )
    under = check_bill_consistency(
        {"freight_amount": "$900.00", "total_amount": "$950.00"},
        priors=empty_priors(),
    )
    assert CODE_FREIGHT_EXCEEDS_TOTAL not in _codes(equal)
    assert CODE_FREIGHT_EXCEEDS_TOTAL not in _codes(under)


def test_missing_or_unparseable_money_does_not_trigger():
    missing = check_bill_consistency({"freight_amount": "$100.00"}, priors=empty_priors())
    junk = check_bill_consistency(
        {"freight_amount": "not-a-price", "total_amount": "also-bad"},
        priors=empty_priors(),
    )
    empty = check_bill_consistency({}, priors=empty_priors())
    assert CODE_FREIGHT_EXCEEDS_TOTAL not in _codes(missing)
    assert CODE_FREIGHT_EXCEEDS_TOTAL not in _codes(junk)
    assert empty["checks"] == []


def test_negative_impossible_values_are_detected():
    payload = check_bill_consistency(
        {
            "weight": "-12.5",
            "freight_amount": "$-40.00",
            "line_items": [{"quantity": "-2", "rate": "$10.00", "amount": "$20.00"}],
        },
        priors=empty_priors(),
    )
    negatives = [row for row in payload["checks"] if row["code"] == CODE_NEGATIVE_VALUE]
    fields = {row["fields_involved"][0] for row in negatives}
    assert "weight" in fields
    assert "freight_amount" in fields
    assert any(row["observed_values"].get("quantity") == -2.0 for row in negatives)


def test_legitimate_zero_values_are_not_flagged():
    payload = check_bill_consistency(
        {
            "fuel_surcharge": "$0.00",
            "handling_charge": "$0.00",
            "quantity": "0",
            "weight": "0",
            "freight_amount": "$10.00",
            "total_amount": "$10.00",
        },
        priors=empty_priors(),
    )
    assert CODE_NEGATIVE_VALUE not in _codes(payload)
    assert CODE_FREIGHT_EXCEEDS_TOTAL not in _codes(payload)


def test_line_item_sum_mismatch_is_detected():
    payload = check_bill_consistency(
        {
            "total_amount": "$3,450.00",
            "line_items": [
                {"amount": "$4,000.00"},
                {"amount": "$2,000.00"},
            ],
        },
        priors=empty_priors(),
    )
    assert CODE_LINE_ITEM_SUM_MISMATCH in _codes(payload)


def test_line_item_arithmetic_within_tolerance_is_accepted():
    payload = check_bill_consistency(
        {
            "total_amount": "$20.02",
            "line_items": [{"quantity": "2", "rate": "$10.00", "amount": "$20.02"}],
        },
        priors=empty_priors(),
    )
    assert CODE_LINE_ITEM_ARITHMETIC not in _codes(payload)
    assert CODE_LINE_ITEM_SUM_MISMATCH not in _codes(payload)


def test_line_item_qty_rate_mismatch_is_detected():
    payload = check_bill_consistency(
        {"line_items": [{"quantity": "2", "rate": "$10.00", "amount": "$50.00"}]},
        priors=empty_priors(),
    )
    assert CODE_LINE_ITEM_ARITHMETIC in _codes(payload)
    assert next(row for row in payload["checks"] if row["code"] == CODE_LINE_ITEM_ARITHMETIC)["severity"] == "warning"


def _strong_route_priors():
    priors = empty_priors()
    gold = {
        "consignor": "Clean Planet Hooper",
        "consignee": "Aquamarine Contractors Inc.",
        "carrier": "CALIFORNIA MATERIALS, INC.",
        "driver_name": "Gerald Valentin",
        "origin": "North Hooper St, Stockton, CA",
        "destination": "Discovery Bay, CA",
    }
    for index in range(3):
        observe_reviewed_ticket(gold, document_id=f"gold-{index}", priors=priors)
    return priors


def test_historical_carrier_conflict_warns_when_prior_is_strong():
    extracted = {
        "consignor": "Clean Planet Hooper",
        "consignee": "Aquamarine Contractors Inc.",
        "carrier": "ACME FREIGHT, INC.",
    }
    payload = check_bill_consistency(extracted, priors=_strong_route_priors())
    assert CODE_HISTORICAL_CONFLICT in _codes(payload)
    row = next(item for item in payload["checks"] if item["code"] == CODE_HISTORICAL_CONFLICT)
    assert row["severity"] == "warning"
    assert row["evidence"]["usual_value"] == "CALIFORNIA MATERIALS, INC."
    assert extracted["carrier"] == "ACME FREIGHT, INC."


def test_no_historical_evidence_does_not_warn():
    payload = check_bill_consistency(
        {
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "carrier": "ACME FREIGHT, INC.",
        },
        priors=empty_priors(),
    )
    assert CODE_HISTORICAL_CONFLICT not in _codes(payload)


def test_sparse_historical_counts_do_not_warn():
    priors = empty_priors()
    observe_reviewed_ticket(
        {
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "carrier": "CALIFORNIA MATERIALS, INC.",
        },
        document_id="once",
        priors=priors,
    )
    payload = check_bill_consistency(
        {
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "carrier": "ACME FREIGHT, INC.",
        },
        priors=priors,
    )
    assert CODE_HISTORICAL_CONFLICT not in _codes(payload)


def test_historical_conflict_never_overwrites_extracted_carrier():
    extracted = {
        "consignor": "Clean Planet Hooper",
        "consignee": "Aquamarine Contractors Inc.",
        "carrier": "ACME FREIGHT, INC.",
    }
    raw_ocr: dict = {}
    attach_consistency_checks(extracted, raw_ocr, priors=_strong_route_priors())
    assert extracted["carrier"] == "ACME FREIGHT, INC."
    assert "CALIFORNIA MATERIALS, INC." != extracted["carrier"]
    assert raw_ocr["consistency_checks"]["checks"]


def test_prior_only_entity_is_not_introduced():
    extracted = {
        "consignor": "Clean Planet Hooper",
        "consignee": "Aquamarine Contractors Inc.",
        "carrier": "ACME FREIGHT, INC.",
    }
    check_bill_consistency(extracted, priors=_strong_route_priors())
    assert extracted.get("carrier") == "ACME FREIGHT, INC."
    assert "Ghost Hauling LLC" not in str(extracted)
    assert extracted.get("driver_name") is None


def test_existing_validation_behavior_remains_intact():
    complete = {
        "bill_number": "HB-78421",
        "invoice_number": "INV-HB-78421",
        "consignor": "Sharma Industrial Supply",
        "consignee": "Metro Warehouse",
        "origin": "Kanpur",
        "destination": "Delhi",
        "freight_amount": "$3,450.00",
        "total_amount": "$3,450.00",
    }
    status, warnings = validate_extraction_status(complete, confidence=0.90)
    assert status == DocumentStatus.COMPLETED
    assert warnings == []

    mismatch = dict(complete)
    mismatch["line_items"] = [
        {"item_no": "1", "description": "Steel", "amount": "$4,000.00"},
        {"item_no": "2", "description": "Pipes", "amount": "$2,000.00"},
    ]
    status, warnings = validate_extraction_status(mismatch, confidence=0.90)
    assert status == DocumentStatus.REVIEW
    assert any("Line item sum" in item for item in warnings)


def test_origin_destination_same_state_is_ok():
    from app.ocr.consistency import CODE_ORIGIN_DEST_STATE_MISMATCH

    payload = check_bill_consistency(
        {"origin": "Stockton, CA 95213", "destination": "Discovery Bay, CA"},
        priors=empty_priors(),
    )
    assert CODE_ORIGIN_DEST_STATE_MISMATCH not in _codes(payload)


def test_origin_destination_state_mismatch_is_flagged():
    from app.ocr.consistency import CODE_ORIGIN_DEST_STATE_MISMATCH

    payload = check_bill_consistency(
        {"origin": "Stockton, CA 95213", "destination": "Dallas, TX"},
        priors=empty_priors(),
    )
    assert CODE_ORIGIN_DEST_STATE_MISMATCH in _codes(payload)
    row = next(item for item in payload["checks"] if item["code"] == CODE_ORIGIN_DEST_STATE_MISMATCH)
    assert row["severity"] == "warning"


def test_duplicate_tags_on_same_bill_are_flagged():
    from app.ocr.consistency import CODE_DUPLICATE_TAG

    payload = check_bill_consistency(
        {
            "line_items": [
                {"tag": "684755", "weight": "18.30"},
                {"tag": "684755", "weight": "19.99"},
            ]
        },
        priors=empty_priors(),
    )
    assert CODE_DUPLICATE_TAG in _codes(payload)


def test_duplicate_tag_date_across_customer_is_flagged():
    from app.ocr.consistency import CODE_DUPLICATE_TAG_DATE

    payload = check_bill_consistency(
        {
            "consignee": "Aquamarine",
            "bill_date": "2025-04-30",
            "line_items": [{"tag": "684755"}],
        },
        priors=empty_priors(),
        peer_tickets=[
            {
                "document_id": "peer-1",
                "consignee": "Aquamarine",
                "bill_date": "2025-04-30",
                "tags": ["684755"],
            }
        ],
    )
    assert CODE_DUPLICATE_TAG_DATE in _codes(payload)


def test_new_consistency_flags_do_not_rewrite_fields():
    extracted = {
        "origin": "Stockton, CA 95213",
        "destination": "Dallas, TX",
        "vehicle_number": "22",
        "commodity_description": "Import Fill",
        "line_items": [{"tag": "1"}, {"tag": "1"}],
    }
    attach_consistency_checks(extracted, priors=empty_priors())
    assert extracted["vehicle_number"] == "22"
    assert extracted["commodity_description"] == "Import Fill"
    assert extracted["origin"] == "Stockton, CA 95213"
