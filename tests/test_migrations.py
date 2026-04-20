"""Config migration runner — version negotiation, backup, error modes."""

from __future__ import annotations

import pytest
import yaml

from meeting_hive import migrations


def _write_config(path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def test_no_op_when_already_current(tmp_path):
    path = tmp_path / "config.yaml"
    data = {"config_version": migrations.CURRENT_VERSION, "scope": "work"}
    _write_config(path, data)

    result, modified = migrations.migrate(data, path)

    assert modified is False
    assert result is data
    # No backup file created.
    assert not any(p.name.endswith(".bak-v1") for p in tmp_path.iterdir())


def test_unversioned_config_is_treated_as_v1(tmp_path):
    """Configs written before versioning existed have no `config_version`
    key. They should be read as v1 without erroring."""
    path = tmp_path / "config.yaml"
    data = {"scope": "work"}  # no config_version
    _write_config(path, data)

    # At CURRENT_VERSION=1, treating unversioned as v1 means no-op.
    result, modified = migrations.migrate(data, path)
    assert modified is False
    assert result == data


def test_newer_config_raises(tmp_path):
    """If config declares a version newer than this meeting-hive supports,
    migration refuses to proceed (forward-incompatible — user must upgrade)."""
    path = tmp_path / "config.yaml"
    data = {"config_version": migrations.CURRENT_VERSION + 99}
    _write_config(path, data)

    with pytest.raises(migrations.MigrationError, match="newer"):
        migrations.migrate(data, path)


def test_bad_version_type_raises(tmp_path):
    path = tmp_path / "config.yaml"
    data = {"config_version": "one"}
    _write_config(path, data)

    with pytest.raises(migrations.MigrationError, match="integer"):
        migrations.migrate(data, path)


def test_migration_chain_runs_in_order(tmp_path, monkeypatch):
    """Synthetic migrations v1 -> v2 -> v3 all run on a v1 input."""
    path = tmp_path / "config.yaml"
    data = {"config_version": 1, "old_key": "value"}
    _write_config(path, data)

    def upgrade_1_to_2(cfg: dict) -> dict:
        cfg["added_in_v2"] = True
        return cfg

    def upgrade_2_to_3(cfg: dict) -> dict:
        cfg["renamed"] = cfg.pop("old_key")
        return cfg

    monkeypatch.setattr(migrations, "CURRENT_VERSION", 3)
    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        [(1, 2, upgrade_1_to_2), (2, 3, upgrade_2_to_3)],
    )

    result, modified = migrations.migrate(data, path)
    assert modified is True
    assert result["config_version"] == 3
    assert result["added_in_v2"] is True
    assert result["renamed"] == "value"
    assert "old_key" not in result

    # File is rewritten with the new shape.
    on_disk = yaml.safe_load(path.read_text())
    assert on_disk["config_version"] == 3
    assert on_disk["renamed"] == "value"

    # Backup of the v1 file is left alongside.
    backup = path.with_name(path.name + ".bak-v1")
    assert backup.exists()
    pre_migration = yaml.safe_load(backup.read_text())
    assert pre_migration == {"config_version": 1, "old_key": "value"}


def test_non_contiguous_chain_raises(tmp_path, monkeypatch):
    """If a migration for the current version is missing, the runner should
    refuse rather than silently skip."""
    path = tmp_path / "config.yaml"
    data = {"config_version": 1}
    _write_config(path, data)

    def upgrade_2_to_3(cfg: dict) -> dict:
        return cfg

    monkeypatch.setattr(migrations, "CURRENT_VERSION", 3)
    monkeypatch.setattr(migrations, "MIGRATIONS", [(2, 3, upgrade_2_to_3)])

    with pytest.raises(migrations.MigrationError, match="missing step"):
        migrations.migrate(data, path)


def test_init_writes_current_config_version(tmp_path, monkeypatch, capsys):
    """End-to-end: `meeting-hive init --summarizer ollama` emits a config
    with the current schema version at the top."""
    from meeting_hive import __main__ as cli
    from meeting_hive import paths

    # Force the config path to land under tmp (conftest patches XDG already,
    # but re-pointing here to be explicit).
    monkeypatch.setattr(paths, "config_file", lambda: tmp_path / "config.yaml")

    parser = cli._build_parser()
    args = parser.parse_args(
        [
            "init",
            "--summarizer",
            "ollama",
            "--source",
            "granola",
            "--vocabulary",
            "sqlite",
            "--scope",
            "work",
            "--internal-domains",
            "",
        ]
    )
    # non-interactive mode because stdin isn't a TTY in tests
    rc = cli._cmd_init(args)
    assert rc == 0

    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert cfg["config_version"] == migrations.CURRENT_VERSION
