# PROJECT_INDEX.md

## 1. Purpose

This file is the **single entry point for Codex** for all future work on the intraday trading-alert project.

Every fresh Codex session must begin here.

This file defines:
- what the project is;
- which documentation file governs each area;
- required reading order;
- document dependency relationships;
- document conflict-resolution rules;
- approved-decision precedence;
- documentation drift checks;
- how Codex determines what to build next;
- how work must be handed off between fresh sessions.

This file is an **authority router and session entry point**. It does not duplicate the detailed specifications contained in the canonical documents.

## 2. Project Summary

The project is a modular, human-in-the-loop intraday trading-alert platform for U.S. equities, ETFs, and associated listed options.

The intended end-state is:

```text
MARKET DATA
    ↓
NORMALIZED DATA
    ↓
SHARED FEATURES
    ↓
STRATEGY STATE MACHINES
    ↓
HEADS-UP / ACTIONABLE SETUPS
    ↓
STRUCTURAL STOP + TARGETS
    ↓
CONFIDENCE / QUALITY SCORING
    ↓
OPTION CONTRACT ANALYSIS
    ↓
CROSS-STRATEGY DEDUPLICATION / CONFLUENCE
    ↓
DISCORD ALERT
    ↓
HUMAN DISCRETION
    ↓
MANUAL EXECUTION
```

In parallel:

```text
ALL MECHANICAL EVENTS
    ↓
RESEARCH EVENT STORE
    ↓
OUTCOME TRACKING
    ↓
HISTORICAL REPLAY
    ↓
WALK-FORWARD / ABLATION
    ↓
LIVE SHADOW VALIDATION
    ↓
PROMOTE / MODIFY / DISABLE / REJECT
    ↓
CONTINUOUS STRATEGY HEALTH MONITORING
```

The eight approved playbooks are:
1. `CRVOL_ORB5`
2. `HOD_COMP_RS`
3. `OR_FAILURE_REV`
4. `FIRST_PULLBACK_VWAP`
5. `INDEX_OPEN_DRIVE_BREADTH`
6. `GAP_FADE_FAILED_OPEN`
7. `CAT_FIRST_CONSOL`
8. `VP_ACCEPT_LVN`

The system is **not an automated trading system**. It detects, evaluates, scores, records, and alerts. The human trader makes the final decision and manually places any trade.

## 3. Canonical Documentation Set

### `PROJECT_INDEX.md`
[PROJECT_INDEX.md](./PROJECT_INDEX.md)

Single entry point. Responsible for navigation, authority routing, dependency routing, conflict rules, reading order, drift checks, and session start/end instructions.

### `MASTER_SPEC.md`
[MASTER_SPEC.md](./MASTER_SPEC.md)

Top-level project contract. Governs project purpose, scope, non-goals, architecture, platform-wide requirements, and definition of done.

### `PLAYBOOKS.md`
[PLAYBOOKS.md](./PLAYBOOKS.md)

Canonical strategy specification. Governs the exact behavior of all eight trading strategies.

### `DATA_REQUIREMENTS.md`
[DATA_REQUIREMENTS.md](./DATA_REQUIREMENTS.md)

Canonical data specification. Governs actual data availability, required fields/resolution, proxies, degraded modes, and blockers.

### `TESTING_AND_VALIDATION.md`
[TESTING_AND_VALIDATION.md](./TESTING_AND_VALIDATION.md)

Canonical evidence standard. Governs testing, replay, look-ahead protection, walk-forward, ablation, shadow validation, and strategy promotion/rejection.

### `CODING_STANDARDS.md`
[CODING_STANDARDS.md](./CODING_STANDARDS.md)

Canonical engineering standard. Governs implementation structure, typing, configuration, error handling, logging, state ownership, persistence, and versioning.

### `DECISIONS_AND_OPEN_QUESTIONS.md`
[DECISIONS_AND_OPEN_QUESTIONS.md](./DECISIONS_AND_OPEN_QUESTIONS.md)

Decision history and unresolved research register. Explains why decisions exist and what still requires evidence.

### `ROADMAP.md`
[ROADMAP.md](./ROADMAP.md)

Dependency-ordered build plan. Governs milestones, acceptance criteria, blockers, and next work.

### `SESSION_PROTOCOL.md`
[SESSION_PROTOCOL.md](./SESSION_PROTOCOL.md)

Required operating procedure for each fresh Codex implementation session.

## 4. Dependency-Based Document Table

| Document | Depends On | Used By / Feeds Into | Consult When |
|---|---|---|---|
| `PROJECT_INDEX.md` | All canonical documents remaining internally consistent | Every fresh Codex session | Determining where to look, authority, reading order, dependencies, or conflict handling |
| `MASTER_SPEC.md` | Approved project decisions and scope | All supporting documents | Determining purpose, architecture, scope, or non-goals |
| `PLAYBOOKS.md` | `MASTER_SPEC.md`; usable data from `DATA_REQUIREMENTS.md` | Strategy implementation, tests, validation, roadmap | Implementing or reviewing strategy behavior |
| `DATA_REQUIREMENTS.md` | `MASTER_SPEC.md`; inputs from `PLAYBOOKS.md`; repository/API findings | Strategies, degraded modes, validation, blockers | Determining whether an input exists or what fallback is permitted |
| `TESTING_AND_VALIDATION.md` | `MASTER_SPEC.md`; `PLAYBOOKS.md`; `DATA_REQUIREMENTS.md` | Research conclusions, promotion decisions, regression requirements | Testing code or evaluating edge |
| `CODING_STANDARDS.md` | `MASTER_SPEC.md`; behavioral/data contracts | Production implementation | Designing modules, interfaces, config, logging, storage, error handling |
| `DECISIONS_AND_OPEN_QUESTIONS.md` | Findings and decisions from all domains | Canonical-document updates and roadmap changes | Understanding rationale, approved changes, unresolved issues, hypotheses |
| `ROADMAP.md` | All substantive canonical specs | `SESSION_PROTOCOL.md` and implementation sessions | Selecting the next dependency-ready milestone |
| `SESSION_PROTOCOL.md` | `PROJECT_INDEX.md`, `ROADMAP.md`, all canonical requirements | Every fresh coding session | Determining how to execute, test, document, hand off, and stop |

