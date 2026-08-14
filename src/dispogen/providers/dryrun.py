"""Dry-run provider: writes the exact assembled prompt to disk and returns nothing.

This is the default so `dispogen generate` works on a fresh clone with no
credentials. It is also the most valuable debugging surface in the system — when
a disposition produces garbage, the answer is almost always in the prompt that
was actually sent rather than the one you think was sent.

Use the emitted prompt files to drive generation by hand (or paste into Claude
Code) when you would rather not wire up an API key at all.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .base import Completion, Provider, register


@register("dryrun")
class DryRunProvider(Provider):
    def __init__(self, spec: dict):
        super().__init__(spec)
        self.out = Path(spec.get("prompt_dir", "logs/attempts"))
        self.out.mkdir(parents=True, exist_ok=True)
        self.model = spec.get("model", "dryrun")

    def complete(self, system: str, user: str, *, schema=None,
                 max_tokens=None, effort=None, cache_prefix=None) -> Completion:
        label = (self.spec.get("label") or
                 hashlib.sha256(user.encode()).hexdigest()[:12])
        user = f"{cache_prefix}{user}" if cache_prefix else user
        blob = (f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n\n"
                f"=== SCHEMA ===\n{json.dumps(schema, indent=2, ensure_ascii=False) if schema else '(none)'}\n")
        p = self.out / f"{label}.prompt.txt"
        p.write_text(blob, encoding="utf-8")
        return Completion(text="", parsed=None, model="dryrun", provider=self.name,
                          stop_reason="dryrun", usage={"prompt_written_to": str(p)})
