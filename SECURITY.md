# Security Policy

## Supported versions

meeting-hive is pre-1.0 and only the latest release is supported. Security
fixes are merged into `main` and released as a new patch version.

| Version | Supported |
|---------|-----------|
| latest `0.x` | yes |
| older `0.x` | no |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email the maintainer at **plribeiro3000@gmail.com** with:

- A description of the issue
- Steps to reproduce (ideally a minimal proof of concept)
- The affected version (`meeting-hive --version`)
- Any mitigations you've identified

You should get an acknowledgement within **3 business days**. Expect a fix
or triage decision within **14 days** for confirmed issues.

If the report is accepted, you will be credited in the release notes (unless
you prefer to remain anonymous).

## Scope

meeting-hive stores API keys in `secrets.env` (chmod 600) and a local SQLite
vocabulary database. Relevant threat surfaces:

- **Credential exposure** in `secrets.env` — if you suspect exposure, rotate
  the affected key at the provider immediately
- **Path handling** in source adapters reading user-supplied directories
- **YAML/JSON parsing** of local cache files (Granola, Wispr Flow)
- **Shell invocations** in `scripts/install.sh` and `notify.py`

## Out of scope

- Issues in third-party backends (Anthropic API, OpenAI API, Granola, Fathom,
  Wispr Flow, Ollama) — report those upstream
- Issues requiring physical access to the user's machine
- Social engineering the user into pasting malicious config

## Defensive posture

- API keys read via `read -s` (never echoed)
- `secrets.env` written with `chmod 600`, config dir with `chmod 700`
- Subprocess calls use list-form args, never `shell=True`
- User regex from `config.yaml` is treated as trusted (config is user-owned);
  a malformed pattern is logged and skipped, not crashed on
