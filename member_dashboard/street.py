"""Wall Street view of one ticker from Nasdaq's public data (free, no key): company name,
analyst price targets and ratings, next earnings date. Feeds the analysis's one-year outlook.
Never raises: missing data leaves the fields empty, never guessed."""
from dataclasses import dataclass
from datetime import datetime
import asyncio
import json
import re

import aiohttp

BASE = 'https://api.nasdaq.com/api'
_HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
            'Accept': 'application/json'}


@dataclass(frozen=True)
class Street:
    company: str = ''
    target_average: float | None = None
    target_low: float | None = None
    target_high: float | None = None
    buy: int | None = None
    hold: int | None = None
    sell: int | None = None
    earnings_date: str | None = None  # ISO date


def _price(value):
    try: value = float(str(value).replace('$', '').replace(',', ''))
    except (TypeError, ValueError): return None
    return value if value > 0 else None


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def parse(info, target, earnings):
    company = ((info or {}).get('data') or {}).get('companyName') or ''
    consensus = (((target or {}).get('data') or {}).get('consensusOverview')) or {}
    text = (((earnings or {}).get('data') or {}).get('reportText')) or ''
    found = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
    try: when = datetime(int(found[3]), int(found[1]), int(found[2])).date().isoformat() if found else None
    except ValueError: when = None
    return Street(str(company)[:120], _price(consensus.get('priceTarget')), _price(consensus.get('lowPriceTarget')),
                  _price(consensus.get('highPriceTarget')), _count(consensus.get('buy')), _count(consensus.get('hold')),
                  _count(consensus.get('sell')), when)


async def street(ticker):
    async def get(session, path):
        try:
            async with session.get(BASE + path, headers=_HEADERS, allow_redirects=False) as response:
                if response.status != 200: return None
                body = bytearray()
                while chunk := await response.content.read(65536):
                    body.extend(chunk)
                    if len(body) > 500_000: return None
            return json.loads(body)
        except Exception:
            return None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10), trust_env=False) as session:
            symbol = ticker.lower()
            info, target, earnings = await asyncio.gather(
                get(session, f'/quote/{symbol}/info?assetclass=stocks'), get(session, f'/analyst/{symbol}/targetprice'),
                get(session, f'/analyst/{symbol}/earnings-date'))
        return parse(info, target, earnings)
    except Exception:
        return Street()
