# TODO #110 — durable outcome-loop specification and build plan

**Status:** Ready to build
**Decision date:** 2026-08-30 Pacific

## Outcome

Build one small repository-local Codex plugin at `plugins/outcome-loop`.
It owns a frozen mission file, an append-only attempt ledger, copied and hashed
evidence, reviewer handoff files, and the deterministic final check. It does
not replace Ultragoal, Ralph, Team, planning, research, coding, or test tools.
Those tools may do the work; this plugin decides what stage is legal next and
whether the measured goal truly passed.

The plugin is complete only when its tests prove all rows in the acceptance
matrix below, a non-trading dry run rejects a false first attempt and accepts a
meaningfully different second attempt, a clean temporary Codex setup installs
and resumes the plugin, and a safe synthetic trading-shaped mission exercises
the same loop without starting TODO #111.

## Scope decisions

- Location: `plugins/outcome-loop`, inside this repository. The TODO workflow
  limits work to this repository, so this first version is not a personal plugin.
- Runtime: one Python standard-library command program. Do not add a package.
- Skills: one controller skill named `outcome-loop` and one separate read-only
  skill named `independent-verifier`.
- Saved runs: `.omx/outcome-loop/<mission-id>/`. `.omx/` is already ignored by
  Git, so raw run evidence stays local and cannot enter the public repository by
  accident.
- Sources of truth: the frozen `mission.json` and append-only `ledger.jsonl`.
  `state.json` and `final-result.json` are rebuildable views, not competing
  records.
- OMX boundary: Ultragoal may track the larger build and Ralph or Team may keep
  execution moving. Outcome-loop never creates or changes `.omx/ultragoal/*`,
  never calls hidden goal routes, never launches agents, and never treats an OMX
  goal state as proof that the mission passed.
- Domain boundary: the core has no stock, option, Discord, brokerage, or trading
  rules. Those belong in a mission file.
- No Claude wrapper or stop script in version 1. A later wrapper must call this
  same final check and cannot introduce another completion flag.

## Mission file

The mission is JSON. `validate-mission` rejects unknown top-level fields so a
misspelling cannot silently weaken a rule. It also rejects missing fields,
empty values, duplicate list entries, paths outside the repository, overlapping
allowed and forbidden actions, a non-zero expected goal exit code, invalid
decimal costs, and a mission ID that does not match `[a-z0-9][a-z0-9-]{2,63}`.

Required shape:

```json
{
  "formatVersion": 1,
  "missionId": "analyst-record-dry-run",
  "missionVersion": 1,
  "domain": "general",
  "title": "Measure complete analyst records",
  "goal": "Produce the expected count of unique complete analyst records.",
  "passCondition": {
    "description": "The independent record checker returns success.",
    "command": [
      "python3",
      "plugins/outcome-loop/tests/fixtures/check_analyst_records.py",
      "{evidence:analyst-result}"
    ],
    "checkerFiles": [
      "plugins/outcome-loop/tests/fixtures/check_analyst_records.py"
    ],
    "workingDirectory": ".",
    "expectedExitCode": 0,
    "timeoutSeconds": 10
  },
  "feasibilityChecks": {
    "data": {
      "command": ["python3", "plugins/outcome-loop/tests/fixtures/check_feasibility.py", "data", "{evidence}"],
      "checkerFiles": ["plugins/outcome-loop/tests/fixtures/check_feasibility.py"],
      "timeoutSeconds": 10
    },
    "access": {
      "command": ["python3", "plugins/outcome-loop/tests/fixtures/check_feasibility.py", "access", "{evidence}"],
      "checkerFiles": ["plugins/outcome-loop/tests/fixtures/check_feasibility.py"],
      "timeoutSeconds": 10
    },
    "cost": {
      "command": ["python3", "plugins/outcome-loop/tests/fixtures/check_feasibility.py", "cost", "{evidence}"],
      "checkerFiles": ["plugins/outcome-loop/tests/fixtures/check_feasibility.py"],
      "timeoutSeconds": 10
    },
    "permission": {
      "command": ["python3", "plugins/outcome-loop/tests/fixtures/check_feasibility.py", "permission", "{evidence}"],
      "checkerFiles": ["plugins/outcome-loop/tests/fixtures/check_feasibility.py"],
      "timeoutSeconds": 10
    }
  },
  "permissions": {
    "allowedActions": [
      "read_repository",
      "modify_repository",
      "run_local_checks",
      "run_goal_check"
    ],
    "forbiddenActions": [
      "place_trade",
      "send_production_message",
      "push_remote",
      "read_secret",
      "network_access"
    ]
  },
  "budget": {
    "maxCostUsd": "0.00",
    "maxAttempts": 3
  },
  "allowedEvidence": {
    "roots": [
      "plugins/outcome-loop",
      "plugins/outcome-loop/tests/fixtures",
      ".omx/outcome-loop/analyst-record-dry-run"
    ],
    "requiredKinds": [
      "feasibility_data",
      "feasibility_access",
      "feasibility_cost",
      "feasibility_permission",
      "plan",
      "implementation",
      "test"
    ]
  },
  "stopConditions": [
    "budget_exhausted",
    "attempt_limit_reached",
    "permission_or_access_blocked",
    "owner_only_decision",
    "mission_invalidated"
  ]
}
```

