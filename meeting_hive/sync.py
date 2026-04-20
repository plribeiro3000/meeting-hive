"""Orchestrator: load vocabulary + meetings, correct, regen summary, classify, write, notify."""

from __future__ import annotations

import logging

from meeting_hive import (
    classifier,
    corrector,
    migrations,
    notify,
    paths,
    sources,
    summarizers,
    vocabs,
    writer,
)

log = logging.getLogger(__name__)


def _attach_file_logger() -> None:
    """Append-mode file logger so a cron/launchd/systemd run leaves a trail.

    Attaches to the `meeting_hive` logger (not root) so third-party libraries
    (anthropic, openai, requests) don't dump their own INFO logs into our file.
    """
    log_path = paths.log_file()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    handler.setLevel(logging.INFO)
    pkg_logger = logging.getLogger("meeting_hive")
    pkg_logger.setLevel(logging.INFO)
    pkg_logger.addHandler(handler)


def _resolve_source(cfg: dict) -> sources.MeetingSource:
    src_cfg = cfg.get("source") or {}
    name = src_cfg.get("adapter", "granola")
    return sources.resolve(name, src_cfg.get("config") or {})


def _resolve_vocab(cfg: dict) -> vocabs.VocabularySource:
    vocab_cfg = cfg.get("vocabulary") or {}
    name = vocab_cfg.get("adapter", "sqlite")
    return vocabs.resolve(name, vocab_cfg.get("config") or {})


def _resolve_summarizer(cfg: dict) -> summarizers.Summarizer:
    sum_cfg = cfg.get("summarizer") or {}
    name = sum_cfg.get("adapter")
    if not name:
        raise summarizers.SummarizerNotFoundError(
            "summarizer.adapter is required in config.yaml — pick one of: "
            f"{', '.join(summarizers.registered())}"
        )
    return summarizers.resolve(name, sum_cfg.get("config") or {})


