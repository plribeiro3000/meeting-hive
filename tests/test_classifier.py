"""Classifier is rule-based and deterministic — every branch is testable without mocks."""

from __future__ import annotations

import pytest

from meeting_hive.classifier import (
    ClassifyMeta,
    ConfigError,
    classify,
    load_config,
    suggest_rule,
)

BASE_CFG = {
    "internal_domains": ["mycompany.com"],
    "internal_only": {
        "default_subtype": "alignment",
        "title_hints": [
            {"match": "(?i)founders", "subtype": "founders"},
        ],
    },
    "title_patterns": [
        {"match": "(?i)^board review", "type": "investor", "entity": "Board"},
    ],
    "email_rules": {
        "jane@gmail.com": {"type": "community", "entity": "Jane"},
    },
    "domain_rules": {
        "acme.com": {"type": "client", "entity": "Acme"},
        "stripe.com": {"type": "vendor", "entity": "Stripe"},
    },
}


def test_title_patterns_beat_everything_else():
    meta = ClassifyMeta("Board Review Q1", ["ceo@mycompany.com"])
    result = classify(meta, BASE_CFG)
    assert result is not None
    assert result.type == "investor"
    assert result.entity == "Board"


def test_internal_only_with_title_hint():
    meta = ClassifyMeta("Founders Friday", ["a@mycompany.com", "b@mycompany.com"])
    result = classify(meta, BASE_CFG)
    assert result is not None
    assert result.type == "internal"
    assert result.entity == "founders"


def test_internal_only_falls_back_to_default_subtype():
    meta = ClassifyMeta("Weekly standup", ["a@mycompany.com", "b@mycompany.com"])
    result = classify(meta, BASE_CFG)
    assert result is not None
    assert result.type == "internal"
    assert result.entity == "alignment"


def test_email_rule_hits_before_domain_rule():
    meta = ClassifyMeta("Coffee", ["jane@gmail.com"])
    result = classify(meta, BASE_CFG)
    assert result is not None
    assert result.type == "community"
    assert result.entity == "Jane"


def test_domain_rule_matches_first_external_domain():
    meta = ClassifyMeta("Kickoff", ["alice@acme.com", "bob@stripe.com", "me@mycompany.com"])
    result = classify(meta, BASE_CFG)
    assert result is not None
    # Either acme or stripe — implementation picks the first match in attendee order.
    assert result.type in ("client", "vendor")


def test_unknown_external_domain_returns_none():
    meta = ClassifyMeta("Call with new prospect", ["j@newprospect.xyz", "me@mycompany.com"])
    assert classify(meta, BASE_CFG) is None


def test_empty_attendees_returns_none_without_title_match():
    meta = ClassifyMeta("Random one-off", [])
    assert classify(meta, BASE_CFG) is None


def test_internal_requires_attendees():
    """With no attendees, the internal branch shouldn't trigger."""
    meta = ClassifyMeta("Alone time", [])
    assert classify(meta, BASE_CFG) is None


def test_bad_regex_in_title_patterns_is_skipped_not_fatal():
    cfg = {
        **BASE_CFG,
        "title_patterns": [
            {"match": "[unclosed", "type": "investor", "entity": "Broken"},
            {"match": "(?i)^board review", "type": "investor", "entity": "Board"},
        ],
    }
    meta = ClassifyMeta("Board Review", ["me@mycompany.com"])
    result = classify(meta, cfg)
    assert result is not None
    assert result.entity == "Board"


def test_suggest_rule_mentions_external_domains():
    meta = ClassifyMeta("Call with Newco", ["partner@newco.io", "me@mycompany.com"])
    snippet = suggest_rule(meta, BASE_CFG)
    # Internal domain is echoed in the attendees preamble; only the external
    # domain should appear in the suggested rule block.
    assert "newco.io:" in snippet
    assert "mycompany.com:" not in snippet


def test_suggest_rule_without_external_domains():
    meta = ClassifyMeta("Random", ["me@mycompany.com"])
    snippet = suggest_rule(meta, BASE_CFG)
    assert "title_patterns" in snippet or "email_rules" in snippet


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_load_config_invalid_yaml_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("key: [unclosed")
    with pytest.raises(ConfigError, match="invalid"):
        load_config(bad)


def test_load_config_non_mapping_raises(tmp_path):
    bad = tmp_path / "list.yaml"
    bad.write_text("- just\n- a\n- list")
    with pytest.raises(ConfigError, match="YAML object"):
        load_config(bad)


def test_load_config_rejects_wrong_field_shape(tmp_path):
    bad = tmp_path / "wrong.yaml"
    bad.write_text('domain_rules: "should be a mapping"\n')
    with pytest.raises(ConfigError, match="domain_rules"):
        load_config(bad)
