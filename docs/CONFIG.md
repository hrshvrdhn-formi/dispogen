# Config reference

You write **one file** to onboard an agent: `config/clients/<name>.yaml`. It is
deep-merged over `config/default.yaml`, so you only declare what differs.

If you find yourself editing Python to onboard a client, that is a bug — open an
issue. The two exceptions, both designed as extension points, are
[adding a provider](CONTRIBUTING.md#adding-a-provider) and
[adding a transcript decoder](CONTRIBUTING.md#adding-a-transcript-decoder).

Read `config/clients/gcli.yaml` alongside this page. It is a real, working
binding and every block below appears in it.

---

## How the merge works

Dicts merge key by key; **lists replace wholesale**. That is deliberate — if
lists appended, you could never shorten an inherited list, e.g. to drop an FP
slot your taxonomy cannot supply.

```yaml
# default.yaml            client.yaml              result
quota:                    quota:                   quota:
  fn_probes: 5              fp_probes: 8             fn_probes: 5
  fp_probes: 5                                       fp_probes: 8
```

Missing keys raise at load, not three phases later. `Config.REQUIRED` lists the
minimum surface; a half-written config fails immediately and names every key it
still needs.

---

## `client` — identity

```yaml
client:
  name: gcli-persistency          # used in output filenames
  display_name: "GCLI Persistency — Anika"
  language: hinglish              # documentation only; nothing structural
  anchor: "Tue 07 Jul 2026, 14:32"
```

**`anchor`** is the reference timestamp every callback is scheduled relative to.
V7 requires each `redial.schedule` to be strictly after it. Match it to whatever
your re-dial matrix assumes, or every case fails the same check.

---

## `inputs` — where your documents are

### `inputs.taxonomy` (required)

```yaml
inputs:
  taxonomy:
    path: context/disposition_definitions.xlsx
    sheet: "Disposition Master"
    columns:
      group:            "Group Disposition"
      group_desc:       "Group Disposition Description"
      sub:              "Sub Disposition"
      sub_desc:         "Sub Disposition Description"
      expanded:         "Expanded Disposition"
      expanded_desc:    "Expanded Disposition Description"
      decision_rules:   "Decision Rules - Triggers / Exclusions / Tie-breakers"
      engine_code:      "Engine Code (rules_json key)"
      engineering_note: "Engineering Note / Risk"
    forward_fill: [group, group_desc, sub, sub_desc]
```

`columns` maps a **role** to your sheet's **exact row-1 header**. Rename here,
never in code. A header that does not match raises at load and prints every
header the sheet actually has — so the fix is usually visible in the error.

`forward_fill` handles the near-universal convention that group and sub cells are
blank on continuation rows. Remove entries only if your sheet repeats them.

> **`engine_code` is the key for everything.** Numeric labels like `0011` are
> display strings and are **not unique across levels** in a real taxonomy — a sub
> and a leaf can share a number. Every internal structure keys on `engine_code`.

### `inputs.output_format` (required)

```yaml
  output_format:
    path: context/disposition_definitions.xlsx
    sheet: "Output Format"
    probe_type_column: "Type"
    probe_type_values:
      FP: "Regression Test case for False Positives"
      FN: "Regression Test case for False Negatives"
    probe_order: [FP, FN]
```

The **column contract is read from row 1 of this sheet**, not from config. Your
client renames a column, the workbook follows, and nothing in the repo changes.

**`probe_order`** sets which probe type occupies the low SNs. V2 enforces it.

### `inputs.redial_matrix` (optional)

```yaml
  redial_matrix:
    path: context/redial_test_matrix.xlsx
    sheet: "Re-Dial Test Matrix"
    logic_sheet: "Scheduling Logic"
    code_column: "Expanded Disposition"
    calling_window: {start: "09:00", end: "21:00"}
```

Supplies callback seeds per disposition. `calling_window` is enforced by V7.
Omit the whole block and callbacks become `derived` rather than `seeded`.

### `inputs.interaction_report` (optional, high value)

```yaml
  interaction_report:
    path: context/interaction_report.xlsx
    annotated_sheets: ["21-07-26", "22-07-2026"]
    transcript_column: transcript
    label_columns:      [after_extended_disposition, after_sub_disposition]
    confidence_columns: [after_extended_disposition_confidence]
    annotation_column_prefixes: [discrepancy, actual, Actual_]
    leakage_blocklist: [lead_stage_computed]
```

This is where **empirical** rivals come from — confusions the engine has actually
demonstrated, which outrank rivals merely named in a rule. Worth chasing down.

- `annotation_column_prefixes` — any column whose name starts with one of these
  marks a human correction. Add a prefix, get those columns mined; no code change.
- `leakage_blocklist` — fields excluded from the mined set because they *are* the
  field under test. Leaving the label in the mined context leaks the answer.

> Human annotations are recorded as `human_claim`, **never as ground truth.** In
> the reference corpus ~29% of "gold" conflicts with or is under-determined by the
> written rules. Treating it as truth is the largest false-positive vector there
> is.

### `inputs.extras` (optional)

Any additional workbook, mined for seeds:

```yaml
  extras:
    - name: config_design
      path: context/config_design.xlsx
      sheets:
        uat:     {sheet: "UAT", id_column: "Test Case ID", expected_column: "Expected Outcome"}
        params:  {sheet: "Pre-Call Parameters", name_column: "Variable Name"}
```

---

## `taxonomy` — how codes and classes are read

```yaml
taxonomy:
  code_regex: '\b(0[0-9][0-9A-F]{2}|09[12])\b'
  abstention_code: NEEDS_HUMAN_REVIEW
  source_of_truth_rules:
    - {match: "cross-call code", class: cross-call}
    - {match: "telephony",       class: telephony}
  source_of_truth_default: transcript
  source_of_truth_overrides:
    NO_RESPONSE: hybrid
  speaker_identity_rivals: ["0072", "0071", "0074"]
  exclude_from_generation: [NEEDS_HUMAN_REVIEW]
```

**`code_regex`** is the highest-leverage line in the file. It is applied to your
**decision-rule prose**, not just the code column — that is how the confusion
graph is built. Test it against the codes cited *inside* rule text, including
outliers (the reference taxonomy has 3-digit `091`/`092` among 4-digit codes). If
preflight reports "rival supply degraded" on most leaves, this regex is usually
why.

**`source_of_truth_rules`** decide *what a case for a leaf is even made of*. Each
`match` is a case-insensitive substring searched in the leaf's decision rules and
engineering note; **first match wins**, so order matters.

| Class | A case is made of | Validators |
|---|---|---|
| `transcript` | ≥1 substantive customer turn | V6 requires it |
| `telephony` | call metadata only, **no transcript** | V6 forbids a transcript |
| `system` | pre-call system state, **no transcript** | V6 forbids a transcript |
| `cross-call` | prior-call state in `pre_call_parameters` | current call must not suffice |
| `hybrid` | either | both permitted |
| `abstention` | the leaf is a refusal target | usually excluded from generation |

For non-transcript classes, V9/V11 check `trap_phrase` and `decisive_evidence`
against `pre_call_parameters` instead of the transcript. Getting the class wrong
is the single most common cause of a wall of V11 failures.

**`exclude_from_generation`** — leaves that are not real dispositions (an
abstention target has no positive instances to write).

---

## `transcripts` — decoding the corpus

```yaml
transcripts:
  decoders: [pyrepr, json, flat_assistant_user, flat_agent_customer]
  speaker_labels:
    flat_assistant_user: {agent: "ASSISTANT:", customer: "USER:"}
  null_markers: ["n/a", "null", "none", "-", ""]
```

Tried in order, first match wins. `pyrepr` is single-quoted Python `repr` —
`json.loads` throws on it, and a corpus exported from pandas is full of it.

Preflight prints a per-decoder hit count. A decoder with **0 hits** that you
expected to fire means either the format is absent or the column name differs —
header matching is case-insensitive precisely because real workbooks capitalise
inconsistently across sheets.

---

## `tokens` — production markers

```yaml
tokens:
  candidates: ["</interrupted>", "<silence-detected/>"]
  documented_but_not_produced: ["[/interrupted]"]
```

Extracted from the **corpus**, not from the system prompt. In the reference
client the prompt documents `[/interrupted]` while production emits
`</interrupted>` — a degraded-input probe using the documented form tests
nothing, so V12 rejects it.

Get this list by grepping your real transcripts, not by reading the prompt.

---

## `precedence` — tie-breakers the taxonomy already states

```yaml
precedence:
  - id: P1
    rule: "Any payment intent outranks any callback request"
    anchor: 'a call-back request that also contains "pay kar dunga" is CTP, not CIP'
```

**`anchor` must appear verbatim in the taxonomy** or preflight P16 fails. That is
the point: it is how you find out the source document changed under you. Copy
anchors out of the document — do not retype them, and do not tidy the
punctuation.

These are enforced deterministically so no model ever re-litigates a decision the
document already made.

---

## `compliance_checks` — rails the synthetic agent must not break

```yaml
compliance_checks:
  - id: C9
    pattern: 'आपका mobile number बता|अपना email बता'
    why: "agent must not collect mobile/email for the payment link"
```

Regexes matched against **agent turns only** (V10). The agent in a generated
transcript is the production agent and is bound by production rules — otherwise
the suite teaches the wrong behaviour if it is ever reused to evaluate the agent.

---

## `deidentify` — the release gate

```yaml
deidentify:
  enabled: true
  salt_env: DISPOGEN_DEID_SALT
  harvest:
    person_names:   {columns: [lead_name, customer_name], min_length: 3}
    policy_numbers: {columns: [policy_no], numeric: true, min_length: 6}
  pools:
    surnames_deva: [चौहान, राठौड़, ...]
    policy_prefix: "09"
    phone_prefix:  "70000"
```

`harvest` names the columns holding real identifiers, across **every** input
workbook. Anything found is blocked from appearing in generated output (V16).

**Pool entries must not occur in the client corpus.** Any that do are dropped at
load with a collision note; a fully-overlapping pool raises `PoolExhausted`.
Otherwise scrubbing swaps one real name for another and reports success.

`policy_prefix` should sit outside the real range so a synthetic number is never
mistaken for a live policy.

Set `DISPOGEN_DEID_SALT` in the environment and **keep it out of git**. Same salt
→ same synthetic identities across regenerations; rotate it and the mapping
changes.

---

## `models` — routing

```yaml
models:
  generator:
    provider: anthropic
    model: claude-opus-5
    effort: max
    max_tokens: 128000
    thinking: adaptive
    base_url: https://<resource>.services.ai.azure.com/anthropic   # optional
  critic_panel:
    - {provider: anthropic, model: claude-opus-5, effort: high, max_tokens: 16000}
  advocate:
    {provider: anthropic, model: claude-opus-5, effort: xhigh, max_tokens: 16000}
```

**No sampling parameters.** `temperature`, `top_p` and `top_k` return a 400 on
Opus 5 and Sonnet 5. Steer with `effort` and with prompting.

**`max_tokens` caps thinking *plus* text.** Ten cases with full transcripts run
25–35k of text alone; at 32000 the reasoning consumed the whole budget and the
response truncated inside case 1. Head-room is the fix, not less thinking.

**`base_url`** points at a gateway speaking the Anthropic wire format (Microsoft
Foundry, an internal proxy). `ANTHROPIC_BASE_URL` also works; config wins.

---

## `render.contract_map` — binding your columns

```yaml
render:
  contract_map:
    "SN": sn
    "Scenario": scenario
    "Transcript": transcript_flat
    "Expected Disposition": expected_graded
```

Maps each column of **your** output-format sheet to a named resolver. Unmapped
columns render blank rather than failing — a new column in the client's sheet
degrades to an empty column, not a crash.

`render.appended_columns` adds the rule-trace columns after the contract. They
are what make a reviewer able to check a case without re-reading the taxonomy.

---

## `domain_terms` — keeping learnings portable

```yaml
domain_terms: [persistency, renewal, policyholder]
```

Terms that must not appear in `learnings/`. The lint keeps accumulated learnings
transferable to the next onboarding instead of silently becoming client-specific.

---

## Minimum viable config

Everything else has a working default:

```yaml
client:
  name: acme
  anchor: "Tue 07 Jul 2026, 14:32"
inputs:
  taxonomy:
    path: context/taxonomy.xlsx
    sheet: "Dispositions"
    columns:
      group: "Group"
      sub: "Sub"
      expanded: "Expanded"
      decision_rules: "Rules"
      engine_code: "Code"
  output_format:
    path: context/taxonomy.xlsx
    sheet: "Output Format"
taxonomy:
  code_regex: '\b\d{4}\b'
precedence: []
```

Start here, run `preflight`, and add blocks as it tells you what is missing.
