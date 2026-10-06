"""Recent news headlines for one ticker from Google News RSS (free, no key).

Feeds the Custom Stock Analysis write-up and the assistant (owner report 2026-10-06:
"a few generic comments about price, and nothing else. No recent news or other catalysts").
"""
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import time
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


async def headlines(ticker, *, limit=8, clock=time.time):
    """Never raises: a news outage leaves the analysis without news, nothing else."""
    params = {'q': f'{ticker} stock when:7d', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8), trust_env=False) as session:
            async with session.get(FEED, params=params, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=False) as response:
                if response.status != 200: return []
                body = bytearray()  # One read() returns only the first chunk; read to the end.
                while chunk := await response.content.read(65536):
                    body.extend(chunk)
                    if len(body) > 1_000_000: return []
        return parse(body.decode('utf-8', 'replace'), now=clock(), limit=limit)
    except Exception:
        return []
