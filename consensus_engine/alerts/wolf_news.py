"""#news alert layer for the Wolf macro-brain (TODO #20, phase 1).

Posts proactive alerts on a new or stage-changed Wolf thesis, through a durable
outbox so a crash can never double-post or lose an alert:

    create pending row (dedupe_key = "<thesis_id>|<stage>")  -> post -> mark posted

Tiers (phase 1, Wolf-only — no confluence yet):
    surface  = forming / diverging / imminent  -> plain #news post, no @-ping
    high     = acting (Wolf revealed a position) -> louder #news post, no @-ping
    critical = Wolf + >=2 corroborating sources  -> @-ping  (PHASE 2 only)

The @-ping path (allowed_mentions override + <=3/hr rate limit) is built and
unit-tested but stays dormant in phase 1: critical tier is never reached without
the phase-2 confluence engine, and `wolf.enable_critical_ping` defaults off.
"""
from __future__ import annotations

import json
import logging
import time

from consensus_engine import config as cfg, db
from consensus_engine.analysis.wolf_confluence import combined_tier, _SOURCE_LABEL

log = logging.getLogger(__name__)

# Critical @-ping rate limit (independent of the email ingestion cap).
_CRITICAL_PING_WINDOW = 3600
_CRITICAL_PING_MAX = 3
_critical_ping_log: list[float] = []

_DIR_EMOJI = {"bull": "🟢", "bear": "🔴"}
_STAGE_LABEL = {
    "forming": "forming",
    "diverging": "divergences building",
    "imminent": "imminent",
    "acting": "Wolf has taken a position",
}


def tier_for(event: dict) -> str:
    """Phase-1 tier. HIGH on the action: stage=='acting' OR position started/adding.
    Everything else (build steps) is surface. (critical/@-ping is phase-2.)"""
    if event.get("stage") == "acting" or event.get("intent") in ("started", "adding"):
        return "high"
    return "surface"


def effective_tier(event: dict, confl_row: dict | None) -> str:
    """Combined tier = max(phase-1 tier, confluence tier). Confluence can only push UP.
    The confluence tier already enforces its gates (has_levels + >=1/>=2 corroborators)."""
    confl_tier = (confl_row or {}).get("tier") or event.get("confluence_tier", "surface")
    return combined_tier(tier_for(event), confl_tier)


def _confluence_field(confl_row: dict | None) -> dict | None:
    """Build the '🤝 Confluence' embed field from a stored wolf_confluence_checks row.
    None when there's nothing to say (no agreeing or disagreeing source)."""
    if not confl_row:
        return None
    agree_n = int(confl_row.get("agree_count", 0) or 0)
    disagree_n = int(confl_row.get("disagree_count", 0) or 0)
    if agree_n == 0 and disagree_n == 0:
        return None
    try:
        agree = json.loads(confl_row.get("agree_sources_json") or "[]")
        disagree = json.loads(confl_row.get("disagree_sources_json") or "[]")
    except Exception:
        agree, disagree = [], []

    def _label(s: dict) -> str:
        lbl = _SOURCE_LABEL.get(s.get("source_type", ""), s.get("source_type", "?"))
        extra = ""
        if s.get("source_type") == "youtube" and s.get("n_channels"):
            extra += f" ({s['n_channels']} ch)"
        tickers = s.get("sample_tickers") or []
        if tickers:
            extra += f": {', '.join(tickers[:3])}"
        return lbl + extra

    direction = (confl_row.get("direction") or "").upper()
    if confl_row.get("divided"):
        opp = ", ".join(_label(s) for s in disagree) or "others"
        value = f"⚖️ **Analysts divided** — Wolf {direction} vs {opp}"
    else:
        s_word = "source" if agree_n == 1 else "sources"
        lines = [f"**{agree_n} {s_word} agree** — " + ("; ".join(_label(s) for s in agree) or "—")]
        if disagree_n:
            lines.append(f"{disagree_n} disagree — " + "; ".join(_label(s) for s in disagree))
        value = "\n".join(lines)
    return {"name": "🤝 Confluence", "value": value[:1024], "inline": False}


