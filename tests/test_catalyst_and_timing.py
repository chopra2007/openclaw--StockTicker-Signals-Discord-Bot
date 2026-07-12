"""#55 catalyst grading + #20 confluence-timing gate.

The load-bearing property in both features is the SAFEGUARD, not the happy path:
  * BHAR is a short-term statistic and must be structurally unable to grade a long bet.
  * Empirical-Bayes shrinkage must never touch the analyst promotion gate.
  * The timing gate must be byte-identical to today's behaviour while its flag is OFF.
  * Two sources reading the same order book must not count as two agreeing sources.
"""

import pytest

from consensus_engine.analysis import benchmark_grading as bg
from consensus_engine.analysis import wolf_confluence as wc
from consensus_engine.db import eb_shrink


# ── fixtures ────────────────────────────────────────────────────────────────

def _bars(daily_pct: float, n: int = 130) -> dict[str, float]:
    """A synthetic price series compounding daily_pct per session."""
    out, price = {}, 100.0
    for i in range(n):
        # Plain sequential 'sessions': the grader walks bar indexes, not the calendar.
        out[f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}"] = price
        price *= 1.0 + daily_pct
    return out


ENTRY = "2026-01-01"
STOCK_UP = _bars(0.004)     # outruns...
BENCH_UP = _bars(0.001)     # ...its benchmark
STOCK_DOWN = _bars(-0.003)


# ── #55: BHAR scope is enforced in code, not by convention ──────────────────

def test_bhar_refuses_a_long_horizon_window():
    """A future edit that wires BHAR into the 90-day path must FAIL, not silently ship."""
    with pytest.raises(ValueError):
        bg.buy_and_hold_abnormal_return(STOCK_UP, BENCH_UP, ENTRY, 60)


def test_long_term_function_refuses_a_bhar_window():
    with pytest.raises(ValueError):
        bg.checkpoint_excess_return(STOCK_UP, BENCH_UP, ENTRY, bg.BHAR_WINDOW_DAYS)


def test_bhar_is_benchmark_relative_not_raw():
    """The whole point of #55: rising with your sector is not a win."""
    bhar = bg.buy_and_hold_abnormal_return(STOCK_UP, STOCK_UP, ENTRY, 21)
    assert bhar == pytest.approx(0.0, abs=1e-9)   # stock IS its benchmark -> zero edge
    assert bg.directional_win(bhar, "long") == 0  # ...and therefore NOT a win

    beat = bg.buy_and_hold_abnormal_return(STOCK_UP, BENCH_UP, ENTRY, 21)
    assert beat > 0
    assert bg.directional_win(beat, "long") == 1


def test_short_call_wins_when_the_stock_lags_its_sector():
    bhar = bg.buy_and_hold_abnormal_return(STOCK_DOWN, BENCH_UP, ENTRY, 21)
    assert bhar < 0
    assert bg.directional_win(bhar, "short") == 1
    assert bg.directional_win(bhar, "long") == 0


def test_window_still_open_is_ungraded_not_a_loss():
    short_series = {f"2026-01-{d:02d}": 100.0 for d in range(1, 5)}
    bhar = bg.buy_and_hold_abnormal_return(short_series, short_series, ENTRY, 21)
    assert bhar is None
    assert bg.directional_win(bhar, "long") is None   # None, never 0


def test_unresolvable_ticker_is_skipped_not_guessed():
    assert bg.resolve_benchmark("ZZZZ") is None      # -> caller skips the post
    assert bg.resolve_benchmark("NVDA") == "SMH"     # sub-industry beats broad sector
    assert bg.resolve_benchmark("AAPL") == "XLK"


# ── #55: EB shrinkage pulls thin records toward the pack ────────────────────

def test_shrinkage_lands_between_raw_rate_and_pooled_mean():
    pooled_mean, pooled_var = 0.50, 0.01
    thin = eb_shrink(wins=3, n=5, pooled_mean=pooled_mean, pooled_var=pooled_var)
    assert pooled_mean < thin < 0.60          # 3/5 = 0.60 raw, pulled toward 0.50

    fat = eb_shrink(wins=60, n=100, pooled_mean=pooled_mean, pooled_var=pooled_var)
    assert abs(fat - 0.60) < abs(thin - 0.60)  # a fat record barely moves


# ── #20: the timing gate ───────────────────────────────────────────────────

THESIS = {"scope_type": "stock", "scope_key": "NVDA", "direction": "bull", "has_levels": 1}


def _rows(**by_source):
    return {k: [{"ticker": "NVDA", "dir": d} for d in dirs] for k, dirs in by_source.items()}