Field rules:

- `formatVersion` is exactly `1`.
- `missionVersion` is a positive integer and is copied into every saved state
  and final result.
- `domain` is a non-empty label only. It does not change core behavior.
- `passCondition.command` is a non-empty argument list. Run it directly with
  `subprocess.run(..., shell=False)`. Never join it into a shell command.
- Every final-check input file that is not a checker uses the exact
  `{evidence:<id>}` form. Direct work paths and unrecorded file paths are
  invalid mission arguments.
- `passCondition.checkerFiles` is a non-empty list of repository files needed
  by that command. The command must name at least one listed checker file.
- `passCondition.workingDirectory` resolves inside the repository.
- `passCondition.expectedExitCode` is exactly `0` in version 1.
- `timeoutSeconds` is an integer from 1 through 300.
- `feasibilityChecks` has exactly `data`, `access`, `cost`, and `permission`.
  Every entry has a non-empty argument list, one or more checker files, one
  `{evidence}` argument, and its own timeout.
- Permission names are lower-case slugs. An action must be listed in
  `allowedActions` and absent from `forbiddenActions` before the controller may
  authorize it.
- Money uses `decimal.Decimal`, never floating-point math. `maxCostUsd` is a
  non-negative string with at most two decimal places.
- `maxAttempts` is at least 1. Reaching it produces `STOPPED`, never
  `COMPLETE`.
- Evidence roots are repository-relative real paths. Symlinks and paths that
  escape the repository are rejected.
- Required evidence kinds are non-empty lower-case slugs.
- `stopConditions` may contain only the five values shown above and must contain
  at least one value.

`init` copies the exact mission bytes into the run directory and saves their
SHA-256 hash in `mission.sha256`. Every later command recalculates the hash
before reading or changing state. Reformatting or changing the frozen copy is a
mission change and blocks resume and final completion. A changed mission needs
a new mission version and a new mission ID; it is never edited in place.

At the same time, `init` copies every pass and feasibility checker into
`frozen-checkers/`, preserving its repository-relative path, and saves source
and copied SHA-256 hashes in `checker-manifest.json` and the ledger. Every run
uses the frozen path in place of the matching source path. Before a checker
runs, both the source and frozen copy must still match the initialized hash.
A changed or missing checker blocks the stage; it is never silently refreshed.

## Candidate file and duplicate rule

Each attempt starts with one candidate file:

```json
{
  "candidateId": "attempt-2-unique-records",
  "name": "Count unique complete records",
  "method": {
    "family": "unique-record-identity",
    "inputs": ["analyst", "direction", "published-time", "ticker"],
    "transformation": "normalize-and-deduplicate",
    "decisionRule": "all-required-fields-and-unique-key",
    "output": "complete-record-count"
  },
  "thresholds": {
    "minimumCompleteRecords": 4
  },
  "differenceFromRejected": {
    "priorAttempt": 1,
    "changedFields": ["method.family", "method.transformation", "method.decisionRule"],
    "reason": "The first method counted duplicate rows as separate records."
  }
}
```

The program normalizes the five `method` fields as lower-case slugs, sorts and
deduplicates `inputs`, then hashes only this normalized `method` object with
SHA-256. It deliberately excludes `candidateId`, `name`, `thresholds`, and the
claimed difference text. If that fingerprint matches any rejected attempt,
the new candidate is rejected as a name-only or threshold-only retry.

On attempt 2 or later, `differenceFromRejected` is required. At least one
listed `changedFields` entry must actually differ from the named earlier
candidate. This is the deterministic minimum. The independent reviewer must
also judge whether the changed method addresses the earlier failure; wording
alone is not machine-provable.

## Run directory

```text
.omx/outcome-loop/<mission-id>/
├── mission.json
├── mission.sha256
├── checker-manifest.json
├── ledger.jsonl
├── state.json
├── final-result.json                 # only after a valid pass
├── frozen-checkers/
│   ├── pass/
│   └── feasibility/
├── evidence/
│   ├── attempt-0001/
│   │   └── <evidence-id>--<original-name>
│   └── attempt-0002/
├── review/
│   └── attempt-0002/
│       ├── input.json
│       └── output.json
└── work/                             # mission-created local output
```

Every command takes an explicit repository root and mission ID. A file lock in
the run directory prevents two controllers from changing one mission at the
same time. New JSON views are written to a sibling temporary file and moved
into place atomically.