def _can_ping(now: float) -> bool:
    """True if a critical @-ping is allowed under the <=3/hr rate limit."""
    cutoff = now - _CRITICAL_PING_WINDOW
    _critical_ping_log[:] = [t for t in _critical_ping_log if t > cutoff]
    if len(_critical_ping_log) >= _CRITICAL_PING_MAX:
        return False
    _critical_ping_log.append(now)
    return True


def format_message(event: dict, levels: list[dict]) -> str:
    """Build the #news message text from VALIDATED fields only (never raw email text)."""
    direction = event["direction"]
    emoji = _DIR_EMOJI.get(direction, "⚪")
    scope_key = event["scope_key"]
    scope_type = event["scope_type"]
    stage_lbl = _STAGE_LABEL.get(event["stage"], event["stage"])
    head = "🆕 New thesis" if event["kind"] == "new" else "🔄 Stage change"
    arrow = ""
    if event["kind"] == "stage_change" and event.get("old_stage"):
        arrow = f" ({event['old_stage']} → {event['stage']})"
    lines = [
        f"{emoji} **{scope_key}** ({scope_type}) — Wolf turns **{direction.upper()}**",
        f"{head}: {stage_lbl}{arrow}",
    ]
    if levels:
        lvl_txt = ", ".join(
            f"{l['price']:g}" + (f" ({l['role']})" if l.get("role") else "")
            for l in levels[:5]
        )
        lines.append(f"Key levels: {lvl_txt}")
    snippet = event.get("snippet", "")
    if snippet:
        lines.append(f"_{snippet}_")
    return "\n".join(lines)


_INTENT_LABEL = {
    "none": None, "watching": "watching it", "looking": "looking for an entry",
    "started": "started a position", "adding": "adding to the position",
}
_TRAJ_LABEL = {
    "building": "building", "stable": "holding", "cooling": "cooling", "turned": "turned",
}
_TF_LADDER = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "daily", "3d", "weekly"]
_TF_RANK = {t: i for i, t in enumerate(_TF_LADDER)}

# Embed colour by direction (bear red / bull green); grey if unknown.
_DIR_COLOR = {"bear": 0xE03131, "bull": 0x2F9E44}
# Plain-English instrument names so the title reads cleanly ("$SMH · Semis").
_SCOPE_DISPLAY = {
    "SMH": "Semis", "SOX": "Semis", "NDX": "Nasdaq", "SPX": "S&P 500", "RUT": "Russell 2000",
    "DJIA": "Dow", "VIX": "Volatility", "OIL": "Oil", "GOLD": "Gold", "BONDS": "Bonds",
    "YIELDS": "Yields", "DXY": "US Dollar", "BTC": "Bitcoin", "IGV": "Software",
    "XLE": "Energy", "XLF": "Financials", "XLK": "Tech", "XLV": "Healthcare",
}


def _fmt_date(ts) -> str:
    """Mon DD from a unix ts (UTC), e.g. 'May 22'. Falls back to '' on bad input."""
    try:
        return time.strftime("%b %d", time.gmtime(float(ts)))
    except Exception:
        return ""


def _tf_range_label(tf: list[str]) -> str:
    """Compact range from a normalized ladder set, e.g. ['1m','3m','5m','15m'] -> '1M–15M'."""
    rungs = sorted({t for t in (tf or []) if t in _TF_RANK}, key=lambda t: _TF_RANK[t])
    if not rungs:
        return ""
    if len(rungs) == 1:
        return rungs[0].upper()
    return f"{rungs[0].upper()}–{rungs[-1].upper()}"


