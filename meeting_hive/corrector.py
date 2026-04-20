"""Apply Wispr vocabulary as case-sensitive, whole-word replacements."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class CorrectionResult:
    text: str
    replacements: dict[str, int]


def apply_vocabulary(text: str, vocab: dict[str, str]) -> CorrectionResult:
    """Apply each `phrase -> replacement` from `vocab` to `text` as a case-sensitive,
    whole-word regex substitution.

    Longer phrases are applied first so that multi-word entries match before their
    single-word substrings. Phrases containing only punctuation/spaces are skipped.
    """
    if not text or not vocab:
        return CorrectionResult(text=text or "", replacements={})

    # Sort phrases by length DESC so multi-word phrases match before their substrings.
    phrases = sorted(vocab.keys(), key=len, reverse=True)
    counts: dict[str, int] = {}

    result = text
    for phrase in phrases:
        replacement = vocab[phrase]
        # Use word boundaries. For phrases containing non-word chars, \b may not
        # behave; fall back to literal match.
        if re.search(r"^\w", phrase) and re.search(r"\w$", phrase):
            pattern = r"\b" + re.escape(phrase) + r"\b"
        else:
            pattern = re.escape(phrase)
        new_result, n = re.subn(pattern, replacement, result)
        if n > 0:
            counts[phrase] = n
            result = new_result

    if counts:
        total = sum(counts.values())
        log.debug("Applied %d corrections across %d phrases", total, len(counts))

    return CorrectionResult(text=result, replacements=counts)
