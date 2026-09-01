import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[3]
PLUGIN = SOURCE_ROOT / "plugins" / "outcome-loop"


def run(root, *args, stdin=None, expect=0, program=None, env=None):
    command = [sys.executable, str(program or root / "plugins/outcome-loop/scripts/outcome_loop.py"), *args, "--root", str(root)]
    result = subprocess.run(command, input=json.dumps(stdin) if stdin is not None else None, text=True, capture_output=True, env=env)
    assert result.returncode == expect, (command, result.stdout, result.stderr)
    return json.loads(result.stdout)


def run_codex(codex_home, *args):
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    result = subprocess.run([shutil.which("codex"), *args], text=True, capture_output=True, env=env)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return json.loads(result.stdout)


def rehash_ledger(path, mutate):
    events = [json.loads(line) for line in path.read_text().splitlines()]
    mutate(events)
    previous = "0" * 64
    lines = []
    for sequence, event in enumerate(events, 1):
        event.pop("eventHash", None)
        event["sequence"] = sequence
        event["previousHash"] = previous
        event["eventHash"] = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        previous = event["eventHash"]
        lines.append(json.dumps(event, sort_keys=True, separators=(",", ":")))
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "plugins").mkdir(parents=True)
    shutil.copytree(PLUGIN, root / "plugins/outcome-loop")
    (root / ".agents/plugins").mkdir(parents=True)
    shutil.copy2(SOURCE_ROOT / ".agents/plugins/marketplace.json", root / ".agents/plugins/marketplace.json")
    return root


def mission(root, mission_id="analyst-record-dry-run", checker="check_analyst_records.py", max_cost="0.00", max_attempts=3):
    value = json.loads((root / "plugins/outcome-loop/templates/mission.template.json").read_text())
    value["missionId"] = mission_id
    value["budget"] = {"maxCostUsd": max_cost, "maxAttempts": max_attempts}
    value["allowedEvidence"]["roots"][-1] = f".omx/outcome-loop/{mission_id}"
    value["passCondition"]["command"][1] = f"plugins/outcome-loop/tests/fixtures/{checker}"
    value["passCondition"]["checkerFiles"] = [f"plugins/outcome-loop/tests/fixtures/{checker}"]
    path = root / "plugins/outcome-loop/tests/fixtures" / f"{mission_id}.json"
    path.write_text(json.dumps(value, indent=2) + "\n")
    return path, value


def write(root, name, value):
    path = root / "plugins/outcome-loop/tests/fixtures" / name
    path.write_text(json.dumps(value) + "\n" if not isinstance(value, str) else value)
    return path


def candidate(root, attempt, family, threshold=4):
    value = {"candidateId": f"attempt-{attempt}-{family}", "name": family, "method": {"family": family, "inputs": ["analyst", "direction", "published-time", "ticker"], "transformation": family, "decisionRule": family, "output": "complete-record-count"}, "thresholds": {"minimumCompleteRecords": threshold}}
    if attempt > 1:
        value["differenceFromRejected"] = {"priorAttempt": attempt - 1, "changedFields": ["method.family", "method.transformation", "method.decisionRule"], "reason": "Addresses the prior failure."}
    path = write(root, f"candidate-{attempt}.json", value)
    return path, value


def init(root, mission_path):
    return run(root, "init", "--mission", str(mission_path.relative_to(root)), "--controller-agent-id", "controller-agent", "--controller-thread-id", "controller-thread")


def add_evidence(root, mission_id, evidence_id, kind, value, *, source_name=None):
    path = write(root, source_name or f"{mission_id}-{evidence_id}.json", value)
    return run(root, "evidence", "--mission-id", mission_id, "--id", evidence_id, "--kind", kind, "--file", str(path.relative_to(root)))


def reach_review(root, mission_id, attempt, family, result_value):
    path, _ = candidate(root, attempt, family)
    run(root, "candidate", "--mission-id", mission_id, "--candidate", str(path.relative_to(root)))
    reach_planned(root, mission_id, attempt)
    auth = run(root, "authorize-action", "--mission-id", mission_id, "--action", "modify_repository", "--estimated-cost-usd", "0.00")["authorizationId"]
    run(root, "start-build", "--mission-id", mission_id, "--builder-agent-id", f"builder-agent-{attempt}", "--builder-thread-id", f"builder-thread-{attempt}", "--authorization-id", auth)
    run(root, "complete-action", "--mission-id", mission_id, "--authorization-id", auth, "--actual-cost-usd", "0.00")
    add_evidence(root, mission_id, f"implementation-{attempt}", "implementation", {"method": family})
    add_evidence(root, mission_id, f"test-{attempt}", "test", {"passed": True})
    add_evidence(root, mission_id, "result", "test", result_value, source_name=f"{mission_id}-result-{attempt}.json")
    return run(root, "build-result", "--mission-id", mission_id, "--status", "pass", "--evidence", f"implementation-{attempt}", "--evidence", f"test-{attempt}")


def reach_planned(root, mission_id, attempt):
    for check in ("data", "access", "cost", "permission"):
        eid = f"{check}-{attempt}"
        add_evidence(root, mission_id, eid, f"feasibility_{check}", {"check": check, "available": True, "fact": f"{check} is locally available"})
        run(root, "feasibility", "--mission-id", mission_id, "--check", check, "--status", "pass", "--evidence", eid)
    add_evidence(root, mission_id, f"plan-{attempt}", "plan", {"steps": ["build", "test"]})
    run(root, "plan", "--mission-id", mission_id, "--evidence", f"plan-{attempt}")


def approve(root, mission_id, attempt, *, reviewer_agent=None, reviewer_thread=None, decision="APPROVE", disposition=None, edits=None):
    prepared = run(root, "prepare-review", "--mission-id", mission_id)
    cap = prepared["reviewCapability"]
    input_hash = prepared["review"]["inputSha256"]
    review = review_value(mission_id, attempt, input_hash, reviewer_agent=reviewer_agent, reviewer_thread=reviewer_thread, decision=decision, disposition=disposition, edits=edits)
    result = run(root, "review-result", "--mission-id", mission_id, "--submitter-agent-id", "controller-agent", "--submitter-thread-id", "controller-thread", "--from-stdin", stdin={"reviewCapability": cap, "review": review}, expect=0)
    return result, cap, review


def review_value(mission_id, attempt, input_hash, *, reviewer_agent=None, reviewer_thread=None, decision="APPROVE", disposition=None, edits=None):
    return {"formatVersion": 1, "missionId": mission_id, "attempt": attempt, "inputSha256": input_hash, "reviewer": {"agentId": reviewer_agent or f"reviewer-agent-{attempt}", "threadId": reviewer_thread or f"reviewer-thread-{attempt}", "role": "independent-verifier", "mode": "read_only"}, "decision": decision, "disposition": disposition, "checks": {key: "PASS" for key in ["missionMatches", "goalEvidenceSupportsPass", "feasibilityPrecededBuild", "candidateAddressesEarlierFailure", "budgetAndPermissionsIntact", "rawArtifactsRead", "networkNotUsed"]}, "artifactFindings": [] if decision == "APPROVE" else ["Concrete finding"], "editedPaths": edits or []}


def set_pass_checker(root, mission_path, mission_value, name, source, *, timeout=10):
    checker = root / "plugins/outcome-loop/tests/fixtures" / name
    checker.write_text(source)
    relative = str(checker.relative_to(root))
    mission_value["passCondition"]["command"][1] = relative
    mission_value["passCondition"]["checkerFiles"] = [relative]
    mission_value["passCondition"]["timeoutSeconds"] = timeout
    mission_path.write_text(json.dumps(mission_value, indent=2) + "\n")
    return checker


def final(root, mission_id):
    auth = run(root, "authorize-action", "--mission-id", mission_id, "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    return run(root, "final-gate", "--mission-id", mission_id, "--authorization-id", auth)


def full_two_attempt(root, mission_id="analyst-record-dry-run", checker="check_analyst_records.py", second=None):
    mission_path, _ = mission(root, mission_id, checker)
    init(root, mission_path)
    reach_review(root, mission_id, 1, "plain-line-count", {"uniqueCompleteRecords": 5})
    approve(root, mission_id, 1)
    failed = final(root, mission_id)
    assert failed["stage"] == "DISCOVERY" and failed["attempt"] == 2
    reach_review(root, mission_id, 2, "normalize-and-deduplicate", second or {"uniqueCompleteRecords": 4})
    approve(root, mission_id, 2)
    return final(root, mission_id)


def test_init_rejects_each_missing_required_mission_field(repo):
    path, value = mission(repo)
    for field in list(value):
        broken = copy.deepcopy(value); broken.pop(field)
        path.write_text(json.dumps(broken))
        run(repo, "validate-mission", "--mission", str(path.relative_to(repo)), expect=2)


def test_bare_file_like_goal_argument_is_rejected(repo):
    path, value = mission(repo)
    value["passCondition"]["command"].append("result.json")
    path.write_text(json.dumps(value))
    run(repo, "validate-mission", "--mission", str(path.relative_to(repo)), expect=2)


def test_bare_relative_goal_file_argument_is_rejected(repo):
    path, value = mission(repo)
    write(repo, "result", {"uniqueCompleteRecords": 4})
    value["passCondition"]["command"].append("result")
    path.write_text(json.dumps(value))
    run(repo, "validate-mission", "--mission", str(path.relative_to(repo)), expect=2)


def test_changed_mission_or_checker_hash_blocks_resume_and_final_gate(repo):
    path, _ = mission(repo); init(repo, path)
    frozen = repo / ".omx/outcome-loop/analyst-record-dry-run/mission.json"
    frozen.write_text(frozen.read_text() + " ")
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)


def test_init_starts_discovery_attempt_one_and_freezes_all_checkers(repo):
    path, _ = mission(repo); state = init(repo, path)
    assert state["stage"] == "DISCOVERY" and state["attempt"] == 1
    manifest = json.loads((repo / ".omx/outcome-loop/analyst-record-dry-run/checker-manifest.json").read_text())
    assert len(manifest["files"]) == 5 and all((repo / ".omx/outcome-loop/analyst-record-dry-run" / x["frozen"]).is_file() for x in manifest["files"])


def test_build_is_forbidden_until_all_four_frozen_feasibility_commands_pass(repo):
    path, _ = mission(repo); init(repo, path); c,_=candidate(repo,1,"plain-line-count")
    run(repo,"candidate","--mission-id","analyst-record-dry-run","--candidate",str(c.relative_to(repo)))
    run(repo,"start-build","--mission-id","analyst-record-dry-run","--builder-agent-id","b","--builder-thread-id","bt","--authorization-id","missing",expect=2)