## Saved state

`state.json` contains exactly the latest replayed view:

```json
{
  "formatVersion": 1,
  "missionId": "analyst-record-dry-run",
  "missionVersion": 1,
  "missionHash": "<sha256>",
  "checkerManifestHash": "<sha256>",
  "controller": {
    "agentId": "<frozen controller agent ID>",
    "threadId": "<frozen controller thread ID>"
  },
  "stage": "DISCOVERY",
  "attempt": 1,
  "repairCycle": 0,
  "candidate": null,
  "rejections": [],
  "feasibility": {
    "data": null,
    "access": null,
    "cost": null,
    "permission": null
  },
  "planEvidenceId": null,
  "builder": null,
  "budget": {
    "maxCostUsd": "0.00",
    "spentCostUsd": "0.00",
    "maxAttempts": 3
  },
  "evidence": [],
  "authorizations": [],
  "review": null,
  "reviewCapability": null,
  "finalGate": null,
  "ledgerHeadHash": "<sha256>",
  "updatedAt": "<Pacific timestamp>"
}
```

Use `ZoneInfo("America/Los_Angeles")` for saved and displayed times. The ledger
is authoritative. On resume, replay it and compare the result with
`state.json`. If the view is missing or corrupt, rebuild it from the intact
ledger. If the ledger itself is corrupt, stop; do not infer progress from files
that happen to exist.

## Append-only ledger

Each line is one complete JSON object:

```json
{
  "formatVersion": 1,
  "sequence": 7,
  "at": "<Pacific timestamp>",
  "event": "feasibility_recorded",
  "missionId": "analyst-record-dry-run",
  "attempt": 1,
  "fromStage": "FEASIBILITY",
  "toStage": "FEASIBILITY",
  "previousHash": "<prior event hash>",
  "payload": {},
  "eventHash": "<this event hash>"
}
```

`eventHash` is SHA-256 of the UTF-8 canonical JSON for every field except
`eventHash`, using sorted keys and compact separators. The first
`previousHash` is 64 zeroes. Replay rejects a missing sequence, broken previous
hash, changed line, unknown event, illegal stage change, mission mismatch, or
attempt number that moves backward.

Minimum event names are:

- `mission_initialized`, `checkers_frozen`, `attempt_started`, `candidate_selected`,
  `attempt_rejected`
- `evidence_recorded`, `feasibility_recorded`, `plan_recorded`,
  `builder_declared`
- `action_authorized`, `action_completed`, `permission_breach`,
  `budget_breach`
- `build_passed`, `build_failed`, `review_prepared`,
  `review_capability_used`, `review_received`, `review_invalid`,
  `review_rejected`, `final_repair_started`
- `final_gate_started`, `final_gate_blocked`, `goal_check_failed`,
  `final_gate_passed`, `mission_stopped`

No command edits or deletes an old line. A domain event carries `fromStage` and
`toStage`, so state changes do not need a second ledger entry.

## Exact stage rules

The only success path is:

```text
DISCOVERY -> FEASIBILITY -> PLANNED -> BUILDING -> REVIEW -> FINAL_GATE -> COMPLETE
```

`STOPPED` is a separate terminal state and is never treated as success.

Rules:

1. `init` requires controller agent and thread IDs, freezes them with the
   mission and every checker, then writes
   `mission_initialized`, `checkers_frozen`, and `attempt_started`. The result
   is `DISCOVERY`, attempt 1.
2. `candidate` accepts a structurally new candidate and moves
   `DISCOVERY -> FEASIBILITY`.
3. Feasibility has exactly four checks: `data`, `access`, `cost`, and
   `permission`. Each call needs a recorded, non-empty evidence file of its
   matching kind and runs the mission's frozen checker against the frozen
   evidence copy. Exit code 0 is not enough: stdout must be one JSON object with
   `status:"PASS"`, the exact evidence SHA-256, and a non-empty `facts` list.
   All four must pass in the ledger before the last pass moves
   `FEASIBILITY -> PLANNED`. Empty, random, wrong-kind, or checker-rejected
   evidence cannot unlock build.
4. A failed feasibility or explicit candidate failure records the candidate and
   reason in `rejections`, starts the next attempt at `DISCOVERY`, and clears
   candidate-specific state. If `maxAttempts` is exhausted, it moves to
   `STOPPED`.
5. `plan` records a plan evidence ID while staying `PLANNED`. `start-build`
   requires that evidence, a builder agent ID, a builder thread ID, and an open
   authorization for `modify_repository`. Both builder IDs must differ from the
   frozen controller IDs; controller-as-builder is rejected. It consumes the
   authorization and then moves
   `PLANNED -> BUILDING`. There is no path into `BUILDING` before all four
   feasibility entries passed.
