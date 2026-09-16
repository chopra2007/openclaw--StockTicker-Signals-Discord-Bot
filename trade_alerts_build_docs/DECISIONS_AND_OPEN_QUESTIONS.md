# DECISIONS_AND_OPEN_QUESTIONS.md

## 1. Purpose

This document records durable approved decisions, rationale, rejected alternatives, assumptions, unresolved questions, data blockers, and research hypotheses.

It explains **why** decisions exist and **what still needs to be learned**.

It does not permanently override canonical specifications. Approved decisions that change a canonical requirement must be synchronized into the governing document. Open questions/hypotheses never override established requirements.

## 2. Status Vocabulary

- `CONFIRMED`
- `PROVISIONAL`
- `NEEDS VALIDATION`
- `BLOCKED BY DATA`
- `REJECTED`
- `DEFERRED`

## 3. Decision Precedence

A later **explicitly approved** decision may supersede an older conflicting requirement.

Required process:
1. record approved decision here;
2. identify affected canonical document;
3. update canonical document;
4. version strategy/config if material;
5. update roadmap if implementation remains.

Open questions, hypotheses, observations, proposed changes, and blocked items do **not** override established requirements.

## 4. Project Decisions

### D-001 — Human-in-the-loop
`CONFIRMED`

System detects/scores/alerts. Human performs final review and manual trade.

### D-002 — No automated execution
`CONFIRMED`

No automatic orders, exits, stops, position sizing, or brokerage-position control.

### D-003 — Manual broker execution
`CONFIRMED`

Schwab/thinkorswim used manually; broker API primarily data/analytics.

### D-004 — Reuse existing infrastructure
`CONFIRMED`

Audit Openclaw, Discord, Schwab, options, storage, analytics before replacement.

### D-005 — Discord primary alert surface
`CONFIRMED`

Concise decision-oriented alerts; full diagnostics in storage.

### D-006 — Morning scope
`CONFIRMED`

Premarket through ~07:15 Pacific, main active window ~06:30–07:15 Pacific.

### D-007 — Long and short
`CONFIRMED`

Evaluate separately; do not assume symmetry.

### D-008 — Options common execution vehicle
`CONFIRMED`

Underlying edge and option quality remain separate.

### D-009 — Same-week options preferred
`CONFIRMED`

Not shortest-DTE at any cost.

### D-010 — Free/existing data preferred
`CONFIRMED`

Paid data only after evidence.

### D-011 — Low false-positive burden
`CONFIRMED`

Quality over alert count.

### D-012 — Evaluate every mechanical alert
`CONFIRMED`

Performance does not depend on whether user traded it.

### D-013 — Actual trade tracking not core
`CONFIRMED`

Optional ACCEPTED/REJECTED/NO_DECISION sufficient.

## 5. Architecture Decisions

### D-014 — Shared feature engine
`CONFIRMED`

No per-strategy duplicated VWAP/ATR/RVOL/etc.

### D-015 — Explicit state machines
`CONFIRMED`

Stateful formation is central.

### D-016 — Heads-up before actionable when possible
`CONFIRMED`

Reduce human reaction latency.

### D-017 — Structural stops
`CONFIRMED`

Reject fixed arbitrary percentage stops.

### D-018 — Structural targets
`CONFIRMED`

Use observable market structure.

### D-019 — Minimum reward concept
`PROVISIONAL`

T1 ~>=1.5R; T2 often >=2.5R.

Question: should this differ by strategy?

### D-020 — Confidence not win probability
`CONFIRMED`

### D-021 — Confidence decomposable
`CONFIRMED`

Persist factors/components.

### D-022 — Initial confidence weights
`PROVISIONAL`

Common 50/30/20; #5 45/35/20; #7 40/40/20; #8 45/30/25.

### D-023 — Options downstream
`CONFIRMED`

Unusual options activity alone does not validate underlying.

### D-024 — Poor option quality valid outcome
`CONFIRMED`

`STOCK SETUP VALID — OPTIONS QUALITY POOR`.

### D-025 — Delta prior
`PROVISIONAL`

abs(delta) 0.50–0.70, often ~0.60.

### D-026 — 0DTE stricter
`CONFIRMED DESIGN`

Primarily highly liquid SPY/QQQ situations.

### D-027 — Cross-strategy dedup
`CONFIRMED`

Primary + confluence instead of duplicate spam.

### D-028 — Relative strength mostly context
`CONFIRMED`

### D-029 — VWAP mostly context, not generic standalone strategy
`CONFIRMED`

### D-030 — Volume Profile not inherently predictive
`CONFIRMED`

Direction comes from current acceptance/participation.

## 6. Data Decisions

### D-031 — L2 not core
`CONFIRMED`

Optional modifier only.

### D-032 — Historical L2 must not delay project
`CONFIRMED`

### D-033 — Time-and-sales optional
`CONFIRMED DESIGN`

Test incremental value after human delay.

### D-034 — Full breadth ideal, proxy acceptable
`CONFIRMED`

Store breadth mode.

### D-035 — Unknown catalyst remains unknown
`CONFIRMED`

### D-036 — #7 requires reliable catalyst data
`CONFIRMED`

Current faithful implementation: `BLOCKED BY DATA`.

### D-037 — #8 approximate profile first
`CONFIRMED`

### D-038 — True vs approximate profile kept separate
`CONFIRMED`

### D-039 — Paid data must be evidence-justified
`CONFIRMED`

## 7. Portfolio Decisions

### D-040 — Eight approved playbooks
`CONFIRMED`

Canonical IDs are fixed unless explicitly changed.

### D-041 — Build priority
`CONFIRMED`

#1→#2→#3/#4→early validation→#5→#6→#7→#8.

## 8. Strategy-Specific Decisions

### #1
- D-042 Generic ORB insufficient — `CONFIRMED`
- D-043 5m OR initial default — `PROVISIONAL`
- D-044 RVOL ~2.0 initial threshold — `PROVISIONAL`
- D-045 acceptance ~10s / 0.70 prior — `PROVISIONAL`
- D-046 catalyst may be modifier/proxy-aware — `CONFIRMED DESIGN`

### #2
- D-047 compression HOD reference point-in-time — `CONFIRMED`
- D-048 compression must prove incremental value — `NEEDS VALIDATION`
- D-049 RS initially mandatory — `PROVISIONAL`

### #3
- D-050 real breakout attempt required — `CONFIRMED`
- D-051 distinct from generic mean reversion — `CONFIRMED`
- D-052 confirmation may sacrifice entry — `PROVISIONAL`

### #4
- D-053 first pullback highest priority — `CONFIRMED DESIGN`
- D-054 VWAP currently part of setup — `PROVISIONAL`
- D-055 AVWAP optional — `NEEDS VALIDATION`

### #5
- D-056 opening drive starts at regular-session open — `CONFIRMED`
- D-057 breadth filters narrow leadership — `CONFIRMED DESIGN`
- D-058 sector proxy can precede full breadth — `CONFIRMED`

### #6
- D-059 never fade gap merely because it exists — `CONFIRMED`
- D-060 catalyst class important — `CONFIRMED DESIGN`
- D-061 full gap fill not assumed — `CONFIRMED`

### #7
- D-062 catalyst direction alone insufficient — `CONFIRMED`
- D-063 first consolidation key hypothesis — `NEEDS VALIDATION`
- D-064 mixed earnings/guidance needs caution — `CONFIRMED DESIGN`
- D-065 modern price efficiency may weaken continuation — `NEEDS VALIDATION`