Core flow:

```text
MASTER_SPEC.md
      ↓
PLAYBOOKS.md
      ↕
DATA_REQUIREMENTS.md
      ↓
TESTING_AND_VALIDATION.md
      ↕
CODING_STANDARDS.md
      ↓
ROADMAP.md
      ↓
SESSION_PROTOCOL.md
```

`DECISIONS_AND_OPEN_QUESTIONS.md` interacts with all layers. `PROJECT_INDEX.md` is the navigation and authority router.

## 5. Reading Order

Every fresh session starts with this file, the current ROADMAP section 31 handoff,
and the work packet supplied for its role. Then read the canonical documents or
sections that govern the assigned milestone:

```text
1. PROJECT_INDEX.md
2. ROADMAP.md section 31 and the named milestone acceptance criteria
3. SESSION_PROTOCOL.md sections that govern the assigned role
4. Relevant MASTER_SPEC, PLAYBOOKS, DATA_REQUIREMENTS,
   TESTING_AND_VALIDATION, CODING_STANDARDS, and
   DECISIONS_AND_OPEN_QUESTIONS sections named by the work packet or discovered
   dependency
```

Read a whole canonical document only when the assignment spans that whole domain,
a conflict cannot be resolved from the relevant section, or a dependency is not
yet known. Read PREBUILD_REVIEW.md or older milestone evidence only to investigate
a related repository fact or historical claim. They cannot override a canonical
requirement. Initial implementation, repair, independent review, and records-only
finalization receive different bounded reading packets. Fixed safety, authority,
missingness, point-in-time, off-switch, and definition-of-done rules remain in
every packet.

## 6. Document Authority and Decision Precedence

The project uses **scoped authority**.

### 6.1 Highest substantive authority

`MASTER_SPEC.md` governs:
- project scope;
- project goals;
- system-wide architecture;
- explicit non-goals;
- platform-wide requirements.

### 6.2 Domain authorities

Within approved scope:

```text
PLAYBOOKS.md
→ trading-strategy behavior

DATA_REQUIREMENTS.md
→ data availability, proxies, degraded modes

TESTING_AND_VALIDATION.md
→ testing and evidence standards

CODING_STANDARDS.md
→ implementation conventions
```

The more specific canonical document governs details within its domain.

### 6.3 Approved-decision precedence

An **explicitly approved decision** recorded in `DECISIONS_AND_OPEN_QUESTIONS.md` may supersede an older requirement when clearly marked approved and representing a later project decision.

Required synchronization:

```text
APPROVED DECISION
        ↓
identify affected canonical document
        ↓
update that canonical document
        ↓
version strategy/config if required
        ↓
update ROADMAP.md if implementation work follows
```

When approval and chronology are clear:

```text
LATEST EXPLICITLY APPROVED PROJECT DECISION
>
OLDER CONFLICTING REQUIREMENT
```

Codex cannot declare its own proposal approved.

### 6.4 Open questions never override requirements

`OPEN QUESTION`, `HYPOTHESIS`, `OBSERVATION`, `NEEDS VALIDATION`, `BLOCKED BY DATA`, and `PROPOSED CHANGE` do **not** override established project requirements, approved decisions, or document authority.

### 6.5 Rejected alternatives never override requirements

`REJECTED` items exist for historical context only.

### 6.6 Software convenience never overrides domain behavior

If engineering convenience conflicts with strategy behavior, `PLAYBOOKS.md` wins on trading behavior. If desired behavior depends on unavailable data, `DATA_REQUIREMENTS.md` wins on what can actually be supplied. If methodology is invalid, `TESTING_AND_VALIDATION.md` wins on whether evidence can be trusted.

## 7. Conflict Resolution Procedure

If documents appear to conflict:

```text
1. Identify the exact conflicting statements.
2. Determine whether one is only an open question, hypothesis, observation, or rejected alternative.
3. Check for a later explicitly APPROVED decision.
4. If one exists, treat it as the intended newer requirement and synchronize affected canonical docs.
5. Otherwise apply MASTER_SPEC.md for project-wide requirements.
6. Apply the relevant domain authority.
7. Do not invent a compromise or promote an open question into a decision.
8. If material conflict remains unresolved, record it and block affected implementation if necessary.
```

## 8. Important Cross-Document Relationships

`PLAYBOOKS.md` + `DATA_REQUIREMENTS.md` jointly determine whether a strategy runs as `FULL`, `PROXY`, `DEGRADED`, or `BLOCKED BY DATA`.

`PLAYBOOKS.md` defines current approved rules; `TESTING_AND_VALIDATION.md` determines whether those rules demonstrate useful edge.

`PLAYBOOKS.md` defines behavior; `CODING_STANDARDS.md` defines implementation structure.

Only approved decisions may supersede older requirements. Open questions, hypotheses, observations, and rejected alternatives never do.

## 9. Documentation Drift Check

Every fresh implementation session checks the assigned milestone and affected
documents for drift before editing. A broad project-wide drift audit is required
only for a project-wide documentation or architecture assignment.

Required start-of-session check:

