# Contributing

The design goal is that onboarding a client is **config only**. Before adding
code, check whether the thing you need is already a config key — see
[docs/CONFIG.md](docs/CONFIG.md). If onboarding forced you to edit Python, that
is a bug worth reporting even if you have a working local patch.

There are three intentional extension points, below.

```bash
python -m pip install -e ".[anthropic,dev]"
python -m pytest -q
```

The suite builds its own toy taxonomy and never reads `context/`, so it passes on
a fresh clone with no credentials.

---

## Adding a provider

The single highest-value contribution. Gate D's premise is that critics fail
**independently**, and same-vendor models share training lineage and therefore
blind spots. A second vendor is the real strengthening; lenses are a substitute.

```python
# src/dispogen/providers/mine.py
from .base import Completion, Provider, register


@register("mine")
class MineProvider(Provider):
    def __init__(self, spec: dict):
        super().__init__(spec)
        self.model = spec.get("model", "default-model")
        # spec carries base_url, max_retries, effort, max_tokens

    def complete(self, system: str, user: str, *, schema=None,
                 max_tokens=None, effort=None, cache_prefix=None) -> Completion:
        ...
        return Completion(text=..., model=self.model, provider=self.name,
                          stop_reason=..., usage={...})
```

Import it in `providers/__init__.py`, then reference it in config:

```yaml
models:
  critic_panel:
    - {provider: anthropic, model: claude-opus-5, effort: high}
    - {provider: mine,      model: your-model,    effort: high}
```

Nothing else in the pipeline learns which vendor ran.

**Contract to honour:**

| Requirement | Why |
|---|---|
| `cache_prefix` is prepended to `user` and cached if you can | Certification re-sends the whole taxonomy per case per critic; uncached it dominates the cost of a run |
| Set `refused=True` rather than raising, when a safety classifier declines | The pipeline reports refusals per disposition and continues |
| Retry 429/5xx with **jittered** backoff | Without jitter every worker refused in the same second retries in the same second |
| Never send sampling parameters to models that reject them | `temperature`/`top_p`/`top_k` are a 400 on Opus 5 and Sonnet 5 |
| Report real token counts in `usage` | The rate gate and the run report both read them |

---

## Adding a transcript decoder

Corpora arrive in whatever the client's export produced.

```python
# src/dispogen/corpus.py

@decoder("my_format")
def _my_format(raw: str, cfg) -> list[dict] | None:
    """Return [{"speaker": "agent"|"customer", "text": ...}] or None if it is
    not this format. Returning None must be cheap — every decoder is tried in
    order until one matches."""
```

Then list it in the client config:

```yaml
transcripts:
  decoders: [pyrepr, json, my_format]
```

Normalise onto the internal roles `agent` and `customer`. Client-specific labels
belong in `transcripts.speaker_labels`, not in the decoder.

Preflight prints per-decoder hit counts — a new decoder with 0 hits is telling
you something.

---

## Adding a validator

Validators are **deterministic string and structure operations**. No model runs
in `validators.py`, and that is load-bearing rather than incidental: V11 catches
plausible-but-wrong labels precisely because it does not share a model's
judgement about what "plausible" means.

```python
# in validate(), inside the per-case loop
if some_condition:
    E("V17", cid, "what is wrong, stated as the defect not the rule")
```

- Assert on the **check ID** in tests, not on message text, so rewording an error
  does not fail the suite but weakening a check does.
- Anything client-specific goes through `cfg`, never a literal.
- Respect `source_of_truth_class` — a check that assumes a transcript will fire
  on every telephony case and bury the real failures.

---

## Style

Match the surrounding code. A few conventions that are deliberate:

**Comments explain the non-obvious decision, not the mechanism.** Most of the
comments in this repo exist because a plausible alternative is wrong in a way
that fails silently:

```python
def allocate(cfg, tax, leaf, graph, empirical) -> dict:
    """Fill FP slots by semantic role, per config.quota.fp_slots.

    Rank-ordering the candidate pool and zipping it onto the archetypes drops the
    highest-information roles on any leaf with a crowded sibling set, while still
    reporting the quota as filled. Slots therefore reserve their own pool.
    """
```

If you fix a bug that was silent, leave the note. The next person will otherwise
reintroduce it, because the wrong version looks equivalent.

**Fail loudly over passing quietly.** `PoolExhausted` raises rather than letting a
scrub swap one real name for another and report success. Preflight fails on an
unresolvable anchor rather than warning. A dry run reports `NOT_RUN`, never
`CERTIFIED`.

**Do not weaken a check to make a run green.** V11 and V16 gate release. If a
case cannot cite a clause that licenses its answer, the case is the problem.

---

## Tests

Every regression in this repo has a test named after the failure, not the
function:

```python
def test_zero_padded_identifier_does_not_survive(cfg):
    """`(?<!\\d)4471902(?!\\d)` never fires inside "04471902".

    The padding zero is itself a digit, so the lookbehind blocks the match: the
    number survived the scrub while its spoken form was replaced, which read as a
    partial success rather than a failure.
    """
```

Keep that shape. A test called `test_scrub_works` does not tell the next reader
what broke.

**Never read `context/` from a test.** It is real customer data and it is
git-ignored, so any test depending on it fails on every clone but yours. Build
what you need in `conftest.py`.

---

## Data protection

Non-negotiable, and worth re-reading before any PR:

- `context/` never gets committed. It holds real names, phone numbers, policy
  numbers and call transcripts.
- `DISPOGEN_DEID_SALT` never enters version control.
- **Never paste a real identifier into code, a docstring, a test fixture, or a
  commit message.** This has happened — a real policy number was once used as a
  docstring example. Use obviously synthetic values.
- Run `dispogen --client <name> scan-pii` before sharing any output.

If you are adding an example to the docs, invent the data.
