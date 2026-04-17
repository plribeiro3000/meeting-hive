"""Generic markdown-directory source adapter.

Tool-agnostic: reads meetings from a directory of markdown files with YAML
frontmatter. Works with any meeting tool that exports markdown, or with hand-
written notes.

Expected file layout (default):

    <root>/
        YYYY-MM-DD-<slug>.md

Expected frontmatter (keys are lowercase; extras are ignored):

    ---
    title: "Kickoff with Acme"
    date: 2026-04-17
    time: "15:00-15:30"          # optional — "HH:MM" or "HH:MM-HH:MM", 24h
    attendees:                    # or `invitees:` — list of emails
      - alice@acme.com
      - me@example.com
    id: optional-stable-id       # falls back to filename stem
    ---
    (transcript body)

The body (everything after the frontmatter) is returned verbatim as the
transcript text.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from meeting_hive.sources import Meeting, SourceUnavailable

log = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


class MarkdownSource:
    """Read meetings from a directory of YAML-frontmatter markdown files.

    Config keys (all optional except `path`):
        path:          directory to scan. **Required.**
        pattern:       glob for meeting files (default: "**/*.md").
        id_field:      frontmatter key to use as meeting id
                       (default: "id"; falls back to filename stem).
        attendees_field: frontmatter key holding attendee emails
                         (default: tries "attendees", then "invitees").
        ignore_summary: if True, skips files whose frontmatter `type` is
                        "meeting-summary" (default: True — avoids re-ingesting
                        our own summary files when pointing this adapter at
                        ~/.meeting-notes/).
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        path = cfg.get("path")
        if not path:
            raise ValueError("MarkdownSource requires `path` in config")
        self._root = Path(path).expanduser()
        self._pattern = cfg.get("pattern", "**/*.md")
        self._id_field = cfg.get("id_field", "id")
        self._attendees_field = cfg.get("attendees_field")
        self._ignore_summary = cfg.get("ignore_summary", True)
        self._index: dict[str, Path] = {}  # populated on list_meetings

    def list_meetings(self, since_days: int) -> list[Meeting]:
        if not self._root.exists():
            raise SourceUnavailable(f"Markdown source path not found: {self._root}")

        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        meetings: list[Meeting] = []
        self._index = {}

        for file in sorted(self._root.glob(self._pattern)):
            try:
                fm, _body = _split_frontmatter(file.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("Skipping %s — failed to parse frontmatter: %s", file.name, e)
                continue
            if not fm:
                continue
            if self._ignore_summary and str(fm.get("type", "")).lower() == "meeting-summary":
                continue

            created = _parse_datetime(fm)
            if created is None:
                log.debug("Skipping %s — no usable date in frontmatter", file.name)
                continue
            if created < cutoff:
                continue

            attendees = _extract_attendees(fm, self._attendees_field)
            meeting_id = str(fm.get(self._id_field) or file.stem)
            title = str(fm.get("title") or file.stem)

            self._index[meeting_id] = file
            meetings.append(
                Meeting(id=meeting_id, title=title, attendees=attendees, created_at=created)
            )

        meetings.sort(key=lambda m: m.created_at)
        log.info("Markdown: %d meetings in last %d days", len(meetings), since_days)
        return meetings

    def get_transcript(self, meeting_id: str) -> str | None:
        file = self._index.get(meeting_id)
        if file is None:
            # Fallback: slow scan (covers the case where get_transcript is called
            # without a preceding list_meetings, e.g. during tests).
            for candidate in self._root.glob(self._pattern):
                if candidate.stem == meeting_id:
                    file = candidate
                    break
        if file is None or not file.exists():
            return None
        try:
            _fm, body = _split_frontmatter(file.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to read transcript from %s: %s", file.name, e)
            return None
        return body.strip() or None


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_raw, body = m.group(1), m.group(2)
    fm = yaml.safe_load(fm_raw) or {}
    if not isinstance(fm, dict):
        raise ValueError("frontmatter is not a mapping")
    return fm, body


def _parse_datetime(fm: dict) -> datetime | None:
    """Build a tz-aware datetime from frontmatter `date` + optional `time`."""
    date_val = fm.get("date")
    if date_val is None:
        return None

    if isinstance(date_val, datetime):
        dt = date_val
    elif hasattr(date_val, "year") and hasattr(date_val, "month") and hasattr(date_val, "day"):
        # `datetime.date` (from YAML) — combine with optional time.
        t = _parse_time(fm.get("time"))
        dt = datetime.combine(date_val, t or time(0, 0))
    else:
        try:
            dt = datetime.fromisoformat(str(date_val))
        except ValueError:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def _parse_time(raw: Any) -> time | None:
    if raw is None:
        return None
    m = _TIME_RE.search(str(raw))
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return time(hh, mm)
    return None


def _extract_attendees(fm: dict, preferred_field: str | None) -> list[str]:
    candidates = [preferred_field] if preferred_field else ["attendees", "invitees"]
    for key in candidates:
        if key and key in fm:
            val = fm[key]
            if isinstance(val, list):
                return [str(x) for x in val if isinstance(x, str) and x]
            if isinstance(val, str):
                return [val]
    return []


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    src = MarkdownSource({"path": root})
    for m in src.list_meetings(since_days=30):
        print(
            f"  {m.created_at.strftime('%Y-%m-%d %H:%M')} | "
            f"{m.title[:50]:50s} | {len(m.attendees)} attendees"
        )