```text
[ ] Strategy IDs and versions agree across documents.
[ ] ROADMAP milestone assumptions match MASTER_SPEC and domain specs.
[ ] PLAYBOOK inputs agree with DATA_REQUIREMENTS availability/proxy rules.
[ ] Validation requirements are reflected in ROADMAP implementation milestones.
[ ] CODING_STANDARDS does not prescribe behavior that changes approved strategy logic.
[ ] Approved decisions have been propagated to affected canonical docs.
[ ] Open questions/hypotheses have NOT been treated as approved requirements.
[ ] Completed ROADMAP milestones agree with repository state.
[ ] Documentation references and filenames remain valid.
[ ] PROJECT_INDEX still lists all nine canonical documents and the non-authoritative review record.
[ ] All eight playbooks and FR-001 through FR-031 have a capability-map row and milestone owner.
[ ] Every required additional capability in the review map remains tracked through completion or an explicit blocker.
[ ] Proposed resolutions have not been mistaken for approval.
[ ] Early shadow dependencies include storage, delivery isolation, options outcome, and deduplication.
[ ] Visible times use Pacific and preserve the specified market instants.
```

Minor drift may be corrected during the selected session. Material drift affecting the next milestone must be resolved before implementation, or the work must be marked blocked if no approved resolution exists.

If an approved newer decision exists but the governing canonical document still contains the old rule, that is documentation drift and must be synchronized.

If code or docs adopt an unresolved open question/hypothesis as approved, restore the established requirement unless a valid approval record exists.

## 10. Continuing Work Across Fresh Codex Sessions

`ROADMAP.md` = **WHAT COMES NEXT**.

`SESSION_PROTOCOL.md` = **HOW TO DO IT SAFELY**.

Every fresh session should read the roadmap, run the drift check, find the earliest dependency-ready unfinished milestone, confirm prerequisites, implement only that coherent scope, test, update docs, and stop.

## 11. START HERE FOR CODEX

At the beginning of every new session:

```text
You are continuing the intraday human-in-the-loop trading-alert project.

Treat the repository documentation as durable project memory.
Do not rely on prior chat context.

1. Read PROJECT_INDEX.md as the authority map and read ROADMAP section 31.
2. Read the work packet and the canonical sections it names for the assigned
   milestone and role.
3. Read additional canonical or implementation sections only when a discovered
   dependency, conflict, or missing fact requires them.
4. Inspect git status, relevant changes, existing modules, tests,
   configuration, integrations, and reusable functionality.
5. Perform the drift check for the assigned milestone and affected documents.
6. Resolve minor documentation drift immediately.
7. If material drift affects the next milestone, resolve it from an
   existing approved decision if possible; otherwise mark work blocked.
8. Select the earliest dependency-ready unfinished ROADMAP milestone.
9. Confirm it is not blocked by missing prerequisites, required data,
   or unresolved specification conflict.
10. Search existing code before creating new functionality.
11. Implement only one coherent, testable milestone or tightly bounded prerequisite.
12. Preserve approved strategy logic.
13. Follow DATA_REQUIREMENTS for unavailable data; never invent a feed.
14. Keep underlying setup validity separate from options quality.
15. Keep mechanical alerts separate from human decisions.
16. Keep replay/historical logic point-in-time safe.
17. Add/update required tests.
18. Run applicable tests, lint, type checks, and repository validation.
19. Fix regressions introduced by the session.
20. Update ROADMAP and affected canonical docs.
21. Record blockers, hypotheses, unresolved issues, and durable decisions.
22. Perform an end-of-session documentation drift check.
23. Stop after the selected milestone.
```

## 12. During Implementation

Continuously verify:
- Am I changing approved strategy behavior?
- Am I treating an open question as approved?
- Am I assuming unavailable data exists?
- Am I duplicating shared functionality?
- Am I introducing look-ahead?
- Am I mixing options quality with underlying validity?
- Am I mutating historical alert facts?
- Am I expanding scope?
- Am I outside the selected milestone?
- Have I created documentation drift?

## 13. Strategy Changes

Material strategy changes require:

```text
OBSERVATION
↓
HYPOTHESIS
↓
VALIDATION
↓
APPROVED DECISION
↓
NEW STRATEGY / CONFIG VERSION
↓
PLAYBOOKS.md UPDATE
↓
ROADMAP / DECISION UPDATE
```

An observation or hypothesis alone never changes the approved rule.

## 14. Data Discoveries

When repository/API inspection changes a data assumption from `PROVISIONAL` to `CONFIRMED` or `BLOCKED BY DATA`, update `DATA_REQUIREMENTS.md` in the same session.

## 15. Research Results

Research output becomes a hypothesis, not production logic, until validated and explicitly approved.

## 16. END OF SESSION

Before stopping:

```text
[ ] Selected milestone is complete or accurately marked partial.
[ ] Relevant tests were run.
[ ] Introduced regressions were fixed.
[ ] Lint/type checks were run where configured.
[ ] Diff was reviewed.
[ ] No secrets were introduced.
[ ] ROADMAP.md updated.
[ ] DATA_REQUIREMENTS.md updated if data capability changed.
[ ] DECISIONS_AND_OPEN_QUESTIONS.md updated as needed.
[ ] PLAYBOOKS.md updated only for approved/versioned strategy change.
[ ] MASTER_SPEC.md updated only for genuine project-wide change.
[ ] TESTING_AND_VALIDATION.md updated if evidence methodology changed.
[ ] CODING_STANDARDS.md updated if durable engineering standards changed.
[ ] PROJECT_INDEX.md updated if ownership/dependencies/authority/reading order changes.
```

End-of-session drift check:

```text
[ ] Approved decisions propagated to affected canonical docs.
[ ] No unresolved item accidentally promoted to approved rule.
[ ] ROADMAP reflects actual implementation.
[ ] Data statuses reflect discovered capabilities.
[ ] Strategy rules remain synchronized with implementation.
[ ] Validation docs remain synchronized with research/replay behavior.
[ ] No stale paths, IDs, versions, or milestones introduced.
[ ] PROJECT_INDEX still routes authority correctly.
```

