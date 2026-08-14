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
        import os

        import anthropic as _a
        # Resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an `ant auth login`
        # profile, in that order. A bare constructor is correct.
        #
        # `base_url` points at a gateway (Microsoft Foundry, an internal proxy)
        # that speaks the Anthropic wire format. Config beats the environment so a
        # client binding can pin its own endpoint; both are optional.
        kw = {}
        url = spec.get("base_url") or os.environ.get("ANTHROPIC_BASE_URL")
        if url:
            kw["base_url"] = url
        self._client = _a.Anthropic(**kw)
        self.model = spec.get("model", "claude-opus-5")

    def _call_with_retry(self, kwargs: dict, mt: int):
        """Retry on 429 and transient 5xx with exponential backoff.

        The rate gate is an estimate, so some requests will still be refused —
        and a disposition lost to a 429 costs a full regeneration of work the
        server already accepted payment for on its siblings.
        """
        import random
        import time

        import anthropic as _a
        import httpx

        # A long stream is a long-lived socket. Gateways reset them, and the raw
        # httpx error is NOT always wrapped as APIConnectionError — a bare
        # ReadError escaping here loses a disposition that was minutes from done.
        retry_on = (_a.RateLimitError, _a.InternalServerError, _a.APITimeoutError,
                    _a.APIConnectionError, httpx.TransportError, httpx.RemoteProtocolError)

        attempts = int(self.spec.get("max_retries", 6))
        for i in range(attempts):
            try:
                if mt > _STREAM_ABOVE:
                    with self._client.messages.stream(**kwargs) as stream:
                        return stream.get_final_message()
                return self._client.messages.create(**kwargs)
            except retry_on as e:
                if i == attempts - 1:
                    raise
                # Jitter matters more than the base delay here: without it every
                # worker refused in the same second retries in the same second.
                delay = _retry_after(e) or min(60.0, 4.0 * (2 ** i))
                time.sleep(delay * (0.5 + random.random()))
        raise RuntimeError("unreachable")

    def complete(self, system: str, user: str, *, schema: dict | None = None,
                 max_tokens: int | None = None, effort: str | None = None,
                 cache_prefix: str | None = None) -> Completion:
        mt = int(max_tokens or self.spec.get("max_tokens", 8000))
        oc: dict = {"effort": effort or self.spec.get("effort", "high")}
        if schema:
            oc["format"] = {"type": "json_schema", "schema": schema}

        if cache_prefix:
            content = [{"type": "text", "text": cache_prefix,
                        "cache_control": {"type": "ephemeral"}},
                       {"type": "text", "text": user}]
        else:
            content = user

        kwargs = dict(
            model=self.model,
            max_tokens=mt,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config=oc,
        )
        if self.spec.get("thinking", "adaptive") == "adaptive":
            kwargs["thinking"] = {"type": "adaptive"}

        msg = self._call_with_retry(kwargs, mt)

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


def _retry_after(err) -> float | None:
    """Honour the server's own retry-after when it gives one."""
    h = getattr(getattr(err, "response", None), "headers", None)
    for k in ("retry-after", "anthropic-ratelimit-tokens-reset"):
        v = (h or {}).get(k) if h else None
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _usage(msg) -> dict:
    u = getattr(msg, "usage", None)
    if not u:
        return {}
    return {k: getattr(u, k, None) for k in
            ("input_tokens", "output_tokens",
             "cache_read_input_tokens", "cache_creation_input_tokens")}
