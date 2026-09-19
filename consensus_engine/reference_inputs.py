"""Offline reference snapshots from supplied quote decisions and bar histories.

No fetch, stream owner, clock read or trading calculation lives here. Coverage
counts describe only the supplied records, never a provider's actual coverage.
"""

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Mapping

from .analysis.wolf_scope import stock_sector_etf
from .historical_bars import HistoryBatch, HistoryCoverage, HistoryRequest
from .quote_events import QuoteEventDecision, QuoteEventPolicy
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc, session_date_at


INTERFACE_VERSION = "M24_V1"
SECTOR_ETFS = ("XLK", "XLF", "XLY", "XLC", "XLI", "XLV", "XLP", "XLE", "XLU", "XLRE", "XLB")
ETF_REFERENCES = ("SPY", "QQQ", *SECTOR_ETFS)
EXPECTED_REFERENCES = (*ETF_REFERENCES, "VIX")


def _known(value: str) -> bool:
    return isinstance(value, str) and value.strip().upper() not in ("", "UNKNOWN", "UNSPECIFIED")


@dataclass(frozen=True)
class ReferenceScope:
    """Explicit per-ETF source, modes, age policy and optional history request.

An omitted policy or history request stays unavailable. No defaults select a
live age, return window, history source or reference-market trading rule.
"""

    symbol: str
    source: str
    quote_data_mode: str
    history_data_mode: str
    quote_policy: QuoteEventPolicy | None
    history_request: HistoryRequest | None

    def __post_init__(self) -> None:
        if self.symbol not in ETF_REFERENCES:
            raise RecordError("reference scope requires a supported ETF")
        if not all(_known(value) for value in (self.source, self.quote_data_mode, self.history_data_mode)):
            raise RecordError("reference source and data modes must be known")
        if self.quote_policy is not None and not isinstance(self.quote_policy, QuoteEventPolicy):
            raise RecordError("reference quote policy must be QuoteEventPolicy or null")
        if self.history_request is not None and (
                not isinstance(self.history_request, HistoryRequest)
                or self.history_request.symbol != self.symbol):
            raise RecordError("reference history request must match the ETF")

    def as_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "source": self.source,
                "quote_data_mode": self.quote_data_mode, "history_data_mode": self.history_data_mode,
                "quote_policy": self.quote_policy.as_dict() if self.quote_policy else None,
                "history_request": self.history_request.as_dict() if self.history_request else None}


@dataclass(frozen=True)
class ReferenceCoverage:
    symbol: str
    scope: ReferenceScope | None
    quote_decision: QuoteEventDecision | None
    history: HistoryCoverage | None
    history_conventions_json: str | None
    quote_reasons: tuple[str, ...]
    history_reasons: tuple[str, ...]

    @property
    def quote_usable(self) -> bool:
        return self.quote_decision is not None and not self.quote_reasons

    @property
    def history_complete(self) -> bool:
        return self.history is not None and self.history.complete and not self.history_reasons

    def as_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "scope": self.scope.as_dict() if self.scope else None,
                "quote_decision": self.quote_decision.as_dict() if self.quote_decision else None,
                "history": self.history.as_dict() if self.history else None,
                "history_conventions": json.loads(self.history_conventions_json)
                if self.history_conventions_json is not None else None,
                "quote_usable": self.quote_usable, "history_complete": self.history_complete,
                "quote_reasons": list(self.quote_reasons), "history_reasons": list(self.history_reasons)}


