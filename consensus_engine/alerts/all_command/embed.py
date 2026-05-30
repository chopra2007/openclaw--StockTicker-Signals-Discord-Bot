"""Discord embed builder for !all command.

Layout:
- color: bullish=0x57F287, bearish=0xED4245, neutral/low_conf=0xFEE75C
- title: "$TICKER — Full Analysis" (cashtag prefix per Ship 1 N1)
- description: optional **TL;DR:** line (Ship 2 M1) + direction line +
  sanitized narrative + score breakdown + sources.
  Truncation order: narrative first to fit 4000 chars; if still over, drop
  sources line (move count to footer); score breakdown ALWAYS stays.
- 3 inline fields: Direction, Confidence, Price (Commit 16 dropped the
  trade-plan-duplicating Buy Zone / SL / TP fields — they now live only in
  the narrative Trade Plan table)
- footer: cache age (if any) + sources count + ISO timestamp

Ship 1 helpers (N1, N2, N3, N4, N5, N7) and Ship 2 helper (TL;DR extraction)
live here so all rendering changes stay in one file per plan
.omc/plans/ship1-ship2-format-narrative.md.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Optional

from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown


COLOR_BULLISH = 0x57F287
COLOR_BEARISH = 0xED4245
COLOR_NEUTRAL = 0xFEE75C

_DESC_LIMIT = 4000
_TRUNC_SUFFIX = " _(see vault for full)_"

# Ship 1 N4 — arrow stays "⇄" when level within this fraction of current price.
_ARROW_TOLERANCE = 0.001  # 0.1 %

# Ship 2 M1 — TL;DR is extracted by matching the literal `**TL;DR:**` prefix
# (case-insensitive) at the start of any line in the narrative.
_TLDR_RE = re.compile(r"(?im)^\s*\*\*TL;DR:\*\*\s*(.+?)$")

# Trade Plan table — match the section header + markdown table that follows.
_TRADE_PLAN_SECTION_RE = re.compile(
    r"(##\s*Trade Plan\s*\n)((?:\|.*\n?)+)",
    re.IGNORECASE,
)


def _reformat_trade_plan(narrative: str) -> str:
    """Replace the verbose markdown table under ## Trade Plan with compact bold lines.

    Input rows look like:  | Buy Zone | $206–$211 | long rationale... |
    Output:
        ## Trade Plan
        **Buy Zone:** $206–$211  ·  **SL:** $196.19
        **TP1:** $218  ·  **TP2:** $226  ·  **TP3:** $233
        **Horizon:** 4–6 days  ·  **Move:** ±$12/5d  ·  **Next Catalyst:** 3 days
    """
    def _replace(m: re.Match) -> str:
        header = m.group(1).rstrip("\n")
        table_text = m.group(2)
        rows: dict[str, str] = {}
        for line in table_text.splitlines():
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) < 2:
                continue
            param, level = cols[0], cols[1]
            if not param or set(param) <= {"-", " "}:  # separator row
                continue
            if param.lower() == "parameter":  # header row
                continue
            rows[param] = level

        lines: list[str] = [header]
        bz = rows.get("Buy Zone", "")
        sl = rows.get("Stop-Loss", rows.get("Stop Loss", rows.get("SL", "")))
        if bz:
            lines.append(f"**Buy Zone:** {bz}")
        if sl:
            lines.append(f"**SL:** {sl}")
        for key in ("TP1", "TP2", "TP3"):
            if rows.get(key):
                lines.append(f"**{key}:** {rows[key]}")
        if rows.get("Horizon"):
            lines.append(f"**Horizon:** {rows['Horizon']}")
        if rows.get("Expected Move"):
            lines.append(f"**Move:** {rows['Expected Move']}")
        nc = rows.get("Next Catalyst", "")
        if nc and nc.lower() not in ("unknown", "—", "-", "n/a", ""):
            lines.append(f"**Next Catalyst:** {nc}")

        return "\n".join(lines) + "\n"

    return _TRADE_PLAN_SECTION_RE.sub(_replace, narrative)


# ---------------------------------------------------------------------------
# Ship 1 helpers
# ---------------------------------------------------------------------------

def _fmt_cashtag(ticker: str) -> str:
    """Ship 1 N1 — return `$TICKER` (idempotent on already-prefixed input)."""
    if not ticker:
        return ""
    t = str(ticker).strip().upper()
    return t if t.startswith("$") else f"${t}"


def _fmt_money_compact(value) -> str:
    """Ship 1 N3 — compact $-notation: 2,400,000 → '$2.4M', 437000 → '$437K'.

    Strips trailing `.0` so whole-number compact values render as `$437K`
    not `$437.0K` (acceptance criterion in US-S1-001).
    """
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if v < 0 else ""
    n = abs(v)

    def _trim(x: float) -> str:
        s = f"{x:.1f}"
        return s[:-2] if s.endswith(".0") else s

    # Boundaries pad by 50 of the next unit so 999_950+ rounds to "1M",
    # not "1000K"; same idea at the K/B edges.
    if n >= 999_500_000:
        return f"{sign}${_trim(n / 1_000_000_000)}B"
    if n >= 999_500:
        return f"{sign}${_trim(n / 1_000_000)}M"
    if n >= 950:
        return f"{sign}${_trim(n / 1_000)}K"
    if n == int(n):
        return f"{sign}${int(n)}"
    return f"{sign}${n:.2f}"


def _direction_emoji(direction: str) -> str:
    """Ship 1 N2 — colored-circle direction emoji (replaces 📈/📉/⏸)."""
    d = (direction or "").upper()
    if d == "BULLISH":
        return "🟢 BULLISH"
    if d == "BEARISH":
        return "🔴 BEARISH"
    return "⚪ NEUTRAL"


def _arrow_for_level(level: Optional[float], current: Optional[float]) -> str:
    """Ship 1 N4 — directional arrow for a price level relative to current_price.

    Returns ↑ when level above spot, ↓ below, ⇄ when within 0.1 % of spot.
    Returns empty string when either value is missing (caller renders plain).
    """
    if level is None or current is None:
        return ""
    try:
        lv = float(level)
        cur = float(current)
    except (TypeError, ValueError):
        return ""
    if cur <= 0:
        return ""
    if abs(lv - cur) / cur <= _ARROW_TOLERANCE:
        return "⇄"
    return "↑" if lv > cur else "↓"


def _level_oneliner(
    field_name: str,
    value: Optional[float],
    current: Optional[float],
    direction: str,
) -> str:
    """Ship 1 N5 — italic one-liner under a level. Empty string when no value."""
    if value is None or current is None:
        return ""
    dir_u = (direction or "").upper()
    fname = (field_name or "").upper()
    if fname == "SL":
        if dir_u == "BULLISH":
            return "_Below this, the thesis is invalidated — exit._"
        if dir_u == "BEARISH":
            return "_Above this, the short thesis breaks — cover._"
        return "_Risk-off level — close the position if breached._"
    if fname == "TP1":
        return "_Primary objective — trim a third to lock in the move._"
    if fname == "TP2":
        return "_Stretch target — trim the next third on touch._"
    if fname == "TP3":
        return "_Home-run target — runners only with a trailing stop._"
    if fname == "BUY ZONE":
        return "_Stage entries inside this band; chase past the high is FOMO._"
    return ""


def _fmt_relative_days(delta: int) -> str:
    """Ship 1 N7 — bucket an integer day delta into relative phrasing.

    today / in 1 session / in N sessions (≤7) / in N days / 1 day ago /
    N days ago.
    """
    if delta == 0:
        return "today"
    if delta == 1:
        return "in 1 session"
    if 2 <= delta <= 7:
        return f"in {delta} sessions"
    if delta > 7:
        return f"in {delta} days"
    if delta == -1:
        return "1 day ago"
    return f"{abs(delta)} days ago"


def _fmt_relative_date(iso_date: Optional[str]) -> str:
    """Ship 1 N7 — relative phrasing for an ISO date string (YYYY-MM-DD).

    Returns the raw input when parsing fails (graceful ISO fallback) and ''
    when no input. Otherwise delegates to `_fmt_relative_days`.
    """
    if not iso_date:
        return ""
    try:
        target = datetime.strptime(str(iso_date)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return str(iso_date)
    return _fmt_relative_days((target - date.today()).days)


# ---------------------------------------------------------------------------
# Ship 2 helper
# ---------------------------------------------------------------------------

def _extract_tldr(narrative: str) -> str:
    """Ship 2 M1 — extract the `**TL;DR:** ...` sentence text from narrative.

    Returns the sentence stripped of the `**TL;DR:**` prefix, or '' when no
    matching line is found. Caller decides how to render or fall back.
    """
    if not narrative:
        return ""
    m = _TLDR_RE.search(narrative)
    if not m:
        return ""
    return m.group(1).strip()


def _strip_tldr(narrative: str) -> str:
    """Remove the matched TL;DR line from the body so it isn't shown twice."""
    if not narrative:
        return ""
    return _TLDR_RE.sub("", narrative, count=1).lstrip("\n")


