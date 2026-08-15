"""dispogen CLI.

    dispogen preflight   --client gcli
    dispogen compile     --client gcli
    dispogen prescan     --client gcli
    dispogen packs       --client gcli [--only CODE ...]
    dispogen generate    --client gcli --only CODE [--provider dryrun]
    dispogen validate    --client gcli
    dispogen transliterate --client gcli    # romanised Hindi -> Devanagari, in place
    dispogen certify     --client gcli          # blind panel + adversarial advocate
    dispogen render      --client gcli
    dispogen run         --client gcli          # preflight -> render
    dispogen scan-pii    --client gcli
    dispogen scrub       --client gcli          # de-identify existing cases in place
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Console encodings (notably cp1252 on Windows) crash on Devanagari, Cyrillic,
# CJK — i.e. exactly the corpora this tool exists for. Reconfigure rather than
# strip: an FDE debugging a Hindi transcript needs to see the Hindi.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from . import corpus, packs as packmod, prescan, preflight, render, taxonomy as taxmod
from .config import Config, ConfigError
from .deidentify import Deidentifier
from .validators import lint_learnings, validate


def _cfg(a) -> Config:
    return Config.load(a.client, Path(a.root) if a.root else None)


def _deid(cfg: Config) -> Deidentifier:
    return Deidentifier(cfg, corpus.harvest_identifiers(cfg))


def _cases(cfg: Config) -> list[Path]:
    return sorted((cfg.root / "output" / "cases").glob("*.json"))


def _load_case_docs(cfg: Config, only: list[str] | None) -> list[dict]:
    docs = []
    for p in _cases(cfg):
        if only and p.stem not in only:
            continue
        docs.append(json.loads(p.read_text(encoding="utf-8")))
    return docs


# ------------------------------------------------------------------ commands

def cmd_preflight(a) -> int:
    cfg = _cfg(a)
    res = preflight.run(cfg, require_credentials=a.check_credentials)
    for c in res.checks:
        if not c.ok:
            print(f"  FAIL {c.id}  {c.desc}\n        {c.detail}")
    m = res.manifest
    print(f"PREFLIGHT: {'PASS' if res.passed else 'FAIL'}   client={cfg.name}")
    if m:
        cnt = m["counts"]
        print(f"  taxonomy: {cnt['leaves']} leaves / {cnt['groups']} groups / {cnt['subs']} subs")
        print(f"  leaves with explicit rivals: {cnt['leaves_with_explicit_rivals']}/{cnt['leaves']}")
        print(f"  annotated rows mined: {cnt['annotations']}")
        print(f"  decoders: {m['decoders']}")
        print(f"  token vocabulary: {m['token_vocabulary']}")
        print(f"  rival supply degraded on {len(m['rival_supply_degraded'])} leaves")
        print(f"  config_hash: {m['config_hash']}")
        (cfg.workdir("compiled") / "context_manifest.json").write_text(
            json.dumps(m, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for w in res.warnings:
        print(f"  WARN {w}")
    return 0 if res.passed else 1


def cmd_compile(a) -> int:
    cfg = _cfg(a)
    tax = taxmod.load(cfg)
    graph = taxmod.confusion_graph(cfg, tax)
    ladder, missing = taxmod.precedence(cfg, tax)
    d = cfg.workdir("compiled")
    (d / "taxonomy.json").write_text(json.dumps(
        {"leaves": [l.dict() for l in tax.leaves],
         "subs": [{"group": g, "sub": s, "description": v} for (g, s), v in tax.subs.items()],
         "groups": tax.groups}, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "confusion_graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "precedence_ladder.json").write_text(
        json.dumps(ladder, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"compiled -> {d}")
    print(f"  {len(tax.leaves)} leaves, {sum(1 for v in graph.values() if v['rivals'])} with rivals")
    if missing:
        print(f"  WARN precedence anchors no longer resolving: {missing}")
    return 0


def cmd_prescan(a) -> int:
    cfg = _cfg(a)
    tax = taxmod.load(cfg)
    graph = taxmod.confusion_graph(cfg, tax)
    ann = (corpus.mine_annotations(cfg)
           if cfg.optional_path("inputs.interaction_report.path") else [])
    f = prescan.run(cfg, tax, graph, ann)
    (cfg.workdir("compiled") / "ambiguity_prescan.json").write_text(
        json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"AMBIGUITY PRE-SCAN: {len(f)} findings over {len(ann)} annotated rows")
    for k, c in prescan.summary(f).items():
        print(f"    class {k}  {c:3d}  {prescan.CLASSES[k]}")
    return 0


def cmd_packs(a) -> int:
    cfg = _cfg(a)
    tax = taxmod.load(cfg)
    p = packmod.build_all(cfg, tax, a.only or None)
    packmod.write(cfg, p)
    for code, pack in p.items():
        q = pack["quota"]
        print(f"{code:30s} rivals={len(q['fp_allocation'])} shortfall={q['shortfall']}")
        for al in q["fp_allocation"]:
            print(f"    {al['slot']} {al['archetype']:26s} -> {al['rival_num']:6s} "
                  f"({al['level']}, {al['tier']})")
        for n in q["allocation_notes"]:
            print(f"    NOTE {n}")
    return 0


def _extract_json(text: str):
    """Recover the JSON object from a response that may be fenced or prefaced.

    Writing the raw text straight to disk means one stray sentence of preamble
    makes the file unparseable, and the failure only surfaces at validate time
    with no indication that generation itself succeeded.
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = t[3:]
        t = t.split("\n", 1)[1] if t[:4].lower().startswith("json") else t
        t = t.rsplit("```", 1)[0]
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None