### #8
- D-066 lowest initial research confidence — `CONFIRMED`
- D-067 LVN is not direction — `CONFIRMED`
- D-068 profile parameters engineering priors — `PROVISIONAL`
- D-069 mandatory matched control — `CONFIRMED`

## 9. Validation Decisions

- D-070 Expectancy in R primary — `CONFIRMED`
- D-071 MFE/MAE required — `CONFIRMED`
- D-072 reaction-delay testing mandatory — `CONFIRMED`
- D-073 perfect trigger fills not trusted — `CONFIRMED`
- D-074 same-bar ambiguity conservative — `CONFIRMED`
- D-075 walk-forward required — `CONFIRMED`
- D-076 ablation required — `CONFIRMED`
- D-077 popular indicators not automatically valuable — `CONFIRMED`
- D-078 parameter plateaus preferred — `CONFIRMED`
- D-079 modifications become new hypotheses — `CONFIRMED`
- D-080 human discretion is testable — `CONFIRMED`
- D-081 confidence must be calibrated — `CONFIRMED`
- D-082 underlying edge before options performance — `CONFIRMED`
- D-083 no automatic strategy promotion — `CONFIRMED`
- D-084 strategy can be rejected — `CONFIRMED`

## 10. Monitoring Decisions

- D-085 production edge monitored continuously — `CONFIRMED`
- D-086 losing streak does not prove failure — `CONFIRMED`
- D-087 no live auto-tuning — `CONFIRMED`
- D-088 champion/challenger — `CONFIRMED`
- D-089 version history preserved — `CONFIRMED`

## 11. Rejected Alternatives

- R-001 generic independent indicator alerts — `REJECTED`
- R-002 L2 imbalance scalp as primary strategy — `REJECTED FOR INITIAL PORTFOLIO`
- R-003 Fibonacci-only standalone strategy — `REJECTED FOR TOP 8`
- R-004 tape acceleration standalone scalp — `REJECTED FOR TOP 8`
- R-005 cumulative delta divergence core strategy — `REJECTED FOR TOP 8`
- R-006 optimizing for claimed internet win rates — `REJECTED`
- R-007 build all strategies before research infra — `REJECTED`
- R-008 self-tuning live thresholds — `REJECTED`
- R-009 treat human-selected trades as mechanical performance — `REJECTED`
- R-010 buy institutional data before evidence — `REJECTED`

## 12. Repository Assumptions Requiring Audit

- A-001 Schwab capability fields — provisional implementation fact
- A-002 existing unusual-options module — confirmed context
- A-003 existing alert tracking — confirmed context; schema/method audit required

## 13. Open Questions

### System / shared
- OQ-001 exact repo module layout — PARTIALLY RESOLVED: existing Python host identified in §28; domain records are implemented in trade_alerts_models.py under M1.3; the common interface is in strategy_interface.py under M4.1 with protected proof complete in M4_1_VERIFICATION §7; transition/runtime/storage integration remains M4.2/M5 work
- OQ-002 persistent storage technology — RESOLVED for the existing host: SQLite/migrations; M1.3 defines linked record values; database layout and link-integrity enforcement remain M5.1 work
- OQ-003 restart/state recovery design
- OQ-004 alert-channel structure
- OQ-005 canonical RVOL definition
- OQ-006 ATR exact convention
- OQ-007 point-in-time swing detection

### #1
- OQ-008 OR length
- OQ-009 RVOL threshold
- OQ-010 catalyst incremental value
- OQ-011 acceptance horizon
- OQ-012 tape intensity value

### #2
- OQ-013 compression ratio
- OQ-014 duration
- OQ-015 RS threshold/necessity
- OQ-016 exhaustion quantification

### #3
- OQ-017 failure window
- OQ-018 meaningful excursion
- OQ-019 1m close confirmation value

### #4
- OQ-020 VWAP incremental value
- OQ-021 pullback depth
- OQ-022 volume ratio
- OQ-023 second pullbacks

### #5
- OQ-024 breadth threshold
- OQ-025 full breadth vs proxy
- OQ-026 breadth components
- OQ-027 drive efficiency
- OQ-028 VIX incremental value

### #6
- OQ-029 which gaps are fadeable
- OQ-030 catalyst classification
- OQ-031 failed-extension threshold
- OQ-032 gap-fill staleness

### #7
- OQ-033 catalyst provider
- OQ-034 catalyst classes
- OQ-035 first consolidation depth
- OQ-036 #7 vs #2 overlap

### #8
- OQ-037 does LVN add value?
- OQ-038 profile bin size
- OQ-039 LVN percentile definition
- OQ-040 multi-session profiles
- OQ-041 true vs approximate profile

### Options
- OQ-042 DTE by strategy
- OQ-043 delta target
- OQ-044 OptionScore threshold
- OQ-045 IV suitability
- OQ-046 option ranking value

### Human / confidence / portfolio
- OQ-047 human review net value
- OQ-048 useful rejection reasons
- OQ-049 human decision latency
- OQ-050 confidence ranking
- OQ-051 unnecessary confidence factors
- OQ-052 reaction-delay survivors
- OQ-053 excessive strategy overlap
- OQ-054 confluence value
- OQ-055 appropriate daily alert volume

## 14. Questions Codex Must Not Invent Answers For

Do not decide by intuition:
- which strategy is profitable/highest win rate
- optimal RVOL/compression/pullback/gap thresholds
- profitable catalyst classes
- whether VWAP/AVWAP/breadth/L2/LVN adds edge
- confidence cutoff for sizing
- best delta/DTE
- ideal alert frequency
- useful human discretionary rules

Use `NEEDS VALIDATION` or `BLOCKED BY DATA`.

## 15. Engineering Questions Codex May Resolve

Reversible engineering choices may be proposed based on repo conventions:
- directory structure
- class names
- indexes
- serialization
- interfaces
- incremental feature implementation
- state persistence
- test organization

They must preserve canonical behavior.

## 16. Questions Requiring Historical Data

- ORB edge
- compression edge
- VWAP pullback
- gap fade
- breadth
- profile
- parameter robustness
- long/short asymmetry
- regime effects

Use replay/walk-forward/ablation.

## 17. Questions Requiring Live/Shadow Data

- actual latency
- human reaction
- quote staleness
- Discord delay
- news latency
- human accept/reject value
- live option spreads
- disconnect frequency
- sub-minute acceptance quality

## 18. Paid-Data Queue

| Data | Current Decision |
|---|---|
| Premium catalyst/news | CONSIDER only if #7 justifies |
| Full breadth history | CONSIDER only if #5 proxy promising |
| Historical OPRA | CONSIDER after underlying edge |
| Tick/NBBO history | CONSIDER if execution ambiguity material |
| Historical L2 | NOT JUSTIFIED INITIALLY |
| Direct exchange depth | NOT JUSTIFIED INITIALLY |
| True trade-level profile | NOT JUSTIFIED INITIALLY |

## 19. Change Protocol

```text
OBSERVATION
→ HYPOTHESIS
→ TEST
→ APPROVED DECISION
→ VERSION CHANGE
→ CANONICAL DOC UPDATE
```

## 20. Initial Hypothesis Registry

