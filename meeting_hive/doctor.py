"""`meeting-hive doctor` — diagnose installation health.

Exits 0 if every check passes, 1 if any check fails. Intended to be run
after install or when the daily sync produces unexpected errors.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from meeting_hive import classifier, migrations, paths, sources, summarizers, vocabs

OK = "✓"
WARN = "⚠"
FAIL = "✗"


@dataclass
class Check:
    name: str
    status: str  # OK | WARN | FAIL
    detail: str


def _check_config() -> tuple[Check, dict | None]:
    cfg_path = paths.config_file()
    if not cfg_path.exists():
        return (
            Check("config.yaml", FAIL, f"not found at {cfg_path} — run `meeting-hive init`"),
            None,
        )
    try:
        cfg = classifier.load_config(cfg_path)
    except classifier.ConfigError as e:
        return Check("config.yaml", FAIL, str(e)), None
    return Check("config.yaml", OK, str(cfg_path)), cfg


def _check_secrets_permissions() -> Check:
    secrets = paths.secrets_file()
    if not secrets.exists():
        return Check("secrets.env", WARN, f"not present at {secrets} (fine if no API key needed)")
    if sys.platform == "win32":
        return Check("secrets.env", OK, f"{secrets} (permissions not enforced on Windows)")
    mode = secrets.stat().st_mode & 0o777
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        return Check(
            "secrets.env",
            WARN,
            f"{secrets} is world/group readable (mode={oct(mode)}) — run `chmod 600`",
        )
    return Check("secrets.env", OK, f"{secrets} (mode={oct(mode)})")


def _check_source(cfg: dict) -> Check:
    src_cfg = cfg.get("source") or {}
    name = src_cfg.get("adapter")
    if not name:
        return Check("source adapter", FAIL, "source.adapter missing in config.yaml")
    try:
        sources.resolve(name, src_cfg.get("config") or {})
    except sources.SourceNotFoundError as e:
        return Check("source adapter", FAIL, str(e))
    except ValueError as e:
        return Check("source adapter", FAIL, f"{name}: {e}")
    except Exception as e:
        return Check("source adapter", FAIL, f"{name}: {e}")
    return Check("source adapter", OK, name)


def _check_vocabulary(cfg: dict) -> Check:
    vcfg = cfg.get("vocabulary") or {}
    name = vcfg.get("adapter")
    if not name:
        return Check(
            "vocabulary adapter", WARN, "vocabulary.adapter missing — will default to sqlite"
        )
    try:
        adapter = vocabs.resolve(name, vcfg.get("config") or {})
    except vocabs.VocabNotFoundError as e:
        return Check("vocabulary adapter", FAIL, str(e))
    except Exception as e:
        return Check("vocabulary adapter", FAIL, f"{name}: {e}")
    try:
        entries = adapter.load()
    except Exception as e:
        return Check("vocabulary adapter", WARN, f"{name}: load() failed: {e}")
    return Check("vocabulary adapter", OK, f"{name} ({len(entries)} entries)")


def _check_summarizer(cfg: dict) -> Check:
    scfg = cfg.get("summarizer") or {}
    name = scfg.get("adapter")
    if not name:
        return Check(
            "summarizer adapter",
            FAIL,
            "summarizer.adapter missing — pick one of: " + ", ".join(summarizers.registered()),
        )
    try:
        summarizers.resolve(name, scfg.get("config") or {})
    except summarizers.SummarizerNotFoundError as e:
        return Check("summarizer adapter", FAIL, str(e))
    except Exception as e:
        return Check("summarizer adapter", FAIL, f"{name}: {e}")

    # API-key presence check (no network call — we don't want doctor to bill).
    env_var = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }.get(name)
    if env_var and not os.environ.get(env_var):
        return Check(
            "summarizer adapter",
            WARN,
            f"{name} configured but {env_var} is not set in the environment",
        )
    return Check("summarizer adapter", OK, name)


def _check_schema_version(cfg: dict) -> Check:
    declared = cfg.get("config_version", 1)
    if not isinstance(declared, int):
        return Check(
            "config schema",
            FAIL,
            f"config_version must be an integer, got {type(declared).__name__}",
        )
    if declared == migrations.CURRENT_VERSION:
        return Check("config schema", OK, f"v{declared}")
    if declared < migrations.CURRENT_VERSION:
        return Check(
            "config schema",
            WARN,
            f"v{declared} (current is v{migrations.CURRENT_VERSION}) "
            "— `meeting-hive sync` will migrate it on the next run",
        )
    return Check(
        "config schema",
        FAIL,
        f"v{declared} is newer than this meeting-hive (v{migrations.CURRENT_VERSION}). "
        "Upgrade the package.",
    )


def _check_archive() -> Check:
    archive = Path.home() / ".meeting-notes"
    if not archive.exists():
        return Check("archive", WARN, f"{archive} does not exist yet (created on first sync)")
    return Check("archive", OK, str(archive))


def run() -> int:
    """Run all checks. Return 0 on success, 1 on any failure."""
    checks: list[Check] = []

    cfg_check, cfg = _check_config()
    checks.append(cfg_check)

    checks.append(_check_secrets_permissions())

    if cfg is not None:
        checks.append(_check_schema_version(cfg))
        checks.append(_check_source(cfg))
        checks.append(_check_vocabulary(cfg))
        checks.append(_check_summarizer(cfg))

    checks.append(_check_archive())

    # Render report.
    for c in checks:
        print(f"  {c.status} {c.name:<22} {c.detail}")

    failed = [c for c in checks if c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]
    print()
    if failed:
        print(f"{FAIL} {len(failed)} check(s) failed, {len(warned)} warning(s).")
        return 1
    if warned:
        print(f"{WARN} {len(warned)} warning(s). meeting-hive should still run.")
        return 0
    print(f"{OK} All checks passed.")
    return 0
