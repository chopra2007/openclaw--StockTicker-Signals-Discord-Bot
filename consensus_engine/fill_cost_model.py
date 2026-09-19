"""D-106/D-107 offline fill and cost model shared across the first four playbooks.

D-106 fixes the human-reaction window at exactly 0-30 seconds after alert time
and requires fills to be modeled from the price path in that window, never at
the trigger price. D-107 requires real spread from quote data, modeled
slippage and commissions. This module applies those two rules mechanically to
already-normalized ``Quote`` records (trade prints and top-of-book snapshots);
it does not fetch data, decide which instant is an alert, choose a playbook's
threshold, size a position, or evaluate a stop/target outcome.

Cost realism inputs (``slippage_bps``, ``commission_per_share``) are supplied
by the caller and are not searched, tuned or chosen from a result; they model
transaction friction, not a strategy parameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any, Sequence

from .trade_alerts_models import Quote, RecordError
from .utils.time_context import as_utc


WINDOW_SECONDS = 30.0
POLICY_VERSION = "D106_D107_FILL_COST_V1"
DIRECTIONS = frozenset({"LONG", "SHORT"})
_STATUSES = frozenset({"FILLED", "NO_TRADE_IN_WINDOW", "NO_QUOTE_AT_FILL"})


def _finite_nonnegative(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise RecordError(f"{name} must be a finite non-negative number")
    return float(value)


@dataclass(frozen=True)
class FillCostPolicy:
    """Explicit cost-realism inputs; no defaults are assumed as authoritative."""

    version: str
    slippage_bps: float
    commission_per_share: float

    def __post_init__(self) -> None:
        if self.version != POLICY_VERSION:
            raise RecordError("fill cost policy version is not supported")
        object.__setattr__(self, "slippage_bps", _finite_nonnegative(self.slippage_bps, "slippage_bps"))
        object.__setattr__(
            self, "commission_per_share",
            _finite_nonnegative(self.commission_per_share, "commission_per_share"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "slippage_bps": self.slippage_bps,
            "commission_per_share": self.commission_per_share,
        }


@dataclass(frozen=True)
class ModeledFill:
    """One D-106/D-107 fill decision; ``modeled_price`` is null unless FILLED."""

    status: str
    alert_time: datetime
    direction: str
    window_end: datetime
    policy: FillCostPolicy
    trade_print_time: datetime | None
    trade_print_price: float | None
    quote_time: datetime | None
    bid: float | None
    ask: float | None
    spread_cost_per_share: float | None
    slippage_cost_per_share: float | None
    commission_per_share: float | None
    total_cost_per_share: float | None
    modeled_price: float | None
    input_record_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "alert_time": self.alert_time.isoformat(),
            "direction": self.direction, "window_end": self.window_end.isoformat(),
            "policy": self.policy.as_dict(),
            "trade_print_time": self.trade_print_time.isoformat() if self.trade_print_time else None,
            "trade_print_price": self.trade_print_price,
            "quote_time": self.quote_time.isoformat() if self.quote_time else None,
            "bid": self.bid, "ask": self.ask,
            "spread_cost_per_share": self.spread_cost_per_share,
            "slippage_cost_per_share": self.slippage_cost_per_share,
            "commission_per_share": self.commission_per_share,
            "total_cost_per_share": self.total_cost_per_share,
            "modeled_price": self.modeled_price,
            "input_record_ids": list(self.input_record_ids),
        }


def _unresolved(status: str, alert_time: datetime, direction: str, window_end: datetime,
                policy: FillCostPolicy, input_ids: tuple[str, ...]) -> ModeledFill:
    return ModeledFill(
        status=status, alert_time=alert_time, direction=direction, window_end=window_end,
        policy=policy, trade_print_time=None, trade_print_price=None, quote_time=None,
        bid=None, ask=None, spread_cost_per_share=None, slippage_cost_per_share=None,
        commission_per_share=None, total_cost_per_share=None, modeled_price=None,
        input_record_ids=input_ids,
    )


def _valid_trades(trades: Sequence[Quote]) -> list[Quote]:
    result = []
    for quote in trades:
        if not isinstance(quote, Quote):
            raise RecordError("trade prints must be canonical Quote records")
        if (quote.metadata.quality == "VALID" and quote.trade_time is not None
                and quote.last is not None and quote.last > 0):
            result.append(quote)
    return result


def _valid_quotes(quotes: Sequence[Quote]) -> list[Quote]:
    result = []
    for quote in quotes:
        if not isinstance(quote, Quote):
            raise RecordError("top-of-book snapshots must be canonical Quote records")
        if (quote.metadata.quality == "VALID" and quote.quote_time is not None
                and quote.bid is not None and quote.ask is not None
                and quote.bid > 0 and quote.ask > 0):
            result.append(quote)
    return result


def model_fill(
    *, alert_time: datetime, direction: str, trades: Sequence[Quote],
    quotes: Sequence[Quote], policy: FillCostPolicy,
) -> ModeledFill:
    """Model one D-106 0-30s fill using real trade prints and top-of-book quotes.

    The fill price is the first valid trade print at or after ``alert_time``
    and within the fixed 30-second window. Its cost is the half-spread from
    the most recent valid quote at or before that print (or, absent one, the
    earliest valid quote still inside the window), plus modeled slippage and
    commission from ``policy``. No price is chosen by scanning for the most
    favorable instant; the first actionable print is used.
    """
    if not isinstance(policy, FillCostPolicy):
        raise RecordError("model_fill requires a FillCostPolicy")
    alert_time = as_utc(alert_time)
    if direction not in DIRECTIONS:
        raise RecordError("direction must be LONG or SHORT")
    window_end = alert_time + timedelta(seconds=WINDOW_SECONDS)
    sign = 1 if direction == "LONG" else -1

    trade_pool = sorted(
        (quote for quote in _valid_trades(trades) if alert_time <= quote.trade_time <= window_end),
        key=lambda quote: (quote.trade_time, quote.record_id),
    )
    input_ids = tuple(quote.record_id for quote in trades) + tuple(quote.record_id for quote in quotes)
    if not trade_pool:
        return _unresolved("NO_TRADE_IN_WINDOW", alert_time, direction, window_end, policy, input_ids)
    fill_trade = trade_pool[0]

    quote_pool = [quote for quote in _valid_quotes(quotes) if alert_time <= quote.quote_time <= window_end]
    before = [quote for quote in quote_pool if quote.quote_time <= fill_trade.trade_time]
    if before:
        fill_quote = max(before, key=lambda quote: (quote.quote_time, quote.record_id))
    elif quote_pool:
        fill_quote = min(quote_pool, key=lambda quote: (quote.quote_time, quote.record_id))
    else:
        return _unresolved("NO_QUOTE_AT_FILL", alert_time, direction, window_end, policy, input_ids)

    trade_price = fill_trade.last
    assert trade_price is not None
    spread_cost = (fill_quote.ask - fill_quote.bid) / 2.0
    slippage_cost = trade_price * policy.slippage_bps / 10_000.0
    commission = policy.commission_per_share
    total_cost = spread_cost + slippage_cost + commission
    modeled_price = trade_price + sign * total_cost

    return ModeledFill(
        status="FILLED", alert_time=alert_time, direction=direction, window_end=window_end,
        policy=policy, trade_print_time=fill_trade.trade_time, trade_print_price=trade_price,
        quote_time=fill_quote.quote_time, bid=fill_quote.bid, ask=fill_quote.ask,
        spread_cost_per_share=spread_cost, slippage_cost_per_share=slippage_cost,
        commission_per_share=commission, total_cost_per_share=total_cost,
        modeled_price=modeled_price, input_record_ids=input_ids,
    )


__all__ = [
    "WINDOW_SECONDS", "POLICY_VERSION", "FillCostPolicy", "ModeledFill", "model_fill",
]
