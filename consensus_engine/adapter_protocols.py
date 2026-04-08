"""Protocol contracts for precision engine adapters."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class FinnhubContext:
    """Market data from Finnhub quote + company news."""
    price: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    prev_close: float = 0.0
    rvol: float = 1.0
    news_headlines: list[str] = field(default_factory=list)
    news_sources: list[str] = field(default_factory=list)
    market_ok: bool = False  # True if price moved meaningfully


@dataclass
class SearchHit:
    """A single search result from Brave/Exa/SerpApi."""
    title: str
    url: str
    source: str  # domain or publisher name
    snippet: str = ""


@dataclass
class FirecrawlPage:
    """Extracted content from a URL via Firecrawl."""
    url: str
    title: str = ""
    text: str = ""
    success: bool = False


@runtime_checkable
class FinnhubProtocol(Protocol):
    async def get_context(self, ticker: str) -> FinnhubContext: ...


@runtime_checkable
class SearchProtocol(Protocol):
    """Common protocol for Brave, Exa, and SerpApi search adapters."""
    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]: ...


@runtime_checkable
class FirecrawlProtocol(Protocol):
    async def extract(self, urls: list[str]) -> list[FirecrawlPage]: ...
