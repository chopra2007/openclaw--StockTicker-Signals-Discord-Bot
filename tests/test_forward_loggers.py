"""#62: the two forward-loggers that feed the autonomous auto-flip engine.

The safety property under test everywhere below: logging must change ZERO alerts
until the auto-flip engine flips a scoring flag.
"""
import json
import time

import pytest

from consensus_engine import config, db
from consensus_engine.analysis import display_signals as ds
from consensus_engine.analysis.source_performance import compute_source_performance_live


# --- feature-vector merge ---------------------------------------------------

async def _snapshot(fv: dict | None = None) -> int:
    return await db.record_decision_snapshot(
        ticker="AAA", decision="STRONG", final_score=50.0, sources_json="{}",
        feature_vector_json=json.dumps(fv) if fv else None,
    )


async def test_merge_adds_keys_and_keeps_the_old_ones():
    await db.init_db()
    sid = await _snapshot({"n_opposing": 2})
    assert await db.merge_snapshot_feature_vector(sid, {"peer_rs": 1.5}) is True
    conn = await db.get_db()
    cur = await conn.execute("SELECT feature_vector_json FROM decision_snapshots WHERE id=?", (sid,))
    fv = json.loads((await cur.fetchone())["feature_vector_json"])
    assert fv == {"n_opposing": 2, "peer_rs": 1.5}
    await db.close_db()


async def test_merge_into_a_null_vector():
    await db.init_db()
    sid = await _snapshot(None)
    await db.merge_snapshot_feature_vector(sid, {"max_pain": 1.0})
    conn = await db.get_db()
    cur = await conn.execute("SELECT feature_vector_json FROM decision_snapshots WHERE id=?", (sid,))
    assert json.loads((await cur.fetchone())["feature_vector_json"]) == {"max_pain": 1.0}
    await db.close_db()


async def test_merge_survives_unparseable_stored_json():
    await db.init_db()
    sid = await _snapshot({"a": 1})
    conn = await db.get_db()
    await conn.execute("UPDATE decision_snapshots SET feature_vector_json='{oops' WHERE id=?", (sid,))
    await conn.commit()
    assert await db.merge_snapshot_feature_vector(sid, {"peer_rs": 2.0}) is True
    cur = await conn.execute("SELECT feature_vector_json FROM decision_snapshots WHERE id=?", (sid,))
    assert json.loads((await cur.fetchone())["feature_vector_json"]) == {"peer_rs": 2.0}
    await db.close_db()


async def test_merge_on_a_missing_row_returns_false_not_raise():
    await db.init_db()
    assert await db.merge_snapshot_feature_vector(999_999, {"x": 1}) is False
    await db.close_db()


async def test_merge_of_nothing_is_a_no_op():
    await db.init_db()
    assert await db.merge_snapshot_feature_vector(1, {}) is False
    await db.close_db()


# --- canonical features (what the auto-flip checker actually reads) ----------

FULL = {
    "max_pain_spot_gap_pct": 4.5, "max_pain_strike": 300.0,
    "analyst_momentum_shift": -0.09,
    "eps_revision_breadth": 0.8, "eps_revision_net": 24.0,
    "peer_rs_delta": 13.09, "peer_rs_verdict": "outperforming",
    "chart_pattern": "bull_flag", "chart_pattern_confidence": 0.6,
}


def test_canonical_emits_the_five_names_the_checker_looks_for():
    out = ds.canonical_features(FULL)
    assert set(out) == {"max_pain", "analyst_momentum", "eps_revision", "peer_rs",
                        "chart_pattern"}


def test_every_canonical_value_is_a_plain_number():
    """The checker skips any non-numeric value. A string label here would make the
    switch permanently un-testable while looking like it was logged."""
    for k, v in ds.canonical_features(FULL).items():
        assert isinstance(v, (int, float)) and not isinstance(v, bool), k


def test_bullish_pattern_is_positive_and_no_pattern_is_zero():
    assert ds.canonical_features({**FULL, "chart_pattern": "bull_flag",
                                  "chart_pattern_confidence": 0.6})["chart_pattern"] == 0.6
    flat = ds.canonical_features({"chart_pattern": "none", "chart_pattern_confidence": 0.0})
    assert flat["chart_pattern"] == 0.0


def test_no_pattern_is_recorded_not_dropped():
    """'Clean chart' is data. Dropping it biases the sample toward stocks that
    happened to have a pattern."""
    assert "chart_pattern" in ds.canonical_features({"chart_pattern": "none"})