6. `complete-action` closes the build authorization after the work and records
   actual cost. A build result is refused while that authorization is open. A
   failed build or test stays in `BUILDING` with the same candidate and attempt,
   increments `repairCycle`, and records its evidence. A passing build with
   required implementation and test evidence moves `BUILDING -> REVIEW`.
7. A rejected review chooses one explicit disposition. `repair` moves
   `REVIEW -> BUILDING` on the same attempt and increments `repairCycle`.
   `new_candidate` records a rejection and starts the next attempt in
   `DISCOVERY`.
8. `prepare-review` creates a one-time reviewer capability. A valid independent
   approval must present it and moves `REVIEW -> FINAL_GATE`.
9. A failing goal command records its output, rejects the candidate, and starts
   a new attempt in `DISCOVERY`. If no attempt remains, it moves to `STOPPED`.
10. Only `final-gate` may move `FINAL_GATE -> COMPLETE` and write
    `final-result.json`. A correctable final-check blocker may use
    `repair-final-gate` to move `FINAL_GATE -> BUILDING` on the same attempt.
    That event invalidates the review, increments `repairCycle`, and requires
    fresh implementation evidence, test evidence, review input, reviewer
    capability, and approval before `FINAL_GATE` can be entered again.
11. `stop` accepts only a stop condition frozen in the mission and moves any
    non-complete stage to `STOPPED`. Resume validates and reports a stopped
    mission but cannot reopen it. A new mission version and ID are required.
12. No command can leave `COMPLETE` or `STOPPED`.

## Evidence rules

`evidence` accepts an ID, kind, and source file. It resolves the real source
path, rejects directories and symlinks, checks it lies under an allowed root,
copies the raw bytes into the attempt evidence directory, and records both the
source and copied SHA-256 hashes, byte count, paths, attempt, and ledger
sequence. Feasibility evidence must contain at least one byte; the
mission-specific checker decides whether those bytes actually prove the named
fact.

Before review and again before completion, the program checks:

- every recorded source file still exists and has its recorded hash;
- every copied file exists and has the same hash;
- every required kind exists for the current attempt;
- feasibility evidence was recorded before its pass event;
- plan evidence was recorded before `start-build`;
- implementation and test evidence were recorded before `build_passed`;
- no evidence from a rejected attempt is used to complete the current one.

For the final command, argument 0 is the executable, checker-file arguments are
replaced by frozen checker paths, and every other file input must be an exact
`{evidence:<id>}` placeholder. Final gate resolves each placeholder only to the
current attempt's copied evidence file. The evidence ID must already be in the
review input manifest, and its source hash, copied hash, and reviewed hash must
all still match. A direct `work/result.json`, other unrecorded path, missing ID,
evidence recorded after review, or input changed after review is rejected before
the checker runs.

Command output from the goal check is saved directly under the current attempt
and hashed as `goal_command_output`; it is not accepted from builder prose.

## Checker execution

Feasibility and final goal commands run only from their frozen checker copies.
The program replaces every checker source argument with its frozen path and
replaces feasibility `{evidence}` with that check's frozen evidence path. For
the final command it replaces each `{evidence:<id>}` only with the reviewed
copied evidence path for that ID. It uses
`shell=False`, the frozen working directory, and a clean environment containing
only `PATH` set to `os.defpath`, `LANG=C.UTF-8`, `LC_ALL=C.UTF-8`, and
`PYTHONNOUSERSITE=1`. It does not pass repository or machine environment
variables through to the checker.

Each command uses its frozen `timeoutSeconds`. A timeout, signal, malformed
JSON response, changed checker hash, missing checker, wrong evidence hash, or
non-zero exit is a failed check. The program caps stdout and stderr at 1 MiB
each, redacts their bodies from normal chat output, and saves their hashes and
exit facts in the ledger.

Version 1 does not claim arbitrary operating-system network isolation. Every
mission used by TODO #110 must list `network_access` as forbidden. The reviewer
must inspect checker files and report `networkNotUsed:"PASS"`; the dry-run tests
also fail if a fixture checker opens a socket or makes a network request. If a
locally available network sandbox is later added, it may strengthen this rule
but cannot replace the frozen permission or reviewer check.

## Budget and permission checks

The controller must call `authorize-action` before every action with side
effects or cost. It supplies an action slug and estimated cost. The command:

1. checks the action is allowed and not forbidden;
2. checks estimated cost plus recorded spend does not exceed `maxCostUsd`;
3. writes an authorization ID to the ledger.

After the action, `complete-action` records the authorization ID and actual
cost. Reusing an authorization, completing an unknown authorization, or actual
cost above the remaining budget writes a breach and moves to `STOPPED`.
Attempt creation also enforces `maxAttempts` before writing the new attempt.

