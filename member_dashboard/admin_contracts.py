"""Small, strict administration DTOs; never expose storage rows."""
from typing import Literal
from pydantic import Field
from .contracts import PublicModel, Feature, Identifier

class FeatureState(PublicModel):
    name: Feature
    enabled: bool
    version: int = Field(ge=1)

class MemberState(PublicModel):
    id: Identifier
    username: str
    role: Literal['admin','member']
    status: Literal['active','suspended']

class InviteState(PublicModel):
    id: Identifier
    created_at: float
    expires_at: float
    consumed: bool
    revoked: bool

class TokenLink(PublicModel):
    id: Identifier
    token: str = Field(repr=False)
    expires_at: float

class AuditState(PublicModel):
    id: Identifier
    actor_id: Identifier | None
    target_id: Identifier | None
    action: str
    occurred_at: float
    result: Literal['ok','denied']

class MemberPage(PublicModel):
    items: list[MemberState]
    next_cursor: str | None

class InvitePage(PublicModel):
    items: list[InviteState]
    next_cursor: str | None

class AuditPage(PublicModel):
    items: list[AuditState]
    next_cursor: str | None

class Observation(PublicModel):
    status: Literal['responsive','stale','unavailable']
    observed_at: float | None = None
    progress_at: float | None = None
    state: Literal['idle','busy','draining','blocked'] | None = None

class QueueHealth(PublicModel):
    queued: int
    running: int
    draining: int
    oldest_age_seconds: float | None

class UsageHealth(PublicModel):
    runs: int
    input_tokens: int | None
    output_tokens: int | None
    cost: float | None
    known_usage_runs: int

class SourceFreshness(PublicModel):
    source: str
    checked_at: float | None
    succeeded_at: float | None
    stale: bool

class FailureCount(PublicModel):
    code: str
    count: int

class AdminHealth(PublicModel):
    checked_at: float
    api: Observation
    frontend: Observation
    supervisor: Observation
    compute: Observation
    queue: QueueHealth
    sources: list[SourceFreshness]
    failures: list[FailureCount]
    usage: UsageHealth
