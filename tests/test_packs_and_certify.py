"""A pack must be sufficient on its own, and a blind critic must actually be blind.

Both properties are easy to break by adding a field somewhere else and never
noticing: the pipeline still runs, it just stops testing what it claims to.
"""
import json

from dispogen import certify, packs as packmod
from dispogen.validators import validate

HOST = "PAID_BANK"


def test_a_pack_carries_everything_the_validators_enforce(cfg, tax):
    p = packmod.build_all(cfg, tax, [HOST])[HOST]
    c = p["contract"]
    assert c["probe_order"] == ["FP", "FN"]
    assert c["calling_window"] == {"start": "09:00", "end": "21:00"}
    assert "non_production_tokens" in c and "forbidden_agent_patterns" in c
    assert p["citable_clause_sources"]["leaf_rules"]
    assert p["precedence_ladder"][0]["anchor"] in tax.corpus


def test_every_rival_carries_its_own_ancestors(cfg, tax):
    """V13 checks the group/sub/expanded triple.

    A generator that only sees a rival's label has to guess the ancestors, and
    guessing "same as the host" is right until the rival is out-of-class.
    """
    p = packmod.build_all(cfg, tax, [HOST])[HOST]
    out = [r for r in p["rivals"] if r["num"] == "0072"]
    assert out and out[0]["their_group"] == "NC - Not Connected"


def test_a_pack_is_json_serialisable_and_hashed(cfg, tax):
    p = packmod.build_all(cfg, tax, [HOST])[HOST]
    json.dumps(p, ensure_ascii=False)
    assert len(p["pack_hash"]) == 16


def test_the_hash_changes_when_the_allocation_changes(cfg, tax):
    a = packmod.build_all(cfg, tax, [HOST])[HOST]["pack_hash"]
    cfg.data["quota"]["fp_slots"] = cfg.data["quota"]["fp_slots"][:3]
    b = packmod.build_all(cfg, tax, [HOST])[HOST]["pack_hash"]
    assert a != b


def test_the_blind_view_hides_every_field_that_names_the_answer():
    case = {"transcript": [{"speaker": "customer", "text": "x"}],
            "pre_call_parameters": {"policy_no": "04471903"},
            "expected_expanded": "0011 - Paid via Bank", "declared_grade": "EXPANDED",
            "cited_clause": "...", "decisive_evidence": "x", "rival_code": "0012",
            "trap_phrase": "x", "archetype": "nearest_rival_decoy", "slot": "FP-1",
            "probe_type": "FP", "scenario": "author's framing", "must_not_select": ["0011"],
            "test_case_id": "PAID_BANK-FP-01", "rebutted_rivals": [],
            "perturbations": [], "precedence_rule_applied": None}
    v = certify.blind_view(case)
    assert set(v) == {"transcript", "pre_call_parameters"}
    # `scenario` is written from the author's point of view and `archetype` names
    # the construction — leaving either in turns the blind pass into a hint.
    assert "scenario" not in v and "archetype" not in v


def test_the_critic_sees_the_whole_taxonomy_not_a_shortlist(tax):
    v = certify.taxonomy_view(tax)
    assert len(v["expanded"]) == len(tax.leaves)
    assert len(v["groups"]) == len(tax.groups)


def test_dissent_demotes_the_grade_rather_than_overriding_it():
    assert certify.demote("EXPANDED") == "SUB"
    assert certify.demote("SUB") == "GROUP"
    assert certify.demote("GROUP") is None, "a GROUP case has nowhere left to fall"


def test_a_verdict_matching_the_author_agrees():
    case = {"declared_grade": "SUB", "expected_group": "G", "expected_sub": "S",
            "expected_expanded": None}
    ok, _ = certify._agrees({"grade": "SUB", "group": "G", "sub": "S", "expanded": None}, case)
    assert ok


def test_an_abstention_is_dissent_not_agreement():
    case = {"declared_grade": "EXPANDED", "expected_group": "G",
            "expected_sub": "S", "expected_expanded": "E"}
    ok, why = certify._agrees({"grade": "ABSTAIN", "ambiguity": "no clause decides"}, case)
    assert not ok and "abstain" in why.lower()


def test_an_unparseable_verdict_is_dissent_not_a_skip():
    ok, why = certify._agrees(None, {"declared_grade": "GROUP"})
    assert not ok and "unparseable" in why


def test_a_fenced_json_verdict_is_still_read():
    assert certify._json('```json\n{"grade": "GROUP"}\n```')["grade"] == "GROUP"
    assert certify._json("Here you go: {\"grade\": \"SUB\"} — hope that helps")["grade"] == "SUB"
    assert certify._json("no object here") is None


def test_case_documents_survive_a_round_trip_through_validate(cfg, tax):
    """Guards the seam: packs and validators must agree on field names."""
    p = packmod.build_all(cfg, tax, [HOST])[HOST]
    errs = validate(cfg, tax, {"engine_code": HOST, "cases": []}, p)
    assert any(e.startswith("[V2]") for e in errs)
