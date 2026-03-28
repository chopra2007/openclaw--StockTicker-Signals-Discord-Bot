"""Reddit trend pipeline.

Fetches recent posts from finance subreddits, extracts tickers,
computes momentum metrics, and returns trending tickers.
"""

import asyncio
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
    """Compute per-ticker mention count and unique authors from a post list.

    Each post dict must have keys: ticker, author, created_utc.
    Returns {ticker: {mentions, unique_authors, momentum}}.
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
    """Fetch recent posts from a subreddit using Reddit's public RSS feed."""
    import xml.etree.ElementTree as ET

    url = f"https://www.reddit.com/r/{subreddit}/new/.rss"
    headers = {"User-Agent": "OpenClaw/1.0 (stock trend engine)"}
    try:
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("Reddit r/%s returned %d", subreddit, resp.status)
                return []
            xml_text = await resp.text()

        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)

        posts = []
        for entry in entries[:limit]:
            title_el = entry.find("atom:title", ns)
            content_el = entry.find("atom:content", ns)
            author_el = entry.find("atom:author/atom:name", ns)
            updated_el = entry.find("atom:updated", ns)
            id_el = entry.find("atom:id", ns)

            title = title_el.text if title_el is not None and title_el.text else ""
            content = content_el.text if content_el is not None and content_el.text else ""
            author = author_el.text.lstrip("/u/") if author_el is not None and author_el.text else ""
            raw_id = id_el.text if id_el is not None and id_el.text else ""
            parts = raw_id.rstrip("/").split("/")
            post_id = parts[-1] if parts else ""

            posts.append({
                "id": post_id,
                "subreddit": subreddit,
                "title": title,
                "selftext": content,
                "author": author,
                "score": 0,
                "num_comments": 0,
                "created_utc": int(time.time()),
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
