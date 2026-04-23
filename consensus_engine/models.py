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
    SEC_FILING = "sec_filing"
    YOUTUBE = "youtube"


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
    image_url: Optional[str] = None
    image_urls: list[str] = field(default_factory=list)
    vision_outputs: list[dict] = field(default_factory=list)
    final_signal: Optional[dict] = None
    avatar_url: Optional[str] = None
    display_name: Optional[str] = None
    discord_source_link: Optional[str] = None
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
    options_flow: int = 0

    @property
    def total(self) -> int:
        return (self.base + self.additional_analysts + self.news_catalyst
                + self.sec_filing + self.social_apewisdom + self.social_stocktwits
                + self.social_reddit + self.google_trends + self.technical
                + self.llm_boost + self.options_flow)


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
    sec_summary: str = ""
    llm_reasoning: str = ""
    options: Optional["OptionsResult"] = None
    # Reliability engine fields (populated by cross_reference.py, default-safe)
    reliability_decision: str = ""          # ALERT/WATCHLIST/IGNORE/UNCERTAIN/INSUFFICIENT_EVIDENCE/DEGRADED_MODE
    contradiction_index: float = 0.0        # 0=unanimous, 1=perfectly split
    reliability_weights: dict = field(default_factory=dict)  # per-source-type weight
    suppressed: bool = False                # True when reliability gate blocks the alert

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


@dataclass
class OptionsResult:
    """Unusual options activity detected for a ticker."""
    ticker: str
    unusual_calls: bool = False
    unusual_puts: bool = False
    max_call_ratio: float = 0.0   # max volume/OI ratio across calls
    max_put_ratio: float = 0.0    # max volume/OI ratio across puts
    put_call_ratio: float = 0.0   # total put volume / total call volume
    top_contract: str = ""        # contractSymbol with highest unusual ratio

    @property
    def has_unusual_activity(self) -> bool:
        return self.unusual_calls or self.unusual_puts


# ---------------------------------------------------------------------------
# YouTube video analysis models
# ---------------------------------------------------------------------------

# Taxonomy constants — decoupled from LLM prompt so validators and the
# deterministic classifier can share a single source of truth.
LEVEL_TYPES = ("support", "resistance", "target", "breakdown", "ema", "ma")
SETUP_TYPES = ("breakout", "pullback", "earnings", "trend", "reversal")
CATALYST_TYPES = ("earnings", "fed", "cpi", "jobs", "other")


@dataclass
class PriceLevel:
    """Extracted support/resistance level from YouTube video."""
    ticker: str
    level_type: str  # support|resistance|target|breakdown|ema|ma
    price: float
    condition: str  # "if holds above 640"
    consequence: str  # "rally to 700"
    confidence: float  # 0.0-1.0
    video_timestamp_sec: int | None = None
    evidence_span_ids: list[int] = field(default_factory=list)
    classifier_confidence: float = 1.0


@dataclass
class MacroThesis:
    """Macro analysis extracted from YouTube video."""
    direction: Direction  # bullish|bearish|neutral
    themes: list[str]  # ["recession risk", "Fed pivot expected"]
    timeframe: str  # short|medium|long
    summary: str  # one paragraph
    narrative: str = ""


@dataclass
class VideoOptionIdea:
    """Options trade idea extracted from a YouTube video."""
    ticker: str
    option_type: str        # call|put
    strike: float | None
    expiry: str | None
    strategy: str | None    # single|spread|leaps|debit|credit
    source: str | None      # flow_observation|personal_idea
    conviction: str | None  # high|medium|low
    context: str
    source_snippet: str
    chunk_id: int = 0
    video_timestamp_sec: int | None = None
    evidence_span_ids: list[int] = field(default_factory=list)
    classifier_confidence: float | None = None


@dataclass
class VideoTradeSetup:
    """Coherent entry/stop/target trade setup extracted from a YouTube video."""
    ticker: str
    entry_low: float | None
    entry_high: float | None
    stop: float | None
    targets: list[float]
    timeframe: str | None   # intraday|swing|positional|long-term
    setup_type: str | None  # breakout|pullback|earnings|trend|reversal
    context: str
    source_snippet: str
    chunk_id: int = 0
    risk_reward: float | None = None
    video_timestamp_sec: int | None = None
    catalyst_date: str | None = None
    catalyst_desc: str | None = None
    evidence_span_ids: list[int] = field(default_factory=list)
    classifier_confidence: float | None = None