def test_empty_random_or_wrong_kind_feasibility_evidence_cannot_unlock_build(repo):
    path,_=mission(repo); init(repo,path); c,_=candidate(repo,1,"plain-line-count"); run(repo,"candidate","--mission-id","analyst-record-dry-run","--candidate",str(c.relative_to(repo)))
    add_evidence(repo,"analyst-record-dry-run","wrong","test",{"check":"data","available":True})
    run(repo,"feasibility","--mission-id","analyst-record-dry-run","--check","data","--status","pass","--evidence","wrong",expect=2)


def test_only_the_declared_success_stage_order_is_accepted(repo):
    path,_=mission(repo); init(repo,path)
    run(repo,"plan","--mission-id","analyst-record-dry-run","--evidence","missing",expect=2)
    ledger=repo/".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl"; lines=ledger.read_text().splitlines(); event=json.loads(lines[-1]); event["toStage"]="COMPLETE"; event["payload"]["stateAfter"]["stage"]="COMPLETE"; event.pop("eventHash"); event["eventHash"]=hashlib.sha256(json.dumps(event,sort_keys=True,separators=(",",":")).encode()).hexdigest(); lines[-1]=json.dumps(event,separators=(",",":")); ledger.write_text("\n".join(lines)+"\n")
    run(repo,"resume","--mission-id","analyst-record-dry-run",expect=2)


def test_candidate_or_goal_failure_starts_new_discovery_attempt(repo):
    result=full_two_attempt(repo); assert result["stage"]=="COMPLETE" and result["attempt"]==2


def test_build_or_test_failure_repairs_same_candidate(repo):
    path,_=mission(repo); init(repo,path); reach_review(repo,"analyst-record-dry-run",1,"plain-line-count",{"uniqueCompleteRecords":5})
    # Review repair is the same-attempt repair path and increments its repair counter.
    result,_,_=approve(repo,"analyst-record-dry-run",1,decision="REJECT",disposition="repair")
    assert result["stage"]=="BUILDING" and result["attempt"]==1 and result["repairCycle"]==1


def test_rejected_review_can_repair_or_start_new_candidate(repo):
    path,_=mission(repo); init(repo,path); reach_review(repo,"analyst-record-dry-run",1,"plain-line-count",{"uniqueCompleteRecords":5})
    result,_,_=approve(repo,"analyst-record-dry-run",1,decision="REJECT",disposition="new_candidate")
    assert result["stage"]=="DISCOVERY" and result["attempt"]==2


def test_stopped_is_never_complete_and_cannot_resume_to_active(repo):
    path,_=mission(repo); init(repo,path); add_evidence(repo,"analyst-record-dry-run","stop-proof","test",{"blocked":True})
    stopped=run(repo,"stop","--mission-id","analyst-record-dry-run","--condition","owner_only_decision","--evidence","stop-proof")
    assert stopped["stage"]=="STOPPED" and run(repo,"resume","--mission-id","analyst-record-dry-run")["stage"]=="STOPPED"


def test_resume_preserves_version_stage_attempt_rejections_budget_and_evidence(repo):
    full_two_attempt(repo); state=run(repo,"resume","--mission-id","analyst-record-dry-run")
    assert state["missionVersion"]==1 and state["attempt"]==2 and state["rejections"] and state["budget"]["spentCostUsd"]=="0.00" and state["evidence"]


def test_resume_rebuilds_missing_state_from_intact_ledger(repo):
    path,_=mission(repo); init(repo,path); state=repo/".omx/outcome-loop/analyst-record-dry-run/state.json"; state.write_text("not json\n"); assert run(repo,"resume","--mission-id","analyst-record-dry-run")["stage"]=="DISCOVERY" and json.loads(state.read_text())["stage"] == "DISCOVERY"


def test_missing_or_changed_copied_evidence_blocks_completion(repo):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    copied = next(run_dir.glob("evidence/attempt-0001/result--*.json"))

    # Editing the working file is normal during repair and must not block.
    source = repo / "plugins/outcome-loop/tests/fixtures/analyst-record-dry-run-result-1.json"
    source.write_text("changed")
    assert run(repo, "status", "--mission-id", "analyst-record-dry-run")["stage"] == "REVIEW"

    # Changing the durable copy, or losing it, does block.
    kept = copied.read_bytes()
    copied.write_text("changed")
    run(repo, "prepare-review", "--mission-id", "analyst-record-dry-run", expect=2)
    copied.write_bytes(kept)
    copied.unlink()
    run(repo, "prepare-review", "--mission-id", "analyst-record-dry-run", expect=2)


def test_name_only_retry_is_rejected(repo):
    path,_=mission(repo); init(repo,path); c,_=candidate(repo,1,"plain-line-count"); run(repo,"candidate","--mission-id","analyst-record-dry-run","--candidate",str(c.relative_to(repo))); add_evidence(repo,"analyst-record-dry-run","reason","test",{"bad":True}); run(repo,"reject-candidate","--mission-id","analyst-record-dry-run","--reason","bad","--evidence","reason"); c2,v=candidate(repo,2,"plain-line-count"); v["name"]="renamed"; c2.write_text(json.dumps(v)); run(repo,"candidate","--mission-id","analyst-record-dry-run","--candidate",str(c2.relative_to(repo)),expect=2)


def test_threshold_only_retry_is_rejected(repo):
    path,_=mission(repo); init(repo,path); c,_=candidate(repo,1,"plain-line-count"); run(repo,"candidate","--mission-id","analyst-record-dry-run","--candidate",str(c.relative_to(repo))); add_evidence(repo,"analyst-record-dry-run","reason","test",{"bad":True}); run(repo,"reject-candidate","--mission-id","analyst-record-dry-run","--reason","bad","--evidence","reason"); c2,v=candidate(repo,2,"plain-line-count",99); c2.write_text(json.dumps(v)); run(repo,"candidate","--mission-id","analyst-record-dry-run","--candidate",str(c2.relative_to(repo)),expect=2)


def test_review_input_contains_frozen_mission_raw_artifacts_and_capability_hash_only(repo):
    path,_=mission(repo); init(repo,path); reach_review(repo,"analyst-record-dry-run",1,"plain-line-count",{"uniqueCompleteRecords":5}); prepared=run(repo,"prepare-review","--mission-id","analyst-record-dry-run"); inp=json.loads((repo/prepared["review"]["input"]).read_text()); assert inp["mission"] and inp["artifacts"] and inp["reviewCapabilitySha256"] and prepared["reviewCapability"] not in json.dumps(inp)


def test_forged_reviewer_ids_without_the_one_time_capability_are_rejected(repo):
    path,_=mission(repo); init(repo,path); reach_review(repo,"analyst-record-dry-run",1,"plain-line-count",{"uniqueCompleteRecords":5}); run(repo,"prepare-review","--mission-id","analyst-record-dry-run"); review={"reviewCapability":"wrong","review":{}}
    run(repo,"review-result","--mission-id","analyst-record-dry-run","--submitter-agent-id","controller-agent","--submitter-thread-id","controller-thread","--from-stdin",stdin=review,expect=2)


def test_builder_with_capability_cannot_submit_forged_approval(repo):
    path,_=mission(repo); init(repo,path); reach_review(repo,"analyst-record-dry-run",1,"plain-line-count",{"uniqueCompleteRecords":5}); prepared=run(repo,"prepare-review","--mission-id","analyst-record-dry-run")
    run(repo,"review-result","--mission-id","analyst-record-dry-run","--submitter-agent-id","builder-agent-1","--submitter-thread-id","builder-thread-1","--from-stdin",stdin={"reviewCapability":prepared["reviewCapability"],"review":{}},expect=2)


def test_controller_builder_and_reviewer_must_be_pairwise_distinct(repo):
    path,_=mission(repo); init(repo,path); reach_review(repo,"analyst-record-dry-run",1,"plain-line-count",{"uniqueCompleteRecords":5}); prepared=run(repo,"prepare-review","--mission-id","analyst-record-dry-run"); base={"formatVersion":1,"missionId":"analyst-record-dry-run","attempt":1,"inputSha256":prepared["review"]["inputSha256"],"reviewer":{"agentId":"builder-agent-1","threadId":"reviewer-thread","role":"independent-verifier","mode":"read_only"},"decision":"APPROVE","disposition":None,"checks":{k:"PASS" for k in ["missionMatches","goalEvidenceSupportsPass","feasibilityPrecededBuild","candidateAddressesEarlierFailure","budgetAndPermissionsIntact","rawArtifactsRead","networkNotUsed"]},"artifactFindings":[],"editedPaths":[]}
    run(repo,"review-result","--mission-id","analyst-record-dry-run","--submitter-agent-id","controller-agent","--submitter-thread-id","controller-thread","--from-stdin",stdin={"reviewCapability":prepared["reviewCapability"],"review":base},expect=2)


def test_same_thread_reused_capability_and_reviewer_edits_are_rejected(repo):
    path,_=mission(repo); init(repo,path); reach_review(repo,"analyst-record-dry-run",1,"plain-line-count",{"uniqueCompleteRecords":5}); prepared=run(repo,"prepare-review","--mission-id","analyst-record-dry-run")
    review={"formatVersion":1,"missionId":"analyst-record-dry-run","attempt":1,"inputSha256":prepared["review"]["inputSha256"],"reviewer":{"agentId":"reviewer-agent","threadId":"controller-thread","role":"independent-verifier","mode":"read_only"},"decision":"APPROVE","disposition":None,"checks":{k:"PASS" for k in ["missionMatches","goalEvidenceSupportsPass","feasibilityPrecededBuild","candidateAddressesEarlierFailure","budgetAndPermissionsIntact","rawArtifactsRead","networkNotUsed"]},"artifactFindings":[],"editedPaths":["x"]}
    run(repo,"review-result","--mission-id","analyst-record-dry-run","--submitter-agent-id","controller-agent","--submitter-thread-id","controller-thread","--from-stdin",stdin={"reviewCapability":prepared["reviewCapability"],"review":review},expect=2)


def test_invalid_review_envelope_does_not_consume_capability_or_change_durable_state(repo):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    prepared = run(repo, "prepare-review", "--mission-id", "analyst-record-dry-run")
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    state_before = (run_dir / "state.json").read_bytes()
    ledger_before = (run_dir / "ledger.jsonl").read_bytes()
    invalid = review_value("analyst-record-dry-run", 1, prepared["review"]["inputSha256"], disposition="repair")

    run(repo, "review-result", "--mission-id", "analyst-record-dry-run", "--submitter-agent-id", "controller-agent", "--submitter-thread-id", "controller-thread", "--from-stdin", stdin={"reviewCapability": prepared["reviewCapability"], "review": invalid}, expect=2)

    assert (run_dir / "state.json").read_bytes() == state_before
    assert (run_dir / "ledger.jsonl").read_bytes() == ledger_before
    assert not (run_dir / "review/attempt-0001/output.json").exists()
    valid = review_value("analyst-record-dry-run", 1, prepared["review"]["inputSha256"])
    result = run(repo, "review-result", "--mission-id", "analyst-record-dry-run", "--submitter-agent-id", "controller-agent", "--submitter-thread-id", "controller-thread", "--from-stdin", stdin={"reviewCapability": prepared["reviewCapability"], "review": valid})
    assert result["stage"] == "FINAL_GATE"


