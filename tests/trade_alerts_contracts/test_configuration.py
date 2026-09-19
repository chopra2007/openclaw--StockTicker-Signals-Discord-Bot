"""M1.2 canonical configuration contracts.

This module is intentionally run only through the protected contract launcher.
"""

import hashlib
import json
import math
import sys
from dataclasses import FrozenInstanceError
from datetime import date, time

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)


from consensus_engine import config
from consensus_engine.trade_alerts_config import ConfigError, TradeAlertsConfig


STRATEGIES = (
    "CRVOL_ORB5", "HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP",
    "INDEX_OPEN_DRIVE_BREADTH", "GAP_FADE_FAILED_OPEN", "CAT_FIRST_CONSOL",
    "VP_ACCEPT_LVN",
)


def _settings(**overrides):
    value = {"schema_version": 1}
    value.update(overrides)
    return value


def _enabled_strategy(strategy="CRVOL_ORB5"):
    return {
        "enabled": True,
        "strategy_version": "TEST_V1",
        "window": {"start_minutes": 0, "end_minutes": 5},
    }


def _enabled_settings(**overrides):
    value = _settings(
        config_version="FOUNDATION_V1",
        evaluation_enabled=True,
        strategies={strategy: _enabled_strategy(strategy) for strategy in STRATEGIES[:1]},
        data={"collection_enabled": False, "premarket_start": "06:00"},
        options={"enabled": True, "policy_version": "TEST_V1"},
        research={"enabled": True, "policy_version": "TEST_V1"},
        alerts={"delivery_enabled": True, "sink": "discord"},
    )
    value.update(overrides)
    return value


def test_defaults_are_complete_and_all_strategies_are_disabled():
    value = TradeAlertsConfig({"schema_version": 1}).as_dict()
    assert value["schema_version"] == 1
    assert value["config_version"] == "FOUNDATION_V1"
    assert value["evaluation_enabled"] is False
    assert set(value["strategies"]) == set(STRATEGIES)
    assert all(row == {"enabled": False, "strategy_version": None, "window": None}
               for row in value["strategies"].values())
    assert value["data"] == {"collection_enabled": False, "premarket_start": None}
    assert value["options"] == {"enabled": False, "policy_version": None}
    assert value["research"] == {"enabled": False, "policy_version": None}
    assert value["alerts"] == {"delivery_enabled": False, "sink": "recording"}


def test_reordering_and_omitted_defaults_have_same_hash():
    first = TradeAlertsConfig(_enabled_settings())
    second = TradeAlertsConfig({
        "alerts": {"sink": "discord", "delivery_enabled": True},
        "research": {"policy_version": "TEST_V1", "enabled": True},
        "options": {"policy_version": "TEST_V1", "enabled": True},
        "data": {"premarket_start": "06:00", "collection_enabled": False},
        "strategies": {"CRVOL_ORB5": _enabled_strategy()},
        "evaluation_enabled": True,
        "config_version": "FOUNDATION_V1",
        "schema_version": 1,
    })
    assert first.config_hash == second.config_hash
    assert first.canonical_json == second.canonical_json
    assert TradeAlertsConfig({}) == TradeAlertsConfig(TradeAlertsConfig({}).as_dict())


def test_changed_setting_or_version_changes_hash():
    base = TradeAlertsConfig(_enabled_settings())
    changed_setting = _enabled_settings()
    changed_setting["data"]["premarket_start"] = "06:15"
    changed_version = _enabled_settings(config_version="FOUNDATION_V2")
    assert base.config_hash != TradeAlertsConfig(changed_setting).config_hash
    assert base.config_hash != TradeAlertsConfig(changed_version).config_hash


def test_snapshot_and_as_dict_are_detached_from_inputs_and_outputs():
    raw = _enabled_settings()
    snapshot = TradeAlertsConfig(raw)
    raw["strategies"]["CRVOL_ORB5"]["window"]["end_minutes"] = 99
    detached = snapshot.as_dict()
    detached["strategies"]["CRVOL_ORB5"]["window"]["end_minutes"] = 88
    assert snapshot.as_dict()["strategies"]["CRVOL_ORB5"]["window"]["end_minutes"] == 5