def _generate_one(cfg, spec, tmpl, code, pack, gate=None) -> tuple[str, str, int]:
    """Returns (code, message, rc). Runs in a worker thread."""
    from .providers import build as build_provider
    from .ratelimit import estimate_tokens
    prov = build_provider({**spec, "label": code})
    prefix, tail = ("", tmpl.replace("{{PACK}}", json.dumps(pack, ensure_ascii=False, indent=1)))
    waited = 0.0
    if gate is not None:
        # Charge half the ceiling, not the whole thing. max_tokens is head-room so
        # that reasoning never truncates the cases; actual output lands well under
        # it, and billing the ceiling would throttle the run to a third of the
        # quota the deployment actually has. The gate approximates; the 429 retry
        # in the provider is the exact backstop.
        waited = gate.acquire(estimate_tokens(tail, int(spec.get("max_tokens", 8000)), 0.5))
    out = prov.complete(system="You are an adversarial QA engineer.", user=tail,
                        cache_prefix=prefix or None, schema=None,
                        max_tokens=spec.get("max_tokens"))
    held = f" (held {waited:.0f}s)" if waited > 1 else ""
    if out.refused:
        return code, f"REFUSED ({out.refusal_category}) — see docs/ARCHITECTURE.md", 1
    if out.provider == "dryrun":
        return code, f"prompt written -> {out.usage.get('prompt_written_to')}", 0
    doc = _extract_json(out.text)
    if doc is None:
        p = cfg.workdir("logs", "raw") / f"{code}.txt"
        p.write_text(out.text, encoding="utf-8")
        return code, f"UNPARSEABLE ({out.stop_reason}, {len(out.text)} chars) -> {p}", 1
    # Models routinely misreport their own identity in generated text. The
    # response carries the deployment that actually ran; trust that instead, or
    # the provenance on every case is wrong in a way nothing downstream catches.
    doc["generated_by"] = out.model
    dst = cfg.workdir("output", "cases") / f"{code}.json"
    dst.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    n = len(doc.get("cases", []))
    amb = len(doc.get("ambiguities", []) or [])
    u = out.usage or {}
    return code, (f"{n} cases, {amb} ambiguities  "
                  f"[in {u.get('input_tokens')} out {u.get('output_tokens')}]{held}"), 0


