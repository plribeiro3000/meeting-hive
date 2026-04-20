"""secrets.env loader — dotenv-style KEY=value into os.environ."""

from __future__ import annotations

import os
import sys

import pytest

from meeting_hive import secrets


@pytest.fixture
def env(monkeypatch):
    """Clean slate for the env vars this suite touches."""
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "CUSTOM_VAR",
        "QUOTED_VAR",
        "FATHOM_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_missing_file_is_not_an_error(tmp_path, env):
    n = secrets.load_secrets(tmp_path / "absent.env")
    assert n == 0


def test_loads_simple_pairs(tmp_path, env):
    path = tmp_path / "secrets.env"
    path.write_text("ANTHROPIC_API_KEY=sk-xxx\nFATHOM_API_KEY=ft-yyy\n")
    n = secrets.load_secrets(path)
    assert n == 2
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-xxx"
    assert os.environ["FATHOM_API_KEY"] == "ft-yyy"


def test_strips_surrounding_quotes(tmp_path, env):
    path = tmp_path / "secrets.env"
    path.write_text("QUOTED_VAR=\"double\"\nOPENAI_API_KEY='single'\n")
    secrets.load_secrets(path)
    assert os.environ["QUOTED_VAR"] == "double"
    assert os.environ["OPENAI_API_KEY"] == "single"


def test_skips_comments_and_blank_lines(tmp_path, env):
    path = tmp_path / "secrets.env"
    path.write_text(
        "# top comment\n\nANTHROPIC_API_KEY=abc\n   # indented comment\n\nOPENAI_API_KEY=def\n"
    )
    n = secrets.load_secrets(path)
    assert n == 2


def test_existing_env_wins_over_file(tmp_path, env):
    """If the var is already set (shell, CI, launchd EnvironmentVariables),
    the file must not overwrite it."""
    env.setenv("ANTHROPIC_API_KEY", "from-env")
    path = tmp_path / "secrets.env"
    path.write_text("ANTHROPIC_API_KEY=from-file\n")
    n = secrets.load_secrets(path)
    assert n == 0
    assert os.environ["ANTHROPIC_API_KEY"] == "from-env"


def test_malformed_line_is_skipped_not_fatal(tmp_path, env, caplog):
    path = tmp_path / "secrets.env"
    path.write_text("no equals here\nANTHROPIC_API_KEY=ok\n")
    n = secrets.load_secrets(path)
    assert n == 1
    assert os.environ["ANTHROPIC_API_KEY"] == "ok"


def test_empty_key_is_ignored(tmp_path, env):
    path = tmp_path / "secrets.env"
    path.write_text("=orphan\n")
    n = secrets.load_secrets(path)
    assert n == 0


def test_default_path_is_used_when_none(tmp_path, env, monkeypatch):
    """Without an explicit path, the loader uses paths.secrets_file()."""
    from meeting_hive import paths

    fake = tmp_path / "myconfig" / "meeting-hive" / "secrets.env"
    fake.parent.mkdir(parents=True)
    fake.write_text("CUSTOM_VAR=hello\n")
    monkeypatch.setattr(paths, "secrets_file", lambda: fake)
    n = secrets.load_secrets()
    assert n == 1
    assert os.environ["CUSTOM_VAR"] == "hello"


@pytest.mark.skipif(sys.platform == "win32", reason="mode bits only checked on Unix")
def test_warns_on_world_readable_file(tmp_path, env, caplog):
    import logging

    path = tmp_path / "secrets.env"
    path.write_text("ANTHROPIC_API_KEY=abc\n")
    path.chmod(0o644)
    with caplog.at_level(logging.WARNING):
        secrets.load_secrets(path)
    assert any("chmod 600" in rec.message for rec in caplog.records)


@pytest.mark.skipif(sys.platform == "win32", reason="mode bits only checked on Unix")
def test_quiet_on_600_mode(tmp_path, env, caplog):
    import logging

    path = tmp_path / "secrets.env"
    path.write_text("ANTHROPIC_API_KEY=abc\n")
    path.chmod(0o600)
    with caplog.at_level(logging.WARNING):
        secrets.load_secrets(path)
    assert not any("chmod" in rec.message for rec in caplog.records)
