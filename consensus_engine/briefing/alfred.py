"""Alfred: morning Discord briefing with a transactional outbox."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.http import get_session
from consensus_engine import db
from consensus_engine.alerts.discord import _safe_send_kwargs

_ET = ZoneInfo("America/New_York")        # internal: market-session scheduling only (never shown to the user)
_PT = ZoneInfo("America/Los_Angeles")     # display: all user-facing timestamps are PDT

log = logging.getLogger("consensus_engine.briefing.alfred")

# The five sections are the card's fixed spine: same order every morning, and an
# empty one renders a placeholder rather than vanishing, so "nothing happened"
# is distinguishable from "the brief broke".
_SECTION_KEYS = ("overnight", "levels", "calls", "macro", "top_tickers")
# Emoji match the owner's 2026-07-30 reference brief, which used them as visual
# anchors so the five sections can be found at a glance on a phone.
_SECTION_TITLES = {
    "overnight": "🌙  Overnight",
    "levels": "📊  Levels to Watch (SPY)",
    "calls": "🚀  High-Conviction Calls",
    "macro": "📈  Macro",
    "top_tickers": "🔝  Top Tickers",
}
_SECTION_EMPTY = {
    "overnight": "_Nothing overnight._",
    "levels": "_No levels in range._",
    "calls": "_No high-conviction calls._",
    "macro": "_No recent regime update._",
    "top_tickers": "_No tickers stood out._",
}
_MAX_SECTION_CHARS = 3000     # AI output longer than this is treated as malformed

# Discord hard limits.
_MAX_FIELD_VALUE = 1024
_MAX_DESCRIPTION = 4096
_MAX_EMBED_TOTAL = 6000

_BRIEF_COLOR = 0x5865F2
SPY_EM_DAILY_FILE = "SPY_em_daily.png"
SPY_EM_WEEKLY_FILE = "SPY_em_weekly.png"
_MAX_ATTACHMENT_BYTES = 7 * 1024 * 1024   # well under Discord's cap; guards the weekly extra


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
           WHERE extracted_at >= ? AND suppressed = 0
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
             AND suppressed = 0
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
    """OpenRouter call using llm.model + llm.fallback_models chain."""
    from consensus_engine.llm_client import call_with_fallback
    return await call_with_fallback(
        role="primary",
        messages=[
            {"role": "system", "content":
                "You are a pre-market briefing writer. Reply with ONE JSON object "
                "and nothing else — no prose, no code fences. Keys: "
                '"overnight", "levels", "calls", "macro", "top_tickers" '
                '(all five required, each a markdown string, "" when there is '
                'nothing to say), and optional "top_story" (one short sentence, '
                "only when something genuinely matters). Keep each section under "
                "900 characters. Write COMPACT PROSE, not a copy of every input "
                "line: group related tickers into a sentence and name why each "
                "matters, e.g. 'MSFT (up to 91/100) beat; focus on cloud and AI "
                "strength. AAPL, AMZN, META also reported.' Drop entries that "
                "carry no information. Never write a clock time or a timezone: no "
                "Eastern, Eastern Time, ET, EST, or EDT."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=cfg.get("llm.max_tokens", 1024),
        temperature=0.3,
        timeout=45,
    )


def _trim_to_limit(text: str, limit: int) -> str:
    """Cut `text` to `limit` chars at a line/sentence/word boundary, marking the
    cut with a trailing ellipsis. Never truncates silently mid-sentence."""
    if len(text) <= limit:
        return text
    budget = limit - 1                       # room for the "…"
    head = text[:budget]
    floor = budget // 2                      # don't throw away more than half
    nl = head.rfind("\n")
    if nl >= floor:
        return head[:nl].rstrip() + "…"
    dot = head.rfind(". ")
    if dot >= floor:
        return head[:dot + 1].rstrip() + "…"
    sp = head.rfind(" ")
    if sp >= floor:
        return head[:sp].rstrip() + "…"
    return head.rstrip() + "…"


def _clock_line() -> str:
    """The card's date/time — always computed here, never supplied by the AI."""
    return datetime.now(tz=_PT).strftime("%A, %B %-d %Y · %-I:%M %p %Z")


