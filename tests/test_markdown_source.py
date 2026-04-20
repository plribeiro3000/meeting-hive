"""Markdown source adapter — frontmatter parsing, date filtering, attendee extraction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from meeting_hive.sources import SourceUnavailable
from meeting_hive.sources.markdown import MarkdownSource


def _write(path, frontmatter: dict, body: str = "") -> None:
    import yaml

    path.write_text("---\n" + yaml.safe_dump(frontmatter) + "---\n" + body)


def test_missing_directory_raises(tmp_path):
    src = MarkdownSource({"path": str(tmp_path / "does-not-exist")})
    with pytest.raises(SourceUnavailable):
        src.list_meetings(since_days=7)


def test_requires_path():
    with pytest.raises(ValueError, match="path"):
        MarkdownSource({})


def test_lists_files_with_frontmatter(tmp_path):
    _write(
        tmp_path / "2026-04-17-kickoff.md",
        {"title": "Kickoff", "date": "2026-04-17", "attendees": ["a@x.com", "b@y.com"]},
        body="transcript text",
    )
    src = MarkdownSource({"path": str(tmp_path)})
    meetings = src.list_meetings(since_days=365 * 100)  # wide window, deterministic
    assert len(meetings) == 1
    m = meetings[0]
    assert m.title == "Kickoff"
    assert m.attendees == ["a@x.com", "b@y.com"]


def test_date_cutoff_excludes_old_files(tmp_path):
    old = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
    recent = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    _write(tmp_path / "old.md", {"title": "old", "date": old})
    _write(tmp_path / "recent.md", {"title": "recent", "date": recent})

    src = MarkdownSource({"path": str(tmp_path)})
    meetings = src.list_meetings(since_days=7)
    titles = [m.title for m in meetings]
    assert "recent" in titles
    assert "old" not in titles


def test_ignore_summary_skips_meeting_summary_type(tmp_path):
    _write(
        tmp_path / "a.md",
        {"title": "transcript", "date": "2026-04-17", "type": "meeting-transcript"},
    )
    _write(
        tmp_path / "b.md",
        {"title": "summary", "date": "2026-04-17", "type": "meeting-summary"},
    )
    src = MarkdownSource({"path": str(tmp_path)})
    meetings = src.list_meetings(since_days=365 * 100)
    titles = [m.title for m in meetings]
    assert "transcript" in titles
    assert "summary" not in titles


def test_invitees_field_is_recognized(tmp_path):
    _write(
        tmp_path / "a.md",
        {"title": "x", "date": "2026-04-17", "invitees": ["me@x.com"]},
    )
    src = MarkdownSource({"path": str(tmp_path)})
    m = src.list_meetings(since_days=365 * 100)[0]
    assert m.attendees == ["me@x.com"]


def test_get_transcript_returns_body(tmp_path):
    _write(
        tmp_path / "2026-04-17-k.md",
        {"title": "K", "date": "2026-04-17"},
        body="line one\nline two\n",
    )
    src = MarkdownSource({"path": str(tmp_path)})
    meetings = src.list_meetings(since_days=365 * 100)
    transcript = src.get_transcript(meetings[0].id)
    assert transcript == "line one\nline two"


def test_bad_frontmatter_is_skipped_not_fatal(tmp_path):
    (tmp_path / "broken.md").write_text("---\nkey: [unclosed\n---\nbody")
    _write(tmp_path / "good.md", {"title": "good", "date": "2026-04-17"})
    src = MarkdownSource({"path": str(tmp_path)})
    meetings = src.list_meetings(since_days=365 * 100)
    titles = [m.title for m in meetings]
    assert "good" in titles
