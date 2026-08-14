# Disposition Test-Case Generator — Architecture v2 (for review)

**Reviewer inputs:** Disposition_TestCase_Generator_Architecture_1.docx (v1 plan), GCLI_Persistency_Disposition_Definitions.xlsx (×2), Persistency_ReDial_Automation_Test_Matrix.xlsx, persistency Report.xlsx, Persistency System Prompt.md, Configuration Design Document — Persistency Agent.xlsx
**Date:** 14 Aug 2026 · **Status:** proposed, awaiting sign-off

---

## 0. The one-line thesis, restated

The v1 plan says:

> *The LLM writes conversations. Nothing else.*

That is right and I am keeping it. But it is not sufficient for the stated objective. v1 optimises for **coverage** (520 cases, all 52 leaves). The objective is **zero false positives**. Those are different targets and they pull in opposite directions: every mechanism that guarantees you produce 10 cases per disposition is a mechanism that forces a label onto a case that may not deserve one.

So v2 adds a second thesis on top of the first:

> **Ambiguity is not resolved. It is routed.**
> A case enters the graded suite only if it earns a certificate. Everything else leaves the suite alive and lands in the Ambiguous Register. The register is a deliverable, not a failure log.

Concretely: v1's Phase 5 critic resolves disagreement by *majority vote* (2-of-3 wins, 3-way split → human queue). Majority vote is a mechanism for **producing a label**. We need a mechanism for **refusing to produce one**. That single change is the spine of v2.

---

## 1. What I verified before changing anything

Every number below was measured directly from the files, not taken from the v1 document.

### 1.1 Claims that hold

| v1 claim | Measured | |
|---|---|---|
| 52 expanded dispositions, 52 unique engine codes, 5 groups | 52 / 52 / 5 | ✅ |
| `(group, sub, expanded)` unique as a triple | true | ✅ |
| Re-Dial matrix: 83 populated rows, 51 of 52 codes | 83 rows, 51 codes (missing: `Needs Human Review`) | ✅ |
| 17 human-annotated classifier errors | exactly 17 | ✅ |
| Confusion graph is machine-extractable, zero dangling rivals | 0 dangling refs across all 52 leaves | ✅ |
| Extreme seed distribution — never sample uniformly | 0061 has 12 rows; 36 codes have exactly 1 | ✅ |

### 1.2 Claims that are wrong, and what each one breaks

| v1 claim | Measured | What it breaks |
|---|---|---|
| "5 groups, **15 subs**" | **13 subs** | Preflight P5 asserts a count. Hardcoding 15 fails the gate on valid input. |
| "**48 of 52** leaves carry explicit rivals (92%)" | **49 of 52 (94%)**. The three without: `0082 SWITCHED_OFF`, `0084 PHONE_BUSY`, `NEEDS_HUMAN_REVIEW` | Same — and it matters *which* three, because all three need a fallback rival policy, not a count. |
| "At least **3** transcript encodings" | **4**: py-repr list-of-dicts (80), flat `ASSISTANT:/USER:` (90), flat `AGENT:/CUSTOMER:` (13), flat `User:/Assistant:` (30) | The normaliser ships with a missing decoder → silent zero-exemplar yield on that source. |
| Transcripts are "JSON list of `{text, speaker}`" | They are **Python repr** (single-quoted). `json.loads` throws on all 80. | Needs `ast.literal_eval`, not `json.loads`. One-line fix, total data loss if missed. |
| "**Five** inputs" | **Six.** The Configuration Design Document was never assigned a role. | See §1.4 — it is the second-most valuable file in the set. |
| §16.1: "Output format template … was not attached" | **It is attached** — Desktop copy of the disposition workbook, sheet `Output Format`, 11 columns | §8's entire schema was derived from the wrong sheet. See §6. |
| Perturbation axis uses `[/interrupted]` | Production data uses **`</interrupted>`** (86 occurrences). Also present and undocumented: `<silence-detected/>` (4), `<end-call-silence-detection/>` (2) | Every degraded-input probe would carry a token the classifier has never seen. The perturbation tests nothing. |

### 1.3 Structural findings v1 does not mention at all

These change the design, not just the numbers.

**(a) 10 of 52 leaves cannot source 5 distinct FP rivals.**
v1 §7.3 pins a 5-way FP allocation across ranked rivals. I computed the actual supply per leaf (explicit rivals ∪ siblings ∪ parent):