`start-build` requires and consumes an open `modify_repository` authorization;
`build-result` requires that authorization to have been completed with actual
cost. `final-gate` requires an open `run_goal_check` authorization with an
estimated cost of `0.00`, consumes it, runs the local deterministic command, and
records the authorization complete with actual cost `0.00` whether the command
passes, fails, or times out. Any permission breach, budget breach, unrelated
unfinished authorization, cost overrun, or attempt overrun blocks completion.

This contract can prove what passed through its own command program. It cannot
detect a person or agent deliberately running an off-ledger command. The
controller skill must therefore require these checks, and the independent
review must flag evidence of undeclared actions. Do not claim stronger policing
than the artifacts provide.

## Independent review

The builder cannot approve its work. `prepare-review` writes
`review/attempt-N/input.json` containing:

- the complete frozen mission and mission hash;
- the checker manifest plus every frozen pass and feasibility checker;
- the current candidate and its structural fingerprint;
- all earlier rejected candidates and failure reasons;
- the four feasibility decisions and their raw evidence entries;
- budget and permission events;
- the current attempt ledger slice;
- a manifest of every current raw artifact with source path, copied path,
  SHA-256 hash, and byte count;
- frozen controller agent and thread IDs;
- builder agent and thread IDs;
- the SHA-256 hash of a one-time reviewer capability;
- the exact reviewer checklist.

`prepare-review` creates 32 random bytes with `secrets`, encodes them as a
URL-safe capability, stores only its SHA-256 hash in the input, ledger, and
state, and returns the clear capability once in its structured stdout. The
controller does not put it in a file or normal progress message. The
orchestration layer gives it only to the newly created separate reviewer.

There is no builder-written summary in place of raw files. The reviewer reads
the input and the listed raw artifacts directly. The read-only reviewer skill
must not write files or edit the implementation. It returns this envelope to
the controller through the agent response, and the controller pipes it to
`review-result --from-stdin`:

```json
{
  "reviewCapability": "<one-time clear capability>",
  "review": {
    "formatVersion": 1,
    "missionId": "analyst-record-dry-run",
    "attempt": 2,
    "inputSha256": "<review input hash>",
    "reviewer": {
      "agentId": "<separate agent ID>",
      "threadId": "<separate thread ID>",
      "role": "independent-verifier",
      "mode": "read_only"
    },
    "decision": "APPROVE",
    "disposition": null,
    "checks": {
      "missionMatches": "PASS",
      "goalEvidenceSupportsPass": "PASS",
      "feasibilityPrecededBuild": "PASS",
      "candidateAddressesEarlierFailure": "PASS",
      "budgetAndPermissionsIntact": "PASS",
      "rawArtifactsRead": "PASS",
      "networkNotUsed": "PASS"
    },
    "artifactFindings": [],
    "editedPaths": []
  }
}
```

`review-result` also requires submitter agent and thread IDs. It accepts only
the exact controller IDs frozen at init and records them in
`review_capability_used` and `review_received`. The builder and reviewer IDs
must each differ from both controller IDs and from each other. A builder cannot
submit an approval even if it obtains the clear reviewer capability.

`review-result` compares the supplied capability hash with
`hmac.compare_digest`, requires it to be pending for this exact review input,
marks it used once, removes it before saving `output.json`, and never writes the
clear value to the ledger or state. A missing, wrong, reused, or older-review
capability rejects the submission. Supplying forged reviewer IDs without the
capability cannot create an approval.

The saved `output.json` therefore has this inner shape:

```json
{
  "formatVersion": 1,
  "missionId": "analyst-record-dry-run",
  "attempt": 2,
  "inputSha256": "<review input hash>",
  "reviewer": {
    "agentId": "<separate agent ID>",
    "threadId": "<separate thread ID>",
    "role": "independent-verifier",
    "mode": "read_only"
  },
  "decision": "APPROVE",
  "disposition": null,
  "checks": {
    "missionMatches": "PASS",
    "goalEvidenceSupportsPass": "PASS",
    "feasibilityPrecededBuild": "PASS",
    "candidateAddressesEarlierFailure": "PASS",
    "budgetAndPermissionsIntact": "PASS",
    "rawArtifactsRead": "PASS",
    "networkNotUsed": "PASS"
  },
  "artifactFindings": [],
  "editedPaths": []
}
```

For `REJECT`, `disposition` is `repair` or `new_candidate` and at least one
finding is required. Approval is invalid unless all checks pass, the reviewer
role and mode match exactly, `editedPaths` is empty, `inputSha256` matches,
mission/attempt match, source and copied artifact hashes remain unchanged, the
submitter is the frozen controller, and controller, builder, and reviewer IDs
are pairwise distinct. Missing IDs, controller-as-builder,
builder-as-submitter, the same builder and reviewer, a same-thread review,
reviewer edits, missing raw artifacts, or a changed artifact blocks completion.
Corrections require a new build result and fresh review; an old approval never
follows changed code.

