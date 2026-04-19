"""Cross-platform path resolution — XDG on Unix, APPDATA/LOCALAPPDATA on Windows."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from meeting_hive import paths


def test_config_dir_uses_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgconf"))
    if sys.platform == "win32":
        pytest.skip("XDG not honored on Windows")
    assert paths.config_dir() == tmp_path / "xdgconf" / "meeting-hive"


def test_data_dir_uses_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdgdata"))
    if sys.platform == "win32":
        pytest.skip("XDG not honored on Windows")
    assert paths.data_dir() == tmp_path / "xdgdata" / "meeting-hive"


def test_state_dir_uses_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdgstate"))
    if sys.platform == "win32":
        pytest.skip("XDG not honored on Windows")
    assert paths.state_dir() == tmp_path / "xdgstate" / "meeting-hive"


def test_log_file_is_inside_state_dir():
    assert paths.log_file().parent == paths.state_dir()
    assert paths.log_file().name == "meeting-hive.log"


def test_config_file_is_inside_config_dir():
    assert paths.config_file().parent == paths.config_dir()
    assert paths.config_file().name == "config.yaml"


def test_vocabulary_db_is_inside_data_dir():
    assert paths.vocabulary_db().parent == paths.data_dir()
    assert paths.vocabulary_db().name == "vocabulary.db"


def test_paths_resolve_even_without_env_vars(monkeypatch, tmp_path):
    """If XDG_* is unset, falls back to ~/.config etc."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    # HOME is frozen by conftest to tmp_path/home.
    if sys.platform == "win32":
        pytest.skip("Windows branch uses APPDATA/LOCALAPPDATA")
    assert paths.config_dir() == Path.home() / ".config" / "meeting-hive"
    assert paths.data_dir() == Path.home() / ".local" / "share" / "meeting-hive"
    assert paths.state_dir() == Path.home() / ".local" / "state" / "meeting-hive"
