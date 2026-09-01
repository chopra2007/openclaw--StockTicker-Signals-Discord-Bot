#!/usr/bin/env python3
"""Deterministic, repository-local outcome loop controller."""

from __future__ import annotations

import argparse
import contextlib
import copy
import decimal
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
from zoneinfo import ZoneInfo
from datetime import datetime

MAX_OUTPUT = 1024 * 1024
ZERO_HASH = "0" * 64
STAGES = {"DISCOVERY", "FEASIBILITY", "PLANNED", "BUILDING", "REVIEW", "FINAL_GATE", "COMPLETE", "STOPPED"}
REQUIRED_FIELDS = {"formatVersion", "missionId", "missionVersion", "domain", "title", "goal", "passCondition", "feasibilityChecks", "permissions", "budget", "allowedEvidence", "stopConditions"}
CHECKS = ("data", "access", "cost", "permission")
STOP_CONDITIONS = {"budget_exhausted", "attempt_limit_reached", "permission_or_access_blocked", "owner_only_decision", "mission_invalidated"}
EVENTS = {
    "mission_initialized", "checkers_frozen", "attempt_started", "candidate_selected", "attempt_rejected",
    "evidence_recorded", "feasibility_recorded", "plan_recorded", "builder_declared",
    "action_authorized", "action_completed", "permission_breach", "budget_breach", "build_passed",
    "build_failed", "review_prepared", "review_capability_used", "review_received", "review_invalid",
    "review_rejected", "final_repair_started", "final_gate_started", "final_gate_blocked",
    "goal_check_failed", "final_gate_passed", "mission_stopped",
}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ACTION_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
MISSION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
STATE_FIELDS = {
    "formatVersion", "missionId", "missionVersion", "missionHash", "checkerManifestHash",
    "controller", "stage", "attempt", "repairCycle", "candidate", "rejections",
    "feasibility", "planEvidenceId", "builder", "budget", "requiredKinds", "evidence",
    "authorizations", "review", "reviewCapability", "finalGate", "ledgerHeadHash", "updatedAt",
}
VOLATILE_STATE_FIELDS = {"stage", "updatedAt", "ledgerHeadHash"}