def test_missing_signals_are_omitted_never_zero_filled():
    out = ds.canonical_features({"peer_rs_delta": 1.0})
    assert out == {"peer_rs": 1.0}


def test_nan_and_inf_are_dropped():
    assert ds.canonical_features({"peer_rs_delta": float("nan")}) == {}
    assert ds.canonical_features({"peer_rs_delta": float("inf")}) == {}


# --- the scoring consumer: built, and OFF -----------------------------------

def test_consumer_is_zero_while_the_flag_is_off():
    assert ds.display_signal_adjustment(FULL) == 0


def _flag_on(monkeypatch, **extra):
    real = config.get
    over = {"scoring.fold_display_signals.enabled": True, **extra}
    monkeypatch.setattr(config, "get", lambda k, d=None: over.get(k, real(k, d)))


def test_consumer_is_zero_on_empty_signals(monkeypatch):
    _flag_on(monkeypatch)
    assert ds.display_signal_adjustment({}) == 0
    assert ds.display_signal_adjustment(None) == 0


def test_consumer_rewards_a_bullish_picture(monkeypatch):
    _flag_on(monkeypatch)
    assert ds.display_signal_adjustment(
        {"eps_revision_breadth": 1.0, "peer_rs_delta": 10.0,
         "chart_pattern": "bull_flag", "chart_pattern_confidence": 1.0}) > 0


def test_consumer_punishes_a_bearish_picture(monkeypatch):
    _flag_on(monkeypatch)
    assert ds.display_signal_adjustment(
        {"eps_revision_breadth": -1.0, "peer_rs_delta": -10.0}) < 0


def test_consumer_is_hard_capped(monkeypatch):
    _flag_on(monkeypatch, **{"scoring.fold_display_signals.max_points": 8})
    absurd = {"analyst_momentum_shift": 99.0, "eps_revision_breadth": 1.0,
              "peer_rs_delta": 999.0, "chart_pattern": "bull_flag",
              "chart_pattern_confidence": 1.0}
    assert ds.display_signal_adjustment(absurd) == 8
    assert ds.display_signal_adjustment(
        {"peer_rs_delta": -999.0, "eps_revision_breadth": -1.0,
         "analyst_momentum_shift": -99.0, "max_pain_spot_gap_pct": 999.0}) == -8


def test_spot_far_above_max_pain_is_a_headwind(monkeypatch):
    _flag_on(monkeypatch)
    assert ds.display_signal_adjustment({"max_pain_spot_gap_pct": 10.0}) < 0


# --- the analyst horizon gate ----------------------------------------------

def test_horizon_is_1h_while_the_promote_flag_is_off():
    assert db.analyst_horizon() == "1h"


def test_horizon_becomes_24h_when_the_flag_flips(monkeypatch):
    real = config.get
    monkeypatch.setattr(config, "get", lambda k, d=None:
                        True if k == "scoring.analyst_accuracy_weight.enabled" else real(k, d))
    assert db.analyst_horizon() == "24h"


# --- the live analyst producer ---------------------------------------------

