"""Top-K candidate generation alongside unchanged 1-best gazetteer matching."""

from app.ocr.candidates import generate_field_candidates
from app.ocr.matching import apply_entity_matching, _empty_memory
from app.ocr.priors import empty_priors, observe_reviewed_ticket


GAZ = {
    "carrier": ["CALIFORNIA MATERIALS, INC.", "ACME FREIGHT, INC."],
    "consignor": ["Clean Planet", "Clean Planet Hooper", "Bell Marine"],
    "consignee": ["Aquamarine", "Aquamarine Contractors Inc.", "A&A Concrete"],
    "driver_name": ["Gerald Valentin", "Isaac Cordero", "Mike Gordon"],
    "origin": ["North Hooper St, Stockton, CA", "Vernalis, CA"],
    "destination": ["Discovery Bay, CA", "Tracy, CA"],
}


def _memory():
    mem = _empty_memory()
    mem["names"] = {k: list(v) for k, v in GAZ.items()}
    mem["aliases"] = {k: {} for k in GAZ}
    mem["aliases"]["consignee"]["aquamatrix"] = "Aquamarine Contractors Inc."
    return mem


def _values(rows):
    return [row["value"] for row in rows]


def test_exact_gazetteer_candidate():
    rows = generate_field_candidates(
        {"consignor": "Clean Planet"},
        gazetteer=GAZ,
        memory=_memory(),
        priors=empty_priors(),
    )["consignor"]
    assert rows
    assert rows[0]["value"] == "Clean Planet"
    assert rows[0]["fuzzy_score"] == 1.0
    assert "gazetteer" in rows[0]["sources"] or "ocr" in rows[0]["sources"]


def test_fuzzy_near_match_candidate():
    rows = generate_field_candidates(
        {"consignor": "CleanPlanet"},
        gazetteer=GAZ,
        memory=_memory(),
        priors=empty_priors(),
    )["consignor"]
    assert "Clean Planet" in _values(rows)
    hit = next(row for row in rows if row["value"] == "Clean Planet")
    assert hit["fuzzy_score"] >= 0.9


def test_multiple_gazetteer_candidates():
    rows = generate_field_candidates(
        {"consignee": "Aquamarine"},
        gazetteer=GAZ,
        memory=_memory(),
        priors=empty_priors(),
    )["consignee"]
    names = set(_values(rows))
    assert "Aquamarine" in names
    assert "Aquamarine Contractors Inc." in names


def test_historical_prior_annotates_supported_candidate():
    priors = empty_priors()
    observe_reviewed_ticket(
        {
            "carrier": "CALIFORNIA MATERIALS, INC.",
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "driver_name": "Gerald Valentin",
            "origin": "North Hooper St, Stockton, CA",
            "destination": "Discovery Bay, CA",
        },
        document_id="gold-1",
        priors=priors,
    )
    rows = generate_field_candidates(
        {
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "carrier": "CALIFORNIA MATERIALS",
        },
        gazetteer=GAZ,
        memory=_memory(),
        priors=priors,
    )["carrier"]
    hit = next(row for row in rows if row["value"] == "CALIFORNIA MATERIALS, INC.")
    assert hit["prior_count"] >= 1
    assert hit["prior_probability"] > 0
    assert "prior" in hit["sources"]
    assert hit["fuzzy_score"] >= 0.7
    assert "GHOST HAULING" not in _values(rows)


def test_context_narrows_carrier_to_historical_route():
    priors = empty_priors()
    observe_reviewed_ticket(
        {
            "carrier": "CALIFORNIA MATERIALS, INC.",
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
        },
        document_id="gold-1",
        priors=priors,
    )
    rows = generate_field_candidates(
        {
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
        },
        gazetteer=GAZ,
        memory=_memory(),
        priors=priors,
        raw_text="CALIFORNIA MATERIALS, INC. hauled for ACME FREIGHT, INC.",
    )["carrier"]
    names = _values(rows)
    assert "CALIFORNIA MATERIALS, INC." in names
    assert "ACME FREIGHT, INC." not in names
    assert "Ghost Hauling LLC" not in names


def test_prior_does_not_invent_without_ocr_or_gazetteer_evidence():
    priors = empty_priors()
    observe_reviewed_ticket(
        {
            "carrier": "Ghost Hauling LLC",
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
        },
        document_id="gold-ghost",
        priors=priors,
    )
    rows = generate_field_candidates(
        {
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "carrier": "CALIFORNIA MATERIALS",
        },
        gazetteer=GAZ,
        memory=_memory(),
        priors=priors,
    )["carrier"]
    assert "Ghost Hauling LLC" not in _values(rows)


def test_candidate_k_limit():
    rows = generate_field_candidates(
        {"consignee": "Aquamarine"},
        gazetteer=GAZ,
        memory=_memory(),
        priors=empty_priors(),
        top_k=1,
    )["consignee"]
    assert len(rows) == 1


def test_no_candidate_when_evidence_absent():
    empty = generate_field_candidates(
        {"consignor": None},
        gazetteer={"consignor": ["Clean Planet"]},
        memory=_memory(),
        priors=empty_priors(),
        raw_text="",
    )["consignor"]
    assert empty == []


def test_weak_ocr_injects_route_conditioned_priors():
    priors = empty_priors()
    observe_reviewed_ticket(
        {
            "carrier": "CALIFORNIA MATERIALS, INC.",
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "driver_name": "Gerald Valentin",
        },
        document_id="gold-1",
        priors=priors,
    )
    rows = generate_field_candidates(
        {
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "carrier": None,
            "driver_name": None,
        },
        gazetteer=GAZ,
        memory=_memory(),
        priors=priors,
        raw_text="",
    )
    assert "CALIFORNIA MATERIALS, INC." in _values(rows["carrier"])
    carrier = next(row for row in rows["carrier"] if row["value"] == "CALIFORNIA MATERIALS, INC.")
    assert "prior" in carrier["sources"]
    assert "Gerald Valentin" in _values(rows["driver_name"])
    assert "Ghost Hauling LLC" not in _values(rows["carrier"])


def test_matched_context_fields_drive_prior_lookup():
    priors = empty_priors()
    observe_reviewed_ticket(
        {
            "carrier": "CALIFORNIA MATERIALS, INC.",
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "driver_name": "Gerald Valentin",
        },
        document_id="gold-1",
        priors=priors,
    )
    rows = generate_field_candidates(
        {"carrier": None, "driver_name": "@@@"},
        context_fields={
            "consignor": "Clean Planet Hooper",
            "consignee": "Aquamarine Contractors Inc.",
            "carrier": "CALIFORNIA MATERIALS, INC.",
        },
        gazetteer=GAZ,
        memory=_memory(),
        priors=priors,
    )["driver_name"]
    assert "Gerald Valentin" in _values(rows)


def test_one_best_gazetteer_matching_unchanged():
    out = apply_entity_matching({"consignor": "CleanPlanet", "driver_name": "207855"})
    assert out["consignor"] == "Clean Planet"
    assert out["driver_name"] == "207855"
    generate_field_candidates({"consignor": "CleanPlanet"}, gazetteer=GAZ, memory=_memory(), priors=empty_priors())
    out2 = apply_entity_matching({"consignor": "CleanPlanet"})
    assert out2["consignor"] == "Clean Planet"
