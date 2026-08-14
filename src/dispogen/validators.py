"""Deterministic validation, V1-V16. No model runs here.

V11 (rule-trace integrity) and V16 (PII containment) are the two that gate
release. V11 is the only check that can catch a plausible-sounding label no
written rule licenses, because it is a string operation over the source text
rather than a judgement — which is also why it survives blind spots that every
model in a panel might share.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from .config import Config
from .deidentify import Deidentifier
from .taxonomy import Taxonomy

DT_RE = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{2}) "
                   r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{4}), (\d{2}):(\d{2})")
MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def nfc(s: Any) -> str:
    return unicodedata.normalize("NFC", str(s))


def _dt(s: str):
    m = DT_RE.search(str(s))
    return None if not m else (int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)),
                               int(m.group(4)), int(m.group(5)))


def _transcript_text(case: dict) -> str:
    return "\n".join(t.get("text", "") for t in case.get("transcript", []) or [])


def _trigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", nfc(s).lower()))
    return {s[i:i + 3] for i in range(max(0, len(s) - 2))}


def validate(cfg: Config, tax: Taxonomy, doc: dict, pack: dict,
             deid: Deidentifier | None = None) -> list[str]:
    errs: list[str] = []
    code = doc["engine_code"]
    leaf = tax.by_code[code]
    cases = doc.get("cases", [])
    all_nums = ({l.num for l in tax.leaves} | tax.sub_nums()
                | {l.group_code for l in tax.leaves}
                | {cfg.get("taxonomy.abstention_code", "NEEDS_HUMAN_REVIEW")}
                | {c.get("expected_group", "") for c in cases})
    fn_n = cfg.get("quota.fn_probes")
    fp_n = cfg.get("quota.fp_probes")
    order = cfg.get("inputs.output_format.probe_order", ["FP", "FN"])
    window = cfg.get("inputs.redial_matrix.calling_window", {"start": "09:00", "end": "21:00"})
    w_lo, w_hi = int(window["start"][:2]), int(window["end"][:2])

    def E(v, cid, msg):
        errs.append(f"[{v}] {cid}: {msg}")

    # ---- V2 quota + ordering (the output contract's SN ordering is client config)
    fns = [c for c in cases if c["probe_type"] == "FN"]
    fps = [c for c in cases if c["probe_type"] == "FP"]
    if not (len(cases) == fn_n + fp_n and len(fns) == fn_n and len(fps) == fp_n):
        E("V2", code, f"expected {fn_n}FN/{fp_n}FP, got {len(fns)}FN/{len(fps)}FP")
    if [c.get("sn") for c in cases] != list(range(1, len(cases) + 1)):
        E("V2", code, "SN must run 1..N contiguously")
    want = [order[0]] * (fp_n if order[0] == "FP" else fn_n) + \
           [order[1]] * (fn_n if order[1] == "FN" else fp_n)
    if [c["probe_type"] for c in cases] != want:
        E("V2", code, f"output contract orders probes {order}; got a different sequence")

    seen_slots = set()
    for c in cases:
        cid = c.get("test_case_id", "?")
        tx = _transcript_text(c)

        # ---- V3 polarity
        if c["probe_type"] == "FN" and c.get("expected_expanded") != leaf.label:
            E("V3", cid, f"FN must expect {leaf.label!r}, got {c.get('expected_expanded')!r}")
        if c["probe_type"] == "FP":
            if c.get("expected_expanded") == leaf.label:
                E("V3", cid, "FP must not expect the host disposition")
            if leaf.num not in c.get("must_not_select", []):
                E("V3", cid, f"FP must_not_select must contain the host code {leaf.num}")

        # ---- V4 code resolution
        for r in [c.get("rival_code")] + list(c.get("must_not_select", [])) + \
                 [x["code"] for x in c.get("rebutted_rivals", [])]:
            if r and r not in all_nums:
                E("V4", cid, f"unknown code referenced: {r}")

        # ---- V5 pinned allocation
        if c["probe_type"] == "FP":
            slot = c.get("slot")
            pin = next((a for a in pack["quota"]["fp_allocation"] if a["slot"] == slot), None)
            if pin is None:
                E("V5", cid, f"slot {slot} not in the pinned allocation")
            else:
                if c.get("rival_code") != pin["rival_num"]:
                    E("V5", cid, f"slot {slot} pinned to {pin['rival_num']}, "
                                 f"case used {c.get('rival_code')}")
                if c.get("archetype") != pin["archetype"]:
                    E("V5", cid, f"slot {slot} archetype pinned {pin['archetype']}, "
                                 f"case used {c.get('archetype')}")
            if slot in seen_slots:
                E("V5", cid, f"duplicate slot {slot}")
            seen_slots.add(slot)

        # ---- V6 source-of-truth conformance
        soc = pack["source_of_truth_class"]
        toks = set(pack.get("token_vocabulary", []))
        if soc == "transcript":
            subst = [t for t in c.get("transcript", [])
                     if t.get("speaker") == "customer" and t.get("text") not in toks]
            if not subst:
                E("V6", cid, "transcript-class case needs >=1 substantive customer turn")
        if soc in ("telephony", "system") and c.get("transcript"):
            E("V6", cid, f"{soc}-class case must carry no transcript")

        # ---- V7 re-dial validity
        rd = c.get("redial", {}) or {}
        if not str(rd.get("context", "")).strip():
            E("V7", cid, "carry-forward context is empty")
        if not str(rd.get("basis", "")).strip():
            E("V7", cid, "redial basis (seeded vs derived) not declared")
        a, s = _dt(rd.get("anchor_date", "")), _dt(rd.get("schedule", ""))
        if s:
            if not (w_lo <= s[3] < w_hi):
                E("V7", cid, f"callback {s[3]:02d}:{s[4]:02d} outside "
                             f"{window['start']}-{window['end']}")
            if a and s <= a:
                E("V7", cid, "callback not strictly after the anchor")
        req = str(rd.get("is_required", "")).lower()
        if req.startswith("yes") and not s:
            E("V7", cid, "callback required but no parseable datetime")

        # ---- V9 trap completeness
        if c["probe_type"] == "FP":
            for k in ("rival_code", "trap_phrase", "decisive_evidence"):
                if not c.get(k):
                    E("V9", cid, f"missing {k}")
            tp = nfc(c.get("trap_phrase") or "")
            if tp and tp not in nfc(tx):
                E("V9", cid, f"trap_phrase not present in transcript: {tp!r}")

        # ---- V10 compliance rails (client-configured)
        agent_tx = " ".join(t.get("text", "") for t in c.get("transcript", [])
                            if t.get("speaker") == "agent")
        for chk in cfg.get("compliance_checks", []) or []:
            if re.search(chk["pattern"], agent_tx):
                E("V10", cid, f"{chk['id']}: {chk['why']}")

        # ---- V11 rule-trace integrity  <- the zero-FP gate
        cl = nfc(c.get("cited_clause") or "")
        if not cl:
            E("V11", cid, "cited_clause missing")
        elif cl not in nfc(tax.corpus):
            E("V11", cid, f"cited_clause NOT verbatim in taxonomy: {cl!r}")
        de = nfc(c.get("decisive_evidence") or "")
        if not de:
            E("V11", cid, "decisive_evidence missing")
        elif de not in nfc(tx):
            E("V11", cid, f"decisive_evidence NOT verbatim in transcript: {de!r}")
        if not c.get("rebutted_rivals"):
            E("V11", cid, "no rebutted_rivals -- every case must rebut its nearest rivals")
        for r in c.get("rebutted_rivals", []):
            rc = nfc(r.get("clause") or "")
            if not rc or rc not in nfc(tax.corpus):
                E("V11", cid, f"rebuttal clause for {r.get('code')} NOT verbatim: {rc!r}")
            if not str(r.get("why", "")).strip():
                E("V11", cid, f"rebuttal for {r.get('code')} has no reasoning")

        # ---- V12 token vocabulary
        for bad in cfg.get("tokens.documented_but_not_produced", []) or []:
            if bad in tx:
                E("V12", cid, f"non-production token {bad!r}; production emits "
                              f"{pack.get('token_vocabulary')}")

        # ---- V13 grade coherence
        g = c.get("declared_grade")
        if g == "EXPANDED" and not c.get("expected_expanded"):
            E("V13", cid, "EXPANDED grade requires expected_expanded")
        if g == "SUB" and (c.get("expected_expanded") or not c.get("expected_sub")):
            E("V13", cid, "SUB grade requires expected_sub and a null expected_expanded")
        if g == "GROUP" and (c.get("expected_expanded") or c.get("expected_sub")):
            E("V13", cid, "GROUP grade requires null expected_sub and expected_expanded")
        if not c.get("expected_group"):
            E("V13", cid, "expected_group is mandatory at every grade")
        if c.get("expected_expanded"):
            tgt = next((l for l in tax.leaves if l.label == c["expected_expanded"]), None)
            if not tgt:
                E("V13", cid, f"expected_expanded not a taxonomy label: {c['expected_expanded']!r}")
            else:
                if tgt.sub != c.get("expected_sub"):
                    E("V13", cid, "expected_sub is not the parent of expected_expanded")
                if tgt.group != c.get("expected_group"):
                    E("V13", cid, "expected_group is not the grandparent of expected_expanded")

        # ---- V14 precedence conformance
        pr = c.get("precedence_rule_applied")
        if pr:
            rule = next((p for p in pack["precedence_ladder"] if p["id"] == pr), None)
            if not rule:
                E("V14", cid, f"unknown precedence rule {pr}")
            elif rule["anchor"] not in tax.corpus:
                E("V14", cid, f"precedence anchor for {pr} no longer resolves in the taxonomy")

        # ---- V15 paraphrase purity
        if c.get("archetype") == "paraphrased_trigger":
            for phrase in re.findall(r'"([^"]+)"', leaf.decision_rules):
                if nfc(phrase.lower()) in nfc(tx.lower()):
                    E("V15", cid, f"paraphrase probe must avoid listed triggers, found {phrase!r}")

        # ---- V16 PII containment  <- release gate
        if deid and cfg.get("deidentify.enabled", True):
            for hit in deid.report(c):
                E("V16", cid, f"real {hit['kind'][:-1]} from the source corpus present "
                              f"in a generated case: {hit['value']!r}")

    # ---- V8 intra-disposition near-duplicates
    for i in range(len(cases)):
        for j in range(i + 1, len(cases)):
            a, b = _trigrams(_transcript_text(cases[i])), _trigrams(_transcript_text(cases[j]))
            if a and b:
                sim = len(a & b) / len(a | b)
                if sim > 0.82:
                    E("V8", f"{cases[i]['test_case_id']} ~ {cases[j]['test_case_id']}",
                      f"near-duplicate transcripts, Jaccard trigram = {sim:.3f}")
    return errs


def lint_learnings(cfg: Config, text: str) -> list[dict]:
    """Domain-leak lint. Keeps learnings portable to the next onboarding."""
    banned = [rf"\b{re.escape(t)}\b" for t in cfg.get("domain_terms", []) or []]
    banned += [cfg.get("taxonomy.code_regex"), r"[ऀ-ॿ]"]
    banned += cfg.get("learnings.banned_patterns_extra", []) or []
    hits = []
    lines = text.splitlines()
    for pat in banned:
        for m in re.finditer(pat, text):
            ln = text[:m.start()].count("\n")
            hits.append({"pattern": pat, "line": ln + 1,
                         "text": lines[ln].strip()[:100] if ln < len(lines) else ""})
    return hits