```
0111 RENEWAL_ALREADY_PAID        3 rivals    0051 LANG_REROUTE_REGIONAL       4
0071 NRPC_AGENT_DISTRIBUTOR      4           0031 FINANCIAL_UNSTABLE          4
0032 FINANCIAL_WONT_PAY          3           0101 POLICY_INACTIVE_SYSTEM      2
0074 WRONG_NUMBER                4           091  INVALID_NUMBER              3
092  TEMP_OUT_OF_SERVICE         2           NEEDS_HUMAN_REVIEW              0
```

`NEEDS_HUMAN_REVIEW` has **zero** rivals by construction. A pinned 5-way allocation is unsatisfiable for it. Under v1, validator V5 rejects, repair fails twice, the disposition quarantines — and the single most important abstention behaviour in the system goes untested.

**(b) 5 leaves have a singleton sub → FP-3 (stop-at-parent) is degenerate.**
`0110→0111`, `0050→0051`, `0100→0101`, `0070(NC)→0074`, `REVIEW→NHR`. When a sub has exactly one child, "stop at the parent" carries identical information to naming the leaf. v1 caveats *"mandatory for every disposition that has siblings"* but never specifies the substitute archetype. Five leaves get a silently under-specified quota.

**(c) The "0050 collision" is real but mis-stated, and the worse collision is 0070.**
Leaf numeric labels *are* unique (52/52). The collision is **cross-level**: leaf `0050 Policy not applied` vs sub `0050 Language Barrier`. Meanwhile sub `0070 No Right Party Contact` exists under **two different groups** with two different engine codes (`NRPC_CIP`, `NRPC_NC`) — and `0074`'s own decision rule points at `0071`/`0072`, which live under the *other* parent. A naive parent-resolver cross-wires CIP and NC on the highest-traffic third-party-answered boundary in the taxonomy.

**(d) The verified-error corpus is contested. This is the finding that matters most.**

v1 §7.4: *"Real beats synthetic every time."* §2.3: *"pre-verified regression cases with ground-truth labels supplied by a domain expert."* They are pinned into quota unexamined.

I read all 17. **At least 5 conflict with, or are under-determined by, the taxonomy as written:**

| Row | Engine said | Human said | Problem |
|---|---|---|---|
| 30-07 r10 | `0063` | `0044 Product Not Satisfied` | Customer said only *"not interested"*. Sub-0040 states explicitly: *"NOT 0040: a soft 'not interested' with no reason → prefer 0061 or 0032."* And 0044 requires a product complaint, which is absent. The annotator even writes *"closest leaf … no specific reason given."* **Under the rules the answer is 0061.** |
| 21-07 r31 | `0041 Deceased` | *"0070 No Right Party Contact"* | Receiver says *"निशा जी को हम नहीं जानते"* — **denies** the relationship. Denial routes to NC/`0074`, not CIP/`0070`. The annotation names the ambiguous duplicated sub and picks the wrong branch. |
| 21-07 r30 | `0051` | *"call back"* | Whole transcript is agent greeting + `"hello"`. One substantive turn before purpose stated → `0063` by the operational test. No later time was ever requested, so `0061` is unsupported. |
| 21-07 r63 | `0027` | *"call back 2 days before due date **and also** committed to pay"* | Two labels. Precedence rule says payment intent outranks callback. Annotation is internally unresolved. |
| 30-07 r7 | `0051` | *"0025 **(or 0020-family)"*| Annotator explicitly hedges the leaf. |

**Consequence:** pinning the corpus as gold injects ~29% contested labels straight into the graded suite. That is not a marginal risk to the zero-FP objective — it is the largest single source of false positives in the v1 design, and it enters through the door v1 trusts most.

The corpus is still the most valuable asset in the repository. It just needs to be treated as **evidence of confusion**, not as **ground truth**. See §5.3.

### 1.4 The sixth input

`Configuration Design Document — Persistency Agent.xlsx` was attached but has no role in v1. It contains:

| Sheet | Rows | Why it matters |
|---|---|---|
| **UAT** | **78 human-authored test cases** with preconditions, simulated utterances, expected agent behaviour, **expected disposition**, and failure indicators — across 14 categories (Compliance 14, Happy Path 12, Edge Case 9, Persona 7, Adversarial 6, Multilingual 5, Silence & Interruption 5 …) | A second gold corpus, larger than the 17-row one, already written in probe form, and it carries *expected outcome* + *failure indicators* — exactly the FN/FP framing. |
| Objection Handling | 18 objections × 10 status-cell variants | The generator's source of realistic customer pushback per matrix cell. Without it, FN-3 (buried evidence) has nothing plausible to bury the evidence *under*. |
| FAQ KB | 30 questions × 10 status variants | Same, for distractor turns. |
| Pre-Call Parameters | 37 variables with types and examples | The de-identified `lead_parameter_pool` v1 §6.5 assumes but never sources. |
| Call Flow, Branch Locations, Dummy Leads, Post-Interaction Audit | — | Flow-node grounding; realistic branch/city references; audit-parameter alignment. |

