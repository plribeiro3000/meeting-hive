# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> Narrow-scope project: corrects proper nouns in multi-language meeting transcripts using a user-maintained vocabulary. Intended to retire once source tools ship multi-language + custom-vocabulary together. See [README](README.md) for the full framing.

### Added

- Initial release: nightly sync pipeline from a meeting source into a local markdown archive
- Adapter architecture on three axes — `source` (where meetings come from), `vocabulary` (how to spell things), and `summarizer` (which AI regenerates)
- Source adapters: `granola` (local cache + REST API), `fathom` (Fathom public REST API), `markdown` (generic directory of YAML-frontmatter files)
- Vocabulary adapters: `wispr` (read-only, Wispr Flow SQLite), `sqlite` (mutable, local DB managed by meeting-hive)
- Summarizer adapters: `anthropic` (Claude family), `openai` (GPT / o-series), `ollama` (local LLM). No default — installer requires an explicit choice
- `meeting-hive init` CLI: generates `config.yaml` at the standard path (per-OS XDG/AppData), with flags for non-interactive use and prompts for interactive use. Replaces the `config.example.yaml` copy-and-edit pattern.
- `meeting-hive vocab` CLI: `list`, `add`, `remove`, `clear`, `import`, `export`
- Classification engine with `domain_rules`, `title_patterns`, `internal_only`, `email_rules`; UNCLASSIFIED meetings log a copy-paste YAML snippet and are skipped until a rule is added
- Cross-platform desktop notifications (`osascript` on macOS, `notify-send` on Linux, PowerShell toast on Windows)
- Cross-platform paths (XDG on Unix-like, `%APPDATA%` / `%LOCALAPPDATA%` on Windows)
- macOS installer (`scripts/install.sh`) — launchd scheduling (Mon-Fri midnight local time by default, configurable via `--hour`/`--minute`/`--days`), plus full-flag unattended mode for AI-agent / CI setup
- macOS uninstaller (`scripts/uninstall.sh`) — reverses the installer; optional `--purge` for config/data/logs and `--nuke-notes` (with explicit confirmation) for the archive itself
- Scheduling recipes for Linux (systemd user timer, cron) and Windows (Task Scheduler) in `docs/scheduling.md`