- HYP-001 RVOL/stock-in-play improves generic 5m ORB
- HYP-002 compression improves generic HOD/LOD breakout
- HYP-003 RS improves HOD compression
- HYP-004 confirmed OR failure outperforms generic fades
- HYP-005 VWAP improves first pullback
- HYP-006 breadth improves index opening drive
- HYP-007 failed-open structure identifies fadeable gaps
- HYP-008 first consolidation adds value after catalyst repricing
- HYP-009 LVN adds value beyond accepted VAH
- HYP-010 human rejection improves mechanical expectancy
- HYP-011 confidence ranks quality
- HYP-012 OptionScore ranks contract execution quality

## 21. Visible Assumptions

Keep visible:
- 1m bars are the common historical baseline
- sub-minute data may be incomplete
- historical NBBO/options/catalysts/full breadth may be incomplete
- #8 may use approximate profile
- most thresholds are engineering priors
- design ranking is not performance

## 22. Research Confidence Differences

Higher structural support:
- opening price discovery
- intraday momentum
- short-run reversal
- relative performance

Medium:
- exact ORB implementation
- HOD compression
- first pullback
- failed-open gap fade
- catalyst first consolidation

Lower:
- LVN continuation

Broad literature support does not automatically validate the exact project implementation.

## 23. Production Promotion / Demotion

Promotion requires credible data integrity, OOS/forward expectancy, realistic execution, parameter stability, regime understanding, manual feasibility, and acceptable drawdown.

Demotion to DEGRADED/SHADOW/DISABLED may occur for signal, execution, data, confidence, or manual-fit deterioration.

A losing streak alone is not sufficient evidence.

## 24. Rejection / Sunk Cost

Consider rejection when OOS expectancy is non-positive after realistic costs and no robust identifiable subgroup supports continuation, or when data cost, manual reaction requirements, fragility, redundancy, or structural evidence make the strategy unjustified.

Implementation effort is not a reason to retain a weak strategy.

## 25. Scope Expansion

Any future addition such as futures, crypto, automated execution, portfolio sizing, machine-learned strategy generation, or a full trading terminal requires explicit `MASTER_SPEC.md` expansion and supporting documentation updates.

## 26. Canonical Documentation Set

- `PROJECT_INDEX.md`
- `MASTER_SPEC.md`
- `PLAYBOOKS.md`
- `ROADMAP.md`
- `SESSION_PROTOCOL.md`
- `DATA_REQUIREMENTS.md`
- `TESTING_AND_VALIDATION.md`
- `CODING_STANDARDS.md`
- `DECISIONS_AND_OPEN_QUESTIONS.md`

## 27. Final Principle

Future Codex sessions must distinguish:

```text
WHAT THE PROJECT HAS DECIDED
```

from:

```text
WHAT THE PROJECT STILL NEEDS TO LEARN
```

Approved decisions may supersede older requirements when properly recorded and synchronized.

Open questions, hypotheses, observations, and rejected alternatives never override established project requirements or the document hierarchy.

## 28. Prebuild review record — 2026-09-05 Pacific

[PREBUILD_REVIEW.md](./PREBUILD_REVIEW.md) is an evidence/review record, not a new specification. This session applied feature-preserving documentation corrections authorized by the review request. It approved no product changes, purchases, new strategy versions, promotions, numerical threshold changes, replacement framework or new language.

`CONFIRMED` evidence means the stated fact is supported, not that a proposed product decision is approved. New approval records must name decision ID, approver, date, exact scope, superseded requirement, rationale, affected files and required version changes. Existing D-001–D-089 remain the supplied decision record; this review does not invent approval history for them.

Repository findings resolve OQ-001 at the host-boundary level (existing Python `consensus_engine`) and OQ-002 (existing SQLite/migration infrastructure). Proposed new table layouts and module names still require compatible design. OQ-003 recovery now has an engineering contract in CODING_STANDARDS §§52–53; implementation and tests remain pending. OQ-004 channel policy remains open; no new channel or bot is approved.

### P-01 — Exact definitions and conflicting rule alternatives
Status: `PARTIALLY APPROVED FOR RESEARCH`: D-090 approves its specified M0.3A rows; remaining P-01 choices need their own decisions.

M0.3 must turn PLAYBOOKS §13 into versioned, testable definitions. Engineering choices that merely express an already unique rule may be documented directly. Choices that alter candidate selection, trigger, stop, score, threshold or data fidelity require an explicit scoped decision. Examples: ORB A/B/C mode; #4 second pullback; #5 35–40% choice; #7 class C; #8 refill penalty. Keep governing requirements intact until resolved.

### P-02 — Proxy and feature formula closure
Status: `PARTIALLY APPROVED FOR RESEARCH`: D-090 approves its specified feature/proxy rows; all other unspecified behavior remains pending.

The already approved sector breadth, bar profile and tape substitutes remain in scope. Their exact formulas, reference samples, coverage gates and validation controls must be recorded before coding. No unspecified weighting, missing-factor renormalization, volume allocation or interpolation was selected here. Full-fidelity modes remain tracked independently.

### P-03 — Executable outcome and release criteria
Status: `PARTIALLY APPROVED FOR RESEARCH`: D-090 approves O-01 as specified; remaining cost/statistical/release terms stay open.

Freeze entry/exit fractions, timeout/horizon, quote-side and cost treatment, borrow requirements, ambiguity/censoring rules, research split and measurable promotion criteria before evaluating results. Preserve existing $0.45 contract fees in reused measurement paths. No new stop, target, delay or profit gate is chosen by this review. Engineering success and profitable results remain separate.

### P-04 — Additional access, purchases or replacement technology
Status: `LIMITED TESTING CREDIT APPROVED`: D-091 permits up to $25 total Databento credit usage for testing; other purchases and replacement technology remain unapproved.

Schwab account/stream limits, complete catalyst receive history, full constituent membership, true volume profile and historical executable option quotes need evidence. Reuse existing/free data first. If a gap remains, record the exact source, fields, history, measured fidelity, quoted cost and operational burden. Databento testing within the D-091 cumulative cap is already authorized; additional spending or other purchases require their own decision. A cost is UNKNOWN until verified. A different language, replacement bot/framework or major rewrite requires its own explicit scoped approval.

### Continuing blockers

M0.2 owns current access/coverage/capacity evidence. M0.3 owns rule-definition and outcome-policy gaps. M0.4 owns executable offline reuse contracts. M12 owns faithful catalyst completion, M10 full/proxy breadth completion, M13 true/approximate profile completion, and M14/M17 exact historical/forward options validation. Their blocker and acceptance rows live in DATA_REQUIREMENTS and PREBUILD_REVIEW. Blocked required work is not optional or indefinitely deferred.


## 29. M0.3A packet status — owner decision recorded

[M0_3_DEFINITION_PACKET.md](./M0_3_DEFINITION_PACKET.md), version `M03A_ORB5_V1`, was drafted without self-approval. The owner subsequently answered yes to adopting that presented packet as written research rules. **All six specified rows are APPROVED FOR RESEARCH under D-090:** F-01, F-02, F-03, B-01, B-02 and O-01. Local row IDs belong to this packet, not PREBUILD_REVIEW findings.