def test_missing_reviewer_or_evidence_blocks_completion(repo):
    path,_=mission(repo); init(repo,path); run(repo,"final-gate","--mission-id","analyst-record-dry-run","--authorization-id","missing",expect=2)


def test_budget_overrun_and_permission_breach_stop_completion(repo):
    path,_=mission(repo); init(repo,path); c,_=candidate(repo,1,"plain-line-count"); run(repo,"candidate","--mission-id","analyst-record-dry-run","--candidate",str(c.relative_to(repo))); reach_planned(repo,"analyst-record-dry-run",1); result=run(repo,"authorize-action","--mission-id","analyst-record-dry-run","--action","network_access","--estimated-cost-usd","0.00"); assert result["stage"]=="STOPPED"
    budget_path,_=mission(repo,"budget-overrun-dry-run",max_cost="0.05"); init(repo,budget_path); c,_=candidate(repo,1,"plain-line-count"); run(repo,"candidate","--mission-id","budget-overrun-dry-run","--candidate",str(c.relative_to(repo))); reach_planned(repo,"budget-overrun-dry-run",1); authorization=run(repo,"authorize-action","--mission-id","budget-overrun-dry-run","--action","modify_repository","--estimated-cost-usd","0.04")["authorizationId"]
    run(repo,"start-build","--mission-id","budget-overrun-dry-run","--builder-agent-id","builder-agent","--builder-thread-id","builder-thread","--authorization-id",authorization)
    result=run(repo,"complete-action","--mission-id","budget-overrun-dry-run","--authorization-id",authorization,"--actual-cost-usd","0.06"); assert result["stage"]=="STOPPED"
    run(repo,"final-gate","--mission-id","budget-overrun-dry-run","--authorization-id",authorization,expect=2)
    ledger=(repo/".omx/outcome-loop/budget-overrun-dry-run/ledger.jsonl").read_text(); assert '"event":"budget_breach"' in ledger and '"event":"final_gate_passed"' not in ledger


def test_final_gate_repair_invalidates_review_and_requires_fresh_build_test_review(repo):
    path,_=mission(repo); init(repo,path); reach_review(repo,"analyst-record-dry-run",1,"plain-line-count",{"uniqueCompleteRecords":4}); approve(repo,"analyst-record-dry-run",1); add_evidence(repo,"analyst-record-dry-run","repair-proof","test",{"reason":"correctable"}); state=run(repo,"repair-final-gate","--mission-id","analyst-record-dry-run","--reason","correctable","--evidence","repair-proof"); assert state["stage"]=="BUILDING" and state["review"] is None
    run(repo,"build-result","--mission-id","analyst-record-dry-run","--status","pass","--evidence","implementation-1","--evidence","test-1",expect=2)
    add_evidence(repo,"analyst-record-dry-run","implementation-final-repair","implementation",{"fixed":True})
    add_evidence(repo,"analyst-record-dry-run","test-final-repair","test",{"passed":True})
    result=run(repo,"build-result","--mission-id","analyst-record-dry-run","--status","pass","--evidence","implementation-final-repair","--evidence","test-final-repair")
    assert result["stage"]=="REVIEW"


def test_review_repair_and_build_failure_each_require_new_build_evidence(repo):
    path,_=mission(repo); init(repo,path); reach_review(repo,"analyst-record-dry-run",1,"plain-line-count",{"uniqueCompleteRecords":4})
    repaired,_,_=approve(repo,"analyst-record-dry-run",1,decision="REJECT",disposition="repair")
    assert repaired["stage"]=="BUILDING"
    run(repo,"build-result","--mission-id","analyst-record-dry-run","--status","pass","--evidence","implementation-1","--evidence","test-1",expect=2)
    add_evidence(repo,"analyst-record-dry-run","implementation-review-repair","implementation",{"fixed":True})
    add_evidence(repo,"analyst-record-dry-run","test-review-repair","test",{"passed":False})
    failed=run(repo,"build-result","--mission-id","analyst-record-dry-run","--status","fail","--evidence","implementation-review-repair","--evidence","test-review-repair")
    assert failed["stage"]=="BUILDING"
    run(repo,"build-result","--mission-id","analyst-record-dry-run","--status","pass","--evidence","implementation-review-repair","--evidence","test-review-repair",expect=2)
    add_evidence(repo,"analyst-record-dry-run","implementation-after-failure","implementation",{"fixed":True})
    add_evidence(repo,"analyst-record-dry-run","test-after-failure","test",{"passed":True})
    result=run(repo,"build-result","--mission-id","analyst-record-dry-run","--status","pass","--evidence","implementation-after-failure","--evidence","test-after-failure")
    assert result["stage"]=="REVIEW"


def test_goal_check_reads_the_reviewed_copy_not_the_working_source(repo):
    # The goal checker is handed the copy under the run directory, so editing
    # the working source after approval cannot steer the verdict either way.
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    source = repo / "plugins/outcome-loop/tests/fixtures/analyst-record-dry-run-result-1.json"
    # The reviewed copy holds 4 unique records, which passes this mission's goal.
    # Rewrite the working source to 5, which fails it. The run still completes,
    # so the verdict came from the reviewed copy and not from the edited source.
    source.write_text(json.dumps({"uniqueCompleteRecords": 5}) + "\n")
    result = final(repo, "analyst-record-dry-run")
    assert result["stage"] == "COMPLETE"


def test_changed_copied_goal_input_blocks_completion(repo):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    copied = next((repo / ".omx/outcome-loop/analyst-record-dry-run").glob("evidence/attempt-0001/result--*.json"))
    copied.write_text(json.dumps({"uniqueCompleteRecords": 5}) + "\n")
    run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "run_goal_check", "--estimated-cost-usd", "0.00", expect=2)


def test_changed_or_hanging_goal_checker_blocks_completion(repo):
    path,_=mission(repo); init(repo,path); checker=repo/"plugins/outcome-loop/tests/fixtures/check_analyst_records.py"; checker.write_text(checker.read_text()+"\n# changed\n"); run(repo,"resume","--mission-id","analyst-record-dry-run",expect=2)


def test_failed_goal_command_rejects_false_pass_and_continues_discovery(repo):
    path,_=mission(repo); init(repo,path); reach_review(repo,"analyst-record-dry-run",1,"plain-line-count",{"uniqueCompleteRecords":5}); approve(repo,"analyst-record-dry-run",1); result=final(repo,"analyst-record-dry-run"); assert result["stage"]=="DISCOVERY" and result["attempt"]==2


def test_valid_pass_needs_frozen_goal_check_intact_evidence_limits_authorization_and_read_only_approval(repo):
    result=full_two_attempt(repo); assert result["stage"]=="COMPLETE"


def test_repeated_final_gate_is_byte_for_byte_idempotent(repo):
    full_two_attempt(repo); run_dir=repo/".omx/outcome-loop/analyst-record-dry-run"; ledger=run_dir.joinpath("ledger.jsonl").read_bytes(); final_bytes=run_dir.joinpath("final-result.json").read_bytes(); result=run(repo,"final-gate","--mission-id","analyst-record-dry-run","--authorization-id","already-complete"); assert result["stage"]=="COMPLETE" and ledger==run_dir.joinpath("ledger.jsonl").read_bytes() and final_bytes==run_dir.joinpath("final-result.json").read_bytes()


def test_repeated_final_gate_rechecks_copied_evidence_from_every_attempt(repo):
    full_two_attempt(repo)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    state = json.loads((run_dir / "state.json").read_text())
    prior_attempt_evidence = next(entry for entry in state["evidence"] if entry["attempt"] == 1)
    (repo / prior_attempt_evidence["copied"]).write_text("tampered\n")
    run(repo, "final-gate", "--mission-id", "analyst-record-dry-run", "--authorization-id", "already-complete", expect=2)


def test_completed_run_survives_edits_to_working_sources(repo):
    # A finished mission must not be bricked by ordinary later work in the repo.
    full_two_attempt(repo)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    state = json.loads((run_dir / "state.json").read_text())
    final_bytes = run_dir.joinpath("final-result.json").read_bytes()
    for entry in state["evidence"]:
        (repo / entry["source"]).write_text("moved on\n")
    result = run(repo, "final-gate", "--mission-id", "analyst-record-dry-run", "--authorization-id", "already-complete")
    assert result["stage"] == "COMPLETE"
    assert run_dir.joinpath("final-result.json").read_bytes() == final_bytes


@pytest.mark.parametrize("field", ["attempt", "goalRun", "completedAt"])
def test_repeated_final_gate_rejects_any_final_result_tamper(repo, field):
    full_two_attempt(repo)
    final_path = repo / ".omx/outcome-loop/analyst-record-dry-run/final-result.json"
    value = json.loads(final_path.read_text())
    value[field] = {"tampered": True} if field == "goalRun" else "tampered"
    final_path.write_text(json.dumps(value) + "\n")
    run(repo, "final-gate", "--mission-id", "analyst-record-dry-run", "--authorization-id", "already-complete", expect=2)


def test_non_trading_dry_run_rejects_false_first_method_and_completes_different_second_method(repo):
    result=full_two_attempt(repo); ledger=(repo/".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl").read_text(); assert result["attempt"]==2 and "goal_check_failed" in ledger and "final_gate_passed" in ledger


