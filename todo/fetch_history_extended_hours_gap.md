# fetch_history() silently drops the extended-hours flag

**Status:** DONE
**Created:** 2026-08-23

**CURRENT STATUS (2026-08-23):** Fixed and committed (671e3df). `fetch_history()` now takes
`extended_hours: bool = False` and forwards it to `schwab_client.get_price_history()` and to
yfinance's `prepost` flag. Verified with unit tests for both paths, a real Schwab call (SPY
5d/5m: 1306 bars extended vs 390 regular, extended run starting hours before the 9:30am open),
the full pytest suite, and a live `!all SPY` in Discord after restarting the engine.

## What's wrong

`consensus_engine/scanners/schwab_client.py`'s `get_price_history()` takes an `extended_hours`
parameter (added on purpose per commit `c4b0cbd`, "Parameterize the extended-hours flag on
get_price_history") that includes premarket/after-hours bars when `True`.

`consensus_engine/utils/prices.py`'s `fetch_history()` — the shared wrapper most other code
calls instead of hitting `schwab_client` directly — has no `extended_hours` parameter at all:

```python
def fetch_history(ticker: str, *, period=None, start=None, end=None, interval: str = "1d"):
```

Any caller that goes through this wrapper wanting premarket bars silently gets regular-session-only
data back instead — no error, no warning, just fewer/different bars than expected. The bug is a
missing pass-through, not a crash, so it's easy to not notice.

## Why it matters

- Confirmed no current production caller needs extended-hours data through this wrapper *today* —
  this session's research scripts worked around it by calling `schwab_client.get_price_history()`
  directly, per the audit note in `.omc/research/event-reaction-short-duration/briefing.md`.
- But it's a trap for the next feature that needs premarket bars and reaches for the "normal"
  helper (`fetch_history`) instead of knowing to bypass it — exactly the shape of bug that costs a
  debugging session later ("why is my premarket volume always zero/wrong") rather than failing loud.

## Fix

Add `extended_hours: bool = False` to `fetch_history()`'s signature and pass it through to
`schwab_client.get_price_history()` (default `False` preserves current behavior for every existing
caller). Small, low-risk change — the risk is only in not doing it before the next feature trips
over it.

## Files involved

- `consensus_engine/utils/prices.py` — `fetch_history()`, missing the parameter
- `consensus_engine/scanners/schwab_client.py:546` — `get_price_history()`, already supports it