**Recommendation:** promote to a first-class input. The UAT sheet in particular should seed a 7th probe archetype (§5.2).

---

## 2. First-principles reframing

Strip the problem to its irreducible form.

**What is a test case, minimally?** A triple `(evidence, expected_label, decision_procedure)` where the decision procedure is what makes the expected label *derivable* rather than *asserted*.

v1 produces the first two and treats the third as commentary (*"a one-line rationale"*). That is the root cause of the FP exposure. If the rationale is prose, only a human or another model can check it — and a model that shares the generator's blind spot will nod along. **Make the decision procedure machine-checkable and the FP problem changes character**: from *"do we trust the label?"* to *"does the cited clause exist, does the trigger phrase literally appear, and does any competing clause fire unrebutted?"* All three are string operations.

**Where do false positives in the suite actually come from?** Four sources, in descending order of measured volume:

| # | Source | Evidence | v1 defence | v2 defence |
|---|---|---|---|---|
| 1 | **Contested gold** — human annotation conflicts with written rules | 5 of 17 (29%) | none (pinned unexamined) | §5.3 corpus is demoted to evidence; label re-derived and certified like any other |
| 2 | **Level over-specification** — leaf asserted where only the sub is supported | 48 of 106 gold labels grade at sub level | FP-3 probe only | §4.3 grade-level demotion — every case declares its grade, certification runs at that grade |
| 3 | **Genuine taxonomy ambiguity** — two clauses of equal precedence both fire | e.g. bare *"not interested"* has no leaf | none | §4.4 precedence ladder; unresolved → Ambiguous Register |
| 4 | **Generator hallucination** — plausible case, wrong label | unknown | 2-of-3 critic vote | §4 unanimity + rule-trace + adversarial advocate |

**The key asymmetry.** A false positive in the suite costs far more than a missing case. A missing case is a coverage gap you can see in a report. A false positive is a red regression run that is actually a suite bug — and the second time that happens the team stops trusting the suite, which destroys the entire investment. v1 acknowledges this in §14 but the mitigation (majority vote) is calibrated for throughput.

**Therefore the design rule for v2:** *at every fork, prefer refusing over guessing.* Yield is recovered by regenerating into the vacated slot (§4.6), not by lowering the bar.

---

## 3. Master architecture

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  INPUTS  (read-only, sha256-pinned)                                           │
│  ① system_prompt.md ② disposition_definitions.xlsx ③ redial_test_matrix.xlsx  │
│  ④ interaction_report.xlsx ⑤ output_format (sheet) ⑥ config_design.xlsx ★NEW  │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 0   PREFLIGHT GATE                              deterministic · no LLM ║
║  P1–P13 (v1)  +  P14 encoding coverage   P15 rival-supply feasibility         ║
║  P16 precedence-ladder extraction   P17 token-vocabulary match                ║
║  HARD STOP on failure → context_manifest.json + config_hash                   ║
╚═══════════════════════════════╤═══════════════════════════════════════════════╝
                                ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 1   CONTEXT COMPILER                            deterministic · no LLM ║
║                                                                               ║
║   taxonomy.json ──► confusion_graph.json ──► PRECEDENCE LADDER (P1–P8) ★NEW   ║
║        │                    │                        │                        ║
║        │                    ▼                        ▼                        ║
║        │        6-tier rival allocator ★NEW    ambiguity pre-scan ★NEW        ║
║        │        (degrades, never fabricates)   (static clause collisions)     ║
║        ▼                                                                      ║
║   transcript normaliser (4 decoders) ──► exemplar miner ──► prompt slicer     ║
║        │                                                                      ║
║   seeds: verified_errors(17, DEMOTED to evidence) · redial(83) · UAT(78)★NEW  ║
║                                                                               ║
║                        ▼                                                      ║
║              52 self-contained packs  (≤42k tokens, hard budget)              ║
╚═══════════════════════════════╤═══════════════════════════════════════════════╝
                                ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 2   ORCHESTRATOR                                    Claude Code · thin ║