# ---------------------------------------------------------------------------
# Color + price helpers (unchanged from prior revisions)
# ---------------------------------------------------------------------------

def _color_for(structured: StructuredFields) -> int:
    confidence = (getattr(structured, "confidence_label", "") or "").upper()
    direction = (getattr(structured, "direction", "") or "").upper()
    if confidence == "LOW":
        return COLOR_NEUTRAL
    if direction == "BULLISH":
        return COLOR_BULLISH
    if direction == "BEARISH":
        return COLOR_BEARISH
    return COLOR_NEUTRAL


def _format_price(value: Optional[float]) -> str:
    if value is None:
        return "—"
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def _format_price_with_arrow(
    value: Optional[float],
    current: Optional[float],
) -> str:
    """Render `↑ $185.20` style. Falls back to plain price when no arrow."""
    base = _format_price(value)
    if base == "—":
        return base
    arrow = _arrow_for_level(value, current)
    return f"{arrow} {base}" if arrow else base


def _format_buy_zone(
    low: Optional[float],
    high: Optional[float],
    current: Optional[float] = None,
) -> str:
    """Iter5 + Ship 1 N4: render `⇄ $low – $high` when zone brackets current."""
    if low is None or high is None:
        return "—"
    try:
        lo, hi = float(low), float(high)
    except (TypeError, ValueError):
        return "—"
    if lo == hi:
        base = f"${lo:.2f}"
    else:
        base = f"${lo:.2f} – ${hi:.2f}"
    # ⇄ when the zone straddles current price; ↑/↓ when zone fully above/below.
    if current is not None:
        try:
            cur = float(current)
            if cur > 0:
                if lo <= cur <= hi:
                    return f"⇄ {base}"
                if hi < cur:
                    return f"↓ {base}"
                if lo > cur:
                    return f"↑ {base}"
        except (TypeError, ValueError):
            pass
    return base