The approval fixes only the choices actually specified. Missing full target producers, component scoring, A/C entries, option ranking and remaining execution/statistical/release terms are not supplied or approved by implication. M0.3A is complete; M0.3 remains incomplete. **M0.3B preparation is now complete**, with adoption still pending in §32. **M0.4, M1.1–M1.3, M2.1 and repaired M2.2 have completed offline evidence. M2.3 implementation now awaits protected execution; proposed next build: M2.4 after M2.3 verification and independent acceptance**, independent of those new choices; see ROADMAP §31 and M2_3_VERIFICATION.md §6. No further approval request is needed for the unchanged D-090 rows.

## 30. D-090 — Approved M0.3A written research rules

- Status: **APPROVED**, explicitly by the owner on **2026-09-05 Pacific**.
- Approval source: the owner's yes to the assistant's specific request to adopt the linked `M03A_ORB5_V1` research rules, including 10–30 second breakout confirmation, a fixed stop, half at each target and same-day closure of any remainder. The linked six-row packet is the exact scope.
- Approved scope/version: `M03A_ORB5_V1`, rows F-01/F-02/F-03/B-01/B-02/O-01, for written research rules only. Keep the existing explicit feature, variant and outcome identifiers in that packet. No application/configuration version was changed.
- Superseded text: the pending approval of these specific rows in P-01–P-03, packet §1/§9, PLAYBOOKS §14, DATA_REQUIREMENTS §34 and TESTING_AND_VALIDATION §51. Where the original #1 text was incomplete or approximate, the exact packet definition governs only the named B research variants. Other playbooks, untouched priors and remaining open rows retain their authority.
- Rationale: freeze one reproducible version before results; retain separate tape/quote estimates and honest execution/evidence limits. Approval is not proof of a trading edge.
- Affected documents: packet status, PLAYBOOKS §14, DATA_REQUIREMENTS §34, TESTING_AND_VALIDATION §51, this register, PROJECT_INDEX §21, ROADMAP §31, SESSION_PROTOCOL §35 and the later PREBUILD_REVIEW progress note.
- Open dependencies: complete structural-level/obstacle producers, A/C entries, score factors, option ranking, trade-condition/coverage evidence, remaining fees/slippage/borrow/statistical/release criteria, and the other seven strategy-definition rows. Approval does not fabricate those definitions or make #1 actionable.
- Excluded authority: application implementation, live activation, Discord/broker calls, real/paper orders, purchases other than the separate D-091 limit, strategy promotion and profitability claims.
- Integrity: the exact presented packet is backed up before this status-only synchronization. Its pre-approval SHA-256 is `41569f34b20c69cf217377d2f9e81cfcbde58988b1e230611a5ee0a91aa553fb`. Trading formulas, numeric priors, sample inputs and expected outcomes are unchanged by this recording step.

## 31. D-091 — Databento testing-credit authorization and cumulative ledger

Status: **APPROVED**, explicitly by the owner on **2026-09-05 Pacific**. This is separate from D-090.

Scope: Databento credit usage for testing this trade-alert design, when needed, up to **$25 total**. More than $25 requires explicit additional owner approval. This is one aggregate allowance across all tests, requests, retries, agents and continuation sessions; it is not $25 per request, day or session. It does not authorize account top-ups, cash purchases, subscriptions, other providers, application implementation or trades. Existing local/free data remains the first route.

This supersedes P-04's unapproved Databento-testing purchase state only within the stated credit cap, and permits the named Databento credential to be used for those tests. All other approval and secret-handling boundaries continue. Affected documents: DATA_REQUIREMENTS §34, TESTING_AND_VALIDATION §51, PROJECT_INDEX §21, ROADMAP §31 and SESSION_PROTOCOL §35.

Current ledger at recording, **2026-09-05 Pacific**:

| Budget item | USD credit |
|---|---:|
| Owner-approved cumulative cap | 25.00 |
| Confirmed usage charged to this authorization | 0.00 |
| Outstanding or uncertain request reservations | 0.00 |
| Available authorization | 25.00 |

No Databento request or credential read was needed for this documentation update. The zero above records usage under this authorization; it is not a claim about the account's balance or unrelated historical usage.

Before any charged request:

1. Define the test, necessary dataset/schema/symbols/time span and why existing data cannot answer it. Check data fidelity before buying a larger sample.
2. Verify the official cost mechanism for that request and obtain a conservative charge bound, including any chargeable retries/fees. An estimate with unbounded possible overage is insufficient.
3. Read and update this cumulative ledger under one coordinating owner. Record a unique request reference, Pacific time, test/scope, upper-bound reservation and status before dispatch. No parallel agent spending or silent per-session reset.
4. Execute only if `confirmed_usage + all_outstanding_or_uncertain_reservations + new_request_bound <= 25.00`. Reserve first; reconcile the provider's actual charge afterward. If cost cannot be bounded or outstanding usage cannot be reconciled, do not issue another charged request.
5. Keep failed, interrupted and uncertain requests reserved until their charges are known. Reconcile before retrying. Update confirmed usage, reservation and remaining authority after each request. Stop before exceeding $25; request increased authorization if more is needed.

Request ledger: **no requests yet**. Future rows must contain request reference, test/scope, reserved bound, actual charge or UNKNOWN, status and Pacific timestamp. Store no API key or account identifiers here. Read only the configured named API environment variable when needed; never expose its value. D-091 approves spend within its cap, not data suitability, paid-model results, or full strategy readiness.

## 32. M0.3B preparation and independent build readiness

Status: **PREPARED / PROPOSED FOR OWNER DECISION**, 2026-09-05 Pacific. [M0_3B_DEFINITION_PACKET.md](./M0_3B_DEFINITION_PACKET.md), version `M03B_ORB5_V1`, records the full concrete first-strategy recommendation and worked cases. B-STRUCTURE/B-ENTRY, B-SCORE/B-OPTIONS and B-EVIDENCE in its §1 are proposal group IDs, not approved decisions. They supply the remaining proposed P-01/P-02/P-03 choices for #1. All other playbook definitions and data proof remain tracked.

The owner's “go ahead” authorized finishing this preparation and handoff. It did not name previously unseen formulas and is not recorded as adopting them. No D-092 approval is invented. An actual subsequent owner decision must name this packet/version and scope, record any rejected choices and synchronize the governing documents before dependent trading code. D-090/D-091 need no repeat approval.

[FIRST_BUILD_SESSION.md](./FIRST_BUILD_SESSION.md) defines M0.4's existing-interface tests. These are routine engineering work independent of new trading choices; the fresh build kickoff authorizes that bounded local work. M0.4 does not spend Databento credit, use live connections, alter the application, or prove strategy returns. New application models and recovery logic belong to later milestones.

Outstanding owner-only input before dependent strategy coding: adopt or revise the presented new trading-rule packet. No additional owner answer is needed to start the isolated M0.4 build. Actual unavailable source evidence remains a technical/data task; it must not be replaced by asking the owner to invent a fact.

## 33. M0.4 engineering evidence; no new trading approval

The owner-started first build completed the C04 compatibility contracts, recorded in [M0_4_VERIFICATION.md](./M0_4_VERIFICATION.md). This is engineering evidence, not a new approved trading decision. M0.3B stays proposed; D-090/D-091 are unchanged and testing used $0. That session handed off M1.1; current progress is in ROADMAP §31.

Open engineering limits remain assigned: source/adjustment provenance and timestamp precision to M2.1/M2.2; whole-message receipt and failure handling to M4.6; two broader listener tests with unmocked acknowledgment reactions to M18.4; reconciled/approved future deployment and rollback definitions to M18.6. Existing production behavior and the failing-test list were preserved. None of these observations silently changes a trading rule or authorizes live calls.