The capability proves only that the response possessed the one-time value held
by orchestration and that the frozen controller submitted it. The orchestration
layer can still lie about controller, builder, reviewer, or submitter IDs because
those IDs are supplied metadata, not cryptographic identity proof. The actual
trust boundary is therefore: trusted orchestration-provided IDs, frozen
controller identity, separate builder and reviewer threads, one-time
capability, pairwise-distinct recorded IDs, read-only instructions, and
unchanged artifact hashes. State this limitation in the skill and do not claim
the script alone proves who performed the roles.

## Deterministic final check

`final-gate` performs these checks in order and stops before running the goal
command if any precondition fails:

1. lock acquired; frozen mission hash and version match;
2. frozen checker manifest, source hashes, and copied hashes match;
3. ledger hash chain and replayed state are valid;
4. current stage is `FINAL_GATE` and not `STOPPED` or `COMPLETE`;
5. current attempt and candidate are within mission limits;
6. stage order and checker results prove all four feasibility passes happened
   before build with meaningful, non-empty evidence;
7. candidate fingerprint is absent from earlier rejected fingerprints;
8. all required evidence exists and source/copy hashes match;
9. plan, implementation, and test evidence occurred in the required order;
10. no permission breach, budget breach, unrelated unfinished authorization, or overrun
   exists;
11. frozen controller, builder, reviewer, and review submitter records are
    present; the submitter is the controller and all three roles are distinct;
12. review input contains the frozen mission and raw artifact manifest;
13. review capability was used exactly once for this input by the frozen controller;
14. review output is present, hashes to the ledger value, matches the input,
    comes from a distinct read-only reviewer, reports no edits, and approves;
15. reviewed artifacts have not changed since the input was made;
16. every non-checker file argument is an evidence placeholder whose current
    copied file appears unchanged in the review manifest; no direct or
    post-review input path exists;
17. an open zero-cost `run_goal_check` authorization exists;
18. consume it and run the frozen checker arguments with no shell, the clean
    environment, and the frozen timeout; save bounded raw output and its hash;
19. require exit code 0, then append `final_gate_passed`, move to `COMPLETE`,
    and write `final-result.json` from the ledger event.

Assistant text, a completed build, a passing test subset, a reviewer approval by
itself, Ralph's completion phrase, or an Ultragoal completion state cannot write
`COMPLETE`.

If the goal command fails or times out, record its exit facts and hashed output, reject the
current candidate, and start a new discovery attempt subject to the mission
limits. Other correctable gate failures leave the mission incomplete at its
current stage. `repair-final-gate` explicitly moves it back to `BUILDING`,
invalidates the review and capability, and requires fresh build, test, and
review proof before another final attempt.
Boundary breaches move to `STOPPED`.

Repeated `final-gate` on a valid completed run is idempotent: validate the
mission, ledger, saved evidence, and existing final result; return the exact
same result without rerunning the goal command, appending a ledger line, or
changing any file. A changed or missing saved artifact produces an error, not a
second result.

## Command surface

Keep one program with these subcommands:

```text
validate-mission --mission <file> --root <repo>
init --mission <file> --controller-agent-id <id> --controller-thread-id <id> --root <repo>
status --mission-id <id> --root <repo>
resume --mission-id <id> --root <repo>
candidate --mission-id <id> --candidate <file> --root <repo>
evidence --mission-id <id> --id <id> --kind <kind> --file <path> --root <repo>
feasibility --mission-id <id> --check <data|access|cost|permission> --status <pass|fail> --evidence <id> --root <repo>
authorize-action --mission-id <id> --action <slug> --estimated-cost-usd <decimal> --root <repo>
complete-action --mission-id <id> --authorization-id <id> --actual-cost-usd <decimal> --root <repo>
plan --mission-id <id> --evidence <id> --root <repo>
start-build --mission-id <id> --builder-agent-id <id> --builder-thread-id <id> --authorization-id <id> --root <repo>
build-result --mission-id <id> --status <pass|fail> --evidence <id> [--evidence <id> ...] --root <repo>
prepare-review --mission-id <id> --root <repo>
review-result --mission-id <id> --submitter-agent-id <id> --submitter-thread-id <id> --from-stdin --root <repo>
repair-final-gate --mission-id <id> --reason <text> --evidence <id> --root <repo>
reject-candidate --mission-id <id> --reason <text> --evidence <id> --root <repo>
stop --mission-id <id> --condition <frozen-condition> --evidence <id> --root <repo>
final-gate --mission-id <id> --authorization-id <id> --root <repo>
```

All commands return non-zero on refusal and print a small JSON result to stdout.
They never print evidence bodies, environment values, or secrets. `resume`
returns the preserved mission version, stage, attempt, repair count, rejected
fingerprints and reasons, spent budget, evidence IDs and hashes, reviewer state,
and legal next commands. It does not restart `STOPPED` work.