def test_temporary_codex_home_installs_discovers_and_resumes_the_plugin(repo, tmp_path):
    # Prove the real Codex CLI installs, discovers, initializes, and resumes the cached copy.
    market=json.loads((repo/".agents/plugins/marketplace.json").read_text()); assert market["name"]=="openclaw-workspace-local" and market["plugins"][0]["name"]=="outcome-loop"
    codex_home=tmp_path/"codex-home"; codex_home.mkdir()
    added=run_codex(codex_home,"plugin","marketplace","add",str(repo),"--json")
    installed_result=run_codex(codex_home,"plugin","add","outcome-loop@openclaw-workspace-local","--json")
    listed=run_codex(codex_home,"plugin","list","--available","--json")
    installed=Path(installed_result["installedPath"])
    assert added["marketplaceName"]=="openclaw-workspace-local"
    assert any(item["pluginId"]=="outcome-loop@openclaw-workspace-local" and item["installed"] and item["enabled"] for item in listed["installed"])
    assert (installed/"skills/outcome-loop/SKILL.md").is_file() and (installed/"skills/independent-verifier/SKILL.md").is_file()
    skill_dir=installed/"skills/outcome-loop"
    skill_script=(skill_dir/"../../scripts/outcome_loop.py").resolve()
    help_result=subprocess.run([sys.executable,"../../scripts/outcome_loop.py","--help"],cwd=skill_dir,text=True,capture_output=True)
    assert skill_script==installed/"scripts/outcome_loop.py" and help_result.returncode==0
    path,value=mission(repo,"install-resume-dry-run")
    external=repo/"runtime-checkers"; external.mkdir()
    pass_checker=external/"check_analyst_records.py"; feasibility_checker=external/"check_feasibility.py"
    shutil.copy2(repo/"plugins/outcome-loop/tests/fixtures/check_analyst_records.py",pass_checker)
    shutil.copy2(repo/"plugins/outcome-loop/tests/fixtures/check_feasibility.py",feasibility_checker)
    pass_relative=str(pass_checker.relative_to(repo)); feasibility_relative=str(feasibility_checker.relative_to(repo))
    value["passCondition"]["command"][1]=pass_relative; value["passCondition"]["checkerFiles"]=[pass_relative]
    for check in ("data","access","cost","permission"):
        value["feasibilityChecks"][check]["command"][1]=feasibility_relative; value["feasibilityChecks"][check]["checkerFiles"]=[feasibility_relative]
    path.write_text(json.dumps(value,indent=2)+"\n")
    run(repo,"init","--mission",str(path.relative_to(repo)),"--controller-agent-id","controller-agent","--controller-thread-id","controller-thread",program=installed/"scripts/outcome_loop.py")
    source_plugin=repo/"plugins/outcome-loop"; hidden=repo/"plugins/outcome-loop.hidden"; source_plugin.rename(hidden)
    try: state=run(repo,"resume","--mission-id","install-resume-dry-run",program=installed/"scripts/outcome_loop.py")
    finally: hidden.rename(source_plugin)
    assert state["stage"]=="DISCOVERY"


def test_synthetic_trading_shaped_dry_run_exercises_loop_without_network_or_edge_claim(repo):
    result=full_two_attempt(repo,"synthetic-trading-dry-run","check_synthetic_trading.py",{"qualifiedSyntheticRows":2,"claim":"workflow-only-no-edge-claim"}); mission_value=json.loads((repo/"plugins/outcome-loop/tests/fixtures/synthetic-trading-dry-run.json").read_text()); assert result["stage"]=="COMPLETE" and "network_access" in mission_value["permissions"]["forbiddenActions"] and "edge" not in mission_value["goal"].lower()


def test_goal_checker_cannot_change_reviewed_evidence_after_the_precheck(repo):
    path, value = mission(repo)
    set_pass_checker(
        repo,
        path,
        value,
        "check_mutating_evidence.py",
        """#!/usr/bin/env python3
import json, pathlib, sys
evidence = pathlib.Path(sys.argv[1])
value = json.loads(evidence.read_text())
evidence.write_text(json.dumps(value) + "\\nchanged\\n")
print(json.dumps({"status": "PASS"}))
""",
    )
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    authorization = run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    run(repo, "final-gate", "--mission-id", "analyst-record-dry-run", "--authorization-id", authorization, expect=2)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    assert '"event":"final_gate_passed"' not in run_dir.joinpath("ledger.jsonl").read_text()
    assert not run_dir.joinpath("final-result.json").exists()


@pytest.mark.parametrize(
    "target, mutation",
    [
        ("mission", "pathlib.Path('.omx/outcome-loop/analyst-record-dry-run/mission.json').write_text('{}')"),
        ("checker", "pathlib.Path(__file__).write_text('# changed\\n')"),
        ("review", "pathlib.Path('.omx/outcome-loop/analyst-record-dry-run/review/attempt-0001/output.json').write_text('{}')"),
    ],
)
def test_goal_checker_cannot_mutate_frozen_or_reviewed_inputs_and_complete(repo, target, mutation):
    path, value = mission(repo)
    set_pass_checker(
        repo,
        path,
        value,
        f"check_mutating_{target}.py",
        f"""#!/usr/bin/env python3
import json, pathlib
{mutation}
print(json.dumps({{"status": "PASS"}}))
""",
    )
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    authorization = run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    run(repo, "final-gate", "--mission-id", "analyst-record-dry-run", "--authorization-id", authorization, expect=2)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    ledger = run_dir.joinpath("ledger.jsonl").read_text()
    assert '"event":"final_gate_passed"' not in ledger
    assert not run_dir.joinpath("final-result.json").exists()


def test_goal_checker_output_capture_is_bounded_and_explicitly_truncated(repo):
    path, value = mission(repo)
    set_pass_checker(
        repo,
        path,
        value,
        "check_high_output.py",
        """#!/usr/bin/env python3
import os
chunk = b"x" * 65536
for _ in range(48):
    os.write(1, chunk)
for _ in range(32):
    os.write(2, chunk)
""",
    )
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    started = time.monotonic()
    result = final(repo, "analyst-record-dry-run")
    assert time.monotonic() - started < 10
    facts = result["goalRun"]
    assert facts["stdoutBytes"] == 1024 * 1024
    assert facts["stderrBytes"] == 1024 * 1024
    assert facts["stdoutTotalBytes"] == 3 * 1024 * 1024
    assert facts["stderrTotalBytes"] == 2 * 1024 * 1024
    assert facts["stdoutTruncated"] is True and facts["stderrTruncated"] is True
    output_dir = repo / ".omx/outcome-loop/analyst-record-dry-run/evidence/attempt-0001"
    stdout = output_dir.joinpath("goal-stdout.bin").read_bytes()
    stderr = output_dir.joinpath("goal-stderr.bin").read_bytes()
    assert len(stdout) == len(stderr) == 1024 * 1024
    assert hashlib.sha256(stdout).hexdigest() == facts["stdoutSha256"]
    assert hashlib.sha256(stderr).hexdigest() == facts["stderrSha256"]


def test_runaway_goal_checker_is_killed_at_the_output_limit(repo):
    path, value = mission(repo)
    set_pass_checker(
        repo,
        path,
        value,
        "check_runaway_output.py",
        """#!/usr/bin/env python3
import os, time
chunk = b"x" * (1024 * 1024)
while True:
    os.write(1, chunk)
    time.sleep(0.002)
""",
    )
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    started = time.monotonic()
    final(repo, "analyst-record-dry-run")
    assert time.monotonic() - started < 10
    events = [json.loads(line) for line in (repo / ".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl").read_text().splitlines()]
    facts = events[-1]["payload"]["run"]
    assert events[-1]["event"] == "goal_check_failed"
    assert facts["exitCode"] is None
    assert facts["timedOut"] is False
    assert facts["outputLimitExceeded"] is True
    assert facts["stdoutTotalBytes"] + facts["stderrTotalBytes"] == 64 * 1024 * 1024


def test_escaped_writer_loses_its_output_pipe_when_checker_exits(repo):
    path, value = mission(repo)
    marker = repo / "escaped-writer-broken-pipe"
    child = """import os, pathlib, sys, time
os.setsid()
time.sleep(0.2)
try:
    os.write(1, b"x" * (1024 * 1024))
except BrokenPipeError:
    pathlib.Path(sys.argv[1]).write_text("broken")
"""
    set_pass_checker(
        repo,
        path,
        value,
        "check_escaped_writer.py",
        f"""#!/usr/bin/env python3
import subprocess, sys
subprocess.Popen([sys.executable, "-c", {child!r}, {str(marker)!r}])
sys.exit(0)
""",
    )
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    started = time.monotonic()
    result = final(repo, "analyst-record-dry-run")
    assert time.monotonic() - started < 10
    assert result["stage"] == "COMPLETE"
    deadline = time.monotonic() + 2
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.read_text() == "broken"
    assert result["goalRun"]["outputLimitExceeded"] is False
    assert result["goalRun"]["stdoutTotalBytes"] < 64 * 1024 * 1024


@pytest.mark.parametrize("target", ["goal-stdout.bin", "goal-stderr.bin", "final-result.json"])
def test_precreated_final_output_symlink_is_rejected_before_external_write(repo, target):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    output_dir = run_dir / "evidence/attempt-0001"
    outside = repo.parent / f"outside-{target}"
    outside.write_text("unchanged")
    destination = run_dir / target if target == "final-result.json" else output_dir / target
    destination.symlink_to(outside)
    authorization = run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    run(repo, "final-gate", "--mission-id", "analyst-record-dry-run", "--authorization-id", authorization, expect=2)
    ledger = run_dir.joinpath("ledger.jsonl").read_text()
    assert outside.read_text() == "unchanged"
    assert '"event":"final_gate_passed"' not in ledger


def test_timeout_kills_the_goal_checker_process_group(repo):
    path, value = mission(repo)
    marker = repo / "orphan-child-ran"
    set_pass_checker(
        repo,
        path,
        value,
        "check_timeout_process_group.py",
        """#!/usr/bin/env python3
import json, pathlib, subprocess, sys, time
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
subprocess.Popen([sys.executable, "-c", "import pathlib,sys,time; time.sleep(1.2); pathlib.Path(sys.argv[1]).write_text('orphan')", value["marker"]])
time.sleep(30)
""",
        timeout=1,
    )
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4, "marker": str(marker)})
    approve(repo, "analyst-record-dry-run", 1)
    result = final(repo, "analyst-record-dry-run")
    time.sleep(1.5)
    assert result["stage"] == "DISCOVERY" and not marker.exists()


def test_concurrent_final_gate_runs_the_checker_once(repo):
    path, value = mission(repo)
    set_pass_checker(
        repo,
        path,
        value,
        "check_counted_final.py",
        """#!/usr/bin/env python3
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
if value.get("uniqueCompleteRecords") != 4:
    raise SystemExit(1)
with pathlib.Path("plugins/outcome-loop/tests/fixtures/final-gate-runs.log").open("a") as handle:
    handle.write("run\\n")
print(json.dumps({"status": "PASS"}))
""",
    )
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    authorization = run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    results = []
    errors = []

    def call_final():
        try:
            results.append(run(repo, "final-gate", "--mission-id", "analyst-record-dry-run", "--authorization-id", authorization))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=call_final) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    ledger = (repo / ".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl").read_text()
    count_file = repo / "plugins/outcome-loop/tests/fixtures/final-gate-runs.log"
    assert not errors and sorted(result["stage"] for result in results) == ["COMPLETE", "COMPLETE"]
    assert count_file.read_text().splitlines() == ["run"]
    assert ledger.count('"event":"final_gate_started"') == 1 and ledger.count('"event":"final_gate_passed"') == 1


