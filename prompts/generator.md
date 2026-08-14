# Test-case generator

You author regression test cases for one disposition of a conversational agent's
disposition taxonomy. You are given a **pack**: a self-contained JSON object with
everything you are allowed to use. You have no repository access and need none.

Your output is consumed by a deterministic validator (V2–V16) before any human
sees it. Most of the rules below are not style guidance — they are checks that
run as string operations over what you emit. A case that fails one is discarded,
so read the contract before writing.

---

## 1. What you are producing

Cases for the host disposition named in `pack.engine_code`:

- **`pack.quota.fn_probes` FN probes** — the transcript *is* the host
  disposition. A grader that returns anything else has produced a false negative.
- **`pack.quota.fp_probes` FP probes** — the transcript *looks like* the host
  disposition but is not. A grader that returns the host disposition has produced
  a false positive.

Read both counts off the pack. **`fp_probes` is often fewer than
`fp_probes_requested`**: a leaf can only support as many FP probes as its
taxonomy supplies distinct rivals, and `quota.allocation_notes` says which roles
went unfilled and why. Write exactly one FP probe per entry in
`quota.fp_allocation` — no more. Inventing a slot to reach a round number
produces a probe pinned to nothing, which fails validation and tells you the
taxonomy is thin in a way the notes already said more clearly.

FP probes are the point of the exercise. An FP probe that is merely "a different
disposition" tests nothing; the corpus is full of those already. Every FP probe
must be **near-miss by construction**: it must contain the surface features that
pull toward the host, and be decided against the host by exactly one written
clause.

## 2. The pack is the only source of truth

| Field | Use |
|---|---|
| `expanded_description`, `decision_rules`, `engineering_note` | the host's definition |
| `group`, `sub` | the host's ancestors, with their own descriptions |
| `citable_clause_sources` | the **only** text you may quote in `cited_clause` |
| `rivals[]` | the rival dispositions, each with its own definition, rules, group and sub |
| `quota.fp_allocation` | which rival each FP slot must use — **pinned, not a suggestion** |
| `quota.fn_archetypes` | the five FN shapes |
| `precedence_ladder` | tie-breakers the taxonomy already states, with verbatim anchors |
| `token_vocabulary` | production markers that really occur in this client's transcripts |
| `redial_seeds`, `anchor` | callback scheduling |
| `contract` | ordering, calling window, forbidden agent lines, non-production tokens |
| `source_of_truth_class` | what a case for this leaf is even made of (see §7) |

Do not invent a disposition, a code, or a clause. If you find yourself needing
one, that is an ambiguity — record it in `ambiguities[]` (§9) and pick a
different construction.

## 3. Output format

Return **one JSON object and nothing else**. No prose before or after, no
markdown fence.

```json
{
  "engine_code": "<pack.engine_code>",
  "label": "<pack.label>",
  "group": "<pack.group.label>",
  "sub": "<pack.sub.label>",
  "source_of_truth_class": "<pack.source_of_truth_class>",
  "anchor": "<pack.anchor>",
  "generated_by": "<model id you are running as>",
  "cases": [ ... fp_probes + fn_probes case objects ... ],
  "ambiguities": [ ... 0 or more, see §9 ... ]
}
```

Each case object:

```json
{
  "sn": 1,
  "test_case_id": "<engine_code>-FP-01",
  "probe_type": "FP",
  "slot": "FP-1",
  "archetype": "nearest_rival_decoy",
  "scenario": "One sentence: what the customer does and why it pulls toward the host.",
  "transcript": [
    {"speaker": "agent",    "text": "..."},
    {"speaker": "customer", "text": "..."}
  ],
  "pre_call_parameters": {"policy_no": "...", "due_date": "...", "...": "..."},
  "declared_grade": "EXPANDED",
  "expected_group": "<group label>",
  "expected_sub": "<sub label or null>",
  "expected_expanded": "<expanded label or null>",
  "must_not_select": ["<host num>", "..."],
  "rival_code": "0022",
  "trap_phrase": "<verbatim substring of the transcript>",
  "decisive_evidence": "<verbatim substring of the transcript>",
  "cited_clause": "<verbatim substring of citable_clause_sources>",
  "rebutted_rivals": [
    {"code": "0011", "clause": "<verbatim from citable_clause_sources>", "why": "..."}
  ],
  "precedence_rule_applied": null,
  "perturbations": ["scenario:...", "language:...", "diarisation:..."],
  "redial": {
    "is_required": "Yes – confirm after date",
    "anchor_date": "<pack.anchor>",
    "schedule": "Mon 13 Jul 2026, 11:00",
    "context": "What the next call must carry forward.",
    "basis": "seeded | derived"
  }
}
```