_MP_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _fmt_expiry_short(iso: Optional[str]) -> str:
    """'2026-06-19' -> 'Jun 19'. Empty string on bad input."""
    if not iso or not isinstance(iso, str):
        return ""
    parts = iso.split("-")
    if len(parts) != 3:
        return ""
    try:
        return f"{_MP_MONTHS[int(parts[1]) - 1]} {int(parts[2]):02d}"
    except (ValueError, IndexError):
        return ""


def _format_max_pain(mp: Optional[dict], current: Optional[float]) -> str:
    """#6 lever — render the weekly + monthly max-pain strikes with a ↑/↓/⇄
    arrow vs current price. The adjacent Price field supplies the spot context,
    so a strike far from spot (heavy deep-ITM/OTM open interest) reads as a
    direction, not a bug. Returns '—' when no leg is available."""
    if not isinstance(mp, dict):
        return "—"

    def _leg(leg) -> Optional[str]:
        if not isinstance(leg, dict):
            return None
        strike = leg.get("strike")
        if strike is None:
            return None
        try:
            sval = float(strike)
        except (TypeError, ValueError):
            return None
        arrow = _arrow_for_level(sval, current)
        head = f"{arrow} " if arrow else ""
        date = _fmt_expiry_short(leg.get("expiry"))
        tail = f" ({date})" if date else ""
        return f"{head}${sval:g}{tail}"

    lines = []
    wk = _leg(mp.get("weekly"))
    mo = _leg(mp.get("monthly"))
    if wk:
        lines.append(f"wk {wk}")
    if mo:
        lines.append(f"mo {mo}")
    return "\n".join(lines) if lines else "—"


