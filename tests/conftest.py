"""Shared pytest fixtures.

Every test gets an isolated `tmp_path`-based config/data/state dir so the
test suite never touches the user's real meeting-hive installation.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    """Redirect XDG + Windows env vars at module-import time.

    `meeting_hive.paths` reads these each call (no caching), so patching at
    the start of each test is sufficient.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    # Keep HOME off the real one for tests that poke at Path.home().
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def fake_home(tmp_path):
    """Path.home() is frozen to this path by the autouse fixture above."""
    return tmp_path / "home"