def _entry_change_label(entry: dict, prev: dict | None) -> str:
    """What-changed line from OUR enum labels only (never Wolf's raw words)."""
    frm = entry.get("from")
    to = entry.get("to")
    if frm is None:
        return "thesis forms" if to == "forming" else f"thesis opens at {to}"
    parts = []
    position_emitted = False
    if frm != to:
        if to == "acting" and entry.get("intent") in ("started", "adding"):
            parts.append("starts the position")
            position_emitted = True
        elif to == "acting":
            parts.append("moves to acting")
        else:
            parts.append(f"{frm} → {to}")
    # timeframe widening vs the prior entry
    prev_tf = set((prev or {}).get("tf", []) or [])
    this_tf = set(entry.get("tf", []) or [])
    if this_tf - prev_tf and len(this_tf) > len(prev_tf):
        rng = _tf_range_label(sorted(this_tf, key=lambda t: _TF_RANK.get(t, 99)))
        if rng:
            parts.append(f"timeframes widen to {rng}")
    # intent step
    prev_intent = (prev or {}).get("intent", "none")
    this_intent = entry.get("intent", "none")
    intent_lbl = _INTENT_LABEL.get(this_intent)
    if (this_intent != prev_intent and intent_lbl
            and not (position_emitted and this_intent in ("started", "adding"))):
        parts.append(intent_lbl)
    if not parts:
        parts.append("reaffirmed")
    return ", ".join(parts)


def _build_story_so_far(evlog: list[dict]) -> list[str]:
    """Dated • <Mon DD> · <what-changed> lines from OUR enum labels (last ~5)."""
    lines = []
    prev = None
    for entry in evlog:
        date = _fmt_date(entry.get("ts"))
        change = _entry_change_label(entry, prev)
        lines.append(f"• {date} · {change}")
        prev = entry
    return lines[-5:]


async def build_backdrop(thesis_row: dict) -> str | None:
    """R1: ONE labeled backdrop line from the most recent ACTIVE market-scope
    bear/diverging thread — read-only, never merged into this thread's log. Omitted
    if no such regime is active (never show a stale regime). Never for a market thread."""
    if thesis_row.get("scope_type") == "market":
        return None
    try:
        market_threads = await db.get_active_theses("market")
    except Exception:
        return None
    for mt in market_threads:
        if mt.get("direction") == "bear" and mt.get("stage") in ("diverging", "imminent", "acting"):
            stage_lbl = _STAGE_LABEL.get(mt["stage"], mt["stage"])
            return f"{mt['scope_key']} bear ({stage_lbl})"
    return None


def format_conviction_update(event: dict, thesis_row: dict, backdrop: str | None = None,
                             confluence: dict | None = None) -> dict:
    """Clean Discord EMBED for a Wolf alert — validated fields only (R4/§6).

    A title + a few short labelled fields + a footer (no text wall). Built from our own
    enum labels + capped snippet/phrase + validated levels; the raw email body never
    appears, and the send path sets allowed_mentions {'parse': []} so any @ is inert.
    """
    direction = event["direction"]
    emoji = _DIR_EMOJI.get(direction, "⚪")
    scope_key = event["scope_key"]
    name = _SCOPE_DISPLAY.get(scope_key, "")
    dir_word = "BEARISH" if direction == "bear" else ("BULLISH" if direction == "bull" else direction.upper())
    tier = tier_for(event)

    title = f"{emoji} ${scope_key}" + (f" · {name}" if name else "") + f" — Wolf {dir_word}"

    fields: list[dict] = []

    # 1) Wolf's move — the headline action + conviction, in one tidy field.
    if tier == "high":
        move = "🚨 **Started a position**" + (" — room to add" if event.get("intent") == "adding" else "")
    elif event.get("kind") == "new":
        move = f"New — {_STAGE_LABEL.get(event['stage'], event['stage'])}"
    else:
        move = _STAGE_LABEL.get(event["stage"], event["stage"])
    conv = event.get("conv")
    if conv is not None:
        traj = _TRAJ_LABEL.get(event.get("traj", ""), "")
        move += f"\nConviction **{conv}/100**" + (f" · {traj}" if traj else "")
    fields.append({"name": "Wolf's move", "value": move[:1024], "inline": False})

    # 2) Story so far — the dated arc, ONLY when there's a real multi-day build.
    try:
        evlog = json.loads(thesis_row.get("evidence_log_json") or "[]")
    except Exception:
        evlog = []
    story = _build_story_so_far(evlog)
    if len(story) > 1:
        fields.append({"name": "Story so far", "value": "\n".join(story)[:1024], "inline": False})

    # 3) Timeframes + 4) Key levels — short, side by side.
    tf_range = _tf_range_label(event.get("tf", []))
    if tf_range:
        fields.append({"name": "Timeframes", "value": tf_range, "inline": True})
    try:
        levels = json.loads(thesis_row.get("key_levels_json") or "[]")
    except Exception:
        levels = []
    lvl_txt = ", ".join(
        f"{l['price']:g}" + (f" ({l['role']})" if l.get("role") else "")
        for l in levels[:5] if "price" in l
    )
    if lvl_txt:
        fields.append({"name": "Key levels", "value": lvl_txt[:1024], "inline": True})

    # 5) Wolf's words — ONE quote (prefer the conviction phrase).
    quote = event.get("phrase") or event.get("snippet") or ""
    if quote:
        fields.append({"name": "Wolf's words", "value": f"“{quote[:300]}”", "inline": False})

    # 6) Confluence (phase-2) — how many other sources agree/disagree, if known.
    confl_field = _confluence_field(confluence)
    if confl_field:
        fields.append(confl_field)

    footer = "Wolf macro-brain"
    if backdrop:
        footer += f"  ·  Backdrop: {backdrop}"

    return {
        "title": title[:256],
        "color": _DIR_COLOR.get(direction, 0x9AA0A6),
        "fields": fields,
        "footer": {"text": footer[:2048]},
    }


