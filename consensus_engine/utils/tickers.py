"""Unified ticker extraction and validation."""

import re

# Comprehensive blacklist — merged and deduplicated from all existing files
BLACKLIST: set[str] = {
    # Common English words
    "A", "I", "IT", "ON", "IN", "TO", "DO", "BE", "UP", "ALL", "OUT", "FOR", "ARE", "ANY",
    "HAS", "WAS", "NOW", "SEE", "DAY", "BUY", "RUN", "BIG", "MAN", "CAN", "NEW", "ONE",
    "TWO", "SIX", "TEN", "CAR", "JOB", "PAY", "TAX", "THE", "MY", "SO", "AT", "NO", "GO",
    "OR", "AM", "US", "YOU", "SAVE", "HELP", "JUST", "PLUS", "REAL", "OPEN", "LIVE", "TODAY",
    # Additional common English words
    "ADD", "RAN", "SET", "OLD", "LOW", "HOT", "OUR", "HIS", "HER", "OWN", "WAY", "GOT",
    "HIT", "LET", "PUT", "SAY", "SHE", "TOO", "USE", "HIM", "HOW", "ITS", "MAY", "OIL",
    "AGE", "AGO", "AID", "AIM", "AIR", "ARM", "ASK", "ATE", "BAD", "BAR", "BED", "BIT",
    "BOX", "BOY", "BUS", "BUT", "CUT", "DID", "DIG", "DOG", "DRY", "EAR", "EAT", "END",
    "ERA", "EYE", "FAR", "FAT", "FEW", "FIT", "FLY", "GAP", "GAS", "GOD", "GUN",
    "HAD", "HAT", "ICE", "ILL", "KEY", "LAY", "LED", "LEG", "LIE", "LOT", "MAP", "MET",
    "MIX", "MOM", "MUD", "NET", "NOR", "NOT", "NUT", "ODD",
    # Corporate / financial acronyms
    "CEO", "CFO", "CTO", "COO", "DD", "EPS", "ROI", "YTD", "SEC", "FED", "GDP", "ATH",
    "OTC", "IPO", "PNL", "PR", "HR", "LLC", "INC", "ETF", "API", "NYSE", "ISIN",
    # More corporate/financial
    "IOT", "CPI", "PMI", "ISM",
    # Reddit / WSB slang
    "YOLO", "FOMO", "LFG", "WSB", "MOON", "HOLD", "PUMP", "DUMP", "APE", "APES",
    "BULL", "BEAR", "GUH", "TEND", "DFV", "RH", "MAGA", "WIKI",
    # Geopolitics / general
    "USA", "UK", "EU", "UAE",
    # Geopolitics additions
    "IMF", "WHO", "NATO", "FBI", "NSA", "CNN", "PBS", "NPR", "EPA", "IRS", "DOJ", "FDA",
    "BBC", "CIA",
    # Tech buzzwords that collide
    "AI", "EV", "AR", "VR", "PC", "TV",
    # Tech additions
    "OS",
    # Two-letter noise
    "CL", "ES", "CC", "UI", "AA", "HL", "IP", "FM", "PL", "IG", "CD", "EA", "RR",
    "VG", "SF", "RS", "IQ",
    # Two-letter additions
    "AL", "CO", "CF", "BK", "RE", "BA",
    # Three-letter noise
    "AAA", "ABC", "ACE", "ACT", "ATR", "AVG",
    "BAN", "BAT", "BDC", "BNO", "BATL",
    "CAB", "CAP", "CBOE", "CORN",
    "DIP", "DUE",
    "FUN", "GIG",
    "MAX", "MIN", "MOB",
    "OPT", "ORE",
    "POP", "PRO",
    "RAW", "RIG", "ROW",
    "SAP", "SUM", "SUB",
    "TIP", "TOP",
    "VIA", "WAR", "WEB", "WIN", "ZAP",
    # Common tickers that are too noisy to track (index-like, or generate false positives)
    "SPY", "QQQ", "JOSE",
}

_TICKER_PATTERN = re.compile(r'(?<!\w)\$([A-Z]{1,5})(?!\w)|(?<!\w)([A-Z]{2,5})(?!\w)')


def extract_tickers(text: str) -> set[str]:
    """Extract stock tickers from text.

    Matches both $TICKER and plain TICKER formats.
    Filters against blacklist and validates format.
    """
    matches = _TICKER_PATTERN.findall(text)
    tickers = set()
    for dollar_match, plain_match in matches:
        ticker = dollar_match or plain_match
        if ticker and ticker not in BLACKLIST and not ticker.isdigit():
            tickers.add(ticker)
    return tickers


def is_valid_ticker(ticker: str) -> bool:
    """Check if a string looks like a valid ticker symbol."""
    if not ticker or len(ticker) < 1 or len(ticker) > 5:
        return False
    if not ticker.isalpha() or not ticker.isupper():
        return False
    if ticker in BLACKLIST:
        return False
    return True


async def validate_ticker_market_cap(ticker: str) -> bool:
    """Check if a ticker has sufficient market cap ($100M+).

    Uses cached metadata from DB. If not cached, fetches from Finnhub
    and caches the result.
    """
    from consensus_engine import db, config as cfg

    min_cap = cfg.get("ticker_validation.min_market_cap", 100_000_000)
    max_age = cfg.get("ticker_validation.cache_ttl_days", 7)

    meta = await db.get_ticker_metadata(ticker, max_age_days=max_age)
    if meta is not None:
        return meta["market_cap"] >= min_cap

    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return True

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            url = "https://finnhub.io/api/v1/stock/profile2"
            params = {"symbol": ticker, "token": api_key}
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return True
                data = await resp.json()

        name = data.get("name", "")
        market_cap = data.get("marketCapitalization", 0) * 1_000_000
        exchange = data.get("exchange", "")

        if not name:
            await db.cache_ticker_metadata(ticker, "", 0, "")
            return False

        await db.cache_ticker_metadata(ticker, name, market_cap, exchange)
        return market_cap >= min_cap

    except Exception:
        return True