def cmd_generate(a) -> int:
    cfg = _cfg(a)
    spec = dict(cfg.get("models.generator"))
    if a.provider:
        spec["provider"] = a.provider
    tmpl = (cfg.root / "prompts" / "generator.md").read_text(encoding="utf-8")
    tax = taxmod.load(cfg)
    p = packmod.build_all(cfg, tax, a.only or None)
    packmod.write(cfg, p)

    workers = max(1, int(a.workers or 1))
    todo = list(p.items())
    if a.skip_existing:
        d = cfg.workdir("output", "cases")
        before = len(todo)
        todo = [(c, pk) for c, pk in todo if not (d / f"{c}.json").exists()]
        if before != len(todo):
            print(f"skipping {before - len(todo)} already generated; {len(todo)} to go")
    gate = None
    if a.tpm or a.rpm:
        from .ratelimit import RateGate
        gate = RateGate(int(a.tpm or 10 ** 9), int(a.rpm or 10 ** 6), float(a.buffer))
        print(f"rate gate: {a.tpm} tok/min, {a.rpm} req/min, {int(float(a.buffer)*100)}% buffer "
              f"-> {gate.tok_budget:,.0f} tok/min usable", flush=True)

    rc = 0
    if workers == 1:
        for code, pack in todo:
            code, msg, r = _generate_one(cfg, spec, tmpl, code, pack, gate)
            rc |= r
            print(f"{code}: {msg}", flush=True)
        return rc

    from concurrent.futures import ThreadPoolExecutor, as_completed
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_generate_one, cfg, spec, tmpl, c, pk, gate): c for c, pk in todo}
        for f in as_completed(futs):
            done += 1
            try:
                code, msg, r = f.result()
            except Exception as e:  # one disposition failing must not lose the rest
                code, msg, r = futs[f], f"ERROR {type(e).__name__}: {e}", 1
            rc |= r
            print(f"[{done}/{len(todo)}] {code}: {msg}", flush=True)
    return rc


def cmd_validate(a) -> int:
    cfg = _cfg(a)
    tax = taxmod.load(cfg)
    deid = _deid(cfg) if cfg.get("deidentify.enabled", True) else None
    total = 0
    docs = _load_case_docs(cfg, a.only or None)
    if not docs:
        print("no case files in output/cases/ — run `dispogen generate` first")
        return 1
    for doc in docs:
        pk = cfg.root / "compiled" / "packs" / f"{doc['engine_code']}.json"
        if not pk.exists():
            print(f"{doc['engine_code']}: no pack — run `dispogen packs`")
            total += 1
            continue
        errs = validate(cfg, tax, doc, json.loads(pk.read_text(encoding="utf-8")), deid)
        total += len(errs)
        print(f"\n=== {doc['engine_code']} === {'PASS' if not errs else f'{len(errs)} FAILURES'}")
        for e in errs:
            print("   ", e)
    lp = cfg.root / "learnings"
    for f in lp.rglob("*.md"):
        hits = lint_learnings(cfg, f.read_text(encoding="utf-8"))
        if hits:
            total += len(hits)
            print(f"\n=== {f.relative_to(cfg.root)} === DOMAIN LEAK ({len(hits)})")
            for h in hits[:10]:
                print(f"    line {h['line']}  {h['pattern']}  ::  {h['text']}")
    print(f"\nTOTAL FAILURES: {total}")
    return 1 if total else 0


def _translit_one(cfg, spec, tmpl, path, gate=None) -> tuple[str, str, int]:
    from . import translit as tl
    from .providers import build as build_provider
    from .ratelimit import estimate_tokens
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not tl.needs_work(doc):
        return path.stem, f"already Devanagari ({tl.deva_ratio(doc):.0%})", 0
    user = tmpl.replace("{{CASES}}", json.dumps(tl.payload(doc), ensure_ascii=False, indent=1))
    if gate is not None:
        gate.acquire(estimate_tokens(user, int(spec.get("max_tokens", 32000)), 0.5))
    out = build_provider({**spec, "label": f"translit.{path.stem}"}).complete(
        system="You convert romanised Hindi to Devanagari. You change script, never wording.",
        user=user, max_tokens=spec.get("max_tokens"), effort=spec.get("effort"))
    if out.refused:
        return path.stem, f"REFUSED ({out.refusal_category})", 1
    if out.provider == "dryrun":
        return path.stem, f"prompt written -> {out.usage.get('prompt_written_to')}", 0
    parsed = _extract_json(out.text)
    if not parsed or "cases" not in parsed:
        return path.stem, f"UNPARSEABLE ({out.stop_reason}, {len(out.text)} chars)", 1
    before = tl.deva_ratio(doc)
    changed, reverted = tl.apply(doc, parsed["cases"])
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    msg = f"{changed} cases converted, {before:.0%} -> {tl.deva_ratio(doc):.0%} Devanagari"
    if reverted:
        msg += f"; {len(reverted)} REVERTED ({reverted[0]})"
    return path.stem, msg, 1 if reverted else 0


