# Contributing to meeting-hive

Thanks for considering a contribution. This project is narrow by design — see
[README.md](README.md) for the framing ("stopgap, meant to retire"). Contributions
that fit the scope are welcome; contributions that expand the scope probably won't land.

## What's in scope

- **New adapters** for source tools (Meetily, Hyprnote, OpenWhispr, Otter, Zoom AI, …)
- **New vocabulary adapters** (Handy, Voxtype, Nerd Dictation, …)
- **Dedicated installers** for Linux (systemd user timer) and Windows (Task Scheduler)
- **Bug fixes** in the pipeline, classifier, writer
- **Docs improvements** — especially concrete examples

## What's out of scope

- Live transcription, recording, or other features that duplicate source tools
- Writing back to source tools (one-way pipeline by design)
- Re-processing previously written files (forward-only by design)
- Anything that doesn't serve "correct proper nouns in multi-language transcripts"

See the "What's NOT in scope" section of the README for the full list.

## Development setup

```bash
git clone https://github.com/plribeiro3000/meeting-hive.git
cd meeting-hive
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

This installs the package in editable mode plus the dev tooling (ruff, mypy, pytest).

## Before opening a PR

```bash
ruff check .                    # lint
ruff format .                   # format
mypy                            # type-check
pytest -v                       # run tests
```

CI runs the same checks on Ubuntu / macOS / Windows × Python 3.11 / 3.12 / 3.13.

### Adding an adapter

See [`docs/writing-adapters.md`](docs/writing-adapters.md) for the step-by-step guide.

An adapter is a single file implementing the relevant Protocol
(`MeetingSource`, `VocabularySource`, or `Summarizer`) plus one line in the
module's `_BUILTINS` registry. No core pipeline changes needed.

Every new adapter should include:

1. The implementation file (e.g., `meeting_hive/sources/yourtool.py`)
2. A test file (e.g., `tests/test_yourtool_source.py`) with at least: happy path,
   missing-backend error, and auth failure
3. A row in the adapter table in `README.md`
4. An entry in `CHANGELOG.md` under `## [Unreleased]` → `### Added`

## Style

- Type hints on every public function.
- Minimal dependencies — stdlib-first, and if a library is needed, prefer
  `requests` / `pyyaml` / `python-dateutil` that are already in use.
- Exception hierarchy: use the existing error classes (`SourceAuthError`,
  `SummarizerUnavailable`, etc.) so the pipeline can react correctly.
- Error messages tell the user what to do next, not just what broke.

## Commit messages

Angular commit convention: `<type>(<scope>): <subject>`.

Examples:

```
feat(sources): add otter adapter
fix(classifier): honor email_rules over domain_rules for exact-email overrides
docs(readme): clarify Windows installation
```

Types: `feat`, `fix`, `docs`, `chore`, `test`, `refactor`, `build`, `ci`.

## Reporting a security issue

**Do not** open a public issue for security vulnerabilities. See
[SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