Required final report:
1. WHAT WAS COMPLETED
2. FILES CHANGED
3. TESTS PERFORMED / RESULTS
4. KNOWN ISSUES / OPEN QUESTIONS
5. EXACT NEXT ROADMAP MILESTONE
6. READY-TO-COPY PROMPT FOR THE NEXT FRESH CODEX SESSION

Then stop.

## 17. Documentation Synchronization Rule

No material decision should exist only in chat history, Codex output, commit messages, or temporary notes.

Desired steady state:

```text
APPROVED DECISION
=
DECISION RECORD
+
UPDATED GOVERNING CANONICAL DOCUMENT
+
VERSION CHANGE WHERE REQUIRED
+
ROADMAP UPDATE IF WORK REMAINS
```

Open questions remain research items until explicitly resolved and approved.

## 18. Project Documentation Dependency Map

```text
                         PROJECT_INDEX.md
                               │
                               ↓
                        MASTER_SPEC.md
                               │
        ┌──────────────────────┼─────────────────────┐
        │                      │                     │
        ↓                      ↓                     ↓
   PLAYBOOKS.md      DATA_REQUIREMENTS.md   TESTING_AND_VALIDATION.md
        │                      │                     │
        └──────────────┬───────┴─────────────┬───────┘
                       ↓                     ↓
                CODING_STANDARDS.md   DECISIONS_AND_OPEN_QUESTIONS.md
                       │                     │
                       └─────────┬───────────┘
                                 ↓
                            ROADMAP.md
                                 │
                                 ↓
                        SESSION_PROTOCOL.md
                                 │
                                 ↓
                       FRESH CODEX SESSION
```

## 19. Final Codex Principle

Assume the original research conversation no longer exists and the repository documentation is the complete project memory.

```text
read before coding
check for drift before implementing
inspect before replacing
implement before expanding
test before claiming completion
validate before claiming edge
synchronize approved decisions
never promote open questions into requirements
document before stopping
```

## 20. Repository-aware prebuild review

The repository is the parent of this document directory. The existing application is the Python package `consensus_engine`; this folder is design documentation, not a new application root. Read [project working rules](../docs/agents/PROJECT_RULES.md) and [documentation checks](../docs/agents/WORKFLOWS.md).

[PREBUILD_REVIEW.md](./PREBUILD_REVIEW.md) records the 2026-09-05 Pacific review, capability map, source/test evidence, findings, blockers, and unapproved proposals. It preserves the nine-document authority hierarchy. Repository facts describe the existing system; canonical requirements describe the intended extension. A dated code finding does not approve a trading-rule change.

The review made documentation corrections only. It did not implement or activate any strategy. Read ROADMAP §31 for current progress and the exact next milestone. For a review-only session, the user's no-code/no-deployment/no-git-mutation boundary takes precedence over implementation and session-close instructions above.


## 21. M0.3 decisions and next work — 2026-09-05 Pacific

[M0_3_DEFINITION_PACKET.md](./M0_3_DEFINITION_PACKET.md), version `M03A_ORB5_V1`, is now owner-approved for written research rules under D-090. It remains a supporting packet; PLAYBOOKS §14, DATA_REQUIREMENTS §34 and TESTING_AND_VALIDATION §51 incorporate its exact relevant sections under their existing authority. All eight playbooks remain in scope. No application implementation or live activation is approved by this decision.

M0.3A definition/approval work is complete. M0.3B preparation is now complete in [M0_3B_DEFINITION_PACKET.md](./M0_3B_DEFINITION_PACKET.md); its new trading choices remain proposed for owner decision. **M0.4, M1.1–M1.3, M2.1–M2.4 and M3.1's bounded offline row have completed evidence.** [M3_1_VERIFICATION.md](./M3_1_VERIFICATION.md) §16 records two fresh protected runs of 591 tests, including all 54 M3.1 cases. The earlier 587-test proof is historical and preserved. **Proposed independent next build: M3.2 after independent review**, bounded by ROADMAP §31 and M3_1_VERIFICATION §§5–6. Required M2.3/M2.4/M3.1 source branches remain blocked. The full M0.3 gate remains incomplete; unfinished values were not approved by implication. Do not request the already granted D-090 approval again.

The owner also authorized **up to $25 total Databento credit usage for testing**, D-091. DECISIONS §31 holds the cumulative budget and reservation rules. More than $25 requires explicit owner approval; the allowance does not reset across sessions or agents. Paid testing is optional when needed; this update used $0. All other no-implementation/no-Discord/no-trade/no-deployment boundaries continue.


## 22. Start and finish each build session

The owner requested a multi-session build and a one-line next-session kickoff after every session. Follow SESSION_PROTOCOL §§31–32 and §36: read the role packet and relevant canonical sections, execute one coherent dependency-ready milestone, verify it, record the actual result and exact next step, then end the final reply with the single-line kickoff. This is required, not an optional follow-up offer. All detailed instructions stay in these files.

**M3.1’s fifth offline repair has completed protected proof. Proposed independent next build after review: M3.2**, using ROADMAP §31 and M3_1_VERIFICATION §§5–6/16. Both fresh runs passed 591 tests, including all 54 M3.1 cases, with matching test IDs and 67,989-byte recordings. The 587-test/50-case results remain historical. The required M3.1 full-data/source gate stays blocked. M0.3B now has concrete proposals and worked cases; do not redraft them or treat them as approved. Verify M0.2 data coverage for the chosen path before dependent data claims or code. M0.4 proved the specified existing-interface contracts; M1.1 added the shared clock and M1.2 added validated fixed configuration snapshots with compatible legacy behavior. Full definitions/data for all eight strategies need not be complete before independent approved foundation work; each unresolved choice blocks its own dependent path.

