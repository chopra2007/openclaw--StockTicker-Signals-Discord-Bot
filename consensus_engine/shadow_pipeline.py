"""M9.3 shadow-mode pilot: safe recording, input continuity and the initial
pipeline for the first four playbooks (`CRVOL_ORB5`, `HOD_COMP_RS`,
`OR_FAILURE_REV`, `FIRST_PULLBACK_VWAP`) through the shared M5.3 runner.

This is the engineering pilot ROADMAP M9.3 describes, not the M17 evidence-
bearing promotion gate. It opens no database, provider, credential or config
file itself; the caller supplies every strategy, spec, context, transition
engine and already-loaded budget figure, the same boundary `historical_replay.py`
and `alert_delivery.py` already keep. It proves the mechanics only: nothing here
adopts a threshold, calculates a historical outcome, delivers a live alert or
authorizes activation.
"""

from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import math

from .alert_delivery import RecordingSink
from .full_chain_storage import StoragePolicy
from .historical_replay import HistoricalReplayRunner, ReplayResult, ReplaySpec
from .request_queue import QueuePolicy
from .state_transitions import StateTransitionEngine
from .strategy_interface import Strategy, StrategyContext
from .trade_alerts_models import RecordError


SHADOW_MODE_VERSION = "M93_V1"
SHARED_DATA_MODE = "SUPPLIED_REPLAY_INPUTS"
REQUIRED_STRATEGY_IDS = ("CRVOL_ORB5", "HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP")


# --- input continuity --------------------------------------------------------


@dataclass(frozen=True)
class ContinuityGap:
    strategy_id: str
    gap_seconds: float

    def as_dict(self) -> dict:
        return {"strategy_id": self.strategy_id, "gap_seconds": self.gap_seconds}


@dataclass(frozen=True)
class ContinuityReport:
    ok: bool
    checked_count: int
    max_gap_seconds: float
    gaps: tuple[ContinuityGap, ...]

    def as_dict(self) -> dict:
        return {
            "shadow_mode_version": SHADOW_MODE_VERSION,
            "ok": self.ok,
            "checked_count": self.checked_count,
            "max_gap_seconds": self.max_gap_seconds,
            "gaps": [row.as_dict() for row in self.gaps],
        }


def _context_record_ids(context: StrategyContext) -> set[str]:
    ids = {record.record_id for record in (*context.features, *context.catalysts)}
    if context.quote is not None and context.quote.quote is not None:
        ids.add(context.quote.quote.record_id)
    return ids


def check_input_continuity(
    contexts_by_strategy: dict[str, tuple[StrategyContext, ...]], *, max_gap: timedelta,
) -> ContinuityReport:
    """Fail-closed continuity check across the four playbooks' own input streams.

    Every strategy's supplied contexts must already be chronological (the M5.3
    runner separately enforces that during replay); this additionally requires
    one shared session, no record ID reused across strategies, and no gap wider
    than the caller's one explicit ``max_gap``. No gap size is invented here.
    """
    if not isinstance(max_gap, timedelta) or max_gap <= timedelta(0):
        raise RecordError("continuity check requires one explicit positive max_gap")
    if set(contexts_by_strategy) != set(REQUIRED_STRATEGY_IDS):
        raise RecordError("continuity check requires exactly the four first playbooks")
    all_ids: set[str] = set()
    gaps: list[ContinuityGap] = []
    checked = 0
    sessions = set()
    for strategy_id, contexts in contexts_by_strategy.items():
        if not isinstance(contexts, tuple) or not contexts:
            raise RecordError("continuity check requires a non-empty tuple of contexts")
        previous = None
        for context in contexts:
            if not isinstance(context, StrategyContext):
                raise RecordError("continuity check requires canonical StrategyContext records")
            sessions.add(context.session)
            ids = _context_record_ids(context)
            if ids & all_ids:
                raise RecordError("continuity check found a record ID reused across strategies")
            all_ids |= ids
            checked += 1
            if previous is not None:
                if context.evaluated_at < previous:
                    raise RecordError("continuity check requires chronological inputs per strategy")
                delta = (context.evaluated_at - previous).total_seconds()
                if delta > max_gap.total_seconds():
                    gaps.append(ContinuityGap(strategy_id, delta))
            previous = context.evaluated_at
    if len(sessions) != 1:
        raise RecordError("shadow mode pilot requires one shared session across all four playbooks")
    return ContinuityReport(not gaps, checked, max_gap.total_seconds(), tuple(gaps))


# --- recorded budgets (D-104/M0.2K) ------------------------------------------


