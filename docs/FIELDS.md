# Field Reference — Test Cases sheet

Every column of `output/<client>_TestCases.{xlsx,csv}`, what it means, and which
validator enforces it. Counts and examples are from the GCLI persistency run
(499 cases, 51 dispositions).

The sheet has two halves:

- **Columns 1–11 (green header)** — the *client contract*. Read from your own
  `Output Format` sheet at build time and bound to resolvers by
  `render.contract_map` in `config/clients/<client>.yaml`. Rename a column
  upstream and only the config changes.
- **Columns 12–32 (blue header)** — the *machine columns*. Fixed, listed in
  `render.appended_columns`. **This is the half you score against.**

---

## Scoring: read this first

Three columns decide whether a run passed. Everything else is provenance.

| Level | Column | Engine response field | Example |
|---|---|---|---|
| Group | `expected_group` | `group` | `CTP - Committed to Pay` vs `CTP` |
| Sub | `expected_sub` | `sub` | `0020 - Payment Commitment` vs `0020` |
| Expanded | `expected_expanded` | **`extended`** | `0025 - Assured to pay via Online` vs `0025` |

The engine calls the leaf **`extended`**, not `expanded`. Response shape is
`result.rows[].{group, sub, extended, confidence}`. Join on `test_case_id`.
Split the expected value on `" - "` and compare the code only.

Two more columns are not optional:

- **`certification_grade`** — compare *only* levels up to and including this
  one. Past it, a blank means **must not answer**, not "don't care".
- **`must_not_select`** — if the engine returns any of these codes at any
  level, that is a false positive even when the graded levels match.

`score_case` in `src/dispogen/apiclient.py` already implements all of this.

### Three traps

1. **`Group` / `Sub` / `Expanded` (cols 2–4) are NOT the answer.** They name the
   disposition being *probed*. For a false-positive probe that is deliberately
   the wrong answer — **395 of 499 rows have `Expanded` ≠ `expected_expanded`**.
2. **A blank `expected_sub` / `expected_expanded` is an assertion, not a gap.**
   See `certification_grade` below.
3. **64 cases have no transcript, by design.** See `source_of_truth_class`.

---

## Contract columns (1–11)

| # | Column | Meaning |
|---|---|---|
| 1 | `SN` | Serial **within its disposition**, 1–10. Not a global row id — `SN` 1 appears 51 times. Use `test_case_id` as the key. |
| 2 | `Group` | Group code of the disposition being probed: `CTP`, `FDC`, `CIP`, `NC`. Display only. |
| 3 | `Sub` | Sub-disposition *name* of the disposition being probed, e.g. `Payment Commitment`. Display only; carries no code. |
| 4 | `Expanded` | `engine_code` of the disposition being probed, e.g. `ASSISTANCE_REQUIRED`. The pack this case came from. **Not the expected answer.** |
| 5 | `Type` | `Regression Test case for False Negatives` (255) or `...False Positives` (244). Human-readable form of `probe_type`. |
| 6 | `Test Case Scenario` | One-paragraph statement of what the case is doing and why it is hard. Unique per case. |
| 7 | `Generated Transcript` | The conversation as flat text, `AGENT:` / `CUSTOMER:` prefixed, one turn per line. **Blank on 64 rows** — see `source_of_truth_class`. |
| 8 | `Is Redial Required` | Not a boolean. `Yes – <reason>` / `No – <reason>`, 144 distinct values. The reason is part of the expectation. |
| 9 | `Anchor Date` | The "now" the case is written against. Identical on all 499 rows (`Tue 07 Jul 2026, 14:32`) — a fixed clock is what makes the redial expectations reproducible. |
| 10 | `Redial Schedule Date Time` | Expected next-interaction datetime. V7 checks it falls inside the calling window and strictly after the anchor. |
| 11 | `Transcript New Format` | The same transcript in the engine's wire shape: `{"call_transcript": [{"role": "assistant"\|"user", "content": ..., "cycle_id": ..., "state_id": ...}]}`. `role` maps agent→assistant, customer→user. `cycle_id` / `state_id` are dummies from `classify.dummy_cycle_id`. Produced by the same encoder that builds the classification payload, so the two cannot drift. |

---

## Machine columns (12–32)

### Identity

| Column | Meaning |
|---|---|
| `test_case_id` | `<ENGINE_CODE>-<FN\|FP>-<NN>`, e.g. `ASSISTANCE_REQUIRED-FP-01`. Unique. The join key. |
| `probe_type` | `FN` (255) — the case *is* the host disposition and the engine must find it. `FP` (244) — the case looks like the host but is not, and the engine must not pick it. |
| `archetype` | Which failure mode this case probes; 10 values, ~51 each. **FN:** `canonical`, `paraphrased_trigger`, `late_buried_evidence`, `degraded_input`, `co_occurrence_precedence`. **FP:** `nearest_rival_decoy`, `structural_trap`, `stop_at_parent`, `out_of_class`, `under_determined`. This is the column to group by when you want to know *how* the engine fails, not just how often. |
| `generated_by` | Model that authored the case. |
| `certification_status` | `PROVISIONAL` on all 499 — Gate D (the certification tribunal) has not been run against live models. Cases are validator-clean but not tribunal-certified. |

### The answer

