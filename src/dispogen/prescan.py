"""Static ambiguity pre-scan (milestone M0).

Pure text analysis over the taxonomy plus the annotated corpus. No model, no
spend. Its exit criterion on the reference client is that it independently
surfaces the contested gold rows without being told which they are.

Nine classes, A-I. Each finding names the clauses that collide, so it is
actionable by whoever owns the taxonomy rather than being an observation.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from .config import Config
from .taxonomy import Taxonomy, norm_label

CLASSES = {
    "A": "Definitional gap - evidence clear, no leaf covers it",
    "B": "Level ambiguity - sub certain, leaf under-determined",
    "C": "Label / parent collision",
    "D": "Source-of-truth conflict",
    "E": "Unranked co-occurrence",
    "F": "Evidence insufficiency",
    "G": "Cross-call gating",
    "H": "Annotation conflict - human gold vs written rules",
    "I": "Degenerate leaf",
}

_NOT_CLAUSE = re.compile(r"NOT [\w]{2,6}:([^\n]+)")
_QUOTED = re.compile(r"[\"']([^\"']{4,60})[\"']")


def run(cfg: Config, tax: Taxonomy, graph: dict, annotations: list[dict]) -> list[dict]:
    rx = re.compile(cfg.get("taxonomy.code_regex"))
    leaf_nums = {l.num for l in tax.leaves}
    out: list[dict] = []

    def add(cls, subject, detail, impact, **extra):
        out.append({"class": cls, "class_name": CLASSES[cls], "subject": subject,
                    "detail": detail, "impact": impact, **extra})

    # --- C: a numeric label reused across levels, or a sub under two groups
    sub_counts = Counter(norm_label(s) for (_, s) in tax.subs)
    for (g, s) in tax.subs:
        n = norm_label(s)
        if n in leaf_nums:
            add("C", n, f"numeric label {n!r} is BOTH sub {s!r} (group {g}) and a leaf",
                "keying by numeric label cross-wires context packs")
    for n, c in sub_counts.items():
        if c > 1:
            add("C", n, f"sub label {n!r} exists under {c} groups: {tax.sub_owners(n)}",
                "parent resolution is ambiguous; rival pointers may cross groups")

    # --- I: degenerate leaves
    kids = defaultdict(list)
    for l in tax.leaves:
        kids[(l.group, l.sub)].append(l.num)
    for k, v in kids.items():
        if len(v) == 1:
            add("I", v[0], f"sub {k[1]!r} has exactly one child",
                "stop-at-parent probe carries zero information; substitute required")
    for l in tax.leaves:
        hay = (l.engineering_note + " " + l.decision_rules).lower()
        if "catch-all" in hay or "last resort" in hay:
            add("I", l.num, "declared catch-all / last-resort leaf",
                "over-selection is itself the bug under test; cap generation")

    # --- G: modalities the primary signal cannot decide
    for l in tax.leaves:
        if l.source_of_truth_class == "cross-call":
            add("G", l.num, "requires prior-attempt metadata; not derivable from one transcript",
                "single-transcript classifier must be structurally blocked")

    # --- D: source-of-truth conflicts the rules declare
    for l in tax.leaves:
        if "SOURCE OF TRUTH" in l.decision_rules and re.search(
                r"customer('s)? (claim|assertion|opinion|speech)", l.decision_rules, re.I):
            add("D", l.num, "rules declare system status wins over customer assertion",
                "transcript-only classification can never confirm this leaf")

    # --- A: a sub's exclusion routes outside its own child set
    for (g, s), desc in tax.subs.items():
        own = {l.num for l in tax.leaves if l.sub == s and l.group == g}
        for m in _NOT_CLAUSE.finditer(desc or ""):
            txt = m.group(1)
            outs = [x if isinstance(x, str) else x[0] for x in rx.findall(txt)]
            if outs and all(o not in own for o in outs):
                add("A", norm_label(s),
                    f"sub-level exclusion routes outside its own leaf set: {txt.strip()[:140]!r}",
                    "evidence matching this shape has no leaf inside this sub")

    # --- B: leaves whose parent declares a stop-at-parent rule
    for l in tax.leaves:
        if "STOP AT" in (tax.subs.get((l.group, l.sub), "") or ""):
            add("B", l.num, f"parent {l.sub!r} declares a stop-at-parent rule",
                "leaf-level expectation is unsafe unless the channel is explicitly named")

    # --- H: contested gold. Runs blind — it is not told which rows are suspect.
    for a in annotations:
        claim = str(a["human_claim"])
        codes = {x if isinstance(x, str) else x[0] for x in rx.findall(claim)}
        reasons = []
        if not codes:
            reasons.append("human label names no resolvable disposition code")
        if len(codes) > 1:
            reasons.append(f"human label names {len(codes)} codes: {sorted(codes)}")
        if re.search(r"\bor\b|closest|better fit|no specific reason|and also", claim, re.I):
            reasons.append("human label is hedged or internally unresolved")
        for c in codes:
            if c in leaf_nums:
                tgt = tax.by_num[c]
                pdesc = tax.subs.get((tgt.group, tgt.sub), "") or ""
                for m in _NOT_CLAUSE.finditer(pdesc):
                    clause = m.group(1)
                    for kk in _QUOTED.findall(clause):
                        if kk.lower() in claim.lower():
                            reasons.append(
                                f"target {c}'s own sub excludes this shape: "
                                f"'NOT {tgt.sub_num}:{clause.strip()[:120]}'")
            else:
                owners = tax.sub_owners(c)
                if len(owners) > 1:
                    reasons.append(f"human label names only sub {c!r}, which exists under "
                                   f"{len(owners)} groups {owners} -- the branch is unresolved")
        if reasons:
            add("H", f"{a['source_sheet']}#{a['source_row']}", " ; ".join(reasons),
                "pinning this row as ground truth injects a contested label",
                engine_label=a["engine_label"], human_claim=claim[:400])
    return out


def summary(findings: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(f["class"] for f in findings).items()))