def _fallback_sections(data: dict) -> dict:
    """Deterministic five-section brief straight from `data`. An AI failure must
    still produce a complete, useful card — not three sections."""
    # Same caps the AI prompt uses. Without them a quiet-market day is fine but a
    # busy one hands the card 72 alerts (~8k chars), and every section but the
    # first ends up as a trimmed stub — an outage would produce a worse card than
    # it has to.
    alerts = "\n".join(
        f"• **{a['ticker']}** ({a['confidence_score']:.0f}/100) — {a['catalyst']}".rstrip(" —")
        for a in (data.get("alerts") or [])[:15]
    )
    levels = "\n".join(
        f"• **{l['ticker']}** {l['level_type']} ${l['price']} — {l.get('condition_text', '') or ''}".rstrip(" —")
        for l in (data.get("levels") or [])[:10]
    )
    calls = "\n".join(
        f"• **{s['ticker']}** {s['direction']} ({s['channel_name']}) — {(s.get('macro_thesis') or '')[:140]}".rstrip(" —")
        for s in (data.get("yt_signals") or [])[:10]
    )
    macro_row = data.get("macro")
    macro = (f"**{macro_row['direction']}** — {(macro_row.get('summary') or '')[:400]}"
             if macro_row else "")
    tops = []
    for t in (data.get("top_tickers") or [])[:5]:
        secs = t.get("sections") or {}
        analyst = (secs.get("analyst") or {}).get("content") or \
                  (secs.get("analyst") or {}).get("last_good_content") or ""
        tops.append(f"• **{t['ticker']}** — {analyst[:200]}".rstrip(" —"))
    return {
        "overnight": alerts,
        "levels": levels,
        "calls": calls,
        "macro": macro,
        "top_tickers": "\n".join(tops),
    }


def _fallback_render(data: dict) -> str:
    """Readable brief text from the deterministic sections (no AI involved)."""
    return _sections_to_text(_fallback_sections(data), "")


def _parse_sections(raw: str) -> dict | None:
    """Validate the AI's JSON reply. Returns the five sections plus an optional
    top story, or None when the reply is missing/malformed/absurdly long."""
    if not raw or not raw.strip():
        return None
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    out: dict = {}
    for key in _SECTION_KEYS:
        val = obj.get(key)
        if not isinstance(val, str) or len(val) > _MAX_SECTION_CHARS:
            return None
        out[key] = val.strip()
    story = obj.get("top_story")
    out["_top_story"] = story.strip() if isinstance(story, str) else ""
    return out


def _sections_to_text(sections: dict, top_story: str = "") -> str:
    """Render the sections to the readable brief text that is archived, stored as
    rendered_content, and parsed back when a retry rebuilds the embed."""
    lines = ["## Morning Brief", f"_{_clock_line()}_", ""]
    if top_story:
        lines += [f"> {top_story}", ""]
    for key in _SECTION_KEYS:
        body = (sections.get(key) or "").strip() or _SECTION_EMPTY[key]
        lines += [f"### {_SECTION_TITLES[key]}", body, ""]
    return "\n".join(lines).rstrip() + "\n"


# Heading -> section key, matched on the words alone. The archived briefs carry a
# dozen different spellings of these five headings ("🌙 Overnight", "**Overnight
# Highlights**", "Top Tickers (quick glance)", "Macro Pulse"), and a pending brief
# retried across a code change would otherwise reparse to an EMPTY card.
_SECTION_ALIASES = (
    ("overnight",   ("overnight",)),
    ("levels",      ("levels to watch", "levels")),
    ("calls",       ("high conviction", "highconviction", "analyst calls")),
    ("macro",       ("macro",)),
    ("top_tickers", ("top tickers",)),
)