_RS_EMOJI = {"outperforming": "🟢", "underperforming": "🔴", "in-line": "⚪"}


def _format_peer_strength(ps: Optional[dict]) -> str:
    """#6 lever — 'stock% vs <benchmark> bench% (Nd) — verdict'. benchmark_label
    is the peer-group name (clean curated mean) or the ETF symbol (fallback,
    which includes the stock itself — labelled honestly). '—' when unavailable."""
    if not isinstance(ps, dict):
        return "—"
    stock = ps.get("stock_pct")
    bench = ps.get("benchmark_pct")
    label = ps.get("benchmark_label")
    verdict = ps.get("verdict")
    if stock is None or bench is None or not label:
        return "—"
    try:
        s = float(stock)
        b = float(bench)
    except (TypeError, ValueError):
        return "—"
    window = ps.get("window_days", 5)
    emoji = _RS_EMOJI.get(verdict, "")
    head = f"{emoji} " if emoji else ""
    return f"{head}{s:+.1f}% vs {label} {b:+.1f}% ({window}d) — {verdict}"


def _level_value_block(
    field_name: str,
    value: Optional[float],
    current: Optional[float],
    direction: str,
) -> str:
    """Combine arrow+price and italic one-liner into a single field value."""
    line = _format_price_with_arrow(value, current)
    oneliner = _level_oneliner(field_name, value, current, direction)
    return f"{line}\n{oneliner}" if oneliner else line


