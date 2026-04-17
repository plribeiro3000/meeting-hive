"""Cross-platform path helpers (XDG on Unix-like; %APPDATA% on Windows)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "meeting-hive"


def _env_or(env_var: str, default: Path) -> Path:
    val = os.environ.get(env_var)
    return Path(val).expanduser() if val else default


def config_dir() -> Path:
    """Where user-editable config lives (e.g. config.yaml, secrets.env)."""
    if sys.platform == "win32":
        base = _env_or("APPDATA", Path.home() / "AppData" / "Roaming")
        return base / APP_NAME
    return _env_or("XDG_CONFIG_HOME", Path.home() / ".config") / APP_NAME


def data_dir() -> Path:
    """Where persistent app data lives (e.g. vocabulary.db)."""
    if sys.platform == "win32":
        base = _env_or("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return base / APP_NAME
    return _env_or("XDG_DATA_HOME", Path.home() / ".local" / "share") / APP_NAME


def state_dir() -> Path:
    """Where logs and transient state live."""
    if sys.platform == "win32":
        base = _env_or("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return base / APP_NAME / "state"
    return _env_or("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_NAME


def log_file() -> Path:
    return state_dir() / f"{APP_NAME}.log"


def config_file() -> Path:
    return config_dir() / "config.yaml"


def secrets_file() -> Path:
    return config_dir() / "secrets.env"


def vocabulary_db() -> Path:
    return data_dir() / "vocabulary.db"
