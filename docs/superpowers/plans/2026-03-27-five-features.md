# Five Engine Completions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete five outstanding items: wire Reddit scan into social loop, integrate Reddit trend pipeline, add Discord command listener, add options flow scanner, and delete legacy scripts.

**Architecture:** All five items extend the existing `consensus_engine` package. Reddit trend runs as a 4h loop in `main.py`. Commands extend the existing Discord Gateway `DiscordTweetShiftListener`. Options flow uses `yfinance` (already a dep) in a `ThreadPoolExecutor`. Legacy scripts are deleted.

**Tech Stack:** Python 3.11, aiohttp, aiosqlite, yfinance, pytest-asyncio

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `consensus_engine/main.py` | Wire `scan_reddit`, add `reddit_trend_loop`, pass `on_command` to listener |
| Create | `consensus_engine/scanners/reddit_trend.py` | Async Reddit fetch + ticker metrics + trend filtering |
| Create | `consensus_engine/scanners/options.py` | yfinance options chain → unusual activity detection |
| Create | `consensus_engine/alerts/commands.py` | Route `!` commands, format responses, send replies |
| Modify | `consensus_engine/scanners/discord_tweetshift.py` | Add `on_command` callback + `_commands_channel_id` |
| Modify | `consensus_engine/models.py` | Add `OptionsResult`; add `options_flow` to `ScoreBreakdown` |
| Modify | `consensus_engine/cross_reference.py` | Add `_run_options_check`, integrate into gather + breakdown |
| Modify | `consensus_engine/alerts/discord.py` | Add `send_trend_digest` and `send_command_reply` helpers |
| Modify | `consensus_engine/db.py` | Add `reddit_posts` table to SCHEMA |
| Delete | workspace root scripts | Remove 10+ legacy standalone scripts |
| Create | `tests/test_reddit_trend.py` | Tests for trend pipeline |
| Create | `tests/test_options.py` | Tests for options scanner |
| Create | `tests/test_commands.py` | Tests for command routing |

---

## Task 1: Wire scan_reddit into social_scan_loop

**Files:**
- Modify: `consensus_engine/main.py`
- Test: `tests/test_integration.py` (existing)

- [ ] **Step 1: Update the import in main.py**

Open `consensus_engine/main.py`. Find the social scanner import block (around line 31):

```python
from consensus_engine.scanners.social import (
    scan_stocktwits, scan_apewisdom, scan_google_trends,
)
```

Change to:

```python
from consensus_engine.scanners.social import (
    scan_reddit, scan_stocktwits, scan_apewisdom, scan_google_trends,
)
```

- [ ] **Step 2: Add scan_reddit to the gather call in social_scan_loop**

In `social_scan_loop` (around line 183), find:

```python
            results = await asyncio.gather(
                scan_stocktwits(), scan_apewisdom(),
                return_exceptions=True,
            )
```

Change to:

```python
            results = await asyncio.gather(
                scan_reddit(), scan_stocktwits(), scan_apewisdom(),
                return_exceptions=True,
            )
```

- [ ] **Step 3: Verify the engine still imports cleanly**

```bash
cd /root/.openclaw/workspace
python3 -c "from consensus_engine.main import run; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/main.py
git commit -m "feat: wire scan_reddit into social_scan_loop"
```

---

## Task 2: Reddit trend pipeline

**Files:**
- Create: `consensus_engine/scanners/reddit_trend.py`
- Modify: `consensus_engine/db.py`
- Modify: `consensus_engine/alerts/discord.py`
- Modify: `consensus_engine/main.py`
- Create: `tests/test_reddit_trend.py`

### Step 2a: Add reddit_posts table to SCHEMA

- [ ] **Step 1: Write a failing test**

Create `tests/test_reddit_trend.py`:

```python
"""Tests for the Reddit trend pipeline."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_parse_post_extracts_tickers():
    from consensus_engine.scanners.reddit_trend import _extract_tickers_from_text
    tickers = _extract_tickers_from_text("NVDA earnings beat, also watching TSLA calls")
    assert "NVDA" in tickers
    assert "TSLA" in tickers
    # Blacklisted words filtered
    assert "THE" not in tickers
    assert "ARE" not in tickers


@pytest.mark.asyncio
async def test_compute_trend_metrics_threshold():
    from consensus_engine.scanners.reddit_trend import _compute_metrics
    posts = [
        {"ticker": "NVDA", "author": "user1", "title": "NVDA buy", "created_utc": 1000000},
        {"ticker": "NVDA", "author": "user2", "title": "NVDA calls", "created_utc": 1000100},
        {"ticker": "NVDA", "author": "user3", "title": "NVDA breakout", "created_utc": 1000200},
        {"ticker": "NVDA", "author": "user1", "title": "NVDA again", "created_utc": 1000300},
        {"ticker": "NVDA", "author": "user4", "title": "NVDA up", "created_utc": 1000400},
        {"ticker": "NVDA", "author": "user5", "title": "NVDA moon", "created_utc": 1000500},
        {"ticker": "NVDA", "author": "user6", "title": "NVDA squeeze", "created_utc": 1000600},
        {"ticker": "NVDA", "author": "user7", "title": "NVDA nice", "created_utc": 1000700},
        {"ticker": "TSLA", "author": "user1", "title": "TSLA down", "created_utc": 1000000},
    ]
    metrics = _compute_metrics(posts)
    assert metrics["NVDA"]["mentions"] == 8
    assert metrics["NVDA"]["unique_authors"] == 7
    assert "TSLA" in metrics


@pytest.mark.asyncio
async def test_filter_trending_passes_threshold():
    from consensus_engine.scanners.reddit_trend import _filter_trending
    metrics = {
        "NVDA": {"mentions": 10, "unique_authors": 6, "momentum": 2.0},
        "TSLA": {"mentions": 5, "unique_authors": 3, "momentum": 1.2},
        "AAPL": {"mentions": 9, "unique_authors": 2, "momentum": 3.0},
    }
    # NVDA: passes (mentions >= 8 AND unique_authors >= 5)
    # TSLA: fails both conditions
    # AAPL: fails unique_authors < 5 (momentum passes but unique_authors doesn't)
    trending = _filter_trending(metrics)
    tickers = [t["ticker"] for t in trending]
    assert "NVDA" in tickers
    assert "TSLA" not in tickers
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/test_reddit_trend.py -v
```

