"""Run the suite against a live classification engine and score the result.

This closes the loop the rest of the pipeline exists to set up. Everything before
this point produces cases whose expected answer is *defensible* — traceable to a
verbatim clause. Only here do we find out what the engine actually does with them.

Two things this module is careful about:

`activity_uuid` is derived deterministically from `test_case_id`, so results join
back to cases by key rather than by row order. A bulk endpoint is free to return
rows in any order, drop rows it could not parse, or coalesce duplicates — and
positional joins fail silently when it does, producing a scorecard that is
confidently wrong.

Scoring is done **at the grade each case declares**. A case that expects to stop
at the sub is not scored against a leaf, because answering the leaf is precisely
the failure it was written to detect. Scoring everything at leaf level would
count the correct behaviour as a miss.
"""
from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .config import Config

# The column contract of the client's own interaction report. The engine reads
# the `before_*` and input columns and fills the `after_*` ones.
REPORT_COLUMNS = [
    "activity_uuid", "activity_type", "activity_status", "activity_date",
    "activity_time", "before_disposition", "before_disposition_confidence",
    "before_sub_disposition", "before_sub_disposition_confidence",
    "before_extended_disposition", "before_extended_disposition_confidence",
    "after_disposition", "after_disposition_confidence",
    "after_sub_disposition", "after_sub_disposition_confidence",
    "after_extended_disposition", "after_extended_disposition_confidence",
    "policy_uid", "due_date", "due_amount", "phase", "voice_recording_url",
    "transcript", "before_reliability_score", "after_reliability_score",
    "reliability_score_reasoning", "next_activity_uuid", "call_audit_score",
]

_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def case_uuid(test_case_id: str) -> str:
    """Stable per-case id. Same case, same uuid, every run."""
    return uuid.uuid5(_NS, f"dispogen::{test_case_id}").hex


ROLE = {"agent": "assistant", "customer": "user"}


def encode_transcript(transcript: list[dict], fmt: str, cycle_id: str = "",
                      state_id_base: int = 600) -> str:
    """Serialise turns for the transcript column.

    `call_transcript` is the shape the engine's own callers use: a wrapper object
    around role/content turns, where `agent`/`customer` become
    `assistant`/`user`. The corpus stores the older `speaker`/`text` Python repr,
    so both have to be expressible — which is why this is config, not a constant.
    """
    turns = transcript or []
    if fmt == "pyrepr":
        return repr([{"text": t.get("text", ""), "speaker": t.get("speaker", "")}
                     for t in turns])
    rc = []
    for i, t in enumerate(turns):
        d = {"role": ROLE.get(t.get("speaker"), t.get("speaker", "")),
             "content": t.get("text", "")}
        if cycle_id:
            d["cycle_id"] = cycle_id
            d["state_id"] = state_id_base + i
        rc.append(d)
    if fmt == "role_json":
        return json.dumps(rc, ensure_ascii=False)
    return json.dumps({"call_transcript": rc}, ensure_ascii=False)


def _first(params: dict, *names, default=""):
    for n in names:
        if params.get(n) not in (None, ""):
            return params[n]
    return default


def to_rows(cfg: Config, docs: list[dict]) -> list[dict]:
    """One report row per test case."""
    pre = cfg.get("classify.prior_state", {}) or {}
    fmt = cfg.get("classify.transcript_format", "call_transcript")
    # A fixed placeholder, not a random one: the same case must produce a
    # byte-identical CSV on every run, or diffing two exports is meaningless.
    cyc = cfg.get("classify.dummy_cycle_id", "")
    rows = []
    for doc in docs:
        for c in doc.get("cases", []):
            p = c.get("pre_call_parameters") or {}
            rd = c.get("redial") or {}
            date, tm = _split_anchor(rd.get("anchor_date") or cfg.get("client.anchor", ""))
            rows.append({
                "activity_uuid": case_uuid(c["test_case_id"]),
                "activity_type": "interaction",
                "activity_status": "recorded",
                "activity_date": date,
                "activity_time": tm,
                # Prior-call state. Cross-call leaves carry their own; everything
                # else gets a neutral prior from config rather than an invented one.
                "before_disposition": _first(p, "before_disposition",
                                             default=pre.get("disposition", "")),
                "before_disposition_confidence": pre.get("confidence", ""),
                "before_sub_disposition": _first(p, "before_sub_disposition",
                                                 default=pre.get("sub_disposition", "")),
                "before_sub_disposition_confidence": pre.get("confidence", ""),
                "before_extended_disposition": _first(p, "before_extended_disposition",
                                                      default=pre.get("extended_disposition", "")),
                "before_extended_disposition_confidence": pre.get("confidence", ""),
                # The engine fills these. Sending values would hand it the answer.
                "after_disposition": "", "after_disposition_confidence": "",
                "after_sub_disposition": "", "after_sub_disposition_confidence": "",
                "after_extended_disposition": "", "after_extended_disposition_confidence": "",
                "policy_uid": _first(p, "policy_no", "policy_uid", "policy_number"),
                "due_date": _first(p, "due_date"),
                "due_amount": _first(p, "due_amount", "modal_premium", "premium_amount",
                                     "premium", "premium_due", "total_premium"),
                "phase": _first(p, "phase", default="pre_due"),
                "voice_recording_url": "",
                "transcript": encode_transcript(c.get("transcript") or [], fmt, cyc),
                "before_reliability_score": "", "after_reliability_score": "",
                "reliability_score_reasoning": "", "next_activity_uuid": "",
                "call_audit_score": "N/A",
            })
    return rows


