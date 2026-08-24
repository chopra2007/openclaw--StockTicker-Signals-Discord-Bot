from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from consensus_engine import config as cfg
from consensus_engine.alerts import commands
from consensus_engine.alerts.discord import format_detail_followup, format_instant_ping
from consensus_engine.alerts.nfci_display import nfci_state, render_nfci_note
from consensus_engine.models import (
    Conviction,
    CrossReferenceResult,
    Direction,
    ParsedTweet,
    ScoreBreakdown,
    TweetType,
)


TODAY = date(2026, 8, 16)


def _row(value=-0.549, observation_date="2026-08-07"):
    return {
        "nfci_index": value,
        "nfci_multiplier": 1.02745,
        "nfci_observation_date": observation_date,
        "recorded_at": 1_786_929_345.0,
    }


def _xref(row=None):
    return CrossReferenceResult(
        ticker="ABCD",
        breakdown=ScoreBreakdown(base=30),
        catalyst_summary="",
        catalyst_type="",
        nfci_row=row,
    )


def test_tight_normal_and_loose_states():
    assert nfci_state(_row(1.5), TODAY, 16, -0.706, 1.402) == "tight"
    assert nfci_state(_row(-0.5), TODAY, 16, -0.706, 1.402) == "normal"
    assert nfci_state(_row(-0.8), TODAY, 16, -0.706, 1.402) == "loose"


def test_missing_and_stale_rows_render_nothing():
    assert nfci_state(None, TODAY, 16, -0.706, 1.402) is None
    stale = _row(observation_date=(TODAY - timedelta(days=17)).isoformat())
    assert render_nfci_note(stale, TODAY, 16, -0.706, 1.402, unusual_only=False) is None


def test_detail_card_only_adds_unusual_note(monkeypatch):
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get", lambda key, default=None: {
            "features.cross_asset.nfci_note": True,
            "features.cross_asset.nfci_max_observation_age_days": 16,
            "features.cross_asset.nfci_loose_cutoff": -0.706,
            "features.cross_asset.nfci_tight_cutoff": 1.402,
        }.get(key, real_get(key, default)),
    )
    with patch("consensus_engine.alerts.discord.datetime") as clock:
        clock.now.return_value = __import__("datetime").datetime(2026, 8, 16)
        normal = format_detail_followup(_xref(_row(-0.5)))
        tight = format_detail_followup(_xref(_row(1.5)))
    assert "Economy-wide financial stress" not in str(normal)
    assert "borrowing is harder than normal" in str(tight)


def test_flag_off_suppresses_detail_note(monkeypatch):
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get", lambda key, default=None: False
        if key == "features.cross_asset.nfci_note" else real_get(key, default),
    )
    assert "NFCI" not in str(format_detail_followup(_xref(_row(1.5))))


def test_market_always_renders_usable_normal_reading(monkeypatch):
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get", lambda key, default=None: {
            "features.cross_asset.nfci_max_observation_age_days": 16,
            "features.cross_asset.nfci_loose_cutoff": -0.706,
            "features.cross_asset.nfci_tight_cutoff": 1.402,
        }.get(key, real_get(key, default)),
    )
    with patch("consensus_engine.alerts.commands.datetime") as clock:
        clock.now.return_value = __import__("datetime").datetime(2026, 8, 16)
        embed = commands._build_market_embed(
            [], [], None, None, "note", nfci_row=_row(-0.5)
        )
    assert "financial conditions normal" in str(embed)
    assert "2026-08-07" in str(embed)


def test_instant_ping_has_no_nfci_note():
    tweet = ParsedTweet(
        tweet_url="https://example.test/tweet",
        analyst="tester",
        raw_text="ABCD long",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["ABCD"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="ABCD long",
    )
    assert "NFCI" not in str(format_instant_ping(tweet))


async def test_alert_display_read_is_database_only(monkeypatch, tmp_path):
    import consensus_engine.db as db_module
    db_module.DB_PATH = str(tmp_path / "nfci.db")
    db_module._db = None
    await db_module.init_db()
    await db_module.insert_cross_asset_shadow(
        None, None, None, None, 1.0,
        nfci_index=-0.8,
        nfci_multiplier=1.04,
        nfci_observation_date="2026-08-07",
    )
    with patch("urllib.request.urlopen", side_effect=AssertionError("network called")):
        row = await db_module.get_latest_nfci_display()
    assert row["nfci_observation_date"] == "2026-08-07"
    await db_module.close_db()
    db_module._db = None
    db_module.DB_PATH = None


async def test_same_day_row_gains_matching_observation_date(tmp_path):
    import consensus_engine.db as db_module
    db_module.DB_PATH = str(tmp_path / "nfci-fill.db")
    db_module._db = None
    await db_module.init_db()
    wrote = await db_module.insert_cross_asset_shadow(
        None, None, None, None, 1.0,
        nfci_index=-0.549,
        nfci_multiplier=1.02745,
    )
    updated = await db_module.insert_cross_asset_shadow(
        None, None, None, None, 1.0,
        nfci_index=-0.549,
        nfci_multiplier=1.02745,
        nfci_observation_date="2026-08-07",
    )
    assert wrote is True
    assert updated is False
    assert (await db_module.get_latest_nfci_display())["nfci_observation_date"] == "2026-08-07"
    await db_module.close_db()
    db_module._db = None
    db_module.DB_PATH = None


async def test_market_handler_uses_cached_nfci_row_only(monkeypatch):
    captured = {}

    async def latest(table):
        return None

    async def capture(channel_id, message_id, embed):
        captured["embed"] = embed

    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get", lambda key, default=None: {
            "features.market_command.enabled": True,
            "features.market_breadth.enabled": False,
            "features.vvix_residual.enabled": False,
            "features.cross_asset.nfci_note": True,
            "features.cross_asset.nfci_max_observation_age_days": 16,
            "features.cross_asset.nfci_loose_cutoff": -0.706,
            "features.cross_asset.nfci_tight_cutoff": 1.402,
        }.get(key, real_get(key, default)),
    )
    monkeypatch.setattr("consensus_engine.analysis.market_panel.get_latest_row", latest)
    monkeypatch.setattr(commands.db, "get_latest_nfci_display", lambda: _async_value(_row()))
    monkeypatch.setattr(commands, "_build_market_context_fields", lambda: _async_value([]))
    monkeypatch.setattr(commands, "send_command_embed_reply", capture)
    with patch("urllib.request.urlopen", side_effect=AssertionError("network called")), \
         patch("consensus_engine.alerts.commands.datetime") as clock:
        # Freeze "today" close to the fake row's 2026-08-07 reading so the
        # 16-day staleness check in render_nfci_note() doesn't age it out as
        # real calendar time moves past the fixed reading date (TODO #94).
        clock.now.return_value = __import__("datetime").datetime(2026, 8, 16)
        await commands._handle_market("local", "local")
    assert "NFCI -0.549" in str(captured["embed"])


async def _async_value(value):
    return value
