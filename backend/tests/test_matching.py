"""Gazetteer matching, glyph repair, and ZIP hints after OCR."""

from app.ocr.matching import (
    add_gazetteer_value,
    apply_entity_matching,
    apply_zip_hints,
    fix_id_glyphs,
    is_weak_entity_stub,
    match_gazetteer_name,
    name_variants,
    SEED_GAZETTEER,
)


def test_short_ocr_fragments_are_weak_stubs():
    assert is_weak_entity_stub("consignor", "clean") is True
    assert is_weak_entity_stub("consignee", "Aaua") is True
    assert is_weak_entity_stub("consignor", "Clean Planet Hooper") is False
    assert is_weak_entity_stub("consignee", "Aquamarine Contractors Inc.") is False
    assert is_weak_entity_stub("carrier", "CMAT") is False
    assert is_weak_entity_stub("bill_number", "16766-1") is False
    assert is_weak_entity_stub("total_amount", "$100.00") is False
    assert is_weak_entity_stub("invoice_number", "INV-1") is False
    assert is_weak_entity_stub("destination", "YRZ5 Stockton Discavery Bay CA") is True
    assert is_weak_entity_stub("destination", "Discovery Bay, CA") is False
    assert is_weak_entity_stub("consignor", "California Materials, Inc.") is True
    assert is_weak_entity_stub("consignor", "CALIFORNIA MATERIALS, INC.") is True
    assert "California Materials" not in " ".join(SEED_GAZETTEER["consignor"])


def test_discavery_snaps_to_discovery_bay():
    hit = match_gazetteer_name("Discavery", SEED_GAZETTEER["destination"])
    assert hit is not None
    assert "Discovery" in hit


def test_cleanplanet_snaps_to_clean_planet():
    hit = match_gazetteer_name("CleanPlanet", SEED_GAZETTEER["consignor"])
    assert hit == "Clean Planet"


def test_a9a_concrete_maps_ampersand():
    assert "A&A Concrete" in name_variants("A9A Concrete")
    hit = match_gazetteer_name("A9A Concrete", SEED_GAZETTEER["consignee"])
    assert hit == "A&A Concrete"


def test_id_glyphs_o_to_zero_when_digit_heavy():
    assert fix_id_glyphs("HB-O78421") == "HB-078421"
    assert fix_id_glyphs("28O") == "280"
    assert fix_id_glyphs("INV-998877") == "INV-998877"
    assert fix_id_glyphs("ISAAC") == "ISAAC"


def test_payroll_digits_are_not_matched_as_driver():
    out = apply_entity_matching({"driver_name": "207855"})
    assert out["driver_name"] == "207855"
    gaz = add_gazetteer_value("driver_name", "207855", {"driver_name": ["Isaac Cordero"]})
    assert gaz["driver_name"] == ["Isaac Cordero"]


def test_zip_hint_fills_known_city_state():
    out = apply_zip_hints({"origin": "95213", "destination": "Discovery Bay CA 94505"})
    assert out["origin"] == "Stockton, CA 95213"
    assert "94505" in out["destination"]
    assert "Discovery Bay" in out["destination"]


def test_apply_entity_matching_company_and_place():
    out = apply_entity_matching({
        "consignor": "CleanPlanet",
        "consignee": "A9A Concrete",
        "origin": "StocktonCA",
        "bill_number": "1674O-1",
        "driver_name": "207855",
    })
    assert out["consignor"] == "Clean Planet Hooper"
    assert out["consignee"] == "A&A Concrete"
    assert out["origin"] == "Stockton, CA"
    assert out["bill_number"] == "16740-1"
    assert out["driver_name"] == "207855"


def test_apply_entity_matching_snaps_discavery_destination():
    out = apply_entity_matching({"destination": "Discavery"})
    assert "Discovery" in (out.get("destination") or "")


