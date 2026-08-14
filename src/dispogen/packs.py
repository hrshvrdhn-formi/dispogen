"""Phase 1 step 5 — pack assembly.

Each pack is sufficient on its own: a generator given a pack needs no repository
access, no lookups, no shared state. That is what makes the fan-out safe and what
keeps every branch under a fixed token budget regardless of corpus size.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import corpus, taxonomy as taxmod
from .config import Config
from .taxonomy import Taxonomy


def build_all(cfg: Config, tax: Taxonomy, only: list[str] | None = None) -> dict[str, dict]:
    graph = taxmod.confusion_graph(cfg, tax)
    ladder, _ = taxmod.precedence(cfg, tax)
    annotations = (corpus.mine_annotations(cfg)
                   if cfg.optional_path("inputs.interaction_report.path") else [])
    emp = corpus.empirical_pairs(cfg, annotations)
    seeds = corpus.redial_seeds(cfg)
    from .preflight import _token_vocab
    vocab = sorted(_token_vocab(cfg))

    targets = [tax.by_code[c] for c in only] if only else tax.leaves
    out = {}
    for leaf in targets:
        alloc = taxmod.allocate(cfg, tax, leaf, graph, emp)
        rivals = []
        for r in alloc["rivals"]:
            tgt = tax.by_num.get(r["num"])
            if tgt:
                definition, rules, label = tgt.description, tgt.decision_rules, tgt.label
            elif r["level"] == "sub":
                key = next(((g, s) for (g, s) in tax.subs
                            if taxmod.norm_label(s) == r["num"] and g == leaf.group),
                           next(((g, s) for (g, s) in tax.subs
                                 if taxmod.norm_label(s) == r["num"]), None))
                definition, rules = (tax.subs.get(key, ""), "")
                label = key[1] if key else r["num"]
            else:
                definition, rules = tax.groups.get(leaf.group, ""), ""
                label = leaf.group
            # A rival's own group/sub, so a case can state expected_group and
            # expected_sub without a taxonomy lookup. V13 checks the triple is
            # coherent; a generator holding only the rival's label cannot satisfy it.
            if tgt:
                r_group, r_sub = tgt.group, tgt.sub
            elif r["level"] == "sub":
                r_group, r_sub = leaf.group, label
            else:
                r_group, r_sub = leaf.group, None
            rivals.append({**r, "label": label, "definition": definition,
                           "their_rules": rules,
                           "their_group": r_group, "their_sub": r_sub,
                           "redial_seed": seeds.get(r["num"], [])[:1]})

        pack = {
            "engine_code": leaf.engine_code,
            "label": leaf.label,
            "group": {"code": leaf.group_code, "label": leaf.group,
                      "description": tax.groups.get(leaf.group, "")},
            "sub": {"num": leaf.sub_num, "label": leaf.sub,
                    "description": tax.subs.get((leaf.group, leaf.sub), "")},
            "expanded_description": leaf.description,
            "decision_rules": leaf.decision_rules,
            "engineering_note": leaf.engineering_note,
            "source_of_truth_class": leaf.source_of_truth_class,
            "singleton_sub": alloc["singleton_sub"],
            "sibling_set": [s.num for s in tax.siblings(leaf)],
            "rivals": rivals,
            "quota": {
                "fn_probes": cfg.get("quota.fn_probes"),
                "fp_probes": cfg.get("quota.fp_probes"),
                "fn_archetypes": cfg.get("quota.fn_archetypes"),
                "fp_allocation": [
                    {"slot": s["slot"], "archetype": alloc["slots"][s["slot"]]["role"],
                     "rival_num": alloc["slots"][s["slot"]]["num"],
                     "rival_code": alloc["slots"][s["slot"]]["engine_code"],
                     "tier": alloc["slots"][s["slot"]]["tier"],
                     "level": alloc["slots"][s["slot"]]["level"],
                     "why": alloc["slots"][s["slot"]]["why"]}
                    for s in cfg.get("quota.fp_slots") if s["slot"] in alloc["slots"]],
                "shortfall": alloc["shortfall"],
                "allocation_notes": alloc["notes"],
            },
            "precedence_ladder": ladder,
            "token_vocabulary": vocab,
            "redial_seeds": seeds.get(leaf.num, []),
            "anchor": cfg.get("client.anchor"),
            # Everything `validate` enforces that is not derivable from the
            # taxonomy. Without these the generator writes cases that cannot
            # pass V2/V7/V10/V12 and has no way to know why.
            "contract": {
                "probe_order": cfg.get("inputs.output_format.probe_order", ["FP", "FN"]),
                "calling_window": cfg.get("inputs.redial_matrix.calling_window",
                                          {"start": "09:00", "end": "21:00"}),
                "forbidden_agent_patterns": [
                    {"id": c["id"], "pattern": c["pattern"], "why": c["why"]}
                    for c in cfg.get("compliance_checks", []) or []],
                "non_production_tokens": cfg.get("tokens.documented_but_not_produced", []) or [],
                "abstention_code": cfg.get("taxonomy.abstention_code", "NEEDS_HUMAN_REVIEW"),
                # Internal roles, not client vocabulary. Decoders normalise every
                # client's own speaker labels onto these two before anything reads them.
                "speaker_roles": ["agent", "customer"],
            },
            "citable_clause_sources": {
                "leaf_rules": leaf.decision_rules,
                "leaf_description": leaf.description,
                "sub_description": tax.subs.get((leaf.group, leaf.sub), ""),
                "group_description": tax.groups.get(leaf.group, ""),
            },
        }
        pack["pack_hash"] = hashlib.sha256(
            json.dumps(pack, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        out[leaf.engine_code] = pack
    return out


def write(cfg: Config, packs: dict[str, dict]) -> Path:
    d = cfg.workdir("compiled", "packs")
    for code, pack in packs.items():
        (d / f"{code}.json").write_text(
            json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    return d