## Acceptance matrix and focused tests

The test names below are the required behavior, not suggestions.

1. `test_init_rejects_each_missing_required_mission_field`
2. `test_changed_mission_or_checker_hash_blocks_resume_and_final_gate`
3. `test_init_starts_discovery_attempt_one_and_freezes_all_checkers`
4. `test_build_is_forbidden_until_all_four_frozen_feasibility_commands_pass`
5. `test_empty_random_or_wrong_kind_feasibility_evidence_cannot_unlock_build`
6. `test_only_the_declared_success_stage_order_is_accepted`
7. `test_candidate_or_goal_failure_starts_new_discovery_attempt`
8. `test_build_or_test_failure_repairs_same_candidate`
9. `test_rejected_review_can_repair_or_start_new_candidate`
10. `test_stopped_is_never_complete_and_cannot_resume_to_active`
11. `test_resume_preserves_version_stage_attempt_rejections_budget_and_evidence`
12. `test_resume_rebuilds_missing_state_from_intact_ledger`
13. `test_missing_or_changed_source_or_copied_evidence_blocks_completion`
14. `test_name_only_retry_is_rejected`
15. `test_threshold_only_retry_is_rejected`
16. `test_review_input_contains_frozen_mission_raw_artifacts_and_capability_hash_only`
17. `test_forged_reviewer_ids_without_the_one_time_capability_are_rejected`
18. `test_builder_with_capability_cannot_submit_forged_approval`
19. `test_controller_builder_and_reviewer_must_be_pairwise_distinct`
20. `test_same_thread_reused_capability_and_reviewer_edits_are_rejected`
21. `test_missing_reviewer_or_evidence_blocks_completion`
22. `test_budget_overrun_and_permission_breach_stop_completion`
23. `test_final_gate_repair_invalidates_review_and_requires_fresh_build_test_review`
24. `test_changed_or_unrecorded_goal_input_blocks_completion`
25. `test_changed_or_hanging_goal_checker_blocks_completion`
26. `test_failed_goal_command_rejects_false_pass_and_continues_discovery`
27. `test_valid_pass_needs_frozen_goal_check_intact_evidence_limits_authorization_and_read_only_approval`
28. `test_repeated_final_gate_is_byte_for_byte_idempotent`
29. `test_non_trading_dry_run_rejects_false_first_method_and_completes_different_second_method`
30. `test_temporary_codex_home_installs_discovers_and_resumes_the_plugin`
31. `test_synthetic_trading_shaped_dry_run_exercises_loop_without_network_or_edge_claim`

The non-trading test uses a small local analyst-record fixture. Attempt 1 uses a
plain line count that incorrectly counts a duplicate as a complete record. Even
with seeded builder and reviewer pass claims, the frozen goal command rejects
it and the run returns to `DISCOVERY`, attempt 2. Attempt 2 changes the method to
normalize required fields and count unique record identities, passes a fresh
read-only review, passes the goal command, and reaches `COMPLETE`.

The synthetic trading-shaped test uses invented price rows and a deterministic
local rule. It runs feasibility, one rejected candidate, a structurally
different second candidate, separate read-only review, and the final check. It
must make no network or brokerage call, place no order, send no message, and
make no profitability or trading-edge claim. It proves only that a trading-shaped
mission can use the loop. TODO #111 starts later as a fresh mission and remains
outside this build.

The clean-install test creates a temporary directory with `mktemp -d`, uses it
as `CODEX_HOME` only for the test commands, and cleans it afterward. With the
repository root and marketplace name resolved from the saved marketplace file,
it runs the current local command surface:

```text
codex plugin marketplace add <repo-root>
codex plugin add outcome-loop@openclaw-workspace-local
codex plugin list --available --json
```

It must see the plugin installed and enabled, see both skills in the installed
copy, initialize a fixture mission through that installed copy, then start a
fresh Codex process with the same temporary `CODEX_HOME` and prove `resume`
returns the saved stage and attempt. The test must not change the real Codex
home or rely on the source tree being on Python's import path.

## Files to build

```text
.agents/plugins/marketplace.json
plugins/outcome-loop/.codex-plugin/plugin.json
plugins/outcome-loop/scripts/outcome_loop.py
plugins/outcome-loop/templates/mission.template.json
plugins/outcome-loop/skills/outcome-loop/SKILL.md
plugins/outcome-loop/skills/outcome-loop/references/mission-contract.md
plugins/outcome-loop/skills/independent-verifier/SKILL.md
plugins/outcome-loop/tests/test_outcome_loop.py
plugins/outcome-loop/tests/fixtures/analyst-records.jsonl
plugins/outcome-loop/tests/fixtures/check_analyst_records.py
plugins/outcome-loop/tests/fixtures/check_feasibility.py
plugins/outcome-loop/tests/fixtures/synthetic-trading-rows.jsonl
plugins/outcome-loop/tests/fixtures/check_synthetic_trading.py
plugins/outcome-loop/tests/fixtures/synthetic-trading-mission.json
```

