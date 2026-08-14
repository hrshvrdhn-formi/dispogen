"""Phase 5 — the certification tribunal (Gate D).

Majority vote produces a label for every case, including the ones the written
rules do not decide. That is the wrong instrument here: the failure we are hunting
is a confident answer that no clause licenses, and a vote launders exactly that
into consensus. So the panel runs blind and must be **unanimous**, dissent demotes
the grade rather than overriding it, and an adversarial advocate gets the last
word with full sight of the answer.

A case that cannot survive this is not deleted — it is recorded, because a case
the panel cannot agree on is a finding about the taxonomy, not a bad test.
"""
from __future__ import annotations

import json
from typing import Any

from .config import Config
from .providers import build as build_provider
from .taxonomy import Taxonomy

GRADES = ["EXPANDED", "SUB", "GROUP"]

# Fields that would tell a "blind" critic the answer. Stripping the obvious ones
# is not enough: `slot`, `archetype` and `rival_code` name the construction, and
# `scenario` is written from the author's point of view.
BLINDED = {"declared_grade", "expected_group", "expected_sub", "expected_expanded",
           "must_not_select", "rival_code", "trap_phrase", "decisive_evidence",
           "cited_clause", "rebutted_rivals", "precedence_rule_applied",
           "probe_type", "slot", "archetype", "scenario", "test_case_id",
           "perturbations"}


def blind_view(case: dict) -> dict:
    """What a critic sees: the call, and nothing about why it was written."""
    return {k: v for k, v in case.items() if k not in BLINDED}


def trace_view(case: dict) -> dict:
    return {k: v for k, v in case.items() if k in BLINDED}


def taxonomy_view(tax: Taxonomy) -> dict:
    """The full taxonomy, not a shortlist.

    Handing the critic the host and its rivals is a multiple-choice question with
    the answer in the options. The point of the blind pass is that the critic has
    to find the leaf in the same space the production grader searches.
    """
    return {
        "groups": [{"label": g, "description": d} for g, d in tax.groups.items()],
        "subs": [{"group": g, "label": s, "description": d}
                 for (g, s), d in tax.subs.items()],
        "expanded": [{"label": l.label, "group": l.group, "sub": l.sub,
                      "description": l.description, "decision_rules": l.decision_rules,
                      "source_of_truth_class": l.source_of_truth_class}
                     for l in tax.leaves],
    }


def split_at(template: str, marker: str) -> tuple[str, str]:
    """Split a rendered prompt into a cacheable prefix and the per-case tail.

    Everything before `marker` — instructions plus the whole taxonomy — is
    identical for every case and every critic. Sending it uncached on a full run
    costs more than the generation it is checking.
    """
    i = template.find(marker)
    return (template, "") if i < 0 else (template[:i], template[i:])


def _json(text: str) -> Any:
    """Tolerate a fenced or prose-wrapped object without silently accepting junk."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```")[1] if "```" in t[3:] else t[3:]
        t = t.split("\n", 1)[1] if t[:4].lower().startswith("json") else t
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None


def _agrees(v: dict | None, case: dict) -> tuple[bool, str]:
    """Does one critic's verdict match what the author claimed?"""
    if not v:
        return False, "unparseable verdict"
    g = v.get("grade")
    if g == "ABSTAIN":
        return False, f"abstained: {v.get('ambiguity') or 'no reason given'}"
    if g != case.get("declared_grade"):
        return False, f"graded {g}, case declares {case.get('declared_grade')}"
    for field, key in (("expected_group", "group"), ("expected_sub", "sub"),
                       ("expected_expanded", "expanded")):
        want, got = case.get(field), v.get(key)
        if (want or None) != (got or None):
            return False, f"{key}: {got!r} != {want!r}"
    return True, "agrees"


def demote(grade: str) -> str | None:
    i = GRADES.index(grade) if grade in GRADES else -1
    return GRADES[i + 1] if 0 <= i < len(GRADES) - 1 else None


