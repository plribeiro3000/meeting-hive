"""Ollama summarizer adapter — local LLM via the Ollama HTTP API.

Requires a running Ollama server (https://ollama.com). Default endpoint is
http://localhost:11434. No API key needed.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from meeting_hive.summarizers import (
    SummarizerError,
    SummarizerUnavailable,
    format_prompt,
    strip_fences,
)

log = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3"


class OllamaSummarizer:
    """Regenerate meeting summaries via a local Ollama server.

    Config keys (all optional):
        base_url:  Ollama server URL. Default: http://localhost:11434.
        model:     Model name available on the Ollama server. Default: llama3.
        timeout:   HTTP timeout in seconds. Default: 300 (local models can be slow).
        retries:   Retry attempts on transient errors. Default: 3.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._base_url = cfg.get("base_url", DEFAULT_URL).rstrip("/")
        self._model = cfg.get("model", DEFAULT_MODEL)
        self._timeout = int(cfg.get("timeout", 300))
        self._retries = int(cfg.get("retries", 3))

    def summarize(self, transcript: str, title: str, attendees: list[str]) -> str:
        prompt = format_prompt(transcript, title, attendees)
        url = f"{self._base_url}/api/chat"
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }

        last_error: Exception | None = None
        for attempt in range(self._retries):
            try:
                resp = requests.post(url, json=body, timeout=self._timeout)
                if resp.status_code == 404:
                    raise SummarizerError(
                        f"Ollama model {self._model!r} not found on {self._base_url}. "
                        f"Run `ollama pull {self._model}` to install it."
                    )
                resp.raise_for_status()
                data = resp.json()
                content = (data.get("message") or {}).get("content") or ""
                return strip_fences(content)
            except requests.ConnectionError as e:
                raise SummarizerUnavailable(
                    f"Cannot reach Ollama at {self._base_url} — is the server running?"
                ) from e
            except requests.HTTPError as e:
                last_error = e
                wait = 2 ** attempt
                log.warning(
                    "Ollama HTTP error (attempt %d/%d): %s — sleeping %ds",
                    attempt + 1, self._retries, e, wait,
                )
                time.sleep(wait)

        raise SummarizerError(f"Ollama failed after {self._retries} attempts: {last_error}")
