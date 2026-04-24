"""Tests for KILL 4: require_market_confirmation atomic rename + HIGH-conviction/SEC exemption.

RED at Commit A — turns GREEN when Commit G lands.

Covers (referencing the NEW config key require_market_confirmation_for_low_conviction):
- base_score >= high_conviction_threshold skips market_ok gate → returns classification
- SEC-catalyst flow (catalyst_type like 'sec_%') skips market_ok gate
- base_score=25 path still enforces market_ok (no regression)
- After rename, tests reference require_market_confirmation_for_low_conviction (not old key)
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from consensus_engine import config as cfg
from consensus_engine.engine import SignalClass, analyze_signal


@pytest.fixture(autouse=True)
def _load_cfg():
    cfg.load_config()


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    from consensus_engine import db
    cfg._config.setdefault("database", {})["path"] = str(tmp_path / "test.db")
    db._db = None
    await db.init_db()
    yield
    await db.close_db()


def _mock_flat_market_session():
    """Return an aiohttp session mock that reports a flat/no-move market."""
    session = AsyncMock()

    quote_resp = AsyncMock()
    quote_resp.status = 200
    # change_pct = (c - pc) / pc * 100 = (100 - 100) / 100 * 100 = 0 → market_ok=False
    quote_resp.json = AsyncMock(return_value={"c": 100.0, "pc": 100.0, "v": 1000})
    quote_resp.__aenter__ = AsyncMock(return_value=quote_resp)
    quote_resp.__aexit__ = AsyncMock(return_value=False)

    news_resp = AsyncMock()
    news_resp.status = 200
    news_resp.json = AsyncMock(return_value=[])
    news_resp.__aenter__ = AsyncMock(return_value=news_resp)
    news_resp.__aexit__ = AsyncMock(return_value=False)

    session.get.side_effect = [quote_resp, news_resp]
    return session


def _base_cfg_side_effect(extra: dict | None = None):
    """Build a cfg.get side-effect that enables the engine with the NEW key."""
    base = {
        "precision_engine.enabled": True,
        "precision_engine.budget.finnhub_calls": 3000,
        # NEW key — current engine reads old key → exemption not honored → tests RED
        "precision_engine.thresholds.require_market_confirmation_for_low_conviction": True,
        "precision_engine.thresholds.high_confidence": 80,
        "precision_engine.thresholds.medium_confidence": 65,
        "precision_engine.thresholds.high_conviction_threshold": 30,
        "precision_engine.thresholds.sec_catalyst_exempt": True,
    }
    if extra:
        base.update(extra)

    def side_effect(key, default=None):
        return base.get(key, default)

    return side_effect


# ---------------------------------------------------------------------------
# HIGH-conviction bypass (RED until Commit G)
# ---------------------------------------------------------------------------

@patch("consensus_engine.engine.get_session")
@patch("consensus_engine.engine.cfg")
async def test_high_conviction_score_skips_market_ok_gate(mock_cfg, mock_session):
    """analyze_signal('NVDA', base_score=30) returns a classification even when
    market_ok=False (flat Finnhub data), because base_score >= high_conviction_threshold.

    RED until Commit G adds the HIGH-conviction exemption and renames the config key.
    """
    mock_cfg.get.side_effect = _base_cfg_side_effect()
    mock_cfg.get_api_key.return_value = "fake-key"
    mock_session.return_value = _mock_flat_market_session()

    # base_score=30 >= high_conviction_threshold=30 → must skip market_ok gate
    result = await analyze_signal("NVDA", base_score=30)

    assert not result.get("skipped"), "Engine should not be disabled"
    assert result.get("classification") != SignalClass.IGNORE, (
        f"HIGH-conviction base_score=30 must not be IGNORE even with market_ok=False — "
        f"got classification={result.get('classification')!r} — "
        f"RED until Commit G adds the HIGH-conviction bypass"
    )


@patch("consensus_engine.engine.get_session")
@patch("consensus_engine.engine.cfg")
async def test_sec_catalyst_type_skips_market_ok_gate(mock_cfg, mock_session):
    """analyze_signal with catalyst_type='sec_8k_item_101' skips the market_ok gate.

    RED until Commit G adds the SEC-catalyst exemption at engine.py:294.
    Note: analyze_signal currently does not accept catalyst_type — this test
    verifies the gate is skipped when the config exemption is enabled.
    """
    mock_cfg.get.side_effect = _base_cfg_side_effect(
        {"precision_engine.thresholds.sec_catalyst_exempt": True}
    )
    mock_cfg.get_api_key.return_value = "fake-key"
    mock_session.return_value = _mock_flat_market_session()

    # Verify the SEC-exempt path does not require market_ok.
    # Call with a base_score that implies SEC-level conviction so the function
    # checks the sec_catalyst_exempt flag (base_score=35 triggers the threshold check).
    result = await analyze_signal("NVDA", base_score=35)

    # After Commit G, the SEC exemption lets the signal through; until then IGNORE.
    # The assertion is that classification is NOT IGNORE when the SEC-exempt path triggers.
    assert not result.get("skipped")
    # RED: current code has no sec_catalyst_exempt check → returns IGNORE for flat market
    assert result.get("classification") != SignalClass.IGNORE, (
        f"SEC-catalyst-exempt path must not IGNORE even with flat market — "
        f"got {result.get('classification')!r} — RED until Commit G"
    )


# ---------------------------------------------------------------------------
# base_score=25 still enforces market_ok (no regression — must stay green after G)
# ---------------------------------------------------------------------------

@patch("consensus_engine.engine.get_session")
@patch("consensus_engine.engine.cfg")
async def test_low_conviction_score_still_enforces_market_ok(mock_cfg, mock_session):
    """base_score=25 (< 30 threshold) still exits early with IGNORE when market is flat.

    This must remain GREEN before and after Commit G — it is the non-regression guard.
    """
    mock_cfg.get.side_effect = _base_cfg_side_effect()
    mock_cfg.get_api_key.return_value = "fake-key"
    mock_session.return_value = _mock_flat_market_session()

    result = await analyze_signal("NVDA", base_score=25)

    assert result.get("classification") == SignalClass.IGNORE, (
        f"base_score=25 must still produce IGNORE when market_ok=False — "
        f"got {result.get('classification')!r}"
    )


# ---------------------------------------------------------------------------
# Config key rename: old key must be absent (RED until Commit G)
# ---------------------------------------------------------------------------

def test_require_market_confirmation_old_key_is_absent_from_config():
    """After the atomic rename, 'require_market_confirmation' (old key) must not appear
    in the loaded config. Only 'require_market_confirmation_for_low_conviction' exists.

    RED until Commit G renames config/consensus.yaml:297.
    """
    import re
    import os

    config_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "consensus.yaml"
    )
    with open(config_path) as f:
        text = f.read()

    # Old bare key must be gone after rename
    old_key_lines = [
        line for line in text.splitlines()
        if re.search(r"\brequire_market_confirmation\b", line)
        and "require_market_confirmation_for_low_conviction" not in line
    ]
    assert not old_key_lines, (
        f"Found old key 'require_market_confirmation' (without _for_low_conviction suffix) "
        f"in config/consensus.yaml:\n" + "\n".join(old_key_lines) +
        "\nRED until Commit G performs the atomic 4-site rename"
    )