║  reads state/ · enqueues NOT-CERTIFIED · dispatches waves of 6                ║
║  never reads a pack, a transcript, or a case.  Context flat in N.             ║
╚═══════════════════════════════╤═══════════════════════════════════════════════╝
                                ▼  fan-out × 52
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 3   GENERATOR SUBAGENT × 52                        routed frontier LLM ║
║  1 pack in → up to 10 cases out (5 FN archetypes + 5 FP allocations)          ║
║  EACH CASE MUST EMIT A RULE-TRACE:  ★NEW                                      ║
║    { cited_clause (verbatim from Decision Rules)                              ║
║    , decisive_span  (verbatim from the transcript)                            ║
║    , rebutted_rivals[ {code, why_it_does_not_fire, clause} ]                  ║
║    , declared_grade: GROUP | SUB | EXPANDED }                                 ║
║  + learnings/inbox/<engine_code>.md                                           ║
╚═══════════════════════════════╤═══════════════════════════════════════════════╝
                                ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 4   STRUCTURAL VALIDATION      V1–V10 (v1) + V11–V14 ★NEW  · no LLM    ║
║  V11 rule-trace integrity · V12 token-vocabulary · V13 grade coherence        ║
║  V14 precedence conformance         reject → repair (≤2) → quarantine         ║
╚═══════════════════════════════╤═══════════════════════════════════════════════╝
                                ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 5   CERTIFICATION TRIBUNAL           ★NEW — replaces the v1 critic     ║
║                                                                               ║
║        ┌──────────────┬──────────────┬──────────────┐                        ║
║        │  Labeller A  │  Labeller B  │  Labeller C  │  blind · taxonomy-only  ║
║        │  family 1    │  family 2    │  family 3    │  no label, no probe     ║
║        └──────┬───────┴──────┬───────┴──────┬───────┘  type, no rationale     ║
║               └──────────────┼──────────────┘                                 ║
║                              ▼                                                ║
║                    UNANIMOUS at declared grade?                               ║
║                     │                      │                                  ║
║                    YES                    NO                                  ║
║                     ▼                      ▼                                  ║
║          ADVERSARIAL ADVOCATE      DEMOTE ONE GRADE ──► re-poll                ║
║          (argues FOR the rival,     EXPANDED → SUB → GROUP                    ║
║           must cite a clause)              │                                  ║
║                     │                      └── exhausted ──┐                  ║
║           rebutted? │ no ──────────────────────────────────┤                  ║
║                    yes                                     ▼                  ║
║                     ▼                            ╔══════════════════╗         ║
║              ✅ CERTIFIED                        ║ AMBIGUOUS        ║         ║
║              → graded suite                      ║ REGISTER         ║         ║
║                                                  ╚════════╤═════════╝         ║
╚═══════════════════════════════╤═══════════════════════════════════╪═══════════╝
                                │                                   │
                                │        ┌──────────────────────────┘
                                ▼        ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 6   AMBIGUITY REGISTER COMPILER                    ★NEW  · no LLM      ║
║  classify every exile into A–I (§7) · attach colliding clauses verbatim ·     ║
║  cluster · rank by production frequency · emit proposed taxonomy amendment    ║
║  ◄── also fed by: Phase 1 static pre-scan, contested gold (§5.3),             ║
║      V14 precedence conflicts, low-confidence production rows                 ║
╚═══════════════════════════════╤═══════════════════════════════════════════════╝
                                ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 7   BACKFILL LOOP  ★NEW   slot vacated by exile → regenerate (≤3)      ║
║            then MERGE & RENDER                            deterministic       ║
║  learnings rollup · coverage report · workbook build (openpyxl)               ║
╚═══════════════════════════════╤═══════════════════════════════════════════════╝
                                ▼
      ┌──────────────────────────────────────────────────────────────┐
      │  Sheet 1  Test Cases        (CERTIFIED ONLY — the graded suite)│
      │  Sheet 2  Ambiguous Scenarios  ★ the section you asked for    │
      │  Sheet 3  Coverage Matrix   Sheet 4  Re-Dial Expectations     │
      │  Sheet 5  Taxonomy Defect Report   Sheet 6  Run Metadata      │
      └──────────────────────────────────────────────────────────────┘