def cmd_transliterate(a) -> int:
    """Rewrite romanised Hindi in transcripts as Devanagari, in place."""
    cfg = _cfg(a)
    spec = dict(cfg.get("models.transliterator", cfg.get("models.generator")))
    if a.provider:
        spec["provider"] = a.provider
    tmpl = (cfg.root / "prompts" / "transliterate.md").read_text(encoding="utf-8")
    paths = [p for p in _cases(cfg) if not a.only or p.stem in a.only]
    gate = None
    if a.tpm or a.rpm:
        from .ratelimit import RateGate
        gate = RateGate(int(a.tpm or 10 ** 9), int(a.rpm or 10 ** 6), float(a.buffer))
    rc, done = 0, 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max(1, int(a.workers or 1))) as ex:
        futs = {ex.submit(_translit_one, cfg, spec, tmpl, p, gate): p for p in paths}
        for f in as_completed(futs):
            done += 1
            try:
                code, msg, r = f.result()
            except Exception as e:
                code, msg, r = futs[f].stem, f"ERROR {type(e).__name__}: {e}", 1
            rc |= r
            print(f"[{done}/{len(paths)}] {code}: {msg}", flush=True)
    print("\nre-run `dispogen validate` — V9/V11 check the spans this rewrote")
    return rc


def cmd_certify(a) -> int:
    cfg = _cfg(a)
    from . import certify as certmod
    tax = taxmod.load(cfg)
    docs = _load_case_docs(cfg, a.only or None)
    if not docs:
        print("no case files in output/cases/")
        return 1
    log = []
    for doc in docs:
        entries = certmod.run(cfg, tax, doc, provider=a.provider)
        log += entries
        print(f"\n=== {doc['engine_code']} ===")
        for e in entries:
            print(f"  {e['status']:12s} {e['test_case_id']}")
            for d in e.get("dissent", []):
                print(f"       dissent: {d}")
        # Stamp the verdict onto the case file so the rendered workbook reports
        # what the tribunal actually found rather than defaulting to PROVISIONAL.
        by_id = {e["test_case_id"]: e for e in entries}
        for c in doc.get("cases", []):
            e = by_id.get(c.get("test_case_id"))
            # NOT_RUN carries no information the default PROVISIONAL does not.
            # Writing it would make a dry run look like a tribunal outcome.
            if e and e["status"] != "NOT_RUN":
                c["certification_status"] = e["status"]
                c["certified_grade"] = e.get("certified_grade")
        (cfg.workdir("output", "cases") / f"{doc['engine_code']}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    # Distinct from output/certification_log.json, which is the gate-summary table
    # the workbook renders. These are the per-case verdicts behind it.
    p = cfg.workdir("output") / "certification_verdicts.json"
    p.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    s = certmod.summary(log)
    print(f"\n{s}\nWROTE {p}")
    # NOT_RUN is not a pass. A dry run leaves every case PROVISIONAL, and saying
    # otherwise is how an uncertified suite ends up shipped as certified.
    return 1 if (set(s) - {"CERTIFIED"}) else 0


def cmd_classify(a) -> int:
    """Run the suite against the live engine and keep the raw result."""
    import os
    from . import apiclient as api
    cfg = _cfg(a)
    docs = _load_case_docs(cfg, a.only or None)
    if not docs:
        print("no case files in output/cases/")
        return 1
    rows = api.to_rows(cfg, docs)
    if a.limit:
        rows = rows[:int(a.limit)]
    dst = cfg.workdir("output", "classify") / f"{cfg.name}_input.csv"
    api.write_csv(rows, dst)
    print(f"{len(rows)} rows -> {dst}")
    if a.export_only:
        return 0

    key = os.environ.get(cfg.get("classify.api_key_env", "DISPO_API_KEY"), "")
    if not key:
        print(f"set {cfg.get('classify.api_key_env')} in the environment")
        return 2
    if a.mode == "one":
        return _classify_one_all(cfg, api, docs, key, a)
    job = api.submit(cfg, dst, key)
    print(f"submitted: {json.dumps(job, ensure_ascii=False)}")
    su = job.get("status_url")
    if not su:
        print("no status_url in the response — nothing to poll")
        return 1

    def tick(res, secs):
        keys = {k: v for k, v in res.items() if not isinstance(v, (list, dict))}
        print(f"  [{secs:6.0f}s] {json.dumps(keys, ensure_ascii=False)[:220]}", flush=True)

    res = api.poll(cfg, su, key, timeout_s=int(a.timeout or 3600), on_tick=tick)
    out = cfg.workdir("output", "classify") / f"{cfg.name}_job.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nstatus={res.get('status')}  -> {out}")
    return 0 if str(res.get("status", "")).lower() in ("completed", "complete", "done",
                                                       "succeeded") else 1


