"""Registry of usage sources. New agents register their adapter here."""

from __future__ import annotations

from ..i18n import t
from .base import ParseResult, Source
from .claude_code import ClaudeCodeSource

_REGISTRY: dict[str, type[Source]] = {
    ClaudeCodeSource.name: ClaudeCodeSource,
}


def available_sources() -> list[str]:
    return sorted(_REGISTRY)


def create_sources(names: list[str] | None = None) -> list[Source]:
    selected = names or available_sources()
    unknown = [name for name in selected if name not in _REGISTRY]
    if unknown:
        raise ValueError(t("error.source", names=", ".join(unknown)))
    return [_REGISTRY[name]() for name in selected]


__all__ = ["ParseResult", "Source", "available_sources", "create_sources"]
