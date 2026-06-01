"""Narrative sanitization, contradiction detection, and data-only fallback.

Sanitizes LLM output before exposure to Discord:
- Markdown links `[text](url)` -> `text (url)` (defeats clickable phishing)
- `@everyone` / `@here` mentions replaced with `[mention removed]`
- Control characters stripped

Detects direction contradictions between narrative and structured signal; if
the LLM goes off-rails, retries once with a hardened prompt and ultimately
falls back to a deterministic 2-line data-only render.
"""
from __future__ import annotations

import logging
import re
from typing import Awaitable, Callable, Optional

from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown

log = logging.getLogger("consensus_engine.alerts.all_command.output_filter")


_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MENTION_RE = re.compile(r"@(?:everyone|here)\b", re.IGNORECASE)

# all-risk-section v2 Fix #5 — internal pipeline labels that leaked into the
# Discord prose (live NVDA showed "per [macro_risk] news" and "as indicated by
# the COMPUTED SIGNAL"). These are evidence/routing tags meant for the prompt,
# never the reader. Strip them post-render so they never reach Discord.
#  - `[macro_risk]` / `[evidence:3]` / `[news_id:2]` style bracket tags
#  - the bare phrase `COMPUTED SIGNAL` (with optional "the"/"per"/"as indicated
#    by the" lead-in so we don't leave a dangling "the")
#  - the "high-vol data unavailable" apology that rides inside the swing
#    expected-move parenthetical (e.g. "(0.7×ATR×√5; high-vol data
#    unavailable)") — internal plumbing the reader shouldn't see. The bare
#    formula "0.7×ATR×√5" is a legitimate Trade Plan citation and is KEPT.
_INTERNAL_BRACKET_TAG_RE = re.compile(
    r"\s*\[(?:macro_risk|evidence:\s*\d+|news_id:\s*\d+|sec_id:\s*\d+"
    r"|twitter_id:\s*\d+|yt_evidence:\s*\d+)\]",
    re.IGNORECASE,
)
# Replace the token, optionally absorbing a single preceding "the " so we get
# "per the COMPUTED SIGNAL" -> "per the data" (one article, grammatical) rather
# than "the the data".
_COMPUTED_SIGNAL_RE = re.compile(
    r"(?:\bthe\s+)?\bCOMPUTED\s+SIGNAL\b", re.IGNORECASE,
)
# Strip only the apology clause inside the parenthetical, keep the formula.
_HIGH_VOL_APOLOGY_RE = re.compile(
    r"\s*;\s*high-vol\s+data\s+unavailable", re.IGNORECASE,
)
_DANGLING_SPACE_RE = re.compile(r" {2,}")
# Match thesis-reversal language only — generic financial vocabulary like
# "sell-side", "short interest", or "downside protection" appears in
# catalyst lists for bullish setups all the time and is not a contradiction.
_BEARISH_WORDS = re.compile(
    r"\b(?:bearish\s+(?:thesis|reversal|bias|outlook|setup|pattern)"
    r"|outlook\s+is\s+bearish"
    r"|recommend(?:s|ed)?\s+(?:selling|shorting|going\s+short)"
    r"|expect(?:s|ed)?\s+(?:a\s+)?(?:crash|plunge|tanking|sell-?off))\b",
    re.IGNORECASE,
)
_BULLISH_WORDS = re.compile(
    r"\b(?:bullish\s+(?:thesis|reversal|bias|outlook|setup|pattern)"
    r"|outlook\s+is\s+bullish"
    r"|recommend(?:s|ed)?\s+(?:buying|going\s+long)"
    r"|expect(?:s|ed)?\s+(?:a\s+)?(?:rally|breakout|surge))\b",
    re.IGNORECASE,
)


def _scrub_internal_tags(text: str) -> str:
    """all-risk-section v2 Fix #5 — strip internal pipeline labels from prose.

    Removes the evidence/routing tags the prompt uses internally so they never
    reach Discord: `[macro_risk]`, `[evidence:N]` and siblings, the bare phrase
    `COMPUTED SIGNAL` (with a leading "per the"/"as indicated by the" if
    present), and the `; high-vol data unavailable` apology clause inside the
    expected-move parenthetical. Leaves the `0.7×ATR×√5` formula intact (it is a
    legitimate Trade Plan citation).
    """
    out = _INTERNAL_BRACKET_TAG_RE.sub("", text)
    out = _COMPUTED_SIGNAL_RE.sub("the data", out)
    # collapse an accidental "the the" if a different lead-in preceded it.
    out = re.sub(r"\bthe\s+the\b", "the", out, flags=re.IGNORECASE)
    out = _HIGH_VOL_APOLOGY_RE.sub("", out)
    out = _DANGLING_SPACE_RE.sub(" ", out)
    return out


