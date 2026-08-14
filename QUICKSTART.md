# Quickstart — onboarding an agent in about an hour

Assumes you have the client's taxonomy workbook and their output-format sheet.
Everything else is optional and can be added later.

---

## 0. Install

```bash
python -m pip install -e ".[anthropic,dev]"
```

```bash
python -m pytest -q
```

61 tests, no credentials needed. If these fail on a fresh clone, stop — the
problem is the environment, not your config.

## 1. Drop the documents in

```bash
cp /path/to/taxonomy.xlsx context/disposition_definitions.xlsx
```

`context/` is git-ignored. It holds real customer data. Do not commit it, do not
paste transcripts into tickets, do not copy identifiers into examples.

## 2. Copy the reference config

```bash
cp config/clients/gcli.yaml config/clients/acme.yaml
```

Now work through it top to bottom. The blocks that matter, in the order you will
hit trouble:

**`inputs.taxonomy.columns`** — map each role to the exact column header in row 1
of your sheet. Get this wrong and preflight tells you the header it wanted and
every header it actually found.

**`inputs.taxonomy.forward_fill`** — most taxonomy sheets leave the group and sub
cells blank on continuation rows. Keep the default unless yours repeats them.

**`taxonomy.code_regex`** — must match your disposition codes, including the
outliers. Check it against the codes cited inside your *decision-rule text*, not
just the code column: that text is where the confusion graph comes from.

**`precedence`** — each rule needs an `anchor` that is a **verbatim** substring of
the taxonomy. Copy it out of the document; do not retype it. Preflight P16 fails
if an anchor stops resolving, which is how you find out the document changed.

**`inputs.output_format`** — point at the sheet whose row 1 is the column contract
your client expects. The renderer reads the contract from that sheet rather than
from config, so a renamed column does not need a code change.

## 3. Preflight until it is green

```bash
dispogen --client acme preflight
```

```
PREFLIGHT: PASS   client=acme
  taxonomy: 52 leaves / 5 groups / 13 subs
  leaves with explicit rivals: 49/52
  rival supply degraded on 15 leaves
  config_hash: ea259047036d2589
```

Read the last two lines rather than skimming for PASS.

- *leaves with explicit rivals* — how many leaves name a rival in their own rules.
  A low number means the confusion graph is thin and FP probes will lean on
  siblings, which are weaker traps.
- *rival supply degraded* — leaves where a slot had to fall back. Expected on
  singleton subs; if it is most of the taxonomy, your `code_regex` is probably
  not matching the codes inside the rule text.

## 4. Look at the ambiguity pre-scan before generating anything

```bash
dispogen --client acme prescan
```

This runs on the documents alone — no model, no cases. It is the cheapest signal
you will get about the taxonomy's quality, and it is worth reading in full before
you spend anything on generation. A large class **H** count (human gold conflicts
with the written rules) means the annotated corpus cannot be used as ground truth
without a decision from the taxonomy owner.

## 5. Build packs and eyeball one

```bash
dispogen --client acme packs --only <ENGINE_CODE>
```

```
0011_PAID_BANK                 rivals=5 shortfall=0
    FP-1 nearest_rival_decoy        -> 0022   (expanded, explicit)
    FP-3 stop_at_parent             -> 0010   (sub, parent)
    FP-5 under_determined           -> CTP    (group, group)
```

Check that FP-3 got a **sub** and FP-5 got a **group**. If either got a sibling,
the leaf's pools were empty and the allocator fell back — the note says so. Those
two slots are the ones that catch level errors, so a fallback there is worth
understanding rather than accepting.

## 6. Generate

Dry run first. It costs nothing and shows you the exact prompt:

```bash
dispogen --client acme generate --only <ENGINE_CODE> --provider dryrun
```

Read `logs/attempts/<ENGINE_CODE>.prompt.txt`. If the pack looks thin there, it
will be thin for the model too.

Then, with `ANTHROPIC_API_KEY` set:

```bash
dispogen --client acme generate --only <ENGINE_CODE>
```

## 7. Validate, and expect failures on the first pass

```bash
dispogen --client acme validate --only <ENGINE_CODE>
```

The common ones:

- **V11 cited_clause NOT verbatim** — the model normalised whitespace, fixed a
  typo, or translated. The clause must be copied character for character,
  including the source document's own errors.
- **V11 decisive_evidence NOT verbatim** — quoted a paraphrase of its own
  transcript.
- **V5 slot pinned to X, case used Y** — the model picked a rival it found more
  interesting. Re-generate; do not hand-edit the pin.
- **V8 near-duplicate** — one scaffold reused across ten cases.

These are cheap to fix by regenerating and expensive to fix by hand. Regenerate.

## 8. Certify

```bash
dispogen --client acme certify --only <ENGINE_CODE>
```

`DEMOTED` is a normal outcome and usually a correct one: the panel could not
unanimously reach the leaf, so the case now expects the sub. `EXILED` means the
case does not survive review — read the `dissent` lines, because they are often
telling you something true about the taxonomy rather than about the case.

Until certify has run against real models, every case is `PROVISIONAL`. A dry run
does not certify anything, and the tool will not pretend otherwise.

## 9. Scan for PII, then render

```bash
dispogen --client acme scan-pii
```

Must print `CLEAN` before you share anything. If it does not:

```bash
dispogen --client acme scrub && dispogen --client acme scan-pii
```

```bash
dispogen --client acme render
```

The workbook lands in `output/<client>_TestCases.xlsx` with seven sheets: Test
Cases, Ambiguous Scenarios, Coverage Matrix, Re-Dial Expectations, Certification
Log, Taxonomy Defects, Run Metadata.

---

## Then hand back two things

The **Test Cases** sheet is the deliverable people expect. The **Ambiguous
Scenarios** sheet is the one that changes the product: every row is a question the
written rules cannot answer, and each will keep producing disagreement in
production until a taxonomy owner decides it.

Hand back both. A suite delivered without the register looks more complete than
it is.