def _classify_one_all(cfg, api, docs, key, a) -> int:
    """Per-case classification, concurrent, joined by interaction_ref."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    cases = [c for d in docs for c in d.get("cases", [])]
    if a.limit:
        cases = cases[: int(a.limit)]
    out_dir = cfg.workdir("output", "classify")
    results, errors = [], []

    def one(c):
        return c, api.classify_one(cfg, c, key, timeout_s=int(a.timeout or 300))

    with ThreadPoolExecutor(max_workers=int(a.workers or 8)) as ex:
        futs = {ex.submit(one, c): c for c in cases}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                c, verdict = f.result()
                results.append(api.score_case(c, verdict))
            except Exception as e:
                c = futs[f]
                errors.append({"test_case_id": c["test_case_id"],
                               "error": f"{type(e).__name__}: {e}"})
            if i % 25 == 0 or i == len(cases):
                print(f"  [{i}/{len(cases)}] scored={len(results)} errors={len(errors)}",
                      flush=True)

    summary = api.summarise(results)
    # A spreadsheet of expected-vs-got, because scored.json is not reviewable by
    # the people who own the taxonomy.
    import csv as _csv
    with (out_dir / "scored.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["test_case_id", "probe_type", "archetype", "declared_grade",
                    "outcome", "expected_group", "expected_sub", "expected_expanded",
                    "got_group", "got_sub", "got_expanded", "forbidden_hit",
                    "confidence", "decision", "engine_reason"])
        for r in sorted(results, key=lambda x: x["test_case_id"]):
            e, g = r["expected"], r["got"]
            w.writerow([r["test_case_id"], r["probe_type"], r["archetype"],
                        r["declared_grade"], r["outcome"],
                        e["GROUP"], e["SUB"], e["EXPANDED"],
                        g["GROUP"], g["SUB"], g["EXPANDED"],
                        ";".join(r.get("forbidden_hit") or []),
                        r.get("confidence"), r.get("decision"),
                        (r.get("engine_reason") or "")[:400]])
    (out_dir / "scored.json").write_text(
        json.dumps({"summary": summary, "results": results, "errors": errors},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n=== ENGINE SCORECARD ({summary['total']} cases) ===")
    print(f"  accuracy          {summary['accuracy']:.1%}")
    print(f"  FALSE POSITIVES   {summary['false_positives']:3d}  ({summary['fp_rate']:.1%} of FP probes)")
    print(f"  false negatives   {summary['false_negatives']:3d}  ({summary['fn_rate']:.1%} of FN probes)")
    print(f"  over-committed    {summary['over_committed']:3d}")
    print(f"  outcomes          {summary['outcomes']}")
    if errors:
        print(f"  errors            {len(errors)}")
    print(f"\nWROTE {out_dir / 'scored.json'}")
    return 0


def cmd_scan_pii(a) -> int:
    cfg = _cfg(a)
    deid = _deid(cfg)
    tot = sum(len(v) for v in deid.real.values())
    print(f"harvested {tot} real identifiers "
          f"({ {k: len(v) for k, v in deid.real.items()} })")
    leaks = 0
    for p in _cases(cfg):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for c in doc.get("cases", []):
            for h in deid.report(c):
                leaks += 1
                print(f"  LEAK {c.get('test_case_id')}  {h['kind']}  {h['value']}")
    print(f"\n{'CLEAN' if not leaks else f'{leaks} LEAKS — run `dispogen scrub`'}")
    return 1 if leaks else 0


def cmd_scrub(a) -> int:
    cfg = _cfg(a)
    deid = _deid(cfg)
    n = 0
    for p in _cases(cfg):
        doc = json.loads(p.read_text(encoding="utf-8"))
        before = json.dumps(doc, ensure_ascii=False)
        doc = deid.scrub(doc)
        after = json.dumps(doc, ensure_ascii=False)
        if before != after:
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            n += 1
            print(f"  scrubbed {p.name}")
    print(f"{n} file(s) rewritten. Re-run `dispogen scan-pii` to confirm.")
    return 0


def cmd_render(a) -> int:
    cfg = _cfg(a)
    docs = _load_case_docs(cfg, a.only or None)
    if not docs:
        print("no case files in output/cases/")
        return 1
    reg_p = cfg.root / "output" / "ambiguity_register.json"
    register = json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.exists() else {"entries": []}
    man_p = cfg.root / "compiled" / "context_manifest.json"
    manifest = json.loads(man_p.read_text(encoding="utf-8")) if man_p.exists() else {}
    ps_p = cfg.root / "compiled" / "ambiguity_prescan.json"
    findings = json.loads(ps_p.read_text(encoding="utf-8")) if ps_p.exists() else []
    g_p = cfg.root / "output" / "certification_log.json"
    gates = json.loads(g_p.read_text(encoding="utf-8")) if g_p.exists() else []
    out = cfg.root / "output" / f"{cfg.name}_TestCases.xlsx"
    render.build(cfg, docs, register, manifest, findings, gates, out)
    print(f"WROTE {out}")
    csv_out = render.write_csv(cfg, docs, cfg.root / "output" / f"{cfg.name}_TestCases.csv")
    n = sum(len(d.get("cases", [])) for d in docs)
    print(f"WROTE {csv_out}  ({n} cases across {len(docs)} dispositions)")
    return 0


def cmd_run(a) -> int:
    for step in (cmd_preflight, cmd_compile, cmd_prescan, cmd_packs):
        rc = step(a)
        if rc:
            return rc
    rc = cmd_validate(a)
    if rc:
        print("\nvalidation failed — not rendering a workbook from failing cases")
        return rc
    return cmd_render(a)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser("dispogen", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", default="gcli", help="client config name or path")
    ap.add_argument("--root", default=None, help="repo root (default: cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        s = sub.add_parser(name, help=(fn.__doc__ or name).strip().split("\n")[0], **kw)
        s.set_defaults(fn=fn)
        return s

    add("preflight", cmd_preflight).add_argument(
        "--check-credentials", action="store_true", help="ping the generator deployment")
    add("compile", cmd_compile)
    add("prescan", cmd_prescan)
    add("packs", cmd_packs).add_argument("--only", nargs="*", help="engine codes")
    g = add("generate", cmd_generate)
    g.add_argument("--only", nargs="*", help="engine codes")
    g.add_argument("--provider", help="override models.generator.provider (e.g. dryrun)")
    g.add_argument("--workers", type=int, default=1, help="dispositions to generate concurrently")
    g.add_argument("--skip-existing", action="store_true",
                   help="leave dispositions that already have a case file alone")
    g.add_argument("--tpm", type=int, help="deployment tokens-per-minute quota")
    g.add_argument("--rpm", type=int, help="deployment requests-per-minute quota")
    g.add_argument("--buffer", default=0.30,
                   help="headroom kept below the quota (0.30 = use 70%%)")
    add("validate", cmd_validate).add_argument("--only", nargs="*")
    tr = add("transliterate", cmd_transliterate)
    tr.add_argument("--only", nargs="*")
    tr.add_argument("--provider")
    tr.add_argument("--workers", type=int, default=1)
    tr.add_argument("--tpm", type=int)
    tr.add_argument("--rpm", type=int)
    tr.add_argument("--buffer", default=0.30)

    cert = add("certify", cmd_certify)
    cert.add_argument("--only", nargs="*")
    cert.add_argument("--provider", help="override the panel provider (e.g. dryrun)")
    add("render", cmd_render).add_argument("--only", nargs="*")
    cl = add("classify", cmd_classify)
    cl.add_argument("--only", nargs="*")
    cl.add_argument("--limit", type=int, help="submit only the first N rows (pilot)")
    cl.add_argument("--export-only", action="store_true", help="write the CSV, do not submit")
    cl.add_argument("--timeout", type=int, default=3600)
    cl.add_argument("--workers", type=int, default=8)
    cl.add_argument("--mode", choices=["csv", "one"], default="one",
                    help="'one' = per-case classify-one (joins by interaction_ref)")
    add("scan-pii", cmd_scan_pii)
    add("scrub", cmd_scrub)
    add("run", cmd_run).add_argument("--check-credentials", action="store_true")

    a = ap.parse_args(argv)
    for attr in ("only", "provider", "check_credentials", "workers", "skip_existing",
                 "tpm", "rpm", "buffer", "limit", "export_only", "timeout", "mode"):
        if not hasattr(a, attr):
            setattr(a, attr, None)
    try:
        return a.fn(a)
    except ConfigError as e:
        print(f"CONFIG ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
