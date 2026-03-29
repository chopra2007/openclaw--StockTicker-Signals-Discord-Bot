# OpenClaw Optimization & Proactive Scanners Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 scoring/pipeline bugs and add 5 proactive market scanners (pre-market gaps, SEC 8-K watcher, options sweeps, volume breakouts, earnings calendar) plus Reddit JSON API restoration.

**Architecture:** Existing signal-first pipeline stays intact. Bug fixes touch `cross_reference.py`, `main.py`, `tweet_parser.py`, and `config/consensus.yaml`. New scanners follow the established pattern: background loop in `main.py`, scanner module in `scanners/`, Discord alerts via existing `send_command_reply`. New `!gaps`, `!leaderboard` commands added to `commands.py`.

**Tech Stack:** Python 3.11, asyncio, aiohttp, aiosqlite, yfinance, Finnhub API, SEC EDGAR API, pytest

---

## Phase 1: Quick Wins (Bug Fixes + Reddit)

### Task 1: Remove Double LLM Call in Cross-Reference

**Files:**
- Modify: `consensus_engine/cross_reference.py:118-131`
- Test: `tests/test_cross_reference.py`

- [ ] **Step 1: Write test verifying LLM is called only once when catalyst exists**

Add to `tests/test_cross_reference.py`:

```python
@pytest.mark.asyncio
async def test_llm_called_once_with_real_data():
    """LLM should be called exactly once — with real data after gather, not with nulls."""
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/123",
        analyst="test",
        raw_text="$NVDA breaking out hard",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="NVDA breakout",
    )

    mock_catalyst = CatalystResult(
        ticker="NVDA", catalyst_summary="Earnings beat",
        catalyst_type="Earnings Beat", news_sources=["reuters"],
        source_urls=["https://reuters.com"], confidence=0.8,
    )
    mock_technical = TechnicalResult(
        ticker="NVDA",
        filters=[TechnicalFilter(name="RVOL", value=3.0, threshold="> 2.0x", passed=True)],
        price=100, volume=50000000,
    )

    llm_mock = AsyncMock(return_value=(80.0, "Strong"))

    with patch("consensus_engine.cross_reference._run_news_cascade",
               new_callable=AsyncMock, return_value=mock_catalyst), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new_callable=AsyncMock, return_value=(False, "")), \
         patch("consensus_engine.cross_reference._run_social_check",
               new_callable=AsyncMock, return_value={}), \
         patch("consensus_engine.cross_reference._run_technical",
               new_callable=AsyncMock, return_value=mock_technical), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new_callable=AsyncMock, return_value=[]), \
         patch("consensus_engine.cross_reference._run_llm_score", llm_mock), \
         patch("consensus_engine.cross_reference._run_options_check",
               new_callable=AsyncMock, return_value=None):
        result = await cross_reference("NVDA", tweet)

    # LLM should be called exactly once — with real catalyst+technical data
    assert llm_mock.call_count == 1
    args = llm_mock.call_args
    assert args[0][1] is not None  # catalyst is not None
    assert args[0][2] is not None  # technical is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cross_reference.py::test_llm_called_once_with_real_data -v`
Expected: FAIL — `assert llm_mock.call_count == 1` fails because LLM is called twice (once with nulls in gather, once with real data).

- [ ] **Step 3: Fix the double LLM call**

In `consensus_engine/cross_reference.py`, replace lines 118-131:

```python
    catalyst, (sec_hit, sec_summary), social_data, technical, other_analysts, (llm_score, llm_reasoning), options = \
        await asyncio.gather(
            _run_news_cascade(ticker),
            _run_sec_check(ticker),
            _run_social_check(ticker),
            _run_technical(ticker, direction=direction),
            _run_other_analysts(ticker, exclude_analyst=tweet.analyst),
            _run_llm_score(ticker, None, None),
            _run_options_check(ticker, executor),
        )

    if technical or catalyst:
        llm_score, llm_reasoning = await _run_llm_score(ticker, catalyst, technical)
```

With:

```python
    catalyst, (sec_hit, sec_summary), social_data, technical, other_analysts, options = \
        await asyncio.gather(
            _run_news_cascade(ticker),
            _run_sec_check(ticker),
            _run_social_check(ticker),
            _run_technical(ticker, direction=direction),
            _run_other_analysts(ticker, exclude_analyst=tweet.analyst),
            _run_options_check(ticker, executor),
        )

    llm_score, llm_reasoning = 0.0, ""
    if technical or catalyst:
        llm_score, llm_reasoning = await _run_llm_score(ticker, catalyst, technical)
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `pytest tests/test_cross_reference.py -v`
Expected: ALL PASS (including the new test and the existing `test_cross_reference_with_mocked_sources`)

Note: The existing test patches `_run_llm_score` to return `(75.0, "Strong setup")`. After our change, the gather no longer calls LLM, so the mock will only be called once (from the `if technical or catalyst` branch). But the existing test has `_run_technical` returning None and `_run_news_cascade` returning a catalyst, so LLM will still be called once. The test should still pass because `llm_boost` calculation stays the same.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/cross_reference.py tests/test_cross_reference.py
git commit -m "fix: remove double LLM call in cross-reference — saves API budget + 2-3s latency"
```

---

### Task 2: Fix Quality Gate Threshold for LOW Conviction

**Files:**
- Modify: `config/consensus.yaml:141`
- Modify: `tests/test_quality_gate.py:33-37`

- [ ] **Step 1: Update the quality gate config threshold**

In `config/consensus.yaml`, change line 141:

```yaml
  min_base_score_for_alert: 20  # LOW conviction (20) now passes if direction is explicit
```

- [ ] **Step 2: Update the test to expect LOW+LONG to pass**

In `tests/test_quality_gate.py`, replace `test_quality_gate_allows_low_with_direction`:

```python
def test_quality_gate_allows_low_with_direction():
    """LOW conviction but with a direction should pass (score=20 >= threshold=20)."""
    parsed = _make_parsed(direction=Direction.LONG, conviction=Conviction.LOW)
    assert _passes_quality_gate(parsed, "NVDA") is True
```

- [ ] **Step 3: Run tests to verify all pass**

Run: `pytest tests/test_quality_gate.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add config/consensus.yaml tests/test_quality_gate.py
git commit -m "fix: lower quality gate to 20 — LOW conviction with direction now alerts"
```

---

### Task 3: Cap Analyst Multiplier

**Files:**
- Modify: `consensus_engine/cross_reference.py:132`
- Modify: `config/consensus.yaml`
- Test: `tests/test_cross_reference.py`

- [ ] **Step 1: Write test for analyst cap**

Add to `tests/test_cross_reference.py`:

```python
@pytest.mark.asyncio
async def test_analyst_multiplier_capped():
    """Analyst multiplier should be capped at max_additional_analysts (default 3)."""
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/123",
        analyst="test",
        raw_text="$NVDA breaking out all day",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="NVDA",
    )

    # 10 other analysts mentioning same ticker — should be capped at 3
    ten_analysts = [f"analyst_{i}" for i in range(10)]

    with patch("consensus_engine.cross_reference._run_news_cascade",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new_callable=AsyncMock, return_value=(False, "")), \
         patch("consensus_engine.cross_reference._run_social_check",
               new_callable=AsyncMock, return_value={}), \
         patch("consensus_engine.cross_reference._run_technical",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new_callable=AsyncMock, return_value=ten_analysts), \
         patch("consensus_engine.cross_reference._run_llm_score",
               new_callable=AsyncMock, return_value=(0.0, "")), \
         patch("consensus_engine.cross_reference._run_options_check",
               new_callable=AsyncMock, return_value=None):
        result = await cross_reference("NVDA", tweet)

    # 3 (cap) * 20 = 60, NOT 10 * 20 = 200
    assert result.breakdown.additional_analysts == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cross_reference.py::test_analyst_multiplier_capped -v`
