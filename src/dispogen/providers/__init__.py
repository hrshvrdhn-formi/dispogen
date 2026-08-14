"""Provider registry. Import a module here to register its provider."""
from .base import Completion, Provider, build, register, registered  # noqa: F401
from . import dryrun  # noqa: F401  (always available, no credentials needed)

try:  # optional dependency
    from . import anthropic_provider  # noqa: F401
except Exception:  # pragma: no cover - SDK absent
    pass

__all__ = ["Completion", "Provider", "build", "register", "registered"]
