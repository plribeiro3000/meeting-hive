"""SQLite vocabulary adapter — mutable, upsert semantics, bulk import."""

from __future__ import annotations

import pytest

from meeting_hive import vocabs
from meeting_hive.vocabs.sqlite import SqliteVocabulary


@pytest.fixture
def vocab(tmp_path):
    return SqliteVocabulary({"db_path": str(tmp_path / "vocab.db")})


def test_resolve_returns_mutable_adapter(tmp_path):
    adapter = vocabs.resolve("sqlite", {"db_path": str(tmp_path / "v.db")})
    assert isinstance(adapter, vocabs.MutableVocabularySource)


def test_empty_vocabulary_loads_empty_dict(vocab):
    assert vocab.load() == {}


def test_add_and_load(vocab):
    vocab.add("Post Grass", "Postgres")
    vocab.add("Cube Or Nets", "Kubernetes")
    loaded = vocab.load()
    assert loaded == {"Post Grass": "Postgres", "Cube Or Nets": "Kubernetes"}


def test_add_upserts_existing_phrase(vocab):
    vocab.add("Super Base", "Supabase")
    vocab.add("Super Base", "Supabase (edited)")
    assert vocab.load()["Super Base"] == "Supabase (edited)"


def test_add_rejects_empty(vocab):
    with pytest.raises(ValueError):
        vocab.add("", "x")
    with pytest.raises(ValueError):
        vocab.add("x", "")


def test_remove_returns_true_when_present(vocab):
    vocab.add("x", "y")
    assert vocab.remove("x") is True
    assert vocab.load() == {}


def test_remove_returns_false_when_absent(vocab):
    assert vocab.remove("nope") is False


def test_clear_returns_count(vocab):
    vocab.add("a", "b")
    vocab.add("c", "d")
    assert vocab.clear() == 2
    assert vocab.load() == {}


def test_bulk_upsert_creates_all(vocab):
    n = vocab.bulk_upsert({"a": "1", "b": "2", "c": "3"}, source="import:test")
    assert n == 3
    assert vocab.load() == {"a": "1", "b": "2", "c": "3"}


def test_bulk_upsert_updates_existing(vocab):
    vocab.add("a", "old")
    vocab.bulk_upsert({"a": "new", "b": "fresh"}, source="import:test")
    assert vocab.load() == {"a": "new", "b": "fresh"}


def test_bulk_upsert_empty_returns_zero(vocab):
    assert vocab.bulk_upsert({}, source="import:test") == 0


def test_entries_returns_source_and_sorts_by_phrase(vocab):
    vocab.add("zoo", "z", source="manual")
    vocab.bulk_upsert({"alpha": "a"}, source="import:wispr")
    entries = vocab.entries()
    assert [e[0] for e in entries] == ["alpha", "zoo"]
    assert entries[0][2] == "import:wispr"
    assert entries[1][2] == "manual"