def _format_cache_age(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return None
    if s < 60:
        return f"cached {s}s ago"
    return f"cached {s // 60}m ago"


def _build_breakdown_inline(score_breakdown: ScoreBreakdown) -> str:
    """Compact one-line breakdown for description."""
    if score_breakdown is None:
        return ""
    parts: list[str] = []
    label_for = {
        "news_catalyst": "news",
        "social_apewisdom": "ape",
        "social_stocktwits": "twits",
        "social_reddit": "reddit",
        "google_trends": "trends",
        "technical": "tech",
        "llm_boost": "llm",
        "options_flow": "opts",
        "consensus_boost": "cons",
    }
    for attr, label in label_for.items():
        try:
            val = int(getattr(score_breakdown, attr, 0) or 0)
        except (TypeError, ValueError):
            continue
        if val:
            parts.append(f"{label}={val}")
    return ", ".join(parts)


_TICKER_ALIAS_PATH = "config/ticker_aliases.json"


def _ticker_aliases(ticker: str) -> list[str]:
    """Return lowercase aliases for a ticker (e.g. NVDA → ['nvidia']).

    Empty list if the ticker isn't in config/ticker_aliases.json. Cheap
    enough to re-read per call — file is ~1KB."""
    import json
    import os
    try:
        path = _TICKER_ALIAS_PATH
        if not os.path.isabs(path):
            # Resolve relative to repo root (where consensus-engine is launched).
            path = os.path.join(os.getcwd(), path)
        with open(path) as f:
            d = json.load(f)
        return [a.lower() for a in d.get(ticker.upper(), [])]
    except (OSError, ValueError):
        return []


def _signal_is_primary_coverage(signal: dict, ticker: str) -> bool:
    """Evidence-based filter: surface a video for `ticker` only if the parser
    captured at least one youtube_evidence_spans row whose tickers_json
    explicitly tags this ticker. That count is pre-computed by
    db.get_youtube_signals_for_ticker as `evidence_spans_for_ticker`.

    Rationale: the youtube_signals table is coarse-grained — when a video
    mentions multiple tickers, the parser creates a row per ticker, and
    those rows can carry mention_count / conviction values that don't
    reliably distinguish "primary topic" from "incidental mention".
    The youtube_evidence_spans table is fine-grained — each row is a
    transcript quote, and tickers_json lists the tickers that specific
    quote actually discusses. Requiring at least one such quote tags
    the ticker means the parser has fine-grained evidence that the
    video discusses it, not just a coarse "I saw this ticker name
    somewhere in the transcript" tag.

    Trade-off: older signals from before the parser started emitting
    evidence spans will have count=0 and be filtered out. That's
    intentional — we'd rather show fewer (correct) results than fill
    the field with false positives. As the parser ingests new videos
    the field will populate naturally.

    The `ticker` param is kept in the signature so future filters that
    incorporate title-match or alias logic can be added without changing
    callers. Currently unused."""
    return (signal.get("evidence_spans_for_ticker") or 0) >= _cfg_min_evidence_spans()


def _cfg_min_evidence_spans() -> int:
    """Minimum quote-level evidence spans required for a signal to surface.
    Threshold is config-driven so it can be raised without code changes."""
    from consensus_engine import config as _cfg
    return int(_cfg.get("all_command.youtube_links.min_evidence_spans", 1))


def _build_youtube_links_field(yt_signals: list[dict], ticker: str = "") -> Optional[dict]:
    """Build the optional "Recent YouTube Coverage" embed field.

    Filters out incidental cross-ticker tags (see _signal_is_primary_coverage)
    so the user only sees videos that actually cover the requested ticker.
    Reads up to `all_command.youtube_links.max_videos` distinct videos from
    yt_signals (dedupe by video_id, preserve query order), formats each as
    a clickable markdown link, returns a Discord field dict or None.

    Shares the rendering contract with cross_reference._build_social_summary
    (Step 11b / Section 2P) — same config keys, same escape helper, same
    NULL-title fallback (channel-name preferred, plain "Video" last resort).
    """
    from consensus_engine import config as _cfg
    from consensus_engine.alerts._markdown import _escape_md_link_text

    if not yt_signals or not _cfg.get("all_command.youtube_links.enabled", True):
        return None

    max_videos = _cfg.get("all_command.youtube_links.max_videos", 3)
    title_max = _cfg.get("all_command.youtube_links.title_max_chars", 80)
    seen: set[str] = set()
    link_lines: list[str] = []
    for s in yt_signals:
        vid = s.get("video_id")
        if not vid or vid in seen:
            continue
        if ticker and not _signal_is_primary_coverage(s, ticker):
            continue
        seen.add(vid)
        url = f"https://www.youtube.com/watch?v={vid}"
        raw_title = s.get("video_title")
        if raw_title:
            text = _escape_md_link_text(raw_title)
            if len(text) > title_max:
                text = text[:title_max] + "…"
        else:
            channel = s.get("channel_name") or "Unknown"
            text = f"Video by {_escape_md_link_text(channel)}"
        link_lines.append(f"• [{text}]({url})")
        if len(link_lines) >= max_videos:
            break

    if not link_lines:
        return None
    return {
        "name": "Recent YouTube Coverage",
        "value": "\n".join(link_lines),
        "inline": False,
    }


def build_embed(
    ticker: str,
    structured: StructuredFields,
    score_breakdown: ScoreBreakdown,
    narrative: str,
    sources_used: list[str],
    cache_age_seconds: Optional[int],
    yt_signals: Optional[list[dict]] = None,
) -> dict:
    """Return a Discord embed payload dict for the !all command."""
    direction = getattr(structured, "direction", "") or ""
    current_price = getattr(structured, "current_price", None)
    direction_line = _direction_emoji(direction)
    breakdown_inline = _build_breakdown_inline(score_breakdown)
    final_score = (
        getattr(score_breakdown, "total", None)
        if score_breakdown is not None
        else None
    )
    score_line = (
        f"**Score:** {final_score} ({breakdown_inline})"
        if final_score is not None and breakdown_inline
        else (f"**Score:** {final_score}" if final_score is not None else "")
    )

    sources = list(sources_used or [])
    sources_line = (
        f"**Sources:** {', '.join(sources[:10])}"
        if sources else ""
    )

    # Ship 2 M1 — pull TL;DR sentence (if narrator emitted it) for the
    # first description line; strip it from the body so it doesn't appear
    # twice. When missing, fall back to the existing direction-line header.
    tldr_text = _extract_tldr(narrative)
    body_narrative = _strip_tldr(narrative) if tldr_text else narrative
    body_narrative = _reformat_trade_plan(body_narrative)
    tldr_line = f"**TL;DR:** {tldr_text}" if tldr_text else ""

    # Build description with truncation order: narrative first, then drop
    # sources line if needed. Score line + TL;DR line always stay.
    description_dropped_sources = False

    def _assemble(narrative_text: str, include_sources: bool) -> str:
        chunks: list[str] = []
        if tldr_line:
            chunks.append(tldr_line)
        chunks.append(direction_line)
        if narrative_text:
            chunks.append(narrative_text)
        if score_line:
            chunks.append(score_line)
        if include_sources and sources_line:
            chunks.append(sources_line)
        return "\n".join(chunks)

    description = _assemble(body_narrative, include_sources=True)
    if len(description) > _DESC_LIMIT:
        # Step 1: truncate narrative
        fixed = _assemble("", include_sources=True)
        budget = _DESC_LIMIT - len(fixed) - len(_TRUNC_SUFFIX) - 1
        if budget > 0 and body_narrative:
            truncated = body_narrative[:budget].rstrip() + _TRUNC_SUFFIX
        else:
            truncated = _TRUNC_SUFFIX.strip()
        description = _assemble(truncated, include_sources=True)
        if len(description) > _DESC_LIMIT:
            # Step 2: drop sources from description
            description_dropped_sources = True
            description = _assemble(truncated, include_sources=False)
            if len(description) > _DESC_LIMIT:
                description = description[:_DESC_LIMIT]

    from consensus_engine import config as _cfg
    _swing_v2 = bool(_cfg.get("all_command.swing_v2_enabled", True))

    # Commit 16: drop the trade-plan-duplicating fields per user feedback
    # post-iter15 — Buy Zone / SL / TP1-3 / Horizon / Next Catalyst /
    # Expected Move are already in the LLM-generated Trade Plan table
    # (with rationale per row). Keeping the same numbers in inline fields
    # was pure visual duplication. Keep only the three fields the table
    # doesn't surface: Direction, Confidence, Price.
    fields = [
        {"name": "Direction", "value": direction_line, "inline": True},
        {"name": "Confidence",
         "value": getattr(structured, "confidence_label", "LOW") or "LOW",
         "inline": True},
        {"name": "Price",
         "value": _format_price(current_price),
         "inline": True},
    ]
    # #6 levers — append only when there's real data (em-dash means no data).
    mp_val = _format_max_pain(getattr(structured, "max_pain", None), current_price)
    if mp_val != "—":
        fields.append({"name": "Max Pain", "value": mp_val, "inline": True})
    rs_val = _format_peer_strength(getattr(structured, "peer_strength", None))
    if rs_val != "—":
        fields.append({"name": "Sector Strength", "value": rs_val, "inline": False})

    yt_field = _build_youtube_links_field(yt_signals or [], ticker=ticker)
    if yt_field is not None:
        fields.append(yt_field)

    sources_count = len(sources)
    footer_chunks: list[str] = []
    if description_dropped_sources:
        footer_chunks.append(f"Sources: {sources_count} (see vault)")
    else:
        footer_chunks.append(f"Sources: {sources_count}")

    return {
        "title": f"{_fmt_cashtag(ticker)} — Full Analysis",
        "color": _color_for(structured),
        "description": description,
        "fields": fields,
        "footer": {"text": " | ".join(footer_chunks)},
    }


def _level_value_block_zone(
    low: Optional[float],
    high: Optional[float],
    current: Optional[float],
    direction: str,
) -> str:
    """Buy Zone variant of _level_value_block — uses _format_buy_zone for line."""
    line = _format_buy_zone(low, high, current)
    oneliner = _level_oneliner("BUY ZONE", low, current, direction)
    return f"{line}\n{oneliner}" if oneliner else line
