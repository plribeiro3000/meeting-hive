"""Summarizer adapters — Protocol + registry.

Same four contracts as the other axes: single lookup, minimal Protocol, opaque
config, zero inter-adapter coupling. No default adapter — the installer picks
one at setup time and writes it to config.yaml.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol, runtime_checkable

PROMPT_TEMPLATE = """You write meeting summaries in the exact format below. The meeting was transcribed automatically from audio — transcription errors may exist and you should infer the correct meaning.

# Meeting
- Title: {title}
- Attendees: {attendees}

# Summary format (required)

Write EXACTLY in this structure, with no text before or after:

```
<one-sentence opening paragraph summarizing the objective>

## Key Points
- <Topic 1 name><one sentence describing the topic>
- <bullet detailing a point discussed>
- <bullet detailing another point>
- <Topic 2 name><one sentence describing the topic>
- <bullets>
- ...

## Action Items
- <Owner 1>
- <concrete action>
- <concrete action>
- <Owner 2>
- <action>
```

If there are no clear Action Items, omit the entire section. Topics in "Key Points" should reflect the logical blocks of the conversation (2-5 topics). Don't invent attendees or facts — only what was discussed in the transcript.

Respond in the same language as the transcript.

# Transcript

{transcript}
"""


@runtime_checkable
class Summarizer(Protocol):
    def summarize(self, transcript: str, title: str, attendees: list[str]) -> str: ...


class SummarizerError(RuntimeError):
    """Base exception for summarizer adapter failures."""


class SummarizerAuthError(SummarizerError):
    """Adapter could not authenticate (missing or rejected API key)."""


class SummarizerUnavailable(SummarizerError):
    """Adapter backend is not reachable (server down, etc.)."""


class SummarizerNotFoundError(RuntimeError):
    """Requested adapter name is not registered."""


_BUILTINS: dict[str, str] = {
    "anthropic": "meeting_hive.summarizers.anthropic:AnthropicSummarizer",
    "openai": "meeting_hive.summarizers.openai:OpenAISummarizer",
    "ollama": "meeting_hive.summarizers.ollama:OllamaSummarizer",
}


def resolve(name: str, config: dict[str, Any] | None = None) -> Summarizer:
    if name not in _BUILTINS:
        raise SummarizerNotFoundError(
            f"Unknown summarizer adapter: {name!r}. Built-in: {sorted(_BUILTINS)}"
        )
    module_path, cls_name = _BUILTINS[name].split(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, cls_name)
    return cls(config or {})


def registered() -> list[str]:
    return sorted(_BUILTINS)


def format_prompt(transcript: str, title: str, attendees: list[str]) -> str:
    """Apply the canonical prompt template. Shared by every adapter so the
    output shape stays consistent across backends."""
    return PROMPT_TEMPLATE.format(
        title=title,
        attendees=", ".join(attendees) if attendees else "(not listed)",
        transcript=transcript,
    )


def strip_fences(text: str) -> str:
    """Strip a surrounding ```-fenced block if the model wrapped the output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()
