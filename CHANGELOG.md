# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.4] - 2026-04-20

### Fixed

- Scheduled sync on macOS

## [1.1.3] - 2026-04-20

### Fixed

- Anthropic summarizer

## [1.1.2] - 2026-04-20

### Fixed

- Anthropic summarizer

## [1.1.1] - 2026-04-20

### Fixed

- Autocommit availability

## [1.1.0] - 2026-04-20

### Added

- Local archive history

## [1.0.1] - 2026-04-19

### Fixed

- Secret loading

## [1.0.0] - 2026-04-19

### Added

- Nightly sync pipeline from a meeting source into a local markdown archive
- Adapter architecture on three axes — `source`, `vocabulary`, and `summarizer`
- Source adapters: `granola`, `fathom`, `markdown`
- Vocabulary adapters: `wispr` (read-only), `sqlite` (mutable)
- Summarizer adapters: `anthropic`, `openai`, `ollama` (no default — installer picks)
- `meeting-hive init` CLI — generates `config.yaml` at the standard path
- `meeting-hive vocab` CLI — `list`, `add`, `remove`, `clear`, `import`, `export`
- `meeting-hive doctor` CLI — diagnose installation health
- Config schema versioning (`config_version`) and migration runner — `meeting-hive sync` upgrades stale config files automatically, leaving a backup beside the original
- `meeting-hive --version` flag
- Classification engine with `domain_rules`, `title_patterns`, `internal_only`, `email_rules`
- Cross-platform desktop notifications (macOS / Linux / Windows)
- Cross-platform paths (XDG on Unix-like, `%APPDATA%` / `%LOCALAPPDATA%` on Windows)
- macOS installer and uninstaller under `scripts/macos/`
- Scheduling recipes for Linux (systemd / cron) and Windows (Task Scheduler) in `docs/scheduling.md`
- Adapter authoring guide (`docs/writing-adapters.md`)
- Test suite covering classifier, writer, corrector, sync, adapters, registries, paths, doctor
- CI matrix — Ubuntu / macOS / Windows × Python 3.11 / 3.12 / 3.13
- Community health files — `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue / PR templates, Dependabot config
- Developer tooling — `ruff`, `mypy`, `pytest`, `pre-commit`, `.editorconfig`
- Security tooling — ruff `S` (flake8-bandit), `pip-audit` in CI, CodeQL workflow, `gitleaks` pre-commit hook
- PEP 561 `py.typed` marker
