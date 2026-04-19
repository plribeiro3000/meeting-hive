"""CLI entrypoint for meeting-hive.

Subcommands:
    init [options]                    # generate config.yaml at the default path
    sync                              # run the ingestion pipeline
    doctor                            # diagnose installation health
    vocab list                        # read-only
    vocab add <phrase> <replacement>  # mutable adapter required
    vocab remove <phrase>             # mutable adapter required
    vocab clear                       # mutable adapter required
    vocab import <kind> [<source>]    # kind: wispr | yaml
    vocab export yaml <file>          # read-only
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from meeting_hive import __version__, classifier, paths, sources, summarizers, vocabs


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meeting-hive",
        description=(
            "Sync meetings from a source tool into a local, AI-queryable markdown archive."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
    parser.add_argument("-V", "--version", action="version", version=f"meeting-hive {__version__}")
    sub = parser.add_subparsers(dest="command")

    # init
    init_p = sub.add_parser(
        "init", help="Generate config.yaml with sensible defaults at the standard path."
    )
    init_p.add_argument(
        "--summarizer",
        choices=summarizers.registered(),
        help="Summarizer adapter (required; prompts if stdin is a TTY and not passed).",
    )
    init_p.add_argument(
        "--source",
        choices=sources.registered(),
        help=f"Source adapter. Default: granola. Options: {', '.join(sources.registered())}.",
    )
    init_p.add_argument(
        "--source-path",
        help="Required when --source=markdown: directory holding meeting .md files.",
    )
    init_p.add_argument(
        "--vocabulary",
        choices=vocabs.registered(),
        help=f"Vocabulary adapter. Default: sqlite. Options: {', '.join(vocabs.registered())}.",
    )
    init_p.add_argument(
        "--scope",
        help="Archive subfolder under ~/.meeting-notes/. Default: work.",
    )
    init_p.add_argument(
        "--internal-domains",
        help="Comma-separated list of your organization's email domains.",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing config.yaml.",
    )

    # sync
    sync_p = sub.add_parser(
        "sync", help="Run the ingestion pipeline (default command if none given)."
    )
    sync_p.add_argument(
        "--since", type=int, default=7, metavar="DAYS", help="Lookback window in days (default: 7)."
    )
    sync_p.add_argument(
        "--dry-run", action="store_true", help="Do not write files or send notifications."
    )

    # doctor
    sub.add_parser(
        "doctor",
        help="Diagnose installation health — config, adapters, secrets, archive.",
    )

    # vocab
    vocab_p = sub.add_parser("vocab", help="Manage the vocabulary of corrections.")
    vocab_sub = vocab_p.add_subparsers(dest="vocab_command", required=True)

    vocab_sub.add_parser("list", help="List all phrase → replacement entries.")

    add_p = vocab_sub.add_parser("add", help="Add or update an entry.")
    add_p.add_argument("phrase")
    add_p.add_argument("replacement")

    rm_p = vocab_sub.add_parser("remove", help="Remove an entry by phrase.")
    rm_p.add_argument("phrase")

    vocab_sub.add_parser("clear", help="Remove every entry from the configured adapter.")

    imp_p = vocab_sub.add_parser("import", help="Import entries into the configured adapter.")
    imp_p.add_argument("kind", choices=["wispr", "yaml"], help="Importer type.")
    imp_p.add_argument(
        "source", nargs="?", help="Source file (for yaml) or leave empty for wispr defaults."
    )

    exp_p = vocab_sub.add_parser("export", help="Export entries from the configured adapter.")
    exp_p.add_argument("kind", choices=["yaml"], help="Export format.")
    exp_p.add_argument("dest", help="Destination file.")

    return parser


def _load_adapter() -> vocabs.VocabularySource:
    cfg = classifier.load_config()
    vcfg = cfg.get("vocabulary") or {}
    name = vcfg.get("adapter", "sqlite")
    return vocabs.resolve(name, vcfg.get("config") or {})


def _require_mutable(adapter: vocabs.VocabularySource) -> vocabs.MutableVocabularySource:
    if not isinstance(adapter, vocabs.MutableVocabularySource):
        adapter_name = type(adapter).__name__
        raise vocabs.VocabReadOnlyError(
            f"Configured vocabulary adapter ({adapter_name}) is read-only. "
            f"Switch `vocabulary.adapter` to `sqlite` in config.yaml to manage entries via CLI."
        )
    return adapter


def _cmd_vocab_list(args) -> int:
    adapter = _load_adapter()
    vocab = adapter.load()
    if not vocab:
        print("(no entries)")
        return 0
    width = max(len(p) for p in vocab)
    for phrase in sorted(vocab):
        print(f"  {phrase:<{width}}  ->  {vocab[phrase]}")
    print(f"\nTotal: {len(vocab)} entries")
    return 0


def _cmd_vocab_add(args) -> int:
    adapter = _require_mutable(_load_adapter())
    adapter.add(args.phrase, args.replacement)
    print(f"✓ added  {args.phrase!r}  ->  {args.replacement!r}")
    return 0


def _cmd_vocab_remove(args) -> int:
    adapter = _require_mutable(_load_adapter())
    removed = adapter.remove(args.phrase)
    if removed:
        print(f"✓ removed  {args.phrase!r}")
        return 0
    print(f"(not found)  {args.phrase!r}")
    return 1


def _cmd_vocab_clear(args) -> int:
    adapter = _require_mutable(_load_adapter())
    n = adapter.clear()
    print(f"✓ cleared {n} entries")
    return 0


def _cmd_vocab_import(args) -> int:
    target = _require_mutable(_load_adapter())
    if args.kind == "wispr":
        wispr = vocabs.resolve("wispr")
        pairs = wispr.load()
    else:  # yaml
        if not args.source:
            print("error: `import yaml` requires a source file path", file=sys.stderr)
            return 2
        import yaml as _yaml

        data = _yaml.safe_load(Path(args.source).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            print(
                "error: YAML file must be a top-level mapping of phrase -> replacement",
                file=sys.stderr,
            )
            return 2
        pairs = {str(k): str(v) for k, v in data.items()}

    # Prefer bulk_upsert if available (set by sqlite adapter).
    if hasattr(target, "bulk_upsert"):
        n = target.bulk_upsert(pairs, source=f"import:{args.kind}")
    else:
        for p, r in pairs.items():
            target.add(p, r)
        n = len(pairs)

    print(f"✓ imported {n} entries from {args.kind}")
    return 0


def _cmd_vocab_export(args) -> int:
    adapter = _load_adapter()
    pairs = adapter.load()
    import yaml as _yaml

    Path(args.dest).write_text(
        _yaml.safe_dump(pairs, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"✓ exported {len(pairs)} entries to {args.dest}")
    return 0


VOCAB_DISPATCH = {
    "list": _cmd_vocab_list,
    "add": _cmd_vocab_add,
    "remove": _cmd_vocab_remove,
    "clear": _cmd_vocab_clear,
    "import": _cmd_vocab_import,
    "export": _cmd_vocab_export,
}


# -------------------------------------------------------------------
# init subcommand: generate a fresh config.yaml with sensible defaults.
# -------------------------------------------------------------------


CONFIG_TEMPLATE = """# meeting-hive config — generated by `meeting-hive init`.
# See docs/configuration.md for the full schema and every adapter option.