## 34. M1.1 engineering completion — 2026-09-05 Pacific

The shared clock is implemented and independently tested; see
[M1_1_VERIFICATION.md](./M1_1_VERIFICATION.md). Six additive helpers preserve old
callers and supply absolute instants, Pacific formatting, calendar-date lookup,
caller-configured premarket/regular windows and session phase. Premarket has no
platform default: D-090's 01:00 value is used explicitly in its research examples.
This expresses the approved timing contract without adopting any new strategy rule.

The independent combined selection passed 125 cases in each of two protected
processes. Only AT-02's clock portion closes. M2.2/M3.6 still own bar finality,
availability, missing-minute and revision proof. That session handed off M1.2;
current progress is in ROADMAP §31.
M0.3B, data-access gaps, D-090 rules and D-091's $0 usage/$0 reservations are unchanged.

## 35. M1.2 engineering completion — 2026-09-05 Pacific

The configuration foundation is implemented and independently tested; see
[M1_2_VERIFICATION.md](./M1_2_VERIFICATION.md) and CODING_STANDARDS §56. It uses
schema version 1 and config label FOUNDATION_V1, known non-secret fields,
canonical JSON/SHA-256 identity and an immutable session snapshot through the
existing loader. All new switches are off; pending policy/strategy versions,
windows and premarket start remain null. The combined 194 tests passed twice.

These are reversible engineering choices under §15, not a new trading approval.
A syntactically valid version label does not establish an adopted strategy or
complete policy. Actual controller gates, persistence and replay retain their
existing owners. No D-092 or M0.3B adoption is created; D-090's formulas and D-091's
$0 used/$0 reserved balance are unchanged. That session handed off M1.3; current progress is in ROADMAP §31.


## 36. M1.3 engineering completion — 2026-09-06 Pacific

The canonical record layer is implemented under CODING_STANDARDS §57; see
[M1_3_VERIFICATION.md](./M1_3_VERIFICATION.md). Thirteen immutable record types
preserve source/missingness, exact option identity, configuration/session links,
mechanical facts and separate option/delivery/human/outcome results. The final
independent combined selection passed 363 cases in each of two protected processes.

These are reversible engineering choices under §15. Schema version 1 describes
record structure, not an approved trading policy. It introduces no D-092, M0.3B
adoption, threshold, provider/data claim or profitability result. D-090 and the
D-091 ledger are unchanged. Actual storage/link validation, runtime/recovery and
source coverage retain their owners. That session handed off M2.1 offline Schwab
normalization in M1_3_VERIFICATION §6; current progress is in ROADMAP §31.


## 37. M2.1 engineering completion — 2026-09-06 Pacific

Three pure Schwab response mappings are implemented under CODING_STANDARDS §58;
see [M2_1_VERIFICATION.md](./M2_1_VERIFICATION.md). The 41 new tests passed twice;
the independent combined selection passed 420 cases twice. These are reversible
engineering choices under §15, not new trading decisions or provider evidence.
Legacy callers, existing models/configuration and the live runtime are unchanged.

Raw source time and explicit bar boundaries remain separate. Quote source time
uses the quote timestamp, with a trade-time fallback only if quote time is absent;
both original times remain stored. Invalid optional provider values become null;
required incomplete bars, contradictory context and false valid quote labels fail.
These conventions do not define age/skew limits or certify source finality.
M0.2/M2.2/M2.3/M14.2 retain those evidence/runtime gates. At that historical
handoff M0.3B remained proposed and no D-092 existed; D-092 and later frozen
research sections now carry current definition status. D-090/D-091 were
unchanged at $0 used and $0 reserved in that historical record.
That session handed off M2.2 historical bars. That M2.3 handoff is historical. Its offline implementation now awaits protected
execution; proposed next build: M2.4 after M2.3 verification and independent
acceptance, using M2_3_VERIFICATION §6 and ROADMAP §31.

## 38. M2.2 review repair — 2026-09-06 Pacific

Unknown evidence references (`UNKNOWN` or `UNSPECIFIED`, ignoring case and outer
spaces) now prevent complete historical coverage. Four added test cases preserve
the supplied prices while requiring unknown coverage. This enforces DATA §32 and
CODING §59; it adds no trading decision. Two existing peer-history caller tests
are included in the required protected selection. M2_2_VERIFICATION §10 records
the historical launcher failure; §11 now records fresh supervisor proof: 424 tests
passed in each of two protected runs, including all four repair cases and both
peer-history cases. Records-only finalization preserves code, tests and protection.
M2.3 remains the proposed next build after independent M2.2 acceptance.
D-090, D-091, M0.3B proposals and all unresolved data/full-mode gates are unchanged.


## 39. M2.3 offline event implementation — verification pending

The owner-assigned automatic M2.3 session adds the bounded canonical Quote
event/continuity prerequisite under CODING_STANDARDS §60. Protected tests are
written; M2_3_VERIFICATION §§8/10 record earlier supervisor results and §11 reopens
offline acceptance after two further source-time findings. A repeated same-session
source time before recovery cannot preserve usable old data. A source time after
availability remains on the unusable retained input, even after the clock catches
up. Cache repeats preserve rejected data. Two fresh protected runs are required.
This enforces the existing missingness/recovery contract without a new decision. Reversible engineering choices
under §15 include one fixed-scope state owner, explicit supplied policy, separate
quote/trade age, constant retained state, conservative timestamp/conflict handling,
and recovery evidence tied to a new observation in the current connection epoch.
Same-time disconnect/reconnect cannot reuse its old snapshot. These choices add
no numerical live defaults, provider sequence semantics or trading rules.

Proposed next after M2.3 verification/acceptance: M2.4's offline reference-input
snapshot/coverage prerequisite in ROADMAP §31 and M2_3_VERIFICATION §6. Full M2.3
transport and actual provider/coverage/capacity proof remain explicitly blocked
under M0.2/M2.3 with supervised reopening evidence. No D-092 approval is created;
At that historical handoff M0.3B remained proposed. D-092 and later frozen
research sections now carry current definition status; D-090 remains preserved
and D-091 then stayed $0 used and $0 reserved.


## 40. M2.4 supplied-reference implementation — proof pending

The automatic assignment selects M2.4 under ROADMAP §31 and M2_3_VERIFICATION §6.
M2.3 §12 finalized the earlier offline proof; its dated pending notes above are
historical. M2.4 preserves the supplied partial reference code/tests and completes
its bounded contract/evidence handoff under CODING_STANDARDS §61. Protected
execution is pending in M2_4_VERIFICATION; no passing test claim is made.

Reversible engineering choices under §15 include fixed per-reference source/mode/
policy/request scope, exact evaluation-time Quote decisions, M2.2 available-time
history coverage, deterministic frozen output and separate current stock mapping.
VIX remains explicitly unsupported until its index input contract and actual
source facts exist. No return, breadth, score or trading formula is selected.
No new approval record or M0.3B adoption is created; D-090 is unchanged.

Full M2.4 source completion remains blocked with exact supervised reopening proof
in M2_4_VERIFICATION §7. The proposed independent next software milestone is
M3.1's already approved offline price calculations, after protected M2.4 proof and
review. All remaining definition, full-data and live-operation gates retain their
owners. D-091 remains $0 used and $0 reserved; no paid/live request occurred.

