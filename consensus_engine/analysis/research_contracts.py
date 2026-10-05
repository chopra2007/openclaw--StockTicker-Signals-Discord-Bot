"""Typed value contracts shared by bot and restricted research compute."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Literal, Callable, Awaitable, TYPE_CHECKING
from collections.abc import Mapping
from datetime import date
from types import MappingProxyType
import dataclasses
import math
if TYPE_CHECKING:
    from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import (ScoreBreakdown, CatalystResult, TechnicalResult,
                                    OptionsResult, YouTubeContext)


@dataclass(frozen=True)
class ScoreRequest:
    kind: Literal["precision", "sec_graduation", "llm_score", "consolidation", "burst",
                  "finra_volume", "finra_baseline", "short_interest", "pead"]
    arguments: tuple = ()

    def __post_init__(self):
        if self.kind not in {"precision", "sec_graduation", "llm_score", "consolidation",
                            "burst", "finra_volume", "finra_baseline", "short_interest", "pead"}:
            raise ValueError("Unknown score data request")


@dataclass(frozen=True)
class ResearchRequest:
    kind: Literal['sane_levels', 'direction_parity', 'gap_fill', 'smart_shadow',
                  'stage', 'nasdaq', 'pead']
    value: object = None

    def __post_init__(self):
        if self.kind not in {'sane_levels', 'direction_parity', 'gap_fill',
                             'smart_shadow', 'stage', 'nasdaq', 'pead'}:
            raise ValueError('Unknown research data request')


def freeze_value(value):
    """Own a finite JSON value; reject handles, callables and opaque objects."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Research values must be finite")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Research record keys must be strings")
        return MappingProxyType({key: freeze_value(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze_value(item) for item in value)
    raise TypeError("Research records accept values, never operational objects")


def thaw_value(value):
    if isinstance(value, Mapping):
        return {key: thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_value(item) for item in value]
    return value


def _timestamp(value):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError('Observation time must be a finite epoch value or None')


@dataclass(frozen=True)
class CalculationSettings:
    """Immutable calculation-only configuration; no environment or secrets."""
    values: Mapping = field(default_factory=dict)
    min_purchase_dollars: float = 250_000.0

    def __post_init__(self):
        allowed = {'scoring', 'precision_engine', 'all_command', 'features',
                   'options_flow', 'youtube'}
        if set(self.values) - allowed:
            raise ValueError("Non-calculation settings are forbidden")
        object.__setattr__(self, 'values', freeze_value(self.values))
        if type(self.min_purchase_dollars) not in (int, float) or not math.isfinite(self.min_purchase_dollars):
            raise ValueError('The purchase threshold must be finite')

    def get(self, path, default=None):
        value = self.values
        for part in path.split('.'):
            if not isinstance(value, Mapping) or part not in value:
                return default
            value = value[part]
        return value


@dataclass(frozen=True)
class ModelRecord:
    """An immutable allowlisted market model, without arbitrary attributes.

    The existing value models are reconstructed locally so their properties
    remain the sole implementation of passed counts and activity predicates.
    """
    kind: Literal['CatalystResult', 'TechnicalResult', 'OptionsResult', 'YouTubeContext']
    values: Mapping

    def __post_init__(self):
        from consensus_engine.models import TechnicalFilter
        types = {'CatalystResult': CatalystResult, 'TechnicalResult': TechnicalResult,
                 'OptionsResult': OptionsResult, 'YouTubeContext': YouTubeContext}
        if self.kind not in types:
            raise ValueError('Unknown market model')
        allowed = {item.name for item in dataclasses.fields(types[self.kind])}
        if self.kind == 'TechnicalResult':
            allowed |= {'candles', 'candles_raw', 'current_price', 'last_price', 'atr', 'atr_14'}
        if self.kind == 'OptionsResult':
            allowed |= {'expiry', 'nearest_expiry', 'expiry_date'}
        if set(self.values) - allowed:
            raise ValueError('Unknown market model field')
        values = freeze_value(self.values)
        if self.kind == 'TechnicalResult':
            filter_fields = {item.name for item in dataclasses.fields(TechnicalFilter)}
            for row in values.get('filters', ()):
                if not isinstance(row, Mapping) or set(row) != filter_fields:
                    raise ValueError('Invalid technical filter')
            for row in values.get('candles', ()):
                if not isinstance(row, Mapping) or set(row) - {'open', 'high', 'low', 'close', 'volume', 'timestamp', 'date'}:
                    raise ValueError('Invalid candle')
        object.__setattr__(self, 'values', values)

    def model(self):
        from consensus_engine.models import TechnicalFilter, Direction, Conviction
        types = {'CatalystResult': CatalystResult, 'TechnicalResult': TechnicalResult,
                 'OptionsResult': OptionsResult, 'YouTubeContext': YouTubeContext}
        values = thaw_value(self.values)
        if self.kind == 'TechnicalResult':
            values['filters'] = [TechnicalFilter(**row) for row in values.get('filters', [])]
        if self.kind == 'YouTubeContext':
            values['direction'] = Direction(values['direction'])
            values['top_conviction'] = Conviction(values['top_conviction'])
        fields = {item.name for item in dataclasses.fields(types[self.kind])}
        result = types[self.kind](**{key: val for key, val in values.items() if key in fields})
        for key in set(values) - fields:
            setattr(result, key, values[key])
        return result


@dataclass(frozen=True)
class SourceStatus:
    source_id: str
    source_version: str
    status: Literal['completed', 'unavailable', 'failed']
    observed_at: float | None
    message: str | None = None

    def __post_init__(self):
        if not all(isinstance(value, str) and value and len(value) <= 128
                   for value in (self.source_id, self.source_version)):
            raise ValueError('Source identity and version are required')
        if self.status not in {'completed', 'unavailable', 'failed'}:
            raise ValueError('Invalid source status')
        _timestamp(self.observed_at)
        if self.message is not None and (not isinstance(self.message, str) or len(self.message) > 1024):
            raise ValueError('Source message exceeds its bound')


@dataclass(frozen=True)
class ResearchEvidence:
    id: str
    source_id: str
    source_version: str
    observed_at: float | None
    url: str | None
    excerpt: str
    research_only: bool = True

    def __post_init__(self):
        if not all(isinstance(value, str) and value for value in (self.id, self.source_id, self.source_version)):
            raise ValueError('Evidence requires source identity and version')
        if not isinstance(self.excerpt, str) or len(self.excerpt) > 8_000:
            raise ValueError('Evidence excerpt exceeds its bound')
        _timestamp(self.observed_at)
        if self.url is not None and (not isinstance(self.url, str) or len(self.url) > 2048):
            raise ValueError('Evidence URL exceeds its bound')
        if type(self.research_only) is not bool:
            raise TypeError('research_only must be explicit')


@dataclass(frozen=True)
class ConsolidationInput:
    fired: bool = False
    consolidated_id: int | None = None
    effective_n_clusters: int = 0
    combined_log_odds: float = 0.0
    consensus_boost: int = 0
    sources_seen: tuple[str, ...] = ()
    reason: str = 'unavailable'

    def __post_init__(self):
        object.__setattr__(self, 'sources_seen', tuple(self.sources_seen))
        freeze_value(vars(self))


@dataclass(frozen=True)
class ScoreInputs:
    catalyst: ModelRecord | None = None
    technical: ModelRecord | None = None
    options: ModelRecord | None = None
    youtube: ModelRecord | None = None
    sec_hit: bool = False
    sec_summary: str = ''
    aligned_analysts: tuple[str, ...] = ()
    opposing_analysts: tuple[str, ...] = ()
    social_data: Mapping = field(default_factory=dict)
    precision: Mapping = field(default_factory=dict)
    sec_graduation: Mapping | None = None
    llm_score: tuple[float, str] = (0.0, '')
    consolidation: ConsolidationInput = field(default_factory=ConsolidationInput)
    burst_rows: tuple = ()
    finra_volume: Mapping | None = None
    finra_baseline: Mapping | None = None
    short_interest: Mapping | None = None
    pead: Mapping | None = None

    def __post_init__(self):
        expected = {'catalyst': 'CatalystResult', 'technical': 'TechnicalResult',
                    'options': 'OptionsResult', 'youtube': 'YouTubeContext'}
        for name, kind in expected.items():
            value = getattr(self, name)
            if value is not None and (type(value) is not ModelRecord or value.kind != kind):
                raise TypeError('Score inputs require typed immutable market records')
        for name in ('social_data', 'precision', 'sec_graduation', 'burst_rows',
                     'finra_volume', 'finra_baseline', 'short_interest', 'pead',
                     'aligned_analysts', 'opposing_analysts', 'llm_score'):
            object.__setattr__(self, name, freeze_value(getattr(self, name)))
        if type(self.sec_hit) is not bool or not isinstance(self.sec_summary, str):
            raise TypeError('SEC score facts must be values')
        if type(self.consolidation) is not ConsolidationInput:
            raise TypeError('Consolidation must be an explicit value record')


@dataclass(frozen=True)
class ResearchInputs:
    score: ScoreInputs = field(default_factory=ScoreInputs)
    technical_long: ModelRecord | None = None
    technical_short: ModelRecord | None = None
    news_catalyst: ModelRecord | None = None
    options_unusual: ModelRecord | None = None
    youtube_levels: tuple = ()
    daily_candles: tuple = ()
    earnings_date: str | None = None
    company_name: str = ''
    sanity_quote: float | None = None
    evidence: tuple[ResearchEvidence, ...] = ()
    source_statuses: tuple[SourceStatus, ...] = ()

    def __post_init__(self):
        expected = {'technical_long': 'TechnicalResult', 'technical_short': 'TechnicalResult',
                    'news_catalyst': 'CatalystResult', 'options_unusual': 'OptionsResult'}
        for name, kind in expected.items():
            value = getattr(self, name)
            if value is not None and (type(value) is not ModelRecord or value.kind != kind):
                raise TypeError('Research inputs require typed immutable market records')
        for name in ('youtube_levels', 'daily_candles'):
            object.__setattr__(self, name, freeze_value(getattr(self, name)))
        for row in self.youtube_levels:
            if set(row) - {'price', 'level_type', 'type', 'freshness_days', 'confidence',
                           'source_type', 'source_url', 'quote', 'channel', 'video_id',
                           'approved', 'channel_name', 'touches', 'trust_score'}:
                raise ValueError('Unknown public level field')
        for row in self.daily_candles:
            if set(row) - {'open', 'high', 'low', 'close', 'volume', 'timestamp', 'date'}:
                raise ValueError('Unknown candle field')
        if type(self.score) is not ScoreInputs:
            raise TypeError('A typed score input is required')
        for name, cls in (('evidence', ResearchEvidence), ('source_statuses', SourceStatus)):
            rows = tuple(getattr(self, name))
            if any(type(row) is not cls for row in rows):
                raise TypeError('Typed provenance records are required')
            object.__setattr__(self, name, rows)
        if len(self.evidence) > 128 or len(self.source_statuses) > 128:
            raise ValueError('Too many source records')
        _timestamp(self.sanity_quote)
        if not isinstance(self.company_name, str) or len(self.company_name) > 256:
            raise ValueError('Company name exceeds its bound')
        if self.earnings_date is not None and not isinstance(self.earnings_date, str):
            raise TypeError('Earnings date must be a value')


@dataclass(frozen=True)
class ResearchClock:
    epoch: float
    monotonic: float
    pacific_date: date

    def __post_init__(self):
        _timestamp(self.epoch)
        _timestamp(self.monotonic)
        if self.epoch is None or self.monotonic is None or type(self.pacific_date) is not date:
            raise ValueError('Research clock requires explicit epoch, monotonic and Pacific date')


@dataclass(frozen=True)
class GapFillRequest:
    ticker: str
    anchors_count: int
    has_event_date: bool
    direction: str
    deadline: float
    company_name: str = ''
    sector: str = ''


@dataclass(frozen=True)
class GapFillResult:
    harvested_anchors_snippets: tuple[str, ...] = ()
    eight_k_summary_snippets: tuple[str, ...] = ()
    event_date_snippets: tuple[str, ...] = ()
    catalyst_research_snippets: tuple[str, ...] = ()
    macro_risk_snippets: tuple[str, ...] = ()
    evidence: tuple[ResearchEvidence, ...] = ()
    source_statuses: tuple[SourceStatus, ...] = ()

    def __post_init__(self):
        has_text = False
        for name in ('harvested_anchors_snippets', 'eight_k_summary_snippets',
                     'event_date_snippets', 'catalyst_research_snippets', 'macro_risk_snippets'):
            rows = tuple(getattr(self, name))
            if len(rows) > 20 or any(not isinstance(row, str) or len(row) > 8_000 for row in rows):
                raise ValueError('Public gap-fill text exceeds its bound')
            object.__setattr__(self, name, rows)
            has_text |= bool(rows)
        for name, cls in (('evidence', ResearchEvidence), ('source_statuses', SourceStatus)):
            rows = tuple(getattr(self, name))
            if any(type(row) is not cls for row in rows):
                raise TypeError('Gap-fill provenance requires typed source records')
            object.__setattr__(self, name, rows)
        known = {(row.source_id, row.source_version) for row in self.source_statuses
                 if row.status == 'completed'}
        if has_text and (not self.evidence or any((row.source_id, row.source_version) not in known
                                                 for row in self.evidence)):
            raise ValueError('Gap-fill prose needs completed source provenance')


@dataclass(frozen=True)
class SynthesisRequest:
    ticker: str
    structured_json: str
    score_json: str
    news: tuple[str, ...]
    sec: tuple[str, ...]
    evidence: tuple[ResearchEvidence, ...]
    deadline_seconds: float
    retry_instruction: str = ''


@dataclass(frozen=True)
class ResearchServices:
    settings: CalculationSettings
    clock: ResearchClock
    synthesis: Callable[[SynthesisRequest], Awaitable[str]]
    gap_fill: Callable[[GapFillRequest], Awaitable[GapFillResult]]
    telemetry: Callable[[dict], None]
    deadline_seconds: float = 160.0
    max_output_chars: int = 20_000

    def __post_init__(self):
        if type(self.settings) is not CalculationSettings or type(self.clock) is not ResearchClock:
            raise TypeError('Explicit immutable settings and clock are required')
        if not 0 < self.deadline_seconds <= 160 or not 0 < self.max_output_chars <= 20_000:
            raise ValueError('Research service budgets exceed the allowed bound')
        if not all(callable(callback) for callback in (self.synthesis, self.gap_fill, self.telemetry)):
            raise TypeError('Explicit bounded services are required')


@dataclass(frozen=True)
class ResearchOutput:
    narrative: str
    structured: StructuredFields
    score_breakdown: ScoreBreakdown
    evidence: tuple[ResearchEvidence, ...]
    conflicts: tuple[str, ...]
    source_statuses: tuple[SourceStatus, ...]
    analysis_version: str
    narrative_status: str
    anchors: tuple = ()
    trade_plan: Mapping = field(default_factory=dict)


@dataclass
class ScoreTickerResult:
    """Tweetless scoring result wrapping the parallel-gather + ScoreBreakdown.

    Returned by `score_ticker()`; `cross_reference()` decorates this into a
    `CrossReferenceResult` with tweet-specific fields.
    """
    ticker: str
    breakdown: ScoreBreakdown
    catalyst: Optional[CatalystResult] = None
    technical: Optional[TechnicalResult] = None
    options: Optional[OptionsResult] = None
    youtube: Optional[YouTubeContext] = None
    social_data: dict = field(default_factory=dict)
    sec_hit: bool = False
    sec_summary: str = ""
    other_analysts: list = field(default_factory=list)
    llm_reasoning: str = ""
    consolidation_result: Optional[object] = None
    metrics: dict = field(default_factory=dict)
    # I3 producer (signal-features-2026-06-09): 0=unanimous, 1=perfectly split.
    # Computed in score_ticker; 0.0 until features.contradiction_index_live.enabled.
    contradiction_index: float = 0.0
    # I3: distinct opposing sources (youtube/options/sec) disagreeing with the tweet
    # direction. Persisted for forward backtesting of the >=2-actor downgrade gate.
    n_opposing: int = 0

    @property
    def final_score(self) -> int:
        return self.breakdown.total



@dataclass
class _SecGraduation:
    """Parsed Form-4 facts the I5 graduation tier needs. Defaults = no signal."""
    has_form4: bool = False
    max_buy_dollars: float = 0.0      # largest single-insider open-market BUY ($)
    reporter_role: str = "other"      # canonicalized role of the top buyer
    is_planned: bool = False          # 10b5-1 / pre-arranged plan footnote present
    plan_flag_seen: bool = False      # a footnote was parseable for the top buy
    txn_date: str = ""                # transaction date of the top buy (YYYY-MM-DD)
    net_selling: bool = False         # open-market sells present with no qualifying buy



@dataclass
class _BurstAnalysis:
    """Result of E6 manufactured-agreement scan over analyst signal texts."""
    burst_detected: bool = False
    burst_actor_ids: frozenset = field(default_factory=frozenset)
    has_independent_corroboration: bool = False
    # True when burst detected AND no independent corroboration yet.
    boost_gated: bool = False
