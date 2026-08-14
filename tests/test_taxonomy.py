import pytest

from dispogen import taxonomy as taxmod
from dispogen.config import Config


def test_forward_fill_gives_continuation_rows_their_ancestors(tax):
    leaf = tax.by_code["PAID_BRANCH"]
    assert leaf.group == "CTP - Committed to Pay"
    assert leaf.sub == "0010 - Payment Made"


def test_sub_change_does_not_reset_the_group(tax):
    assert tax.by_code["ASSURED_ADVISOR"].group == "CTP - Committed to Pay"
    assert tax.by_code["ASSURED_ADVISOR"].sub == "0020 - Payment Commitment"


def test_source_of_truth_is_classified_from_the_rules_text(tax):
    assert tax.by_code["PAID_BANK"].source_of_truth_class == "transcript"
    # The engineering note mentions cross-call; rule order decides which wins.
    assert tax.by_code["SWITCHED_OFF"].source_of_truth_class == "telephony"


def test_confusion_graph_ignores_self_references(cfg, tax):
    g = taxmod.confusion_graph(cfg, tax)
    assert "0011" not in [r["num"] for r in g["PAID_BANK"]["rivals"]]
    assert "0012" in [r["num"] for r in g["PAID_BANK"]["rivals"]]


def test_a_sub_code_cited_in_rules_resolves_as_a_sub_not_a_leaf(cfg, tax):
    g = taxmod.confusion_graph(cfg, tax)
    rivals = g["ASSURED_ADVISOR"]["rivals"]
    assert {r["num"]: r["level"] for r in rivals}["0011"] == "expanded"


def test_precedence_anchor_that_stops_resolving_is_reported(cfg, tax):
    ladder, missing = taxmod.precedence(cfg, tax)
    assert missing == []
    cfg.data["precedence"] = [{"id": "P9", "rule": "x", "anchor": "text that is not there"}]
    _, missing = taxmod.precedence(cfg, tax)
    assert missing == ["P9"]


def test_slots_fill_by_role_not_by_rank(cfg, tax):
    """The regression this check exists for.

    Ranking the candidate pool and zipping it onto the archetypes gives the
    highest-weight rivals to the first slots, so stop_at_parent and out_of_class
    get siblings — while the quota still reports 5/5 filled.
    """
    graph = taxmod.confusion_graph(cfg, tax)
    alloc = taxmod.allocate(cfg, tax, tax.by_code["PAID_BANK"], graph, {})
    assert alloc["slots"]["FP-3"]["level"] == "sub", "stop_at_parent must get the parent"
    assert alloc["slots"]["FP-5"]["level"] == "group", "under_determined must get the group"
    assert alloc["slots"]["FP-3"]["num"] == "0010"


def test_no_rival_is_used_for_two_slots(cfg, tax):
    graph = taxmod.confusion_graph(cfg, tax)
    alloc = taxmod.allocate(cfg, tax, tax.by_code["PAID_BANK"], graph, {})
    nums = [s["num"] for s in alloc["slots"].values()]
    assert len(nums) == len(set(nums))


def test_a_singleton_sub_declares_stop_at_parent_degenerate(cfg, tax):
    graph = taxmod.confusion_graph(cfg, tax)
    alloc = taxmod.allocate(cfg, tax, tax.by_code["ASSURED_ADVISOR"], graph, {})
    assert alloc["singleton_sub"] is True
    assert any("degenerate" in n for n in alloc["notes"])
    # FP-3 falls back rather than silently going unfilled.
    assert "FP-3" not in alloc["slots"] or alloc["slots"]["FP-3"]["level"] != "sub"


def test_empirical_confusion_outranks_a_merely_documented_rival(cfg, tax):
    graph = taxmod.confusion_graph(cfg, tax)
    emp = {"0011": [{"other": "0072", "evidence": "engine actually confused these"}]}
    alloc = taxmod.allocate(cfg, tax, tax.by_code["PAID_BANK"], graph, emp)
    assert alloc["slots"]["FP-1"]["tier"] == "empirical"


def test_a_renamed_column_names_itself_in_the_error(repo):
    import openpyxl
    p = repo / "context" / "tax.xlsx"
    wb = openpyxl.load_workbook(p)
    ws = wb["Disposition Master"]
    ws.cell(row=1, column=8).value = "Renamed Code Column"
    wb.save(p)
    with pytest.raises(ValueError) as e:
        taxmod.load(Config.load("testco", repo))
    assert "Engine Code (rules_json key)" in str(e.value)
    assert "Renamed Code Column" in str(e.value), "the error must list the actual headers"