## 41. M4.1 engineering interface — protected proof complete

The assigned M4.1 work defines the common strategy contract in
`strategy_interface.py`; see CODING_STANDARDS §65 and M4_1_VERIFICATION.
Required-data declarations, frozen context/state and signatures reuse existing
canonical records. These are reversible engineering choices under §15. They
select no trading graph, threshold, score formula, stop, target or expiry duration.
The concrete strategy script exists only in tests and proves interface use only.

Both protected supervisor runs passed 720 tests, including all 55 M4.1 cases,
with matching ordered IDs, clean isolation and cleanup, and byte-identical long
and short records. M4_1_VERIFICATION §7 and M4_1_SUPERVISOR_TESTS.json record the
verified proof. The earlier failed local attempt and ownership notes remain
historical in M4_1_LOCAL_CHECKS.json; they are not current pending work.
M4.2 is the proposed next dependency-ready milestone after independent review.
M0.3B stays proposed, all eight playbooks and source gates remain required, and no
approval record is invented.
D-090 and D-091 are unchanged, with $0 used and $0 reserved.

## 42. M4.2 engineering state/storage mechanism — expanded proof complete

The assigned M4.2 work implements the supplied-rule transition mechanism under
CODING_STANDARDS §66. Reversible engineering choices under §15 are immutable
scope/rule attribution, serialized accepted order, recording before memory
advance, an injected existing database handle and an additive append-only table.
No trading graph, expiry duration, score, stop, target or M0.3B proposal is adopted.
Both fresh protected runs passed **826 tests**, including all 56 M4.2 cases and
the four database checks added after review, with matching ordered IDs, clean
isolation/cleanup and byte-identical long/short records. M4_2_VERIFICATION §13
and M4_2_LOCAL_CHECKS.json record the expanded proof and records-only finalization.
All 808 tested file contents matched before editing; code, tests, configuration
and protection remain unchanged. Earlier attempts and the narrower 822-test
selection remain historical. This software proof establishes no trading rule,
live source, recovery system or profitability.

Proposed next after M4.2 independent review: M4.3's bounded
D-090 §6 supplied-input risk/target selector in M4_2_VERIFICATION §5. Unavailable
structural producers/applicability and all source gates remain required before
dependent action. Full M5 event retention, candidate/delivery transactions and
recovery remain open. M0.3B stays proposed; D-090 and the cumulative D-091 ledger
are unchanged at $0 used/$0 reserved. No new owner decision is invented.

## 43. M4.3 supplied geometry — no new trading decision

The assigned M4.3 prerequisite implements only D-090 §6's supplied-input risk
and target selector; see CODING_STANDARDS §67 and M4_3_VERIFICATION. Typed feature
bindings, explicit per-family coverage, frozen request/result attribution and
exact decimal-text comparisons are reversible engineering choices under §15.
Canonical risk/target models and all existing display callers remain unchanged.
Protected offline proof is complete: both runs passed 892 tests, including all
105 M4.3 cases. This does not claim actual source coverage.

M0.3B remains PROPOSED. Full producers/applicability/priority, actual anchor/path/
family coverage, increments, and applicable soft invalidation/runner definitions
stay required in the separate blocked M4.3 row. M4_3_VERIFICATION §4 records exact
owners and reopening proof. No family becomes optional and no missing level is
replaced by an invented R multiple. Proposed independent next_milestone after
offline proof and blocked-gate review is M4.4, bounded in that record's §5.
D-090 and D-091 remain unchanged, at $0 used/$0 reserved. No new decision approval,
live access, purchase or profitability claim is created.

## 44. M4.4 supplied confidence — no new scoring decision

The assigned offline M4.4 slice adds pure composition and full supplied attribution
under CODING_STANDARDS §68. Protected proof is complete in M4_4_VERIFICATION §8.
Typed required terms, exact explicit weights, canonical score/factor reuse and
immutable input/session/configuration references are engineering choices under
§15. They supply no factor formula, score cutoff, missing-factor normalization,
new playbook weight or live consumer. A supplied policy version grants no approval.

M0.3B's B-SCORE proposal remains unadopted. Full factor normalization, membership,
factor-to-component formulas, missingness/freshness rules and actual compatible
source coverage remain required under M0.3/M4.4 and their data/strategy owners.
M16.4 retains calibration. M4_4_VERIFICATION §4 saves exact reopening proof and
§5 proposes independent M4.5 supplied candidate assembly after offline proof and
review. No required blocked feature is removed. D-090 and D-091 are unchanged,
with $0 used/$0 reserved. No owner decision or profitability claim is invented.

## 45. D-092 — Agent-selected M0.3B offline research rules

Status: **FROZEN FOR OFFLINE RESEARCH / DATA MANIFEST BLOCKED**, 2026-09-13 Pacific.

The owner's [research authorization](./RESEARCH_AUTHORIZATION_20260913.md) delegates ordinary entry, stop, target, filter, option and testing choices to the agent. Under that authority, [M0_3B_DEFINITION_PACKET.md](./M0_3B_DEFINITION_PACKET.md) version `M03B_OR_RESEARCH_V2` freezes twelve base opening-range combinations: 5-minute/15-minute, immediate/confirmed/retest and long/short. Each base combines with two stops and fixed 2R, fixed 3R and D-090 structural exits, producing exactly 72 V2 result arms. All are retained and reported. The historical packet's named structure, catalyst, macro, score, option, cost, uncertainty and release formulas are selected for V2 as stated in the new preregistration section.

The new comparison family uses `1/1440` per arm with the existing 10-session circular moving-block bootstrap. Results remain split by range, entry, direction, stop, exit and fixed SPY gap regime. D-090 and `M03A_ORB5_V1` remain unchanged as a separately reported historical arm. No old result is relabeled or reused when entry, stop or exit differs.

The required coverage-only audit found no qualifying source manifest. Exact development, calibration and untouched final-validation dates therefore remain unavailable. This is a source gate, not an owner-choice gate. Replay cannot start until M0.2 publishes an immutable manifest hash and exact 60%/20%/remainder date lists before any result is viewed. No provider call, credential read, purchase, test run, live activation or profit calculation occurred in this decision record. At this decision, the other seven playbook definition rows remained required; later definition decisions record subsequent progress.

## 46. D-093 — Agent-selected M0.3C HOD compression research rules

Status: **FROZEN FOR OFFLINE RESEARCH**, 2026-09-13 Pacific.

Under the owner's [research authorization](./RESEARCH_AUTHORIZATION_20260913.md),
[M0_3C_DEFINITION_PACKET.md](./M0_3C_DEFINITION_PACKET.md) version
`M03C_HOD_COMP_RS_V1` freezes one first `HOD_COMP_RS` research version. It uses
non-overlapping recent-three/prior-seven windows, a three-to-eight-bar structure,
the HOD/LOD known when compression starts, an exact 15-bar SPY warm-up, mirrored
long/short rules, separate tape and projected-volume modes, fixed risk, targets,
score and stock outcome treatment.

The version preserves the existing playbook thresholds and resolves the choices
named in PLAYBOOKS §13. It does not change D-090 or D-092, select a profitable
rule, prove source coverage or authorize replay, alerts, orders or deployment.
Historical results require a coverage-only manifest and frozen chronological
dates before any result is opened. Missing tape, quote, borrow or option facts
block only their dependent evidence.

