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


def _build_youtube_links_field(yt_signals: list[dict]) -> Optional[dict]:
    """Build the optional "Recent YouTube Coverage" embed field.

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
    yt_field = _build_youtube_links_field(yt_signals or [])
    if yt_field is not None:
        fields.append(yt_field)

    cache_text = _format_cache_age(cache_age_seconds)
    sources_count = len(sources)
    footer_chunks: list[str] = []
    if cache_text:
        footer_chunks.append(cache_text)
    if description_dropped_sources:
        footer_chunks.append(f"Sources: {sources_count} (see vault)")
    else:
        footer_chunks.append(f"sources: {sources_count}")
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    footer_chunks.append(ts)

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
