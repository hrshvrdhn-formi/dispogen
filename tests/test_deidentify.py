"""Regressions for the P0 leak.

Every test here corresponds to a way the first implementation reported a clean
scrub while a real identifier was still in the file.
"""
import pytest

from dispogen.deidentify import Deidentifier, PoolExhausted, _num_re


def real(**kw):
    base = {"person_names": set(), "policy_numbers": set(),
            "phone_numbers": set(), "emails": set()}
    base.update({k: set(v) for k, v in kw.items()})
    return base


def test_zero_padded_identifier_does_not_survive(cfg):
    """`(?<!\\d)4471902(?!\\d)` never fires inside "04471902".

    The padding zero is itself a digit, so the lookbehind blocks the match: the
    number survived the scrub while its spoken form was replaced, which read as a
    partial success rather than a failure.
    """
    d = Deidentifier(cfg, real(policy_numbers=["4471902"]))
    out = d.scrub({"t": "policy 04471902 is due"})
    assert "4471902" not in out["t"]
    assert d.report(out) == []


def test_bare_and_padded_forms_map_to_the_same_synthetic_identity(cfg):
    d = Deidentifier(cfg, real(policy_numbers=["4471902"]))
    a = d.scrub("ref 4471902")
    b = d.scrub("ref 04471902")
    assert a.split()[-1] == b.split()[-1]


def test_a_longer_number_that_merely_contains_it_is_untouched(cfg):
    """Only leading ZEROS are padding. A leading 9 makes it a different number."""
    d = Deidentifier(cfg, real(policy_numbers=["4471902"]))
    assert d.scrub("txn 94471902") == "txn 94471902"


def test_digit_by_digit_spoken_form_is_scrubbed(cfg):
    d = Deidentifier(cfg, real(policy_numbers=["1765"]))
    out = d.scrub("मेरा number one seven six five है")
    assert "one seven six five" not in out


def test_a_pool_that_overlaps_the_corpus_is_filtered(cfg):
    """Otherwise scrubbing swaps one real name for another and reports success."""
    cfg.data["deidentify"]["pools"]["surnames_deva"] = ["Mehta", "Verma"]
    d = Deidentifier(cfg, real(person_names=["Verma"]))
    assert "Verma" not in d.pools["surnames_deva"]
    assert d.collisions[0]["dropped"] == ["Verma"]


def test_a_fully_overlapping_pool_raises_rather_than_passing_silently(cfg):
    cfg.data["deidentify"]["pools"]["surnames_deva"] = ["Verma"]
    with pytest.raises(PoolExhausted, match="surnames_deva"):
        Deidentifier(cfg, real(person_names=["Verma"]))


def test_replacement_is_deterministic_under_a_fixed_salt(cfg, monkeypatch):
    monkeypatch.setenv("DISPOGEN_DEID_SALT", "fixed")
    a = Deidentifier(cfg, real(policy_numbers=["4471902"])).scrub("p 4471902")
    b = Deidentifier(cfg, real(policy_numbers=["4471902"])).scrub("p 4471902")
    assert a == b


def test_rotating_the_salt_changes_the_mapping(cfg, monkeypatch):
    monkeypatch.setenv("DISPOGEN_DEID_SALT", "one")
    a = Deidentifier(cfg, real(policy_numbers=["4471902"])).scrub("p 4471902")
    monkeypatch.setenv("DISPOGEN_DEID_SALT", "two")
    b = Deidentifier(cfg, real(policy_numbers=["4471902"])).scrub("p 4471902")
    assert a != b


def test_scrub_reaches_into_nested_structures(cfg):
    d = Deidentifier(cfg, real(emails=["a@b.com"]))
    out = d.scrub({"cases": [{"transcript": [{"text": "mail a@b.com"}]}]})
    assert "a@b.com" not in out["cases"][0]["transcript"][0]["text"]


def test_report_names_the_kind_and_the_value(cfg):
    d = Deidentifier(cfg, real(person_names=["Sharma"]))
    hits = d.report({"t": "Sharma ji"})
    assert hits == [{"kind": "person_names", "value": "Sharma"}]


def test_num_re_rejects_an_all_zero_identifier():
    assert _num_re("000") is None
