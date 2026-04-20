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

## Releasing (maintainers)

The project ships to PyPI via [Trusted Publishing][tp] — no API tokens, no
secrets stored in GitHub. The workflow is triggered by pushing a
`v<version>` tag.

To cut a release:

1. Bump `__version__` in `meeting_hive/__init__.py`.
2. Move `## [Unreleased]` content to `## [X.Y.Z] - YYYY-MM-DD` in `CHANGELOG.md`.
3. Commit with message `chore: release vX.Y.Z`.
4. Tag: `git tag -a vX.Y.Z -m "vX.Y.Z"` (the workflow verifies the tag
   matches the package version and refuses otherwise).
5. Push: `git push origin main vX.Y.Z`.

The `release.yml` workflow builds a wheel + sdist, publishes to PyPI, and
creates a GitHub Release with the artifacts.

### First-time PyPI setup

Before the very first release, configure a pending publisher on PyPI:

1. Log in at https://pypi.org.
2. Go to *Your projects* → *Publishing* → *Add a new pending publisher*.
3. Fill in:
   - PyPI project name: `meeting-hive`
   - Owner: `plribeiro3000`
   - Repository: `meeting-hive`
   - Workflow name: `release.yml`
   - Environment: `pypi`
4. Save.

Then create the `pypi` environment on GitHub:
**Settings → Environments → New environment → `pypi`** (protection rules
optional).

After the first successful publish, the pending publisher becomes a real
publisher — no further setup needed.

[tp]: https://docs.pypi.org/trusted-publishers/

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