def sanitize_narrative(text: str) -> str:
    """Strip markdown links, control chars, @everyone/@here mentions, and
    internal pipeline tags (all-risk-section v2 Fix #5)."""
    if not text or not isinstance(text, str):
        return ""
    out = _MARKDOWN_LINK_RE.sub(r"\1 (\2)", text)
    out = _CONTROL_RE.sub("", out)
    out = _MENTION_RE.sub("[mention removed]", out)
    out = _scrub_internal_tags(out)
    return out


_RISK_HEADING_RE = re.compile(
    r"(?im)^\s*(?:#+\s*|\*\*\s*)?risk(?:s|\s+considerations?)?\b",
)


def detect_contradiction(narrative: str, structured: StructuredFields) -> bool:
    """Return True if the narrative direction contradicts structured.direction.

    BULLISH structured + bearish narrative words -> contradiction.
    BEARISH structured + bullish narrative words -> contradiction.
    NEUTRAL structured -> no contradiction (LLM is free to discuss either side).

    Scope: only text BEFORE a `## Risk Considerations` (or similar) heading is
    scanned. The Risk section legitimately discusses the opposing-direction
    scenario — that is its purpose, not a thesis contradiction.
    """
    if not narrative or structured is None:
        return False
    direction = (structured.direction or "").upper()
    risk_match = _RISK_HEADING_RE.search(narrative)
    text_to_scan = narrative[: risk_match.start()] if risk_match else narrative
    if direction == "BULLISH":
        return bool(_BEARISH_WORDS.search(text_to_scan))
    if direction == "BEARISH":
        return bool(_BULLISH_WORDS.search(text_to_scan))
    return False


async def sanitize_or_retry(
    narrative: str,
    structured: StructuredFields,
    retry_fn: Callable[[], Awaitable[str]],
) -> tuple[str, str]:
    """Sanitize narrative; on contradiction retry once via retry_fn.

    Returns (sanitized_text, status). status is one of:
        "ok"                -> sanitized narrative is safe to emit
        "fallback_data_only" -> retry also contradicted; caller renders fallback
    """
    sanitized = sanitize_narrative(narrative)
    if not detect_contradiction(sanitized, structured):
        return sanitized, "ok"

    log.warning(
        "output_filter: contradiction detected vs direction=%s; retrying once",
        getattr(structured, "direction", "?"),
    )
    try:
        retry_text = await retry_fn()
    except Exception as e:
        log.warning("output_filter: retry_fn raised %s; falling back", e)
        return "", "fallback_data_only"

    sanitized_retry = sanitize_narrative(retry_text or "")
    if not sanitized_retry or detect_contradiction(sanitized_retry, structured):
        return "", "fallback_data_only"
    return sanitized_retry, "ok"


def render_data_only_fallback(
    structured: StructuredFields,
    score_breakdown: ScoreBreakdown,
    sources: list[str],
    sec_evidence_block: Optional[str] = None,
) -> str:
    """Deterministic render used when the narrative is unavailable.

    Direction/confidence/score on two lines by default. When a SEC evidence
    block is supplied (#13), it is appended so insider detail survives the
    low-budget / contradiction data-only fallback.
    """
    direction = getattr(structured, "direction", "NEUTRAL") or "NEUTRAL"
    label = getattr(structured, "confidence_label", "LOW") or "LOW"
    final_score = (
        getattr(score_breakdown, "total", None)
        if score_breakdown is not None
        else None
    )
    score_str = str(final_score) if final_score is not None else "—"
    out = (
        "_(Narrative unavailable for this run — structured signal only.)_\n"
        f"**Direction:** {direction} · **Confidence:** {label} · "
        f"**Score:** {score_str}"
    )
    if sec_evidence_block:
        out += "\n\n**SEC insider activity:**\n" + sec_evidence_block
    return out