class Refusal(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    return sha_bytes(path.read_bytes())


def now():
    return datetime.now(ZoneInfo("America/Los_Angeles")).isoformat()


def money(value):
    try:
        parsed = decimal.Decimal(value)
    except decimal.InvalidOperation as exc:
        raise Refusal("invalid decimal cost") from exc
    if parsed < 0 or parsed.as_tuple().exponent < -2 or not parsed.is_finite():
        raise Refusal("cost must be non-negative with at most two decimals")
    return parsed


def money_text(value):
    return f"{value:.2f}"


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(f"invalid JSON file: {path}") from exc


def root_path(value):
    root = Path(value).resolve()
    if not root.is_dir():
        raise Refusal("repository root is not a directory")
    return root


def inside(root, path):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def identity(value, label):
    if not isinstance(value, str) or not value.strip():
        raise Refusal(f"{label} must be non-empty")
    return value.strip()


def safe_repo_path(root, raw, *, must_file=False):
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise Refusal("path must be non-empty and repository-relative")
    joined = root / raw
    relative = joined.relative_to(root)
    cursor = root
    if any((cursor := cursor / part).is_symlink() for part in relative.parts):
        raise Refusal("symlinks are not allowed")
    resolved = joined.resolve()
    if not inside(root, resolved):
        raise Refusal("path escapes repository")
    if must_file and not resolved.is_file():
        raise Refusal(f"file does not exist: {raw}")
    return resolved


def validate_command(root, value, *, feasibility=False):
    allowed = {"command", "checkerFiles", "timeoutSeconds"} if feasibility else {"command", "checkerFiles", "workingDirectory", "expectedExitCode", "timeoutSeconds"}
    if not isinstance(value, dict) or set(value) != allowed:
        raise Refusal("invalid checker command fields")
    cmd = value["command"]
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
        raise Refusal("command must be a non-empty argument list")
    files = value["checkerFiles"]
    if not isinstance(files, list) or not files or len(files) != len(set(files)):
        raise Refusal("checkerFiles must be a non-empty unique list")
    for file in files:
        safe_repo_path(root, file, must_file=True)
    if not any(file in cmd for file in files):
        raise Refusal("command must name a checker file")
    timeout = value["timeoutSeconds"]
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 300:
        raise Refusal("timeoutSeconds must be 1 through 300")
    if feasibility:
        if cmd.count("{evidence}") != 1:
            raise Refusal("feasibility command needs exactly one {evidence} argument")
    else:
        if value["expectedExitCode"] != 0:
            raise Refusal("version 1 expectedExitCode must be zero")
        working_directory = safe_repo_path(root, value["workingDirectory"])
        for arg in cmd[1:]:
            if arg in files or re.fullmatch(r"\{evidence:[a-z0-9][a-z0-9-]*\}", arg):
                continue
            if (working_directory / arg).exists() or (working_directory / arg).is_symlink():
                raise Refusal("final file arguments must be evidence placeholders")
            if not arg.startswith("-") and any(path.is_file() or path.is_symlink() for path in root.rglob(arg)):
                raise Refusal("final file arguments must be evidence placeholders")
            file_like = "/" in arg or "\\" in arg or bool(re.search(r"(?:^\.[A-Za-z0-9_-]+|\.[A-Za-z][A-Za-z0-9_-]{0,15})$", arg))
            if file_like:
                raise Refusal("final non-checker file arguments must be evidence placeholders")


def validate_mission(path, root):
    raw = path.read_bytes()
    try:
        mission = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Refusal("mission is not valid JSON") from exc
    if not isinstance(mission, dict) or set(mission) != REQUIRED_FIELDS:
        raise Refusal("mission fields do not exactly match version 1")
    if mission["formatVersion"] != 1 or not isinstance(mission["missionVersion"], int) or isinstance(mission["missionVersion"], bool) or mission["missionVersion"] < 1:
        raise Refusal("invalid mission version")
    if not isinstance(mission["missionId"], str) or not MISSION_ID.fullmatch(mission["missionId"]):
        raise Refusal("invalid mission ID")
    for key in ("domain", "title", "goal"):
        if not isinstance(mission[key], str) or not mission[key].strip():
            raise Refusal(f"{key} must be non-empty")
    validate_command(root, mission["passCondition"])
    if set(mission["feasibilityChecks"]) != set(CHECKS):
        raise Refusal("feasibilityChecks must contain data, access, cost, and permission")
    for check in CHECKS:
        validate_command(root, mission["feasibilityChecks"][check], feasibility=True)
    permissions = mission["permissions"]
    if not isinstance(permissions, dict) or set(permissions) != {"allowedActions", "forbiddenActions"}:
        raise Refusal("invalid permissions")
    allowed, forbidden = permissions["allowedActions"], permissions["forbiddenActions"]
    for values in (allowed, forbidden):
        if not isinstance(values, list) or len(values) != len(set(values)) or not all(isinstance(x, str) and ACTION_SLUG.fullmatch(x) for x in values):
            raise Refusal("permission actions must be unique lower-case slugs")
    if set(allowed) & set(forbidden):
        raise Refusal("allowed and forbidden actions overlap")
    budget = mission["budget"]
    if not isinstance(budget, dict) or set(budget) != {"maxCostUsd", "maxAttempts"}:
        raise Refusal("invalid budget")
    money(budget["maxCostUsd"])
    if not isinstance(budget["maxAttempts"], int) or isinstance(budget["maxAttempts"], bool) or budget["maxAttempts"] < 1:
        raise Refusal("maxAttempts must be at least one")
    evidence = mission["allowedEvidence"]
    if not isinstance(evidence, dict) or set(evidence) != {"roots", "requiredKinds"}:
        raise Refusal("invalid allowedEvidence")
    for key in ("roots", "requiredKinds"):
        if not isinstance(evidence[key], list) or not evidence[key] or len(evidence[key]) != len(set(evidence[key])):
            raise Refusal(f"{key} must be a non-empty unique list")
    for evidence_root in evidence["roots"]:
        safe_repo_path(root, evidence_root)
    if not all(isinstance(x, str) and ACTION_SLUG.fullmatch(x) for x in evidence["requiredKinds"]):
        raise Refusal("evidence kinds must be lower-case slugs")
    stops = mission["stopConditions"]
    if not isinstance(stops, list) or not stops or len(stops) != len(set(stops)) or not set(stops) <= STOP_CONDITIONS:
        raise Refusal("invalid stop conditions")
    return mission, raw


def run_dir(root, mission_id):
    if not MISSION_ID.fullmatch(mission_id):
        raise Refusal("invalid mission ID")
    return safe_repo_path(root, str(Path(".omx/outcome-loop") / mission_id))


def internal_path(run, relative, *, must_file=False):
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts:
        raise Refusal("internal run path must be relative")
    root = run.parents[2]
    target = run / relative
    try:
        target.relative_to(run)
        root_relative = target.relative_to(root)
    except ValueError as exc:
        raise Refusal("internal run path escapes mission run") from exc
    resolved = target.resolve(strict=False)
    if not inside(run, resolved):
        raise Refusal("internal run path escapes mission run")
    return safe_repo_path(root, str(root_relative), must_file=must_file)


@contextlib.contextmanager
def locked(run):
    run.mkdir(parents=True, exist_ok=True)
    lock = internal_path(run, ".lock")
    with lock.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def frozen_valid(root, run):
    mission_path = internal_path(run, "mission.json", must_file=True)
    mission_hash_path = internal_path(run, "mission.sha256", must_file=True)
    manifest_path = internal_path(run, "checker-manifest.json", must_file=True)
    raw = mission_path.read_bytes()
    expected = mission_hash_path.read_text().strip()
    if sha_bytes(raw) != expected:
        raise Refusal("frozen mission hash changed")
    mission, _ = validate_mission(mission_path, root)
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or set(manifest) != {"formatVersion", "files", "manifestHash"} or manifest.get("formatVersion") != 1 or not isinstance(manifest.get("files"), list):
        raise Refusal("checker manifest is corrupt")
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {"group", "source", "frozen", "sha256"}:
            raise Refusal("checker manifest entry is corrupt")
        source = safe_repo_path(root, entry["source"], must_file=True)
        frozen = internal_path(run, entry["frozen"], must_file=True)
        if sha_file(source) != entry["sha256"] or sha_file(frozen) != entry["sha256"]:
            raise Refusal("frozen or source checker hash changed")
    manifest_body = {k: v for k, v in manifest.items() if k != "manifestHash"}
    if sha_bytes(canonical(manifest_body)) != manifest["manifestHash"]:
        raise Refusal("checker manifest hash changed")
    return mission, expected, manifest


def state_changes(before, after):
    return {key for key in STATE_FIELDS - VOLATILE_STATE_FIELDS if before.get(key) != after.get(key)}


def require_changes(before, after, allowed):
    unexpected = state_changes(before, after) - set(allowed)
    if unexpected:
        raise Refusal("ledger state contains unearned changes")


def validate_state_shape(state):
    if not isinstance(state, dict) or set(state) != STATE_FIELDS:
        raise Refusal("ledger state fields are corrupt")
    if state.get("formatVersion") != 1 or state.get("stage") not in STAGES:
        raise Refusal("ledger state is corrupt")
    if not isinstance(state.get("attempt"), int) or isinstance(state["attempt"], bool) or state["attempt"] < 1:
        raise Refusal("ledger attempt is corrupt")
    if not isinstance(state.get("repairCycle"), int) or isinstance(state["repairCycle"], bool) or state["repairCycle"] < 0:
        raise Refusal("ledger repair count is corrupt")
    controller = state.get("controller")
    if not isinstance(controller, dict) or set(controller) != {"agentId", "threadId"}:
        raise Refusal("ledger controller identity is corrupt")
    identity(controller.get("agentId"), "controller agent ID")
    identity(controller.get("threadId"), "controller thread ID")
    if any(not isinstance(state.get(key), list) for key in ("rejections", "evidence", "authorizations", "requiredKinds")):
        raise Refusal("ledger list state is corrupt")
    if not isinstance(state.get("feasibility"), dict) or set(state["feasibility"]) != set(CHECKS):
        raise Refusal("ledger feasibility state is corrupt")
    budget = state.get("budget")
    if not isinstance(budget, dict) or set(budget) != {"maxCostUsd", "spentCostUsd", "maxAttempts"}:
        raise Refusal("ledger budget state is corrupt")
    money(budget["maxCostUsd"])
    money(budget["spentCostUsd"])
    if not isinstance(budget["maxAttempts"], int) or isinstance(budget["maxAttempts"], bool) or budget["maxAttempts"] < 1:
        raise Refusal("ledger attempt budget is corrupt")


def validate_initial_state(state, event):
    validate_state_shape(state)
    payload = event["payload"]
    expected_defaults = {
        "stage": "DISCOVERY", "attempt": 1, "repairCycle": 0, "candidate": None,
        "rejections": [], "planEvidenceId": None, "builder": None, "evidence": [],
        "authorizations": [], "review": None, "reviewCapability": None, "finalGate": None,
    }
    if any(state.get(key) != value for key, value in expected_defaults.items()):
        raise Refusal("mission initialization contains unearned state")
    if any(value is not None for value in state["feasibility"].values()):
        raise Refusal("mission initialization contains unearned feasibility")
    if payload.get("missionHash") != state["missionHash"] or payload.get("controller") != state["controller"]:
        raise Refusal("mission initialization payload is corrupt")


def evidence_entry_ok(entry, attempt):
    required = {"id", "kind", "source", "copied", "sha256", "bytes", "attempt"}
    return (
        isinstance(entry, dict) and set(entry) == required and SLUG.fullmatch(entry.get("id", ""))
        and ACTION_SLUG.fullmatch(entry.get("kind", "")) and isinstance(entry.get("source"), str)
        and bool(entry["source"]) and isinstance(entry.get("copied"), str) and bool(entry["copied"])
        and re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")) is not None
        and isinstance(entry.get("bytes"), int) and not isinstance(entry["bytes"], bool) and entry["bytes"] >= 0
        and entry.get("attempt") == attempt
    )


def validate_reset(before, after, reason):
    if after["rejections"] != before["rejections"] + [{
        "attempt": before["attempt"], "candidate": before["candidate"],
        "fingerprint": before["candidate"]["fingerprint"] if before["candidate"] else None,
        "reason": reason,
    }]:
        raise Refusal("ledger rejection state is corrupt")
    if before["attempt"] >= before["budget"]["maxAttempts"]:
        if after["attempt"] != before["attempt"] or after["stage"] != "STOPPED":
            raise Refusal("ledger attempt limit is corrupt")
        return
    if after["attempt"] != before["attempt"] + 1 or after["stage"] != "DISCOVERY":
        raise Refusal("ledger attempt advance is corrupt")
    expected = {
        "repairCycle": 0, "candidate": None, "feasibility": {key: None for key in CHECKS},
        "planEvidenceId": None, "builder": None, "review": None, "reviewCapability": None,
        "finalGate": None,
    }
    if any(after.get(key) != value for key, value in expected.items()):
        raise Refusal("ledger new-attempt state is corrupt")


def validate_event_transition(before, after, event, history, mission, run):
    validate_state_shape(after)
    name, payload = event["event"], event["payload"]
    if event["attempt"] != after["attempt"] or event["missionId"] != after["missionId"]:
        raise Refusal("ledger event identity is corrupt")
    immutable = {"formatVersion", "missionId", "missionVersion", "missionHash", "checkerManifestHash", "controller", "requiredKinds"}
    if any(before[key] != after[key] for key in immutable):
        raise Refusal("immutable ledger state changed")
    if before["budget"]["maxCostUsd"] != after["budget"]["maxCostUsd"] or before["budget"]["maxAttempts"] != after["budget"]["maxAttempts"]:
        raise Refusal("frozen ledger budget changed")

    fixed = {
        "checkers_frozen": {("DISCOVERY", "DISCOVERY")},
        "attempt_started": {("DISCOVERY", "DISCOVERY")},
        "candidate_selected": {("DISCOVERY", "FEASIBILITY")},
        "plan_recorded": {("PLANNED", "PLANNED")},
        "builder_declared": {("PLANNED", "BUILDING")},
        "build_passed": {("BUILDING", "REVIEW")},
        "build_failed": {("BUILDING", "BUILDING")},
        "review_prepared": {("REVIEW", "REVIEW")},
        "review_capability_used": {("REVIEW", "REVIEW")},
        "review_received": {("REVIEW", "FINAL_GATE")},
        "final_repair_started": {("FINAL_GATE", "BUILDING")},
        "final_gate_started": {("FINAL_GATE", "FINAL_GATE")},
        "final_gate_passed": {("FINAL_GATE", "COMPLETE")},
    }
    pair = (event["fromStage"], event["toStage"])
    if name in {"evidence_recorded", "action_authorized", "action_completed"} and (pair[0] != pair[1] or pair[0] in {"COMPLETE", "STOPPED"}):
        raise Refusal("illegal ledger stage change")
    if name in fixed and pair not in fixed[name]:
        raise Refusal("illegal ledger stage change")
    if name == "feasibility_recorded" and pair not in {("FEASIBILITY", "FEASIBILITY"), ("FEASIBILITY", "PLANNED")}:
        raise Refusal("illegal ledger stage change")
    if name in {"permission_breach", "budget_breach", "mission_stopped"} and (pair[0] in {"COMPLETE", "STOPPED"} or pair[1] != "STOPPED"):
        raise Refusal("illegal ledger stage change")
    if name in {"attempt_rejected", "goal_check_failed"} and pair[1] not in {"DISCOVERY", "STOPPED"}:
        raise Refusal("illegal ledger stage change")
    if name == "review_rejected" and pair not in {("REVIEW", "BUILDING"), ("REVIEW", "DISCOVERY"), ("REVIEW", "STOPPED")}:
        raise Refusal("illegal ledger stage change")
    if name in {"review_invalid", "final_gate_blocked", "mission_initialized"}:
        raise Refusal("illegal ledger event sequence")
    if name == "checkers_frozen" and event["sequence"] != 2:
        raise Refusal("checker freeze event is out of order")
    if name == "attempt_started" and event["sequence"] != 3:
        raise Refusal("attempt start event is out of order")

    payload_fields = set(payload) - {"stateAfter"}
    allowed_payloads = {
        "checkers_frozen": [{"checkerManifestHash"}], "attempt_started": [set()],
        "candidate_selected": [{"fingerprint"}], "evidence_recorded": [{"evidence"}],
        "feasibility_recorded": [{"check", "run"}],
        "attempt_rejected": [{"check", "run"}, {"reason", "evidenceId"}],
        "plan_recorded": [{"evidenceId"}], "builder_declared": [{"builder"}],
        "action_authorized": [{"authorization"}], "action_completed": [{"authorizationId"}, {"authorizationId", "goalRun"}],
        "permission_breach": [{"action"}], "budget_breach": [{"action"}, {"authorizationId"}],
        "build_passed": [{"evidenceIds"}], "build_failed": [{"evidenceIds"}],
        "review_prepared": [{"inputSha256", "capabilitySha256"}],
        "review_capability_used": [{"inputSha256", "submitter"}],
        "review_received": [{"outputSha256"}], "review_rejected": [{"disposition"}],
        "final_repair_started": [{"reason", "evidenceId"}], "final_gate_started": [{"authorizationId"}],
        "goal_check_failed": [{"run"}], "final_gate_passed": [{"run"}],
        "mission_stopped": [{"condition", "evidenceId"}],
    }
    if payload_fields not in allowed_payloads.get(name, []):
        raise Refusal("ledger event payload is corrupt")

    allowed_changes = {
        "checkers_frozen": set(), "attempt_started": set(), "candidate_selected": {"candidate"},
        "evidence_recorded": {"evidence"}, "feasibility_recorded": {"feasibility"},
        "plan_recorded": {"planEvidenceId"}, "builder_declared": {"builder", "authorizations"},
        "action_authorized": {"authorizations"}, "action_completed": {"authorizations", "budget"},
        "permission_breach": set(), "budget_breach": set(), "build_passed": set(),
        "build_failed": {"repairCycle"}, "review_prepared": {"review", "reviewCapability"},
        "review_capability_used": {"reviewCapability"}, "review_received": {"review"},
        "final_repair_started": {"repairCycle", "review", "reviewCapability", "finalGate"},
        "final_gate_started": {"authorizations"}, "final_gate_passed": {"finalGate"},
        "mission_stopped": set(),
    }
    reset_changes = {"attempt", "repairCycle", "candidate", "rejections", "feasibility", "planEvidenceId", "builder", "review", "reviewCapability", "finalGate"}
    if name in {"attempt_rejected", "goal_check_failed"} or (name == "review_rejected" and payload.get("disposition") == "new_candidate"):
        require_changes(before, after, reset_changes)
        if name == "attempt_rejected" and "check" in payload:
            reason = f"feasibility {payload['check']} failed"
        elif name == "goal_check_failed":
            reason = "deterministic goal check failed"
        elif name == "review_rejected":
            reason = "independent review rejected candidate"
        else:
            reason = payload.get("reason")
        if not isinstance(reason, str) or not reason:
            raise Refusal("ledger rejection reason is corrupt")
        validate_reset(before, after, reason)
        return
    if name == "review_rejected":
        require_changes(before, after, {"repairCycle", "review", "reviewCapability"})
        if payload.get("disposition") != "repair" or after["repairCycle"] != before["repairCycle"] + 1 or after["review"] is not None or after["reviewCapability"] is not None:
            raise Refusal("ledger review repair is corrupt")
        return
    require_changes(before, after, allowed_changes.get(name, set()))

    if name == "checkers_frozen" and payload.get("checkerManifestHash") != after["checkerManifestHash"]:
        raise Refusal("checker freeze event is corrupt")
    elif name == "attempt_started" and (after["stage"] != "DISCOVERY" or after["attempt"] != 1):
        raise Refusal("attempt start event is corrupt")
    elif name == "candidate_selected":
        if before["candidate"] is not None or not isinstance(after["candidate"], dict) or after["candidate"].get("fingerprint") != payload.get("fingerprint"):
            raise Refusal("candidate event is corrupt")
        candidate_copy = copy.deepcopy(after["candidate"])
        claimed_fp = candidate_copy.pop("fingerprint", None)
        candidate_copy.pop("normalizedMethod", None)
        calculated_fp, normalized = fingerprint(candidate_copy)
        if calculated_fp != claimed_fp or after["candidate"].get("normalizedMethod") != normalized:
            raise Refusal("candidate fingerprint is corrupt")
    elif name == "evidence_recorded":
        entry = payload.get("evidence")
        if not evidence_entry_ok(entry, after["attempt"]) or after["evidence"] != before["evidence"] + [entry]:
            raise Refusal("evidence event is corrupt")
    elif name == "feasibility_recorded":
        check = payload.get("check")
        result = after["feasibility"].get(check) if check in CHECKS else None
        evidence = next((item for item in before["evidence"] if item["attempt"] == before["attempt"] and item["id"] == (result or {}).get("evidenceId")), None)
        if not result or result.get("status") != "PASS" or not evidence or evidence["kind"] != f"feasibility_{check}" or result.get("sha256") != evidence["sha256"] or not result.get("facts"):
            raise Refusal("feasibility event is corrupt")
        expected_feasibility = copy.deepcopy(before["feasibility"]); expected_feasibility[check] = result
        if after["feasibility"] != expected_feasibility or (after["stage"] == "PLANNED") != all(after["feasibility"].values()):
            raise Refusal("feasibility stage is unearned")
    elif name == "plan_recorded":
        evidence = next((item for item in before["evidence"] if item["attempt"] == before["attempt"] and item["id"] == payload.get("evidenceId") and item["kind"] == "plan"), None)
        if not evidence or after["planEvidenceId"] != payload["evidenceId"]:
            raise Refusal("plan event is corrupt")
    elif name == "action_authorized":
        authorization = payload.get("authorization")
        if not isinstance(authorization, dict) or set(authorization) != {"id", "action", "estimatedCostUsd", "status", "attempt"} or after["authorizations"] != before["authorizations"] + [authorization] or authorization.get("attempt") != after["attempt"] or authorization.get("status") != "open":
            raise Refusal("authorization event is corrupt")
        identity(authorization.get("id"), "authorization ID")
        action = identity(authorization.get("action"), "authorization action")
        estimate = money(authorization.get("estimatedCostUsd"))
        allowed = mission["permissions"]["allowedActions"]
        forbidden = mission["permissions"]["forbiddenActions"]
        if action not in allowed or action in forbidden:
            raise Refusal("authorization violates frozen permissions")
        if money(before["budget"]["spentCostUsd"]) + estimate > money(before["budget"]["maxCostUsd"]):
            raise Refusal("authorization exceeds frozen budget")
        if any(item.get("id") == authorization["id"] for item in before["authorizations"]):
            raise Refusal("authorization ID was reused")
        if any(item.get("status") in {"open", "running"} for item in before["authorizations"]):
            raise Refusal("another authorization is unfinished")
        expected_stage = "FINAL_GATE" if action == "run_goal_check" else "PLANNED"
        if before["stage"] != expected_stage:
            raise Refusal("authorization was created in an illegal stage")
    elif name == "builder_declared":
        builder = payload.get("builder")
        if after["builder"] != builder or not isinstance(builder, dict) or set(builder) != {"agentId", "threadId", "authorizationId"}:
            raise Refusal("builder event is corrupt")
        identity(builder.get("agentId"), "builder agent ID"); identity(builder.get("threadId"), "builder thread ID")
        authorization = next((item for item in after["authorizations"] if item["id"] == builder["authorizationId"]), None)
        if not authorization or authorization.get("action") != "modify_repository" or authorization.get("status") != "open" or authorization.get("usedByBuild") is not True:
            raise Refusal("builder authorization is corrupt")
        if builder["agentId"] == after["controller"]["agentId"] or builder["threadId"] == after["controller"]["threadId"]:
            raise Refusal("controller cannot be builder")
        expected_authorizations = copy.deepcopy(before["authorizations"])
        prior_authorization = next((item for item in expected_authorizations if item["id"] == builder["authorizationId"]), None)
        if not prior_authorization:
            raise Refusal("builder authorization is missing")
        prior_authorization["usedByBuild"] = True
        if after["authorizations"] != expected_authorizations:
            raise Refusal("builder event changed unrelated authorizations")
    elif name == "action_completed":
        auth_id = payload.get("authorizationId")
        old = next((item for item in before["authorizations"] if item["id"] == auth_id), None)
        new = next((item for item in after["authorizations"] if item["id"] == auth_id), None)
        if not old or not new or old.get("status") not in {"open", "running"} or new.get("status") != "completed" or "actualCostUsd" not in new:
            raise Refusal("action completion is corrupt")
        expected_authorizations = copy.deepcopy(before["authorizations"]); expected_authorizations[before["authorizations"].index(old)] = new
        if after["authorizations"] != expected_authorizations:
            raise Refusal("unearned authorization state")
        actual = money(new["actualCostUsd"])
        expected_spend = money(before["budget"]["spentCostUsd"]) + (actual if old["status"] == "open" else decimal.Decimal("0"))
        if expected_spend > money(before["budget"]["maxCostUsd"]) or money(after["budget"]["spentCostUsd"]) != expected_spend:
            raise Refusal("ledger spend is corrupt")
        if "goalRun" in payload:
            if before["stage"] != "FINAL_GATE" or old["status"] != "running" or new.get("action") != "run_goal_check" or new.get("actualCostUsd") != "0.00" or not isinstance(payload["goalRun"], dict):
                raise Refusal("goal-check completion is corrupt")
        elif old["status"] == "running":
            raise Refusal("goal-check completion facts are missing")
        elif new.get("action") == "modify_repository":
            if before["stage"] != "BUILDING" or old.get("usedByBuild") is not True:
                raise Refusal("repository action completion is out of order")
        elif before["stage"] != "PLANNED" or new.get("action") == "run_goal_check":
            raise Refusal("action completion is out of order")
    elif name == "build_passed":
        ids = payload.get("evidenceIds")
        boundary = max((item["sequence"] for item in history if item["attempt"] == after["attempt"] and (item["event"] in {"builder_declared", "build_failed", "final_repair_started"} or (item["event"] == "review_rejected" and item["payload"].get("disposition") == "repair"))), default=0)
        fresh_ids = {item["payload"]["evidence"]["id"] for item in history if item["event"] == "evidence_recorded" and item["attempt"] == after["attempt"] and item["sequence"] > boundary}
        kinds = {item["kind"] for item in after["evidence"] if item["attempt"] == after["attempt"] and item["id"] in set(ids or []) & fresh_ids}
        if not isinstance(ids, list) or not {"implementation", "test"} <= kinds:
            raise Refusal("build pass is unearned")
    elif name == "build_failed":
        if after["repairCycle"] != before["repairCycle"] + 1:
            raise Refusal("build repair count is corrupt")
    elif name == "review_prepared":
        review, capability = after["review"], after["reviewCapability"]
        if not isinstance(review, dict) or not isinstance(capability, dict) or capability != {"hash": payload.get("capabilitySha256"), "inputSha256": payload.get("inputSha256"), "used": False} or review.get("inputSha256") != payload.get("inputSha256") or review.get("output") is not None:
            raise Refusal("review preparation is corrupt")
    elif name == "review_capability_used":
        expected = copy.deepcopy(before["reviewCapability"])
        if not expected or expected.get("used") is not False:
            raise Refusal("review capability use is corrupt")
        expected["used"] = True
        if after["reviewCapability"] != expected or payload.get("inputSha256") != expected["inputSha256"] or payload.get("submitter") != after["controller"]:
            raise Refusal("review capability use is corrupt")
    elif name == "review_received":
        review = after["review"]
        if not isinstance(review, dict) or review.get("outputSha256") != payload.get("outputSha256") or review.get("submitter") != after["controller"] or not after["reviewCapability"] or after["reviewCapability"].get("used") is not True:
            raise Refusal("review receipt is corrupt")
        reviewer = review.get("reviewer", {})
        identity(reviewer.get("agentId"), "reviewer agent ID"); identity(reviewer.get("threadId"), "reviewer thread ID")
        identities = [(after["controller"]["agentId"], after["controller"]["threadId"]), (after["builder"]["agentId"], after["builder"]["threadId"]), (reviewer["agentId"], reviewer["threadId"])]
        if len({item[0] for item in identities}) != 3 or len({item[1] for item in identities}) != 3:
            raise Refusal("ledger role identities are not distinct")
        expected_review = copy.deepcopy(before["review"])
        expected_review.update({"output": review.get("output"), "outputSha256": review.get("outputSha256"), "reviewer": reviewer, "submitter": after["controller"]})
        if review != expected_review:
            raise Refusal("review receipt contains unearned state")
        _, output_path = validate_review_files(run, after, require_output=True)
        validate_review_contract(read_json(output_path), after, review["inputSha256"])
    elif name == "final_repair_started":
        if after["repairCycle"] != before["repairCycle"] + 1 or after["review"] is not None or after["reviewCapability"] is not None or after["finalGate"] is not None:
            raise Refusal("final repair event is corrupt")
    elif name == "final_gate_started":
        auth_id = payload.get("authorizationId")
        old = next((item for item in before["authorizations"] if item["id"] == auth_id), None)
        new = next((item for item in after["authorizations"] if item["id"] == auth_id), None)
        if not old or not new or old.get("action") != "run_goal_check" or old.get("status") != "open" or new.get("status") != "running" or new.get("estimatedCostUsd") != "0.00":
            raise Refusal("final gate authorization is corrupt")
        expected_authorizations = copy.deepcopy(before["authorizations"]); expected_authorizations[before["authorizations"].index(old)] = new
        if after["authorizations"] != expected_authorizations:
            raise Refusal("final gate changed unrelated authorizations")
    elif name == "final_gate_passed":
        prior = history[-1] if history else None
        prior_payload = prior.get("payload", {}) if prior else {}
        run = payload.get("run")
        authorization_id = prior_payload.get("authorizationId")
        authorization = next((item for item in after["authorizations"] if item.get("id") == authorization_id), None)
        if (
            not prior or prior.get("event") != "action_completed"
            or prior_payload.get("goalRun") != run
            or not isinstance(run, dict) or run.get("exitCode") != 0 or run.get("timedOut") is not False
            or not authorization or authorization.get("attempt") != after["attempt"]
            or authorization.get("action") != "run_goal_check" or authorization.get("status") != "completed"
            or authorization.get("actualCostUsd") != "0.00"
            or after["finalGate"] != run or not after["review"] or not after["review"].get("output")
        ):
            raise Refusal("final completion is unearned")


def replay(run, mission=None):
    root = run.parents[2]
    if mission is None:
        mission, _ = validate_mission(internal_path(run, "mission.json", must_file=True), root)
    ledger = internal_path(run, "ledger.jsonl", must_file=True)
    previous, state, expected_sequence = ZERO_HASH, None, 1
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise Refusal("ledger is missing") from exc
    history = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Refusal("ledger is corrupt") from exc
        event_hash = event.pop("eventHash", None)
        if event.get("sequence") != expected_sequence or event.get("previousHash") != previous or event.get("event") not in EVENTS or sha_bytes(canonical(event)) != event_hash:
            raise Refusal("ledger hash chain is corrupt")
        if state is not None:
            if event["missionId"] != state["missionId"] or event["attempt"] < state["attempt"] or event["fromStage"] != state["stage"]:
                raise Refusal("illegal ledger transition")
        name, before_stage, after_stage = event["event"], event["fromStage"], event["toStage"]
        if after_stage == "COMPLETE" and name != "final_gate_passed":
            raise Refusal("only final_gate_passed can complete a mission")
        if before_stage in {"COMPLETE", "STOPPED"}:
            raise Refusal("terminal ledger state changed")
        next_state = event.get("payload", {}).get("stateAfter")
        if not isinstance(next_state, dict) or next_state.get("stage") != event["toStage"]:
            raise Refusal("ledger state is corrupt")
        if state is None:
            if expected_sequence != 1 or name != "mission_initialized" or before_stage != "DISCOVERY" or after_stage != "DISCOVERY":
                raise Refusal("ledger does not start with mission initialization")
            validate_initial_state(next_state, event)
        else:
            validate_event_transition(state, next_state, event, history, mission, run)
        state = next_state
        history.append({**event, "eventHash": event_hash})
        previous, expected_sequence = event_hash, expected_sequence + 1
    if state is None:
        raise Refusal("ledger is empty")
    state = copy.deepcopy(state)
    state["ledgerHeadHash"] = previous
    return state, len(lines), previous


def write_state(run, state):
    atomic_json(internal_path(run, "state.json"), state)


def append_event(run, state, name, to_stage=None, extra=None):
    current, count, head = replay(run)
    if current["ledgerHeadHash"] != state["ledgerHeadHash"]:
        raise Refusal("state is stale")
    next_state = copy.deepcopy(state)
    next_state["stage"] = to_stage or state["stage"]
    next_state["updatedAt"] = now()
    payload = dict(extra or {})
    snapshot = copy.deepcopy(next_state)
    snapshot["ledgerHeadHash"] = ""
    payload["stateAfter"] = snapshot
    event = {"formatVersion": 1, "sequence": count + 1, "at": now(), "event": name, "missionId": state["missionId"], "attempt": next_state["attempt"], "fromStage": state["stage"], "toStage": next_state["stage"], "previousHash": head, "payload": payload}
    event["eventHash"] = sha_bytes(canonical(event))
    with internal_path(run, "ledger.jsonl", must_file=True).open("a", encoding="utf-8") as handle:
        handle.write(canonical(event).decode() + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    next_state["ledgerHeadHash"] = event["eventHash"]
    write_state(run, next_state)
    return next_state


def initial_append(run, state, name, to_stage, extra=None):
    ledger = internal_path(run, "ledger.jsonl")
    count = len(ledger.read_text().splitlines()) if ledger.exists() else 0
    head = ZERO_HASH
    if count:
        prior, _, head = replay(run)
        from_stage = prior["stage"]
    else:
        from_stage = to_stage
    next_state = copy.deepcopy(state)
    next_state["stage"] = to_stage
    next_state["updatedAt"] = now()
    snapshot = copy.deepcopy(next_state)
    snapshot["ledgerHeadHash"] = ""
    payload = dict(extra or {})
    payload["stateAfter"] = snapshot
    event = {"formatVersion": 1, "sequence": count + 1, "at": now(), "event": name, "missionId": state["missionId"], "attempt": state["attempt"], "fromStage": from_stage, "toStage": to_stage, "previousHash": head, "payload": payload}
    event["eventHash"] = sha_bytes(canonical(event))
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(canonical(event).decode() + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    next_state["ledgerHeadHash"] = event["eventHash"]
    write_state(run, next_state)
    return next_state


def load(root, mission_id):
    run = run_dir(root, mission_id)
    mission, mission_hash, manifest = frozen_valid(root, run)
    state, _, _ = replay(run, mission)
    if state["missionHash"] != mission_hash or state["checkerManifestHash"] != manifest["manifestHash"]:
        raise Refusal("saved hashes do not match")
    if state["missionVersion"] != mission["missionVersion"] or state["requiredKinds"] != mission["allowedEvidence"]["requiredKinds"]:
        raise Refusal("saved mission fields do not match")
    if state["budget"]["maxCostUsd"] != money_text(money(mission["budget"]["maxCostUsd"])) or state["budget"]["maxAttempts"] != mission["budget"]["maxAttempts"] or state["attempt"] > state["budget"]["maxAttempts"]:
        raise Refusal("saved budget does not match")
    if any(not evidence_entry_ok(entry, entry.get("attempt")) or entry["attempt"] > state["attempt"] for entry in state["evidence"]):
        raise Refusal("saved evidence state is corrupt")
    validate_authorizations(state, mission)
    evidence_ok(root, state, mission=mission, all_attempts=True)
    saved = internal_path(run, "state.json")
    try:
        saved_state = read_json(saved) if saved.exists() else None
    except Refusal:
        saved_state = None
    if saved_state != state:
        write_state(run, state)
    if state.get("review") is not None:
        validate_review_files(run, state)
    if state["stage"] == "COMPLETE":
        evidence_ok(root, state, mission=mission, required=True, all_attempts=True)
        review = state.get("review") or {}
        input_path, output_path = validate_review_files(run, state, require_output=True)
        if sha_file(input_path) != review.get("inputSha256") or sha_file(output_path) != review.get("outputSha256"):
            raise Refusal("completed review files changed")
        review_output = validate_review_contract(read_json(output_path), state, review["inputSha256"])
        if review_output["decision"] != "APPROVE":
            raise Refusal("completed review is invalid")
        final_path = internal_path(run, "final-result.json", must_file=True)
        if read_json(final_path) != completed_result(run, state):
            raise Refusal("completed result changed")
        for stream in ("stdout", "stderr"):
            stream_path = internal_path(run, Path("evidence") / f"attempt-{state['attempt']:04d}" / f"goal-{stream}.bin", must_file=True)
            if sha_file(stream_path) != state["finalGate"].get(f"{stream}Sha256") or stream_path.stat().st_size != state["finalGate"].get(f"{stream}Bytes"):
                raise Refusal("completed goal output changed")
    return run, mission, manifest, state


def validate_authorizations(state, mission):
    authorizations = state["authorizations"]
    ids = [item.get("id") for item in authorizations if isinstance(item, dict)]
    if len(ids) != len(authorizations) or len(ids) != len(set(ids)):
        raise Refusal("saved authorizations are corrupt")
    allowed = mission["permissions"]["allowedActions"]
    forbidden = mission["permissions"]["forbiddenActions"]
    active = 0
    spent = decimal.Decimal("0")
    for item in authorizations:
        required = {"id", "action", "estimatedCostUsd", "status", "attempt"}
        optional = set(item) - required
        if not required <= set(item) or not optional <= {"actualCostUsd", "usedByBuild"}:
            raise Refusal("saved authorization fields are corrupt")
        identity(item["id"], "authorization ID")
        if item["action"] not in allowed or item["action"] in forbidden or item["status"] not in {"open", "running", "completed"}:
            raise Refusal("saved authorization violates frozen mission")
        money(item["estimatedCostUsd"])
        if not isinstance(item["attempt"], int) or isinstance(item["attempt"], bool) or not 1 <= item["attempt"] <= state["attempt"]:
            raise Refusal("saved authorization attempt is corrupt")
        if item["status"] in {"open", "running"}:
            active += 1
            if "actualCostUsd" in item:
                raise Refusal("unfinished authorization has actual cost")
        else:
            if "actualCostUsd" not in item:
                raise Refusal("completed authorization is missing actual cost")
            spent += money(item["actualCostUsd"])
        if item["status"] == "running" and (item["action"] != "run_goal_check" or item["estimatedCostUsd"] != "0.00"):
            raise Refusal("running authorization is invalid")
        if "usedByBuild" in item and (item["usedByBuild"] is not True or item["action"] != "modify_repository"):
            raise Refusal("build authorization marker is invalid")
    if active > 1 or spent != money(state["budget"]["spentCostUsd"]) or spent > money(state["budget"]["maxCostUsd"]):
        raise Refusal("saved authorization totals are corrupt")


def fingerprint(candidate):
    if not isinstance(candidate, dict) or not {"candidateId", "name", "method", "thresholds"} <= set(candidate):
        raise Refusal("invalid candidate")
    method = candidate["method"]
    if not isinstance(method, dict) or set(method) != {"family", "inputs", "transformation", "decisionRule", "output"}:
        raise Refusal("invalid candidate method")
    normalized = {}
    for key in ("family", "transformation", "decisionRule", "output"):
        value = method[key].strip().lower() if isinstance(method[key], str) else ""
        if not SLUG.fullmatch(value):
            raise Refusal("method values must be lower-case slugs")
        normalized[key] = value
    if not isinstance(method["inputs"], list) or not method["inputs"]:
        raise Refusal("method inputs required")
    normalized["inputs"] = sorted(set(x.strip().lower() for x in method["inputs"]))
    if not all(SLUG.fullmatch(x) for x in normalized["inputs"]):
        raise Refusal("method inputs must be slugs")
    return sha_bytes(canonical(normalized)), normalized


def clean_run(command, cwd, timeout):
    env = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONNOUSERSITE": "1"}
    process = subprocess.Popen(command, cwd=cwd, env=env, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    totals = {"stdout": 0, "stderr": 0}

    def drain(name, pipe):
        while chunk := pipe.read(64 * 1024):
            totals[name] += len(chunk)
            remaining = MAX_OUTPUT - len(captured[name])
            if remaining > 0:
                captured[name].extend(chunk[:remaining])

    readers = [
        threading.Thread(target=drain, args=("stdout", process.stdout)),
        threading.Thread(target=drain, args=("stderr", process.stderr)),
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    for reader in readers:
        reader.join()
    stdout, stderr = bytes(captured["stdout"]), bytes(captured["stderr"])
    return {
        "exitCode": None if timed_out else process.returncode,
        "timedOut": timed_out,
        "stdoutSha256": sha_bytes(stdout),
        "stderrSha256": sha_bytes(stderr),
        "stdoutBytes": len(stdout),
        "stderrBytes": len(stderr),
        "stdoutTotalBytes": totals["stdout"],
        "stderrTotalBytes": totals["stderr"],
        "stdoutTruncated": totals["stdout"] > len(stdout),
        "stderrTruncated": totals["stderr"] > len(stderr),
        "stdout": stdout,
        "stderr": stderr,
    }


def frozen_command(root, run, manifest, cfg, evidence_path=None, final_evidence=None):
    mapping = {entry["source"]: str(internal_path(run, entry["frozen"], must_file=True)) for entry in manifest["files"]}
    command = []
    for arg in cfg["command"]:
        if arg in mapping:
            command.append(mapping[arg])
        elif arg == "{evidence}":
            command.append(str(evidence_path))
        elif re.fullmatch(r"\{evidence:([a-z0-9][a-z0-9-]*)\}", arg):
            evidence_id = arg[10:-1]
            if final_evidence is None or evidence_id not in final_evidence:
                raise Refusal("goal input is not reviewed evidence")
            command.append(str(final_evidence[evidence_id]))
        else:
            command.append(arg)
    cwd = root / cfg.get("workingDirectory", ".")
    if final_evidence is not None:
        checker_args = {entry["source"] for entry in manifest["files"]}
        for original in cfg["command"][1:]:
            if original not in checker_args and not re.fullmatch(r"\{evidence:[a-z0-9][a-z0-9-]*\}", original):
                if (cwd / original).exists() or (cwd / original).is_symlink():
                    raise Refusal("final file arguments must be evidence placeholders")
    return clean_run(command, cwd, cfg["timeoutSeconds"])


def evidence_ok(root, state, *, mission, required=False, all_attempts=False):
    current = [e for e in state["evidence"] if e["attempt"] == state["attempt"]]
    checked = state["evidence"] if all_attempts else current
    allowed = [safe_repo_path(root, path) for path in mission["allowedEvidence"]["roots"]]
    for entry in checked:
        source = safe_repo_path(root, entry["source"], must_file=True)
        if not any(inside(path, source) or source == path for path in allowed):
            raise Refusal("recorded evidence source is outside allowed roots")
        expected_copied = Path(".omx/outcome-loop") / state["missionId"] / "evidence" / f"attempt-{entry['attempt']:04d}" / f"{entry['id']}--{source.name}"
        if entry["copied"] != str(expected_copied):
            raise Refusal("recorded evidence destination is invalid")
        copied = safe_repo_path(root, entry["copied"], must_file=True)
        if sha_file(source) != entry["sha256"] or sha_file(copied) != entry["sha256"]:
            raise Refusal("recorded evidence changed or is missing")
    if required:
        kinds = {e["kind"] for e in current}
        missing = set(state["requiredKinds"]) - kinds
        if missing:
            raise Refusal("required evidence is missing")
    return current


def validate_review_files(run, state, *, require_output=False):
    review = state.get("review")
    if not isinstance(review, dict):
        raise Refusal("review state is corrupt")
    attempt_dir = Path("review") / f"attempt-{state['attempt']:04d}"
    input_path = internal_path(run, attempt_dir / "input.json", must_file=True)
    expected_input = str(input_path.relative_to(run.parents[2]))
    if review.get("input") != expected_input or sha_file(input_path) != review.get("inputSha256"):
        raise Refusal("review input changed")
    output_path = None
    if review.get("output") is not None:
        output_path = internal_path(run, attempt_dir / "output.json", must_file=True)
        expected_output = str(output_path.relative_to(run.parents[2]))
        if review.get("output") != expected_output or sha_file(output_path) != review.get("outputSha256"):
            raise Refusal("review output changed")
    if require_output and output_path is None:
        raise Refusal("review output is missing")
    return input_path, output_path


def completed_result(run, state):
    try:
        final_event = json.loads(internal_path(run, "ledger.jsonl", must_file=True).read_text(encoding="utf-8").splitlines()[-1])
    except (OSError, IndexError, json.JSONDecodeError) as exc:
        raise Refusal("completed ledger event is missing") from exc
    if final_event.get("event") != "final_gate_passed" or final_event.get("eventHash") != state["ledgerHeadHash"]:
        raise Refusal("completed ledger event is invalid")
    goal_run = final_event.get("payload", {}).get("run")
    if goal_run != state.get("finalGate"):
        raise Refusal("completed goal result does not match the ledger")
    return {"formatVersion": 1, "missionId": state["missionId"], "missionVersion": state["missionVersion"], "missionHash": state["missionHash"], "attempt": state["attempt"], "stage": "COMPLETE", "goalRun": goal_run, "ledgerHeadHash": state["ledgerHeadHash"], "completedAt": state["updatedAt"]}


def reset_attempt(state, reason):
    rejected = {"attempt": state["attempt"], "candidate": state["candidate"], "fingerprint": state["candidate"]["fingerprint"] if state["candidate"] else None, "reason": reason}
    state["rejections"].append(rejected)
    if state["attempt"] >= state["budget"]["maxAttempts"]:
        return "STOPPED"
    state["attempt"] += 1
    state["repairCycle"] = 0
    state["candidate"] = None
    state["feasibility"] = {x: None for x in CHECKS}
    state["planEvidenceId"] = None
    state["builder"] = None
    state["review"] = None
    state["reviewCapability"] = None
    state["finalGate"] = None
    return "DISCOVERY"


def legal_next(state):
    return {
        "DISCOVERY": ["candidate", "stop"], "FEASIBILITY": ["evidence", "feasibility", "reject-candidate", "stop"],
        "PLANNED": ["evidence", "plan", "authorize-action", "start-build", "stop"],
        "BUILDING": ["evidence", "complete-action", "build-result", "stop"],
        "REVIEW": ["prepare-review", "review-result", "stop"], "FINAL_GATE": ["authorize-action", "final-gate", "repair-final-gate", "stop"],
        "COMPLETE": ["status", "resume", "final-gate"], "STOPPED": ["status", "resume"],
    }[state["stage"]]


def cmd_init(args, root):
    controller_agent_id = identity(args.controller_agent_id, "controller agent ID")
    controller_thread_id = identity(args.controller_thread_id, "controller thread ID")
    mission_path = safe_repo_path(root, args.mission, must_file=True)
    mission, raw = validate_mission(mission_path, root)
    parent = safe_repo_path(root, ".omx/outcome-loop")
    parent.mkdir(parents=True, exist_ok=True)
    lock_path = safe_repo_path(root, ".omx/outcome-loop/.init.lock")
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        final_run = run_dir(root, mission["missionId"])
        if final_run.exists() or final_run.is_symlink():
            raise Refusal("mission run already exists")
        staging = Path(tempfile.mkdtemp(prefix=f".{mission['missionId']}.init-", dir=parent))
        try:
            run = staging
            internal_path(run, "mission.json").write_bytes(raw)
            mission_hash = sha_bytes(raw)
            internal_path(run, "mission.sha256").write_text(mission_hash + "\n")
            entries = []
            seen = set()
            groups = [("pass", mission["passCondition"])] + [(f"feasibility/{name}", mission["feasibilityChecks"][name]) for name in CHECKS]
            for group, cfg in groups:
                for source_rel in cfg["checkerFiles"]:
                    key = (group, source_rel)
                    if key in seen:
                        continue
                    seen.add(key)
                    source = root / source_rel
                    frozen_rel = f"frozen-checkers/{group}/{source_rel}"
                    frozen = internal_path(run, frozen_rel)
                    frozen.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, frozen)
                    entries.append({"group": group, "source": source_rel, "frozen": frozen_rel, "sha256": sha_file(source)})
            manifest = {"formatVersion": 1, "files": entries}
            manifest["manifestHash"] = sha_bytes(canonical(manifest))
            atomic_json(internal_path(run, "checker-manifest.json"), manifest)
            state = {"formatVersion": 1, "missionId": mission["missionId"], "missionVersion": mission["missionVersion"], "missionHash": mission_hash, "checkerManifestHash": manifest["manifestHash"], "controller": {"agentId": controller_agent_id, "threadId": controller_thread_id}, "stage": "DISCOVERY", "attempt": 1, "repairCycle": 0, "candidate": None, "rejections": [], "feasibility": {x: None for x in CHECKS}, "planEvidenceId": None, "builder": None, "budget": {"maxCostUsd": money_text(money(mission["budget"]["maxCostUsd"])), "spentCostUsd": "0.00", "maxAttempts": mission["budget"]["maxAttempts"]}, "requiredKinds": mission["allowedEvidence"]["requiredKinds"], "evidence": [], "authorizations": [], "review": None, "reviewCapability": None, "finalGate": None, "ledgerHeadHash": ZERO_HASH, "updatedAt": now()}
            state = initial_append(run, state, "mission_initialized", "DISCOVERY", {"missionHash": mission_hash, "controller": state["controller"]})
            state = append_event(run, state, "checkers_frozen", extra={"checkerManifestHash": manifest["manifestHash"]})
            state = append_event(run, state, "attempt_started")
            replay(run, mission)
            if final_run.exists() or final_run.is_symlink():
                raise Refusal("mission run already exists")
            os.replace(staging, final_run)
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return state
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def cmd_candidate(args, root, run, mission, manifest, state):
    if state["stage"] != "DISCOVERY": raise Refusal("candidate is only legal in DISCOVERY")
    candidate = read_json(safe_repo_path(root, args.candidate, must_file=True))
    fp, normalized = fingerprint(candidate)
    if fp in {x["fingerprint"] for x in state["rejections"] if x["fingerprint"]}:
        raise Refusal("candidate repeats a rejected method")
    if state["attempt"] > 1:
        diff = candidate.get("differenceFromRejected")
        if not isinstance(diff, dict) or set(diff) != {"priorAttempt", "changedFields", "reason"} or not diff["changedFields"]:
            raise Refusal("later attempts require differenceFromRejected")
        prior = next((x for x in state["rejections"] if x["attempt"] == diff["priorAttempt"]), None)
        if not prior:
            raise Refusal("named prior attempt was not rejected")
        old = prior["candidate"]
        if not any(path.startswith("method.") and old.get("normalizedMethod", {}).get(path.split(".", 1)[1]) != normalized.get(path.split(".", 1)[1]) for path in diff["changedFields"]):
            raise Refusal("claimed method fields did not change")
    candidate["fingerprint"], candidate["normalizedMethod"] = fp, normalized
    state["candidate"] = candidate
    return append_event(run, state, "candidate_selected", "FEASIBILITY", {"fingerprint": fp})


def cmd_evidence(args, root, run, mission, manifest, state):
    if state["stage"] in {"COMPLETE", "STOPPED"}: raise Refusal("terminal missions reject evidence")
    if not SLUG.fullmatch(args.id) or not ACTION_SLUG.fullmatch(args.kind): raise Refusal("evidence ID and kind must be slugs")
    if any(e["id"] == args.id and e["attempt"] == state["attempt"] for e in state["evidence"]): raise Refusal("evidence ID already used")
    source = safe_repo_path(root, args.file, must_file=True)
    if source.is_symlink(): raise Refusal("symlink evidence rejected")
    allowed = [safe_repo_path(root, p) for p in mission["allowedEvidence"]["roots"]]
    if not any(inside(path, source) or source == path for path in allowed): raise Refusal("evidence is outside allowed roots")
    data = source.read_bytes()
    copied_rel = Path(".omx/outcome-loop") / state["missionId"] / "evidence" / f"attempt-{state['attempt']:04d}" / f"{args.id}--{source.name}"
    copied = safe_repo_path(root, str(copied_rel))
    copied.parent.mkdir(parents=True, exist_ok=True)
    copied.write_bytes(data)
    entry = {"id": args.id, "kind": args.kind, "source": str(source.relative_to(root)), "copied": str(copied_rel), "sha256": sha_bytes(data), "bytes": len(data), "attempt": state["attempt"]}
    state["evidence"].append(entry)
    return append_event(run, state, "evidence_recorded", extra={"evidence": entry})


def find_evidence(state, evidence_id, kind=None):
    entry = next((e for e in state["evidence"] if e["attempt"] == state["attempt"] and e["id"] == evidence_id), None)
    if not entry or (kind and entry["kind"] != kind): raise Refusal("matching current-attempt evidence not found")
    return entry


def cmd_feasibility(args, root, run, mission, manifest, state):
    if state["stage"] != "FEASIBILITY" or args.check not in CHECKS: raise Refusal("feasibility check is not legal")
    entry = find_evidence(state, args.evidence, f"feasibility_{args.check}")
    if entry["bytes"] < 1: raise Refusal("feasibility evidence is empty")
    result = frozen_command(root, run, manifest, mission["feasibilityChecks"][args.check], root / entry["copied"])
    decision = None
    if args.status == "pass" and result["exitCode"] == 0 and not result["timedOut"]:
        try: decision = json.loads(result["stdout"])
        except json.JSONDecodeError: decision = None
    valid = isinstance(decision, dict) and decision.get("status") == "PASS" and decision.get("evidenceSha256") == entry["sha256"] and isinstance(decision.get("facts"), list) and bool(decision["facts"])
    facts = {k: v for k, v in result.items() if k not in {"stdout", "stderr"}}
    if not valid:
        stage = reset_attempt(state, f"feasibility {args.check} failed")
        return append_event(run, state, "attempt_rejected", stage, {"check": args.check, "run": facts})
    state["feasibility"][args.check] = {"status": "PASS", "evidenceId": entry["id"], "sha256": entry["sha256"], "facts": decision["facts"]}
    to_stage = "PLANNED" if all(state["feasibility"].values()) else "FEASIBILITY"
    return append_event(run, state, "feasibility_recorded", to_stage, {"check": args.check, "run": facts})


def cmd_authorize(args, root, run, mission, manifest, state):
    if state["stage"] in {"COMPLETE", "STOPPED"}: raise Refusal("terminal mission")
    expected_stage = "FINAL_GATE" if args.action == "run_goal_check" else "PLANNED"
    if state["stage"] != expected_stage: raise Refusal(f"{args.action} authorization is only legal in {expected_stage}")
    if any(item["status"] in {"open", "running"} for item in state["authorizations"]): raise Refusal("another authorization is unfinished")
    estimate = money(args.estimated_cost_usd)
    allowed, forbidden = mission["permissions"]["allowedActions"], mission["permissions"]["forbiddenActions"]
    if args.action not in allowed or args.action in forbidden:
        state = append_event(run, state, "permission_breach", "STOPPED", {"action": args.action})
        return state
    if money(state["budget"]["spentCostUsd"]) + estimate > money(state["budget"]["maxCostUsd"]):
        return append_event(run, state, "budget_breach", "STOPPED", {"action": args.action})
    auth = {"id": secrets.token_hex(16), "action": args.action, "estimatedCostUsd": money_text(estimate), "status": "open", "attempt": state["attempt"]}
    state["authorizations"].append(auth)
    state = append_event(run, state, "action_authorized", extra={"authorization": auth})
    state["authorizationId"] = auth["id"]
    return state


def find_auth(state, auth_id):
    auth = next((x for x in state["authorizations"] if x["id"] == auth_id), None)
    if not auth: raise Refusal("unknown authorization")
    return auth


def cmd_complete_action(args, root, run, mission, manifest, state):
    auth = find_auth(state, args.authorization_id)
    if auth["status"] != "open": raise Refusal("authorization is not open")
    if auth["action"] == "run_goal_check": raise Refusal("run_goal_check is completed only by final-gate")
    if auth["action"] == "modify_repository" and (state["stage"] != "BUILDING" or auth.get("usedByBuild") is not True):
        raise Refusal("modify_repository is completed only in BUILDING after start-build")
    if auth["action"] != "modify_repository" and state["stage"] != "PLANNED":
        raise Refusal("action completion is only legal in PLANNED")
    actual = money(args.actual_cost_usd)
    spent = money(state["budget"]["spentCostUsd"])
    if spent + actual > money(state["budget"]["maxCostUsd"]):
        return append_event(run, state, "budget_breach", "STOPPED", {"authorizationId": auth["id"]})
    auth["status"], auth["actualCostUsd"] = "completed", money_text(actual)
    state["budget"]["spentCostUsd"] = money_text(spent + actual)
    return append_event(run, state, "action_completed", extra={"authorizationId": auth["id"]})


def cmd_plan(args, root, run, mission, manifest, state):
    if state["stage"] != "PLANNED": raise Refusal("plan is only legal in PLANNED")
    find_evidence(state, args.evidence, "plan")
    state["planEvidenceId"] = args.evidence
    return append_event(run, state, "plan_recorded", extra={"evidenceId": args.evidence})


def cmd_start_build(args, root, run, mission, manifest, state):
    if state["stage"] != "PLANNED" or not state["planEvidenceId"] or not all(state["feasibility"].values()): raise Refusal("build prerequisites are missing")
    auth = find_auth(state, args.authorization_id)
    if auth["action"] != "modify_repository" or auth["status"] != "open": raise Refusal("open modify_repository authorization required")
    builder_agent_id = identity(args.builder_agent_id, "builder agent ID")
    builder_thread_id = identity(args.builder_thread_id, "builder thread ID")
    controller = state["controller"]
    if builder_agent_id == controller["agentId"] or builder_thread_id == controller["threadId"]: raise Refusal("controller cannot be builder")
    auth["usedByBuild"] = True
    state["builder"] = {"agentId": builder_agent_id, "threadId": builder_thread_id, "authorizationId": auth["id"]}
    return append_event(run, state, "builder_declared", "BUILDING", {"builder": state["builder"]})


def fresh_build_evidence_ids(run, state):
    boundary = 0
    fresh = set()
    for line in internal_path(run, "ledger.jsonl", must_file=True).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["attempt"] != state["attempt"]:
            continue
        is_boundary = event["event"] in {"builder_declared", "build_failed", "final_repair_started"}
        is_boundary = is_boundary or (event["event"] == "review_rejected" and event["payload"].get("disposition") == "repair")
        if is_boundary:
            boundary = event["sequence"]
            fresh.clear()
        elif event["event"] == "evidence_recorded" and event["sequence"] > boundary:
            fresh.add(event["payload"]["evidence"]["id"])
    if not boundary:
        raise Refusal("build evidence boundary is missing")
    return fresh


def cmd_build_result(args, root, run, mission, manifest, state):
    if state["stage"] != "BUILDING" or not state["builder"]: raise Refusal("build result is not legal")
    auth = find_auth(state, state["builder"]["authorizationId"])
    if auth["status"] != "completed": raise Refusal("build action must be completed first")
    entries = [find_evidence(state, eid) for eid in args.evidence]
    if args.status == "pass":
        fresh_ids = fresh_build_evidence_ids(run, state)
        kinds = {x["kind"] for x in entries if x["id"] in fresh_ids}
        if not {"implementation", "test"} <= kinds: raise Refusal("passing build needs implementation and test evidence")
        return append_event(run, state, "build_passed", "REVIEW", {"evidenceIds": args.evidence})
    state["repairCycle"] += 1
    return append_event(run, state, "build_failed", extra={"evidenceIds": args.evidence})


REVIEW_CHECKS = {"missionMatches", "goalEvidenceSupportsPass", "feasibilityPrecededBuild", "candidateAddressesEarlierFailure", "budgetAndPermissionsIntact", "rawArtifactsRead", "networkNotUsed"}
REVIEW_FIELDS = {"formatVersion", "missionId", "attempt", "inputSha256", "reviewer", "decision", "disposition", "checks", "artifactFindings", "editedPaths"}
REVIEWER_FIELDS = {"agentId", "threadId", "role", "mode"}


def validate_review_contract(review, state, input_sha256):
    if not isinstance(review, dict) or set(review) != REVIEW_FIELDS:
        raise Refusal("review fields do not exactly match version 1")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict) or set(reviewer) != REVIEWER_FIELDS:
        raise Refusal("reviewer fields do not exactly match version 1")
    checked = copy.deepcopy(review)
    checked_reviewer = checked["reviewer"]
    checked_reviewer["agentId"] = identity(checked_reviewer["agentId"], "reviewer agent ID")
    checked_reviewer["threadId"] = identity(checked_reviewer["threadId"], "reviewer thread ID")
    if checked_reviewer["role"] != "independent-verifier" or checked_reviewer["mode"] != "read_only":
        raise Refusal("reviewer must be an independent read-only verifier")
    if checked["formatVersion"] != 1 or checked["missionId"] != state["missionId"] or checked["attempt"] != state["attempt"] or checked["inputSha256"] != input_sha256:
        raise Refusal("review does not match prepared input")
    if not isinstance(checked["checks"], dict) or set(checked["checks"]) != REVIEW_CHECKS or any(value not in {"PASS", "FAIL"} for value in checked["checks"].values()):
        raise Refusal("review checklist is invalid")
    if checked["editedPaths"] != []:
        raise Refusal("reviewer must be read-only and make no edits")
    findings = checked["artifactFindings"]
    if not isinstance(findings, list) or not all(isinstance(item, str) and item.strip() for item in findings):
        raise Refusal("review findings are invalid")
    controller, builder = state["controller"], state.get("builder")
    if not isinstance(builder, dict):
        raise Refusal("review builder identity is missing")
    identities = [(controller["agentId"], controller["threadId"]), (builder["agentId"], builder["threadId"]), (checked_reviewer["agentId"], checked_reviewer["threadId"])]
    if len({item[0] for item in identities}) != 3 or len({item[1] for item in identities}) != 3:
        raise Refusal("controller, builder, and reviewer must be pairwise distinct")
    if checked["decision"] == "APPROVE":
        if checked["disposition"] is not None or findings or any(value != "PASS" for value in checked["checks"].values()):
            raise Refusal("approval requires no findings and every check to pass")
    elif checked["decision"] == "REJECT":
        if checked["disposition"] not in {"repair", "new_candidate"} or not findings:
            raise Refusal("rejection requires a disposition and finding")
    else:
        raise Refusal("invalid review decision")
    return checked


def cmd_prepare_review(args, root, run, mission, manifest, state):
    if state["stage"] != "REVIEW": raise Refusal("review is only prepared in REVIEW")
    artifacts = evidence_ok(root, state, mission=mission, required=True)
    capability = secrets.token_urlsafe(32)
    capability_hash = sha_bytes(capability.encode())
    ledger_path = internal_path(run, "ledger.jsonl", must_file=True)
    input_obj = {"formatVersion": 1, "mission": mission, "missionHash": state["missionHash"], "checkerManifest": manifest, "candidate": state["candidate"], "rejections": state["rejections"], "feasibility": state["feasibility"], "budget": state["budget"], "permissions": mission["permissions"], "ledgerSlice": [json.loads(x) for x in ledger_path.read_text().splitlines() if json.loads(x)["attempt"] == state["attempt"]], "artifacts": artifacts, "controller": state["controller"], "builder": state["builder"], "reviewCapabilitySha256": capability_hash, "checklist": sorted(REVIEW_CHECKS)}
    review_dir = internal_path(run, Path("review") / f"attempt-{state['attempt']:04d}")
    review_dir.mkdir(parents=True, exist_ok=True)
    input_path = internal_path(run, Path("review") / f"attempt-{state['attempt']:04d}" / "input.json")
    atomic_json(input_path, input_obj)
    input_hash = sha_file(input_path)
    state["reviewCapability"] = {"hash": capability_hash, "inputSha256": input_hash, "used": False}
    state["review"] = {"input": str(input_path.relative_to(root)), "inputSha256": input_hash, "preparedEvidenceIds": [x["id"] for x in artifacts], "output": None}
    state = append_event(run, state, "review_prepared", extra={"inputSha256": input_hash, "capabilitySha256": capability_hash})
    state["reviewCapabilityClear"] = capability
    return state


def cmd_review_result(args, root, run, mission, manifest, state):
    if state["stage"] != "REVIEW" or not args.from_stdin or not state["reviewCapability"]: raise Refusal("no pending review")
    submitter_agent_id = identity(args.submitter_agent_id, "submitter agent ID")
    submitter_thread_id = identity(args.submitter_thread_id, "submitter thread ID")
    controller = state["controller"]
    if submitter_agent_id != controller["agentId"] or submitter_thread_id != controller["threadId"]: raise Refusal("only the frozen controller may submit review")
    envelope = json.load(sys.stdin)
    if not isinstance(envelope, dict) or set(envelope) != {"reviewCapability", "review"}:
        raise Refusal("review envelope fields are invalid")
    clear, review = envelope.get("reviewCapability", ""), envelope.get("review")
    cap = state["reviewCapability"]
    if not isinstance(clear, str) or cap["used"] or not hmac.compare_digest(sha_bytes(clear.encode()), cap["hash"]): raise Refusal("review capability is wrong or already used")
    review = validate_review_contract(review, state, cap["inputSha256"])
    reviewer = review["reviewer"]
    decision = review.get("decision")
    disposition = review.get("disposition")
    evidence_ok(root, state, mission=mission, required=True)
    cap["used"] = True
    state = append_event(run, state, "review_capability_used", extra={"inputSha256": cap["inputSha256"], "submitter": controller})
    output_path = internal_path(run, Path("review") / f"attempt-{state['attempt']:04d}" / "output.json")
    atomic_json(output_path, review)
    output_hash = sha_file(output_path)
    state["review"]["output"] = str(output_path.relative_to(root))
    state["review"]["outputSha256"] = output_hash
    state["review"]["reviewer"] = reviewer
    state["review"]["submitter"] = controller
    if decision == "APPROVE":
        return append_event(run, state, "review_received", "FINAL_GATE", {"outputSha256": output_hash})
    if disposition == "repair":
        state["repairCycle"] += 1
        state["review"] = None; state["reviewCapability"] = None
        return append_event(run, state, "review_rejected", "BUILDING", {"disposition": "repair"})
    stage = reset_attempt(state, "independent review rejected candidate")
    return append_event(run, state, "review_rejected", stage, {"disposition": "new_candidate"})


def cmd_repair_final(args, root, run, mission, manifest, state):
    if state["stage"] != "FINAL_GATE": raise Refusal("final repair requires FINAL_GATE")
    find_evidence(state, args.evidence)
    state["repairCycle"] += 1
    state["review"] = None; state["reviewCapability"] = None; state["finalGate"] = None
    return append_event(run, state, "final_repair_started", "BUILDING", {"reason": args.reason, "evidenceId": args.evidence})


def cmd_reject(args, root, run, mission, manifest, state):
    find_evidence(state, args.evidence)
    if state["stage"] in {"COMPLETE", "STOPPED"}: raise Refusal("terminal mission")
    stage = reset_attempt(state, args.reason)
    return append_event(run, state, "attempt_rejected", stage, {"reason": args.reason, "evidenceId": args.evidence})


def cmd_stop(args, root, run, mission, manifest, state):
    if state["stage"] in {"COMPLETE", "STOPPED"}: raise Refusal("mission is terminal")
    if args.condition not in mission["stopConditions"]: raise Refusal("stop condition is not frozen in mission")
    find_evidence(state, args.evidence)
    return append_event(run, state, "mission_stopped", "STOPPED", {"condition": args.condition, "evidenceId": args.evidence})


def final_preconditions(root, run, mission, manifest, state):
    if state["stage"] != "FINAL_GATE" or not state["review"] or not state["review"].get("output"): raise Refusal("valid approval is missing")
    evidence = evidence_ok(root, state, mission=mission, required=True)
    input_path, output_path = validate_review_files(run, state, require_output=True)
    review_input = read_json(input_path)
    review_output = validate_review_contract(read_json(output_path), state, state["review"]["inputSha256"])
    reviewed = {x["id"]: x for x in review_input["artifacts"]}
    if review_input["artifacts"] != evidence:
        raise Refusal("review is stale because the evidence set changed")
    paths = {}
    for item in evidence:
        if item["id"] in state["review"]["preparedEvidenceIds"]:
            old = reviewed.get(item["id"])
            if old != item: raise Refusal("reviewed artifact manifest changed")
            paths[item["id"]] = root / item["copied"]
    if review_output["decision"] != "APPROVE": raise Refusal("review did not approve")
    if any(x["status"] == "open" and x["action"] != "run_goal_check" for x in state["authorizations"]): raise Refusal("unrelated authorization remains open")
    return paths


def cmd_final_gate(args, root, run, mission, manifest, state):
    if state["stage"] == "COMPLETE":
        evidence_ok(root, state, mission=mission, required=True, all_attempts=True)
        final_path = internal_path(run, "final-result.json", must_file=True)
        result = read_json(final_path)
        if result != completed_result(run, state): raise Refusal("completed result changed")
        return result
    paths = final_preconditions(root, run, mission, manifest, state)
    auth = find_auth(state, args.authorization_id)
    if auth["action"] != "run_goal_check" or auth["status"] != "open" or auth["estimatedCostUsd"] != "0.00": raise Refusal("open zero-cost run_goal_check authorization required")
    auth["status"] = "running"
    state = append_event(run, state, "final_gate_started", extra={"authorizationId": auth["id"]})
    auth = find_auth(state, args.authorization_id)
    result = frozen_command(root, run, manifest, mission["passCondition"], final_evidence=paths)
    # A checker may be buggy or hostile. Revalidate every frozen and reviewed
    # input after it exits and before any successful result can be recorded.
    post_mission, post_mission_hash, post_manifest = frozen_valid(root, run)
    if post_mission_hash != state["missionHash"] or post_manifest["manifestHash"] != state["checkerManifestHash"]:
        raise Refusal("frozen inputs changed during goal check")
    post_paths = final_preconditions(root, run, post_mission, post_manifest, state)
    if post_paths != paths:
        raise Refusal("reviewed inputs changed during goal check")
    output_dir = internal_path(run, Path("evidence") / f"attempt-{state['attempt']:04d}")
    stdout_path = internal_path(run, Path("evidence") / f"attempt-{state['attempt']:04d}" / "goal-stdout.bin")
    stderr_path = internal_path(run, Path("evidence") / f"attempt-{state['attempt']:04d}" / "goal-stderr.bin")
    final_path = internal_path(run, "final-result.json")
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path.write_bytes(result["stdout"])
    stderr_path.write_bytes(result["stderr"])
    auth["status"], auth["actualCostUsd"] = "completed", "0.00"
    facts = {k: v for k, v in result.items() if k not in {"stdout", "stderr"}}
    state = append_event(run, state, "action_completed", extra={"authorizationId": auth["id"], "goalRun": facts})
    if result["exitCode"] != 0 or result["timedOut"]:
        stage = reset_attempt(state, "deterministic goal check failed")
        return append_event(run, state, "goal_check_failed", stage, {"run": facts})
    state["finalGate"] = facts
    state = append_event(run, state, "final_gate_passed", "COMPLETE", {"run": facts})
    final = completed_result(run, state)
    atomic_json(final_path, final)
    return final


def parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    def add(name):
        q = sub.add_parser(name); q.add_argument("--root", required=True); return q
    q=add("validate-mission"); q.add_argument("--mission", required=True)
    q=add("init"); q.add_argument("--mission", required=True); q.add_argument("--controller-agent-id", required=True); q.add_argument("--controller-thread-id", required=True)
    for name in ("status", "resume"): q=add(name); q.add_argument("--mission-id", required=True)
    q=add("candidate"); q.add_argument("--mission-id", required=True); q.add_argument("--candidate", required=True)
    q=add("evidence"); q.add_argument("--mission-id", required=True); q.add_argument("--id", required=True); q.add_argument("--kind", required=True); q.add_argument("--file", required=True)
    q=add("feasibility"); q.add_argument("--mission-id", required=True); q.add_argument("--check", required=True, choices=CHECKS); q.add_argument("--status", required=True, choices=("pass","fail")); q.add_argument("--evidence", required=True)
    q=add("authorize-action"); q.add_argument("--mission-id", required=True); q.add_argument("--action", required=True); q.add_argument("--estimated-cost-usd", required=True)
    q=add("complete-action"); q.add_argument("--mission-id", required=True); q.add_argument("--authorization-id", required=True); q.add_argument("--actual-cost-usd", required=True)
    q=add("plan"); q.add_argument("--mission-id", required=True); q.add_argument("--evidence", required=True)
    q=add("start-build"); q.add_argument("--mission-id", required=True); q.add_argument("--builder-agent-id", required=True); q.add_argument("--builder-thread-id", required=True); q.add_argument("--authorization-id", required=True)
    q=add("build-result"); q.add_argument("--mission-id", required=True); q.add_argument("--status", required=True, choices=("pass","fail")); q.add_argument("--evidence", action="append", required=True)
    q=add("prepare-review"); q.add_argument("--mission-id", required=True)
    q=add("review-result"); q.add_argument("--mission-id", required=True); q.add_argument("--submitter-agent-id", required=True); q.add_argument("--submitter-thread-id", required=True); q.add_argument("--from-stdin", action="store_true")
    q=add("repair-final-gate"); q.add_argument("--mission-id", required=True); q.add_argument("--reason", required=True); q.add_argument("--evidence", required=True)
    q=add("reject-candidate"); q.add_argument("--mission-id", required=True); q.add_argument("--reason", required=True); q.add_argument("--evidence", required=True)
    q=add("stop"); q.add_argument("--mission-id", required=True); q.add_argument("--condition", required=True); q.add_argument("--evidence", required=True)
    q=add("final-gate"); q.add_argument("--mission-id", required=True); q.add_argument("--authorization-id", required=True)
    return p


def output(value):
    safe = copy.deepcopy(value)
    capability = safe.pop("reviewCapabilityClear", None) if isinstance(safe, dict) else None
    if isinstance(safe, dict) and "stage" in safe and "repairCycle" in safe:
        safe = {"missionId": safe["missionId"], "missionVersion": safe["missionVersion"], "stage": safe["stage"], "attempt": safe["attempt"], "repairCycle": safe["repairCycle"], "rejections": safe["rejections"], "budget": safe["budget"], "evidence": [{k:e[k] for k in ("id","kind","sha256","attempt")} for e in safe["evidence"]], "review": safe["review"], "legalNextCommands": legal_next(safe)}
        if "authorizationId" in value: safe["authorizationId"] = value["authorizationId"]
    if capability: safe["reviewCapability"] = capability
    print(json.dumps(safe, sort_keys=True))


def main():
    args = parser().parse_args()
    try:
        root = root_path(args.root)
        if args.command == "validate-mission":
            mission, raw = validate_mission(safe_repo_path(root, args.mission, must_file=True), root)
            return output({"valid": True, "missionId": mission["missionId"], "sha256": sha_bytes(raw)})
        if args.command == "init":
            return output(cmd_init(args, root))
        run = run_dir(root, args.mission_id)
        if not run.is_dir():
            raise Refusal("mission run does not exist")
        with locked(run):
            run, mission, manifest, state = load(root, args.mission_id)
            if args.command in {"status", "resume"}: return output(state)
            dispatch = {"candidate": cmd_candidate, "evidence": cmd_evidence, "feasibility": cmd_feasibility, "authorize-action": cmd_authorize, "complete-action": cmd_complete_action, "plan": cmd_plan, "start-build": cmd_start_build, "build-result": cmd_build_result, "prepare-review": cmd_prepare_review, "review-result": cmd_review_result, "repair-final-gate": cmd_repair_final, "reject-candidate": cmd_reject, "stop": cmd_stop, "final-gate": cmd_final_gate}
            return output(dispatch[args.command](args, root, run, mission, manifest, state))
    except (Refusal, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
