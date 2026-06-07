"""Deterministic video classifier (Stage B of v2 two-stage pipeline).

Converts evidence spans emitted by Stage A (Gemini evidence extractor) into
CandidateSignal / CandidateLevel / CandidateSetup / CandidateCatalyst objects
plus a MacroThesis. Classification is done here — in pure Python — so every
rule is testable in isolation, auditable, and reversible via suppression.

Rules are intentionally lexical + shallow rather than learned. If a rule
cannot decide, it either leaves the decision to the read-time filter
(via `suppressed=True`) or lowers classifier_confidence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from consensus_engine.models import (
    CATALYST_TYPES,
    CandidateCatalyst,
    CandidateLevel,
    CandidateSetup,
    CandidateSignal,
    Conviction,
    Direction,
    EvidenceBundle,
    EvidenceSpan,
    LEVEL_TYPES,
    MacroThesis,
)

log = logging.getLogger("consensus_engine.analysis.video_classifier")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    """Aggregate output of Stage B for one video."""
    signals: list[CandidateSignal] = field(default_factory=list)
    levels: list[CandidateLevel] = field(default_factory=list)
    setups: list[CandidateSetup] = field(default_factory=list)
    catalyst_candidates: list[CandidateCatalyst] = field(default_factory=list)
    macro_thesis: MacroThesis | None = None


# ---------------------------------------------------------------------------
# Keyword lexicons
# ---------------------------------------------------------------------------

_BULLISH_KW = {
    "bullish", "long", "buy", "calls", "breakout", "rally", "uptrend",
    "draft pick", "top pick", "beaten down unfairly", "favorite", "conviction",
    "upside", "higher", "ath", "all-time high",
}

_BEARISH_KW = {
    "bearish", "short", "puts", "fade", "downside", "breakdown", "selloff",
    "sell-off", "crash", "lower", "capping",
}

_FORWARD_SHORT_RE = re.compile(
    r"(going to|will|would|i'?d|let'?s|if it|set up to|target|bias to)"
    r".{0,40}"
    r"(short|put|puts|fade|sell|lower|below|downside|breakdown)",
    re.IGNORECASE,
)

_NEGATION_RE = re.compile(
    r"(don'?t|do not|not|never|no)\s+\w{0,20}?"
    r"(long|short|buy|sell|bullish|bearish)",
    re.IGNORECASE,
)

_PAST_TENSE_RECAP_RE = re.compile(
    r"\b(was|is|were|has been|had been|got|fell|dropped|rallied|jumped|closed)\s+"
    r"\w{0,30}(up|down|higher|lower)\b",
    re.IGNORECASE,
)

_CONVICTION_UPGRADE_KW = {
    "number one", "#1", "my favorite", "top pick", "draft pick",
    "high conviction", "my conviction",
}

_MACRO_KW = {
    "market", "s&p", "sp500", "spx", "spy", "nasdaq", "ndx", "qqq",
    "sector", "rotation", "macro", "fed", "fomc", "inflation", "vix",
    "yield", "yields", "bonds", "treasury",
}

# Level-type context phrases (each maps to level_type + base confidence weight).
_RESISTANCE_KW = {"resistance", "ceiling", "overhead", "capping"}
_SUPPORT_KW = {
    "support", "floor", "fomo", "defended", "pullback to", "buyers at",
    "hold ", "holding", "bounce off", "bounced off",
}
_EMA_RE = re.compile(r"\b(?:\d{1,3}[- ])?ema\b|(?:\d+)[- ]period\s+ema", re.IGNORECASE)
_MA_RE = re.compile(
    r"\b(moving average|sma|\d{1,3}[- ]day\s+ma|simple moving|exponential moving)\b",
    re.IGNORECASE,
)
_TARGET_KW = {"target", "objective", "going to", "draft pick", "upside to"}
_BREAKDOWN_KW = {"breakdown", "broken below", "below", "loses", "losing"}

# "7,000 level" / "at the N level" — generic support when price is above (prior-ATH logic).
_GENERIC_LEVEL_RE = re.compile(
    r"(at the|the)\s+[\d,.]+\s+level\b", re.IGNORECASE
)
# "today's high was N" / "high of N" / "the high" — recent rejection = resistance.
_RECENT_HIGH_RE = re.compile(
    r"\b(high\s+(?:was|of|today|yesterday)|today'?s\s+high|the\s+high\s+(?:was|today))\b",
    re.IGNORECASE,
)

# Setup component keywords
_ENTRY_KW = {"entry", "get in", "enter", "buying at", "start buying", "long at"}
_STOP_KW = {"stop", "stop loss", "invalidation", "invalidate", "below"}
# For targets inside setup detection we reuse _TARGET_KW.

_CATALYST_KW_MAP: list[tuple[str, set[str]]] = [
    ("earnings", {"earnings", "eps", "report", "quarterly"}),
    ("fed", {"fed", "fomc", "powell", "rate decision", "rate hike", "rate cut"}),
    ("cpi", {"cpi", "inflation print", "ppi"}),
    ("jobs", {"jobs", "nfp", "non-farm", "nonfarm", "unemployment"}),
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return (text or "").lower()


def _any_kw(text: str, kws: set[str]) -> bool:
    low = _normalize(text)
    return any(k in low for k in kws)


def _count_kw(text: str, kws: set[str]) -> int:
    low = _normalize(text)
    return sum(low.count(k) for k in kws)


# Tickers whose index/name *contains* a number → the number is a name, not a price.
# e.g. "Nasdaq 100" appears in every NDX mention but 100 is not a level.
_TICKER_NAME_NUMBERS: dict[str, set[float]] = {
    "NDX": {100.0},
    "QQQ": {100.0},
    "SPX": {500.0},
    "SPY": {500.0},
    "RUT": {2000.0},
    "XLK": {50.0},
    "XLF": {50.0},
    "XLE": {50.0},
}


def _is_plausible_price(span: EvidenceSpan, number: float, ticker: str) -> bool:
    """Reject numbers that are obviously not price levels.

    A number from Stage A's raw ``numbers[]`` is only a valid level candidate if
    it passes sanity checks:
      - Not the index's own name number ("Nasdaq 100" → 100 isn't a price for NDX).
      - Not a percentage ("down 18%" → 18 isn't a level).
      - Not a small integer count ("11 sectors", "four charts", "23 days").
      - Tiny values (< $10) only allowed when a dollar sign or 'dollar' sits
        within a short window of the number in the quote.
    """
    if number <= 0:
        return False
    quote = span.quote or ""
    low = quote.lower()

    # Index/ETF "name numbers" — e.g. the 100 in "Nasdaq 100".
    named_numbers = _TICKER_NAME_NUMBERS.get(ticker.upper(), set())
    if number in named_numbers and f"{ticker.lower()} {int(number)}" in low.replace(",", ""):
        return False
    # Explicit "Nasdaq 100" phrase — hits for any ticker but SPX/NDX context.
    if number == 100.0 and "nasdaq 100" in low:
        return False

    # Context window around the number for "%", "$", "percent" detection.
    ctx = _window_around(quote, number)
    ctx_low = ctx.lower()
    # If followed by % / percent → it's a percentage, not a price.
    num_str_candidates = [str(int(number)) if float(number).is_integer() else None,
                          f"{number:.2f}", f"{number:g}"]
    for cand in filter(None, num_str_candidates):
        idx = ctx.find(cand)
        if idx >= 0:
            tail = ctx[idx + len(cand): idx + len(cand) + 8].lstrip()
            if tail.startswith("%") or tail.startswith(" %") or tail.lower().startswith("percent"):
                return False
            # "up 18" / "down 18" — likely a percentage even without %.
            head = ctx[max(0, idx - 12): idx].lower()
            if any(kw in head for kw in ("up ", "down ", "gain", "lost", "loss ", "fell ", "rose ", "dropped ")):
                if "$" not in head:
                    return False
            break

    # Integer count heuristics — "11 sectors", "four charts", "23 days".
    # If number is a small integer AND a count word follows within 25 chars.
    if float(number).is_integer() and number <= 50:
        # look within 35 chars after the number
        for cand in filter(None, num_str_candidates):
            idx = ctx.find(cand)
            if idx >= 0:
                tail = ctx[idx + len(cand): idx + len(cand) + 40].lower()
                count_words = ("sector", "chart", "day", "week", "month", "year", "point",
                               "bar", "candle", "stock", "minute", "hour", "times", "ticker",
                               "reason", "thing", "line", "level")
                # "level" is tricky — speakers say "the 7,000 level" meaning price.
                # So require the count word to be NOT preceded by "the/at the/this".
                for cw in count_words:
                    if cw in tail:
                        head = ctx[max(0, idx - 15): idx].lower().rstrip()
                        if cw == "level":
                            # "at the 7000 level" / "the 7000 level" → it IS a price.
                            if "the " in head or " at " in head or head.endswith("at"):
                                continue
                        return False
                break

    # Tiny values: < 10 require explicit $ or "dollar" near the number.
    if number < 10:
        if "$" not in ctx and "dollar" not in ctx_low:
            return False

    return True


def _window_around(quote: str, number: float) -> str:
    """Return ±40 char context window around the first occurrence of `number`."""
    s = quote
    # Try a few textual forms of the number.
    candidates: list[str] = []
    if float(number).is_integer():
        candidates.append(str(int(number)))
    candidates.append(f"{number:.2f}")
    candidates.append(f"{number:g}")
    for cand in candidates:
        idx = s.find(cand)
        if idx >= 0:
            lo = max(0, idx - 40)
            hi = min(len(s), idx + len(cand) + 40)
            return s[lo:hi]
    return s  # fall back to full quote


# ---------------------------------------------------------------------------
# Rule 1 — direction + conviction
# ---------------------------------------------------------------------------

def _classify_direction(
    spans: list[EvidenceSpan], ticker: str
) -> tuple[Direction, Conviction, float, int, str]:
    """Classify direction + conviction for a single ticker from its spans.

    Returns (direction, conviction, confidence, mention_count, context_quote).
    Applies forward-looking-verb check and negation to avoid false short signals.
    """
    mention_count = 0
    bull_score = 0
    bear_score = 0
    forward_short = False
    negated = False
    recap_only = True  # set False once a non-recap bullish/bearish quote shows up
    context_quote = ""

    for sp in spans:
        if ticker not in sp.tickers:
            continue
        mention_count += 1
        quote = sp.quote or ""
        if not context_quote:
            context_quote = quote

        bs = _count_kw(quote, _BULLISH_KW)
        ss = _count_kw(quote, _BEARISH_KW)
        bull_score += bs
        bear_score += ss

        if _NEGATION_RE.search(quote):
            negated = True
        if _FORWARD_SHORT_RE.search(quote):
            forward_short = True
        # A quote is "recap-only" if it's all past-tense descriptive ("oil was
        # down 18%") with no forward-looking verb near a bearish keyword.
        if (bs or ss) and not _PAST_TENSE_RECAP_RE.search(quote):
            recap_only = False

    if mention_count == 0:
        return Direction.NEUTRAL, Conviction.LOW, 0.0, 0, ""

    # Decide direction.
    if negated:
        direction = Direction.NEUTRAL
    elif bull_score > bear_score:
        direction = Direction.LONG
    elif bear_score > bull_score and forward_short and not recap_only:
        direction = Direction.SHORT
    else:
        direction = Direction.NEUTRAL

    # Conviction from mention_count, with upgrade for strong conviction phrases.
    if mention_count >= 4:
        conviction = Conviction.HIGH
    elif mention_count >= 2:
        conviction = Conviction.MEDIUM
    else:
        conviction = Conviction.LOW
    if any(_any_kw(sp.quote, _CONVICTION_UPGRADE_KW)
           for sp in spans if ticker in sp.tickers):
        conviction = {
            Conviction.LOW: Conviction.MEDIUM,
            Conviction.MEDIUM: Conviction.HIGH,
            Conviction.HIGH: Conviction.HIGH,
        }[conviction]

    # Confidence: ratio of dominant-side score to total keyword hits, floor 0.2.
    total_kw = bull_score + bear_score
    if direction == Direction.NEUTRAL:
        confidence = 0.3 if total_kw == 0 else 0.4
    else:
        dominant = bull_score if direction == Direction.LONG else bear_score
        confidence = min(1.0, 0.4 + 0.1 * dominant) if total_kw else 0.3
    return direction, conviction, round(confidence, 3), mention_count, context_quote


# ---------------------------------------------------------------------------
# Rule 2 — level-type classification
# ---------------------------------------------------------------------------

def _classify_level_type(
    span: EvidenceSpan, number: float
) -> tuple[str, float]:
    """Classify a (ticker, number) pair as one of LEVEL_TYPES.

    Returns (level_type, confidence). Defaults to ('target', 0.3) if ambiguous —
    callers can downgrade based on classifier_confidence at read time.
    """
    ctx = _window_around(span.quote or "", number)
    low = ctx.lower()

    # Check EMA/MA first — they are TA constructs tagged separately.
    if _EMA_RE.search(low):
        return "ema", 0.9
    if _MA_RE.search(low):
        return "ma", 0.85

    # Breakdown wins over support when negation/below framing present.
    if _any_kw(low, _BREAKDOWN_KW) and ("below" in low or "broken" in low):
        return "breakdown", 0.8

    # Recent-high framing: "today's high was 7147" or "the high of 7147" —
    # price has already been rejected at this level, so it is resistance.
    if _RECENT_HIGH_RE.search(low):
        return "resistance", 0.75

    if _any_kw(low, _RESISTANCE_KW):
        return "resistance", 0.85
    if "above" in low and number > 0:
        # "above N" framing with no bullish support keyword usually = resistance.
        if not _any_kw(low, _SUPPORT_KW):
            return "resistance", 0.6

    if _any_kw(low, _SUPPORT_KW):
        return "support", 0.85
    # Prior-ATH framing → support if price currently above.
    if ("all-time high" in low or "ath" in low) and "above" not in low:
        return "support", 0.6
    # "at the N level" / "the 7,000 level" — generic psychological level.
    # When price broke through without reaction (speaker's framing), it
    # becomes prior-resistance-now-support. We tag as support with moderate
    # confidence so downstream alerts can surface it.
    if _GENERIC_LEVEL_RE.search(low) or " level" in low:
        return "support", 0.5

    if _any_kw(low, _TARGET_KW):
        return "target", 0.7

    # Fallback — unclassified but we keep the row.
    return "target", 0.3


# ---------------------------------------------------------------------------
# Rule 3 — setup clustering
# ---------------------------------------------------------------------------

def _classify_component(span: EvidenceSpan, number: float) -> str | None:
    """Return one of {entry, stop, target} for a number inside a span, or None.

    Uses the closest component keyword that precedes the number in the quote so
    that a single sentence like "entry 400 stop 389 target 450" correctly
    tags each of its numbers.
    """
    quote = (span.quote or "").lower()
    candidates: list[str] = []
    if float(number).is_integer():
        candidates.append(str(int(number)))
    candidates.append(f"{number:.2f}")
    candidates.append(f"{number:g}")
    idx = -1
    for cand in candidates:
        idx = quote.find(cand)
        if idx >= 0:
            break
    if idx < 0:
        return None
    before = quote[max(0, idx - 30):idx]
    # "entry target at N" — compound phrase where the number is the entry, not a
    # separate target. Restrict to short tail so "entry at 400 target 450" still
    # tags 450 as a real target rather than entry.
    tail = before[-16:]
    if "entry target" in tail or "entry price" in tail:
        return "entry"
    # Pick the latest (nearest-to-number) keyword that appears in `before`.
    component_kws = [
        ("stop", ("stop", "invalidation", "invalidate")),
        ("entry", ("entry", "enter", "get in", "buying at", "long at")),
        ("target", ("target", "going to", "objective", "upside to")),
    ]
    best_comp: str | None = None
    best_pos: int = -1
    for comp, kws in component_kws:
        for kw in kws:
            p = before.rfind(kw)
            if p > best_pos:
                best_pos = p
                best_comp = comp
    return best_comp


def _cluster_setups(
    spans: list[EvidenceSpan], ticker: str, window_sec: int = 90
) -> list[CandidateSetup]:
    """Cluster nearby spans for `ticker` into trade setups.

    Requires ≥2 of {entry, stop, target, catalyst_date} — matching the v2 plan.
    Absorbed levels are *not* deleted here; the DB helper
    `mark_levels_absorbed_by_setup` handles that at persistence time.
    """
    ticker_spans = [sp for sp in spans if ticker in sp.tickers]
    if not ticker_spans:
        return []
    ticker_spans.sort(key=lambda s: s.ts_sec)

    clusters: list[list[EvidenceSpan]] = []
    current: list[EvidenceSpan] = []
    last_ts: int | None = None
    for sp in ticker_spans:
        if last_ts is None or sp.ts_sec - last_ts <= window_sec:
            current.append(sp)
        else:
            clusters.append(current)
            current = [sp]
        last_ts = sp.ts_sec
    if current:
        clusters.append(current)

    setups: list[CandidateSetup] = []
    for cluster in clusters:
        entries: list[float] = []
        stops: list[float] = []
        targets: list[float] = []
        ctx_snippets: list[str] = []
        span_ids: list[int] = []
        catalyst_date: str | None = None
        catalyst_desc: str | None = None
        first_ts = cluster[0].ts_sec

        for sp in cluster:
            ctx_snippets.append(sp.quote)
            if sp.dates_mentioned and catalyst_date is None:
                catalyst_date = sp.dates_mentioned[0]
                catalyst_desc = sp.quote
            for n in sp.numbers:
                comp = _classify_component(sp, n)
                if comp == "entry":
                    entries.append(n)
                elif comp == "stop":
                    stops.append(n)
                elif comp == "target":
                    targets.append(n)
            # track positional index for provenance (caller can remap to DB ids)
            span_ids.append(cluster.index(sp))

        components_present = sum(bool(x) for x in [entries, stops, targets])
        has_date = catalyst_date is not None
        # Require ≥2 of {entry, stop, target, catalyst_date}
        if components_present + (1 if has_date else 0) < 2:
            continue

        entry_low = min(entries) if entries else None
        entry_high = max(entries) if entries else None
        stop = stops[0] if stops else None
        rr: float | None = None
        if entry_low is not None and stop is not None and targets:
            risk = abs(entry_low - stop)
            reward = abs(targets[0] - entry_low)
            rr = round(reward / risk, 3) if risk else None

        confidence = 0.4 + 0.2 * components_present  # 0.6..1.0
        setups.append(CandidateSetup(
            ticker=ticker,
            entry_low=entry_low,
            entry_high=entry_high,
            stop=stop,
            targets=targets,
            timeframe=None,
            setup_type=None,
            catalyst_date=catalyst_date,
            catalyst_desc=catalyst_desc,
            context=" | ".join(ctx_snippets)[:500],
            evidence_span_ids=[],  # filled by caller with real DB ids
            classifier_confidence=round(min(1.0, confidence), 3),
            video_timestamp_sec=first_ts,
            risk_reward=rr,
        ))
    return setups


# ---------------------------------------------------------------------------
# Rule 4 — catalyst candidates
# ---------------------------------------------------------------------------

def _infer_catalyst_type(quote: str) -> str:
    low = (quote or "").lower()
    for label, kws in _CATALYST_KW_MAP:
        if any(k in low for k in kws):
            return label
    return "other"


def _extract_catalyst_candidates(
    spans: list[EvidenceSpan],
) -> list[CandidateCatalyst]:
    """One CandidateCatalyst per (ticker, mentioned_date). Dates resolved later.

    Skip spans whose only "ticker" is an empty placeholder — those produce
    catalyst rows with ticker="" that add no alerting value.
    """
    out: list[CandidateCatalyst] = []
    seen: set[tuple[str, str]] = set()
    for sp in spans:
        if not sp.dates_mentioned:
            continue
        if not sp.tickers:
            continue  # un-tickered date mentions produce noise — drop.
        for ticker in sp.tickers:
            if not ticker:
                continue
            for date in sp.dates_mentioned:
                key = (ticker, date)
                if key in seen:
                    continue
                seen.add(key)
                out.append(CandidateCatalyst(
                    ticker=ticker,
                    catalyst_type=_infer_catalyst_type(sp.quote),
                    mentioned_date=date,
                    resolved_date=None,
                    verified=0,
                    context_text=sp.quote,
                    evidence_span_ids=[],  # caller maps to DB ids
                    video_timestamp_sec=sp.ts_sec,
                ))
    return out


# ---------------------------------------------------------------------------
# Rule 5 — macro thesis
# ---------------------------------------------------------------------------

_MACRO_BULL_KW = {
    "bullish", "rally", "rallying", "breakout", "uptrend", "all-time high",
    "new high", "risk on", "risk-on", "buyers", "strong", "moving higher",
    "advancing", "FOMO",
}
_MACRO_BEAR_KW = {
    "bearish", "selloff", "sell-off", "crash", "downtrend", "risk off",
    "risk-off", "capping", "topped", "exhaustion", "breakdown",
}


def _build_macro_thesis(spans: list[EvidenceSpan]) -> MacroThesis:
    macro_spans = [sp for sp in spans if _any_kw(sp.quote, _MACRO_KW)]
    if not macro_spans:
        return MacroThesis(
            direction=Direction.NEUTRAL, themes=[], timeframe="short",
            summary="", narrative="",
        )
    # Direction from macro-specific lexicon. General bull/bear words ("lower",
    # "higher", "below", "above") trip on recap language and mislead the tally,
    # so use tighter macro-only keywords here.
    bull = sum(_count_kw(sp.quote, _MACRO_BULL_KW) for sp in macro_spans)
    bear = sum(_count_kw(sp.quote, _MACRO_BEAR_KW) for sp in macro_spans)
    if bull > bear:
        direction = Direction.LONG
    elif bear > bull * 1.3:  # small bearish lead isn't enough on macro — require clear margin
        direction = Direction.SHORT
    else:
        direction = Direction.NEUTRAL

    # Themes — pick up to 3 distinct macro keywords actually mentioned.
    themes: list[str] = []
    for sp in macro_spans:
        for kw in _MACRO_KW:
            if kw in sp.quote.lower() and kw not in themes:
                themes.append(kw)
                if len(themes) >= 3:
                    break
        if len(themes) >= 3:
            break

    # Narrative: up to 5 macro quotes PLUS any span carrying a speaker-
    # specific phrase we want to surface verbatim (e.g. "Sellers Shut Off",
    # "draft pick", "Virgin POC"). Ordered by timestamp, deduped.
    signature_phrases = (
        "sellers shut off", "draft pick", "virgin poc", "fomo",
        "piling on", "iceberg tick",
    )
    signature_spans = [
        sp for sp in spans
        if any(ph in (sp.quote or "").lower() for ph in signature_phrases)
    ]
    selected = list(macro_spans[:5])
    for sp in signature_spans:
        if sp not in selected:
            selected.append(sp)
    selected.sort(key=lambda s: s.ts_sec)
    seen_quotes: set[str] = set()
    narrative_quotes: list[str] = []
    for sp in selected:
        q = (sp.quote or "").strip()
        if not q or q in seen_quotes:
            continue
        seen_quotes.add(q)
        narrative_quotes.append(q)
    summary = narrative_quotes[0] if narrative_quotes else ""
    narrative = " ".join(narrative_quotes)
    return MacroThesis(
        direction=direction,
        themes=themes,
        timeframe="short",
        summary=summary,
        narrative=narrative,
    )


# ---------------------------------------------------------------------------
# Rule 6 — suppression + dedup
# ---------------------------------------------------------------------------

def _suppress_weak_signals(signals: list[CandidateSignal]) -> None:
    """In-place suppression — keep rows, annotate reason, don't delete.

    Suppression rules:
    - direction=neutral + conviction=low -> "neutral_low" (classic noise)
    - direction=neutral at any conviction -> "neutral_direction"
      Rationale: a neutral direction carries no trading edge regardless of
      how often the ticker was mentioned. These rows persist for audit but
      do not drive alerts.
    """
    for sig in signals:
        if sig.direction == Direction.NEUTRAL and sig.conviction == Conviction.LOW:
            sig.suppressed = True
            sig.suppression_reason = "neutral_low"
        elif sig.direction == Direction.NEUTRAL:
            sig.suppressed = True
            sig.suppression_reason = "neutral_direction"


def _suppress_near_price_dedup(
    levels: list[CandidateLevel], pct_window: float = 0.005
) -> None:
    """Within same ticker+level_type, mark duplicates within ±0.5% as suppressed."""
    by_key: dict[tuple[str, str], list[CandidateLevel]] = {}
    for lvl in levels:
        by_key.setdefault((lvl.ticker, lvl.level_type), []).append(lvl)
    for group in by_key.values():
        group.sort(key=lambda l: l.price)
        kept_prices: list[float] = []
        for lvl in group:
            if any(abs(lvl.price - kp) <= pct_window * max(kp, 1e-9)
                   for kp in kept_prices):
                lvl.suppressed = True
                lvl.suppression_reason = "near_price_dedup"
            else:
                kept_prices.append(lvl.price)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _unique_tickers(spans: list[EvidenceSpan]) -> list[str]:
    seen: list[str] = []
    for sp in spans:
        for t in sp.tickers:
            if t and t not in seen:
                seen.append(t)
    return seen


def classify_evidence(bundle: EvidenceBundle) -> ClassificationResult:
    """Main entry point — classify Stage A evidence into Stage B candidates."""
    spans = bundle.spans or []
    tickers = _unique_tickers(spans)

    signals: list[CandidateSignal] = []
    levels: list[CandidateLevel] = []
    setups: list[CandidateSetup] = []

    for ticker in tickers:
        direction, conviction, conf, count, ctx = _classify_direction(spans, ticker)
        first_ts = next(
            (sp.ts_sec for sp in spans if ticker in sp.tickers), None
        )
        signals.append(CandidateSignal(
            ticker=ticker,
            direction=direction,
            conviction=conviction,
            mention_count=count,
            context=ctx,
            evidence_span_ids=[],
            classifier_confidence=conf,
            video_timestamp_sec=first_ts,
        ))

        for sp in spans:
            if ticker not in sp.tickers:
                continue
            for n in sp.numbers:
                if not _is_plausible_price(sp, n, ticker):
                    continue
                level_type, level_conf = _classify_level_type(sp, n)
                if level_type not in LEVEL_TYPES:
                    continue
                levels.append(CandidateLevel(
                    ticker=ticker,
                    level_type=level_type,
                    price=n,
                    context=sp.quote,
                    evidence_span_ids=[],
                    classifier_confidence=level_conf,
                    video_timestamp_sec=sp.ts_sec,
                ))

        setups.extend(_cluster_setups(spans, ticker))

    catalyst_candidates = _extract_catalyst_candidates(spans)
    # Validate catalyst_type against taxonomy.
    for cat in catalyst_candidates:
        if cat.catalyst_type not in CATALYST_TYPES:
            cat.catalyst_type = "other"

    # Resolve raw setup.catalyst_date ("April 29") to ISO ("2026-04-29") using
    # the same sync resolver the async catalyst pipeline uses. This lets
    # setup-derived alerts carry a machine-readable catalyst date without
    # waiting for the downstream async resolver pass.
    if getattr(bundle, "publish_ts", None):
        try:
            from consensus_engine.analysis.catalyst_resolver import (
                _parse_publish_ts, _resolve_relative_date,
            )
            publish_dt = _parse_publish_ts(bundle.publish_ts)
            for s in setups:
                if s.catalyst_date and not s.catalyst_date.startswith("20"):
                    resolved = _resolve_relative_date(s.catalyst_date, publish_dt)
                    if resolved:
                        s.catalyst_date = resolved
        except Exception as e:
            log.debug("classify_evidence: setup catalyst date resolve failed: %s", e)

    macro = _build_macro_thesis(spans)

    _suppress_weak_signals(signals)
    _suppress_near_price_dedup(levels)

    return ClassificationResult(
        signals=signals,
        levels=levels,
        setups=setups,
        catalyst_candidates=catalyst_candidates,
        macro_thesis=macro,
    )


# ---------------------------------------------------------------------------
# A2: on-screen chart numbers -> structured price levels
# ---------------------------------------------------------------------------

def classify_visual_levels(
    visual_rows: list[dict],
    top_ticker: str,
    live_price: float | None,
    *,
    band_pct: float = 0.10,
    confidence: float = 0.55,
    max_levels: int = 20,
    ticker_prices: dict[str, float | None] | None = None,
) -> list[CandidateLevel]:
    """Turn Gemini-read on-screen chart PRICE numbers into structured levels.

    The visual-evidence branch (`youtube_visual_evidence`) captures numbers
    Gemini reads off the chart -- axis labels, fib levels, drawn price lines --
    that are never spoken. The spoken-span classifier (`classify_evidence`)
    never sees them, so they never reach `youtube_levels`. This files them so
    they participate in scoring / cross-reference, not just the alert text.

    Attribution is Conservative: the caller passes the video's single
    top-mentioned ticker and every kept level is attached to it.

    A live price anchor is required to separate real drawn levels from Y-axis
    gridlines (0/10/20 on a $98 stock) and numbers belonging to a *different*
    ticker the video also covered: a `kind=='price'` value is kept only within
    `band_pct` of `live_price`. With no anchor we cannot tell a gridline from a
    real level, so nothing is filed (the narrator path still shows the raw
    numbers as text).

    `level_type` is derived from the anchor: below price -> support, else
    resistance. Confidence is held below the spoken-classifier tier so a visual
    level never outranks a level the analyst actually spoke.

    B3 #13 (gated by the caller via `youtube.visual.tag_structured_levels`):
    when `ticker_prices` is provided, a row that carries its own per-number
    `ticker` tag (`row.get("ticker")`) whose ticker has a usable anchor in the
    map is filed under THAT ticker using THAT ticker's anchor for the proximity
    band — not `top_ticker`/`live_price`. Untagged rows (and every row when
    `ticker_prices` is None) keep top-ticker attribution exactly as before, so
    with no map / no tags the output is byte-identical to pre-B3 behavior.
    """
    if not visual_rows or not top_ticker:
        return []
    if not live_price or live_price <= 0:
        return []
    out: list[CandidateLevel] = []
    seen: set[tuple[str, float]] = set()
    for row in visual_rows:
        if not isinstance(row, dict):
            continue
        if (row.get("kind") or "").strip().lower() != "price":
            continue
        raw = str(row.get("value", "")).replace(",", "").replace("$", "").strip()
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val <= 0:
            continue
        # Resolve the attribution ticker + its anchor. Default = top-ticker
        # (pre-B3 behavior). A per-row tag only diverts when ticker_prices is
        # supplied AND that ticker has a usable (>0) anchor.
        row_ticker = top_ticker
        anchor = live_price
        if ticker_prices:
            tag = (row.get("ticker") or "").strip().upper()
            if tag and tag != top_ticker:
                tagged_anchor = ticker_prices.get(tag)
                if tagged_anchor and tagged_anchor > 0:
                    row_ticker = tag
                    anchor = tagged_anchor
        if abs(val / anchor - 1.0) > band_pct:
            continue  # gridline / mis-scaled / wrong-ticker -> not a real level
        key = (row_ticker, round(val, 2))
        if key in seen:
            continue
        seen.add(key)
        where = row.get("where_seen") or row.get("where") or "chart"
        ts = row.get("ts_sec")
        out.append(
            CandidateLevel(
                ticker=row_ticker,
                level_type="support" if val < anchor else "resistance",
                price=val,
                context=f"chart shows {val} ({where})",
                evidence_span_ids=[],
                classifier_confidence=confidence,
                suppressed=False,
                suppression_reason=None,
                video_timestamp_sec=int(ts) if isinstance(ts, (int, float)) else None,
            )
        )
        if len(out) >= max_levels:
            break
    return out