The handoff preparation was documentation only; the first owner-started build session has now completed M0.4. When the owner starts a fresh build session with the SESSION_PROTOCOL §32 kickoff, carry out ordinary local work allowed by the next scoped milestone without asking again for routine implementation permission. Preserve approved-rule and dependency gates, the cumulative $25 Databento limit, and all ungranted live/deployment/trading/Git authority. The kickoff must not manufacture approval for unresolved product choices. Check ROADMAP §31 for later progress; do not keep replaying this dated first-session instruction after M0.4 is complete.

## 23. Completed first build — 2026-09-05 Pacific

[M0_4_VERIFICATION.md](./M0_4_VERIFICATION.md) is a supporting execution/evidence record, not a new canonical specification. It records C04-01–C04-07, isolated commands/artifacts, source preservation, legacy limitations and the exact M1.1 handoff. ROADMAP §31 remains the current progress authority. All nine canonical documents, eight strategies and remaining data/approval gates retain their scope.

## 24. Completed shared clock — 2026-09-05 Pacific

[M1_1_VERIFICATION.md](./M1_1_VERIFICATION.md) records the six additive clock helpers,
41 new fixed-input cases, independent 125-test runs, unchanged legacy functions,
and its historical M1.2 handoff. It is a supporting evidence record, not a tenth
canonical specification. Clock boundaries do not prove data finality or complete
AT-02. No trading rule, live activation, spending or Git authority was added.

## 25. Completed configuration foundation — 2026-09-05 Pacific

[M1_2_VERIFICATION.md](./M1_2_VERIFICATION.md) records the strict configuration
namespace, immutable session copy, secret-free version/hash and independent
194-case runs passing twice. All new switches are off and unfinished trading
values remain unset. This supporting evidence adds no trading/data/activation
approval. That session handed off M1.3; use ROADMAP §31 for current progress.


## 26. Completed canonical records — 2026-09-06 Pacific

[M1_3_VERIFICATION.md](./M1_3_VERIFICATION.md) records immutable typed market,
feature, candidate and linked result records, configuration attribution and
independent protected tests. No provider, storage or strategy runtime is activated.
That session handed off M2.1, bounded offline normalization beside the existing
Schwab client; it has since completed. Use ROADMAP §31 for the next step. The nine canonical authorities and remaining approval/data gates
are unchanged.

## 27. Completed offline Schwab normalization — 2026-09-06 Pacific

[M2_1_VERIFICATION.md](./M2_1_VERIFICATION.md) records three pure raw-response
mappings, protected synthetic tests, independent compatibility evidence and
unchanged legacy interfaces. Original times, missingness, exact option identity
and caller-supplied bar boundaries remain explicit. Current provider coverage,
finality, streaming and dynamic freshness gates remain open. That session handed
off M2.2; its review repair and fresh protected proof are now complete in
M2_2_VERIFICATION §11. Proposed next build after repaired M2.2
passes independent acceptance review: M2.3, using ROADMAP §31 and
M2_2_VERIFICATION §6. Existing approval, spending,
live/deployment and Git boundaries are unchanged.

## 28. Automatic session starts — 2026-09-06 Pacific

The owner authorized a background controller to start successive local build
sessions after a controlled two-session handoff test. See SESSION_PROTOCOL §42.
Each session still handles one coherent dependency-ready milestone. A separate
review and fresh protected-test evidence must pass before the next milestone
starts. The controller reads the current roadmap; it never counts session exits
as completed milestones. Existing strategy, data, spending and live-operation
boundaries persist. This authorizes automatic local session starts, not approval
of unresolved product choices or deployment. Setup evidence is machine-local;
this entry does not claim that the controller or any new milestone has passed.

[AUTOMATION_VERIFICATION.md](./AUTOMATION_VERIFICATION.md) now records the completed
controller checks and real fixture handoff. That setup evidence does not itself
complete a build milestone; use ROADMAP §31 for the build's current status.

## 29. M2.2 proof finalized; acceptance review pending — 2026-09-06 Pacific

[M2_2_VERIFICATION.md](./M2_2_VERIFICATION.md) §§10–11 record the repair and fresh proof:
unknown evidence-reference labels cannot establish complete coverage. Four added
test cases cover both labels, mixed case and outer spaces. The required protected
selection includes two existing peer-history caller tests omitted earlier.
[M2_2_LOCAL_CHECKS.json](./M2_2_LOCAL_CHECKS.json) saves the inspected publication
hashes, source identity and fresh results: **424 tests passed in each of two
protected runs**, including 75 historical-interface cases and both peer-history
callers. Test IDs and history outputs match, with no unexpected isolation denials.
All 771 saved file contents matched before this records-only finalization; code,
tests and protection are unchanged. The earlier 418-test results and launcher
errors remain historical. Status: **completed** for the bounded offline contract
and evidence handoff. The supervisor's separate review still decides acceptance.

**Proposed exact next milestone: M2.3**, after independent M2.2 acceptance, the offline normalized Quote event/continuity
prerequisite in M2_2_VERIFICATION §6 and ROADMAP §31. Full streaming integration,
provider access/field/cadence/coverage/capacity proof and supervised live checks
remain required under M0.2/M2.3. An offline prerequisite cannot complete those
branches. At that historical handoff M0.3B remained proposed; D-092 and the
later frozen research sections now carry current definition status. All eight
playbooks, full-data modes and later roadmap obligations remain intact. All
switches remain off, and no spending or live authority is added. ROADMAP §31
carries the current next step.


## 30. M2.3 review repair awaiting protected proof — 2026-09-06 Pacific

