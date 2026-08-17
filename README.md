# dispogen

Generates disposition and re-dial regression test cases for conversational
agents, from the client's own taxonomy documents.

Given a disposition taxonomy, an output-format contract, a re-dial matrix and
(optionally) an annotated interaction report, `dispogen` produces for **every
leaf disposition**:

- 5 false-negative probes — the call *is* this disposition, in five different shapes;
- 5 false-positive probes — the call *looks like* it and is not, one per rival role;
- a machine-checkable **rule-trace** on every case, tying the expected answer to a
  verbatim clause of the taxonomy and a verbatim span of the transcript;
- an **Ambiguous Scenarios** register of everything the written rules do not decide.

Onboarding a new agent is one YAML file. If you find yourself editing Python to
onboard a client, that is a bug — please open an issue.

---

## Why the rule-trace, and what "zero false positives" actually means

The goal is a suite with no false positives in it. That phrase is worth being
precise about, because the obvious reading is not achievable and claiming it
would be dishonest.

A false positive in a *test suite* is a case whose expected answer is wrong — the
grader answers correctly and the suite marks it a failure. Those are worse than
useless: they train the next iteration of the agent toward the mislabelling.

Two things make them hard to eliminate. First, a plausible-sounding label is
indistinguishable from a correct one at review time; that is what "plausible"
means. Second, roughly a third of any real annotated corpus conflicts with, or is
under-determined by, the written rules — so a case that matches human gold is not
thereby correct.

So the design does not try to *judge* correctness. It makes the decision
procedure **mechanically checkable**:

| Field | Constraint |
|---|---|
| `cited_clause` | a verbatim substring of the taxonomy |
| `decisive_evidence` | a verbatim substring of this case's own transcript |
| `rebutted_rivals[].clause` | verbatim, one per rival a grader could plausibly reach |
| `declared_grade` | EXPANDED / SUB / GROUP, coherent with the expected fields |

These are string operations (validator **V11**). They do not depend on a model's
judgement, so they survive blind spots that every model in a panel might share. A
case that cannot cite a clause that licenses its answer does not ship.

What that buys: **no case ships whose expected answer is unsupported by the
written rules.** What it does not buy: immunity to a taxonomy that is itself
wrong or contradictory. That residue is not swept up — it is routed to the
Ambiguous Scenarios register, where a taxonomy owner has to decide.

**Ambiguity is not resolved. It is routed.**

---

## Install

```bash
git clone <your-fork-url> && cd disposition-testgen
python -m pip install -e ".[anthropic,dev]"
```

Python 3.10+. Without the `anthropic` extra everything still runs — generation
falls back to the `dryrun` provider, which writes the exact prompts to
`logs/attempts/` instead of calling a model.

---

## Onboarding an agent

### 1. Drop the documents in `context/`

| Document | Required | What it supplies |
|---|---|---|
| Disposition taxonomy (xlsx) | **yes** | groups, subs, leaves, decision rules, engine codes |
| Output-format sheet (xlsx) | **yes** | the exact column contract the workbook must match |
| Re-dial matrix (xlsx) | no | callback seeds and the calling window |
| Annotated interaction report (xlsx) | no | empirically observed confusions; human-vs-rules conflicts |
| System prompt (md) | no | the agent's own framing and token vocabulary |

`context/` is git-ignored. It holds real customer data — names, phone numbers,
policy numbers, call transcripts. **It must never be committed.** The repository
ships the pipeline, not the corpus.

### 2. Write one config

```bash
cp config/clients/gcli.yaml config/clients/<your-agent>.yaml
```

Edit the paths, sheet names, and column names to match your documents. Everything
client-specific lives here: taxonomy columns, code shapes, precedence rules with
their verbatim anchors, compliance rails, de-identification pools, the render
contract map. `config/default.yaml` holds the client-agnostic policy — probe
quotas, slot roles, tier weights, model routing — and you rarely need to touch it.

### 3. Preflight

```bash
dispogen --client <your-agent> preflight
```