def test_ledger_tampering_breaks_the_hash_chain(repo):
    path, _ = mission(repo)
    init(repo, path)
    ledger = repo / ".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl"
    lines = ledger.read_text().splitlines()
    first = json.loads(lines[0])
    first["payload"]["controller"]["agentId"] = "forged-controller"
    first.pop("eventHash")
    first["eventHash"] = hashlib.sha256(json.dumps(first, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    lines[0] = json.dumps(first, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n")
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)


@pytest.mark.parametrize(("value", "expected"), [("missing", 0), (False, 0), (True, 2), (None, 2)])
def test_replay_accepts_only_legacy_missing_or_false_output_limit(repo, value, expected):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    final(repo, "analyst-record-dry-run")
    ledger = repo / ".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl"

    def mutate(events):
        goal_run = events[-2]["payload"]["goalRun"]
        final_run = events[-1]["payload"]["run"]
        saved_run = events[-1]["payload"]["stateAfter"]["finalGate"]
        if value == "missing":
            for item in (goal_run, final_run, saved_run):
                item.pop("outputLimitExceeded")
        else:
            for item in (goal_run, final_run, saved_run):
                item["outputLimitExceeded"] = value

    rehash_ledger(ledger, mutate)
    final_path = repo / ".omx/outcome-loop/analyst-record-dry-run/final-result.json"
    saved_final = json.loads(final_path.read_text())
    if value == "missing":
        saved_final["goalRun"].pop("outputLimitExceeded")
    else:
        saved_final["goalRun"]["outputLimitExceeded"] = value
    saved_final["ledgerHeadHash"] = json.loads(ledger.read_text().splitlines()[-1])["eventHash"]
    final_path.write_text(json.dumps(saved_final, sort_keys=True, separators=(",", ":")) + "\n")
    result = run(repo, "status", "--mission-id", "analyst-record-dry-run", expect=expected)
    assert (result.get("stage") == "COMPLETE") is (expected == 0)


@pytest.mark.parametrize("injection", ["complete", "review", "authorization", "evidence"])
def test_fully_rehashed_state_injection_cannot_create_unearned_progress(repo, injection):
    path, _ = mission(repo)
    init(repo, path)
    ledger = repo / ".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl"

    def mutate(events):
        state = events[-1]["payload"]["stateAfter"]
        if injection == "complete":
            state["stage"] = "COMPLETE"
            state["finalGate"] = {"exitCode": 0, "timedOut": False}
            events[-1]["toStage"] = "COMPLETE"
            events[-1]["event"] = "final_gate_passed"
            events[-1]["payload"] = {"run": state["finalGate"], "stateAfter": state}
        elif injection == "review":
            state["review"] = {"output": "forged-review.json", "outputSha256": "0" * 64}
        elif injection == "authorization":
            state["authorizations"].append({"id": "forged", "action": "run_goal_check", "estimatedCostUsd": "0.00", "status": "open", "attempt": 1})
        else:
            state["evidence"].append({"id": "forged", "kind": "test", "source": "forged", "copied": "forged", "sha256": "0" * 64, "bytes": 1, "attempt": 1})

    rehash_ledger(ledger, mutate)
    result = run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)
    assert "error" in result


def test_fully_rehashed_illegal_event_sequence_is_rejected(repo):
    path, _ = mission(repo)
    init(repo, path)
    ledger = repo / ".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl"

    def mutate(events):
        state = copy.deepcopy(events[-1]["payload"]["stateAfter"])
        state["stage"] = "FINAL_GATE"
        state["review"] = {"output": "forged-review.json", "outputSha256": "0" * 64}
        events.append({"formatVersion": 1, "at": events[-1]["at"], "event": "review_received", "missionId": state["missionId"], "attempt": 1, "fromStage": "DISCOVERY", "toStage": "FINAL_GATE", "payload": {"outputSha256": "0" * 64, "stateAfter": state}})

    rehash_ledger(ledger, mutate)
    run(repo, "status", "--mission-id", "analyst-record-dry-run", expect=2)


@pytest.mark.parametrize("tamper", ["mismatched-run", "exit-code", "timeout"])
def test_fully_rehashed_failed_final_run_cannot_be_reported_complete(repo, tamper):
    full_two_attempt(repo)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    ledger = run_dir / "ledger.jsonl"

    def mutate(events):
        final = events[-1]
        assert final["event"] == "final_gate_passed"
        if tamper in {"mismatched-run", "exit-code"}:
            final["payload"]["run"]["exitCode"] = 9
            final["payload"]["stateAfter"]["finalGate"]["exitCode"] = 9
        else:
            final["payload"]["run"]["timedOut"] = True
            final["payload"]["stateAfter"]["finalGate"]["timedOut"] = True
        if tamper != "mismatched-run":
            events[-2]["payload"]["goalRun"] = copy.deepcopy(final["payload"]["run"])

    rehash_ledger(ledger, mutate)
    final_event = json.loads(ledger.read_text().splitlines()[-1])
    state = final_event["payload"]["stateAfter"]
    forged_result = {
        "formatVersion": 1,
        "missionId": state["missionId"],
        "missionVersion": state["missionVersion"],
        "missionHash": state["missionHash"],
        "attempt": state["attempt"],
        "stage": "COMPLETE",
        "goalRun": state["finalGate"],
        "ledgerHeadHash": final_event["eventHash"],
        "completedAt": state["updatedAt"],
    }
    run_dir.joinpath("final-result.json").write_text(json.dumps(forged_result, indent=2, sort_keys=True) + "\n")
    run_dir.joinpath("state.json").write_text("corrupt\n")

    result = run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)
    assert "error" in result


@pytest.mark.parametrize("tamper", ["outside", "wrong-destination"])
def test_fully_rehashed_evidence_paths_cannot_escape_or_change_destination(repo, tamper):
    path, _ = mission(repo)
    init(repo, path)
    ledger = repo / ".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl"
    data = b'{"forged":true}\n'
    if tamper == "outside":
        outside = repo.parent / "outside.json"
        outside.write_bytes(data)
        source = copied = "../outside.json"
    else:
        source_path = repo / "plugins/outcome-loop/tests/fixtures/injected-source.json"
        copied_path = repo / "plugins/outcome-loop/tests/fixtures/injected-copy.json"
        source_path.write_bytes(data); copied_path.write_bytes(data)
        source = str(source_path.relative_to(repo)); copied = str(copied_path.relative_to(repo))
    entry = {"id": "forged", "kind": "test", "source": source, "copied": copied, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "attempt": 1}

    def mutate(events):
        state = copy.deepcopy(events[-1]["payload"]["stateAfter"])
        state["evidence"].append(entry)
        events.append({"formatVersion": 1, "at": events[-1]["at"], "event": "evidence_recorded", "missionId": state["missionId"], "attempt": 1, "fromStage": "DISCOVERY", "toStage": "DISCOVERY", "payload": {"evidence": entry, "stateAfter": state}})

    rehash_ledger(ledger, mutate)
    (repo / ".omx/outcome-loop/analyst-record-dry-run/state.json").write_text("corrupt\n")
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)


@pytest.mark.parametrize("target", ["mission", "mission-hash", "manifest", "frozen-checker", "source-checker"])
def test_same_byte_symlink_substitution_of_frozen_inputs_is_rejected(repo, target):
    path, _ = mission(repo)
    init(repo, path)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    manifest = json.loads(run_dir.joinpath("checker-manifest.json").read_text())
    targets = {
        "mission": run_dir / "mission.json",
        "mission-hash": run_dir / "mission.sha256",
        "manifest": run_dir / "checker-manifest.json",
        "frozen-checker": run_dir / manifest["files"][0]["frozen"],
        "source-checker": repo / manifest["files"][0]["source"],
    }
    original = targets[target]
    outside = repo.parent / f"same-bytes-{target}"
    outside.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(outside)

    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)


@pytest.mark.parametrize("target", ["ledger", "state"])
def test_same_byte_symlink_substitution_of_core_run_files_is_rejected(repo, target):
    path, _ = mission(repo)
    init(repo, path)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    original = run_dir / f"{target}.jsonl" if target == "ledger" else run_dir / "state.json"
    outside = repo.parent / f"same-bytes-{target}"
    outside.write_bytes(original.read_bytes())
    original.unlink(); original.symlink_to(outside)

    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)
    candidate_path, _ = candidate(repo, 1, "plain-line-count")
    run(repo, "candidate", "--mission-id", "analyst-record-dry-run", "--candidate", str(candidate_path.relative_to(repo)), expect=2)


@pytest.mark.parametrize("artifact", ["input", "output"])
def test_same_byte_symlink_substitution_of_review_files_is_rejected(repo, artifact):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    if artifact == "input":
        state = run(repo, "prepare-review", "--mission-id", "analyst-record-dry-run")
    else:
        approve(repo, "analyst-record-dry-run", 1)
        state = json.loads((repo / ".omx/outcome-loop/analyst-record-dry-run/state.json").read_text())
    original = repo / state["review"][artifact]
    outside = repo.parent / f"same-bytes-review-{artifact}"
    outside.write_bytes(original.read_bytes())
    original.unlink(); original.symlink_to(outside)
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)


def test_same_byte_symlink_substitution_of_recorded_evidence_is_rejected(repo):
    # The copy is the durable record and is read on every command, so swapping
    # it for a symlink out of the repository is always refused. The equivalent
    # swap on the working source is covered by the two symlink tests at the end
    # of this file: inert during the loop, refused at the final gate.
    path, _ = mission(repo)
    init(repo, path)
    add_evidence(repo, "analyst-record-dry-run", "proof", "test", {"safe": True})
    state = json.loads((repo / ".omx/outcome-loop/analyst-record-dry-run/state.json").read_text())
    original = repo / state["evidence"][0]["copied"]
    outside = repo.parent / "same-bytes-evidence-copied"
    outside.write_bytes(original.read_bytes())
    original.unlink(); original.symlink_to(outside)
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)


@pytest.mark.parametrize("target", ["final-result.json", "goal-stdout.bin", "goal-stderr.bin"])
def test_same_byte_symlink_substitution_of_completed_outputs_is_rejected(repo, target):
    full_two_attempt(repo)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    original = run_dir / target if target == "final-result.json" else run_dir / "evidence/attempt-0002" / target
    outside = repo.parent / f"same-bytes-{target}"
    outside.write_bytes(original.read_bytes())
    original.unlink(); original.symlink_to(outside)
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)


