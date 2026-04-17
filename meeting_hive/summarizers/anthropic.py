"""Anthropic summarizer adapter — Claude family via the Anthropic SDK."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from meeting_hive.summarizers import (
    SummarizerAuthError,
    SummarizerError,
    format_prompt,
    strip_fences,
)

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-5-20251001"
DEFAULT_MAX_TOKENS = 2000


class AnthropicSummarizer:
    """Regenerate meeting summaries via Claude (or any Anthropic-compatible endpoint).

    Config keys (all optional):
        model:         Anthropic model ID. Default: claude-sonnet-4-5-20251001.
        max_tokens:    Upper bound on response size. Default: 2000.
        api_key_env:   Env var holding the API key. Default: ANTHROPIC_API_KEY.
        base_url:      Override the API endpoint (e.g. LiteLLM proxy, AWS Bedrock
                       via a compat layer). Leave unset for api.anthropic.com.
        retries:       Retry attempts on 429/5xx. Default: 3.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._model = cfg.get("model", DEFAULT_MODEL)
        self._max_tokens = int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS))
        self._api_key_env = cfg.get("api_key_env", "ANTHROPIC_API_KEY")
        self._base_url = cfg.get("base_url")
        self._retries = int(cfg.get("retries", 3))
        self._explicit_key = cfg.get("api_key")

    def _get_key(self) -> str:
        key = self._explicit_key or os.environ.get(self._api_key_env)
        if not key:
            raise SummarizerAuthError(
                f"{self._api_key_env} not set — check your secrets.env"
            )
        return key

    def summarize(self, transcript: str, title: str, attendees: list[str]) -> str:
        import anthropic

        prompt = format_prompt(transcript, title, attendees)
        client = anthropic.Anthropic(api_key=self._get_key(), base_url=self._base_url)

        last_error: Exception | None = None
        for attempt in range(self._retries):
            try:
                message = client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return strip_fences(message.content[0].text)
            except anthropic.AuthenticationError as e:
                raise SummarizerAuthError(str(e)) from e
            except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
                last_error = e
                wait = 2 ** attempt
                log.warning(
                    "Anthropic error (attempt %d/%d): %s — sleeping %ds",
                    attempt + 1, self._retries, e, wait,
                )
                time.sleep(wait)

        raise SummarizerError(f"Anthropic failed after {self._retries} attempts: {last_error}")
