"""Fathom source adapter — reads meetings via Fathom's public REST API.

Docs: https://developers.fathom.ai/
API: https://api.fathom.ai/external/v1

Auth via X-Api-Key header. Get a key from your Fathom account settings and
put it in secrets.env as FATHOM_API_KEY.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
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

DEFAULT_BASE_URL = "https://api.fathom.ai/external/v1"
DEFAULT_PAGE_SIZE_HINT = 100  # Fathom uses cursor pagination; size isn't user-controlled.


class FathomSource:
    """Read meetings from Fathom's REST API.

    Config keys (all optional):
        base_url:    Override the API endpoint. Default: https://api.fathom.ai/external/v1.
        api_key_env: Env var holding the API key. Default: FATHOM_API_KEY.
        api_key:     Inline key (takes precedence over env). Avoid in production.
        retries:     Retry attempts on 429/5xx. Default: 3.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._base_url = cfg.get("base_url", DEFAULT_BASE_URL).rstrip("/")
        self._api_key_env = cfg.get("api_key_env", "FATHOM_API_KEY")
        self._explicit_key = cfg.get("api_key")
        self._retries = int(cfg.get("retries", 3))

    def _headers(self) -> dict[str, str]:
        key = self._explicit_key or os.environ.get(self._api_key_env)
        if not key:
            raise SourceAuthError(
                f"{self._api_key_env} not set — check secrets.env"
            )
        return {
            "X-Api-Key": key,
            "Accept": "application/json",
        }

    def _request(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self._retries):
            try:
                resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
                if resp.status_code == 401:
                    raise SourceAuthError("Fathom rejected the API key (401)")
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    log.warning("Fathom 429 — sleeping %ds", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.ConnectionError as e:
                raise SourceUnavailable(f"Cannot reach Fathom at {self._base_url}") from e
            except requests.HTTPError as e:
                last_error = e
                if attempt == self._retries - 1:
                    raise SourceError(f"Fathom HTTP error: {e}") from e
                time.sleep(2 ** attempt)
        raise SourceError(f"Fathom request failed after {self._retries} attempts: {last_error}")

    def list_meetings(self, since_days: int) -> list[Meeting]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        params = {"created_after": cutoff.isoformat()}
        meetings: list[Meeting] = []
        cursor: str | None = None

        while True:
            if cursor:
                params["cursor"] = cursor
            data = self._request("/meetings", params=params)

            for item in data.get("items") or data.get("meetings") or data.get("data") or []:
                meetings.append(self._to_meeting(item))

            cursor = data.get("next_cursor") or data.get("cursor") or None
            if not cursor:
                break

        meetings.sort(key=lambda m: m.created_at)
        log.info("Fathom: %d meetings in last %d days", len(meetings), since_days)
        return meetings

    def get_transcript(self, meeting_id: str) -> str | None:
        try:
            data = self._request(f"/recordings/{meeting_id}/transcript")
        except SourceError as e:
            log.warning("Fathom transcript fetch failed for %s: %s", meeting_id, e)
            return None
        segments = data.get("transcript") or []
        if not segments:
            return None
        return _join_segments(segments)

    @staticmethod
    def _to_meeting(item: dict) -> Meeting:
        recording_id = item.get("recording_id")
        invitees = item.get("calendar_invitees") or []
        attendees = [inv.get("email") for inv in invitees if inv.get("email")]

        created_at = _parse_dt(item.get("created_at"))
        rec_start = _parse_dt(item.get("recording_start_time"))
        rec_end = _parse_dt(item.get("recording_end_time"))
        duration = None
        if rec_start and rec_end:
            duration = int((rec_end - rec_start).total_seconds())

        title = item.get("title") or item.get("meeting_title") or "(untitled)"
        return Meeting(
            id=str(recording_id),
            title=title,
            attendees=attendees,
            created_at=created_at or datetime.now(timezone.utc),
            duration_seconds=duration,
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
        ts = seg.get("timestamp")
        speaker = (seg.get("speaker") or {}).get("display_name") or ""
        prefix_parts = []
        if ts:
            prefix_parts.append(str(ts))
        if speaker:
            prefix_parts.append(speaker)
        prefix = " ".join(prefix_parts)
        lines.append(f"{prefix}: {text}" if prefix else text)
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    src = FathomSource()
    for m in src.list_meetings(since_days=7):
        print(
            f"  {m.created_at.strftime('%Y-%m-%d %H:%M')} | "
            f"{m.title[:50]:50s} | {len(m.attendees)} attendees"
        )