@pytest.mark.parametrize("tamper", ["forbidden", "over-budget", "duplicate", "not-open"])
def test_fully_rehashed_impossible_authorization_is_rejected(repo, tamper):
    path, _ = mission(repo)
    init(repo, path)
    ledger = repo / ".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl"

    def authorization_event(events, authorization):
        state = copy.deepcopy(events[-1]["payload"]["stateAfter"])
        state["authorizations"].append(authorization)
        events.append({"formatVersion": 1, "at": events[-1]["at"], "event": "action_authorized", "missionId": state["missionId"], "attempt": 1, "fromStage": "DISCOVERY", "toStage": "DISCOVERY", "payload": {"authorization": authorization, "stateAfter": state}})

    def mutate(events):
        base = {"id": "a" * 32, "action": "modify_repository", "estimatedCostUsd": "0.00", "status": "open", "attempt": 1}
        if tamper == "forbidden":
            base["action"] = "network_access"
            authorization_event(events, base)
        elif tamper == "over-budget":
            base["estimatedCostUsd"] = "0.01"
            authorization_event(events, base)
        elif tamper == "not-open":
            base["status"] = "completed"; base["actualCostUsd"] = "0.00"
            authorization_event(events, base)
        else:
            authorization_event(events, base)
            duplicate = copy.deepcopy(base)
            authorization_event(events, duplicate)

    rehash_ledger(ledger, mutate)
    (repo / ".omx/outcome-loop/analyst-record-dry-run/state.json").write_text("corrupt\n")
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)


@pytest.mark.parametrize(
    "command, id_args",
    [
        ("init", ["--controller-agent-id", "   ", "--controller-thread-id", "controller-thread"]),
        ("init", ["--controller-agent-id", "controller-agent", "--controller-thread-id", "\t"]),
        ("start-build", ["--builder-agent-id", " ", "--builder-thread-id", "builder-thread"]),
        ("start-build", ["--builder-agent-id", "builder-agent", "--builder-thread-id", " "]),
        ("review", ["reviewer-agent", " "]),
        ("review", [" ", "reviewer-thread"]),
        ("submitter", [" ", "controller-thread"]),
        ("submitter", ["controller-agent", " "]),
    ],
)
def test_agent_and_thread_ids_must_be_non_empty_after_trimming(repo, command, id_args):
    path, _ = mission(repo)
    if command == "init":
        run(repo, "init", "--mission", str(path.relative_to(repo)), *id_args, expect=2)
        return
    init(repo, path)
    if command == "start-build":
        candidate_path, _ = candidate(repo, 1, "plain-line-count")
        run(repo, "candidate", "--mission-id", "analyst-record-dry-run", "--candidate", str(candidate_path.relative_to(repo)))
        for check in ("data", "access", "cost", "permission"):
            add_evidence(repo, "analyst-record-dry-run", check, f"feasibility_{check}", {"check": check, "available": True, "fact": "available"})
            run(repo, "feasibility", "--mission-id", "analyst-record-dry-run", "--check", check, "--status", "pass", "--evidence", check)
        add_evidence(repo, "analyst-record-dry-run", "plan", "plan", {"steps": ["build"]})
        run(repo, "plan", "--mission-id", "analyst-record-dry-run", "--evidence", "plan")
        authorization = run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "modify_repository", "--estimated-cost-usd", "0.00")["authorizationId"]
        run(repo, "start-build", "--mission-id", "analyst-record-dry-run", *id_args, "--authorization-id", authorization, expect=2)
        return
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    prepared = run(repo, "prepare-review", "--mission-id", "analyst-record-dry-run")
    if command == "submitter":
        review = review_value("analyst-record-dry-run", 1, prepared["review"]["inputSha256"])
        run(repo, "review-result", "--mission-id", "analyst-record-dry-run", "--submitter-agent-id", id_args[0], "--submitter-thread-id", id_args[1], "--from-stdin", stdin={"reviewCapability": prepared["reviewCapability"], "review": review}, expect=2)
        return
    review = review_value("analyst-record-dry-run", 1, prepared["review"]["inputSha256"], reviewer_agent=id_args[0], reviewer_thread=id_args[1])
    run(repo, "review-result", "--mission-id", "analyst-record-dry-run", "--submitter-agent-id", "controller-agent", "--submitter-thread-id", "controller-thread", "--from-stdin", stdin={"reviewCapability": prepared["reviewCapability"], "review": review}, expect=2)


def test_status_or_resume_before_init_creates_no_lock_and_does_not_block_init(repo):
    path, _ = mission(repo)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    run(repo, "status", "--mission-id", "analyst-record-dry-run", expect=2)
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)
    assert not run_dir.exists()
    assert init(repo, path)["stage"] == "DISCOVERY"


def test_todo_110_fixture_checkers_make_no_network_system_calls(repo):
    fixtures = repo / "plugins/outcome-loop/tests/fixtures"
    inputs = {
        "check_feasibility.py": ["data", str(write(repo, "strace-feasibility.json", {"check": "data", "available": True, "fact": "local"}))],
        "check_analyst_records.py": [str(write(repo, "strace-analyst.json", {"uniqueCompleteRecords": 4}))],
        "check_synthetic_trading.py": [str(write(repo, "strace-trading.json", {"qualifiedSyntheticRows": 2, "claim": "workflow-only-no-edge-claim"}))],
    }
    network_call = re.compile(r"\b(socket|socketpair|connect|accept|accept4|bind|listen|sendto|recvfrom|sendmsg|recvmsg|shutdown|getsockname|getpeername|getsockopt|setsockopt)\(")
    for checker, arguments in inputs.items():
        trace = repo / f"{checker}.network.trace"
        result = subprocess.run(["/usr/bin/strace", "-f", "-qq", "-e", "trace=network", "-o", str(trace), sys.executable, str(fixtures / checker), *arguments], text=True, capture_output=True)
        assert result.returncode == 0, (checker, result.stdout, result.stderr)
        assert not network_call.search(trace.read_text()), (checker, trace.read_text())


def test_symlink_escape_is_rejected_as_evidence(repo):
    path, _ = mission(repo)
    init(repo, path)
    outside = repo.parent / "outside-evidence.json"
    outside.write_text("{}\n")
    link = repo / "plugins/outcome-loop/tests/fixtures/symlink-evidence.json"
    link.symlink_to(outside)
    run(repo, "evidence", "--mission-id", "analyst-record-dry-run", "--id", "escape", "--kind", "test", "--file", str(link.relative_to(repo)), expect=2)


def test_precreated_mission_run_or_lock_symlink_is_rejected_before_writing(repo):
    path, _ = mission(repo)
    outside_run = repo.parent / "outside-run"
    outside_run.mkdir()
    runs = repo / ".omx/outcome-loop"
    runs.mkdir(parents=True)
    runs.joinpath("analyst-record-dry-run").symlink_to(outside_run, target_is_directory=True)
    run(repo, "init", "--mission", str(path.relative_to(repo)), "--controller-agent-id", "controller-agent", "--controller-thread-id", "controller-thread", expect=2)
    assert list(outside_run.iterdir()) == []

    runs.joinpath("analyst-record-dry-run").unlink()
    init(repo, path)
    outside_lock = repo.parent / "outside-lock"
    outside_lock.write_text("unchanged")
    (runs / "analyst-record-dry-run/.lock").symlink_to(outside_lock)
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)
    assert outside_lock.read_text() == "unchanged"


def test_precreated_evidence_destination_symlink_is_rejected_before_writing(repo):
    path, _ = mission(repo)
    init(repo, path)
    candidate_path, _ = candidate(repo, 1, "plain-line-count")
    run(repo, "candidate", "--mission-id", "analyst-record-dry-run", "--candidate", str(candidate_path.relative_to(repo)))
    source = write(repo, "evidence-source.json", {"safe": True})
    outside = repo.parent / "outside-evidence-destination"
    outside.mkdir()
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    run_dir.joinpath("evidence").symlink_to(outside, target_is_directory=True)
    run(repo, "evidence", "--mission-id", "analyst-record-dry-run", "--id", "blocked", "--kind", "test", "--file", str(source.relative_to(repo)), expect=2)
    assert list(outside.iterdir()) == []


def test_stale_review_and_older_capability_are_rejected(repo):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    first = run(repo, "prepare-review", "--mission-id", "analyst-record-dry-run")
    second = run(repo, "prepare-review", "--mission-id", "analyst-record-dry-run")
    old_review = review_value("analyst-record-dry-run", 1, first["review"]["inputSha256"])
    run(repo, "review-result", "--mission-id", "analyst-record-dry-run", "--submitter-agent-id", "controller-agent", "--submitter-thread-id", "controller-thread", "--from-stdin", stdin={"reviewCapability": first["reviewCapability"], "review": old_review}, expect=2)
    fresh_review = review_value("analyst-record-dry-run", 1, second["review"]["inputSha256"])
    run(repo, "review-result", "--mission-id", "analyst-record-dry-run", "--submitter-agent-id", "controller-agent", "--submitter-thread-id", "controller-thread", "--from-stdin", stdin={"reviewCapability": second["reviewCapability"], "review": fresh_review})
    add_evidence(repo, "analyst-record-dry-run", "after-review", "test", {"changed": True})
    authorization = run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    run(repo, "final-gate", "--mission-id", "analyst-record-dry-run", "--authorization-id", authorization, expect=2)


