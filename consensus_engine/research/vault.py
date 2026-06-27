"""Vault markdown rendering + atomic file writes."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("consensus_engine.research.vault")

PT = ZoneInfo("America/Los_Angeles")  # display-only: research-note timestamps are PDT
_ORDER = [("analyst", "Analyst Signals (TweetShift)"),
          ("sec", "Earnings & SEC"),
          ("news", "News (last 12h)")]


def _section_body(section: dict | None) -> tuple[str, bool]:
    """Return (body_text, is_stale). Falls back to last_good_content when current failed."""
    if not section:
        return ("_No data yet._", False)
    if section.get("status") == "ok" and section.get("content"):
        return (section["content"], False)
    if section.get("last_good_content"):
        return (section["last_good_content"], True)
    return ("_Fetch failed and no prior content._", False)


def render_ticker_markdown(ticker: str, sections: dict) -> str:
    now_et = datetime.now(tz=PT).strftime("%Y-%m-%d %H:%M %Z")
    flags = []
    for key, _ in _ORDER:
        s = sections.get(key)
        if s and s.get("status") == "ok":
            flags.append(f"{key} ✓")
        elif s and s.get("last_good_content"):
            flags.append(f"{key} (stale)")
        else:
            flags.append(f"{key} ✗")
    header = (
        f"# {ticker} Research Note\n"
        f"Generated: {now_et}  |  Sources: {'  '.join(flags)}\n\n"
    )
    parts = [header]
    for key, title in _ORDER:
        body, stale = _section_body(sections.get(key))
        suffix = "  _(last-good)_" if stale else ""
        parts.append(f"## {title}{suffix}\n{body}\n")
    return "\n".join(parts)


async def write_ticker_vault(ticker: str, sections: dict, vault_path: str) -> str:
    """Atomically write vault/tickers/TICKER.md. Returns the final path."""
    dest_dir = os.path.join(vault_path, "tickers")
    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, f"{ticker.upper()}.md")
    tmp = final + ".tmp"
    content = render_ticker_markdown(ticker.upper(), sections)

    def _write():
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, final)

    await asyncio.get_event_loop().run_in_executor(None, _write)
    log.info("Wrote vault note %s", final)
    return final