def confluence_event(thesis_row: dict, result, combined: str) -> dict:
    """Build a standalone #news event for a confluence tier-up (kind='confluence').

    `result` is a wolf_confluence.ConfluenceResult; `combined` the max(phase1,confluence) tier.
    """
    return {
        "kind": "confluence",
        "thesis_id": thesis_row["id"],
        "scope_type": thesis_row["scope_type"],
        "scope_key": thesis_row["scope_key"],
        "direction": thesis_row["direction"],
        "stage": thesis_row.get("stage", ""),
        "confluence_tier": result.tier,
        "snippet": f"{result.agree_count} other source(s) now corroborate Wolf.",
    }


def format_confluence_alert(thesis_row: dict, confl_row: dict | None, event: dict) -> dict:
    """Clean #news EMBED for a standalone confluence escalation — its headline IS the
    cross-source agreement, plus Wolf's standing call + levels. Validated fields only."""
    direction = event["direction"]
    emoji = _DIR_EMOJI.get(direction, "⚪")
    scope_key = event["scope_key"]
    name = _SCOPE_DISPLAY.get(scope_key, "")
    dir_word = "BEARISH" if direction == "bear" else ("BULLISH" if direction == "bull" else direction.upper())
    tier = (confl_row or {}).get("combined_tier") or event.get("confluence_tier", "high")
    crown = "🚨 " if tier == "critical" else ""

    title = f"{crown}{emoji} ${scope_key}" + (f" · {name}" if name else "") + " — sources back Wolf"
    fields: list[dict] = [
        {"name": "Wolf's call",
         "value": f"Wolf is {dir_word} — {_STAGE_LABEL.get(event.get('stage'), event.get('stage', ''))}",
         "inline": False},
    ]
    confl_field = _confluence_field(confl_row)
    if confl_field:
        fields.append(confl_field)
    try:
        levels = json.loads(thesis_row.get("key_levels_json") or "[]")
    except Exception:
        levels = []
    lvl_txt = ", ".join(
        f"{l['price']:g}" + (f" ({l['role']})" if l.get("role") else "")
        for l in levels[:5] if "price" in l
    )
    if lvl_txt:
        fields.append({"name": "Key levels", "value": lvl_txt[:1024], "inline": True})

    return {
        "title": title[:256],
        "color": _DIR_COLOR.get(direction, 0x9AA0A6),
        "fields": fields,
        "footer": {"text": f"Wolf macro-brain · confluence {tier}"[:2048]},
    }


