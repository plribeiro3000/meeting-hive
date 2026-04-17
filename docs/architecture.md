# Architecture

> For the project's positioning (stopgap, narrow scope, the bee metaphor) see the [README](../README.md). This doc is the technical reference.

## Adapter axes

The pipeline has three pluggable axes, chosen in `config.yaml`:

- **Source adapter** — where meeting records come from (`granola`, `markdown`, …).
- **Vocabulary adapter** — the `phrase → replacement` map applied to transcripts (`sqlite`, `wispr`, …).
- **Summarizer adapter** — the AI backend that regenerates the summary (`anthropic`, `openai`, `ollama`). No default — the installer picks one at setup time.

Each adapter implements a minimal Protocol (see `meeting_hive/sources/__init__.py`, `meeting_hive/vocabs/__init__.py`, `meeting_hive/summarizers/__init__.py`) and receives an opaque `config` dict it self-validates. The pipeline never imports adapters directly — it goes through `<axis>.resolve(name, config)`. Writing a new adapter is a single file plus one line in the module's `_BUILTINS` registry.

## Pipeline (per run)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. Load config                                                            │
│    → fail loud if YAML is broken (notification + abort)                   │
├──────────────────────────────────────────────────────────────────────────┤
│ 2. Resolve source + vocabulary + summarizer adapters from config         │
├──────────────────────────────────────────────────────────────────────────┤
│ 3. vocab_adapter.load() → { phrase: replacement }                        │
├──────────────────────────────────────────────────────────────────────────┤
│ 4. source_adapter.list_meetings(since_days=N)                            │
├──────────────────────────────────────────────────────────────────────────┤
│ 5. For each meeting:                                                      │
│    a. Idempotency: skip if file already exists in archive                 │
│    b. Classify via rules; if UNCLASSIFIED → log suggestion, skip          │
│    c. source_adapter.get_transcript(id)                                   │
│    d. Apply vocabulary to transcript                                      │
│    e. summarizer_adapter.summarize(corrected transcript)                  │
│    f. Apply vocabulary to summary (the AI may echo original spellings)    │
│    g. Write paired markdown files to ~/.meeting-notes/<scope>/<year>/     │
├──────────────────────────────────────────────────────────────────────────┤
│ 6. Emit desktop notification (✅ / ⚠️ / ❌ depending on outcome)           │
└──────────────────────────────────────────────────────────────────────────┘
```

## Why a 7-day lookback (default)?

When meeting-hive fires each morning, it doesn't only process yesterday's meetings — it scans the last 7 days. Reason: if a meeting was **unclassified** on a previous run (new client, new vendor), the user has a week to add the rule. The next run picks it up automatically because:

- **Idempotency** skips meetings already in the archive
- **UNCLASSIFIED** doesn't write anything, so the meeting remains in the lookback window until it's classifiable

This gives you a 7-day grace period for novel scenarios without manual intervention.

## File layout on disk

```
~/.meeting-notes/
└── <scope>/                # e.g., "work", "personal" — set in config.yaml
    └── <year>/
        ├── YYYY-MM-DD-my-meeting-slug-summary.md
        └── YYYY-MM-DD-my-meeting-slug-transcript.md
```

The archive lives at `~/.meeting-notes/` (a top-level dotdir) rather than under the XDG data dir (`~/.local/share/meeting-hive/`). This is **intentional**: the notes are the asset users want to back up, sync across machines, or point other tools at — keeping them at a top-level, discoverable path makes Time Machine / restic / cloud-sync selections obvious, and matches the convention of other plain-text-archive tools. Everything *internal* to meeting-hive (config, vocabulary DB, logs) still follows XDG; only the user-facing archive sits outside it, by design.

## Frontmatter schema

Every file has a YAML frontmatter block. Example:

```yaml
---
date: 2026-04-16
time: "15:00-15:30 GMT-05:00"
title: "Acme / MyCompany - Kickoff"
client: Acme
invitees:
  - alice@acme.com
  - bob@acme.com
  - me@mycompany.com
source: meeting-hive
summary_type: ai
type: meeting-summary
related: 2026-04-16-acme-mycompany-kickoff-transcript.md
---
```

- `date` / `time`: ISO date + local range with timezone offset
- `title`: quoted string (escapes YAML-safely)
- **Classification field** (one of `client`/`vendor`/`internal`/`investor`/`community`/`event`): the category key, value is the canonical entity name
- `invitees`: list of attendee emails (not names — emails are canonical identifiers)
- `source`: always `meeting-hive` (the tool that wrote the file). The originating source tool is implicit in the adapter you configured and is not duplicated in every file.
- `summary_type: ai`: only on `-summary.md` files
- `type`: `meeting-summary` or `meeting-transcript`
- `related`: name of the paired file

This shape is intentionally grep-friendly:

```bash
# all Acme client meetings
grep -rl "^client: Acme$" ~/.meeting-notes/

# all meetings with Alice
grep -rl "alice@acme.com" ~/.meeting-notes/

# all internal founders meetings
grep -rl "^internal: founders$" ~/.meeting-notes/

