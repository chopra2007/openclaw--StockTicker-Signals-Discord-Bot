"""Narrative quality-bar measurements for the !all command.

Pure helpers used by both:
  - the aggregator's `quality_bar:` log line emitted at the end of
    `_compute_all` (Layer A/B observability per plan PR7);
  - the pytest fixture suite in `tests/test_all_command_quality_bar.py`
    (Layer A; 9 acceptance checks × 3 tickers = 27 assertions).

No I/O. No LLM calls. Each function takes a narrative string (and any
auxiliary structured context) and returns a small int / bool that maps
1:1 to one of the 9 quality-bar items in `quality-bar.md` §"Acceptance
criteria for v2".
"""
from __future__ import annotations

import re
from typing import Optional


_NUMBERED_FACT_RE = re.compile(
    r"\b(?:\$?\d{1,3}(?:[.,]\d+)?(?:%|\$|B|M|K|bn| dollars| billion)?"
    r"|Q[1-4]\s?(?:FY)?\d{2,4}|FY\d{2,4}|20\d{2}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)

# A bullet is a markdown line starting with `*`, `-`, or `•` (after stripping
# leading whitespace). Numbered lists also count.
_BULLET_RE = re.compile(r"^\s*(?:[\*\-•]|\d+\.)\s+\S", re.MULTILINE)

# Match section headers in either markdown (`## Catalyst`, `**Catalysts:**`) or
# plain prefixed labels.
_CATALYST_HEADER_RE = re.compile(
    r"(?im)^\s*(?:#+\s*|\*\*\s*)?catalyst[s]?\b",
)
_RISK_HEADER_RE = re.compile(
    r"(?im)^\s*(?:#+\s*|\*\*\s*)?risk(?:s|\s+considerations?)?\b",
)

# Heuristics that signal raw model thinking leaked through the filter.
_THINKING_LEAK_MARKERS = (
    "<thinking>",
    "</thinking>",
    "Paragraph 1:",
    "Paragraph 2:",
    "Paragraph 3:",
    "Paragraph 4:",
    "Paragraph 5:",
    "Paragraph 6:",
    "Step 1:",
    "Step 2:",
    "word count",
    "Word count:",
    "[INTERNAL]",
)


def count_numbered_facts(narrative: str) -> int:
    """Count distinct numeric/$/date specifics — proxy for evidence specificity."""
    if not narrative:
        return 0
    found = set()
    for m in _NUMBERED_FACT_RE.finditer(narrative):
        found.add(m.group(0).lower())
    return len(found)


def _bullets_under_header(narrative: str, header_re: re.Pattern[str]) -> int:
    """Count bullet lines appearing in the section that follows the matched header."""
    if not narrative:
        return 0
    m = header_re.search(narrative)
    if not m:
        return 0
    tail = narrative[m.end():]
    # Section ends at the next header line (markdown #+ or **bold:** style).
    next_header = re.search(
        r"(?im)^\s*(?:#+\s+\S|\*\*[A-Z][\w\s]+:?\s*\*\*)",
        tail,
    )
    section = tail[: next_header.start()] if next_header else tail
    return len(_BULLET_RE.findall(section))


def count_catalyst_bullets(narrative: str) -> int:
    return _bullets_under_header(narrative, _CATALYST_HEADER_RE)


def count_risk_bullets(narrative: str) -> int:
    return _bullets_under_header(narrative, _RISK_HEADER_RE)


def has_thinking_leak(narrative: str) -> bool:
    if not narrative:
        return False
    return any(marker in narrative for marker in _THINKING_LEAK_MARKERS)


def sources_named_in_narrative(narrative: str, sources_surfaced: list[str]) -> int:
    """Count how many of the surfaced source labels are actually mentioned."""
    if not narrative or not sources_surfaced:
        return 0
    text = narrative.lower()
    hits = 0
    for label in sources_surfaced:
        # Strip common DB suffixes so e.g. "youtube_evidence_db" matches "youtube".
        base = label.lower().split("_db")[0].split("_24h")[0].split("_last3")[0]
        # Try the base token and some friendly variants.
        candidates = {base}
        if base.startswith("youtube"):
            candidates |= {"youtube", "yt"}
        if base in {"news", "sec", "twitter", "reddit", "wsb", "social", "chat",
                    "brief", "vault", "options", "apewisdom"}:
            candidates.add(base)
        if any(c and c in text for c in candidates):
            hits += 1
    return hits


def trade_plan_complete(
    sl: Optional[float],
    tp1: Optional[float],
    tp2: Optional[float],
    tp3: Optional[float],
) -> bool:
    return all(v is not None for v in (sl, tp1, tp2, tp3))


# Ship 2 M2/M6 — narrative must contain these literal section markers.
# Comparison is case-insensitive but token-exact so a missing token forces
# a re-prompt rather than passing through with a malformed Bear Case section.
REQUIRED_SECTION_TOKENS = (
    "**TL;DR:**",
    "**What could go wrong:**",
    "**Risks & mitigants:**",
)


def missing_required_sections(narrative: str) -> list[str]:
    """Return the list of REQUIRED_SECTION_TOKENS missing from `narrative`."""
    if not narrative:
        return list(REQUIRED_SECTION_TOKENS)
    lower = narrative.lower()
    return [tok for tok in REQUIRED_SECTION_TOKENS if tok.lower() not in lower]


def has_required_sections(narrative: str) -> bool:
    """Ship 2 — True iff every REQUIRED_SECTION_TOKENS marker is present.

    Used by `narrator.synthesize_narrative` to structurally reject and
    re-prompt narratives that drop a section.
    """
    return not missing_required_sections(narrative)
