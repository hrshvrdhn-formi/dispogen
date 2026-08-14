"""Shared fixtures.

The suite builds its own two-group taxonomy workbook rather than reading the
client corpus. That corpus is git-ignored real customer data, so a test that
depends on it fails on every clone but the author's — and the behaviour under
test is the pipeline, not the client.
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pytest
import yaml

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dispogen.config import Config  # noqa: E402

TAX_HEADERS = ["Group Disposition", "Group Disposition Description",
               "Sub Disposition", "Sub Disposition Description",
               "Expanded Disposition", "Expanded Disposition Description",
               "Decision Rules - Triggers / Exclusions / Tie-breakers",
               "Engine Code (rules_json key)", "Engineering Note / Risk"]

# Group / sub cells are blank on continuation rows, exactly as a real taxonomy
# sheet is authored — forward-fill is behaviour under test, not a convenience.
TAX_ROWS = [
    ["CTP - Committed to Pay", "Customer committed to pay.",
     "0010 - Payment Made", "Payment already made.",
     "0011 - Paid via Bank", "Paid through the bank channel.",
     'Trigger: "bank mein jama". Exclusion: NOT THIS if 0012 applies. '
     'NOT THIS if the call never connected, see 0072. Compare 0013.', "PAID_BANK", ""],
    ["", "", "", "",
     "0012 - Paid at Branch", "Paid at a branch counter.",
     'Trigger: "branch mein jama". NOT THIS: promise to pay later.', "PAID_BRANCH", ""],
    ["", "", "", "",
     "0013 - Paid Online", "Paid through the web portal.",
     'Trigger: "website se kiya". NOT THIS if a counter was visited.', "PAID_ONLINE", ""],
    ["", "", "0020 - Payment Commitment", "Customer promises to pay.",
     "0022 - Assured to pay to Advisor", "Will hand payment to the advisor.",
     'Trigger: "agent ko denge". Exclusion: NOT THIS if already paid, see 0011.',
     "ASSURED_ADVISOR", ""],
    ["NC - Not Connected", "Call did not reach the policyholder.",
     "0070 - Telephony", "Network-level outcome.",
     "0072 - Switched Off", "Handset switched off.",
     "Determined by telephony disposition, not by anything said.", "SWITCHED_OFF",
     "cross-call code may override"],
]

DEFAULT_YAML = Path(__file__).resolve().parents[1] / "config" / "default.yaml"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal but complete repo root: defaults, a client config, a taxonomy."""
    (tmp_path / "config" / "clients").mkdir(parents=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "config" / "default.yaml").write_text(
        DEFAULT_YAML.read_text(encoding="utf-8"), encoding="utf-8")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Disposition Master"
    ws.append(TAX_HEADERS)
    for r in TAX_ROWS:
        ws.append(r)
    of = wb.create_sheet("Output Format")
    of.append(["SN", "Type", "Scenario", "Transcript", "Expected Disposition"])
    wb.save(tmp_path / "context" / "tax.xlsx")

    client = {
        "client": {"name": "testco", "anchor": "Tue 07 Jul 2026, 14:32"},
        "inputs": {
            "taxonomy": {
                "path": "context/tax.xlsx", "sheet": "Disposition Master",
                "columns": {
                    "group": "Group Disposition",
                    "group_desc": "Group Disposition Description",
                    "sub": "Sub Disposition", "sub_desc": "Sub Disposition Description",
                    "expanded": "Expanded Disposition",
                    "expanded_desc": "Expanded Disposition Description",
                    "decision_rules": "Decision Rules - Triggers / Exclusions / Tie-breakers",
                    "engine_code": "Engine Code (rules_json key)",
                    "engineering_note": "Engineering Note / Risk"},
                "forward_fill": ["group", "group_desc", "sub", "sub_desc"]},
            "output_format": {"path": "context/tax.xlsx", "sheet": "Output Format",
                              "probe_order": ["FP", "FN"]},
            "redial_matrix": {"calling_window": {"start": "09:00", "end": "21:00"}},
        },
        "taxonomy": {
            "code_regex": r"\b(0[0-9][0-9A-F]{2})\b",
            "source_of_truth_rules": [{"match": "telephony", "class": "telephony"},
                                      {"match": "cross-call code", "class": "cross-call"}],
        },
        "precedence": [{"id": "P1", "rule": "Completed payment outranks a promise.",
                        "anchor": "NOT THIS: promise to pay later"}],
        "deidentify": {"pools": {"givens_deva": ["Aarav"], "surnames_deva": ["Mehta"],
                                 "policy_prefix": "09", "phone_prefix": "70000"}},
        "domain_terms": ["persistency"],
    }
    (tmp_path / "config" / "clients" / "testco.yaml").write_text(
        yaml.safe_dump(client, allow_unicode=True), encoding="utf-8")
    return tmp_path


@pytest.fixture
def cfg(repo: Path) -> Config:
    return Config.load("testco", repo)


@pytest.fixture
def tax(cfg):
    from dispogen import taxonomy as taxmod
    return taxmod.load(cfg)
