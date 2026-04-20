"""Vocabulary corrector — case-sensitive, whole-word, longest-phrase-first."""

from __future__ import annotations

from meeting_hive.corrector import apply_vocabulary


def test_empty_inputs_are_noops():
    assert apply_vocabulary("", {}).text == ""
    assert apply_vocabulary("hello", {}).text == "hello"
    assert apply_vocabulary("", {"x": "y"}).text == ""


def test_single_phrase_replacement():
    result = apply_vocabulary("Post Grass is great", {"Post Grass": "Postgres"})
    assert result.text == "Postgres is great"
    assert result.replacements == {"Post Grass": 1}


def test_longer_phrase_wins_over_shorter_prefix():
    """`Super Base Enterprise` must match before `Super Base` consumes the prefix."""
    vocab = {
        "Super Base": "Supabase",
        "Super Base Enterprise": "Supabase Enterprise",
    }
    result = apply_vocabulary("Super Base Enterprise handles auth", vocab)
    assert result.text == "Supabase Enterprise handles auth"
    assert result.replacements.get("Super Base Enterprise") == 1
    assert "Super Base" not in result.replacements


def test_word_boundary_prevents_substring_match():
    # "Grass" should not be touched inside "Grasshopper".
    result = apply_vocabulary("Grasshopper", {"Grass": "Wheat"})
    assert result.text == "Grasshopper"


def test_case_sensitive():
    result = apply_vocabulary("post grass and Post Grass", {"Post Grass": "Postgres"})
    assert result.text == "post grass and Postgres"


def test_multiple_occurrences_counted():
    result = apply_vocabulary("Post Grass, Post Grass, Post Grass", {"Post Grass": "Postgres"})
    assert result.text == "Postgres, Postgres, Postgres"
    assert result.replacements["Post Grass"] == 3


def test_phrase_with_punctuation_falls_back_to_literal():
    # Phrase starts with non-word char → no word-boundary wrapper.
    result = apply_vocabulary("hello @foo world", {"@foo": "@bar"})
    assert result.text == "hello @bar world"