[M2_3_VERIFICATION.md](./M2_3_VERIFICATION.md) §11 records the second offline Quote
event/continuity repair. A same-session source time before recovery cannot leave
an earlier healthy quote usable when quote/trade times repeat. A source time after
availability stays visibly invalid, including after the clock catches up. The two
named tests and 43-decision recording case are expanded; fresh protected execution
is pending. Sections 8/10's earlier 487/489-test runs are historical.
[M2_3_LOCAL_CHECKS.json](./M2_3_LOCAL_CHECKS.json) separates current local checks
from those old results. No passing repair result is claimed. The supervisor must
supply two successful protected runs and identical repaired recording proof;
a fresh builder then finalizes evidence/roadmap without code/test changes.

**Saved proposed next_milestone: M2.4**, after M2.3 verification and independent
acceptance. Its exact offline reference-input scope is in M2_3_VERIFICATION §6.
The full M2.3 live-provider branch remains a required blocked row, with its
supervised reopening proof in §7 of that record. Earlier M2.2-to-M2.3 handoffs
above are historical; ROADMAP §31 remains current. M0.2, M0.3B adoption, the other
seven definitions and all later/full-data features remain open. No live switch,
provider call, purchase, new trading rule or profitability claim is added.


## 31. M3.1 regular-session ATR and interval repair — proof finalized

[M3_1_VERIFICATION.md](./M3_1_VERIFICATION.md) §§15–16 record the repair and its
fresh protected proof.
Minute ATR now limits its previous close to the regular session, including after
a certified no-trade open. Core minute and daily calculations reject a history
request with the wrong interval instead of treating one minute as a daily bar or
one daily bar as a minute session.

The test file contains **54 M3.1 cases**, with all earlier cases preserved.
The compact end-to-end recording now covers both mixed-session ATR paths and both
wrong-interval paths. Both fresh protected runs passed **591 tests**, including all
54 M3.1 cases, with identical ordered test IDs and identical **67,989-byte** compact
recordings. Isolation and cleanup were clean.
[M3_1_LOCAL_CHECKS.json](./M3_1_LOCAL_CHECKS.json) and
[M3_1_VERIFICATION.md](./M3_1_VERIFICATION.md) §16 save the current proof.
[M3_1_LAUNCHER_LIMITATION.txt](./M3_1_LAUNCHER_LIMITATION.txt) preserves the earlier
local sandbox error as historical evidence. The previous 587-test proof and all
older runs are historical.

ROADMAP §31 remains current. Its M3.1 offline row is `[x]` and its separate
required full-data/source row stays `[!]`. Saved proposed **next_milestone: M3.2**
remains after independent review. M2.3 §12 and M2.4 §9 finalized
their offline proof; earlier pending notes above and in other canonical files are
historical. Full eligible-trade VWAP, actual opening-trade evidence, trade conditions,
cancels/corrections and compatible actual histories still require the separately
supervised reopening proof in M3_1_VERIFICATION §6.

All nine canonical authorities, eight playbooks, unfinished definitions and later
features remain tracked. All switches stay off. No live access or purchase is
needed for this repair; D-091 remains $0 used and $0 reserved. No trading edge is claimed.

## 32. M3.2 supplied-Bar participation — offline proof complete

[M3_2_VERIFICATION.md](./M3_2_VERIFICATION.md) records the current assigned
M3.2 slice. Three D-090 F-02 calculations and 46 protected cases are implemented:
opening-five-minute RVOL, full-window premarket RVOL and the prior-20-session
close-times-share-volume median. Both fresh supervisor runs passed 637 tests,
including all 46 M3.2 cases, within the unchanged limit. Ordered test IDs and
10,041-byte compact recordings match; isolation and cleanup were clean.
Independent review remains. [M3_2_LOCAL_CHECKS.json](./M3_2_LOCAL_CHECKS.json)
records the proof.
Earlier M3.1-to-M3.2 handoffs above are historical; ROADMAP §31 is current.

The supervisor's earlier first run and second-run timeout are historical.
M3_2_VERIFICATION §7 records the test-only repair, and §8 records its successful
fresh proof. Production and protection code did not change during the repair or
records-only finalization.

Required M3.2 general same-time/cumulative definitions, tape/projection source
coverage and actual compatible histories stay blocked in M3_2_VERIFICATION §5.
Records-only finalization keeps that gate open and returns blocked. Proposed
independent next_milestone: **M3.6**, bounded
in §6 of that record. M3.3–M3.5 definitions and all later features remain tracked.
No proposed rule, live access, purchase or profitability claim is added.

## 33. M3.6 supplied-Bar opening range — request-window repair proved

[M3_6_VERIFICATION.md](./M3_6_VERIFICATION.md) records the current assigned
M3.6 work. The pure calculation and all 28 protected cases have completed proof.
It uses the five scheduled regular-session opening minutes and exposes no completed high, low, mid
or width until every interval is final and available and at least one traded.
Certified no-trade minutes add no invented prices. All switches remain off.

The supervisor's fresh proof at 19:48:40 Pacific passed 665 tests in each of two
protected runs, including all 28 repaired M3.6 cases. Ordered IDs match, isolation
and cleanup were clean, and the compact 9,379-byte records are byte-identical.
M3_6_VERIFICATION §12 is the final record. The offline row is complete; the
separate actual-source row remains blocked. The saved independent next milestone
is M4.1 after review.

### Historical local attempts and superseded proof

The following pending states describe earlier attempts. They are superseded by
the finalized 665-test proof above and M3_6_VERIFICATION §12.

The local unchanged protected launcher stopped before collection at its initial
ownership step with the exact error saved in M3_6_LAUNCHER_LIMITATION.txt. No test
pass was claimed then. The supervisor needed to run the saved selection twice and
return XML, isolation and compact recording files for records-only finalization.
ROADMAP §31 remains the progress authority.

