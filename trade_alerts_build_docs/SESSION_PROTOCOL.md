# SESSION_PROTOCOL.md

## 1. Purpose

This document defines the required operating procedure for every future Codex coding session.

Its purpose is to ensure fresh sessions can regain context, select the correct milestone, avoid duplication, preserve approved trading logic, make small testable changes, update documentation, and leave a clean handoff.

## 2. Core Rule

For an authorized implementation session:

```text
READ
→ INSPECT
→ SELECT ONE COHERENT MILESTONE
→ IMPLEMENT
→ TEST
→ DOCUMENT
→ HAND OFF
→ STOP
```

Do not attempt the entire project in one context window.

## 3. Required Reading

Start with `PROJECT_INDEX.md`, the current ROADMAP section 31 handoff, and the
role-specific work packet. Read the canonical sections named by the assigned
milestone and any additional section needed to resolve a discovered dependency
or conflict. Do not load every canonical file or accumulated evidence history for
a narrow repair, review, or records-only finalization.

Repository documentation is persistent project memory. Do not assume original conversation context exists.

## 4. Authority

Use `PROJECT_INDEX.md` for routing/conflict precedence.

Key rule:
- approved newer decisions may supersede older requirements but must be synchronized into the governing canonical document;
- open questions/hypotheses/observations never override established requirements.

## 5. Mandatory Repository Inspection

Before coding:
- inspect current branch/worktree status
- inspect relevant recent commits
- inspect project structure
- locate existing related modules
- inspect tests/config/docs
- locate reusable market data, Schwab, Discord, options, storage, scheduler, logging, replay components

Do not implement a new equivalent before checking whether one already exists.

## 6. Uncommitted Work

If existing changes are present:
- inspect them
- do not discard unrelated work
- avoid broad formatting churn
- do not use destructive `git reset --hard`, `git clean -fd`, or equivalent unless explicitly instructed

## 7. Select Session Scope

Use `ROADMAP.md`.

Choose the earliest dependency-ready unfinished milestone.

Prefer one complete milestone over multiple partial milestones.

Small prerequisites may be included if directly required. Substantial newly discovered prerequisites should become their own roadmap work.

## 8. Documentation Drift Check

Before implementation perform the drift check in `PROJECT_INDEX.md`.

Resolve minor drift immediately. Resolve material drift from approved decisions if possible. Otherwise mark affected work blocked rather than guessing.

## 9. Strategy Logic Protection

Do not silently change:
- thresholds
- eligibility
- state transitions
- heads-up rules
- actionable triggers
- stale rules
- invalidation
- stop methodology
- targets
- confidence weighting
- options policies
- suppression/dedup rules

If a rule looks wrong:
1. preserve current approved behavior if safe;
2. record the issue;
3. classify `NEEDS VALIDATION`, `BLOCKED BY DATA`, or conflict;
4. do not invent a production rule.

## 10. Provisional Thresholds

Provisional values are still the current implementation rules until properly validated and approved.

Do not “improve” them by intuition.

## 11. Data Rule

Check `DATA_REQUIREMENTS.md`.

- confirmed data → proceed
- approved proxy → use proxy and store mode
- unavailable/no proxy → block/degrade/disable as specified

Never convert `UNKNOWN` into favorable information.

## 12. Shared Logic

Search for shared implementations before adding strategy-specific calculations.

Centralize:
- market clock
- VWAP
- ATR
- RVOL
- RS
- HOD/LOD
- premarket/prior levels
- gap
- opening range
- spread
- volume acceleration
- structural R:R
- option ranking
- event serialization
- suppression
- confidence

## 13. Separation of Concerns

Maintain:

```text
RAW DATA
→ NORMALIZED DATA
→ FEATURES
→ MARKET CONTEXT
→ SETUP DETECTION
→ STRATEGY STATE
→ RISK/TARGETS
→ CONFIDENCE
→ OPTIONS
→ DEDUP
→ ATOMIC RESEARCH FACTS / DELIVERY INTENT
→ ALERT RENDERING / DELIVERY
→ SEPARATE DELIVERY ACKNOWLEDGMENT
```

## 14. No Automated Trading

Do not add order placement, automated exits/stops, automated position sizing, or live brokerage position synchronization unless scope is explicitly changed in `MASTER_SPEC.md`.

## 15. Point-in-Time Integrity

Every historical/replay calculation must ask:

> Could the live system have known this at the timestamp?

No future HOD/LOD, daily volume, VWAP, catalyst classification, breadth membership, profile, option quote, or target structure.

## 16. State-Machine Discipline

