"""Adapter registries — resolve/registered/not-found behavior."""

from __future__ import annotations

import pytest

from meeting_hive import sources, summarizers, vocabs


def test_sources_registered_contains_builtin():
    names = sources.registered()
    assert "granola" in names
    assert "fathom" in names
    assert "markdown" in names


def test_vocabs_registered_contains_builtin():
    names = vocabs.registered()
    assert "wispr" in names
    assert "sqlite" in names


def test_summarizers_registered_contains_builtin():
    names = summarizers.registered()
    assert "anthropic" in names
    assert "openai" in names
    assert "ollama" in names


def test_sources_resolve_unknown_raises():
    with pytest.raises(sources.SourceNotFoundError):
        sources.resolve("no-such-source", {})


def test_vocabs_resolve_unknown_raises():
    with pytest.raises(vocabs.VocabNotFoundError):
        vocabs.resolve("no-such-vocab", {})


def test_summarizers_resolve_unknown_raises():
    with pytest.raises(summarizers.SummarizerNotFoundError):
        summarizers.resolve("no-such-summarizer", {})


def test_sqlite_resolves_to_mutable_interface(tmp_path):
    adapter = vocabs.resolve("sqlite", {"db_path": str(tmp_path / "v.db")})
    assert isinstance(adapter, vocabs.MutableVocabularySource)


def test_wispr_resolves_to_read_only_interface(tmp_path):
    adapter = vocabs.resolve("wispr", {"db_path": str(tmp_path / "nonexistent.sqlite")})
    assert isinstance(adapter, vocabs.VocabularySource)
    assert not isinstance(adapter, vocabs.MutableVocabularySource)
