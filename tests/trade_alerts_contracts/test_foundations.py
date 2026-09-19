"""Existing config, calendar, SQLite and automatic-fixture contracts (M0.4)."""

from datetime import date, datetime
import sqlite3
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)


def test_c04_01_config_defaults_cache_and_reload(tmp_path, monkeypatch):
    from consensus_engine import config
    import trade_alerts_isolation as isolation

    assert isolation.dotenv_calls
    assert config.get("example.nested.value") == 7
    assert config.get("example.missing", 19) == 19
    assert config.get("example.scalar.missing", 23) == 23
    cached = config.load_config()
    assert config.load_config(tmp_path / "ignored.yaml") is cached
    config._DEFAULT_CONFIG_PATH.write_text("example:\n  nested:\n    value: 11\n")
    assert config.get("example.nested.value") == 7
    assert config.reload() == {"example": {"nested": {"value": 11}}}
    assert config.get("example.nested.value") == 11
    monkeypatch.setenv("M04_SYNTHETIC_VALUE", "fixture-only")
    config._DEFAULT_CONFIG_PATH.write_text(
        "example:\n  direct: $M04_SYNTHETIC_VALUE\n  missing: $M04_ABSENT_VALUE\n"
        "  items: [$M04_SYNTHETIC_VALUE, literal]\n")
    assert config.reload()["example"] == {
        "direct": "fixture-only", "missing": "", "items": ["fixture-only", "literal"]}


@pytest.mark.parametrize("day,close,offset", [
    (date(2026, 3, 6), "13:00", -8),
    (date(2026, 3, 9), "13:00", -7),
    (date(2026, 7, 2), "13:00", -7),
    (date(2026, 11, 27), "10:00", -8),
])
def test_c04_04_calendar_exact_session_bounds(day, close, offset):
    from consensus_engine.utils import time_context

    bounds = time_context.session_bounds(day)
    assert bounds is not None
    opened, closed = [value.astimezone(ZoneInfo("America/Los_Angeles")) for value in bounds]
    assert opened.strftime("%H:%M") == "06:30"
    assert closed.strftime("%H:%M") == close
    assert opened.utcoffset().total_seconds() == offset * 3600
    calendar_row = time_context._NYSE.schedule(day, day).iloc[0]
    assert opened == calendar_row["market_open"]
    assert closed == calendar_row["market_close"]


def test_c04_04_holiday_weekend_and_exact_session_dates():
    from consensus_engine.utils import time_context

    assert time_context.session_bounds(date(2026, 7, 3)) is None
    assert time_context.session_bounds(date(2026, 7, 4)) is None
    assert time_context.session_dates(date(2026, 7, 1), date(2026, 7, 6)) == [
        date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6)]
    assert time_context.session_dates(date(2026, 7, 6), date(2026, 7, 1)) == []


def test_c04_04_fixed_clock_display(monkeypatch):
    from consensus_engine.utils import time_context

    fixed = datetime(2026, 3, 9, 7, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz)

    monkeypatch.setattr(time_context, "datetime", Clock)
    assert time_context.build_time_context_oneliner() == "2026-03-09 07:00 AM PDT (Mon, NYSE open)"


async def test_c04_05_real_migrations_idempotent_and_transaction_rollback(tmp_path):
    from consensus_engine import db

    assert db._db is None
    conn = await db.init_db()
    assert await db.get_db() is conn
    path_row = await (await conn.execute("PRAGMA database_list")).fetchone()
    assert path_row[2] == db.DB_PATH
    assert str(tmp_path) in path_row[2]
    versions = [tuple(row) for row in await (await conn.execute(
        "SELECT version, note FROM schema_version ORDER BY version")).fetchall()]
    assert [row[0] for row in versions] == list(range(7, 37))
    schema = [tuple(row) for row in await (await conn.execute(
        "SELECT name, sql FROM sqlite_master ORDER BY name")).fetchall()]
    await conn.execute("CREATE TABLE m04_probe (value INTEGER UNIQUE)")
    with pytest.raises(sqlite3.IntegrityError):
        await conn.execute_transaction([
            ("INSERT INTO m04_probe VALUES (?)", (1,)),
            ("INSERT INTO m04_probe VALUES (?)", (1,)),
        ])
    assert (await (await conn.execute("SELECT COUNT(*) FROM m04_probe")).fetchone())[0] == 0
    await conn.execute_transaction([
        ("INSERT INTO m04_probe VALUES (?)", (2,)),
        ("INSERT INTO m04_probe VALUES (?)", (3,)),
    ])
    await conn.execute("DROP TABLE m04_probe")
    await db.close_db()
    assert db._db is None
    with pytest.raises(sqlite3.ProgrammingError):
        await conn.execute("SELECT 1")
    reopened = await db.init_db()
    assert reopened is not conn
    assert [tuple(row) for row in await (await reopened.execute(
        "SELECT version, note FROM schema_version ORDER BY version")).fetchall()] == versions
    assert [tuple(row) for row in await (await reopened.execute(
        "SELECT name, sql FROM sqlite_master ORDER BY name")).fetchall()] == schema


@pytest.mark.parametrize("iteration", [1, 2])
async def test_c04_07_automatic_flags_db_and_http_cleanup(iteration, monkeypatch):
    from consensus_engine import config, db
    from consensus_engine.utils import http, prices
    from consensus_engine.scanners import schwab_client
    import pandas as pd

    assert db._db is None
    assert http._session is None
    assert http._lock is None
    assert config._config is None
    assert config.load_config()["features"]["schwab_ohlcv"]["enabled"] is True
    assert config.get("features.schwab_ohlcv.enabled") is False
    real_get = config.get
    monkeypatch.setattr(config, "get", lambda key, default=None: (
        True if key == "features.schwab_ohlcv.enabled" else real_get(key, default)))
    calls = []
    frame = pd.DataFrame({"Close": [100.0]})

    def history(*args, **kwargs):
        calls.append((args, kwargs))
        return frame

    monkeypatch.setattr(schwab_client, "get_price_history", history)
    assert prices.fetch_history("SYNTH", period="1d") is frame
    assert len(calls) == 1
    await db.get_db()

    class Session:
        closed = False

        async def close(self):
            self.closed = True

    http._session = Session()
    http._get_lock()