def test_getter_uses_cached_config_and_reload_detaches_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("trade_alerts:\n  schema_version: 1\n")
    monkeypatch.setattr(config, "_DEFAULT_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_config", None)
    first = config.get_trade_alerts_config()
    path.write_text("trade_alerts:\n  schema_version: 1\n  config_version: CHANGED\n")
    assert config.get_trade_alerts_config().as_dict() == first.as_dict()
    config.reload()
    second = config.get_trade_alerts_config()
    assert second is not first
    assert second.config_version == "CHANGED"
    assert first.config_version == "FOUNDATION_V1"
    config.load_config()["trade_alerts"]["config_version"] = "MUTATED"
    assert second.config_version == "CHANGED"
    assert config.get_trade_alerts_config().config_version == "MUTATED"


@pytest.mark.parametrize("payload", [
    {"schema_version": True},
    {"schema_version": 1.0},
    {"unknown": 1},
    {"data": {"unknown": False}},
    {"strategies": {"UNKNOWN": {"enabled": False, "strategy_version": None, "window": None}}},
    {"config_version": "bad token!"},
    {"data": {"premarket_start": "6:00"}},
    {"alerts": {"sink": "webhook"}},
])
def test_invalid_types_and_unknown_fields_raise_config_error(payload):
    with pytest.raises(ConfigError):
        TradeAlertsConfig(_settings(**payload))


@pytest.mark.parametrize("payload", [
    {"strategies": {"CRVOL_ORB5": {"enabled": True, "strategy_version": None, "window": None}}},
    {"strategies": {"CRVOL_ORB5": {"enabled": True, "strategy_version": "TEST_V1", "window": None}}},
    {"evaluation_enabled": True},
    {"options": {"enabled": True}},
    {"research": {"enabled": True}},
    {"alerts": {"delivery_enabled": True, "sink": "recording"}},
])
def test_cross_field_requirements_raise_config_error(payload):
    with pytest.raises(ConfigError):
        TradeAlertsConfig(_settings(**payload))


@pytest.mark.parametrize("window", [
    {"start_minutes": -1, "end_minutes": 5},
    {"start_minutes": 5, "end_minutes": 5},
    {"start_minutes": 5, "end_minutes": 4},
    {"start_minutes": 0, "end_minutes": 1441},
])
def test_strategy_window_bounds_raise_config_error(window):
    with pytest.raises(ConfigError):
        TradeAlertsConfig(_settings(strategies={
            "CRVOL_ORB5": {"enabled": True, "strategy_version": "TEST_V1", "window": window},
        }))


def test_null_trade_alerts_subtree_is_invalid_but_missing_subtree_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "_DEFAULT_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_config", None)
    path.write_text("other:\n  value: 1\n")
    assert config.get_trade_alerts_config().config_version == "FOUNDATION_V1"
    config.reload()
    path.write_text("trade_alerts: null\n")
    with pytest.raises(ConfigError):
        config.reload()
    assert config._config is None


def test_secret_and_environment_references_are_rejected_without_echoing_values():
    for payload in (
        _settings(api_key="SHOULD_NOT_APPEAR"),
        _settings(data={"premarket_start": "$SECRET_VALUE"}),
    ):
        with pytest.raises(ConfigError) as error:
            TradeAlertsConfig(payload)
        assert "SHOULD_NOT_APPEAR" not in str(error.value)
        assert "SECRET_VALUE" not in str(error.value)


def test_legacy_secret_changes_do_not_change_trade_alerts_hash(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "_DEFAULT_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_config", None)
    monkeypatch.setenv("M12_LEGACY_TOKEN", "SYNTHETIC_SECRET_ONE")
    path.write_text("api_keys:\n  token: $M12_LEGACY_TOKEN\ntrade_alerts:\n  schema_version: 1\n")
    first = config.get_trade_alerts_config()
    assert config.load_config()["api_keys"]["token"] == "SYNTHETIC_SECRET_ONE"
    monkeypatch.setenv("M12_LEGACY_TOKEN", "SYNTHETIC_SECRET_TWO")
    config.reload()
    second = config.get_trade_alerts_config()
    assert config.load_config()["api_keys"]["token"] == "SYNTHETIC_SECRET_TWO"
    assert first.config_hash == second.config_hash
    assert "api_keys" not in first.canonical_json
    assert "SYNTHETIC_SECRET" not in first.canonical_json + second.canonical_json


def test_frozen_attributes_cannot_be_changed():
    with pytest.raises((FrozenInstanceError, AttributeError)):
        TradeAlertsConfig({"schema_version": 1}).config_version = "CHANGED"


