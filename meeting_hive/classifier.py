"""Classify a meeting via YAML rules. Returns None on miss (caller handles UNCLASSIFIED)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from meeting_hive import paths

log = logging.getLogger(__name__)

DEFAULT_CONFIG = paths.config_file()


class ConfigError(RuntimeError):
    """Raised when config.yaml is missing or malformed."""


@dataclass
class Classification:
    type: str  # client | vendor | internal | investor | community | event
    entity: str  # canonical entity name (or internal subtype)


@dataclass
class ClassifyMeta:
    title: str
    attendees: list[str]


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    """Load and validate config.yaml. Raises ConfigError with a line number on bad YAML."""
    path = Path(path).expanduser()
    if not path.exists():
        raise ConfigError(f"config.yaml not found at {path}")
    try:
        raw = path.read_text()
        cfg = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}" if mark else "unknown location"
        raise ConfigError(f"config.yaml invalid at {where}: {e}") from e
    if not isinstance(cfg, dict):
        raise ConfigError("config.yaml must be a YAML object at the top level")

    # Minimal schema check.
    for key in ("title_patterns", "internal_only", "domain_rules", "email_rules"):
        if key in cfg and not isinstance(cfg[key], (list, dict)):
            raise ConfigError(
                f"config.yaml: `{key}` must be a list or object, got {type(cfg[key]).__name__}"
            )

    return cfg


def classify(meta: ClassifyMeta, cfg: dict) -> Classification | None:
    """Apply rules in order: title_patterns → internal_only → email_rules → domain_rules.

    Returns None if no rule matches.
    """
    title = meta.title or ""
    attendees = [a.lower() for a in (meta.attendees or [])]

    # 1. Title patterns (most specific — explicitly configured recurring meetings).
    for rule in cfg.get("title_patterns") or []:
        pattern = rule.get("match")
        if not pattern:
            continue
        try:
            if re.search(pattern, title):
                return Classification(type=rule["type"], entity=rule["entity"])
        except re.error as e:
            log.warning("Bad regex in title_patterns (%r): %s", pattern, e)

    # 2. Internal only — every attendee is in one of the configured internal_domains.
    internal_domains = {d.lower() for d in (cfg.get("internal_domains") or [])}
    internal_cfg = cfg.get("internal_only") or {}
    external = [a for a in attendees if _domain_of(a) not in internal_domains]
    if attendees and internal_domains and not external:
        subtype = internal_cfg.get("default_subtype", "alignment")
        for hint in internal_cfg.get("title_hints") or []:
            pat = hint.get("match")
            if pat and re.search(pat, title):
                subtype = hint["subtype"]
                break
        return Classification(type="internal", entity=subtype)

    # 3. Email-exact rules (gmail contacts, etc.).
    email_rules = cfg.get("email_rules") or {}
    for email in attendees:
        if email in email_rules:
            rule = email_rules[email]
            return Classification(type=rule["type"], entity=rule["entity"])

    # 4. Domain rules — first external domain that matches.
    domain_rules = cfg.get("domain_rules") or {}
    for email in attendees:
        dom = _domain_of(email)
        if dom in domain_rules:
            rule = domain_rules[dom]
            return Classification(type=rule["type"], entity=rule["entity"])

    return None


def _domain_of(email: str) -> str:
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[1].lower()


def suggest_rule(meta: ClassifyMeta, cfg: dict | None = None) -> str:
    """Return a YAML snippet the user can copy into config.yaml for this unclassified meeting."""
    internal_domains = {d.lower() for d in ((cfg or {}).get("internal_domains") or [])}
    external_domains = sorted(
        {
            _domain_of(a)
            for a in meta.attendees
            if _domain_of(a) and _domain_of(a) not in internal_domains
        }
    )
    lines = [
        f'  # UNCLASSIFIED: "{meta.title}"',
        f"  # attendees: {', '.join(meta.attendees) if meta.attendees else '(none)'}",
    ]
    if external_domains:
        lines.append("  # Suggested domain_rules entry(ies):")
        for dom in external_domains:
            lines.append(f"  #   {dom}:")
            lines.append("  #     type: ???   # client | vendor | investor | community")
            lines.append('  #     entity: "???"')
    else:
        lines.append("  # No external domains — consider adding a title_patterns entry, or")
        lines.append("  # email_rules for specific gmail contacts.")
    return "\n".join(lines)
