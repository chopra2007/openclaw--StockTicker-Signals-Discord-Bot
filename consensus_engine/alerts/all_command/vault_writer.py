"""Vault read/write for !all command.

Owns a separate vault file per ticker — `<vault>/tickers/<TICKER>-all.md` —
so the !all rebuild does NOT race or overwrite Atlas's `<TICKER>.md`
(Pass-3 mitigation B2). Atomic writes use a unique tmp suffix
`{pid}.{uuid8}` plus os.replace, plus a per-ticker asyncio.Lock to serialize
same-process concurrent !all rebuilds for the same ticker.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from consensus_engine.alerts.all_command.levels import Anchor
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown
from consensus_engine.utils.tickers import is_valid_ticker

log = logging.getLogger("consensus_engine.alerts.all_command.vault_writer")

# Per-ticker write locks (module-level dict; created lazily).
_write_locks: dict[str, asyncio.Lock] = {}
_lock_guard = asyncio.Lock()


def _vault_dir(vault_path: str) -> str:
    """Resolve `<vault_path>/tickers` directory."""
    return os.path.join(vault_path, "tickers")


def _vault_file(vault_path: str, ticker: str) -> str:
    """Resolve `<vault_path>/tickers/<TICKER>-all.md` (separate from Atlas)."""
    return os.path.join(_vault_dir(vault_path), f"{ticker}-all.md")


async def _get_write_lock(ticker: str) -> asyncio.Lock:
    """Return the per-ticker asyncio.Lock, creating it on first use."""
    async with _lock_guard:
        lock = _write_locks.get(ticker)
        if lock is None:
            lock = asyncio.Lock()
            _write_locks[ticker] = lock
        return lock


async def read_existing_vault(ticker: str, vault_path: str) -> Optional[str]:
    """Read prior `<vault>/tickers/<TICKER>-all.md` for context.

    Returns None on missing/corrupt content. Never raises — corrupt vault is
    treated as no prior context (per plan §7 'Vault read corruption').
    """
    if not vault_path:
        return None
    path = _vault_file(vault_path, ticker)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 — corrupt read = no prior ctx
        log.warning(
            "vault_writer.read_existing_vault: %s unreadable: %s",
            path, exc,
        )
        return None


def render_all_command_markdown(
    ticker: str,
    structured: StructuredFields,
    score_breakdown: ScoreBreakdown,
    narrative: str,
    sources_used: list[str],
    alert_history: list[dict],
    anchors_used: list[Anchor],
) -> str:
    """Render the self-contained markdown body for `<TICKER>-all.md`.

    Layout (per plan §3.8):
    1. Title + generated timestamp + cache key
    2. Direction / Confidence / Trade Plan
    3. Narrative (full)
    4. Score Breakdown
    5. Sources
    6. Alert History
    7. Anchored Levels Used
    """
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _price(v) -> str:
        return f"${float(v):.2f}" if isinstance(v, (int, float)) and v is not None else "—"

    direction = getattr(structured, "direction", "NEUTRAL") or "NEUTRAL"
    confidence = getattr(structured, "confidence_label", "LOW") or "LOW"

    # Score breakdown table
    breakdown_rows = []
    if score_breakdown is not None:
        for attr in (
            "base", "additional_analysts", "news_catalyst", "sec_filing",
            "technical", "social_apewisdom", "social_stocktwits", "social_reddit",
            "google_trends", "llm_boost", "options_flow", "consensus_boost",
        ):
            try:
                val = int(getattr(score_breakdown, attr, 0) or 0)
            except (TypeError, ValueError):
                continue
            if val:
                breakdown_rows.append(f"| {attr} | {val} |")
        total = getattr(score_breakdown, "total", None)
    else:
        total = None
    breakdown_block = "| component | points |\n|---|---|\n"
    breakdown_block += "\n".join(breakdown_rows) if breakdown_rows else "| (none) | 0 |"
    if total is not None:
        breakdown_block += f"\n\n**Total:** {total}"

    # Sources
    if sources_used:
        sources_block = "\n".join(f"- {s}" for s in sources_used)
    else:
        sources_block = "_(no sources)_"

    # Alert history (full list)
    if alert_history:
        history_lines: list[str] = []
        for row in alert_history:
            ts_raw = row.get("alerted_at", row.get("ts", ""))
            try:
                ts_str = (
                    datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
                            .isoformat(timespec="minutes")
                    if ts_raw else "—"
                )
            except (TypeError, ValueError):
                ts_str = str(ts_raw)
            score = row.get("final_score", row.get("score", "—"))
            catalyst = row.get("catalyst", "—")
            history_lines.append(f"- `{ts_str}` score={score} catalyst={catalyst}")
        history_block = "\n".join(history_lines)
    else:
        history_block = "_(no alerts in 30 days)_"

    # Anchors
    if anchors_used:
        anchor_lines = ["| price | source | type | touches | freshness | score |",
                        "|---|---|---|---|---|---|"]
        for a in anchors_used:
            anchor_lines.append(
                f"| {_price(a.price)} | {a.source} | {a.source_type} | "
                f"{a.touches} | {a.freshness_days}d | {a.computed_score:.2f} |"
            )
        anchor_block = "\n".join(anchor_lines)
    else:
        anchor_block = "_(no anchors)_"

    from consensus_engine import config as _cfg
    swing_v2 = bool(_cfg.get("all_command.swing_v2_enabled", True))
    if swing_v2:
        next_catalyst_days = getattr(structured, "next_catalyst_days", None)
        nc_str = f"{next_catalyst_days}d" if isinstance(next_catalyst_days, int) and next_catalyst_days >= 0 else "TBD"
        sh_days = getattr(structured, "swing_horizon_days", None)
        sh_band = getattr(structured, "swing_horizon_band", None)
        if isinstance(sh_days, int) and sh_days > 0 and sh_band:
            sh_str = f"{sh_band[0]}–{sh_band[1]} days"
        elif sh_days == 0:
            sh_str = "at target"
        else:
            sh_str = "TBD"
        em_str = getattr(structured, "magnitude_band_label", None) or "TBD"
        trade_plan_block = (
            f"- Next Catalyst: {nc_str}\n"
            f"- Horizon: {sh_str}\n"
            f"- Expected Move: {em_str}\n"
        )
        schema_version = 2
    else:
        trade_plan_block = (
            f"- Timeframe: {getattr(structured, 'breakout_timeframe', 'TBD') or 'TBD'}\n"
            f"- Magnitude: {getattr(structured, 'magnitude_label', 'TBD') or 'TBD'}\n"
        )
        schema_version = 1

    return (
        f"# {ticker} — !all Analysis\n"
        f"_Generated: {now_iso}_  •  _cache_key=all:{ticker}, ttl=15m_  •  "
        f"_schema_version={schema_version}_\n\n"
        "## Direction / Confidence / Trade Plan\n"
        f"- Direction: **{direction}**\n"
        f"- Confidence: **{confidence}**\n"
        f"- SL: {_price(getattr(structured, 'sl', None))}\n"
        f"- TP1: {_price(getattr(structured, 'tp1', None))}\n"
        f"- TP2: {_price(getattr(structured, 'tp2', None))}\n"
        f"- TP3: {_price(getattr(structured, 'tp3', None))}\n"
        f"{trade_plan_block}\n"
        "## Narrative\n"
        f"{narrative or '_(no narrative)_'}\n\n"
        "## Score Breakdown\n"
        f"{breakdown_block}\n\n"
        "## Sources\n"
        f"{sources_block}\n\n"
        "## Alert History (last 30d)\n"
        f"{history_block}\n\n"
        "## Anchored Levels Used\n"
        f"{anchor_block}\n"
    )


async def write_all_command_vault(
    ticker: str,
    content: str,
    vault_path: str,
) -> str:
    """Atomically write `content` to `<vault>/tickers/<TICKER>-all.md`.

    Defense-in-depth: re-validates the ticker shape before any path operation
    (D16). Uses a unique tmp suffix `{pid}.{uuid8}` so two same-process writes
    never collide on the tmp file even with the per-ticker lock. Lock is per
    ticker so concurrent !all writes to different tickers don't serialize.
    Returns the final file path on success.
    """
    if not is_valid_ticker(ticker):
        raise ValueError(f"vault_writer: invalid ticker {ticker!r}")
    if not vault_path:
        raise ValueError("vault_writer: vault_path is empty")

    target_dir = _vault_dir(vault_path)
    final_path = _vault_file(vault_path, ticker)
    suffix = f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    tmp_path = final_path + suffix

    lock = await _get_write_lock(ticker)
    async with lock:
        os.makedirs(target_dir, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, final_path)
    return final_path
