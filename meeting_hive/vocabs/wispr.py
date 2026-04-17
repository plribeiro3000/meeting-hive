"""Wispr Flow vocabulary adapter (read-only).

Wispr Flow is a voice-to-text dictation app for macOS and Windows
(https://wisprflow.ai). It maintains a personal vocabulary in a local SQLite
database. This adapter reads that vocabulary as the source of truth for
meeting-hive corrections.

Read-only by design: meeting-hive never writes to Wispr's database — that's
the other tool's data model, edited via the Wispr UI.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_QUERY = """
    SELECT phrase, replacement
    FROM Dictionary
    WHERE isDeleted = 0
      AND replacement IS NOT NULL
      AND replacement != ''
      AND isSnippet = 0
"""


def _default_db_path() -> Path:
    """Where Wispr Flow keeps its SQLite per OS."""
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Roaming" / "Wispr Flow" / "flow.sqlite"
    # macOS.
    return Path.home() / "Library" / "Application Support" / "Wispr Flow" / "flow.sqlite"


class WisprVocabulary:
    """Read `phrase -> replacement` entries from Wispr Flow's SQLite.

    Config keys (all optional):
        db_path: override the SQLite location.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._db_path = Path(cfg.get("db_path") or _default_db_path()).expanduser()

    def load(self) -> dict[str, str]:
        if not self._db_path.exists():
            log.warning(
                "Wispr DB not found at %s; returning empty vocabulary", self._db_path
            )
            return {}

        # Wispr may hold a write lock while running — snapshot to /tmp first.
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            shutil.copyfile(self._db_path, tmp_path)
            for suffix in ("-wal", "-shm"):
                side = self._db_path.with_name(self._db_path.name + suffix)
                if side.exists():
                    shutil.copyfile(side, tmp_path.with_name(tmp_path.name + suffix))

            conn = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True)
            try:
                rows = conn.execute(_QUERY).fetchall()
            finally:
                conn.close()

            vocab = {phrase: replacement for phrase, replacement in rows}
            log.info("Loaded %d Wispr vocabulary entries", len(vocab))
            return vocab
        finally:
            for suffix in ("", "-wal", "-shm"):
                candidate = (
                    tmp_path.with_name(tmp_path.name + suffix) if suffix else tmp_path
                )
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    vocab = WisprVocabulary().load()
    for phrase, replacement in sorted(vocab.items()):
        print(f"  {phrase!r:40s} -> {replacement!r}")
    print(f"\nTotal: {len(vocab)} entries")