def test_independence_collapse_same_order_book_is_one_vote():
    """Options flow + the Schwab chain snapshot read the SAME order book. Four bullish
    rows across the two are ONE agreeing family, not two — this is the double-count guard."""
    rows = _rows(options=["long", "long"], schwab_options=["long", "long"])
    verdict, bucket_agree, fast_agree, buckets = wc.score_timing(THESIS, rows)

    assert bucket_agree == 1                     # ...not 2, and certainly not 4
    assert [b.bucket for b in buckets] == ["options"]
    assert sorted(buckets[0].sources) == ["options", "schwab_options"]
    assert buckets[0].n_rows == 4                # all four rows fed the single vote
    assert verdict == "wait"                     # one family agreeing is not a green light


def test_insider_sources_also_collapse_to_one_family():
    rows = _rows(sec=["bullish"], form4=["bullish"])
    _, bucket_agree, _, buckets = wc.score_timing(THESIS, rows)
    assert bucket_agree == 1
    assert buckets[0].bucket == "insider"


def test_act_needs_two_independent_families_and_one_fast_mover():
    rows = _rows(twitter=["long", "long"], options=["long"])
    verdict, bucket_agree, fast_agree, _ = wc.score_timing(THESIS, rows)
    assert (verdict, bucket_agree, fast_agree) == ("act", 2, 2)


def test_slow_only_agreement_never_says_act():
    """SEC + YouTube may both be right, but neither says the move is happening NOW."""
    rows = _rows(sec=["bullish"], youtube=["long"])
    verdict, bucket_agree, fast_agree, _ = wc.score_timing(THESIS, rows)
    assert bucket_agree == 2 and fast_agree == 0
    assert verdict == "wait"          # two families, but nobody fast -> a thesis, not a trade


def test_no_agreement_is_none():
    verdict, bucket_agree, _, _ = wc.score_timing(THESIS, _rows(twitter=["short"]))
    assert (verdict, bucket_agree) == ("none", 0)


def test_internally_mixed_family_abstains():
    """A family that cannot make up its own mind casts no vote at all."""
    rows = _rows(twitter=["long", "short"], options=["long"])
    verdict, bucket_agree, _, buckets = wc.score_timing(THESIS, rows)
    assert [b.bucket for b in buckets] == ["options"]
    assert (verdict, bucket_agree) == ("wait", 1)


# ── #20: flag OFF must change nothing ──────────────────────────────────────

def test_timing_flag_off_is_byte_identical(monkeypatch):
    """With collect OFF, score_confluence returns exactly what it returns today: the
    timing fields sit at their empty defaults and the tier is untouched."""
    from consensus_engine import config as cfg
    real_get = cfg.get
    monkeypatch.setattr(cfg, "get", lambda k, d=None: False if k.startswith(
        "wolf.confluence.timing") else real_get(k, d))

    rows = _rows(twitter=["long", "long"], options=["long"], sec=["bullish"])
    res = wc.score_confluence(THESIS, rows)

    assert res.timing_verdict == "none"
    assert res.timing_bucket_agree == 0 and res.timing_fast_agree == 0
    assert res.timing_buckets == []
    assert res.tier == "critical"       # the EXISTING ladder, unchanged by #20


def test_collect_on_records_verdict_without_touching_the_tier(monkeypatch):
    """The shipped default: verdict computed and stored, alerts byte-identical."""
    from consensus_engine import config as cfg
    real_get = cfg.get

    def fake(k, d=None):
        if k == "wolf.confluence.timing.collect":
            return True
        if k == "wolf.confluence.timing.enabled":
            return False
        return real_get(k, d)
    monkeypatch.setattr(cfg, "get", fake)

    rows = _rows(twitter=["long"], options=["long"])
    res = wc.score_confluence(THESIS, rows)

    assert res.timing_verdict == "act"          # the shadow verdict IS recorded...
    off_tier = res.tier

    monkeypatch.setattr(cfg, "get", lambda k, d=None: real_get(k, d) if not k.startswith(
        "wolf.confluence.timing") else False)
    assert wc.score_confluence(THESIS, rows).tier == off_tier   # ...and changed no tier


def test_enabled_lets_an_act_verdict_escalate_one_notch(monkeypatch):
    """Only when the gate is switched ON (after the backtest) may it raise the alert."""
    from consensus_engine import config as cfg
    real_get = cfg.get
    monkeypatch.setattr(cfg, "get", lambda k, d=None: True if k.startswith(
        "wolf.confluence.timing") else real_get(k, d))

    # One agreeing legacy source + levels = 'high' today; an 'act' verdict lifts it to critical.
    rows = _rows(twitter=["long"], options=["long"])
    res = wc.score_confluence(THESIS, rows)
    assert res.timing_verdict == "act"
    assert res.tier == "critical"
