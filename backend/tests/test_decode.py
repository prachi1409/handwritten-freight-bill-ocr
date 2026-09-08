"""Bounded joint decoder over Point 2 candidates."""

from app.ocr.decode import apply_joint_selection, decode_joint_assignment, resolve_entity_assignment
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


def test_apply_joint_selection_writes_entity_not_money():
    extracted = {
        "carrier": "ACME FREIGHT, INC.",
        "consignee": "Aquamarine Contractors Inc.",
        "freight_amount": "$1,250.00",
        "total_amount": "$1,425.00",
        "weight": "24,500 lbs",
    }
    joint = {"selected": {"carrier": "CALIFORNIA MATERIALS, INC.", "consignee": "Aquamarine Contractors Inc."}}
    out, report = apply_joint_selection(
        extracted,
        joint,
        {
            "carrier": [
                _cand("ACME FREIGHT, INC.", 0.82, sources=["gazetteer"]),
                _cand("CALIFORNIA MATERIALS, INC.", 0.80, prior_p=1.0, prior_count=3, sources=["gazetteer", "prior"]),
            ]
        },
    )
    assert out["carrier"] == "CALIFORNIA MATERIALS, INC."
    assert report["fields"]["carrier"]["status"] == "applied"
    assert out["freight_amount"] == "$1,250.00"
    assert out["total_amount"] == "$1,425.00"
    assert out["weight"] == "24,500 lbs"


def test_apply_joint_ocr_guard_keeps_strong_ocr():
    extracted = {"consignor": "Clean Planet"}
    joint = {"selected": {"consignor": "Clean Planet Hooper"}}
    out, report = apply_joint_selection(
        extracted,
        joint,
        {
            "consignor": [
                _cand("Clean Planet", 1.0, sources=["ocr"]),
                _cand("Clean Planet Hooper", 0.74, prior_p=1.0, prior_count=3, sources=["gazetteer", "prior"]),
            ]
        },
    )
    assert out["consignor"] == "Clean Planet"
    assert report["fields"]["consignor"]["status"] == "ocr_guard"


def test_apply_joint_does_not_lock_place_salad():
    extracted = {"origin": "V.hosper", "destination": "Htth u Uol/raels 30 Pelnr"}
    joint = {
        "selected": {
            "origin": "W. Hooper St.",
            "destination": "Palm Wood",
        }
    }
    out, report = apply_joint_selection(
        extracted,
        joint,
        {
            "origin": [
                _cand("V.hosper", 1.0, sources=["ocr"]),
                _cand("W. Hooper St.", 0.72, sources=["gazetteer"]),
            ],
            "destination": [
                _cand("Htth u Uol/raels 30 Pelnr", 1.0, sources=["ocr"]),
                _cand("Palm Wood", 0.70, sources=["gazetteer"]),
            ],
        },
    )
    assert out["origin"] == "W. Hooper St."
    assert out["destination"] == "Palm Wood"
    assert report["fields"]["origin"]["status"] == "applied"
    assert report["fields"]["destination"]["status"] == "applied"


def test_apply_joint_rejects_datebox_destination_salad():
    extracted = {"destination": "YRZ5 Stockton Discavery Bay CA", "origin": "STOCKTON"}
    joint = {"selected": {"destination": "YRZ5 Stockton Discavery Bay CA"}}
    out, report = apply_joint_selection(
        extracted,
        joint,
        {
            "destination": [
                _cand("YRZ5 Stockton Discavery Bay CA", 1.0, prior_count=1, sources=["ocr", "prior"]),
            ]
        },
    )
    assert out.get("destination") in (None, "")
    assert report["fields"]["destination"]["status"] == "rejected_junk"


def test_apply_joint_replaces_salad_destination_with_gazetteer_place():
    extracted = {"destination": "YRZ5 Stockton Discavery Bay CA"}
    joint = {"selected": {"destination": "Discovery Bay, CA"}}
    out, report = apply_joint_selection(
        extracted,
        joint,
        {
            "destination": [
                _cand("Discovery Bay, CA", 0.80, prior_p=1.0, prior_count=3, sources=["gazetteer", "prior"]),
            ]
        },
    )
    assert out["destination"] == "Discovery Bay, CA"
    assert report["fields"]["destination"]["status"] == "applied"


def test_apply_joint_replaces_ocr_stub_with_historical_name():
    extracted = {"consignor": "clean"}
    joint = {"selected": {"consignor": "Clean Planet Hooper"}}
    out, report = apply_joint_selection(
        extracted,
        joint,
        {
            "consignor": [
                _cand("clean", 1.0, sources=["ocr"]),
                _cand("Clean Planet Hooper", 0.74, prior_p=1.0, prior_count=3, sources=["gazetteer", "prior"]),
            ]
        },
    )
    assert out["consignor"] == "Clean Planet Hooper"
    assert report["fields"]["consignor"]["status"] == "applied"


