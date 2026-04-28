"""Ticker grounding — verify a ticker label is literally supported by evidence text.

The LLM (Gemini in v2 + legacy paths, OpenRouter in transcript fallback) emits a
ticker label alongside an evidence string. The label is hallucination-prone; the
evidence string is anchored. This module checks that the label is supported by
the string.

Used by:
- gemini_video_parser._build_evidence_bundle (Path A)
- gemini_video_parser._build_parsed_video (Path B)
- video_parser._parse_llm_response and _fallback_parse (Path C)
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("consensus_engine.analysis.ticker_grounding")

# ─── Alias map ─────────────────────────────────────────────────────────────
# Curated company-name → ticker map for common cases where speakers say the
# company name without the symbol. Loaded from config/ticker_aliases.json so
# operators can add tickers without code changes.
#
# Format: { "TICKER": ["alias1", "alias2", ...] } — aliases stored lowercase
# during runtime normalization.

_DEFAULT_ALIASES_PATH = "config/ticker_aliases.json"


@lru_cache(maxsize=1)
def _load_aliases() -> dict[str, tuple[str, ...]]:
    """Load alias map. Lowercase aliases. Cached for process lifetime."""
    path = Path(_DEFAULT_ALIASES_PATH)
    if not path.exists():
        log.warning("ticker_grounding: alias file %s missing — using empty map", path)
        return {}
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("ticker_grounding: failed to parse %s: %s", path, exc)
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for ticker, aliases in raw.items():
        if not isinstance(aliases, list):
            continue
        norm = tuple(a.strip().lower() for a in aliases if isinstance(a, str) and a.strip())
        if norm:
            out[ticker.upper()] = norm
    return out


def _reset_alias_cache() -> None:
    """Test helper — clear the alias cache so reloads pick up edits."""
    _load_aliases.cache_clear()


# ─── Core grounding API ────────────────────────────────────────────────────

def is_ticker_grounded(ticker: str, text: str) -> bool:
    """True if `ticker` is literally supported by `text`.

    Grounding succeeds if any of:
    - $TICKER appears (e.g., $NVDA)
    - Bare TICKER appears as a word (e.g., NVDA, but not NVDAQ)
    - A registered alias appears as a word (e.g., "nvidia" for NVDA)

    Case-insensitive. Punctuation tolerant. Diacritics not handled (rare in EN
    finance content).
    """
    if not ticker or not text:
        return False
    sym = ticker.strip().upper()
    if not sym:
        return False
    low = text.lower()
    sym_low = sym.lower()

    # $NVDA — strongest signal
    if re.search(rf"\${re.escape(sym_low)}\b", low):
        return True

    # Bare NVDA as a whole word (not part of NVDAQ, etc.)
    if re.search(rf"\b{re.escape(sym_low)}\b", low):
        return True

    # Alias check
    for alias in _load_aliases().get(sym, ()):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return True

    return False


def filter_tickers_by_grounding(
    tickers: list[str], text: str,
) -> tuple[list[str], list[str]]:
    """Split a ticker list into (grounded, dropped).

    Use this when you have a ticker list per evidence span/snippet.
    """
    grounded: list[str] = []
    dropped: list[str] = []
    for t in tickers:
        if is_ticker_grounded(t, text):
            grounded.append(t)
        else:
            dropped.append(t)
    return grounded, dropped


def assert_ticker_grounded_in_any(
    ticker: str, texts: list[str],
) -> bool:
    """True if `ticker` is grounded in at least one of the provided texts.

    Used for video-level allowlisting where a ticker is allowed if grounded in
    title, description, OR any span quote (Layer 3 wires this up).
    """
    return any(is_ticker_grounded(ticker, t) for t in texts if t)


def build_video_allowlist(
    video_title: str,
    video_description: str = "",
    span_quotes: list[str] | None = None,
    extra_texts: list[str] | None = None,
    candidate_tickers: list[str] | None = None,
) -> set[str]:
    """Build the set of tickers acceptably grounded in this video's evidence.

    A ticker is in the allowlist if it is grounded (literal or alias match) in
    any of: title, description, any span quote, any extra text.

    `candidate_tickers`: if provided, restrict the check to this set. Otherwise
    we'd have to enumerate all known tickers — too expensive. In practice the
    caller passes the union of all tickers the LLM claimed.
    """
    if not candidate_tickers:
        return set()
    pool = [video_title or "", video_description or ""]
    pool.extend(q for q in span_quotes or [] if q)
    if extra_texts:
        pool.extend(t for t in extra_texts if t)

    out: set[str] = set()
    for ticker in candidate_tickers:
        if assert_ticker_grounded_in_any(ticker, pool):
            out.add(ticker.upper())
    return out