## 47. D-094 — Agent-selected M0.3D OR failure research rules

Status: **FROZEN FOR OFFLINE RESEARCH**, 2026-09-13 Pacific.

Under the owner's [research authorization](./RESEARCH_AUTHORIZATION_20260913.md),
[M0_3D_DEFINITION_PACKET.md](./M0_3D_DEFINITION_PACKET.md) version
`M03D_OR_FAILURE_REV_V1` freezes one first `OR_FAILURE_REV` research version. It
uses a 0.10 ATR meaningful excursion, starts the inclusive 180-second failure
timer at the buffered crossing, requires a final one-minute close strictly back
inside, and compares that close arm with a stronger later break of the frozen
failure bar. It also fixes ten one-second inside-acceptance samples, tape and
quote modes, mirrored risk, targets, score, outcomes and explicit ownership when
an ORB structure reverses. The structural exit stays the playbook prior; fixed
2R and fixed 3R exits are separately retained comparison arms.

The version preserves the existing playbook thresholds and resolves the choices
named in PLAYBOOKS §13. It does not change D-090, D-092 or D-093, select a
profitable rule, prove source coverage or authorize replay, alerts, orders or
deployment. Historical results require a coverage-only manifest and frozen
chronological dates before any result is opened. Missing catalyst, tape, quote,
borrow or option facts block only their dependent evidence.

## 48. D-095 — Agent-selected M0.3E first-pullback research rules

Status: **FROZEN FOR OFFLINE RESEARCH**, 2026-09-13 Pacific.

Under the owner's [research authorization](./RESEARCH_AUTHORIZATION_20260913.md),
[M0_3E_DEFINITION_PACKET.md](./M0_3E_DEFINITION_PACKET.md) version
`M03E_FIRST_PULLBACK_VWAP_V1` freezes one first `FIRST_PULLBACK_VWAP` research
version. It uses completed-minute impulses, two-bar swing confirmation,
independent pullback structures, duration-normalized volume, three-minute VWAP
slope, strict close-cross counting, exact 0.65 and 0.70 retracement roles, a
frozen reversal-bar crossing and mirrored risk, targets, score and outcomes.
The first-only prior remains primary. A separate lower-priority arm retains the
second pullback, and the third remains suppressed. Structural, fixed 2R and
fixed 3R exits remain separate comparison arms. Direction, priority/ordinal,
exit, delay, score population and cost form a frozen family of 360 primary
comparisons with a `1 / 7200` family threshold.

The version preserves the existing playbook thresholds and resolves the choices
named in PLAYBOOKS §13. It does not change D-090, D-092, D-093 or D-094, select
a profitable rule, prove source coverage or authorize replay, alerts, orders or
deployment. Historical results require a coverage-only manifest and frozen
chronological dates before any result is opened. Missing bar, trade, quote,
news, borrow or option facts block only their dependent evidence.

## 49. D-096 — Agent-selected M0.3F index opening-drive breadth research rules

Status: **FROZEN FOR OFFLINE RESEARCH**, 2026-09-13 Pacific.

Under the owner's [research authorization](./RESEARCH_AUTHORIZATION_20260913.md),
[M0_3F_DEFINITION_PACKET.md](./M0_3F_DEFINITION_PACKET.md) version
`M03F_INDEX_OPEN_DRIVE_BREADTH_V2` freezes one first
`INDEX_OPEN_DRIVE_BREADTH` research version. It defines full-constituent,
11-sector-proxy and hybrid modes without rescaling missing components, exact
coverage, mirrored breadth, the drive path denominator and zero case, the 0.35
and 0.40 retracement roles, warning, reduction and suppression behavior, risk,
targets, score and outcomes.

Review found V1 still left two implementation choices open: M0.3A names two
VWAP modes, and "prior eligible price" did not define the Up Volume sequence
or interval. V2 replaces that discretion with exactly
`SESSION_VWAP_BAR_HLC3_V1` in every arm and
`SESSION_DIRECTIONAL_TRADE_VOLUME_V1` from the regular open through evaluation.
Packet §4.1 fixes per-trade share attribution, immediate predecessor prices,
neutral first/tied trades and as-of ordering/corrections. New boundary examples
cover these rules. The comparison family is unchanged; this selects one VWAP
mode, not an added arm. The repair passed protected verification and awaits
independent acceptance.

The full and hybrid modes remain required and blocked until point-in-time index
membership, weights, minute history and coverage are verified. Sector proxy is
a separately labeled research fallback, not evidence of full breadth. The 720
comparison cells retain every direction, mode, priority, exit, delay, score
population and stock-cost assumption with a `1 / 14400` family threshold.

The version preserves the existing playbook thresholds and resolves the choices
named in PLAYBOOKS §13. It does not change D-090, D-092, D-093, D-094 or D-095,
select a profitable rule, prove source coverage or authorize replay, alerts,
orders or deployment. Historical results require a coverage-only manifest and
frozen chronological dates before any result is opened. Missing membership,
bars, trades, quotes, macro events, borrow or option facts block only their
dependent evidence.

## 50. D-097 — Agent-selected M0.3G failed-gap-fade research rules

Status: **FROZEN FOR OFFLINE RESEARCH**, 2026-09-13 Pacific.

Under the owner's [research authorization](./RESEARCH_AUTHORIZATION_20260913.md),
[M0_3G_DEFINITION_PACKET.md](./M0_3G_DEFINITION_PACKET.md) version
`M03G_GAP_FADE_FAILED_OPEN_V1` freezes one first
`GAP_FADE_FAILED_OPEN` research version. It defines the exact three-minute
opening-extension window, failed-extension equality, loss of open, later
failed-reclaim attempt and inclusive 180-second deadline, same-instant
stock-minus-SPY relative strength from open and exact mirrored gap-down behavior.

The version keeps unknown catalysts distinct from no catalyst. Class C has no
score penalty, D subtracts 15 points, B subtracts 30 and continuation-aligned A
suppresses. Risk protects beyond both the opening and reclaim extremes.
Structural, fixed 2R and fixed 3R exits remain separate comparison arms. The 480
comparison cells retain every direction, catalyst class, exit, delay, score
population and stock-cost assumption with a `1 / 9600` family threshold.

The version preserves existing playbook thresholds and resolves the choices
named in PLAYBOOKS §13. It does not change D-090, D-092, D-093, D-094, D-095 or
D-096, select a profitable rule, prove source coverage or authorize replay,
alerts, orders or deployment. Historical results require a coverage-only
manifest and frozen chronological dates before any result is opened. Missing
bars, trades, quotes, SPY, catalyst, borrow or option facts block only their
dependent evidence.

## 51. D-098 — Agent-selected M0.3H catalyst-consolidation research rules

Status: **FROZEN FOR OFFLINE RESEARCH**, 2026-09-13 Pacific.

Under the owner's [research authorization](./RESEARCH_AUTHORIZATION_20260913.md),
[M0_3H_DEFINITION_PACKET.md](./M0_3H_DEFINITION_PACKET.md) version
`M03H_CAT_FIRST_CONSOL_V1` freezes one first `CAT_FIRST_CONSOL` research
version. It defines point-in-time A/B/C/D classification, material and
contradictory news, post-receipt reaction start, regular-session impulse,
two-bar extreme confirmation, first-consolidation ownership and exact 0.50/0.65
depth roles.