async def _alert(handle: str, entry: float, p24: float | None, p5: float | None,
                 catalyst: str = "Analyst Upgrade") -> None:
    conn = await db.get_db()
    await conn.execute(
        """INSERT INTO alert_history (ticker, catalyst_type, analyst_mentions,
             alerted_at, price_at_alert, price_1h_later, price_24h_later, price_5d_later)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("AAA", catalyst, json.dumps([handle]), time.time() - 10 * 86400,
         entry, entry * 1.5, p24, p5),
    )
    await conn.commit()


async def test_live_producer_writes_24h_and_5d_but_never_1h():
    await db.init_db()
    await _alert("bob", 100.0, 110.0, 120.0)
    summary = await compute_source_performance_live()
    assert summary["by_horizon"] == {"24h": 1, "5d": 1}
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) c FROM source_performance WHERE horizon='1h'")
    assert (await cur.fetchone())["c"] == 0, "a 1h row would immediately change live alerts"
    await db.close_db()


async def test_live_producer_grades_a_bullish_call_by_the_up_move():
    await db.init_db()
    await _alert("bull", 100.0, 110.0, 90.0)   # right at 24h, wrong at 5d
    await compute_source_performance_live()
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT horizon, rolling_accuracy FROM source_performance WHERE entity_id='bull'")
    got = {r["horizon"]: r["rolling_accuracy"] for r in await cur.fetchall()}
    assert got == {"24h": 1.0, "5d": 0.0}
    await db.close_db()


async def test_live_producer_grades_a_bearish_catalyst_by_the_down_move():
    await db.init_db()
    await _alert("bear", 100.0, 90.0, 80.0, catalyst="Analyst Downgrade")
    await compute_source_performance_live()
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT horizon, rolling_accuracy FROM source_performance WHERE entity_id='bear'")
    got = {r["horizon"]: r["rolling_accuracy"] for r in await cur.fetchall()}
    assert got == {"24h": 1.0, "5d": 1.0}, "a downgrade is right when the price falls"
    await db.close_db()


async def test_missing_horizon_price_is_skipped_not_counted_as_a_loss():
    await db.init_db()
    await _alert("partial", 100.0, 110.0, None)
    await compute_source_performance_live()
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT horizon FROM source_performance WHERE entity_id='partial'")
    assert [r["horizon"] for r in await cur.fetchall()] == ["24h"]
    await db.close_db()


# --- the safety property ----------------------------------------------------

async def test_filling_the_table_leaves_live_readers_cold():
    """The whole design in one test: the producer writes a strong track record,
    and every live reader still sees nothing, so no alert can change."""
    await db.init_db()
    for _ in range(20):
        await _alert("star", 100.0, 110.0, 120.0)
    await compute_source_performance_live()

    assert db.analyst_horizon() == "1h"
    assert await db.get_analyst_precision("star") is None
    assert await db.get_analyst_precision_lb("star", min_n=10) is None
    await db.close_db()


async def test_flipping_the_flag_is_what_turns_the_data_on(monkeypatch):
    await db.init_db()
    for _ in range(20):
        await _alert("star", 100.0, 110.0, 120.0)
    await compute_source_performance_live()

    real = config.get
    monkeypatch.setattr(config, "get", lambda k, d=None:
                        True if k == "scoring.analyst_accuracy_weight.enabled" else real(k, d))
    assert db.analyst_horizon() == "24h"
    assert await db.get_analyst_precision("star") == 1.0
    lb = await db.get_analyst_precision_lb("star", min_n=10)
    assert lb is not None and 0.0 < lb <= 1.0
    await db.close_db()


async def test_consolidation_prior_stays_cold_start_after_the_table_fills():
    """The read in consolidation.py had NO horizon filter: any row at any horizon
    would have warmed the consensus-boost path and moved live alerts."""
    await db.init_db()
    await _alert("src", 100.0, 110.0, 120.0)
    await compute_source_performance_live()
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT rolling_accuracy FROM source_performance WHERE entity_id=? AND horizon=? LIMIT 1",
        ("src", db.analyst_horizon()),
    )
    assert await cur.fetchone() is None, "prior must stay cold while the flag is off"
    await db.close_db()


# --- 5d outcome fill --------------------------------------------------------

async def test_5d_query_ignores_the_upper_age_bound_when_asked():
    """1h/24h read a live spot price, so ancient rows are unfillable. The 5d fill
    reads historical bars, so the whole back-catalogue is fair game."""
    await db.init_db()
    conn = await db.get_db()
    await conn.execute(
        """INSERT INTO alert_history (ticker, alerted_at, price_at_alert)
           VALUES ('OLD', ?, 10.0)""", (time.time() - 90 * 86400,))
    await conn.commit()

    bounded = await db.get_alerts_needing_price_update("price_5d_later")
    unbounded = await db.get_alerts_needing_price_update("price_5d_later", ignore_max_age=True)
    assert not any(a["ticker"] == "OLD" for a in bounded)
    assert any(a["ticker"] == "OLD" for a in unbounded)
    await db.close_db()


async def test_update_alert_price_accepts_the_5d_field():
    await db.init_db()
    conn = await db.get_db()
    cur = await conn.execute(
        "INSERT INTO alert_history (ticker, alerted_at, price_at_alert) VALUES ('X', ?, 1.0)",
        (time.time(),))
    await conn.commit()
    await db.update_alert_price(cur.lastrowid, "price_5d_later", 12.5)
    cur2 = await conn.execute("SELECT price_5d_later FROM alert_history WHERE id=?", (cur.lastrowid,))
    assert (await cur2.fetchone())["price_5d_later"] == 12.5
    await db.close_db()


async def test_update_alert_price_rejects_an_unknown_field():
    await db.init_db()
    await db.update_alert_price(1, "price_99d_later; DROP TABLE alert_history", 1.0)
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) c FROM alert_history")
    assert (await cur.fetchone())["c"] >= 0   # table still exists
    await db.close_db()