# ----------------------------------------------------------------- Phase-3 digests
_DIGEST_TITLE = {
    "midday": "☀️ Wolf Midday Brief",
    "nightly": "🌙 Wolf Nightly Wrap",
    "sunday": "🗓️ Wolf Weekly Recap",
    "sunday-addon": "🗓️ Wolf Weekly Recap — update",
}
_DIGEST_COLOR = 0x5C7CFA


def _digest_thesis_line(t: dict) -> str:
    emoji = _DIR_EMOJI.get(t.get("direction"), "⚪")
    sk = t.get("scope_key", "")
    name = _SCOPE_DISPLAY.get(sk, "")
    label = _STAGE_LABEL.get(t.get("stage"), t.get("stage", ""))
    return f"{emoji} {sk}" + (f" ({name})" if name else "") + (f" · {label}" if label else "")


def _scoreboard_line(s: dict) -> str:
    emoji = _DIR_EMOJI.get(s.get("direction"), "⚪")
    crown = "🚨 " if s.get("combined_tier") == "critical" else ""
    return (f"{crown}{emoji} {s.get('scope_key', '')}: {s.get('agree', 0)} agree / "
            f"{s.get('disagree', 0)} disagree ({s.get('combined_tier', '')})")


def _outcome_line(o: dict) -> str:
    """Humble wording only — NEVER 'played out' / 'nailed it' / 'win' (Codex BLOCKER-2)."""
    sk = o.get("scope_key", "")
    sym = o.get("proxy_symbol") or sk
    pct = o.get("pct_move")
    st = o.get("state")
    if st == "moved_with":
        return f"🟢 {sk}: since Wolf flagged it actionable, {sym} moved +{abs(pct):.1f}% in his direction"
    if st == "moved_against":
        return f"🔴 {sk}: {sym} moved {abs(pct):.1f}% against his call"
    if st == "flat":
        return f"⚪ {sk}: roughly flat since he flagged it ({sym} {pct:+.1f}%)"
    if st == "invalidated":
        return f"✖️ {sk}: Wolf has since dropped this call"
    return f"… {sk}: not enough data to judge yet"


def _beneficiary_block(g: dict) -> str:
    """Render one thesis's inferred beneficiary picks (phase-4 #2). Header names the Wolf
    thesis; each pick is the bot's RS-leadership inference with an honest tier dot."""
    head = f"**{g.get('scope_key', '')} {g.get('direction', '')}** → bot's leaders:"
    lines = [head]
    for p in g.get("picks", []):
        dot = "🟢" if p.get("tier") == "green" else "🟡"
        lines.append(f"{dot} {p.get('ticker', '')} {str(p.get('side', 'long')).upper()} — {p.get('reason', '')}")
    return "\n".join(lines)


def format_digest(variant: str, payload: dict) -> dict:
    """Build the #news digest embed from a gathered payload (see wolf_digest.gather_digest).
    Empty buckets are dropped (so a thin/absent beneficiaries list omits the section)."""
    title = _DIGEST_TITLE.get(variant, "Wolf Brief")
    fields: list[dict] = []
    max_field = int(cfg.get("wolf.digests.max_theses_per_field", 8))

    def _bucket(name, items, render):
        if items:
            shown = items[:max_field]
            val = "\n".join(render(i) for i in shown)
            if len(items) > max_field:
                val += "\n…and %d more" % (len(items) - max_field)
            fields.append({"name": name, "value": val[:1024], "inline": False})

    _bucket("🎯 Acting now", payload.get("acting"), _digest_thesis_line)
    _bucket("⏳ Imminent", payload.get("imminent"), _digest_thesis_line)
    _bucket("👀 Watchlist", payload.get("watchlist"), _digest_thesis_line)
    _bucket("🤝 Sources agree", payload.get("scoreboard"), _scoreboard_line)
    _bucket("🤖 Bot's read — inferred, not Wolf's picks", payload.get("beneficiaries"), _beneficiary_block)
    if variant in ("sunday", "sunday-addon"):
        outs = payload.get("outcomes") or []
        scored = [o for o in outs if o.get("state") != "inconclusive"] or outs
        _bucket("📊 How his calls have moved", scored, _outcome_line)

    desc_lines = [x for x in (payload.get("lean"), payload.get("regime_clause")) if x]
    embed = {
        "title": title[:256],
        "color": _DIGEST_COLOR,
        "fields": fields,
        "footer": {"text": f"Wolf macro-brain · {variant} · {payload.get('generated_at_pt', '')}"[:2048]},
    }
    if desc_lines:
        embed["description"] = "\n".join(desc_lines)[:4096]
    return embed


