"""Unified ticker extraction and validation."""

import re

# Comprehensive blacklist — merged and deduplicated from all existing files
BLACKLIST: set[str] = {
    # Common English words
    "A", "I", "IT", "ON", "IN", "TO", "DO", "BE", "UP", "ALL", "OUT", "FOR", "ARE", "ANY",
    "HAS", "WAS", "NOW", "SEE", "DAY", "BUY", "RUN", "BIG", "MAN", "CAN", "NEW", "ONE",
    "TWO", "SIX", "TEN", "CAR", "JOB", "PAY", "TAX", "THE", "MY", "SO", "AT", "NO", "GO",
    "OR", "AM", "US", "YOU", "SAVE", "HELP", "JUST", "PLUS", "REAL", "OPEN", "LIVE", "TODAY",
    # Corporate / financial acronyms
    "CEO", "CFO", "CTO", "COO", "DD", "EPS", "ROI", "YTD", "SEC", "FED", "GDP", "ATH",
    "OTC", "IPO", "PNL", "PR", "HR", "LLC", "INC", "ETF", "API", "NYSE", "ISIN",
    # Reddit / WSB slang
    "YOLO", "FOMO", "LFG", "WSB", "MOON", "HOLD", "PUMP", "DUMP", "APE", "APES",
    "BULL", "BEAR", "GUH", "TEND", "DFV", "RH", "MAGA", "WIKI",
    # Geopolitics / general
    "USA", "UK", "EU", "UAE",
    # Tech buzzwords that collide
    "AI", "EV", "AR", "VR", "PC", "TV",
    # Two-letter noise
    "CL", "ES", "CC", "UI", "AA", "HL", "IP", "FM", "PL", "IG", "CD", "EA", "RR",
    "VG", "SF", "RS", "IQ",
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