def run(since_days: int = 7, dry_run: bool = False) -> dict:
    _attach_file_logger()
    log.info("=== meeting-hive starting (since=%d, dry_run=%s) ===", since_days, dry_run)

    stats = {"processed": 0, "skipped": 0, "pending_classification": 0, "failed": 0}

    # 1. Load config — bail early on syntax error.
    try:
        cfg = classifier.load_config()
    except classifier.ConfigError as e:
        log.error("Config error: %s", e)
        if not dry_run:
            notify.notify("meeting-hive", f"❌ config.yaml invalid: {e}")
        return {**stats, "failed": 1}

    # 1b. Run pending config schema migrations (in-place, with backup).
    try:
        cfg, migrated = migrations.migrate(cfg, paths.config_file())
        if migrated:
            log.info(
                "config.yaml migrated to schema v%d (backup written alongside)",
                migrations.CURRENT_VERSION,
            )
    except migrations.MigrationError as e:
        log.error("Config migration failed: %s", e)
        if not dry_run:
            notify.notify("meeting-hive", f"❌ config migration failed: {e}")
        return {**stats, "failed": 1}

    # 2. Resolve adapters.
    try:
        source = _resolve_source(cfg)
    except (sources.SourceNotFoundError, ValueError) as e:
        log.error("Source adapter misconfigured: %s", e)
        if not dry_run:
            notify.notify("meeting-hive", f"❌ source adapter error: {e}")
        return {**stats, "failed": 1}

    try:
        vocab_adapter = _resolve_vocab(cfg)
    except (vocabs.VocabNotFoundError, ValueError) as e:
        log.error("Vocabulary adapter misconfigured: %s", e)
        if not dry_run:
            notify.notify("meeting-hive", f"❌ vocabulary adapter error: {e}")
        return {**stats, "failed": 1}

    try:
        summarizer_adapter = _resolve_summarizer(cfg)
    except (summarizers.SummarizerNotFoundError, ValueError) as e:
        log.error("Summarizer adapter misconfigured: %s", e)
        if not dry_run:
            notify.notify("meeting-hive", f"❌ summarizer adapter error: {e}")
        return {**stats, "failed": 1}

    vocab = vocab_adapter.load()

    # 3. List meetings.
    try:
        meetings = source.list_meetings(since_days=since_days)
    except sources.SourceAuthError as e:
        log.error("Source auth failed: %s", e)
        if not dry_run:
            notify.notify("meeting-hive", "❌ source auth expired — re-authenticate in the app.")
        return {**stats, "failed": 1}
    except sources.SourceUnavailable as e:
        log.error("Source unavailable: %s", e)
        if not dry_run:
            notify.notify("meeting-hive", f"❌ source unavailable: {e}")
        return {**stats, "failed": 1}

    pending: list[tuple[str, str]] = []
    scope = cfg.get("scope", writer.DEFAULT_SCOPE)

    # 4. Per-meeting pipeline.
    for m in meetings:
        date_str = m.created_at.astimezone().strftime("%Y-%m-%d")
        slug = writer.slugify(m.title)

        if writer.already_exists(date_str, slug, scope=scope):
            log.debug("Skip (exists): %s %s", date_str, slug)
            stats["skipped"] += 1
            continue

        meta = classifier.ClassifyMeta(title=m.title, attendees=m.attendees)
        result = classifier.classify(meta, cfg)
        if result is None:
            suggestion = classifier.suggest_rule(meta, cfg)
            log.warning("UNCLASSIFIED: %s (%s)\n%s", m.title, date_str, suggestion)
            pending.append((m.title, suggestion))
            stats["pending_classification"] += 1
            continue

        try:
            transcript = source.get_transcript(m.id)
        except sources.SourceAuthError:
            log.error("Source auth failed mid-run — aborting")
            if not dry_run:
                notify.notify("meeting-hive", "❌ source auth expired mid-run.")
            stats["failed"] += 1
            break

        if not transcript:
            log.warning("No transcript for %s — skipping", m.title)
            stats["failed"] += 1
            continue

        transcript_fixed = corrector.apply_vocabulary(transcript, vocab).text

        try:
            summary = summarizer_adapter.summarize(
                transcript=transcript_fixed,
                title=m.title,
                attendees=m.attendees,
            )
        except summarizers.SummarizerAuthError as e:
            log.error("Summarizer auth failed: %s", e)
            if not dry_run:
                notify.notify("meeting-hive", f"❌ summarizer auth error: {e}")
            stats["failed"] += 1
            break
        except summarizers.SummarizerUnavailable as e:
            log.error("Summarizer unavailable: %s", e)
            if not dry_run:
                notify.notify("meeting-hive", f"❌ summarizer unavailable: {e}")
            stats["failed"] += 1
            break
        except Exception as e:
            log.error("Summarizer failed for %s: %s", m.title, e)
            stats["failed"] += 1
            continue

        summary_fixed = corrector.apply_vocabulary(summary, vocab).text

        try:
            writer.write_meeting(
                title=m.title,
                start=m.created_at,
                duration_seconds=m.duration_seconds,
                attendees=m.attendees,
                classification_type=result.type,
                classification_entity=result.entity,
                transcript=transcript_fixed,
                summary=summary_fixed,
                scope=scope,
                source="meeting-hive",
                dry_run=dry_run,
            )
        except Exception as e:
            log.error("Writer failed for %s: %s", m.title, e)
            stats["failed"] += 1
            continue

        stats["processed"] += 1

    log.info("=== meeting-hive done: %s ===", stats)

    if dry_run:
        return stats

    if stats["failed"] > 0:
        notify.notify(
            "meeting-hive",
            f"❌ {stats['failed']} failure(s). "
            f"{stats['processed']} ok, {stats['pending_classification']} pending.",
        )
    elif stats["pending_classification"] > 0:
        titles = ", ".join(t for t, _ in pending[:3])
        more = "" if len(pending) <= 3 else f" (+{len(pending) - 3})"
        notify.notify(
            "meeting-hive",
            f"⚠️ {stats['processed']} ok, "
            f"{stats['pending_classification']} need classification: {titles}{more}",
        )
    elif stats["processed"] > 0:
        notify.notify("meeting-hive", f"✅ {stats['processed']} meeting(s) synced.")

    return stats