# -------------------------------------------------------------------
# Source: where meetings come from.
#   Built-in adapters: {sources_registered}
# -------------------------------------------------------------------
source:
  adapter: {source}
  config:{source_config}

# -------------------------------------------------------------------
# Vocabulary: the phrase → replacement mapping applied to transcripts.
#   Built-in adapters: {vocabs_registered}
# -------------------------------------------------------------------
vocabulary:
  adapter: {vocab}
  config: {{}}

# -------------------------------------------------------------------
# Summarizer: the AI backend that regenerates the meeting summary.
#   Built-in adapters: {summarizers_registered}
#   API key (if any) is read from secrets.env in the same config dir.
# -------------------------------------------------------------------
summarizer:
  adapter: {summarizer}
  config: {{}}

# -------------------------------------------------------------------
# Classification rules (evaluated in order; first match wins).
# Add entries as the daily notification surfaces UNCLASSIFIED meetings.
# -------------------------------------------------------------------

# Archive subfolder under ~/.meeting-notes/.
scope: {scope}

# Email domains your organization owns. A meeting where every attendee matches
# one of these is classified as internal.
internal_domains:
{domains_block}

# Layer 1: named recurring meetings (regex against the title).
title_patterns: []

# Layer 2: when every attendee is in internal_domains, pick a subtype via
# title hints. `default_subtype` is used when no hint matches.
internal_only:
  default_subtype: alignment
  title_hints: []

# Layer 3: specific email → category (for gmail / personal contacts).
email_rules: {{}}