async def _post_digest_event(event: dict, now: float) -> bool:
    """Post a scheduled digest through the durable outbox (reuses dedupe + dry_run).
    A digest carries its own dedupe_key (digest|<variant>|<PT-date>) and is not tied
    to a thesis row, so it skips the thesis-centric path in post_event."""
    dedupe_key = event["dedupe_key"]
    payload = event.get("payload", {})
    stored = {"event": {"kind": "digest", "variant": event.get("variant"), "dedupe_key": dedupe_key},
              "digest": payload}
    alert_id = await db.create_pending_alert(dedupe_key, None, "surface", json.dumps(stored), now)
    if alert_id is None:
        # Row exists. Only skip if it actually POSTED — otherwise a prior send FAILED and
        # we retry it now (a transient Discord blip must not silently drop the digest
        # forever). 'posted' rows are never re-sent, so no double-post.
        existing = await db.get_wolf_alert(dedupe_key)
        if existing and existing.get("status") == "posted":
            log.debug("wolf_news: digest already posted for %s, skipping", dedupe_key)
            return False
        alert_id = existing["id"] if existing else None
        if alert_id is None:
            return False
        log.info("wolf_news: retrying previously-failed digest %s", dedupe_key)
    embed = format_digest(event.get("variant", ""), payload)
    dry_run = cfg.get("wolf.dry_run", True)
    if dry_run:
        log.info("wolf_news[DRY-RUN] would post digest %s:\n%s",
                 dedupe_key, json.dumps(embed, ensure_ascii=False))
        await db.mark_alert_posted(alert_id, None, now)
        return True
    msg_id = await _send_news(embed=embed)
    if msg_id:
        await db.mark_alert_posted(alert_id, msg_id, now)
        return True
    await db.mark_alert_failed(alert_id)
    return False


async def _send_news(content: str | None = None, embed: dict | None = None,
                     ping_user_id: str | None = None) -> str | None:
    """POST to #news (an embed and/or text). If ping_user_id is set, prefix an @-mention
    and allow only that user. Returns the Discord message id on success, None otherwise.
    """
    import aiohttp

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_news_channel_id", "") or "")
    if not token or not channel_id:
        log.warning("wolf_news: missing discord token or news channel_id; skipping post")
        return None

    payload: dict = {}
    if embed is not None:
        payload["embeds"] = [embed]
    msg = content or ""
    if ping_user_id:
        msg = (f"<@{ping_user_id}> " + msg).strip()
        payload["allowed_mentions"] = {"users": [str(ping_user_id)]}
    else:
        payload["allowed_mentions"] = {"parse": []}
    if msg:
        payload["content"] = msg[:1990]

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    return data.get("id")
                body = await resp.text()
                log.error("wolf_news: discord post failed %s: %s", resp.status, body[:200])
                return None
    except Exception as exc:
        log.error("wolf_news: discord post error: %s", exc)
        return None