Expected: `ImportError` — module doesn't exist yet.

- [ ] **Step 3: Add reddit_posts table to db.py SCHEMA**

In `consensus_engine/db.py`, after the `ticker_metadata` table block and before the closing `"""`, add:

```python
CREATE TABLE IF NOT EXISTS reddit_posts (
    id TEXT PRIMARY KEY,
    subreddit TEXT NOT NULL,
    title TEXT,
    author TEXT,
    score INTEGER DEFAULT 0,
    num_comments INTEGER DEFAULT 0,
    created_utc INTEGER NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reddit_posts_created ON reddit_posts(created_utc);
CREATE INDEX IF NOT EXISTS idx_reddit_posts_sub ON reddit_posts(subreddit);
```

Also add this function to `db.py`:

```python
async def insert_reddit_posts(posts: list[dict]) -> int:
    """Bulk-insert Reddit posts, ignoring duplicates. Returns count inserted."""
    conn = await get_db()
    inserted = 0
    for post in posts:
        try:
            await conn.execute(
                """INSERT OR IGNORE INTO reddit_posts
                   (id, subreddit, title, author, score, num_comments, created_utc, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    post["id"], post["subreddit"], post.get("title", ""),
                    post.get("author", ""), post.get("score", 0),
                    post.get("num_comments", 0), post["created_utc"], time.time(),
                ),
            )
            inserted += 1
        except Exception:
            pass
    await conn.commit()
    return inserted


async def get_reddit_posts_since(since_utc: int) -> list[dict]:
    """Fetch posts created after since_utc."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT id, subreddit, title, author FROM reddit_posts WHERE created_utc > ? ORDER BY created_utc DESC",
        (since_utc,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Create consensus_engine/scanners/reddit_trend.py**

```python
"""Reddit trend pipeline.

Fetches recent posts from finance subreddits, extracts tickers,
computes momentum metrics, and returns trending tickers.
"""

import logging
import re
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger("consensus_engine.scanner.reddit_trend")

SUBREDDITS = [
    "wallstreetbets", "stocks", "investing", "options",
    "pennystocks", "StockMarket", "Daytrading",
]

BLACKLIST = {
    "AI", "ON", "IT", "DD", "THE", "FOR", "ARE", "ALL", "OUT", "NOW",
    "UP", "GO", "MY", "SO", "AT", "IN", "NO", "CEO", "USA", "A", "I",
    "TO", "DO", "BE", "HAS", "WAS", "SEE", "DAY", "BUY", "RUN", "BIG",
    "MAN", "CAN", "NEW", "ONE", "TWO", "SIX", "TEN", "CAR", "JOB", "PAY",
    "TAX", "EPS", "ROI", "YTD", "SEC", "FED", "GDP", "ATH", "OTC", "IPO",
    "PNL", "PR", "HR", "LLC", "INC", "YOLO", "FOMO", "LFG", "WSB", "MOON",
    "HOLD", "PUMP", "DUMP", "APE", "APES", "BULL", "BEAR", "GUH", "TEND",
    "DFV", "RH", "UK", "EU", "EV", "AR", "VR", "PC", "TV", "ETF", "JOSE",
    "AND", "BUT", "OR", "NOT", "WITH", "FROM", "THIS", "THAT", "THEY",
    "WHEN", "WHAT", "WILL", "MORE", "VERY", "ALSO", "JUST", "THAN",
    "THEN", "BEEN", "HAVE", "THEY", "THEIR", "THERE", "WERE",
}

_TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b|\$[A-Z]{1,5}\b")


def _extract_tickers_from_text(text: str) -> set[str]:
    """Extract valid-looking ticker symbols from text, filtering blacklist."""
    matches = _TICKER_RE.findall(text)
    return {m.lstrip("$") for m in matches if m.lstrip("$") not in BLACKLIST}


def _compute_metrics(posts: list[dict]) -> dict[str, dict]:
    """Compute per-ticker mention count, unique authors, from a post list.

    Each post dict must have keys: ticker, author, created_utc.
    Returns {ticker: {mentions, unique_authors}}.
    """
    data: dict[str, dict] = {}
    for post in posts:
        ticker = post["ticker"]
        author = post.get("author", "")
        if ticker not in data:
            data[ticker] = {"mentions": 0, "unique_authors": set(), "momentum": 1.0}
        data[ticker]["mentions"] += 1
        if author:
            data[ticker]["unique_authors"].add(author)

    # Freeze sets to counts
    for ticker in data:
        data[ticker]["unique_authors"] = len(data[ticker]["unique_authors"])

    return data


def _filter_trending(
    metrics: dict[str, dict],
    min_mentions: int = 8,
    min_momentum: float = 1.5,
    min_unique_authors: int = 5,
) -> list[dict]:
    """Filter tickers meeting the trend threshold.

    Passes if: mentions >= min_mentions AND (momentum > min_momentum OR unique_authors >= min_unique_authors)
    """
    trending = []
    for ticker, m in metrics.items():
        if m["mentions"] >= min_mentions and (
            m.get("momentum", 1.0) > min_momentum or m["unique_authors"] >= min_unique_authors
        ):
            trending.append({
                "ticker": ticker,
                "mentions": m["mentions"],
                "unique_authors": m["unique_authors"],
                "momentum": m.get("momentum", 1.0),
            })
    return sorted(trending, key=lambda x: x["mentions"], reverse=True)


