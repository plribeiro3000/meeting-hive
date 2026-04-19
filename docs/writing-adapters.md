# Writing a new adapter

meeting-hive has three adapter axes — **source**, **vocabulary**, **summarizer**
— each with its own Protocol, registry, and exception hierarchy. A new adapter
is almost always a single file + one registry line + one test file.

Before starting, read [`architecture.md`](architecture.md) and skim an existing
adapter of the same axis. The existing ones are the spec.

## The four contracts every adapter respects

1. **Single lookup function (`resolve`).** Call sites never import adapters
   directly. The core pipeline only knows the Protocol.
2. **Minimal Protocol.** The Protocol defines the *smallest* set of methods
   the pipeline uses. Your adapter can have more methods internally; only the
   Protocol ones are read externally.
3. **Opaque per-adapter config dict.** Your `__init__(self, config: dict)`
   self-validates its config. No shared schema between adapters.
4. **Zero inter-adapter coupling.** An adapter module does not import another
   adapter module. Helpers that would be shared belong in the axis's
   `__init__.py`.

## Source adapters

Source adapters fetch meetings and transcripts from some upstream system
(local cache, REST API, markdown directory, …).

**Protocol** (`meeting_hive/sources/__init__.py`):

```python
class MeetingSource(Protocol):
    def list_meetings(self, since_days: int) -> list[Meeting]: ...
    def get_transcript(self, meeting_id: str) -> str | None: ...
```

**Errors to raise** (also in `sources/__init__.py`):

- `SourceAuthError` — auth failed (token expired, rejected). Pipeline shows a
  "re-authenticate" notification and aborts.
- `SourceUnavailable` — backend unreachable (file missing, server down).
- `SourceError` — catch-all base.

**Skeleton:**

```python
# meeting_hive/sources/yourtool.py
from __future__ import annotations

import logging
from typing import Any

from meeting_hive.sources import Meeting, SourceAuthError, SourceUnavailable

log = logging.getLogger(__name__)


class YourToolSource:
    """One-sentence summary of what this adapter reads.

    Config keys:
        api_key_env: env var holding the API key (default: YOURTOOL_API_KEY)
        ...
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._api_key_env = cfg.get("api_key_env", "YOURTOOL_API_KEY")
        # validate or raise SourceUnavailable / ValueError here

    def list_meetings(self, since_days: int) -> list[Meeting]:
        ...

    def get_transcript(self, meeting_id: str) -> str | None:
        ...
```

**Register it** — add one line to `_BUILTINS` in `meeting_hive/sources/__init__.py`:

```python
_BUILTINS: dict[str, str] = {
    "granola": "meeting_hive.sources.granola:GranolaSource",
    "fathom":  "meeting_hive.sources.fathom:FathomSource",
    "yourtool": "meeting_hive.sources.yourtool:YourToolSource",  # ← new
}
```

## Vocabulary adapters

Two Protocol layers:

- **`VocabularySource`** — read-only. Every vocabulary adapter implements this.
- **`MutableVocabularySource`** — extends the above with `add` / `remove` /
  `clear`. Only implement this if meeting-hive *owns* the underlying data
  store. Wrappers around other tools' databases (like `wispr`) should stay
  read-only to avoid corrupting the other tool's data model.

**Skeleton (read-only wrapper):**

```python
class YourToolVocabulary:
    """Reads vocabulary from YourTool's config. Read-only by design."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._path = cfg.get("path")

    def load(self) -> dict[str, str]:
        # Return { phrase: replacement }
        ...
```

**Skeleton (mutable, meeting-hive-owned):**

```python
class YourToolVocabulary:
    def load(self) -> dict[str, str]: ...
    def add(self, phrase: str, replacement: str) -> None: ...
    def remove(self, phrase: str) -> bool: ...
    def clear(self) -> int: ...
```

## Summarizer adapters

Summarizer adapters take a corrected transcript and return a summary string.

**Protocol** (`meeting_hive/summarizers/__init__.py`):

```python
class Summarizer(Protocol):
    def summarize(self, transcript: str, title: str, attendees: list[str]) -> str: ...
```

**Shared helpers** in the same module:

- `format_prompt(transcript, title, attendees) → str` — applies the canonical
  prompt template so output shape stays consistent across backends. Use this.
- `strip_fences(text) → str` — strip surrounding ```` ``` ```` wrappers the
  model sometimes emits.

**Skeleton:**

```python
# meeting_hive/summarizers/yourllm.py
from meeting_hive.summarizers import (
    SummarizerAuthError,
    SummarizerUnavailable,
    format_prompt,
    strip_fences,
)


class YourLLMSummarizer:
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._model = cfg.get("model", "default-model-name")

    def summarize(self, transcript: str, title: str, attendees: list[str]) -> str:
        prompt = format_prompt(transcript=transcript, title=title, attendees=attendees)
        # ... call your backend ...
        return strip_fences(response)
```

## Testing

Every new adapter needs at least three tests:

1. **Happy path** — a minimal input that produces the expected output.
2. **Missing-backend failure** — config points at a non-existent resource;
   adapter raises `SourceUnavailable` / equivalent.
3. **Auth failure** — wrong or missing credentials; adapter raises the right
   `*AuthError`.

See `tests/test_markdown_source.py` for a full example (no network mocks
needed because the markdown adapter is filesystem-only).

For adapters that hit a network, mock with `monkeypatch` on the HTTP client.
Don't add `responses` / `httpretty` — the test suite is stdlib + pytest only.

## Checklist before opening a PR

- [ ] New file in the correct axis directory
- [ ] Line added to `_BUILTINS` in that axis's `__init__.py`
- [ ] Test file in `tests/` covering happy path + at least one failure mode
- [ ] Row added to the adapter table in `README.md`
- [ ] Entry under `## [Unreleased]` → `### Added` in `CHANGELOG.md`
- [ ] `ruff check .`, `mypy`, `pytest -v` all green locally
