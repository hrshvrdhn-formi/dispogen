# Worked example — GCLI Persistency

A real end-to-end run, with the numbers it actually produced. Use it to calibrate
what "normal" looks like before you trust or distrust your own first run.

**Agent:** outbound life-insurance renewal voice agent, Hinglish
**Taxonomy:** 52 leaves / 13 subs / 5 groups
**Generator:** `claude-opus-5` via a Microsoft Foundry deployment, `effort: max`

---

## Result

| | |
|---|---|
| Dispositions generated | **51** (1 excluded: the abstention target has no positive instances) |
| Test cases | **499** — 244 FP, 255 FN |
| Validation | **0 failures** across V2–V16 |
| Ambiguities recorded | **268** |
| Static taxonomy defects (pre-scan) | **62** |
| Certification | not run — every case is `PROVISIONAL` |

Grades: 395 `EXPANDED`, 49 `SUB`, 55 `GROUP`. The ~20% of cases answering at
sub or group level are the `stop_at_parent` and `under_determined` probes — they
are the ones testing over-commitment, and a run where everything is `EXPANDED`
means those roles were not filled.

FP counts are below FN counts (244 vs 255) because **a leaf gets as many FP
probes as its taxonomy supplies distinct rivals**. Eleven leaves could not supply
five. That shortfall is reported per leaf rather than padded to a round number.

---

## Cost and wall-clock

Generation ran 51 dispositions at `--workers 20` against a 500k tokens/min,
500 requests/min deployment with a 30% buffer.

| | Per disposition | Total |
|---|---|---|
| Input | ~12.5k tokens | ~640k |
| Output | ~65k tokens | ~3.3M |

Roughly **45 minutes** wall-clock. In series it would have been most of a day.

The output figure is dominated by reasoning, not by the cases themselves — the
text of ten cases is 25–35k tokens. That ratio is why `max_tokens` has to be
generous: at 32000 the reasoning consumed the entire budget and responses
truncated inside case 1.

---

## What went wrong, and what it cost

Worth reading — most of these will happen to you.

**Truncation at `max_tokens: 32000`.** Cases truncated mid-JSON with
`stop_reason: max_tokens`. `max_tokens` caps thinking *plus* text. Raised to
128000 (the deployment ceiling; 200000 returns a 400). Cost: one wasted run.

**Three empty responses.** `UNPARSEABLE (None, 0 chars)` on three dispositions
early in the fan-out. Transient. Re-running with `--skip-existing` picked up
exactly those three. Do not redesign around this — it is a hiccup, not a pattern.

**Telephony dispositions failed en masse.** `PHONE_BUSY`, `RINGING`,
`OUT_OF_COVERAGE`, `INVALID_NUMBER` produced 10–15 failures each on V9/V11:
*decisive_evidence NOT verbatim in transcript*. The cases were correct; the
**validator** was wrong. A telephony case has no transcript by design — its
evidence lives in `pre_call_parameters`. V9/V11 now check against the right
source per `source_of_truth_class`. Cost: one validator fix, zero regeneration.

**Romanised transcripts.** The model wrote Hinglish in Latin script; production
ASR emits Devanagari. `transliterate` converts script without touching wording,
rewriting `decisive_evidence` and `trap_phrase` in lockstep — they are verbatim
substrings and V9/V11 check exact containment, so converting the transcript alone
would silently invalidate every case it touched. Cases whose spans stop resolving
are reverted rather than shipped broken.

**A real policy number in a docstring.** Caught by scanning every staged file
against the live corpus before the first commit. Also a real surname sitting in
the de-identification pool — which meant scrubbing would have swapped one real
name for another and reported success. Both replaced; the pool now raises
`PoolExhausted` rather than passing quietly.

---

## The ambiguity register is the other deliverable

268 ambiguities across 51 dispositions — roughly **five per disposition**, found
by trying to write a decidable test case and failing.

| Class | | Count |
|---|---|---|
| A | definitional gap — evidence clear, no leaf covers it | 61 |
| D | source-of-truth conflict | 48 |
| B | level ambiguity — sub certain, leaf under-determined | 47 |
| E | unranked co-occurrence | 47 |
| H | annotation conflict — human gold vs written rules | 23 |
| C | label / parent collision | 18 |
| F | evidence insufficiency | 15 |
| G | cross-call gating | 5 |
| I | degenerate leaf | 4 |

Plus 62 defects found by the static pre-scan, before any model ran.

Every one of these is a question the written rules cannot answer, and each will
keep producing disagreement in production until a taxonomy owner decides it. The
test suite is what the client expects; **this is what changes the product.**

> **Known gap:** in this run the 268 generated ambiguities are recorded in the
> case files but were not merged into `output/ambiguity_register.json`, so the
> workbook's Ambiguous Scenarios sheet shows only the 16 hand-authored entries.
> The merge — dedupe across dispositions, fold in the pre-scan, rank by blast
> radius — is scheduled for v2.

---

## Reproducing it

```bash
export ANTHROPIC_API_KEY=...
export DISPOGEN_DEID_SALT=$(python -c "import secrets;print(secrets.token_hex(16))")
```

```bash
dispogen --client gcli preflight && dispogen --client gcli prescan
```

```bash
dispogen --client gcli generate --workers 20 --skip-existing --tpm 500000 --rpm 500
```

```bash
dispogen --client gcli validate && dispogen --client gcli scan-pii && dispogen --client gcli render
```

The de-identified cases from this run are in
[`examples/gcli/cases/`](../examples/gcli/cases) — three dispositions, with full
rule-traces, safe to read.