Strategies must use explicit deterministic states. Persist meaningful transitions.

Reject impossible transitions where practical.

## 17. Immutable Alert Facts

Once generated, do not mutate:
- trigger
- alert price
- stop
- targets
- confidence
- feature snapshot
- strategy/config version

Outcomes are separate.

## 18. Testing During Every Session

Run:
1. the exact failing cases and directly affected protected checks;
2. nearby/integration checks needed by changed callers and interfaces;
3. a broader protected acceptance selection justified by changed dependencies,
   with a broad fallback when impact is unknown;
4. lint/type checks where configured.

A failed focused stage stops broader testing. Run acceptance once unless the
claim requires repeatability. Deterministic recordings, reopen/retry behavior,
recovery, ordering, idempotence, or another stated repeatability reason require
fresh-process repetition and artifact comparison. A narrow builder selection
cannot remove controller- or reviewer-required coverage.

Code, tests, configuration, dependencies, or protected inputs invalidate affected
proof. Records-only finalization may reuse matching published proof and must not
rerun product tests only to repair documentation or structured evidence format.

Do not claim success without executing available verification.

New regressions introduced in the session must be fixed before completion unless truly blocked.

## 19. Synthetic Strategy Tests

Every strategy milestone should include deterministic cases:
- valid setup
- near miss
- invalid
- stale
- long
- short
- data unavailable
- spread too wide
- insufficient R:R
- invalidation
- expiry

Use strategy-specific scenarios from `ROADMAP.md` and `TESTING_AND_VALIDATION.md`.

## 20. Logging / Failure Handling

Add structured observability for important state transitions, suppressions, stale data, feature unavailability, alerts, option rejection, duplicate suppression, and delivery failure.

Never swallow errors that could invalidate strategy output.

Fail safe: suppress/degrade/disable rather than emit actionable alerts from invalid mandatory data.

## 21. Documentation Updates

During every session ask:
- did a new dependency appear?
- did an interface change?
- did a data assumption change?
- did a milestone complete?
- did an unresolved question become resolved?
- did an approved decision create drift?

Update the relevant canonical document.

## 22. Strategy Versioning

Material strategy behavior changes require a new strategy version or material config version.

Non-semantic refactors/logging/rendering changes generally do not.

Preserve old historical version attribution.

## 23. Research Boundary

Implementation does not prove profitability.

Use precise statuses:
- implemented
- unit-tested
- replayable
- shadow-ready
- historically tested
- walk-forward tested
- provisional
- active

New historical patterns are observations/hypotheses until held-out/future validation and approval.

## 24. Session Blockers

For missing credentials, unavailable data, external provider failure, or unresolvable specification conflict:
- document exact blocker
- complete useful non-blocked work
- mark roadmap `[!]`
- define smallest next actionable task
- do not fake success

## 25. Minimize User Intervention

Before asking:
- inspect repo
- inspect docs
- inspect config
- inspect API interfaces
- inspect prior decisions

Ask only when the project materials cannot resolve a genuinely blocking decision.

## 26. Git / Checkpoint Discipline

Before committing:
- inspect `git status`
- inspect diff
- exclude unrelated pre-existing changes
- remove temporary/debug artifacts
- run required tests
- update docs

Only when the current user request authorizes saved code changes and repository workflow permits; an explicit no-commit/no-push instruction wins:
- create one logical local commit for completed, tested session work
- use a descriptive conventional message where repo style exists
- do not force-push, rewrite history, or auto-push unless explicitly requested/configured
- if milestone is partial, prefer leaving a clean tested checkpoint only if doing so is useful and consistent with repo policy

## 27. Subagents

If subagents are available, use them for bounded tasks such as repo audit, targeted code search, test review, or documentation consistency checks. Main session owns integration and final verification. Avoid parallel conflicting edits.

## 28. Session Start Checklist

```text
[ ] Read PROJECT_INDEX and canonical docs.
[ ] Read relevant implementation docs.
[ ] Inspect git status.
[ ] Perform documentation drift check.
[ ] Locate next roadmap milestone.
[ ] Verify dependencies.
[ ] Inspect reusable code.
[ ] Check data constraints.
[ ] Check open questions/approved decisions.
[ ] Define coherent session scope.
```

## 29. During-Session Checklist

```text
[ ] Preserve approved strategy logic.
[ ] Reuse shared components.
[ ] Avoid unrelated refactors.
[ ] Keep point-in-time safety.
[ ] Add tests.
[ ] Add failure handling.
[ ] Add required observability.
[ ] Keep data modes explicit.
[ ] Separate options from underlying validity.
[ ] Separate human decisions from mechanical alerts.
```