Seventeen checks (P1–P17) run before anything is generated: the taxonomy parses,
engine codes are unique, every precedence anchor still resolves verbatim, the
transcript decoders cover the corpus, the rival supply is sufficient for the FP
slots. Preflight failing here is the cheapest possible failure — fix the config
or the document, not the output.

### 4. Run

```bash
dispogen --client <your-agent> run
```

`run` chains preflight → compile → prescan → packs → validate → render.
Generation is deliberately not in that chain: it costs money and it is the step
you want to scope with `--only` while iterating.

---

## Commands

| Command | Does |
|---|---|
| `preflight` | P1–P17. Nothing else runs if this fails. |
| `compile` | Normalise the taxonomy; emit the confusion graph and precedence ladder. |
| `prescan` | Static ambiguity pre-scan (M0) over the taxonomy and any annotations. |
| `packs` | Build one self-contained generation pack per leaf, with rivals pinned by role. |
| `generate` | Author cases. `--provider dryrun` emits prompts without calling a model. |
| `validate` | V1–V16, deterministic. No model runs. |
| `transliterate` | Rewrite romanised transcripts in the local script, in place. |
| `certify` | Gate D: blind critic panel, unanimity-or-demote, then adversarial advocate. |
| `scan-pii` | Harvest real identifiers from `context/`, report any that reached the output. |
| `scrub` | De-identify existing cases in place, deterministically. |
| `render` | Build the client-format workbook **and a flat CSV of every case**. |
| `run` | preflight → compile → prescan → packs → validate → render. |

Add `--only <ENGINE_CODE> ...` to scope `packs`, `generate`, `validate`,
`transliterate`, `certify` and `render` to specific dispositions.

`generate` and `transliterate` take `--workers`, plus `--tpm` / `--rpm` /
`--buffer` to stay inside a deployment's quota. A fan-out's binding constraint is
the burst when requests start, not the sustained draw — fifty packs firing at
once is ~1M input tokens in one instant. `--skip-existing` makes a partial run
resumable.

### Script normalisation

Models asked for Hinglish tend to write romanised Hindi, while production ASR
emits Devanagari. `transliterate` converts the script without touching wording.

It also rewrites `decisive_evidence` and `trap_phrase` in lockstep, because those
are verbatim substrings of the transcript and V9/V11 check them by exact
containment — converting the transcript alone silently invalidates every case it
touches. Each case is re-verified locally and **reverted** if its spans stop
resolving: a case that keeps its Latin script is a cosmetic defect, one whose
rule-trace no longer resolves is a broken test.

Re-run `scan-pii` afterwards. Converting a romanised name to Devanagari can make
it collide with a real name in the corpus that the Latin form never matched.

---

## How it decides what to test

### FP slots are filled by role, not by rank

Each leaf gets five FP probes, and each probe is pinned to a rival chosen for a
**semantic role**:

| Slot | Role | The grader failure it catches |
|---|---|---|
| FP-1 | `nearest_rival_decoy` | keying on a surface phrase shared with the closest rival |
| FP-2 | `structural_trap` | matching the host's shape while the content says otherwise |
| FP-3 | `stop_at_parent` | over-committing to a leaf when evidence stops at the sub |
| FP-4 | `out_of_class` | ignoring group boundaries — wrong modality, wrong speaker |
| FP-5 | `under_determined` | manufacturing specificity from group-level evidence |

Candidates are drawn from six tiers, empirical confusion first: rivals the engine
has *actually* been observed to confuse outrank rivals merely named in a rule.

Slots reserve their own candidate pools. Ranking one pool and zipping it onto the
five roles looks equivalent and is not — on any leaf with a crowded sibling set it
hands the top-weighted siblings to FP-1 and FP-2, leaves `stop_at_parent` and
`out_of_class` unfilled, and still reports the quota as 5/5. The two roles it
drops are the two that catch level errors, which are the most common failure in
production.

### Certification is unanimity, not majority