Expected: FAIL — `assert 200 == 60`

- [ ] **Step 3: Add config and cap the multiplier**

In `config/consensus.yaml`, add under `scoring.multipliers` (after `additional_analyst: 20`):

```yaml
    max_additional_analysts: 3
```

In `consensus_engine/cross_reference.py`, replace line 132:

```python
    analyst_pts = len(other_analysts) * m.get("additional_analyst", 20)
```

With:

```python
    max_analysts = cfg.get("scoring.multipliers.max_additional_analysts", 3)
    analyst_pts = min(len(other_analysts), max_analysts) * m.get("additional_analyst", 20)
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `pytest tests/test_cross_reference.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/cross_reference.py config/consensus.yaml tests/test_cross_reference.py
git commit -m "fix: cap analyst multiplier at 3 — prevents score inflation from 10+ analysts"
```

---

### Task 4: Reddit JSON API Migration

**Files:**
- Modify: `consensus_engine/scanners/social.py:35-98`
- Modify: `consensus_engine/main.py:222-225`
- Test: `tests/test_social_reddit.py` (new)

- [ ] **Step 1: Write test for Reddit JSON parsing**

Create `tests/test_social_reddit.py`:

```python
"""Tests for Reddit JSON API scanner."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from consensus_engine.scanners.social import _parse_reddit_json
from consensus_engine.models import SourceType


def test_parse_reddit_json_extracts_tickers():
    """Parse Reddit JSON response and extract ticker signals."""
    reddit_response = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "$NVDA is about to break out, loading calls",
                        "selftext": "massive volume on NVDA today",
                        "subreddit": "wallstreetbets",
                    }
                },
                {
                    "data": {
                        "title": "What do you think about the market?",
                        "selftext": "I'm not sure what to buy",
                        "subreddit": "wallstreetbets",
                    }
                },
                {
                    "data": {
                        "title": "$TSLA puts printing",
                        "selftext": "",
                        "subreddit": "wallstreetbets",
                    }
                },
            ]
        }
    }
    signals = _parse_reddit_json(reddit_response, "wallstreetbets")
    tickers = [s.ticker for s in signals]
    assert "NVDA" in tickers
    assert "TSLA" in tickers
    assert all(s.source_type == SourceType.REDDIT for s in signals)


def test_parse_reddit_json_empty():
    """Empty response returns no signals."""
    signals = _parse_reddit_json({"data": {"children": []}}, "test")
    assert signals == []


def test_parse_reddit_json_missing_data():
    """Malformed response returns no signals."""
    signals = _parse_reddit_json({}, "test")
    assert signals == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_social_reddit.py -v`
Expected: FAIL — `_parse_reddit_json` doesn't exist yet

- [ ] **Step 3: Replace Reddit RSS with JSON API**

In `consensus_engine/scanners/social.py`, replace the Reddit section (lines 31-98) with:

```python
# ---------------------------------------------------------------------------
# Reddit (public JSON API — no auth needed)
# ---------------------------------------------------------------------------

async def scan_reddit() -> list[TickerSignal]:
    """Fetch subreddit posts via Reddit's public JSON API."""
    subreddits = cfg.get("social.subreddits", [])
    if not subreddits:
        return []

    signals = []
    headers = {
        "User-Agent": "OpenClaw/1.0 (stock trend engine)",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        for sub in subreddits:
            if not await rate_limiter.acquire("reddit"):
                break
            try:
                url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        log.warning("Reddit JSON r/%s returned %d", sub, resp.status)
                        rate_limiter.report_failure("reddit")
                        continue
                    data = await resp.json()
                sub_signals = _parse_reddit_json(data, sub)
                signals.extend(sub_signals)
                rate_limiter.report_success("reddit")
            except Exception as e:
                log.warning("Reddit JSON error for r/%s: %s", sub, e)
                rate_limiter.report_failure("reddit")
            await asyncio.sleep(2)

    log.info("Reddit: %d signals from %d subreddits", len(signals), len(subreddits))
    return signals


def _parse_reddit_json(data: dict, subreddit: str) -> list[TickerSignal]:
    """Parse Reddit JSON API response into TickerSignal list."""
    children = data.get("data", {}).get("children", [])
    signals = []
    for child in children[:25]:
        post = child.get("data", {})
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        text = (title + " " + selftext).strip()

        tickers = extract_tickers(text)
        for ticker in tickers:
            signals.append(TickerSignal(
                ticker=ticker,
                source_type=SourceType.REDDIT,
                source_detail=f"r/{subreddit}",
                raw_text=text[:500],
                sentiment=_quick_sentiment(text),
                detected_at=time.time(),
            ))
    return signals
```

- [ ] **Step 4: Re-enable Reddit in social_scan_loop**

In `consensus_engine/main.py`, replace lines 221-225:

```python
            # Reddit disabled — rate-limited (403); StockTwits disabled — Cloudflare blocked
            results = await asyncio.gather(
                scan_apewisdom(),
                return_exceptions=True,
            )
```

With:

```python
            # StockTwits disabled — Cloudflare blocked
            results = await asyncio.gather(
                scan_reddit(),
                scan_apewisdom(),
                return_exceptions=True,
            )
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_social_reddit.py tests/test_cross_reference.py tests/test_quality_gate.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add consensus_engine/scanners/social.py consensus_engine/main.py tests/test_social_reddit.py
git commit -m "fix: restore Reddit via JSON API — replaces rate-limited RSS with /new.json"
```

---

## Phase 2: New Signal Sources

### Task 5: Tiered Catalyst Scoring

**Files:**
- Modify: `config/consensus.yaml`
- Modify: `consensus_engine/cross_reference.py:133`
- Test: `tests/test_cross_reference.py`

- [ ] **Step 1: Write test for tiered catalyst scoring**

Add to `tests/test_cross_reference.py`:

```python
from consensus_engine.cross_reference import _get_catalyst_score


def test_tiered_catalyst_high():
    assert _get_catalyst_score("Earnings Beat") == 25


def test_tiered_catalyst_medium():
    assert _get_catalyst_score("Analyst Upgrade") == 15


def test_tiered_catalyst_low():
    assert _get_catalyst_score("Partnership") == 8


def test_tiered_catalyst_unknown_defaults_to_medium():
    assert _get_catalyst_score("Unknown Event") == 15
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cross_reference.py::test_tiered_catalyst_high -v`
Expected: FAIL — `_get_catalyst_score` doesn't exist

- [ ] **Step 3: Add tiered config and scoring function**

In `config/consensus.yaml`, add after the `multipliers` block (after `options_flow: 10`):

```yaml
  catalyst_tiers:
    high:
      score: 25
      types:
        - "Earnings Beat"
        - "M&A"
        - "FDA Approval"
        - "Government Contract"
        - "Short Squeeze"
    medium:
      score: 15
      types:
        - "Analyst Upgrade"
        - "SEC Filing"
        - "Insider Buying"
        - "Guidance Update"
        - "Analyst Downgrade"
    low:
      score: 8
      types:
        - "Partnership"
        - "Patent"
        - "Product Launch"
        - "Breaking News"
        - "Dividend"
```

In `consensus_engine/cross_reference.py`, add this function after `compute_social_score`:

```python
def _get_catalyst_score(catalyst_type: str) -> int:
    """Look up tiered score for a catalyst type. Defaults to medium (15)."""
    tiers = cfg.get("scoring.catalyst_tiers", {})
    for tier_data in tiers.values():
        if catalyst_type in tier_data.get("types", []):
            return tier_data.get("score", 15)
    return tiers.get("medium", {}).get("score", 15)
```

Then replace line 133 in `cross_reference()`:

```python
    news_pts = m.get("news_catalyst", 15) if (catalyst and catalyst.passed) else 0
```

With:

```python
    news_pts = _get_catalyst_score(catalyst.catalyst_type) if (catalyst and catalyst.passed) else 0
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/test_cross_reference.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add config/consensus.yaml consensus_engine/cross_reference.py tests/test_cross_reference.py
git commit -m "feat: tiered catalyst scoring — Earnings Beat (25) > Partnership (8)"
```

---

### Task 6: Pre-Market Gap Scanner

**Files:**
- Create: `consensus_engine/scanners/premarket.py`
- Modify: `consensus_engine/main.py`
- Modify: `consensus_engine/alerts/commands.py`
- Modify: `config/consensus.yaml`
- Test: `tests/test_premarket.py` (new)

- [ ] **Step 1: Write test for gap detection logic**

Create `tests/test_premarket.py`:

```python
"""Tests for pre-market gap scanner."""
import pytest
from consensus_engine.scanners.premarket import _detect_gaps, GapResult


def test_detect_gaps_finds_large_gap():
    quotes = {
        "NVDA": {"c": 100.0, "pc": 90.0},   # +11.1% gap
        "AAPL": {"c": 150.0, "pc": 149.0},   # +0.67% gap (below threshold)
        "TSLA": {"c": 200.0, "pc": 210.0},   # -4.76% gap down
    }
    results = _detect_gaps(quotes, threshold_pct=3.0)
    tickers = [r.ticker for r in results]
    assert "NVDA" in tickers
    assert "TSLA" in tickers
    assert "AAPL" not in tickers


def test_detect_gaps_sorted_by_magnitude():
    quotes = {
        "A": {"c": 110.0, "pc": 100.0},  # +10%
        "B": {"c": 120.0, "pc": 100.0},  # +20%
    }
    results = _detect_gaps(quotes, threshold_pct=3.0)
    assert results[0].ticker == "B"
    assert results[1].ticker == "A"


def test_detect_gaps_handles_zero_prev_close():
    quotes = {"X": {"c": 50.0, "pc": 0.0}}
    results = _detect_gaps(quotes, threshold_pct=3.0)
    assert results == []


def test_detect_gaps_empty():
    results = _detect_gaps({}, threshold_pct=3.0)
    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_premarket.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Create the pre-market gap scanner**

Create `consensus_engine/scanners/premarket.py`:

```python
"""Pre-market gap scanner.

Scans watchlist tickers for >3% gaps using Finnhub /quote.
Runs 8:00-9:25am ET, posts digest to Discord.
"""

import logging
from dataclasses import dataclass

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.premarket")


@dataclass
class GapResult:
    ticker: str
    current_price: float
    prev_close: float
    gap_pct: float


def _detect_gaps(quotes: dict[str, dict], threshold_pct: float = 3.0) -> list[GapResult]:
    """Detect gaps from Finnhub quote data. Returns sorted by abs(gap_pct) descending."""
    results = []
    for ticker, q in quotes.items():
        current = q.get("c", 0)
        prev_close = q.get("pc", 0)
        if not prev_close or prev_close == 0:
            continue
        gap_pct = ((current - prev_close) / prev_close) * 100
        if abs(gap_pct) >= threshold_pct:
            results.append(GapResult(
                ticker=ticker,
                current_price=current,
                prev_close=prev_close,
                gap_pct=round(gap_pct, 2),
            ))
    results.sort(key=lambda r: abs(r.gap_pct), reverse=True)
    return results


async def _fetch_quote(session: aiohttp.ClientSession, ticker: str, api_key: str) -> tuple[str, dict]:
    """Fetch a single Finnhub quote. Returns (ticker, quote_data)."""
    if not await rate_limiter.acquire("finnhub"):
        return ticker, {}
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={api_key}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return ticker, {}
            data = await resp.json()
            rate_limiter.report_success("finnhub")
            return ticker, data
    except Exception as e:
        log.debug("Finnhub quote error for %s: %s", ticker, e)
        rate_limiter.report_failure("finnhub")
        return ticker, {}


async def scan_premarket_gaps() -> list[GapResult]:
    """Scan watchlist for pre-market gaps using Finnhub /quote."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        log.warning("Pre-market scanner: no Finnhub API key")
        return []

    watchlist = cfg.get("premarket.watchlist", [])
    if not watchlist:
        log.debug("Pre-market scanner: empty watchlist")
        return []

    threshold = cfg.get("premarket.gap_threshold_pct", 3.0)

    quotes = {}
    async with aiohttp.ClientSession() as session:
        # Batch in groups of 30 to respect rate limits
        for i in range(0, len(watchlist), 30):
            batch = watchlist[i:i+30]
            import asyncio
            results = await asyncio.gather(
                *[_fetch_quote(session, t, api_key) for t in batch],
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, tuple) and r[1]:
                    quotes[r[0]] = r[1]

    gaps = _detect_gaps(quotes, threshold)
    if gaps:
        log.info("Pre-market: %d gaps found (>%.1f%%)", len(gaps), threshold)
    return gaps


def format_gap_digest(gaps: list[GapResult]) -> str:
    """Format gap results as a Discord message."""
    if not gaps:
        return "No significant pre-market gaps detected."
    lines = ["**Pre-Market Gap Scanner**"]
    for g in gaps[:15]:
        direction = "UP" if g.gap_pct > 0 else "DOWN"
        sign = "+" if g.gap_pct > 0 else ""
        lines.append(
            f"`${g.ticker}` {direction} **{sign}{g.gap_pct:.1f}%** "
            f"(${g.prev_close:.2f} → ${g.current_price:.2f})"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Add config for pre-market scanner**

In `config/consensus.yaml`, add at the end before `# Logging`:

```yaml
# Pre-Market Gap Scanner
premarket:
  enabled: true
  gap_threshold_pct: 3.0
  scan_interval: 300
  start_hour: 8   # ET
  end_hour: 9     # ET (9:25 handled in code)
  watchlist:
    - NVDA
    - TSLA
    - AAPL
    - MSFT
    - AMZN
    - META
    - GOOGL
    - AMD
    - SMCI
    - PLTR
    - MARA
    - COIN
    - SOFI
    - RIVN
    - NIO
    - MSTR
    - ARM
    - AVGO
    - CRM
    - NFLX
```

- [ ] **Step 5: Add `!gaps` command**

In `consensus_engine/alerts/commands.py`, add to the `HELP_TEXT` string under `**Market Scanners**`:

```
`!gaps` — pre-market gap scanner (>3% gaps)
```

Add to `route_command()`:

```python
    elif command == "gaps":
        await _handle_gaps(channel_id, message_id)
```

Add handler:

```python
async def _handle_gaps(channel_id: str, message_id: str) -> None:
    """Run pre-market gap scan on demand."""
    await send_command_reply(channel_id, message_id, "Scanning pre-market gaps...")
    asyncio.create_task(_gaps_and_reply(channel_id, message_id))


async def _gaps_and_reply(channel_id: str, message_id: str) -> None:
    try:
        from consensus_engine.scanners.premarket import scan_premarket_gaps, format_gap_digest
        gaps = await scan_premarket_gaps()
        msg = format_gap_digest(gaps)
        await send_command_reply(channel_id, message_id, msg)
    except Exception as e:
        log.error("Gaps command error: %s", e)
        await send_command_reply(channel_id, message_id, "Gap scan failed.")
```

- [ ] **Step 6: Add pre-market loop to main.py**

In `consensus_engine/main.py`, add import at top:

```python
from consensus_engine.scanners.premarket import scan_premarket_gaps, format_gap_digest
```

Add new loop function after `reddit_trend_loop`:

```python
async def premarket_gap_loop(stop_event: asyncio.Event):
    """Background loop: scan for pre-market gaps 8:00-9:25am ET."""
    from datetime import datetime
    import pytz
    interval = cfg.get("premarket.scan_interval", 300)
    et = pytz.timezone("US/Eastern")

    while not stop_event.is_set():
        try:
            now_et = datetime.now(et)
            hour, minute = now_et.hour, now_et.minute
            start_h = cfg.get("premarket.start_hour", 8)
            end_h = cfg.get("premarket.end_hour", 9)

            in_window = (hour >= start_h and (hour < end_h or (hour == end_h and minute <= 25)))
            if in_window and cfg.get("premarket.enabled", True):
                gaps = await scan_premarket_gaps()
                if gaps:
                    from consensus_engine.alerts.discord import send_command_reply
                    channel = cfg.get("api_keys.discord_channel_id", "")
                    if channel:
                        msg = format_gap_digest(gaps)
                        await send_command_reply(channel, None, msg)
        except Exception as e:
            log.error("Pre-market gap loop error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass
```

Add to the `tasks` list in `run()`:

```python
        asyncio.create_task(premarket_gap_loop(stop_event), name="premarket-gaps"),
```

- [ ] **Step 7: Run all tests**

Run: `pytest tests/test_premarket.py tests/test_cross_reference.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add consensus_engine/scanners/premarket.py consensus_engine/main.py consensus_engine/alerts/commands.py config/consensus.yaml tests/test_premarket.py
git commit -m "feat: add pre-market gap scanner — detects >3% gaps 8-9:25am ET, !gaps command"
```

---

### Task 7: SEC 8-K Real-Time Watcher

**Files:**
- Create: `consensus_engine/scanners/sec_watcher.py`
- Modify: `consensus_engine/main.py`
- Test: `tests/test_sec_watcher.py` (new)

- [ ] **Step 1: Write test for 8-K feed parsing**

Create `tests/test_sec_watcher.py`:

```python
"""Tests for SEC 8-K real-time watcher."""
import pytest
from consensus_engine.scanners.sec_watcher import _parse_8k_feed


SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>8-K - NVIDIA CORP (0001045810) (Filer)</title>
    <link href="https://www.sec.gov/Archives/edgar/data/1045810/000104581024000123/0001045810-24-000123-index.htm" rel="alternate" type="text/html"/>
    <summary>8-K filed by NVIDIA CORP</summary>
    <updated>2026-03-29T10:00:00-04:00</updated>
    <id>urn:tag:sec.gov,2026:0001045810-24-000123</id>
  </entry>
  <entry>
    <title>10-Q - SOME CORP (0009999999) (Filer)</title>
    <link href="https://www.sec.gov/Archives/edgar/data/9999999/000099999924000001/index.htm" rel="alternate" type="text/html"/>
    <summary>10-Q filed by SOME CORP</summary>
    <updated>2026-03-29T09:00:00-04:00</updated>
    <id>urn:tag:sec.gov,2026:0009999999-24-000001</id>
  </entry>
</feed>"""


def test_parse_8k_feed_extracts_8k_only():
    filings = _parse_8k_feed(SAMPLE_ATOM)
    assert len(filings) == 1
    assert filings[0]["cik"] == "0001045810"
    assert filings[0]["form"] == "8-K"
    assert "NVIDIA" in filings[0]["company"]


def test_parse_8k_feed_empty():
    filings = _parse_8k_feed("<feed xmlns='http://www.w3.org/2005/Atom'></feed>")
    assert filings == []


def test_parse_8k_feed_invalid_xml():
    filings = _parse_8k_feed("not xml")
    assert filings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sec_watcher.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Create the SEC 8-K watcher**

Create `consensus_engine/scanners/sec_watcher.py`:

```python
"""SEC 8-K Real-Time Watcher.

Polls SEC EDGAR for new 8-K filings every 15 minutes.
Catches material events before analysts tweet about them.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.sec_watcher")

_USER_AGENT = "OpenClaw Signal Engine (ak@openclaw.dev)"

_8K_FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=8-K&dateb=&owner=include&count=40&output=atom"
)


@dataclass
class Filing8K:
    cik: str
    company: str
    form: str
    url: str
    filing_id: str


def _parse_8k_feed(xml_text: str) -> list[dict]:
    """Parse SEC EDGAR ATOM feed for 8-K filings.

    Returns list of dicts with keys: cik, company, form, url, filing_id.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        log.warning("SEC 8-K feed: invalid XML")
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    filings = []

    for entry in entries:
        title_el = entry.find("atom:title", ns)
        link_el = entry.find("atom:link", ns)
        id_el = entry.find("atom:id", ns)

        if title_el is None or title_el.text is None:
            continue

        title = title_el.text
        # Only 8-K filings
        if not title.startswith("8-K"):
            continue

        # Extract CIK from title: "8-K - COMPANY NAME (CIK) (Filer)"
        cik_match = re.search(r'\((\d{10})\)', title)
        cik = cik_match.group(1) if cik_match else ""

        # Extract company name
        company = title.split(" - ", 1)[1].split(" (")[0] if " - " in title else ""

        url = link_el.get("href", "") if link_el is not None else ""
        filing_id = id_el.text if id_el is not None and id_el.text else url

        filings.append({
            "cik": cik,
            "company": company,
            "form": "8-K",
            "url": url,
            "filing_id": filing_id,
        })

    return filings


async def fetch_recent_8k_filings() -> list[dict]:
    """Fetch recent 8-K filings from SEC EDGAR ATOM feed."""
    if not await rate_limiter.acquire("sec_edgar"):
        return []

    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": _USER_AGENT}
            async with session.get(_8K_FEED_URL, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    log.warning("SEC 8-K feed returned %d", resp.status)
                    rate_limiter.report_failure("sec_edgar")
                    return []
                xml_text = await resp.text()

        rate_limiter.report_success("sec_edgar")
        return _parse_8k_feed(xml_text)
    except Exception as e:
        log.warning("SEC 8-K feed error: %s", e)
        rate_limiter.report_failure("sec_edgar")
        return []


async def _resolve_ticker_from_cik(cik: str) -> Optional[str]:
    """Resolve a CIK to a ticker using the SEC ticker map (via sec_edgar module)."""
    try:
        from consensus_engine.scanners.sec_edgar import _load_ticker_map, _ticker_to_cik
        await _load_ticker_map()
        # Reverse lookup: CIK -> ticker
        for ticker, mapped_cik in _ticker_to_cik.items():
            if mapped_cik == cik:
                return ticker
    except Exception as e:
        log.debug("CIK->ticker resolve error: %s", e)
    return None


async def scan_8k_filings() -> list[dict]:
    """Scan for new 8-K filings, dedup, resolve tickers, filter by market cap.

    Returns list of dicts: {ticker, company, url, filing_id, form}.
    """
    filings = await fetch_recent_8k_filings()
    if not filings:
        return []

    results = []
    for f in filings:
        # Dedup via seen_tweets table (reuse for filing dedup)
        filing_id = f["filing_id"]
        if not await db.is_new_tweet(filing_id):
            continue

        ticker = await _resolve_ticker_from_cik(f["cik"])
        if not ticker:
            continue

        # Market cap filter
        from consensus_engine.utils.tickers import validate_ticker_market_cap
        if not await validate_ticker_market_cap(ticker):
            continue

        await db.mark_tweet_seen(filing_id, f"SEC-8K-{f['company'][:30]}")
        results.append({
            "ticker": ticker,
            "company": f["company"],
            "url": f["url"],
            "filing_id": filing_id,
            "form": "8-K",
        })

    if results:
        log.info("SEC 8-K watcher: %d new filings for tracked tickers", len(results))
    return results
```

- [ ] **Step 4: Add 8-K watcher loop to main.py**

In `consensus_engine/main.py`, add after `premarket_gap_loop`:

```python
async def sec_8k_watcher_loop(stop_event: asyncio.Event):
    """Background loop: poll SEC EDGAR for new 8-K filings every 15 min."""
    interval = 900  # 15 minutes
    while not stop_event.is_set():
        try:
            from consensus_engine.scanners.sec_watcher import scan_8k_filings
            filings = await scan_8k_filings()
            for filing in filings:
                ticker = filing["ticker"]
                log.info("SEC 8-K alert: $%s — %s", ticker, filing["company"])
                # Process like a tweet — create a synthetic tweet for the pipeline
                tweet_data = {
                    "url": filing["url"],
                    "analyst": f"SEC-8K",
                    "text": f"8-K filed by {filing['company']} (${ticker}) — material event disclosure",
                    "image_url": None,
                    "avatar_url": None,
                    "display_name": "SEC EDGAR",
                }
                await process_tweet(tweet_data)
        except Exception as e:
            log.error("SEC 8-K watcher error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass
```

Add to the `tasks` list in `run()`:

```python
        asyncio.create_task(sec_8k_watcher_loop(stop_event), name="sec-8k-watcher"),
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_sec_watcher.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add consensus_engine/scanners/sec_watcher.py consensus_engine/main.py tests/test_sec_watcher.py
git commit -m "feat: add SEC 8-K real-time watcher — catches material events before analysts tweet"
```

---

## Phase 3: Smart Money & Proactive

### Task 8: Volume Breakout Scanner

**Files:**
- Create: `consensus_engine/scanners/volume_scanner.py`
- Modify: `consensus_engine/main.py`
- Modify: `config/consensus.yaml`
- Test: `tests/test_volume_scanner.py` (new)

- [ ] **Step 1: Write test for volume breakout detection**

Create `tests/test_volume_scanner.py`:

```python
"""Tests for volume breakout scanner."""
import pytest
from consensus_engine.scanners.volume_scanner import _detect_breakouts, BreakoutResult


def test_detect_breakouts_finds_high_rvol():
    quote_data = {
        "NVDA": {"c": 110.0, "pc": 100.0, "v": 500000},  # +10%, 500k vol
        "AAPL": {"c": 150.0, "pc": 149.0, "v": 10000},   # +0.67%, low vol
    }
    avg_volumes = {"NVDA": 50000, "AAPL": 100000}
    results = _detect_breakouts(quote_data, avg_volumes, rvol_threshold=5.0, min_price_change_pct=1.0)
    tickers = [r.ticker for r in results]
    assert "NVDA" in tickers      # RVOL 10x, +10%
    assert "AAPL" not in tickers   # RVOL 0.1x


def test_detect_breakouts_filters_low_price_change():
    quote_data = {"X": {"c": 100.5, "pc": 100.0, "v": 500000}}  # +0.5%, high vol
    avg_volumes = {"X": 10000}
    results = _detect_breakouts(quote_data, avg_volumes, rvol_threshold=5.0, min_price_change_pct=1.0)
    assert results == []  # price change too low


def test_detect_breakouts_empty():
    results = _detect_breakouts({}, {}, rvol_threshold=5.0, min_price_change_pct=1.0)
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_volume_scanner.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Create the volume breakout scanner**

Create `consensus_engine/scanners/volume_scanner.py`:

```python
"""Volume breakout scanner.

Detects stocks with RVOL >5x during market hours.
Volume precedes price — this is the earliest possible signal.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.volume")


@dataclass
class BreakoutResult:
    ticker: str
    current_price: float
    prev_close: float
    price_change_pct: float
    volume: int
    avg_volume: int
    rvol: float


def _detect_breakouts(
    quote_data: dict[str, dict],
    avg_volumes: dict[str, int],
    rvol_threshold: float = 5.0,
    min_price_change_pct: float = 1.0,
) -> list[BreakoutResult]:
    """Detect volume breakouts from quote + avg volume data."""
    results = []
    for ticker, q in quote_data.items():
        current = q.get("c", 0)
        prev_close = q.get("pc", 0)
        volume = int(q.get("v", 0))
        avg_vol = avg_volumes.get(ticker, 0)

        if not prev_close or prev_close == 0 or avg_vol == 0:
            continue

        price_change_pct = ((current - prev_close) / prev_close) * 100
        rvol = volume / avg_vol

        if rvol >= rvol_threshold and abs(price_change_pct) >= min_price_change_pct:
            results.append(BreakoutResult(
                ticker=ticker,
                current_price=current,
                prev_close=prev_close,
                price_change_pct=round(price_change_pct, 2),
                volume=volume,
                avg_volume=avg_vol,
                rvol=round(rvol, 1),
            ))

    results.sort(key=lambda r: r.rvol, reverse=True)
    return results


async def _fetch_avg_volume(ticker: str, executor) -> tuple[str, int]:
    """Fetch 20-day avg volume via yfinance (blocking)."""
    def _fetch():
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            hist = t.history(period="1mo")
            if hist.empty:
                return 0
            return int(hist["Volume"].tail(20).mean())
        except Exception:
            return 0

    loop = asyncio.get_running_loop()
    try:
        avg = await loop.run_in_executor(executor, _fetch)
        return ticker, avg
    except Exception:
        return ticker, 0


async def scan_volume_breakouts(executor=None) -> list[BreakoutResult]:
    """Scan watchlist for volume breakouts using Finnhub quotes + yfinance avg volumes."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return []

    watchlist = cfg.get("volume_scanner.watchlist", cfg.get("premarket.watchlist", []))
    if not watchlist:
        return []

    rvol_threshold = cfg.get("volume_scanner.rvol_threshold", 5.0)
    min_pct = cfg.get("volume_scanner.min_price_change_pct", 1.0)

    # Fetch current quotes from Finnhub
    from consensus_engine.scanners.premarket import _fetch_quote
    quotes = {}
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(watchlist), 30):
            batch = watchlist[i:i+30]
            results = await asyncio.gather(
                *[_fetch_quote(session, t, api_key) for t in batch],
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, tuple) and r[1]:
                    quotes[r[0]] = r[1]

    # Fetch avg volumes for tickers with volume data
    avg_volumes = {}
    vol_tasks = [_fetch_avg_volume(t, executor) for t in quotes]
    vol_results = await asyncio.gather(*vol_tasks, return_exceptions=True)
    for r in vol_results:
        if isinstance(r, tuple) and r[1] > 0:
            avg_volumes[r[0]] = r[1]

    breakouts = _detect_breakouts(quotes, avg_volumes, rvol_threshold, min_pct)
    if breakouts:
        log.info("Volume scanner: %d breakouts found", len(breakouts))
    return breakouts


def format_volume_digest(breakouts: list[BreakoutResult]) -> str:
    """Format breakout results as a Discord message."""
    if not breakouts:
        return "No volume breakouts detected."
    lines = ["**Volume Breakout Scanner**"]
    for b in breakouts[:10]:
        sign = "+" if b.price_change_pct > 0 else ""
        lines.append(
            f"`${b.ticker}` **{b.rvol:.1f}x RVOL** | "
            f"{sign}{b.price_change_pct:.1f}% | "
            f"Vol: {b.volume:,} (avg {b.avg_volume:,})"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Add config for volume scanner**

In `config/consensus.yaml`, add:

```yaml
# Volume Breakout Scanner
volume_scanner:
  enabled: true
  rvol_threshold: 5.0
  min_price_change_pct: 1.0
  scan_interval: 900
```

- [ ] **Step 5: Add volume scanner loop to main.py**

In `consensus_engine/main.py`, add:

```python
async def volume_scanner_loop(stop_event: asyncio.Event):
    """Background loop: scan for volume breakouts during market hours."""
    from datetime import datetime
    import pytz
    interval = cfg.get("volume_scanner.scan_interval", 900)
    et = pytz.timezone("US/Eastern")

    while not stop_event.is_set():
        try:
            now_et = datetime.now(et)
            hour = now_et.hour
            # Market hours: 9:30am-4pm ET (use 9-16 for simplicity)
            if 9 <= hour < 16 and cfg.get("volume_scanner.enabled", True):
                from consensus_engine.scanners.volume_scanner import scan_volume_breakouts, format_volume_digest
                breakouts = await scan_volume_breakouts(executor=_executor)
                if breakouts:
                    channel = cfg.get("api_keys.discord_channel_id", "")
                    if channel:
                        msg = format_volume_digest(breakouts)
                        await send_command_reply(channel, None, msg)
                    # Also trigger cross-reference for top breakouts
                    for b in breakouts[:3]:
                        tweet_data = {
                            "url": f"volume-scanner-{b.ticker}-{time.time():.0f}",
                            "analyst": "Volume-Scanner",
                            "text": f"${b.ticker} volume breakout: {b.rvol:.1f}x RVOL, {b.price_change_pct:+.1f}%",
                            "image_url": None,
                            "avatar_url": None,
                            "display_name": "Volume Scanner",
                        }
                        await process_tweet(tweet_data)
        except Exception as e:
            log.error("Volume scanner loop error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass
```

Add to the `tasks` list in `run()`:

```python
        asyncio.create_task(volume_scanner_loop(stop_event), name="volume-scanner"),
```

- [ ] **Step 6: Run all tests**

Run: `pytest tests/test_volume_scanner.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add consensus_engine/scanners/volume_scanner.py consensus_engine/main.py config/consensus.yaml tests/test_volume_scanner.py
git commit -m "feat: add volume breakout scanner — detects RVOL >5x during market hours"
```

---

### Task 9: Earnings Calendar Pre-Alert

**Files:**
- Create: `consensus_engine/scanners/earnings_calendar.py`
- Modify: `consensus_engine/main.py`
- Test: `tests/test_earnings_calendar.py` (new)

- [ ] **Step 1: Write test for earnings filtering**

Create `tests/test_earnings_calendar.py`:

```python
"""Tests for earnings calendar pre-alert scanner."""
import pytest
from consensus_engine.scanners.earnings_calendar import _filter_upcoming_earnings


def test_filter_finds_tracked_tickers():
    earnings = [
        {"symbol": "NVDA", "date": "2026-03-30", "hour": "amc", "epsEstimate": 0.85},
        {"symbol": "RANDOM", "date": "2026-03-30", "hour": "bmo", "epsEstimate": 1.2},
        {"symbol": "TSLA", "date": "2026-03-30", "hour": "amc", "epsEstimate": 0.50},
    ]
    tracked = {"NVDA", "TSLA", "AMD"}
    result = _filter_upcoming_earnings(earnings, tracked)
    tickers = [e["symbol"] for e in result]
    assert "NVDA" in tickers
    assert "TSLA" in tickers
    assert "RANDOM" not in tickers


def test_filter_empty_earnings():
    result = _filter_upcoming_earnings([], {"NVDA"})
    assert result == []


def test_filter_no_tracked():
    earnings = [{"symbol": "NVDA", "date": "2026-03-30", "hour": "amc", "epsEstimate": 0.85}]
    result = _filter_upcoming_earnings(earnings, set())
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_earnings_calendar.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Create the earnings calendar scanner**

Create `consensus_engine/scanners/earnings_calendar.py`:

```python
"""Earnings calendar pre-alert scanner.

Alerts 24 hours before tracked stocks report earnings.
Uses Finnhub /calendar/earnings endpoint (free tier).
"""

import logging
from datetime import datetime, timedelta

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.earnings")


def _filter_upcoming_earnings(earnings: list[dict], tracked_tickers: set[str]) -> list[dict]:
    """Filter earnings to only those for tracked tickers."""
    return [e for e in earnings if e.get("symbol") in tracked_tickers]


async def fetch_earnings_calendar(from_date: str, to_date: str) -> list[dict]:
    """Fetch earnings calendar from Finnhub."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return []
    if not await rate_limiter.acquire("finnhub"):
        return []

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://finnhub.io/api/v1/calendar/earnings?from={from_date}&to={to_date}&token={api_key}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    log.warning("Finnhub earnings calendar returned %d", resp.status)
                    rate_limiter.report_failure("finnhub")
                    return []
                data = await resp.json()
                rate_limiter.report_success("finnhub")
                return data.get("earningsCalendar", [])
    except Exception as e:
        log.warning("Finnhub earnings calendar error: %s", e)
        rate_limiter.report_failure("finnhub")
        return []


async def scan_upcoming_earnings() -> list[dict]:
    """Scan for earnings reports happening tomorrow for tracked tickers."""
    # Get tickers mentioned by analysts in last 7 days
    tracked = set()
    try:
        conn = await db.get_db()
        import time
        cutoff = time.time() - 7 * 86400
        cursor = await conn.execute(
            "SELECT DISTINCT ticker FROM alert_messages WHERE created_at >= ?",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        tracked = {r["ticker"] for r in rows}
    except Exception as e:
        log.debug("Error fetching tracked tickers: %s", e)

    # Also add watchlist tickers
    watchlist = cfg.get("premarket.watchlist", [])
    tracked.update(watchlist)

    if not tracked:
        return []

    tomorrow = datetime.utcnow() + timedelta(days=1)
    from_date = tomorrow.strftime("%Y-%m-%d")
    to_date = from_date  # same day

    earnings = await fetch_earnings_calendar(from_date, to_date)
    filtered = _filter_upcoming_earnings(earnings, tracked)

    if filtered:
        log.info("Earnings pre-alert: %d tracked tickers reporting tomorrow", len(filtered))
    return filtered


def format_earnings_alert(earnings: list[dict]) -> str:
    """Format earnings pre-alert as a Discord message."""
    if not earnings:
        return "No tracked tickers reporting earnings tomorrow."
    lines = ["**Earnings Pre-Alert — Tomorrow**"]
    for e in earnings[:15]:
        symbol = e.get("symbol", "?")
        hour = e.get("hour", "?")
        timing = "before open" if hour == "bmo" else "after close" if hour == "amc" else hour
        eps_est = e.get("epsEstimate")
        eps_str = f" (EPS est: ${eps_est:.2f})" if eps_est else ""
        lines.append(f"`${symbol}` reports **{timing}**{eps_str}")
    return "\n".join(lines)
```

- [ ] **Step 4: Add earnings scanner loop to main.py**

In `consensus_engine/main.py`, add:

```python
async def earnings_alert_loop(stop_event: asyncio.Event):
    """Background loop: check for earnings reports happening tomorrow. Runs daily at 6pm ET."""
    from datetime import datetime
    import pytz
    et = pytz.timezone("US/Eastern")
    last_run_date = None

    while not stop_event.is_set():
        try:
            now_et = datetime.now(et)
            today = now_et.date()
            # Run once per day at 6pm ET
            if now_et.hour >= 18 and last_run_date != today:
                last_run_date = today
                from consensus_engine.scanners.earnings_calendar import scan_upcoming_earnings, format_earnings_alert
                earnings = await scan_upcoming_earnings()
                if earnings:
                    from consensus_engine.alerts.discord import send_command_reply
                    channel = cfg.get("api_keys.discord_channel_id", "")
                    if channel:
                        msg = format_earnings_alert(earnings)
                        await send_command_reply(channel, None, msg)
        except Exception as e:
            log.error("Earnings alert loop error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=300)
            break
        except asyncio.TimeoutError:
            pass
```

Add to the `tasks` list in `run()`:

```python
        asyncio.create_task(earnings_alert_loop(stop_event), name="earnings-alert"),
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_earnings_calendar.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add consensus_engine/scanners/earnings_calendar.py consensus_engine/main.py tests/test_earnings_calendar.py
git commit -m "feat: add earnings calendar pre-alert — warns 24h before tracked stocks report"
```

---

### Task 10: Unusual Options Sweep Scanner

**Files:**
- Modify: `consensus_engine/scanners/options.py`
- Modify: `consensus_engine/main.py`
- Test: `tests/test_options.py`

- [ ] **Step 1: Write test for market-wide sweep detection**

Add to `tests/test_options.py`:

```python
from consensus_engine.scanners.options import _detect_unusual_activity, _is_sweep
from unittest.mock import MagicMock
import pandas as pd


def test_is_sweep_high_volume_ratio():
    assert _is_sweep(vol=600, oi=100, min_ratio=5.0, min_notional=0) is True


def test_is_sweep_below_threshold():
    assert _is_sweep(vol=200, oi=100, min_ratio=5.0, min_notional=0) is False


def test_is_sweep_zero_oi():
    assert _is_sweep(vol=1000, oi=0, min_ratio=5.0, min_notional=0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_options.py::test_is_sweep_high_volume_ratio -v`
Expected: FAIL — `_is_sweep` doesn't exist

- [ ] **Step 3: Add sweep detection and market-wide scan**

In `consensus_engine/scanners/options.py`, add after the imports:

```python
_SWEEP_RATIO_THRESHOLD = 5.0
_SWEEP_MIN_NOTIONAL = 100000  # $100K


def _is_sweep(vol: float, oi: float, min_ratio: float = 5.0, min_notional: float = 0) -> bool:
    """Check if volume/OI ratio qualifies as a sweep."""
    if oi == 0:
        return False
    return (vol / oi) >= min_ratio
```

Add market-wide scan function at the end of the file:

```python
async def scan_unusual_options_market(watchlist: list[str], executor=None) -> list[dict]:
    """Scan a watchlist for unusual options activity across all tickers.

    Returns list of dicts: {ticker, direction, max_ratio, top_contract, put_call_ratio}.
    """
    import asyncio
    results = []
    for ticker in watchlist:
        try:
            result = await check_unusual_options(ticker, executor)
            if result and result.has_unusual_activity:
                direction = "CALL" if result.unusual_calls else "PUT"
                results.append({
                    "ticker": ticker,
                    "direction": direction,
                    "max_ratio": max(result.max_call_ratio, result.max_put_ratio),
                    "top_contract": result.top_contract,
                    "put_call_ratio": result.put_call_ratio,
                })
        except Exception as e:
            log.debug("Options sweep scan error for %s: %s", ticker, e)
    results.sort(key=lambda r: r["max_ratio"], reverse=True)
    return results


def format_options_sweep_digest(sweeps: list[dict]) -> str:
    """Format sweep results as Discord message."""
    if not sweeps:
        return "No unusual options sweeps detected."
    lines = ["**Options Sweep Scanner**"]
    for s in sweeps[:10]:
        lines.append(
            f"`${s['ticker']}` **{s['direction']}** sweep — "
            f"{s['max_ratio']:.1f}x vol/OI | P/C: {s['put_call_ratio']:.2f}"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Add options sweep loop to main.py**

In `consensus_engine/main.py`, add:

```python
async def options_sweep_loop(stop_event: asyncio.Event):
    """Background loop: scan for unusual options sweeps during market hours."""
    from datetime import datetime
    import pytz
    interval = 1800  # 30 min
    et = pytz.timezone("US/Eastern")

    while not stop_event.is_set():
        try:
            now_et = datetime.now(et)
            if 9 <= now_et.hour < 16:
                from consensus_engine.scanners.options import scan_unusual_options_market, format_options_sweep_digest
                watchlist = cfg.get("premarket.watchlist", [])[:20]  # top 20 to avoid rate limits
                sweeps = await scan_unusual_options_market(watchlist, executor=_executor)
                if sweeps:
                    channel = cfg.get("api_keys.discord_channel_id", "")
                    if channel:
                        msg = format_options_sweep_digest(sweeps)
                        from consensus_engine.alerts.discord import send_command_reply
                        await send_command_reply(channel, None, msg)
        except Exception as e:
            log.error("Options sweep loop error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass
```

Add to the `tasks` list in `run()`:

```python
        asyncio.create_task(options_sweep_loop(stop_event), name="options-sweep"),
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_options.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add consensus_engine/scanners/options.py consensus_engine/main.py tests/test_options.py
git commit -m "feat: add market-wide options sweep scanner — detects institutional positioning"
```

---

## Phase 4: Quality & Trust

### Task 11: Per-Analyst Win Rate + Leaderboard

**Files:**
- Modify: `consensus_engine/db.py`
- Modify: `consensus_engine/alerts/commands.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write test for analyst stats query**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_get_analyst_performance_stats():
    """Test analyst performance query returns expected structure."""
    from consensus_engine import db
    from consensus_engine import config as cfg
    import time

    cfg.load_config()
    await db.init_db()

    # Insert test data
    conn = await db.get_db()
    now = time.time()
    # Insert alert_messages with analyst
    await conn.execute(
        "INSERT INTO alert_messages (ticker, analyst, instant_msg_id, base_score, final_score, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("NVDA", "unusual_whales", "msg1", 30, 75, now - 3600),
    )
    # Insert matching alert_history with price data
    await conn.execute(
        """INSERT INTO alert_history (ticker, confidence_score, catalyst, catalyst_type,
           consensus_breakdown, technical_data, analyst_mentions, alerted_at,
           price_at_alert, price_1h_later, price_24h_later)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("NVDA", 75, "Earnings", "Earnings Beat", "{}", "{}", '["unusual_whales"]',
         now - 3600, 100.0, 105.0, 110.0),
    )
    await conn.commit()

    stats = await db.get_analyst_performance_stats()
    assert isinstance(stats, list)
    if stats:
        assert "analyst" in stats[0]
        assert "total_alerts" in stats[0]
        assert "win_rate_1h" in stats[0]

    await db.close_db()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_get_analyst_performance_stats -v`
Expected: FAIL — `get_analyst_performance_stats` doesn't exist

- [ ] **Step 3: Add analyst performance query to db.py**

In `consensus_engine/db.py`, add:

```python
async def get_analyst_performance_stats() -> list[dict]:
    """Get per-analyst win rates by joining alert_messages with alert_history.

    Returns list of dicts sorted by total_alerts desc:
      {analyst, total_alerts, wins_1h, win_rate_1h, wins_24h, win_rate_24h, avg_pnl_1h}
    """
    conn = await get_db()
    cursor = await conn.execute("""
        SELECT
            am.analyst,
            COUNT(*) as total_alerts,
            SUM(CASE WHEN ah.price_1h_later > ah.price_at_alert THEN 1 ELSE 0 END) as wins_1h,
            SUM(CASE WHEN ah.price_24h_later > ah.price_at_alert THEN 1 ELSE 0 END) as wins_24h,
            AVG(CASE WHEN ah.price_at_alert > 0 AND ah.price_1h_later IS NOT NULL
                THEN (ah.price_1h_later - ah.price_at_alert) / ah.price_at_alert * 100
                ELSE NULL END) as avg_pnl_1h
        FROM alert_messages am
        INNER JOIN alert_history ah ON am.ticker = ah.ticker
            AND abs(am.created_at - ah.alerted_at) < 60
        WHERE ah.price_at_alert > 0
        GROUP BY am.analyst
        HAVING total_alerts >= 1
        ORDER BY total_alerts DESC
    """)
    rows = await cursor.fetchall()
    results = []
    for r in rows:
        total = r["total_alerts"]
        results.append({
            "analyst": r["analyst"],
            "total_alerts": total,
            "wins_1h": r["wins_1h"] or 0,
            "win_rate_1h": (r["wins_1h"] / total * 100) if r["wins_1h"] else 0,
            "wins_24h": r["wins_24h"] or 0,
            "win_rate_24h": (r["wins_24h"] / total * 100) if r["wins_24h"] else 0,
            "avg_pnl_1h": r["avg_pnl_1h"] or 0,
        })
    return results
```

- [ ] **Step 4: Add `!leaderboard` command**

In `consensus_engine/alerts/commands.py`, add to `HELP_TEXT` under `**Market Scanners**`:

```
`!leaderboard` — analyst win rate rankings
```

Add to `route_command()`:

```python
    elif command == "leaderboard":
        await _handle_leaderboard(channel_id, message_id)
```

Add handler:

```python
async def _handle_leaderboard(channel_id: str, message_id: str) -> None:
    """Show analyst performance leaderboard."""
    try:
        from consensus_engine import db
        stats = await db.get_analyst_performance_stats()
        if not stats:
            await send_command_reply(channel_id, message_id, "No analyst performance data yet.")
            return
        lines = ["**Analyst Leaderboard**"]
        for i, s in enumerate(stats[:15], 1):
            sign = "+" if s["avg_pnl_1h"] >= 0 else ""
            lines.append(
                f"**{i}.** `@{s['analyst']}` — "
                f"{s['total_alerts']} alerts | "
                f"1h: {s['win_rate_1h']:.0f}% ({sign}{s['avg_pnl_1h']:.1f}%) | "
                f"24h: {s['win_rate_24h']:.0f}%"
            )
        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Leaderboard command error: %s", e)
        await send_command_reply(channel_id, message_id, "Leaderboard unavailable.")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_db.py::test_get_analyst_performance_stats -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add consensus_engine/db.py consensus_engine/alerts/commands.py tests/test_db.py
git commit -m "feat: add per-analyst win rate tracking + !leaderboard command"
```

---

### Task 12: Cross-Reference Result Cache

**Files:**
- Create: `consensus_engine/utils/xref_cache.py`
- Modify: `consensus_engine/cross_reference.py`
- Test: `tests/test_xref_cache.py` (new)

- [ ] **Step 1: Write test for cache behavior**

Create `tests/test_xref_cache.py`:

```python
"""Tests for cross-reference result cache."""
import time
import pytest
from consensus_engine.utils.xref_cache import XRefCache


def test_cache_miss():
    cache = XRefCache(ttl_seconds=300)
    assert cache.get("NVDA") is None


def test_cache_hit():
    cache = XRefCache(ttl_seconds=300)
    cache.put("NVDA", {"score": 75})
    assert cache.get("NVDA") == {"score": 75}


def test_cache_expired():
    cache = XRefCache(ttl_seconds=1)
    cache.put("NVDA", {"score": 75})
    # Manually expire
    cache._entries["NVDA"] = (time.time() - 2, {"score": 75})
    assert cache.get("NVDA") is None


def test_cache_different_tickers():
    cache = XRefCache(ttl_seconds=300)
    cache.put("NVDA", {"score": 75})
    cache.put("TSLA", {"score": 50})
    assert cache.get("NVDA") == {"score": 75}
    assert cache.get("TSLA") == {"score": 50}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_xref_cache.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Create the cache module**

Create `consensus_engine/utils/xref_cache.py`:

```python
"""In-memory cross-reference result cache with TTL.

Prevents redundant API calls when multiple analysts tweet the same ticker
within a short window. Keyed by ticker, 5-minute TTL.
"""

import time
from typing import Any, Optional


class XRefCache:
    """Simple in-memory cache with per-entry TTL."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, ticker: str) -> Optional[Any]:
        """Get cached result, or None if missing/expired."""
        entry = self._entries.get(ticker)
        if entry is None:
            return None
        timestamp, value = entry
        if time.time() - timestamp > self.ttl_seconds:
            del self._entries[ticker]
            return None
        return value

    def put(self, ticker: str, value: Any) -> None:
        """Cache a result for a ticker."""
        self._entries[ticker] = (time.time(), value)


# Module-level singleton
_cache = XRefCache(ttl_seconds=300)


def get_cached_xref(ticker: str) -> Optional[Any]:
    return _cache.get(ticker)


def cache_xref(ticker: str, result: Any) -> None:
    _cache.put(ticker, result)
```

- [ ] **Step 4: Integrate cache into cross_reference()**

In `consensus_engine/cross_reference.py`, add import at top:

```python
from consensus_engine.utils.xref_cache import get_cached_xref, cache_xref
```

At the start of the `cross_reference()` function, after the `direction =` line, add:

```python
    # Check xref cache (prevents redundant API calls for same ticker within 5 min)
    cached = get_cached_xref(ticker)
    if cached is not None:
        log.info("Cross-reference cache HIT for $%s", ticker)
        return cached
```

At the end of `cross_reference()`, before the `return result` line, add:

```python
    cache_xref(ticker, result)
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_xref_cache.py tests/test_cross_reference.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add consensus_engine/utils/xref_cache.py consensus_engine/cross_reference.py tests/test_xref_cache.py
git commit -m "feat: add cross-reference result cache — 5-min TTL prevents redundant API calls"
```

---

### Task 13: Fallback Parser Direction Detection

**Files:**
- Modify: `consensus_engine/analysis/tweet_parser.py:176-190`
- Modify: `tests/test_tweet_parser.py`

- [ ] **Step 1: Write test for fallback direction detection**

Add to `tests/test_tweet_parser.py`:

```python
from consensus_engine.analysis.tweet_parser import _fallback_parse
from consensus_engine.models import Direction


def test_fallback_detects_long_direction():
    parsed = _fallback_parse("https://x.com/t/1", "analyst", "$NVDA bullish breakout, buying calls here")
    assert parsed.direction == Direction.LONG


def test_fallback_detects_short_direction():
    parsed = _fallback_parse("https://x.com/t/2", "analyst", "$TSLA puts printing, bearish setup")
    assert parsed.direction == Direction.SHORT


def test_fallback_defaults_to_neutral():
    parsed = _fallback_parse("https://x.com/t/3", "analyst", "$AAPL interesting chart pattern here")
    assert parsed.direction == Direction.NEUTRAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tweet_parser.py::test_fallback_detects_long_direction -v`
Expected: FAIL — fallback always returns NEUTRAL

- [ ] **Step 3: Add direction detection to fallback**

In `consensus_engine/analysis/tweet_parser.py`, replace `_fallback_parse`:

```python
_LONG_KEYWORDS = {"long", "buy", "buying", "bullish", "calls", "moon", "breakout", "gap up", "ripping"}
_SHORT_KEYWORDS = {"short", "put", "puts", "bearish", "dump", "gap down", "crash", "selling", "fade"}


def _fallback_parse(url: str, analyst: str, text: str) -> ParsedTweet:
    """Regex fallback when LLM fails. Extracts tickers and detects direction from keywords."""
    tickers = [t for t in extract_tickers(text) if t not in _INDICATOR_NAMES]
    tweet_type = TweetType.TICKER_CALLOUT if tickers else TweetType.SENTIMENT

    # Keyword-based direction detection
    lower = text.lower()
    long_hits = sum(1 for kw in _LONG_KEYWORDS if kw in lower)
    short_hits = sum(1 for kw in _SHORT_KEYWORDS if kw in lower)
    if long_hits > short_hits:
        direction = Direction.LONG
    elif short_hits > long_hits:
        direction = Direction.SHORT
    else:
        direction = Direction.NEUTRAL

    return ParsedTweet(
        tweet_url=url,
        analyst=analyst,
        raw_text=text,
        tweet_type=tweet_type,
        tickers=tickers,
        direction=direction,
        options=None,
        conviction=Conviction.MEDIUM,
        summary=text[:100],
    )
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/test_tweet_parser.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/analysis/tweet_parser.py tests/test_tweet_parser.py
git commit -m "fix: fallback parser now detects direction from keywords instead of defaulting to NEUTRAL"
```

---

## Final Step: Run Full Test Suite

- [ ] **Run all tests to confirm nothing is broken**

```bash
pytest tests/ -v
```

Expected: ALL PASS (115 existing + ~20 new tests)

- [ ] **Commit any remaining changes and push**

```bash
git push origin master
```
