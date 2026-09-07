"""Historical entity/route co-occurrence priors from reviewed tickets."""

from app.ocr.priors import (
    carriers_for,
    destinations_for,
    drivers_for,
    empty_priors,
    likely_entities,
    observe_reviewed_ticket,
    rebuild_priors_from_records,
)


TICKET_A = {
    "carrier": "CALIFORNIA MATERIALS, INC.",
    "consignor": "Clean Planet Hooper",
    "consignee": "Aquamarine Contractors Inc.",
    "driver_name": "Gerald Valentin",
    "origin": "North Hooper St, Stockton, CA",
    "destination": "Discovery Bay, CA",
}
TICKET_B = {
    "carrier": "CALIFORNIA MATERIALS, INC.",
    "consignor": "Clean Planet Hooper",
    "consignee": "Aquamarine Contractors Inc.",
    "driver_name": "Isaac Cordero",
    "origin": "North Hooper St, Stockton, CA",
    "destination": "Discovery Bay, CA",
}
TICKET_C = {
    "carrier": "CALIFORNIA MATERIALS, INC.",
    "consignor": "Bell Marine",
    "consignee": "CORONE & CO",
    "driver_name": "Mike Gordon",
    "origin": "Vernalis, CA",
    "destination": "Tracy, CA",
}


def test_reviewed_tickets_count_consignor_consignee_pairs():
    priors = rebuild_priors_from_records([TICKET_A, TICKET_B, TICKET_C])
    pair = priors["pairs"]["consignor→consignee"]
    aqua = [slot for slot in pair.values() if slot["right"] == "Aquamarine Contractors Inc."]
    assert len(aqua) == 1
    assert aqua[0]["count"] == 2
    assert aqua[0]["left"] == "Clean Planet Hooper"
    corone = [slot for slot in pair.values() if slot["right"] == "CORONE & CO"]
    assert corone[0]["count"] == 1


def test_rebuild_ignores_unreviewed_style_junk_when_not_passed():
    priors = rebuild_priors_from_records([TICKET_A])
    assert "Aquamatrix" not in str(priors)
    assert len(priors["tickets"]) == 1


def test_payroll_digits_are_not_stored_as_driver_priors():
    priors = rebuild_priors_from_records([
        {**TICKET_A, "driver_name": "207855"},
    ])
    assert priors["unigrams"]["driver_name"] == {}
    assert priors["pairs"]["carrier→driver"] == {}


def test_same_document_id_does_not_double_count():
    priors = empty_priors()
    observe_reviewed_ticket(TICKET_A, document_id="doc-1", priors=priors)
    observe_reviewed_ticket(TICKET_A, document_id="doc-1", priors=priors)
    assert len(priors["tickets"]) == 1
    aqua = list(priors["pairs"]["consignor→consignee"].values())[0]
    assert aqua["count"] == 1


def test_carriers_for_consignor_and_consignee():
    priors = rebuild_priors_from_records([TICKET_A, TICKET_C])
    ranked = carriers_for("Clean Planet Hooper", "Aquamarine Contractors Inc.", priors=priors)
    assert ranked
    assert ranked[0][0] == "CALIFORNIA MATERIALS, INC."
    assert ranked[0][1] == 1
    assert ranked[0][2] == 1.0


def test_drivers_for_consignor_and_carrier():
    priors = rebuild_priors_from_records([TICKET_A, TICKET_B])
    ranked = drivers_for("Clean Planet Hooper", "CALIFORNIA MATERIALS, INC.", priors=priors)
    names = {name for name, _count, _prob in ranked}
    assert names == {"Gerald Valentin", "Isaac Cordero"}
    assert all(count == 1 for _name, count, _prob in ranked)


def test_destinations_for_origin():
    priors = rebuild_priors_from_records([TICKET_A, TICKET_B, TICKET_C])
    ranked = destinations_for("North Hooper St, Stockton, CA", priors=priors)
    assert ranked[0][0] == "Discovery Bay, CA"
    assert ranked[0][1] == 2


def test_likely_entities_from_partial_fields():
    priors = rebuild_priors_from_records([TICKET_A, TICKET_B, TICKET_C])
    likely = likely_entities(
        {
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "carrier": "CALIFORNIA MATERIALS, INC.",
            "origin": "North Hooper St, Stockton, CA",
        },
        priors=priors,
    )
    assert likely["carrier"][0][0] == "CALIFORNIA MATERIALS, INC."
    assert likely["destination"][0][0] == "Discovery Bay, CA"
    driver_names = {name for name, _c, _p in likely["driver_name"]}
    assert "Gerald Valentin" in driver_names
    assert "Mike Gordon" not in driver_names


def test_gazetteer_matching_is_unchanged():
    from app.ocr.matching import apply_entity_matching

    out = apply_entity_matching({"consignor": "CleanPlanet", "driver_name": "207855"})
    assert out["consignor"] == "Clean Planet"
    assert out["driver_name"] == "207855"
