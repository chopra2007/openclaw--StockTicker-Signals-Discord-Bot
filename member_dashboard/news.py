"""Recent news for one ticker from Bing News and Google News RSS (free, no key).

Feeds the Custom Stock Analysis write-up and the assistant (owner report 2026-10-06:
"a few generic comments about price, and nothing else. No recent news or other catalysts").
Bing gives the publisher's own link and a one-line summary with the facts ("BNP Paribas raised
its price target to $345"); Google adds headlines Bing misses. Google's links stay Google
redirects: resolving them server-side gets this server blocked ("429, unusual traffic").
"""
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import asyncio
import re
import time
from urllib.parse import parse_qs, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import aiohttp

WINDOW = 30 * 86400
FEED = 'https://news.google.com/rss/search'
BING = 'https://www.bing.com/news/search'


def options_story(title):
    """Trading contracts are not company news; ordinary uses of 'puts' remain valid."""
    return bool(re.search(r'\b\d+(?:\.\d+)?\s+(?:call|put)\b|\b[A-Z]{1,6}\d{6}[CP]\d{8}\b|\b(?:call|put)s?\s+options?\b|\boptions?\s+(?:activity|trading|trades?|volume|flow|chain|contracts?|expiration|expiry|strategy|strategies|market|prices?|moves?)\b|\bunusual\s+options?\b|\b(?:calls?|puts?)\s+(?:trading|trades?|volume|contracts?|expiration|expiry)\b', title, re.I))


@dataclass(frozen=True)
class Headline:
    title: str
    source: str
    published: float
    url: str
    summary: str = ''


def parse(xml_text, *, now, limit=8):
    """Newest-first company headlines from the last 30 days."""
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
        if not title or options_story(title) or key in seen or not now - WINDOW <= published <= now + 3600 or not link.startswith('https://'): continue
        seen.add(key)
        rows.append(Headline(title[:300], source[:80], published, link[:2048]))
    rows.sort(key=lambda row: row.published, reverse=True)
    return rows[:limit]


def parse_bing(xml_text, *, now, limit=10):
    """Bing News RSS: the real article address is the `url` query value of Bing's click link."""
    if '<!DOCTYPE' in xml_text.upper() or '<!ENTITY' in xml_text.upper(): return []
    rows, seen = [], set()
    for item in ET.fromstring(xml_text).iter('item'):
        title = ' '.join((item.findtext('title') or '').split())
        summary = ' '.join((item.findtext('description') or '').split())
        source = ' '.join((item.findtext('{*}Source') or '').split()).removesuffix(' on MSN')
        try: published = parsedate_to_datetime(item.findtext('pubDate') or '').timestamp()
        except (TypeError, ValueError): continue
        link = parse_qs(urlsplit((item.findtext('link') or '').strip()).query).get('url', [''])[0]
        link = article_url(link)
        key = title.lower()
        if not title or options_story(title) or not link or key in seen or not now - WINDOW <= published <= now + 3600: continue
        seen.add(key)
        rows.append(Headline(title[:300], source[:80], published, link, summary[:400]))
    rows.sort(key=lambda row: row.published, reverse=True)
    return rows[:limit]


def about(row, ticker, name):
    """Keep stories about this company: the ticker or the company's name is in the title or summary."""
    text = row.title + ' ' + row.summary
    if re.search(rf'(?<![A-Za-z]){re.escape(ticker)}(?![A-Za-z])', text): return True
    first = name.split()[0] if name else ''
    words = [name] + ([first] if len(first) >= 4 and first.lower() not in _GENERIC else [])
    return any(re.search(rf'\b{re.escape(word)}\b', text, re.I) for word in words if word)


# First words too common to identify a company on their own ("Advanced Micro Devices" -> AMD only).
_GENERIC = {'advanced', 'american', 'applied', 'first', 'general', 'global', 'international', 'united', 'national', 'new', 'the'}


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


async def _feed(session, url, params):
    async with session.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=False) as response:
        if response.status != 200: return ''
        body = bytearray()  # One read() returns only the first chunk; read to the end.
        while chunk := await response.content.read(65536):
            body.extend(chunk)
            if len(body) > 1_000_000: return ''
    return body.decode('utf-8', 'replace')


def short_name(company):
    """'Micron Technology, Inc. Common Stock' -> 'Micron Technology' (for search and matching)."""
    name = re.split(r' (?:Common Stock|Class [A-C]|Ordinary Shares|American Depositary)', company or '')[0]
    name = re.sub(r',? (?:Inc\.?|Corporation|Corp\.?|Holdings?|Ltd\.?|plc|N\.V\.|S\.A\.|Co\.?)$', '', name.strip(), flags=re.I)
    return name.strip()


async def headlines(ticker, name='', *, limit=12, clock=time.time):
    """Never raises: a news outage leaves the analysis without news, nothing else."""
    now = clock()
    queries = [f'{ticker} stock'] + ([f'{name} stock', name] if name else [])
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12), trust_env=False) as session:
            async def bing(query):
                try: return parse_bing(await _feed(session, BING, {'q': query, 'format': 'rss', 'mkt': 'en-US', 'qft': 'interval="9"'}), now=now, limit=30)
                except Exception: return []
            async def google():
                try: return parse(await _feed(session, FEED, {'q': f'{name or ticker} when:30d', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'}), now=now, limit=30)
                except Exception: return []
            found = await asyncio.gather(*(bing(query) for query in queries), google())
    except Exception:
        return []
    rows, seen = [], set()
    for row in [row for group in found for row in group]:  # Bing first: it has summaries and direct links.
        key = re.sub(r'[^a-z0-9]', '', row.title.lower())[:60]
        if key in seen or not about(row, ticker, name): continue
        seen.add(key)
        rows.append(row)
    rows.sort(key=lambda row: row.published, reverse=True)
    return rows[:limit]