M3_6_VERIFICATION §8 records the retry at 18:54 Pacific. That supervisor failure
summary contained no proof files or readable artifact path. The saved source/test/
protection hashes matched; that repair changed records only. Its 26 written cases
had not been collected by the local launcher. The offline status was then
**ready_for_verification** until fresh proof could be supplied.

A later test-only repair now builds only the five Bars used by the broad-request
case instead of building a full regular session first. It preserved all 26 cases
and assertions. The protected launcher still stopped before collection at 19:11
Pacific, and no supervisor proof files were supplied. M3_6_VERIFICATION §9 records
that attempt's test hash and exact result.

Historical supervisor proof is recorded in M3_6_VERIFICATION §10. Both protected
runs passed 663 tests, including all 26 M3.6 cases, with identical ordered IDs and
identical 7,237-byte compact recordings. Isolation and cleanup were clean. The
earlier launcher failures above remain historical.

M3_6_VERIFICATION §11 records the request-window review repair. A HistoryBatch
archive can contain Bars outside its original request, so the feature now requires that
the supplied request itself cover all five opening intervals. Truncated and
disjoint requests remain incomplete even when their archives contain the Bars.
That brought the count to 28 cases and added both paths to the compact proof. The
§10 proof predates that source and test change. Status was **ready_for_verification**
until the successful runs now finalized in §12. The local 19:37 Pacific launcher
attempt stopped before collection at its initial ownership
step; M3_6_VERIFICATION §11 saves the exact result.

### Required source gate and independent next work

Actual source/finality/correction coverage stays blocked under M0.2/M2.2 and the
M3.6 evidence record. Proposed independent next_milestone after review:
**M4.1**, the shared strategy interface. M3.3–M3.5 and M0.3B remain
unfinished and are not adopted or removed. No live access, purchase, new trading
rule or profitability claim is added.

## 34. M4.1 shared strategy interface — protected proof complete

[M4_1_VERIFICATION.md](./M4_1_VERIFICATION.md) records the assigned common
interface and 55 passing protected cases. It uses the existing canonical records
for features, state transitions, candidates, confidence and risk. The long/short
end-to-end proof uses supplied Bars, actual shared calculations and a test-only
strategy. No real playbook, live consumer or new trading rule is implemented.

Both supervisor runs passed **720 tests**, including all **55 M4.1 cases**, with
matching ordered test IDs, clean isolation and cleanup, and byte-identical long
and short records. M4_1_VERIFICATION §7 and M4_1_SUPERVISOR_TESTS.json record the
verified proof; M4_1_LOCAL_CHECKS.json separates the current completed status from
the historical failed local attempt and ownership notes. Records-only
finalization is complete. The separate reviewer still decides acceptance before
the controller advances. Saved proposed `next_milestone`: **M4.2**,
bounded in M4_1_VERIFICATION §5 and ROADMAP §31. Earlier M4.1 handoffs above are
historical. All source and definition gates remain open with their existing owners.

## 35. M4.2 state changes and storage — expanded protected proof complete

[M4_2_VERIFICATION.md](./M4_2_VERIFICATION.md) records the implemented common
transition engine and append-only storage. Rules are explicitly supplied, state
advances only after storage succeeds, and migration 35 preserves the existing
database. Full feature/candidate/delivery storage and recovery remain M5 work.

**Current status: completed** for independent acceptance review. Both fresh
protected runs passed **826 tests**, including all **56 M4.2 cases** and the four
database checks added after review. Ordered IDs match, isolation and cleanup
passed, and long/short end-to-end recordings are identical across runs. All 39
published artifact hashes and all 808 tested file contents matched before
records-only finalization. M4_2_VERIFICATION §13 and M4_2_LOCAL_CHECKS.json save
the expanded proof. No code, test, configuration or protection file changed.

The supervisor's separate reviewer decides acceptance before the controller
advances. Saved proposed `next_milestone`: **M4.3**, within M4_2_VERIFICATION §5
and ROADMAP §31.
All 16 milestone paths, earlier owner inputs and unfinished source/definition
rows remain tracked. All switches stay off. No live access, spending, new trading
rule or profitability claim is added.

### Historical M4.2 attempts and first finalization

M4_2_VERIFICATION §§3/7–9 preserve the earlier local ownership errors and supervisor
timeouts. Section 10 records the later two runs with 817 passes and five failures,
then the protected configuration-fixture repair. Their pending states describe
those attempts only. They do not contradict the successful earlier selection below.

Section 11 records the **23:07:35 Pacific** proof: both runs passed 822 tests,
including all 56 M4.2 cases and the repaired market configuration checks. Long
and short M4.2 records and affected M3.1/M2.4 records match. The publication holds
XML, logs, isolation and recordings; the tested-file manifest is separate.
The first finalization marked M4.2 completed, but review reopened verification
because four database checks had been omitted. Section 12 records that repair;
section 13 now finalizes its expanded proof.
The 822-test results remain verified evidence for their earlier selection; they
are not proof of the expanded 18-selector selection. No historical failure or
premature completion status is the current handoff.

## 36. M4.3 supplied risk and targets — protected proof complete

[M4_3_VERIFICATION.md](./M4_3_VERIFICATION.md) records the assigned D-090 §6
supplied-input selector and its protected cases. Existing canonical features,
risk and target records are reused. Stops round outward to the known increment;
exact extension and reward limits apply only with complete supplied family
coverage. Unknown inputs cannot become a passing result. No live consumer is added.

