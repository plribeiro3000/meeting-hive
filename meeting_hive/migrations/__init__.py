"""Config schema migrations.

Every `config.yaml` carries a `config_version` key (integer, starts at 1).
On startup, `meeting-hive sync` calls `migrate()` to bring the file up to
the current schema, writing a backup of the previous state beside it.

Why we key migrations off the *config* version rather than the *package*
version: a user can install meeting-hive v0.5 on top of a config last
touched by v0.1 — we don't know when they last ran it. The config version
tells us what schema we're reading, independent of the installer or
package distribution channel (git / pipx / PyPI / etc.).

Writing a new migration:

1. Add a function ``def upgrade_N_to_M(cfg: dict) -> dict:`` below —
   mutate and return the config dict. Keep it pure; do not touch the
   filesystem.
2. Append ``(N, M, upgrade_N_to_M)`` to ``MIGRATIONS``, sorted by
   ``from_version``.
3. Bump ``CURRENT_VERSION`` to ``M``.
4. Add tests in ``tests/test_migrations.py`` — at minimum: the upgrade
   transforms a known v_N input into the expected v_M output.
5. Document the change in ``CHANGELOG.md`` under ``### Changed`` with the
   user-visible effect (renamed key, new required field, etc.).
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


CURRENT_VERSION = 1


class MigrationError(RuntimeError):
    """Raised when a config can't be migrated — e.g. it declares a newer
    schema than this meeting-hive knows how to handle."""


# (from_version, to_version, upgrade_fn) tuples. Sorted by from_version.
# Empty today because we're at v1 — the first migration lands here when
# the schema first changes.
MIGRATIONS: list[tuple[int, int, Callable[[dict], dict]]] = []


def migrate(config: dict, config_path: Path) -> tuple[dict, bool]:
    """Bring `config` up to CURRENT_VERSION and persist the result.

    Returns ``(migrated_config, was_modified)``. When modified, a backup of
    the pre-migration file is left at ``<config_path>.bak-v<N>`` where N is
    the version before the migration ran.

    An unversioned config (no `config_version` key) is treated as v1 — that
    was the shape of the initial release, before versioning existed.
    """
    current = _read_version(config)

    if current == CURRENT_VERSION:
        return config, False

    if current > CURRENT_VERSION:
        raise MigrationError(
            f"config at {config_path} declares config_version={current}, "
            f"but this meeting-hive only knows up to v{CURRENT_VERSION}. "
            "Upgrade meeting-hive, or downgrade the file manually."
        )

    backup = config_path.with_name(f"{config_path.name}.bak-v{current}")
    shutil.copyfile(config_path, backup)
    log.info("Backed up %s -> %s before migration", config_path, backup)

    for from_v, to_v, fn in MIGRATIONS:
        if from_v < current:
            continue
        if from_v != current:
            # Non-contiguous — shouldn't happen if MIGRATIONS is written correctly.
            raise MigrationError(
                f"no migration path from v{current} to v{CURRENT_VERSION} "
                f"(missing step for v{current})"
            )
        log.info("Migrating config v%d -> v%d", from_v, to_v)
        config = fn(config)
        config["config_version"] = to_v
        current = to_v

    if current != CURRENT_VERSION:
        raise MigrationError(f"migration chain ended at v{current}, expected v{CURRENT_VERSION}")

    _write_config(config, config_path)
    log.info("Config migrated to v%d", CURRENT_VERSION)
    return config, True


def _read_version(config: dict) -> int:
    """Read config_version with a safe default for pre-versioning configs."""
    value = config.get("config_version", 1)
    if not isinstance(value, int):
        raise MigrationError(
            f"config_version must be an integer, got {type(value).__name__}: {value!r}"
        )
    return value


def _write_config(config: dict, path: Path) -> None:
    """Write config back to disk.

    Comments in the original file are lost — the previous content is
    preserved in the backup written by ``migrate()``. Callers who want
    comment-preserving round-trips should switch to ruamel.yaml upstream.
    """
    path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
