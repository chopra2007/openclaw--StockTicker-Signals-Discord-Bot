"""Allowlisted public responses. Internal grants and lineage never serialize here."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Section = Literal["analysis", "sec", "options", "em_daily", "em_weekly"]
Status = Literal["queued", "running", "completed", "unavailable", "failed"]
Feature = Literal["feed", "setups", "analysis", "sec", "options", "em_daily", "em_weekly", "assistant"]
FeedSource = Literal['analyst_views','signal_events','alert_history','decision_snapshots','ticker_signals','research_sections']
ShortText = Annotated[str, Field(max_length=256)]
Text = Annotated[str, Field(max_length=4000)]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class SourceContribution(BaseModel):
    """Internal source/product lineage. This is never a member response model."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    source_id: Identifier
    product_id: Identifier
    source_version: Identifier
    policy_version: Identifier


class FieldDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field_path: Identifier
    required_features: list[Feature] = Field(min_length=1, max_length=8)


class ContentLineage(BaseModel):
    """Validated metadata for internal stored content, distinct from safe DTOs.

    Empty database lineage defaults represent unverified legacy/pending content.
    They cannot be promoted to this complete-lineage contract.
    """
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    sources: list[SourceContribution] = Field(min_length=1, max_length=200)
    required_features: list[Feature] = Field(min_length=1, max_length=8)
    field_dependencies: list[FieldDependency] = Field(max_length=200)
    retention_deadline: float | None


class Metric(PublicModel):
    value: float | None
    unit: ShortText
    method: ShortText


class ContextMetric(PublicModel):
    name: Literal['net_gamma', 'gamma_flip', 'iv_skew', 'risk']
    metric: Metric
    observed_at: float | None
    source_id: Identifier
    source_version: Identifier


class Evidence(PublicModel):
    id: Identifier
    source_id: Identifier
    source_version: Identifier
    observed_at: float | None
    url: Annotated[str, Field(max_length=2048)] | None
    excerpt: Text
    research_only: bool


class FeedPayload(PublicModel):
    ticker: str = Field(max_length=16)
    direction: Literal['bullish','bearish','neutral','unclear']
    excerpt: Text
    score: float | None = None
    price: float | None = None
    research_only: Literal[True] = True
    entry: float | None = None
    target: float | None = None
    invalidation: float | None = None
    attributions: list[Annotated[str,Field(max_length=1536)]] = Field(default_factory=list,max_length=200)
    evidence: list[Evidence] = Field(default_factory=list,max_length=200)


class FeedUpsert(PublicModel):
    operation: Literal['upsert'] = 'upsert'
    id: Identifier
    content_version: Identifier
    summary_version: Identifier
    source: FeedSource | None
    payload: FeedPayload
    observed_at: float | None
    projected_at: float
    published_at: float | None = None
    stale: bool
    delay_seconds: float = Field(ge=0)


class FeedDelete(PublicModel):
    operation: Literal['delete'] = 'delete'
    id: Identifier


class SourceFreshness(PublicModel):
    source: FeedSource
    status: Literal['available','stale','unavailable']
    checked_at: float | None
    succeeded_at: float | None


class FeedPage(PublicModel):
    records: list[Annotated[FeedUpsert | FeedDelete,Field(discriminator='operation')]] = Field(max_length=100)
    cursor: str = Field(max_length=4096)
    snapshot: bool
    has_more: bool
    sources: list[SourceFreshness] = Field(max_length=9)


class RetractionAnnotation(PublicModel):
    status: Literal['retracted','unavailable']
    recorded_at: float | None


class Level(PublicModel):
    label: ShortText
    price: Metric


class AnalysisPayload(PublicModel):
    kind: Literal["analysis"] = "analysis"
    summary: Text
    direction: Literal["bullish", "bearish", "neutral", "unclear"]
    score: Metric | None
    catalysts: list[Text] = Field(default_factory=list, max_length=50)
    conflicts: list[Text] = Field(default_factory=list, max_length=50)
    levels: list[Level] = Field(default_factory=list, max_length=50)
    risk_metrics: list[Metric] = Field(default_factory=list, max_length=50)
    context_metrics: list[ContextMetric] = Field(default_factory=list, max_length=20)


class Filing(PublicModel):
    accession: Identifier
    form: ShortText
    filed_at: float | None
    title: ShortText
    summary: Text
    url: Annotated[str, Field(max_length=2048)] | None
    detail_status: Literal["ok", "unavailable", "not_requested"]


class InsiderSummary(PublicModel):
    accession: Identifier
    summary: Text
    conviction: Literal["routine", "conviction", "unknown"]
    transaction_value: Metric | None


class SecPayload(PublicModel):
    kind: Literal["sec"] = "sec"
    coverage: Literal["complete", "partial"]
    filings: list[Filing] = Field(default_factory=list, max_length=200)
    insiders: list[InsiderSummary] = Field(default_factory=list, max_length=200)
    warning: Text | None = None