Both fresh supervisor runs passed **892 tests**, including all **105 M4.3 cases**,
with matching ordered IDs, clean isolation/cleanup and byte-identical long/short
recordings. M4_3_VERIFICATION §8 and M4_3_LOCAL_CHECKS.json save the proof.
M4_3_LAUNCHER_LIMITATION.txt preserves the earlier local failure as history.
The separate reviewer decides acceptance.
The required full structure/definition/source row stays [!] under §4 of that
record, even after the offline row completes. Proposed independent next_milestone:
**M4.4**, within M4_3_VERIFICATION §5 and ROADMAP §31. All prior unfinished work,
M0.3B proposals and live/data/approval boundaries remain intact. All switches stay
off; D-091 remains $0 used/$0 reserved. No trading returns are established.

## 37. M4.4 supplied confidence — protected proof complete

[M4_4_VERIFICATION.md](./M4_4_VERIFICATION.md) records the assigned offline
composition boundary. It combines explicitly supplied Setup/Context/Execution
scores, preserves exact weights and factor versions, and retains original
feature/session/configuration details. Missing factors yield no confidence.
Canonical records, legacy scores and all switches remain unchanged.

Both fresh supervisor runs passed **949 tests**, including all **68 M4.4 cases**,
with matching ordered IDs, clean isolation/cleanup and byte-identical long/short
recordings. M4_4_VERIFICATION §8 and M4_4_LOCAL_CHECKS.json save the proof.
M4_4_LAUNCHER_LIMITATION.txt preserves the earlier local failure as history. The
separate reviewer decides acceptance.

Required full factor definitions, missingness/freshness policy and actual source
readiness remain blocked in §4 of the evidence record. After offline proof,
retain separate [x]/[!] rows and return blocked with proposed independent
**next_milestone: M4.5**, bounded in §5. ROADMAP §31 is current. Earlier handoffs
above remain historical. M0.3B is not adopted, all prior unfinished work remains,
and no live access, purchase or profitability claim is added.

## 38. M4.5 supplied candidate assembly — protected proof complete

[M4_5_VERIFICATION.md](./M4_5_VERIFICATION.md) records the assigned common
assembly boundary. Existing AlertCandidate, SuppressionEvent and ConfluenceLink
records remain unchanged. The new pure functions check supplied context, geometry,
full confidence attribution, component links and explicit expiry instants.
Suppression records keep the caller's reason separate from original alert facts.
No strategy, score cutoff, cooldown, confluence priority or live consumer is added.

Both fresh protected runs passed **1,045 tests**, including all **96 M4.5 cases**,
with matching ordered IDs, clean isolation/cleanup and byte-identical long/short
recordings. M4_5_VERIFICATION §8 and M4_5_LOCAL_CHECKS.json save the proof. The
local launcher failure remains historical. Proposed next_milestone: **M4.6**,
bounded in M4_5_VERIFICATION §5 and ROADMAP §31, after independent review.
All prior source/definition/approval gates and all switches remain unchanged.

## 39. M4.6 offline delivery — primary-attribution repair proof complete

[M4_6_VERIFICATION.md](./M4_6_VERIFICATION.md) §13 finalizes the current repair.
Delivery reuses complete assembly checks before storage or sending. Both fresh
protected runs passed **1,193 tests**, including all **130 M4.6 cases** and **48
new rejection cases**. Ordered IDs match; isolation and cleanup passed. Expanded
long/short recordings match at **28,043/28,094 bytes** and retain all rejected paths.

Status: **completed for independent review**. All 55 published hashes and all 828
tested file contents matched before records-only finalization. Code, tests and
protection remain unchanged. M4_6_LOCAL_CHECKS.json saves the inspected proof.
Earlier 1,145-test/82-case proof and local launcher errors remain historical.
ROADMAP §31 retains the completed offline row and the proposed next_milestone:
**M5.1**, within M4_6_VERIFICATION §5, after independent acceptance.

That M4.6 handoff's M4.7 `[!]` and M0.3B-proposed statements are historical.
D-100 and `M47_FIRST4_RESEARCH_V1` now freeze the minimum first-four option and
portfolio definitions, while ROADMAP section 31 records implementation awaiting
protected proof. All earlier source, historical execution, calibration and live
branches stay required. All switches remain off.

## 40. M5.1 typed append-only research event store — repair proof complete

[M5_1_VERIFICATION.md](./M5_1_VERIFICATION.md) records the assigned M5.1 storage
scope. `consensus_engine/event_store.py` adds `ResearchEventStore` (M51_V1);
`consensus_engine/db.py` adds the append-only `trade_alerts_research_events_v1`
table and bumps the schema version to 36. It resolves and retains typed supplied
records (raw input, feature snapshot, state transition, candidate, component,
suppression, option result, configuration, delivery intent/result), rejects
conflicting ids/links, keeps missing data visible, and proves atomic rollback,
idempotent retry and reopen in a recording sink.

M5_1_VERIFICATION section 15 finalizes the repairs in sections 10–14. Both fresh
protected runs passed **1,249 tests**, including all **23 M5.1 cases**, twelve
identity checks and both required Batch 2 storage tests. Ordered IDs match;
isolation and cleanup passed. Expanded long/short recordings are byte-identical
at **12,092/12,113 bytes**, including all six rejection paths per direction.
All 59 published hashes and all 833 tested file contents matched before
records-only finalization. Code, tests and protection remain unchanged.

Status: **completed for independent review**. ROADMAP section 31 marks M5.1 [x]
and retains proposed **next_milestone: M5.2**, within M5_1_VERIFICATION section 7,
after independent acceptance. No required gate remains for this common store.
Earlier pending attempts, 1,245-test proof and incomplete 1,259-test attempt remain
historical in that evidence record. M5.5 retains full recovery. At that historical
handoff M4.7 was definition-blocked and M0.3B remained proposed; D-092, D-100 and
the current ROADMAP handoff supersede only those old definition states. Source
gates remain required. All switches stay off.
At that handoff D-091 remained $0 used and $0 reserved.