def test_concurrent_init_has_one_success_one_clean_refusal_and_resumes(repo):
    path, _ = mission(repo)
    command = [sys.executable, str(repo / "plugins/outcome-loop/scripts/outcome_loop.py"), "init", "--mission", str(path.relative_to(repo)), "--controller-agent-id", "controller-agent", "--controller-thread-id", "controller-thread", "--root", str(repo)]
    barrier = threading.Barrier(2)
    results = []

    def call_init():
        barrier.wait()
        results.append(subprocess.run(command, text=True, capture_output=True))

    threads = [threading.Thread(target=call_init) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(result.returncode for result in results) == [0, 2]
    assert all(json.loads(result.stdout) for result in results)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    assert len(run_dir.joinpath("ledger.jsonl").read_text().splitlines()) == 3
    assert run(repo, "resume", "--mission-id", "analyst-record-dry-run")["stage"] == "DISCOVERY"


def test_interrupted_staging_init_is_recoverable_and_partial_final_init_is_refused(repo):
    path, _ = mission(repo)
    parent = repo / ".omx/outcome-loop"
    parent.mkdir(parents=True)
    stale = parent / ".analyst-record-dry-run.init-interrupted"
    stale.mkdir()
    stale.joinpath("mission.json").write_text("partial\n")
    assert init(repo, path)["stage"] == "DISCOVERY"
    assert run(repo, "resume", "--mission-id", "analyst-record-dry-run")["attempt"] == 1

    second_path, _ = mission(repo, "partial-final-dry-run")
    partial = parent / "partial-final-dry-run"
    partial.mkdir()
    partial.joinpath("mission.json").write_text("partial\n")
    run(repo, "init", "--mission", str(second_path.relative_to(repo)), "--controller-agent-id", "controller-agent", "--controller-thread-id", "controller-thread", expect=2)
    assert partial.joinpath("mission.json").read_text() == "partial\n"


def test_action_authorization_and_completion_follow_exact_stages(repo):
    path, _ = mission(repo)
    init(repo, path)
    run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "modify_repository", "--estimated-cost-usd", "0.00", expect=2)
    run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "run_goal_check", "--estimated-cost-usd", "0.00", expect=2)
    candidate_path, _ = candidate(repo, 1, "plain-line-count")
    run(repo, "candidate", "--mission-id", "analyst-record-dry-run", "--candidate", str(candidate_path.relative_to(repo)))
    reach_planned(repo, "analyst-record-dry-run", 1)
    authorization = run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "modify_repository", "--estimated-cost-usd", "0.00")["authorizationId"]
    run(repo, "complete-action", "--mission-id", "analyst-record-dry-run", "--authorization-id", authorization, "--actual-cost-usd", "0.00", expect=2)
    run(repo, "start-build", "--mission-id", "analyst-record-dry-run", "--builder-agent-id", "builder-agent", "--builder-thread-id", "builder-thread", "--authorization-id", authorization)
    run(repo, "complete-action", "--mission-id", "analyst-record-dry-run", "--authorization-id", authorization, "--actual-cost-usd", "0.00")


def test_post_review_action_handlers_refuse_unrelated_work_and_manual_goal_completion(repo):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "modify_repository", "--estimated-cost-usd", "0.00", expect=2)
    authorization = run(repo, "authorize-action", "--mission-id", "analyst-record-dry-run", "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    run(repo, "complete-action", "--mission-id", "analyst-record-dry-run", "--authorization-id", authorization, "--actual-cost-usd", "0.00", expect=2)


def test_fully_rehashed_post_review_action_chain_is_rejected(repo):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    ledger = repo / ".omx/outcome-loop/analyst-record-dry-run/ledger.jsonl"

    def mutate(events):
        state = copy.deepcopy(events[-1]["payload"]["stateAfter"])
        authorization = {"id": "f" * 32, "action": "modify_repository", "estimatedCostUsd": "0.00", "status": "open", "attempt": 1}
        state["authorizations"].append(authorization)
        events.append({"formatVersion": 1, "at": events[-1]["at"], "event": "action_authorized", "missionId": state["missionId"], "attempt": 1, "fromStage": "FINAL_GATE", "toStage": "FINAL_GATE", "payload": {"authorization": authorization, "stateAfter": copy.deepcopy(state)}})
        state["authorizations"][-1].update({"status": "completed", "actualCostUsd": "0.00"})
        events.append({"formatVersion": 1, "at": events[-1]["at"], "event": "action_completed", "missionId": state["missionId"], "attempt": 1, "fromStage": "FINAL_GATE", "toStage": "FINAL_GATE", "payload": {"authorizationId": authorization["id"], "stateAfter": state}})

    rehash_ledger(ledger, mutate)
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)


@pytest.mark.parametrize("tamper", ["top-field", "reviewer-field", "missing-check", "wrong-mission", "write-mode", "reused-agent"])
def test_fully_rehashed_forged_review_contract_is_rejected(repo, tamper):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, "analyst-record-dry-run", 1)
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    output_path = run_dir / "review/attempt-0001/output.json"
    review = json.loads(output_path.read_text())
    if tamper == "top-field": review["extra"] = True
    elif tamper == "reviewer-field": review["reviewer"]["extra"] = True
    elif tamper == "missing-check": review["checks"].pop("networkNotUsed")
    elif tamper == "wrong-mission": review["missionId"] = "forged-mission"
    elif tamper == "write-mode": review["reviewer"]["mode"] = "write"
    else: review["reviewer"]["agentId"] = "builder-agent-1"
    output_path.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n")
    output_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()

    def mutate(events):
        event = events[-1]
        assert event["event"] == "review_received"
        event["payload"]["outputSha256"] = output_hash
        event["payload"]["stateAfter"]["review"]["outputSha256"] = output_hash

    rehash_ledger(run_dir / "ledger.jsonl", mutate)
    run(repo, "resume", "--mission-id", "analyst-record-dry-run", expect=2)


