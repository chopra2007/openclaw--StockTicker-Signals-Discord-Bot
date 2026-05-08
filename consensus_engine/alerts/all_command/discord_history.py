"""Discord channel history fetchers for !all command.

Reads:
- #chat: last 24h of messages, filtered to those mentioning `$TICKER`,
  the bareword `TICKER` (case-insensitive whole-word), or the company name
  (when the ticker_metadata.name is non-empty per Pass-0 D5 caveat).
- #brief: the most recent 3 messages, no filtering (always feed-in).

Both functions degrade gracefully — any exception (token missing, HTTP error,
malformed JSON) is logged and returns `[]`. The aggregator treats the source
as "unavailable" rather than aborting.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg

log = logging.getLogger("consensus_engine.alerts.all_command.discord_history")

_DISCORD_API = "https://discord.com/api/v10"
_PAGE_LIMIT = 100
_MAX_PAGES = 5            # 500 msgs hard cap per call (D4 safety)
_MAX_RESULTS = 50         # bounded per spec
_HTTP_TIMEOUT = 10        # seconds per page
_24H_SECONDS = 86_400

# Discord epoch (2015-01-01) — used to decode message snowflakes to unix ts.
_DISCORD_EPOCH_MS = 1_420_070_400_000


def _snowflake_to_timestamp(snowflake: str) -> Optional[float]:
    """Decode a Discord snowflake to unix seconds. Returns None on bad input."""
    try:
        return ((int(snowflake) >> 22) + _DISCORD_EPOCH_MS) / 1000.0
    except (TypeError, ValueError):
        return None


def _build_match_pattern(ticker: str, company_name: Optional[str]) -> re.Pattern:
    """Build a single regex that fires on $TICKER, bareword TICKER, or company name.

    Cashtag and bareword are matched case-insensitively with word boundaries.
    Company name is matched as a literal (escape regex meta) substring,
    case-insensitive. Both are OR-ed in one alternation pattern.
    """
    parts = [rf"\${re.escape(ticker)}\b", rf"\b{re.escape(ticker)}\b"]
    if company_name and company_name.strip():
        parts.append(re.escape(company_name.strip()))
    return re.compile("|".join(parts), re.IGNORECASE)


async def _fetch_page(
    session: aiohttp.ClientSession,
    channel_id: str,
    headers: dict,
    *,
    limit: int = _PAGE_LIMIT,
    before: Optional[str] = None,
) -> list[dict]:
    """Fetch one page of messages. Returns [] on any non-200 response."""
    params: dict[str, object] = {"limit": limit}
    if before:
        params["before"] = before
    url = f"{_DISCORD_API}/channels/{channel_id}/messages"
    async with session.get(
        url,
        headers=headers,
        params=params,
        timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT),
    ) as resp:
        if resp.status != 200:
            body = await resp.text()
            log.warning(
                "discord_history: channel=%s status=%d body=%.200s",
                channel_id, resp.status, body,
            )
            return []
        return await resp.json()


async def fetch_chat_24h_ticker_filtered(
    ticker: str,
    company_name: Optional[str],
) -> list[str]:
    """Return up to 50 #chat message contents from the last 24h matching ticker/name.

    Pagination iterates with `before=<oldest_id>` until the page's oldest
    message is older than 24h or until the 5-page safety cap is hit. Returns
    `[]` on any failure (no token, HTTP error, JSON corruption).
    """
    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", "")) or ""
    if not token or not channel_id:
        log.warning(
            "discord_history.fetch_chat_24h: missing token or discord_channel_id",
        )
        return []

    cutoff = time.time() - _24H_SECONDS
    pattern = _build_match_pattern(ticker.upper(), company_name)
    headers = {"Authorization": f"Bot {token}"}
    matched: list[str] = []
    before: Optional[str] = None

    try:
        async with aiohttp.ClientSession() as session:
            for _page in range(_MAX_PAGES):
                page = await _fetch_page(
                    session, channel_id, headers, before=before,
                )
                if not page:
                    break
                for msg in page:
                    msg_id = str(msg.get("id", ""))
                    msg_ts = _snowflake_to_timestamp(msg_id)
                    if msg_ts is None or msg_ts < cutoff:
                        # 24h boundary reached on this page; stop after sweep.
                        continue
                    content = str(msg.get("content", "") or "")
                    if not content:
                        continue
                    if pattern.search(content):
                        matched.append(content)
                        if len(matched) >= _MAX_RESULTS:
                            return matched
                # Decide whether to paginate further: stop if last msg is past cutoff
                last_id = str(page[-1].get("id", ""))
                last_ts = _snowflake_to_timestamp(last_id)
                if last_ts is None or last_ts < cutoff:
                    break
                before = last_id
    except Exception as exc:  # noqa: BLE001 — graceful degrade per D13
        log.warning("discord_history.fetch_chat_24h failed: %s", exc)
        return []
    return matched


async def fetch_brief_last_3() -> list[str]:
    """Return the most recent 3 #brief message contents (no filtering)."""
    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_briefing_channel_id", "")) or ""
    if not token or not channel_id:
        log.warning(
            "discord_history.fetch_brief_last_3: missing token or discord_briefing_channel_id",
        )
        return []

    headers = {"Authorization": f"Bot {token}"}
    try:
        async with aiohttp.ClientSession() as session:
            page = await _fetch_page(session, channel_id, headers, limit=3)
            return [str(m.get("content", "") or "") for m in page if m.get("content")]
    except Exception as exc:  # noqa: BLE001 — graceful degrade per D13
        log.warning("discord_history.fetch_brief_last_3 failed: %s", exc)
        return []
