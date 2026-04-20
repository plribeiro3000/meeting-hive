"""Vocabulary adapters — Protocol + registry.

Same four contracts as sources: single lookup, minimal Protocol, opaque config,
zero inter-adapter coupling.

Two Protocol layers:

- `VocabularySource` — read-only (every adapter implements this).
- `MutableVocabularySource` — adds edit operations (used by adapters meeting-hive
  owns, like `sqlite`; not used by adapters that wrap external tools, like `wispr`,
  where write-back would corrupt the other tool's data model).
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VocabularySource(Protocol):
    def load(self) -> dict[str, str]:
        """Return a mapping of `phrase -> replacement`."""
        ...


@runtime_checkable
class MutableVocabularySource(VocabularySource, Protocol):
    def add(self, phrase: str, replacement: str) -> None: ...
    def remove(self, phrase: str) -> bool:
        """Return True if removed, False if phrase was not present."""
        ...

    def clear(self) -> int:
        """Remove everything. Return the number of entries removed."""
        ...


class VocabError(RuntimeError):
    """Base exception for vocabulary adapter failures."""


class VocabNotFoundError(RuntimeError):
    """Requested adapter name is not registered."""


class VocabReadOnlyError(VocabError):
    """Raised when a mutation is attempted on a read-only adapter."""


_BUILTINS: dict[str, str] = {
    "wispr": "meeting_hive.vocabs.wispr:WisprVocabulary",
    "sqlite": "meeting_hive.vocabs.sqlite:SqliteVocabulary",
}


def resolve(name: str, config: dict[str, Any] | None = None) -> VocabularySource:
    if name not in _BUILTINS:
        raise VocabNotFoundError(
            f"Unknown vocabulary adapter: {name!r}. Built-in: {sorted(_BUILTINS)}"
        )
    module_path, cls_name = _BUILTINS[name].split(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, cls_name)
    return cls(config or {})


def registered() -> list[str]:
    return sorted(_BUILTINS)