async def _fetch_subreddit(session: aiohttp.ClientSession, subreddit: str, limit: int = 50) -> list[dict]:
    """Fetch recent posts from a subreddit using Reddit's public JSON API."""
    url = f"https://www.reddit.com/r/{subreddit}/new.json"
    params = {"limit": limit}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; OpenClaw/1.0)"}
    try:
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("Reddit r/%s returned %d", subreddit, resp.status)
                return []
            data = await resp.json()
            children = data.get("data", {}).get("children", [])
            posts = []
            for child in children:
                post = child.get("data", {})
                posts.append({
                    "id": post.get("id", ""),
                    "subreddit": subreddit,
                    "title": post.get("title", ""),
                    "selftext": post.get("selftext", ""),
                    "author": post.get("author", ""),
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "created_utc": int(post.get("created_utc", 0)),
                })
            return posts
    except Exception as e:
        log.warning("Reddit fetch error for r/%s: %s", subreddit, e)
        return []


async def crawl_and_get_trending() -> list[dict]:
    """Fetch recent posts, store to DB, compute + return trending tickers."""
    subreddits = cfg.get("social.reddit_trend_subreddits", SUBREDDITS)
    lookback_hours = cfg.get("social.reddit_trend_lookback_hours", 24)
    since_utc = int(time.time()) - lookback_hours * 3600

    all_posts = []
    async with aiohttp.ClientSession() as session:
        for sub in subreddits:
            posts = await _fetch_subreddit(session, sub)
            if posts:
                await db.insert_reddit_posts(posts)
                all_posts.extend(posts)
            # Brief pause between subreddits
            import asyncio
            await asyncio.sleep(2)

    # Get all recent posts (including previously stored)
    recent = await db.get_reddit_posts_since(since_utc)

    # Expand posts into (ticker, author, created_utc) triples
    expanded = []
    for post in recent:
        text = post.get("title", "")
        tickers = _extract_tickers_from_text(text)
        for ticker in tickers:
            expanded.append({
                "ticker": ticker,
                "author": post.get("author", ""),
                "created_utc": post.get("created_utc", 0),
            })

    if not expanded:
        log.info("Reddit trend: no posts in last %dh", lookback_hours)
        return []

    metrics = _compute_metrics(expanded)
    trending = _filter_trending(metrics)

    log.info("Reddit trend: %d trending tickers from %d posts", len(trending), len(recent))
    return trending