```

---

## 4. Phase 5 in detail — the zero-FP mechanism

This is the part that is genuinely new, so it gets the detail.

### 4.1 Why unanimity, not majority

Majority vote answers *"what is the most likely label?"* We need the answer to *"is there any reasonable reading under which this label is wrong?"* Those are different questions. A 2-1 split is direct evidence that a competent reader reached a different conclusion — which is the definition of a case that should not be graded pass/fail. v1 treats 2-1 as a resolved case. v2 treats it as a signal.

Cost: unanimity across 3 families rejects more. That is the point, and §4.6 recovers the yield.

### 4.2 Machine-checkable rule-trace (runs *before* any labeller)

Each case ships a trace. Four deterministic checks, no model involved:

1. **Clause existence** — `cited_clause` must be a verbatim substring of that leaf's `Decision Rules` cell. Not paraphrased. String match.
2. **Span presence** — `decisive_span` must be a verbatim substring of the generated transcript.
3. **Rival non-firing** — for every code in the leaf's rival set, no rival TRIGGER phrase may appear in the transcript *unless* `rebutted_rivals` names it and cites the clause that defeats it.
4. **Trap presence (FP cases)** — `trap_phrase` must literally appear, and must be drawn from the *host* disposition's trigger list.

This catches the failure mode that model-based critique structurally cannot: a plausible-sounding label that no written rule actually licenses. It is also the check that survives shared blind spots across model families.

### 4.3 Grade-level demotion — the yield-preserving move

The taxonomy's own highest-value rule is *stop at the parent when the channel is not named*, and 48 of 106 gold labels grade at sub level. So a case can be certain at one level and uncertain at the next. v2 makes the grade a first-class field.

```
   declared_grade = EXPANDED         unanimous? ── yes ──► CERTIFIED @ EXPANDED
          │                                                 expected_expanded = 0025
          └── no ──► demote to SUB   unanimous? ── yes ──► CERTIFIED @ SUB
                       │                                    expected_expanded = NULL
                       │                                    expected_sub      = 0020
                       │                                    must_not_select   still enforced
                       └── no ──► demote to GROUP  ── yes ──► CERTIFIED @ GROUP
                                    │
                                    └── no ──► AMBIGUOUS REGISTER
```

A case certified at SUB is a **fully valid, fully gradeable test case** — it asserts less, and what it asserts is true. This is the single biggest reason v2 does not bleed coverage: most "ambiguous" cases are not ambiguous at all, they are ambiguous *one level down*. It also directly regression-tests the over-specification bug that is the taxonomy's largest documented error class.

### 4.4 The precedence ladder — determinism where the taxonomy already decided

The taxonomy states its own tie-breakers. They are extractable and should be enforced in Python, not re-litigated by a model. All eight are quoted verbatim from the definitions file:

| # | Rule | Source clause |
|---|---|---|
| P1 | Any payment intent → **CTP beats CIP** | *"a call-back request that also contains 'pay kar dunga' is CTP, not CIP"* |
| P2 | Money reason → **0031 beats 0061** | *"THIS CODE OUTRANKS 0061 … even when the customer also names a date"* |
| P3 | Death report → **0041 beats 0072** | *"This code OVERRIDES 0072 even though a relative answered"* |
| P4 | System status beats customer assertion | *"0110 is driven by system … 0010 is driven by the customer's claim"*; *"0101 is the SYSTEM confirming"* |
| P5 | Channel not named → **stop at sub** | *"If the channel is not named, STOP AT 0010"* / *"STOP AT 0020"* |
| P6 | Language evidence beats call brevity | *"The call being short and courteous does NOT downgrade this to 0063"* |
| P7 | Relationship acknowledged → CIP 0071/0072; denied → NC 0074 | *"if the receiver ACKNOWLEDGES knowing the policyholder … it is CIP, not 0074"* |
| P8 | 0 substantive turns → 0083; 1 turn pre-purpose → 0063; identified audio fault → 0062 | operational tests in 0083 / 0063 / 0062 |

**Decision rule:** if the ladder resolves a co-occurrence, the case is **not** ambiguous — it is a precedence test, and it becomes an FN-5 probe. If two clauses of *equal* precedence both fire, or no rule covers the collision, it is **genuinely** ambiguous → Register. This distinction is what keeps the Register honest: it contains real taxonomy gaps, not model uncertainty.

### 4.5 The adversarial advocate

Unanimity has a failure mode: three labellers can be unanimously wrong on a case the generator made *too easy*. So after unanimity, one more agent is asked to **argue for the strongest rival** and must cite a clause. If the advocate produces a citation that the case's rule-trace does not already rebut with a higher-precedence clause → the case goes to the Register even though the vote was unanimous.

This also produces `trap_strength`, which is what acceptance criterion A3 actually needs.

### 4.6 Backfill

Exiling a case vacates an archetype slot. The orchestrator re-enqueues that slot with the exile's rule-trace attached as a negative example (*"this framing was ambiguous because X — do not reproduce it"*), up to 3 attempts. After 3, the slot is reported short in the coverage matrix rather than filled with a weaker case.

Net effect: the graded suite still targets 10/leaf, the Register grows in parallel, and neither one is padded.

---

## 5. Changes to Phases 1, 3 and the seed policy

### 5.1 Six-tier rival allocator (fixes §1.3a)

Replaces v1's flat "distribute 5 across ranked rivals". Draws in order until 5 distinct rivals are found:

```
T1  empirical rivals   (observed in the 17-row corpus / low-confidence rows)   weight 1.2
T2  explicit rivals    (regex over NOT THIS / THE BOUNDARY vs / tie-breaker)   weight 1.0
T3  siblings           (same sub — structurally confusable by construction)    weight 0.8
T4  parent             (stop-at-parent)  — SKIPPED if sub is singleton         weight 0.9
T5  out-of-class       (from the group-level NOT clauses; telephony/system/
                        cross-call codes the transcript classifier must not
                        select)                                               weight 0.7
