"""Discord command routing.

Handles !-prefixed commands received via the Discord Gateway.
Commands:
  !help               — list available commands
  !status             — engine status summary
  !trend              — last Reddit trend digest on demand
  !scan <TICKER>      — full on-demand check: one score + 🟢/🟡/🔴 band + evidence
  !performance        — alert win rates and P&L stats
  !signals <TICKER>   — active signal counts by source
  !analysts <TICKER>  — analysts who recently mentioned a ticker
  !active-tickers     — all tickers with active signals
  !sec <TICKER>       — recent SEC filings (8-K, Form 4, 13D, etc.)
  !options <TICKER>   — unusual options activity (call/put ratios, vol/OI)
  !em <TICKER>        — options-implied daily expected move + chart
  !technical <TICKER> — run 6 technical filters independently
  !news <TICKER>      — run news cascade standalone
  !google-trends <T>  — Google Trends spike % for a ticker
  !apewisdom          — ApeWisdom trending tickers
  !alert-history <T>  — alert history with price outcomes for a ticker
  !levels <T>         — price levels (support/resistance) from YouTube + signals
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from consensus_engine import config as cfg, db
from consensus_engine.alerts.display_scale import call_put_split
from consensus_engine.alerts.discord import send_command_reply, send_command_embed_reply
from consensus_engine.scanners.reddit_trend import crawl_and_get_trending
from consensus_engine.alerts.discord import send_trend_digest
from consensus_engine.utils.tickers import is_valid_ticker_format
from consensus_engine.utils.time_context import build_time_context


_INVALID_TICKER_MSG = "Invalid ticker `{ticker}`. Tickers must be 1-5 uppercase letters."

log = logging.getLogger("consensus_engine.alerts.commands")

# ---------------------------------------------------------------------------
# Semaphore pool — concurrency discipline (plan section 2G)
# ---------------------------------------------------------------------------
# _OUTER_SEM: limits simultaneous handler entries (one per user command).
# _INNER_SEM: limits background tasks spawned by create_task (heavy I/O).
# Both use `async with` — no bare acquire/release; exception-safe.

_OUTER_SEM = asyncio.Semaphore(cfg.get("commands.outer_concurrency", 4))
_INNER_SEM = asyncio.Semaphore(cfg.get("commands.inner_concurrency", 64))


async def _dispatch_inner(coro) -> asyncio.Task:
    """Wrap a coroutine in _INNER_SEM and schedule as a Task."""
    async def _guarded():
        async with _INNER_SEM:
            return await coro
    return asyncio.create_task(_guarded())


# ---------------------------------------------------------------------------
# Multi-ticker command support
# ---------------------------------------------------------------------------
# One command can now name several tickers: `!all nvda amd mu` or
# `!all nvda, amd, mu`. `_parse_ticker_args` splits the list; `_run_ticker_command`
# runs it — light commands all at once, medium/heavy one at a time.
# LONG / SHORT are reserved direction words (see analysis/technical.py), never
# tickers — a tiny explicit set, NOT the full blacklist, so `!all SPY` still works.

_DIRECTION_WORDS = {"LONG", "SHORT"}


def _parse_ticker_args(
    args: list[str], *, cap: int, takes_direction: bool = False
) -> tuple[list[str], str, list[str], list[str]]:
    """Split a command's args into (tickers, direction, invalid, dropped).

    - Split on commas AND spaces; strip a leading '$'; uppercase.
    - LONG / SHORT are reserved direction words, never tickers. For a command
      that takes a direction the last one seen wins (default 'long'); for every
      other command they are simply removed.
    - tickers: well-formed symbols (1-5 letters), deduped, first-seen order,
      trimmed to `cap`.
    - invalid: tokens that fail the format check (bad length / non-alpha).
    - dropped: valid tickers beyond the cap.
    """
    tokens = [t for t in re.split(r"[,\s]+", " ".join(args)) if t]
    direction = "long"
    valid: list[str] = []
    invalid: list[str] = []
    for tok in tokens:
        sym = tok.lstrip("$").upper()
        if not sym:
            continue
        if sym in _DIRECTION_WORDS:
            if takes_direction:
                direction = sym.lower()
            continue  # never a ticker, for any command
        if is_valid_ticker_format(sym):
            valid.append(sym)
        elif sym not in invalid:
            invalid.append(sym)
    valid = list(dict.fromkeys(valid))  # dedupe, preserve first-seen order
    dropped = valid[cap:]
    valid = valid[:cap]
    return valid, direction, invalid, dropped


def _batch_note(
    tickers: list[str], invalid: list[str], dropped: list[str], cap: int
) -> Optional[str]:
    """One short acknowledgment line for a multi-ticker run, or None.

    Returns None for a clean single-ticker run (so single-ticker output is
    unchanged). Otherwise names what is running and what was skipped/dropped.
    """
    clauses = []
    if invalid:
        clauses.append("Skipped " + ", ".join(invalid) + " (not a ticker).")
    if dropped:
        clauses.append(f"Dropped {', '.join(dropped)} (max {cap}).")
    if len(tickers) <= 1 and not clauses:
        return None
    head = "Running " + ", ".join(f"${t}" for t in tickers) + "."
    return " ".join([head] + clauses)


async def _run_ticker_command(
    args: list[str], channel_id: str, message_id: str, *,
    work, mode: str, cap: int, usage: str, takes_direction: bool = False,
) -> None:
    """Run a ticker command for one or more tickers.

    work: async callable — work(ticker) normally, or work(ticker, direction)
          when takes_direction is True. It sends its own reply(ies); a
          medium/heavy handler returns the background task it dispatched, which
          the sequential runner awaits before starting the next ticker.
    mode: "parallel" (fire all at once) or "sequential" (one at a time).
    cap:  max tickers to run; extras are dropped with a note.
    usage: shown when no ticker is given.
    """
    if not args:
        await send_command_reply(channel_id, message_id, usage)
        return

    tickers, direction, invalid, dropped = _parse_ticker_args(
        args, cap=cap, takes_direction=takes_direction
    )
    if not tickers:
        bad = (invalid or dropped or args)[0]
        await send_command_reply(
            channel_id, message_id, _INVALID_TICKER_MSG.format(ticker=str(bad).upper())
        )
        return

    note = _batch_note(tickers, invalid, dropped, cap)
    if note:
        await send_command_reply(channel_id, message_id, note)

    def _call(t: str):
        return work(t, direction) if takes_direction else work(t)

    if mode == "sequential" and len(tickers) > 1:
        # Run one at a time inside a single background task so route_command
        # returns fast (never holds _OUTER_SEM for the minutes a 3x !all takes).
        # Each handler dispatches its own inner task and returns it; we await
        # that task before starting the next ticker.
        async def _chain():
            for t in tickers:
                try:
                    task = await _call(t)
                    if task is not None:
                        await task
                except Exception as e:  # noqa: BLE001
                    log.error("multi-ticker sequential failed for $%s: %s",
                              t, e, exc_info=e)
        await _dispatch_inner(_chain())
    else:
        # Single ticker (any mode) or parallel: fire each handler directly.
        # Medium/heavy handlers dispatch their work to the background (true
        # parallel); light handlers reply inline. Route returns promptly.
        for t in tickers:
            try:
                await _call(t)
            except Exception as e:  # noqa: BLE001
                log.error("multi-ticker failed for $%s: %s", t, e, exc_info=e)


def _parse_history_limit(content: str, default: int = 20) -> int:
    """Extract 'last N messages' from content, capped at 50."""
    m = re.search(r'last\s+(\d+)\s+messages?', content, re.IGNORECASE)
    if m:
        return min(int(m.group(1)), 50)
    return default


async def _fetch_channel_history(channel_id: str, limit: int = 20) -> str:
    """Fetch recent messages from a Discord channel and format them as context."""
    import aiohttp
    from consensus_engine.utils.http import get_session
    from consensus_engine.main import _strip_secrets_preamble
    token = cfg.get_api_key("discord_bot_token")
    if not token:
        return ""
    try:
        session = await get_session()
        async with session.get(
            f"https://discord.com/api/v10/channels/{channel_id}/messages?limit={limit}",
            headers={"Authorization": f"Bot {token}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return ""
            msgs = await resp.json()
        lines = []
        for m in reversed(msgs):
            author = m.get("author", {}).get("username", "unknown")
            parts = []
            body = m.get("content", "").strip()
            if body:
                # Defensive: strip any residual `[secrets]` preamble from prior
                # bot replies so it never re-enters the LLM context window.
                cleaned = _strip_secrets_preamble(body)
                if cleaned and cleaned != "(agent returned no content)":
                    parts.append(cleaned)
            for embed in m.get("embeds", []):
                if embed.get("title"):
                    parts.append(f"[embed: {embed['title']}]")
                if embed.get("description"):
                    parts.append(embed["description"][:200])
                for field in embed.get("fields", []):
                    parts.append(f"{field.get('name','')}: {field.get('value','')[:150]}")
            if parts:
                lines.append(f"{author}: " + " | ".join(parts))
        return "\n".join(lines)
    except Exception as exc:
        log.warning("Failed to fetch channel history: %s", exc)
        return ""


async def _handle_ask(question: str, channel_id: str, message_id: str) -> None:
    """Route !ask through the same OpenClaw agent as @-mention.

    Prepends the last 10 channel messages as context so the agent can answer
    with awareness of the recent conversation flow. Otherwise relies on
    `_handle_mention`'s subprocess invocation, retry loop, and telemetry —
    so !ask and @mention now share one config, one prompt, one model chain.
    """
    if not question:
        await send_command_reply(
            channel_id, message_id,
            "Please include a question. Example: `!ask what is NVDA doing today?`",
        )
        return

    # Deterministic earnings-date answer runs on the raw question (before history
    # is prepended) so it can't false-positive on an earnings mention in history.
    from consensus_engine.alerts.earnings_answer import maybe_answer_earnings
    if await maybe_answer_earnings(question, channel_id, message_id):
        return

    history = await _fetch_channel_history(channel_id, limit=10)
    if history:
        content = (
            "Recent channel messages (oldest→newest, for context only):\n"
            f"{history}\n\n"
            f"Question: {question}"
        )
    else:
        content = question

    from consensus_engine.main import _handle_mention
    await _handle_mention(content, channel_id, message_id, allow_intercept=False)

def _build_help_embed() -> dict:
    """Build the !help embed — a sectioned command reference (slate accent),
    one short description per command."""
    return {
        "title": "🐾  OpenClaw Signal Bot — Commands",
        "description": "Real-time stock signal intelligence",
        "color": 0xF1C40F,  # gold (user pick)
        "fields": [
            {
                "name": "📊  Core",
                "value": (
                    "`!scan <ticker>` — full check: one score + 🟢🟡🔴 band + evidence\n"
                    "`!all <ticker>` — synthesize every source into one AI analysis\n"
                    "`!ask <question>` — full-power AI answer to any question\n"
                    "`!status` — engine health (active signals, last alert)\n"
                    "`!performance` — alert win rates and profit/loss stats\n"
                    "`!trend` — post the latest Reddit trend digest\n"
                    "`!help` — show this command list"
                ),
                "inline": False,
            },
            {
                "name": "🎯  Ticker Intel",
                "value": (
                    "`!signals <ticker>` — active signal counts by source\n"
                    "`!analysts <ticker>` — analysts who recently mentioned it\n"
                    "`!news <ticker>` — news cascade (headline + catalyst type)\n"
                    "`!sec <ticker>` — recent SEC filings (8-K, Form 4, 13D…)\n"
                    "`!options <ticker>` — unusual options activity (vol/OI ratios)\n"
                    "`!em <ticker>` — options-implied daily expected move + chart\n"
                    "`!technical <ticker>` — 6 technical filters with pass/fail\n"
                    "`!google-trends <ticker>` — Google Trends interest spike %\n"
                    "`!alert-history <ticker>` — past alerts with 1h/24h price outcomes\n"
                    "`!active-tickers` — every ticker with active signals right now"
                ),
                "inline": False,
            },
            {
                "name": "📺  YouTube",
                "value": (
                    "`!yt <url>` — analyze a video (tickers, conviction, levels)\n"
                    "`!transcript <url>` — fetch a video's transcript text\n"
                    "`!yt-mentions <ticker>` — YouTube signals for a ticker (last 7 days)\n"
                    "`!macro` — macro digest across all channels (last 7 days)\n"
                    "`!yt-follow <channel>` — add a YouTube channel to the follow list\n"
                    "`!yt-health` — 7-day pipeline health + Gemini budget\n"
                    "`!yt-evidence <video id>` — first 10 grounded evidence spans from a video"
                ),
                "inline": False,
            },
            {
                "name": "📐  Levels",
                "value": (
                    "`!levels <ticker>` — support/resistance from YouTube + signals\n"
                    "`!cluster <ticker>` — price-level cluster history"
                ),
                "inline": False,
            },
            {
                "name": "🔥  Scanners",
                "value": (
                    "`!apewisdom` — ApeWisdom trending tickers\n"
                    "`!leaderboard` — analyst win-rate rankings"
                ),
                "inline": False,
            },
            {
                "name": "⚙️  Engine",
                "value": (
                    "`!source-health` — data-source status (freshness, error rate)\n"
                    "`!feature-health` — all features, on/off state, last flip\n"
                    "`!shadow-mode-report <feature>` — 14-day KPI report for a feature"
                ),
                "inline": False,
            },
        ],
        "footer": {"text": "OpenClaw Signal Engine · 31 commands"},
    }


def parse_command(content: str) -> Optional[tuple[str, list[str]]]:
    """Parse a Discord message into (command, args) if it starts with !.

    Returns None if the message is not a command.
    Handles messages that begin with a bot mention: <@123> !command args
    """
    content = content.strip()
    # Strip leading Discord mention so "@bot !options TSLA" works
    content = re.sub(r'^<@!?[0-9]+>\s*', '', content)
    if not content.startswith("!"):
        return None
    parts = content[1:].split()
    if not parts:
        return None
    return parts[0].lower(), parts[1:]


async def route_command(
    command: str,
    args: list[str],
    channel_id: str,
    message_id: str,
    author_id: str | None = None,
) -> None:
    """Dispatch a parsed command to its handler."""
    async with _OUTER_SEM:
        await _route_command_inner(command, args, channel_id, message_id, author_id)


async def _route_command_inner(
    command: str,
    args: list[str],
    channel_id: str,
    message_id: str,
    author_id: str | None = None,
) -> None:
    if command in ("help", "readme"):
        await send_command_embed_reply(channel_id, message_id, _build_help_embed())

    elif command == "status":
        await _handle_status(channel_id, message_id)

    elif command == "trend":
        await _handle_trend(channel_id, message_id)

    elif command == "performance":
        await _handle_performance(channel_id, message_id)

    elif command == "scan":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_scan(t, channel_id, message_id),
            mode="sequential", cap=5,
            usage="Usage: `!scan <TICKER>` — e.g. `!scan NVDA` (or several: `!scan nvda amd mu`)")

    elif command == "ask":
        question = " ".join(args).strip()
        if not question:
            await send_command_reply(channel_id, message_id,
                "Usage: `!ask <your question>` — routes to the heavyweight LLM "
                "chain with longer answers (auto-split across messages if needed).")
        else:
            await _handle_ask(question, channel_id, message_id)

    elif command == "all":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_all(t, channel_id, message_id),
            mode="sequential", cap=3,
            usage="Usage: `!all <TICKER>` — e.g. `!all AMD` (or up to 3: `!all nvda amd mu`)")

    elif command == "signals":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_signals(t, channel_id, message_id),
            mode="parallel", cap=5,
            usage="Usage: `!signals <TICKER>` — e.g. `!signals NVDA` (or several: `!signals nvda amd`)")

    elif command == "analysts":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_analysts(t, channel_id, message_id),
            mode="parallel", cap=5,
            usage="Usage: `!analysts <TICKER>` — e.g. `!analysts NVDA` (or several: `!analysts nvda amd`)")

    elif command in ("active-tickers", "active_tickers", "active"):
        await _handle_active_tickers(channel_id, message_id)

    elif command == "news":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_news(t, channel_id, message_id),
            mode="sequential", cap=5,
            usage="Usage: `!news <TICKER>` — e.g. `!news NVDA` (or several: `!news nvda amd mu`)")

    elif command == "sec":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_sec(t, channel_id, message_id),
            mode="sequential", cap=5,
            usage="Usage: `!sec <TICKER>` — e.g. `!sec NVDA` (or several: `!sec nvda amd mu`)")

    elif command == "options":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_options(t, channel_id, message_id),
            mode="sequential", cap=5,
            usage="Usage: `!options <TICKER>` — e.g. `!options NVDA` (or several: `!options nvda amd mu`)")

    elif command == "technical":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t, d: _handle_technical(t, d, channel_id, message_id),
            mode="parallel", cap=5, takes_direction=True,
            usage="Usage: `!technical <TICKER> [long|short]` — e.g. `!technical NVDA` "
                  "(or several: `!technical nvda amd short`)")

    elif command in ("google-trends", "trends", "gtrends"):
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_google_trends(t, channel_id, message_id),
            mode="sequential", cap=5,
            usage="Usage: `!google-trends <TICKER>` — e.g. `!google-trends NVDA` "
                  "(or several: `!google-trends nvda amd`)")

    elif command == "serpapi-trends":
        # Run SerpAPI Google Trends for active tickers (called via cron)
        await _run_serpapi_trends(channel_id, message_id)

    elif command == "apewisdom":
        await _handle_apewisdom(channel_id, message_id)

    elif command in ("alert-history", "history"):
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_alert_history(t, channel_id, message_id),
            mode="parallel", cap=5,
            usage="Usage: `!alert-history <TICKER>` — e.g. `!alert-history NVDA` "
                  "(or several: `!alert-history nvda amd`)")

    elif command == "leaderboard":
        await _handle_leaderboard(channel_id, message_id)

    elif command in ("source-health", "source_health"):
        await _handle_source_health(channel_id, message_id)

    elif command == "transcript":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!transcript <YOUTUBE_URL>` — e.g. `!transcript https://www.youtube.com/watch?v=xxxxx`")
        else:
            await _handle_transcript(args[0], channel_id, message_id)

    elif command == "levels":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_levels(t, channel_id, message_id),
            mode="parallel", cap=5,
            usage="Usage: `!levels <TICKER>` — e.g. `!levels NVDA` (or several: `!levels nvda amd`)")

    elif command == "yt":
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!yt <URL>` — e.g. `!yt https://youtu.be/xxxxx`")
        else:
            await _handle_yt(args[0], channel_id, message_id, author_id=author_id)

    elif command in ("yt-mentions", "yt_mentions"):
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_yt_mentions(t, channel_id, message_id),
            mode="parallel", cap=5,
            usage="Usage: `!yt-mentions $TICKER` — e.g. `!yt-mentions $NVDA` "
                  "(or several: `!yt-mentions nvda amd`)")

    elif command == "macro":
        await _handle_macro(channel_id, message_id)

    elif command in ("yt-follow", "yt_follow"):
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!yt-follow @handle` or `!yt-follow https://youtube.com/@handle`")
        else:
            await _handle_yt_follow(args[0], channel_id, message_id)

    elif command in ("yt-health", "yt_health"):
        await _handle_yt_health(channel_id, message_id)

    elif command in ("yt-evidence", "yt_evidence"):
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!yt-evidence <video_id>`")
        else:
            await _handle_yt_evidence(args[0], channel_id, message_id)

    elif command in ("feature-health", "feature_health"):
        await _handle_feature_health(channel_id, message_id)

    elif command in ("shadow-mode-report", "shadow_mode_report", "shadow-report"):
        if not args:
            await send_command_reply(channel_id, message_id, "Usage: `!shadow-mode-report <feature>` — e.g. `!shadow-mode-report regime_classifier`")
        else:
            await _handle_shadow_mode_report(args[0].lower().replace("-", "_"), channel_id, message_id)

    elif command == "cluster":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_cluster_history(t, channel_id, message_id),
            mode="parallel", cap=5,
            usage="Usage: `!cluster <TICKER>` — e.g. `!cluster NVDA` (or several: `!cluster nvda amd`)")

    elif command == "em":
        await _run_ticker_command(
            args, channel_id, message_id,
            work=lambda t: _handle_em(t, channel_id, message_id),
            mode="sequential", cap=5,
            usage="Usage: `!em <TICKER>` — e.g. `!em SPY` (or several: `!em nvda amd mu`)")

    elif command in ("market", "rotation", "breadth", "regime"):
        await _handle_market(channel_id, message_id)

    else:
        await send_command_reply(channel_id, message_id, f"Unknown command `!{command}`. Try `!help`.")


# ---------------------------------------------------------------------------
# Existing handlers
# ---------------------------------------------------------------------------

async def _handle_status(channel_id: str, message_id: str) -> None:
    """Reply with a brief engine status summary."""
    try:
        from consensus_engine import db
        import time
        conn = await db.get_db()
        now = time.time()

        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM ticker_signals WHERE expires_at > ?", (now,)
        )
        row = await cursor.fetchone()
        active_signals = row["cnt"] if row else 0

        cursor = await conn.execute(
            "SELECT ticker, confidence_score, alerted_at FROM alert_history ORDER BY alerted_at DESC LIMIT 1"
        )
        last_alert = await cursor.fetchone()

        lines = ["**Engine Status**", f"Active signals: {active_signals}"]
        if last_alert:
            ago_min = int((now - last_alert["alerted_at"]) / 60)
            lines.append(f"Last alert: `${last_alert['ticker']}` score={last_alert['confidence_score']:.0f} ({ago_min}m ago)")
        else:
            lines.append("Last alert: none")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Status command error: %s", e)
        await send_command_reply(channel_id, message_id, "Status unavailable.")


async def _handle_trend(channel_id: str, message_id: str) -> None:
    """Trigger an on-demand Reddit trend digest."""
    try:
        await send_command_reply(channel_id, message_id, "Running trend scan... (may take ~30s)")
        trending = await crawl_and_get_trending()
        if trending:
            await send_trend_digest(trending)
            await send_command_reply(channel_id, message_id, f"Trend digest posted — {len(trending)} tickers found.")
        else:
            await send_command_reply(channel_id, message_id, "No trending tickers found right now.")
    except Exception as e:
        log.error("Trend command error: %s", e)
        await send_command_reply(channel_id, message_id, "Trend scan failed.")


async def _handle_performance(channel_id: str, message_id: str) -> None:
    """Reply with alert performance stats (win rates, P&L, top/worst alerts)."""
    try:
        from consensus_engine import db
        from datetime import datetime

        stats = await db.get_performance_stats()

        if stats["total_all"] == 0:
            await send_command_reply(channel_id, message_id, "No alert data yet.")
            return

        lines = ["**Alert Performance**"]
        lines.append(f"Total alerts: **{stats['total_all']}** all-time | **{stats['total_7d']}** last 7d")

        if stats["win_rate_1h"] is not None:
            lines.append(f"Win rate @ 1h: **{stats['win_rate_1h']:.1f}%** ({stats['total_1h']} alerts)")
        else:
            lines.append("Win rate @ 1h: no data")

        if stats["win_rate_24h"] is not None:
            lines.append(f"Win rate @ 24h: **{stats['win_rate_24h']:.1f}%** ({stats['total_24h']} alerts)")
        else:
            lines.append("Win rate @ 24h: no data")

        if stats["avg_pnl_1h"] is not None:
            sign = "+" if stats["avg_pnl_1h"] >= 0 else ""
            lines.append(f"Avg P&L @ 1h: **{sign}{stats['avg_pnl_1h']:.2f}%**")
        if stats["avg_pnl_24h"] is not None:
            sign = "+" if stats["avg_pnl_24h"] >= 0 else ""
            lines.append(f"Avg P&L @ 24h: **{sign}{stats['avg_pnl_24h']:.2f}%**")

        if stats["top3_best_1h"]:
            lines.append("\n**Top 3 Best (1h)**")
            for r in stats["top3_best_1h"]:
                dt = datetime.fromtimestamp(r["alerted_at"]).strftime("%m/%d %H:%M")
                lines.append(f"`${r['ticker']}` +{r['pnl_pct']:.2f}% ({dt})")

        if stats["top3_worst_1h"]:
            lines.append("\n**Top 3 Worst (1h)**")
            for r in stats["top3_worst_1h"]:
                dt = datetime.fromtimestamp(r["alerted_at"]).strftime("%m/%d %H:%M")
                lines.append(f"`${r['ticker']}` {r['pnl_pct']:.2f}% ({dt})")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Performance command error: %s", e)
        await send_command_reply(channel_id, message_id, "Performance stats unavailable.")


async def _handle_scan(ticker: str, channel_id: str, message_id: str) -> None:
    """Run the full on-demand check and reply with one gated score + band."""
    await send_command_reply(channel_id, message_id, f"Scanning `${ticker}`...")
    return await _dispatch_inner(_scan_and_reply(ticker, channel_id, message_id))


async def _scan_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    """Background task: run the on-demand check and post ONE verdict.

    #50: !scan is the single combined command. It runs the cross-reference (for
    the supporting evidence) AND the precision engine (for the gated 0-100 score
    plus its 🟢/🟡/🔴 band) — the SAME score the live alerts use — so there is one
    coherent number, never a second additive total. (Replaces the old !market-view.)
    """
    try:
        from consensus_engine.cross_reference import cross_reference
        from consensus_engine.engine import analyze_signal
        from consensus_engine.models import ParsedTweet, TweetType, Direction, Conviction
        fake_tweet = ParsedTweet(
            tweet_url="command",
            analyst="command",
            raw_text=f"!scan {ticker}",
            tweet_type=TweetType.TICKER_CALLOUT,
            tickers=[ticker],
            direction=Direction.NEUTRAL,
            options=None,
            conviction=Conviction.MEDIUM,
            summary=f"On-demand scan for ${ticker}",
        )
        xref = await cross_reference(ticker, fake_tweet, executor=None)

        # Precision gate — the same engine the live pipeline + alerts use, so the
        # number here is on the one 0-100 band scale (not the raw additive sum).
        tech_n = xref.technical.passed_count if (xref and xref.technical is not None) else 0
        try:
            precision = await analyze_signal(
                ticker,
                base_score=fake_tweet.base_score,
                breakdown=xref.breakdown,
                technical_filter_count=tech_n,
                analyst="command",
            )
        except Exception as exc:
            log.warning("Scan precision engine failed for $%s: %s", ticker, exc)
            precision = None

        # ONE score: the precision-gated 0-100 number. The dot is the band of THAT
        # score (same high/med thresholds the engine uses), so the colour and the
        # number can never disagree — that coherence is the whole point of #50.
        _high = cfg.get("precision_engine.thresholds.high_confidence", 80)
        _med = cfg.get("precision_engine.thresholds.medium_confidence", 65)
        budget_skipped = False
        if precision and not precision.get("skipped"):
            score = int(precision.get("total_score", 0) or 0)
            budget_skipped = bool(precision.get("skipped_sources"))
            dot = "🟢" if score >= _high else ("🟡" if score >= _med else "🔴")
            header = f"{dot} **Score: {score}**"
        else:
            header = "⚪ **Score: unavailable** — couldn't compute, try again"

        lines = [f"**${ticker} Scan**", header]
        if xref.catalyst_summary:
            lines.append(f"News: {xref.catalyst_summary[:200]}")
        if xref.options and xref.options.has_unusual_activity:
            opt = xref.options
            opt_parts = []
            if opt.unusual_calls:
                opt_parts.append(f"unusual calls ({opt.max_call_ratio:.1f}x vol/OI)")
            if opt.unusual_puts:
                opt_parts.append(f"unusual puts ({opt.max_put_ratio:.1f}x vol/OI)")
            if opt_parts:
                lines.append(f"Options: {', '.join(opt_parts)}")
        if xref.social_summary:
            lines.append(f"Social: {xref.social_summary}")
        if xref and xref.technical is not None and xref.technical.filters:
            passed = sum(1 for f in xref.technical.filters if f.passed)
            lines.append(f"Technical: {passed}/{len(xref.technical.filters)} filters passed")
        if budget_skipped:
            lines.append("_(some data sources were unavailable this run)_")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Scan background task error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Scan failed for `${ticker}`.")


async def _handle_all(ticker: str, channel_id: str, message_id: str) -> None:
    """Comprehensive cross-source analysis for a ticker via the all_command package."""
    from consensus_engine.alerts.all_command import handle_all
    task = await _dispatch_inner(handle_all(ticker, channel_id, message_id))

    def _log_handle_all_exception(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.error("!all handler task failed for $%s: %s", ticker, exc, exc_info=exc)

    task.add_done_callback(_log_handle_all_exception)
    return task


# ---------------------------------------------------------------------------
# New Tier 1 handlers
# ---------------------------------------------------------------------------

async def _handle_signals(ticker: str, channel_id: str, message_id: str) -> None:
    """Show active signal counts by source for a ticker."""
    try:
        from consensus_engine import db
        counts = await db.get_signal_counts_by_source(ticker)
        if not counts:
            await send_command_reply(channel_id, message_id, f"No active signals for `${ticker}`.")
            return
        lines = [f"**Active Signals — ${ticker}**"]
        for source, count in sorted(counts.items(), key=lambda x: -x[1]):
            lines.append(f"`{source}`: {count}")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Signals command error: %s", e)
        await send_command_reply(channel_id, message_id, f"Failed to fetch signals for `${ticker}`.")


async def _handle_analysts(ticker: str, channel_id: str, message_id: str) -> None:
    """Show analysts who recently mentioned a ticker."""
    try:
        from consensus_engine import db
        analysts = await db.get_recent_analysts_for_ticker(ticker, window_seconds=3600)
        if not analysts:
            await send_command_reply(channel_id, message_id, f"No analysts mentioned `${ticker}` in the last hour.")
            return
        handles = ", ".join(f"@{a}" for a in analysts)
        await send_command_reply(channel_id, message_id, f"**Analysts mentioning ${ticker} (last 1h)**\n{handles}")
    except Exception as e:
        log.error("Analysts command error: %s", e)
        await send_command_reply(channel_id, message_id, f"Failed to fetch analysts for `${ticker}`.")


async def _handle_active_tickers(channel_id: str, message_id: str) -> None:
    """List all tickers with active signals."""
    try:
        from consensus_engine import db
        tickers = await db.get_active_tickers(min_signals=1)
        if not tickers:
            await send_command_reply(channel_id, message_id, "No active tickers right now.")
            return
        ticker_list = "  ".join(f"`${t}`" for t in tickers[:30])
        await send_command_reply(channel_id, message_id, f"**Active Tickers ({len(tickers)})**\n{ticker_list}")
    except Exception as e:
        log.error("Active-tickers command error: %s", e)
        await send_command_reply(channel_id, message_id, "Failed to fetch active tickers.")


async def _handle_news(ticker: str, channel_id: str, message_id: str) -> None:
    """Run news cascade for a ticker and reply with result."""
    await send_command_reply(channel_id, message_id, f"Running news scan for `${ticker}`...")
    return await _dispatch_inner(_news_and_reply(ticker, channel_id, message_id))


async def _news_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.news import news_cascade
        result = await news_cascade(ticker)
        if not result:
            await send_command_reply(channel_id, message_id, f"No news found for `${ticker}`.")
            return
        lines = [f"**News — ${ticker}**"]
        lines.append(f"Type: **{result.catalyst_type or 'General'}**")
        if result.catalyst_summary:
            lines.append(f"Summary: {result.catalyst_summary[:200]}")
        if result.news_sources:
            lines.append(f"Sources: {', '.join(result.news_sources[:3])}")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("News command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"News scan failed for `${ticker}`.")


async def _handle_sec(ticker: str, channel_id: str, message_id: str) -> None:
    """Show recent SEC filings for a ticker."""
    await send_command_reply(channel_id, message_id, f"Checking SEC filings for `${ticker}`...")
    return await _dispatch_inner(_sec_and_reply(ticker, channel_id, message_id))


def _fmt_insider_name(raw: str) -> str:
    """Convert SEC 'LAST FIRST' format to 'First Last' for display."""
    parts = raw.strip().split()
    if len(parts) >= 2:
        return " ".join(reversed(parts))
    return raw.title()


def _pack_insider_blocks(summaries: list, routine: int, limit: int = 3800) -> list[str]:
    """Split insider summaries into one or more fenced code blocks, each within
    `limit` chars, so the whole set always fits inside embed descriptions.
    The routine-count line rides on the last block only."""
    from consensus_engine.alerts.insider_display import render_cards
    groups: list[list] = []
    cur: list = []
    for s in summaries:
        if cur and len(render_cards(cur + [s], 0)) > limit:
            groups.append(cur)
            cur = [s]
        else:
            cur.append(s)
    if cur:
        groups.append(cur)
    return [render_cards(g, routine if i == len(groups) - 1 else 0)
            for i, g in enumerate(groups)]


def _pack_sec_embeds(sections: list[str], limit: int = 3800) -> list[str]:
    """Greedily pack section strings into embed descriptions within `limit`."""
    descs: list[str] = []
    cur = ""
    for sec in sections:
        piece = sec[:limit]
        if cur and len(cur) + 2 + len(piece) > limit:
            descs.append(cur)
            cur = piece
        else:
            cur = (cur + "\n\n" + piece) if cur else piece
    if cur:
        descs.append(cur)
    return descs


async def _sec_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.sec_edgar import (
            check_recent_filings, fetch_form4_details,
        )
        from consensus_engine.alerts.insider_display import (
            aggregate_insiders, _fmt_date,
        )
        filings = await check_recent_filings(ticker, hours_back=72)
        if not filings:
            await send_command_reply(channel_id, message_id, f"No SEC filings in the last 72h for `${ticker}`.")
            return

        dict_filings = [f for f in filings if isinstance(f, dict)]
        form4 = [f for f in dict_filings if f.get("form") == "4"]
        other = [f for f in dict_filings if f.get("form") != "4"]

        all_txs: list = []
        for f in form4[:8]:
            txs = await fetch_form4_details(
                f.get("cik", ""),
                f.get("accession_number", ""),
                f.get("primary_document", ""),
            )
            all_txs.extend(txs or [])
        summaries, routine = aggregate_insiders(all_txs)

        # Insider blocks (fenced code cards; every insider shown — no top-N cap).
        insider_blocks = _pack_insider_blocks(summaries, routine) if summaries else []
        if not insider_blocks and form4:
            insider_blocks = [
                "Recent Form 4 filings were routine awards / option exercises "
                "— no open-market conviction trades." if routine else
                "Recent Form 4 filings present; insider detail could not be retrieved."
            ]

        sections = list(insider_blocks)
        if other:
            other_lines = ["**Other filings**"]
            for f in other[:12]:
                other_lines.append(f"📄 **{f.get('form', '?')}** · {_fmt_date(f.get('filing_date', ''))}")
            sections.append("\n".join(other_lines))
        if not sections:
            sections = ["No insider or notable filings in the last 72h."]

        embeds = _pack_sec_embeds(sections)
        for i, desc in enumerate(embeds):
            title = (f"📄 SEC Filings — ${ticker} · last 72h" if i == 0
                     else f"📄 SEC Filings — ${ticker} (cont.)")
            await send_command_embed_reply(
                channel_id, message_id,
                {"title": title, "description": desc, "color": 0x2B6CB0},
            )
    except Exception as e:
        log.error("SEC command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"SEC lookup failed for `${ticker}`.")


async def _handle_options(ticker: str, channel_id: str, message_id: str) -> None:
    """Show unusual options activity for a ticker."""
    await send_command_reply(channel_id, message_id, f"Checking options flow for `${ticker}`...")
    return await _dispatch_inner(_options_and_reply(ticker, channel_id, message_id))


_OPT_PT = ZoneInfo("America/Los_Angeles")


def _fmt_opt_pt(ts: float) -> str:
    """Epoch -> 'Fri Jun 26' (Pacific trading day; date only, time dropped)."""
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, _OPT_PT).strftime("%a %b %-d")


_OPT_OTM_MAX = 0.30   # allow OTM directional bets up to 30% from spot
_OPT_ITM_MAX = 0.10   # past 10% ITM the option is stock-like (a hedge), not a bet


def _is_directional(strike: float, spot: float, side: str) -> bool:
    """A contract is a directional bet (vs a far-OTM lottery ticket or a deep-ITM
    hedge/stock-replacement) when its strike sits within 30% OTM / 10% ITM of
    spot. OTM/ITM flips by side: a CALL is OTM above spot, a PUT is OTM below
    spot. No spot (can't classify) -> keep it."""
    if not spot:
        return True
    otm = (strike > spot) if side == "CALL" else (strike < spot)
    dist = abs(strike - spot) / spot
    return dist <= (_OPT_OTM_MAX if otm else _OPT_ITM_MAX)


def _current_day_pool(hits: list) -> list:
    """Keep only contracts that last traded on the MOST RECENT session present
    (today during market hours, the prior session otherwise), so a stale
    high-ratio strike can't surface. Undated input is returned unchanged."""
    dated = [h for h in hits if h.last_trade_ts]
    if not dated:
        return list(hits)
    latest_day = max(
        datetime.fromtimestamp(h.last_trade_ts, _OPT_PT).date() for h in dated
    )
    return [h for h in dated
            if datetime.fromtimestamp(h.last_trade_ts, _OPT_PT).date() == latest_day]


def _build_options_embed(ticker: str, result, top, peak_call: float, peak_put: float) -> dict:
    """Glanceable !options embed (layout B2): two columns — the headline
    contract on the left, the day's call-vs-put flow on the right. The dot
    before the strike is green when the biggest unusual bet is a CALL, red
    when it's a PUT. Card colour follows the day's call/put VOLUME split (a
    robust aggregate), so one cheap far-OTM lotto print can't mislead it.
    peak_call/peak_put are the hottest vol/OI on each side among directional
    contracts (same eligible pool as the headline)."""
    call_vol, put_vol = result.total_call_vol, result.total_put_vol
    total_vol = call_vol + put_vol
    share = (call_vol / total_vol) if total_vol > 0 else 0.5
    color = 0x2ECC71 if share >= 0.55 else 0xE74C3C if share <= 0.45 else 0xF1C40F

    # Right column: the call/put % split + the hottest single contract on EACH
    # side (both now span the same 2 expirations as the headline, so a side's
    # peak agrees with the headline by construction).
    split = call_put_split(call_vol, put_vol)
    if split:
        calls_s, puts_s = split
        flow_lines = [f"🟢 Calls {calls_s}%", f"🔴 Puts {puts_s}%"]
        peak = []
        if peak_call >= 3:
            peak.append(f"🟢 {peak_call:.0f}×")
        if peak_put >= 3:
            peak.append(f"🔴 {peak_put:.0f}×")
        if peak:
            flow_lines.append("  ".join(peak))
        flow_value = "\n".join(flow_lines)
    else:
        flow_value = "No call/put volume yet today."
    flow_field = {"name": "📊 Call vs Put flow", "value": flow_value, "inline": True}

    if top is None:
        return {
            "title": f"📊  ${ticker} — Unusual Options",
            "description": "No standout directional contract on the latest session.",
            "color": color,
            "fields": [flow_field],
        }

    # Dot follows the headline bet's side: 🟢 = a CALL is the biggest unusual
    # contract (heavy call buying), 🔴 = a PUT is.
    arrow = "🟢" if top.side == "CALL" else "🔴"
    try:
        exp_txt = datetime.strptime(top.expiry, "%Y-%m-%d").strftime("%b %-d")
    except ValueError:
        exp_txt = top.expiry
    if top.premium_usd >= 1_000_000:
        prem_txt = f"~${top.premium_usd / 1_000_000:.1f}M"
    else:
        prem_txt = f"~${top.premium_usd / 1_000:.0f}K"

    desc = f"{arrow}  **{exp_txt} · ${top.strike:g} strike**  ·  🗓️ {_fmt_opt_pt(top.last_trade_ts)}"

    contract_lines = [
        f"🔢 {top.volume:,} vs {top.open_interest:,} open",
        f"💰 {prem_txt} traded",
    ]
    if top.spot:
        contract_lines.append(f"📍 Stock ${top.spot:,.2f}")
    contract_field = {"name": "🔥 The contract", "value": "\n".join(contract_lines), "inline": True}

    return {
        "title": f"📊  ${ticker} — Unusual Options",
        "description": desc,
        "color": color,
        "fields": [contract_field, flow_field],
    }


async def _options_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.options import check_unusual_options, scan_options_flow
        # nearest=2 so the call/put % split spans the same 2 expirations the flow
        # scan uses below. (The split counts every contract; the headline + peaks
        # come from the directional-only pool further down.)
        result = await check_unusual_options(ticker, executor=None, nearest=2)
        if not result:
            await send_command_reply(channel_id, message_id, f"No options data available for `${ticker}`.")
            return

        # Permissive thresholds (no premium floor, no staleness gate) — the
        # filters below pick the live session and the meaningful contracts.
        # min_volume=100 drops 1-lot noise.
        hits = await scan_options_flow(
            [ticker], executor=None,
            min_vol_oi=0.01, min_volume=100, min_premium=0,
            max_staleness_min=0, nearest_expirations=2,
        )
        # Keep only directional bets (drop far-OTM lottos + deep-ITM hedges),
        # then the most recent session; rank by vol/OI. Per-side peaks come from
        # the same eligible pool so they agree with the headline.
        pool = _current_day_pool([h for h in hits if _is_directional(h.strike, h.spot, h.side)])
        top = max(pool, key=lambda h: h.vol_oi_ratio) if pool else None
        peak_call = max((h.vol_oi_ratio for h in pool if h.side == "CALL"), default=0.0)
        peak_put = max((h.vol_oi_ratio for h in pool if h.side == "PUT"), default=0.0)

        embed = _build_options_embed(ticker, result, top, peak_call, peak_put)
        await send_command_embed_reply(channel_id, message_id, embed)
    except Exception as e:
        log.error("Options command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Options lookup failed for `${ticker}`.")


async def _handle_em(ticker: str, channel_id: str, message_id: str) -> None:
    """Show the options-implied daily expected move (with chart) for a ticker.

    Works on any optionable ticker; tickers with no listed options or with
    options too illiquid for a reliable straddle get a friendly message from
    compute_em (the open-interest floor is the liquidity gate)."""
    await send_command_reply(channel_id, message_id, f"Calculating expected move for `${ticker}`…")
    return await _dispatch_inner(_em_and_reply(ticker, channel_id, message_id))


async def _em_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    from consensus_engine.scanners import expected_move as em
    from consensus_engine.alerts.discord import send_command_embed_with_image
    try:
        result = await em.compute_em(ticker, executor=None)
        embed = em.build_em_embed(result, with_image=True)
        # Chart render is blocking (matplotlib) — run off the event loop.
        loop = asyncio.get_running_loop()
        image = await loop.run_in_executor(None, em.render_chart, result)
        if image is None:
            embed = em.build_em_embed(result, with_image=False)
        await send_command_embed_with_image(
            channel_id, message_id, embed, image, em.chart_filename(ticker),
        )
    except em.EMUnavailable as e:
        await send_command_reply(channel_id, message_id, str(e))
    except Exception as e:
        log.error("EM command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Expected-move lookup failed for `${ticker}`.")


async def _handle_technical(ticker: str, direction: str, channel_id: str, message_id: str) -> None:
    """Run technical filters for a ticker."""
    await send_command_reply(channel_id, message_id, f"Running technical analysis for `${ticker}` ({direction})...")
    await _dispatch_inner(_technical_and_reply(ticker, direction, channel_id, message_id))


async def _technical_and_reply(ticker: str, direction: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.analysis.technical import verify_technical
        result = await verify_technical(ticker, direction=direction)
        if not result:
            await send_command_reply(channel_id, message_id, f"Could not fetch technical data for `${ticker}`.")
            return
        lines = [f"**Technical — ${ticker}** ({direction.upper()})  {result.passed_count}/{len(result.filters)} filters passed"]
        for f in result.filters:
            icon = "✅" if f.passed else "❌"
            lines.append(f"{icon} {f.name}: {f.value} ({f.threshold})")
        if result.price:
            lines.append(f"Price: **${result.price:.2f}** | Change: {result.price_change_pct:+.2f}%")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Technical command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Technical analysis failed for `${ticker}`.")


# ---------------------------------------------------------------------------
# New Tier 2 handlers
# ---------------------------------------------------------------------------

async def _handle_google_trends(ticker: str, channel_id: str, message_id: str) -> None:
    """Check Google Trends spike for a ticker."""
    await send_command_reply(channel_id, message_id, f"Checking Google Trends for `${ticker}`...")
    return await _dispatch_inner(_google_trends_and_reply(ticker, channel_id, message_id))


async def _google_trends_and_reply(ticker: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.social import scan_google_trends
        results = await scan_google_trends([ticker])
        delta = results.get(ticker)
        if delta is None:
            await send_command_reply(channel_id, message_id, f"No Google Trends data for `${ticker}`.")
            return
        sign = "+" if delta >= 0 else ""
        verdict = "spike detected" if delta >= 20 else "normal interest"
        await send_command_reply(
            channel_id, message_id,
            f"**Google Trends — ${ticker}**\nInterest change: **{sign}{delta:.1f}%** ({verdict})"
        )
    except Exception as e:
        log.error("Google Trends command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Google Trends lookup failed for `${ticker}`.")


async def _run_serpapi_trends(channel_id: str, message_id: str) -> None:
    """Run SerpAPI Google Trends for active DB tickers + ApeWisdom fill (cron job)."""
    if not cfg.get("precision_engine.serpapi_enabled", True):
        await send_command_reply(channel_id, message_id, "SerpAPI Google Trends: Disabled (no credits)")
        return
    from consensus_engine.main import _is_weekend_pause
    if _is_weekend_pause():
        await send_command_reply(channel_id, message_id, "SerpAPI Google Trends: Skipped (weekend pause)")
        return

    await send_command_reply(channel_id, message_id, "Running SerpAPI Google Trends...")
    try:
        from consensus_engine import db
        from consensus_engine.scanners.social import scan_google_trends_serpapi, scan_apewisdom
        from consensus_engine.models import TickerSignal, SourceType, Sentiment

        # DB tickers first (already in signal pipeline), then ApeWisdom fills remaining slots
        db_tickers = await db.get_active_tickers(min_signals=1)
        ape_signals = await scan_apewisdom()
        ape_tickers = [s.ticker for s in ape_signals[:20]]

        seen = set(db_tickers)
        combined = list(db_tickers) + [t for t in ape_tickers if t not in seen]
        active = combined[:10]

        if not active:
            await send_command_reply(channel_id, message_id, "No tickers to scan (DB empty, ApeWisdom unavailable).")
            return

        # Run SerpAPI on combined ticker list
        trends = await scan_google_trends_serpapi(active)
        
        if not trends:
            await send_command_reply(channel_id, message_id, "SerpAPI Google Trends: No data returned.")
            return
        
        # Store results
        for ticker, delta in trends.items():
            await db.insert_signal(TickerSignal(
                ticker=ticker,
                source_type=SourceType.GOOGLE_TRENDS,
                source_detail=f"serpapi delta={delta:.1f}",
                raw_text=f"Google Trends (SerpAPI): {delta:.1f}%",
                sentiment=Sentiment.BULLISH if delta > 0 else Sentiment.NEUTRAL,
            ))
        
        # Format results
        lines = ["**SerpAPI Google Trends Results:**"]
        for ticker, delta in sorted(trends.items(), key=lambda x: -abs(x[1]))[:10]:
            sign = "+" if delta >= 0 else ""
            lines.append(f"  ${ticker}: {sign}{delta:.1f}%")
        
        await send_command_reply(channel_id, message_id, "\n".join(lines))
        
    except Exception as e:
        log.error("SerpAPI trends cron error: %s", e)
        await send_command_reply(channel_id, message_id, f"SerpAPI Google Trends failed: {e}")


async def _handle_apewisdom(channel_id: str, message_id: str) -> None:
    """Show ApeWisdom trending tickers."""
    await send_command_reply(channel_id, message_id, "Fetching ApeWisdom trending...")
    await _dispatch_inner(_apewisdom_and_reply(channel_id, message_id))


async def _apewisdom_and_reply(channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.social import scan_apewisdom
        signals = await scan_apewisdom()
        if not signals:
            await send_command_reply(channel_id, message_id, "No ApeWisdom data available.")
            return
        lines = ["**ApeWisdom Trending**"]
        for i, s in enumerate(signals[:15], 1):
            lines.append(f"**{i}.** `${s.ticker}`")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("ApeWisdom command error: %s", e)
        await send_command_reply(channel_id, message_id, "ApeWisdom scan failed.")


async def _handle_alert_history(ticker: str, channel_id: str, message_id: str) -> None:
    """Show alert history with price outcomes for a ticker."""
    try:
        from consensus_engine import db
        from datetime import datetime
        conn = await db.get_db()
        cursor = await conn.execute(
            """SELECT ticker, confidence_score, catalyst_type, price_at_alert,
                      price_1h_later, price_24h_later, alerted_at
               FROM alert_history
               WHERE ticker = ?
               ORDER BY alerted_at DESC
               LIMIT 10""",
            (ticker,)
        )
        rows = await cursor.fetchall()
        if not rows:
            await send_command_reply(channel_id, message_id, f"No alert history for `${ticker}`.")
            return
        lines = [f"**Alert History — ${ticker}** (last {len(rows)})"]
        for r in rows:
            dt = datetime.fromtimestamp(r["alerted_at"]).strftime("%m/%d %H:%M")
            score = int(r["confidence_score"])
            entry = f"${r['price_at_alert']:.2f}" if r["price_at_alert"] else "n/a"
            pnl_1h = ""
            pnl_24h = ""
            if r["price_at_alert"] and r["price_1h_later"]:
                pct = (r["price_1h_later"] - r["price_at_alert"]) / r["price_at_alert"] * 100
                pnl_1h = f" | 1h: {pct:+.1f}%"
            if r["price_at_alert"] and r["price_24h_later"]:
                pct = (r["price_24h_later"] - r["price_at_alert"]) / r["price_at_alert"] * 100
                pnl_24h = f" | 24h: {pct:+.1f}%"
            catalyst = f" [{r['catalyst_type']}]" if r["catalyst_type"] else ""
            lines.append(f"`{dt}` score={score}{catalyst} entry={entry}{pnl_1h}{pnl_24h}")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Alert-history command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Alert history unavailable for `${ticker}`.")


async def _handle_leaderboard(channel_id: str, message_id: str) -> None:
    """Show analyst performance leaderboard."""
    try:
        from consensus_engine import db
        stats = await db.get_analyst_performance_stats()
        if not stats:
            await send_command_reply(channel_id, message_id, "No analyst performance data yet.")
            return
        lines = ["**Analyst Leaderboard**"]
        for i, s in enumerate(stats[:15], 1):
            sign = "+" if s["avg_pnl_1h"] >= 0 else ""
            lines.append(
                f"**{i}.** `@{s['analyst']}` -- "
                f"{s['total_alerts']} alerts | "
                f"1h: {s['win_rate_1h']:.0f}% ({sign}{s['avg_pnl_1h']:.1f}%) | "
                f"24h: {s['win_rate_24h']:.0f}%"
            )
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Leaderboard command error: %s", e)
        await send_command_reply(channel_id, message_id, "Leaderboard unavailable.")


async def _handle_source_health(channel_id: str, message_id: str) -> None:
    """Show source health status table with freshness and error rate."""
    try:
        from consensus_engine import db, config as cfg
        import time

        rows = await db.get_all_source_health()
        if not rows:
            await send_command_reply(
                channel_id, message_id,
                "No source health data yet — engine must run at least one cycle first.",
            )
            return

        critical = set(cfg.get("source_health.critical_sources", ["finnhub", "yfinance"]))
        source_max_age = cfg.get("source_health.source_max_age", {})
        degraded_mult = cfg.get("source_health.degraded_freshness_multiplier", 5)
        max_error_rate = cfg.get("source_health.max_error_rate", 0.3)

        lines = ["**Source Health**", "```"]
        lines.append(f"{'Source':<24} {'Status':<9} {'Freshness':>12} {'Err%':>5}")
        lines.append("-" * 54)

        for r in rows:
            src = r["source_id"]
            freshness = r["freshness_seconds"]
            err_rate = r["error_rate"]
            max_age = source_max_age.get(src, 300)

            if r["last_heartbeat"] == 0 or freshness > max_age * degraded_mult:
                status = "OFFLINE"
            elif err_rate > max_error_rate or freshness > max_age * 2:
                status = "DEGRADED"
            else:
                status = "OK"

            crit_flag = "*" if src in critical else " "
            fresh_str = f"{int(freshness)}s ago" if freshness < 9990 else "never"
            err_str = f"{err_rate * 100:.0f}%"
            lines.append(f"{crit_flag}{src:<23} {status:<9} {fresh_str:>12} {err_str:>5}")

        lines.append("```")
        lines.append("_* = critical source_")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Source-health command error: %s", e)
        await send_command_reply(channel_id, message_id, "Source health unavailable.")


async def _handle_transcript(youtube_url: str, channel_id: str, message_id: str) -> None:
    """Fetch YouTube video transcript."""
    await send_command_reply(channel_id, message_id, f"Fetching transcript for {youtube_url}...")
    await _dispatch_inner(_transcript_and_reply(youtube_url, channel_id, message_id))


async def _transcript_and_reply(youtube_url: str, channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.utils.transcript_fetch import (
            parse_video_id,
            fetch_transcript_cascade,
        )

        video_id = parse_video_id(youtube_url)
        if not video_id:
            await send_command_reply(
                channel_id, message_id,
                "Could not parse video ID. Use a standard YouTube URL "
                "(watch, shorts, or youtu.be).",
            )
            return

        text, lang, is_auto = await fetch_transcript_cascade(video_id, ["en"])

        caption_type = "auto-generated" if is_auto else "manual"
        header = f"**Transcript** ({lang}, {caption_type}, {len(text)} chars)"
        preview = text[:1500] + "..." if len(text) > 1500 else text
        await send_command_reply(channel_id, message_id, f"{header}\n{preview}")
    except Exception as e:
        log.error("Transcript command error for %s: %s", youtube_url, e)
        await send_command_reply(channel_id, message_id, f"Transcript failed: {e}")


# ---------------------------------------------------------------------------
# Reliability commands
# ---------------------------------------------------------------------------

async def _handle_levels(ticker: str, channel_id: str, message_id: str) -> None:
    """Show price levels (support/resistance) from YouTube + signal_events."""
    try:
        levels = await db.get_youtube_levels_for_ticker(ticker, days=14)
        if not levels:
            await send_command_reply(
                channel_id, message_id,
                f"No price levels found for `${ticker}` in the last 14 days.",
            )
            return

        lines = [f"**Price Levels — ${ticker}** ({len(levels)} zones)"]
        for lv in levels[:10]:
            ltype = lv.get("level_type", "level").upper()
            price = lv.get("price", 0.0)
            conf = lv.get("confidence", 0.0)
            condition = lv.get("condition_text") or ""
            consequence = lv.get("consequence_text") or ""
            channel = lv.get("channel_name") or "unknown"

            conf_bar = "★" * round(conf * 5) + "☆" * (5 - round(conf * 5))
            entry = f"`{ltype}` **${price:.2f}** {conf_bar} [{channel}]"
            if condition:
                entry += f"\n  ↳ IF {condition}"
            if consequence:
                entry += f"\n  ↳ THEN {consequence}"
            lines.append(entry)

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Levels command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Levels lookup failed for `${ticker}`.")


# ---------------------------------------------------------------------------
# YouTube intelligence commands
# ---------------------------------------------------------------------------

def _format_ts(sec: int | None) -> str:
    """Render a video timestamp as ``mm:ss`` (or ``h:mm:ss`` when ≥ 1 hour)."""
    if sec is None:
        return ""
    try:
        s = int(sec)
    except (TypeError, ValueError):
        return ""
    if s < 0:
        s = 0
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _format_verified(verified: int | None) -> str:
    """Return ``✓`` (confirmed), ``?`` (unverified), or ``⚠`` (contradicted)."""
    if verified == 1:
        return "✓"
    if verified == -1:
        return "⚠"
    return "?"


def _format_youtube_option_summary(opt) -> str:
    """Format a VideoOptionIdea (dataclass or dict) as a short Discord line."""
    def _get(attr, key):
        return getattr(opt, attr, None) if hasattr(opt, attr) else (opt.get(key) if hasattr(opt, "get") else None)

    ticker = _get("ticker", "ticker") or "?"
    opt_type = (_get("option_type", "option_type") or "?").upper()
    strike = _get("strike", "strike")
    expiry = _get("expiry", "expiry")
    source = _get("source", "source") or ""
    ts_sec = _get("video_timestamp_sec", "video_timestamp_sec")

    src_icon = "🔥" if "flow" in source.lower() else "💡"
    strike_str = f"${strike:.0f}" if strike is not None else ""
    expiry_str = f" exp {expiry}" if expiry else ""
    ts_str = f" @ {_format_ts(ts_sec)}" if ts_sec is not None else ""
    return f"  {src_icon} `{ticker}` {opt_type} {strike_str}{expiry_str}{ts_str}".rstrip()


def _format_youtube_setup_summary(setup) -> str:
    """Format a VideoTradeSetup (dataclass or dict) as a short Discord line."""
    def _get(attr, key):
        return getattr(setup, attr, None) if hasattr(setup, attr) else (setup.get(key) if hasattr(setup, "get") else None)

    ticker = _get("ticker", "ticker") or "?"
    entry_low = _get("entry_low", "entry_low")
    entry_high = _get("entry_high", "entry_high")
    # dataclass uses 'stop'; DB dict uses 'stop_price'
    stop = _get("stop", "stop") if _get("stop", "stop") is not None else _get("stop_price", "stop_price")
    targets_raw = _get("targets", "targets")
    targets_json = _get("targets_json", "targets_json")
    risk_reward = _get("risk_reward", "risk_reward")
    ts_sec = _get("video_timestamp_sec", "video_timestamp_sec")
    catalyst_date = _get("catalyst_date", "catalyst_date")
    catalyst_desc = _get("catalyst_desc", "catalyst_desc")

    # Resolve targets to a list
    targets: list = []
    if isinstance(targets_raw, list):
        targets = targets_raw
    elif isinstance(targets_json, str):
        import json as _json
        try:
            targets = _json.loads(targets_json)
        except Exception:
            targets = []

    entry_str = f"${entry_low:.0f}–${entry_high:.0f}" if entry_low is not None and entry_high is not None else (f"${entry_low:.0f}" if entry_low is not None else "?")
    stop_str = f"${stop:.0f}" if stop is not None else "?"
    target_str = f"${targets[0]:.0f}" if targets else "?"
    rr_str = f" (R/R {risk_reward:.1f}x)" if risk_reward is not None else ""
    ts_str = f" @ {_format_ts(ts_sec)}" if ts_sec is not None else ""
    catalyst_str = ""
    if catalyst_date:
        desc = f" {catalyst_desc}" if catalyst_desc else ""
        catalyst_str = f" | Catalyst {catalyst_date}{desc}"
    return f"  📐 `{ticker}` Entry {entry_str}{ts_str} | Stop {stop_str} | Target {target_str}{rr_str}{catalyst_str}"


async def _handle_yt(
    youtube_url: str,
    channel_id: str,
    message_id: str,
    author_id: str | None = None,
) -> None:
    """On-demand full analysis of a YouTube video."""
    if author_id:
        limit = int(cfg.get("youtube.user_rate_limit_per_hour", 5) or 5)
        if await db.check_user_rate_limit(author_id, "yt", limit=limit, window_sec=3600):
            await send_command_reply(
                channel_id, message_id,
                f"Rate limit: {limit} `!yt` per hour per user. Try again later.",
            )
            return
        await db.log_user_command(author_id, "yt")
    await send_command_reply(channel_id, message_id, f"Analysing {youtube_url} ...")
    await _dispatch_inner(_yt_analyse_and_reply(youtube_url, channel_id, message_id))


def _format_two_stage_reply(
    title: str,
    channel_name: str,
    bundle,
    result,
    catalysts,
    min_confidence: float,
    require_verified: bool,
) -> str:
    """Render the v2 two-stage `!yt` reply: outline + macro + catalysts + candidates."""
    lines = [f"🎬 **{title}** — {channel_name}", ""]

    # Timestamped outline
    segments = getattr(bundle, "segments", []) or []
    if segments:
        lines.append("**Timestamped outline:**")
        for seg in segments[:20]:
            ts = _format_ts(seg.get("ts_start_sec"))
            seg_title = (seg.get("title") or "").strip()
            lines.append(f"[{ts}] {seg_title}")
        lines.append("")

    # Macro thesis (narrative)
    macro = getattr(result, "macro_thesis", None)
    if macro is not None:
        dir_label = {
            "long": "🟢 BULLISH", "short": "🔴 BEARISH", "neutral": "⚪ NEUTRAL",
        }.get(getattr(macro.direction, "value", str(macro.direction)), "⚪ NEUTRAL")
        lines.append(f"**Macro thesis:** {dir_label}")
        narrative = getattr(macro, "narrative", "") or macro.summary or ""
        if narrative:
            lines.append(narrative[:500])
        lines.append("")

    # Upcoming catalysts
    visible_catalysts = []
    for cat in catalysts or []:
        if require_verified and cat.verified != 1:
            continue
        if cat.suppressed:
            continue
        visible_catalysts.append(cat)
    if visible_catalysts:
        lines.append("**Upcoming catalysts:**")
        for cat in visible_catalysts[:8]:
            date_str = cat.resolved_date or cat.mentioned_date
            mark = _format_verified(cat.verified)
            lines.append(f"• {cat.ticker} {date_str} {cat.catalyst_type} {mark}")
        lines.append("")

    # Tickers (signals)
    visible_signals = [s for s in (result.signals or []) if not s.suppressed
                       and s.classifier_confidence >= min_confidence]
    if visible_signals:
        lines.append("**Tickers:**")
        for sig in visible_signals[:10]:
            dir_icon = {"long": "🟢", "short": "🔴"}.get(sig.direction.value, "⚪")
            conv = sig.conviction.value.upper()
            lines.append(
                f"{dir_icon} {sig.ticker} {sig.direction.value.upper()} "
                f"({conv}, {sig.classifier_confidence:.2f})"
            )
        lines.append("")

    # Setups
    visible_setups = [s for s in (result.setups or []) if not s.suppressed
                      and s.classifier_confidence >= min_confidence]
    if visible_setups:
        lines.append("**Setups:**")
        for setup in visible_setups[:5]:
            lines.append(_format_youtube_setup_summary(setup).lstrip())
        lines.append("")

    # Levels (separate support / resistance rows)
    visible_levels = [lv for lv in (result.levels or []) if not lv.suppressed
                      and lv.classifier_confidence >= min_confidence]
    support = [lv for lv in visible_levels if lv.level_type == "support"]
    resistance = [lv for lv in visible_levels if lv.level_type == "resistance"]
    targets = [lv for lv in visible_levels if lv.level_type == "target"]
    if support or resistance or targets:
        lines.append("**Levels:**")
        for lv in support[:6]:
            ts = _format_ts(lv.video_timestamp_sec)
            ts_str = f" @ {ts}" if ts else ""
            lines.append(f"SUPPORT {lv.ticker} ${lv.price:g}{ts_str}")
        for lv in resistance[:6]:
            ts = _format_ts(lv.video_timestamp_sec)
            ts_str = f" @ {ts}" if ts else ""
            lines.append(f"RESISTANCE {lv.ticker} ${lv.price:g}{ts_str}")
        for lv in targets[:6]:
            ts = _format_ts(lv.video_timestamp_sec)
            ts_str = f" @ {ts}" if ts else ""
            lines.append(f"TARGET {lv.ticker} ${lv.price:g}{ts_str}")

    return "\n".join(lines).rstrip()


async def _yt_analyse_and_reply(youtube_url: str, channel_id: str, message_id: str) -> None:
    try:
        import time as _time
        import aiohttp as _aiohttp
        from consensus_engine.utils.transcript_fetch import parse_video_id, fetch_transcript_cascade
        from consensus_engine.analysis.video_parser import parse_video_transcript

        video_id = parse_video_id(youtube_url)
        if not video_id:
            await send_command_reply(channel_id, message_id, "Could not parse video ID from URL.")
            return

        # oEmbed for title + channel
        title, channel_name = video_id, "unknown"
        try:
            import aiohttp as _aiohttp
            from consensus_engine.utils.http import get_session as _get_session
            sess = await _get_session()
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            async with sess.get(oembed_url, timeout=_aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    title = data.get("title", video_id)
                    channel_name = data.get("author_name", "unknown")
        except Exception:
            pass

        # ── v2 two-stage evidence pipeline (flag-gated) ───────────────────────
        if cfg.get("youtube.use_two_stage", False):
            try:
                from consensus_engine.local_video_ingest import extract_evidence_via_chain
                from consensus_engine.analysis.video_classifier import classify_evidence
                from consensus_engine.analysis.catalyst_resolver import resolve_and_verify_catalysts
                import time as _chain_time

                published_at = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
                _chain_start = _chain_time.monotonic()
                bundle, _telemetry = await extract_evidence_via_chain(
                    video_id, channel_name, published_at,
                )
                _chain_elapsed = _chain_time.monotonic() - _chain_start
                if bundle is not None:
                    result = classify_evidence(bundle)
                    catalysts = await resolve_and_verify_catalysts(
                        result.catalyst_candidates, bundle.publish_ts,
                    )
                    min_conf = float(cfg.get("youtube.classifier.min_confidence", 0.5))
                    require_verified = bool(cfg.get("youtube.catalyst.require_verified", False))
                    msg = _format_two_stage_reply(
                        title, channel_name, bundle, result, catalysts,
                        min_conf, require_verified,
                    )
                    chain_winner = _telemetry.chain_winner or "unknown"
                    msg = f"Extracted {len(bundle.spans)} spans via `{chain_winner}` in {_chain_elapsed:.1f}s.\n" + msg
                    await send_command_reply(channel_id, message_id, msg)
                    return
            except Exception as e:
                log.warning("!yt two-stage error for %s, falling back: %s", video_id, e)
                if not cfg.get("youtube.legacy_fallback", True):
                    await send_command_reply(channel_id, message_id, f"Analysis failed: {e}")
                    return

        # Check if already parsed
        already = await db.has_video_been_processed(video_id)
        if not already:
            text, _lang, _is_auto = await fetch_transcript_cascade(video_id, ["en"])
            if not text:
                await send_command_reply(channel_id, message_id, "Could not fetch transcript for this video.")
                return
            parsed = await parse_video_transcript(
                video_id, text, channel_name, _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
            )
        else:
            # Pull cached signals from DB
            sigs = await db.get_youtube_signals_for_ticker("", days=30)
            sigs = [s for s in sigs if s.get("video_id") == video_id]
            parsed = None

        lines = [f"🎬 **{title}** — {channel_name}"]
        if parsed is not None:
            tickers = parsed.tickers[:5]
            if tickers:
                lines.append("**Tickers:**")
                for t in tickers:
                    dir_icon = {"long": "🟢", "short": "🔴"}.get(t.get("direction", ""), "⚪")
                    lines.append(f"  {dir_icon} `${t['symbol']}` {t.get('direction','').upper()} [{t.get('conviction','').upper()}]")
            else:
                lines.append("No tickers extracted.")

            macro = parsed.macro_thesis
            dir_label = {"long": "BULLISH", "short": "BEARISH", "neutral": "NEUTRAL"}.get(macro.direction.value, str(macro.direction))
            lines.append(f"**Macro:** {dir_label} — {macro.summary[:120] if macro.summary else 'N/A'}")
            lines.append(f"**Conviction:** {parsed.overall_conviction.value.upper()}")

            lvls = parsed.price_levels[:3]
            if lvls:
                lines.append("**Levels:**")
                for lv in lvls:
                    lines.append(f"  `{lv.level_type.upper()}` ${lv.price:.2f} (conf {lv.confidence:.0%})")

            setups = getattr(parsed, "setups", [])[:3]
            if setups:
                lines.append("**Trade Setups:**")
                for s in setups:
                    lines.append(_format_youtube_setup_summary(s))

            options = getattr(parsed, "options", [])[:3]
            if options:
                lines.append("**Options Ideas:**")
                for o in options:
                    lines.append(_format_youtube_option_summary(o))
        else:
            lines.append("Already processed — use `!yt-mentions $TICKER` to see signals.")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("!yt command error for %s: %s", youtube_url, e)
        await send_command_reply(channel_id, message_id, f"Analysis failed: {e}")


async def _handle_yt_mentions(ticker: str, channel_id: str, message_id: str) -> None:
    """Show YouTube signals for a ticker (last 7 days, top 5 by conviction)."""
    try:
        sigs = await db.get_youtube_signals_for_ticker(ticker, days=7)
        if not sigs:
            await send_command_reply(channel_id, message_id, f"No YouTube mentions of `${ticker}` in the last 7 days.")
            return

        _CONV_ORDER = {"high": 0, "medium": 1, "low": 2}
        sigs.sort(key=lambda s: _CONV_ORDER.get(s.get("conviction", "low"), 2))
        sigs = sigs[:5]

        lines = [f"📹 **YouTube Mentions — ${ticker}** ({len(sigs)} results)"]
        for s in sigs:
            dir_icon = {"long": "🟢", "short": "🔴", "neutral": "⚪"}.get(s.get("direction", ""), "⚪")
            conv = s.get("conviction", "").upper()
            ch = s.get("channel_name") or "unknown"
            lines.append(f"{dir_icon} [{ch}] {s.get('direction','').upper()} [{conv}] — video `{s.get('video_id','')}`")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("!yt-mentions command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Lookup failed for `${ticker}`.")


async def build_macro_digest() -> str:
    """Build the macro digest string from youtube_macro (last 7 days)."""
    rows = await db.get_recent_youtube_macro(days=7)
    if not rows:
        return "📊 Macro Digest: No data in the last 7 days."

    counts: dict[str, int] = {"long": 0, "short": 0, "neutral": 0}
    all_themes: list[str] = []
    for r in rows:
        direction = r.get("direction", "neutral").lower()
        norm = {"bullish": "long", "long": "long", "bearish": "short", "short": "short"}.get(direction, "neutral")
        counts[norm] = counts.get(norm, 0) + 1
        all_themes.extend(r.get("themes") or [])

    # Top 3 themes by frequency
    theme_freq: dict[str, int] = {}
    for t in all_themes:
        theme_freq[t] = theme_freq.get(t, 0) + 1
    top_themes = sorted(theme_freq, key=lambda x: -theme_freq[x])[:3]

    bull = counts.get("long", 0)
    bear = counts.get("short", 0)
    neut = counts.get("neutral", 0)
    themes_str = ", ".join(top_themes) if top_themes else "none"
    return f"📊 Macro Digest (via YouTube): BULLISH ({bull} channels) / BEARISH ({bear}) / NEUTRAL ({neut}) — Top themes: {themes_str}"


async def _handle_macro(channel_id: str, message_id: str) -> None:
    """Post macro digest from youtube_macro (last 7 days)."""
    try:
        digest = await build_macro_digest()
        await send_command_reply(channel_id, message_id, digest)
    except Exception as e:
        log.error("!macro command error: %s", e)
        await send_command_reply(channel_id, message_id, "Macro digest unavailable.")


# ---------------------------------------------------------------------------
# !market / !rotation / !breadth / !regime — daily market-CONTEXT dashboard
# ---------------------------------------------------------------------------
#
# This is DESCRIPTIVE market context (a view, not a buy/sell signal). The
# back-tests found no tradeable edge, so nothing here gates an alert. The four
# daily reads (sector rotation, style leadership, price-trend regime, the bot's
# own directional breadth) are written once a day by scripts/market_daily.py and
# read straight back from SQLite via market_panel — no live fetch at command time.
#
# Honest rotation wording is load-bearing: a sector that is "leading" has ALREADY
# moved (it is late, not a fresh entry); a sector that is "improving" is early.

# RRG quadrant -> (heading shown to the user, one-word plain gloss).
_QUADRANT_LABEL = {
    "improving": ("Improving (early)", "weak but turning up"),
    "leading": ("Leading (already moved)", "strong, late — not a fresh entry"),
    "weakening": ("Weakening (rolling over)", "strong but losing steam"),
    "lagging": ("Lagging", "weak and still falling"),
}
# Order groups so the EARLY read is on top and the LATE read is clearly marked.
_QUADRANT_ORDER = ("improving", "leading", "weakening", "lagging")

_TREND_LABEL = {
    "green": "🟢 uptrend (above 200-day, rising)",
    "yellow": "🟡 mixed / transitioning",
    "red": "🔴 downtrend (below 200-day, falling)",
}

_MARKET_DISCLAIMER = (
    "Market CONTEXT only — a view, not a buy/sell signal. No edge was found in "
    "back-testing; this just shows where money has been rotating."
)


def _pdt_now_str() -> str:
    """Current time as a PDT label (never ET — house rule)."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M PDT")


def _build_market_embed(
    sector_rows: list[dict],
    factor_rows: list[dict],
    trend_row: Optional[dict],
    breadth_row: Optional[dict],
    breadth_note: str,
) -> dict:
    """Render the four persisted daily reads into one Discord embed (pure).

    ``sector_rows`` / ``factor_rows`` are all rows for the latest date;
    ``trend_row`` / ``breadth_row`` are the single newest rows (or None).
    """
    fields: list[dict] = []

    # --- Sector rotation leaderboard, grouped by quadrant (early -> late) -----
    as_of = ""
    if sector_rows:
        as_of = sector_rows[0].get("date_utc", "")
        by_q: dict[str, list[dict]] = {q: [] for q in _QUADRANT_ORDER}
        for r in sector_rows:
            by_q.setdefault(r["quadrant"], []).append(r)
        lines: list[str] = []
        for q in _QUADRANT_ORDER:
            group = by_q.get(q) or []
            if not group:
                continue
            heading, gloss = _QUADRANT_LABEL[q]
            # Strongest relative-strength first within each group.
            group.sort(key=lambda x: x["rs_ratio"], reverse=True)
            etfs = ", ".join(f"`{r['etf']}`" for r in group)
            star = " ⭐" if any(r.get("inflection") for r in group) else ""
            lines.append(f"__{heading}__ — _{gloss}_{star}\n{etfs}")
        fields.append({
            "name": "🔄  Sector rotation (13 ETFs vs SPY)",
            "value": "\n".join(lines) or "no data",
            "inline": False,
        })

    # --- Style / factor leadership -------------------------------------------
    if factor_rows:
        leaders = [r for r in factor_rows if r.get("leading")]
        leaders.sort(key=lambda x: x["rs_vs_spy"], reverse=True)
        if leaders:
            top = leaders[0]
            accel = top.get("accelerating")
            accel_txt = ("speeding up" if accel in (1, True)
                         else "fading" if accel in (0, False) else "flat")
            lead_line = (f"Leading style: `{top['factor_etf']}` "
                         f"(+{top['rs_vs_spy']:.1f} vs SPY, {accel_txt})")
            others = ", ".join(f"`{r['factor_etf']}`" for r in leaders[1:6])
            value = lead_line + (f"\nAlso leading: {others}" if others else "")
        else:
            value = "No style is beating SPY right now (broad market leads)."
        fields.append({
            "name": "🎚️  Style leadership (factor ETFs)",
            "value": value,
            "inline": False,
        })

    # --- Price-trend / direction regime --------------------------------------
    if trend_row:
        state = trend_row.get("trend_state", "")
        label = _TREND_LABEL.get(state, state or "unknown")
        sym = trend_row.get("index_symbol", "SPY")
        close = trend_row.get("close")
        sma200 = trend_row.get("sma_200")
        pct = ""
        if close and sma200:
            pct = f" ({(close / sma200 - 1) * 100:+.1f}% vs its 200-day average)"
        fields.append({
            "name": "📈  Price-trend regime",
            "value": f"`{sym}`: {label}{pct}",
            "inline": False,
        })

    # --- Internal breadth (the bot's OWN directional stream) ------------------
    if breadth_row:
        net = breadth_row.get("net_bull_bear", 0)
        nb = breadth_row.get("n_bullish", 0)
        ns = breadth_row.get("n_bearish", 0)
        z = breadth_row.get("osc_z", 0.0)
        lean = "more bullish than usual" if z > 0.5 else \
               "more bearish than usual" if z < -0.5 else "about average"
        fields.append({
            "name": "🐂  Our own signal breadth",
            "value": (f"Net {net:+d} ({nb} bullish − {ns} bearish tickers), "
                      f"trend z-score {z:+.2f} → {lean}.\n_{breadth_note}_"),
            "inline": False,
        })

    title = "📊  Market Context"
    if as_of:
        title += f" — as of {as_of} (prior close)"
    return {
        "title": title,
        "description": _MARKET_DISCLAIMER,
        "color": 0x95A5A6,  # slate — neutral, not green/red, so it never reads as a call
        "fields": fields or [{"name": "No data yet",
                              "value": "The daily market read has not run yet.",
                              "inline": False}],
        "footer": {"text": f"OpenClaw market context · a view, not a signal · {_pdt_now_str()}"},
    }


# #47 "better way": plain-English, HAZARD-framed translation of a market-scope
# Wolf thesis. Bear on an index = a top / downside risk (never "SELL").
_MKT_DIR_WORD = {"bear": "top / downside risk", "bull": "bottom / upside"}
_MKT_STAGE_WORD = {
    "forming": "early — forming",
    "diverging": "building",
    "imminent": "imminent",
    "acting": "acting (Wolf has a position)",
}


async def _build_market_context_fields() -> list[dict]:
    """#47 'better way' — surface the FRESH, engine-native market-regime signals as
    component-first DESCRIPTIVE context (no composite score; divergence stays visible).

    Leads with Wolf's market-level top/bottom theses + cross-source confluence (a
    qualitatively different, analyst-driven signal that was never inside the quant
    kill-gate), then the volatility-regime label. A validated free *predictor* of
    SPY/QQQ turns was proven NO-GO across many phases, so this is strictly context —
    never a forecast, and deliberately NOT fused into a single 'risk score'.
    """
    from consensus_engine import db
    fields: list[dict] = []

    # --- Wolf market-level theses + confluence (lead — the different mechanism) ---
    try:
        conn = await db.get_db()
        cur = await conn.execute(
            """SELECT m.scope_key, m.direction, m.stage,
                      c.agree_count, c.disagree_count
                 FROM macro_theses m
                 LEFT JOIN wolf_confluence_checks c ON c.thesis_id = m.id
                WHERE m.scope_type = 'market'
                  AND COALESCE(m.status, 'active') = 'active'
                ORDER BY m.last_updated DESC LIMIT 6"""
        )
        theses = await cur.fetchall()
    except Exception:
        theses = []

    if theses:
        lines = []
        for t in theses:
            side = _MKT_DIR_WORD.get(t["direction"], t["direction"])
            stage = _MKT_STAGE_WORD.get(t["stage"], t["stage"])
            agree = t["agree_count"] or 0
            disagree = t["disagree_count"] or 0
            if agree >= 1 and agree >= disagree:
                conf = f"{agree} other source(s) agree"
            elif disagree > agree:
                conf = f"others lean the other way ({disagree}) — analysts divided"
            else:
                conf = "Wolf alone so far"
            lines.append(f"• **{t['scope_key']}** — {side} ({stage}); {conf}")
        fields.append({
            "name": "🌊  Wolf's market read (analyst view, not the bot's)",
            "value": "\n".join(lines) + (
                "\n_Expert-newsletter theses + how the bot's other sources line up. "
                "A view, not a forecast._"),
            "inline": False,
        })

    # --- Volatility regime (engine-native, fresh; read regime_daily directly —
    # market_panel.get_latest_row allowlists only the 4 RS/breadth tables) ---
    label = None
    try:
        conn = await db.get_db()
        cur = await conn.execute(
            "SELECT regime_label FROM regime_daily ORDER BY date_utc DESC LIMIT 1"
        )
        rrow = await cur.fetchone()
        if rrow:
            label = rrow["regime_label"]
    except Exception:
        label = None
    if label:
        gloss = {
            "calm": "quiet tape — low realized volatility",
            "normal": "ordinary volatility",
            "elevated": "stress building — above-normal volatility",
            "panic": "high stress — volatility spiking",
        }.get(label, "")
        fields.append({
            "name": "🌡️  Volatility regime",
            "value": f"**{label}**{(' — ' + gloss) if gloss else ''}.",
            "inline": False,
        })

    return fields


async def _handle_market(channel_id: str, message_id: str) -> None:
    """Reply with the daily market-CONTEXT dashboard (read-only, no edge claim).

    Reads the four persisted daily tables (sector_rs_daily, factor_rs_daily,
    trend_daily, internal_breadth_daily) through market_panel and renders one
    embed. Leads with descriptive market-regime context (#47: Wolf market theses +
    confluence + volatility regime). Gated by ``features.market_command.enabled``.
    """
    if not cfg.get("features.market_command.enabled", False):
        await send_command_reply(
            channel_id, message_id,
            "`!market` is not enabled yet. It shows daily market context "
            "(sector rotation, style leadership, trend, breadth) — a view, not a signal.",
        )
        return
    try:
        from consensus_engine.analysis import market_panel
        from consensus_engine.analysis.internal_breadth import LONG_BIAS_NOTE

        sector_latest = await market_panel.get_latest_row("sector_rs_daily")
        sector_rows: list[dict] = []
        if sector_latest:
            sector_rows = await market_panel.get_recent_rows(
                "sector_rs_daily", limit=64,
                filters={"date_utc": sector_latest["date_utc"]})

        factor_latest = await market_panel.get_latest_row("factor_rs_daily")
        factor_rows: list[dict] = []
        if factor_latest:
            factor_rows = await market_panel.get_recent_rows(
                "factor_rs_daily", limit=64,
                filters={"date_utc": factor_latest["date_utc"]})

        trend_row = await market_panel.get_latest_row("trend_daily")
        breadth_row = await market_panel.get_latest_row("internal_breadth_daily")

        embed = _build_market_embed(
            sector_rows, factor_rows, trend_row, breadth_row, LONG_BIAS_NOTE)
        # #47 "better way": lead with the descriptive market-regime context
        # (Wolf market theses + confluence, then the volatility regime). Fail-soft —
        # the existing dashboard renders unchanged if these sources are unavailable.
        try:
            context_fields = await _build_market_context_fields()
            if context_fields:
                embed["fields"] = context_fields + embed["fields"]
        except Exception as ctx_exc:
            log.debug("market context fields unavailable: %s", ctx_exc)
        await send_command_embed_reply(channel_id, message_id, embed)
    except Exception as e:
        log.error("!market command error: %s", e)
        await send_command_reply(channel_id, message_id, "Market context unavailable.")


# ---------------------------------------------------------------------------
# !yt-follow
# ---------------------------------------------------------------------------

async def _handle_yt_follow(handle_or_url: str, channel_id: str, message_id: str) -> None:
    """Resolve a YouTube @handle or channel URL to a channel_id and add it to the follow list."""
    await send_command_reply(channel_id, message_id, f"Looking up `{handle_or_url}`...")
    await _dispatch_inner(_yt_follow_and_reply(handle_or_url, channel_id, message_id))


async def _yt_follow_and_reply(handle_or_url: str, channel_id_discord: str, message_id: str) -> None:
    import re
    import json as _json
    from consensus_engine.utils.http import get_session

    # Normalise input → canonical URL
    raw = handle_or_url.strip().lstrip("@")
    if handle_or_url.startswith("@"):
        url = f"https://www.youtube.com/@{raw}"
    elif "youtube.com" in handle_or_url:
        url = handle_or_url if handle_or_url.startswith("http") else f"https://{handle_or_url}"
    else:
        url = f"https://www.youtube.com/@{raw}"

    try:
        session = await get_session()
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True) as resp:
            if resp.status != 200:
                await send_command_reply(channel_id_discord, message_id, f"Could not fetch channel page (HTTP {resp.status}).")
                return
            html = await resp.text()

        # Extract channel_id from page HTML
        m = re.search(r'"channelId"\s*:\s*"(UC[^"]{20,})"', html)
        if not m:
            # Fallback: canonical link
            m = re.search(r'href="https://www\.youtube\.com/channel/(UC[^"]{20,})"', html)
        if not m:
            await send_command_reply(channel_id_discord, message_id, f"Could not find a channel ID for `{handle_or_url}`. Make sure the handle is correct.")
            return

        yt_channel_id = m.group(1)

        # Extract display name
        name_m = re.search(r'"title"\s*:\s*"([^"]+)".*?"channelId"\s*:\s*"' + re.escape(yt_channel_id), html, re.DOTALL)
        if not name_m:
            name_m = re.search(r'<title>([^<]+)\s*-\s*YouTube</title>', html)
        display_name = name_m.group(1).strip() if name_m else yt_channel_id

        # Check if already followed
        existing = await db.get_channel_display_name(yt_channel_id)
        if existing != yt_channel_id:  # found a real name → already in DB
            await send_command_reply(channel_id_discord, message_id, f"Already following **{existing}** (`{yt_channel_id}`).")
            return

        # Insert into DB
        conn = await db.get_db()
        await conn.execute(
            "INSERT OR IGNORE INTO youtube_channels (channel_id, display_name, approved, trust_score) VALUES (?, ?, 1, 1.0)",
            (yt_channel_id, display_name),
        )
        await conn.commit()

        # Persist to sources.json
        sources_path = "/root/.openclaw/sources.json"
        try:
            with open(sources_path) as f:
                sources = _json.load(f)
            channels = sources.setdefault("youtube_channels", [])
            if not any(c.get("channel_id") == yt_channel_id for c in channels):
                channels.append({"channel_id": yt_channel_id, "display_name": display_name})
                with open(sources_path, "w") as f:
                    _json.dump(sources, f, indent=2)
        except Exception as e:
            log.warning("!yt-follow: could not update sources.json: %s", e)

        await send_command_reply(
            channel_id_discord, message_id,
            f"✅ Now following **{display_name}** (`{yt_channel_id}`). New videos will be scanned automatically."
        )

    except Exception as e:
        log.error("!yt-follow error for %s: %s", handle_or_url, e)
        await send_command_reply(channel_id_discord, message_id, f"Error looking up channel: {e}")


# ---------------------------------------------------------------------------
# !yt-health  + !yt-evidence   (Phase P8 observability)
# ---------------------------------------------------------------------------

async def _handle_yt_health(channel_id: str, message_id: str) -> None:
    """7-day YouTube pipeline health: runs, parse rate, tokens, latency, budget,
    top channels, suppression count."""
    try:
        from consensus_engine.engine import BudgetManager
        conn = await db.get_db()
        cur = await conn.execute(
            """SELECT
                   COUNT(*) AS total_runs,
                   SUM(CASE WHEN json_parse_ok = 1 THEN 1 ELSE 0 END) AS parse_ok,
                   AVG(span_count) AS avg_spans,
                   SUM(input_tokens) AS total_in,
                   SUM(output_tokens) AS total_out,
                   AVG(latency_ms) AS avg_latency_ms,
                   SUM(filter_drop_count) AS total_suppressed
               FROM youtube_analysis_runs
               WHERE started_at >= strftime('%s', 'now') - 7*24*3600"""
        )
        row = await cur.fetchone()
        total_runs = (row["total_runs"] or 0) if row else 0
        parse_ok = (row["parse_ok"] or 0) if row else 0
        avg_spans = (row["avg_spans"] or 0.0) if row else 0.0
        total_in = (row["total_in"] or 0) if row else 0
        total_out = (row["total_out"] or 0) if row else 0
        avg_latency_ms = (row["avg_latency_ms"] or 0.0) if row else 0.0
        total_suppressed = (row["total_suppressed"] or 0) if row else 0
        parse_pct = (parse_ok / total_runs * 100.0) if total_runs else 0.0

        budget = BudgetManager()
        budget_in_pct = await budget.pct_used("gemini_input_tokens")
        budget_out_pct = await budget.pct_used("gemini_output_tokens")
        budget_calls_pct = await budget.pct_used("gemini_video_calls")

        cur = await conn.execute(
            """SELECT channel_name, COUNT(*) AS n
               FROM youtube_signals
               WHERE extracted_at >= strftime('%s','now') - 7*24*3600
                 AND channel_name IS NOT NULL
               GROUP BY channel_name
               ORDER BY n DESC
               LIMIT 5"""
        )
        top_channels = await cur.fetchall()
        top_channels_str = (
            ", ".join(f"{c['channel_name']} ({c['n']})" for c in top_channels)
            if top_channels else "none"
        )

        lines = [
            "📊 **YouTube Pipeline Health — last 7 days**",
            f"Videos analyzed: {total_runs}   Parse-ok: {parse_pct:.1f}%",
            f"Avg spans/video: {avg_spans:.1f}   Avg latency: {avg_latency_ms/1000:.1f}s",
            f"Gemini tokens: in {total_in:,}  out {total_out:,}",
            f"Candidates suppressed: {total_suppressed}",
            f"**Budget used today:** input {budget_in_pct:.0f}%  output {budget_out_pct:.0f}%  calls {budget_calls_pct:.0f}%",
            f"**Top channels (7d):** {top_channels_str}",
        ]
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("!yt-health error: %s", e, exc_info=True)
        await send_command_reply(channel_id, message_id, "YouTube health unavailable.")


async def _handle_yt_evidence(video_id: str, channel_id: str, message_id: str) -> None:
    """Show the first 10 grounded evidence spans extracted from a video_id so
    users can audit any alert."""
    try:
        conn = await db.get_db()
        cur = await conn.execute(
            """SELECT ts_sec, quote
               FROM youtube_evidence_spans
               WHERE video_id = ?
               ORDER BY ts_sec ASC
               LIMIT 10""",
            (video_id,),
        )
        rows = await cur.fetchall()
        if not rows:
            await send_command_reply(
                channel_id, message_id,
                f"No evidence spans for `{video_id}`. "
                "Either not analyzed yet or pre-v2 run.",
            )
            return
        lines = [f"🔎 **Evidence spans for `{video_id}`** (first {len(rows)})"]
        for r in rows:
            ts = int(r["ts_sec"] or 0)
            mm, ss = divmod(ts, 60)
            quote = (r["quote"] or "").strip().replace("\n", " ")
            if len(quote) > 160:
                quote = quote[:157] + "..."
            lines.append(f"`{mm:02d}:{ss:02d}` — {quote}")
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("!yt-evidence error for %s: %s", video_id, e, exc_info=True)
        await send_command_reply(channel_id, message_id, "Evidence lookup failed.")


# ---------------------------------------------------------------------------
# Feature flag commands
# ---------------------------------------------------------------------------

async def _handle_feature_health(channel_id: str, message_id: str) -> None:
    """List all 6 features with enabled state + last audit row."""
    from consensus_engine.utils.feature_flags import KNOWN_FEATURES, read_feature_state, audit_history
    lines = ["**Feature Flag Health**"]
    for name in KNOWN_FEATURES:
        state = await read_feature_state(name)
        icon = "🟢" if state else "⚫"
        lines.append(f"{icon} `{name}`: {'enabled' if state else 'disabled'}")
    # Last 3 audit rows
    history = await audit_history(limit=3)
    if history:
        lines.append("\n**Recent flips:**")
        for row in history:
            import datetime
            ts = datetime.datetime.utcfromtimestamp(row["flipped_at"]).strftime("%Y-%m-%d %H:%M")
            direction = "→ON" if row["new_state"] else "→OFF"
            lines.append(f"• `{row['feature']}` {direction} at {ts} ({row['reason'] or 'no reason'})")
    await send_command_reply(channel_id, message_id, "\n".join(lines))


async def _handle_shadow_mode_report(feature: str, channel_id: str, message_id: str) -> None:
    """Compute KPIs from last 14d shadow feature_vector_json data."""
    from consensus_engine.utils.feature_flags import KNOWN_FEATURES
    if feature not in KNOWN_FEATURES:
        await send_command_reply(channel_id, message_id, f"Unknown feature `{feature}`. Known: {', '.join(KNOWN_FEATURES)}")
        return
    try:
        import json
        import time
        conn = await db.get_db()
        cutoff = time.time() - 14 * 86400
        cur = await conn.execute(
            "SELECT feature_vector_json, decision FROM decision_snapshots WHERE recorded_at >= ? ORDER BY recorded_at DESC LIMIT 500",
            (cutoff,),
        )
        rows = await cur.fetchall()
        if not rows:
            await send_command_reply(channel_id, message_id, f"No shadow data found for `{feature}` in the last 14 days.")
            return

        # Map feature names to feature_vector_json keys
        key_map = {
            "contradiction_penalty": "contradiction_verdict",
            "regime_classifier": "regime_context",
            "sector_confirmation": "sector_verdict",
            "cross_source_consolidation": "consolidation_result",
            "analyst_herding": "cluster_membership",
            "form4_cluster": None,  # D1 has no shadow mode; gated on kill-switch
        }
        fv_key = key_map.get(feature)
        if fv_key is None:
            await send_command_reply(channel_id, message_id, f"`{feature}` does not have shadow-mode KPIs (it is gated on the kill-switch).")
            return

        total = 0
        disagree = 0
        for row in rows:
            fv = json.loads(row["feature_vector_json"] or "{}")
            if fv_key not in fv:
                continue
            total += 1
            # Disagreement: shadow result differs from live decision
            shadow_data = fv[fv_key]
            if isinstance(shadow_data, dict) and shadow_data.get("apply_penalty") and row["decision"] == "STRONG_ALERT":
                disagree += 1
            elif isinstance(shadow_data, dict) and shadow_data.get("threshold_shift", 0) != 0:
                disagree += 1
            elif isinstance(shadow_data, dict) and shadow_data.get("consensus_boost", 0) != 0:
                disagree += 1

        if total == 0:
            await send_command_reply(channel_id, message_id, f"No `{fv_key}` entries in shadow data yet for `{feature}`.")
            return

        disagree_rate = disagree / total * 100
        lines = [
            f"**Shadow-Mode Report: `{feature}`**",
            f"Snapshots analyzed (last 14d): {total}",
            f"Disagreement rate: {disagree_rate:.1f}%",
            f"Note: Brier-Δ CI requires outcome data (price_1h/24h). Run after outcomes populate.",
            f"\n*Shadow rows present — feature is computing. Ready for KPI-gated flip when thresholds met.*",
        ]
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.exception("shadow_mode_report error for %s", feature)
        await send_command_reply(channel_id, message_id, f"Error computing shadow report: {e}")


async def _handle_cluster_history(ticker: str, channel_id: str, message_id: str) -> None:
    """Reply with last 5 analyst cluster events for a ticker."""
    try:
        import json
        import time
        conn = await db.get_db()
        cur = await conn.execute(
            """SELECT id, cluster_size, effective_size, members_json, regime_label, fired_at
               FROM cluster_events
               WHERE ticker = ?
               ORDER BY fired_at DESC
               LIMIT 5""",
            (ticker,),
        )
        rows = await cur.fetchall()
        if not rows:
            await send_command_reply(channel_id, message_id, f"No analyst cluster events found for `${ticker}`.")
            return
        import datetime as _dt
        lines = [f"**Analyst Cluster History — ${ticker}** (last {len(rows)})"]
        for row in rows:
            ts = _dt.datetime.utcfromtimestamp(row["fired_at"]).strftime("%Y-%m-%d %H:%M UTC")
            members = json.loads(row["members_json"] or "[]")
            analysts = ", ".join(m.get("analyst", "?") for m in members[:5])
            if len(members) > 5:
                analysts += f" +{len(members) - 5} more"
            lines.append(
                f"• [{ts}] cluster_id={row['id']} size={row['cluster_size']} "
                f"effective={row['effective_size']:.1f} regime={row['regime_label'] or 'n/a'}\n"
                f"  Analysts: {analysts}"
            )
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.exception("cluster_history error for %s", ticker)
        await send_command_reply(channel_id, message_id, f"Error fetching cluster history: {e}")
