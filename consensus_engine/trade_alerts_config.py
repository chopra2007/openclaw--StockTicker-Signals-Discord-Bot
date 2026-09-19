"""Validated, non-secret configuration snapshots for the trade-alert extension.

This foundation stores requested settings, not trading approval or runtime
readiness. Strategy thresholds and unfinished policies are intentionally absent.
The existing config module remains the only file/environment loader.
"""

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any


STRATEGY_IDS = (
    "CRVOL_ORB5", "HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP",
    "INDEX_OPEN_DRIVE_BREADTH", "GAP_FADE_FAILED_OPEN", "CAT_FIRST_CONSOL",
    "VP_ACCEPT_LVN",
)


class ConfigError(ValueError):
    """An invalid setting, reported without echoing its supplied value."""


def _section(value: Any, defaults: dict, path: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be a mapping")
    if value.keys() - defaults.keys():
        raise ConfigError(f"{path} contains unsupported fields")
    return defaults | value


def _boolean(value: Any, path: str) -> None:
    if type(value) is not bool:
        raise ConfigError(f"{path} must be true or false")


def _version(value: Any, path: str, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise ConfigError(f"{path} must be a literal version label")


def _window(value: Any, path: str) -> dict | None:
    if value is None:
        return None
    result = _section(value, {"start_minutes": None, "end_minutes": None}, path)
    start, end = result["start_minutes"], result["end_minutes"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= 1440:
        raise ConfigError(f"{path} must satisfy 0 <= start_minutes < end_minutes <= 1440")
    return result


def _normalize(settings: dict) -> dict:
    root = _section(settings, {
        "schema_version": 1,
        "config_version": "FOUNDATION_V1",
        "evaluation_enabled": False,
        "strategies": {},
        "data": {},
        "options": {},
        "alerts": {},
        "research": {},
    }, "trade_alerts")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise ConfigError("trade_alerts.schema_version must be 1")
    _version(root["config_version"], "trade_alerts.config_version")
    _boolean(root["evaluation_enabled"], "trade_alerts.evaluation_enabled")

    strategies = _section(root["strategies"], {name: {} for name in STRATEGY_IDS},
                          "trade_alerts.strategies")
    for name, value in strategies.items():
        path = f"trade_alerts.strategies.{name}"
        strategy = _section(value, {
            "enabled": False, "strategy_version": None, "window": None,
        }, path)
        _boolean(strategy["enabled"], f"{path}.enabled")
        _version(strategy["strategy_version"], f"{path}.strategy_version", optional=True)
        strategy["window"] = _window(strategy["window"], f"{path}.window")
        if strategy["enabled"] and (strategy["strategy_version"] is None
                                    or strategy["window"] is None):
            raise ConfigError(f"{path} requires an explicit version and window when enabled")
        strategies[name] = strategy
    root["strategies"] = strategies
    if root["evaluation_enabled"] and not any(s["enabled"] for s in strategies.values()):
        raise ConfigError("trade_alerts.evaluation_enabled requires an enabled strategy")

    data = _section(root["data"], {"collection_enabled": False, "premarket_start": None},
                    "trade_alerts.data")
    _boolean(data["collection_enabled"], "trade_alerts.data.collection_enabled")
    start = data["premarket_start"]
    if start is not None and (not isinstance(start, str)
                              or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", start)):
        raise ConfigError("trade_alerts.data.premarket_start must be a Pacific HH:MM string or null")
    root["data"] = data

    for name in ("options", "research"):
        path = f"trade_alerts.{name}"
        policy = _section(root[name], {"enabled": False, "policy_version": None}, path)
        _boolean(policy["enabled"], f"{path}.enabled")
        _version(policy["policy_version"], f"{path}.policy_version", optional=True)
        if policy["enabled"] and policy["policy_version"] is None:
            raise ConfigError(f"{path} requires an explicit policy_version when enabled")
        root[name] = policy

    alerts = _section(root["alerts"], {"delivery_enabled": False, "sink": "recording"},
                      "trade_alerts.alerts")
    _boolean(alerts["delivery_enabled"], "trade_alerts.alerts.delivery_enabled")
    if alerts["sink"] not in ("recording", "discord"):
        raise ConfigError("trade_alerts.alerts.sink must be recording or discord")
    if alerts["delivery_enabled"] and (not root["evaluation_enabled"]
                                       or alerts["sink"] != "discord"):
        raise ConfigError("trade_alerts.alerts delivery requires evaluation and the discord sink")
    root["alerts"] = alerts
    return root


@dataclass(frozen=True, init=False)
class TradeAlertsConfig:
    """Fixed session settings, independent of the loader cache and later reloads.

    Canonical UTF-8 JSON includes defaults and both versions, with sorted keys,
    compact separators and no non-finite numbers. The SHA-256 covers only this
    dedicated namespace. as_dict() returns a fresh copy for consumer use; retain
    this snapshot, rather than reloading it, for the duration of a session.
    """

    config_version: str
    config_hash: str
    canonical_json: str

    def __init__(self, settings: dict) -> None:
        normalized = _normalize(settings)
        canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False)
        object.__setattr__(self, "config_version", normalized["config_version"])
        object.__setattr__(self, "canonical_json", canonical)
        object.__setattr__(self, "config_hash", hashlib.sha256(canonical.encode("utf-8")).hexdigest())

    def as_dict(self) -> dict[str, Any]:
        """Return detached settings; edits cannot change this session's facts."""
        return json.loads(self.canonical_json)
