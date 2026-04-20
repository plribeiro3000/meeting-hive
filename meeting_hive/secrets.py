"""Load secrets.env KEY=value pairs into ``os.environ`` on CLI startup.

Replaces the `bin/meeting-hive` bash wrapper's ``set -a; source secrets.env``
for users installing meeting-hive via ``pip`` or ``pipx`` — those skip the
wrapper and call the Python entry point directly, so this module restores
the same behavior natively.

File format (dotenv-style, minimal):

- One ``KEY=value`` pair per line.
- Lines starting with ``#`` and blank lines are ignored.
- Outer single or double quotes around the value are stripped.
- Existing environment variables are **not** overridden — the caller's env
  wins over the file, matching how ``set -a; source`` behaved when the var
  was already set externally (e.g., by CI or the user's shell profile).

Security: on Unix-like systems the loader warns if the file is readable by
group or others (mode & 0o077). Windows has no equivalent mode bit check;
the warning is skipped there.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from meeting_hive import paths

log = logging.getLogger(__name__)


def load_secrets(path: Path | None = None) -> int:
    """Populate ``os.environ`` from ``secrets.env``. Returns the count loaded.

    A missing file is not an error (returns 0) — secrets.env is optional for
    adapters that don't need an API key (e.g. ollama).
    """
    path = path or paths.secrets_file()
    if not path.exists():
        return 0

    if sys.platform != "win32":
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            log.warning(
                "%s is readable by group/others (mode=%o); run `chmod 600 %s`",
                path,
                mode,
                path,
            )

    count = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            log.warning("%s: skipping line without '=': %r", path.name, raw)
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if not key:
            continue
        if key in os.environ:
            continue
        os.environ[key] = value
        count += 1

    if count:
        log.debug("Loaded %d secret(s) from %s", count, path)
    return count