def _split_anchor(anchor: str) -> tuple[str, str]:
    """'Tue 07 Jul 2026, 14:32' -> ('2026-07-30', '14:32:00')."""
    import re
    m = re.search(r"(\d{2}) (\w{3}) (\d{4}), (\d{2}):(\d{2})", str(anchor))
    if not m:
        return "", ""
    months = {m_: i for i, m_ in enumerate(
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
    d, mon, y, hh, mm = m.groups()
    return f"{y}-{months.get(mon, 1):02d}-{d}", f"{hh}:{mm}:00"


def write_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


# ----------------------------------------------------------------- transport

def _multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "----dispogen" + uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n").encode()
    out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
            f"filename=\"{file_path.name}\"\r\nContent-Type: text/csv\r\n\r\n").encode()
    out += file_path.read_bytes() + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _request(url: str, api_key: str, data=None, content_type=None, method="GET") -> Any:
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-api-key", api_key)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {body[:500]}") from e
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"_raw": body}


def submit(cfg: Config, csv_path: Path, api_key: str) -> dict:
    base = cfg.get("classify.base_url").rstrip("/")
    body, ctype = _multipart(
        {"customer_id": cfg.get("classify.customer_id"),
         "use_case_id": cfg.get("classify.use_case_id")}, "file", csv_path)
    return _request(f"{base}{cfg.get('classify.submit_path', '/admin/dispositions/classify')}",
                    api_key, data=body, content_type=ctype, method="POST")


def classify_one(cfg: Config, case: dict, api_key: str, *, timeout_s: int = 300) -> dict:
    """Classify a single case and return the engine's verdict.

    Preferred over the bulk CSV path for two reasons: `interaction_ref` comes back
    on the result, so rows join by key instead of by position; and the CSV
    endpoint on this deployment reports `pre_llm_empty_transcript` for every row —
    including rows taken verbatim from the engine's own interaction report — so
    it cannot currently be used to measure anything.
    """
    base = cfg.get("classify.base_url").rstrip("/")
    p = case.get("pre_call_parameters") or {}
    payload = {
        "transcript": [{"role": {"agent": "assistant", "customer": "user"}.get(
                            t.get("speaker"), t.get("speaker")),
                        "content": t.get("text", "")}
                       for t in case.get("transcript") or []],
        "customer_id": cfg.get("classify.customer_id"),
        "use_case_id": cfg.get("classify.use_case_id"),
        "interaction_ref": case["test_case_id"],
        "metadata": {k: str(v) for k, v in p.items()},
    }
    job = _request(f"{base}/admin/dispositions/classify-one", api_key,
                   data=json.dumps(payload).encode(),
                   content_type="application/json", method="POST")
    su = job.get("status_url") or f"/admin/dispositions/jobs/{job.get('job_id')}"
    res = poll(cfg, su, api_key, timeout_s=timeout_s)
    return res.get("result") or {}


def poll(cfg: Config, status_url: str, api_key: str, *, timeout_s: int = 3600,
         on_tick=None) -> dict:
    base = cfg.get("classify.base_url").rstrip("/")
    url = status_url if status_url.startswith("http") else base + status_url
    interval = max(1.0, cfg.get("classify.poll_interval_ms", 2000) / 1000)
    t0 = time.monotonic()
    last = None
    while time.monotonic() - t0 < timeout_s:
        res = _request(url, api_key)
        status = str(res.get("status", "")).lower()
        if on_tick and res != last:
            on_tick(res, time.monotonic() - t0)
            last = res
        if status in ("completed", "complete", "done", "succeeded", "failed", "error"):
            return res
        time.sleep(interval)
    raise TimeoutError(f"job still {last and last.get('status')!r} after {timeout_s}s")


