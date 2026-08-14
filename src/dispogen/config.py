"""Config loading. The only place client-specific values are allowed to live."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    pass


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Config:
    """A client binding merged over the shipped defaults.

    `cfg.get("inputs.taxonomy.sheet")` reads a dotted path; missing keys raise
    unless a default is supplied, so a half-written client config fails at load
    rather than three phases later.
    """

    def __init__(self, data: dict, root: Path, name: str):
        self.data, self.root, self.name = data, root, name

    @classmethod
    def load(cls, client: str, root: Path | None = None) -> "Config":
        root = Path(root or Path.cwd()).resolve()
        default = root / "config" / "default.yaml"
        if not default.exists():
            raise ConfigError(f"missing {default} — run from the repo root")
        base = yaml.safe_load(default.read_text(encoding="utf-8")) or {}

        p = Path(client)
        if not p.exists():
            p = root / "config" / "clients" / f"{client}.yaml"
        if not p.exists():
            avail = sorted(x.stem for x in (root / "config" / "clients").glob("*.yaml"))
            raise ConfigError(f"no client config '{client}'. Available: {avail or '(none)'}")
        over = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

        cfg = cls(_deep_merge(base, over), root, over.get("client", {}).get("name", p.stem))
        cfg.validate()
        return cfg

    # ---- access -----------------------------------------------------------
    _MISSING = object()

    def get(self, path: str, default: Any = _MISSING) -> Any:
        cur: Any = self.data
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                if default is self._MISSING:
                    raise ConfigError(f"missing config key: {path}")
                return default
            cur = cur[part]
        return cur

    def path(self, key: str) -> Path:
        return (self.root / self.get(key)).resolve()

    def optional_path(self, key: str) -> Path | None:
        v = self.get(key, None)
        return (self.root / v).resolve() if v else None

    # ---- required surface -------------------------------------------------
    REQUIRED = [
        "client.name", "client.anchor",
        "inputs.taxonomy.path", "inputs.taxonomy.sheet", "inputs.taxonomy.columns",
        "inputs.output_format.path", "inputs.output_format.sheet",
        "taxonomy.code_regex", "precedence", "quota.fp_slots", "quota.fn_archetypes",
    ]

    def validate(self) -> None:
        missing = [k for k in self.REQUIRED if self.get(k, None) is None]
        if missing:
            raise ConfigError(
                "client config is missing required keys:\n  " + "\n  ".join(missing)
                + "\n\nCopy config/clients/gcli.yaml and fill these in."
            )
        cols = self.get("inputs.taxonomy.columns")
        for c in ("group", "sub", "expanded", "decision_rules", "engine_code"):
            if c not in cols:
                raise ConfigError(f"inputs.taxonomy.columns.{c} is required")

    # ---- derived ----------------------------------------------------------
    @property
    def salt(self) -> str:
        env = self.get("deidentify.salt_env", "DISPOGEN_DEID_SALT")
        return os.environ.get(env, "dispogen-default-salt")

    def workdir(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p
