"""Bounded joint decoder over Point 2 candidates."""

from app.ocr.decode import decode_joint_assignment
from app.ocr.priors import empty_priors, observe_reviewed_ticket


def _cand(value, fuzzy, prior_p=0.0, prior_count=0, sources=None):
    return {
        "value": value,
        "fuzzy_score": fuzzy,
        "prior_probability": prior_p,
        "prior_count": prior_count,
        "sources": sources or ["gazetteer"],
        "final_candidate_score": fuzzy,
        "score": fuzzy,
    }


GOLD = {
    "carrier": "CALIFORNIA MATERIALS, INC.",
    "consignor": "Clean Planet Hooper",
    "consignee": "Aquamarine Contractors Inc.",
    "driver_name": "Gerald Valentin",
    "origin": "North Hooper St, Stockton, CA",
    "destination": "Discovery Bay, CA",
}


def _priors_gold():
    priors = empty_priors()
    observe_reviewed_ticket(GOLD, document_id="gold-1", priors=priors)
    return priors


def test_strong_ocr_beats_weak_historical():
    priors = _priors_gold()
    result = decode_joint_assignment(
        {
            "consignor": [
                _cand("Clean Planet", 1.0, sources=["ocr"]),
                _cand("Clean Planet Hooper", 0.74, prior_p=1.0, prior_count=3, sources=["gazetteer", "prior"]),
            ]
        },
        priors=priors,
    )
    assert result["selected"]["consignor"] == "Clean Planet"


def test_prior_resolves_ambiguous_candidates():
    priors = _priors_gold()
    result = decode_joint_assignment(
        {
            "consignee": [
                _cand("Aquamarine", 0.88, sources=["ocr", "gazetteer"]),
                _cand("Aquamarine Contractors Inc.", 0.88, prior_p=1.0, prior_count=2, sources=["gazetteer", "prior"]),
            ]
        },
        priors=priors,
    )
    assert result["selected"]["consignee"] == "Aquamarine Contractors Inc."


def test_consignor_consignee_prior_selects_carrier():
    priors = _priors_gold()
    result = decode_joint_assignment(
        {
            "consignor": [_cand("Clean Planet Hooper", 1.0, sources=["ocr"])],
            "consignee": [_cand("Aquamarine Contractors Inc.", 1.0, sources=["ocr"])],
            "carrier": [
                _cand("ACME FREIGHT, INC.", 0.82, sources=["gazetteer"]),
                _cand("CALIFORNIA MATERIALS, INC.", 0.82, prior_p=1.0, prior_count=1, sources=["gazetteer", "prior"]),
            ],
        },
        priors=priors,
    )
    assert result["selected"]["carrier"] == "CALIFORNIA MATERIALS, INC."
    names = {row["relation"] for row in result["relations_used"]}
    assert "consignor+consignee→carrier" in names


def test_consignor_carrier_prior_selects_driver():
    priors = _priors_gold()
    result = decode_joint_assignment(
        {
            "consignor": [_cand("Clean Planet Hooper", 1.0, sources=["ocr"])],
            "carrier": [_cand("CALIFORNIA MATERIALS, INC.", 1.0, sources=["ocr"])],
            "driver_name": [
                _cand("Isaac Cordero", 0.86, sources=["gazetteer"]),
                _cand("Gerald Valentin", 0.86, prior_p=1.0, prior_count=1, sources=["gazetteer", "prior"]),
            ],
        },
        priors=priors,
    )
    assert result["selected"]["driver_name"] == "Gerald Valentin"
    names = {row["relation"] for row in result["relations_used"]}
    assert "consignor+carrier→driver" in names


def test_consistent_combination_beats_inconsistent_high_fuzzy():
    priors = _priors_gold()
    result = decode_joint_assignment(
        {
            "consignor": [_cand("Clean Planet Hooper", 1.0, sources=["ocr"])],
            "consignee": [_cand("Aquamarine Contractors Inc.", 0.90, sources=["gazetteer"])],
            "carrier": [
                _cand("ACME FREIGHT, INC.", 0.92, sources=["gazetteer"]),
                _cand("CALIFORNIA MATERIALS, INC.", 0.80, prior_p=1.0, prior_count=1, sources=["gazetteer", "prior"]),
            ],
        },
        priors=priors,
    )
    assert result["selected"]["carrier"] == "CALIFORNIA MATERIALS, INC."
    assert result["selected"]["consignee"] == "Aquamarine Contractors Inc."


def test_prior_only_entity_cannot_be_selected():
    priors = _priors_gold()
    observe_reviewed_ticket(
        {**GOLD, "carrier": "Ghost Hauling LLC"},
        document_id="ghost",
        priors=priors,
    )
    result = decode_joint_assignment(
        {
            "consignor": [_cand("Clean Planet Hooper", 1.0, sources=["ocr"])],
            "consignee": [_cand("Aquamarine Contractors Inc.", 1.0, sources=["ocr"])],
            "carrier": [_cand("CALIFORNIA MATERIALS, INC.", 0.9, sources=["gazetteer"])],
        },
        priors=priors,
    )
    assert "Ghost Hauling LLC" not in result["selected"].values()
    assert result["selected"]["carrier"] == "CALIFORNIA MATERIALS, INC."


def test_single_candidate_is_preserved():
    result = decode_joint_assignment(
        {"consignor": [_cand("Bell Marine", 0.7, sources=["ocr"])]},
        priors=empty_priors(),
    )
    assert result["selected"]["consignor"] == "Bell Marine"


def test_empty_candidates_do_not_crash():
    result = decode_joint_assignment({}, priors=empty_priors())
    assert result["selected"] == {}
    assert result["joint_score"] == 0.0
    result2 = decode_joint_assignment(None, priors=empty_priors())
    assert result2["selected"] == {}
    result3 = decode_joint_assignment({"carrier": []}, priors=empty_priors())
    assert result3["selected"] == {}