| Column | Meaning |
|---|---|
| `certification_grade` | How deep the evidence licenses a claim: `EXPANDED` (395), `SUB` (49), `GROUP` (55). V13 enforces the shape below exactly. |
| `expected_group` | `CODE - Label`, always present. |
| `expected_sub` | `CODE - Label`. **Blank on the 55 GROUP-grade rows.** |
| `expected_expanded` | `CODE - Label`. **Blank on the 104 GROUP+SUB-grade rows.** |
| `must_not_select` | Comma-separated codes the engine must not return, at any level. Always populated. For FP probes it always contains the host code (V3). It may legitimately contain an *ancestor* of the expected answer — that is the "don't stop at the parent" construction, not a contradiction. V17 only fires when a case forbids the answer at its own declared grade. |

**Why the blanks are load-bearing:**

| grade | rows | `expected_sub` | `expected_expanded` | means |
|---|---|---|---|---|
| EXPANDED | 395 | filled | filled | answer the leaf |
| SUB | 49 | filled | **blank** | stop at the sub — naming a leaf is the failure |
| GROUP | 55 | **blank** | **blank** | stop at the group — naming a sub or leaf is the failure |

The `stop_at_parent` and `under_determined` archetypes exist to catch an engine
that answers deeper than the evidence supports. Filling those blanks in to make
the sheet look complete destroys the probe.

### The rule-trace

This is the mechanism behind the zero-false-positive claim: every case carries a
machine-checkable derivation, so correctness is decided by string containment,
not by a second model's opinion.

| Column | Meaning | Check |
|---|---|---|
| `cited_clause` | The taxonomy text that licenses the answer. Must be a **verbatim substring** of that leaf's `Decision Rules` cell. | V11 |
| `decisive_evidence` | The span of the case's **own transcript** (or telephony/system state) that satisfies the clause. Verbatim. | V11 |
| `rebutted_rivals` | `code: why` pairs, ` \| `-joined. Every case must rebut its nearest rivals, and each rebuttal clause must itself be verbatim taxonomy. | V11 |
| `rival_code` | The single nearest rival this case was built against. Blank on 50 rows where no single rival dominates. | V4 |
| `trap_phrase` | The decoy — text that superficially matches the host disposition but does not license it. Must appear verbatim in the evidence. **Blank on all 255 FN probes**; this is an FP-only field. | V9 |
| `precedence_rule_applied` | `P1`–`P8` when two labels both fire and a precedence rule breaks the tie. Blank on 398 rows where nothing competes. | V14 |

### Context

| Column | Meaning |
|---|---|
| `source_of_truth_class` | **What the case is made of** — `transcript` (388), `telephony` (57), `cross-call` (30), `system` (14), `hybrid` (10). |
| `pre_call_parameters` | JSON of the state the agent had before dialling: policy no., due date, premium, payfile flag, attempt history. For non-transcript classes this *is* the evidence. |
| `perturbations` | Comma-separated axes varied for this case: `language:Hinglish`, `scenario:...`, `channel:...`. V8's near-duplicate check works against these. |
| `redial_context` | What the next interaction must carry forward. V7 requires it non-empty. |
| `redial_basis` | `seeded` (169) — taken from a re-dial matrix row; `derived` (300) — inferred, with the reasoning stated inline. V7 requires the distinction be declared, so you can tell a client-specified schedule from one the generator reasoned out. |

---

## The 64 blank transcripts

`Generated Transcript` is empty on 64 rows, and `Transcript New Format` on those
rows is `{"call_transcript": []}`. This is correct: the call never connected, so
there is no conversation to transcribe.

| `source_of_truth_class` | rows | dispositions |
|---|---|---|
| `telephony` | 54 | `PHONE_BUSY`, `SWITCHED_OFF`, `OUT_OF_COVERAGE`, `RINGING`, `INVALID_NUMBER`, `TEMP_OUT_OF_SERVICE` |
| `system` | 10 | `POLICY_INACTIVE_SYSTEM`, `RENEWAL_ALREADY_PAID` |

Their evidence lives in `pre_call_parameters` — call outcome codes, ring
duration, policy status flags. V6 actively *requires* these cases to carry no
transcript: a `SWITCHED_OFF` case with a conversation in it would be incoherent.

**Consequence for measurement.** A transcript-only classification endpoint
receives nothing for these 64 and cannot succeed on them. In the 2026-08-15 run
they scored **2/64 (3.1%)** against **201/435 (46.2%)** for cases that did carry
a transcript. Either route them through an endpoint that reads call metadata, or
report them separately — folding them into a single accuracy figure blames the
engine for evidence the test channel never delivered.

---

## Validator index

| Rule | Guards |
|---|---|
| V3 | FN expects the host; FP does not, and forbids the host code |
| V4 | Every referenced code exists in the taxonomy |
| V5 | Case matches its pinned FP slot allocation (rival, archetype, no duplicates) |
| V6 | Evidence matches `source_of_truth_class` — transcript cases have customer turns, telephony cases have none |
| V7 | Redial: context non-empty, basis declared, callback inside the window and after the anchor |
| V8 | No near-duplicate cases |
| V9 | `trap_phrase` present in the evidence |
| V10 | Client compliance checks |
| V11 | The rule-trace: `cited_clause`, `decisive_evidence`, `rebutted_rivals` all verbatim |
| V12 | No token the production engine cannot emit |
| V13 | Grade/expected-field shape, and the group→sub→leaf chain is a real ancestry |
| V14 | `precedence_rule_applied` resolves in the taxonomy |
| V15 | Paraphrase probes avoid the literal trigger phrases |
| V16 | **No PII from the source corpus.** Release gate. |
| V17 | A case does not forbid its own answer at its declared grade |
| V18 | Speaker roles are ones production can emit (`agent` / `customer`) |