def _section_key_for_heading(heading: str) -> str | None:
    """Which of the five sections this heading names, ignoring emoji, markdown
    emphasis, punctuation and trailing qualifiers. None when it names none."""
    text = re.sub(r"[^a-z0-9 ]+", " ", (heading or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    for key, aliases in _SECTION_ALIASES:
        for alias in aliases:
            if text.startswith(alias):
                return key
    return None


def _sections_from_text(content: str) -> tuple[dict, str, str]:
    """Inverse of _sections_to_text. Returns (sections, top_story, footnote).
    Tolerant of whitespace and case so an edited archive still parses."""
    sections: dict = {k: "" for k in _SECTION_KEYS}
    top_story, footnote = "", ""
    current = None
    preamble: list[str] = []
    buf: dict = {k: [] for k in _SECTION_KEYS}
    for line in (content or "").splitlines():
        head = re.match(r"^\s*#{2,4}\s*(.+?)\s*$", line)
        if head:
            key = _section_key_for_heading(head.group(1))
            if key:
                current = key
                continue
        if current is None:
            preamble.append(line)
        else:
            buf[current].append(line)
    for key in _SECTION_KEYS:
        sections[key] = "\n".join(buf[key]).strip()
    for line in preamble:
        stripped = line.strip()
        if stripped.startswith(">"):
            top_story = stripped.lstrip("> ").strip()
    # The out-of-range-levels warning is appended after the last section.
    tail = sections["top_tickers"]
    warn = re.search(r"^⚠️ .*$", tail, flags=re.M)
    if warn:
        footnote = warn.group(0)
        sections["top_tickers"] = tail.replace(footnote, "").strip()
    return sections, top_story, footnote


def _has_forbidden_timezone_label(content: str) -> bool:
    """Detect exchange-time labels while preserving the unrelated `$ET` ticker."""
    return bool(
        re.search(r"\bEastern(?:\s+Time)?\b", content, flags=re.IGNORECASE)
        or re.search(r"\b(?:EST|EDT)\b", content)
        or re.search(r"(?<!\$)\bET\b", content)
    )


async def _render_briefing(data: dict) -> str:
    """Try LLM synthesis; fall back to a template if LLM is unavailable."""
    # Item C (deep-dive-2026-06-08): drop out-of-range levels (NVDA 850 on a $208 stock,
    # SMH 12,616) BEFORE both the LLM prompt and the fallback read data["levels"]. Filter in
    # place once per ticker so both paths see only sane levels; record a count for the footnote.
    from consensus_engine.analysis.level_display_sanity import filter_levels_for_display
    _kept, _hidden = [], 0
    _by_ticker: dict[str, list] = {}
    for l in data["levels"]:
        _by_ticker.setdefault(l["ticker"], []).append(l)
    for tk, lvls in _by_ticker.items():
        keep, drop = await filter_levels_for_display(tk, lvls)
        _kept.extend(keep)
        _hidden += drop
    data["levels"] = _kept
    data["_levels_hidden"] = _hidden

    # Drop the trailing dash when there is no catalyst: feeding the model bare
    # "- SNDK (82/100) — " lines got it echoed straight onto the card.
    alert_lines = [
        f"- {a['ticker']} ({a['confidence_score']:.0f}/100) — {a['catalyst']}".rstrip(" —")
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
        "Build a morning briefing from the data below. Reply with the JSON object "
        "described in the system message — the five section keys, markdown inside "
        "each. No clock times, no timezone labels.\n\n"
        f"## Overnight alerts\n" + ("\n".join(alert_lines) or "_none_") + "\n\n"
        f"## Levels\n" + ("\n".join(level_lines) or "_none_") + "\n\n"
        f"## YT Signals\n" + ("\n".join(yt_lines) or "_none_") + "\n\n"
        f"## {macro_block}\n\n"
        f"## Top Tickers\n" + ("\n".join(top_lines) or "_none_")
    )
    try:
        raw = await _llm_synthesize(prompt)
    except Exception as exc:
        log.warning("Alfred LLM synthesis failed (%s); using deterministic fallback", exc)
        raw = ""

    sections = _parse_sections(raw)
    if sections is None:
        if raw:
            log.warning("Alfred rejected AI reply that failed the JSON section contract")
        sections, top_story = _fallback_sections(data), ""
    elif _has_forbidden_timezone_label(raw):
        # Relabeling an invented "9:30 ET" as Pacific would make the clock time
        # wrong. Reject the AI text instead and use the deterministic Pacific
        # fallback, which is safer than showing a mislabeled time.
        log.warning("Alfred rejected AI text containing a forbidden timezone label")
        sections, top_story = _fallback_sections(data), ""
    else:
        top_story = sections.pop("_top_story", "")

    out = _sections_to_text(sections, top_story)
    # Item C: user-visible footnote so a wrongly-hidden real level is detectable (not buried).
    hidden = data.get("_levels_hidden", 0)
    if hidden:
        out = f"{out}\n⚠️ {hidden} level{'s' if hidden != 1 else ''} hidden as out-of-range.\n"
    return out


# ---------------------------------------------------------------------------
# SPY expected move + the card
# ---------------------------------------------------------------------------
async def _spy_expected_move(horizon: str) -> tuple[object | None, bytes | None]:
    """Reuse the !em engine for SPY. Never raises — a failure just means no
    numbers and no chart for that horizon."""
    from consensus_engine.scanners.expected_move import compute_em, render_chart
    try:
        result = await compute_em("SPY", horizon=horizon)
    except Exception as exc:
        log.warning("Alfred SPY %s expected move unavailable: %s", horizon, exc)
        return None, None
    try:
        png = render_chart(result)
    except Exception as exc:
        log.warning("Alfred SPY %s chart render failed: %s", horizon, exc)
        png = None
    if png is None:
        log.info("Alfred SPY %s chart not rendered; posting numbers only", horizon)
    return result, png


def _em_summary_line(result) -> str:
    pct = result.em.get("raw_straddle_em_pct")
    pct_txt = f" ({pct * 100:.2f}%)" if isinstance(pct, (int, float)) else ""
    word = "Weekly" if result.horizon == "weekly" else "Daily"
    return (f"**SPY {word} expected move ±${result.primary_em:,.2f}{pct_txt}**\n"
            f"🔴 {result.upper:,.2f} · 🔵 {result.spot:,.2f} now · 🟢 {result.lower:,.2f}"
            f" · expires `{result.expiration}`")


def _em_meta(result, rendered: bool) -> dict:
    return {
        "spot": round(result.spot, 4),
        "expected_move": round(result.primary_em, 4),
        "expected_move_pct": result.em.get("raw_straddle_em_pct"),
        "upper": round(result.upper, 4),
        "lower": round(result.lower, 4),
        "expiration": result.expiration,
        "chart": rendered,
    }


def _build_briefing_embed(sections: dict, top_story: str, footnote: str) -> dict:
    """The main card: fixed five fields, every value inside Discord's limits."""
    description = f"_{_clock_line()}_"
    if top_story:
        description += f"\n\n**{top_story}**"
    embed = {
        "title": "☀️  Morning Brief",
        "description": _trim_to_limit(description, _MAX_DESCRIPTION),
        "color": _BRIEF_COLOR,
        "fields": [
            {"name": _SECTION_TITLES[k],
             "value": _trim_to_limit((sections.get(k) or "").strip() or _SECTION_EMPTY[k],
                                     _MAX_FIELD_VALUE),
             "inline": False}
            for k in _SECTION_KEYS
        ],
    }
    if footnote:
        embed["footer"] = {"text": _trim_to_limit(footnote, 2048)}
    return _fit_embed(embed)


def _fit_embed(embed: dict) -> dict:
    """Keep the whole embed under Discord's 6000-char total by trimming the
    longest field first — visibly, never silently."""
    def total(e: dict) -> int:
        return (len(e.get("title", "")) + len(e.get("description", ""))
                + len((e.get("footer") or {}).get("text", ""))
                + sum(len(f["name"]) + len(f["value"]) for f in e.get("fields", [])))

    while total(embed) > _MAX_EMBED_TOTAL:
        over = total(embed) - _MAX_EMBED_TOTAL
        biggest = max(embed["fields"], key=lambda f: len(f["value"]))
        target = max(60, len(biggest["value"]) - over)
        if target >= len(biggest["value"]):
            break
        biggest["value"] = _trim_to_limit(biggest["value"], target)
    return embed


async def _build_briefing_payload(content: str) -> tuple[list[dict], list[tuple[str, bytes]], str]:
    """Turn the archived brief text into (embeds, attachments, em_metadata JSON).
    The daily SPY chart is expected; the weekly one is strictly best-effort and
    can never delay or block the post."""
    sections, top_story, footnote = _sections_from_text(content)
    meta: dict = {}

    daily, daily_png = await _spy_expected_move("daily")
    if daily is not None:
        meta["daily"] = _em_meta(daily, daily_png is not None)
        sections["levels"] = (_em_summary_line(daily) + "\n" + (sections["levels"] or "")).strip()
    else:
        meta["daily"] = {"error": "unavailable"}

    weekly, weekly_png = await _spy_expected_move("weekly")
    if weekly is not None:
        meta["weekly"] = _em_meta(weekly, weekly_png is not None)
    else:
        meta["weekly"] = {"error": "unavailable"}

    main = _build_briefing_embed(sections, top_story, footnote)
    embeds = [main]
    attachments: list[tuple[str, bytes]] = []

    if daily_png and len(daily_png) <= _MAX_ATTACHMENT_BYTES:
        main["image"] = {"url": f"attachment://{SPY_EM_DAILY_FILE}"}
        attachments.append((SPY_EM_DAILY_FILE, daily_png))
    # A Discord embed holds one image, so the weekly chart rides in a second
    # embed inside the SAME message.
    if weekly_png and len(weekly_png) <= _MAX_ATTACHMENT_BYTES:
        embeds.append({
            "title": "SPY — Weekly Expected Move",
            "description": _trim_to_limit(_em_summary_line(weekly), _MAX_DESCRIPTION),
            "color": _BRIEF_COLOR,
            "image": {"url": f"attachment://{SPY_EM_WEEKLY_FILE}"},
        })
        attachments.append((SPY_EM_WEEKLY_FILE, weekly_png))
    elif weekly_png:
        log.info("Alfred skipped the weekly SPY chart: %d bytes is too large", len(weekly_png))

    return embeds, attachments, json.dumps(meta, separators=(",", ":"))


async def send_briefing_message(embeds: list[dict],
                                attachments: list[tuple[str, bytes]] | None = None) -> str | None:
    """POST one non-reply message with the brief embed(s) and up to two PNGs.
    Returns the Discord message id, or None so the run stays retryable."""
    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("alfred.channel_id", "") or
                     cfg.get("api_keys.discord_briefing_channel_id", "") or "")
    if not token or not channel_id:
        log.warning("Alfred Discord: missing bot token or briefing channel id")
        return None
    if getattr(cfg, "dry_run", False):
        log.info("[DRY-RUN] Alfred would post to %s: %s (%d embeds, %d files)",
                 channel_id, (embeds[0].get("title") if embeds else ""),
                 len(embeds), len(attachments or []))
        return "dry-run"

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    files = list(attachments or [])
    payload = _safe_send_kwargs({"embeds": embeds})
    if files:
        payload["attachments"] = [{"id": i, "filename": name}
                                  for i, (name, _) in enumerate(files)]

    session = await get_session()
    try:
        if files:
            form = aiohttp.FormData()
            form.add_field("payload_json", json.dumps(payload),
                           content_type="application/json")
            for i, (name, blob) in enumerate(files):
                form.add_field(f"files[{i}]", blob, filename=name,
                               content_type="image/png")
            async with session.post(
                url, headers={"Authorization": f"Bot {token}"}, data=form,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status in (200, 201):
                    return str((await resp.json()).get("id", ""))
                log.warning("Alfred multipart post failed: %d; retrying without images",
                            resp.status)
        else:
            return await _post_briefing_json(url, token, {"embeds": embeds})
    except Exception as exc:
        log.error("Alfred Discord send error: %s", exc)
        if not files:
            return None

    # Multipart failed — post the embeds without images so the numbers still land.
    plain = [{k: v for k, v in e.items() if k != "image"} for e in embeds]
    plain = [e for e in plain if e.get("fields") or e.get("description")]
    try:
        return await _post_briefing_json(url, token, {"embeds": plain})
    except Exception as exc:
        log.error("Alfred Discord fallback send error: %s", exc)
        return None


async def _post_briefing_json(url: str, token: str, body: dict) -> str | None:
    session = await get_session()
    async with session.post(
        url,
        headers={"Authorization": f"Bot {token}",
                 "Content-Type": "application/json"},
        json=_safe_send_kwargs(body),
        timeout=aiohttp.ClientTimeout(total=20),
    ) as resp:
        if resp.status not in (200, 201):
            log.warning("Alfred Discord post failed: %d", resp.status)
            return None
        return str((await resp.json()).get("id", ""))


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


async def post_briefing(session_key: str, data: dict) -> None:
    """Drive the pending → posted → archived state machine.
    Idempotent: safe to call repeatedly; no double-posts on restart.
    """
    vault_path = cfg.get("vault.path", "/root/.openclaw/vault")

    run = await db.get_briefing_run(session_key)
    if run and run["status"] == "archived":
        log.info("Alfred %s already archived; skipping", session_key)
        return

    # Stage 1: render + persist as pending
    if not run:
        content = await _render_briefing(data)
        await db.upsert_briefing_run(
            session_key,
            session_start_utc=data["session_start_utc"],
            session_end_utc=data["session_end_utc"],
            rendered_content=content,
            status="pending",
        )
        run = await db.get_briefing_run(session_key)
    elif run["status"] == "pending" and not run.get("rendered_content"):
        content = await _render_briefing(data)
        await db.upsert_briefing_run(session_key, rendered_content=content, status="pending")
        run = await db.get_briefing_run(session_key)

    # Stage 2: post to Discord (only if pending)
    if run["status"] == "pending":
        embeds, attachments, em_metadata = await _build_briefing_payload(
            run["rendered_content"] or "")
        msg_id = await send_briefing_message(embeds, attachments)
        if not msg_id:
            log.warning("Alfred %s Discord post failed; leaving pending for retry", session_key)
            return
        await db.upsert_briefing_run(session_key, discord_message_id=msg_id,
                                     status="posted", em_metadata=em_metadata)
        run = await db.get_briefing_run(session_key)

    # Stage 3: archive to vault
    if run["status"] == "posted":
        await _write_vault_briefing(session_key, run["rendered_content"] or "", vault_path)
        await db.upsert_briefing_run(session_key, status="archived")


def _in_post_window(now_et: datetime, window: list) -> bool:
    if not window or len(window) != 2:
        return False
    try:
        start_hh, start_mm = [int(x) for x in str(window[0]).split(":")]
        end_hh, end_mm = [int(x) for x in str(window[1]).split(":")]
    except Exception:
        return False
    cur = (now_et.hour, now_et.minute)
    return (start_hh, start_mm) <= cur <= (end_hh, end_mm)


async def alfred_loop(stop_event) -> None:
    from consensus_engine.research.sessions import current_et_session, is_market_holiday

    if not cfg.get("alfred.enabled", False):
        log.info("Alfred disabled; loop exiting")
        return

    while not stop_event.is_set():
        now_et = datetime.now(tz=_ET)   # internal: the trading day is the exchange's
        now_pt = datetime.now(tz=_PT)   # the post window is configured in the user's time (PDT)
        window = list(cfg.get("alfred.post_window_pdt", ["05:50", "06:00"]) or [])
        is_trading = now_et.weekday() < 5 and not is_market_holiday(now_et)

        if is_trading and _in_post_window(now_pt, window):
            start, end, session_key = current_et_session(now_et)
            run = await db.get_briefing_run(session_key)
            if not run or run["status"] != "archived":
                try:
                    data = await build_briefing_data(start, end)
                    await post_briefing(session_key, data)
                except Exception as exc:
                    log.error("Alfred loop error for %s: %s", session_key, exc)

        try:
            await _asyncio.wait_for(stop_event.wait(), timeout=60)
        except _asyncio.TimeoutError:
            pass
