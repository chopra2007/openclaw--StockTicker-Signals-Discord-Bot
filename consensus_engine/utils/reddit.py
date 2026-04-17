"""Reddit fetcher: OAuth API (client_credentials) with RSS fallback.

OAuth setup (free):
  1. Go to https://www.reddit.com/prefs/apps → create a "script" app
  2. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env
  3. No user account needed — client_credentials grant reads public data

Without credentials: falls back to RSS (100 posts/subreddit, no scores).
With credentials: OAuth API (up to 1000 posts, includes score + comment count).
"""

import asyncio
import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

import aiohttp

from consensus_engine import config as cfg

log = logging.getLogger("consensus_engine.utils.reddit")

_USER_AGENT = "OpenClaw/1.0 (stock trend engine; contact chopra2007@gmail.com)"

_token: Optional[str] = None
_token_expiry: float = 0.0

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    text = _HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


async def _get_oauth_token(session: aiohttp.ClientSession) -> Optional[str]:
    """Fetch or return cached OAuth token (1h TTL)."""
    global _token, _token_expiry

    client_id = cfg.get_api_key("reddit_client_id")
    client_secret = cfg.get_api_key("reddit_client_secret")
    if not client_id or not client_secret:
        return None

    now = time.time()
    if _token and now < _token_expiry - 60:
        return _token

    try:
        async with session.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=aiohttp.BasicAuth(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": _USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                log.warning("Reddit OAuth token request failed: %d", resp.status)
                return None
            data = await resp.json()
            _token = data.get("access_token")
            _token_expiry = now + data.get("expires_in", 3600)
            log.debug("Reddit OAuth token obtained")
            return _token
    except Exception as e:
        log.warning("Reddit OAuth token error: %s", e)
        return None


async def fetch_subreddit_posts(
    session: aiohttp.ClientSession,
    subreddit: str,
    limit: int = 100,
) -> list[dict]:
    """Fetch recent posts. OAuth if credentials set, RSS otherwise."""
    token = await _get_oauth_token(session)
    if token:
        return await _fetch_via_oauth(session, subreddit, limit, token)
    return await _fetch_via_rss(session, subreddit, min(limit, 100))


async def _fetch_via_oauth(
    session: aiohttp.ClientSession,
    subreddit: str,
    limit: int,
    token: str,
) -> list[dict]:
    """Fetch via OAuth API — full post data including scores, pagination."""
    headers = {"Authorization": f"Bearer {token}", "User-Agent": _USER_AGENT}
    posts: list[dict] = []
    after: Optional[str] = None

    while len(posts) < limit:
        params: dict = {"limit": min(100, limit - len(posts)), "raw_json": "1"}
        if after:
            params["after"] = after

        try:
            async with session.get(
                f"https://oauth.reddit.com/r/{subreddit}/new",
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 401:
                    global _token, _token_expiry
                    _token, _token_expiry = None, 0.0
                    log.warning("Reddit OAuth token expired mid-fetch, invalidated")
                    break
                if resp.status != 200:
                    log.warning("Reddit OAuth r/%s returned %d", subreddit, resp.status)
                    break
                data = await resp.json()
        except Exception as e:
            log.warning("Reddit OAuth fetch error r/%s: %s", subreddit, e)
            break

        children = data.get("data", {}).get("children", [])
        if not children:
            break

        for child in children:
            p = child.get("data", {})
            posts.append({
                "id": p.get("id", ""),
                "subreddit": subreddit,
                "title": p.get("title", ""),
                "selftext": p.get("selftext", ""),
                "author": p.get("author", ""),
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "created_utc": int(p.get("created_utc", time.time())),
                "url": p.get("url", ""),
            })

        after = data.get("data", {}).get("after")
        if not after or len(children) < 100:
            break
        await asyncio.sleep(0.5)

    log.debug("Reddit OAuth r/%s: %d posts fetched", subreddit, len(posts))
    return posts


async def _fetch_via_rss(
    session: aiohttp.ClientSession,
    subreddit: str,
    limit: int = 100,
) -> list[dict]:
    """Fetch via public RSS feed — no credentials, up to 100 posts, no scores."""
    url = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit={limit}"
    try:
        async with session.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                log.warning("Reddit RSS r/%s returned %d", subreddit, resp.status)
                return []
            xml_text = await resp.text()
    except Exception as e:
        log.warning("Reddit RSS error r/%s: %s", subreddit, e)
        return []

    try:
        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        posts = []
        for entry in entries[:limit]:
            title_el = entry.find("atom:title", ns)
            content_el = entry.find("atom:content", ns)
            author_el = entry.find("atom:author/atom:name", ns)
            id_el = entry.find("atom:id", ns)

            title = title_el.text if title_el is not None and title_el.text else ""
            content = _strip_html(content_el.text) if content_el is not None and content_el.text else ""
            author = author_el.text.lstrip("/u/") if author_el is not None and author_el.text else ""
            raw_id = id_el.text if id_el is not None else ""
            post_id = raw_id.rstrip("/").split("/")[-1] if raw_id else ""

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
        log.debug("Reddit RSS r/%s: %d posts fetched", subreddit, len(posts))
        return posts
    except Exception as e:
        log.warning("Reddit RSS parse error r/%s: %s", subreddit, e)
        return []