class OptionContract(PublicModel):
    symbol: ShortText
    expiry: ShortText
    side: Literal["call", "put"]
    strike: Metric
    volume: Metric | None
    open_interest: Metric | None
    premium: Metric | None
    observed_at: float | None


class OptionsPayload(PublicModel):
    kind: Literal["options"] = "options"
    contracts: list[OptionContract] = Field(default_factory=list, max_length=200)
    call_volume: Metric | None
    put_volume: Metric | None
    put_call_ratio: Metric | None
    call_premium: Metric | None
    put_premium: Metric | None
    context_metrics: list[ContextMetric] = Field(default_factory=list, max_length=20)


class MoveRange(PublicModel):
    method: ShortText
    lower: Metric | None
    upper: Metric | None
    expected_move: Metric | None


class QuoteTime(PublicModel):
    source_id: Identifier
    observed_at: float | None
    input_kind: Literal['call','put','underlying','selection','history'] | None = None


class MovePayload(PublicModel):
    kind: Literal["move"] = "move"
    horizon: Literal["daily", "weekly"]
    spot: Metric | None
    expiry: ShortText | None
    ranges: list[MoveRange] = Field(default_factory=list, max_length=10)
    quote_times: list[QuoteTime] = Field(default_factory=list, max_length=20)
    chart_asset_id: Identifier | None
    context_metrics: list[ContextMetric] = Field(default_factory=list, max_length=20)


Payload = Annotated[AnalysisPayload | SecPayload | OptionsPayload | MovePayload, Field(discriminator="kind")]


class SectionResult(PublicModel):
    section: Section
    status: Status
    job_id: Identifier | None
    result_id: Identifier | None
    observed_at: float | None
    computed_at: float | None
    valid_until: float | None
    stale: bool
    analysis_version: Identifier
    evidence: list[Evidence] = Field(default_factory=list, max_length=200)
    payload: Payload | None
    message: Text | None
    attributions: list[ShortText] = Field(default_factory=list, max_length=200)
    delay_seconds: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_section_payload(self):
        if self.payload is not None:
            expected = "move" if self.section in ("em_daily", "em_weekly") else self.section
            if self.payload.kind != expected:
                raise ValueError("payload does not match section")
            if isinstance(self.payload, MovePayload):
                horizon = "daily" if self.section == "em_daily" else "weekly"
                if self.payload.horizon != horizon:
                    raise ValueError("payload horizon does not match section")
        return self


class HealthResponse(PublicModel):
    status: Literal["ok"]


class ResearchRequest(PublicModel):
    id: Identifier
    report_id: Identifier
    ticker: Annotated[str, Field(max_length=16)]
    sections: dict[Section, SectionResult]


class ReportRef(PublicModel):
    id: Identifier
    created_at: float
    ticker: Annotated[str, Field(max_length=16)] | None = None


class ReportPage(PublicModel):
    items: list[ReportRef] = Field(max_length=100)
    cursor: Annotated[str, Field(max_length=4096)] | None


class SavedEvidenceAnnotation(PublicModel):
    evidence_id: Identifier
    source_id: Identifier
    source_version: Identifier
    status: Literal['retracted', 'unavailable']
    recorded_at: float | None


class SavedReport(ReportRef):
    version: int | None
    saved_at: float | None
    finalized: bool
    availability: Literal['available', 'pending', 'unavailable']
    sections: dict[Section, SectionResult]
    annotations: dict[Section, list[SavedEvidenceAnnotation]] = Field(default_factory=dict)


class ConversationRef(PublicModel):
    id: Identifier
    title: ShortText
    created_at: float
    version: int


class ConversationPage(PublicModel):
    items: list[ConversationRef] = Field(max_length=100)
    cursor: Annotated[str, Field(max_length=4096)] | None


class MessageContent(PublicModel):
    """Task 10 persists this typed body, with complete internal model lineage."""
    text: Text
    evidence: list[Evidence] = Field(default_factory=list, max_length=200)


class SavedMessage(PublicModel):
    id: Identifier
    role: Literal['user', 'assistant']
    created_at: float
    text: Text | None
    evidence: list[Evidence] = Field(default_factory=list, max_length=200)
    availability: Literal['available', 'unavailable']
    annotations: list[SavedEvidenceAnnotation] = Field(default_factory=list, max_length=200)


class SavedConversation(ConversationRef):
    messages: list[SavedMessage] = Field(max_length=100)
    cursor: Annotated[str, Field(max_length=4096)] | None


class AssistantRun(PublicModel):
    id: Identifier
    conversation_id: Identifier
    status: Status
    ticker_context: Annotated[str, Field(max_length=16)] | None
    created_at: float
    finished_at: float | None
    message: ShortText | None
    response_message_id: Identifier | None
    model_id: Identifier | None
    input_tokens: int | None
    output_tokens: int | None
    cost: float | None
