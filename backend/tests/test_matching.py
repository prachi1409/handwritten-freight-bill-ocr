"""Gazetteer matching, glyph repair, and ZIP hints after OCR."""

from app.ocr.matching import (
    add_gazetteer_value,
    apply_entity_matching,
    apply_zip_hints,
    fix_id_glyphs,
    match_gazetteer_name,
    name_variants,
    SEED_GAZETTEER,
)


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
    assert out["consignor"] == "Clean Planet"
    assert out["consignee"] == "A&A Concrete"
    assert out["origin"] == "Stockton, CA"
    assert out["bill_number"] == "16740-1"
    assert out["driver_name"] == "207855"


def test_entity_matching_can_be_disabled(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_ENTITY_MATCHING", False)
    raw = {"consignor": "CleanPlanet"}
    assert apply_entity_matching(raw)["consignor"] == "CleanPlanet"


def test_longer_ocr_name_is_not_shrunk():
    hit = match_gazetteer_name("Clean Planet Hooper", ["Clean Planet"])
    assert hit is None


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
