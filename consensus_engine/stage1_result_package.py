"""M9.1CW: one durable offline package for the first-four stage-1 results.

The package accepts only completed frozen comparisons and their exact accepted
winner event streams.  It stores no market data and performs no strategy run.
Its JSON record is immutable, fingerprinted, and safe to reopen before stage 2.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Sequence

from .first_pullback_stage1_comparison import (
    FirstPullbackStage1Comparison, compare_first_pullback_stage1,
)
from .hod_comp_rs_stage1_comparison import (
    HodCompRsStage1Comparison, compare_hod_comp_rs_stage1,
)
from .or_failure_stage1_comparison import (
    OrFailureStage1Comparison, compare_or_failure_stage1,
)
from .orb5_stage1_result import Orb5Stage1Comparison, compare_orb5_stage1
from .search_run_config import PLAYBOOKS, STAGE1_CANDIDATES, TRAINING_TICKERS
from .stage1_training_measurement import Stage1TrainingMeasurement
from .stage2_training_comparison import AcceptedStage1Winner, Stage2TrainingEvent
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc

PACKAGE_VERSION = "M91CW_FIRST4_STAGE1_RESULT_PACKAGE_V1"

_COMPARISON_TYPES = {
    "CRVOL_ORB5": Orb5Stage1Comparison,
    "HOD_COMP_RS": HodCompRsStage1Comparison,
    "OR_FAILURE_REV": OrFailureStage1Comparison,
    "FIRST_PULLBACK_VWAP": FirstPullbackStage1Comparison,
}
_COMPARISON_BUILDERS = {
    "CRVOL_ORB5": compare_orb5_stage1,
    "HOD_COMP_RS": compare_hod_comp_rs_stage1,
    "OR_FAILURE_REV": compare_or_failure_stage1,
    "FIRST_PULLBACK_VWAP": compare_first_pullback_stage1,
}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return as_utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return {"float_hex": value.hex()}
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise RecordError(f"unsupported package value: {type(value).__name__}")


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _valid_float(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"float_hex"}:
        return False
    try:
        float.fromhex(value["float_hex"])
    except (TypeError, ValueError):
        return False
    return True


def _measurement(row: Stage1TrainingMeasurement) -> dict[str, Any]:
    measured = row.measurement
    return {
        "policy_version": row.policy_version,
        "playbook": row.playbook,
        "candidate": {
            "candidate_id": measured.candidate.candidate_id,
            "settings": _json_value(measured.candidate.settings),
            "table_order": measured.candidate.table_order,
        },
        "mean_profit_r": _json_value(measured.mean_profit_r),
        "weekly_win_rate": _json_value(measured.weekly_win_rate),
        "drawdown_recovery_weeks": _json_value(measured.drawdown_recovery_weeks),
        "bootstrap_lower_bound": _json_value(row.bootstrap_lower_bound),
        "trade_count": row.trade_count,
        "week_count": row.week_count,
        "evaluated_tickers": list(row.evaluated_tickers),
        "disabled_rules": list(row.disabled_rules),
    }


def _event(event: Stage2TrainingEvent) -> dict[str, Any]:
    trade = event.trade
    return {
        "alerted_at": _json_value(event.alerted_at),
        "trade": {
            "playbook": trade.playbook,
            "candidate_id": trade.candidate_id,
            "ticker": trade.ticker,
            "direction": trade.direction,
            "closed_at": _json_value(trade.closed_at),
            "resolved_r": _json_value(trade.resolved_r),
            "cost_model_version": trade.cost_model_version,
            "costs_complete": trade.costs_complete,
            "tested_axes": list(trade.tested_axes),
            "input_record_ids": list(trade.input_record_ids),
        },
    }


def _accepted_entry(comparison: object, winner: AcceptedStage1Winner) -> dict[str, Any]:
    playbook = winner.playbook
    expected_type = _COMPARISON_TYPES.get(playbook)
    if expected_type is None or not isinstance(comparison, expected_type):
        raise RecordError("each first-four playbook needs its accepted comparison type")
    if _COMPARISON_BUILDERS[playbook](comparison.runs) != comparison:
        raise RecordError("stage-1 comparison does not match its candidate runs")
    if comparison.status != "RANKED" or comparison.blockers or comparison.winner is None:
        raise RecordError("stage-1 packages accept only ranked comparisons without blockers")
    if winner.measurement != comparison.winner:
        raise RecordError("accepted winner does not match its comparison")

    candidates = STAGE1_CANDIDATES[playbook]
    runs_by_id = {run.candidate_id: run for run in comparison.runs}
    if tuple(runs_by_id) != tuple(candidate.candidate_id for candidate in candidates):
        raise RecordError("comparison runs must keep the frozen candidate order")
    run_measurements = tuple(runs_by_id[candidate.candidate_id].measurement
                             for candidate in candidates)
    if any(row is None for row in run_measurements):
        raise RecordError("every frozen candidate needs a complete measurement")
    winner_by_id = {row.measurement.candidate.candidate_id: row
                    for row in winner.candidate_measurements}
    if (tuple(winner_by_id) != tuple(candidate.candidate_id for candidate in candidates)
            or tuple(winner_by_id[candidate.candidate_id] for candidate in candidates)
            != run_measurements):
        raise RecordError("accepted winner must preserve every comparison measurement")

    winning_run = runs_by_id[winner.measurement.measurement.candidate.candidate_id]
    events = tuple(winner.events)
    if not events or any(not isinstance(event, Stage2TrainingEvent) for event in events):
        raise RecordError("accepted winner needs resolved alert-time events")
    resolved = getattr(winning_run, "resolved", None)
    if resolved is not None and tuple(event.trade for event in events) != tuple(resolved):
        raise RecordError("accepted alert-time events must match the winning resolved trades")
    if playbook == "CRVOL_ORB5" and winner != comparison.accepted_winner:
        raise RecordError("ORB5 package winner must be the comparison's accepted winner")

    source_ids = tuple(sorted({record_id for event in events
                               for record_id in event.trade.input_record_ids}))
    if not source_ids:
        raise RecordError("accepted events must preserve their source record identities")
    coverage = comparison.runs[0].evaluated_sessions
    rows = []
    for candidate in candidates:
        run = runs_by_id[candidate.candidate_id]
        if run.evaluated_sessions != coverage:
            raise RecordError("candidate retained-session coverage must match")
        exclusions = getattr(run, "exclusions", getattr(run, "excluded", ()))
        rows.append({
            "candidate_id": candidate.candidate_id,
            "runner_version": run.version,
            "measurement": _measurement(run.measurement),
            "retained_session_coverage": _json_value(run.evaluated_sessions),
            "exclusions": _json_value(exclusions),
        })
    return {
        "playbook": playbook,
        "comparison_version": comparison.version,
        "comparison_status": comparison.status,
        "winner_candidate_id": winner.measurement.measurement.candidate.candidate_id,
        "candidates": rows,
        "resolved_alert_time_events": [_event(event) for event in events],
        "source_record_identities": list(source_ids),
    }


def _validate_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "package_version", "playbooks", "source_record_identities",
    }:
        raise RecordError("stage-1 package has an invalid top-level shape")
    if payload["package_version"] != PACKAGE_VERSION:
        raise RecordError("stage-1 package version is not accepted")
    rows = payload["playbooks"]
    if not isinstance(rows, list) or [row.get("playbook") for row in rows
                                     if isinstance(row, dict)] != list(PLAYBOOKS):
        raise RecordError("stage-1 package must contain the first four playbooks in order")
    source_ids: set[str] = set()
    for row, playbook in zip(rows, PLAYBOOKS):
        if set(row) != {
            "playbook", "comparison_version", "comparison_status",
            "winner_candidate_id", "candidates", "resolved_alert_time_events",
            "source_record_identities",
        } or row["comparison_status"] != "RANKED" or not isinstance(
                row["comparison_version"], str) or not row["comparison_version"]:
            raise RecordError("stage-1 package comparison record is incomplete")
        candidates = row["candidates"]
        expected = [candidate.candidate_id for candidate in STAGE1_CANDIDATES[playbook]]
        if (not isinstance(candidates, list)
                or [item.get("candidate_id") for item in candidates
                    if isinstance(item, dict)] != expected
                or row["winner_candidate_id"] not in expected):
            raise RecordError("stage-1 package candidate catalog is incomplete")
        reference_coverage = None
        for item, candidate in zip(candidates, STAGE1_CANDIDATES[playbook]):
            if set(item) != {
                "candidate_id", "runner_version", "measurement",
                "retained_session_coverage", "exclusions",
            } or not isinstance(item["runner_version"], str) or not item["runner_version"]:
                raise RecordError("stage-1 package candidate record is incomplete")
            measured = item["measurement"]
            if not isinstance(measured, dict) or set(measured) != {
                "policy_version", "playbook", "candidate", "mean_profit_r",
                "weekly_win_rate", "drawdown_recovery_weeks",
                "bootstrap_lower_bound", "trade_count", "week_count",
                "evaluated_tickers", "disabled_rules",
            }:
                raise RecordError("stage-1 package measurement record is incomplete")
            identity = measured["candidate"]
            if (identity != {
                    "candidate_id": candidate.candidate_id,
                    "settings": _json_value(candidate.settings),
                    "table_order": candidate.table_order,
                } or measured["playbook"] != playbook
                    or not isinstance(measured["policy_version"], str)
                    or not measured["policy_version"]
                    or measured["evaluated_tickers"] != list(TRAINING_TICKERS)
                    or any(not _valid_float(measured[name]) for name in (
                        "mean_profit_r", "weekly_win_rate", "drawdown_recovery_weeks",
                        "bootstrap_lower_bound",
                    ))
                    or type(measured["trade_count"]) is not int
                    or type(measured["week_count"]) is not int
                    or not isinstance(measured["disabled_rules"], list)
                    or not all(isinstance(value, str) and value
                               for value in measured["disabled_rules"])):
                raise RecordError("stage-1 package measurement identity does not match")
            coverage = item["retained_session_coverage"]
            if not isinstance(coverage, list) or not coverage:
                raise RecordError("stage-1 package retained-session coverage is missing")
            try:
                coverage_tickers = {entry[0] for entry in coverage
                                    if isinstance(entry, list) and len(entry) == 2}
                coverage_dates = tuple(date.fromisoformat(entry[1]) for entry in coverage)
            except (IndexError, TypeError, ValueError) as exc:
                raise RecordError("stage-1 package retained-session coverage is invalid") from exc
            if coverage_tickers != set(TRAINING_TICKERS) or len(coverage_dates) != len(coverage):
                raise RecordError("stage-1 package retained-session coverage is invalid")
            if reference_coverage is None:
                reference_coverage = coverage
            elif coverage != reference_coverage:
                raise RecordError("stage-1 package retained-session coverage does not match")
        events = row["resolved_alert_time_events"]
        ids = row["source_record_identities"]
        if not isinstance(events, list) or not events or not isinstance(ids, list) or not ids:
            raise RecordError("stage-1 package is missing events or source identities")
        for event in events:
            if (not isinstance(event, dict) or set(event) != {"alerted_at", "trade"}
                    or not isinstance(event["alerted_at"], str)
                    or not isinstance(event["trade"], dict)
                    or set(event["trade"]) != {
                        "playbook", "candidate_id", "ticker", "direction", "closed_at",
                        "resolved_r", "cost_model_version", "costs_complete",
                        "tested_axes", "input_record_ids",
                    }
                    or event["trade"]["playbook"] != playbook
                    or event["trade"]["candidate_id"] != row["winner_candidate_id"]
                    or event["trade"]["costs_complete"] is not True
                    or event["trade"]["direction"] not in {"LONG", "SHORT"}
                    or not isinstance(event["trade"]["closed_at"], str)
                    or not _valid_float(event["trade"]["resolved_r"])
                    or not isinstance(event["trade"]["input_record_ids"], list)
                    or not event["trade"]["input_record_ids"]
                    or any(not isinstance(value, str) or not value
                           for value in event["trade"]["input_record_ids"])):
                raise RecordError("stage-1 package resolved event is incomplete")
            try:
                as_utc(datetime.fromisoformat(event["alerted_at"].replace("Z", "+00:00")))
                as_utc(datetime.fromisoformat(event["trade"]["closed_at"].replace("Z", "+00:00")))
            except (AttributeError, TypeError, ValueError) as exc:
                raise RecordError("stage-1 package event time is invalid") from exc
        event_ids = {identity for event in events
                     for identity in event.get("trade", {}).get("input_record_ids", [])}
        if (any(not isinstance(value, str) or not value for value in ids)
                or sorted(event_ids) != ids):
            raise RecordError("stage-1 package source identities do not match its events")
        source_ids.update(ids)
    if sorted(source_ids) != payload["source_record_identities"]:
        raise RecordError("stage-1 package source identity index does not match")
    return payload


@dataclass(frozen=True)
class Stage1ResultPackage:
    canonical_json: str
    fingerprint: str

    def __post_init__(self) -> None:
        try:
            payload = json.loads(self.canonical_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RecordError("stage-1 package JSON is invalid") from exc
        _validate_payload(payload)
        if _canonical(payload) != self.canonical_json:
            raise RecordError("stage-1 package JSON is not canonical")
        expected = hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()
        if self.fingerprint != expected:
            raise RecordError("stage-1 package fingerprint does not match")

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_json)


def build_stage1_result_package(
    comparisons: Sequence[object], winners: Sequence[AcceptedStage1Winner],
) -> Stage1ResultPackage:
    if len(comparisons) != len(PLAYBOOKS) or len(winners) != len(PLAYBOOKS):
        raise RecordError("one comparison and accepted winner are required per playbook")
    winners_by_playbook = {winner.playbook: winner for winner in winners
                           if isinstance(winner, AcceptedStage1Winner)}
    if tuple(winners_by_playbook) != PLAYBOOKS:
        raise RecordError("accepted winners must name the first four playbooks in order")
    entries = tuple(_accepted_entry(comparison, winners_by_playbook[playbook])
                    for comparison, playbook in zip(comparisons, PLAYBOOKS))
    if tuple(entry["playbook"] for entry in entries) != PLAYBOOKS:
        raise RecordError("comparisons must use the frozen first-four playbook order")
    source_ids = sorted({identity for entry in entries
                         for identity in entry["source_record_identities"]})
    payload = {
        "package_version": PACKAGE_VERSION,
        "playbooks": list(entries),
        "source_record_identities": source_ids,
    }
    canonical = _canonical(payload)
    return Stage1ResultPackage(
        canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest())


def write_stage1_result_package(path: Path, package: Stage1ResultPackage) -> None:
    if not isinstance(package, Stage1ResultPackage):
        raise RecordError("a validated stage-1 package is required")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (_canonical({"fingerprint": package.fingerprint,
                           "record": package.as_dict()}) + "\n").encode("utf-8")
    if destination.exists():
        if destination.read_bytes() == encoded:
            return
        raise RecordError("an immutable stage-1 package already exists at this path")
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        raise RecordError("a stage-1 package temporary file already exists")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_stage1_result_package(path: Path) -> Stage1ResultPackage:
    try:
        wrapper = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecordError("stage-1 package cannot be reopened") from exc
    if not isinstance(wrapper, dict) or set(wrapper) != {"fingerprint", "record"}:
        raise RecordError("stage-1 package wrapper is invalid")
    canonical = _canonical(_validate_payload(wrapper["record"]))
    return Stage1ResultPackage(canonical, wrapper["fingerprint"])


__all__ = [
    "PACKAGE_VERSION", "Stage1ResultPackage", "build_stage1_result_package",
    "read_stage1_result_package", "write_stage1_result_package",
]
