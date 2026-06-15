"""Chat-memory rollups (#39): summarize the bot's archived Discord chat transcripts into
small, durable, REDACTED rollups so it can recall a month-old conversation after a restart
wipe — without re-bloating the live cue.

Pipeline per archive (`channel-<id>.deleted.<ts>.jsonl`, NOT the .trajectory sidecar):
  parse user/assistant text turns + the safeguard compaction summaries already in the file
  -> build a cheap extractive date-bucketed rollup (proven 115x on real data)
  -> REDACT secrets (keys/tokens/emails) — a precondition, since rollups are kept
     permanently while the raw archives are deleted after 30 days
  -> write ONE chat_memory_rollups row keyed by the archive's content sha256 (idempotent).

The cleanup is IDENTITY-gated (exact sha256 + status='complete' + byte-size match), never
date overlap — a date match could delete the wrong / un-summarized file.
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from consensus_engine import config as cfg, db

log = logging.getLogger(__name__)

SESSIONS_DIR = "/home/openclaw/.openclaw/agents/main/sessions"

# ---- redaction: mask secrets before anything permanent is written -------------------
_SECRET_PATTERNS = [
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9]{16,}\b"),                       # OpenAI-style
    re.compile(r"\bapify_(?:api|proxy)_[A-Za-z0-9]{16,}\b"),             # Apify
    re.compile(r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{16,}\b"),     # GitHub
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),                     # Slack
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"),                          # Google
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                 # AWS key id
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}", re.I),                # bearer tokens
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password|passwd)\b\s*[:=]\s*\S{8,}"),
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), # emails
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),  # JWT
]


def redact(text: str) -> str:
    """Mask key/token/email/secret-like substrings with [REDACTED]."""
    if not text:
        return text
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


# ---- parsing -------------------------------------------------------------------------
_FENCE_RE = re.compile(r"```\s*\n(.*?)\n```", re.S)


def _user_text(raw: str) -> str:
    """Strip the steering-template [Context:...] preamble from a user turn — keep just the
    real user message (the fenced 'User message' block when present)."""
    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1).strip()
    # older preamble form: drop a leading bracketed [Context: ...] block
    if raw.lstrip().startswith("["):
        idx = raw.find("]")
        if idx != -1 and idx < len(raw) - 1:
            return raw[idx + 1:].strip()
    return raw.strip()


def _block_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text").strip()
    return ""


def parse_archive(path: str) -> dict:
    """Return {turns:[{ts,role,text}], compaction_summaries:[str], span:(start,end)}."""
    turns: list[dict] = []
    summaries: list[str] = []
    tss: list[float] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            t = r.get("type")
            ts = _iso_to_epoch(r.get("timestamp"))
            if ts:
                tss.append(ts)
            if t == "message":
                msg = r.get("message") or {}
                role = msg.get("role")
                text = _block_text(msg.get("content"))
                if role == "user":
                    text = _user_text(text)
                if role in ("user", "assistant") and text:
                    turns.append({"ts": ts, "role": role, "text": text})
            elif t == "compaction":
                s = (r.get("summary") or "").strip()
                if s:
                    summaries.append(s)
    span = (min(tss), max(tss)) if tss else (0.0, 0.0)
    return {"turns": turns, "compaction_summaries": summaries, "span": span}


def _iso_to_epoch(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# ---- extractive rollup ---------------------------------------------------------------
def build_extractive_rollup(parsed: dict, per_line_cap: int = 220) -> str:
    """Cheap, high-fidelity rollup: date-bucketed Q/A pairs + the compaction summaries.
    No LLM needed (the research showed this alone answered month-old recall questions)."""
    lines: list[str] = []
    turns = parsed["turns"]
    # pair each user turn with the next assistant turn
    i = 0
    by_day: dict[str, list[str]] = {}
    order: list[str] = []
    while i < len(turns):
        if turns[i]["role"] == "user":
            q = turns[i]["text"]
            a = ""
            if i + 1 < len(turns) and turns[i + 1]["role"] == "assistant":
                a = turns[i + 1]["text"]
                i += 1
            day = _day_of(turns[i]["ts"])
            if day not in by_day:
                by_day[day] = []
                order.append(day)
            entry = f"  Q: {_clip(q, per_line_cap)}"
            if a:
                entry += f"\n  A: {_clip(a, per_line_cap)}"
            by_day[day].append(entry)
        i += 1
    for day in order:
        lines.append(f"[{day}]")
        lines.extend(by_day[day])
    if parsed["compaction_summaries"]:
        lines.append("\n## Prior compaction summaries (verbatim, distilled by the runtime):")
        for s in parsed["compaction_summaries"]:
            lines.append(_clip(s, 1200))
    return "\n".join(lines)


def _day_of(ts: float | None) -> str:
    if not ts:
        return "undated"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


# ---- summarize one archive -----------------------------------------------------------
def _channel_id_from_path(path: str) -> str:
    base = os.path.basename(path)
    m = re.match(r"channel-(\d+)\.", base)
    return m.group(1) if m else base


def _sha256_of(path: str) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


async def summarize_archive(path: str, now: float | None = None, use_llm: bool | None = None) -> dict:
    """Parse -> extractive rollup -> (optional LLM tighten) -> REDACT -> write a row.
    Returns a summary dict {channel_id, sha, turns, bytes, status}."""
    now = now or time.time()
    sha, nbytes = _sha256_of(path)
    channel_id = _channel_id_from_path(path)
    parsed = parse_archive(path)
    rollup = build_extractive_rollup(parsed)

    if use_llm is None:
        use_llm = bool(cfg.get("chat_memory.llm_tighten", False))
    model_used = "extractive"
    if use_llm and rollup:
        tightened = await _llm_tighten(rollup)
        if tightened:
            rollup = tightened
            model_used = "gpt-oss-120b"

    rollup = redact(rollup)            # PRECONDITION: redact before the permanent write
    status = "complete" if parsed["turns"] or parsed["compaction_summaries"] else "failed"
    await db.upsert_chat_rollup(
        channel_id=channel_id, archive_path=path, source_sha256=sha,
        session_label=f"channel-{channel_id}", status=status,
        span_start_utc=parsed["span"][0], span_end_utc=parsed["span"][1],
        turn_count=len(parsed["turns"]), source_bytes=nbytes,
        rollup=rollup, model=model_used, now=now)
    return {"channel_id": channel_id, "sha": sha, "turns": len(parsed["turns"]),
            "bytes": nbytes, "status": status}


async def _llm_tighten(extractive: str) -> str | None:
    """Best-effort: tighten the extractive rollup into Decisions/Open-questions/Identifiers."""
    try:
        from consensus_engine.llm_client import call_with_fallback
        prompt = (
            "Summarize this Discord chat log into a COMPACT memory note with sections: "
            "Decisions, Open questions, Identifiers (tickers/files/IDs), Pending asks. "
            "Keep every concrete identifier (ticker, file path, function, number). "
            "Do not invent anything. Log:\n\n" + extractive[:120000])
        out = await call_with_fallback(
            None, [{"role": "user", "content": prompt}],
            chain=cfg.get("wolf.extraction_models", []) or None,
            max_tokens=2000, temperature=0.1, timeout=60)
        return (out or "").strip() or None
    except Exception as e:
        log.debug("chat_rollup: LLM tighten failed (using extractive): %s", e)
        return None


# ---- scan + cleanup ------------------------------------------------------------------
def _transcript_archives() -> list[str]:
    """All conversation-transcript archives (excludes the .trajectory sidecars)."""
    files = glob.glob(os.path.join(SESSIONS_DIR, "channel-*.deleted.*.jsonl"))
    return sorted(f for f in files if ".trajectory." not in f)


async def scan_and_summarize(max_archives: int = 25, max_bytes: int = 80_000_000) -> dict:
    """Summarize un-rolled-up transcript archives, oldest first, within a budget (so the
    backlog drains over a few runs instead of one-per-night). Idempotent via sha256."""
    done = 0
    spent = 0
    for path in _transcript_archives():
        if done >= max_archives or spent >= max_bytes:
            break
        try:
            sha, nbytes = _sha256_of(path)
        except Exception:
            continue
        if await db.chat_rollup_exists(sha):
            continue
        try:
            await summarize_archive(path)
            done += 1
            spent += nbytes
        except Exception as e:
            log.warning("chat_rollup: failed to summarize %s: %s", path, e)
    remaining = 0
    for p in _transcript_archives():
        try:
            if not await db.chat_rollup_exists(_sha256_of(p)[0]):
                remaining += 1
        except Exception:
            pass
    log.info("chat_rollup: summarized %d archive(s) this run; %d still un-summarized",
             done, remaining)
    return {"summarized": done, "remaining": remaining}


async def cleanup_old_archives(retention_days: int = 30, now: float | None = None) -> int:
    """Delete raw transcript archives older than retention_days ONLY when an exact-hash
    'complete' rollup of those bytes exists (identity gate). Also drops the .trajectory
    sidecar. Returns files deleted."""
    now = now or time.time()
    cutoff = now - retention_days * 86400
    deleted = 0
    for path in _transcript_archives():
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime > cutoff:
            continue
        try:
            sha, nbytes = _sha256_of(path)
        except Exception:
            continue
        row = await db.get_chat_rollup_by_sha(sha)
        if not row or row.get("status") != "complete" or int(row.get("source_bytes", -1)) != nbytes:
            continue   # no covering complete rollup of these EXACT bytes -> keep
        try:
            os.remove(path)
            deleted += 1
            traj = path.replace(".deleted.", ".trajectory.deleted.")
            if os.path.exists(traj):
                os.remove(traj)
                deleted += 1
        except OSError as e:
            log.warning("chat_rollup: could not delete %s: %s", path, e)
    if deleted:
        log.info("chat_rollup: cleanup deleted %d raw archive file(s) (rollups kept)", deleted)
    return deleted


async def chat_memory_loop(stop_event) -> None:
    """Nightly: summarize the un-rolled-up backlog (budgeted) then run the gated cleanup.
    No-op while chat_memory.enabled is false. NOT a gateway-reconnect hook (reconnects are
    constant; a reconnect-triggered summarization would burn quota + block the loop)."""
    interval = int(cfg.get("intervals.chat_memory_loop", 86400))
    while not stop_event.is_set():
        try:
            if cfg.get("chat_memory.enabled", False):
                await scan_and_summarize(
                    max_archives=int(cfg.get("chat_memory.max_archives_per_run", 25)))
                await cleanup_old_archives(
                    retention_days=int(cfg.get("chat_memory.retention_days", 30)))
        except Exception as e:
            log.error("chat_memory_loop error: %s", e, exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