## 30. Pre-Completion Checklist

```text
[ ] Focused tests run.
[ ] Integration tests run where required.
[ ] Lint/type checks run where configured.
[ ] Diff reviewed.
[ ] No secret introduced.
[ ] No silent strategy change.
[ ] No look-ahead introduced.
[ ] Error handling explicit.
[ ] Canonical docs updated.
[ ] ROADMAP updated.
[ ] Open issues recorded.
[ ] End-of-session drift check completed.
[ ] Exact next milestone and blockers saved; one-line next-session kickoff prepared.
```

## 31. Required End-of-Session Report

Every session must finish with:
1. WHAT WAS COMPLETED
2. FILES CHANGED
3. TESTS PERFORMED / RESULTS
4. KNOWN ISSUES / OPEN QUESTIONS
5. EXACT NEXT ROADMAP MILESTONE
6. ONE-LINE, READY-TO-COPY KICKOFF FOR THE NEXT FRESH SESSION

Keep the report short and plain. The kickoff is mandatory after every build session; do not merely offer to provide it. Save the actual progress, evidence, blockers and next dependency-ready milestone before writing the kickoff. Finish the response with exactly one copyable line in a text code block, using §32. If the session is incomplete, preserve that fact and make the handoff resume the remaining work instead of marking it complete. Then stop.

## 32. Next-Session Prompt Template

Use the same single-line trigger after every session. The files carry the changing milestone, approved rules, unfinished work, evidence and cumulative Databento budget; do not put that detail into a long pasteable prompt. Verify that PROJECT_INDEX routes to the current ROADMAP before handing off. The next session must read those files rather than infer the next step from an older chat.

```text
Start the next build session by reading /root/.openclaw/workspace/trade_alerts_build_docs/PROJECT_INDEX.md.
```

If the whole planned build is complete, record that terminal state and say so; do not invent another coding milestone. Otherwise the fresh session selects the recorded dependency-ready work. Each session handles one coherent milestone and returns this one-line handoff again.

## 33. Successful Session Definition

```text
one coherent milestone advances
+
approved behavior preserved
+
tests substantiate change
+
documentation synchronized
+
next session can continue safely
```

## 34. Review-only and integration safeguards

The 2026-09-05 Pacific prebuild session is documentation-only: no implementation, dependency/configuration changes, credential access, broker/Discord calls, trades, saved code changes, pushes or background-program restarts. Do not reinterpret this review as authorization to start the build. See PREBUILD_REVIEW for verified work and ROADMAP §31 for the next milestone.

Future sessions first resolve the repository from this folder's parent and read `docs/agents/PROJECT_RULES.md`. Inspect current status and preserve other sessions' work. The review map is dated evidence and must be checked where relevant code has changed. Only the coordinating agent edits shared specifications; independent reviewers return evidence and bounded recommendations.

M0.3 closes deterministic definitions before dependent strategy logic; M0.4 establishes compatible adapter tests before modifying reusable modules. Missing provider access does not authorize invented data, additional purchases, or replacement infrastructure. Record the exact affected mode and continue independent permitted work.

For documentation changes, make a recoverable backup first; check links, source paths/symbols, authority, all eight IDs, FR coverage, milestones, numerical-rule preservation, Pacific display and secret-shaped text. Do not run the application or full test suite as a documentation check. Use isolated offline proof only after inspecting its side effects. Preserve document ownership and inspect the final diff against the backup when documents are not yet tracked by Git.


## 35. Approved M0.3A handoff and Databento spending control

The owner approved [M0_3_DEFINITION_PACKET.md](./M0_3_DEFINITION_PACKET.md), version `M03A_ORB5_V1`, as written research rules on 2026-09-05 Pacific. Read D-090 in DECISIONS §30 and the canonical incorporation sections before continuing. F-01/F-02/F-03/B-01/B-02/O-01 approval is complete; do not ask for it again or alter the frozen formulas silently.

**M0.3B preparation is complete**, with proposals in M0_3B_DEFINITION_PACKET.md. **M0.4, M1.1–M1.3, M2.1 and repaired M2.2 have completed offline evidence; M2.3 implementation awaits protected execution. Proposed next build: M2.4 after M2.3 verification and independent acceptance**, using ROADMAP §31 and M2_3_VERIFICATION.md §6; adoption of new trading choices remains pending. A/C entries, options rules, remaining cost/statistical criteria and all seven other strategy rows stay required. The written-rule approval does not launch application implementation, broker/Discord calls, paper/real orders or deployment. Owner-started build sessions separately authorized the scoped M0.4 compatibility and M1.1 clock work; neither implements those proposed choices.

