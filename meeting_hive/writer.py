"""Write paired {summary, transcript}.md files to ~/.meeting-notes/ with frontmatter."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

NOTES_ROOT = Path.home() / ".meeting-notes"
DEFAULT_SCOPE = "work"
SLUG_MAX_LEN = 60


def slugify(text: str) -> str:
    """Normalize title into a kebab-case slug safe for filenames."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > SLUG_MAX_LEN:
        text = text[:SLUG_MAX_LEN].rstrip("-")
    return text or "untitled"


def target_paths(date_str: str, slug: str, scope: str = DEFAULT_SCOPE, year: str | None = None) -> tuple[Path, Path]:
    """Return (summary_path, transcript_path) for a given date+slug under the given scope."""
    year = year or date_str.split("-")[0]
    base = NOTES_ROOT / scope / year
    return (
        base / f"{date_str}-{slug}-summary.md",
        base / f"{date_str}-{slug}-transcript.md",
    )


def already_exists(date_str: str, slug: str, scope: str = DEFAULT_SCOPE) -> bool:
    summary, transcript = target_paths(date_str, slug, scope=scope)
    return summary.exists() or transcript.exists()


def _format_time_range(start: datetime, duration_seconds: int | None) -> str:
    """Format "HH:MM-HH:MM GMT±HH:MM" from start + optional duration, in local time."""
    start_local = start.astimezone()
    start_str = start_local.strftime("%H:%M")
    if duration_seconds:
        from datetime import timedelta
        end_local = start_local + timedelta(seconds=duration_seconds)
        end_str = end_local.strftime("%H:%M")
    else:
        end_str = start_str

    tz = start_local.strftime("%z")
    if not tz:
        # Naive datetime slipped through — fall back to the current machine offset.
        tz = datetime.now().astimezone().strftime("%z")

    if len(tz) == 5:        # "+HHMM" / "-HHMM"
        tz_fmt = f"GMT{tz[:3]}:{tz[3:]}"
    elif len(tz) == 7:      # "+HHMMSS" / "-HHMMSS" (rare, sub-minute offsets)
        tz_fmt = f"GMT{tz[:3]}:{tz[3:5]}"
    else:
        tz_fmt = "UTC"

    return f"{start_str}-{end_str} {tz_fmt}"


def _frontmatter_block(
    *,
    date_str: str,
    time_str: str,
    title: str,
    classification_type: str,
    classification_entity: str,
    invitees: list[str],
    doc_type: str,
    related: str,
    include_summary_type: bool,
    source: str = "meeting-hive",
) -> str:
    lines = [
        "---",
        f"date: {date_str}",
        f'time: "{time_str}"',
        f'title: "{_escape_yaml(title)}"',
        f"{classification_type}: {classification_entity}",
        "invitees:",
    ]
    for email in invitees:
        lines.append(f"  - {email}")
    lines.append(f"source: {source}")
    if include_summary_type:
        lines.append("summary_type: ai")
    lines.append(f"type: {doc_type}")
    lines.append(f"related: {related}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _escape_yaml(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def write_meeting(
    *,
    title: str,
    start: datetime,
    duration_seconds: int | None,
    attendees: list[str],
    classification_type: str,
    classification_entity: str,
    transcript: str,
    summary: str,
    scope: str = DEFAULT_SCOPE,
    source: str = "meeting-hive",
    dry_run: bool = False,
) -> tuple[Path, Path] | None:
    """Write the paired files. Returns paths, or None if skipped (already exists or dry-run).

    Idempotent: if either file already exists, nothing is written and None is returned.
    """
    date_str = start.astimezone().strftime("%Y-%m-%d")
    slug = slugify(title)
    summary_path, transcript_path = target_paths(date_str, slug, scope=scope)

    if already_exists(date_str, slug, scope=scope):
        log.debug("Skip (exists): %s", summary_path.name)
        return None

    time_str = _format_time_range(start, duration_seconds)

    summary_fm = _frontmatter_block(
        date_str=date_str,
        time_str=time_str,
        title=title,
        classification_type=classification_type,
        classification_entity=classification_entity,
        invitees=attendees,
        doc_type="meeting-summary",
        related=transcript_path.name,
        include_summary_type=True,
        source=source,
    )
    summary_body = f"\n# {title} — Summary\n\n{summary.strip()}\n"

    transcript_fm = _frontmatter_block(
        date_str=date_str,
        time_str=time_str,
        title=title,
        classification_type=classification_type,
        classification_entity=classification_entity,
        invitees=attendees,
        doc_type="meeting-transcript",
        related=summary_path.name,
        include_summary_type=False,
        source=source,
    )
    transcript_body = f"\n# {title} — Transcript\n\n{transcript.strip()}\n"

    if dry_run:
        log.info("[DRY RUN] Would write: %s", summary_path)
        log.info("[DRY RUN] Would write: %s", transcript_path)
        return summary_path, transcript_path

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary_fm + summary_body)
    transcript_path.write_text(transcript_fm + transcript_body)
    log.info("Wrote: %s", summary_path.name)
    return summary_path, transcript_path


if __name__ == "__main__":
    from datetime import timezone
    logging.basicConfig(level=logging.INFO)
    paths = write_meeting(
        title="TEST — Writer smoke check",
        start=datetime(2026, 4, 17, 15, 0, tzinfo=timezone.utc),
        duration_seconds=1800,
        attendees=["alice@example.com", "bob@example.com"],
        classification_type="internal",
        classification_entity="alignment",
        transcript="00:00 Hello world.",
        summary="Smoke test meeting.\n\n## Key Points\n- Test OK",
        dry_run=True,
    )
    print("Would write:", paths)