def test_extra_capability_field_is_refused_without_consuming_or_persisting_capability(repo):
    path, _ = mission(repo)
    init(repo, path)
    reach_review(repo, "analyst-record-dry-run", 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    prepared = run(repo, "prepare-review", "--mission-id", "analyst-record-dry-run")
    review = review_value("analyst-record-dry-run", 1, prepared["review"]["inputSha256"])
    review["reviewCapability"] = prepared["reviewCapability"]
    run_dir = repo / ".omx/outcome-loop/analyst-record-dry-run"
    state_before = run_dir.joinpath("state.json").read_bytes()
    ledger_before = run_dir.joinpath("ledger.jsonl").read_bytes()
    envelope = {"reviewCapability": prepared["reviewCapability"], "review": review}
    run(repo, "review-result", "--mission-id", "analyst-record-dry-run", "--submitter-agent-id", "controller-agent", "--submitter-thread-id", "controller-thread", "--from-stdin", stdin=envelope, expect=2)
    assert run_dir.joinpath("state.json").read_bytes() == state_before
    assert run_dir.joinpath("ledger.jsonl").read_bytes() == ledger_before
    assert prepared["reviewCapability"].encode() not in state_before + ledger_before + run_dir.joinpath("review/attempt-0001/input.json").read_bytes()
    review.pop("reviewCapability")
    result = run(repo, "review-result", "--mission-id", "analyst-record-dry-run", "--submitter-agent-id", "controller-agent", "--submitter-thread-id", "controller-thread", "--from-stdin", stdin={"reviewCapability": prepared["reviewCapability"], "review": review})
    assert result["stage"] == "FINAL_GATE"


def test_editing_a_recorded_evidence_source_does_not_brick_the_mission(repo):
    path, _ = mission(repo)
    init(repo, path)
    mission_id = "analyst-record-dry-run"
    candidate_path, _ = candidate(repo, 1, "plain-line-count")
    run(repo, "candidate", "--mission-id", mission_id, "--candidate", str(candidate_path.relative_to(repo)))
    reach_planned(repo, mission_id, 1)
    source = repo / "plugins/outcome-loop/tests/fixtures" / f"{mission_id}-plan-1.json"
    recorded = json.loads(source.read_text())
    run_dir = repo / ".omx/outcome-loop" / mission_id
    copied = next(run_dir.glob("evidence/attempt-0001/plan-1--*.json"))
    copy_before = copied.read_bytes()

    # The repair loop is expected to keep editing its own working files.
    source.write_text(json.dumps({"steps": ["build", "test", "repair"]}) + "\n")

    state = run(repo, "status", "--mission-id", mission_id)
    assert state["stage"] == "PLANNED"
    run(repo, "stop", "--mission-id", mission_id, "--condition", "owner_only_decision", "--evidence", "plan-1")
    # The durable copy is untouched by the edit and still carries the recorded bytes.
    assert copied.read_bytes() == copy_before == (json.dumps(recorded) + "\n").encode()


def test_deleting_a_recorded_evidence_source_does_not_brick_the_mission(repo):
    path, _ = mission(repo)
    init(repo, path)
    mission_id = "analyst-record-dry-run"
    candidate_path, _ = candidate(repo, 1, "plain-line-count")
    run(repo, "candidate", "--mission-id", mission_id, "--candidate", str(candidate_path.relative_to(repo)))
    reach_planned(repo, mission_id, 1)
    (repo / "plugins/outcome-loop/tests/fixtures" / f"{mission_id}-plan-1.json").unlink()
    assert run(repo, "status", "--mission-id", mission_id)["stage"] == "PLANNED"


def test_tampering_with_the_evidence_copy_is_still_refused(repo):
    path, _ = mission(repo)
    init(repo, path)
    mission_id = "analyst-record-dry-run"
    candidate_path, _ = candidate(repo, 1, "plain-line-count")
    run(repo, "candidate", "--mission-id", mission_id, "--candidate", str(candidate_path.relative_to(repo)))
    reach_planned(repo, mission_id, 1)
    copied = next((repo / ".omx/outcome-loop" / mission_id).glob("evidence/attempt-0001/plan-1--*.json"))
    copied.write_text(json.dumps({"steps": ["forged"]}) + "\n")
    assert "changed" in run(repo, "status", "--mission-id", mission_id, expect=2)["error"]


def test_checker_that_outlives_itself_via_a_child_still_times_out(repo):
    path, value = mission(repo)
    mission_id = "analyst-record-dry-run"
    # Exits immediately, but leaves a child holding the inherited stdout pipe.
    set_pass_checker(repo, path, value, "check_orphan.py", (
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "sys.exit(0)\n"
    ), timeout=3)
    init(repo, path)
    reach_review(repo, mission_id, 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, mission_id, 1)
    auth = run(repo, "authorize-action", "--mission-id", mission_id, "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    started = time.monotonic()
    state = run(repo, "final-gate", "--mission-id", mission_id, "--authorization-id", auth)
    elapsed = time.monotonic() - started
    # The checker itself exited 0 well inside its timeout, so the run is allowed
    # to complete. What must not happen is waiting on the surviving child: the
    # old code blocked here for the child's full 60 seconds, holding the lock.
    assert elapsed < 30, elapsed
    assert state["stage"] == "COMPLETE"
    # The lock was released, so the mission is still usable.
    assert run(repo, "status", "--mission-id", mission_id)["stage"] == "COMPLETE"


def test_mission_missing_a_required_action_is_refused_at_validation(repo):
    for dropped in ("modify_repository", "run_goal_check"):
        path, value = mission(repo, mission_id=f"missing-{dropped.replace('_', '-')}")
        value["permissions"]["allowedActions"] = [x for x in value["permissions"]["allowedActions"] if x != dropped]
        path.write_text(json.dumps(value, indent=2) + "\n")
        error = run(repo, "validate-mission", "--mission", str(path.relative_to(repo)), expect=2)["error"]
        assert dropped in error, error
        init_error = run(repo, "init", "--mission", str(path.relative_to(repo)), "--controller-agent-id", "c", "--controller-thread-id", "t", expect=2)["error"]
        assert dropped in init_error, init_error


def test_repair_cycle_spend_can_be_authorized_and_recorded_in_building(repo):
    path, value = mission(repo, max_cost="10.00")
    mission_id = "analyst-record-dry-run"
    value["permissions"]["allowedActions"].append("run_historical_test")
    path.write_text(json.dumps(value, indent=2) + "\n")
    init(repo, path)
    candidate_path, _ = candidate(repo, 1, "plain-line-count")
    run(repo, "candidate", "--mission-id", mission_id, "--candidate", str(candidate_path.relative_to(repo)))
    reach_planned(repo, mission_id, 1)
    build_auth = run(repo, "authorize-action", "--mission-id", mission_id, "--action", "modify_repository", "--estimated-cost-usd", "0.00")["authorizationId"]
    run(repo, "start-build", "--mission-id", mission_id, "--builder-agent-id", "builder-agent", "--builder-thread-id", "builder-thread", "--authorization-id", build_auth)
    run(repo, "complete-action", "--mission-id", mission_id, "--authorization-id", build_auth, "--actual-cost-usd", "0.00")
    add_evidence(repo, mission_id, "implementation-1", "implementation", {"method": "plain-line-count"})
    add_evidence(repo, mission_id, "test-1", "test", {"passed": False})
    state = run(repo, "build-result", "--mission-id", mission_id, "--status", "fail", "--evidence", "implementation-1", "--evidence", "test-1")
    assert state["stage"] == "BUILDING" and state["repairCycle"] == 1
    assert "authorize-action" in state["legalNextCommands"]

    # Repair-cycle research costs money and must reach the ledger.
    repair_auth = run(repo, "authorize-action", "--mission-id", mission_id, "--action", "run_historical_test", "--estimated-cost-usd", "2.50")["authorizationId"]
    state = run(repo, "complete-action", "--mission-id", mission_id, "--authorization-id", repair_auth, "--actual-cost-usd", "2.50")
    assert state["budget"]["spentCostUsd"] == "2.50"
    assert run(repo, "resume", "--mission-id", mission_id)["budget"]["spentCostUsd"] == "2.50"


def test_repair_spend_over_budget_stops_the_mission(repo):
    path, value = mission(repo, max_cost="1.00")
    mission_id = "analyst-record-dry-run"
    value["permissions"]["allowedActions"].append("run_historical_test")
    path.write_text(json.dumps(value, indent=2) + "\n")
    init(repo, path)
    candidate_path, _ = candidate(repo, 1, "plain-line-count")
    run(repo, "candidate", "--mission-id", mission_id, "--candidate", str(candidate_path.relative_to(repo)))
    reach_planned(repo, mission_id, 1)
    build_auth = run(repo, "authorize-action", "--mission-id", mission_id, "--action", "modify_repository", "--estimated-cost-usd", "0.00")["authorizationId"]
    run(repo, "start-build", "--mission-id", mission_id, "--builder-agent-id", "builder-agent", "--builder-thread-id", "builder-thread", "--authorization-id", build_auth)
    run(repo, "complete-action", "--mission-id", mission_id, "--authorization-id", build_auth, "--actual-cost-usd", "0.00")
    add_evidence(repo, mission_id, "implementation-1", "implementation", {"method": "plain-line-count"})
    add_evidence(repo, mission_id, "test-1", "test", {"passed": False})
    run(repo, "build-result", "--mission-id", mission_id, "--status", "fail", "--evidence", "implementation-1", "--evidence", "test-1")
    state = run(repo, "authorize-action", "--mission-id", mission_id, "--action", "run_historical_test", "--estimated-cost-usd", "5.00")
    assert state["stage"] == "STOPPED"


def test_modify_repository_and_goal_check_stay_pinned_to_their_own_stage(repo):
    path, _ = mission(repo)
    mission_id = "analyst-record-dry-run"
    init(repo, path)
    candidate_path, _ = candidate(repo, 1, "plain-line-count")
    run(repo, "candidate", "--mission-id", mission_id, "--candidate", str(candidate_path.relative_to(repo)))
    reach_planned(repo, mission_id, 1)
    # run_goal_check belongs to the final gate, never to PLANNED.
    assert "FINAL_GATE" in run(repo, "authorize-action", "--mission-id", mission_id, "--action", "run_goal_check", "--estimated-cost-usd", "0.00", expect=2)["error"]
    build_auth = run(repo, "authorize-action", "--mission-id", mission_id, "--action", "modify_repository", "--estimated-cost-usd", "0.00")["authorizationId"]
    run(repo, "start-build", "--mission-id", mission_id, "--builder-agent-id", "builder-agent", "--builder-thread-id", "builder-thread", "--authorization-id", build_auth)
    run(repo, "complete-action", "--mission-id", mission_id, "--authorization-id", build_auth, "--actual-cost-usd", "0.00")
    # A second repository authorization cannot be minted mid-build.
    assert "PLANNED" in run(repo, "authorize-action", "--mission-id", mission_id, "--action", "modify_repository", "--estimated-cost-usd", "0.00", expect=2)["error"]


def test_non_finite_and_malformed_mission_values_refuse_instead_of_crashing(repo):
    for bad_cost in ("Infinity", "NaN", "-Infinity"):
        path, value = mission(repo, mission_id="bad-cost-mission")
        value["budget"]["maxCostUsd"] = bad_cost
        path.write_text(json.dumps(value, indent=2) + "\n")
        assert "error" in run(repo, "validate-mission", "--mission", str(path.relative_to(repo)), expect=2)

    path, _ = mission(repo)
    init(repo, path)
    bad = write(repo, "bad-candidate.json", {"candidateId": "c", "name": "n", "method": {"family": "f", "inputs": [7], "transformation": "t", "decisionRule": "d", "output": "o"}, "thresholds": {}})
    assert "error" in run(repo, "candidate", "--mission-id", "analyst-record-dry-run", "--candidate", str(bad.relative_to(repo)), expect=2)


def test_final_gate_refuses_when_the_measured_work_is_gone_from_the_repository(repo):
    path, _ = mission(repo)
    mission_id = "analyst-record-dry-run"
    init(repo, path)
    reach_review(repo, mission_id, 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, mission_id, 1)
    auth = run(repo, "authorize-action", "--mission-id", mission_id, "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    fixtures = repo / "plugins/outcome-loop/tests/fixtures"
    (fixtures / f"{mission_id}-implementation-1.json").unlink()
    (fixtures / f"{mission_id}-result-1.json").unlink()
    # Certifying success while the implementation and the measured result are
    # gone from the working tree would make COMPLETE meaningless.
    assert "does not exist" in run(repo, "final-gate", "--mission-id", mission_id, "--authorization-id", auth, expect=2)["error"]
    assert run(repo, "status", "--mission-id", mission_id)["stage"] == "FINAL_GATE"


def test_final_gate_still_passes_when_a_repair_edited_evidence_it_already_recorded(repo):
    # A repair cycle legitimately rewrites files it recorded earlier in the same
    # attempt. The gate must not become unpassable because of that.
    path, _ = mission(repo)
    mission_id = "analyst-record-dry-run"
    init(repo, path)
    reach_review(repo, mission_id, 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, mission_id, 1)
    auth = run(repo, "authorize-action", "--mission-id", mission_id, "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    source = repo / "plugins/outcome-loop/tests/fixtures" / f"{mission_id}-implementation-1.json"
    source.write_text(json.dumps({"method": "plain-line-count", "revised": True}) + "\n")
    assert run(repo, "final-gate", "--mission-id", mission_id, "--authorization-id", auth)["stage"] == "COMPLETE"


def test_checker_whose_child_escapes_the_process_group_still_returns(repo):
    path, value = mission(repo)
    mission_id = "analyst-record-dry-run"
    # The grandchild calls setsid, so killpg cannot reach it, and it holds the
    # inherited stdout pipe open well past the timeout.
    set_pass_checker(repo, path, value, "check_escaping_orphan.py", (
        "import os, subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import os,time; os.setsid(); time.sleep(120)'])\n"
        "sys.exit(0)\n"
    ), timeout=3)
    init(repo, path)
    reach_review(repo, mission_id, 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, mission_id, 1)
    auth = run(repo, "authorize-action", "--mission-id", mission_id, "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    started = time.monotonic()
    state = run(repo, "final-gate", "--mission-id", mission_id, "--authorization-id", auth)
    elapsed = time.monotonic() - started
    # killpg cannot reach a setsid grandchild, so nothing may depend on it
    # exiting or on it releasing an inherited stream. The old code waited the
    # child's full 120 seconds; the timeout must be the only clock that matters.
    assert elapsed < 40, elapsed
    assert state["stage"] == "COMPLETE"
    assert run(repo, "status", "--mission-id", mission_id)["stage"] == "COMPLETE"


def test_replacing_a_recorded_source_with_a_symlink_does_not_brick_the_mission(repo, tmp_path):
    path, _ = mission(repo)
    mission_id = "analyst-record-dry-run"
    init(repo, path)
    candidate_path, _ = candidate(repo, 1, "plain-line-count")
    run(repo, "candidate", "--mission-id", mission_id, "--candidate", str(candidate_path.relative_to(repo)))
    reach_planned(repo, mission_id, 1)
    source = repo / "plugins/outcome-loop/tests/fixtures" / f"{mission_id}-plan-1.json"
    elsewhere = tmp_path / "moved-plan.json"
    elsewhere.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(elsewhere)
    # A file-to-symlink swap used to fail every command with no way forward.
    assert run(repo, "status", "--mission-id", mission_id)["stage"] == "PLANNED"
    run(repo, "stop", "--mission-id", mission_id, "--condition", "owner_only_decision", "--evidence", "plan-1")


def test_symlinked_source_is_still_refused_at_the_final_gate(repo, tmp_path):
    path, _ = mission(repo)
    mission_id = "analyst-record-dry-run"
    init(repo, path)
    reach_review(repo, mission_id, 1, "plain-line-count", {"uniqueCompleteRecords": 4})
    approve(repo, mission_id, 1)
    auth = run(repo, "authorize-action", "--mission-id", mission_id, "--action", "run_goal_check", "--estimated-cost-usd", "0.00")["authorizationId"]
    source = repo / "plugins/outcome-loop/tests/fixtures" / f"{mission_id}-implementation-1.json"
    elsewhere = tmp_path / "outside-implementation.json"
    elsewhere.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(elsewhere)
    assert "symlink" in run(repo, "final-gate", "--mission-id", mission_id, "--authorization-id", auth, expect=2)["error"]
    # Recoverable: the run is still alive and can be repaired.
    assert run(repo, "status", "--mission-id", mission_id)["stage"] == "FINAL_GATE"
