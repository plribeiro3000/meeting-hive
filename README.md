# meeting-hive

[![CI](https://github.com/plribeiro3000/meeting-hive/actions/workflows/ci.yml/badge.svg)](https://github.com/plribeiro3000/meeting-hive/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**A local-first pipeline for correcting speech-to-text errors in meeting transcripts, using a vocabulary you maintain.**

Each meeting becomes a normalized pair of markdown files on your disk. Any tool with filesystem access — macOS Spotlight, `grep`, Obsidian, or whatever AI assistant you happen to use — can search, cross-reference, and reason across the whole hive.

Runs on macOS, Linux, and Windows via an adapter architecture: you pick which meeting tool feeds the pipeline and which vocabulary source corrects its transcripts. Swap either independently. Add new adapters without touching the core.

**Platform support:** macOS is first-class (dedicated installer under `scripts/macos/`). Linux and Windows are documented with manual setup recipes — see [`docs/scheduling.md`](docs/scheduling.md). Dedicated installers for both are tracked as [good first issues](https://github.com/plribeiro3000/meeting-hive/issues).

---

## Why this exists

This is a stopgap. A reasonably well-built one, but still a stopgap.

Meeting-recording and speech-to-text tools have come a long way: live transcription, AI summaries, cross-meeting search, MCP integrations with Claude / ChatGPT / Cursor. For most people, the tool they already use does the whole job.

The specific gap this project addresses: **proper-noun accuracy in multi-language meetings**.

Speech-to-text engines handle proper nouns poorly by default. Company names, product names, tech jargon, people's names rarely sit in training data, and accent variation makes it worse. The common fix across tools is a **custom vocabulary** feature: you tell the engine "when you hear 'Post Grass', write 'Postgres'". Where it breaks, consistently across the market:

- **Tools with custom vocabulary, but only when pinned to one language.** [Granola's Internal Jargon feature is disabled when Multi-language mode is on](https://help.granola.ai/article/multi-language). [Otter.ai can only transcribe one language at a time](https://help.otter.ai/hc/en-us/articles/360047247414-Supported-languages) (French+English is the only simultaneous pair), so the vocabulary effectively lives in a single language.
- **Tools without any custom vocabulary feature.** [Fathom doesn't offer one](https://tldv.io/blog/fireflies-vs-fathom/). You're stuck with whatever the STT produces.
- **Transcripts are read-only after the fact.** Even when the error is right there on screen, the source tool won't let you fix it.

If your meetings mix languages (technical calls across Portuguese / English / Spanish, for example — with teams spread across different accents), none of those paths gives you a vocabulary that actually applies to your day-to-day. Same ~50 terms — company names, tools, platforms — coming out wrong, consistently, meeting after meeting. Waiting for vendors to resolve the trade-off is possible but open-ended.

`meeting-hive` is the workaround: pull meetings onto disk, apply a vocabulary you maintain (language-agnostic, because it lives outside the source tool), re-summarize against the corrected text, and leave plain markdown any tool can read.

**This is not a replacement for your meeting tool.** Source tools own recording, live transcription, live summarization, cross-meeting search, MCP integrations — things this project doesn't do and shouldn't try. `meeting-hive` addresses one narrow gap and nothing more.

**The goal is for this project to retire.** When source tools ship multi-language mode *with* user-editable custom vocabulary, this becomes redundant and should die. It's open source on the off-chance someone else has the same specific pain. It's not trying to grow.

## A side benefit: the archive self-organizes

Once meetings are on disk, `meeting-hive` also tags each one with a category (`client: Acme`, `vendor: Stripe`, `internal: founders`, …) drawn from rules you maintain in `config.yaml`.

The classifier doesn't guess. If no rule matches a meeting, the meeting **isn't written** — it's surfaced in the daily notification with a copy-paste YAML snippet suggesting where to add the rule (by domain, title pattern, or specific email). You decide the canonical name and category; the next run picks up the meeting. A 7-day lookback guarantees nothing is lost, only deferred.

The rule list grows incrementally as you work:

- **Zero placeholders.** The archive never fills up with `UNKNOWN` / `TBD` entries that nobody ever goes back to fix.
- **No silent misclassification.** Either a human-defined rule matched, or nothing got written. Always auditable.
- **A living map of your professional graph.** Over weeks, `config.yaml` becomes an accurate directory of the clients, vendors, teams, and recurring meetings you actually deal with. Any other tool or script can read that same file for its own purposes.

This falls out of the architecture regardless of whether the vocabulary problem gets solved upstream — so if meeting-hive ever does retire, the classification scheme is portable to whatever replaces it.

## The name

The name borrows from the beehive metaphor, because each piece maps cleanly to what the pipeline does:

- **A cell** — one meeting. Paired markdown files (transcript + summary, both with frontmatter) stored on disk.
- **The hive** — your whole archive. All cells organized by scope and year, readable as plain text.
- **The bees** — whatever works the hive. Spotlight, `grep`, Obsidian, any AI agent with filesystem access — they forage across cells to extract patterns, find prior decisions, surface context you didn't know to ask for.
- **The flower** — the source tool that produces the raw meeting. It's where the nectar (audio + speech-to-text) is generated. The bees never visit the flower directly; they only work the hive.

`meeting-hive` is the step between the flower and the hive: harvest the meeting from the flower, clean up the data with the vocabulary, store the cell. That's the whole job.

## How it works

The pipeline has three adapter axes:

```
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ Source adapter   │   │ Vocabulary       │   │ Summarizer       │
│ (where meetings  │   │ adapter          │   │ adapter          │
│  come from)      │   │ (how to spell    │   │ (which AI        │
└────────┬─────────┘   │  things)         │   │  regenerates)    │
         │             └────────┬─────────┘   └────────┬─────────┘
         │                      │                      │
         ▼                      ▼                      ▼
    ┌──────────────────── meeting-hive ────────────────────┐
    │  classify → correct transcript → re-summarize →       │
    │  write paired markdown                                 │
    └────────────────────────────┬─────────────────────────┘
                                 │
                                 ▼
                   ~/.meeting-notes/<scope>/<year>/
                      YYYY-MM-DD-slug-summary.md
                      YYYY-MM-DD-slug-transcript.md
                                 │
                                 ▼
                   Any tool with filesystem access
                   (Spotlight, grep, Obsidian, any AI, etc.)
```

Built-in adapters:

| Axis | Adapter | Notes |
|---|---|---|
| **Source** | `granola` | [Granola](https://granola.ai) local cache + REST fallback. macOS today; Windows when Granola ships a Windows client. |
| **Source** | `fathom` | [Fathom](https://fathom.ai) via its [public REST API](https://developers.fathom.ai/). Cross-platform. Requires `FATHOM_API_KEY`. |
| **Source** | `markdown` | Generic — reads meetings from a directory of YAML-frontmatter `.md` files. Any tool that exports markdown. Cross-platform. |
| **Vocabulary** | `wispr` | Read-only wrapper over the [Wispr Flow](https://wisprflow.ai) dictation dictionary (macOS / Windows). Use if you already maintain a vocab there. |
| **Vocabulary** | `sqlite` | Local SQLite DB managed by meeting-hive. Cross-platform, mutable via `meeting-hive vocab` CLI. |
| **Summarizer** | `anthropic` | Claude family (Sonnet / Opus / Haiku) via the Anthropic API — or any Anthropic-compatible endpoint via `base_url`. |
| **Summarizer** | `openai` | GPT / o-series via OpenAI — or any OpenAI-compatible server via `base_url` (LM Studio, llama.cpp, Jan.ai, vLLM, LocalAI, OpenRouter, LiteLLM). |
| **Summarizer** | `ollama` | Local LLM via [Ollama](https://ollama.com). No API key; requires the server running locally. |

Adding a new adapter is a single file + one line in the built-in registry. Adapters are config-driven, so the core pipeline doesn't know which one is in use.

## Prerequisites

- **Python 3.11+**
- **A summarizer backend** — an Anthropic or OpenAI API key, OR a local [Ollama](https://ollama.com) server with at least one model pulled
- **A source** — one of the supported adapters set up (Granola signed in, a Fathom API key, or any tool that can write markdown into a directory)
- **A vocabulary source** (optional) — leave `sqlite` as the default and populate it via CLI, or point to Wispr Flow

## Install

Installing the Python package gives you the `meeting-hive` and `meeting-hive-autocommit` CLIs on your `PATH`:

```bash
pipx install meeting-hive
```

That's enough for manual runs on any platform. Scheduling (macOS launchd / Linux systemd / Windows Task Scheduler) is a separate step — see below.

### macOS (launchd)

For automatic nightly runs, clone the repo and run the macOS installer. It only handles the launchd registration; the Python package still comes from `pipx`.

```bash
git clone https://github.com/plribeiro3000/meeting-hive.git ~/Projects/meeting-hive
cd ~/Projects/meeting-hive
./scripts/macos/install.sh --summarizer anthropic   # or openai / ollama
```

The installer:

- Verifies `meeting-hive-autocommit` is on `PATH` (from `pipx` / `pip`). If not, exits with the command to run.
- Asks for adapter choices (summarizer, source, vocabulary), scope, and internal email domains
- Runs `meeting-hive init` with your answers to generate `config.yaml` at the standard path (first run only)
- Prompts for the summarizer's API key if it needs one (Anthropic / OpenAI) and writes it to `secrets.env` (chmod 600). Ollama needs no key.
- Renders the launchd plist and loads it

Everything the installer creates is idempotent. Re-running it is safe.

#### Unattended install (for AI agents / CI)

The installer works non-interactively if every decision is passed as a flag. Stdin not being a TTY is auto-detected; missing `--summarizer` becomes a hard error (everything else falls back to sensible defaults). API keys are never requested programmatically — pass `--skip-secrets` and the installer prints the exact command the user needs to run afterwards.

```bash
./scripts/macos/install.sh \
    --summarizer anthropic \
    --source granola \
    --vocabulary sqlite \
    --scope work \
    --internal-domains mycompany.com,myco.co.uk \
    --skip-secrets
```

After the install finishes, the user (not the agent) runs:

```bash
echo 'ANTHROPIC_API_KEY=sk-...' >> ~/.config/meeting-hive/secrets.env
chmod 600 ~/.config/meeting-hive/secrets.env
```

Verify with a dry-run that doesn't hit the network or LLM:

```bash
meeting-hive sync --since 1 --dry-run --verbose
```

`./scripts/macos/install.sh --help` lists every flag.

#### Schedule

Default: Monday-Friday at 00:00 local time. Override via installer flags:

```bash
./scripts/macos/install.sh --hour 4 --minute 30 --days 1-5
./scripts/macos/install.sh --hour 3 --minute 0 --days 0,2,4,6   # Sun/Tue/Thu/Sat
./scripts/macos/install.sh --days 0-6                           # every day
```

Weekdays follow launchd's convention: `0` or `7` = Sunday, `1` = Monday, ..., `6` = Saturday. Re-running the installer with different flags regenerates the plist and reloads the agent.

#### Uninstall

```bash
./scripts/macos/uninstall.sh              # removes launchd agent, plist, and CLI symlink
./scripts/macos/uninstall.sh --purge      # also removes config, vocabulary DB, logs
./scripts/macos/uninstall.sh --purge --nuke-notes  # also removes ~/.meeting-notes/ (data loss)
```

`--nuke-notes` requires you to type the archive path to confirm (or pass `--i-really-mean-it` in non-TTY mode). The meeting archive is user data — the script won't delete it by accident. See `uninstall.sh --help` for every flag.

### Linux & Windows

No dedicated scheduling installer yet. The `pipx install meeting-hive` step above gives you the CLIs; scheduling is up to you (systemd / cron / Task Scheduler — recipes in [`docs/scheduling.md`](docs/scheduling.md)).

Generate `config.yaml` with interactive prompts:

```bash
meeting-hive init
```

Or pass everything non-interactively:

```bash
meeting-hive init --summarizer ollama --source granola --vocabulary sqlite \
  --internal-domains mycompany.com
```

If your summarizer needs an API key, add it to the secrets file:

- Linux: `$XDG_CONFIG_HOME/meeting-hive/secrets.env` (or `~/.config/meeting-hive/secrets.env`)
- Windows: `%APPDATA%\meeting-hive\secrets.env`

```
ANTHROPIC_API_KEY=sk-...      # or OPENAI_API_KEY=...
```

Then schedule `meeting-hive sync` — see **[`docs/scheduling.md`](docs/scheduling.md)** for systemd / cron / Task Scheduler recipes.

To uninstall on Linux / Windows there's no dedicated script yet. Manual steps:

**Linux** (systemd user timer):

```bash
systemctl --user disable --now meeting-hive.timer
rm ~/.config/systemd/user/meeting-hive.{service,timer}
pipx uninstall meeting-hive
rm -rf ~/.config/meeting-hive ~/.local/share/meeting-hive ~/.local/state/meeting-hive
# ~/.meeting-notes/ is your archive — delete separately only if you really want to.
```

**Windows** (Task Scheduler):

```powershell
Unregister-ScheduledTask -TaskName "meeting-hive sync" -Confirm:$false
pipx uninstall meeting-hive
Remove-Item $env:APPDATA\meeting-hive -Recurse
Remove-Item $env:LOCALAPPDATA\meeting-hive -Recurse
# %USERPROFILE%\.meeting-notes is your archive — delete separately only if you really want to.
```

## CLI

```bash
# Run the ingestion pipeline.
meeting-hive sync --since 7
meeting-hive sync --since 1 --dry-run --verbose

# Manage the vocabulary (when `vocabulary.adapter: sqlite`).
meeting-hive vocab list
meeting-hive vocab add "Post Grass" "Postgres"
meeting-hive vocab remove "Post Grass"
meeting-hive vocab clear

# Bulk operations.
meeting-hive vocab import wispr              # seed from Wispr Flow
meeting-hive vocab import yaml file.yaml     # seed from a YAML file
meeting-hive vocab export yaml backup.yaml   # dump to YAML
```

If your configured vocabulary adapter is read-only (e.g., `wispr`), mutating commands print a clear error telling you where to edit entries.

## Configuration

After install, edit your config to pick adapters and teach the classifier about your entities:

```yaml
source:
  adapter: granola        # or: markdown
  config: {}

vocabulary:
  adapter: sqlite         # or: wispr
  config: {}

summarizer:
  adapter: anthropic      # or: openai | ollama (no default — set by installer)
  config: {}

internal_domains:
  - mycompany.com

domain_rules:
  acme.com:
    type: client
    entity: Acme

title_patterns:
  - match: "(?i)founders friday"
    type: internal
    entity: founders
```

See **[`docs/configuration.md`](docs/configuration.md)** for the full schema including all adapter config keys.

## Daily operation

- **Record meetings as usual** in your source tool.
- **Next run**, a desktop notification appears:
  - ✅ "3 meeting(s) synced." — nothing for you to do
  - ⚠️ "2 ok, 1 need classification: Call with New Prospect" — copy the suggested YAML snippet from the log into `config.yaml`. Next run picks it up.
  - ❌ "config.yaml invalid (line 47)" / "source auth expired" — go fix and the next run recovers.
- **Manual run anytime**: `meeting-hive sync --since 1 --verbose`
- **Dry-run (no writes, no notifications)**: `meeting-hive sync --dry-run --verbose`

## Local history (git)

Installing the package ships a second command alongside the main CLI: `meeting-hive-autocommit`. It runs `meeting-hive sync` and then commits any archive changes to a local-only git repository under `~/.meeting-notes/.git/` after every sync. Empty syncs produce no commit. Nothing is pushed anywhere — the history lives on your disk.

What this gives you:

- **Daily diff**: `cd ~/.meeting-notes && git log --oneline` shows one entry per sync with changes, `git show <commit>` displays exactly what got written that day.
- **Rollback**: `git reset --hard <commit>` reverts the archive to any prior sync. If a run writes something wrong, you can undo it without touching the source tool.
- **Audit**: every change to every file is attributable to a specific sync, so "when did this line appear?" is always answerable via `git blame`.

On macOS, the installer schedules `meeting-hive-autocommit` automatically. Linux and Windows users point their scheduler at `meeting-hive-autocommit` instead of `meeting-hive sync` — see [`docs/scheduling.md`](docs/scheduling.md).

**This is versioning, not backup.** The history lives on the same disk as the archive. If the disk dies, both are gone. See below.

## Backup

**meeting-hive does not back up your archive, and neither does the local git history described above.** If you care about your meeting notes surviving disk failure, theft, ransomware, or accidental deletion, you are responsible for configuring a backup mechanism. The markdown files in `~/.meeting-notes/` are plain text; any standard tool works:

- **Time Machine** (macOS) — set it up with an external drive and make sure `~/.meeting-notes/` is not excluded.
- **Backblaze** — continuous off-site backup of your whole Mac; versioned; the archive is covered automatically.
- **restic / borg / kopia** — client-side encrypted incremental backups to any backend (local disk, S3, Backblaze B2, SFTP). You hold the encryption key; the storage provider only sees opaque blobs.
- **Cloud sync** (iCloud Drive, Dropbox, OneDrive) — convenient, but note two caveats: (a) macOS only syncs folders placed inside the provider's sync root, which would require moving the archive out of `$HOME`; (b) sync is not backup — if the pipeline writes a corrupted file, it propagates to every synced device.

Pick one and set it up before your first unattended run.

## What's NOT in scope

- **Being a replacement for your meeting-recording tool.** This project doesn't record, transcribe, summarize live, or offer cross-meeting search as a service. That's what your source tool is for.
- **Writing back to the source tool.** Source tool transcripts are read-only from our side; vocabulary is yours to maintain. `meeting-hive` is one-way: source → local archive.
- **Re-processing already-written files.** If you add a new vocabulary rule today, old files don't get re-corrected. Forward-only.
- **Growing beyond fixing transcriptions.** Features that don't directly serve the "correct proper nouns in multi-language transcripts" goal won't be added.

## Contributing

Narrow-scope project with an explicit goal of retiring once source tools ship multi-language vocabulary. If you have the same specific pain — multi-language technical meetings where per-language vocab doesn't apply — contributions are welcome.

Good PR fits:

- Adapters for source tools I don't use (Meetily, Hyprnote, OpenWhispr, Zoom AI Companion, Fathom, Otter, …)
- Adapters for vocabulary tools beyond Wispr Flow (Handy, Voxtype, Nerd Dictation, …)
- Dedicated installers for Linux (systemd user service + timer) and Windows (Task Scheduler)

Adding an adapter is a single file in `meeting_hive/sources/` or `meeting_hive/vocabs/` implementing the Protocol, plus one line in the module's `_BUILTINS` registry. No other code changes needed.

If your workflow already works with what exists — you don't need this project. That's fine; you're not the audience this is for.

## License

MIT — see [LICENSE](LICENSE).