@dataclass(frozen=True)
class ReferenceSnapshot:
    evaluated_at: datetime
    session: str
    references: tuple[ReferenceCoverage, ...]
    current_sector_mappings: tuple[tuple[str, str | None], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "interface_version": INTERFACE_VERSION, "evaluated_at": self.evaluated_at.isoformat(),
            "session": self.session, "coverage_basis": "SUPPLIED_RECORDS_ONLY",
            "expected_etfs": list(ETF_REFERENCES),
            "usable_quote_count": sum(row.quote_usable for row in self.references),
            "complete_history_count": sum(row.history_complete for row in self.references),
            "references": [row.as_dict() for row in self.references],
            # Current mapping is context only, never an available historical input.
            "current_sector_mappings": [
                {"stock": stock, "sector_etf": sector, "basis": "CURRENT_MAP_ONLY",
                 "historical_membership": "UNAVAILABLE"}
                for stock, sector in self.current_sector_mappings
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def _quote_view(scope: ReferenceScope, decision: QuoteEventDecision | None,
                at: datetime, session: str) -> tuple[QuoteEventDecision | None, tuple[str, ...]]:
    if decision is None:
        return None, ("MISSING_QUOTE_DECISION",)
    if decision.evaluated_at > at:
        return None, ("FUTURE_QUOTE_DECISION",)
    quote = decision.quote
    if quote is not None:
        meta = quote.metadata
        if (meta.instrument_id, meta.source, meta.instrument_type, meta.session, meta.data_mode) != (
                scope.symbol, scope.source, "ETF", session, scope.quote_data_mode):
            return None, ("QUOTE_SCOPE_MISMATCH",)
        # Canonical Quote validation bounds both component times by original
        # availability. This check therefore excludes future components too.
        if meta.available_time > at:
            return None, ("QUOTE_NOT_AVAILABLE",)
    reasons = list(decision.reasons)
    if quote is None and "MISSING_QUOTE" not in reasons:
        reasons.append("MISSING_QUOTE")
    # An old usable decision is not a fresh age/continuity check. Its own ages
    # and time remain visible; the caller must inspect its stream at this instant.
    if decision.evaluated_at != at:
        reasons.append("QUOTE_DECISION_TIME_MISMATCH")
    if scope.quote_policy is None:
        reasons.append("MISSING_QUOTE_POLICY")
    elif decision.policy != scope.quote_policy:
        reasons.append("QUOTE_POLICY_MISMATCH")
    return decision, tuple(dict.fromkeys(reasons))


def _history_view(scope: ReferenceScope, batch: HistoryBatch | None, at: datetime
                  ) -> tuple[HistoryCoverage | None, str | None, tuple[str, ...]]:
    request = scope.history_request
    if request is None:
        return None, None, ("MISSING_HISTORY_REQUEST",)
    if batch is None:
        # Keep the expected scheduled intervals even when no batch was supplied.
        from .historical_bars import HistoryConventions

        coverage = HistoryBatch(request, scope.source, HistoryConventions(), ()).coverage_at(at)
        return coverage, None, ("MISSING_HISTORY",)
    if batch.request != request or batch.source != scope.source:
        return None, None, ("HISTORY_SCOPE_MISMATCH",)
    coverage = batch.coverage_at(at)
    reasons = []
    if not coverage.complete:
        reasons.append("HISTORY_INCOMPLETE")
    for item in coverage.intervals:
        if item.bar is not None:
            meta = item.bar.metadata
            if meta.instrument_type != "ETF":
                reasons.append("HISTORY_INSTRUMENT_TYPE_MISMATCH")
            if meta.data_mode != scope.history_data_mode:
                reasons.append("HISTORY_MODE_MISMATCH")
    conventions = json.dumps(batch.conventions.as_dict(), sort_keys=True, separators=(",", ":"))
    return coverage, conventions, tuple(dict.fromkeys(reasons))


def build_reference_snapshot(*, evaluated_at: datetime, session: str,
                             scopes: tuple[ReferenceScope, ...],
                             quote_decisions: Mapping[str, QuoteEventDecision],
                             histories: Mapping[str, HistoryBatch],
                             stock_symbols: tuple[str, ...] = ()) -> ReferenceSnapshot:
    """Gather fixed per-symbol views without substituting one reference for another.

Quote decisions must come from M2.3 evaluated at this exact instant. History
requests can cover prior sessions; M2.2 selects only available records. Current
sector mappings are returned separately and cannot certify historical membership.
VIX is explicit but unsupported: neither the canonical type nor the event stream
supports an index. Supplied VIX values cannot bypass that missing contract.
"""
    if not isinstance(evaluated_at, datetime):
        raise RecordError("reference evaluation requires an aware datetime")
    at = as_utc(evaluated_at)
    if session != session_date_at(at).isoformat():
        raise RecordError("reference evaluation must match its session")
    if not isinstance(scopes, tuple) or any(not isinstance(scope, ReferenceScope) for scope in scopes):
        raise RecordError("reference scopes must be a tuple of ReferenceScope")
    by_symbol = {scope.symbol: scope for scope in scopes}
    if len(by_symbol) != len(scopes):
        raise RecordError("reference scopes cannot repeat an ETF")
    for supplied, expected_type in ((quote_decisions, QuoteEventDecision), (histories, HistoryBatch)):
        if not isinstance(supplied, Mapping) or any(
                key not in EXPECTED_REFERENCES or not isinstance(value, expected_type)
                for key, value in supplied.items()):
            raise RecordError("reference inputs require supported symbols and typed records")
    if not isinstance(stock_symbols, tuple) or any(not _known(stock) for stock in stock_symbols):
        raise RecordError("stock symbols must be a tuple of known identifiers")
    stocks = tuple(sorted({stock.strip().upper() for stock in stock_symbols}))
    mappings = tuple((stock, stock_sector_etf(stock)) for stock in stocks)
    rows = []
    for symbol in EXPECTED_REFERENCES:
        scope = by_symbol.get(symbol)
        if symbol == "VIX" or scope is None:
            reason = "UNSUPPORTED_INDEX_INPUT" if symbol == "VIX" else "MISSING_REFERENCE_SCOPE"
            rows.append(ReferenceCoverage(symbol, scope, None, None, None, (reason,), (reason,)))
            continue
        quote, quote_reasons = _quote_view(scope, quote_decisions.get(symbol), at, session)
        history, conventions, history_reasons = _history_view(scope, histories.get(symbol), at)
        rows.append(ReferenceCoverage(symbol, scope, quote, history, conventions,
                                      quote_reasons, history_reasons))
    return ReferenceSnapshot(at, session, tuple(rows), mappings)
