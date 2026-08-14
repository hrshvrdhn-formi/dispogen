"""Provider interface.

Generation, critique, and advocacy all go through this. Swapping vendors is a
config edit plus one module — nothing else in the pipeline knows which model ran.

A genuinely independent critic panel wants a SECOND VENDOR, not three models from
one lineage: shared training data means shared blind spots, which is exactly what
the panel exists to break. Register your own provider (see README > Adding a
provider) and list it in `models.critic_panel`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Completion:
    text: str
    parsed: Any = None
    model: str = ""
    provider: str = ""
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)
    refused: bool = False
    refusal_category: str | None = None


class Provider:
    name = "base"

    def __init__(self, spec: dict):
        self.spec = spec
        self.model = spec.get("model", "")

    def complete(self, system: str, user: str, *, schema: dict | None = None,
                 max_tokens: int | None = None, effort: str | None = None,
                 cache_prefix: str | None = None) -> Completion:
        """`cache_prefix` is prepended to `user` and marked cacheable.

        Certification sends the whole taxonomy to every critic for every case. On
        a full run that is the dominant cost by an order of magnitude, and all of
        it is the same bytes — so the split is worth carrying through the
        interface rather than leaving each provider to rediscover it.
        """
        raise NotImplementedError


_REGISTRY: dict[str, Callable[[dict], Provider]] = {}


def register(name: str):
    def wrap(cls):
        _REGISTRY[name] = cls
        cls.name = name
        return cls
    return wrap


def build(spec: dict) -> Provider:
    p = spec.get("provider", "dryrun")
    if p not in _REGISTRY:
        raise ValueError(f"unknown provider {p!r}. Registered: {sorted(_REGISTRY)}. "
                         f"See README > Adding a provider.")
    return _REGISTRY[p](spec)


def registered() -> list[str]:
    return sorted(_REGISTRY)
