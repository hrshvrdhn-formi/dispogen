"""Script normalisation — romanised Hindi to Devanagari, in place.

This runs over finished cases rather than regenerating them, because the cases
are already validated and certified work; only their script is wrong.

The hard part is not the conversion. It is that `decisive_evidence` and
`trap_phrase` are verbatim substrings of the transcript, enforced by V9 and V11
as exact containment. Rewriting the transcript without rewriting those spans in
lockstep silently invalidates every case it touches. So each case is verified
locally after conversion and reverted if the spans no longer resolve — a case
that keeps its Latin script is a cosmetic defect, one whose rule-trace no longer
resolves is a broken test.
"""
from __future__ import annotations

import json
import re
import unicodedata

DEVA = re.compile(r"[ऀ-ॿ]")
# Latin letters that are not inside an XML-ish production marker.
LATIN = re.compile(r"[A-Za-z]")


def has_latin_outside_markers(text: str) -> bool:
    stripped = re.sub(r"<[^>]*>|\[[^\]]*\]", " ", text or "")
    return bool(LATIN.search(stripped))


def needs_work(doc: dict) -> bool:
    return any(has_latin_outside_markers(t.get("text", ""))
               for c in doc.get("cases", []) for t in c.get("transcript", []) or [])


def deva_ratio(doc: dict) -> float:
    """Share of letters in transcripts that are Devanagari. Progress, not a gate."""
    d = n = 0
    for c in doc.get("cases", []):
        for t in c.get("transcript", []) or []:
            s = re.sub(r"<[^>]*>|\[[^\]]*\]", " ", t.get("text", ""))
            d += len(DEVA.findall(s))
            n += len(LATIN.findall(s)) + len(DEVA.findall(s))
    return d / n if n else 1.0


def payload(doc: dict) -> list[dict]:
    return [{"test_case_id": c.get("test_case_id"),
             "transcript": [{"speaker": t.get("speaker"), "text": t.get("text", "")}
                            for t in c.get("transcript", []) or []],
             "decisive_evidence": c.get("decisive_evidence"),
             "trap_phrase": c.get("trap_phrase")}
            for c in doc.get("cases", []) if c.get("transcript")]


def _nfc(s) -> str:
    return unicodedata.normalize("NFC", str(s or ""))


def verify(case: dict) -> list[str]:
    """The same containment V9/V11 will apply. Cheaper to catch it here."""
    tx = "\n".join(t.get("text", "") for t in case.get("transcript", []) or [])
    bad = []
    de = _nfc(case.get("decisive_evidence"))
    if de and de not in _nfc(tx):
        bad.append("decisive_evidence")
    tp = _nfc(case.get("trap_phrase"))
    if tp and tp not in _nfc(tx):
        bad.append("trap_phrase")
    return bad


def apply(doc: dict, converted: list[dict]) -> tuple[int, list[str]]:
    """Merge converted text back in. Returns (cases_changed, cases_reverted)."""
    by_id = {c.get("test_case_id"): c for c in converted if isinstance(c, dict)}
    changed, reverted = 0, []
    for case in doc.get("cases", []):
        new = by_id.get(case.get("test_case_id"))
        if not new or not new.get("transcript"):
            continue
        old_turns = case.get("transcript") or []
        new_turns = new["transcript"]
        # A turn count that does not match means the model dropped or merged a
        # turn. Silently accepting it would change what the case tests.
        if len(new_turns) != len(old_turns):
            reverted.append(f"{case.get('test_case_id')}: turn count "
                            f"{len(old_turns)} -> {len(new_turns)}")
            continue
        snapshot = json.loads(json.dumps(
            {k: case.get(k) for k in ("transcript", "decisive_evidence", "trap_phrase")},
            ensure_ascii=False))
        for old, nt in zip(old_turns, new_turns):
            if old.get("speaker") != nt.get("speaker"):
                nt["speaker"] = old.get("speaker")
            old["text"] = nt.get("text", old.get("text", ""))
        if new.get("decisive_evidence"):
            case["decisive_evidence"] = new["decisive_evidence"]
        if new.get("trap_phrase") and case.get("trap_phrase"):
            case["trap_phrase"] = new["trap_phrase"]

        bad = verify(case)
        if bad:
            case.update(snapshot)
            reverted.append(f"{case.get('test_case_id')}: {'+'.join(bad)} no longer resolves")
        else:
            changed += 1
    return changed, reverted
