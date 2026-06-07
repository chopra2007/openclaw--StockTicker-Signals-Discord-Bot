"""Wolf trade-idea rendering + relabeled levels (the #news 'Trade idea' / 'Key levels' field).

Covers the BTC example the user specified:
  Trade idea: short a re-test of $74,192 → $70k / SL above $74,200
  Key levels (no setup): 74,192 (resistance) · 70,000 (target)
"""
import json

from consensus_engine.alerts import wolf_news as wn
from consensus_engine.analysis.wolf_email_parser import _coerce_thesis


# ---- formatting helpers -------------------------------------------------

def test_money_formats():
    assert wn._money(74192) == "$74,192"
    assert wn._money(74200) == "$74,200"
    assert wn._money(152.5) == "$152.50"


def test_money_k_abbreviates_target():
    assert wn._money_k(70000) == "$70k"
    assert wn._money_k(74192) == "$74.2k"
    assert wn._money_k(950) == "$950"


def test_stop_just_beyond_entry():
    assert wn._stop_from_entry(74192, "short") == 74200   # round up, above
    assert wn._stop_from_entry(74192, "long") == 74100    # round down, below


# ---- trade idea ---------------------------------------------------------

def test_trade_idea_exact_btc_spec():
    setup = {"action": "short", "entry": 74192, "target": 70000}
    val = wn._trade_idea_value("bear", setup, [])
    assert val == "short a re-test of $74,192 → $70k\nSL above $74,200"


def test_trade_idea_fills_entry_target_from_levels():
    # setup has no numbers but Wolf framed a short; levels supply entry(high)/target(low)
    setup = {"action": "short", "entry": None, "target": None}
    levels = [{"price": 70000, "role": "support"}, {"price": 74192, "role": "support"}]
    val = wn._trade_idea_value("bear", setup, levels)
    assert val == "short a re-test of $74,192 → $70k\nSL above $74,200"


def test_trade_idea_long_uses_below_stop_and_low_entry():
    setup = {"action": "long", "entry": None, "target": None}
    levels = [{"price": 200, "role": "support"}, {"price": 230, "role": "resistance"}]
    val = wn._trade_idea_value("bull", setup, levels)
    assert val == "long a re-test of $200 → $230\nSL below $199"


def test_no_trade_idea_without_setup():
    assert wn._trade_idea_value("bear", None, [{"price": 74192}]) is None


def test_no_trade_idea_when_no_numbers_anywhere():
    # action but no entry/target and no levels -> can't state a trade
    assert wn._trade_idea_value("bear", {"action": "short", "entry": None, "target": None}, []) is None


# ---- level relabeling ---------------------------------------------------

def test_relabel_bear_two_supports():
    levels = [{"price": 74192, "role": "support"}, {"price": 70000, "role": "support"}]
    out = wn._relabel_levels("bear", levels)
    by_price = {l["price"]: l["role"] for l in out}
    assert by_price[74192] == "resistance"
    assert by_price[70000] == "target"


def test_relabel_bull_two_supports():
    levels = [{"price": 200, "role": "support"}, {"price": 230, "role": "support"}]
    out = wn._relabel_levels("bull", levels)
    by_price = {l["price"]: l["role"] for l in out}
    assert by_price[200] == "support"
    assert by_price[230] == "target"


def test_relabel_keeps_explicit_roles():
    levels = [{"price": 100, "role": "support"}, {"price": 130, "role": "resistance"}]
    out = wn._relabel_levels("bear", levels)
    by_price = {l["price"]: l["role"] for l in out}
    assert by_price[130] == "resistance"   # explicit kept (not forced)
    assert by_price[100] == "target"       # ambiguous support -> target (bear)


def test_relabel_single_level_unchanged():
    levels = [{"price": 100, "role": "support"}]
    assert wn._relabel_levels("bear", levels) == levels


# ---- the combined field chooser ----------------------------------------

def test_levels_field_prefers_trade_idea():
    row = {"trade_setup_json": json.dumps({"action": "short", "entry": 74192, "target": 70000})}
    f = wn._levels_field("bear", row, [{"price": 74192}, {"price": 70000}])
    assert f["name"] == "Trade idea"
    assert "short a re-test of $74,192 → $70k" in f["value"]


def test_levels_field_falls_back_to_relabeled_levels():
    row = {"trade_setup_json": None}
    f = wn._levels_field("bear", row, [{"price": 74192, "role": "support"},
                                       {"price": 70000, "role": "support"}])
    assert f["name"] == "Key levels"
    assert f["value"] == "74,192 (resistance) · 70,000 (target)"


# ---- extraction coercion -----------------------------------------------

def _base_raw(**over):
    raw = {"identifier": "BTC", "direction": "bear", "stage": "imminent"}
    raw.update(over)
    return raw


def test_coerce_keeps_setup_matching_direction():
    th = _coerce_thesis(_base_raw(setup={"action": "short", "entry": 74192, "target": 70000}))
    assert th["setup"] == {"action": "short", "entry": 74192.0, "target": 70000.0}


def test_coerce_drops_setup_conflicting_direction():
    # bear thesis but a 'long' setup -> contradiction, dropped
    th = _coerce_thesis(_base_raw(setup={"action": "long", "entry": 74192, "target": 80000}))
    assert th["setup"] is None


def test_coerce_drops_setup_without_numbers():
    th = _coerce_thesis(_base_raw(setup={"action": "short", "entry": None, "target": None}))
    assert th["setup"] is None


# ---- #26 trade-idea guards ---------------------------------------------

def test_trade_idea_rejects_backwards_short():
    # a short must have entry ABOVE target; entry<=target is a parse error → None
    assert wn._trade_idea_value("bear", {"action": "short", "entry": 70000, "target": 74192}, []) is None


def test_trade_idea_accepts_correct_short():
    val = wn._trade_idea_value("bear", {"action": "short", "entry": 74192, "target": 70000}, [])
    assert val == "short a re-test of $74,192 → $70k\nSL above $74,200"


def test_trade_idea_rejects_backwards_long():
    # a long must have entry BELOW target; entry>=target is a parse error → None
    assert wn._trade_idea_value("bull", {"action": "long", "entry": 230, "target": 200}, []) is None


def test_coerce_drops_setup_with_one_sided_price():
    # entry present but no target → not a framed trade (require BOTH)
    th = _coerce_thesis(_base_raw(setup={"action": "short", "entry": 74192, "target": None}))
    assert th["setup"] is None


def test_coerce_drops_setup_with_nonpositive_price():
    # entry 0 is non-positive → dropped (same >0 guard the levels use)
    th = _coerce_thesis(_base_raw(setup={"action": "short", "entry": 0, "target": 70000}))
    assert th["setup"] is None
