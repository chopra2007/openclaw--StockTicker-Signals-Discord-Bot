"""One shared renderer for insider (Form 4) activity across every surface.

A single insider sale often files as dozens of tiny "fills" at slightly
different prices. This module collapses those fills into ONE block per
insider, per transaction date, per direction (buy/sell) — showing who, how
many shares, the average price, the total dollar value, the date, and how
many fills it took. Every command that shows insiders draws from here, so the
numbers and the look never drift from one place to the next.

Surfaces:
  - `!sec` and the Score card / auto-alerts  -> `render_cards`   (code block)
  - `!all` "Full Analysis" card              -> `render_all_field` (clean text)
  - the AI evidence text fed to `!all`       -> `render_evidence` (plain lines)

`aggregate_insiders` is the shared, pure grouping step all four use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


@dataclass
class InsiderSummary:
    """One insider's open-market trades on one date in one direction."""
    name: str          # display name, "First Last"
    role: str          # abbreviated title, e.g. "CEO"
    direction: str     # "Buy" | "Sell" | raw code
    shares: float      # total shares across the fills
    avg_price: float   # value / shares
    value: float       # total dollar value
    date: str          # raw transaction date, "YYYY-MM-DD"
    n_fills: int       # number of fills in the group
    price_lo: float    # lowest fill price (0.0 if unknown)
    price_hi: float    # highest fill price (0.0 if unknown)


# ── formatting helpers ─────────────────────────────────────────────────────

# Common SEC officer titles → short label. Phrase match first (most specific),
# then a whole-token acronym match, so "President and CEO" → "CEO" but a title
# that merely contains the letters "cao" inside a word is not mis-tagged.
_TITLE_PHRASES = [
    ("chief financial", "CFO"),
    ("chief executive", "CEO"),
    ("chief operating", "COO"),
    ("chief accounting", "CAO"),
    ("chief technology", "CTO"),
    ("chief marketing", "CMO"),
    ("chief compliance", "CCO"),
    ("chief legal", "Chief Legal"),
    ("general counsel", "General Counsel"),
]
_TITLE_TOKENS = {
    "ceo": "CEO", "cfo": "CFO", "coo": "COO", "cao": "CAO",
    "cto": "CTO", "cmo": "CMO", "cco": "CCO",
}


def _abbrev_title(raw: str) -> str:
    """Shorten a verbose SEC title. Unknown titles are trimmed, never guessed."""
    t = (raw or "").strip()
    if not t:
        return "Insider"
    low = t.lower()
    for needle, abbr in _TITLE_PHRASES:
        if needle in low:
            return abbr
    tokens = set(re.split(r"[^a-z0-9%]+", low))
    for tok, abbr in _TITLE_TOKENS.items():
        if tok in tokens:
            return abbr
    if "director" in tokens:
        return "Director"
    if "10%" in low or "ten percent" in low:
        return "10% Owner"
    if len(t) <= 18:
        return t
    return t[:17].rstrip() + "…"


