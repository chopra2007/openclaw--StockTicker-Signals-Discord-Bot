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
    # Exchange / venue names (mentioned as organizations, not stocks)
    "CME", "OPRA", "CBOE", "CBOT", "NYMEX", "COMEX", "NASDAQ",
    # Reddit / WSB slang
    "YOLO", "FOMO", "LFG", "WSB", "MOON", "HOLD", "PUMP", "DUMP", "APE", "APES",
    "BULL", "BEAR", "GUH", "TEND", "DFV", "RH", "MAGA", "WIKI",
    # Direction words — never a ticker in a tweet/transcript (bullish/bearish is
    # a separate concept handled in analysis/technical.py, not this blacklist).
    "SHORT", "LONG",
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
    # Technical indicator names (NOT tickers)
    "RSI", "EMA", "MACD", "VWAP", "SMA", "RVOL", "DOJI",
    "BOLL", "MFI", "OBV", "ADX", "CCI", "DMI", "SAR", "ROC",
    "WMA", "HMA", "TEMA", "KAMA", "PPO", "TSI", "CMF", "EMV",
    # Financial acronyms that collide with tickers
    "IRA", "DTE", "VOO", "DOW", "ROTH", "ESPP", "HSA",
    # Common tickers that are too noisy to track (index-like, or generate false positives)
    "SPY", "QQQ", "JOSE",
}

# Known institution names whose ticker symbols should be excluded when full name appears
_INSTITUTION_TICKERS = {
    "MS": ["morgan stanley"],
    "GS": ["goldman sachs"],
    "JPM": ["jp morgan", "jpmorgan", "chase"],
    "C": ["citigroup", "citi"],
    "BAC": ["bank of america", "bofa"],
    "WFC": ["wells fargo"],
    "BLK": ["blackrock"],
    "SCHW": ["charles schwab"],
    "AXP": ["american express"],
    "CS": ["credit suisse"],
    "UBS": ["ubs"],
    "DB": ["deutsche bank"],
}

_TICKER_PATTERN = re.compile(r'(?<!\w)\$([A-Z]{1,5})(?!\w)|(?<!\w)([A-Z]{2,5})(?!\w)')


def extract_tickers(text: str) -> set[str]:
    """Extract stock tickers from text.

    Matches both $TICKER and plain TICKER formats.
    Filters against blacklist and validates format.
    Excludes tickers that appear as part of known institution names.
    """
    import logging
    log = logging.getLogger("tickers")
    matches = _TICKER_PATTERN.findall(text)
    tickers = set()
    text_lower = text.lower()
    
    for dollar_match, plain_match in matches:
        ticker = dollar_match or plain_match
        if ticker and ticker not in BLACKLIST and not ticker.isdigit():
            # Skip if ticker matches institution name in text
            if ticker in _INSTITUTION_TICKERS:
                for phrase in _INSTITUTION_TICKERS[ticker]:
                    if phrase in text_lower:
                        log.debug(f"Skipping {ticker} - appears as institution: {phrase}")
                        break
                else:
                    tickers.add(ticker)
            else:
                tickers.add(ticker)
    return tickers


def is_valid_ticker_format(ticker: str) -> bool:
    """Format-only check: 1-5 uppercase letters, no BLACKLIST filter.

    Use this for EXPLICIT user commands (e.g. `!all SPY`) where the user
    has clearly named a ticker. The BLACKLIST in is_valid_ticker exists
    to suppress false positives during text-extraction (scanning tweets,
    transcripts, etc.) where strings like SPY / QQQ / ETF would mostly
    appear in non-ticker contexts. When the user types the ticker
    directly, that ambiguity doesn't exist — accept it."""
    if not ticker or len(ticker) < 1 or len(ticker) > 5:
        return False
    if not ticker.isalpha() or not ticker.isupper():
        return False
    return True


def is_valid_ticker(ticker: str) -> bool:
    """Strict: format + BLACKLIST. Use for ticker EXTRACTION from arbitrary text.

    For explicit user commands, prefer is_valid_ticker_format() — that one
    skips the BLACKLIST so users can ask about ETFs and similar tickers
    that the extraction filter intentionally suppresses."""
    if not is_valid_ticker_format(ticker):
        return False
    if ticker in BLACKLIST:
        return False
    return True


# ---------------------------------------------------------------------------
# Conversational (@-mention / !ask) ticker anchoring — TODO #35.
# The scanner BLACKLIST above is tuned for tweet/transcript EXTRACTION, where
# index ETFs and word-homographs are mostly noise. It is WRONG for chat: it
# blocks SPY/QQQ/GAP, which are perfectly valid chat questions. So the chat lane
# gets its OWN, much smaller policy.
#
#  - GRAMMAR words ("it", "on", "all", "the", "for"...) only anchor when the user
#    is explicit ($-prefixed) — otherwise "is that ALL" would wrongly become Allstate.
#  - SOFT tokens (WEN="when", FED, CPI, AI, EV...) anchor SOFTLY (advisory: "if X
#    here is a stock it's <Company>, else answer normally") and only when explicit
#    or the message looks stock-focused.
#  - Everything else that resolves to a real listed company (APP=Applovin,
#    GAP=Gap, SPY, QQQ, NVDA, WEN→only soft, ...) anchors normally.
# The Finnhub/cache non-empty-name gate is the final "is it a real company" check.

