"""Doctor command — runs the check list and reports status."""

from __future__ import annotations

from meeting_hive import doctor, paths


def _write_minimal_config(tmp_path, summarizer="anthropic"):
    cfg_dir = paths.config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "source:\n"
        "  adapter: markdown\n"
        f"  config:\n    path: {tmp_path}\n"
        "vocabulary:\n  adapter: sqlite\n  config: {}\n"
        f"summarizer:\n  adapter: {summarizer}\n  config: {{}}\n"
        "scope: work\n"
        "internal_domains: []\n"
        "title_patterns: []\n"
        "internal_only: {default_subtype: alignment}\n"
        "domain_rules: {}\n"
        "email_rules: {}\n"
    )


def test_fails_when_config_missing(capsys):
    rc = doctor.run()
    assert rc == 1
    out = capsys.readouterr().out
    assert "config.yaml" in out


def test_passes_with_valid_setup(tmp_path, capsys, monkeypatch):
    _write_minimal_config(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stub")
    rc = doctor.run()
    out = capsys.readouterr().out
    assert rc == 0
    assert "source adapter" in out
    assert "vocabulary adapter" in out
    assert "summarizer adapter" in out


def test_warns_when_api_key_missing(tmp_path, capsys, monkeypatch):
    _write_minimal_config(tmp_path, summarizer="openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rc = doctor.run()
    out = capsys.readouterr().out
    # Doctor treats warnings as non-fatal, so rc is still 0.
    assert rc == 0
    assert "OPENAI_API_KEY" in out


def test_fails_when_summarizer_adapter_missing(tmp_path, capsys):
    cfg_dir = paths.config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "source:\n  adapter: markdown\n  config:\n    path: " + str(tmp_path) + "\n"
        "vocabulary:\n  adapter: sqlite\n  config: {}\n"
        "summarizer: {}\n"
        "scope: work\n"
        "internal_domains: []\n"
        "title_patterns: []\n"
        "internal_only: {default_subtype: alignment}\n"
        "domain_rules: {}\n"
        "email_rules: {}\n"
    )
    rc = doctor.run()
    out = capsys.readouterr().out
    assert rc == 1
    assert "summarizer" in out
