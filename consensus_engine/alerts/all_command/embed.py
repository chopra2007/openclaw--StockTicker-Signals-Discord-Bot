"""Discord embed builder for !all command.

Layout:
- color: bullish=0x57F287, bearish=0xED4245, neutral/low_conf=0xFEE75C
- title: "${TICKER} — Full Analysis"
- description: direction line + sanitized narrative + score breakdown + sources
  Truncation order: narrative first to fit 4000 chars; if still over, drop
  sources line (move count to footer); score breakdown ALWAYS stays.
- 8 inline fields: Direction, Confidence, Timeframe, Magnitude, SL, TP1, TP2, TP3
- footer: cache age (if any) + sources count + ISO timestamp
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown


COLOR_BULLISH = 0x57F287
COLOR_BEARISH = 0xED4245
COLOR_NEUTRAL = 0xFEE75C

_DESC_LIMIT = 4000
_TRUNC_SUFFIX = " _(see vault for full)_"


def _direction_emoji(direction: str) -> str:
    d = (direction or "").upper()
    if d == "BULLISH":
        return "📈 BULLISH"
    if d == "BEARISH":
        return "📉 BEARISH"
    return "⏸ NEUTRAL"


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


def _format_buy_zone(low: Optional[float], high: Optional[float]) -> str:
    """Iter5: render `$low – $high` for the entry bracket; `—` if missing."""
    if low is None or high is None:
        return "—"
    try:
        lo, hi = float(low), float(high)
    except (TypeError, ValueError):
        return "—"
    if lo == hi:
        return f"${lo:.2f}"
    return f"${lo:.2f} – ${hi:.2f}"


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


def build_embed(
    ticker: str,
    structured: StructuredFields,
    score_breakdown: ScoreBreakdown,
    narrative: str,
    sources_used: list[str],
    cache_age_seconds: Optional[int],
) -> dict:
    """Return a Discord embed payload dict for the !all command."""
    direction_line = _direction_emoji(getattr(structured, "direction", ""))
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

    # Build description with truncation order: narrative first, then drop
    # sources line if needed. Score line always stays.
    description_dropped_sources = False

    def _assemble(narrative_text: str, include_sources: bool) -> str:
        chunks = [direction_line]
        if narrative_text:
            chunks.append(narrative_text)
        if score_line:
            chunks.append(score_line)
        if include_sources and sources_line:
            chunks.append(sources_line)
        return "\n".join(chunks)

    description = _assemble(narrative, include_sources=True)
    if len(description) > _DESC_LIMIT:
        # Step 1: truncate narrative
        # Reserve length for fixed parts + truncation suffix
        fixed = _assemble("", include_sources=True)
        budget = _DESC_LIMIT - len(fixed) - len(_TRUNC_SUFFIX) - 1
        if budget > 0 and narrative:
            truncated = narrative[:budget].rstrip() + _TRUNC_SUFFIX
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

    fields = [
        {"name": "Direction", "value": direction_line, "inline": True},
        {"name": "Confidence",
         "value": getattr(structured, "confidence_label", "LOW") or "LOW",
         "inline": True},
        {"name": "Price",
         "value": _format_price(getattr(structured, "current_price", None)),
         "inline": True},
        {"name": "Buy Zone",
         "value": _format_buy_zone(
             getattr(structured, "buy_zone_low", None),
             getattr(structured, "buy_zone_high", None),
         ),
         "inline": True},
        {"name": "SL",
         "value": _format_price(getattr(structured, "sl", None)),
         "inline": True},
        {"name": "TP1",
         "value": _format_price(getattr(structured, "tp1", None)),
         "inline": True},
        {"name": "TP2",
         "value": _format_price(getattr(structured, "tp2", None)),
         "inline": True},
        {"name": "TP3",
         "value": _format_price(getattr(structured, "tp3", None)),
         "inline": True},
    ]

    if _swing_v2:
        nc_days = getattr(structured, "next_catalyst_days", None)
        nc_value = f"{nc_days}d" if isinstance(nc_days, int) and nc_days >= 0 else "—"
        sh_days = getattr(structured, "swing_horizon_days", None)
        sh_band = getattr(structured, "swing_horizon_band", None)
        if isinstance(sh_days, int) and sh_days > 0 and sh_band:
            sh_value = f"{sh_band[0]}-{sh_band[1]}d"
        elif sh_days == 0:
            sh_value = "at target"
        else:
            sh_value = "—"
        em_value = getattr(structured, "magnitude_band_label", None) or "—"
        fields.extend([
            {"name": "Next Catalyst", "value": nc_value, "inline": True},
            {"name": "Swing Horizon", "value": sh_value, "inline": True},
            {"name": "Expected Move", "value": em_value, "inline": True},
        ])
    else:
        fields.extend([
            {"name": "Timeframe",
             "value": getattr(structured, "breakout_timeframe", "TBD") or "TBD",
             "inline": True},
            {"name": "Magnitude",
             "value": getattr(structured, "magnitude_label", "—") or "—",
             "inline": True},
        ])

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
        "title": f"${ticker} — Full Analysis",
        "color": _color_for(structured),
        "description": description,
        "fields": fields,
        "footer": {"text": " | ".join(footer_chunks)},
    }