@dataclass(frozen=True)
class ProviderBudget:
    """Pure arithmetic over an already-loaded ledger; no file or network access."""

    authority_usd: float
    spent_usd: float

    def __post_init__(self) -> None:
        for value, name in ((self.authority_usd, "authority"), (self.spent_usd, "spend")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise RecordError(f"provider {name} must be a known finite amount")
        if self.authority_usd <= 0 or self.spent_usd < 0:
            raise RecordError("provider budget must be a known nonnegative amount")
        if self.spent_usd > self.authority_usd:
            raise RecordError("provider spend exceeds its recorded authority")

    @property
    def remaining_usd(self) -> float:
        return round(self.authority_usd - self.spent_usd, 4)

    def as_dict(self) -> dict:
        return {"authority_usd": self.authority_usd, "spent_usd": self.spent_usd,
                "remaining_usd": self.remaining_usd}


def provider_budget_from_ledger(ledger: dict) -> ProviderBudget:
    """Sum the already-loaded ledger's downloaded jobs; the caller reads the file."""
    if not isinstance(ledger, dict) or "authority_usd" not in ledger or "jobs" not in ledger:
        raise RecordError("ledger must supply authority_usd and a jobs list")
    if not isinstance(ledger["jobs"], list):
        raise RecordError("ledger jobs must be a list")
    spent = sum(float(job["actual_cost_usd"]) for job in ledger["jobs"] if job.get("downloaded"))
    return ProviderBudget(float(ledger["authority_usd"]), spent)


@dataclass(frozen=True)
class ShadowModeBudgets:
    """The recorded provider/queue/storage/memory ceilings this pilot must stay under.

    ``queue_policy`` and ``storage_policy`` reuse the frozen defaults M0.2D and
    the collector already publish; this module invents no new ceiling.
    """

    queue_policy: QueuePolicy
    storage_policy: StoragePolicy
    provider: ProviderBudget

    def __post_init__(self) -> None:
        if type(self.queue_policy) is not QueuePolicy or self.queue_policy.enabled:
            raise RecordError("shadow mode requires the frozen offline queue policy, disabled")
        if type(self.storage_policy) is not StoragePolicy or self.storage_policy.enabled:
            raise RecordError("shadow mode requires the frozen storage policy, disabled")
        if type(self.provider) is not ProviderBudget:
            raise RecordError("shadow mode requires a checked provider budget")

    def as_dict(self) -> dict:
        return {
            "shadow_mode_version": SHADOW_MODE_VERSION,
            "queue_policy": {
                "enabled": self.queue_policy.enabled,
                "account_ceiling": self.queue_policy.account_ceiling,
                "ceiling_window_seconds": self.queue_policy.ceiling_window_seconds,
                "maximum_length": self.queue_policy.maximum_length,
            },
            "storage_policy": {
                "enabled": self.storage_policy.enabled,
                "fixed_reserve_bytes": self.storage_policy.fixed_reserve_bytes,
                "reserve_fraction": self.storage_policy.reserve_fraction,
                "peak_memory_bytes": self.storage_policy.peak_memory_bytes,
            },
            "provider": self.provider.as_dict(),
        }


def default_shadow_mode_budgets(ledger: dict) -> ShadowModeBudgets:
    """The exact M0.2K-recorded ceilings: frozen queue/storage defaults plus the
    caller's already-loaded provider ledger."""
    return ShadowModeBudgets(QueuePolicy(), StoragePolicy(), provider_budget_from_ledger(ledger))


# --- the pilot itself ---------------------------------------------------------


@dataclass(frozen=True)
class ShadowModePlaybookRun:
    strategy_id: str
    strategy_version: str
    data_mode: str
    result: ReplayResult

    def as_dict(self) -> dict:
        return {"strategy_id": self.strategy_id, "strategy_version": self.strategy_version,
                "data_mode": self.data_mode, "result": self.result.as_dict()}


@dataclass(frozen=True)
class ShadowModeReport:
    session: str
    budgets: ShadowModeBudgets
    continuity: ContinuityReport
    runs: tuple[ShadowModePlaybookRun, ...]

    def as_dict(self) -> dict:
        return {
            "shadow_mode_version": SHADOW_MODE_VERSION,
            "session": self.session,
            "alert_sink": RecordingSink.name,
            "replay_sink": "RecordingReplaySink",
            "budgets": self.budgets.as_dict(),
            "continuity": self.continuity.as_dict(),
            "runs": [row.as_dict() for row in self.runs],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


async def run_shadow_mode_pilot(
    *, specs: dict[str, ReplaySpec], strategies: dict[str, Strategy],
    transitions: dict[str, StateTransitionEngine], store,
    contexts_by_strategy: dict[str, tuple[StrategyContext, ...]],
    budgets: ShadowModeBudgets, max_gap: timedelta, sink_factory,
) -> ShadowModeReport:
    """Run exactly the four first playbooks over one shared session.

    ``sink_factory`` must return a fresh recording-only replay sink for every
    call; the M5.3 runner already refuses any other sink type. Refuses to run
    any strategy at all when the supplied inputs are not continuous.
    """
    if (set(specs) != set(REQUIRED_STRATEGY_IDS) or set(strategies) != set(REQUIRED_STRATEGY_IDS)
            or set(transitions) != set(REQUIRED_STRATEGY_IDS)):
        raise RecordError("shadow mode pilot requires exactly the four first playbooks")
    if type(budgets) is not ShadowModeBudgets:
        raise RecordError("shadow mode pilot requires a checked ShadowModeBudgets record")
    continuity = check_input_continuity(contexts_by_strategy, max_gap=max_gap)
    if not continuity.ok:
        raise RecordError("shadow mode pilot refuses to run on discontinuous supplied inputs")
    session_id = next(iter(contexts_by_strategy.values()))[0].session.session
    runs = []
    for strategy_id in REQUIRED_STRATEGY_IDS:
        strategy = strategies[strategy_id]
        if strategy.strategy_id != strategy_id:
            raise RecordError("supplied strategy does not match its declared playbook")
        declared_modes = {row.data_mode for row in strategy.required_data()}
        if SHARED_DATA_MODE not in declared_modes:
            raise RecordError("shadow mode pilot requires the shared supplied-replay data mode")
        sink = sink_factory()
        runner = HistoricalReplayRunner(spec=specs[strategy_id], strategy=strategy,
                                        transitions=transitions[strategy_id], store=store, sink=sink)
        result = await runner.run(contexts_by_strategy[strategy_id])
        runs.append(ShadowModePlaybookRun(strategy_id, strategy.strategy_version,
                                          SHARED_DATA_MODE, result))
    return ShadowModeReport(session_id, budgets, continuity, tuple(runs))