A majority vote produces a label for every case, including cases the written
rules do not decide — which is exactly the failure being hunted. So the panel
runs **blind** (it never sees the expected answer, the archetype, or even the
author's scenario summary), and a label is accepted only if every critic reaches
it independently. Dissent **demotes** the grade — EXPANDED → SUB → GROUP —
before it exiles the case, because the right answer to insufficient evidence is a
coarser grade, not a different guess.

An adversarial advocate then attacks the survivors with full sight of the answer.

> **On panel independence:** the default panel is three Anthropic models. Shared
> training lineage means shared blind spots, so this is genuinely weaker than a
> cross-vendor panel. `models.critic_panel` takes any registered provider — see
> *Adding a provider*. Treat same-vendor certification as a floor.

---

## Ambiguous scenarios

`prescan` classifies what the rules fail to decide, before any case is written;
generation adds to the register whenever authoring hits a gap. Both land in the
**Ambiguous Scenarios** sheet with the competing labels, the clauses that
conflict, and a proposed amendment.

| | Class |
|---|---|
| A | definitional gap — evidence clear, no leaf covers it |
| B | level ambiguity — sub certain, leaf under-determined |
| C | label or parent collision |
| D | source-of-truth conflict |
| E | unranked co-occurrence |
| F | evidence insufficiency |
| G | cross-call gating |
| H | annotation conflict — human gold vs written rules |
| I | degenerate leaf (e.g. a sub with one child) |

This sheet is the deliverable the taxonomy owner acts on. An empty register on a
thin taxonomy is not a clean bill of health — it means the ambiguity was absorbed
into an undeclared assumption.

---

## Data protection

- `context/` is git-ignored and must stay that way.
- `DISPOGEN_DEID_SALT` never enters version control. Same salt → same synthetic
  identities across regenerations; rotate it and the mapping changes.
- **V16** is a release gate, not a style check. It harvests every real identifier
  from `context/` and fails the build if one appears in a generated case.
- `scan-pii` before you share anything. `scrub` fixes existing files in place.

```bash
dispogen --client <your-agent> scan-pii
```

---

## Adding a provider

`models.*` entries name a provider by string. Register your own:

```python
# src/dispogen/providers/mine.py
from .base import Completion, Provider, register

@register("mine")
class MineProvider(Provider):
    def complete(self, system, user, *, schema=None, max_tokens=None, effort=None):
        ...
        return Completion(text=..., model=self.model, provider=self.name)
```

Import it in `providers/__init__.py` and set `provider: mine` in your config.
Nothing else in the pipeline knows which model ran — this is the extension point
for a genuinely independent critic panel.

> The Anthropic provider passes **no sampling parameters**. Opus 5 and Sonnet 5
> reject `temperature`, `top_p` and `top_k` with a 400. Steer with `effort` and
> with prompting.

---

## Layout

```
config/
  default.yaml            client-agnostic policy
  clients/<name>.yaml     the only file you write to onboard an agent
context/                  the client's documents — git-ignored, real data
prompts/
  generator.md            authors the ten cases for one disposition
  critic.md               blind grader; refusal is a first-class answer
  advocate.md             adversarial reviewer, full sight
src/dispogen/
  config.py taxonomy.py corpus.py packs.py
  prescan.py preflight.py validators.py deidentify.py certify.py render.py cli.py
  providers/              base registry + anthropic + dryrun
tests/                    builds its own toy taxonomy; never reads context/
docs/                     see below
```

## Documentation

Read in this order on your first onboarding:

| | |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | onboard an agent in about an hour, start to finish |
| [docs/FIELDS.md](docs/FIELDS.md) | every column of the output sheet, and which three to score against |
| [docs/CONFIG.md](docs/CONFIG.md) | every key in the one file you write, and why it matters |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | organised by what you actually see in the terminal |
| [docs/RUN_REPORT.md](docs/RUN_REPORT.md) | a real 51-disposition run — costs, timings, what went wrong |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | the design, and what it deliberately does not claim |
| [CONTRIBUTING.md](CONTRIBUTING.md) | the three extension points; the data-protection rules |

If you are debugging a failing run, go straight to
[TROUBLESHOOTING](docs/TROUBLESHOOTING.md) — it is indexed by validator ID.

## Tests

```bash
python -m pytest -q
```

71 tests. The suite builds its own two-group taxonomy workbook, so it needs no
credentials and never reads `context/` — it passes on a fresh clone.
