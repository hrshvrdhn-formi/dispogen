"""Validator behaviour, with V11 and V16 given the most attention.

Every test asserts on the check ID, not on the message text, so rewording an
error does not fail the suite but weakening a check does.
"""
import copy

import pytest

from dispogen import packs as packmod
from dispogen.deidentify import Deidentifier
from dispogen.validators import lint_learnings, validate

HOST = "PAID_BANK"
CLAUSE = 'Trigger: "bank mein jama". Exclusion: NOT THIS if 0012 applies.'
RIVAL_CLAUSE = 'Trigger: "branch mein jama". NOT THIS: promise to pay later.'


@pytest.fixture
def pack(cfg, tax):
    return packmod.build_all(cfg, tax, [HOST])[HOST]


# V8 compares transcripts pairwise on trigram overlap, so a fixture that varies
# only an index trips it and masks whatever the test was actually asserting.
OPENERS = [
    "नमस्ते सर, renewal premium को लेकर call किया है",
    "Good afternoon, आपकी policy के बारे में बात करनी थी",
    "जी नमस्कार, एक ज़रूरी update देना था आपको",
    "Hello ma'am, main aapke insurance plan ke silsile mein baat kar rahi hoon",
    "सर आपका थोड़ा समय चाहिए था, premium को लेकर",
    "क्या मैं policyholder से बात कर रही हूं?",
    "जी हां, आपकी सुविधा के अनुसार बात कर लेते हैं",
    "Sir aapka due date nikal raha hai, isliye reminder call hai",
    "नमस्ते, आपने पिछली बार कहा था कि confirm करेंगे",
    "Aapse ek minute baat kar sakti hoon premium ke regarding?",
]
REPLIES = [
    "मैंने bank mein jama कर दिया था, receipt भी mere paas rakhi hai",
    "हां भाई, bank mein jama karwa diya tha last Thursday ko",
    "पैसे तो bank mein jama हो चुके हैं, cheque clear भी हो गया",
    "Maine SBI ki branch wale counter par nahi, bank mein jama kiya tha online",
    "बैंक वालों ने बोला था दो दिन लगेंगे, तो bank mein jama है already",
    "अरे वो तो कब का bank mein jama कर दिया, आपको दिख नहीं रहा?",
    "Jama kar diya tha bank mein jama, receipt number bhi note kiya hua hai",
    "हमने bank mein jama किया था, पर confirmation message नहीं आया",
    "देखिए मैंने खुद जाकर bank mein jama करवाया था उस दिन",
    "Bank mein jama ho gaya hai, ab aur kya karna hai bataiye",
]


def _case(sn, ptype, slot=None, **kw):
    n = sn if ptype == "FP" else sn - 5
    c = {
        "sn": sn, "test_case_id": f"{HOST}-{ptype}-{n:02d}", "probe_type": ptype,
        "scenario": f"scenario {sn}",
        "transcript": [
            {"speaker": "agent", "text": OPENERS[sn - 1]},
            {"speaker": "customer", "text": REPLIES[sn - 1]},
        ],
        "pre_call_parameters": {"policy_no": "04471903"},
        "declared_grade": "EXPANDED",
        "expected_group": "CTP - Committed to Pay",
        "expected_sub": "0010 - Payment Made",
        "expected_expanded": "0011 - Paid via Bank",
        "must_not_select": [],
        "decisive_evidence": REPLIES[sn - 1],
        "cited_clause": CLAUSE,
        "rebutted_rivals": [{"code": "0012", "clause": RIVAL_CLAUSE,
                             "why": "the channel named is the bank, not a branch counter"}],
        "precedence_rule_applied": None,
        "perturbations": [f"scenario:v{sn}"],
        "redial": {"is_required": "No", "anchor_date": "Tue 07 Jul 2026, 14:32",
                   "schedule": "Wed 08 Jul 2026, 11:00",
                   "context": f"payment {sn} confirmed", "basis": "derived"},
    }
    if ptype == "FP":
        c["slot"] = slot
        c["must_not_select"] = ["0011"]
        c["trap_phrase"] = "bank mein jama"
        c["expected_expanded"] = "0012 - Paid at Branch"
        c["expected_sub"] = "0010 - Payment Made"
    c.update(kw)
    return c


@pytest.fixture
def doc(pack):
    """Ten cases pinned to the real allocation, so V5 has something to check."""
    alloc = pack["quota"]["fp_allocation"]
    fps = []
    for i, a in enumerate(alloc, 1):
        c = _case(i, "FP", slot=a["slot"], archetype=a["archetype"])
        c["rival_code"] = a["rival_num"]
        if a["level"] == "sub":
            c.update(declared_grade="SUB", expected_expanded=None,
                     expected_sub="0010 - Payment Made")
        elif a["level"] == "group":
            c.update(declared_grade="GROUP", expected_expanded=None, expected_sub=None)
        elif a["rival_num"] == "0072":
            c.update(expected_group="NC - Not Connected",
                     expected_sub="0070 - Telephony",
                     expected_expanded="0072 - Switched Off")
        else:
            c.update(expected_expanded="0012 - Paid at Branch")
        fps.append(c)
    fns = [_case(i, "FN", archetype=f"a{i}") for i in range(6, 11)]
    return {"engine_code": HOST, "label": "0011 - Paid via Bank",
            "source_of_truth_class": "transcript", "cases": fps + fns}


def ids(errs):
    return sorted({e.split("]")[0].lstrip("[") for e in errs})


def test_a_well_formed_document_passes(cfg, tax, doc, pack):
    assert validate(cfg, tax, doc, pack) == []


