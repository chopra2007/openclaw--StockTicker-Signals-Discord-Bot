"""Alfred: morning Discord briefing with a transactional outbox."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db

_ET = ZoneInfo("America/New_York")

log = logging.getLogger("consensus_engine.briefing.alfred")


async def build_briefing_data(session_start_utc: float,
                              session_end_utc: float) -> dict:
    """Gather all source data Alfred needs to synthesize a brief."""
    conn = await db.get_db()

    # Overnight alerts
    cur = await conn.execute(
        """SELECT ticker, confidence_score, catalyst, catalyst_type,
                  alerted_at, price_at_alert
           FROM alert_history
           WHERE alerted_at BETWEEN ? AND ?
           ORDER BY alerted_at DESC""",
        (session_start_utc, session_end_utc),
    )
    alerts = [dict(r) for r in await cur.fetchall()]

    # Pending youtube_levels (last 14d, not triggered)
    levels_cutoff = time.time() - 14 * 86400
    cur = await conn.execute(
        """SELECT ticker, level_type, price, condition_text, consequence_text,
                  channel_name, published_at
           FROM youtube_levels
           WHERE extracted_at >= ?
           ORDER BY extracted_at DESC LIMIT 30""",
        (levels_cutoff,),
    )
    levels = [dict(r) for r in await cur.fetchall()]

    # High-conviction youtube_signals, last 7d, directional
    yt_cutoff = time.time() - 7 * 86400
    cur = await conn.execute(
        """SELECT ticker, direction, conviction, channel_name, macro_thesis,
                  published_at
           FROM youtube_signals
           WHERE extracted_at >= ?
             AND conviction='high' AND direction != 'neutral'
           ORDER BY extracted_at DESC LIMIT 20""",
        (yt_cutoff,),
    )
    yt_signals = [dict(r) for r in await cur.fetchall()]

    # Latest macro regime
    cur = await conn.execute(
        "SELECT direction, themes, timeframe, summary, confidence, published_at "
        "FROM youtube_macro ORDER BY id DESC LIMIT 1"
    )
    row = await cur.fetchone()
    macro = dict(row) if row else None

    # Top tickers (last 24h) + their research sections
    top = await db.get_top_tickers_session(session_end_utc - 86400, session_end_utc, limit=5)
    top_tickers = []
    for t in top:
        sections = await db.get_research_sections(t)
        top_tickers.append({"ticker": t, "sections": sections})

    return {
        "session_start_utc": session_start_utc,
        "session_end_utc": session_end_utc,
        "alerts": alerts,
        "levels": levels,
        "yt_signals": yt_signals,
        "macro": macro,
        "top_tickers": top_tickers,
    }


async def _llm_synthesize(prompt: str) -> str:
    """OpenRouter call using the same llm.model as llm_scorer.py."""
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        return ""
    model = cfg.get("llm.model", "minimax/minimax-m2.5")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content":
                            "You are a pre-market briefing writer. Produce concise, "
                            "actionable markdown. Lead with the most important story. "
                            "Keep under 1500 characters."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": cfg.get("llm.max_tokens", 1024),
                    "temperature": 0.3,
                },
                timeout=aiohttp.ClientTimeout(total=45),
            ) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
                return (data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content") or "").strip()
    except Exception as exc:
        log.warning("Alfred LLM call failed: %s", exc)
        return ""


def _fallback_render(data: dict) -> str:
    lines = ["## Morning Brief",
             f"_{datetime.now(tz=_ET).strftime('%Y-%m-%d %H:%M ET')}_", ""]
    if data["alerts"]:
        lines.append("**Overnight alerts:**")
        for a in data["alerts"][:10]:
            lines.append(
                f"- {a['ticker']} ({a['confidence_score']:.0f}) — {a['catalyst']}"
            )
        lines.append("")
    if data["top_tickers"]:
        lines.append("**Top tickers last 24h:**")
        for t in data["top_tickers"]:
            lines.append(f"- {t['ticker']}")
        lines.append("")
    if data["macro"]:
        lines.append(f"**Macro:** {data['macro']['direction']} — {data['macro'].get('summary', '')[:160]}")
    if len(lines) <= 3:
        lines.append("_No material overnight activity._")
    return "\n".join(lines)


async def _render_briefing(data: dict) -> str:
    """Try LLM synthesis; fall back to a template if LLM is unavailable."""
    alert_lines = [
        f"- {a['ticker']} ({a['confidence_score']:.0f}/100) — {a['catalyst']}"
        for a in data["alerts"][:15]
    ]
    level_lines = [
        f"- {l['ticker']} {l['level_type']} ${l['price']}: {l.get('condition_text', '')}"
        for l in data["levels"][:10]
    ]
    yt_lines = [
        f"- {s['ticker']} {s['direction']} ({s['channel_name']}): {s.get('macro_thesis', '')[:140]}"
        for s in data["yt_signals"][:10]
    ]
    macro = data["macro"]
    macro_block = (
        f"Macro: {macro['direction']} — themes={macro.get('themes','')} — {macro.get('summary','')[:200]}"
        if macro else "Macro: no recent regime update"
    )
    top_lines = []
    for t in data["top_tickers"]:
        secs = t["sections"]
        analyst = (secs.get("analyst") or {}).get("content") or (secs.get("analyst") or {}).get("last_good_content") or ""
        top_lines.append(f"- **{t['ticker']}** — {analyst[:300]}")

    prompt = (
        "Build a morning Discord briefing from the data below. "
        "Sections: Overnight, Levels to Watch, High-Conviction Analyst Calls, "
        "Macro, Top Tickers. Keep under 1500 characters total. Markdown.\n\n"
        f"## Overnight alerts\n" + ("\n".join(alert_lines) or "_none_") + "\n\n"
        f"## Levels\n" + ("\n".join(level_lines) or "_none_") + "\n\n"
        f"## YT Signals\n" + ("\n".join(yt_lines) or "_none_") + "\n\n"
        f"## {macro_block}\n\n"
        f"## Top Tickers\n" + ("\n".join(top_lines) or "_none_")
    )
    out = await _llm_synthesize(prompt)
    if out:
        return out
    return _fallback_render(data)


async def _send_discord_briefing(content: str) -> str | None:
    """POST a briefing to the dedicated channel. Returns Discord message id."""
    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("alfred.channel_id", "") or
                     cfg.get("api_keys.discord_briefing_channel_id", "") or "")
    if not token or not channel_id:
        log.warning("Alfred Discord: missing bot token or briefing channel id")
        return None
    if getattr(cfg, "dry_run", False):
        log.info("[DRY-RUN] Alfred would post to %s: %s", channel_id, content[:80])
        return "dry-run"

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    # Discord hard limit is 2000 chars.
    payload = {"content": content[:1990]}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers={"Authorization": f"Bot {token}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status not in (200, 201):
                    log.warning("Alfred Discord post failed: %d", resp.status)
                    return None
                data = await resp.json()
                return str(data.get("id", ""))
    except Exception as exc:
        log.error("Alfred Discord send error: %s", exc)
        return None


import asyncio as _asyncio
import os as _os


async def _write_vault_briefing(session_key: str, content: str, vault_path: str) -> str:
    """Atomically write vault/macro/briefings/{session_key}.md."""
    dest_dir = _os.path.join(vault_path, "macro", "briefings")
    _os.makedirs(dest_dir, exist_ok=True)
    final = _os.path.join(dest_dir, f"{session_key}.md")
    tmp = final + ".tmp"

    def _write():
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        _os.replace(tmp, final)

    await _asyncio.get_event_loop().run_in_executor(None, _write)
    log.info("Alfred archived briefing to %s", final)
    return final