The preserved A/B-only trigger remains primary. Class C can enter only a
separately labeled abnormality diagnostic; it never becomes actionable. D,
ambiguous direction, unknown coverage and opposing A/B news suppress. The
version also freezes ten-second acceptance, mirrored risk, structural, fixed 2R
and fixed 3R exits, score and outcomes. The 720 comparison cells retain every
direction, catalyst population, depth, exit, delay, score population and stock-
cost assumption with a `1 / 14400` family threshold.

The version preserves existing playbook thresholds and resolves the choices
named in PLAYBOOKS §13. It does not change D-090, D-092, D-093, D-094, D-095,
D-096 or D-097, select a profitable rule, prove source coverage or authorize
replay, alerts, orders or deployment. Historical results require a coverage-only
manifest and frozen chronological dates before any result is opened. Missing
catalyst history, bars, trades, quotes, borrow or option facts block only their
dependent evidence.

## 52. D-099 — Agent-selected M0.3I prior-value/LVN research rules

Status: **FROZEN FOR OFFLINE RESEARCH**, 2026-09-13 Pacific.

Under the owner's [research authorization](./RESEARCH_AUTHORIZATION_20260913.md),
[M0_3I_DEFINITION_PACKET.md](./M0_3I_DEFINITION_PACKET.md) version
`M03I_VP_ACCEPT_LVN_V1` freezes one first `VP_ACCEPT_LVN` research version. It
defines exact true-trade and bar volume allocation, bin origins and tick
rounding, width sensitivities, smoothing edges, VPOC/value-area ties, LVN/HVN
shelves and adjacency, stability IoU, zero prior volume and refill penalties.

Review correction, 2026-09-13 Pacific: packet §5's phrase "fourth distinct trade
crossing ... after the first break" conflicted with the fourth-total-cross
rule. The first buffered break is crossing 1; each later strict-side change of
the frozen unbuffered VAH/VAL adds one. Equality, same-side trades and duplicate
observations add nothing. Crossing 4 ends the untriggered candidate immediately.
Packet §5, boundary example 10, PLAYBOOKS and TESTING_AND_VALIDATION now use
this one count. This corrects the wording within the frozen version before
dependent implementation or results.

The version also freezes 90-second acceptance, state transitions, stop
precedence, structural/fixed exits, score, outcomes and the mandatory matched
accepted-value control. The 1,440 comparison cells retain every direction,
profile mode, width, cohort, exit, delay, score population and stock-cost
assumption with a `1 / 28800` family threshold.

The version preserves existing playbook thresholds and resolves the last choice
named in PLAYBOOKS §13. It does not change D-090, D-092, D-093, D-094, D-095,
D-096, D-097 or D-098, select a profitable rule, prove source coverage or
authorize replay, alerts, orders or deployment. Historical results require a
coverage-only manifest and frozen chronological dates before any result is
opened. Missing bars, trades, quotes, adjustment history, borrow or option facts
block only their dependent evidence.

## 53. D-100 — Agent-selected M4.7 first-four shared research rules

Status: **FROZEN FOR OFFLINE RESEARCH**, 2026-09-14 Pacific.

Under the owner's [research authorization](./RESEARCH_AUTHORIZATION_20260913.md),
[M4_7_DEFINITION_PACKET.md](./M4_7_DEFINITION_PACKET.md) version
`M47_FIRST4_RESEARCH_V1` freezes the finite first-four option filters, shared
OptionScore, rank order, three new ordinary-only strategy policies, strict
preserved #1 0DTE policy, full-chain missingness, stable wrapper identity,
complete-batch portfolio recording, exact reversal release, producer cooldowns
and delivery-intent expiry.

This closes M4.7's P-01/P-02 definition branch for the minimum first-four
offline path. It does not claim that the choices are profitable or calibrated.
It does not prove source units, complete chains, quotes, historical execution,
remaining strategies or live behavior. Those obligations stay with M0.2,
M14–M17 and M19. D-090 and every frozen underlying research arm remain
unchanged.

## 54. D-101 to D-105 — Owner decisions of 2026-09-16 (Databento budget, universe, M0.2 gap policy)

Given directly by the owner on 2026-09-16 Pacific to release the M0.2/M9.3 stop.

### D-101 — Databento authority is USD 60, a fresh total

Status: **CONFIRMED**

Owner's words: "I authorize you to spend $60 in total on databento however you
see fit without my approval", and on being asked whether this was fresh or
cumulative, "$60 is a fresh total".

This **supersedes** the USD 40 cap with USD 16 of standing reservations and USD
24 unreserved that appears in DATA_REQUIREMENTS.md §, M0_2H_SOURCE_PREFLIGHT.md,
M0_2I_COST_CHECK.md, M0_2I_COST_CHECK_V2.md and ROADMAP.md. The prior
reservations are retired: they do not consume any part of the USD 60. Spending
inside USD 60 needs no further approval. Spending above it is forbidden.

Live ledger: `/root/trade-alerts-builder/databento-spend-ledger.json`.

### D-102 — Research universe for paid history is 17 names

Status: **CONFIRMED**

NVDA, MSFT, AAPL, GOOGL, AMZN, META, AVGO, TSLA, BRK.B, LLY, SPY, QQQ, IWM,
XLV, GLD, USO, VXX. The owner confirmed this list as correct. History depth is
one year, which the owner stated is enough. This does not repeal the 60-name
`research_symbols` set in M0_2H_SOURCE_ACQUISITION_SPEC.json; it states which
names paid tick history was actually bought for.

### D-103 — Option moneyness band for any paid option request

Status: **CONFIRMED**

10% in the money to 10% out of the money. The existing 0-7 DTE limit in
`HISTORICAL_OPTIONS_V1` is unchanged.

### D-104 — M0.2 acceptance bar: record the gap, switch off the rule

Status: **CONFIRMED** — supersedes the "every field proven" reading of M0.2

Owner's words: "Testing some data is better than testing nothing because 1
aspect wasn't able to be downloaded."

A field that cannot be obtained is **recorded as a gap**, and every rule that
depends on it is **switched off and labelled untested**. A missing field is
never approximated, estimated, proxied or filled so that a test can run through
it. A result produced while a dependent rule is switched off must say so.

This changes M0.2 from "every field proven" to "proven, or documented as a gap
with its dependents disabled". It does not lower any evidence standard for the
fields that ARE obtained, and it does not authorize replay, alerts, orders or
deployment.

Known gates this releases: original availability, corrections and finality,
point-in-time index membership, historical borrow, and complete-chain proof.
Each becomes a recorded gap with its dependent arms off, not a halt.

### D-105 — BRK.B option parent symbol

Status: **CONFIRMED** (technical finding, verified)

Databento OPRA parent symbols use `.` as the root/type separator, so
`BRK.B.OPT` is rejected with `symbology_invalid_symbol` (HTTP 400). The correct
form has no dot in the root: `BRKB.OPT`. Verified 2026-09-16 with
`metadata.get_cost`, which priced one day of `cbbo-1m` at USD 0.0978. This was
the unexplained HTTP 400 that blocked M0.2I from 2026-09-14. The equity symbol
remains `BRK.B`, which is correct for EQUS.MINI `raw_symbol` requests.
M0_2H_SOURCE_ACQUISITION_SPEC.json has been corrected.