@pytest.mark.parametrize("payload", [
    {"evaluation_enabled": 0}, {"evaluation_enabled": 1},
    {"evaluation_enabled": "false"}, {"data": {"collection_enabled": 0}},
    {"data": {"collection_enabled": "false"}},
])
def test_booleans_are_strict(payload):
    with pytest.raises(ConfigError):
        TradeAlertsConfig(_settings(**payload))


@pytest.mark.parametrize("window", [
    {"start_minutes": 0.0, "end_minutes": 5},
    {"start_minutes": 0, "end_minutes": 5.0},
    {"start_minutes": math.nan, "end_minutes": 5},
    {"start_minutes": 0, "end_minutes": math.inf},
])
def test_window_numbers_are_strict_and_finite(window):
    with pytest.raises(ConfigError):
        TradeAlertsConfig(_settings(strategies={
            "CRVOL_ORB5": {"enabled": False, "strategy_version": None, "window": window},
        }))


def test_environment_reference_is_rejected_before_legacy_resolution(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("M12_SYNTHETIC", "FOUND_BY_LEGACY_RESOLVER")
    path.write_text("trade_alerts:\n  schema_version: 1\n  config_version: $M12_SYNTHETIC\n")
    monkeypatch.setattr(config, "_DEFAULT_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_config", None)
    with pytest.raises(ConfigError) as error:
        config.get_trade_alerts_config()
    assert "FOUND_BY_LEGACY_RESOLVER" not in str(error.value)
    assert config._config is None


def test_known_default_hash_matches_canonical_record(tmp_path):
    snapshot = TradeAlertsConfig({"schema_version": 1})
    # Independently derived from the explicit dormant configuration section.
    assert snapshot.config_hash == "bbe2460d8bd241a94d019da3542375bee4170bcd887e8b57315927ed4d290591"
    canonical = json.dumps(snapshot.as_dict(), sort_keys=True, separators=(",", ":"))
    assert snapshot.canonical_json == canonical
    assert snapshot.config_hash == hashlib.sha256(canonical.encode()).hexdigest()
    (tmp_path / "m12-config-proof.json").write_text(json.dumps({
        "config_hash": snapshot.config_hash, "canonical_json": canonical,
    }, sort_keys=True) + "\n")


def test_supplied_window_remains_explicit_for_existing_clock_consumer():
    snapshot = TradeAlertsConfig(_enabled_settings())
    assert snapshot.as_dict()["strategies"]["CRVOL_ORB5"]["window"] == {"start_minutes": 0, "end_minutes": 5}
    from consensus_engine.utils import time_context
    from zoneinfo import ZoneInfo
    settings = snapshot.as_dict()
    bounds = time_context.premarket_bounds(
        date(2026, 3, 9), time.fromisoformat(settings["data"]["premarket_start"]))
    assert bounds[0].astimezone(ZoneInfo("America/Los_Angeles")).strftime("%H:%M") == "06:00"
    from datetime import timedelta
    window = settings["strategies"]["CRVOL_ORB5"]["window"]
    opened, closed = time_context.regular_session_window(
        date(2026, 3, 9), timedelta(minutes=window["start_minutes"]),
        timedelta(minutes=window["end_minutes"]))
    assert opened.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%H:%M") == "06:30"
    assert closed.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%H:%M") == "06:35"


def test_enabled_settings_pass_through_real_loader_without_starting_runtime(tmp_path, monkeypatch):
    import yaml
    path = tmp_path / "config.yaml"
    enabled = _enabled_settings()
    enabled["data"]["collection_enabled"] = True
    path.write_text(yaml.safe_dump({"trade_alerts": enabled, "legacy": {"value": 7}}))
    monkeypatch.setattr(config, "_DEFAULT_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_config", None)
    snapshot = config.get_trade_alerts_config()
    assert snapshot.as_dict()["evaluation_enabled"] is True
    assert snapshot.as_dict()["data"]["collection_enabled"] is True
    assert snapshot.as_dict()["options"]["enabled"] is True
    assert snapshot.as_dict()["research"]["enabled"] is True
    assert snapshot.as_dict()["alerts"]["delivery_enabled"] is True
    assert config.get("legacy.value") == 7


@pytest.mark.parametrize("settings", [None, [], "invalid", {"strategies": None},
                                      {"strategies": {"CRVOL_ORB5": []}},
                                      {"options": None}, {"research": []},
                                      {"data": {"premarket_start": "24:00"}}])
def test_malformed_sections_are_rejected(settings):
    with pytest.raises(ConfigError):
        TradeAlertsConfig(settings)