T6  under-determined   (abstention / insufficient evidence)                    weight 0.6
```

If supply < 5 after all six tiers → **reduce the FP count and reallocate to FN**, log the shortfall. Never fabricate a rival. Applies to the 10 leaves in §1.3a.

**Special case — `NEEDS_HUMAN_REVIEW` (0 rivals).** Its FP probes invert: 5 cases that *look* unclassifiable but are resolvable at group level, because the taxonomy says NHR *"must never be reached because a leaf was ambiguous."* Over-selecting NHR is the exact failure mode. This is the most valuable leaf in the suite and v1 quarantines it.

**Special case — singleton subs (5 leaves).** FP-3 stop-at-parent is replaced by **FP-3′ cross-group boundary**: a case whose evidence sits on the group boundary this leaf guards (e.g. `0074` ↔ `0071/0072` — the acknowledged-vs-denied relationship test, which is P7 and also the most frequent real-world confusion in the corpus).

### 5.2 Probe archetypes — 5 FN + 5 FP, with two fixes

FN-1…FN-5 and FP-1…FP-5 carry over from v1 §7.2/§7.3 unchanged in intent. Two amendments:

- **FN-4 (degraded input)** must use the **production token vocabulary**: `</interrupted>`, `<silence-detected/>`, `<end-call-silence-detection/>`. Not `[/interrupted]`. Enforced by validator V12 against a vocabulary extracted from the corpus at preflight.
- **New: FN-6 / FP-6 "UAT replay"** — where the Configuration Design UAT sheet has a case for this disposition (13 leaves have one), it is adapted rather than invented. These 78 cases already carry expected outcome + failure indicators. Adapted, not pinned: they go through the same tribunal as everything else.

### 5.3 Seed policy — demoting the gold corpus

The change that most directly serves the zero-FP objective.

| Corpus | v1 treatment | v2 treatment |
|---|---|---|
| 17 verified errors | pinned as ground truth, replace a generated case | **Evidence, not label.** The transcript + the *fact of confusion* are pinned (this is what feeds T1 empirical rivals, which is genuinely high value). The **label is re-derived** from the rules and must clear the tribunal like any other case. |
| — where human label agrees with derived label | — | pinned as `provenance: verified_error`, `trap_strength: production_confirmed` — the strongest cases in the suite |
| — where human label conflicts (5 of 17) | pinned anyway ❌ | routed to the **Ambiguous Register, class H**, with both labels, both clause citations, and a proposed taxonomy amendment |

We keep 100% of the corpus's value (A7 still satisfiable — every row is *used*), and we stop it from being the largest FP vector in the system.

### 5.4 New preflight checks

| # | Check | Prevents |
|---|---|---|
| P14 | Every transcript cell decodes under one of 4 registered decoders; count per decoder logged | Silent zero-exemplar yield on an unrecognised encoding |
| P15 | Rival-supply feasibility computed per leaf; leaves with <5 flagged and their quota rewritten *before* generation | V5 rejection loops → needless quarantine |
| P16 | Precedence ladder extracts to ≥8 rules; each cites a locatable clause | Model re-litigating decisions the taxonomy already made |
| P17 | Token vocabulary extracted from corpus; asserted non-empty and disjoint from the system prompt's documented set where they differ | Perturbations the classifier has never seen |

---

## 6. Output contract — corrected

v1 §8 built the schema on the Re-Dial Matrix's 10 columns because the format reference was believed missing. **It is present**: `GCLI_Persistency_Disposition_Definitions.xlsx` (Desktop) → sheet `Output Format`. Its actual contract, and it differs in three material ways:

```
SN | Group | Sub | Expanded | Type | Test Case Scenario | Generated Transcript
   | Is Redial Required | Anchor Date | Redial Schedule Date Time | Transcript New Format
