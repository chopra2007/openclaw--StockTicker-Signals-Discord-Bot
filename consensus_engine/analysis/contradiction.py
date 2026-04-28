"""A1: contradiction-penalty + macro-event blackout.

evaluate_contradiction is called after STRONG_ALERT threshold is reached.
If contradiction_index >= threshold AND we are NOT in a macro blackout window,
the signal is downgraded to WATCHLIST.

Shadow-mode: always computes ContradictionVerdict; only apply_penalty=True
when feature is enabled AND conditions are met.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import threading

from consensus_engine import config as cfg

log = logging.getLogger(__name__)

_YAML_PATH = Path(__file__).parent.parent / "data" / "macro_events.yaml"
_YAML_CACHE: dict | None = None
_YAML_LOADED_AT: float = 0.0
_YAML_LOCK = threading.Lock()
_CACHE_TTL = 3600.0  # 1 hour


def _load_macro_events() -> dict:
    global _YAML_CACHE, _YAML_LOADED_AT
    now = time.time()
    with _YAML_LOCK:
        if _YAML_CACHE is not None and (now - _YAML_LOADED_AT) < _CACHE_TTL:
            return _YAML_CACHE
        if not _YAML_PATH.exists():
            log.warning("[A1] macro_events.yaml not found at %s — treating as no blackout", _YAML_PATH)
            _YAML_CACHE = {}
            _YAML_LOADED_AT = now
            return _YAML_CACHE
        try:
            import yaml
            with open(_YAML_PATH) as f:
                data = yaml.safe_load(f) or {}
            _YAML_CACHE = data
            _YAML_LOADED_AT = now
            mtime = _YAML_PATH.stat().st_mtime
            age_days = (now - mtime) / 86400
            if age_days > 90:
                log.warning("[A1] macro_events.yaml is %.0f days old — quarterly refresh may be overdue", age_days)
            return _YAML_CACHE
        except Exception as e:
            log.warning("[A1] Failed to load macro_events.yaml: %s — treating as no blackout", e)
            _YAML_CACHE = {}
            _YAML_LOADED_AT = now
            return _YAML_CACHE


@dataclass
class ContradictionVerdict:
    apply_penalty: bool
    reason: str   # "below_threshold" | "macro_blackout" | "disabled" | "applied"
    macro_event: Optional[str] = None


def is_in_macro_blackout(now_utc: datetime, blackout_minutes: int = 30) -> tuple[bool, Optional[str]]:
    """Check if now_utc is within blackout_minutes of any macro event in yaml.

    Returns (in_window, event_label).
    """
    events = _load_macro_events()
    if not events:
        return False, None
    from dateutil import parser as dateutil_parser
    window = timedelta(minutes=blackout_minutes)
    for event_type, timestamps in events.items():
        if event_type == "schema_version":
            continue
        if not isinstance(timestamps, list):
            continue
        for ts_str in timestamps:
            try:
                event_dt = dateutil_parser.parse(str(ts_str))
                if event_dt.tzinfo is None:
                    event_dt = event_dt.replace(tzinfo=timezone.utc)
                now_aware = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
                if abs((now_aware - event_dt).total_seconds()) <= window.total_seconds():
                    label = f"{event_type}@{event_dt.strftime('%Y-%m-%dT%H:%M')}"
                    return True, label
            except Exception:
                continue
    return False, None


def evaluate_contradiction(
    contradiction_index: float,
    now_utc: datetime,
) -> ContradictionVerdict:
    """Compute A1 verdict. Always returns a verdict (shadow-mode safe).

    apply_penalty=True only when: enabled AND index >= threshold AND not in macro blackout.
    """
    if not cfg.get("features.contradiction_penalty.enabled", True):
        return ContradictionVerdict(apply_penalty=False, reason="disabled")

    threshold = cfg.get("features.contradiction_penalty.contradiction_max", 0.5)
    if contradiction_index < threshold:
        return ContradictionVerdict(apply_penalty=False, reason="below_threshold")

    blackout_minutes = cfg.get("features.contradiction_penalty.macro_blackout_minutes", 30)
    in_blackout, event_label = is_in_macro_blackout(now_utc, blackout_minutes)
    if in_blackout:
        return ContradictionVerdict(apply_penalty=False, reason="macro_blackout", macro_event=event_label)

    return ContradictionVerdict(apply_penalty=True, reason="applied")
