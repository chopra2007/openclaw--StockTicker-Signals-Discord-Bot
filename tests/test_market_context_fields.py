"""#47 "better way" — `!market` descriptive market-context fields.

Verifies `_build_market_context_fields` surfaces the FRESH engine-native signals
(Wolf market theses + cross-source confluence, then the volatility regime) as
component-first DESCRIPTIVE context — and NEVER as a fused composite "risk score"
(the cross-model + adversarial gate's hard requirement: a composite would launder
the proven-NO-GO quant gauges into an implied prediction).
"""
import time

import pytest

from consensus_engine.alerts.commands import _build_market_context_fields


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    import consensus_engine.db as db_module
    db_module.DB_PATH = str(tmp_path / "test.db")
    db_module._db = None
    await db_module.init_db()
    yield
    await db_module.close_db()
    db_module._db = None
    db_module.DB_PATH = None


async def _seed_market(direction_rows, regime_label=None):
    """direction_rows: list of (scope_key, direction, stage, agree, disagree)."""
    import consensus_engine.db as db_module
    conn = await db_module.get_db()
    now = time.time()
    for i, (scope_key, direction, stage, agree, disagree) in enumerate(direction_rows, start=1):
        await conn.execute(
            """INSERT INTO macro_theses
               (id, scope_type, scope_key, direction, stage, created_at, last_updated, status)
               VALUES (?, 'market', ?, ?, ?, ?, ?, 'active')""",
            (i, scope_key, direction, stage, now, now),
        )
        await conn.execute(
            """INSERT INTO wolf_confluence_checks
               (thesis_id, scope_type, scope_key, direction, checked_at, window_days,
                agree_count, disagree_count)
               VALUES (?, 'market', ?, ?, ?, 21, ?, ?)""",
            (i, scope_key, direction, now, agree, disagree),
        )
    if regime_label is not None:
        await conn.execute(
            """INSERT INTO regime_daily
               (date_utc, realized_vol_20d, mean_252d, std_252d, z_score_raw,
                z_score_smoothed, regime_label, computed_at)
               VALUES ('2026-06-26', 0.12, 0.10, 0.03, 0.7, 0.66, ?, ?)""",
            (regime_label, now),
        )
    await conn.commit()


async def test_wolf_and_regime_render_component_first():
    await _seed_market(
        [("SPX", "bear", "imminent", 0, 2),   # divided
         ("NVDA?ignored", "bull", "forming", 2, 0)],  # agree (still a market row here)
        regime_label="elevated",
    )
    fields = await _build_market_context_fields()

    # component-first: Wolf and regime are SEPARATE fields, not one fused score
    assert len(fields) == 2
    wolf = fields[0]["value"]
    assert "SPX" in wolf
    assert "analysts divided" in wolf           # disagree>agree path
    assert "other source(s) agree" in wolf       # agree path
    assert "A view, not a forecast" in fields[0]["value"]

    regime = fields[1]
    assert "Volatility regime" in regime["name"]
    assert "elevated" in regime["value"]


async def test_no_composite_score_string_anywhere():
    """The hard honesty invariant: never a single fused 'N/100' or 'risk score'."""
    await _seed_market([("SPX", "bear", "imminent", 0, 2)], regime_label="normal")
    fields = await _build_market_context_fields()
    blob = " ".join(f["name"] + " " + f["value"] for f in fields).lower()
    assert "/100" not in blob
    assert "risk score" not in blob
    assert "score:" not in blob


async def test_empty_state_returns_no_fields():
    """No active market theses + no regime row → no context fields (no fake content)."""
    fields = await _build_market_context_fields()
    assert fields == []


async def test_bear_is_hazard_framed_not_a_sell_call():
    await _seed_market([("NDX", "bear", "imminent", 0, 0)])
    fields = await _build_market_context_fields()
    wolf = fields[0]["value"].lower()
    assert "top / downside risk" in wolf
    assert "sell" not in wolf   # hazard framing, never an order
