"""Anthropic provider (official SDK).

Notes that bit us and are easy to get wrong:

* `temperature` / `top_p` / `top_k` are REMOVED on Claude Opus 5 and Sonnet 5 —
  sending any of them returns a 400. Steer with `effort` and prompting instead.
  (The v1 architecture doc's "temperature 0.2-0.4 for FP probes" is invalid.)
* Assistant-turn prefills return a 400 on these models. Structured output is
  `output_config.format`, not a prefill.
* Anything over ~16k `max_tokens` must stream or the request hits an HTTP timeout.
* Thinking is on by default on Opus 5, and `max_tokens` caps thinking PLUS text.
* Safety classifiers can decline with HTTP 200 and `stop_reason == "refusal"` —
  check that before reading `content`, or the first block access throws.
"""
from __future__ import annotations

import json

from .base import Completion, Provider, register

_STREAM_ABOVE = 16000


@register("anthropic")
class AnthropicProvider(Provider):
    def __init__(self, spec: dict):
        super().__init__(spec)
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "the anthropic SDK is not installed — `pip install -e '.[anthropic]'`, "
                "or run with `--provider dryrun` to emit prompts without calling a model"
            ) from e
        import anthropic as _a
        # Resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an `ant auth login`
        # profile, in that order. A bare constructor is correct.
        self._client = _a.Anthropic()
        self.model = spec.get("model", "claude-opus-5")

    def complete(self, system: str, user: str, *, schema: dict | None = None,
                 max_tokens: int | None = None, effort: str | None = None) -> Completion:
        mt = int(max_tokens or self.spec.get("max_tokens", 8000))
        oc: dict = {"effort": effort or self.spec.get("effort", "high")}
        if schema:
            oc["format"] = {"type": "json_schema", "schema": schema}

        kwargs = dict(
            model=self.model,
            max_tokens=mt,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=oc,
        )
        if self.spec.get("thinking", "adaptive") == "adaptive":
            kwargs["thinking"] = {"type": "adaptive"}

        if mt > _STREAM_ABOVE:
            with self._client.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
        else:
            msg = self._client.messages.create(**kwargs)

        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            return Completion(text="", model=msg.model, provider=self.name,
                              stop_reason="refusal", refused=True,
                              refusal_category=getattr(details, "category", None),
                              usage=_usage(msg))

        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        parsed = None
        if schema and text.strip():
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        return Completion(text=text, parsed=parsed, model=msg.model, provider=self.name,
                          stop_reason=msg.stop_reason, usage=_usage(msg))


def _usage(msg) -> dict:
    u = getattr(msg, "usage", None)
    if not u:
        return {}
    return {k: getattr(u, k, None) for k in
            ("input_tokens", "output_tokens",
             "cache_read_input_tokens", "cache_creation_input_tokens")}