# Common English / grammar words and bare tech acronyms that are almost never meant as
# the ticker in chat — only anchor these when the user is explicit ($-prefixed).
_CHAT_GRAMMAR_WORDS: set[str] = {
    "A", "I", "IT", "ON", "IN", "TO", "DO", "BE", "UP", "ALL", "OUT", "FOR", "ARE",
    "ANY", "THE", "AND", "BUT", "NOT", "NOW", "NEW", "OUR", "HIS", "HER", "HAS", "WAS",
    "CAN", "ONE", "TWO", "SEE", "WHO", "WHY", "HOW", "YOU", "US", "MY", "SO", "AT",
    "NO", "GO", "OR", "AM", "ADD", "BUY", "TOP", "DAY", "USE", "GET", "GOT", "LET",
    "PUT", "SAY", "OLD", "LOW", "HOT", "OWN", "WAY", "HAD", "HAT", "TOO", "FAR", "FEW",
    "BIG", "MAN", "RUN", "SET", "END", "EAT", "FIT", "FLY", "SIX", "TEN", "JOB", "PAY",
    "THIS", "THAT", "WHAT", "WHEN", "JUST", "SAVE", "HELP", "REAL", "OPEN", "LIVE",
    "AI", "EV", "AR", "VR", "OS", "PC", "TV",   # bare tech acronyms — topic words, not tickers
}
# Tradeable but slang/ambiguous tokens (WEN="when" meme; FED/CPI/... macro acronyms).
# Anchored SOFTLY (advisory: "if a stock, it's <Co>, else answer normally"), which is
# safe in both "tell me about WEN" (-> Wendy's) and "WEN moon?" (crypto). The Finnhub
# non-empty-name gate drops the acronyms that aren't real listed companies (FED, CPI...).
_CHAT_SOFT_WORDS: set[str] = {
    "WEN", "FED", "CPI", "PMI", "GDP", "ATH", "IPO", "CEO", "CFO", "ETF",
    "OIL", "GAS", "ICE", "KEY", "MAP", "WAR", "WEB", "WIN",
}


async def resolve_chat_ticker_anchors(text: str, cap: int = 5) -> list[dict]:
    """Resolve ticker-shaped tokens in a chat message to real companies for prompt
    anchoring. Returns up to `cap` dicts {symbol, name, exchange, soft}. Pure read —
    only a cached lookup + (on a miss) one Finnhub profile call that also warms the cache."""
    from consensus_engine import db

    if not text:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for dollar_match, plain_match in _TICKER_PATTERN.findall(text):
        sym = dollar_match or plain_match
        explicit = bool(dollar_match)
        if not sym or sym in seen or not is_valid_ticker_format(sym):
            continue
        if sym in _CHAT_GRAMMAR_WORDS and not explicit:
            continue  # "is that ALL" must not become Allstate; "AI" stays a topic word
        soft = sym in _CHAT_SOFT_WORDS
        # soft tokens anchor ADVISORILY whenever they resolve (no stock-context gate —
        # the advisory phrasing + the real-company gate below are the safety mechanism).
        # resolve to a real listed company (cache first, then one Finnhub call)
        meta = await db.get_ticker_metadata(sym, max_age_days=7)
        if meta is None:
            try:
                await validate_ticker_market_cap(sym)  # warms the cache (name+exchange)
            except Exception:
                pass
            meta = await db.get_ticker_metadata(sym, max_age_days=7)
        name = (meta or {}).get("name") or ""
        if not name:
            continue  # not a real listed company -> don't anchor
        seen.add(sym)
        out.append({"symbol": sym, "name": name,
                    "exchange": (meta or {}).get("exchange") or "", "soft": soft})
        if len(out) >= cap:
            break
    return out


def format_ticker_anchor(anchors: list[dict]) -> str:
    """Render resolved anchors into a steering-prompt block. '' when there are none
    (so the template is unchanged for normal questions)."""
    if not anchors:
        return ""
    hard = [a for a in anchors if not a["soft"]]
    soft = [a for a in anchors if a["soft"]]
    lines = ["\nTicker context — uppercase tokens in the user's message that are STOCK SYMBOLS. "
             "Answer about the company/stock, not a same-spelled brand/product/word:"]
    for a in hard:
        exch = f", {a['exchange']}" if a["exchange"] else ""
        lines.append(f"  {a['symbol']} = {a['name']}{exch}")
    for a in soft:
        exch = f", {a['exchange']}" if a["exchange"] else ""
        lines.append(f"  {a['symbol']} = IF the user means a stock here, it is {a['name']}{exch} "
                     f"— otherwise answer normally.")
    return "\n".join(lines)


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
        return False

    try:
        import aiohttp
        from consensus_engine.utils.http import get_session
        session = await get_session()
        url = "https://finnhub.io/api/v1/stock/profile2"
        params = {"symbol": ticker, "token": api_key}
        async with session.get(url, params=params,
                               timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return False
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
        return False