# ---------------------------------------------------------------------------
# v2 two-stage pipeline: evidence-first models
# ---------------------------------------------------------------------------

@dataclass
class EvidenceSpan:
    """One literal quote extracted from a video with structured annotations.

    Produced by Stage A (Gemini evidence extractor). No classification —
    just verbatim transcription with entity tags.
    """
    ts_sec: int
    quote: str
    tickers: list[str] = field(default_factory=list)
    numbers: list[float] = field(default_factory=list)
    dates_mentioned: list[str] = field(default_factory=list)


@dataclass
class EvidenceBundle:
    """Full Stage A output: video metadata + segments + evidence spans."""
    video_id: str
    duration_sec: int | None
    publish_ts: str
    segments: list[dict] = field(default_factory=list)
    spans: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class CandidateSignal:
    """Directional candidate produced by Stage B deterministic classifier."""
    ticker: str
    direction: Direction
    conviction: Conviction
    mention_count: int
    context: str
    evidence_span_ids: list[int] = field(default_factory=list)
    classifier_confidence: float = 0.0
    suppressed: bool = False
    suppression_reason: str | None = None
    video_timestamp_sec: int | None = None


@dataclass
class CandidateLevel:
    """Price-level candidate produced by Stage B deterministic classifier."""
    ticker: str
    level_type: str  # one of LEVEL_TYPES
    price: float
    context: str
    evidence_span_ids: list[int] = field(default_factory=list)
    classifier_confidence: float = 0.0
    suppressed: bool = False
    suppression_reason: str | None = None
    video_timestamp_sec: int | None = None


@dataclass
class CandidateSetup:
    """Entry/stop/target trade setup candidate produced by Stage B."""
    ticker: str
    entry_low: float | None
    entry_high: float | None
    stop: float | None
    targets: list[float]
    timeframe: str | None
    setup_type: str | None  # one of SETUP_TYPES
    catalyst_date: str | None
    catalyst_desc: str | None
    context: str
    evidence_span_ids: list[int] = field(default_factory=list)
    classifier_confidence: float = 0.0
    suppressed: bool = False
    suppression_reason: str | None = None
    video_timestamp_sec: int | None = None
    risk_reward: float | None = None


@dataclass
class CandidateCatalyst:
    """Catalyst candidate with relative-date resolution and verification status.

    `verified`: -1=contradicted by external source, 0=unverified, 1=confirmed.
    """
    ticker: str
    catalyst_type: str  # one of CATALYST_TYPES
    mentioned_date: str
    resolved_date: str | None = None
    verified: int = 0
    context_text: str = ""
    evidence_span_ids: list[int] = field(default_factory=list)
    video_timestamp_sec: int | None = None
    suppressed: bool = False
    suppression_reason: str | None = None


# Back-compat alias for call sites that prefer a video-scoped name.
VideoCatalyst = CandidateCatalyst


@dataclass
class RunTelemetry:
    """Per-run metrics persisted alongside youtube_analysis_runs."""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    json_parse_ok: bool = False
    span_count: int = 0
    filter_drop_count: int = 0


@dataclass
class ParsedVideo:
    """LLM-parsed YouTube video with extracted trade intelligence."""
    video_id: str
    channel_name: str
    raw_transcript: str
    tickers: list[dict]  # [{"symbol": "SPY", "direction": "long", "conviction": "high", "mention_count": 3}]
    price_levels: list[PriceLevel]
    macro_thesis: MacroThesis
    overall_conviction: Conviction
    parsed_at: float = field(default_factory=time.time)
    run_id: int | None = None
    options: list[VideoOptionIdea] = field(default_factory=list)
    setups: list[VideoTradeSetup] = field(default_factory=list)
    catalysts: list[CandidateCatalyst] = field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)
    telemetry: RunTelemetry | None = None

    @property
    def has_tickers(self) -> bool:
        return len(self.tickers) > 0


@dataclass
class YouTubeContext:
    """YouTube signal aggregation for cross-reference integration."""
    mention_count: int
    direction: Direction
    top_conviction: Conviction
    channels: list[str]
    levels: list[dict]  # [{"type": "support", "price": 650.0, "confidence": 0.9}]
    score_boost: int  # +15 for high, +10 for medium, +5 for low
