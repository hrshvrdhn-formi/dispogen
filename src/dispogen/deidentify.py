"""De-identification.

Synthetic test cases must not carry real identifiers out of the client corpus.
This is a release gate, not a nicety: generated cases get committed, shared, and
pasted into tickets, and a policy number lifted from a production export is a
data-protection incident regardless of how synthetic the surrounding text is.

Replacement is deterministic given a salt, so a case keeps a stable synthetic
identity across regenerations without ever touching a real record. The salt is
never written to disk.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .config import Config


class PoolExhausted(Exception):
    """Every candidate in a synthetic pool also occurs in the real corpus."""


class Deidentifier:
    def __init__(self, cfg: Config, real: dict[str, set[str]]):
        self.cfg = cfg
        self.real = real
        self.salt = cfg.salt
        self._map: dict[str, str] = {}

        # A synthetic pool that overlaps the real corpus swaps one real
        # identifier for another and reports success. Filter first, fail loudly
        # if nothing survives — a silent pass here is worse than a crash.
        raw = cfg.get("deidentify.pools", {}) or {}
        real_names = real.get("person_names", set())
        self.pools = {}
        for k, v in raw.items():
            if isinstance(v, list):
                keep = [x for x in v if x not in real_names]
                if not keep:
                    raise PoolExhausted(
                        f"every entry in deidentify.pools.{k} also appears in the client "
                        f"corpus. Add distinct values to config/clients/*.yaml.")
                if len(keep) < len(v):
                    self.collisions = getattr(self, "collisions", [])
                    self.collisions.append(
                        {"pool": k, "dropped": sorted(set(v) - set(keep))})
                self.pools[k] = keep
            else:
                self.pools[k] = v

    def _h(self, value: str, n: int) -> int:
        d = hashlib.sha256(f"{self.salt}|{value}".encode("utf-8")).hexdigest()
        return int(d[:12], 16) % max(1, n)

    # ---- per-kind synthesis ----------------------------------------------
    def _person(self, real: str) -> str:
        givens = self.pools.get("givens_deva", ["A"])
        surnames = self.pools.get("surnames_deva", ["B"])
        # A harvested value may be a given name, a surname, or a full name.
        # Replacing token-wise keeps the shape without needing to know which.
        parts = real.split()
        if len(parts) >= 2:
            return (f"{givens[self._h(real + '|g', len(givens))]} "
                    f"{surnames[self._h(real + '|s', len(surnames))]}")
        pool = surnames if self._h(real + "|k", 2) else givens
        return pool[self._h(real, len(pool))]

    def _policy(self, real: str) -> str:
        prefix = str(self.pools.get("policy_prefix", "09"))
        width = max(len(real) - len(prefix), 4)
        return prefix + str(self._h(real, 10 ** width)).zfill(width)

    def _phone(self, real: str) -> str:
        prefix = str(self.pools.get("phone_prefix", "70000"))
        width = max(len(real) - len(prefix), 4)
        return prefix + str(self._h(real, 10 ** width)).zfill(width)

    def _email(self, real: str) -> str:
        return f"user{self._h(real, 999999):06d}@example.invalid"

    _SYNTH = {"person_names": "_person", "policy_numbers": "_policy",
              "phone_numbers": "_phone", "emails": "_email"}

    def synth(self, kind: str, real: str) -> str:
        key = f"{kind}:{real}"
        if key not in self._map:
            self._map[key] = getattr(self, self._SYNTH[kind])(real)
        return self._map[key]

    # ---- scanning ---------------------------------------------------------
    def scan(self, blob: str) -> list[tuple[str, str]]:
        """Real identifiers present in `blob`, as (kind, value)."""
        hits = []
        for kind, values in self.real.items():
            if kind not in self._SYNTH:
                continue
            for v in values:
                if not v:
                    continue
                if kind == "policy_numbers":
                    if _num_re(v) and _num_re(v).search(blob):
                        hits.append((kind, v))
                elif v in blob:
                    hits.append((kind, v))
        return hits

    def scrub(self, obj: Any) -> Any:
        """Recursively replace every real identifier with its synthetic twin."""
        if isinstance(obj, str):
            out = obj
            for kind, values in self.real.items():
                if kind not in self._SYNTH:
                    continue
                for v in sorted(values, key=len, reverse=True):
                    if not v:
                        continue
                    if kind == "policy_numbers":
                        rx = _num_re(v)
                        if rx is None:
                            continue
                        stripped = v.lstrip("0")
                        rep = self.synth(kind, v)
                        out = rx.sub(rep, out)
                        # digit-by-digit spoken form, e.g. "one seven six five"
                        spoken = " ".join(_DIGIT_WORDS[int(d)] for d in stripped)
                        if spoken in out:
                            out = out.replace(
                                spoken, " ".join(_DIGIT_WORDS[int(d)] for d in rep.lstrip("0")))
                    elif v in out:
                        out = out.replace(v, self.synth(kind, v))
            return out
        if isinstance(obj, list):
            return [self.scrub(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.scrub(v) for k, v in obj.items()}
        return obj

    def report(self, obj: Any) -> list[dict]:
        blob = json.dumps(obj, ensure_ascii=False)
        return [{"kind": k, "value": v} for k, v in self.scan(blob)]


_DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five",
                "six", "seven", "eight", "nine"]


def _num_re(value: str):
    r"""Match a numeric identifier with or without leading-zero padding.

    A naive `(?<!\d)4471902(?!\d)` never fires inside "04471902" — the padding
    zero is itself a digit, so the lookbehind blocks the match and the real
    number survives the scrub while the spoken form gets replaced.
    """
    stripped = value.lstrip("0")
    if not stripped:
        return None
    return re.compile(rf"(?<![0-9])0*{re.escape(stripped)}(?![0-9])")