# Layer 4: external attendee domain → category. Most rules live here.
domain_rules: {{}}
"""


def _render_config(
    *,
    summarizer: str,
    source: str,
    source_path: str | None,
    vocab: str,
    scope: str,
    internal_domains: list[str],
) -> str:
    if source == "markdown":
        if not source_path:
            raise ValueError("--source-path is required when --source=markdown")
        source_config = f"\n    path: {source_path}"
    else:
        source_config = " {}"

    if internal_domains:
        domains_block = "\n".join(f"  - {d}" for d in internal_domains)
    else:
        domains_block = "  # - yourcompany.com"

    return CONFIG_TEMPLATE.format(
        source=source,
        source_config=source_config,
        vocab=vocab,
        summarizer=summarizer,
        scope=scope,
        domains_block=domains_block,
        sources_registered=", ".join(sources.registered()),
        vocabs_registered=", ".join(vocabs.registered()),
        summarizers_registered=", ".join(summarizers.registered()),
    )


def _prompt_choice(label: str, options: list[str], default: str | None = None) -> str:
    default_hint = f" [default: {default}]" if default else ""
    options_str = " / ".join(options)
    while True:
        print(f"{label} ({options_str}){default_hint}: ", end="", flush=True)
        choice = input().strip()
        if not choice and default:
            return default
        if choice in options:
            return choice
        print(f"  invalid choice — pick one of: {options_str}", file=sys.stderr)


def _prompt_free(label: str, default: str | None = None) -> str:
    default_hint = f" [default: {default}]" if default else ""
    print(f"{label}{default_hint}: ", end="", flush=True)
    value = input().strip()
    return value or (default or "")


def _cmd_init(args) -> int:
    cfg_path = paths.config_file()
    if cfg_path.exists() and not args.force:
        print(
            f"error: {cfg_path} already exists. Use --force to overwrite "
            "(your existing config will be lost).",
            file=sys.stderr,
        )
        return 2

    interactive = sys.stdin.isatty()

    summarizer = args.summarizer
    if not summarizer:
        if not interactive:
            print("error: --summarizer is required (non-interactive)", file=sys.stderr)
            return 2
        print()
        print("Pick a summarizer backend (required):")
        print("  anthropic — Claude via Anthropic API (requires API key)")
        print("  openai    — GPT / o-series via OpenAI API (requires API key)")
        print("  ollama    — Local LLM via Ollama (no API key)")
        summarizer = _prompt_choice("Summarizer", summarizers.registered())

    source = args.source
    if not source:
        source = (
            _prompt_choice("Source", sources.registered(), default="granola")
            if interactive
            else "granola"
        )

    source_path = args.source_path
    if source == "markdown" and not source_path:
        if interactive:
            source_path = _prompt_free("Path to meetings directory")
            if not source_path:
                print("error: --source=markdown needs a path", file=sys.stderr)
                return 2
        else:
            print("error: --source-path is required when --source=markdown", file=sys.stderr)
            return 2

    vocab = args.vocabulary
    if not vocab:
        vocab = (
            _prompt_choice("Vocabulary", vocabs.registered(), default="sqlite")
            if interactive
            else "sqlite"
        )

    scope = args.scope
    if not scope:
        scope = _prompt_free("Scope (archive subfolder)", default="work") if interactive else "work"

    raw_domains = args.internal_domains
    if raw_domains is None and interactive:
        raw_domains = _prompt_free("Internal email domains (comma-separated, empty to skip)")
    internal_domains = [d.strip() for d in (raw_domains or "").split(",") if d.strip()]

    try:
        content = _render_config(
            summarizer=summarizer,
            source=source,
            source_path=source_path,
            vocab=vocab,
            scope=scope,
            internal_domains=internal_domains,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(content, encoding="utf-8")
    print(f"✓ wrote {cfg_path}")
    print(f"  summarizer: {summarizer}")
    print(f"  source: {source}" + (f" ({source_path})" if source_path else ""))
    print(f"  vocabulary: {vocab}")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Default command: sync (backwards compat with existing launchd plist).
    command = args.command or "sync"

    try:
        if command == "init":
            return _cmd_init(args)

        if command == "sync":
            from meeting_hive.sync import run

            since = getattr(args, "since", 7)
            dry_run = getattr(args, "dry_run", False)
            stats = run(since_days=since, dry_run=dry_run)
            return 0 if stats.get("failed", 0) == 0 else 1

        if command == "doctor":
            from meeting_hive import doctor

            return doctor.run()

        if command == "vocab":
            handler = VOCAB_DISPATCH[args.vocab_command]
            return handler(args)

        parser.print_help()
        return 2
    except vocabs.VocabReadOnlyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except classifier.ConfigError as e:
        print(f"error: config.yaml — {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
