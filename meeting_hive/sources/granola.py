"""Granola source adapter (local cache + REST API fallback).

Supports macOS natively. The Granola app exists for macOS and is coming to
Windows; when it ships, this adapter should work on Windows as well (point
`cache_path` at the app's Roaming/AppData location via config).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dateutil import parser as dateparser

from meeting_hive.sources import (
    Meeting,
    SourceAuthError,
    SourceUnavailable,
)

log = logging.getLogger(__name__)

API_BASE = "https://api.granola.ai/v1"
CLIENT_HEADERS = {
    "User-Agent": "Granola/1.0.0 (Macintosh; OS X/15.0.0) Electron/33.0.0",
    "Accept": "application/json, text/plain, */*",
    "X-Client-Version": "5.354.0",
}


def _default_app_dir() -> Path:
    """Where Granola keeps its cache and auth files by OS."""
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Roaming" / "Granola"
    # macOS (Linux is not supported by Granola itself, but we don't need to fail here —
    # the cache file simply won't exist and we'll raise SourceUnavailable on use).
    return Path.home() / "Library" / "Application Support" / "Granola"


class GranolaSource:
    """Read meetings from Granola's local cache, falling back to the REST API.

    Config keys (all optional):
        cache_path:     override the Granola app data directory.
        cache_filename: override the cache JSON filename (default: cache-v6.json).
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._app_dir = Path(cfg.get("cache_path") or _default_app_dir()).expanduser()
        self._cache_filename = cfg.get("cache_filename", "cache-v6.json")

    @property
    def _cache_path(self) -> Path:
        return self._app_dir / self._cache_filename

    @property
    def _auth_path(self) -> Path:
        return self._app_dir / "supabase.json"

    def _load_token(self) -> str:
        if not self._auth_path.exists():
            raise SourceUnavailable(f"Granola auth file not found at {self._auth_path}")
        data = json.loads(self._auth_path.read_text())
        workos = data.get("workos_tokens")
        if not workos:
            raise SourceAuthError("No workos_tokens in supabase.json")
        tokens = json.loads(workos) if isinstance(workos, str) else workos
        token = tokens.get("access_token")
        if not token:
            raise SourceAuthError("No access_token in workos_tokens")
        return token

    def _load_cache(self) -> dict:
        if not self._cache_path.exists():
            raise SourceUnavailable(f"Granola cache not found at {self._cache_path}")
        return json.loads(self._cache_path.read_text())

    def _api_post(self, path: str, body: dict, token: str, retries: int = 3) -> Any:
        url = f"{API_BASE}{path}"
        headers = {**CLIENT_HEADERS, "Authorization": f"Bearer {token}"}
        for attempt in range(retries):
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=30)
                if resp.status_code == 401:
                    raise SourceAuthError(
                        "Granola token rejected (401) — re-login in the desktop app"
                    )
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    log.warning("Granola 429 — sleeping %ds", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    def list_meetings(self, since_days: int) -> list[Meeting]:
        cache = self._load_cache()
        docs = cache.get("cache", {}).get("state", {}).get("documents", {})

        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        meetings: list[Meeting] = []

        for doc_id, doc in docs.items():
            if doc.get("deleted_at"):
                continue
            if not doc.get("valid_meeting", True):
                continue
            try:
                created = dateparser.parse(doc["created_at"])
            except (KeyError, ValueError):
                continue
            if created < cutoff:
                continue

            people = doc.get("people") or {}
            attendees_raw = people.get("attendees") or []
            attendees = [a.get("email") for a in attendees_raw if a.get("email")]
            creator_email = (people.get("creator") or {}).get("email")
            if creator_email and creator_email not in attendees:
                attendees.append(creator_email)

            meetings.append(Meeting(
                id=doc_id,
                title=doc.get("title") or "(untitled)",
                attendees=attendees,
                created_at=created,
            ))

        meetings.sort(key=lambda m: m.created_at)
        log.info("Granola: %d meetings in last %d days", len(meetings), since_days)
        return meetings

    def get_transcript(self, meeting_id: str) -> str | None:
        cache = self._load_cache()
        transcripts = cache.get("cache", {}).get("state", {}).get("transcripts", {})

        segments = transcripts.get(meeting_id)
        if segments:
            return _join_segments(segments)

        # Fallback: REST API.
        try:
            token = self._load_token()
            data = self._api_post(
                "/get-document-transcript", {"document_id": meeting_id}, token
            )
        except SourceAuthError:
            raise
        except Exception as e:
            log.warning("Granola API transcript fetch failed for %s: %s", meeting_id, e)
            return None

        if isinstance(data, list):
            return _join_segments(data)
        if isinstance(data, dict) and "transcript" in data:
            t = data["transcript"]
            if isinstance(t, list):
                return _join_segments(t)
            if isinstance(t, str):
                return t
        log.warning("Unexpected transcript shape for %s: %s", meeting_id, type(data).__name__)
        return None


def _join_segments(segments: list[dict]) -> str:
    lines = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        ts = seg.get("start_timestamp")
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