def test_probe_order_follows_the_client_output_contract(cfg, tax, doc, pack):
    doc["cases"] = doc["cases"][5:] + doc["cases"][:5]
    for i, c in enumerate(doc["cases"], 1):
        c["sn"] = i
    assert "V2" in ids(validate(cfg, tax, doc, pack))


def test_an_fn_probe_must_expect_the_host(cfg, tax, doc, pack):
    doc["cases"][5]["expected_expanded"] = "0012 - Paid at Branch"
    assert "V3" in ids(validate(cfg, tax, doc, pack))


def test_an_fp_probe_pinned_to_the_wrong_rival_is_rejected(cfg, tax, doc, pack):
    doc["cases"][0]["rival_code"] = "0072"
    assert "V5" in ids(validate(cfg, tax, doc, pack))


def test_a_telephony_class_case_may_not_carry_a_transcript(cfg, tax, doc, pack):
    pack = copy.deepcopy(pack)
    pack["source_of_truth_class"] = "telephony"
    assert "V6" in ids(validate(cfg, tax, doc, pack))


def test_a_callback_before_the_anchor_is_rejected(cfg, tax, doc, pack):
    doc["cases"][0]["redial"]["schedule"] = "Mon 06 Jul 2026, 11:00"
    assert "V7" in ids(validate(cfg, tax, doc, pack))


def test_a_callback_outside_the_calling_window_is_rejected(cfg, tax, doc, pack):
    doc["cases"][0]["redial"]["schedule"] = "Wed 08 Jul 2026, 23:30"
    assert "V7" in ids(validate(cfg, tax, doc, pack))


def test_near_duplicate_transcripts_are_caught(cfg, tax, doc, pack):
    doc["cases"][1]["transcript"] = copy.deepcopy(doc["cases"][0]["transcript"])
    assert "V8" in ids(validate(cfg, tax, doc, pack))


def test_a_trap_phrase_not_in_the_transcript_is_rejected(cfg, tax, doc, pack):
    doc["cases"][0]["trap_phrase"] = "never said this"
    assert "V9" in ids(validate(cfg, tax, doc, pack))


def test_a_paraphrased_clause_does_not_satisfy_v11(cfg, tax, doc, pack):
    """The whole zero-FP argument rests on this being a string operation.

    A near-miss citation is the failure mode: it reads as grounded, and a model
    judging groundedness would accept it.
    """
    doc["cases"][0]["cited_clause"] = 'Trigger: "bank mein jama" — exclusion if 0012 applies.'
    assert "V11" in ids(validate(cfg, tax, doc, pack))


def test_decisive_evidence_must_be_a_span_of_this_transcript(cfg, tax, doc, pack):
    # Present in ANOTHER case's transcript, absent from this one.
    doc["cases"][0]["decisive_evidence"] = REPLIES[4]
    assert "V11" in ids(validate(cfg, tax, doc, pack))


def test_a_case_that_rebuts_nothing_is_rejected(cfg, tax, doc, pack):
    doc["cases"][0]["rebutted_rivals"] = []
    assert "V11" in ids(validate(cfg, tax, doc, pack))


def test_a_rebuttal_without_reasoning_is_rejected(cfg, tax, doc, pack):
    doc["cases"][0]["rebutted_rivals"][0]["why"] = "   "
    assert "V11" in ids(validate(cfg, tax, doc, pack))


def test_a_non_production_token_is_rejected(cfg, tax, doc, pack):
    cfg.data.setdefault("tokens", {})["documented_but_not_produced"] = ["[/interrupted]"]
    doc["cases"][6]["transcript"][1]["text"] += " [/interrupted]"
    assert "V12" in ids(validate(cfg, tax, doc, pack))


def test_a_sub_grade_with_a_leaf_answer_is_incoherent(cfg, tax, doc, pack):
    doc["cases"][5]["declared_grade"] = "SUB"
    assert "V13" in ids(validate(cfg, tax, doc, pack))


def test_expected_sub_must_be_the_parent_of_expected_expanded(cfg, tax, doc, pack):
    doc["cases"][5]["expected_sub"] = "0020 - Payment Commitment"
    assert "V13" in ids(validate(cfg, tax, doc, pack))


def test_an_unknown_precedence_rule_is_rejected(cfg, tax, doc, pack):
    doc["cases"][0]["precedence_rule_applied"] = "P99"
    assert "V14" in ids(validate(cfg, tax, doc, pack))


def test_a_paraphrase_probe_may_not_use_a_listed_trigger(cfg, tax, doc, pack):
    doc["cases"][5]["archetype"] = "paraphrased_trigger"
    assert "V15" in ids(validate(cfg, tax, doc, pack))


def test_a_real_identifier_blocks_release(cfg, tax, doc, pack):
    doc["cases"][0]["transcript"][0]["text"] += " Sharma ji"
    deid = Deidentifier(cfg, {"person_names": {"Sharma"}, "policy_numbers": set(),
                              "phone_numbers": set(), "emails": set()})
    assert "V16" in ids(validate(cfg, tax, doc, pack, deid))


def test_learnings_that_name_the_client_domain_are_flagged(cfg):
    hits = lint_learnings(cfg, "The persistency agent mis-scored 0011 on retries.")
    assert {h["pattern"] for h in hits}
    assert any("persistency" in h["text"] for h in hits)


def test_portable_learnings_pass_the_lint(cfg):
    assert lint_learnings(cfg, "Truncation after a perfective auxiliary removes nothing.") == []
