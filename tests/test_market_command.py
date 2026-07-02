"""F6 — the read-only !market / !rotation / !breadth / !regime dashboard.

End-to-end on a TEMP db seeded from a frozen parquet fixture (real historical
closes, checked into git) + synthetic signal_events. Proves the handler renders
all four daily reads (sector rotation, style leadership, price-trend regime,
internal breadth) into one embed with HONEST market-CONTEXT labels (a view, not
a buy/sell signal), the early vs already-moved rotation wording, and a PDT
timestamp.

Hermetic by design (see todo/regression-gate-auto-recovery.md "Concrete
flaky-test example"): this used to seed from the LIVE parquet cache + a live
yfinance refresh + the live consensus.db, which only exists on this VPS and
depends on a network fetch that GitHub's runners get throttled on — the fixture
+ `download=False` removes both dependencies so the test can't flake on CI.

Never touches the live consensus.db: writes go to the per-test temp db forced by
the autouse `_isolate_db` fixture.
"""
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from consensus_engine import config as cfg
from consensus_engine import db
import market_daily

_STORE_DIR = str(_ROOT / "tests" / "fixtures" / "market_store")


def _embed_text(embed: dict) -> str:
    """Flatten an embed dict into one searchable string."""
    parts = [embed.get("title", ""), embed.get("description", "")]
    for f in embed.get("fields", []):
        parts.append(f.get("name", ""))
        parts.append(f.get("value", ""))
    parts.append(embed.get("footer", {}).get("text", ""))
    return "\n".join(parts)


def _seed_signal_events(dst_path: str) -> int:
    """Insert a small synthetic informed directional stream into the temp db.

    Gives the internal-breadth read something to compute over, without depending
    on the live consensus.db (which doesn't exist off this VPS). Deliberately
    long-biased (matches the real bot's structural bias) across several tickers
    and days so the rolling window + z-score have real variation.
    """
    import sqlite3

    rows = []
    now = time.time()
    tickers_long = ["AAPL", "MSFT", "NVDA", "META", "GOOGL"]
    tickers_short = ["TSLA", "SNAP"]
    for day_offset in range(10):
        recorded_at = now - day_offset * 86400
        for ticker in tickers_long:
            rows.append(("twitter", "fixture", ticker, "long", 0.7, None, None, None,
                        recorded_at, None))
        for ticker in tickers_short:
            rows.append(("twitter", "fixture", ticker, "short", 0.7, None, None, None,
                        recorded_at, None))

    dst = sqlite3.connect(dst_path)
    try:
        from consensus_engine.db import SCHEMA
        dst.executescript(SCHEMA)
        dst.executemany(
            "INSERT INTO signal_events (source_type, source_detail, ticker, direction, "
            "quality_score, latency_sec, provenance, model_version, recorded_at, source_link) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        dst.commit()
    finally:
        dst.close()
    return len(rows)


async def _seed_temp_db() -> dict:
    """Seed all 4 daily tables into the isolated temp db; return market_daily counts."""
    db_path = db.DB_PATH
    _seed_signal_events(db_path)
    summary = market_daily.run(db_path=db_path, days=None, dry_run=False,
                               store_dir=_STORE_DIR, download=False)
    return summary


@pytest.mark.asyncio
async def test_market_command_renders_all_four_reads(monkeypatch):
    summary = await _seed_temp_db()
    # The orchestrator wrote every table the dashboard needs.
    assert summary["sector_rs_daily"] > 0
    assert summary["factor_rs_daily"] > 0
    assert summary["trend_daily"] > 0
    assert summary["internal_breadth_daily"] > 0

    await db.init_db()

    # Enable the command flag on top of the autouse audit-off wrapper.
    _current = cfg.get

    def _enabled(key, default=None):
        if key == "features.market_command.enabled":
            return True
        return _current(key, default)

    monkeypatch.setattr(cfg, "get", _enabled)

    captured = {}

    async def _capture(channel_id, message_id, embed):
        captured["embed"] = embed
        return "fake_id"

    from consensus_engine.alerts import commands
    monkeypatch.setattr(commands, "send_command_embed_reply", _capture)

    await commands.route_command("market", [], "chan", "msg")

    assert "embed" in captured, "handler must send an embed when enabled"
    text = _embed_text(captured["embed"])

    # 1. Sector leaderboard present (at least one sector ETF rendered).
    assert "Sector rotation" in text
    assert any(etf in text for etf in ("XLK", "XLF", "XLE", "SMH")), text

    # 2. Honest rotation labels — early vs already-moved must both be available.
    assert "improving (early)" in text.lower()
    assert "already moved" in text.lower()

    # 3. Leading style line.
    assert "Style leadership" in text

    # 4. Trend / regime state.
    assert "Price-trend regime" in text
    assert any(w in text.lower() for w in ("uptrend", "downtrend", "mixed")), text

    # 5. Internal-breadth line with the structural long-bias caveat.
    assert "signal breadth" in text.lower()
    assert "long-biased" in text.lower()

    # 6. Context-not-signal disclaimer.
    assert "not a buy/sell signal" in text.lower()

    # 7. PDT timestamp (never ET — house rule).
    assert "PDT" in text
    assert "ET" not in captured["embed"]["footer"]["text"].replace("PDT", "")


@pytest.mark.asyncio
async def test_market_command_off_path(monkeypatch):
    """Default OFF: replies with a plain 'not enabled' message, no embed."""
    sent = {}

    async def _reply(channel_id, message_id, content):
        sent["content"] = content

    from consensus_engine.alerts import commands
    monkeypatch.setattr(commands, "send_command_reply", _reply)
    # conftest forces market_command.enabled OFF for the baseline suite -> off path
    # (it is live ON in the deployed config; the render test forces ON in-body).
    await commands.route_command("rotation", [], "chan", "msg")
    assert "not enabled" in sent.get("content", "").lower()


def test_commands_module_imports():
    """Import sanity: the edited dispatch module loads and exposes the handler."""
    from consensus_engine.alerts import commands
    assert hasattr(commands, "_handle_market")
    assert hasattr(commands, "_build_market_embed")
