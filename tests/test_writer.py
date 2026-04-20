"""Writer: slug generation, frontmatter shape, idempotency by filename."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from meeting_hive import writer


@pytest.fixture
def sample_write_args():
    return {
        "title": "Kickoff — Acme / MyCompany",
        "start": datetime(2026, 4, 17, 15, 0, tzinfo=UTC),
        "duration_seconds": 1800,
        "attendees": ["alice@acme.com", "me@mycompany.com"],
        "classification_type": "client",
        "classification_entity": "Acme",
        "transcript": "00:00 Hello world.",
        "summary": "Smoke test meeting.\n\n## Key Points\n- Test OK",
    }


@pytest.fixture(autouse=True)
def _archive_under_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(writer, "NOTES_ROOT", tmp_path / ".meeting-notes")


def test_slugify_handles_accents_and_symbols():
    assert writer.slugify("Reunião — Acme/Álvaro") == "reuniao-acme-alvaro"


def test_slugify_empty_string_is_untitled():
    assert writer.slugify("") == "untitled"
    assert writer.slugify("!!!") == "untitled"


def test_slugify_respects_max_len():
    long = "a" * 200
    slug = writer.slugify(long)
    assert len(slug) <= writer.SLUG_MAX_LEN
    assert slug == "a" * writer.SLUG_MAX_LEN


def test_slugify_trims_trailing_hyphens_after_truncation():
    text = "a" * 59 + " " * 10 + "b" * 30
    slug = writer.slugify(text)
    assert not slug.endswith("-")


def test_write_creates_paired_files(sample_write_args):
    result = writer.write_meeting(**sample_write_args, scope="work")
    assert result is not None
    summary, transcript = result
    assert summary.exists()
    assert transcript.exists()
    assert summary.name.endswith("-summary.md")
    assert transcript.name.endswith("-transcript.md")


def test_write_is_idempotent_when_summary_already_exists(sample_write_args, tmp_path):
    result = writer.write_meeting(**sample_write_args, scope="work")
    assert result is not None

    # Second call should return None (skipped).
    second = writer.write_meeting(**sample_write_args, scope="work")
    assert second is None


def test_write_dry_run_does_not_create_files(sample_write_args, tmp_path):
    result = writer.write_meeting(**sample_write_args, scope="work", dry_run=True)
    assert result is not None
    summary, transcript = result
    assert not summary.exists()
    assert not transcript.exists()


def test_frontmatter_contains_expected_fields(sample_write_args):
    result = writer.write_meeting(**sample_write_args, scope="work")
    assert result is not None
    summary_content = result[0].read_text()
    assert summary_content.startswith("---\n")
    assert "date: 2026-04-17" in summary_content
    assert 'title: "Kickoff' in summary_content
    assert "client: Acme" in summary_content
    assert "alice@acme.com" in summary_content
    assert "summary_type: ai" in summary_content
    assert "type: meeting-summary" in summary_content
    assert "related:" in summary_content
    assert "source: meeting-hive" in summary_content


def test_transcript_frontmatter_omits_summary_type(sample_write_args):
    result = writer.write_meeting(**sample_write_args, scope="work")
    assert result is not None
    transcript_content = result[1].read_text()
    assert "summary_type" not in transcript_content
    assert "type: meeting-transcript" in transcript_content


def test_files_go_under_scope_and_year(sample_write_args, tmp_path):
    result = writer.write_meeting(**sample_write_args, scope="personal")
    assert result is not None
    summary = result[0]
    assert "personal" in summary.parts
    assert "2026" in summary.parts


def test_quotes_in_title_are_escaped(sample_write_args):
    sample_write_args["title"] = 'She said "hi"'
    result = writer.write_meeting(**sample_write_args, scope="work")
    assert result is not None
    summary_content = result[0].read_text()
    # Title line should have the quote escaped, not unterminated YAML.
    assert 'title: "She said \\"hi\\""' in summary_content


def test_target_paths_shape():
    summary, transcript = writer.target_paths("2026-04-17", "acme-kickoff", scope="work")
    assert summary.name == "2026-04-17-acme-kickoff-summary.md"
    assert transcript.name == "2026-04-17-acme-kickoff-transcript.md"
    assert summary.parent.name == "2026"