```

- [ ] **Step 5: Add send_trend_digest to alerts/discord.py**

Append to the bottom of `consensus_engine/alerts/discord.py`:

```python
async def send_trend_digest(trending: list[dict]) -> Optional[str]:
    """Post a Reddit trend digest to the main Discord channel. Returns message ID."""
    if cfg.dry_run:
        log.info("[DRY-RUN] Trend digest: %d tickers", len(trending))
        return "dry_run_digest_id"

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit():
        log.warning("Discord not configured for trend digest")
        return None

    if not trending:
        return None

    lines = []
    for i, t in enumerate(trending[:15], 1):
        momentum_str = f"{t['momentum']:.1f}x" if t.get("momentum", 1.0) > 1.0 else "—"
        lines.append(
            f"**{i}.** `${t['ticker']}` — {t['mentions']} mentions | "
            f"{t['unique_authors']} authors | momentum {momentum_str}"
        )

    embed = {
        "title": "Reddit Trend Digest",
        "description": "\n".join(lines),
        "color": 0x7289DA,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "footer": {"text": "OpenClaw Signal Engine — last 24h"},
    }

    async with aiohttp.ClientSession() as session:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        payload = {"embeds": [embed]}
        async with session.post(url, headers=headers, json=payload,
                                timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status not in (200, 201):
                log.warning("Trend digest send failed: %d", resp.status)
                return None
            data = await resp.json()
            return data.get("id")
```

- [ ] **Step 6: Add reddit_trend_loop to main.py**

Add import near the top of `consensus_engine/main.py` with the other scanner imports:

```python
from consensus_engine.scanners.reddit_trend import crawl_and_get_trending
from consensus_engine.alerts.discord import send_instant_ping, send_detail_followup, send_trend_digest
```

Add the loop function after `prune_loop`:

```python
async def reddit_trend_loop(stop_event: asyncio.Event):
    """Background loop: crawl Reddit every 4h and post trend digest."""
    interval = cfg.get("intervals.reddit_trend", 14400)  # 4 hours
    while not stop_event.is_set():
        try:
            trending = await crawl_and_get_trending()
            if trending:
                await send_trend_digest(trending)
        except Exception as e:
            log.error("Reddit trend loop error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass
```

In the `run()` function, add the new task to the `tasks` list:

```python
    tasks = [
        asyncio.create_task(nitter_poll_loop(stop_event), name="nitter-poller"),
        asyncio.create_task(tweetshift_listener_loop(stop_event), name="tweetshift-listener"),
        asyncio.create_task(social_scan_loop(stop_event), name="social-scanner"),
        asyncio.create_task(price_followup_loop(stop_event), name="price-followup"),
        asyncio.create_task(prune_loop(stop_event), name="pruner"),
        asyncio.create_task(reddit_trend_loop(stop_event), name="reddit-trend"),
    ]
```

Also update the log line:

```python
    log.info("All loops started: nitter-poller, tweetshift-listener, social-scanner, price-followup, pruner, reddit-trend")
```

- [ ] **Step 7: Run tests**

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/test_reddit_trend.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 8: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/scanners/reddit_trend.py consensus_engine/db.py \
        consensus_engine/alerts/discord.py consensus_engine/main.py \
        tests/test_reddit_trend.py
git commit -m "feat: add Reddit trend pipeline with 4h digest loop"
```

---

## Task 3: Discord command listener

**Files:**
- Create: `consensus_engine/alerts/commands.py`
- Modify: `consensus_engine/scanners/discord_tweetshift.py`
- Modify: `consensus_engine/alerts/discord.py`
- Modify: `consensus_engine/main.py`
- Create: `tests/test_commands.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_commands.py`:

```python
"""Tests for Discord command routing."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_route_help_command():
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send:
        await route_command("help", [], "chan123", "msg123")
        mock_send.assert_called_once()
        content = mock_send.call_args[0][2]  # third positional arg is content
        assert "!scan" in content
        assert "!status" in content


@pytest.mark.asyncio
async def test_route_unknown_command():
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send:
        await route_command("foobar", [], "chan123", "msg123")
        mock_send.assert_called_once()
        content = mock_send.call_args[0][2]
        assert "Unknown command" in content


@pytest.mark.asyncio
async def test_parse_command_from_message():
    from consensus_engine.alerts.commands import parse_command
    cmd, args = parse_command("!scan NVDA")
    assert cmd == "scan"
    assert args == ["NVDA"]

    cmd2, args2 = parse_command("!help")
    assert cmd2 == "help"
    assert args2 == []

    # Non-command returns None
    result = parse_command("just a regular message")
    assert result is None


@pytest.mark.asyncio
async def test_route_scan_requires_ticker():
    from consensus_engine.alerts.commands import route_command
    with patch("consensus_engine.alerts.commands.send_command_reply", new_callable=AsyncMock) as mock_send:
        await route_command("scan", [], "chan123", "msg123")
        content = mock_send.call_args[0][2]
        assert "Usage" in content or "ticker" in content.lower()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/test_commands.py -v
```

Expected: `ImportError` — module doesn't exist yet.

- [ ] **Step 3: Add send_command_reply to alerts/discord.py**

Append to `consensus_engine/alerts/discord.py`:

```python
async def send_command_reply(channel_id: str, reply_to_msg_id: str, content: str) -> Optional[str]:
    """Send a plain-text reply to a Discord command message."""
    if cfg.dry_run:
        log.info("[DRY-RUN] Command reply to %s: %s", reply_to_msg_id, content[:80])
        return "dry_run_reply_id"

    token = cfg.get_api_key("discord_bot_token")
    if not token:
        log.warning("Discord bot token not configured")
        return None

    async with aiohttp.ClientSession() as session:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        payload = {
            "content": content[:2000],
            "message_reference": {"message_id": reply_to_msg_id},
        }
        async with session.post(url, headers=headers, json=payload,
                                timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status not in (200, 201):
                log.warning("Command reply failed: %d", resp.status)
                return None
            data = await resp.json()
            return data.get("id")
```

- [ ] **Step 4: Create consensus_engine/alerts/commands.py**

```python
"""Discord command routing.

Handles ! -prefixed commands received via the Discord Gateway.
Commands:
  !help          — list available commands
  !status        — engine status summary
  !trend         — last Reddit trend digest on demand
  !scan <TICKER> — run cross-reference on a ticker and reply with score
"""

import logging
from typing import Optional

from consensus_engine.alerts.discord import send_command_reply

log = logging.getLogger("consensus_engine.alerts.commands")

HELP_TEXT = """**OpenClaw Signal Engine — Commands**
`!help` — show this message
`!status` — engine health summary (active signals, last alert)
`!trend` — post latest Reddit trend digest
`!scan <TICKER>` — run cross-reference on a ticker (e.g. `!scan NVDA`)"""


def parse_command(content: str) -> Optional[tuple[str, list[str]]]:
    """Parse a Discord message into (command, args) if it starts with !.

    Returns None if the message is not a command.
    """
    content = content.strip()
    if not content.startswith("!"):
        return None
    parts = content[1:].split()
    if not parts:
        return None
    return parts[0].lower(), parts[1:]


async def route_command(
    command: str,
    args: list[str],
    channel_id: str,
    message_id: str,
) -> None:
    """Dispatch a parsed command to its handler."""
    if command in ("help", "readme"):
        await send_command_reply(channel_id, message_id, HELP_TEXT)

    elif command == "status":
        await _handle_status(channel_id, message_id)

    elif command == "trend":
        await _handle_trend(channel_id, message_id)

    elif command == "scan":
        if not args:
            await send_command_reply(
                channel_id, message_id,
                "Usage: `!scan <TICKER>` — e.g. `!scan NVDA`"
            )
        else:
            await _handle_scan(args[0].upper(), channel_id, message_id)

    else:
        await send_command_reply(
            channel_id, message_id,
            f"Unknown command `!{command}`. Try `!help`."
        )


async def _handle_status(channel_id: str, message_id: str) -> None:
    """Reply with a brief engine status summary."""
    try:
        from consensus_engine import db
        import time
        conn = await db.get_db()
        now = time.time()

        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM ticker_signals WHERE expires_at > ?", (now,)
        )
        row = await cursor.fetchone()
        active_signals = row["cnt"] if row else 0

        cursor = await conn.execute(
            "SELECT ticker, confidence_score, alerted_at FROM alert_history ORDER BY alerted_at DESC LIMIT 1"
        )
        last_alert = await cursor.fetchone()

        lines = [f"**Engine Status**", f"Active signals: {active_signals}"]
        if last_alert:
            ago_min = int((now - last_alert["alerted_at"]) / 60)
            lines.append(f"Last alert: `${last_alert['ticker']}` score={last_alert['confidence_score']:.0f} ({ago_min}m ago)")
        else:
            lines.append("Last alert: none")

        await send_command_reply(channel_id, message_id, "\n".join(lines))
    except Exception as e:
        log.error("Status command error: %s", e)
        await send_command_reply(channel_id, message_id, "Status unavailable.")


async def _handle_trend(channel_id: str, message_id: str) -> None:
    """Trigger an on-demand Reddit trend digest."""
    try:
        await send_command_reply(channel_id, message_id, "Running trend scan... (may take ~30s)")
        from consensus_engine.scanners.reddit_trend import crawl_and_get_trending
        from consensus_engine.alerts.discord import send_trend_digest
        trending = await crawl_and_get_trending()
        if trending:
            await send_trend_digest(trending)
        else:
            await send_command_reply(channel_id, message_id, "No trending tickers found right now.")
    except Exception as e:
        log.error("Trend command error: %s", e)
        await send_command_reply(channel_id, message_id, "Trend scan failed.")


async def _handle_scan(ticker: str, channel_id: str, message_id: str) -> None:
    """Run cross-reference on a ticker and reply with results."""
    try:
        await send_command_reply(channel_id, message_id, f"Scanning `${ticker}`...")
        from consensus_engine.cross_reference import cross_reference
        from consensus_engine.models import (
            ParsedTweet, TweetType, Direction, Conviction, OptionsDetail
        )
        # Build a minimal ParsedTweet so cross_reference() has what it needs
        fake_tweet = ParsedTweet(
            tweet_url="command",
            analyst="command",
            raw_text=f"!scan {ticker}",
            tweet_type=TweetType.TICKER_CALLOUT,
            tickers=[ticker],
            direction=Direction.NEUTRAL,
            options=None,
            conviction=Conviction.MEDIUM,
            summary=f"On-demand scan for ${ticker}",
        )
        xref = await cross_reference(ticker, fake_tweet)
        b = xref.breakdown
        parts = []
        if b.base: parts.append(f"base={b.base}")
        if b.news_catalyst: parts.append(f"news={b.news_catalyst}")
        if b.sec_filing: parts.append(f"sec={b.sec_filing}")
        if b.technical: parts.append(f"tech={b.technical}")
        if b.additional_analysts: parts.append(f"analysts={b.additional_analysts}")
        social = b.social_apewisdom + b.social_stocktwits + b.social_reddit + b.google_trends
        if social: parts.append(f"social={social}")
        if b.llm_boost: parts.append(f"llm={b.llm_boost}")

        score_str = " + ".join(parts) + f" = **{xref.final_score}**"
        summary_lines = [f"**${ticker} Scan — Score: {xref.final_score}**", score_str]
        if xref.catalyst_summary:
            summary_lines.append(f"News: {xref.catalyst_summary[:200]}")
        if xref.social_summary:
            summary_lines.append(f"Social: {xref.social_summary}")

        await send_command_reply(channel_id, message_id, "\n".join(summary_lines))
    except Exception as e:
        log.error("Scan command error for %s: %s", ticker, e)
        await send_command_reply(channel_id, message_id, f"Scan failed for `${ticker}`.")
```

- [ ] **Step 5: Extend DiscordTweetShiftListener with command support**

In `consensus_engine/scanners/discord_tweetshift.py`, update `__init__`:

```python
    def __init__(self, on_tweet: Callable, on_command: Optional[Callable] = None):
        """
        Args:
            on_tweet: async callback(tweet_data: dict) called for each new tweet.
            on_command: optional async callback(command, args, channel_id, message_id)
                        called for ! -prefixed messages on the commands channel.
        """
        self._on_tweet = on_tweet
        self._on_command = on_command
        self._token: str = ""
        self._feed_channel_id: str = ""
        self._commands_channel_id: str = ""
        self._known: set[str] = set()

        self._session_id: Optional[str] = None
        self._sequence: Optional[int] = None
        self._heartbeat_interval: float = 41.25
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._stop = False
```

Update `_load_config` to also read the commands channel:

```python
    def _load_config(self):
        self._token = cfg.get_api_key("discord_bot_token") or ""
        self._feed_channel_id = str(
            cfg.get("api_keys.discord_feed_channel_id", "") or ""
        ).strip()
        self._commands_channel_id = str(
            cfg.get("api_keys.discord_channel_id", "") or ""
        ).strip()
        accounts = cfg.get_twitter_accounts()
        self._known = _known_handles(accounts)
```

Update `_handle_dispatch` to add command handling after the TweetShift block:

```python
    async def _handle_dispatch(self, event: str, data: dict):
        if event == "READY":
            self._session_id = data.get("session_id")
            log.info("Discord Gateway READY (session=%s)", self._session_id)

        elif event == "MESSAGE_CREATE":
            channel_id = str(data.get("channel_id", ""))
            message_id = str(data.get("id", ""))
            content = data.get("content", "")

            # TweetShift feed channel: process as tweet
            if channel_id == self._feed_channel_id:
                tweet_data = _parse_tweetshift_message(data)
                if not tweet_data:
                    return
                handle_lower = _normalize_handle(tweet_data["analyst"])
                if self._known and handle_lower not in self._known:
                    log.debug("Ignoring message from unknown handle @%s", tweet_data["analyst"])
                    return
                if not await db.is_new_tweet(tweet_data["url"]):
                    return
                await db.mark_tweet_seen(tweet_data["url"], tweet_data["analyst"])
                log.info("TweetShift tweet: @%s — %.80s", tweet_data["analyst"], tweet_data["text"])
                try:
                    await self._on_tweet(tweet_data)
                except Exception as e:
                    log.error("Tweet callback error: %s", e, exc_info=True)

            # Commands channel: route ! commands
            elif channel_id == self._commands_channel_id and self._on_command:
                from consensus_engine.alerts.commands import parse_command
                parsed = parse_command(content)
                if parsed:
                    cmd, args = parsed
                    log.info("Discord command: !%s %s", cmd, args)
                    try:
                        await self._on_command(cmd, args, channel_id, message_id)
                    except Exception as e:
                        log.error("Command callback error: %s", e, exc_info=True)
```

- [ ] **Step 6: Update tweetshift_listener_loop in main.py to pass on_command**

Add import at top of `main.py`:

```python
from consensus_engine.alerts.commands import route_command
```

Update `tweetshift_listener_loop`:

```python
async def tweetshift_listener_loop(stop_event: asyncio.Event):
    """Discord Gateway loop: receive TweetShift tweets and process them."""
    listener = DiscordTweetShiftListener(on_tweet=process_tweet, on_command=route_command)
    await listener.run(stop_event)
```

- [ ] **Step 7: Run tests**

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/test_commands.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 8: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/alerts/commands.py consensus_engine/alerts/discord.py \
        consensus_engine/scanners/discord_tweetshift.py consensus_engine/main.py \
        tests/test_commands.py
git commit -m "feat: add Discord command listener (!help, !status, !trend, !scan)"
```

---

## Task 4: Options flow scanner

**Files:**
- Create: `consensus_engine/scanners/options.py`
- Modify: `consensus_engine/models.py`
- Modify: `consensus_engine/cross_reference.py`
- Create: `tests/test_options.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_options.py`:

```python
"""Tests for the options flow scanner."""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd


def _make_options_chain(calls_data, puts_data):
    """Build a mock yfinance option_chain result."""
    calls = pd.DataFrame(calls_data)
    puts = pd.DataFrame(puts_data)
    chain = MagicMock()
    chain.calls = calls
    chain.puts = puts
    return chain


def test_detect_unusual_calls():
    from consensus_engine.scanners.options import _detect_unusual_activity
    chain = _make_options_chain(
        calls_data=[
            {"contractSymbol": "NVDA240119C00500000", "volume": 5000, "openInterest": 1000,
             "impliedVolatility": 0.45, "inTheMoney": False},
        ],
        puts_data=[
            {"contractSymbol": "NVDA240119P00500000", "volume": 100, "openInterest": 500,
             "impliedVolatility": 0.40, "inTheMoney": False},
        ],
    )
    result = _detect_unusual_activity(chain)
    assert result.unusual_calls is True
    assert result.unusual_puts is False
    assert result.max_call_ratio == pytest.approx(5.0)


def test_detect_no_unusual_activity():
    from consensus_engine.scanners.options import _detect_unusual_activity
    chain = _make_options_chain(
        calls_data=[
            {"contractSymbol": "NVDA240119C00500000", "volume": 50, "openInterest": 1000,
             "impliedVolatility": 0.30, "inTheMoney": False},
        ],
        puts_data=[
            {"contractSymbol": "NVDA240119P00500000", "volume": 80, "openInterest": 2000,
             "impliedVolatility": 0.28, "inTheMoney": False},
        ],
    )
    result = _detect_unusual_activity(chain)
    assert result.unusual_calls is False
    assert result.unusual_puts is False


def test_put_call_ratio():
    from consensus_engine.scanners.options import _detect_unusual_activity
    chain = _make_options_chain(
        calls_data=[
            {"contractSymbol": "X", "volume": 1000, "openInterest": 5000,
             "impliedVolatility": 0.3, "inTheMoney": False},
        ],
        puts_data=[
            {"contractSymbol": "Y", "volume": 3000, "openInterest": 5000,
             "impliedVolatility": 0.3, "inTheMoney": False},
        ],
    )
    result = _detect_unusual_activity(chain)
    assert result.put_call_ratio == pytest.approx(3.0)


def test_options_result_has_unusual_activity_property():
    from consensus_engine.models import OptionsResult
    r = OptionsResult(ticker="NVDA", unusual_calls=True)
    assert r.has_unusual_activity is True
    r2 = OptionsResult(ticker="NVDA")
    assert r2.has_unusual_activity is False
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/test_options.py -v
```

Expected: `ImportError` — modules don't exist yet.

- [ ] **Step 3: Add OptionsResult to models.py**

In `consensus_engine/models.py`, add after `AlertMessage`:

```python
@dataclass
class OptionsResult:
    """Unusual options activity detected for a ticker."""
    ticker: str
    unusual_calls: bool = False
    unusual_puts: bool = False
    max_call_ratio: float = 0.0   # max volume/OI ratio across calls
    max_put_ratio: float = 0.0    # max volume/OI ratio across puts
    put_call_ratio: float = 0.0   # total put volume / total call volume
    top_contract: str = ""        # contractSymbol with highest unusual ratio

    @property
    def has_unusual_activity(self) -> bool:
        return self.unusual_calls or self.unusual_puts
```

Also add `options_flow: int = 0` to `ScoreBreakdown`:

```python
@dataclass
class ScoreBreakdown:
    """Additive score from all cross-reference sources."""
    base: int = 0
    additional_analysts: int = 0
    news_catalyst: int = 0
    sec_filing: int = 0
    social_apewisdom: int = 0
    social_stocktwits: int = 0
    social_reddit: int = 0
    google_trends: int = 0
    technical: int = 0
    llm_boost: int = 0
    options_flow: int = 0

    @property
    def total(self) -> int:
        return (self.base + self.additional_analysts + self.news_catalyst
                + self.sec_filing + self.social_apewisdom + self.social_stocktwits
                + self.social_reddit + self.google_trends + self.technical
                + self.llm_boost + self.options_flow)
```

- [ ] **Step 4: Create consensus_engine/scanners/options.py**

```python
"""Options flow scanner.

Uses yfinance options chain to detect unusual activity:
- Volume/OpenInterest ratio > 3x with volume > 100 contracts
- Computes put/call ratio from total volumes

Runs in a ThreadPoolExecutor since yfinance is blocking.
"""

import logging
from typing import Optional

from consensus_engine.models import OptionsResult

log = logging.getLogger("consensus_engine.scanner.options")

_UNUSUAL_RATIO_THRESHOLD = 3.0
_MIN_VOLUME = 100


def _detect_unusual_activity(chain) -> OptionsResult:
    """Detect unusual activity from a yfinance option_chain result.

    Args:
        chain: yfinance option_chain namedtuple with .calls and .puts DataFrames

    Returns:
        OptionsResult with detected unusual activity.
    """
    calls = chain.calls
    puts = chain.puts

    unusual_calls = False
    unusual_puts = False
    max_call_ratio = 0.0
    max_put_ratio = 0.0
    top_contract = ""
    total_call_vol = 0
    total_put_vol = 0

    if calls is not None and not calls.empty:
        for _, row in calls.iterrows():
            vol = float(row.get("volume", 0) or 0)
            oi = float(row.get("openInterest", 0) or 0)
            total_call_vol += vol
            if vol < _MIN_VOLUME or oi == 0:
                continue
            ratio = vol / oi
            if ratio > max_call_ratio:
                max_call_ratio = ratio
                top_contract = str(row.get("contractSymbol", ""))
            if ratio >= _UNUSUAL_RATIO_THRESHOLD:
                unusual_calls = True

    if puts is not None and not puts.empty:
        for _, row in puts.iterrows():
            vol = float(row.get("volume", 0) or 0)
            oi = float(row.get("openInterest", 0) or 0)
            total_put_vol += vol
            if vol < _MIN_VOLUME or oi == 0:
                continue
            ratio = vol / oi
            if ratio > max_put_ratio:
                max_put_ratio = ratio
            if ratio >= _UNUSUAL_RATIO_THRESHOLD:
                unusual_puts = True

    put_call_ratio = (total_put_vol / total_call_vol) if total_call_vol > 0 else 0.0

    return OptionsResult(
        ticker="",  # filled in by caller
        unusual_calls=unusual_calls,
        unusual_puts=unusual_puts,
        max_call_ratio=round(max_call_ratio, 2),
        max_put_ratio=round(max_put_ratio, 2),
        put_call_ratio=round(put_call_ratio, 2),
        top_contract=top_contract,
    )


async def check_unusual_options(ticker: str, executor) -> Optional[OptionsResult]:
    """Check for unusual options activity on a ticker.

    Fetches the nearest-expiry options chain via yfinance (blocking, runs
    in executor). Returns None if no data is available or on error.
    """
    import asyncio

    def _fetch():
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            expirations = t.options
            if not expirations:
                return None
            # Use the nearest expiry (most liquid, most actionable)
            chain = t.option_chain(expirations[0])
            return chain
        except Exception as e:
            log.debug("yfinance options fetch error for %s: %s", ticker, e)
            return None

    loop = asyncio.get_event_loop()
    chain = await loop.run_in_executor(executor, _fetch)
    if chain is None:
        return None

    result = _detect_unusual_activity(chain)
    result.ticker = ticker

    if result.has_unusual_activity:
        log.info(
            "Unusual options for $%s: calls=%s (max_ratio=%.1f) puts=%s (max_ratio=%.1f) p/c=%.2f",
            ticker, result.unusual_calls, result.max_call_ratio,
            result.unusual_puts, result.max_put_ratio, result.put_call_ratio,
        )
    else:
        log.debug("No unusual options for $%s (max_call_ratio=%.1f)", ticker, result.max_call_ratio)

    return result
```

- [ ] **Step 5: Integrate options check into cross_reference.py**

Add import at the top of `consensus_engine/cross_reference.py`:

```python
from consensus_engine.models import (
    ParsedTweet, CrossReferenceResult, ScoreBreakdown,
    CatalystResult, TechnicalResult, OptionsResult,
)
```

Add the helper function:

```python
async def _run_options_check(ticker: str, executor) -> Optional[OptionsResult]:
    """Check for unusual options activity."""
    try:
        from consensus_engine.scanners.options import check_unusual_options
        return await check_unusual_options(ticker, executor)
    except Exception as e:
        log.debug("Options check error for %s: %s", ticker, e)
        return None
```

Update `cross_reference()` to accept and use the executor. Since `cross_reference` is called from `main.py` which owns `_executor`, pass it through:

```python
async def cross_reference(ticker: str, tweet: ParsedTweet, executor=None) -> CrossReferenceResult:
    """Run all cross-reference sources in parallel and compute final score."""
    log.info("Starting cross-reference for $%s (base=%d)", ticker, tweet.base_score)
    m = cfg.get("scoring.multipliers", {})

    catalyst, (sec_hit, sec_summary), social_data, technical, other_analysts, (llm_score, llm_reasoning), options = \
        await asyncio.gather(
            _run_news_cascade(ticker),
            _run_sec_check(ticker),
            _run_social_check(ticker),
            _run_technical(ticker),
            _run_other_analysts(ticker, exclude_analyst=tweet.analyst),
            _run_llm_score(ticker, None, None),
            _run_options_check(ticker, executor),
        )
```

Add options scoring to the breakdown computation in `cross_reference()`:

```python
    options_pts = 0
    if options and options.has_unusual_activity:
        options_pts = m.get("options_flow", 10)
```

Update `ScoreBreakdown` construction to include `options_flow=options_pts`:

```python
    breakdown = ScoreBreakdown(
        base=tweet.base_score,
        additional_analysts=analyst_pts,
        news_catalyst=news_pts,
        sec_filing=sec_pts,
        technical=tech_pts,
        llm_boost=llm_pts,
        options_flow=options_pts,
        **social_breakdown,
    )
```

Add options summary to the result and the detail followup. Update `CrossReferenceResult` construction in `cross_reference()`:

```python
    result = CrossReferenceResult(
        ticker=ticker,
        breakdown=breakdown,
        catalyst_summary=catalyst.catalyst_summary if catalyst else "",
        catalyst_type=catalyst.catalyst_type if catalyst else "",
        catalyst_sources=catalyst.news_sources if catalyst else [],
        catalyst_urls=catalyst.source_urls if catalyst else [],
        technical=technical,
        other_analysts=other_analysts,
        social_summary=", ".join(social_parts) if social_parts else "",
        sec_summary=sec_summary,
        llm_reasoning=llm_reasoning,
        options=options,
    )
```

Add `options: Optional[OptionsResult] = None` field to `CrossReferenceResult` in `models.py`:

```python
@dataclass
class CrossReferenceResult:
    """Aggregated cross-reference data for detail follow-up."""
    ticker: str
    breakdown: ScoreBreakdown
    catalyst_summary: str
    catalyst_type: str
    catalyst_sources: list[str] = field(default_factory=list)
    catalyst_urls: list[str] = field(default_factory=list)
    technical: Optional[TechnicalResult] = None
    other_analysts: list[str] = field(default_factory=list)
    social_summary: str = ""
    sec_summary: str = ""
    llm_reasoning: str = ""
    options: Optional["OptionsResult"] = None

    @property
    def final_score(self) -> int:
        return self.breakdown.total
```

Update `format_detail_followup` in `alerts/discord.py` to show options data. After the social field block and before the other_analysts block, add:

```python
    if xref.options and xref.options.has_unusual_activity:
        opt = xref.options
        parts_o = []
        if opt.unusual_calls:
            parts_o.append(f"Unusual CALLS (max ratio {opt.max_call_ratio:.1f}x)")
        if opt.unusual_puts:
            parts_o.append(f"Unusual PUTS (max ratio {opt.max_put_ratio:.1f}x)")
        parts_o.append(f"P/C ratio: {opt.put_call_ratio:.2f}")
        fields.append({"name": "Options Flow", "value": "\n".join(parts_o), "inline": False})
```

Also add `options_flow` to the breakdown text in `format_detail_followup`:

```python
    if b.options_flow: parts.append(f"options({b.options_flow})")
```

Update `_run_cross_reference_and_followup` in `main.py` to pass the executor:

```python
async def _run_cross_reference_and_followup(
    ticker: str, parsed, msg_id: str, row_id: int
):
    """Background task: run cross-references then send detail follow-up."""
    try:
        xref = await cross_reference(ticker, parsed, executor=_executor)
```

- [ ] **Step 6: Add scoring multiplier to config**

In `config/consensus.yaml`, add under `scoring.multipliers`:

```yaml
      options_flow: 10
```

- [ ] **Step 7: Run tests**

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/test_options.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 8: Run full test suite to check nothing broke**

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: previously passing tests still PASS.

- [ ] **Step 9: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/scanners/options.py consensus_engine/models.py \
        consensus_engine/cross_reference.py consensus_engine/alerts/discord.py \
        consensus_engine/main.py config/consensus.yaml tests/test_options.py
git commit -m "feat: add options flow scanner with yfinance unusual activity detection"
```

---

## Task 5: Delete legacy standalone scripts

**Files:**
- Delete: 12 standalone scripts from workspace root

These scripts pre-date the `consensus_engine` package. Their functionality has been absorbed or superseded. None are imported by the engine.

- [ ] **Step 1: Verify none are imported by the engine**

```bash
cd /root/.openclaw/workspace
grep -r "import catalyst_alert\|import flash_check\|import omni_crawler\|import reddit_crawler\|import trend_engine\|import generate_digest\|import command_handler\|import task_state\|import gnews\|import dds\|import ddg\|import msft_scraper\|import seed_db\|import fetch_nvda\|import reddit\b" consensus_engine/ 2>/dev/null
```

Expected: no output (nothing imports these).

- [ ] **Step 2: Delete the scripts**

```bash
cd /root/.openclaw/workspace
rm catalyst_alert.py command_handler.py db_migrate.py ddg.py dds.py \
   fetch_nvda.py flash_check.py generate_digest.py gnews.py msft_scraper.py \
   omni_crawler.py reddit.py reddit_crawler.py seed_db.py task_state.py trend_engine.py
```

- [ ] **Step 3: Verify workspace root is clean**

```bash
cd /root/.openclaw/workspace
ls *.py 2>/dev/null
```

Expected: no output (no loose `.py` files in workspace root).

- [ ] **Step 4: Run full test suite to confirm nothing broke**

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace
git add -u
git commit -m "chore: delete legacy standalone scripts (absorbed into consensus_engine package)"
```

---

## Final verification

- [ ] **Smoke test the full engine import**

```bash
cd /root/.openclaw/workspace
python3 -m consensus_engine --dry-run --once
```

Expected: engine starts, runs one poll cycle, logs activity, exits cleanly with no ImportErrors.

- [ ] **Full test suite**

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all tests PASS (or same pass rate as before this feature work).

- [ ] **Push to remote**

```bash
cd /root/.openclaw/workspace
git push
```