# ------------------------------------------------------------------- scoring

def _num(label: str) -> str:
    """'0022 - Assured to pay to Advisor' -> '0022'."""
    return str(label or "").split(" - ")[0].strip()


def score_case(case: dict, verdict: dict) -> dict:
    """Score one case at the grade it declares.

    A case that expects to stop at the sub is not scored against a leaf: answering
    the leaf is exactly the failure it was written to detect, so scoring
    everything at leaf level would count the correct behaviour as a miss.
    """
    grade = case.get("declared_grade", "EXPANDED")
    got = {"GROUP": _num(verdict.get("group")),
           "SUB": _num(verdict.get("sub")),
           "EXPANDED": _num(verdict.get("extended"))}
    want = {"GROUP": _num(case.get("expected_group")),
            "SUB": _num(case.get("expected_sub")),
            "EXPANDED": _num(case.get("expected_expanded"))}

    ORDER = ["GROUP", "SUB", "EXPANDED"]
    levels = ORDER[:ORDER.index(grade) + 1]
    correct = all(got[l] == want[l] for l in levels if want[l])

    # A case cannot forbid its own answer. ~9% of generated FP probes listed an
    # ancestor of their expected label in must_not_select, which would make every
    # possible verdict simultaneously right and wrong. Subtracting the expected
    # codes keeps those cases scorable; V17 reports them so they get regenerated.
    expected_codes = {v for v in want.values() if v}
    declared = {_num(x) for x in (case.get("must_not_select") or [])}
    forbidden = declared - expected_codes
    contradictory = sorted(declared & expected_codes)
    hit = forbidden & ({got["EXPANDED"], got["SUB"], got["GROUP"]} - {""})

    # Answering deeper than the declared grade is not a detail — for a
    # stop_at_parent or under_determined probe it is precisely the failure under
    # test, so it must be caught even when the graded levels themselves match.
    deeper = [l for l in ORDER[ORDER.index(grade) + 1:] if got[l]]
    over = bool(deeper) and grade in ("GROUP", "SUB")

    if hit:
        outcome = "FALSE_POSITIVE" if case["probe_type"] == "FP" else "FALSE_NEGATIVE"
    elif over and correct:
        # Only when the graded levels are otherwise right. A case that is BOTH
        # wrong at its own grade and over-committed is a wrong label; reporting
        # it as over-commitment would hide the larger error.
        outcome = "OVER_COMMITTED"
    elif correct:
        outcome = "PASS"
    else:
        outcome = "WRONG_LABEL" if case["probe_type"] == "FP" else "FALSE_NEGATIVE"

    return {
        "test_case_id": case["test_case_id"], "probe_type": case["probe_type"],
        "archetype": case.get("archetype"), "declared_grade": grade,
        "expected": {l: want[l] for l in ORDER},
        "got": got, "outcome": outcome,
        "forbidden_hit": sorted(hit), "contradictory_must_not_select": contradictory,
        "confidence": verdict.get("confidence"),
        "decision": verdict.get("decision"), "stage": verdict.get("stage"),
        "engine_reason": (verdict.get("level_2_reason") or verdict.get("level_1_reason")
                          or verdict.get("level_0_reason") or ""),
    }


def summarise(scored: list[dict]) -> dict:
    from collections import Counter
    by = Counter(s["outcome"] for s in scored)
    fp = [s for s in scored if s["probe_type"] == "FP"]
    fn = [s for s in scored if s["probe_type"] == "FN"]
    n = len(scored) or 1
    return {
        "total": len(scored),
        "outcomes": dict(by),
        "accuracy": round(by["PASS"] / n, 4),
        "false_positives": by["FALSE_POSITIVE"],
        "fp_rate": round(by["FALSE_POSITIVE"] / (len(fp) or 1), 4),
        "false_negatives": by["FALSE_NEGATIVE"],
        "fn_rate": round(by["FALSE_NEGATIVE"] / (len(fn) or 1), 4),
        "over_committed": by["OVER_COMMITTED"],
        "by_archetype": {a: dict(Counter(s["outcome"] for s in scored if s["archetype"] == a))
                         for a in sorted({s["archetype"] for s in scored if s["archetype"]})},
    }