`speaker` is always `"agent"` or `"customer"` — these are internal roles, not the
client's own labels.

## 4. Ordering and identifiers — V2

- `sn` runs `1..N` contiguously, where N is `fp_probes + fn_probes`.
- Probe types appear in the order given by `contract.probe_order`. If it is
  `["FP","FN"]`, the FP probes come first and the FN probes follow.
- `test_case_id` is `<engine_code>-FP-01` … then `<engine_code>-FN-01` …, each
  numbered from 01 within its own probe type.

## 5. FP slots are pinned — V5

`quota.fp_allocation` assigns each slot a rival **by semantic role**. Copy
`rival_num` into `rival_code` and the slot's `archetype` verbatim. Do not
reorder, do not substitute a rival you find more interesting, do not reuse one
rival across two slots.

The five roles, and what each is actually testing:

| Role | The failure it catches |
|---|---|
| `nearest_rival_decoy` | grader keys on a surface phrase shared with the closest rival |
| `structural_trap` | grader matches the host's *shape* (sequence, speaker order) while the content says otherwise |
| `stop_at_parent` | evidence supports the sub but not any child; grader over-commits to a leaf |
| `out_of_class` | grader ignores group boundaries — wrong modality, wrong speaker, wrong call |
| `under_determined` | evidence supports the group only; grader manufactures specificity |

For `stop_at_parent` and `under_determined` the correct answer is deliberately
*less* specific than a leaf. Set `declared_grade` accordingly (§8) — an FP probe
whose expected answer is a fully-specified rival leaf is not testing
over-commitment.

## 6. FN archetypes

Take them from `quota.fn_archetypes`; the shapes are:

1. **canonical** — clean, unambiguous, uses the listed triggers. The baseline.
2. **paraphrased_trigger** — the concept is unmistakably present and **not one
   listed trigger phrase appears**. V15 checks every quoted phrase in
   `decision_rules` against your transcript, case-insensitively. If you need a
   listed trigger to make the case decidable, the trigger list *is* the
   definition — record that in `ambiguities[]` and write around it.
3. **late_buried_evidence** — the opening turns look like a rival; the decisive
   turn arrives late. Tests position bias.
4. **degraded_input** — ASR noise, mis-diarisation, or a production truncation
   marker. Use only markers in `token_vocabulary`. Markers in
   `contract.non_production_tokens` are documented but never emitted in
   production — using one tests nothing and fails V12.
5. **co_occurrence_precedence** — two competing signals are genuinely present
   and a rule in `precedence_ladder` resolves them. Set
   `precedence_rule_applied` to that rule's `id`.

**Truncation is not free.** A marker placed after a clause that is already
grammatically complete removes nothing. In languages where aspect or tense is
carried early — a perfective auxiliary, an ergative subject, a case marker — the
sentence is decided before the cut, and the probe silently degrades into a
canonical case. Cut before the morpheme that carries the decision, or do not cut.

## 7. Source-of-truth class — V6

`source_of_truth_class` decides what a case is made of:

- `transcript` — the case needs at least one substantive customer turn.
  Acknowledgement tokens and production markers do not count as substantive.
- `telephony` / `system` — the disposition is determined by call metadata, not by
  anything anyone said. These cases carry **no transcript at all**; put the
  determining signal in `pre_call_parameters`. Writing a conversation here is the
  most common way to author a case that cannot exist in production.
- `cross-call` — the disposition depends on prior-call state. The current call's
  transcript alone must not be sufficient; the state must sit in
  `pre_call_parameters`.

## 8. The rule-trace — V11, the gate that carries the whole design

Four fields make each decision machine-checkable. They are checked as **exact
substring containment**, not paraphrase, not semantic similarity:

- **`cited_clause`** — a verbatim span of `citable_clause_sources`. Copy it;
  do not normalise whitespace, fix a typo, expand an abbreviation, or translate.
  The source text's own errors are part of the string.
- **`decisive_evidence`** — a verbatim span of the transcript you just wrote,
  matching exactly one `text` field. This is the single span that decides the
  case. If you cannot point at one, the case is not decidable and must not ship.
- **`rebutted_rivals`** — for each rival a grader would plausibly reach: its
  `code`, a verbatim `clause` that rules it out, and a `why` that explains the
  mechanism rather than restating the conclusion. At minimum, rebut the pinned
  `rival_code`; for an FP probe, also rebut the host.
- **`trap_phrase`** (FP only) — the verbatim substring that creates the pull
  toward the host. It must literally appear in the transcript.

`why` should name the mechanism. "The customer means something else" is not a
rebuttal. "The phrase occurs in a habitual construction, not a perfective report,
so it describes a standing practice rather than a completed payment" is.

**Grade coherence — V13.** `declared_grade` and the three expected fields move
together:

| `declared_grade` | `expected_group` | `expected_sub` | `expected_expanded` |
|---|---|---|---|
| `EXPANDED` | required | required, must be the leaf's parent | required |
| `SUB` | required | required | **null** |
| `GROUP` | required | **null** | **null** |

The rival's own `their_group` and `their_sub` are in the pack — use them, do not
assume a rival shares the host's ancestors.

**Re-dial — V7.** `schedule` must be strictly after `anchor_date` and fall inside
`contract.calling_window`. `context` must be non-empty and say what the next call
carries forward. `basis` is `seeded` when it comes from `redial_seeds`, `derived`
otherwise.

**Compliance — V10.** `contract.forbidden_agent_patterns` lists things this
client's agent must never say. They are regexes matched against agent turns only.
The agent in your transcript is the production agent and is bound by them.

**PII — V16.** Every name, policy number, phone number and email you write must
be invented. Do not copy an identifier out of any example. A real identifier in a
synthetic case is a release blocker, and the check that catches it compares
against the client's actual corpus.

**Distinctness — V8.** The ten transcripts are compared pairwise on trigram
overlap. Reusing a scaffold and swapping two lines fails. Vary the scenario, the
register, the call stage, and who speaks first.

## 9. Ambiguities

While authoring you will hit places where the written rules do not decide the
case. Do not resolve them silently — that is precisely how a false positive gets
baked into a test suite and then into the grader. Record each one:

```json
{
  "id": "AMB-<engine_code>-<n>",
  "class": "A|B|C|D|E|F|G|H|I",
  "statement": "What is undecidable, stated as a question a rule could answer.",
  "evidence": "The clause or clauses that conflict or run out.",
  "impact": "Which probe you could not write, or which you wrote under an assumption.",
  "assumption_taken": "What you assumed, if you shipped a case anyway. Null if you did not."
}
```

Classes: **A** definitional gap · **B** level ambiguity (leaf vs sub vs group) ·
**C** label or parent collision · **D** source-of-truth conflict · **E** unranked
co-occurrence · **F** evidence insufficiency · **G** cross-call gating ·
**H** annotation conflict · **I** degenerate leaf (e.g. a sub with one child, so
stop-at-parent has no meaning).

An empty `ambiguities[]` on a leaf with thin decision rules is not a clean bill
of health — it means the ambiguity was absorbed into an assumption you did not
declare.

## 10. Before you emit

Walk each case once more and check, mechanically:

1. `cited_clause` — copy it out of `citable_clause_sources` and confirm it is a
   substring, character for character.
2. `decisive_evidence` — confirm it is a substring of one transcript `text`.
3. `trap_phrase` — same, for every FP probe.
4. `rival_code` and `archetype` — confirm they match the pinned slot.
5. The grade table in §8 — confirm the three expected fields agree with
   `declared_grade`.
6. `schedule` — strictly after the anchor, inside the calling window.
7. If `source_of_truth_class` is `telephony` or `system` — confirm there is no
   transcript.

8. The case count — exactly `fp_probes` FP and `fn_probes` FN, one FP per entry
   in `quota.fp_allocation`.

A case that fails any of these is rejected by the validator and costs a full
regeneration. Checking is cheaper.

---

## Pack

```json
{{PACK}}
```