async def post_event(event: dict) -> bool:
    """Post one thesis event to #news via the durable outbox. Returns True if posted.

    Dry-run (config wolf.dry_run, default True) records the outbox row + logs the
    rendered message but does NOT hit Discord — used for the pre-sign-off gate.
    """
    now = time.time()
    if event.get("kind") == "digest":
        return await _post_digest_event(event, now)
    thesis_id = event["thesis_id"]
    # Phase-2: combined tier (max of phase-1 stage tier and the stored confluence tier).
    confl_row = await db.get_confluence_check(thesis_id) if thesis_id is not None else None
    tier = effective_tier(event, confl_row)

    # Dedupe bucket (§4): a conviction_update rides a (stage,intent,tf_width) bucket so
    # an identical snapshot can't double-post, but a genuine escalation (new bucket)
    # gets through. A 'new' event still dedupes on stage.
    if event["kind"] == "conviction_update":
        rungs = [t for t in (event.get("tf") or []) if t in _TF_RANK]
        tf_width = len(set(rungs))
        # include the highest rung so a same-width set that gains a LONGER timeframe
        # (e.g. {5m,15m} -> {5m,daily}) is a distinct bucket and still posts.
        max_rung = max(rungs, key=lambda t: _TF_RANK[t]) if rungs else "none"
        bucket = f"{event['stage']}:{event.get('intent', 'none')}:{tf_width}:{max_rung}"
        dedupe_key = f"{thesis_id}|conv|{bucket}"
    elif event["kind"] == "confluence":
        # one standalone confluence alert per tier escalation (loop hysteresis is the
        # primary guard; this outbox key is the durable belt-and-suspenders).
        dedupe_key = f"{thesis_id}|confl|{tier}"
    else:
        dedupe_key = f"{thesis_id}|{event['stage']}"

    # fetch the thesis row for rendering (levels + evidence_log + backdrop)
    thesis = await db.get_active_thesis(event["scope_type"], event["scope_key"], event["direction"])
    levels = []
    if thesis:
        try:
            levels = json.loads(thesis["key_levels_json"]) or []
        except Exception:
            levels = []

    payload = {"event": event, "tier": tier}
    alert_id = await db.create_pending_alert(dedupe_key, thesis_id, tier, json.dumps(payload), now)
    if alert_id is None:
        # Row exists. Mirror the digest retry (_post_digest_event, phase-4 #3): only skip
        # if it actually POSTED — otherwise a prior send FAILED and we retry now, so a
        # transient Discord blip doesn't silently drop a thesis alert forever. The status
        # check guarantees no double-post ('posted' rows are never re-sent); the retry
        # re-renders from the current thesis row, consistent with the digest path.
        existing = await db.get_wolf_alert(dedupe_key)
        if existing and existing.get("status") == "posted":
            log.debug("wolf_news: already posted for %s, skipping", dedupe_key)
            return False
        alert_id = existing["id"] if existing else None
        if alert_id is None:
            return False
        log.info("wolf_news: retrying previously-failed thesis alert %s", dedupe_key)

    # Render the clean conviction EMBED for ANY event backed by a thesis row (a first
    # sighting that's already a position deserves the same card as an escalation); the
    # rare no-thesis fallback uses plain text.
    if thesis and event["kind"] == "confluence":
        embed = format_confluence_alert(thesis, confl_row, event)
        content = None
    elif thesis:
        backdrop = await build_backdrop(thesis)
        embed = format_conviction_update(event, thesis, backdrop=backdrop, confluence=confl_row)
        content = None
    else:
        embed = None
        content = format_message(event, levels)

    # critical @-ping is phase-2 only (needs confluence corroborator) AND opt-in
    ping_user = None
    if (tier == "critical"
            and cfg.get("wolf.enable_critical_ping", False)
            and _can_ping(now)):
        ping_user = str(cfg.get("api_keys.discord_owner_user_id", "") or "") or None

    dry_run = cfg.get("wolf.dry_run", True)
    if dry_run:
        preview = content if content is not None else json.dumps(embed, ensure_ascii=False)
        log.info("wolf_news[DRY-RUN] would post to #news (tier=%s):\n%s", tier, preview)
        await db.mark_alert_posted(alert_id, None, now)
        return True

    msg_id = await _send_news(content=content, embed=embed, ping_user_id=ping_user)
    if msg_id:
        await db.mark_alert_posted(alert_id, msg_id, now)
        return True
    await db.mark_alert_failed(alert_id)
    return False


async def post_events(events: list[dict]) -> int:
    """Post a batch of events. Returns the count actually posted."""
    posted = 0
    for ev in events:
        try:
            if await post_event(ev):
                posted += 1
        except Exception as exc:
            log.error("wolf_news: post_event error: %s", exc, exc_info=True)
    return posted