```

1. **`Expanded` holds the engine code**, not the numeric label (`SUBMITTED_TO_ADVISOR`, not `0011`). Which is exactly what §2.2 of v1 argues for — the format already agrees.
2. **`Type` is the probe type**, values `Regression Test case for False Positives` / `… False Negatives`.
3. **Ordering is FP first (SN 1–5), then FN (SN 6–10)** — v1 assumes FN first. Cosmetic, but it is the drop-in contract.
4. Row 15 confirms the target: *"Similarly to be added across all the other dispositions (520 total across 52 expanded dispositions)."*

**Proposal:** Sheet 1 preserves these 11 columns exactly, in order. Grading/provenance/certification fields append to the right:

`test_case_id · certification_grade (EXPANDED|SUB|GROUP) · expected_group/sub/expanded · must_not_select · rival_code · trap_phrase · decisive_evidence · cited_clause · rebutted_rivals · precedence_rule_applied · source_of_truth_class · pre_call_parameters · perturbations · tribunal_votes · advocate_verdict · trap_strength · provenance`

Note `expected_expanded` is **nullable** — that is what a SUB-grade certification looks like, and it is a feature.

---

## 7. The Ambiguous Scenarios section

Your explicit requirement: *"a separate section for ambiguous scenarios at the end created based on all the insights collected."* This is Sheet 2, and it is fed from five sources, not one:

```
   Phase 1 static pre-scan ────┐   clause collisions found before any generation
   V14 precedence conflicts ───┤
   Tribunal exiles ────────────┼──►  AMBIGUOUS REGISTER  ──► ranked, clustered,
   Contested gold (5 of 17) ───┤                              amendment-proposing
   Low-confidence production ──┘