def _compact_dollar(v) -> str:
    """Total value, compact: 46_300_000 -> '~$46.3M', 190_000 -> '~$190K',
    4_200 -> '~$4,200'."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "~$0"
    a = abs(v)
    if a >= 1e9:
        return f"~${v / 1e9:.1f}B"
    if a >= 1e6:
        return f"~${v / 1e6:.1f}M"
    if a >= 1e4:
        return f"~${v / 1e3:.0f}K"
    return f"~${v:,.0f}"


def _fmt_avg(avg) -> str:
    """Average price: whole dollars at/above $100 ($1,158); cents below ($17.35)."""
    try:
        p = float(avg)
    except (TypeError, ValueError):
        return "$0"
    if p >= 100:
        return f"${p:,.0f}"
    return f"${p:.2f}"


def _fmt_date(raw: str) -> str:
    """Transaction date 'YYYY-MM-DD' -> 'Jun 26'. Raw string on parse failure."""
    s = (raw or "").strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%b %-d")
    except ValueError:
        return s or "?"


def _fmt_fills(n: int) -> str:
    return "1 fill" if n == 1 else f"{n} fills"


def _dot(direction: str) -> str:
    return "🔴" if direction == "Sell" else "🟢" if direction == "Buy" else "⚪"


# ── aggregation ────────────────────────────────────────────────────────────

def aggregate_insiders(transactions: list) -> tuple[list[InsiderSummary], int]:
    """Group a flat list of Form-4 transaction dicts into per-insider blocks.

    Only open-market buys/sales get a block; routine types (awards, option
    exercises, tax withholding, gifts) are counted, not listed. Blocks are
    grouped by (insider, transaction date, direction) and returned sorted by
    total dollar value, largest first. Returns (summaries, routine_count).
    """
    from consensus_engine.scanners.sec_edgar import _OPEN_MARKET_TX_TYPES
    from consensus_engine.alerts.commands import _fmt_insider_name

    txs = [t for t in (transactions or []) if isinstance(t, dict)]
    open_market = [t for t in txs
                   if t.get("transaction_type") in _OPEN_MARKET_TX_TYPES]
    routine_count = len(txs) - len(open_market)

    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for t in open_market:
        raw = str(t.get("reporter_name") or "Unknown")
        date = str(t.get("date") or "")
        direction = str(t.get("direction") or "")
        key = (raw, date, direction)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "raw": raw, "title": str(t.get("title") or "Insider"),
                "date": date, "direction": direction,
                "shares": 0.0, "value": 0.0, "n": 0, "lo": None, "hi": None,
            }
            order.append(key)
        try:
            sh = float(t.get("shares") or 0)
        except (TypeError, ValueError):
            sh = 0.0
        try:
            pr = float(t.get("price") or 0)
        except (TypeError, ValueError):
            pr = 0.0
        g["shares"] += sh
        g["value"] += sh * pr
        g["n"] += 1
        if pr:
            g["lo"] = pr if g["lo"] is None else min(g["lo"], pr)
            g["hi"] = pr if g["hi"] is None else max(g["hi"], pr)

    summaries: list[InsiderSummary] = []
    for key in order:
        g = groups[key]
        avg = (g["value"] / g["shares"]) if g["shares"] else 0.0
        summaries.append(InsiderSummary(
            name=_fmt_insider_name(g["raw"]),
            role=_abbrev_title(g["title"]),
            direction=g["direction"],
            shares=g["shares"], avg_price=avg, value=g["value"],
            date=g["date"], n_fills=g["n"],
            price_lo=g["lo"] or 0.0, price_hi=g["hi"] or 0.0,
        ))
    summaries.sort(key=lambda s: s.value, reverse=True)
    return summaries, routine_count


# ── renderers ──────────────────────────────────────────────────────────────

def render_cards(summaries: list[InsiderSummary], routine_count: int,
                 note: str = "") -> str:
    """Fenced code-block labeled stack — used by `!sec` and the Score card.

    Returns a ```-fenced string; `note` (e.g. '+3 more insiders') is appended
    inside the fence when a caller has trimmed the list to fit a cap.
    """
    blocks: list[str] = []
    for s in summaries:
        header = f"{_dot(s.direction)} {s.name} — {s.role}"
        underline = "─" * (len(header) + 3)
        blocks.append("\n".join([
            header,
            underline,
            f"    {'Shares':<8} {s.shares:,.0f}",
            f"    {'Avg':<8} {_fmt_avg(s.avg_price)}",
            f"    {'Value':<8} {_compact_dollar(s.value)}",
            f"    {'Date':<8} {_fmt_date(s.date)} · {_fmt_fills(s.n_fills)}",
        ]))
    body = "\n\n".join(blocks)
    if routine_count:
        body += f"\n\n+{routine_count} routine award / option transactions"
    if note:
        body += f"\n{note}"
    return f"```\n{body}\n```"


def render_all_field(summaries: list[InsiderSummary], routine_count: int,
                     max_chars: int = 1024) -> str:
    """Clean bold plain-text form for the `!all` card (no code block).

    Two lines per insider; bold name and numbers. Trimmed to `max_chars`
    (Discord's embed-field limit) with a '+N more insider(s)' tail if needed.
    """
    lines: list[str] = []
    shown = 0
    for s in summaries:
        header = f"{_dot(s.direction)} **{s.name}** — {s.role}"
        detail = (f"Shares **{s.shares:,.0f}** · Avg **{_fmt_avg(s.avg_price)}** · "
                  f"Value **{_compact_dollar(s.value)}** · "
                  f"{_fmt_date(s.date)} · {_fmt_fills(s.n_fills)}")
        block = f"{header}\n{detail}"
        candidate = "\n".join(lines + [block])
        if shown and len(candidate) > max_chars - 48:  # leave room for the tail
            break
        lines.append(block)
        shown += 1
    remaining = len(summaries) - shown
    if remaining > 0:
        lines.append(f"+{remaining} more insider(s)")
    if routine_count:
        lines.append(f"*+{routine_count} routine award / option transactions*")
    return "\n".join(lines)


def render_evidence(summaries: list[InsiderSummary], routine_count: int,
                    notable: bool) -> list[str]:
    """Plain-text lines fed to the `!all` write-up LLM. `notable` marks a set
    whose aggregate open-market value cleared the configured buy/sell floor."""
    if not summaries:
        if routine_count:
            return ["Recent Form 4 filings were routine awards / option "
                    "exercises / tax withholding — no open-market conviction trades."]
        return []
    out = [("NOTABLE — " if notable else "")
           + "open-market insider (Form 4) transactions:"]
    for s in summaries:
        out.append(
            f"  - {s.name} ({s.role}) — {s.direction} {s.shares:,.0f} shares "
            f"at avg {_fmt_avg(s.avg_price)} ({_compact_dollar(s.value)}) "
            f"on {_fmt_date(s.date)} ({_fmt_fills(s.n_fills)})."
        )
    if routine_count:
        out.append(f"  plus {routine_count} routine award / option "
                   f"transaction(s) (collapsed).")
    return out
