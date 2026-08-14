# Troubleshooting

Organised by what you will actually see in the terminal. Each entry says what the
check is protecting, why it fired, and whether to fix the config, the document,
or regenerate.

**The general rule:** validation failures are cheap to fix by regenerating and
expensive to fix by hand. Hand-editing a case to satisfy a validator usually
defeats the check — the case now passes and still tests nothing.

---

## Preflight

### `column 'X' not found. Sheet has: [...]`

Your `inputs.taxonomy.columns` mapping does not match row 1. The error prints
every header the sheet actually has; copy the right one across. Watch for
trailing spaces and non-breaking spaces in client workbooks.

### `rival supply degraded on 40+ leaves`

Almost always **`taxonomy.code_regex`**. It is applied to decision-rule *prose* to
build the confusion graph, so it has to match codes as they are cited inside
sentences, not just as they appear in the code column.

```bash
dispogen --client acme compile
```

Then read `compiled/confusion_graph.json` and look at `dangling` — codes the
regex matched that resolve to nothing. A large `dangling` list means the regex is
over-matching (catching years, amounts, phone fragments). An empty `rivals` list
across the board means it is under-matching.

Some degradation is legitimate: a sub with exactly one child has no meaningful
`stop_at_parent` rival, and the allocator says so in `allocation_notes`.

### `precedence anchors no longer resolving: ['P3']`

The source document changed. The anchor is a verbatim substring, so this is the
system telling you the taxonomy moved under you — which is the whole reason
anchors are verbatim. Re-copy the clause out of the current document.

### `decoders: {'EMPTY': 340, 'pyrepr': 0}`

A decoder you expected to fire got zero hits. Either that encoding is absent, or
the transcript column is named differently on that sheet. Header matching is
case-insensitive (real workbooks use both `transcript` and `Transcript`), but the
*name* still has to match — check `inputs.interaction_report.transcript_column`.

### `WARN P12 skipped: no live model ping`

Informational. Pass `--check-credentials` to actually ping the deployment.

---

## Generation

### `UNPARSEABLE (max_tokens, 2199 chars)`

The response hit the token ceiling before finishing the JSON. **`max_tokens` caps
thinking plus text.** Ten cases with full transcripts are 25–35k of text alone;
at `max_tokens: 32000` with high effort, reasoning consumed the entire budget and
the response truncated inside case 1.

Raise `models.generator.max_tokens`. Head-room is the fix, not less thinking. The
raw response is kept under `logs/raw/<CODE>.txt` so you can confirm the shape.

### `UNPARSEABLE (None, 0 chars)`

Empty body. Transient — a dropped connection or a gateway hiccup. Re-run with
`--skip-existing`; it only retries what has no case file. If it reproduces on the
same disposition every time, look at that pack for something pathological (a
5,000-word decision rule, an unbalanced quote).

### `REFUSED (...)`

A safety classifier declined. Check the pack for content that reads as a request
to produce something harmful out of context — abuse, self-harm and fraud
scenarios are legitimate dispositions in a real taxonomy and occasionally trip a
classifier when stripped of framing. Usually resolved by regenerating.

### It is taking hours

Use `--workers`. A 52-leaf taxonomy in series is most of a working day; at
`--workers 20` with a rate gate it is well under an hour.

```bash
dispogen --client acme generate --workers 20 --skip-existing \
  --tpm 500000 --rpm 500 --buffer 0.30
```

Set `--tpm`/`--rpm` from your deployment's actual quota. The binding constraint
is the burst when requests *start*, not the sustained draw — fifty packs firing
at once is roughly a million input tokens in one instant.

### `429` storms

The gate estimates; the provider retries with jittered backoff as the exact
backstop. If you are still seeing them, raise `--buffer` (0.30 → 0.50) rather
than dropping `--workers` — the gate paces admission, so more workers mostly
means more requests waiting politely.

---

## Validation

Run `dispogen --client acme validate` and read the tally before fixing anything.
Failures cluster, and the cluster usually has one cause.

### V2 — quota and ordering

```
[V2] ACME_CODE: expected 5FN/5FP, got 5FN/3FP
```

A leaf gets as many FP probes as its taxonomy supplies **distinct rivals**. If
`quota.fp_allocation` has 3 entries, 3 is correct and the generator was right to
stop. Check `allocation_notes` for which roles went unfilled and why.

```
[V2] ACME_CODE: output contract orders probes ['FP', 'FN']
```

`inputs.output_format.probe_order` disagrees with what was generated. Fix the
config to match the client's sheet, then regenerate.

### V3 — probe polarity

An FN probe that does not expect the host, or an FP probe that does. Regenerate;
this is a model error, not a config one.

### V5 — pinned allocation

```
[V5] ACME-FP-01: slot FP-1 pinned to 0022, case used 0016
```

The generator substituted a rival it found more interesting. Regenerate. **Do not
re-pin the config to match the case** — the allocation is chosen for semantic
role, and following the model's preference collapses the roles that catch level
errors.

### V6 — source of truth

```
[V6] ACME-FP-01: telephony-class case must carry no transcript
```

