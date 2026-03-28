"""Backtest script — replay sample tweets through quality gate and ticker filtering.

Measures false positive reduction by running tweets through:
  1. extract_tickers()      — ticker extraction
  2. _fallback_parse()      — regex-based classification (no LLM)
  3. _passes_quality_gate() — pre-alert quality check

Usage:
    python3 backtest.py
"""

import sys
import os

# Ensure the workspace is on sys.path so consensus_engine imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from consensus_engine.utils.tickers import extract_tickers, is_valid_ticker
from consensus_engine.analysis.tweet_parser import _fallback_parse
from consensus_engine.main import _passes_quality_gate

# ---------------------------------------------------------------------------
# Sample tweets
# ---------------------------------------------------------------------------

SAMPLE_TWEETS = [
    # --- Real trade callouts (should pass) ---
    ("Buying $NVDA here, looks great setup on daily", True),
    ("Going long $TSLA 500c Friday, loaded up", True),
    ("$AAPL breaking out above resistance, adding to my position", True),
    ("Bought $AMD calls this morning, earnings play", True),
    ("Short $RIVN here, dead cat bounce, puts loaded", True),
    ("$SMCI looking strong, bought shares at open", True),

    # --- False positives that should be blocked ---
    ("RSI oversold on everything, be patient", False),
    ("Life is about patience and discipline", False),
    ("MACD crossing, EMA death cross forming", False),
    ("The market is weak today be careful", False),
    ("DTE looking interesting", False),  # DTE = days to expiry, blacklisted
    ("Good morning everyone, let's have a great day", False),
    ("Volume drying up across the board, waiting for catalyst", False),

    # --- Edge cases ---
    ("$AAPL RSI at 30, buying the dip", True),  # Should extract AAPL only, not RSI
    ("Short $TSLA here, death cross on daily", True),  # Should extract TSLA, not false-flag on "death cross"
    ("$MARA and $RIOT running with BTC today", True),  # Multiple tickers
    ("NVDA TSLA AMD all looking bullish today", True),  # Plain tickers no $

    # --- Low conviction neutral (should be blocked) ---
    ("Interesting times ahead", False),
    ("Watching the market closely", False),
    ("Might look at some names later", False),
]

# ---------------------------------------------------------------------------
# Run backtest
# ---------------------------------------------------------------------------

def run_backtest():
    results = []

    for tweet_text, expected_pass in SAMPLE_TWEETS:
        # 1. Extract tickers
        tickers = extract_tickers(tweet_text)

        # 2. Fallback parse (no LLM)
        parsed = _fallback_parse(
            url="https://x.com/test/status/123",
            analyst="test_analyst",
            text=tweet_text,
        )

        # 3. Quality gate — check first ticker (or synthetic empty)
        first_ticker = parsed.tickers[0] if parsed.tickers else ""
        gate_pass = _passes_quality_gate(parsed, first_ticker) if first_ticker else False

        results.append({
            "text": tweet_text,
            "tickers": sorted(tickers),
            "parsed_tickers": parsed.tickers,
            "type": parsed.tweet_type.value,
            "conviction": parsed.conviction.value,
            "direction": parsed.direction.value,
            "base_score": parsed.base_score,
            "gate_pass": gate_pass,
            "expected": expected_pass,
            "correct": gate_pass == expected_pass,
        })

    # ---------------------------------------------------------------------------
    # Print summary table
    # ---------------------------------------------------------------------------

    hdr = f"{'#':>2}  {'Tweet (truncated)':<50}  {'Tickers':<18}  {'Type':>4}  {'Conv':>6}  {'Dir':>7}  {'Score':>5}  {'Gate':>6}  {'Exp':>5}  {'OK':>3}"
    sep = "-" * len(hdr)

    print()
    print("=" * len(hdr))
    print("  OpenClaw Backtest — Quality Gate & Ticker Filter")
    print("=" * len(hdr))
    print()
    print(hdr)
    print(sep)

    for i, r in enumerate(results, 1):
        trunc = r["text"][:48] + (".." if len(r["text"]) > 48 else "")
        tick_str = ", ".join(r["tickers"])[:16] or "(none)"
        gate_label = "PASS" if r["gate_pass"] else "BLOCK"
        exp_label = "PASS" if r["expected"] else "BLOCK"
        ok_label = "Y" if r["correct"] else "N !!!"
        print(
            f"{i:>2}  {trunc:<50}  {tick_str:<18}  {r['type']:>4}  {r['conviction']:>6}  {r['direction']:>7}  {r['base_score']:>5}  {gate_label:>6}  {exp_label:>5}  {ok_label:>3}"
        )

    print(sep)

    # ---------------------------------------------------------------------------
    # Stats
    # ---------------------------------------------------------------------------

    total = len(results)
    would_alert = sum(1 for r in results if r["gate_pass"])
    blocked = total - would_alert
    expected_block = sum(1 for r in results if not r["expected"])
    correctly_blocked = sum(1 for r in results if not r["gate_pass"] and not r["expected"])
    false_positives_remaining = sum(1 for r in results if r["gate_pass"] and not r["expected"])
    correct_count = sum(1 for r in results if r["correct"])

    print()
    print("Stats:")
    print(f"  Total tweets:              {total}")
    print(f"  Would alert (gate pass):   {would_alert}")
    print(f"  Blocked (gate fail):       {blocked}")
    print(f"  Expected to block:         {expected_block}")
    print(f"  Correctly blocked:         {correctly_blocked}/{expected_block}")
    print(f"  False positives remaining: {false_positives_remaining}")
    fp_reduction = (correctly_blocked / expected_block * 100) if expected_block > 0 else 0
    print(f"  False positive reduction:  {fp_reduction:.0f}%")
    print(f"  Overall accuracy:          {correct_count}/{total} ({correct_count/total*100:.0f}%)")
    print()


if __name__ == "__main__":
    run_backtest()