def run(cfg: Config, tax: Taxonomy, doc: dict, provider: str | None = None) -> list[dict]:
    """Certify every case in one disposition document. Returns the log entries."""
    crit_tmpl = (cfg.root / "prompts" / "critic.md").read_text(encoding="utf-8")
    adv_tmpl = (cfg.root / "prompts" / "advocate.md").read_text(encoding="utf-8")
    tax_blob = json.dumps(taxonomy_view(tax), ensure_ascii=False, indent=1)
    panel = [{**p, **({"provider": provider} if provider else {})}
             for p in cfg.get("models.critic_panel")]
    # Pair each panel seat with a lens. Where the panel is one model repeated,
    # the lens is the only thing making the seats different from each other.
    lenses = cfg.get("certification.critic_lenses", []) or [{"id": "default", "instruction": ""}]
    seats = [(p, lenses[i % len(lenses)]) for i, p in enumerate(panel)]
    if len({p.get("model") for p in panel}) == 1 and len(panel) > 1:
        log_note = (f"panel is {len(panel)}x {panel[0].get('model')} differing only by lens "
                    f"— weaker than cross-vendor; unanimity here is not model-independent")
    else:
        log_note = ""
    unanimous = cfg.get("certification.require_unanimous", True)
    do_demote = cfg.get("certification.demote_on_dissent", True)

    log = []
    for case in doc.get("cases", []):
        cid = case.get("test_case_id", "?")
        call = json.dumps(blind_view(case), ensure_ascii=False, indent=1)
        prefix, tail = split_at(
            crit_tmpl.replace("{{TAXONOMY}}", tax_blob).replace("{{CALL}}", call),
            "## Call")
        verdicts = []
        for i, (spec, lens) in enumerate(seats):
            spec = {**spec, "label": f"{cid}.critic{i}.{lens['id']}"}
            out = build_provider(spec).complete(
                system=("You grade calls against a written taxonomy. You refuse when "
                        "the rules do not decide.\n\n" + (lens.get("instruction") or "")).strip(),
                user=tail, cache_prefix=prefix,
                max_tokens=spec.get("max_tokens"), effort=spec.get("effort"))
            seat = {"model": out.model, "lens": lens["id"]}
            if out.provider == "dryrun":
                verdicts.append({**seat, "verdict": None,
                                 "note": out.usage.get("prompt_written_to")})
                continue
            if out.refused:
                verdicts.append({**seat, "verdict": None,
                                 "note": f"refused: {out.refusal_category}"})
                continue
            verdicts.append({**seat, "verdict": _json(out.text)})

        if all(v["verdict"] is None for v in verdicts):
            log.append({"test_case_id": cid, "status": "NOT_RUN",
                        "reason": "no panel verdicts (dry-run or no credentials)",
                        "panel": verdicts})
            continue

        checks = [_agrees(v["verdict"], case) for v in verdicts if v["verdict"]]
        dissent = [why for ok, why in checks if not ok]
        status, grade = "CERTIFIED", case.get("declared_grade")
        if dissent and unanimous:
            grade = demote(case.get("declared_grade", "")) if do_demote else None
            status = "DEMOTED" if grade else "EXILED"

        # The advocate runs on cases the panel accepted. A case the panel already
        # broke goes to the register as-is; re-attacking it adds nothing.
        adv = None
        if status == "CERTIFIED":
            spec = {**dict(cfg.get("models.advocate")), "label": f"{cid}.advocate"}
            if provider:
                spec["provider"] = provider
            a_prefix, a_tail = split_at(
                (adv_tmpl.replace("{{TAXONOMY}}", tax_blob)
                 .replace("{{CASE}}", json.dumps(blind_view(case), ensure_ascii=False, indent=1))
                 .replace("{{TRACE}}", json.dumps(trace_view(case), ensure_ascii=False, indent=1))),
                "## Case under review")
            out = build_provider(spec).complete(
                system="You are an adversarial reviewer. Assume the case is wrong.",
                user=a_tail, cache_prefix=a_prefix,
                max_tokens=spec.get("max_tokens"), effort=spec.get("effort"))
            adv = _json(out.text) if out.provider != "dryrun" else None
            if adv and adv.get("verdict") != "SUSTAINED":
                sev = {f.get("severity") for f in adv.get("findings", [])}
                if adv.get("verdict") == "CONTAMINATED" or "blocking" in sev:
                    status = "EXILED"
                elif adv.get("proposed_remedy") == "demote_grade" and do_demote:
                    grade = adv.get("demote_to") or demote(grade or "")
                    status = "DEMOTED" if grade else "EXILED"
                else:
                    status = "REGENERATE"

        log.append({"test_case_id": cid, "status": status,
                    "declared_grade": case.get("declared_grade"),
                    "certified_grade": grade, "dissent": dissent,
                    "panel": verdicts, "advocate": adv,
                    "panel_caveat": log_note})
    return log


def summary(log: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in log:
        out[e["status"]] = out.get(e["status"], 0) + 1
    return out