Either the class is wrong or the case is. Check `taxonomy.source_of_truth_rules`
first: if a telephony disposition is being classified `transcript`, every case
for it is malformed and the fix is one config line, not 10 regenerations.

```
[V6] ACME-FN-01: transcript-class case needs >=1 substantive customer turn
```

The customer only produced acknowledgement tokens. Regenerate.

### V7 — re-dial

Callback before the anchor, or outside `calling_window`. Confirm
`client.anchor` matches what your re-dial matrix assumes — a wrong anchor fails
every case identically, which is the tell.

### V8 — near-duplicates

```
[V8] ACME-FP-01 ~ ACME-FN-03: Jaccard trigram = 0.871
```

One scaffold reused across cases. Regenerate. If it recurs on the same
disposition, the leaf is genuinely narrow — worth an ambiguity-register entry
rather than ten near-identical probes.

### V9 / V11 — the rule-trace

The largest category, and the most informative.

```
[V11] ACME-FP-01: cited_clause NOT verbatim in taxonomy: '...'
```

The model normalised whitespace, fixed a typo, expanded an abbreviation, or
translated. The clause must be copied **character for character**, including the
source document's own errors. Regenerate.

This check is the one carrying the zero-false-positive claim. It is a string
operation precisely so it does not depend on a model's judgement — which also
means it cannot be satisfied by a clause that is merely *close*. Do not relax it.

```
[V11] ACME-FP-01: decisive_evidence NOT verbatim in transcript
```

For a **transcript-class** leaf, the span must appear in a `text` field.

For a **telephony/system/cross-call** leaf, it is checked against
`pre_call_parameters` instead. If you are seeing this on every case of a
telephony disposition, the source-of-truth class is misconfigured — fix that
before regenerating anything.

```
[V11] ACME-FP-01: no rebutted_rivals
```

The case does not establish its own answer. Regenerate.

### V10 — compliance

The synthetic agent said something the production agent must not. Regenerate. If
it recurs, your `compliance_checks` regex may be over-broad — test it against a
few real agent turns.

### V12 — token vocabulary

A degraded-input probe used a marker production never emits. Check
`tokens.documented_but_not_produced`; the system prompt is not a reliable source
for this, the corpus is.

### V13 — grade coherence

```
[V13] ACME-FP-03: SUB grade requires expected_sub and a null expected_expanded
```

The declared grade and the three expected fields disagree. Common on
`stop_at_parent` and `under_determined` probes, where the correct answer is
deliberately *less* specific than a leaf. Regenerate.

### V15 — paraphrase purity

A `paraphrased_trigger` probe used a phrase quoted in the decision rules. If the
leaf cannot be made decidable without one, the trigger list *is* the definition —
that belongs in the ambiguity register.

### V16 — PII containment

```
[V16] ACME-FP-01: real person_name from the source corpus present
```

**Release blocker.** Run `dispogen --client acme scrub`, then `scan-pii` until it
prints `CLEAN`. Never ship on a V16 failure and never suppress it.

### Domain leak in `learnings/`

The lint found a client term in a file meant to be portable. Rewrite the learning
so it describes the mechanism rather than the client — "truncation after a
perfective auxiliary removes nothing" travels; "0011 mis-scored on Anika retries"
does not.

---

## Output

### The workbook shows `PENDING` for most dispositions

Expected until those dispositions have case files. The Coverage Matrix lists
**every** leaf, not just the generated ones, so it reports what is outstanding
rather than reporting 100% coverage of itself.

### Every case says `PROVISIONAL`

Certification has not run. A dry run does not certify anything and the tool will
not pretend otherwise — `certify` exits non-zero on `NOT_RUN`.

### Devanagari shows as `à¤®à¥‡à¤°à¤¾` in Excel

Open the `.xlsx`, not the `.csv`, or re-export the CSV — it is written
`utf-8-sig` for exactly this reason. If your Excel still mangles it, import via
Data → From Text with UTF-8 selected.

### Transcripts came back in Latin script

Models asked for "Hinglish" tend to write romanised Hindi while production ASR
emits Devanagari.

```bash
dispogen --client acme transliterate --workers 10
```

This converts script without touching wording, and rewrites `decisive_evidence`
and `trap_phrase` in lockstep because V9/V11 check them by exact containment. A
case whose spans stop resolving is reverted rather than shipped broken. Re-run
`scan-pii` afterwards — a romanised name converted to Devanagari can collide with
a real corpus name the Latin form never matched.

---

## Getting a clean run from a messy one

```bash
dispogen --client acme validate 2>&1 | grep -oE "\[V[0-9]+\]" | sort | uniq -c | sort -rn
```

Fix in this order, because earlier categories cause later ones:

1. **V6** — source-of-truth class. One config line can clear a hundred failures.
2. **V2 / V5** — quota and pinning. Config, then regenerate.
3. **V11 / V9** — rule-traces. Regenerate the affected dispositions only.
4. **V16** — scrub last, once the case set is stable.

```bash
dispogen --client acme generate --only CODE_A CODE_B --workers 4
dispogen --client acme validate --only CODE_A CODE_B
```