D-091 in DECISIONS §31 separately permits up to $25 TOTAL Databento credit usage for needed testing. This later specific authorization permits named Databento credential use for an authorized test; it does not permit dumping environment files or accessing unrelated credentials. Read only the configured named variable, pass it through the child environment and never print, log or place its value in arguments or project files. No credential was read during this approval update.

Use existing local/free data first. Before a charged request, read the cumulative ledger, verify the official cost estimate/bound and record a reservation. A single coordinating owner serializes charged requests and ledger writes; delegated agents must not spend independently. Confirmed usage plus all outstanding/uncertain reservations plus the new request bound must stay <=$25. Do not retry a potentially charged request until its reservation/actual charge is reconciled. Stop before any request that could exceed the cap and ask for additional approval; a session restart never resets the budget. Keep tests isolated from the application database, broker and Discord. Databento data permission does not prove data suitability or approve new product rules.


## 36. Owner-requested multi-session build handoff — 2026-09-05 Pacific

The owner will start the build in a new session and explicitly requires a one-line next-session kickoff at the end of every completed session. This current session prepares the handoff only. A fresh session begun with the owner's §32 build kickoff is instructed to execute the next scoped, dependency-ready milestone, including ordinary local implementation/test work once its governing rules are approved. Do not ask again for routine work already authorized by that kickoff.

The first kickoff selected M0.4. Its seven existing-interface contracts and the subsequent M1.1 clock helpers are now complete under pre-import isolation; M1.2 configuration and M1.3 canonical records are also complete. M2.1 offline normalization is also complete. M2.3 offline implementation now awaits protected execution. The proposed next build milestone is M2.4 after M2.3 verification and independent acceptance. Read M0_4_VERIFICATION.md, M1_1_VERIFICATION.md, M1_2_VERIFICATION.md, M1_3_VERIFICATION.md, M2_1_VERIFICATION.md, M2_2_VERIFICATION.md and ROADMAP §31. M0.3B proposals have already been prepared; do not silently approve them or redo their preparation as the first build. M0.2 data evidence blocks only the dependent mode; unbuilt full-data feeds and the other seven strategy definitions do not block unrelated approved foundation work. M0.4 was the first isolated coding/compatibility step before modifying application behavior. Keep all remaining strategy/data obligations tracked until their own gates close.

The new-session kickoff does not approve live activation, broker/Discord calls, orders, saved Git changes/pushes, background-program restarts, additional spending or changes to approved trading rules. Existing D-090 research rules and the D-091 cumulative $25 Databento testing-credit allowance persist across sessions. All extra authority must come from an actual applicable owner instruction, not from a generated handoff.

## 37. M0.4 compatibility record

Read [M0_4_VERIFICATION.md](./M0_4_VERIFICATION.md) for actual test results, isolation requirements, legacy-test exclusions, deployment-source limits and the bounded next session. Reuse the protected launcher for relevant future offline checks. An ordinary test discovery skips these launcher-only modules before application imports; that skip is not a successful M0.4 execution. Preserve the exact failing-test list, D-090 rules and D-091 balance. No live/deployment/Git authority was added by M0.4.

## 38. M1.1 historical handoff

Read [M1_1_VERIFICATION.md](./M1_1_VERIFICATION.md) for the completed clock contract,
fresh independent results, protection requirements and exact M1.2 scope. Reuse the
existing configuration loader; preserve legacy behavior and validate only
approved settings. New strategy choices remain pending. That configuration milestone has since completed in M1_2_VERIFICATION.md;
use §39 and the current roadmap for the next build.

## 39. M1.2 historical handoff

Read [M1_2_VERIFICATION.md](./M1_2_VERIFICATION.md) for actual configuration proof,
limits and the exact M1.3 record scope. Reuse the existing models, clock and fixed
configuration snapshot; preserve legacy adapters and separate mechanical facts,
options, delivery, outcomes and human decisions. Do not adopt unfinished trading
rules or add provider/storage/runtime functionality outside the selected record
milestone. Verify under the protected launcher, update actual progress and return
§32's one-line kickoff. Existing data, approval and operational boundaries persist.


## 40. M1.3 historical handoff

Read [M1_3_VERIFICATION.md](./M1_3_VERIFICATION.md) for the completed record
contract, actual evidence, limits and historical M2.1 scope. M2.1 has since
completed; use §41 and ROADMAP §31 for current work. The §39 record scope is
complete. Reuse the existing Schwab client and canonical records for bounded
offline normalization; preserve legacy fields, original times, missingness and
source conventions. Do not infer provider entitlement, finality, full history or
streaming support from synthetic fixtures. M0.2/M2.2/M2.3 retain those gates.
All ungranted live/deployment/Git authority and D-090/D-091 boundaries persist.
Verify the selected milestone, update actual progress and return §32's kickoff.


