"""Data models for the consensus engine pipeline."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class SourceType(str, Enum):
    TWITTER = "twitter"
    REDDIT = "reddit"
    STOCKTWITS = "stocktwits"
    APEWISDOM = "apewisdom"
    GOOGLE_TRENDS = "google_trends"
    NEWS = "news"


class Sentiment(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class TickerSignal:
    """A single signal from any scanner stage."""
    ticker: str
    source_type: SourceType
    source_detail: str  # analyst handle, subreddit, article URL
    raw_text: str
    sentiment: Sentiment = Sentiment.NEUTRAL
    detected_at: float = field(default_factory=time.time)

    @property
    def expires_at(self) -> float:
        """Signals expire after 2 hours by default."""
        return self.detected_at + 7200


@dataclass
class TwitterConsensus:
    """Aggregated Twitter signal for a ticker."""
    ticker: str
    analysts: list[str]
    timestamps: list[float]
    raw_texts: list[str]
    window_minutes: float = 0.0

    @property
    def count(self) -> int:
        return len(self.analysts)

    @property
    def passed(self) -> bool:
        return self.count >= 3 and self.window_minutes <= 30


@dataclass
class SocialConsensus:
    """Aggregated social signal for a ticker."""
    ticker: str
    reddit_mentions: int = 0
    stocktwits_sentiment: Optional[str] = None
    stocktwits_trending: bool = False
    apewisdom_rank: Optional[int] = None
    google_trend_delta: Optional[float] = None
    platforms_confirming: int = 0

    @property
    def passed(self) -> bool:
        return self.platforms_confirming >= 1


@dataclass
class CatalystResult:
    """News catalyst found for a ticker."""
    ticker: str
    catalyst_summary: str
    catalyst_type: str  # e.g. "Earnings Beat", "FDA Approval"
    news_sources: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0-1

    @property
    def passed(self) -> bool:
        return len(self.news_sources) > 0 and self.catalyst_summary != ""


@dataclass
class TechnicalFilter:
    """Result of a single technical filter."""
    name: str
    value: float
    threshold: str  # human-readable threshold description
    passed: bool


@dataclass
class TechnicalResult:
    """Aggregated technical verification for a ticker."""
    ticker: str
    filters: list[TechnicalFilter] = field(default_factory=list)
    price: float = 0.0
    volume: int = 0
    price_change_pct: float = 0.0

    @property
    def all_passed(self) -> bool:
        return len(self.filters) > 0 and all(f.passed for f in self.filters)

    @property
    def passed_count(self) -> int:
        return sum(1 for f in self.filters if f.passed)

    @property
    def total_count(self) -> int:
        return len(self.filters)


@dataclass
class ConsensusResult:
    """Full consensus evaluation for a ticker."""
    ticker: str
    twitter: Optional[TwitterConsensus] = None
    social: Optional[SocialConsensus] = None
    catalyst: Optional[CatalystResult] = None
    technical: Optional[TechnicalResult] = None
    llm_confidence: float = 0.0
    evaluated_at: float = field(default_factory=time.time)

    @property
    def all_gates_passed(self) -> bool:
        return (
            self.twitter is not None and self.twitter.passed
            and self.social is not None and self.social.passed
            and self.catalyst is not None and self.catalyst.passed
            and self.technical is not None and self.technical.all_passed
            and self.llm_confidence >= 70
        )

    def gate_summary(self) -> dict[str, bool]:
        return {
            "twitter": self.twitter is not None and self.twitter.passed,
            "social": self.social is not None and self.social.passed,
            "catalyst": self.catalyst is not None and self.catalyst.passed,
            "technical": self.technical is not None and self.technical.all_passed,
            "llm_confidence": self.llm_confidence >= 70,
        }


@dataclass
class AlertPayload:
    """Ready-to-send Discord alert."""
    ticker: str
    confidence_score: float
    catalyst_summary: str
    catalyst_type: str
    analyst_mentions: list[str]
    analyst_window_minutes: float
    technical: TechnicalResult
    consensus: ConsensusResult
    news_urls: list[str] = field(default_factory=list)
    price: float = 0.0
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Signal-first architecture models
# ---------------------------------------------------------------------------

class TweetType(str, Enum):
    TICKER_CALLOUT = "A"   # Explicit ticker + direction
    MACRO = "B"            # Macro/geopolitical
    OPTIONS_TRADE = "C"    # Options with strike/expiry
    SENTIMENT = "D"        # General market mood


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class Conviction(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_CONVICTION_SCORES = {
    Conviction.HIGH: 30,
    Conviction.MEDIUM: 25,
    Conviction.LOW: 20,
}


@dataclass
class OptionsDetail:
    """Options trade details extracted from a tweet."""
    present: bool = False
    strike: Optional[float] = None
    expiry: Optional[str] = None
    option_type: Optional[str] = None  # "call" or "put"
    target_price: Optional[float] = None
    profit_target_pct: Optional[float] = None


@dataclass
class ParsedTweet:
    """LLM-parsed tweet with extracted trade details."""
    tweet_url: str
    analyst: str
    raw_text: str
    tweet_type: TweetType
    tickers: list[str]
    direction: Direction
    options: Optional[OptionsDetail]
    conviction: Conviction
    summary: str
    parsed_at: float = field(default_factory=time.time)

    @property
    def is_actionable(self) -> bool:
        return self.tweet_type in (TweetType.TICKER_CALLOUT, TweetType.OPTIONS_TRADE)

    @property
    def base_score(self) -> int:
        return _CONVICTION_SCORES.get(self.conviction, 25)


@dataclass
class ScoreBreakdown:
    """Additive score from all cross-reference sources."""
    base: int = 0
    additional_analysts: int = 0
    news_catalyst: int = 0
    sec_filing: int = 0
    social_apewisdom: int = 0
    social_stocktwits: int = 0
    social_reddit: int = 0
    google_trends: int = 0
    technical: int = 0
    llm_boost: int = 0

    @property
    def total(self) -> int:
        return (self.base + self.additional_analysts + self.news_catalyst
                + self.sec_filing + self.social_apewisdom + self.social_stocktwits
                + self.social_reddit + self.google_trends + self.technical
                + self.llm_boost)


@dataclass
class CrossReferenceResult:
    """Aggregated cross-reference data for detail follow-up."""
    ticker: str
    breakdown: ScoreBreakdown
    catalyst_summary: str
    catalyst_type: str
    catalyst_sources: list[str] = field(default_factory=list)
    catalyst_urls: list[str] = field(default_factory=list)
    technical: Optional[TechnicalResult] = None
    other_analysts: list[str] = field(default_factory=list)
    social_summary: str = ""
    llm_reasoning: str = ""

    @property
    def final_score(self) -> int:
        return self.breakdown.total


@dataclass
class AlertMessage:
    """Tracks Discord message IDs for two-phase alerts."""
    ticker: str
    analyst: str
    instant_msg_id: Optional[str] = None
    followup_msg_id: Optional[str] = None
    base_score: int = 0
    final_score: int = 0
    created_at: float = field(default_factory=time.time)
