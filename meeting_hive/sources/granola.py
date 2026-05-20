"""Granola source adapter — reads meetings via Granola's public REST API.

Docs: https://docs.granola.ai/introduction
API: https://public-api.granola.ai/v1

Auth via Authorization: Bearer <key>. Create a Personal API key in the Granola
desktop app (Settings → Connectors → API keys) and put it in secrets.env as
GRANOLA_API_KEY.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from dateutil import parser as dateparser

from meeting_hive.sources import (
    Meeting,
    SourceAuthError,
    SourceError,
    SourceUnavailable,
)

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://public-api.granola.ai/v1"


class GranolaSource:
    """Read meetings from Granola's REST API.

    Config keys (all optional):
        base_url:    Override the API endpoint. Default: https://public-api.granola.ai/v1.
        api_key_env: Env var holding the API key. Default: GRANOLA_API_KEY.
        api_key:     Inline key (takes precedence over env). Avoid in production.
        retries:     Retry attempts on 429/5xx. Default: 3.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._base_url = cfg.get("base_url", DEFAULT_BASE_URL).rstrip("/")
        self._api_key_env = cfg.get("api_key_env", "GRANOLA_API_KEY")
        self._explicit_key = cfg.get("api_key")
        self._retries = int(cfg.get("retries", 3))
        # Transcript cache populated by list_meetings (which already fetches the
        # detail for every note to read attendees + summary_markdown). Lets
        # get_transcript serve the same data without a second round-trip.
        self._transcript_cache: dict[str, str | None] = {}
        # Fail fast on missing credentials — no point letting the run reach the
        # vocabulary load and the first API call only to abort there.
        if not self._explicit_key and not os.environ.get(self._api_key_env):
            raise SourceAuthError(
                f"{self._api_key_env} not set — check secrets.env. "
                "Create a Personal API key in the Granola desktop app "
                "(Settings → Connectors → API keys). "
                "Requires a Granola Business or Enterprise plan."
            )

    def _headers(self) -> dict[str, str]:
        key = self._explicit_key or os.environ.get(self._api_key_env)
        if not key:
            raise SourceAuthError(f"{self._api_key_env} not set — check secrets.env")
        return {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        }

    def _request(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self._retries):
            try:
                resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
                if resp.status_code == 401:
                    raise SourceAuthError("Granola rejected the API key (401)")
                if resp.status_code == 429:
                    wait = 2**attempt
                    log.warning("Granola 429 — sleeping %ds", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.ConnectionError as e:
                raise SourceUnavailable(f"Cannot reach Granola at {self._base_url}") from e
            except requests.HTTPError as e:
                last_error = e
                if attempt == self._retries - 1:
                    raise SourceError(f"Granola HTTP error: {e}") from e
                time.sleep(2**attempt)
        raise SourceError(f"Granola request failed after {self._retries} attempts: {last_error}")

    def list_meetings(self, since_days: int) -> list[Meeting]:
        cutoff = datetime.now(UTC) - timedelta(days=since_days)
        params: dict[str, Any] = {"created_after": cutoff.isoformat()}
        cursor: str | None = None

        # GET /v1/notes only returns id/title/owner/created_at — no attendees,
        # no transcript. We paginate it to enumerate ids, then hit the detail
        # endpoint for the fields the pipeline actually consumes.
        note_summaries: list[dict] = []
        while True:
            if cursor:
                params["cursor"] = cursor
            data = self._request("/notes", params=params)
            note_summaries.extend(data.get("notes") or [])
            cursor = data.get("cursor") if data.get("hasMore") else None
            if not cursor:
                break

        meetings: list[Meeting] = []
        for summary in note_summaries:
            note_id = summary.get("id")
            if not note_id:
                continue
            detail = self._fetch_detail(note_id)
            if detail is None:
                continue
            meetings.append(self._to_meeting(detail))

        meetings.sort(key=lambda m: m.created_at)
        log.info("Granola: %d meetings in last %d days", len(meetings), since_days)
        return meetings

    def get_transcript(self, meeting_id: str) -> str | None:
        # list_meetings populates _transcript_cache for every meeting it returns,
        # so the typical call path serves the transcript without a network call.
        if meeting_id in self._transcript_cache:
            return self._transcript_cache[meeting_id]
        # Fallback for callers that invoke get_transcript without a preceding
        # list_meetings (tests, ad-hoc CLI use).
        detail = self._fetch_detail(meeting_id)
        if detail is None:
            return None
        return self._transcript_cache.get(meeting_id)

    def _fetch_detail(self, note_id: str) -> dict | None:
        try:
            detail = self._request(f"/notes/{note_id}", params={"include": "transcript"})
        except SourceError as e:
            log.warning("Granola detail fetch failed for %s: %s", note_id, e)
            return None
        transcript = _join_segments(detail.get("transcript") or [])
        self._transcript_cache[note_id] = transcript or None
        return detail

    @staticmethod
    def _to_meeting(detail: dict) -> Meeting:
        attendees_raw = detail.get("attendees") or []
        attendees: list[str] = [
            str(a["email"]) for a in attendees_raw if isinstance(a, dict) and a.get("email")
        ]
        # Granola's attendees list may omit the meeting owner; surface it so
        # downstream email_rules / domain_rules see the owner consistently
        # with how the previous cache-based adapter behaved.
        owner_email = (detail.get("owner") or {}).get("email")
        if owner_email and owner_email not in attendees:
            attendees.append(owner_email)

        created = _parse_dt(detail.get("created_at")) or datetime.now(UTC)
        title = detail.get("title") or "(untitled)"
        reference_summary = detail.get("summary_markdown") or detail.get("summary_text") or None

        return Meeting(
            id=str(detail.get("id")),
            title=title,
            attendees=attendees,
            created_at=created,
            reference_summary=reference_summary,
        )


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return dateparser.parse(value)
    except (ValueError, TypeError):
        return None


def _join_segments(segments: list[dict]) -> str:
    lines: list[str] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        ts = seg.get("start_time")
        if ts:
            try:
                dt = dateparser.parse(ts)
                prefix = f"{dt.strftime('%H:%M:%S')} "
            except (ValueError, TypeError):
                prefix = ""
        else:
            prefix = ""
        lines.append(f"{prefix}{text}")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    src = GranolaSource()
    for m in src.list_meetings(since_days=7):
        print(
            f"  {m.created_at.strftime('%Y-%m-%d %H:%M')} | "
            f"{m.title[:50]:50s} | {len(m.attendees)} attendees"
        )
