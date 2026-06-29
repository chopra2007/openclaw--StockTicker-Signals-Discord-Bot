"""C7 (reliability-hardening): vectorize the O(strikes^2) max-pain payout with
numpy (C ops release the GIL) AND move the math INTO the executor thread so it
no longer runs on the event loop after the fetch returns.

Equivalence is mandatory: `_ref_max_pain` below is an exact copy of the
pre-C7 pure-Python algorithm. The numpy result MUST equal it on realistic
chains AND the edge cases (payout-ties, duplicate strikes, NaN OI, empty,
<2-strike). Integer strikes/OI are used for the tie cases so payouts are exact
in float64 and the tiebreak is deterministic in both implementations."""
import sys
import threading
import types
from types import SimpleNamespace

import pandas as pd
import pytest

from consensus_engine.scanners import options


def _ref_max_pain(chain):
    """Exact copy of the pre-C7 pure-Python max-pain algorithm (the oracle)."""
    calls, puts = chain.calls, chain.puts
    call_oi, put_oi = {}, {}
    for df, dst in ((calls, call_oi), (puts, put_oi)):
        if df is None or getattr(df, "empty", True):
            continue
        for _, row in df.iterrows():
            k = row.get("strike")
            oi = row.get("openInterest")
            try:
                k = float(k)
                oi = float(oi) if oi == oi else 0.0
            except (TypeError, ValueError):
                continue
            if k <= 0:
                continue
            dst[k] = dst.get(k, 0.0) + max(0.0, oi)
    strikes = sorted(set(call_oi) | set(put_oi))
    total_oi = sum(call_oi.values()) + sum(put_oi.values())
    if len(strikes) < 2 or total_oi <= 0:
        return None
    mid = strikes[len(strikes) // 2]

    def payout(S):
        tot = 0.0
        for k, oi in call_oi.items():
            if S > k:
                tot += (S - k) * oi
        for k, oi in put_oi.items():
            if k > S:
                tot += (k - S) * oi
        return tot

    best = min(strikes, key=lambda S: (payout(S), abs(S - mid)))
    return best, total_oi, sum(call_oi.values()), sum(put_oi.values())


def _chain(calls_rows, puts_rows):
    calls = pd.DataFrame(calls_rows) if calls_rows else pd.DataFrame()
    puts = pd.DataFrame(puts_rows) if puts_rows else pd.DataFrame()
    return SimpleNamespace(calls=calls, puts=puts)


def _c(strike, oi):
    return {"strike": strike, "openInterest": oi}


@pytest.mark.parametrize("name,chain", [
    ("realistic", _chain(
        [_c(90, 1200), _c(95, 3400), _c(100, 8800), _c(105, 2100), _c(110, 900)],
        [_c(90, 2600), _c(95, 4100), _c(100, 5200), _c(105, 1500), _c(110, 700)])),
    ("payout_tie_symmetric", _chain(
        [_c(100, 1000), _c(110, 1000)],
        [_c(100, 1000), _c(110, 1000)])),
    ("duplicate_strikes", _chain(
        [_c(100, 500), _c(100, 700), _c(105, 300)],
        [_c(100, 200), _c(105, 400), _c(105, 100)])),
    ("nan_oi", _chain(
        [_c(100, float("nan")), _c(105, 800), _c(110, 600)],
        [_c(100, 400), _c(105, float("nan")), _c(110, 300)])),
    ("half_strikes", _chain(
        [_c(99.5, 1000), _c(100.0, 2000), _c(100.5, 1500)],
        [_c(99.5, 800), _c(100.0, 1200), _c(100.5, 900)])),
])
def test_numpy_equals_reference(name, chain):
    assert options._max_pain_for_chain(chain) == _ref_max_pain(chain), \
        f"numpy max-pain diverged from the reference on '{name}'"


def test_tie_resolves_to_nearest_mid_deterministically():
    """C7: on a payout tie the strike NEAREST the mid wins, deterministically --
    independent of input row order. The vectorized path regroups the float
    summation vs the old per-strike loop, so on a ~1-ULP tie the two MAY pick a
    different equidistant strike; what is guaranteed (and tested here) is that
    the vectorized result is order-stable and applies the documented distance
    tiebreak. Enrichment only -- max-pain never gates an alert."""
    chain = _chain([_c(100, 1000), _c(110, 1000)], [_c(100, 1000), _c(110, 1000)])
    # mid = strikes[2//2] = 110; payout(100) == payout(110) == 10000 -> dist wins.
    assert options._max_pain_for_chain(chain)[0] == 110.0
    rev = _chain([_c(110, 1000), _c(100, 1000)], [_c(110, 1000), _c(100, 1000)])
    assert options._max_pain_for_chain(rev)[0] == 110.0, "winner must not depend on row order"


def test_empty_and_single_strike_return_none():
    assert options._max_pain_for_chain(_chain([], [])) is None
    assert options._max_pain_for_chain(_chain([_c(100, 500)], [])) is None
    assert options._max_pain_for_chain(_chain([_c(0, 500), _c(-5, 100)], [])) is None  # k<=0 dropped


# ---- C7 part 2: the math must run in the executor thread, not the loop ----

class _FakeTicker:
    fast_info = None
    options = ("2026-07-03",)

    def option_chain(self, e):
        calls = pd.DataFrame([_c(95, 1000), _c(100, 5000), _c(105, 1200)])
        puts = pd.DataFrame([_c(95, 1500), _c(100, 4000), _c(105, 900)])
        return SimpleNamespace(calls=calls, puts=puts)


async def test_max_pain_runs_in_executor(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance",
                        types.SimpleNamespace(Ticker=lambda t: _FakeTicker()))
    seen_threads = []
    real = options._max_pain_for_chain

    def spy(chain):
        seen_threads.append(threading.current_thread().name)
        return real(chain)

    monkeypatch.setattr(options, "_max_pain_for_chain", spy)
    result = await options.compute_max_pain("AAPL", None)
    assert result is not None
    assert seen_threads, "max-pain should have been computed"
    assert all(t != "MainThread" for t in seen_threads), \
        f"max-pain must run in the executor thread, not the event loop; ran on {seen_threads}"