def test_resolve_entity_assignment_recovers_gold_driver_and_carrier():
    priors = empty_priors()
    gold = {
        "carrier": "CALIFORNIA MATERIALS, INC.",
        "consignor": "Clean Planet Hooper",
        "consignee": "Aquamarine Contractors Inc.",
        "driver_name": "Gerald Valentin",
        "origin": "North Hooper St, Stockton, CA",
        "destination": "Discovery Bay, CA",
    }
    for index in range(3):
        observe_reviewed_ticket(gold, document_id=f"gold-{index}", priors=priors)

    cheap = {
        "consignor": "Clean Planet Hooper",
        "consignee": "Aquamarine Contractors Inc.",
        "carrier": None,
        "driver_name": None,
        "freight_amount": "$1,250.00",
        "total_amount": "$1,425.00",
    }
    matched = dict(cheap)
    gaz = {
        "carrier": ["CALIFORNIA MATERIALS, INC.", "ACME FREIGHT, INC."],
        "consignor": ["Clean Planet Hooper"],
        "consignee": ["Aquamarine Contractors Inc."],
        "driver_name": ["Gerald Valentin", "Isaac Cordero"],
        "origin": ["North Hooper St, Stockton, CA"],
        "destination": ["Discovery Bay, CA"],
    }
    from app.ocr.matching import _empty_memory

    mem = _empty_memory()
    mem["names"] = {k: list(v) for k, v in gaz.items()}
    mem["aliases"] = {k: {} for k in gaz}

    out, cands, joint = resolve_entity_assignment(
        matched,
        cheap_fields=cheap,
        priors=priors,
        gazetteer=gaz,
        memory=mem,
    )
    assert out["carrier"] == "CALIFORNIA MATERIALS, INC."
    assert out["driver_name"] == "Gerald Valentin"
    assert out["consignor"] == "Clean Planet Hooper"
    assert out["consignee"] == "Aquamarine Contractors Inc."
    assert out["freight_amount"] == "$1,250.00"
    assert out["total_amount"] == "$1,425.00"
    assert joint["applied_to_extraction"] is True
    assert "Gerald Valentin" in [row["value"] for row in cands["driver_name"]]


def test_empty_candidates_do_not_crash():
    result = decode_joint_assignment({}, priors=empty_priors())
    assert result["selected"] == {}
    assert result["joint_score"] == 0.0
    result2 = decode_joint_assignment(None, priors=empty_priors())
    assert result2["selected"] == {}
    result3 = decode_joint_assignment({"carrier": []}, priors=empty_priors())
    assert result3["selected"] == {}


def test_apply_joint_rejects_letterhead_as_consignor():
    extracted = {"carrier": "CALIFORNIA MATERIALS, INC.", "consignor": None}
    joint = {"selected": {"consignor": "California Materials, Inc.", "carrier": "CALIFORNIA MATERIALS, INC."}}
    out, report = apply_joint_selection(
        extracted,
        joint,
        {
            "consignor": [_cand("California Materials, Inc.", 0.80, sources=["ocr_text", "gazetteer"])],
            "carrier": [_cand("CALIFORNIA MATERIALS, INC.", 1.0, sources=["ocr"])],
        },
    )
    assert out.get("consignor") in (None, "")
    assert report["fields"]["consignor"]["status"] == "rejected_letterhead"
    assert out["carrier"] == "CALIFORNIA MATERIALS, INC."


def test_resolve_does_not_fill_empty_consignor_from_letterhead():
    from app.ocr.matching import _empty_memory
    from app.ocr.priors import empty_priors

    gaz = {
        "carrier": ["CALIFORNIA MATERIALS, INC."],
        "consignor": ["Clean Planet Hooper", "California Materials, Inc."],
        "consignee": ["Aquamarine"],
        "driver_name": [],
        "origin": [],
        "destination": [],
    }
    mem = _empty_memory()
    mem["names"] = {k: list(v) for k, v in gaz.items()}
    cheap = {"carrier": "CALIFORNIA MATERIALS, INC.", "consignor": None, "consignee": None}
    out, cands, joint = resolve_entity_assignment(
        dict(cheap),
        cheap_fields=cheap,
        raw_text="CALIFORNIA MATERIALS, INC.\nSTOCKTON, CA\nNo. 9503-1",
        priors=empty_priors(),
        gazetteer=gaz,
        memory=mem,
    )
    assert out.get("consignor") in (None, "")
    assert "California Materials, Inc." not in [row["value"] for row in (cands.get("consignor") or [])]
    assert out["carrier"] == "CALIFORNIA MATERIALS, INC."


def test_local_processor_writes_peaked_driver_from_route_history(create_pdf, monkeypatch):
    from app.ocr import vision_fallback as vf
    from app.ocr.local_processor import LocalOCRProcessor
    from app.ocr.priors import empty_priors, observe_reviewed_ticket

    gold = {
        "carrier": "CALIFORNIA MATERIALS, INC.",
        "consignor": "Clean Planet Hooper",
        "consignee": "Aquamarine Contractors Inc.",
        "driver_name": "Gerald Valentin",
        "origin": "North Hooper St, Stockton, CA",
        "destination": "Discovery Bay, CA",
    }
    priors = empty_priors()
    for index in range(3):
        observe_reviewed_ticket(gold, document_id=f"gold-{index}", priors=priors)

    monkeypatch.setattr("app.ocr.priors.load_priors", lambda: priors)
    monkeypatch.setattr("app.ocr.candidates.load_priors", lambda: priors)
    monkeypatch.setattr("app.ocr.decode.load_priors", lambda: priors)
    monkeypatch.setattr(vf.settings, "GROQ_VISION_FALLBACK_ENABLED", False)

    pdf_path = create_pdf(
        "route_prior_bill.pdf",
        "FREIGHT BILL\nBill No: HB-10021\nConsignor: Clean Planet Hooper\n"
        "Consignee: Aquamarine Contractors Inc.\nCarrier: CALIFORNIA MATERIALS, INC.\n"
        "Origin: North Hooper St, Stockton, CA\nDestination: Discovery Bay, CA\n"
        "Freight Amount: $1,250.00\nTotal Amount: $1,425.00\n",
    )
    result = LocalOCRProcessor().process_document(pdf_path)
    data = result.extracted_data or {}
    joint = result.raw_ocr.get("joint_decode") or {}
    assert joint.get("applied_to_extraction") is True
    assert data.get("freight_amount") or data.get("total_amount")
    parties = [data.get("consignor"), data.get("consignee"), data.get("carrier")]
    if all(parties):
        assert data.get("driver_name") == "Gerald Valentin"