The manifest follows the existing Codex plugin convention: name, version,
description, author, `skills: "./skills/"`, and an interface block. No hook,
agent definition, dependency, or installer is needed. The repository
marketplace is named `openclaw-workspace-local` and contains one local source at
`./plugins/outcome-loop` with installation `AVAILABLE`, authentication
`ON_INSTALL`, and category `Productivity`. The skill reference is the usage
documentation; do not add a duplicate README.

## Architecture invariants

The final architecture review must prove each item with the named code and test
evidence:

1. Only the deterministic command program can write `COMPLETE` or
   `final-result.json`.
2. The exact frozen mission and checker bytes plus the append-only hash-chained
   ledger are the durable sources of truth; `state.json` is replayable.
3. No build begins before all four frozen mission-specific feasibility commands
   pass against non-empty, matching evidence.
4. A rejected candidate or failed goal starts a new attempt; build/test repair
   keeps the same candidate.
5. Candidate identity excludes names and thresholds, so those changes alone
   cannot evade a rejection.
6. Recorded raw evidence is copied, hashed with SHA-256, and rechecked at review
   and completion. Every final non-checker file input is a reviewed evidence
   placeholder; direct, changed, unrecorded, or post-review inputs are rejected.
7. Controller identity is frozen at init. Controller, builder, and reviewer are
   pairwise distinct; only the controller may submit review output, so a builder
   with the capability still cannot forge approval. The reviewer receives the
   frozen mission, raw artifacts, and one-time clear capability through trusted
   orchestration; saved files contain only its hash, and no approval survives
   changed artifacts.
8. Budget and permission breaches can never become `COMPLETE`.
9. `STOPPED` and `COMPLETE` are terminal and never equivalent.
10. A final-check repair returns explicitly to build and invalidates all review
    proof. A second successful final check makes no changes and does not rerun the goal
    command.
11. Pass and feasibility commands use frozen checker copies, no shell, a clean
    environment, bounded output, and timeouts. Network is forbidden by mission
    and checked by review and dry-run tests without claiming unavailable OS
    isolation.
12. The core contains no trading-specific rule; the synthetic trading-shaped
    proof uses invented local data and makes no edge claim.
13. The plugin coordinates existing OMX work; it does not duplicate or mutate
    OMX orchestration state.
14. The repository marketplace installs into a clean temporary Codex home, both
    skills are discovered, and a fresh process resumes saved state.
15. Paths stay inside the repository, symlinks are rejected, shell evaluation
    is not used, and no evidence body or secret is printed.

## Small execution plan

1. **Build the deterministic core.** Add the manifest, mission template, and
   single Python program. Write tests 1–15 first, then implement mission and
   checker freezing, mission-specific feasibility, ledger replay, stage changes,
   evidence hashes, duplicate checks, budget, permissions, and resume.
   Verification: tests 1–15 pass from a clean
   temporary repository.
2. **Add separate review and final completion.** Add review input/output checks
   and the two skills. Write tests 16–28 first, then implement frozen controller
   identity, pairwise role separation, the one-time reviewer capability,
   reviewed evidence placeholders, final repair, frozen goal runner, and sole
   completion path. Verification: tests 1–28 pass, including the
   unchanged ledger length and final-result bytes on a repeated final check.
3. **Prove general use without trading.** Add the analyst-record fixture and run
   the two-attempt dry mission through the real command surface. Add the
   repository marketplace and prove clean install, discovery, and fresh-process
   resume in a temporary Codex home. Run the synthetic trading-shaped mission on
   invented local data. Verification: tests 29–31 pass; inspect both dry-run
   ledgers, rejection, capability hash, reviewer input, checker hashes, and final
   results.
4. **Run repository gates and independent review.** Run the plugin tests, then
   the repository's normal test checks required for the touched files. Run the
   cleanup pass, rerun tests, then use separate code-reviewer and architect
   agents to prove every architecture invariant. A review result other than
   `APPROVE` plus architectural `CLEAR` adds repair work; it does not close the
   TODO.
5. **Close #110 only on proof.** Save the final gate and dry-run evidence, update
   the TODO detail and index through the TODO scripts, and produce the one-line
   kickoff for a fresh TODO #111 session. Do not start the trading mission in
   this work.

## Stop condition for this build

Stop only when the 31 focused behaviors pass, the real non-trading run reaches
`COMPLETE` after rejecting its false first method, the clean temporary install
discovers and resumes the plugin, the synthetic trading-shaped run completes
without network access or an edge claim, repository checks show no new failure,
and separate reviews report `APPROVE` and `CLEAR`. Any missing proof leaves
TODO #110 open.
