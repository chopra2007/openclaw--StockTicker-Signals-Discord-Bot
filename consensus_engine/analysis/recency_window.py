"""Common-recency-window synchronizer (signal-features-2026-06-09, cross-cutting).

Multi-source confluence/contradiction math (I3 contradiction index, I13
ApeWisdom z-gate, I15 Wolf confluence votes, E1 FINRA short-volume, E2
cross-asset) mixes sources with very different time bases: a Form-4 lands
within minutes, FINRA short volume is end-of-day, a YouTube mention can be a
day old. Pairing a 12h-old short-volume spike with a 1-min-old SEC buy
manufactures "confluence" for a move that already happened — phantom
confluence. This helper gives every consumer one shared rule: a leg only
counts if its data-as-of timestamp is inside that source's freshness cap
(`features.recency_window.max_age_min.<source>` in config/consensus.yaml).

Rules (mirrors the I1 null-timestamp safeguard):
- ``as_of`` is None / unparseable  -> stale -> excluded.
- Naive datetimes are assumed UTC.
- A source with no configured cap is kept (caps are opt-in per source) and
  logged at debug so the gap is visible.
- ``features.recency_window.enabled: false`` -> the filter is a no-op.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Union

from consensus_engine import config as cfg

log = logging.getLogger(__name__)

Timestamp = Union[datetime, str, int, float, None]


@dataclass
class SourceLeg:
    """One source's contribution to a multi-source computation."""
    source: str                      # config key under recency_window.max_age_min
    as_of: Timestamp = None          # data-as-of moment (UTC); None = unknown = stale
    weight: float = 1.0
    direction: str = ""              # optional signed direction ("long"/"short"/"buy"...)
    actor: str = ""                  # optional independent-actor identity (I3/I15)
    detail: dict = field(default_factory=dict)


def _coerce_ts(ts: Timestamp) -> Optional[datetime]:
    """Best-effort UTC datetime from the timestamp shapes our DB rows carry."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, (int, float)):
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_fresh(source: str, as_of: Timestamp, *, now: Optional[datetime] = None) -> bool:
    """True when `as_of` is inside `source`'s freshness cap.

    None/unparseable timestamps are stale (False). A source without a
    configured cap is fresh by definition (caps are opt-in).
    """
    if not cfg.get("features.recency_window.enabled", True):
        return True
    cap_min = cfg.get(f"features.recency_window.max_age_min.{source}", None)
    if cap_min is None:
        log.debug("recency_window: no max_age_min cap configured for source %r — leg kept", source)
        return True
    dt = _coerce_ts(as_of)
    if dt is None:
        return False
    now = now or datetime.now(timezone.utc)
    age_min = (now - dt).total_seconds() / 60.0
    # A slightly-future timestamp (clock skew) is fresh; a far-future one is bad data.
    if age_min < -60.0:
        return False
    return age_min <= float(cap_min)


def filter_fresh(legs: list[SourceLeg], *, now: Optional[datetime] = None) -> list[SourceLeg]:
    """Drop every leg outside its source's freshness cap.

    With `features.recency_window.enabled: false` this is an identity pass.
    """
    if not cfg.get("features.recency_window.enabled", True):
        return list(legs)
    now = now or datetime.now(timezone.utc)
    kept = []
    for leg in legs:
        if is_fresh(leg.source, leg.as_of, now=now):
            kept.append(leg)
        else:
            log.debug(
                "recency_window: dropped stale %s leg (as_of=%s)", leg.source, leg.as_of
            )
    return kept