```

**Nine ambiguity classes**, each derived from something measured in these files:

| Class | Definition | Live example from the corpus |
|---|---|---|
| **A** Definitional gap | Evidence is clear; no leaf covers it | Bare *"not interested"*: sub-0040 forbids 0040, 0044 requires a product complaint, 0032 requires money. No leaf fits. (30-07 r10) |
| **B** Level ambiguity | Sub certain, leaf under-determined | Channel never named — 48 of 106 gold labels |
| **C** Label / parent collision | Same numeric label at two levels, or one sub under two groups | `0050` sub vs leaf; `0070` under CIP *and* NC |
| **D** Source-of-truth conflict | Customer assertion contradicts system status | 0010 vs 0110; 0049 vs 0101 |
| **E** Unranked co-occurrence | Two signals, no precedence rule covers the pair | Callback request + product complaint |
| **F** Evidence insufficiency | Corrupted diarisation, ASR loss, single turn | 21-07 r30 (greeting + `"hello"`) |
| **G** Cross-call gating | Undecidable from a single transcript by design | 0019, 002A, 0064 |
| **H** Annotation conflict | Human gold vs written rules | The 5 rows in §1.3d |
| **I** Degenerate leaf | Catch-all or singleton with no discriminating evidence | 0017, NEEDS_HUMAN_REVIEW |

**Each register entry carries:**

```
ambiguity_id · class (A–I) · the case (transcript + pre-call params)
competing_labels[]  — each with its verbatim clause citation
why_unresolved      — which precedence rule is missing, or which two collide
tribunal_split      — the actual votes
production_frequency— how often this shape appears in the 241 real interactions
proposed_amendment  — the specific edit to the definitions file that would resolve it
blast_radius        — which other leaves the amendment touches
```

**This is why the register is the most valuable output, not the residue.** It is the feedback loop into the disposition definitions themselves — the artifact that raises classifier accuracy at the source rather than measuring it downstream. And because entries are clause-level and amendment-shaped, it is directly actionable by whoever owns the taxonomy.

---

## 8. Honest statement on "zero false positives"

I will not claim the architecture proves zero. It cannot, and a design that claims it would be lying to you. What it does:

**Bounded by construction.** A case enters the graded suite only if *all* of these hold — (i) its cited clause verbatim exists in the taxonomy, (ii) its decisive span verbatim exists in the transcript, (iii) no rival trigger fires unrebutted, (iv) three independent model families agree unanimously at the declared grade, (v) an adversarial advocate fails to produce an un-rebutted counter-citation. Any single failure routes to the Register instead.

**The residual risk, named.** Cases where the taxonomy itself is wrong in a way that (a) all three model families share, *and* (b) the deterministic clause checks cannot see. Checks (i)–(iii) are the specific defence against shared model blind spots, because they are string operations over the source text rather than judgements. The Register plus the Taxonomy Defect Report are how that residual surfaces over time.

**What I would report at delivery** — the honest scoreboard, replacing v1's A1 *"520 cases, 5 FN + 5 FP each"*:

```
Attempted                  520
Certified @ EXPANDED       N₁     ← full-strength cases
Certified @ SUB            N₂     ← valid, assert less, test the #1 error class
Certified @ GROUP          N₃
Ambiguous Register         N₄     ← Sheet 2, classified A–I
Coverage shortfall         N₅     ← leaves that could not fill 10, with reasons
```

Anyone who tells you all 520 will certify at EXPANDED has not read the taxonomy. Expect meaningful volume at SUB — that is the design working, not failing.

---

## 9. Revised build sequence

Same principle as v1 §15.1 (prove case quality before scaling orchestration), one insertion.

| M | Deliverable | Exit criterion |
|---|---|---|
| **M0 ★NEW** | Ambiguity pre-scan + precedence ladder + rival-supply report | Static scan reproduces all 5 contested-gold conflicts in §1.3d without being told about them. **This is the cheapest possible validation of the whole thesis — run it first.** |
| M1 | Repo, CLAUDE.md, preflight P1–P17 | Passes on real files; fails loudly on a removed file or renamed column |
| M2 | Context compiler, 52 packs | All packs under budget; zero dangling rivals; 6-tier allocator produces a satisfiable quota for all 52 including NHR |
| M3 | Vertical slice on **0025** — generator + V1–V14 + rule-trace | 10 cases; every rule-trace passes deterministic checks; a human agrees the FP traps are genuinely deceptive |
| **M4 ★CHANGED** | Tribunal — 3 blind labellers, demotion, advocate, Register | On 0025: unanimity rate reported; ≥1 case demotes to SUB and is still gradeable; ≥1 exile lands in the Register correctly classified |
| M5 | Orchestration at scale — state machine, waves, resume, backfill | Full 52-leaf run; kill mid-wave, resume with zero duplicated or lost work |
| M6 | Workbook + Register + coverage + defect report | Opens cleanly; Sheet 1 matches the 11-column contract; Sheet 2 populated and classified |
| M7 | Hardening — CI smoke, cost ceiling, replay harness | Suite executed against live classifier; pass/fail attributed per disposition and probe type |

M0 is new and it is the highest-leverage two days in the plan: it is pure Python over files we already have, it needs no model, and if it fails to reproduce the known conflicts the ambiguity machinery needs rethinking before anything expensive is built.

---

## 10. What I need from you at review

Five decisions. Everything else I can carry with a stated assumption.

1. **Zero-FP interpretation.** I have read it as *zero mislabelled cases in the graded suite* — anything uncertain is routed to Sheet 2 rather than guessed. The alternative reading (*the suite is tuned to hunt classifier over-firing*) is already covered by the FP-probe design, so I believe this is the binding one. **Confirm.**
2. **The contested gold.** §5.3 demotes the 17-row corpus from ground truth to evidence, and routes the 5 conflicting rows to the Register. This contradicts v1's *"real beats synthetic every time."* It is the single most consequential change in v2. **Confirm, or tell me the human annotation wins and I will pin them with a recorded caveat.**
3. **Certification quorum.** 3 families unanimous + advocate. Cost is ~4× the v1 critic. Options: 2 families unanimous (cheaper, weaker), or 3 + advocate (proposed), or 3 + advocate + human sign-off on every SUB demotion (strongest, needs an owner).
4. **Sixth input scope.** Promote the Configuration Design Document to a first-class input (UAT 78 + objections 18 + FAQ 30 + pre-call params 37)? It materially improves transcript realism and gives a second gold corpus. Cost: ~1 day of compiler work.
5. **Chat scope** — v1 §16.1 open question, still open. Every matrix row is `Type = Calling`. Confirm calling-only for v1; it changes the normaliser and the perturbation axes, though not the architecture.

Still open from v1 §16.1 and unchanged: replay-harness ownership (M7 here or the platform test harness), and the human-queue SLA — which under v2 becomes the **Register triage SLA**, and needs a named owner or the register accumulates silently.