# all meetings in March 2026
ls ~/.meeting-notes/work/2026/2026-03-*.md
```

## Why markdown?

Markdown is the worst format for meeting notes except for every other format.

- **Git-diffable** → version history comes for free
- **Grep-friendly** → classic tools work
- **AI-friendly** → LLMs were trained on markdown; they handle it natively
- **Editor-agnostic** → open in Obsidian, VS Code, TextEdit, vim, anything
- **Future-proof** → plain text stays readable regardless of which tools come and go

## Why regenerate the summary instead of just fixing the transcript?

The source's summary is AI-generated **from the source's transcript**. If the transcript has "Post Grass" throughout, the summary says "Post Grass" too. Fixing just the transcript leaves a summary that says "Post Grass" while the transcript below says "Postgres" — disorienting and wrong.

So after correcting the transcript, we regenerate the summary from scratch with Sonnet, then apply corrections to the regenerated summary as belt-and-suspenders (Sonnet sometimes echoes original terms it saw earlier in the transcript).

## Which LLM?

You pick at install time via `--summarizer`. No default in config — the installer requires an explicit choice among:

- `anthropic` — Claude Sonnet is the default model (configurable). Sweet spot for structured summarization at ~10× less than Opus.
- `openai` — GPT-4o is the default model (configurable to any OpenAI model).
- `ollama` — any model you've pulled locally (default suggestion: `llama3`). Free, private, slower.

All three share the same prompt template (in `meeting_hive/summarizers/__init__.py`), so output shape stays consistent across backends. Model and generation params are per-adapter `config` keys.

## Design decisions (non-obvious ones)

### Three-axis adapter architecture

**Source** (where meetings come from), **vocabulary** (how to spell things), and **summarizer** (which AI regenerates the summary) are independent concerns. Coupling any two means every new variant of one forces reinventing the others. Keeping all three orthogonal lets combinations like `granola + wispr + anthropic` and `markdown + sqlite + ollama` share 100% of the pipeline code with zero conditional branches.

The core pipeline knows only about the Protocols — not about specific adapters. Adapters are discovered via a registry; call sites go through `resolve(name, config)`.

### Rule-based classification, not LLM-based

Classification (is this meeting `client: Acme` or `vendor: Stripe`?) is done by **rules**, not LLM inference. Reasons:

1. **Determinism**: same meeting → same classification, always
2. **Cost**: zero inference per classification
3. **Debuggability**: user can see exactly which rule matched
4. **Forward compatibility**: user adds rule once, system remembers forever

The cost is that novel entities hit UNCLASSIFIED and require manual rule addition. That's a feature — it forces the user to **think about** what this entity is, and make the canonical name decision explicitly.

### UNCLASSIFIED skips writing entirely

When a meeting fails classification, meeting-hive does **not** write it with a placeholder category. Reasons:

1. Placeholders pollute the archive with inconsistent data
2. Grep-friendly is only grep-friendly if the shape is consistent
3. Skipping forces the user to add the rule — otherwise the archive quietly grows "UNKNOWN" meetings that never get fixed

The 7-day lookback guarantees no meeting is lost — only delayed.

### Idempotency by filename

`already_exists(date, slug)` checks if either `-summary.md` or `-transcript.md` is already on disk. If yes, skip. This means:

- Running the script twice on the same day is safe
- If the user manually edits a file, re-running doesn't overwrite it
- If the user wants to re-process, they delete the files manually

### Vocabulary is read-only when the adapter represents someone else's tool

The `wispr` adapter wraps Wispr Flow's SQLite. We deliberately **don't** implement writes: that database is Wispr's data model, and a second writer risks corrupting it. The `sqlite` adapter, conversely, is meeting-hive's own database and supports the full mutable Protocol (add/remove/clear/import/export via CLI).

The `MutableVocabularySource` Protocol extends `VocabularySource`, so read-only consumers (the pipeline) accept both; write-only consumers (the CLI) explicitly check for mutability and print a clear error when the configured adapter is read-only.

## Adapter details

### `granola` source

Granola's desktop app maintains a local JSON cache (`cache-v*.json`) and a `supabase.json` with the WorkOS access token. The adapter reads from the cache first (zero latency, works offline), and falls back to Granola's REST API (`api.granola.ai/v1`) when a transcript isn't in the cache (typically for older meetings). The token lets us hit the API without an OAuth flow from the script.

### `markdown` source

Reads meetings from a directory. Each file is a meeting; frontmatter holds `title` / `date` / `time` / `attendees`; the body is the transcript. Tool-agnostic: Meetily, Hyprnote, OpenWhispr export, Zoom AI Companion export, hand-written notes — if it lands in a directory as markdown, this adapter handles it.

### `wispr` vocabulary (read-only)

Opens a snapshot of Wispr Flow's SQLite (`Dictionary` table) to avoid lock contention with the running app. Returns `phrase → replacement` pairs where `isSnippet=0` and `replacement` is non-empty — meeting-hive uses word/phrase substitutions, not multi-line snippets.

### `sqlite` vocabulary (mutable)

A meeting-hive-owned SQLite at the platform-appropriate data dir (`~/.local/share/meeting-hive/vocabulary.db` on Unix, `%LOCALAPPDATA%\meeting-hive\vocabulary.db` on Windows). Schema is a single `vocabulary` table keyed by `phrase`. Managed via the `meeting-hive vocab` CLI.
