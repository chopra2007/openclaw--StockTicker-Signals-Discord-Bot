"""M9.1EQ binding record for the audited saved one-minute bars.

This module publishes which inputs in the existing first-four adapter-count
runner may use the audited OHLCV fields and which inputs must stay off.  It does
not read prices, run a playbook, or open the held-out evaluation.
"""

from __future__ import annotations

from typing import Any, Mapping

from .saved_market_data_audit import AUDIT_VERSION, GAP_DEPENDENT_RULES


BINDING_VERSION = "M91EQ_SAVED_BAR_INPUT_BINDING_V1"
# Kept explicit so the record generator does not import the application stack.
# The focused contract test compares it with retained_adapter_run at runtime.
ADAPTER_RUN_VERSION = "M91BZ_ADAPTER_RUN_V4"
ENABLED_IF_COMPLETE = "ENABLED_IF_REQUIRED_BAR_WINDOWS_COMPLETE"
OFF_UNTESTED = "OFF_UNTESTED"

# These names are the bar-only calls made by retained_adapter_run.  A row being
# enabled does not say that every symbol-date is complete; each adapter still
# applies its own interval, identity, unit and point-in-time checks.
_ENABLED = (
    ("CRVOL_ORB5", "opening_range_5m", "open,high,low,event_time"),
    ("CRVOL_ORB5", "latest_bar_observation", "close,event_time"),
    ("HOD_COMP_RS", "rs_15m", "open,close,event_time,benchmark_bars"),
    ("HOD_COMP_RS", "rs_warmup", "open,close,event_time,benchmark_bars"),
    ("HOD_COMP_RS", "reference_extreme", "high,low,event_time"),
    ("HOD_COMP_RS", "compression", "high,low,event_time"),
    ("HOD_COMP_RS", "rvol", "volume,event_time,20_reference_openings"),
    ("HOD_COMP_RS", "session_vwap", "high,low,close,volume,event_time"),
    ("OR_FAILURE_REV", "tape_and_close", "close,event_time"),
    ("FIRST_PULLBACK_VWAP", "last_trade", "close,event_time"),
    ("FIRST_PULLBACK_VWAP", "vwap_level", "high,low,close,volume,event_time"),
)

_DISABLED = (
    ("HOD_COMP_RS", "median_dollar_volume", "SEPARATE_DAILY_HISTORY_NOT_BOUND"),
    ("HOD_COMP_RS", "open_return", "PRIOR_DAILY_CLOSE_AND_OPENING_TRADE_NOT_BOUND"),
    ("HOD_COMP_RS", "daily_atr_pct", "SEPARATE_DAILY_ATR_SOURCE_NOT_BOUND"),
    ("SHARED", "atr_1m", "EXACT_ATR_SOURCE_AND_CONVENTION_UNRESOLVED"),
    ("FIRST_PULLBACK_VWAP", "vwap_slope", "VWAP_SLOPE_CONVENTION_UNDEFINED"),
    ("FIRST_PULLBACK_VWAP", "vwap_crosses", "VWAP_CROSS_COUNT_CONVENTION_UNDEFINED"),
    ("FIRST_PULLBACK_VWAP", "quote_decision", "HISTORICAL_BID_ASK_ABSENT"),
    ("HOD_COMP_RS", "quote_and_status_inputs", "HISTORICAL_BID_ASK_AND_STATUS_ABSENT"),
    ("CRVOL_ORB5", "tape_intensity", "FIFTEEN_SECOND_TAPE_PRINTS_ABSENT"),
    ("CRVOL_ORB5", "quote_and_status_inputs", "HISTORICAL_BID_ASK_AND_STATUS_ABSENT"),
    ("CRVOL_ORB5", "bar_finality", "FINALITY_UNKNOWN"),
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def bind_saved_bar_inputs(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact enabled/off matrix for one unchanged M9.1EP audit."""
    _require(isinstance(audit, Mapping), "saved market data audit must be an object")
    _require(audit.get("version") == AUDIT_VERSION, "saved market data audit version mismatch")
    _require(audit.get("mode") == "READ_ONLY_OFFLINE_INVENTORY", "audit mode is not read-only")
    _require(audit.get("network_used") is False and audit.get("spend_usd") == 0,
             "audit must have zero network use and spend")
    _require(audit.get("held_out_evaluation_run") is False,
             "binding requires the held-out evaluation to remain closed")
    support = audit.get("field_support")
    _require(isinstance(support, Mapping), "audit field support is missing")
    _require(support.get("bar_native_ohlcv") == "OBSERVED", "bar-native OHLCV was not observed")
    _require(support.get("event_time") == "MINUTE_START_FROM_SAVED_DATE_AND_MINUTE",
             "saved event-time convention mismatch")
    _require(support.get("bid_ask") == "ABSENT", "bid/ask gap must remain explicit")
    _require(support.get("finality") == "UNKNOWN", "finality must remain unknown")
    _require(support.get("adjustment_provenance") == "NOT_PROVEN_BY_SAVED_PARQUET",
             "adjustment provenance must remain unproven")

    gaps = audit.get("gaps")
    _require(isinstance(gaps, Mapping) and set(gaps) == set(GAP_DEPENDENT_RULES),
             "D-104 gap list mismatch")
    _require(all(row == {"status": "GAP", "dependent_rules": OFF_UNTESTED}
                 for row in gaps.values()), "D-104 gap status mismatch")
    files = audit.get("files")
    _require(isinstance(files, list) and len(files) == 2, "exactly two audited files are required")
    identities = []
    for row in files:
        _require(isinstance(row, Mapping), "audited file row must be an object")
        path, digest = row.get("path"), row.get("sha256")
        _require(isinstance(path, str) and path and isinstance(digest, str) and len(digest) == 64,
                 "audited file identity is incomplete")
        identities.append({"path": path, "sha256": digest})
    _require(len({row["sha256"] for row in identities}) == 2,
             "audited files must have different identities")

    return {
        "version": BINDING_VERSION,
        "source_audit_version": AUDIT_VERSION,
        "adapter_run_version": ADAPTER_RUN_VERSION,
        "source_files": identities,
        "enabled_inputs": [
            {"playbook": playbook, "input": name, "status": ENABLED_IF_COMPLETE,
             "required_observed_fields": fields.split(",")}
            for playbook, name, fields in _ENABLED
        ],
        "disabled_inputs": [
            {"playbook": playbook, "input": name, "status": OFF_UNTESTED,
             "reason": reason}
            for playbook, name, reason in _DISABLED
        ],
        "d104_gaps": {name: dict(gaps[name]) for name in sorted(gaps)},
        "held_out_evaluation": {
            "status": "CLOSED",
            "reason": "INPUT_BINDING_AND_PROTECTED_PROOF_REQUIRED_BEFORE_RESULTS",
        },
        "promotion_or_live_release": False,
        "network_used": False,
        "spend_usd": 0,
    }


__all__ = ["BINDING_VERSION", "ENABLED_IF_COMPLETE", "OFF_UNTESTED",
           "bind_saved_bar_inputs"]
