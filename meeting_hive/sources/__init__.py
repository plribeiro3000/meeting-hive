"""Meeting source adapters — Protocol + registry.

Contracts respected by every adapter:

1. Single lookup function (`resolve`). Call sites never import adapters directly.
2. Minimal Protocol. Pipeline reads only the fields on `Meeting` defined here.
3. Opaque per-adapter config dict. Adapters self-validate their config.
4. Zero coupling between adapters. An adapter module does not import another adapter.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class Meeting:
    """Minimal meeting shape consumed by the pipeline.

    Adapters may carry more fields internally; only these are read by the pipeline.
    """

    id: str
    title: str
    attendees: list[str]
    created_at: datetime
    duration_seconds: int | None = None


@runtime_checkable
class MeetingSource(Protocol):
    def list_meetings(self, since_days: int) -> list[Meeting]: ...
    def get_transcript(self, meeting_id: str) -> str | None: ...


class SourceError(RuntimeError):
    """Base exception for source adapter failures."""


class SourceAuthError(SourceError):
    """Adapter could not authenticate with its backend; user action required."""


class SourceUnavailable(SourceError):
    """Adapter backend is not reachable or not set up yet."""


class SourceNotFoundError(RuntimeError):
    """Requested adapter name is not registered."""


# Dotted string → module path:class name, lazy-imported by resolve().
_BUILTINS: dict[str, str] = {
    "granola": "meeting_hive.sources.granola:GranolaSource",
    "fathom": "meeting_hive.sources.fathom:FathomSource",
    "markdown": "meeting_hive.sources.markdown:MarkdownSource",
}


def resolve(name: str, config: dict[str, Any] | None = None) -> MeetingSource:
    """Instantiate a source adapter by registered name."""
    if name not in _BUILTINS:
        raise SourceNotFoundError(
            f"Unknown source adapter: {name!r}. Built-in: {sorted(_BUILTINS)}"
        )
    module_path, cls_name = _BUILTINS[name].split(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, cls_name)
    return cls(config or {})


def registered() -> list[str]:
    return sorted(_BUILTINS)
