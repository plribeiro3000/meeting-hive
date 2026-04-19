"""sync.run end-to-end with stubbed adapters — no network, no disk writes outside tmp."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from meeting_hive import classifier, sources, sync, writer


class _StubSource:
    def __init__(self, meetings, transcripts):
        self._meetings = meetings
        self._transcripts = transcripts

    def list_meetings(self, since_days):
        return self._meetings

    def get_transcript(self, meeting_id):
        return self._transcripts.get(meeting_id)


class _StubVocab:
    def __init__(self, mapping):
        self._mapping = mapping

    def load(self):
        return self._mapping


class _StubSummarizer:
    def __init__(self, text="Summary body."):
        self._text = text
        self.calls = []

    def summarize(self, transcript, title, attendees):
        self.calls.append((transcript, title, list(attendees)))
        return self._text


@pytest.fixture
def base_cfg():
    return {
        "source": {"adapter": "granola", "config": {}},
        "vocabulary": {"adapter": "sqlite", "config": {}},
        "summarizer": {"adapter": "anthropic", "config": {}},
        "scope": "work",
        "internal_domains": ["mycompany.com"],
        "internal_only": {"default_subtype": "alignment"},
        "domain_rules": {"acme.com": {"type": "client", "entity": "Acme"}},
        "title_patterns": [],
        "email_rules": {},
    }


@pytest.fixture
def _patch_adapters(monkeypatch, base_cfg):
    """Swap out config loader and adapter resolvers with stubs."""
    meeting = sources.Meeting(
        id="m1",
        title="Kickoff with Acme",
        attendees=["alice@acme.com", "me@mycompany.com"],
        created_at=datetime(2026, 4, 17, 15, 0, tzinfo=UTC),
        duration_seconds=1800,
    )
    stub_source = _StubSource(
        meetings=[meeting],
        transcripts={"m1": "00:00 Post Grass discussion."},
    )
    stub_vocab = _StubVocab({"Post Grass": "Postgres"})
    stub_summarizer = _StubSummarizer("## Key Points\n- discussed DB")

    monkeypatch.setattr(classifier, "load_config", lambda *a, **kw: base_cfg)
    monkeypatch.setattr(sync, "_resolve_source", lambda cfg: stub_source)
    monkeypatch.setattr(sync, "_resolve_vocab", lambda cfg: stub_vocab)
    monkeypatch.setattr(sync, "_resolve_summarizer", lambda cfg: stub_summarizer)
    return stub_source, stub_vocab, stub_summarizer


def test_dry_run_processes_meeting_without_writing(tmp_path, monkeypatch, _patch_adapters):
    monkeypatch.setattr(writer, "NOTES_ROOT", tmp_path / ".meeting-notes")
    stats = sync.run(since_days=7, dry_run=True)
    assert stats["processed"] == 1
    assert stats["failed"] == 0
    # Dry-run must not create files.
    assert not (tmp_path / ".meeting-notes").exists()


def test_real_run_writes_paired_files(tmp_path, monkeypatch, _patch_adapters):
    monkeypatch.setattr(writer, "NOTES_ROOT", tmp_path / ".meeting-notes")
    # notifications are best-effort; silence them for the test
    from meeting_hive import notify

    monkeypatch.setattr(notify, "notify", lambda *a, **kw: None)

    stats = sync.run(since_days=7, dry_run=False)
    assert stats["processed"] == 1
    archive = tmp_path / ".meeting-notes" / "work" / "2026"
    files = sorted(p.name for p in archive.iterdir())
    assert any(f.endswith("-summary.md") for f in files)
    assert any(f.endswith("-transcript.md") for f in files)


def test_vocabulary_is_applied_to_transcript(tmp_path, monkeypatch, _patch_adapters):
    monkeypatch.setattr(writer, "NOTES_ROOT", tmp_path / ".meeting-notes")
    from meeting_hive import notify

    monkeypatch.setattr(notify, "notify", lambda *a, **kw: None)

    sync.run(since_days=7, dry_run=False)

    transcript_file = next((tmp_path / ".meeting-notes" / "work" / "2026").glob("*-transcript.md"))
    content = transcript_file.read_text()
    assert "Postgres" in content
    assert "Post Grass" not in content


def test_unclassified_meeting_is_skipped_not_failed(tmp_path, monkeypatch, base_cfg):
    """UNCLASSIFIED goes to pending_classification, doesn't write, doesn't fail."""
    meeting = sources.Meeting(
        id="m2",
        title="Call with Unknown",
        attendees=["x@newco.io", "me@mycompany.com"],
        created_at=datetime(2026, 4, 17, 15, 0, tzinfo=UTC),
    )
    stub_source = _StubSource(meetings=[meeting], transcripts={"m2": "body"})

    monkeypatch.setattr(classifier, "load_config", lambda *a, **kw: base_cfg)
    monkeypatch.setattr(sync, "_resolve_source", lambda cfg: stub_source)
    monkeypatch.setattr(sync, "_resolve_vocab", lambda cfg: _StubVocab({}))
    monkeypatch.setattr(sync, "_resolve_summarizer", lambda cfg: _StubSummarizer())
    monkeypatch.setattr(writer, "NOTES_ROOT", tmp_path / ".meeting-notes")
    from meeting_hive import notify

    monkeypatch.setattr(notify, "notify", lambda *a, **kw: None)

    stats = sync.run(since_days=7, dry_run=False)
    assert stats["processed"] == 0
    assert stats["pending_classification"] == 1
    assert stats["failed"] == 0
    assert not (tmp_path / ".meeting-notes").exists()


def test_missing_summarizer_adapter_fails_cleanly(tmp_path, monkeypatch, base_cfg):
    cfg = {**base_cfg, "summarizer": {}}
    monkeypatch.setattr(classifier, "load_config", lambda *a, **kw: cfg)
    # Real _resolve_summarizer will raise SummarizerNotFoundError.
    monkeypatch.setattr(sync, "_resolve_source", lambda cfg: _StubSource([], {}))
    monkeypatch.setattr(sync, "_resolve_vocab", lambda cfg: _StubVocab({}))
    from meeting_hive import notify

    monkeypatch.setattr(notify, "notify", lambda *a, **kw: None)

    stats = sync.run(since_days=7, dry_run=True)
    assert stats["failed"] == 1