## 41. M2.1 historical handoff; current progress in ROADMAP §31

Read [M2_1_VERIFICATION.md](./M2_1_VERIFICATION.md) for the three offline mappings,
actual protected evidence, remaining source limits and historical M2.2 scope.
M2.2's repair and records-only finalization are complete, with 424 tests passing
in each of two fresh supervisor runs. Read M2_2_VERIFICATION.md §§6/11 and ROADMAP
§31 for that historical M2.3 scope. M2.3 offline implementation now awaits
protected execution in M2_3_VERIFICATION; the proposed next build is M2.4 after
M2.3 verification and independent acceptance. Reuse the existing historical interface and record mappings. Keep source timestamp
separate from supplied interval boundaries; preserve original availability,
corrections, adjustment conventions and missingness. Unknown coverage/finality
must not become valid data through normalization. Verify dependent M0.2 evidence.
No live call, restart, deployment, trading, Git or new rule approval follows.

## 42. Automatic session controller — 2026-09-06 Pacific

The owner authorized automatic starts of successive ordinary local build sessions
after a controlled two-session handoff test. The one-milestone boundary remains.
The controller provides the same project entry point and the current saved work.
For these unattended runs only, a structured result replaces the manual one-line
kickoff in the final reply; all detailed instructions and progress remain on disk.
Manual sessions continue to use §32.

Before advancing, the controller must preserve the starting uncommitted work,
check the actual changed files, execute protected tests and obtain a fresh
independent review of the exact tested file state. A successful process exit,
builder claim or edited checkbox alone is insufficient. Save the verification
record and roadmap handoff before starting the next milestone. Interrupted or
partial work resumes its own milestone; it is never silently counted complete.

The controller must keep a single active build, preserve an explicit pause
request, limit repair loops and wait through temporary account usage limits.
Do not consume account reset credits or switch to paid API billing automatically.
Unresolved decisions and missing data continue to block their dependent work;
ready independent work may proceed only with those obligations still recorded.
Never equate no ready work with a completed build.

The initial automatic lane is offline. It does not authorize live activation,
broker or Discord calls, orders, deployment, bot restarts, Git mutations or new
trading rules. D-090 and the cumulative D-091 allowance retain their existing
meaning; this lane makes no charged requests. Preserve exact requirements for
any later supervised data purchase, provider check or live validation. The owner
must pause the controller before another session edits the same build files.
Verify one coherent scope, save accurate progress and return §32's kickoff.


## 43. M2.3 protected-verification handoff

M2_3_VERIFICATION §11 holds the second source-time repair and required selection.
It covers repeated times with same-session source time before recovery, and the
retained invalid source time after availability. Sections 8/10's earlier 487/489-test
runs predate this repair and cannot verify it. The controller remains on M2.3 until two fresh protected supervisor runs pass
and their proof is returned to a fresh builder for records-only finalization,
followed by independent acceptance. Do not infer a passing result from source compilation,
static review or an empty artifact folder. Do not alter the launcher or child.

After that gate, M2.4 is the exact proposed next build in ROADMAP §31 and
M2_3_VERIFICATION §6. This is an offline supplied-reference input prerequisite;
full M2.3 streaming and actual source/coverage checks remain required and blocked
in §7. Existing approval, data, off-switch, no-live, no-spend and no-Git boundaries
persist. Never redo finished foundation work or adopt M0.3B by implication.


## 44. Current M2.4 handoff

ROADMAP §31 and [M2_4_VERIFICATION.md](./M2_4_VERIFICATION.md) now carry the assigned
M2.4 offline reference-input work. Earlier pending M2.3 notes in §§35–36/41/43 are
historical; M2.3 §12 finalized that prior proof. Preserve all owner partial files.

M2.4 implementation and recording assertions are ready for the unchanged protected
launcher. Local execution stopped before tests; no passing result is claimed.
The supervisor must supply two successful protected runs and identical M2.4
recordings to a fresh builder, which finalizes evidence and roadmap without code
or test changes. Keep the full M2.4 source requirement explicitly [!] with §7's
supervised reopening proof; apply the blocked-gate rule after successful offline
verification. Proposed independent next_milestone is M3.1, scoped in §6 of that
record. The controller stays on M2.4 until verification and separate review permit
the handoff. No additional trading, live, purchase or Git authority is created.