def test_entity_matching_can_be_disabled(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_ENTITY_MATCHING", False)
    raw = {"consignor": "CleanPlanet"}
    assert apply_entity_matching(raw)["consignor"] == "CleanPlanet"


def test_longer_ocr_name_is_not_shrunk():
    hit = match_gazetteer_name("Clean Planet Hooper", ["Clean Planet"])
    assert hit is None


def test_stockton_does_not_expand_to_hopper_street():
    hit = match_gazetteer_name(
        "STOCKTON",
        ["STOCKTON N. HOPPER ST", "Stockton, CA", "STOCKTON", "N. Hooper St."],
    )
    assert hit in ("STOCKTON", "Stockton, CA")
    assert "HOPPER" not in (hit or "").upper()
    assert "HOOPER" not in (hit or "").upper()


def test_city_only_origin_does_not_invent_a_street():
    from app.ocr.matching import apply_entity_matching, _empty_memory

    memory = _empty_memory()
    out = apply_entity_matching({"origin": "STOCKTON"}, memory=memory)
    assert "Hooper" not in (out.get("origin") or "")
    assert "Hopper" not in (out.get("origin") or "")


def test_dtscover_token_snaps_to_discovery_bay():
    hit = match_gazetteer_name("HOOPER DTSCOVER BA 4", SEED_GAZETTEER["destination"])
    assert hit is not None
    assert "Discovery" in hit


def test_cpi_hooper_and_aguamarene_aliases():
    from app.ocr.matching import apply_entity_matching, _empty_memory

    memory = _empty_memory()
    out = apply_entity_matching(
        {"consignor": "C.P.I.HOOPER", "consignee": "AGUAMARENE"},
        memory=memory,
    )
    assert out["consignor"] == "Clean Planet Hooper"
    assert "Aquamarine" in (out.get("consignee") or "")


def test_crim_planet_and_noen_houper_aliases():
    from app.ocr.matching import apply_entity_matching, _empty_memory

    memory = _empty_memory()
    out = apply_entity_matching(
        {"consignor": "Crim Planet Hooper", "origin": "Noen Houper"},
        memory=memory,
    )
    assert out["consignor"] == "Clean Planet Hooper"
    assert out["origin"] == "North Hooper"
    out2 = apply_entity_matching({"consignor": "Grand Planet Hooper"}, memory=_empty_memory())
    assert out2["consignor"] == "Clean Planet Hooper"
    out3 = apply_entity_matching(
        {"consignor": "Ocean Planet", "origin": "V.hosper"},
        memory=_empty_memory(),
    )
    assert out3["consignor"] == "Clean Planet Hooper"
    assert "Hooper" in (out3.get("origin") or "")


def test_unknown_place_salad_is_a_weak_stub():
    assert is_weak_entity_stub("origin", "V.hosper") is True
    assert is_weak_entity_stub("destination", "Htth u Uol/raels 30 Pelnr") is True
    assert is_weak_entity_stub("origin", "Stockton, CA") is False
    assert is_weak_entity_stub("destination", "Discovery Bay, CA") is False


def test_review_alias_snaps_far_ocr():
    from app.ocr.matching import apply_entity_matching, _empty_memory

    memory = _empty_memory()
    memory["aliases"]["consignee"]["aquamatrix"] = "Aquamarine"
    out = apply_entity_matching({"consignee": "Aquamatrix"}, memory=memory)
    assert out["consignee"] == "Aquamarine"


def test_regional_zip_fills_manteca():
    out = apply_zip_hints({"origin": "95336"})
    assert out["origin"] == "Manteca, CA 95336"


def test_street_snaps_inside_known_zip():
    from app.ocr.matching import apply_entity_matching, _empty_memory

    memory = _empty_memory()
    out = apply_entity_matching({"origin": "N Hooper St 95213"}, memory=memory)
    assert "Hooper" in out["origin"]
    assert "Stockton" in out["origin"]
    assert "95213" in out["origin"]


def test_gold_harvest_trusts_review_not_ocr_junk():
    from app.ocr.matching import _collapse, _empty_memory, merge_gold_records

    memory = _empty_memory()
    merge_gold_records(
        [{"consignee": "Aquamarine Contractors Inc.", "origin": "N. Hooper St. Stockton CA 95213"}],
        trusted=True,
        memory=memory,
    )
    merge_gold_records(
        [{"consignee": "Aquamatrix", "carrier": "CALIFORNIA MATERIALS, INC."}],
        trusted=False,
        memory=memory,
    )
    names = {_collapse(v) for v in memory["names"]["consignee"]}
    assert "aquamarinecontractorsinc" in names
    assert "aquamatrix" not in names
    assert "CALIFORNIA MATERIALS, INC." in memory["names"]["carrier"]
    assert any("Hooper" in s for s in memory["streets_by_zip"].get("95213", []))


def test_letterhead_is_not_harvested_or_snapped_as_consignor():
    from app.ocr.matching import add_gazetteer_value, apply_entity_matching, merge_gold_records, _empty_memory

    gaz = add_gazetteer_value(
        "consignor",
        "California Materials, Inc.",
        {"consignor": ["Clean Planet Hooper"], "carrier": ["CALIFORNIA MATERIALS, INC."]},
    )
    assert "California Materials, Inc." not in gaz["consignor"]

    memory = _empty_memory()
    merge_gold_records(
        [{"consignor": "California Materials, Inc.", "carrier": "CALIFORNIA MATERIALS, INC."}],
        trusted=True,
        memory=memory,
    )
    assert not any("california" in (n or "").lower() and "materials" in (n or "").lower() for n in memory["names"]["consignor"])

    out = apply_entity_matching({
        "consignor": "California Materials, Inc.",
        "carrier": "CALIFORNIA MATERIALS, INC.",
        "consignee": "Aquamarine",
    })
    assert out["consignor"] is None
    assert out["carrier"] == "CALIFORNIA MATERIALS, INC."
    assert "Aquamarine" in (out.get("consignee") or "")
