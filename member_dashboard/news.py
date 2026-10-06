"""Recent news headlines for one ticker from Google News RSS (free, no key).

Feeds the Custom Stock Analysis write-up and the assistant (owner report 2026-10-06:
"a few generic comments about price, and nothing else. No recent news or other catalysts").
"""
from dataclasses import dataclass
from dataclasses import replace
from email.utils import parsedate_to_datetime
import asyncio
import json
import re
import time
from urllib.parse import quote, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import aiohttp

WINDOW = 7 * 86400
FEED = 'https://news.google.com/rss/search'


@dataclass(frozen=True)
class Headline:
    title: str
    source: str
    published: float
    url: str


def parse(xml_text, *, now, limit=8):
    """Newest-first headlines from the last 7 days; duplicates and blanks dropped."""
    if '<!DOCTYPE' in xml_text.upper() or '<!ENTITY' in xml_text.upper(): return []
    rows, seen = [], set()
    for item in ET.fromstring(xml_text).iter('item'):
        title = ' '.join((item.findtext('title') or '').split())
        source = ' '.join((item.findtext('source') or '').split())
        if source and title.endswith(' - ' + source): title = title[:-len(source) - 3]
        try: published = parsedate_to_datetime(item.findtext('pubDate') or '').timestamp()
        except (TypeError, ValueError): continue
        link = (item.findtext('link') or '').strip()
        key = title.lower()
        if not title or key in seen or not now - WINDOW <= published <= now + 3600 or not link.startswith('https://'): continue
        seen.add(key)
        rows.append(Headline(title[:300], source[:80], published, link[:2048]))
    rows.sort(key=lambda row: row.published, reverse=True)
    return rows[:limit]


def article_url(value):
    """A plain https article link (no login, port or tracking query), else None."""
    try:
        parts = urlsplit(value or '')
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
                or parts.port not in (None, 443) or len(value) > 2048
                or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            return None
        return urlunsplit(('https', parts.hostname, parts.path or '/', '', ''))
    except ValueError:
        return None


_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Cookie': 'CONSENT=YES+cb; SOCS=CAI'}  # Skips the EU consent page.


async def _publisher_link(session, url):
    """Google News links are redirects; ask Google for the real article address (owner: links must open
    the article). Two small requests; on any failure the Google link is kept."""
    try:
        gid = urlsplit(url).path.rsplit('/', 1)[1]
        async with session.get('https://news.google.com/articles/' + gid, headers=_HEADERS, max_redirects=3) as page:
            if page.status != 200 or urlsplit(str(page.url)).hostname != 'news.google.com': return url
            html = (await page.read()).decode('utf-8', 'replace')
        sig, stamp = re.search(r'data-n-a-sg="([^"]+)"', html), re.search(r'data-n-a-ts="(\d+)"', html)
        if not sig or not stamp: return url
        inner = json.dumps(['garturlreq', [['X', 'X', ['X', 'X'], None, None, 1, 1, 'US:en', None, 1, None, None, None, None, None, 0, 1],
                                           'X', 'X', 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], gid, int(stamp.group(1)), sig.group(1)])
        body = 'f.req=' + quote(json.dumps([[['Fbv4je', inner, None, 'generic']]]))
        async with session.post('https://news.google.com/_/DotsSplashUi/data/batchexecute', data=body, allow_redirects=False,
                                headers={**_HEADERS, 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'}) as answer:
            text = (await answer.read()).decode('utf-8', 'replace') if answer.status == 200 else ''
        real = json.loads(json.loads(text.split('\n\n', 1)[1])[0][2])[1]
        return article_url(real) or url
    except Exception:
        return url


async def headlines(ticker, *, limit=8, clock=time.time):
    """Never raises: a news outage leaves the analysis without news, nothing else."""
    params = {'q': f'{ticker} stock when:7d', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12), trust_env=False) as session:
            async with session.get(FEED, params=params, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=False) as response:
                if response.status != 200: return []
                body = bytearray()  # One read() returns only the first chunk; read to the end.
                while chunk := await response.content.read(65536):
                    body.extend(chunk)
                    if len(body) > 1_000_000: return []
            rows = parse(body.decode('utf-8', 'replace'), now=clock(), limit=limit)
            links = await asyncio.gather(*(_publisher_link(session, row.url) for row in rows[:5]))
        return [replace(row, url=link) for row, link in zip(rows, links)] + rows[5:]
    except Exception:
        return []
