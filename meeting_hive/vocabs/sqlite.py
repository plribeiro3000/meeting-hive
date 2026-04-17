"""Local SQLite vocabulary adapter (mutable).

For users who don't have (or don't want to use) an external dictation tool with
a vocabulary feature — meeting-hive manages the database itself. Cross-platform
(stdlib `sqlite3`), no external dependencies.

Managed via the `meeting-hive vocab` CLI subcommands (add / remove / list /
import / export) or by editing `phrase` rows directly if needed.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from meeting_hive import paths

log = logging.getLogger(__name__)

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS vocabulary (
        phrase      TEXT PRIMARY KEY,
        replacement TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        source      TEXT                       -- 'manual' | 'import:<name>' | ...
    );
    CREATE INDEX IF NOT EXISTS idx_vocab_updated ON vocabulary(updated_at);
"""


class SqliteVocabulary:
    """`phrase -> replacement` entries stored in a local SQLite.

    Config keys (all optional):
        db_path: override the database location. Defaults to a cross-platform
                 data dir (XDG on Unix, %LOCALAPPDATA% on Windows).
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self._db_path = Path(cfg.get("db_path") or paths.vocabulary_db()).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # VocabularySource -------------------------------------------------------

    def load(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT phrase, replacement FROM vocabulary").fetchall()
        vocab = {row["phrase"]: row["replacement"] for row in rows}
        log.info("Loaded %d SQLite vocabulary entries from %s", len(vocab), self._db_path)
        return vocab

    # MutableVocabularySource -----------------------------------------------

    def add(self, phrase: str, replacement: str, *, source: str = "manual") -> None:
        if not phrase or not replacement:
            raise ValueError("phrase and replacement must both be non-empty")
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vocabulary (phrase, replacement, created_at, updated_at, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(phrase) DO UPDATE SET
                    replacement = excluded.replacement,
                    updated_at  = excluded.updated_at,
                    source      = excluded.source
                """,
                (phrase, replacement, now, now, source),
            )

    def remove(self, phrase: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM vocabulary WHERE phrase = ?", (phrase,))
            return cur.rowcount > 0

    def clear(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM vocabulary")
            return cur.rowcount

    # Convenience for CLI ---------------------------------------------------

    def entries(self) -> list[tuple[str, str, str]]:
        """Return `(phrase, replacement, source)` tuples sorted by phrase."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT phrase, replacement, COALESCE(source, '') AS source "
                "FROM vocabulary ORDER BY phrase"
            ).fetchall()
        return [(r["phrase"], r["replacement"], r["source"]) for r in rows]

    def bulk_upsert(self, pairs: dict[str, str], *, source: str) -> int:
        """Upsert many phrase→replacement pairs. Return the number touched."""
        if not pairs:
            return 0
        now = _now_iso()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO vocabulary (phrase, replacement, created_at, updated_at, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(phrase) DO UPDATE SET
                    replacement = excluded.replacement,
                    updated_at  = excluded.updated_at,
                    source      = excluded.source
                """,
                [(p, r, now, now, source) for p, r in pairs.items()],
            )
        return len(pairs)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    v = SqliteVocabulary()
    print(f"DB: {v._db_path}")
    print(f"Entries: {len(v.load())}")
